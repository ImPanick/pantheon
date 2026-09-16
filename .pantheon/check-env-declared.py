#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P3-23` — environment variables the code reads and `.env.example` never mentions.

There are four sources of truth about this product's configuration and no two
of them agree: what the code reads, what `.env.example` declares, what
`docker-compose.yml` forwards, and what `docs/setup.md` explains. An operator
looks in `.env.example`. `H08` is what the gap costs: the switch that uncaps
every local agent run appeared **nowhere** outside the module that read it, so
the only way to turn the behaviour off was to already know the variable's name.

Two directions, and they are not symmetrical.

  UNDECLARED   read by app code, absent from `.env.example`. Ratcheted: may
               fall, may not rise. Detected from literal `os.getenv("X")` /
               `os.environ["X"]` call sites, which is precise about what it
               finds and **blind to indirect reads** — `os.getenv(SOME_CONST)`
               is invisible here. That is why the other direction does not use
               the same scan.

  UNREFERENCED declared in `.env.example` and appearing nowhere else in the
               repository at all. Hard rule, max 0: a documented knob nothing
               consumes is worse than an undocumented one, because an operator
               who sets it believes something changed. Matched by plain text
               across every tracked file, so an indirect read, a compose
               forward or a mention in a shell script all count — loose on
               purpose, because a false alarm here would send someone deleting
               a variable that works.

`B20` adds a third direction, and it is the same operator question the other
two ask — *can this variable do anything?* — from the one side neither could
see. A variable can be declared in `.env.example`, forwarded by compose,
explained in the docs, and read by a line that cannot execute:

  UNREACHABLE  read beneath a settings key whose SHIPPED DEFAULT IS TRUTHY.
               `settings.get_setting` merges `DEFAULT_SETTINGS` on every read,
               so `get_setting(K, None) or os.getenv(E)` never reaches the
               `or` — not after the first save, which is what `B20` originally
               claimed, but **at import, on a fresh install, with no settings
               file at all**. `H06` found `PANTHEON_TASK_CONCURRENCY_CAP` dead
               that way on every install this product has ever had. Hard rule,
               max 0, and 0 today: this is a ratchet against the reintroduction
               rather than a backlog. A scope that asks the question properly —
               `settings.setting_is_explicit`, or `settings.env_backed` — is
               not flagged, because those are the two answers.

  MIXED        one dict, some values through `env_backed` and one straight off
               `settings.get`. `H07` converted ten fields of the legacy mail
               config and left the eleventh; `IMAP_STARTTLS` was therefore
               honoured by `mcp_servers/email_server.py` and ignored by
               `routes/email_helpers.py` **on the same host, for the same
               mailbox**. Hard rule, max 0. Narrow on purpose: the finding is
               a sibling left behind, and a rule that fired on every settings
               read near an `env_backed` would be noise nobody reads.

  SPELLING     an environment value judged by an inline `== "true"` or
               `in ("1","true","yes")` instead of by `src/env_flags.env_flag`.
               `B91` counted **38 environment booleans and 10 incompatible
               rules** on 2026-09-15: `PANTHEON_STARTUP_WARMUPS=1` on and
               `IMAP_STARTTLS=1` off in one process, `AUTH_ENABLED=0` leaving
               auth enabled, `CLEANUP_ENABLED=" true"` off at the one site that
               never stripped. Hard rule, max 0 unexempted — a site that must
               keep its own rule says so with `# env-spelling: <reason>`, and
               nine do, each one a case where the shared vocabulary would loosen
               a control or flip a live deployment. The reason lives at the
               site, because a list of exempt names inside a checker is a list
               nobody reads next to the code it is about.

  BOUNDARY     an HTTP request field judged by an inline `== "true"` instead of
               by `src/env_flags.request_flag`. `B97` counted 16 non-environment
               truthiness sites and three vocabularies between them:
               `plan_mode=1` from a form post meant *no* while `plan_mode=true`
               meant yes, on a safety mode. Hard rule, max 0 unexempted, held
               with `# flag-spelling: <reason>` the way SPELLING is held.

  VOCABULARY   a function that is itself a yes/no rule and is not one of the
               four named owners. The other rules find a *site* by knowing where
               its value came from; a model's tool argument and a line of skill
               frontmatter arrive as plain dict values and no dataflow pass can
               tell them from any other string. What can be found is the
               **helper** — every one of the five vocabularies `B97` counted was
               a small function whose whole job was to answer *is this yes*, and
               `routes/model_routes._truthy` and
               `src/tool_policy.tool_toggle_enabled` were exactly that. A
               vocabulary is a *list*: a single-word comparison is one spelling,
               not a rule, and treating every `== "1"` in the tree as one is how
               a checker becomes noise nobody reads (`auto_submitted != "no"` is
               RFC 3834, `x-ratelimit-remaining == "0"` is a count, `level ==
               "off"` is a SafeSearch level — 14 of them). Hard rule, max 0.

`B98` is what made the last three of those honest, and the gap it closed was
measured before it was built rather than after. Every rule above saw **one
scope, one dict, or one comparison at a time**, so a resolver that read the
variable in one statement and judged it in the next was invisible to all of
them. The measurement, taken 2026-09-15 with a per-scope dataflow pass:

  * SPELLING gained **one** genuine site — `routes/auth_routes.py` `SECURE_COOKIES`,
    which reads `configured = os.getenv(...)` and then `configured in
    ("true","false")`. **It already carried an `# env-spelling:` exemption, and
    the exemption was holding nothing**: `exempt_spellings` counted nine holds
    while the rule could reach eight sites, and deleting the ninth would have
    failed no build. That one-site gap is the whole finding, and it is the kind
    that only shows when you count both sides.
  * A fourth shape of the same blindness turned up while building it:
    `src/host_docker_access.py` binds `env = os.environ` and reads
    `env.get(HOST_DOCKER_ENV_VAR)`, so neither this scan nor `literal_reads`
    ever saw it — a `FORBIDDEN.md` Part 2 control whose spelling nothing was
    checking. The pass resolves `os.environ` aliases now and the site is held.
  * UNREACHABLE across function boundaries: **zero**. A settings key read in one
    function and its matching variable in another does not occur in this tree.
  * `services/search/providers._get_provider_key`, `B20`'s worked example where
    the pairing lives in two dict literals rather than in a name: **four pairs
    found, zero findings** — all four ship a falsy default, so the environment
    leg beneath them is genuinely reachable. The hand-checked answer `B20`
    recorded was right, and now something checks it.
  * MIXED through a named helper rather than a lambda alias: **zero**.

A first draft of the pass walked the module with `ast.walk` and reported **104**
findings against 9 real ones, because `ast.walk` does not stop at a nested
function: one namespace held every local in the file and `unit in ("hour","hr")`
inherited `PANTHEON_FALLBACK_OWNER` from twelve hundred lines away. The pass
respects scope. It is also where `_blank_only` comes from — `""` is a member of
three real off-lists, so it has to be in `_TRUTH_TOKENS`, but `x == ""` on its
own is asking *did anyone set this*, which is a different question and 44 places
in this tree ask it.

`NOT_OURS` holds the names Pantheon reads but does not define: the operating
system's, the shell's, and third-party libraries' own conventions. Declaring
`PATH` or `HF_TOKEN` in our example file would be a claim we have no standing
to make. Each entry says whose it is.

