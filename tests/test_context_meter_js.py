# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P12-09` / `B752` — the context budget, where the message is being written.

`P12` made six character budgets into policy and gave them an API. It gave them
no way to see yourself hitting one: a person discovered the ceiling by being
refused. This is the surface half — a meter above the send button — and the
whole-turn endpoint that feeds it.

**Why the endpoint and the meter are in one commit, which is the general lesson
`B752` records.** `.pantheon/check-unreachable.py` holds a ceiling of 90 routes
with no frontend caller. `GET /api/upload/context-budget` alone took it to 91
and the gate went red when `P12-09`'s backend half tried to ship on its own; the
two honest-looking ways out are both wrong (adding it to `ALLOWED` claims a
caller that is not the frontend when the frontend is exactly the caller, and
raising the ceiling is widening a ratchet to fit one's own unwired half). So the
ratchet makes a backend-first split unshippable **by construction**, which is the
ratchet working. It lands with its caller or not at all.

What is pinned, and why each is a defect if it breaks:

  * **the ceiling and the layer that set it are on screen before anything is
    attached.** *"You have 3,000 characters"* and *"your role gives you 3,000
    characters"* are different sentences and only the second tells a person who
    to ask;
  * **the four unmeasured segments are hatched, never blank.** They say
    `measured: false` on the wire because they are assembled in
    `src/agent_loop.py` (`B750`, `B751`), and a bar reading 5% full when the real
    figure is unknown teaches the opposite of what the meter is for — `Law 10`'s
    polarity incident drawn as a bar chart;
  * **the three attachment states are three things on the screen**, and an
    omitted file says *"no room in this message"* in words rather than only in a
    strike-through, which survives neither greyscale nor a screen reader;
  * **`clamped` is said out loud.** Showing the smaller number in silence is how
    an operator concludes their setting did not save;
  * **an unreachable endpoint leaves the composer alone.** Nothing the person
    did failed, so nothing is shouted at them;
  * **the endpoint measures the real spend rather than a second computation of
    it**, and somebody else's upload id measures as nothing;
  * **the route has a caller in `static/`, and the ceiling is still 90.**
"""

import asyncio
import json
import os
import shutil
import types
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.helpers.source_text import blank  # B290

ROOT = Path(__file__).resolve().parents[1]
FILE_HANDLER = ROOT / "static" / "js" / "fileHandler.js"
INDEX = ROOT / "static" / "index.html"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


# ── the payload, written out rather than imported ───────────────────────────
# `context_window_report()`'s shape, pinned here so this file tests the contract
# the browser is built against rather than whatever Python returns today.

def _report(**over):
    report = {
        "ceiling_key": "context_attachment_total_chars",
        "budgets": [
            {"key": "context_attachment_total_chars",
             "label": "Total characters all attachments in one message may use",
             "chars": 24000, "source": "default", "clamped": False,
             "is_ceiling": True},
            {"key": "context_text_file_chars", "label": "One text or code attachment",
             "chars": 24000, "source": "setting", "clamped": True, "is_ceiling": False},
        ],
        "segments": [
            {"key": "system", "label": "System prompt", "measured": False},
            {"key": "skills", "label": "Skills", "measured": False},
            {"key": "memory", "label": "Retrieved memory", "measured": False},
            {"key": "attachments", "label": "Attachments", "measured": True,
             "chars": 6000, "tokens": 1500, "budget_chars": 24000,
             "remaining_chars": 18000,
             "items": [{"id": "a", "name": "notes.txt", "chars": 6000, "state": "full"}]},
            {"key": "history", "label": "Conversation history", "measured": False},
        ],
        "measured_segments": ["attachments"],
        "unmeasured_reason": ("system, skills, memory and history are assembled in "
                              "src/agent_loop.py and are not yet emitted per turn "
                              "— see P12-09, B750 and B751."),
    }
    report.update(over)
    return report


_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

// The composer, as `static/index.html` ships it: the strip the module already
// draws into, and the meter beside it.
const strip = document.body.appendChild(new Node('div'));
strip.setAttribute('id', 'attach-strip');
const meter = document.body.appendChild(new Node('div'));
meter.setAttribute('id', 'context-meter');
meter.hidden = true;
export { strip, meter };

/** Every URL the module asked for, and what each was answered with. */
export const asked = [];
export function serve(body, ok = true, status = 200) {
  globalThis.fetch = async (url) => {
    asked.push(String(url));
    return { ok, status, json: async () => body };
  };
}
serve({});

export function tick(n = 8) {
  let p = Promise.resolve();
  for (let i = 0; i < n; i++) p = p.then(() => new Promise((r) => setTimeout(r, 0)));
  return p;
}

/** What the meter says, read off the screen. */
export function readMeter() {
  if (meter.hidden) return { hidden: true };
  const text = (sel) => { const n = meter.querySelector(sel); return n ? n.textContent : null; };
  const bar = meter.querySelector('.context-meter-bar');
  const fill = meter.querySelector('.context-meter-fill');
  const hatch = meter.querySelector('.context-meter-unmeasured');
  return {
    hidden: false,
    readable: meter.readable,
    figure: text('.context-meter-figure'),
    source: text('.context-meter-source'),
    clamped: text('.context-meter-clamped'),
    unmeasuredNote: text('.context-meter-unmeasured-note'),
    empty: text('.context-meter-empty'),
    barLabel: bar ? bar.getAttribute('aria-label') : null,
    fillWidth: fill ? fill.style.width : null,
    hatchWidth: hatch ? hatch.style.width : null,
    hatchTitle: hatch ? hatch.title : null,
    chips: meter.querySelectorAll('.context-chip').map((c) => ({
      name: c.querySelector('.context-chip-name').textContent,
      // Raw `_html`: '' if and only if the renderer used `textContent`. A
      // filename is a string the person who uploaded it chose.
      nameHtml: c.querySelector('.context-chip-name')._html,
      note: c.querySelector('.context-chip-note').textContent,
      classes: String(c.className || '').split(/\s+/).filter(Boolean),
    })),
  };
}
"""

_STUBS = {
    "ui.js": """
export default {
  esc: (s) => String(s == null ? '' : s), showToast: () => {}, showError: () => {},
  showUploadRejections: () => {}, el: (id) => document.getElementById(id),
};
""",
    "spinner.js": """
export function createWhirlpool(){ return { element: { style: {} }, destroy(){} }; }
export default {
  create: () => ({ createElement: () => document.createElement('span'),
                   start(){}, stop(){} }),
};
""",
}

_PREAMBLE = (
    "import { document, meter, strip, asked, serve, tick, readMeter }"
    " from './shim.js';\n"
    "const fh = await import('./fileHandler.js');\n"
)


@pytest.fixture(scope="module")
def meter_sandbox(tmp_path_factory):
    return _make_sandbox(
        tmp_path_factory.mktemp("ctxmeter"), FILE_HANDLER, _SHIM, _STUBS
    )


def _meter(sandbox, report, script="", *, ok=True):
    return _run(sandbox, _PREAMBLE, """
        serve(%s, %s);
        fh.init('');
        await tick();
        %s
        console.log(JSON.stringify({ meter: readMeter(), asked }));
    """ % (json.dumps(report), "true" if ok else "false", script))


# ── the meter ───────────────────────────────────────────────────────────────

def test_the_ceiling_is_on_screen_before_anything_is_attached(meter_sandbox):
    """The row's whole point: *make the context budget visible while you work,
    not in a settings tab*. Nothing has been attached and there is still a
    number and a denominator."""
    out = _meter(meter_sandbox, _report())
    assert out["meter"]["hidden"] is False, "the composer drew no meter at all"
    assert "24,000 characters" in out["meter"]["figure"], out["meter"]["figure"]
    assert any("/api/upload/context-budget" in url for url in out["asked"]), out["asked"]


def test_the_ceiling_says_who_set_it(meter_sandbox):
    """*"You have 3,000 characters"* and *"your role gives you 3,000
    characters"* are different sentences, and only the second one tells a person
    who to ask."""
    seen = {}
    for source in ("role", "setting", "default"):
        report = _report()
        report["budgets"][0] = dict(report["budgets"][0], source=source, chars=3000)
        seen[source] = _meter(meter_sandbox, report)["meter"]["source"]
    assert "role" in seen["role"].lower(), seen["role"]
    assert len(set(seen.values())) == 3, f"the three layers read the same: {seen}"
    for sentence in seen.values():
        assert "3,000 characters" in sentence, sentence


def test_the_unmeasured_segments_are_hatched_and_never_empty_space(meter_sandbox):
    """Four of the five segments say `measured: false`. A bar that draws them as
    empty reads as headroom, which is the opposite of what a person needs to
    know — and it is `Law 10`'s polarity incident in a bar chart."""
    out = _meter(meter_sandbox, _report())["meter"]
    assert out["hatchWidth"] == "75%", out["hatchWidth"]
    assert out["fillWidth"] == "25%", out["fillWidth"]
    assert "src/agent_loop.py" in out["hatchTitle"], out["hatchTitle"]
    assert out["unmeasuredNote"] is not None, "nothing on screen says four are missing"
    for label in ("System prompt", "Skills", "Retrieved memory", "Conversation history"):
        assert label in out["unmeasuredNote"], out["unmeasuredNote"]
    assert "not measured" in out["unmeasuredNote"]


def test_a_report_where_everything_was_measured_draws_no_hatching(meter_sandbox):
    """The hatching has to mean something. A meter that hatches unconditionally
    is decoration, and the next agent reading it would learn nothing from it."""
    report = _report()
    report["segments"] = [s for s in report["segments"] if s["measured"]]
    report["unmeasured_reason"] = ""
    out = _meter(meter_sandbox, report)["meter"]
    assert out["hatchWidth"] is None, "an all-measured report still drew a hatched remainder"
    assert out["unmeasuredNote"] is None


def test_the_three_attachment_states_are_three_things_on_the_screen(meter_sandbox):
    """A file that fit, a file cut to what was left, and a file the turn had no
    room for are three different things to draw. The words carry it, because a
    strike-through survives neither greyscale nor a screen reader."""
    report = _report()
    report["segments"][3]["items"] = [
        {"id": "a", "name": "notes.txt", "chars": 6000, "state": "full"},
        {"id": "b", "name": "server.log", "chars": 4000, "state": "truncated"},
        {"id": "c", "name": "dump.sql", "chars": 120, "state": "omitted"},
    ]
    chips = _meter(meter_sandbox, report)["meter"]["chips"]
    assert [c["name"] for c in chips] == ["notes.txt", "server.log", "dump.sql"]
    notes = [c["note"] for c in chips]
    assert len(set(notes)) == 3, f"the three states read the same: {notes}"
    assert "25%" in notes[0], notes[0]
    assert "4,000 characters fit" == notes[1], notes[1]
    assert notes[2] == "no room in this message", notes[2]
    assert "context-chip-omitted" in chips[2]["classes"]
    assert "context-chip-truncated" in chips[1]["classes"]


def test_a_filename_reaches_the_chip_as_text_and_never_as_markup(meter_sandbox):
    """The name is whatever the person called the file, echoed back to them."""
    report = _report()
    hostile = '<img src=x onerror="alert(1)">.txt'
    report["segments"][3]["items"] = [
        {"id": "a", "name": hostile, "chars": 10, "state": "full"}]
    chips = _meter(meter_sandbox, report)["meter"]["chips"]
    assert chips[0]["nameHtml"] == ""
    assert chips[0]["name"] == hostile


def test_a_clamped_budget_says_it_was_reduced(meter_sandbox):
    """`clamped: true` means the number shown is not the number somebody asked
    for. Showing the smaller figure in silence is how an operator concludes the
    setting did not save."""
    out = _meter(meter_sandbox, _report())["meter"]
    assert out["clamped"] is not None, "a clamped budget was drawn as if it were the ask"
    assert "reduced" in out["clamped"], out["clamped"]
    clean = _report()
    clean["budgets"] = [clean["budgets"][0]]
    assert _meter(meter_sandbox, clean)["meter"]["clamped"] is None


def test_an_empty_composer_says_so_rather_than_drawing_nothing(meter_sandbox):
    """Zero attachments spending zero characters is a measurement, and it is not
    the same statement as "nobody counted"."""
    report = _report()
    report["segments"][3].update({"chars": 0, "items": [], "remaining_chars": 24000})
    out = _meter(meter_sandbox, report)["meter"]
    assert out["empty"] == "No attachments in this message", out["empty"]
    assert out["fillWidth"] == "0%"


def test_an_unreachable_endpoint_leaves_the_composer_alone(meter_sandbox):
    """Nothing the person did failed. A meter that could not be read is not an
    error to shout about, and the previous answer is not replaced by a blank."""
    out = _meter(meter_sandbox, {"detail": "nope"}, ok=False)
    assert out["meter"]["hidden"] is True, (
        "a failed budget read drew a meter with an invented denominator"
    )


def test_a_payload_with_no_ceiling_draws_nothing(meter_sandbox):
    """A denominator this browser made up is worse than no meter."""
    report = _report()
    report["budgets"] = [dict(report["budgets"][1])]
    assert _meter(meter_sandbox, report)["meter"]["hidden"] is True


def test_the_upload_response_is_read_without_a_second_request(meter_sandbox):
    """The breakdown rides `POST /api/upload`'s response because that request is
    what changed the answer. A composer that fetched again would be asking a
    second time for something it was just handed."""
    report = _report()
    out = _run(meter_sandbox, _PREAMBLE, """
        serve(%s);
        fh.init('');
        await tick();
        const before = asked.length;
        fh.noteContextBudget(%s, ['x']);
        await tick();
        console.log(JSON.stringify({
          meter: readMeter(), extra: asked.length - before, ids: fh.getContextMeasuredIds(),
        }));
    """ % (json.dumps(_report()), json.dumps(report)))
    assert out["extra"] == 0, "the composer re-fetched what the upload already told it"
    assert out["ids"] == ["x"]
    assert out["meter"]["hidden"] is False


# ── the endpoint ────────────────────────────────────────────────────────────

class _Handler:
    def __init__(self, uploads, upload_dir, permissive=False):
        self.uploads = uploads
        self.upload_dir = upload_dir
        self.permissive = permissive

    def resolve_upload(self, fid, owner=None):
        entry = self.uploads.get(fid)
        if entry is None and self.permissive:
            # A handler that resolves whatever id it is handed, which is what
            # makes `validate_upload_id` load-bearing rather than decorative: it
            # is the only thing standing between the query string and a path.
            path = os.path.join(self.upload_dir, fid)
            if not os.path.exists(path):
                return None
            entry = {"path": path, "name": os.path.basename(fid),
                     "mime": "text/plain", "owner": None}
        if entry is None or (owner is not None and entry.get("owner") not in (None, owner)):
            return None
        return entry

    def _inside_upload_dir(self, path):
        return True

    def is_image_file(self, *_a):
        return False

    def is_audio_file(self, *_a):
        return False

    def is_document_file(self, *_a):
        return True

    def validate_upload_id(self, fid):
        return bool(fid) and "/" not in fid and ".." not in fid


def _endpoint(handler):
    import routes.upload_routes as up
    router, _ = up.setup_upload_routes(handler)
    paths = [getattr(r, "path", None) for r in router.routes]
    index = {p: i for i, p in enumerate(paths) if p}
    # `B53`, same router: `GET /{file_id}` is a catch-all FastAPI matches in
    # declaration order, so below it this path resolves as a file id.
    assert index["/api/upload/context-budget"] < index["/api/upload/{file_id}"], (
        "the whole-turn route is declared below the catch-all and can never be "
        f"reached: {paths}"
    )
    return next(r.endpoint for r in router.routes
                if getattr(r, "path", None) == "/api/upload/context-budget")


def _request(user="bob"):
    return types.SimpleNamespace(
        client=types.SimpleNamespace(host="1.2.3.4"),
        state=types.SimpleNamespace(current_user=user),
        app=types.SimpleNamespace(state=types.SimpleNamespace(auth_manager=None)),
    )


def _upload(tmp_path, name, body, owner=None):
    (tmp_path / name).write_text(body, encoding="utf-8")
    return {"path": str(tmp_path / name), "name": name, "mime": "text/plain",
            "owner": owner}


def test_the_whole_turn_endpoint_measures_the_set_it_is_given(tmp_path):
    """The case `B752` exists for: `POST /api/upload` answers for the files in
    *that* request, and a composer holding attachments from two requests has no
    single request to read the turn's cost off."""
    handler = _Handler({"a": _upload(tmp_path, "a.txt", "A" * 5000),
                        "b": _upload(tmp_path, "b.txt", "B" * 7000)}, str(tmp_path))
    out = asyncio.run(_endpoint(handler)(_request(), ids="a,b"))
    attachments = next(s for s in out["segments"] if s["key"] == "attachments")
    assert attachments["measured"] is True
    assert [i["name"] for i in attachments["items"]] == ["a.txt", "b.txt"]
    assert attachments["chars"] >= 12000, attachments
    ceiling = next(b for b in out["budgets"] if b["is_ceiling"])
    assert ceiling["chars"] == 24000 and ceiling["source"] == "default"


def test_no_ids_is_a_measured_zero_and_not_an_unmeasured_blank(tmp_path):
    """"No attachments in this message" and "nobody counted" are different
    things to draw (`Law 10`), and the composer needs the first one from its
    first paint."""
    out = asyncio.run(_endpoint(_Handler({}, str(tmp_path)))(_request(), ids=""))
    attachments = next(s for s in out["segments"] if s["key"] == "attachments")
    assert attachments["measured"] is True
    assert attachments["chars"] == 0 and attachments["items"] == []
    assert out["measured_segments"] == ["attachments"]


def test_the_four_unmeasured_segments_still_say_so(tmp_path):
    out = asyncio.run(_endpoint(_Handler({}, str(tmp_path)))(_request(), ids=""))
    unmeasured = [s["key"] for s in out["segments"] if not s["measured"]]
    assert unmeasured == ["system", "skills", "memory", "history"]
    assert "agent_loop" in out["unmeasured_reason"]


def test_somebody_elses_upload_measures_as_nothing(tmp_path):
    """Ownership is enforced one layer down, by the resolver every other reader
    of an upload already goes through — not by a check written a second time
    here."""
    handler = _Handler({"mine": _upload(tmp_path, "m.txt", "M" * 3000, owner="bob"),
                        "theirs": _upload(tmp_path, "t.txt", "T" * 9000, owner="eve")},
                       str(tmp_path))
    out = asyncio.run(_endpoint(handler)(_request("bob"), ids="mine,theirs"))
    attachments = next(s for s in out["segments"] if s["key"] == "attachments")
    assert [i["name"] for i in attachments["items"]] == ["m.txt"], attachments["items"]


def test_a_malformed_id_is_dropped_rather_than_followed(tmp_path):
    """`validate_upload_id` is the only thing between the query string and a
    path, so the handler under this case resolves whatever it is handed — a
    check that only ever sees ids a fake refuses anyway proves nothing."""
    inside = tmp_path / "uploads"
    inside.mkdir()
    (tmp_path / "outside.txt").write_text("S" * 5000, encoding="utf-8")
    handler = _Handler({"ok": _upload(inside, "ok.txt", "K" * 100)},
                       str(inside), permissive=True)
    out = asyncio.run(_endpoint(handler)(_request(), ids="../outside.txt, ,ok"))
    attachments = next(s for s in out["segments"] if s["key"] == "attachments")
    assert [i["name"] for i in attachments["items"]] == ["ok.txt"], attachments["items"]


# ── the ratchet ─────────────────────────────────────────────────────────────

def test_the_route_has_a_caller_in_static_and_the_markup_has_a_home_for_it():
    """`B752`'s own `Verify:` line. This is what makes the endpoint shippable:
    the checker counts routes with no frontend caller, and the composer's fetch
    is the caller. The pairing is asserted here rather than left to CI so the
    reason survives next to the code that depends on it.

    A substring search is the right tool for exactly this: the question is
    whether a literal path appears anywhere in the frontend, which is the same
    question `check-unreachable.py` asks.
    """
    js = FILE_HANDLER.read_text(encoding="utf-8")
    assert "/api/upload/context-budget" in js, (
        "nothing in the composer names the route, so `check-unreachable.py` "
        "counts it as unreached and the ceiling goes to 91"
    )
    assert 'id="context-meter"' in INDEX.read_text(encoding="utf-8"), (
        "the meter has no element in the shipped markup, so `check-wiring.py` "
        "counts the lookup as unresolved"
    )


def test_the_ratchets_caller_is_the_fetch_and_not_the_prose_around_it():
    """Measured 2026-09-18, and it was nearly the other way round.

    `check-unreachable.py` normalises every template hole to `*`, so a fetch
    written `` `${API_BASE}/api/upload/context-budget${query}` `` normalises to
    `*/api/upload/context-budget*` and does **not** match the route's pattern.
    The route was reached anyway — by the two `` `GET /api/upload/context-budget` ``
    mentions in this module's own comments, which the checker's `_URLISH` regex
    cannot tell from a URL, because a backtick is a backtick. That is `Law 20`'s
    first incident — a source file is code and prose about code interleaved —
    happening to a ratchet rather than to a test, and it means a tidy-up of the
    comments would silently take the ceiling to 91.

    So the claim is checked with the comments blanked, through the checker's own
    normaliser rather than a second copy of it (`Law 14`).
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_check_unreachable", ROOT / ".pantheon" / "check-unreachable.py")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)

    code = blank(FILE_HANDLER)          # `B290`'s one comment blanker
    patterns = set()
    for match in checker._URLISH.findall(code):
        index = match.find("/api/")
        patterns.add(checker.normalise(match[index:] if index >= 0 else match))
    wanted = checker.normalise("/api/upload/context-budget")
    assert wanted in patterns, (
        f"with the comments blanked the composer names no route the checker "
        f"resolves to {wanted}; it found {sorted(p for p in patterns if 'upload' in p)}"
    )
