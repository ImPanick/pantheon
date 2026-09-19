# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P9-09` — the calendar half, and the re-measurement of the other five.

THE ROW'S DATED CORRECTION HOLDS, AND ALL FOUR LINE NUMBERS IN IT ARE STALE.
Re-measured 2026-09-19, each by the thing it renders rather than by the line it
used to be on:

  * **memories** — `static/js/memory.js`, `.memory-item-source`, `auto` or
    `manual` on every row (the row cited `memory.js:776`, which is now inside
    `tidyMemories`);
  * **skills** — `static/js/skills.js`, `_sourcePill` renders `teacher-created`
    naming the teacher model, and `_auditModelPills` renders `audit` /
    `teacher-fixed` naming the audit models (cited `skills.js:208`, now a sort
    comparator);
  * **generated images** — `static/js/gallery.js`, a `Source` section carrying
    `img.model` in the detail view (cited `gallery.js:1286/1481`; `:1481` is now
    the OCR caption);
  * **research reports** — `static/js/research/panel.js`, `.research-job-model`
    on the job card (cited `research/panel.js:897`).

So four of six, confirmed. The two that lack it are **tidy results** and
**calendar parses**, and they are not the same size:

  * **Tidy results need a field this half cannot add.** `POST
    /api/sessions/auto-sort` returns `{status, folders, updated, deleted_empty,
    deleted_throwaway, unfiled_remaining}` and `POST /api/memory/audit` returns
    `{ok, before, after, removed, superseded, contradictions, already_tidy}`.
    Neither carries the model, and in both handlers the model is a local
    variable already in scope — `routes/session_routes.py` even logs it. One key
    each. Both files belong to another agent this wave.
  * **Calendar parses do not.** `POST /api/calendar/quick-parse` has always
    answered with a `confidence`, and `static/js/calendar.js` read `summary`,
    `dtstart`, `dtend`, `all_day`, `location` and `description` out of that same
    response and dropped it. A form that filled itself in from one line of prose
    was indistinguishable from a form the person had typed.

This file pins the calendar half and the four measurements above, so the
correction cannot rot back into "none of them have it".
"""

import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from test_a_draft_skill_is_uncatalogued_not_inactive import js_function  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.helpers.source_text import blank_text  # B290

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"
CALENDAR_JS = JS / "calendar.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

export function readNote(form) {
  const note = form.querySelector('.cal-form-provenance');
  if (!note) return null;
  const t = (sel) => { const n = note.querySelector(sel); return n ? n.textContent : null; };
  return {
    lead: t('.cal-form-provenance-lead'),
    from: t('.cal-form-provenance-from'),
    sure: t('.cal-form-provenance-sure'),
    sureTitle: (note.querySelector('.cal-form-provenance-sure') || {}).title || '',
    unsure: !!note.querySelector('.cal-form-provenance-sure.is-unsure'),
    html: note._html,
    // The note has to sit ABOVE the title it is talking about.
    beforeTitle: form.childNodes.indexOf(note)
      < form.childNodes.indexOf(form.querySelector('.cal-title-wrap')),
    count: form.querySelectorAll('.cal-form-provenance').length,
  };
}

export function makeForm() {
  const form = document.createElement('div');
  form.className = 'cal-form cal-form-bespoke';
  const today = document.createElement('div');
  today.className = 'cal-form-today';
  form.appendChild(today);
  const wrap = document.createElement('div');
  wrap.className = 'cal-title-wrap';
  form.appendChild(wrap);
  document.body.appendChild(form);
  return form;
}
"""


def _calendar(tmp_path, script):
    """`noteQuickParseProvenance`, run for real (`Law 20` option 1).

    Its only free variable is `document`, so the real body runs against the
    shared DOM shim and a mutation to any of its five statements dies here.
    """
    sandbox = _make_sandbox(tmp_path, CALENDAR_JS, _SHIM, {})
    body = js_function(CALENDAR_JS.read_text(encoding="utf-8"),
                       "function noteQuickParseProvenance")
    preamble = (
        "import { document, Node, readNote, makeForm } from './shim.js';\n"
        "function noteQuickParseProvenance(sourceText, confidence) " + body + "\n"
    )
    return _run(sandbox, preamble, script)


def test_the_form_says_a_model_filled_it_in_and_how_sure_it_was(tmp_path):
    out = _calendar(tmp_path, """
        const form = makeForm();
        noteQuickParseProvenance('dentist tuesday 3pm', 0.82);
        console.log(JSON.stringify(readNote(form)));
    """)
    assert out is not None, "the quick-parsed form said nothing about where it came from"
    assert out["lead"] == "Your model filled this in"
    assert "dentist tuesday 3pm" in out["from"], "the line the person typed is echoed back"
    assert out["sure"] == "82% sure"
    assert out["unsure"] is False
    assert out["beforeTitle"] is True, "the note belongs above the fields it describes"


def test_a_guess_the_model_was_not_sure_of_says_so_loudly(tmp_path):
    """A 40%-confident parse presented in the same grey as an 82% one is a
    number nobody acts on. The whole reason to surface `confidence` is the
    band where the model is guessing at a date."""
    out = _calendar(tmp_path, """
        const form = makeForm();
        noteQuickParseProvenance('thing sometime after the trip', 0.4);
        console.log(JSON.stringify(readNote(form)));
    """)
    assert out["sure"] == "40% sure"
    assert out["unsure"] is True
    assert "check the date and time" in out["sureTitle"]