Usage:  python3 .pantheon/check-env-declared.py [--max N] [--list]
"""
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = ROOT / ".env.example"
SKIP_PREFIXES = ("tests/", ".pantheon/")
# Parsed, never imported. Importing `src.settings` to read `DEFAULT_SETTINGS`
# would make a checker's verdict depend on the whole application importing
# cleanly, and on `PANTHEON_DATA_DIR` in whatever shell ran it.
SETTINGS_SOURCE = ROOT / "src" / "settings.py"

# Names read from the environment that belong to somebody else. Declaring these
# in our own example file would be a claim about their meaning that we do not
# get to make, and an operator who changed one there would be surprised.
NOT_OURS = {
    # The operating system and the shell.
    "PATH": "the OS search path",
    "PYTHONPATH": "CPython's module search path",
    "TMPDIR": "the POSIX temp directory",
    "APPDATA": "Windows roaming application data",
    "LOCALAPPDATA": "Windows local application data",
    "ComSpec": "the Windows command interpreter",
    "TERM": "the terminal type, for colour detection",
    "USERNAME": "Windows' own name for the logged-in user",
    "USER": "the POSIX name for the logged-in user",
    "COLORTERM": "terminal colour capability",
    "LOG_LEVEL": "the standard-library logging convention, read by scripts/_lib/cli.py",
    # Third-party libraries reading their own settings.
    "SSL_CERT_FILE": "OpenSSL's own trust-store override",
    "REQUESTS_CA_BUNDLE": "requests' own trust-store override",
    "HF_TOKEN": "Hugging Face Hub's own credential",
    "HUGGING_FACE_HUB_TOKEN": "Hugging Face Hub's own credential",
    "HF_HUB_DISABLE_PROGRESS_BARS": "Hugging Face Hub's own switch",
    "HF_HUB_DOWNLOAD_MAX_WORKERS": "Hugging Face Hub's own switch",
    "npm_config_cache": "npm's own cache location",
}

_ENV_NAME = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)\s*=")


def _tracked(pattern: str | None = None) -> list[str]:
    args = ["git", "ls-files"] + ([pattern] if pattern else [])
    out = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return out.split()


def declared() -> dict[str, int]:
    """Name → line number in `.env.example`, commented entries included."""
    found: dict[str, int] = {}
    for lineno, line in enumerate(ENV_EXAMPLE.read_text(encoding="utf-8").splitlines(), 1):
        match = _ENV_NAME.match(line)
        if match:
            found.setdefault(match.group(1), lineno)
    return found


@lru_cache(maxsize=None)
def _parsed(rel: str):
    """`(source, tree)` for one tracked file, parsed once per process.

    `B220`. Seven passes below walk every tracked `.py`, and before this each
    one re-read and re-parsed all 360 of them: 2.4s of parsing, seven times, in
    a checker that CI and eight tests invoke. Keyed on the repository-relative
    path and read through `ROOT`, so a test that points the module at a fixture
    repository gets its own module object and its own empty cache (the loader in
    `tests/test_env_boundaries.py` builds one per fixture). `Law 19` — nothing
    edits a file during a run — is what makes caching a parse safe at all.

    Returns `None` for a file that cannot be read or parsed, which is the same
    `continue` every caller wrote by hand.
    """
    try:
        source = (ROOT / rel).read_text(encoding="utf-8")
        return source, ast.parse(source)
    except (SyntaxError, OSError):
        return None


def _scan_files():
    """`(rel, source, tree)` for every tracked `.py` the rules look at."""
    for rel in _tracked("*.py"):
        if rel.startswith(SKIP_PREFIXES):
            continue
        parsed = _parsed(rel)
        if parsed is not None:
            yield (rel, *parsed)


def _is_environ_itself(node) -> bool:
    """Whether this expression evaluates to the process environment mapping.

    `B151`. **Deliberately narrower than `_environ_aliases`**, and the
    difference is the row. That pass asks whether `os.environ` appears anywhere
    in the assigned expression, which is right for the question it answers — it
    decides which *comparisons* SPELLING and BOUNDARY are allowed to judge, and
    a false positive there costs one `# env-spelling:` hold. This one feeds the
    UNDECLARED **count**, where a false positive is a phantom undeclared
    variable in a number an operator reads off `ci.yml`.

    Measured 2026-09-16, reusing `_environ_aliases` here: **UNDECLARED 71 → 88,
    and all 17 added names are false.** `mcp_servers/email_server.py` builds
    `cfg = {... os.environ.get(...) ...}`, which makes `cfg` an "alias", and
    then `cfg["imap_password"]` reads as an environment variable named
    `imap_password` — fifteen of them from that one dict. `scripts/hf_download.py`
    does the same with a `kwargs` dict. That is not a widening, it is noise, and
    it is why this rule asks whether the value *is* the mapping.
    """
    if _is_environ(node):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "copy" and _is_environ(node.func.value):
        return True
    if isinstance(node, ast.IfExp):
        return _is_environ_itself(node.body) or _is_environ_itself(node.orelse)
    if isinstance(node, ast.BoolOp):
        return any(_is_environ_itself(v) for v in node.values)
    return False


def _environ_names(scope) -> set:
    """Local names bound to the environment mapping itself, in this scope only.

    Scope-respecting for the reason `_own_body` exists: a module-wide walk would
    let an `env` in one function name an `env` in another (`B98` reported 104
    findings against 9 real ones that way once already).
    """
    names = set()
    for node in _own_body(scope):
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.value is not None:
            target, value = node.target.id, node.value
        if target is not None and _is_environ_itself(value):
            names.add(target)
    return names


def _aliased_reads(rel: str, tree) -> dict[str, set]:
    """Name → files, for reads through a local bound to `os.environ`.

    `B151`. `src/host_docker_access.py` writes `env = os.environ if environ is
    None else environ` and then `env.get(HOST_DOCKER_ENV_VAR)`; `B98` found that
    site through its own dataflow pass and recorded that `literal_reads` still
    could not see it, deliberately, with the asymmetry written down nowhere.
    It is written down now and the scan sees the shape.

    **Measured before widening, because the objection to widening was that the
    ratchet would move without a line of product code changing:** it does not.
    The tree has exactly three strict-alias sites and this rule adds **zero**
    names to UNDECLARED (71 before, 71 after). Two are
    `routes/cookbook_routes.py` writing `env["PYTHONUTF8"] = "1"` into a *copy*
    it hands a subprocess — a variable we set for a child, not one we read from
    the operator, which is why only a `Load` subscript counts — and the third is
    `host_docker_access` naming its variable through a module constant, which
    `literal_reads` refuses to resolve for the reason `_env_name_of` documents.
    So this is a rule that catches the next one rather than the current one, and
    that is stated rather than implied.

    **`Load` only, and `literal_reads`' own `os.environ[...]` branch is not**,
    which is the one place these two halves disagree. `os.environ["X"] = v` writes into *this*
    process's environment, so the name is one this program uses either way and
    counting it is defensible; `env = os.environ.copy()` then `env["X"] = v`
    writes into a mapping that is about to be handed to a child, and the name is
    one we are *setting*, not one an operator may configure. Measured: eight
    `os.environ[...] =` sites, every one of their names already declared or in
    `NOT_OURS`, so narrowing that branch would change the count by zero and
    `Law 1` says leave it alone.
    """
    found: dict[str, set] = {}
    scopes = [tree] + [n for n in ast.walk(tree)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for scope in scopes:
        names = _environ_names(scope)
        if not names:
            continue
        for node in _own_body(scope):
            name = None
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in ("get", "pop") \
                    and isinstance(node.func.value, ast.Name) \
                    and node.func.value.id in names and node.args \
                    and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                name = node.args[0].value
            elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
                    and node.value.id in names and isinstance(node.ctx, ast.Load) \
                    and isinstance(node.slice, ast.Constant) \
                    and isinstance(node.slice.value, str):
                name = node.slice.value
            if name:
                found.setdefault(name, set()).add(rel)
    return found


def literal_reads() -> dict[str, set]:
    """Name → files that read it with a string literal.

    **What this scan does not see, and why.** It feeds the UNDECLARED ratchet,
    whose ceiling an operator reads off `.github/workflows/ci.yml`, so every
    widening of it moves a number without a line of product code changing and
    has to be measured before it ships. Two asymmetries are deliberate and this
    is where both are written down (`B151`) — the second scan they disagree with
    is `B98`'s dataflow pass, which is wider on purpose in both directions:

    1. **A module-level string constant is not resolved.** `os.getenv(NAME_CONST)`
       is invisible here and visible to `_env_name_of`, which says why at its own
       docstring. `src/host_docker_access.py:50` is the site that makes the
       asymmetry concrete: `env.get(HOST_DOCKER_ENV_VAR)`.
    2. **An `os.environ` alias is resolved, but only a strict one.** See
       `_is_environ_itself` for the measurement — reusing `_environ_aliases`,
       which is the pass `B98` built and the obvious thing to reach for, takes
       UNDECLARED from 71 to 88 and every one of the 17 added names is false.
    """
    found: dict[str, set] = {}
    for rel, source, tree in _scan_files():
        # An alias can only come from an expression naming `environ`, so a file
        # without the word cannot have one. Exact, not a heuristic: `_is_environ`
        # tests an attribute spelled `environ`, which has to be in the source.
        if "environ" in source:
            for name, files in _aliased_reads(rel, tree).items():
                found.setdefault(name, set()).update(files)
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Call):
                func = node.func
                getenvish = (
                    (isinstance(func, ast.Attribute) and (
                        func.attr == "getenv"
                        or (func.attr in ("get", "pop")
                            and isinstance(func.value, ast.Attribute)
                            and func.value.attr == "environ")))
                    or (isinstance(func, ast.Name) and func.id == "getenv")
                )
                # `B91`. `env_flags.env_flag("X", default)` IS a literal read of
                # X, and adopting it at 22 sites took this scan from 143 names
                # to 121 — twelve of them undeclared, which would have lowered
                # the ratchet by hiding the variables rather than documenting
                # them. A helper that makes the checker blinder than the code it
                # replaced is a worse defect than the one it fixed.
                if isinstance(func, ast.Name) and func.id == "env_flag":
                    getenvish = True
                if getenvish and node.args and isinstance(node.args[0], ast.Constant) \
                        and isinstance(node.args[0].value, str):
                    name = node.args[0].value
                # `env_backed(settings, key, ENV)` and its boolean twin name the
                # variable in the THIRD argument. These were invisible here
                # before `B91` — `H07` converted ten mail fields to `env_backed`
                # and this scan stopped seeing all ten, which is why the ratchet
                # had been falling for reasons that were not documentation.
                elif isinstance(func, ast.Name) \
                        and func.id in ("env_backed", "env_backed_flag") \
                        and len(node.args) >= 3 and isinstance(node.args[2], ast.Constant) \
                        and isinstance(node.args[2].value, str):
                    name = node.args[2].value
            elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) \
                    and node.value.attr == "environ" and isinstance(node.slice, ast.Constant) \
                    and isinstance(node.slice.value, str):
                name = node.slice.value
            if name:
                found.setdefault(name, set()).add(rel)
    return found


@lru_cache(maxsize=1)
def _corpus() -> tuple:
    """Every tracked file except `.env.example`, read once."""
    texts = []
    for rel in _tracked():
        if rel == ".env.example":
            continue
        try:
            texts.append((ROOT / rel).read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return tuple(texts)


def unreferenced(names) -> list[str]:
    """Declared names that appear nowhere else in the repository."""
    corpus = _corpus()
    return sorted(n for n in names if not any(n in text for text in corpus))


# ── `B20`: can the variable do anything once it is read? ────────────────────


def _str(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def shipped_defaults() -> dict:
    """`DEFAULT_SETTINGS` as written in `src/settings.py`.

    Only what a literal can express: a key whose default is built by a call or
    a comprehension is recorded as `UNREADABLE`, which is falsy, i.e. never
    flagged. Under-reporting is the right direction for a hard rule — a checker
    that guesses at a value it cannot see would fail a build over its own guess.

    `B90` is why that is a sentinel and not `None` any more. A literal `None` in
    `DEFAULT_SETTINGS` became meaningful — it is the tri-state a stored `False`
    needs to mean *no* — so "ships None" and "we could not read it" stopped
    being the same fact. `UNREADABLE` is falsy so every existing caller reading
    this by truthiness is unchanged, and `is None` now means what it says.
    """
    try:
        tree = ast.parse(SETTINGS_SOURCE.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return {}
    out: dict = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "DEFAULT_SETTINGS"
                and isinstance(node.value, ast.Dict)):
            continue
        for key, value in zip(node.value.keys, node.value.values):
            name = _str(key)
            if name is None:
                continue
            try:
                out[name] = ast.literal_eval(value)
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                out[name] = UNREADABLE
    return out


def _env_name_of(node, consts: dict):
    """The variable an `os.getenv(...)`-shaped call reads, or None.

    Resolves a module-level string constant, unlike `literal_reads` above. That
    asymmetry is deliberate and is the reason this is a second walk rather than
    a widening of the first: `literal_reads` feeds the UNDECLARED ratchet, whose
    ceiling an operator reads off `ci.yml`, and a scan that suddenly sees more
    names would move that number without a line of product code changing.
    `PANTHEON_TASK_CONCURRENCY_CAP` is read as `os.getenv(TASK_CONCURRENCY_CAP_ENV)`
    and is exactly the variable `H06` found dead, so a rule that could not see
    it would not have caught the defect it exists for.
    """
    func = node.func
    getenvish = (
        (isinstance(func, ast.Attribute) and (
            func.attr == "getenv"
            or (func.attr in ("get", "pop")
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "environ")))
        or (isinstance(func, ast.Name) and func.id == "getenv"))
    if not (getenvish and node.args):
        return None
    arg = node.args[0]
    return _str(arg) or (consts.get(arg.id) if isinstance(arg, ast.Name) else None)


def _called(node) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else ""


def _settings_receiver(node) -> bool:
    """Whether `<x>.get("k")` is reading settings rather than any other dict."""
    try:
        receiver = ast.unparse(node.func.value)
    except Exception:
        return False
    return "etting" in receiver


@lru_cache(maxsize=None)
def _module_consts(tree) -> dict:
    # Memoised (`B220`), pure, keyed on the tree `_parsed` holds alive. Four
    # rules ask for the same file's constants and one of them used to ask once
    # per function in it.
    return {n.targets[0].id: _str(n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Assign) and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name) and _str(n.value)}


class _Unreadable:
    """A default this checker could not evaluate — a call, a comprehension.

    **Deliberately neither truthy nor falsy in meaning, and not `None`.** It was
    written falsy first, so that `not shipped` would skip it the way a bare
    `None` used to, and a mutation removing the explicit guard survived: the
    guard was decoration resting on the sentinel's own `__bool__`. That is the
    same shape `B20` found and restructured rather than left. Unknown is not
    false; the caller must say so, and now it has to, because without the guard
    an unreadable default falls through to the truthy-default rule and reports
    a finding nobody can act on."""
    __slots__ = ()

    def __repr__(self) -> str:
        return "<unreadable>"


UNREADABLE = _Unreadable()
_NO_SUCH_KEY = object()


def unreachable(defaults: dict) -> list[str]:
    """Env reads that sit beneath a settings key shipping a truthy default.

    The pairing is by name — `PANTHEON_TASK_CONCURRENCY_CAP` to
    `task_concurrency_cap` — which is how every pair in this tree is spelled
    and is the only correspondence a reader can check without running anything.
    """
    found = []
    for rel, _source, tree in _scan_files():
        consts = _module_consts(tree)
        scopes = [n for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))] + [tree]
        for scope in scopes:
            keys, envs, asked = {}, {}, False
            for node in ast.walk(scope):
                if not isinstance(node, ast.Call):
                    continue
                name = _env_name_of(node, consts)
                if name:
                    envs.setdefault(name, node.lineno)
                called = _called(node)
                if called in ("setting_is_explicit", "is_setting_overridden", "env_backed"):
                    asked = True
                if called in ("get_setting", "get_user_setting") and node.args:
                    arg = node.args[0]
                    key = _str(arg) or (consts.get(arg.id) if isinstance(arg, ast.Name) else None)
                    if key:
                        keys.setdefault(key, node.lineno)
            if asked:
                continue
            for key, line in keys.items():
                shipped = defaults.get(key, _NO_SUCH_KEY)
                if shipped is _NO_SUCH_KEY or isinstance(shipped, UNREADABLE.__class__):
                    # Not a key we ship, or a default we could not evaluate.
                    # Guessing at a value this checker cannot see is how a hard
                    # rule starts failing builds over its own arithmetic.
                    continue
                if shipped is not None and not shipped:
                    # A falsy literal default. The env leg beneath it is
                    # genuinely reachable — that is `H06`'s whole distinction —
                    # and a key that is not tri-state has nothing to flatten.
                    continue
                for env, env_line in envs.items():
                    stem = env[len("PANTHEON_"):] if env.startswith("PANTHEON_") else env
                    if stem.lower() != key:
                        continue
                    if shipped is None:
                        # `B90`. A key shipping `None` is tri-state on purpose:
                        # absent, yes, and **no**. `get_setting` merges the
                        # default on every read, so `bool(get_setting(K, False))`
                        # collapses the stored `no` back into the absence it was
                        # added to be distinguishable from — which is the exact
                        # line that let `PANTHEON_ALLOW_MODEL_DOWNLOAD=1` beat a
                        # `Law 16` gate an operator had turned off. Measured
                        # 2026-09-15: stored `False`, effective `True`.
                        found.append(
                            f"{rel}:{env_line} {env} is read beside {key} (:{line}), "
                            f"which ships None because its stored False has to mean "
                            f"*no* — get_setting flattens that back to absence; use "
                            f"settings.env_backed_flag")
                    else:
                        found.append(
                            f"{rel}:{env_line} {env} is read beneath {key}, which ships "
                            f"{shipped!r} — get_setting merges DEFAULT_SETTINGS on "
                            f"every read (:{line}), so this line cannot run")
    return sorted(set(found))


def mixed_layers() -> list[str]:
    """One dict, some values env-backed and one read straight off settings."""
    found = []
    for rel, _source, tree in _scan_files():
        # `routes/email_helpers.py` spells it `_v = lambda k, e, d="": env_backed(...)`
        # and eleven values later that lambda is the only thing distinguishing the
        # ten fields that reach the environment from the one that does not.
        alias = {n.targets[0].id for n in ast.walk(tree)
                 if isinstance(n, ast.Assign) and len(n.targets) == 1
                 and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Lambda)
                 and any(isinstance(c, ast.Call) and _called(c) == "env_backed"
                         for c in ast.walk(n.value.body))}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            backed, raw = set(), []
            for value in node.values:
                for call in ast.walk(value):
                    if not isinstance(call, ast.Call):
                        continue
                    called = _called(call)
                    if called == "env_backed" and len(call.args) >= 3 and _str(call.args[1]):
                        backed.add(_str(call.args[1]))
                    elif called in alias and call.args and _str(call.args[0]):
                        backed.add(_str(call.args[0]))
                    elif called == "get" and call.args and _str(call.args[0]) \
                            and _settings_receiver(call):
                        raw.append((_str(call.args[0]), call.lineno))
            if not backed:
                continue
            for key, line in raw:
                if key in backed:
                    continue
                found.append(
                    f"{rel}:{line} {key} is read straight off settings while "
                    f"{len(backed)} siblings in the same dict go through env_backed — "
                    f"its environment layer is unreachable here and reachable elsewhere")
    return sorted(set(found))


def _env_derived(node, consts: dict) -> list[str]:
    """Environment names an expression subtree reads, resolving module consts."""
    names = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = _env_name_of(child, consts)
            if name:
                names.append(name)
        elif isinstance(child, ast.Subscript) and isinstance(child.value, ast.Attribute) \
                and child.value.attr == "environ":
            name = _str(child.slice) or (consts.get(child.slice.id)
                                         if isinstance(child.slice, ast.Name) else None)
            if name:
                names.append(name)
    return names


# `B91`. Every token any site in the tree accepted as yes or no on 2026-09-15.
# A comparison drawn wholly from this set is a truthiness rule; one that is not
# — `TERM == "dumb"`, `PANTHEON_SCRIPT_HOST in ("", "localhost", …)`, a duration,
# a hostname — is a different question and is none of this rule's business.
_TRUTH_TOKENS = {"1", "0", "true", "false", "yes", "no", "on", "off", "y", "n",
                 "t", "f", "enable", "disable", "enabled", "disabled",
                 # `""` is a member of three real off-lists in this tree —
                 # `not in ("0","false","no","off","")`. Leaving it out made the
                 # rule silently skip the whole comparison; a test caught it.
                 ""}
_SPELLING_EXEMPT = re.compile(r"env-spelling:\s*(.+)")
_FLAG_EXEMPT = re.compile(r"flag-spelling:\s*(.+)")

# The eight words that are only ever a yes or a no. `_TRUTH_TOKENS` is wider —
# it holds `enable`, `disabled`, `y`, `t` and the empty string, because real
# off-lists in this tree contain them — and that width is right for deciding
# whether a comparison *drawn entirely from the vocabulary* is a truthiness
# rule. It is wrong for deciding whether a comparison is one at all: `action ==
# "enable"` and `provider == "disabled"` are enum tests, and there are 14 of
# them. A comparison has to touch one of these eight to be a yes/no question.
_CORE_TRUTH_TOKENS = {"1", "0", "true", "false", "yes", "no", "on", "off"}


def _blank_only(values) -> bool:
    """A comparison against nothing but the empty string is a blank check.

    `B98`. `""` is in `_TRUTH_TOKENS` because three real off-lists spell
    `not in ("0","false","no","off","")`, and leaving it out made the SPELLING
    rule skip those comparisons whole. But `x == ""` on its own is asking *did
    anyone set this*, which is the question `env_truthy` answers with `None` —
    a different question from *does this mean yes*. There are 44 of them in the
    tree and `companion/pairing.py:118` is one the dataflow pass reaches, so
    without this the pass would have arrived with its own false positive.
    """
    return {v.strip() for v in values} == {""}


def _truthiness_values(node):
    """The literal strings a `Compare` tests against, if it is a yes/no test."""
    if not (isinstance(node, ast.Compare) and len(node.ops) == 1):
        return None
    op, right = node.ops[0], node.comparators[0]
    if isinstance(op, (ast.Eq, ast.NotEq)):
        values = [_str(right)] if _str(right) is not None else []
    elif isinstance(op, (ast.In, ast.NotIn)) and isinstance(
            right, (ast.Tuple, ast.Set, ast.List)):
        values = [_str(e) for e in right.elts]
    else:
        return None
    if not values or any(v is None for v in values):
        return None
    if not all(v.strip().lower() in _TRUTH_TOKENS for v in values):
        return None
    if _blank_only(values):
        return None
    return values


@lru_cache(maxsize=None)
def _own_body(scope):
    """Nodes belonging to `scope` itself, stopping at a nested scope.

    Memoised (`B220`). Pure, and AST nodes hash by identity while `_parsed`
    holds the tree alive, so the cache is exact rather than approximate. It is
    worth having because `_origin_map` walks the same scope three times and
    every rule below walks it again: 1,900 calls became 240.

    `ast.walk` does not stop, and that is the whole reason the first draft of
    this pass reported 104 findings against 9 real ones: walking a module
    reaches every local in every function in the file, so one namespace held
    every name and `unit in ("hour","hr")` inherited `PANTHEON_FALLBACK_OWNER`
    from twelve hundred lines away. A dataflow pass that does not respect scope
    is not a dataflow pass.
    """
    out = []
    nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

    def walk(node, top=False):
        for child in ast.iter_child_nodes(node):
            if not top and isinstance(child, nested):
                continue
            out.append(child)
            if not isinstance(child, nested):
                walk(child)
    walk(scope, top=True)
    return out


_REQUEST_PARAM_CALLS = {"Form", "Query", "Body", "Header", "Path", "File", "Cookie"}
# The receivers whose `.get("x")` is a request field rather than any other dict.
# Spelled out rather than pattern-matched on the word "body": `body` and
# `form_data` are what this tree's routes call them, and a rule that guessed
# would start reading a mail body or a response body as a request.
_REQUEST_RECEIVERS = {"form_data", "body", "(body or {})", "form",
                      "request.query_params", "await request.json()"}


def _request_origin(node) -> bool:
    """Whether this expression reads a field off the incoming HTTP request."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "get" and node.args and _str(node.args[0]):
        try:
            return ast.unparse(node.func.value) in _REQUEST_RECEIVERS
        except Exception:
            return False
    return False


