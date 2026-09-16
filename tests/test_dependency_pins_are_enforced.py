# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B320`-`B323` — the dependency set is pinned, and the gate that keeps it that way.

What was measured on 2026-09-16, on the tree these tests were written against:
`requirements.txt` held **31 dependencies and zero `==` pins**, and
`requirements-optional.txt` held 6 of which 2 were pinned. Three consequences,
and the third is the one that is easy to walk past:

  1. The build was not reproducible — the same commit built on two days
     produced two different images.
  2. A yanked or compromised release landed on the next build with nothing and
     nobody in between.
  3. `.github/dependabot.yml` had been configured for pip, reviewed and merged,
     and **could not have opened a single Python pull request**. Dependabot
     bumps a pinned version; a bare `fastapi` is satisfied by every release
     fastapi has ever made, so there was never anything to compare against. The
     automation looked like coverage on the config page and provided none.

So the deliverable is not the bump — a bump drifts back within a month. It is
the pair of rules that keep it true: `.pantheon/check-pins.py` offline in the
release gate, and `.pantheon/audit-dependencies.py` in the one CI job that is
allowed a network.

**These tests drive the real checkers** (`Law 20`), against fixture trees rather
than against this repository wherever the point is the rule and not today's
answer — a checker whose only evidence is "it passes on the tree it was written
for" is the same mistake one layer up. The two tests that do point at the real
tree say so in their names, and they are the ones that fail on the tree as it
stood before this change.

The audit's partition is a pure function tested against canned `pip-audit`
reports. A gate whose tests need a network is a gate whose tests are sometimes
about the network instead of about the gate.
"""

import datetime
import importlib.util
import json
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_CHECKER = _REPO / ".pantheon" / "check-pins.py"
_AUDIT = _REPO / ".pantheon" / "audit-dependencies.py"
_GATE = _REPO / ".pantheon" / "release-gate.py"


def _load(path: Path, name: str, root: Path | None = None):
    """The real module, optionally pointed at a fixture tree instead of the repo."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)      # not __main__, so main() does not run
    if root is not None:
        module.ROOT = root
    return module


ADVISORY = """\
[[advisory]]
id = "PYSEC-0000-1"
aliases = ["CVE-0000-1"]
package = "widget"
version = "1.0.0"
declared_in = "requirements.txt"
what_it_is = "a bug"
why_it_does_not_apply = "the path is not reachable"
fix_available = "nothing"
what_would_change_this = "a release"
decision = "D-2026-01-01-01"
review_by = "2099-01-01"
reviewed_by = "whoever merges the next bump"
"""


def _tree(tmp_path: Path, requirements="widget==1.0.0\n", advisory=ADVISORY,
          decisions="## D-2026-01-01-01 — a decision\n", dependabot=None) -> Path:
    """A minimal repository the checker can be pointed at."""
    (tmp_path / "requirements.txt").write_text(requirements, encoding="utf-8")
    (tmp_path / ".pantheon").mkdir(exist_ok=True)
    (tmp_path / ".pantheon" / "dependency-advisories.toml").write_text(
        advisory, encoding="utf-8")
    (tmp_path / ".pantheon" / "DECISIONS.md").write_text(decisions, encoding="utf-8")
    (tmp_path / ".github").mkdir(exist_ok=True)
    (tmp_path / ".github" / "dependabot.yml").write_text(
        dependabot if dependabot is not None else
        'version: 2\nupdates:\n  - package-ecosystem: pip\n    directory: "/"\n'
        "    schedule:\n      interval: weekly\n",
        encoding="utf-8")
    return tmp_path


# --- Rule 1: every requirement names one release -----------------------------

def test_a_bare_name_is_not_a_dependency_decision(tmp_path):
    """`fastapi` on its own is satisfied by every release ever made."""
    checker = _load(_CHECKER, "pins_bare", _tree(tmp_path, "widget\n"))
    problems = checker.unpinned_problems()
    assert len(problems) == 1
    assert "no version at all" in problems[0]


def test_a_floor_is_still_a_range(tmp_path):
    """`>=2.13.4` is the shape that made Dependabot inert — it is not a pin."""
    checker = _load(_CHECKER, "pins_floor", _tree(tmp_path, "widget>=2.13.4\n"))
    problems = checker.unpinned_problems()
    assert len(problems) == 1
    assert "is a range, not a pin" in problems[0]


