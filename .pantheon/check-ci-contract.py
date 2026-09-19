#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B430` — nothing in this repository could tell you whether CI had ever passed.

Measured 2026-09-17 against `ImPanick/pantheon`: of the last forty workflow
runs, **22 failed, 8 succeeded, 9 skipped, 1 cancelled — and every one of the
eight successes is a Dependabot update run or a `Container scan (Trivy)` job
that skipped its work.** No `CI`, `CodeQL`, `Secret scan`, `Workflow security`
or `Dependency review` run has ever succeeded. Every failing job carries an
empty `runner_name`, an empty `steps` array and a three-to-six second duration:
they did not fail a step, **they never got a runner**.

That is a billing fact and this file cannot fix it. What this file is about is
the second half, which is ours: **five waves shipped on 2026-09-17, each
reporting "gate green on 22 checkers", and each of those was a local
`release-gate.py --fast` run.** The pipeline was red for all five and nothing
here observed it — no test, no checker, no doc. A repository whose whole
argument is *our claims are checkable* carried a checkable claim that nobody
checked.

So this is the checker for the claims CI makes about itself. Seven rules, each
one a way a green check has meant nothing:

  **1  A required check must name a job that exists.** `docs/security-ci.md`
     tells the owner to type eight check names into branch protection. A name
     that matches no job `name:` in any workflow is a required check that can
     never report, and GitHub's answer to that is to leave the merge button
     disabled forever — or, with the rule written the other way round, to let
     everything through. Renaming a job is a one-word diff and it breaks this
     silently.

  **2  A stranger must be able to see the answer.** Every workflow that owns
     one of those required checks carries a status badge in `README.md`,
     pinned with `?branch=`. Unpinned is the trap: `badge.svg` with no branch
     reports the most recent run on *any* ref, so a green Dependabot branch
     paints the badge green while `main` is red — which is exactly the shape of
     the eight successes measured above.

  **3  A trigger must not name a branch that does not exist.** `ci.yml`,
     `codeql.yml` and `docker-publish.yml` all said `dev`. There has never
     been a `dev` branch. In `codeql.yml` it was not cosmetic: the trigger
     read `pull_request: branches: [dev]`, so **CodeQL has never run on a
     single pull request**, while the file's own header says it was added so
     that it would. `B352` corrected the PR and issue templates that pointed
     contributors at the same branch and the workflows were missed.

  **4  A job that reports success must have done its work.** `continue-on-error`
     is how a red step becomes a green check, and it is legitimate — but only
     when the check's *name* says so, because the name is all a reader of the
     Checks tab gets. `focused-test-guidance` does this right ("report-only" is
     in the name). `Trivy (image scan + SARIF upload)` did not: the whole job
     was `continue-on-error`, so a failed image build or a failed upload to the
     Security tab — the tab `docs/security-ci.md` tells you to go and read —
     reported green.

  **5  The local gate must not copy CI, it must read it.** `Law 13`.
     `release-gate.py` already reads the checker list out of `ci.yml`, and
     nothing proved the two agreed about anything *else*: the interpreter, the
     node version, the suite's own argv. Measured on 2026-09-17: the gate ran
     `pytest -q -p no:randomly` where CI runs `pytest -q`, so five waves of
     "the suite passed" were evidence about a **fixed test order CI does not
     use**; and it ran `retrieval_eval.py` where CI runs it `--verbose`. This
     rule imports the gate and compares what it derives against an independent
     parse of the workflow.

  **6  CI must not keep a second list of which files are ours.** `B10` found
     this for JavaScript — CI's own loop named 173 files and never
     `static/sw.js`. The Python half was still there: `compileall` over seven
     hand-typed paths, which on 2026-09-17 missed **51 of 1,429 tracked `.py`
     files, including all 22 checkers CI then runs**, `launcher.py`, and every
     module under `companion/`, `mcp_servers/` and `netagent/`.

  **7  A skip must be able to prove itself.** `ci.yml`'s docs-only shortcut
     decided "every changed file is documentation, skip pytest" from a shell
     pipeline whose empty case answers *yes* — an empty change list produced
     `docs_only=true`, so `Python tests (pytest)` reported success having run
     no tests. The decision now lives in `.github/scripts/docs_only.py` where
     it can be called, and this rule calls it.

Stdlib only, and offline (`Law 16`): the `wiring-ratchet` job installs nothing
before it runs the checkers, so a checker that imports PyYAML is a checker that
cannot run in the CI it is about. The YAML subset these workflows use is parsed
below.

    python3 .pantheon/check-ci-contract.py
    python3 .pantheon/check-ci-contract.py --list   print what each rule sees

