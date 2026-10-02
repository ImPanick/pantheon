# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B357`/`B358` — the security documents say what the repository actually does.

Two rows, one failure mode: a document that was true when it was written and is
not true now, in the part of the repository a stranger reads first.

**`B358`.** `SECURITY.md` told its reader that `pip-audit` scans
`requirements.txt` and `requirements-optional.txt`, is advisory only, and
cannot see `basicsr` — the one dependency this project ships with a known,
unfixable advisory. All three were true when that section was written and none
of them survived `B320`/`B322`: the audit is a blocking job, it reads every
`requirements*.txt`, and it reads the three Real-ESRGAN wheel pins out of
`docker/build-realesrgan-wheels.sh`, which is exactly where `basicsr` enters. A
security policy that understates its own coverage is not a harmless stale
sentence — it is the document a reader uses to decide what they still have to
check themselves.

**`B357`.** Three documents route vulnerability reporters to
`https://github.com/ImPanick/pantheon/security/advisories/new`. That URL only
works when **Private vulnerability reporting** is switched on in the
repository's settings, which is a setting and not a commit, and which nobody
has confirmed is on — `api.github.com` is unreachable from the worktree and the
repository was not public when the row was filed. **Nothing here claims it is
enabled.** What is asserted is the part that is in this repository's hands: a
document that sends a reporter to that URL says what to do when it 404s, and
the setting is on the pre-publication checklist in `docs/security-ci.md` rather
than living only in a roadmap row nobody will read again.

**Closed 2026-10-02.** The setting was measured from the owner's machine —
`gh api repos/ImPanick/pantheon/private-vulnerability-reporting` answered
`{"enabled": true}` — and the documents now say it is on. That is a claim
about a repository setting this suite cannot reach, so what is asserted is its
shape: the reading carries its date and the command that takes it, the command
asks about the same repository the documents send reporters to, and every
fallback is still there for the day the setting is switched off.