def _request_params(scope) -> set:
    """Parameter names a route declares as `Form(...)` / `Query(...)` / ….

    This is the other half of the HTTP boundary and the larger one: nine of the
    sixteen sites `B97` converted read a FastAPI parameter, not a dict.
    """
    if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return set()
    args = scope.args
    ordered = list(args.posonlyargs) + list(args.args)
    defaults = list(args.defaults)
    named = set()
    for arg, default in zip(ordered[len(ordered) - len(defaults):], defaults):
        if isinstance(default, ast.Call) and isinstance(default.func, ast.Name) \
                and default.func.id in _REQUEST_PARAM_CALLS:
            named.add(arg.arg)
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        if isinstance(default, ast.Call) and isinstance(default.func, ast.Name) \
                and default.func.id in _REQUEST_PARAM_CALLS:
            named.add(arg.arg)
    return named


def _is_environ(node) -> bool:
    """Whether this expression *is* the process environment mapping."""
    return isinstance(node, ast.Attribute) and node.attr == "environ"


def _environ_aliases(scope) -> set:
    """Local names bound to `os.environ` itself rather than to a value from it.

    `B98`, and the fourth shape of the same blind spot. `src/host_docker_access.py`
    writes `env = os.environ if environ is None else environ` and then
    `env.get(HOST_DOCKER_ENV_VAR, "").strip().lower() != "true"` — an
    environment boolean with its own narrow rule, invisible to every scan here,
    because the read is a `.get` on a *name* and the name is not `os.environ`.
    `literal_reads` misses it too, for the same reason and with the same
    consequence: it is a `FORBIDDEN.md` Part 2 control ("Host-Docker flag off")
    whose spelling nothing was checking.
    """
    names = set()
    for node in _own_body(scope):
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.value is not None:
            target, value = node.target.id, node.value
        if target is None:
            continue
        if any(_is_environ(child) for child in ast.walk(value)):
            names.add(target)
    return names