Exits 0 when every rule holds, 1 otherwise.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
README = ROOT / "README.md"
SECURITY_CI = ROOT / "docs" / "security-ci.md"
CI = WORKFLOWS / "ci.yml"
GATE = ROOT / ".pantheon" / "release-gate.py"

# `B433`. The branches this repository has. One entry, and the entry is not a
# guess: rule 3 checks it against the branch `docs/security-ci.md` tells the
# owner to protect, which is the only other place in the tree that states which
# branch is real. Two places that already disagreed once is what produced the
# row; making them check each other is the fix (`Law 13`).
#
# When `dev` is created, it goes here and into whichever triggers want it, and
# this checker is what stops the second of those happening without the first.
BRANCHES = {"main"}

# `B434`. A name that must appear in a job or step name when that job or step
# is allowed to fail without failing the check. The Checks tab shows a reader
# the name and nothing else.
ADVISORY_WORDS = ("advisory", "report-only")


# ── a YAML subset, because the job that runs this installs nothing ────────────


def _dedent_block(lines: list[str], start: int, indent: int) -> tuple[str, int]:
    """Consume a `|`/`>` block scalar's body. Returns the text and where it ends."""
    out: list[str] = []
    i, strip = start, None
    while i < len(lines):
        raw = lines[i]
        if raw.strip():
            here = len(raw) - len(raw.lstrip())
            if here <= indent:
                break
            if strip is None:
                strip = here
            out.append(raw[strip:])
        else:
            out.append("")
        i += 1
    return "\n".join(out), i


def _scalar(text: str) -> object:
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [_scalar(p) for p in inner.split(",")] if inner else []
    if text.startswith("{") and text.endswith("}"):
        return {}
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _next_content(lines: list[str], i: int) -> int:
    while i < len(lines) and (not lines[i].strip()
                              or lines[i].lstrip().startswith("#")):
        i += 1
    return i


def _parse(lines: list[str], i: int, indent: int) -> tuple[object, int]:
    """Block mappings, block sequences, flow sequences, block scalars. No anchors,
    no multi-document, no flow mappings with content — none of which appear in
    `.github/workflows/`, and a surprise in the input is better reported as a
    parse failure than silently half-read."""
    body: dict | list | None = None
    level: int | None = None
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        here = len(raw) - len(raw.lstrip())
        if here < indent:
            break
        if level is None:
            level = here
        elif here < level:
            break
        elif here > level:
            raise ValueError(f"unexpected indent at line {i + 1}: {raw!r}")
        stripped = raw.strip()

        if stripped.startswith("- ") or stripped == "-":
            if body is None:
                body = []
            if not isinstance(body, list):
                break
            rest = stripped[2:].strip()
            item_indent = here + 2
            if re.match(r"^[^:#]+:(\s|$)", rest):
                # A mapping whose first key shares the dash's line.
                synthetic = [" " * item_indent + rest, *lines[i + 1:]]
                value, consumed = _parse(synthetic, 0, item_indent)
                body.append(value)
                i += consumed
            else:
                body.append(_scalar(rest))
                i += 1
            continue

        m = re.match(r"^([^:#]+):\s*(.*)$", stripped)
        if not m:
            i += 1
            continue
        if body is None:
            body = {}
        if not isinstance(body, dict):
            break
        key, rest = m.group(1).strip(), m.group(2).strip()
        rest = "" if rest.startswith("#") else re.sub(r"\s+#.*$", "", rest)
        if rest in ("|", ">", "|-", ">-", "|+", ">+"):
            text, i = _dedent_block(lines, i + 1, here)
            body[key] = text
            continue
        if rest:
            body[key] = _scalar(rest)
            i += 1
            continue
        # A block sequence may sit at the key's own indent; a nested mapping
        # may not. Peek rather than guess, or `schedule:`'s `- cron:` is lost.
        nxt = _next_content(lines, i + 1)
        child_indent = here + 1
        if nxt < len(lines):
            nxt_indent = len(lines[nxt]) - len(lines[nxt].lstrip())
            if nxt_indent == here and lines[nxt].lstrip().startswith("-"):
                child_indent = here
        value, i = _parse(lines, i + 1, child_indent)
        body[key] = value if value is not None else {}
    return body, i