def test_a_bounded_range_is_still_a_range(tmp_path):
    checker = _load(_CHECKER, "pins_range", _tree(tmp_path, "widget>=1.0,<2.0\n"))
    assert len(checker.unpinned_problems()) == 1


@pytest.mark.parametrize("line", [
    "widget==1.0.0\n",
    "widget[extra]==1.0.0\n",
    "widget [a,b] == 1.0.0\n",
    'widget==1.0.0; python_version >= "3.11" and python_version < "3.13"\n',
    "widget===1.0.0\n",
])
def test_the_shapes_a_real_requirements_file_uses_are_accepted(tmp_path, line):
    """Extras, spacing and environment markers must not read as unpinned.

    `requirements-optional.txt` really does carry
    `kokoro==0.9.4; python_version >= "3.11" and python_version < "3.13"` and
    `markitdown[docx,pptx,xlsx,xls]==0.1.6`. A rule that flagged either would be
    deleted within a week, which is how a checker stops being a gate.
    """
    checker = _load(_CHECKER, "pins_ok", _tree(tmp_path, line))
    assert checker.unpinned_problems() == []


def test_a_marker_does_not_smuggle_an_unpinned_requirement_through(tmp_path):
    """The marker is not the pin. `kokoro; python_version < "3.13"` is unpinned."""
    checker = _load(_CHECKER, "pins_marker",
                    _tree(tmp_path, 'widget; python_version < "3.13"\n'))
    assert len(checker.unpinned_problems()) == 1


def test_comments_and_includes_are_not_requirements(tmp_path):
    """The prose in requirements.txt is load-bearing documentation, not a dep."""
    checker = _load(_CHECKER, "pins_comments", _tree(tmp_path, (
        "# why this dependency is here, at length\n"
        "\n"
        "widget==1.0.0  # trailing note\n"
        "-r other.txt\n"
        "--index-url https://example.invalid/simple\n"
    )))
    assert checker.unpinned_problems() == []
    assert len(checker.parse_requirements(tmp_path / "requirements.txt")) == 1


def test_this_repository_pins_every_python_dependency():
    """The real tree. Fails on the tree as it stood before this change: 31 + 4."""
    checker = _load(_CHECKER, "pins_real")
    assert checker.unpinned_problems() == []
    names = {n for p in checker.requirement_files()
             for _, _, n, _ in checker.parse_requirements(p)}
    # The dependencies the row counted, so a silent truncation of the file is
    # not mistaken for compliance.
    assert {"fastapi", "mcp", "psycopg2-binary", "httpx2"} <= names
    assert len(names) >= 37


# --- Rule 2: an accepted risk has to justify itself --------------------------

@pytest.mark.parametrize("field", [
    "what_it_is", "why_it_does_not_apply", "fix_available",
    "what_would_change_this", "decision", "review_by", "reviewed_by",
])
def test_an_accepted_risk_missing_any_of_its_reasoning_is_refused(tmp_path, field):
    """An entry that cannot answer one of these is a shrug, not a decision."""
    text = re.sub(rf"(?m)^{field} = .*\n", "", ADVISORY)
    checker = _load(_CHECKER, f"adv_{field}", _tree(tmp_path, advisory=text))
    problems = checker.advisory_problems()
    assert any(f"has no `{field}`" in p for p in problems), problems


def test_an_accepted_risk_citing_a_decision_that_does_not_exist_is_refused(tmp_path):
    """The reasoning has to be somewhere a reader can reach it."""
    checker = _load(_CHECKER, "adv_decision",
                    _tree(tmp_path, decisions="## D-1999-01-01-01 — something else\n"))
    problems = checker.advisory_problems()
    assert any("does not contain" in p for p in problems), problems


def test_an_accepted_risk_whose_review_date_has_passed_fails_the_gate(tmp_path):
    """The expiry is the mechanism. A suppression with no end outlives its reason."""
    text = ADVISORY.replace('review_by = "2099-01-01"', 'review_by = "2026-01-01"')
    checker = _load(_CHECKER, "adv_expired", _tree(tmp_path, advisory=text))
    fresh = checker.advisory_problems(today=datetime.date(2025, 12, 31))
    expired = checker.advisory_problems(today=datetime.date(2026, 1, 2))
    assert fresh == []
    assert any("do not move the date without looking" in p for p in expired), expired