Both are cross-artefact checks — the claim in the prose against the thing the
prose is about, read out of the real workflow, the real register and the real
audit script. A test that read only the document would agree with whatever the
document said.
"""
import importlib.util
import json
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent

ADVISORY_URL = "https://github.com/ImPanick/pantheon/security/advisories/new"


def _tracked_text_files() -> list:
    """Every tracked file git will show us, as paths."""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=str(ROOT),
                         capture_output=True, text=True, check=True).stdout
    return [ROOT / name for name in out.split("\0") if name]


@pytest.fixture(scope="module")
def audit_module():
    """`.pantheon/audit-dependencies.py`, imported and callable.

    The claim under test is about what that script reads, so the answer comes
    from the script rather than from a second reading of the shell variable it
    reads (`Law 20`).
    """
    path = ROOT / ".pantheon" / "audit-dependencies.py"
    spec = importlib.util.spec_from_file_location("pantheon_audit_dependencies", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def security_md() -> str:
    return (ROOT / "SECURITY.md").read_text(encoding="utf-8")


# ── `B358` — what the audit reads, and what the policy says it reads ──────────

def test_the_audit_reads_the_package_the_policy_calls_an_accepted_risk(audit_module):
    """The premise. `basicsr` enters through a shell script and a `--no-deps`
    install, so it is in no requirements file; `realesrgan_pins()` is what
    puts it in front of the scanner anyway."""
    pins = audit_module.realesrgan_pins()
    assert "basicsr==1.4.2" in pins, pins
    assert len(pins) == 3, pins  # basicsr, gfpgan, facexlib


def test_the_policy_names_every_file_the_audit_actually_reads(audit_module, security_md):
    """`B358`'s correction, derived rather than transcribed.

    Fails on the tree as it stood: `SECURITY.md` named two requirements files
    of the three and did not mention the wheel script at all, so a reader
    counting on the sentence would have believed `requirements-image.txt` was
    unscanned.
    """
    audited = sorted(p.name for p in ROOT.glob("requirements*.txt"))
    assert len(audited) >= 3, audited
    missing = [name for name in audited if name not in security_md]
    assert not missing, f"SECURITY.md does not name what the audit reads: {missing}"
    assert audit_module.WHEEL_SCRIPT in security_md, audit_module.WHEEL_SCRIPT


def test_the_policy_does_not_understate_the_audit_as_advisory(security_md):
    """The workflow calls the job blocking; the policy has to agree.

    Fails on the tree as it stood: `SECURITY.md` read *"Advisory only — it
    reports, it does not block"* for a job named `pip-audit (blocking)` that
    fails on any finding without an entry in the register.
    """
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "dependency-review.yml").read_text(encoding="utf-8"))
    job_name = workflow["jobs"]["pip-audit"]["name"]
    assert "blocking" in job_name.lower(), job_name

    line = next((l for l in security_md.splitlines()
                 if l.lstrip().startswith("- **pip-audit**")), None)
    assert line, "SECURITY.md no longer describes pip-audit at all"
    assert "block" in line.lower(), line
    assert "advisory only" not in line.lower(), line
    assert ".pantheon/dependency-advisories.toml" in line, line


def test_the_accepted_risk_in_the_policy_is_the_one_in_the_register(security_md):
    """One accepted risk, described in two places, and they have to be the same
    one. The register is what the blocking job consults; `SECURITY.md` is what
    a reader consults."""
    register = tomllib.loads(
        (ROOT / ".pantheon" / "dependency-advisories.toml").read_text(encoding="utf-8"))
    entries = register["advisory"]
    assert len(entries) == 1, [e["id"] for e in entries]
    entry = entries[0]
    assert f"`{entry['package']}` {entry['version']}" in security_md, entry["package"]
    assert entry["declared_in"] in security_md, entry["declared_in"]
    for alias in entry["aliases"]:
        assert alias in security_md, alias


def test_a_bump_of_the_pinned_version_is_caught_by_the_offline_gate():
    """`B358`'s other half: noticed by something other than a person
    remembering.

    `check-pins.py` refuses a suppression whose `declared_in` file does not pin
    that package at that version, so bumping `basicsr` in the wheel script
    turns the gate red until somebody re-reads the advisory. Driven, not read:
    the checker is run against the real tree.
    """
    result = subprocess.run(["python3", str(ROOT / ".pantheon" / "check-pins.py")],
                            cwd=str(ROOT), capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "accepted risk" in result.stdout, result.stdout


# ── `B357` — the private-reporting route degrades when it is switched off ─────

def test_every_document_that_routes_a_reporter_there_says_what_if_it_404s():
    """`B357`, for every document rather than the three the row counted.

    The advisory URL works only when the repository setting is on. This does
    not and cannot assert that it is — it is a setting, only the owner can flip
    it, and `api.github.com` is not reachable from here. What it asserts is
    that a reporter who clicks through to a 404 is not left with nowhere to go:
    each document either says so itself or points at one in this repository
    that does.

    Derived from the tree (`Law 13`), because the next document to carry this
    link is the one that will carry it without a fallback. Fails on the tree as
    it stood: `.github/ISSUE_TEMPLATE/config.yml` had neither.
    """
    carriers = {}
    for path in _tracked_text_files():
        if path.suffix.lower() not in (".md", ".yml", ".yaml", ".html", ".py"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if ADVISORY_URL in text:
            carriers[path.relative_to(ROOT).as_posix()] = text

    # Not vacuous, and the three the row named are among them.
    assert len(carriers) >= 3, sorted(carriers)
    for required in ("SECURITY.md", "CODE_OF_CONDUCT.md",
                     ".github/ISSUE_TEMPLATE/config.yml"):
        assert required in carriers, sorted(carriers)

    dead_ends = []
    for name, text in sorted(carriers.items()):
        says_itself = "404" in text
        points_at_one = name != "SECURITY.md" and "SECURITY.md" in text
        if not (says_itself or points_at_one):
            dead_ends.append(name)
    assert not dead_ends, (
        "these send a reporter to a URL that 404s when private vulnerability "
        f"reporting is off, and say nothing about it: {dead_ends}")


def test_the_chooser_entry_carries_the_fallback_in_its_own_words():
    """The one that cannot borrow `SECURITY.md`'s.

    GitHub renders `contact_links[].about` as plain text — no link comes out of
    it — and the chooser is what a person sees *before* they reach "New issue",
    which is the moment this link exists to intercept. So its fallback has to
    be in the sentence itself. Parsed as YAML rather than grepped, because what
    GitHub reads is the parsed value.
    """
    config = yaml.safe_load(
        (ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml").read_text(encoding="utf-8"))
    entry = next(link for link in config["contact_links"]
                 if link["url"] == ADVISORY_URL)
    about = entry["about"]
    assert "404" in about, about
    # And it says what to do, not merely that it may fail.
    assert "public issue" in about.lower(), about
    # Public issues stay off, so the chooser is the only place this can be said.
    assert config["blank_issues_enabled"] is False, config


def test_enabling_it_is_on_the_one_time_settings_checklist():
    """`B357`'s other half: the fix is a repository setting, and a setting that
    lives only in a roadmap row is a setting nobody turns on.

    Fails on the tree as it stood: `docs/security-ci.md`'s "One-time settings
    to turn on" section had two items and neither was this one.
    """
    doc = (ROOT / "docs" / "security-ci.md").read_text(encoding="utf-8")
    section = doc.split("## One-time settings to turn on", 1)
    assert len(section) == 2, "the one-time settings section is gone"
    body = section[1].split("\n## ", 1)[0]
    lowered = body.lower()
    # Named in a **heading**, and not only mentioned in prose further down. A
    # checklist is read by its headings — a step whose title says something
    # else is a step nobody does, which a first version of this test let
    # through and a mutation caught.
    headings = [line for line in body.splitlines() if line.startswith("### ")]
    assert len(headings) >= 3, headings
    assert any("private vulnerability reporting" in h.lower() for h in headings), headings
    # The repository being public is the part that had a deadline; since
    # 2026-10-02 the section says the deadline is past and the setting is on.
    assert "public" in lowered, body[-1500:]
    assert "these two settings" not in lowered, body[:400]


def test_the_setting_is_recorded_as_a_reading_of_the_repository_reporters_are_sent_to():
    """`B357`, closed: the checklist says the setting is on, and says it the
    way a measurement is said — dated, with the value read and the command
    that reads it — so the next person can take the reading again instead of
    trusting the sentence.

    Cross-artefact where it can be: the command asks about the repository
    named in the advisory URL every reporter is sent to. A reading of a
    different repository — a fork's, after a rename — would be a true reading
    of the wrong thing. Fails on the tree as it stood: the section said *"Do
    this before the repository goes public"* and nobody had read the setting.
    """
    doc = (ROOT / "docs" / "security-ci.md").read_text(encoding="utf-8")
    section = doc.split("### 3. Turn on private vulnerability reporting", 1)[1]
    section = section.split("\n## ", 1)[0]
    command = re.search(
        r"gh api repos/([\w.-]+)/([\w.-]+)/private-vulnerability-reporting", section)
    assert command, section[:800]
    reported_to = re.match(r"https://github\.com/([\w.-]+)/([\w.-]+)/security/", ADVISORY_URL)
    assert command.groups() == reported_to.groups(), (command.groups(), reported_to.groups())
    reading = section[command.end():].lstrip().splitlines()[0]
    assert json.loads(reading) == {"enabled": True}, reading
    assert re.search(r"[Mm]easured on (\d{4}-\d{2}-\d{2})", section), section[:800]


def test_the_policy_says_it_is_on_and_keeps_the_fallback(security_md):
    """`SECURITY.md` is the document a reporter reads first: it says the route
    is open as of a date, and keeps the one sentence a reporter may put in a
    public issue if it is ever closed. Fails on the tree as it stood: the
    policy said private reporting *"has not been turned on for this
    repository yet"*, which stopped being true on 2026-10-02."""
    reporting = security_md.split("## Reporting a Vulnerability", 1)[1].split("\n### ", 1)[0]
    assert "has not been turned on for this repository yet" not in reporting
    on = re.search(r"Private reporting is on for this repository \(checked (\d{4}-\d{2}-\d{2})",
                   reporting)
    assert on, reporting[:1200]
    assert "404" in reporting
    assert "please enable private vulnerability reporting" in reporting