def _origins_in(expr, consts: dict, varmap: dict, environs: set = frozenset()) -> set:
    """Every boundary this expression's value came through.

    Returns a set of `("env", NAME)` and `("request", "")` pairs. One function
    for both, because the alternative is two walks that must agree about what
    counts as *derived from* — the shape `B20` named and `B91` inherited.
    """
    found = set()
    for child in ast.walk(expr):
        if isinstance(child, ast.Call):
            name = _env_name_of(child, consts)
            if name is None and isinstance(child.func, ast.Attribute) \
                    and child.func.attr in ("get", "pop") \
                    and isinstance(child.func.value, ast.Name) \
                    and child.func.value.id in environs and child.args:
                arg = child.args[0]
                name = _str(arg) or (consts.get(arg.id) if isinstance(arg, ast.Name) else None)
            if name:
                found.add(("env", name))
            elif _request_origin(child):
                found.add(("request", ""))
        elif isinstance(child, ast.Subscript) and isinstance(child.value, ast.Attribute) \
                and child.value.attr == "environ":
            name = _str(child.slice) or (consts.get(child.slice.id)
                                         if isinstance(child.slice, ast.Name) else None)
            if name:
                found.add(("env", name))
        elif isinstance(child, ast.Name) and child.id in varmap \
                and child.id not in ("__lines__", "__environs__"):
            found |= varmap[child.id]
    return found