def test_an_accepted_risk_whose_dependency_moved_is_refused(tmp_path):
    """A suppression that outlived its pin is exactly as misleading as one with
    no reason: it describes a version the tree no longer installs."""
    checker = _load(_CHECKER, "adv_moved", _tree(tmp_path, "widget==2.0.0\n"))
    problems = checker.advisory_problems()
    assert any("outlived it" in p for p in problems), problems


def test_the_same_advisory_cannot_be_accepted_twice(tmp_path):
    checker = _load(_CHECKER, "adv_dup", _tree(tmp_path, advisory=ADVISORY * 2))
    assert any("listed twice" in p for p in checker.advisory_problems())


def test_this_repositorys_accepted_risks_are_complete_and_in_date():
    """The real register. `basicsr` is the only entry and it is fully reasoned."""
    checker = _load(_CHECKER, "adv_real")
    assert checker.advisory_problems() == []
    entries, problems = checker.load_advisories()
    assert problems == []
    assert [e["id"] for e in entries] == ["PYSEC-2026-1215"]
    entry = entries[0]
    assert entry["package"] == "basicsr" and entry["version"] == "1.4.2"
    # The reasoning a reader of a red build needs, not a severity score.
    assert "SLURM_NODELIST" in entry["what_it_is"]
    assert "init_dist" in entry["why_it_does_not_apply"]
    assert "no release since" in entry["fix_available"]
    assert entry["decision"] == "D-2026-09-16-01"
    assert datetime.date.fromisoformat(entry["review_by"]) > datetime.date.today()


# --- Rule 3: something is configured to bump the pins ------------------------

def test_a_pinned_file_nothing_is_configured_to_bump_is_refused(tmp_path):
    """Pinning without automation swaps drift for rot. Both are unowned versions."""
    root = _tree(tmp_path, dependabot="version: 2\nupdates: []\n")
    checker = _load(_CHECKER, "dep_none", root)
    assert any("nothing configured to bump them" in p
               for p in checker.dependabot_problems())


def test_a_pinned_file_outside_every_configured_directory_is_refused(tmp_path):
    root = _tree(
        tmp_path,
        dependabot='version: 2\nupdates:\n  - package-ecosystem: pip\n'
                   '    directory: "/service"\n',
    )
    checker = _load(_CHECKER, "dep_elsewhere", root)
    assert any("nothing will ever bump it" in p
               for p in checker.dependabot_problems())


def test_this_repositorys_requirements_files_are_all_covered():
    checker = _load(_CHECKER, "dep_real")
    assert checker.dependabot_problems() == []
    assert checker._dependabot_pip_directories() == ["/"]
    assert {p.name for p in checker.requirement_files()} == {
        "requirements.txt", "requirements-optional.txt", "requirements-image.txt"}


# --- The network half: partitioning a pip-audit report -----------------------

def _report(*deps):
    return {"dependencies": [
        {"name": n, "version": v, "vulns": list(vulns)} for n, v, *vulns in deps]}


def _vuln(vid, aliases=(), fixes=(), description="a description"):
    return {"id": vid, "aliases": list(aliases), "fix_versions": list(fixes),
            "description": description}


def _register():
    checker = _load(_CHECKER, "reg_real")
    entries, problems = checker.load_advisories()
    assert problems == []
    return entries


def test_a_finding_with_no_recorded_decision_fails_the_audit():
    audit = _load(_AUDIT, "audit_fail")
    report = _report(("widget", "1.0.0", _vuln("PYSEC-9999-9")))
    failures, suppressed, stale = audit.partition(report, _register())
    assert [f[0] for f in failures] == ["widget"]
    assert suppressed == [] and stale == []


def test_the_recorded_finding_is_accepted_and_nothing_else_is():
    """`basicsr` does not fail; an unrelated advisory in the same report does."""
    audit = _load(_AUDIT, "audit_mixed")
    report = _report(
        ("basicsr", "1.4.2", _vuln("PYSEC-2026-1215", ["CVE-2024-27763"])),
        ("widget", "1.0.0", _vuln("PYSEC-9999-9")),
        ("numpy", "2.4.6"),
    )
    failures, suppressed, stale = audit.partition(report, _register())
    assert [s[0] for s in suppressed] == ["basicsr"]
    assert [f[0] for f in failures] == ["widget"]
    assert stale == []