def test_a_missing_or_silly_confidence_does_not_produce_a_silly_number(tmp_path):
    out = _calendar(tmp_path, """
        const form = makeForm();
        noteQuickParseProvenance('a', undefined);
        const missing = readNote(form).sure;
        noteQuickParseProvenance('b', 7);
        const over = readNote(form).sure;
        noteQuickParseProvenance('c', -3);
        const under = readNote(form).sure;
        console.log(JSON.stringify({ missing, over, under }));
    """)
    assert out["missing"] == "0% sure"
    assert out["over"] == "100% sure"
    assert out["under"] == "0% sure"


def test_the_line_you_typed_is_text_and_never_markup(tmp_path):
    """The echo is the person's own words on their way back onto the screen."""
    out = _calendar(tmp_path, """
        const form = makeForm();
        noteQuickParseProvenance('<img src=x onerror=alert(1)>', 0.9);
        console.log(JSON.stringify(readNote(form)));
    """)
    assert "<img src=x onerror=alert(1)>" in out["from"]
    assert out["html"] == "", "the echoed line must not be parsed as markup"


def test_a_second_parse_replaces_the_note_rather_than_stacking_them(tmp_path):
    """`_showEventForm` rewrites the form, but a second quick-add against a form
    that is already open would otherwise leave two provenance lines disagreeing
    about which line produced the fields on screen."""
    out = _calendar(tmp_path, """
        const form = makeForm();
        noteQuickParseProvenance('first line', 0.9);
        noteQuickParseProvenance('second line', 0.5);
        console.log(JSON.stringify(readNote(form)));
    """)
    assert out["count"] == 1
    assert "second line" in out["from"]
    assert out["sure"] == "50% sure"


def test_the_quick_add_handler_reads_the_confidence_it_used_to_drop():
    """`Law 20` option 2 — the handler is a closure with a dozen free variables,
    so the scope is resolved and the assertion made inside it. The defect was
    that every other field of the same response was read here and this one was
    not."""
    src = CALENDAR_JS.read_text(encoding="utf-8")
    start = src.index("/api/calendar/quick-parse")
    end = src.index("_qaInput.addEventListener('keydown'", start)
    body = blank_text(src[start:end])
    for field in ("ev.summary", "ev.location", "ev.dtstart"):
        assert field in body, "the parsed fields moved; re-read this handler"
    assert re.search(r"noteQuickParseProvenance\(\s*text\s*,\s*data\.confidence\s*\)", body), (
        "the form fills itself in from a model and says nothing about it"
    )


def test_the_backend_really_does_send_a_confidence_and_no_model():
    """The premise under the row's split, read out of the handler rather than
    carried. The day `quick-parse` starts naming the model, this test says so
    and the note can name it too."""
    src = (ROOT / "routes" / "calendar_routes.py").read_text(encoding="utf-8")
    start = src.index('"You are a calendar event parser.')
    payload = src[src.index('"ok": True,', start):]
    payload = payload[:payload.index("\n    return router")]
    assert '"confidence"' in payload, "the number this row surfaces is no longer sent"
    assert '"model"' not in payload, (
        "quick-parse now names the model — the note can stop saying 'your model'"
    )


# ── the four that already have it, measured by what they render ─────────────

def test_memories_still_say_whether_a_model_or_a_person_wrote_them():
    body = js_function((JS / "memory.js").read_text(encoding="utf-8"),
                       "export function renderMemoryList")
    assert "memory-item-source" in body
    assert re.search(r"memory\.source === 'auto'", body)


def test_skills_still_name_the_model_that_wrote_or_audited_them():
    src = (JS / "skills.js").read_text(encoding="utf-8")
    source_pill = js_function(src, "function _sourcePill")
    assert "teacher-escalation" in source_pill and "teacher_model" in source_pill
    audit_pills = js_function(src, "function _auditModelPills")
    assert "audit_worker_model" in audit_pills and "audit_teacher_model" in audit_pills


def test_generated_images_still_carry_the_model_that_made_them():
    src = (JS / "gallery.js").read_text(encoding="utf-8")
    assert re.search(r"<label>Source</label>[\s\S]{0,80}img\.model", src), (
        "the gallery detail view no longer names the model"
    )


def test_research_reports_still_carry_the_model_that_ran_them():
    src = (JS / "research" / "panel.js").read_text(encoding="utf-8")
    assert "research-job-model" in src
    assert re.search(r"research-job-model[\s\S]{0,60}job\.modelName", src)


def test_the_two_tidy_endpoints_are_the_named_remainder():
    """Not a wish — the measurement behind the `[·]`. Both handlers hold the
    model in a local and answer without it, so each half is one key. When one of
    them starts sending it, this test is what says the client can read it."""
    sess = (ROOT / "routes" / "session_routes.py").read_text(encoding="utf-8")
    payload = sess[sess.index('"status": "ok",\n            "folders"'):]
    payload = payload[:payload.index("}")]
    assert '"model"' not in payload
    assert 'logger.info(f"Auto-sort: using model={model}' in sess, (
        "the model is in scope in the same handler — that is what makes it one key"
    )
    mem = (ROOT / "routes" / "memory" / "memory_routes.py").read_text(encoding="utf-8")
    audit = mem[mem.index('"before": result.get("before", 0),'):]
    audit = audit[:audit.index("}")]
    assert '"model"' not in audit