def _read_lines(expr, origins: dict) -> tuple:
    """The lines the names in `expr` were read on, for the hold lookup."""
    lines = origins.get("__lines__", {})
    return tuple(lines[child.id] for child in ast.walk(expr)
                 if isinstance(child, ast.Name) and child.id in lines)


def _origin_map(scope, consts: dict, seed: dict) -> dict:
    """Local name → the boundaries its value came through, for one scope.

    `B98`. The one pass all the rules below share, and the answer to the blind
    spot `B20` stated for UNREACHABLE and MIXED and `B91` inherited for
    SPELLING: those rules see one scope, one dict or one comparison at a time,
    so `raw = os.environ.get(X)` in one statement and `raw.lower() == "true"` in
    the next was invisible to every one of them.

    Three passes rather than one because an assignment may name a value defined
    below it in source order inside a loop body; three is past the depth of
    anything in this tree and terminates regardless.
    """
    known = dict(seed)
    lines = dict(seed.get("__lines__", {}))
    environs = set(seed.get("__environs__", ())) | _environ_aliases(scope)
    known["__environs__"] = environs
    for name in _request_params(scope):
        known[name] = {("request", "")}
        lines[name] = scope.lineno
    for _ in range(3):
        for node in _own_body(scope):
            target = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                target, value = node.targets[0].id, node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                    and node.value is not None:
                target, value = node.target.id, node.value
            elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
                target, value = node.target.id, node.value
            if target is None:
                continue
            origins = _origins_in(value, consts, known, environs)
            if origins:
                known[target] = known.get(target, set()) | origins
                lines.setdefault(target, node.lineno)
    known["__lines__"] = lines
    return known