def test_an_accepted_advisory_is_matched_by_its_alias():
    """Advisory databases disagree about identifiers, so the match has to look at
    every id a finding carries, not just the primary one.

    The register lists `PYSEC-2026-1215` and `CVE-2024-27763`. pip-audit's own
    output carries a third, `GHSA-86w8-vhw6-q9qq`, as an alias — and a tool that
    reported the GHSA as the primary id, with the CVE in its alias list, would
    otherwise turn a settled decision into a red build.
    """
    audit = _load(_AUDIT, "audit_alias")
    report = _report(("basicsr", "1.4.2",
                      _vuln("GHSA-86w8-vhw6-q9qq", ["CVE-2024-27763"])))
    failures, suppressed, _ = audit.partition(report, _register())
    assert not failures and len(suppressed) == 1


def test_the_same_advisory_against_a_different_version_is_a_new_finding():
    """The reasoning was written about 1.4.2. It is not a blanket pardon."""
    audit = _load(_AUDIT, "audit_version")
    report = _report(("basicsr", "1.5.0", _vuln("PYSEC-2026-1215")))
    failures, suppressed, _ = audit.partition(report, _register())
    assert [f[0] for f in failures] == ["basicsr"] and suppressed == []


def test_the_same_advisory_against_a_different_package_is_a_new_finding():
    audit = _load(_AUDIT, "audit_package")
    report = _report(("otherpkg", "1.4.2", _vuln("PYSEC-2026-1215")))
    failures, _, _ = audit.partition(report, _register())
    assert [f[0] for f in failures] == ["otherpkg"]


def test_a_suppression_whose_finding_has_gone_away_fails_too():
    """An ignore list that describes nothing is how people stop reading one."""
    audit = _load(_AUDIT, "audit_stale")
    report = _report(("basicsr", "1.4.2"))
    failures, suppressed, stale = audit.partition(report, _register())
    assert not failures and not suppressed
    assert [e["id"] for e in stale] == ["PYSEC-2026-1215"]


def test_a_suppression_is_not_stale_when_its_package_was_not_audited():
    """Auditing a narrower set must not turn a live decision into a failure."""
    audit = _load(_AUDIT, "audit_notaudited")
    failures, suppressed, stale = audit.partition(_report(("numpy", "2.4.6")),
                                                 _register())
    assert not failures and not suppressed and not stale


def test_one_advisory_reported_twice_is_counted_once():
    """pip-audit really does emit PYSEC-2026-1215 twice for basicsr, once per
    matching database range. Counted naively, the log says two accepted risks
    where there is one."""
    audit = _load(_AUDIT, "audit_dupe")
    vuln = _vuln("PYSEC-2026-1215", ["CVE-2024-27763"])
    report = {"dependencies": [
        {"name": "basicsr", "version": "1.4.2", "vulns": [vuln, dict(vuln)]}]}
    _, suppressed, _ = audit.partition(report, _register())
    assert len(suppressed) == 1


def test_the_reason_basicsr_does_not_fail_is_printed_where_the_failure_is_read(capsys):
    """The whole point of the register: the justification is in the build log,
    beside the findings that did fail, not in a file a reader would have to
    know to open."""
    audit = _load(_AUDIT, "audit_output")
    report = _report(("basicsr", "1.4.2", _vuln("PYSEC-2026-1215", ["CVE-2024-27763"])))
    _, suppressed, _ = audit.partition(report, _register())
    audit._print_suppressed(suppressed)
    printed = capsys.readouterr().out
    assert "ACCEPTED RISK" in printed
    assert "D-2026-09-16-01" in printed
    assert "SLURM_NODELIST" in printed
    assert "init_dist" in printed
    assert "2027-03-16" in printed
    assert "what would change this" in printed


def test_the_realesrgan_pins_are_read_from_the_build_script_not_copied():
    """basicsr/gfpgan/facexlib are installed into every image and named in no
    requirements file. The audit reads them where they are actually pinned, so
    the version cannot exist in two places and disagree with itself (`Law 13`)."""
    audit = _load(_AUDIT, "audit_specs")
    assert sorted(audit.realesrgan_pins()) == [
        "basicsr==1.4.2", "facexlib==0.3.0", "gfpgan==1.3.8"]


# --- The wiring: the rules actually run --------------------------------------

