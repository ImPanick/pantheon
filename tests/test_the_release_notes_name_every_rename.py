# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P10-12` — the release notes name every rename, and the list is derived.

The row: *"Write the release notes. Lead with the Odysseus credit. Enumerate the
breaking renames: env vars, storage keys, vector collections, cookie, CLI
scripts, systemd unit, bundle id."* The notes are `docs/release-notes/<x.y.z>.md`.

A rename table typed from memory is the document this repository keeps finding
wrong: `FORBIDDEN.md` still says *"`ODYSSEUS_*` env prefix (99 names)"* and
*"19 CLI scripts"*; the fork point had **92** `ODYSSEUS_` names and **21**
`scripts/odysseus*` commands. So every table in the notes is checked against the
list that owns the fact, and the lists are **called or parsed, never grepped as
prose** (`Law 20`):

* environment variables — `.pantheon/check-env-declared.py`'s own `declared()`
  (`.env.example`) and `literal_reads()` (every literal `os.getenv` /
  `os.environ` / `env_flag` / `env_backed` read in the code);
* command-line tools — `scripts/pantheon`'s own `_list_subcommands()`, the
  function that decides what `pantheon <name>` can run;
* services, volumes and the container user — every tracked compose file, parsed
  as YAML, and the `useradd` line of `docker/entrypoint.sh`;
* stored values — the constants that hold them, resolved by `ast` inside the
  module that owns each one;
* files and paths — `git ls-files`.

**Two directions, and they are not symmetrical (`Law 10`).** *Complete* means
every name the tree's lists hold appears in the notes, as a rename or as new in
Pantheon. *Correct* means every *Odysseus* cell is a name the fork point really
had — which needs `b4d1293`'s objects. This clone begins at a snapshot import
and cannot reach them; CI checks out with `fetch-depth: 0`, and the published
history contains the fork point, so CI runs both halves. To run the upstream
half here, point git at any clone of upstream:
`GIT_ALTERNATE_OBJECT_DIRECTORIES=<clone>/.git/objects pytest <this file>`.