def _scopes_with_origins(tree, consts: dict):
    """`(scope, origin map)` for the module and every function in it.

    The map carries a `"__lines__"` entry: name → the line the value was read
    on. `B98` needs it because the *reason* a site keeps its own rule is written
    beside the read, not beside the comparison — all nine `B91` holds are — and
    a rule that only looked above the comparison would report a site whose hold
    is two lines up and call the exemption missing.
    """
    module_map = _origin_map(tree, consts, {})
    yield tree, module_map
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node, _origin_map(node, consts, module_map)


@lru_cache(maxsize=None)
def _origins_for(rel: str) -> tuple:
    """`_scopes_with_origins` for one file, built once per process.

    `B220`. SPELLING, BOUNDARY and VOCABULARY each asked for the same file's
    origin maps and each rebuilt them: three identical passes over every scope
    in the tree. The maps are read and never written — `_origins_in` and
    `_read_lines` only look things up — so sharing one copy between the three
    rules is the same answer computed once.
    """
    parsed = _parsed(rel)
    if parsed is None:
        return ()
    tree = parsed[1]
    return tuple(_scopes_with_origins(tree, _module_consts(tree)))


def _held(lines, lineno: int, pattern, *also: int) -> bool:
    """Whether a `# <kind>-spelling:` reason sits on or above any of these lines.

    Walks up through the contiguous comment block rather than a fixed window:
    the reasons these sites are held run to five and six lines, and a window
    sized to today's longest one is a trap for tomorrow's. `also` carries the
    line the compared value was *read* on, which is where `B91` put every one of
    its nine reasons.
    """
    for start in (lineno,) + also:
        if start is None:
            continue
        index = start - 1
        while index >= 0 and (lines[index].lstrip().startswith("#") or index == start - 1):
            if pattern.search(lines[index]):
                return True
            index -= 1
    return False



def spellings() -> list[str]:
    """Environment truthiness spelled inline instead of read from `env_flags`.

    `B91`. Measured 2026-09-15 by this same walk: **38 environment booleans, 10
    incompatible rules**. `PANTHEON_STARTUP_WARMUPS=1` was on and
    `IMAP_STARTTLS=1` was off in one process; `AUTH_ENABLED=0` left auth
    enabled; `CLEANUP_ENABLED=" true"` was off because one site of the 38 never
    called `.strip()`. Nothing errored and `.env.example` documented none of it.

    A site may keep its own rule by saying so — `# env-spelling: <reason>` on the
    line or in the three above it. The exemption carries the reason **at the
    site** rather than in a list here, for the same reason `NOT_OURS` makes each
    entry say whose it is: a list of names in a checker is a list nobody reads
    next to the code it is about. Hard rule, max 0 unexempted.

    **`B98` gave it the dataflow pass it was blind without**, and the blindness
    was measurable: this rule saw 8 sites while `exempt_spellings` counted **9**
    holds, and the ninth — `routes/auth_routes.py:110`, `SECURE_COOKIES` — was
    an exemption on a site the rule could not see. It reads
    `configured = os.getenv("SECURE_COOKIES", ...)` in one statement and
    `configured in ("true","false")` in the next, and a rule that sees one
    comparison at a time sees neither the variable nor the read. The exemption
    was decoration: deleting it would have failed nothing. It is load-bearing
    now.
    """
    found = []
    for rel, source, tree in _scan_files():
        if rel == "src/env_flags.py":
            continue
        lines = source.splitlines()
        consts = _module_consts(tree)
        seen = set()
        for scope, origins in _origins_for(rel):
            for node in _own_body(scope):
                values = _truthiness_values(node)
                if values is None:
                    continue
                names = sorted({n for kind, n in _origins_in(
                    node.left, consts, origins, origins.get("__environs__", set()))
                    if kind == "env"})
                if not names:
                    continue
                if (node.lineno, tuple(values)) in seen:
                    continue
                seen.add((node.lineno, tuple(values)))
                read_at = _read_lines(node.left, origins)
                # Walk up through the contiguous comment block rather than a
                # fixed window: the reasons these sites are held run to five and
                # six lines and a window sized to today's longest one is a trap
                # for tomorrow's.
                if _held(lines, node.lineno, _SPELLING_EXEMPT, *read_at):
                    continue
                found.append(
                    f"{rel}:{node.lineno} {'/'.join(names)} is judged by an "
                    f"inline {sorted(values)} — call env_flags.env_flag, or say why not "
                    f"with `# env-spelling: <reason>`")
    return sorted(set(found))


# The one function per boundary that owns *what did this string mean by yes*.
# `B97`. Each is the rule for exactly one producer, and they are deliberately
# not the same rule: an operator types an environment variable, our own
# JavaScript sends an HTTP field, a model writes a tool argument, and a person
# edits skill frontmatter. The trust differs and so does the strictness.
BOUNDARY_OWNERS = {
    "environment": "src/env_flags.py:env_flag / env_truthy",
    "HTTP request field": "src/env_flags.py:request_flag / request_truthy",
    "model tool argument": "src/env_flags.py:tool_arg_truthy",
    "skill frontmatter": "services/memory/skill_format.py:_parse_scalar",
}
# Sites whose yes/no word is somebody else's convention, and whose it is.
#
# `B153`. `B97` named four boundaries and gave each exactly one owner, and the
# count that produced those four turned up a fifth producer with one site and
# no owner: third-party API JSON. One site is not a vocabulary, and inventing a
# fifth rule for it would be `Law 14` — what was missing is the written answer
# to *whose convention is this*, which is what `NOT_OURS` records for `PATH`
# and what the hold at `core/database.py:112` records for SQLAlchemy.
#
# Keyed by `(file, function)` rather than by line, because a line number in a
# register rots the first time somebody adds an import. Checked rather than
# written down: `stale_foreign_producers` fails the run when a registered site
# no longer reads a yes/no word at all, for the same reason `NOT_OURS` fails
# when it names a variable nothing reads any more — an exemption that outlives
# its call site hides the next one that needs looking at (`B98`).
FOREIGN_PRODUCERS = {
    ("core/database.py", "_sqlite_db_path"):
        "SQLAlchemy — `?uri=true` is its own spelling in a connection URL",
    ("services/hwfit/image_models.py", "_variant_score"):
        "huggingface.co's model-search API — `private` is a JSON boolean, "
        "decoded to a Python bool by json.loads before this line reads it",
}
# The functions allowed to *contain* a yes/no vocabulary. Everything else that
# does is a fourth rule at a boundary that already has one, which is the thing
# `B97` exists to stop from happening a fifth time.
_OWNER_FUNCTIONS = {
    ("src/env_flags.py", "env_truthy"),
    ("src/env_flags.py", "env_flag"),
    ("src/env_flags.py", "request_truthy"),
    ("src/env_flags.py", "request_flag"),
    ("src/env_flags.py", "tool_arg_truthy"),
    ("services/memory/skill_format.py", "_parse_scalar"),
}