def load_workflow(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    value, _ = _parse(text.splitlines(), 0, 0)
    return value if isinstance(value, dict) else {}


def workflow_files() -> list[Path]:
    return sorted(p for p in WORKFLOWS.glob("*.yml"))


def _triggers(doc: dict) -> dict:
    # `on` is a YAML 1.1 boolean, and a 1.1 loader would hand back `True` as the
    # key. This parser does not coerce, but accept both so a future swap of the
    # parser cannot make the rule silently find nothing.
    for key in ("on", True, "True", "on:"):
        if key in doc:
            return doc[key] if isinstance(doc[key], dict) else {}
    return {}


def trigger_branches(doc: dict) -> dict[str, list[str]]:
    """event -> the branches its filter names. Absent filter is not an entry:
    "runs on every branch" is a different statement from "runs on `dev`"."""
    out: dict[str, list[str]] = {}
    for event, spec in _triggers(doc).items():
        if isinstance(spec, dict):
            for field in ("branches", "branches-ignore"):
                named = spec.get(field)
                if isinstance(named, list):
                    out.setdefault(f"{event}.{field}", []).extend(
                        str(b) for b in named)
    return out


def jobs(doc: dict) -> dict:
    found = doc.get("jobs")
    return found if isinstance(found, dict) else {}


def job_names(doc: dict) -> list[str]:
    return [str(spec.get("name", key)) for key, spec in jobs(doc).items()
            if isinstance(spec, dict)]


# ── rule 1 — a required check names a job that exists ─────────────────────────


def required_checks() -> list[str]:
    """The names `docs/security-ci.md` tells the owner to type into branch
    protection. Read out of the guide rather than restated here: a second copy
    of this list is the thing the rule is about."""
    text = SECURITY_CI.read_text(encoding="utf-8")
    anchor = "add these checks by name"
    if anchor not in text:
        return []
    after = text.split(anchor, 1)[1]
    names: list[str] = []
    for line in after.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^\s*-\s+`([^`]+)`\s*$", line)
        if not m:
            if names:
                break
            continue
        names.append(m.group(1))
    return names


def rule_required_checks_exist() -> tuple[list[str], dict[str, str]]:
    owners: dict[str, str] = {}
    for path in workflow_files():
        for name in job_names(load_workflow(path)):
            owners.setdefault(name, path.name)
    problems = [
        f"docs/security-ci.md requires the check {name!r} and no job in "
        f".github/workflows/ is named that — branch protection cannot be "
        f"satisfied by a check that never reports"
        for name in required_checks() if name not in owners
    ]
    if not required_checks():
        problems.append(
            "docs/security-ci.md no longer lists the checks to require — "
            "rule 1 has nothing to check and that is a hole, not a pass")
    return problems, owners


# ── rule 2 — the answer is visible from the repository ────────────────────────


def repo_slug() -> str | None:
    """`owner/repo`, from the clone command a stranger is told to run. Derived
    rather than declared: a slug typed twice is a slug that will disagree."""
    m = re.search(r"git clone https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?\s",
                  README.read_text(encoding="utf-8"))
    return f"{m.group(1)}/{m.group(2)}" if m else None


BADGE = re.compile(
    r"https://github\.com/(?P<slug>[\w.-]+/[\w.-]+)/actions/workflows/"
    r"(?P<file>[\w.-]+\.yml)/badge\.svg(?:\?(?P<query>[^\"'\s)]*))?")


def badges() -> list[dict]:
    out = []
    for m in BADGE.finditer(README.read_text(encoding="utf-8")):
        query = m.group("query") or ""
        branch = dict(
            part.split("=", 1) for part in query.split("&") if "=" in part
        ).get("branch")
        out.append({"slug": m.group("slug"), "file": m.group("file"),
                    "branch": branch})
    return out


def rule_badges(owners: dict[str, str]) -> list[str]:
    needed = {owners[name] for name in required_checks() if name in owners}
    needed.add(CI.name)
    have = {b["file"]: b for b in badges()}
    slug = repo_slug()
    problems: list[str] = []
    if slug is None:
        problems.append(
            "README.md no longer contains the clone URL, so there is nothing "
            "to check the badge slugs against")
    for want in sorted(needed):
        badge = have.get(want)
        if badge is None:
            problems.append(
                f"README.md has no status badge for {want} — a reader has no "
                f"way to learn whether it passes")
            continue
        if slug and badge["slug"] != slug:
            problems.append(
                f"the {want} badge points at {badge['slug']} and this repo is "
                f"{slug}")
        if badge["branch"] is None:
            problems.append(
                f"the {want} badge has no `?branch=`, so it reports the newest "
                f"run on ANY ref — a Dependabot branch paints it green while "
                f"the default branch is red")
        elif badge["branch"] not in BRANCHES:
            problems.append(
                f"the {want} badge is pinned to branch {badge['branch']!r}, "
                f"which is not a branch this repository has ({sorted(BRANCHES)})")
    for got in sorted(have):
        if not (WORKFLOWS / got).exists():
            problems.append(
                f"README.md carries a badge for {got}, which is not a workflow "
                f"in this repository — it will render as a broken image")
    return problems


# ── rule 3 — a trigger does not name a branch that does not exist ─────────────


def documented_protected_branch() -> str | None:
    m = re.search(r"branch name pattern to `([\w.\-/]+)`",
                  SECURITY_CI.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def rule_trigger_branches() -> list[str]:
    problems: list[str] = []
    documented = documented_protected_branch()
    if documented is None:
        problems.append(
            "docs/security-ci.md no longer names the branch to protect, so "
            "the branch register in this file has nothing to agree with")
    elif BRANCHES != {documented}:
        problems.append(
            f"this file's branch register is {sorted(BRANCHES)} and "
            f"docs/security-ci.md tells the owner to protect {documented!r} — "
            f"one of the two is wrong about which branches exist")
    for path in workflow_files():
        for where, named in trigger_branches(load_workflow(path)).items():
            for branch in named:
                if branch not in BRANCHES:
                    problems.append(
                        f"{path.name} triggers on {where} = {branch!r}, and "
                        f"there is no such branch — the trigger has never "
                        f"fired and never will (`B433`)")
    return problems


# ── rule 4 — a green check did its work ───────────────────────────────────────


def _is_true(value: object) -> bool:
    return str(value).strip().lower() in ("true", "yes", "on")


def fail_open_sites() -> list[tuple[str, str, str, bool]]:
    """(workflow, kind, name, declared) for every `continue-on-error: true`."""
    out = []
    for path in workflow_files():
        for key, spec in jobs(load_workflow(path)).items():
            if not isinstance(spec, dict):
                continue
            name = str(spec.get("name", key))
            if _is_true(spec.get("continue-on-error", False)):
                out.append((path.name, "job", name,
                            any(w in name.lower() for w in ADVISORY_WORDS)))
            steps = spec.get("steps")
            for step in steps if isinstance(steps, list) else []:
                if not isinstance(step, dict):
                    continue
                if _is_true(step.get("continue-on-error", False)):
                    step_name = str(step.get("name", step.get("uses", "?")))
                    out.append((path.name, f"step in {name}", step_name,
                                any(w in step_name.lower()
                                    for w in ADVISORY_WORDS)))
    return out


def rule_fail_open() -> list[str]:
    return [
        f"{workflow}: the {kind} {name!r} is `continue-on-error: true` and its "
        f"name does not say so. A reader of the Checks tab sees the name and "
        f"nothing else, so this is a green tick that can mean 'I did not "
        f"look'. Put one of {list(ADVISORY_WORDS)} in the name or drop the "
        f"flag (`B435`)"
        for workflow, kind, name, declared in fail_open_sites() if not declared
    ]


# ── rule 5 — the gate reads CI rather than copying it ─────────────────────────


def _load_gate():
    spec = importlib.util.spec_from_file_location("release_gate", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ci_setup_versions(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for tool in ("python", "node"):
        out[tool] = re.findall(rf"^\s*{tool}-version:\s*[\"']?([\w.]+)[\"']?\s*$",
                               text, re.M)
    return out


def ci_pytest_invocations(text: str) -> list[list[str]]:
    found = []
    for m in re.finditer(r"run:\s*(?:python3?)\s+-m\s+pytest([^\n#]*)", text):
        found.append(m.group(1).split())
    return found


def rule_gate_reads_ci() -> list[str]:
    text = CI.read_text(encoding="utf-8")
    problems: list[str] = []
    try:
        gate = _load_gate()
    except Exception as exc:  # pragma: no cover - a broken gate is its own alarm
        return [f"{GATE.name} does not import: {exc}"]

    versions = ci_setup_versions(text)
    for tool, derived in (("python", gate.ci_python_version()),
                          ("node", gate.ci_node_version())):
        pinned = sorted(set(versions[tool]))
        if len(pinned) != 1:
            problems.append(
                f"ci.yml pins {tool}-version {pinned or 'nowhere'} — the gate "
                f"cannot mirror an interpreter the workflow does not agree on")
        elif derived != pinned[0]:
            problems.append(
                f"the gate thinks CI's {tool} is {derived!r} and ci.yml says "
                f"{pinned[0]!r} (`Law 13`)")

    suites = [a for a in ci_pytest_invocations(text)
              if not any(x.startswith("tests/") for x in a)]
    if len(suites) != 1:
        problems.append(
            f"ci.yml has {len(suites)} whole-suite pytest invocations; the "
            f"gate needs exactly one to mirror")
    elif gate.ci_suite_args() != suites[0]:
        problems.append(
            f"the gate runs `pytest {' '.join(gate.ci_suite_args())}` and CI "
            f"runs `pytest {' '.join(suites[0])}` — a local pass is not "
            f"evidence about the run CI will do (`B431`)")

    advisory = re.search(r"run:\s*python3?\s+(\.pantheon/retrieval_eval\.py[^\n#]*)",
                         text)
    if advisory is None:
        problems.append("ci.yml no longer runs the retrieval eval")
    elif gate.ci_advisory_argv() != advisory.group(1).split():
        problems.append(
            f"the gate runs `{' '.join(gate.ci_advisory_argv())}` and CI runs "
            f"`{advisory.group(1)}` (`B431`)")
    return problems


# ── rule 6 — one list of which files are ours ─────────────────────────────────


def _job_script(doc: dict, key: str) -> str:
    spec = jobs(doc).get(key)
    steps = spec.get("steps") if isinstance(spec, dict) else None
    return "\n".join(str(s.get("run", "")) for s in (steps or [])
                     if isinstance(s, dict))


def rule_one_file_list() -> list[str]:
    problems: list[str] = []
    doc = load_workflow(CI)
    for job_key, tool in (("python-syntax", "py_compile"),
                          ("node-syntax", "node --check")):
        script = _job_script(doc, job_key)
        if not script:
            problems.append(f"ci.yml has no {job_key} job to check")
        elif "release-gate.py" not in script:
            problems.append(
                f"ci.yml's {job_key} job builds its own list of which files "
                f"are ours instead of calling the gate's. `B10` is this exact "
                f"defect on the JavaScript side and it cost a required check "
                f"that checked nothing on the largest module in the app; the "
                f"fix there was one list, and {tool} needs the same (`B436`)")
    try:
        gate = _load_gate()
    except Exception as exc:  # pragma: no cover
        return problems + [f"{GATE.name} does not import: {exc}"]
    tracked = subprocess.run(["git", "ls-files", "*.py"], cwd=str(ROOT),
                             capture_output=True, text=True)
    missing = sorted(set(f for f in tracked.stdout.split() if f)
                     - set(gate._python_files()))
    if missing:
        problems.append(
            f"{len(missing)} tracked `.py` files are byte-compiled by nothing: "
            f"{', '.join(missing[:5])}…")
    return problems


# ── rule 7 — a skip proves itself ─────────────────────────────────────────────


def rule_skip_proves_itself() -> list[str]:
    problems: list[str] = []
    helper = ROOT / ".github" / "scripts" / "docs_only.py"
    text = CI.read_text(encoding="utf-8")
    if "docs_only.py" not in text:
        problems.append(
            "ci.yml decides 'this change is documentation, skip the tests' in "
            "shell whose empty case answers yes — an empty change list made "
            "`Python tests (pytest)` report success with no tests run. The "
            "decision belongs in .github/scripts/docs_only.py where it can be "
            "called (`B434`)")
        return problems
    if not helper.exists():
        problems.append(f"ci.yml calls {helper.name} and it is not in the tree")
        return problems
    spec = importlib.util.spec_from_file_location("docs_only", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.is_docs_only([]) is not False:
        problems.append(
            "docs_only.is_docs_only([]) says an empty change set is "
            "documentation. It is not: it is a change set that could not be "
            "computed, and answering yes skips the suite and reports green "
            "(`B434`)")
    if module.is_docs_only(["src/app.py"]) is not False:
        problems.append("docs_only says a Python change is documentation")
    if module.is_docs_only(["docs/setup.md"]) is not True:
        problems.append("docs_only no longer recognises a documentation change")
    return problems


# `B855`. Rule eight, and the one that cost twenty-two checkers. A job step can
# run a script that imports this product; if the job installed no dependencies
# that step dies on the first `import httpx` four modules down, and the job
# fails at step three with twenty-two steps that never ran. It had been that way
# since the workflow was written and nothing could see it, because every one of
# those steps passes on a developer's machine, where the dependencies exist.
#
# The question is asked of the SCRIPT, not of a list kept here: parse it and
# look for an import whose root is one of this repository's own packages.
FIRST_PARTY_ROOTS = ("src", "core", "routes", "integrations", "netagent", "services")

# What "install the dependencies" looks like. Not a spelling preference: a job
# that pins its own subset is the `Law 13` shape this rule exists to stop.
DEPENDENCY_INSTALL = "pip install -r requirements.txt"


def _imports_first_party(path: Path) -> list[str]:
    """Roots of this repository's own packages that `path` imports.

    Anywhere in the file, including inside a function: `check-tool-surface.py`
    does its `import src.agent_tools` inside `main()` on purpose, to break a
    circular import, and an import that runs is an import that needs its
    dependencies.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return sorted(roots & set(FIRST_PARTY_ROOTS))


PY_INTERPRETER = re.compile(r"(?:^|[\s;&|(])python[0-9.]*(?:\s|$)")


def _scripts_a_step_runs(run_text: str) -> list[Path]:
    """Repository Python files a `run:` block hands to a Python interpreter.

    Scoped to blocks that actually invoke one. `docker-publish.yml` reads
    `APP_VERSION` out of `src/constants.py` with `grep`, and a step that greps a
    file neither imports it nor needs its dependencies.
    """
    if not PY_INTERPRETER.search(run_text):
        return []
    found: list[Path] = []
    for token in re.findall(r"[\w./-]+\.py", run_text):
        candidate = ROOT / token
        if candidate.is_file() and candidate not in found:
            found.append(candidate)
    return found


def rule_job_installs_what_it_imports() -> list[str]:
    problems: list[str] = []
    for path in workflow_files():
        doc = load_workflow(path)
        for key, spec in jobs(doc).items():
            steps = spec.get("steps") if isinstance(spec, dict) else None
            steps = steps if isinstance(steps, list) else []
            runs = [str(step.get("run", "")) for step in steps
                    if isinstance(step, dict) and step.get("run")]
            installs = any(DEPENDENCY_INSTALL in text for text in runs)
            if installs:
                continue
            needy: list[str] = []
            for text in runs:
                for script in _scripts_a_step_runs(text):
                    if _imports_first_party(script):
                        rel = script.relative_to(ROOT).as_posix()
                        if rel not in needy:
                            needy.append(rel)
            if needy:
                problems.append(
                    f"{path.name}:{key} runs {', '.join(needy)}, which "
                    f"import{'s' if len(needy) == 1 else ''} this product, and "
                    f"the job never runs `{DEPENDENCY_INSTALL}`. That step dies "
                    f"on a missing dependency and every step after it never "
                    f"runs (`B855`)")
    return problems


# ── run ───────────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true",
                    help="print what each rule sees and stop")
    args = ap.parse_args()

    required_problems, owners = rule_required_checks_exist()

    if args.list:
        print(f"repository      {repo_slug()}")
        print(f"branches        {sorted(BRANCHES)} "
              f"(guide says {documented_protected_branch()!r})")
        print(f"workflows       {len(workflow_files())}")
        print("required checks (docs/security-ci.md):")
        for name in required_checks():
            print(f"  {name:<28} {owners.get(name, '— NO SUCH JOB —')}")
        print("badges (README.md):")
        for badge in badges():
            print(f"  {badge['file']:<28} branch={badge['branch']}")
        print("fail-open sites:")
        for workflow, kind, name, declared in fail_open_sites():
            print(f"  {'declared' if declared else 'SILENT  '}  "
                  f"{workflow:<22} {kind}: {name}")
        return 0

    rules = [
        ("required checks name real jobs", required_problems),
        ("the answer is visible from the repo", rule_badges(owners)),
        ("no trigger names a branch that does not exist", rule_trigger_branches()),
        ("a green check did its work", rule_fail_open()),
        ("the gate reads CI rather than copying it", rule_gate_reads_ci()),
        ("one list of which files are ours", rule_one_file_list()),
        ("a skip proves itself", rule_skip_proves_itself()),
        ("a job installs what it imports", rule_job_installs_what_it_imports()),
    ]

    problems = [(title, p) for title, ps in rules for p in ps]
    print(f"ci contract · {len(rules)} rules · "
          f"{len(required_checks())} required checks · "
          f"{len(badges())} badges · {len(fail_open_sites())} fail-open sites "
          f"· PROBLEMS {len(problems)}")
    for title, problem in problems:
        print(f"  [{title}] {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
