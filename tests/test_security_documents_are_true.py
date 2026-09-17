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

Both are cross-artefact checks — the claim in the prose against the thing the
prose is about, read out of the real workflow, the real register and the real
audit script. A test that read only the document would agree with whatever the
document said.
"""
import importlib.util
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
    # Before the repository is public, which is the only part with a deadline.
    assert "public" in lowered, body[-1500:]
    assert "these two settings" not in lowered, body[:400]