def boundaries() -> list[str]:
    """An HTTP request field judged inline instead of by `request_flag`.

    `B97`. Thirteen sites spelled this `str(x).lower() == "true"`, three more
    went through `routes/model_routes._truthy` with a wider set, and one more
    through `tool_policy.tool_toggle_enabled` with a narrower one — three
    answers to one question, at one boundary, with neither private helper
    reachable from the other's callers. `plan_mode=1` from a form post meant
    *no* while `plan_mode=true` meant yes, on a safety mode.

    Built on `B98`'s dataflow pass rather than on a fifth rule of its own
    (`Law 13`), because the question it asks — *where did this string come
    from* — is the question SPELLING asks, with a different answer. A request
    field is a FastAPI `Form(...)` / `Query(...)` parameter or a `.get` off the
    parsed form or body; nothing else is guessed at, because a rule that read
    any `body` as a request would start flagging mail bodies.

    Held the same way SPELLING is, with `# flag-spelling: <reason>`, and two
    sites are held: `allow_bash` and `tool_policy.tool_toggle_enabled` grant
    tools, and widening a gate is not the same act as honouring an intent.
    Hard rule, max 0 unexempted.
    """
    found = []
    for rel, source, tree in _scan_files():
        if rel == "src/env_flags.py":
            continue
        lines = source.splitlines()
        consts = _module_consts(tree)
        seen = set()
        for scope, origins in _origins_for(rel):
            for node in _own_body(scope):
                values = _truthiness_values(node)
                if values is None:
                    continue
                kinds = {k for k, _ in _origins_in(
                    node.left, consts, origins, origins.get("__environs__", set()))}
                if "request" not in kinds or "env" in kinds:
                    continue
                if (node.lineno, tuple(values)) in seen:
                    continue
                seen.add((node.lineno, tuple(values)))
                if _held(lines, node.lineno, _FLAG_EXEMPT,
                         *_read_lines(node.left, origins)):
                    continue
                found.append(
                    f"{rel}:{node.lineno} an HTTP request field is judged by an "
                    f"inline {sorted(values)} — call env_flags.request_flag, or say "
                    f"why not with `# flag-spelling: <reason>`")
    return sorted(set(found))


