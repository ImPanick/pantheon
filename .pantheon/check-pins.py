#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B320`/`B322` — every Python dependency is pinned, and every accepted risk explains itself.

Two rules, both offline, both about the same disease: a dependency decision that
nobody made.

**Rule 1 — every requirement is pinned to one exact version.** Before this
checker, `requirements.txt` held 31 dependencies and zero `==` pins. That is
three defects wearing one coat:

  * the build is not reproducible — the same commit built on two days produces
    two different images, and "it worked yesterday" has no answer;
  * a yanked or compromised release lands on the next build with nothing in
    between and nobody's name on it;
  * and `.github/dependabot.yml`'s pip section, which looks like coverage, is
    inert. Dependabot raises a pull request when a *pinned* version falls
    behind. A bare `fastapi` is satisfied by every release fastapi has ever
    made, so there was never anything to bump. The automation had been
    configured, reviewed and merged, and could not have opened a single Python
    pull request.

That last one is why this is a checker and not a one-time edit. The bump is a
day's work that drifts back within a month; the rule is what keeps it true. A
new dependency added without a pin fails here, in the offline gate, before it
reaches CI.

**Rule 2 — every advisory suppression carries its reasoning, and expires.**
`.pantheon/dependency-advisories.toml` is the list the network audit
(`.pantheon/audit-dependencies.py`) consults before it fails a build. An entry
on that list is a decision to ship a package with a published advisory against
it, so each one must say what the bug is, why this code cannot reach it, what
upstream offers, what would make the answer different, which `DECISIONS.md`
entry settled it, and when somebody looks again. Missing any of that fails.
A `review_by` date in the past fails. A `decision` that names an entry
DECISIONS.md does not contain fails. A `declared_in` file that does not pin that
package at that version fails — a suppression that has outlived the dependency
it excuses is exactly as misleading as one that never had a reason.

**Why this is offline** (`Law 16`). Developers run `.pantheon/release-gate.py`
constantly, often with no network. Everything above is answered from files in
this repository: it is an internal-consistency check, not a lookup. The half
that genuinely needs the network — asking OSV whether a pinned version has an
advisory today — is a separate CI job and lives in
`.github/workflows/dependency-review.yml`.

    python3 .pantheon/check-pins.py            # report, exit 1 on any problem
    python3 .pantheon/check-pins.py --verbose  # also list what passed