# ── `B452` — the version a reporter is told to quote ─────────────────────────

def _supported_versions(security_md: str) -> list:
    """The *Supported Versions* section's paragraphs, minus the italic history
    notes — a note quoting what the section used to say is the record, not the
    claim (`Law 20`'s `H02`)."""
    section = security_md.split("## Supported Versions", 1)[1].split("\n## ", 1)[0]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", section) if p.strip()]
    return [p for p in paragraphs if not re.match(r"\*(?!\*)", p)]


def _get_version() -> dict:
    """`GET /api/version`, called. The handler is cut out of `app.py` by its own
    AST node — after checking the decorator really routes that path — and run,
    so the answer is the route's rather than a second reading of the constant
    behind it (`Law 20`). Importing `app.py` whole would start the app."""
    import ast
    import asyncio
    import sys

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    routed = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
              and any(isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "get"
                      and d.args and ast.literal_eval(d.args[0]) == "/api/version"
                      for d in n.decorator_list)]
    assert len(routed) == 1, [n.name for n in routed]
    handler = routed[0]
    handler.decorator_list = []
    namespace = {}
    exec(compile(ast.Module(body=[handler], type_ignores=[]), "app.py", "exec"), namespace)
    return asyncio.run(namespace[handler.name]())


def test_the_policy_names_what_the_version_route_returns(security_md):
    """`B452`'s `Verify:` first clause. The answer is taken from the route, and
    the policy has to print that answer verbatim — so cutting a release that
    moves `APP_VERSION` without this page fails here. Fails on the tree as it
    stood: the policy never mentioned `/api/version`."""
    answer = _get_version()
    assert set(answer) == {"version"} and answer["version"], answer
    which = next((p for p in _supported_versions(security_md)
                  if "Which version am I running?" in p), None)
    assert which, _supported_versions(security_md)
    assert "`GET /api/version`" in which, which
    assert json.dumps(answer) in which, (json.dumps(answer), which)