def inert_reads() -> list[str]:
    """A variable read into a module-level name that nothing ever reads back.

    `B150`, found while closing `B96`. `routes/calendar_routes.py` computed
    `_SINGLE_USER_MODE = os.environ.get("PANTHEON_SINGLE_USER", "1") != "0"` at
    import and referenced it **nowhere in the tree**, so the documented
    `PANTHEON_SINGLE_USER=0` did nothing at all: every unauthenticated calendar
    request was written under `PANTHEON_FALLBACK_OWNER` whatever the operator
    set, and the comment three lines above told them to set it. The row it was
    found under thought the switch was *narrow*. It was inert.

    **This is the one shape none of the other rules can have an opinion about**,
    and it is worth saying why. UNDECLARED asks whether the variable is
    documented — it was. UNREFERENCED asks whether anything mentions it — the
    assignment does. UNREACHABLE asks whether the line beneath it can execute —
    it executes. SPELLING asks what the comparison means — it meant what it
    said. Every rule here answers a question about the read, and none of them
    asks whether the *answer* is used.

    Module scope only, and deliberately: a local computed and dropped inside a
    function is a dead store any linter finds, while a module constant is the
    shape that looks configured from the outside. Measured 2026-09-15 across
    every tracked `.py`: **one**, and it is the one above.
    """
    found = []
    for rel, _source, tree in _scan_files():
        consts = _module_consts(tree)
        environs = _environ_aliases(tree)
        assigned = {}
        for node in _own_body(tree):
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)):
                continue
            names = sorted({n for kind, n in _origins_in(node.value, consts, {}, environs)
                            if kind == "env"})
            if names:
                assigned.setdefault(node.targets[0].id, (node.lineno, names))
        if not assigned:
            continue
        used = {n.id for n in ast.walk(tree)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for name, (line, names) in assigned.items():
            if name in used or _referenced_elsewhere(rel, name):
                continue
            found.append(
                f"{rel}:{line} {name} is built from {'/'.join(names)} and nothing "
                f"ever reads it — the variable is documented, declared and inert")
    return sorted(set(found))


@lru_cache(maxsize=None)
def _referenced_elsewhere(rel: str, name: str) -> bool:
    """Whether any OTHER tracked file mentions this name."""
    out = subprocess.run(["git", "grep", "-l", "-w", name], cwd=ROOT,
                         capture_output=True, text=True)
    return any(line and line != rel for line in out.stdout.splitlines())


def rival_vocabularies() -> list[str]:
    """A function that is itself a yes/no rule and is not one of the owners.

    `B97`'s *fails on a fourth*, and the only one of these rules that holds at
    the boundaries whose producer cannot be seen from the source. A model tool
    argument and a line of skill frontmatter arrive as plain dict values — there
    is nothing in the AST that distinguishes them from any other string, so no
    dataflow pass can find the site. What it can find is the **helper**: every
    one of the five vocabularies `B97` counted was written as a small function
    or a lambda whose whole job was to answer *is this yes*, and the next one
    will be too. `routes/model_routes._truthy` and
    `src/tool_policy.tool_toggle_enabled` were exactly that shape.

    A function qualifies when it compares against words drawn from the yes/no
    vocabulary and at least one of the eight that are only ever yes or no —
    `action in ("enable","disable")` and `provider == "disabled"` are enum
    tests, there are 14 of them, and they are none of this rule's business.
    Hard rule, max 0 unexempted; `# flag-spelling:` holds a site that must keep
    its own, and says why at the line.
    """
    found = []
    for rel, source, tree in _scan_files():
        lines = source.splitlines()
        # `B220`. These two are functions of the *file*, and they were being
        # recomputed for every function in it — 27.4s of a 43s run, because a
        # module with sixty functions built sixty identical module-level origin
        # maps. Hoisted; the per-scope map below still takes the module map as
        # its seed, exactly as before, and `_origin_map` copies its seed rather
        # than mutating it, so the output is unchanged.
        consts = _module_consts(tree)
        # `_origins_for` yields the module scope first and then every function,
        # which is the set this loop used to build for itself — one
        # `_origin_map(tree, ...)` per function, sixty times in a sixty-function
        # module. That was 27.4s of a 43.6s run (`B220`).
        for scope, origins in _origins_for(rel)[1:]:
            if (rel, scope.name) in _OWNER_FUNCTIONS:
                continue
            for node in _own_body(scope):
                values = _truthiness_values(node)
                if values is None:
                    continue
                if not {v.strip().lower() for v in values} & _CORE_TRUTH_TOKENS:
                    continue
                # **A vocabulary is a list.** One word is a spelling, not a
                # rule, and reading every `== "1"` in the tree as one is how a
                # checker becomes noise nobody reads: `auto_submitted != "no"`
                # is RFC 3834, `x-ratelimit-remaining == "0"` is a count, and
                # `level == "off"` is a SafeSearch setting. All three compare
                # against a word from the vocabulary and none of them is asking
                # what it means by yes. The rules that catch single spellings
                # are SPELLING and BOUNDARY, which know where the value came
                # from; this one catches the thing they cannot see — somebody
                # writing out a *set* of words, which is what all five of the
                # vocabularies `B97` counted looked like.
                if len({v.strip().lower() for v in values}) < 2:
                    continue
                # Already owned by a rule that knows the producer.
                if {k for k, _ in _origins_in(
                        node.left, consts, origins,
                        origins.get("__environs__", set()))}:
                    continue
                if _held(lines, node.lineno, _FLAG_EXEMPT) \
                        or _held(lines, node.lineno, _SPELLING_EXEMPT):
                    continue
                # A whole function held on its own rule — reported once, at the
                # hold, rather than again for every comparison inside it.
                if _held(lines, scope.lineno, _FLAG_EXEMPT):
                    continue
                found.append(
                    f"{rel}:{node.lineno} {scope.name}() is a yes/no rule of its own "
                    f"({sorted(values)}). Four boundaries have four owners "
                    f"({', '.join(sorted(BOUNDARY_OWNERS.values()))}) — call one, or "
                    f"say why not with `# flag-spelling: <reason>`")
    return sorted(set(found))


def stale_foreign_producers() -> list[str]:
    """Registered foreign producers whose site no longer reads a yes/no word.

    `B153`. The register is a claim about a line of somebody else's code as it
    appears in ours, and a claim nothing checks is the shape `B98` found: nine
    `# env-spelling:` holds against eight sites the rule could reach, so one
    exemption was decoration and deleting it would have failed no build. This
    asks the narrow question the register can answer — is the named function
    still there, and does it still compare against a yes/no word — and says so
    when the answer is no.
    """
    out = []
    for (rel, func), owner in sorted(FOREIGN_PRODUCERS.items()):
        parsed = _parsed(rel)
        if parsed is None:
            out.append(f"{rel}:{func} — {owner} (the file is gone or unparseable)")
            continue
        scopes = [n for n in ast.walk(parsed[1])
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.name == func]
        if not scopes:
            out.append(f"{rel}:{func} — {owner} (the function is gone)")
            continue
        if not any(_truthiness_values(node) is not None
                   for scope in scopes for node in _own_body(scope)):
            out.append(f"{rel}:{func} — {owner} (no yes/no comparison left here)")
    return out


def exempt_spellings(pattern=None) -> list[str]:
    """The `# env-spelling:` / `# flag-spelling:` holds, for `--list`.

    `B98`. This counted **9** while `spellings()` could only see **8**, and the
    gap was the finding: `routes/auth_routes.py:110` exempted a site the rule
    was blind to, so the exemption held nothing. Both numbers are printed for
    that reason — a held count larger than the rule's reach is the shape of an
    exemption that has stopped being load-bearing.
    """
    out = []
    pattern = pattern or _SPELLING_EXEMPT
    for rel, source, _tree in _scan_files():
        lines = source.splitlines()
        for lineno, line in enumerate(lines, 1):
            match = pattern.search(line)
            if match:
                out.append(f"{rel}:{lineno} {match.group(1).strip()}")
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    # `B98`. 74 while the real count was 72, and documenting PANTHEON_SINGLE_USER
    # in the switches block took it to 71: three names of slack, which is three
    # undocumented variables a future change could have added without anything saying
    # so. A ratchet left loose is where the next regression hides.
    ap.add_argument("--max", type=int, default=71,
                    help="ceiling for undeclared variables (may fall, never rise)")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    known = declared()
    reads = literal_reads()
    missing = sorted(set(reads) - set(known) - set(NOT_OURS))
    dead = unreferenced(known)
    stranded = unreachable(shipped_defaults())
    split = mixed_layers()
    spelled = spellings()
    crossed = boundaries()
    rivals = rival_vocabularies()
    inert = inert_reads()
    held = exempt_spellings()
    flag_held = exempt_spellings(_FLAG_EXEMPT)
    foreign_stale = stale_foreign_producers()

    print(f"env vars  read {len(reads)}  ·  declared {len(known)}  ·  "
          f"not ours {len(NOT_OURS)}  ·  UNDECLARED {len(missing)} (max {args.max})  ·  "
          f"UNREFERENCED {len(dead)} (max 0)  ·  UNREACHABLE {len(stranded)} (max 0)  ·  "
          f"MIXED {len(split)} (max 0)  ·  SPELLING {len(spelled)} (max 0, "
          f"{len(held)} held)  ·  BOUNDARY {len(crossed)} (max 0, {len(flag_held)} held)"
          f"  ·  VOCABULARY {len(rivals)} (max 0)  ·  INERT {len(inert)} (max 0)"
          f"  ·  FOREIGN {len(FOREIGN_PRODUCERS)} registered, "
          f"{len(foreign_stale)} stale (max 0)")

    failed = False
    if inert:
        failed = True
        print("\n  Read, and then dropped. A variable computed into a module name "
              "nothing reads back is documented, declared, referenced and inert — "
              "`PANTHEON_SINGLE_USER=0` did nothing for the life of the file "
              "(`B150`, found by `B96`):")
        for line in inert:
            print(f"    {line}")
    if foreign_stale:
        failed = True
        print("\n  A registered foreign producer whose site has moved on. The "
              "register answers *whose convention is this* for a yes/no word "
              "that is not one of the four boundaries (`B153`); an entry that "
              "outlives its call site hides the next producer that needs an "
              "owner:")
        for line in foreign_stale:
            print(f"    {line}")
    if crossed:
        failed = True
        print("\n  An HTTP request field judged by an inline rule. `plan_mode=1` meant "
              "*no* while `plan_mode=true` meant yes, at thirteen sites with no shared "
              "rule between them (`B97`):")
        for line in crossed:
            print(f"    {line}")
    if rivals:
        failed = True
        print("\n  A fourth vocabulary. Four boundaries have four owners and each is "
              "written down; a new private `_truthy` is how the last five started "
              "(`B97`):")
        for line in rivals:
            print(f"    {line}")
    if spelled:
        failed = True
        print("\n  Environment truthiness spelled inline. Ten incompatible rules is "
              "how `PANTHEON_X=1` came to mean yes in one module and no in the next, "
              "with nothing to error and nothing to log (`B91`):")
        for line in spelled:
            print(f"    {line}")
    if stranded:
        failed = True
        print("\n  Read beside a settings key `get_setting` cannot answer for. The "
              "merge runs on every read, so a truthy shipped default makes the line "
              "below it dead (`H06`, `B20`) and a `None` one — the tri-state a "
              "stored `False` needs to mean *no* — is flattened back to absence "
              "(`B90`). Ask `setting_is_explicit`, `env_backed` or `env_backed_flag`:")
        for line in stranded:
            print(f"    {line}")
    if split:
        failed = True
        print("\n  One dict, two rules. A field left on `settings.get` beside fields "
              "that go through `env_backed` has an environment layer everywhere except "
              "here, and nothing in settings.json looks wrong (`H07`, `B20`):")
        for line in split:
            print(f"    {line}")
    if dead:
        failed = True
        print("\n  Declared in .env.example and used by nothing — an operator who sets "
              "one of these believes something changed:")
        for name in dead:
            print(f"    {name} (line {known[name]})")
    stale = sorted(set(NOT_OURS) - set(reads))
    if stale:
        failed = True
        print("\n  NOT_OURS names variables nothing reads any more. An exemption that "
              "outlives its call site hides the next one that needs looking at:")
        for name in stale:
            print(f"    {name} — {NOT_OURS[name]}")
    if len(missing) > args.max:
        failed = True
        print(f"\n  The undeclared count rose from {args.max} to {len(missing)}. "
              "This ratchet only comes down: document the new variable in "
              ".env.example, or add it to NOT_OURS with whose it is.")
        for name in missing[args.max:]:
            print(f"    {name}  ({sorted(reads[name])[0]})")
    if args.list:
        print()
        for name in missing:
            print(f"  {name:44} {sorted(reads[name])[0]}")
        print("\n  Sites keeping their own environment truthiness rule, and why (`B91`):")
        for line in held:
            print(f"    {line}")
        print("\n  Sites keeping their own request/tool truthiness rule, and why (`B97`):")
        for line in flag_held:
            print(f"    {line}")
        print("\n  The four boundaries and who owns each (`B97`):")
        for boundary, owner in BOUNDARY_OWNERS.items():
            print(f"    {boundary:22} {owner}")
        print("\n  Yes/no words that are somebody else's convention, and whose "
              "(`B153`):")
        for (rel, func), owner in sorted(FOREIGN_PRODUCERS.items()):
            print(f"    {rel}:{func}()")
            print(f"      {owner}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