"""

from __future__ import annotations

import argparse
import datetime
import pathlib
import re
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent

ADVISORIES = ".pantheon/dependency-advisories.toml"
DECISIONS = ".pantheon/DECISIONS.md"
DEPENDABOT = ".github/dependabot.yml"

# The fields an entry in the advisory register must carry. Each one answers a
# question a reader of a red build will have, and an entry that cannot answer
# one of them is not a decision, it is a shrug.
REQUIRED_ADVISORY_FIELDS = (
    "id",
    "package",
    "version",
    "declared_in",
    "what_it_is",
    "why_it_does_not_apply",
    "fix_available",
    "what_would_change_this",
    "decision",
    "review_by",
    "reviewed_by",
)

# `pkg[extra1,extra2] ==1.2.3 ; marker`, with the comment already stripped.
_REQ_RE = re.compile(
    r"""^\s*
        (?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)      # distribution name
        \s*(?P<extras>\[[^\]]*\])?                # optional extras
        (?P<spec>[^;]*)                           # version specifier(s)
        (?:;(?P<marker>.*))?$                     # optional environment marker
    """,
    re.VERBOSE,
)

# One clause, and that clause is `==` or `===`. `>=`, `<`, `~=`, `!=` and a bare
# name are all "some range of releases", which is the thing being ruled out.
_PIN_RE = re.compile(r"^===?\s*[^,\s]+$")


def requirement_files() -> list[pathlib.Path]:
    """Every `requirements*.txt` at the top of the tree, in a stable order."""
    return sorted(ROOT.glob("requirements*.txt"))


def parse_requirements(path: pathlib.Path) -> list[tuple[int, str, str, str]]:
    """`(line number, raw line, distribution name, specifier)` per requirement.

    Comment lines, blank lines, `-r`/`-c` includes and bare pip flags are not
    requirements and are skipped. A continuation (`\\` at end of line) is joined
    onto the line before it, because pip reads it that way and a checker that
    did not would disagree with pip about what the file says.
    """
    out: list[tuple[int, str, str, str]] = []
    text = path.read_text(encoding="utf-8")
    pending = ""
    start = 0
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split(" #", 1)[0].split("\t#", 1)[0]
        line = re.sub(r"^\s*#.*$", "", line).strip()
        if not line:
            continue
        if pending:
            line = pending + " " + line
        else:
            start = number
        if line.endswith("\\"):
            pending = line[:-1].strip()
            continue
        pending = ""
        if line.startswith("-"):
            continue
        m = _REQ_RE.match(line)
        if not m:
            out.append((start, line, "", ""))
            continue
        out.append((start, line, m.group("name"), (m.group("spec") or "").strip()))
    return out


def unpinned_problems() -> list[str]:
    """Requirements that name a range of releases instead of one release."""
    problems: list[str] = []
    for path in requirement_files():
        rel = path.relative_to(ROOT).as_posix()
        for number, line, name, spec in parse_requirements(path):
            if not name:
                problems.append(f"{rel}:{number}: cannot parse as a requirement: {line}")
                continue
            if not spec:
                problems.append(
                    f"{rel}:{number}: `{name}` has no version at all — "
                    f"every release ever published satisfies it"
                )
                continue
            if not _PIN_RE.match(spec.replace(" ", "")):
                problems.append(
                    f"{rel}:{number}: `{name}{spec}` is a range, not a pin — "
                    f"use `{name}==<version>` and keep the range as a comment"
                )
    return problems


def _decision_ids() -> set[str]:
    path = ROOT / DECISIONS
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"^##\s+(D-\d{4}-\d{2}-\d{2}-\d+)", text, re.M))


def load_advisories() -> tuple[list[dict], list[str]]:
    """The advisory register, and any problem that stopped it being read."""
    path = ROOT / ADVISORIES
    if not path.exists():
        return [], [f"{ADVISORIES} is missing — the audit has no register to read"]
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        return [], [f"{ADVISORIES}: not valid TOML: {exc}"]
    entries = data.get("advisory", [])
    if not isinstance(entries, list):
        return [], [f"{ADVISORIES}: `advisory` must be a list of tables"]
    return entries, []


def _declares(rel: str, package: str, version: str) -> bool:
    """Does `rel` pin `package` at exactly `version`?

    Deliberately textual and deliberately narrow: it matches `name==version`
    with the name spelled either way round the `-`/`_` split pip treats as
    equivalent. The point is not to parse every file format the repository has
    — the Real-ESRGAN wheels are pinned in a shell variable — but to fail when
    the suppression and the pin have drifted apart.
    """
    path = ROOT / rel
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    name = re.escape(package).replace(r"\-", "[-_]").replace(r"\_", "[-_]")
    return re.search(rf"(?i)(?<![\w.-]){name}(\[[^\]]*\])?\s*===?\s*{re.escape(version)}\b",
                     text) is not None


def advisory_problems(today: datetime.date | None = None) -> list[str]:
    """Every way an accepted risk can stop being an accepted decision."""
    today = today or datetime.date.today()
    entries, problems = load_advisories()
    known = _decision_ids()
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        label = entry.get("id") or f"entry #{index + 1}"
        for field in REQUIRED_ADVISORY_FIELDS:
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                problems.append(
                    f"{ADVISORIES}: {label} has no `{field}` — "
                    f"an entry that cannot answer that is not a decision"
                )
        if not all(isinstance(entry.get(f), str) and entry.get(f, "").strip()
                   for f in REQUIRED_ADVISORY_FIELDS):
            continue
        if entry["id"] in seen:
            problems.append(f"{ADVISORIES}: {label} is listed twice")
        seen.add(entry["id"])

        if entry["decision"] not in known:
            problems.append(
                f"{ADVISORIES}: {label} cites `{entry['decision']}`, which "
                f"{DECISIONS} does not contain"
            )
        if not _declares(entry["declared_in"], entry["package"], entry["version"]):
            problems.append(
                f"{ADVISORIES}: {label} says `{entry['package']}=={entry['version']}` is "
                f"pinned in `{entry['declared_in']}`, and it is not — either the "
                f"dependency moved or the suppression outlived it"
            )
        try:
            review = datetime.date.fromisoformat(entry["review_by"])
        except ValueError:
            problems.append(
                f"{ADVISORIES}: {label} has `review_by = \"{entry['review_by']}\"`, "
                f"which is not an ISO date"
            )
            continue
        if review < today:
            problems.append(
                f"{ADVISORIES}: {label} was to be reviewed by {review.isoformat()} and "
                f"today is {today.isoformat()} — re-read the advisory and record what "
                f"is true now; do not move the date without looking"
            )
    return problems


def _dependabot_pip_directories() -> list[str]:
    """Directories the pip ecosystem is configured for, read without a YAML parser.

    A regex rather than `yaml.safe_load` because this checker runs in the
    offline gate on a bare interpreter, and PyYAML is not a dependency of this
    project. The shape being read is two adjacent keys in a list item, which is
    within what a regex can honestly do.
    """
    path = ROOT / DEPENDABOT
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    out = []
    # Split on the list-item boundary first. Reading "the rest of the block" with
    # one regex does not work here: every following ecosystem entry is indented
    # too, so a body pattern that accepts indented lines swallows the whole file
    # and reports npm's and docker's directories as pip's.
    blocks = re.split(r"(?m)^\s*-\s*package-ecosystem:\s*", text)
    for block in blocks[1:]:
        ecosystem, _, body = block.partition("\n")
        if ecosystem.strip().strip("\"'") != "pip":
            continue
        for m in re.finditer(r"^\s*directory:\s*[\"']?([^\"'\n]+?)[\"']?\s*$",
                             body, re.M):
            out.append(m.group(1).strip())
    return out


def dependabot_problems() -> list[str]:
    """A requirements file Dependabot is not configured to look at.

    `B320`'s other half. Pinning makes the pins bumpable; this makes sure
    something is actually configured to bump them. A pinned file outside every
    configured directory is a file that freezes and then rots, which is worse
    than the range it replaced.
    """
    files = requirement_files()
    if not files:
        return []
    directories = _dependabot_pip_directories()
    if not directories:
        return [
            f"{DEPENDABOT}: no pip ecosystem entry — "
            f"{len(files)} pinned requirements file(s) and nothing configured to bump them"
        ]
    covered = {d.rstrip("/") or "/" for d in directories}
    problems = []
    for path in files:
        parent = "/" + path.parent.relative_to(ROOT).as_posix().strip(".")
        parent = parent.rstrip("/") or "/"
        if parent not in covered:
            problems.append(
                f"{path.relative_to(ROOT).as_posix()}: pinned, but Dependabot's pip "
                f"ecosystem only covers {sorted(covered)} — nothing will ever bump it"
            )
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--verbose", action="store_true",
                    help="also print what was checked and passed")
    args = ap.parse_args()

    files = requirement_files()
    requirements = sum(len(parse_requirements(p)) for p in files)
    entries, _ = load_advisories()

    problems = unpinned_problems() + advisory_problems() + dependabot_problems()

    if args.verbose:
        for path in files:
            print(f"  {path.relative_to(ROOT).as_posix()}: "
                  f"{len(parse_requirements(path))} requirement(s)")
        for entry in entries:
            print(f"  accepted risk {entry.get('id')} "
                  f"({entry.get('package')} {entry.get('version')}) "
                  f"reviewed by {entry.get('review_by')}")

    if problems:
        for problem in problems:
            print(f"  {problem}")
        print(f"FAIL {len(problems)} problem(s) across {len(files)} requirements file(s)")
        return 1

    print(f"PINNED {requirements} requirement(s) in {len(files)} file(s); "
          f"{len(entries)} accepted risk(s), all explained and in date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