def _tag_statement_problem(tags: list, security_md: str):
    """None when the policy's word on tags agrees with `tags`, else why not."""
    claims_none = [p for p in _supported_versions(security_md)
                   if re.search(r"no tagged release|None exist yet", p)]
    if tags and claims_none:
        return f"tags {tags} exist and the policy says none do: {claims_none}"
    if not tags and not claims_none:
        return "no release is tagged and the policy does not say so"
    return None


def test_the_policy_says_whether_a_release_is_tagged(security_md):
    """`B452`'s second clause, against the repository rather than the prose:
    if a `v*` tag exists, the policy may not say none does, and if none does it
    has to say so. A clone without tags checks the second half; CI's full
    checkout checks the first the day a tag is pushed — and the next test
    drives that half here, without creating a tag every worktree would share."""
    tags = subprocess.run(["git", "tag", "-l", "v*"], cwd=str(ROOT),
                          capture_output=True, text=True, check=True).stdout.split()
    assert _tag_statement_problem(tags, security_md) is None


def test_a_cut_tag_makes_the_policy_wrong_until_it_is_edited(security_md):
    """The day `v0.1.0` exists, *"None exist yet"* is false — and this says so."""
    problem = _tag_statement_problem(["v0.1.0"], security_md)
    assert problem and "the policy says none do" in problem, problem


def test_the_policy_does_not_call_the_commit_the_only_identifier(security_md):
    """`B452`'s third clause. The present-tense claim is refused anywhere in
    the file; the dated note recording that it was once made is not a claim.
    And the changelog the section points at has a version heading, so the
    section may not say it has nothing but `[Unreleased]`. Fails on the tree as
    it stood, on both counts."""
    assert not re.search(r"is the only version identifier|only version identifier this project has",
                         security_md)
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(r"^## \[\d+\.\d+\.\d+\] — \d{4}-\d{2}-\d{2}\s*$", changelog, re.M)
    assert not [p for p in _supported_versions(security_md) if "and nothing else" in p]


# ── `D-2026-10-02-03` — the repository is public ─────────────────────────────

# Present tense only. A dated note recording what a page said while the
# repository was private ("…before the repository was public…") is the record
# and stays (`Law 1`); a sentence saying it IS private, or is about to stop
# being, is false since the owner's measurement of 2026-10-02.
_STILL_PRIVATE = re.compile(
    r"(?:this|the) (?:repository|repo) is (?:still )?private"
    r"|(?:is|are) not (?:yet )?public(?: yet)?|\bnot yet public"
    r"|before\W*(?:the|this) repository (?:goes|is) public"
    r"|private repo \(today\)"
    r"|making this repository public"
    r"|(?:has not been|not) (?:turned on|enabled) (?:for|on) this repository yet", re.I)


def _front_door_documents() -> dict:
    out = subprocess.run(["git", "ls-files", "README.md", "SECURITY.md", "docs/"],
                         cwd=str(ROOT), capture_output=True, text=True, check=True).stdout
    return {name: (ROOT / name).read_text(encoding="utf-8")
            for name in out.split() if name.endswith((".md", ".html"))}


def _still_private(text: str) -> list:
    flat = " ".join(text.split())
    return [flat[max(0, m.start() - 60):m.end() + 20] for m in _STILL_PRIVATE.finditer(flat)]


def test_the_front_door_does_not_say_the_repository_is_private():
    """`D-2026-10-02-03`: the repository is public and stays public. Nine
    sentences in `README.md`, `SECURITY.md` and `docs/security-ci.md` said or
    assumed otherwise — the CI-badge note, the ship-line sentence, the badge
    table and the reasons under it, the checklist twice, private reporting
    *"not turned on … yet"*. This refuses seven of them as they stood (base
    `595d1bd`); the other two — *"Making the repository public … is the fix and
    is the owner's call"* and *"the repository was not public yet, so nobody
    has confirmed the switch is on"* — assume it through tense rather than say
    it, and were corrected by hand."""
    documents = _front_door_documents()
    assert {"README.md", "SECURITY.md", "docs/security-ci.md"} <= set(documents)
    found = {name: hits for name, text in documents.items() if (hits := _still_private(text))}
    assert not found, found


@pytest.mark.parametrize("sentence", [
    "while this repository is private the images render blank",
    "Do the third one **before** the repository is public, not after",
    "| Private repo (today) | A blank or broken image |",
    "If that page 404s, private reporting has not been turned on for this repository yet.",
])
def test_the_old_sentences_are_what_the_rule_refuses(sentence):
    """The rule, driven with sentences exactly as the documents had them."""
    assert _still_private(sentence), sentence


def test_a_dated_note_about_the_private_days_is_left_alone():
    """`Law 1`: the record of what a page used to say is not the claim."""
    note = ("*(Until 2026-10-02 this said to do the third one before the "
            "repository was public, not after.)* That was written when the "
            "repository was private and it does not survive going public.")
    assert _still_private(note) == []
