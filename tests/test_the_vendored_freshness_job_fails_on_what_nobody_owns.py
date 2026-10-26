# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B437`: the weekly vendored-freshness job fails on what nobody has accounted for.

It sorts npm's and OSV's answers into five sections, and two of them are by
construction *nobody owns this*: a version behind upstream with no row naming it
(`behind_ok`), and an advisory the record does not explain (`osv_known`). The
logic was a heredoc inside `.github/workflows/vendored-freshness.yml`; it is
`.pantheon/vendored-freshness.py` now, and this drives its decision with the two
upstream questions answered by stand-ins — no network, no YAML.
"""
import importlib.util
import pathlib
import urllib.error

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".pantheon" / "vendored-freshness.py"


@pytest.fixture(scope="module")
def vf():
    spec = importlib.util.spec_from_file_location("_vendored_freshness", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rec(entry="Mermaid", package="mermaid", version="11.0.0", behind_ok="",
         osv_known=None, registry="npm", contains=()):
    return {"entry": entry, "package": package, "version": version, "registry": registry,
            "source": "https://example.invalid", "behind_ok": behind_ok,
            "osv_known": dict(osv_known or {}), "contains": list(contains)}


def _tags(**by_pkg):
    return lambda pkg: by_pkg[pkg]


def _no_vulns(pkg, ver):
    return []


def test_a_version_behind_upstream_with_no_row_naming_it_fails_the_job(vf, capsys):
    rc = vf.main(records=[_rec()], dist_tags=_tags(mermaid={"latest": "11.4.0"}),
                 advisories=_no_vulns)
    out = capsys.readouterr().out
    assert rc == 1
    assert "Mermaid: shipping 11.0.0, npm latest is 11.4.0" in out
    assert "FAIL." in out and "behind_ok" in out


def test_the_same_version_with_a_row_that_owns_it_passes(vf, capsys):
    rc = vf.main(records=[_rec(behind_ok="B999")],
                 dist_tags=_tags(mermaid={"latest": "11.4.0"}), advisories=_no_vulns)
    out = capsys.readouterr().out
    assert rc == 0
    assert "shipping 11.0.0, npm latest is 11.4.0  [B999]" in out


def test_an_unexplained_advisory_fails_and_an_explained_one_does_not(vf):
    vulns = lambda pkg, ver: [{"id": "GHSA-aaaa", "database_specific": {"severity": "HIGH"}}]
    current = _tags(mermaid={"latest": "11.0.0"})
    found = vf.ask([_rec()], current, vulns)
    assert found["vulnerable"] == ["Mermaid mermaid@11.0.0: GHSA-aaaa HIGH"]
    assert vf.decide(found) == 1
    found = vf.ask([_rec(osv_known={"GHSA-aaaa": "only reachable through X, which we do not call"})],
                   current, vulns)
    assert found["vulnerable"] == [] and len(found["excused"]) == 1
    assert vf.decide(found) == 0


def test_a_bundles_inner_package_is_asked_and_held_to_the_same_rule(vf):
    inner = {"package": "jspdf", "version": "4.0.0", "behind_ok": "", "osv_known": {}}
    found = vf.ask([_rec(entry="html2pdf.js", package="html2pdf.js", version="0.14.0",
                         contains=[inner])],
                   _tags(**{"html2pdf.js": {"latest": "0.14.0"}, "jspdf": {"latest": "4.2.0"}}),
                   _no_vulns)
    assert found["behind"] == ["html2pdf.js ⊃ jspdf@4.0.0: the bundle carries 4.0.0, "
                               "npm latest is 4.2.0"]
    assert vf.decide(found) == 1


def test_a_question_nobody_answered_is_said_and_does_not_fail_or_crash(vf):
    def refused(pkg):
        raise urllib.error.URLError("no route")

    def timed_out(pkg, ver):
        raise TimeoutError("read timed out")

    found = vf.ask([_rec(), _rec(entry="SheetJS", package="xlsx", registry="sheetjs")],
                   refused, timed_out)
    assert any("registry said" in line for line in found["unknown"])
    assert any("OSV said" in line for line in found["unknown"])
    assert any("registry='sheetjs' has no index" in line for line in found["unknown"])
    assert vf.decide(found) == 0, "could-not-ask is reported, not failed (as before B437)"


def test_the_record_names_which_dist_tag_to_compare(vf):
    """`B335`: Pyodide's npm `latest` is a different version line."""
    rec = _rec(entry="Pyodide", package="pyodide", version="0.27.7")
    rec["dist_tag"] = "stable-0.27"
    found = vf.ask([rec], _tags(pyodide={"latest": "314.0.7", "stable-0.27": "0.27.7"}),
                   _no_vulns)
    assert vf.decide(found) == 0 and not found["filed"]


def test_the_workflow_runs_the_script_and_carries_no_logic_of_its_own():
    wf = (ROOT / ".github" / "workflows" / "vendored-freshness.yml").read_text(encoding="utf-8")
    assert "run: python3 .pantheon/vendored-freshness.py" in wf
    assert "<<'PY'" not in wf, "the decision is back in a heredoc no test can reach"