def test_the_release_gate_runs_the_pin_checker():
    """Driven through release-gate's own reader of ci.yml rather than by
    grepping the workflow: the gate's checker list IS that function's output,
    so this is the same question CI answers."""
    gate = _load(_GATE, "gate_real")
    names = {name for name, _ in gate._checkers_from_ci()}
    assert "pins" in names
    assert ".pantheon/check-pins.py" in {
        argv[0] for _, argv in gate._checkers_from_ci()}


def test_the_dependency_audit_blocks_the_build():
    """`continue-on-error` on the audit job is the difference between a gate and
    a log line. Comments are stripped first (`Law 20`) so the prose explaining
    why it used to be advisory cannot satisfy the assertion."""
    text = (_REPO / ".github" / "workflows" / "dependency-review.yml").read_text(
        encoding="utf-8")
    code = "\n".join(line for line in text.splitlines()
                     if not line.lstrip().startswith("#"))
    job = code.split("pip-audit:", 1)[1]
    assert "continue-on-error" not in job
    assert "audit-dependencies.py" in job


def test_the_image_installs_no_python_package_that_no_requirements_file_declares():
    """`B321`. The Dockerfile used to install `python-magic==0.4.27` inline,
    where Dependabot's pip ecosystem and the dependency audit could not see it:
    the one package pinned by hand was the one package nothing would ever bump.
    Every `pip install` in the Dockerfile must now name a requirements file or a
    local wheel path."""
    text = (_REPO / "Dockerfile").read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines()
                     if not line.lstrip().startswith("#"))
    installs = re.findall(r"pip install\s+([^\n&|]+)", code)
    assert installs, "no pip install found — has the Dockerfile moved?"
    for argv in installs:
        args = [a for a in argv.split() if not a.startswith("-")
                or a.startswith("-r")]
        named = " ".join(args)
        assert "-r" in named or "/tmp/pantheon-wheels" in named, (
            f"Dockerfile installs `{argv.strip()}` with no requirements file — "
            f"put the pin in requirements-image.txt where the tooling can see it")


# `Law 1`. Every comment line the two requirements files carried before they
# were pinned, verbatim. This is the whole of it rather than a few sampled
# phrases, because the prose IS the documentation: it is the only record of why
# `mcp` is held below 2, why `httpx2` is test-client only, why `psycopg2-binary`
# rather than `psycopg2`, and — in the optional file — that PyMuPDF is AGPL-3.0.
# A sweep that rewrites 37 lines is exactly the kind of change that quietly
# takes a paragraph with it, and a sampled assertion is exactly the kind of test
# that does not notice.
_BASELINE_CORE_COMMENTS = """\
# Vector store + local embeddings for RAG, semantic memory, and tool
# selection. Used on core agent paths, so installed by default — the app
# still degrades to keyword fallback if they're ever missing.
# chromadb-client is the lightweight HTTP client (talks to a standalone
# ChromaDB service); fastembed runs local ONNX embeddings.
# Markdown rendering for research reports (src/visual_report.py).
# Imported at module-top so it's a hard core dep, not optional.
# HTML sanitizer for rendered research reports (src/visual_report.py). Report
# content is untrusted (LLM output over crawled pages) and report pages run
# under a relaxed CSP, so the rendered HTML is allowlist-sanitized.
# Calendar .ics import/export (routes/calendar_routes.py).
# Recurrence rule expansion for calendar events (routes/calendar_routes.py).
# Imported directly as dateutil.rrule — make it explicit even though caldav
# pulls it in transitively.
# CalDAV sync (src/caldav_sync.py). Handles PROPFIND discovery + REPORT
# fetch across Radicale, Nextcloud, Apple, Fastmail; we'd be reinventing
# the protocol without it.
# Built-in servers use the v1 low-level Server decorator API. MCP SDK v2 is a
# breaking rewrite, so keep fresh installs on the maintained v1 line until the
# servers are migrated together.
# starlette.testclient prefers httpx2 since Starlette 1.2.0 and warns on every
# TestClient import when only classic httpx is present. Runtime code keeps
# using `httpx` above; this is test-client only.
# DATABASE_URL defaults to sqlite (core/database.py), but when pointed at an
# external Postgres, SQLAlchemy's postgresql dialect imports psycopg2 inside
# create_engine() and raises ModuleNotFoundError if missing. -binary avoids
# needing libpq-dev/pg_config on the host/image to compile it.
"""