**A cut release is a record, not a mirror.** The *new in Pantheon* lists and the
open gates are statements about the tree on the day the notes were written. Once
the tag `v<x.y.z>` exists those two checks stand down, because a released section
that is quietly corrected is the dishonesty `B44` is about (`CHANGELOG.md`
§ Versions). Everything about Odysseus stays checked forever: the fork point does
not move.
"""
from __future__ import annotations

import ast
import functools
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NOTES_DIR = ROOT / "docs" / "release-notes"
CHANGELOG = ROOT / "CHANGELOG.md"
VERSION_FILE = re.compile(r"^(\d+\.\d+\.\d+)\.md$")
ROW_ID = re.compile(r"^(?:P\d+-\d+[a-z]?|[BH]\d+)$")


# ── the fork point ──────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _claims():
    """`.pantheon/ledger/claims.py` owns the fork point and both of its dates
    (`B349`); the notes are checked against it rather than against a literal."""
    if str(ROOT / ".pantheon") not in sys.path:
        sys.path.insert(0, str(ROOT / ".pantheon"))
    from ledger import claims
    return claims


def _git(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    import os
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                          text=True, timeout=120,
                          env={**os.environ, **env} if env else None)


@functools.lru_cache(maxsize=None)
def _upstream_reachable() -> bool:
    return _git("cat-file", "-e", f"{_claims().FORK_POINT}^{{commit}}").returncode == 0


def _need_upstream():
    if not _upstream_reachable():
        pytest.skip(
            f"`{_claims().FORK_POINT}` is not in this clone's objects (a snapshot "
            "import). CI's fetch-depth: 0 reaches it; locally, set "
            "GIT_ALTERNATE_OBJECT_DIRECTORIES to an upstream clone's .git/objects."
        )


def _released(version: str) -> bool:
    return _git("rev-parse", "-q", "--verify", f"refs/tags/v{version}").returncode == 0


def _app_version() -> str:
    from src.constants import APP_VERSION
    return APP_VERSION


# ── the rename itself ───────────────────────────────────────────────────────

_SHORT = re.compile(r"(?<![A-Za-z0-9])ody(?=[-._])")


def renamed(old: str) -> str:
    """What `scripts/pantheon-init.sh` did to a name: `odysseus` → `pantheon`
    in each of its three cases, and the short `ody` before a separator →
    `pan` (`P0-04`, `P0-31`)."""
    new = (old.replace("ODYSSEUS", "PANTHEON").replace("Odysseus", "Pantheon")
              .replace("odysseus", "pantheon"))
    return _SHORT.sub("pan", new)


# ── the tree's own lists ────────────────────────────────────────────────────

def _load_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@functools.lru_cache(maxsize=None)
def tree_env_names() -> frozenset:
    """Every `PANTHEON_*` variable `.env.example` declares or the code reads by
    name — the two scans `check-env-declared.py` keeps for exactly this
    question."""
    checker = _load_path("_release_env_checker", ROOT / ".pantheon" / "check-env-declared.py")
    names = set(checker.declared()) | set(checker.literal_reads())
    return frozenset(n for n in names if n.startswith("PANTHEON_"))


@functools.lru_cache(maxsize=None)
def tree_env_declared() -> frozenset:
    checker = _load_path("_release_env_checker_d", ROOT / ".pantheon" / "check-env-declared.py")
    return frozenset(checker.declared())


@functools.lru_cache(maxsize=None)
def _tracked() -> tuple:
    out = _git("ls-files").stdout.split("\n")
    return tuple(p for p in out if p)


@functools.lru_cache(maxsize=None)
def _tracked_texts() -> tuple:
    """`(path, text)` for every tracked text file outside the tracker and the
    tests — what a name has to appear in to still exist in the product."""
    texts = []
    for rel in _tracked():
        if rel.startswith((".pantheon/", "tests/")):
            continue
        try:
            texts.append((rel, (ROOT / rel).read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    return tuple(texts)


def read_in(name: str) -> str | None:
    """Where an operator would meet a variable: `.env.example` when it is
    declared there, else the first tracked file outside the docs that names it."""
    if name in tree_env_declared():
        return ".env.example"
    word = re.compile(rf"(?<![A-Z0-9_]){re.escape(name)}(?![A-Z0-9_])")
    for rel, text in sorted(_tracked_texts()):
        if rel.startswith("docs/") or rel.endswith(".md"):
            continue
        if word.search(text):
            return rel
    return None


@functools.lru_cache(maxsize=None)
def tree_cli_names() -> frozenset:
    """What `pantheon <name>` can run, asked of the dispatcher itself, plus the
    dispatcher."""
    from tests.helpers.cli_loader import load_script
    dispatcher = load_script("pantheon")
    return frozenset({"pantheon"} | {p.name for p in dispatcher._list_subcommands()})


@functools.lru_cache(maxsize=None)
def tree_named_paths() -> frozenset:
    """Tracked paths carrying the name, outside the tracker, the tests and the
    documentation artwork (`docs/` is not something an installation refers to)."""
    return frozenset(p for p in _tracked()
                     if "pantheon" in p.lower()
                     and not p.startswith((".pantheon/", "tests/", "docs/")))


def _compose_files(paths) -> list:
    return [p for p in paths
            if re.fullmatch(r"docker-compose[^/]*\.ya?ml|docker/[^/]+\.ya?ml", p)]


def _compose_names(files: dict) -> tuple:
    """`(services, volumes, app)` over every compose file. The app is the one
    service the base file builds from the checkout (`build: .`) — the overlays
    build the workstation from `./workstation`, which is not the app."""
    services, volumes, app = set(), set(), set()
    for rel, text in files.items():
        doc = yaml.safe_load(text) or {}
        for name, body in (doc.get("services") or {}).items():
            services.add(name)
            if rel == "docker-compose.yml" and isinstance(body, dict) and body.get("build") == ".":
                app.add(name)
        volumes.update((doc.get("volumes") or {}).keys())
    return frozenset(services), frozenset(volumes), frozenset(app)


@functools.lru_cache(maxsize=None)
def tree_compose() -> tuple:
    return _compose_names({p: (ROOT / p).read_text(encoding="utf-8")
                           for p in _compose_files(_tracked())})


# POSIX ERE, because `git grep -E` reads it too; matched whole with `finditer`.
_HEADER = r"X-{}(-[A-Za-z]+)+"
_CODE_SUFFIXES = (".py", ".js", ".mjs", ".html", ".sh")


@functools.lru_cache(maxsize=None)
def tree_headers() -> frozenset:
    pat = re.compile(_HEADER.format("Pantheon"))
    return frozenset(m.group(0) for rel, text in _tracked_texts()
                     if rel.endswith(_CODE_SUFFIXES)
                     for m in pat.finditer(text))


_UA = re.compile(
    r"""(?:User-Agent["']\s*:\s*|_USER_AGENT\s*=\s*|_USER_AGENT["']\s*,\s*)["']([^"']+)["']""")


def _user_agents(texts, word: str) -> frozenset:
    return frozenset(ua for text in texts for ua in _UA.findall(text)
                     if word in ua.lower())


@functools.lru_cache(maxsize=None)
def tree_user_agents() -> frozenset:
    return _user_agents((t for rel, t in _tracked_texts() if rel.endswith(".py")), "pantheon")


def _browser_text(pairs) -> str:
    return "\n".join(t for rel, t in pairs
                     if rel.startswith("static/") and not rel.startswith("static/lib/"))


@functools.lru_cache(maxsize=None)
def tree_browser_text() -> str:
    return _browser_text(_tracked_texts())


def browser_has(literal: str) -> bool:
    return re.search(r"""['"`]""" + re.escape(literal), tree_browser_text()) is not None


# Stored values: each one is a constant in the module that owns it. Resolved
# with `ast` inside that module's own scope (`Law 20`, option 2) — importing
# `routes.auth_routes` to read one string would make this test depend on the
# whole application importing cleanly.
STORED = {
    # notes' "What" cell        (module,                   owner class or None, constant)
    "Session cookie":           ("routes/auth_routes.py",  None, "SESSION_COOKIE"),
    "API token prefix":         ("core/api_tokens.py",     None, "TOKEN_PREFIX"),
    "Memory collection":        ("src/memory_vector.py",   "MemoryVectorStore", "COLLECTION_NAME"),
    "RAG collection":           ("src/rag_vector.py",      None, "COLLECTION_NAME"),
    "Tool index collection":    ("src/tool_index.py",      None, "COLLECTION_NAME"),
    "No-login owner":           ("src/owner_identity.py",  None, "DEFAULT_LOCAL_OWNER"),
}


def constant(text: str, owner: str | None, name: str):
    tree = ast.parse(text)
    scope = tree.body
    if owner:
        scope = next(n.body for n in tree.body
                     if isinstance(n, ast.ClassDef) and n.name == owner)
    for node in scope:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not assigned at the top of its scope")


def tree_stored(what: str):
    rel, owner, name = STORED[what]
    return constant((ROOT / rel).read_text(encoding="utf-8"), owner, name)


def tree_accepted_token_prefixes() -> tuple:
    return constant((ROOT / "core/api_tokens.py").read_text(encoding="utf-8"),
                    None, "ACCEPTED_TOKEN_PREFIXES")


def tree_lanes() -> tuple:
    text = (ROOT / "src/embedding_lanes.py").read_text(encoding="utf-8")
    return (constant(text, None, "LANE_FASTEMBED"), constant(text, None, "LANE_CUSTOM"))


def _container_user(entrypoint: str) -> str:
    m = re.search(r"(?m)^[ \t]*useradd\b[^\n]*[ \t](\S+)[ \t]*$", entrypoint)
    assert m, "docker/entrypoint.sh no longer creates the container user with useradd"
    return m.group(1)


def _bundle_id(script: str) -> str:
    m = re.search(r"CFBundleIdentifier</key>\s*<string>([^<]+)</string>", script)
    assert m, "build-macos-app.sh no longer sets CFBundleIdentifier"
    return m.group(1)


def _unit(paths) -> str:
    units = [p for p in paths if "/" not in p and p.endswith(".service")]
    assert len(units) == 1, units
    return units[0]


def tree_single(what: str) -> str:
    if what in STORED:
        return tree_stored(what)
    if what == "Compose service":
        (app,) = tree_compose()[2]
        return app
    if what == "Container user":
        return _container_user((ROOT / "docker/entrypoint.sh").read_text(encoding="utf-8"))
    if what == "systemd unit":
        return _unit(_tracked())
    if what == "macOS bundle id":
        return _bundle_id((ROOT / "build-macos-app.sh").read_text(encoding="utf-8"))
    raise KeyError(what)


SINGLES = ("Compose service", "Container user", "systemd unit", "macOS bundle id",
           *STORED)


# ── the fork point's own lists (need b4d1293) ───────────────────────────────

def _up(*args: str) -> str:
    proc = _git(*args)
    assert proc.returncode in (0, 1), proc.stderr  # 1 = git grep found nothing
    return proc.stdout


def _up_show(path: str) -> str:
    return _up("show", f"{_claims().FORK_POINT}:{path}")


@functools.lru_cache(maxsize=None)
def _up_files() -> tuple:
    out = _up("ls-tree", "-r", "--name-only", _claims().FORK_POINT)
    return tuple(p for p in out.split("\n") if p)


def _up_grep(pattern: str, *pathspec: str) -> frozenset:
    out = _up("grep", "-ohIE", pattern, _claims().FORK_POINT, "--", *pathspec)
    return frozenset(x for x in out.split("\n") if x)


def up_env_names() -> frozenset:
    return _up_grep(r"\bODYSSEUS_[A-Z0-9_]+", ".", ":!tests")


def up_cli_names() -> frozenset:
    out = _up("ls-tree", _claims().FORK_POINT, "scripts/")
    names = set()
    for line in out.split("\n"):
        if not line:
            continue
        mode, _type, _sha, path = line.split(None, 3)
        name = path.rsplit("/", 1)[-1]
        if mode == "100755" and (name == "odysseus" or name.startswith("odysseus-")):
            names.add(name)
    return frozenset(names)


def up_named_paths() -> frozenset:
    cli = {f"scripts/{n}" for n in up_cli_names()}
    return frozenset(p for p in _up_files()
                     if "odysseus" in p.lower() and p not in cli
                     and not p.startswith(("tests/", "docs/")))


def up_compose() -> tuple:
    return _compose_names({p: _up_show(p) for p in _compose_files(_up_files())})


def up_headers() -> frozenset:
    return _up_grep(_HEADER.format("Odysseus"), ".", ":!tests")


def up_user_agents() -> frozenset:
    texts = [_up_show(p) for p in _up_files() if p.endswith(".py") and not p.startswith("tests/")]
    return _user_agents(texts, "odysseus")


def up_browser_literals() -> frozenset:
    found = _up_grep(r"""['"`](ody[-.]|odysseus[-.:_])[A-Za-z0-9_.:-]*""",
                     "static", ":!static/lib")
    return frozenset(x[1:] for x in found)


def up_single(what: str) -> str:
    if what == "API token prefix":
        # `core/api_tokens.py` is Pantheon's (`B43`, 2026-09-07). At the fork
        # point the prefix was a literal at the mint site the token routes own.
        m = re.search(r"""["'](\w+_)["']\s*\+\s*secrets\.token_urlsafe""",
                      _up_show("routes/api_token_routes.py"))
        assert m, "the fork point's token route no longer mints a prefixed token"
        return m.group(1)
    if what in STORED:
        rel, owner, name = STORED[what]
        return constant(_up_show(rel), owner, name)
    if what == "Compose service":
        (app,) = up_compose()[2]
        return app
    if what == "Container user":
        return _container_user(_up_show("docker/entrypoint.sh"))
    if what == "systemd unit":
        return _unit(_up_files())
    if what == "macOS bundle id":
        return _bundle_id(_up_show("build-macos-app.sh"))
    raise KeyError(what)


def _housekeeping(text: str) -> dict:
    tree = ast.parse(text)
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) else [])
        if any(isinstance(t, ast.Name) and t.id == "HOUSEKEEPING_DEFAULTS" for t in targets):
            out = {}
            for k, v in zip(node.value.keys, node.value.values):
                for kk, vv in zip(v.keys, v.values):
                    if isinstance(kk, ast.Constant) and kk.value == "legacy_names":
                        out[k.value] = tuple(ast.literal_eval(vv))
            return out
    raise AssertionError("HOUSEKEEPING_DEFAULTS not found")


def tree_legacy_names() -> dict:
    return _housekeeping((ROOT / "src/task_scheduler.py").read_text(encoding="utf-8"))


# ── reading the notes, one section at a time ────────────────────────────────

def _notes_files() -> list:
    return sorted(p for p in NOTES_DIR.glob("*.md") if VERSION_FILE.match(p.name))


@functools.lru_cache(maxsize=None)
def _notes(version: str) -> str:
    return (NOTES_DIR / f"{version}.md").read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    """The body under one heading, up to the next heading of the same or a
    higher level. `Law 20`: an assertion about a table is an assertion inside
    the section that owns it, never a match anywhere in the file."""
    level = len(heading) - len(heading.lstrip("#"))
    lines = text.split("\n")
    try:
        start = lines.index(heading)
    except ValueError:
        raise AssertionError(f"the notes have no `{heading}` section") from None
    stop = re.compile(rf"^#{{1,{level}}} ")
    body = []
    for line in lines[start + 1:]:
        if stop.match(line):
            break
        body.append(line)
    return "\n".join(body)


def _cell(raw: str) -> str:
    return raw.strip().strip("`").strip()


def table(body: str) -> list:
    """Rows of every Markdown table in `body`, header and rule left out."""
    rows, header_seen = [], False
    for line in body.split("\n"):
        if not line.startswith("|"):
            header_seen = False
            continue
        cells = [_cell(c) for c in line.strip().strip("|").split("|")]
        if not header_seen:
            header_seen = True
            continue
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue
        rows.append(cells)
    return rows


def new_list(body: str) -> set:
    """The code spans in the paragraph that opens `**New in Pantheon`."""
    m = re.search(r"\*\*New in Pantheon.*?(?:\n\s*\n|\Z)", body, re.S)
    assert m, "no `**New in Pantheon` paragraph in this section"
    return set(re.findall(r"`([^`]+)`", m.group(0)))


def _versions():
    return [VERSION_FILE.match(p.name).group(1) for p in _notes_files()]


def _live_versions():
    """Notes for the version the tree reports and not yet tagged: the only
    notes that still describe *this* tree."""
    v = _app_version()
    return [v] if v in _versions() and not _released(v) else []


ENV = "### Environment variables"
CLI = "### Command-line tools"
PATHS = "### Files and paths"
SERVICES = "### Services, containers and volumes"
STORED_SEC = "### Stored values"
HEADERS = "### Headers"
AGENTS = "### User agents"
BROWSER = "### Browser storage and the strings the browser code carries"
GATES = "### Open gates"


def _pairs(version: str, heading: str) -> list:
    rows = table(section(_notes(version), heading))
    assert rows, f"{heading} has no table"
    return rows


# ═══ the artefact exists, and the changelog points at it ═══════════════════

def test_the_version_the_tree_reports_has_release_notes():
    """`P10-12`'s artefact, for the version `GET /api/version` answers with."""
    assert (NOTES_DIR / f"{_app_version()}.md").is_file(), (
        f"no docs/release-notes/{_app_version()}.md — the release artefact for "
        f"the version this tree reports (CHANGELOG.md § Versions)"
    )


@pytest.mark.parametrize("version", _versions())
def test_each_notes_file_is_a_changelog_version_and_is_linked_from_it(version):
    changelog = CHANGELOG.read_text(encoding="utf-8")
    assert re.search(rf"^## \[{re.escape(version)}\]", changelog, re.M), (
        f"docs/release-notes/{version}.md names a version CHANGELOG.md has no "
        f"`## [{version}]` heading for"
    )
    listed = section(changelog, "## Release notes")
    assert f"(docs/release-notes/{version}.md)" in listed, (
        "CHANGELOG.md's § Release notes does not link the notes; a stranger reads "
        "the changelog first, and § Versions says that is where they are listed"
    )
    title = _notes(version).split("\n", 1)[0]
    assert title.startswith("# ") and version in title, title


# ═══ the credit leads ═══════════════════════════════════════════════════════

@pytest.mark.parametrize("version", _versions())
def test_the_first_section_is_the_odysseus_credit(version):
    """*"Lead with the Odysseus credit"* — the first `##` section, and it
    carries the upstream, the licence, the fork point and both of its dates
    (`B349`: two dates, two meanings, each labelled)."""
    text = _notes(version)
    headings = [ln for ln in text.split("\n") if ln.startswith("## ")]
    assert headings and "Odysseus" in headings[0], headings[:2]
    credit = section(text, headings[0])
    c = _claims()
    for needle in (f"https://github.com/{c.UPSTREAM_REMOTE}", f"`{c.FORK_POINT}`",
                   "**AGPL-3.0-or-later**"):
        assert needle in credit, f"the credit does not state {needle!r}"
    # Each date stated as itself, in bold, not merely inside a timestamp: the
    # commit's date and the fork's start are two facts (`B349`).
    for date in (c.FORK_POINT_DATE, c.FORK_CLONE_DATE):
        assert re.search(rf"\*\*{re.escape(date)}\b", credit), (
            f"the credit does not state {date} as a date of its own"
        )


@pytest.mark.parametrize("version", _versions())
def test_the_credits_history_figures_are_the_fork_points(version):
    """The size of what Pantheon was given, counted off the fork point's own
    history: its commits, its distinct author names, its first commit and its
    most frequent author. Needs the history behind `b4d1293`, not just the
    commit (CI's `fetch-depth: 0` has it)."""
    _need_upstream()
    fp = _claims().FORK_POINT
    count = _git("rev-list", "--count", fp)
    if count.returncode != 0:
        pytest.skip("the fork point is here but the history behind it is not (a shallow clone)")
    names = [n for n in _git("log", "--format=%an", fp).stdout.split("\n") if n]
    top = max(set(names), key=names.count)
    roots = _git("rev-list", "--max-parents=0", fp).stdout.split()
    credit = section(_notes(version), next(ln for ln in _notes(version).split("\n")
                                           if ln.startswith("## ")))
    assert f"**{int(count.stdout):,} commits**" in credit
    assert f"**{len(set(names))} distinct author names**" in credit
    assert f"`{top}` wrote {names.count(top)} of them" in credit
    assert len(roots) == 1 and f"`{roots[0][:7]}`" in credit


@pytest.mark.parametrize("version", _versions())
def test_the_forks_first_commit_is_the_one_the_credit_names(version):
    """The fork's start is measured, not remembered: the oldest commit whose
    parent is the fork point, in UTC. Runs where the history reaches it (CI)."""
    _need_upstream()
    fp = _git("rev-parse", f"{_claims().FORK_POINT}^{{commit}}").stdout.strip()
    log = _git("log", "--format=%H %P %ct", "HEAD").stdout.split("\n")
    children = [ln.split() for ln in log if ln and fp in ln.split()[1:-1]]
    if not children:
        pytest.skip("the fork point is reachable but HEAD's history does not descend from it here")
    first = min(children, key=lambda c: int(c[-1]))
    utc = _git("log", "-1", "--date=format-local:%Y-%m-%d", "--format=%cd", first[0],
               env={"TZ": "UTC"}).stdout.strip()
    credit = section(_notes(version), next(ln for ln in _notes(version).split("\n")
                                           if ln.startswith("## ")))
    assert first[0][:7] in credit, f"the credit does not name {first[0][:7]}"
    assert utc in credit


# ═══ environment variables ═════════════════════════════════════════════════

@pytest.mark.parametrize("version", _versions())
def test_every_env_row_is_the_mechanical_rename_and_still_exists(version):
    texts = "\n".join(t for _r, t in _tracked_texts())
    for old, new, where in (r[:3] for r in _pairs(version, ENV)):
        assert renamed(old) == new and old.startswith("ODYSSEUS_"), (old, new)
        assert new in texts, f"{new} is in the notes and nowhere in the tree"
        assert where == read_in(new), f"{new}: the notes say {where!r}, the tree says {read_in(new)!r}"


@pytest.mark.parametrize("version", _live_versions())
def test_every_env_name_the_tree_reads_is_in_the_notes(version):
    """Complete against `check-env-declared.py`: a `PANTHEON_*` variable the
    code reads or `.env.example` declares is a rename or is new — never
    missing. Fails on the tree as it stood: there were no notes."""
    body = section(_notes(version), ENV)
    renamed_to = {r[1] for r in table(body)}
    new = new_list(body)
    assert not renamed_to & new, renamed_to & new
    missing = sorted(tree_env_names() - renamed_to - new)
    assert not missing, f"read by the tree, absent from the notes: {missing}"
    stale = sorted(new - tree_env_names())
    assert not stale, f"listed as new and no longer read: {stale}"


@pytest.mark.parametrize("version", _versions())
def test_the_env_table_is_exactly_what_the_fork_point_had(version):
    _need_upstream()
    body = section(_notes(version), ENV)
    assert {r[0] for r in table(body)} == up_env_names()
    had = {renamed(n) for n in up_env_names()}
    assert not new_list(body) & had, "listed as new, and Odysseus had it"


# ═══ command-line tools ════════════════════════════════════════════════════

@pytest.mark.parametrize("version", _versions())
def test_every_cli_row_is_the_mechanical_rename(version):
    for old, new in (r[:2] for r in _pairs(version, CLI)):
        assert renamed(old) == new, (old, new)
        assert (ROOT / "scripts" / new).is_file(), new


@pytest.mark.parametrize("version", _live_versions())
def test_every_command_the_dispatcher_runs_is_in_the_notes(version):
    body = section(_notes(version), CLI)
    listed = {r[1] for r in table(body)} | new_list(body)
    missing = sorted(tree_cli_names() - listed)
    assert not missing, f"`pantheon` runs these and the notes do not name them: {missing}"


@pytest.mark.parametrize("version", _versions())
def test_the_cli_table_is_exactly_what_the_fork_point_had(version):
    _need_upstream()
    assert {r[0] for r in _pairs(version, CLI)} == up_cli_names()


# ═══ files and paths ═══════════════════════════════════════════════════════

@pytest.mark.parametrize("version", _versions())
def test_every_path_row_is_the_mechanical_rename_and_exists(version):
    tracked = set(_tracked())
    for old, new in (r[:2] for r in _pairs(version, PATHS)):
        assert renamed(old) == new, (old, new)
        assert new in tracked, f"{new} is not a tracked file"


@pytest.mark.parametrize("version", _live_versions())
def test_every_named_path_is_in_the_notes(version):
    """Every tracked path carrying the name is a renamed path, a command
    (`scripts/<name>`), or listed as new."""
    body = section(_notes(version), PATHS)
    cli = section(_notes(version), CLI)
    covered = ({r[1] for r in table(body)} | new_list(body)
               | {f"scripts/{r[1]}" for r in table(cli)}
               | {f"scripts/{n}" for n in new_list(cli)})
    missing = sorted(tree_named_paths() - covered)
    assert not missing, f"tracked, carrying the name, and not in the notes: {missing}"


@pytest.mark.parametrize("version", _versions())
def test_the_path_table_is_exactly_what_the_fork_point_had(version):
    _need_upstream()
    assert {r[0] for r in _pairs(version, PATHS)} == up_named_paths()


# ═══ services, containers, volumes, and the stored values ════════════════

def _singles(version: str) -> dict:
    rows = {}
    for heading in (SERVICES, STORED_SEC):
        for r in table(section(_notes(version), heading)):
            rows[r[0]] = r
    return rows


@pytest.mark.parametrize("version", _versions())
@pytest.mark.parametrize("what", SINGLES)
def test_each_single_name_is_the_one_the_tree_uses(version, what):
    rows = _singles(version)
    assert what in rows, f"the notes have no `{what}` row"
    _what, old, new = rows[what][:3]
    if version in _live_versions():
        assert new == tree_single(what), (what, new, tree_single(what))
    assert renamed(old) == new, (what, old, new)


@pytest.mark.parametrize("version", _versions())
@pytest.mark.parametrize("what", SINGLES)
def test_each_single_name_is_the_one_the_fork_point_used(version, what):
    _need_upstream()
    assert _singles(version)[what][1] == up_single(what), what


@pytest.mark.parametrize("version", _live_versions())
def test_every_compose_service_and_volume_is_in_the_notes(version):
    """Named volumes keep their names; the notes have to say so, because the
    prefix Compose puts on them is what an upgrade loses (measured with
    `docker compose config`, recorded in the notes)."""
    body = section(_notes(version), SERVICES)
    spans = set(re.findall(r"`([^`]+)`", body))
    services, volumes, _app = tree_compose()
    assert not sorted(services - spans), sorted(services - spans)
    assert not sorted(volumes - spans), sorted(volumes - spans)


@pytest.mark.parametrize("version", _versions())
def test_the_named_volumes_odysseus_had_are_unchanged(version):
    _need_upstream()
    _s, up_volumes, _a = up_compose()
    body = section(_notes(version), SERVICES)
    for volume in up_volumes:
        assert f"`{volume}`" in body
    assert up_volumes <= tree_compose()[1]


@pytest.mark.parametrize("version", _live_versions())
def test_the_old_token_prefix_is_still_honoured_as_the_notes_say(version):
    """The one stored value with a migration path (`P0-31`,
    `check-fork-names.py`'s `ALLOWED`): tokens minted as `ody_` keep working."""
    old = _singles(version)["API token prefix"][1]
    assert old in tree_accepted_token_prefixes()
    assert f"`{old}`" in section(_notes(version), STORED_SEC)


@pytest.mark.parametrize("version", _live_versions())
def test_the_collection_lanes_are_named(version):
    body = section(_notes(version), STORED_SEC)
    for lane in tree_lanes():
        assert f"_{lane}`" in body, lane


@pytest.mark.parametrize("version", _versions())
def test_the_task_rename_map_is_the_fork_points_own(version):
    """`legacy_names` is not a Pantheon rename: it was already at the fork
    point, so an Odysseus install has nothing to do. The notes say so and give
    the count; both are derived."""
    m = tree_legacy_names()
    body = section(_notes(version), STORED_SEC)
    n_names = sum(len(v) for v in m.values())
    assert f"{len(m)} built-in tasks" in body and f"{n_names} earlier names" in body
    if _upstream_reachable():
        assert _housekeeping(_up_show("src/task_scheduler.py")) == m


# ═══ headers and user agents ═══════════════════════════════════════════════

@pytest.mark.parametrize("version", _versions())
def test_every_header_row_is_the_mechanical_rename(version):
    for r in _pairs(version, HEADERS):
        assert renamed(r[0]) == r[1], r[:2]


@pytest.mark.parametrize("version", _live_versions())
def test_every_header_the_tree_sends_or_reads_is_in_the_notes(version):
    body = section(_notes(version), HEADERS)
    listed = {r[1] for r in table(body)} | new_list(body)
    assert tree_headers() == listed, sorted(tree_headers() ^ listed)


@pytest.mark.parametrize("version", _versions())
def test_the_header_table_is_exactly_what_the_fork_point_had(version):
    _need_upstream()
    assert {r[0] for r in _pairs(version, HEADERS)} == up_headers()


@pytest.mark.parametrize("version", _live_versions())
def test_every_user_agent_is_in_the_notes(version):
    body = section(_notes(version), AGENTS)
    listed = {r[1] for r in table(body) if r[1] != "—"} | new_list(body)
    assert tree_user_agents() == listed, sorted(tree_user_agents() ^ listed)


@pytest.mark.parametrize("version", _versions())
def test_the_user_agent_table_is_exactly_what_the_fork_point_had(version):
    _need_upstream()
    assert {r[0] for r in _pairs(version, AGENTS)} == up_user_agents()


# ═══ browser storage ═══════════════════════════════════════════════════════

@pytest.mark.parametrize("version", _versions())
def test_every_browser_row_is_renamed_where_used_and_gone_where_not(version):
    """A row's Pantheon cell is the renamed literal when the browser code still
    carries it and `—` when it does not. Both directions are checkable here."""
    for old, new in (r[:2] for r in _pairs(version, BROWSER)):
        if new == "—":
            if version in _live_versions():
                assert not browser_has(renamed(old)), f"{old}: the notes say gone; {renamed(old)} is used"
        else:
            assert new == renamed(old), (old, new)
            if version in _live_versions():
                assert browser_has(new), f"{new} is not in the browser code"


@pytest.mark.parametrize("version", _versions())
def test_the_browser_table_is_exactly_what_the_fork_point_had(version):
    _need_upstream()
    assert {r[0] for r in _pairs(version, BROWSER)} == up_browser_literals()


# ═══ the gates the notes admit to ══════════════════════════════════════════

@pytest.mark.parametrize("version", _live_versions())
def test_the_open_gates_are_the_ship_lines_open_blocking_rows(version):
    """The notes say what still stands between this tree and the line
    `SHIP-LINE.md` draws — every open `blocking` row, and nothing that has
    closed. `P10-12` is the notes themselves and is left out. Stands down when
    the tag is cut: from then on the list is a record of release day."""
    ship = _load_path("_release_ship_line", ROOT / ".pantheon" / "ship-line.py")
    rows = ship.parse_rows(ship.TRACKER.read_text(encoding="utf-8"))
    register = ship.parse_register(ship.PROPOSAL.read_text(encoding="utf-8"))
    blocking = {r.id for r in rows
                if r.open and register.get(r.id, ("", ""))[0] == "blocking"} - {"P10-12"}
    body = section(_notes(version), GATES)
    listed = {s for s in re.findall(r"`([^`]+)`", body) if ROW_ID.match(s)}
    assert listed == blocking, (
        f"open and blocking, not in the notes: {sorted(blocking - listed)}; "
        f"in the notes and no longer an open gate: {sorted(listed - blocking)}"
    )
