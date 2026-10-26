# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B761` — the composer prices an attachment before the message is sent.

A file in the composer has not been uploaded (`fileHandler.uploadPending` runs
at send), so the server had nothing to measure and `P12-09`'s meter said
*"N attached — measured when you send"*: the limit, after you hit it. The row's
`Verify:` — *attach a 40,000-character log to an empty composer and the meter
says it will be truncated before the message is sent* — is driven here on the
real `static/js/fileHandler.js` in the meter's own sandbox
(`tests/test_context_meter_js.py`), with real `File` objects and the server's
real default budgets (`src/context_budget.py`, read rather than retyped), and
no upload: nothing leaves the browser until send, which is the half of the
row's question this answer chose.
"""
import json
import shutil

import pytest

from src.context_budget import context_budget_report
from test_context_meter_js import _PREAMBLE, meter_sandbox  # noqa: F401
from test_tool_effect_surfaces_js import _run

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _report():
    """`GET /api/upload/context-budget` with no ids: the budgets, a measured
    zero, and the four unmeasured segments — the shape the route answers."""
    report = context_budget_report()
    report["segments"] = [
        {"key": "system", "label": "System prompt", "measured": False},
        {"key": "attachments", "label": "Attachments", "measured": True,
         "chars": 0, "items": [], "remaining_chars": 0},
    ]
    return report


def _drive(sandbox, files_js: str, then: str = ""):
    return _run(sandbox, _PREAMBLE, """
        serve(%s);
        fh.init('');
        await tick();
        const before = asked.length;
        await fh.addFiles(%s, { skipCrop: true });
        await tick(20);
        %s
        console.log(JSON.stringify({ meter: readMeter(), uploads: asked.slice(before),
          estimate: (document.querySelector('.context-meter-estimate') || {}).textContent || null }));
    """ % (json.dumps(_report()), files_js, then))


def _budget(key):
    return next(b["chars"] for b in context_budget_report()["budgets"] if b["key"] == key)


def test_a_40000_character_log_says_it_will_be_cut_before_it_is_sent(meter_sandbox):  # noqa: F811
    log_allowance = _budget("context_log_file_chars")
    assert log_allowance < 40000, "the premise: the default .log allowance is smaller"
    out = _drive(meter_sandbox, "[new File(['x'.repeat(39999) + '\\n'], 'server.log', { type: 'text/plain' })]")
    meter = out["meter"]
    (chip,) = meter["chips"]
    assert chip["name"] == "server.log"
    assert "context-chip-truncated" in chip["classes"] and "context-chip-estimate" in chip["classes"]
    assert chip["note"] == (f"≈ 40,000 characters — will be cut to {log_allowance:,} "
                            "(the .log allowance)")
    assert meter["figure"].startswith(f"≈ {log_allowance:,} of ")
    assert out["estimate"] == ("server.log will not be sent whole. "
                               "Estimated here before sending; measured exactly when you send.")
    assert meter["empty"] is None, "it still said 'measured when you send'"
    assert out["uploads"] == [], "pricing a file must not upload it"


def test_a_small_text_file_is_priced_as_a_share_of_the_budget(meter_sandbox):  # noqa: F811
    ceiling = _budget("context_attachment_total_chars")
    out = _drive(meter_sandbox, "[new File(['a'.repeat(2400)], 'notes.md', { type: 'text/markdown' })]")
    (chip,) = out["meter"]["chips"]
    assert chip["note"] == f"≈ 2,400 characters, {round(2400 / ceiling * 100)}% of the budget"
    assert "context-chip-truncated" not in chip["classes"]
    assert out["estimate"] == "Estimated here before sending; measured exactly when you send."


def test_the_turns_ceiling_is_spent_in_order_and_the_last_file_finds_no_room(meter_sandbox):  # noqa: F811
    ceiling = _budget("context_attachment_total_chars")
    per_file = _budget("context_text_file_chars")
    big = min(per_file, ceiling)
    out = _drive(meter_sandbox, f"""[
        new File(['a'.repeat({big})], 'one.txt'),
        new File(['b'.repeat(50)], 'two.txt'),
    ]""")
    first, second = out["meter"]["chips"]
    assert first["note"].startswith(f"≈ {big:,} characters")
    assert "context-chip-omitted" in second["classes"]
    assert second["note"] == "≈ 50 characters — no room in this message"


def test_a_file_no_converter_reads_here_still_waits_for_the_send(meter_sandbox):  # noqa: F811
    out = _drive(meter_sandbox, """[
        new File(['%PDF-1.4'], 'report.pdf', { type: 'application/pdf' }),
        new File(['x'.repeat(100)], 'a.py'),
    ]""")
    pdf, py = out["meter"]["chips"]
    assert pdf["name"] == "report.pdf" and pdf["note"] == "measured when you send"
    assert py["note"].startswith("≈ 100 characters")


def test_only_binaries_keep_the_old_sentence(meter_sandbox):  # noqa: F811
    out = _drive(meter_sandbox, "[new File([new Uint8Array([137, 80, 78, 71])], 'photo.png', { type: 'image/png' })]")
    assert out["meter"]["empty"] == "1 attached — measured when you send"
    assert out["estimate"] is None