_BASELINE_OPTIONAL_COMMENTS = """\
# Optional dependencies — install only if you use the corresponding feature.
# The app handles their absence gracefully (clear error message on first use).
#
# Note: chromadb-client + fastembed moved to requirements.txt — RAG, semantic
# memory, and tool selection are core paths, so they ship by default now.
# Local speech-to-text (microphone -> text) via faster-whisper, for the
# "local" STT provider. Runs on CPU out of the box (CTranslate2 backend, no
# torch needed). Install if you want to dictate/transcribe with the mic
# without sending audio to an external endpoint.
# Optional extra: install `torch` too if you have a CUDA GPU and want
# GPU-accelerated transcription — it's auto-detected, CPU is used otherwise.
# Local text-to-speech via Kokoro-82M for the "local" TTS provider.
# Kokoro 0.9.4 declares Python >=3.10,<3.13; Pantheon itself requires 3.11+,
# so pip installs these extras on 3.11-3.12 and deliberately skips them on
# Python 3.13+ (including the Python 3.14 container image). Kokoro declares
# torch; the local provider still
# requires a CUDA-enabled torch build and GPU at runtime. SoundFile is separate
# in Kokoro's official install instructions and is not a transitive dependency.
# DuckDuckGo as a search provider option.
# Install if you want DDG in the search-provider dropdown.
# Alternatives: SearXNG, Brave, Tavily, Serper, Google PSE.
# PDF form-filling feature (fillable AcroForm detection, field extraction,
# value/annotation/signature stamping, page rendering for the form overlay).
# NOTE: PyMuPDF is AGPL-3.0. Pantheon is already AGPL-3.0-or-later, so this
# adds an upstream copyright holder rather than a new obligation class — see
# CREDITS.md. PDF *text* extraction goes through pypdf (BSD-3-Clause) and works
# without PyMuPDF; installing it unlocks form-filling, the PDF viewer's page
# render, annotation fill, and fillable-PDF detection on chat attachments.
# Office / EPUB document text extraction (chat attachments + the personal-docs
# RAG index). markitdown (MIT, Microsoft) converts .docx/.xlsx/.pptx/.xls/.epub
# to Markdown — more token-efficient and model-legible than a raw dump. Optional
# and lazy-imported via src/markitdown_runtime.py; without it those formats fall
# back to a friendly "install to extract" banner. (Pantheon as a whole is
# AGPL-3.0-or-later; the permissive licences here apply to individual vendored
# dependencies, not to the project — see CREDITS.md.)
# Extras pull mammoth/lxml/python-pptx/pandas/openpyxl/xlrd; the base also pulls
# magika (onnxruntime), already a core dep via fastembed. We avoid the
# [all]/Azure/audio extras (cloud + heavy). Pinned to a release >30 days old per
# the dependency-age discussion in issue #485.
"""


@pytest.mark.parametrize("name,baseline", [
    ("requirements.txt", _BASELINE_CORE_COMMENTS),
    ("requirements-optional.txt", _BASELINE_OPTIONAL_COMMENTS),
])
def test_pinning_did_not_cost_a_single_line_of_the_prose(name, baseline):
    text = (_REPO / name).read_text(encoding="utf-8")
    missing = [line for line in baseline.splitlines()
               if line.strip() and line not in text]
    assert missing == [], f"{name} lost {len(missing)} comment line(s): {missing[:3]}"


def test_the_checker_reports_a_clean_tree_as_clean():
    """End to end on the real repository, through main(), the way CI runs it."""
    checker = _load(_CHECKER, "pins_main")
    import sys
    argv = sys.argv
    sys.argv = ["check-pins.py"]
    try:
        assert checker.main() == 0
    finally:
        sys.argv = argv


def test_a_canned_report_round_trips_through_the_audit_entry_point(tmp_path):
    """The `--report` path exists so the partition can be exercised without a
    network, here and by anyone debugging a red build from its JSON."""
    audit = _load(_AUDIT, "audit_main")
    path = tmp_path / "report.json"
    path.write_text(json.dumps(_report(
        ("basicsr", "1.4.2", _vuln("PYSEC-2026-1215", ["CVE-2024-27763"])))),
        encoding="utf-8")
    import sys
    argv = sys.argv
    sys.argv = ["audit-dependencies.py", "--report", str(path)]
    try:
        assert audit.main() == 0
    finally:
        sys.argv = argv
