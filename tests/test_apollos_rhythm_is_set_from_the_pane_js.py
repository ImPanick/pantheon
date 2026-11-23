# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apollo's rhythm and voice in the pane, driven: what the main view says of
when Apollo speaks and how, and what each control asks the server.

What the rhythm does is the server's (`src/apollo/rhythm.py`, tested in
`test_apollos_rhythm_speaks_only_on_news`); these cases check the pane says
it plainly and sends the whole briefing list each time.

Driven under node: the real `apolloPane.js` and `apolloPaneModel.js` on the
shared DOM shim, the server faked by path.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_apollos_pane_shows_the_work_and_what_it_knows_js import _PREAMBLE, _SHIM, _STUBS  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PANE = ROOT / "static" / "js" / "apolloPane.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_RHYTHM = (
    "const M = await import('./apolloPaneModel.js');\n"
    "let RH = { briefings: [\n"
    "    { id: 'b1', name: 'First light', time: '07:00', enabled: true, next_run: null },\n"
    "    { id: 'b2', name: 'Briefing', time: '17:30', enabled: true, next_run: null }],\n"
    "  checkin_hours: 3, timezone: 'America/Anchorage', has_chat: true,\n"
    "  quiet: { start: '22:00', end: '07:00' }, last_spoke_at: null };\n"
    "routes['GET /api/apollo/tasks'] = () => [200, { tasks: [] }];\n"
    "routes['GET /api/apollo/spaces'] = () => [200, { spaces: [] }];\n"
    "routes['GET /api/apollo/rhythm'] = () => [200, RH];\n"
    "routes['PUT /api/apollo/rhythm'] = (m, u, b) => [200, RH];\n"
    "let VO = { warmth: 0, play: -1, preset: 'strategist', pushback: 'x',\n"
    "  presets: [{ id: 'apollo', name: 'Apollo' }, { id: 'razor', name: 'Razor' },\n"
    "            { id: 'strategist', name: 'Strategist' }, { id: 'spark', name: 'Spark' }],\n"
    "  nudges: [{ id: 'c1', words: 'Apollo made itself terser: They cut my replies short.' }],\n"
    "  held: { badge: 'needs-bigger', words: 'Needs a bigger model', model: 'qwen3:4b' } };\n"
    "routes['GET /api/apollo/voice'] = () => [200, VO];\n"
    "routes['PUT /api/apollo/voice'] = () => [200, VO];\n"
    "routes['POST /api/apollo/voice/undo/*'] = () => [200, VO];\n"
    "const puts = () => sent.filter((s) => s.method === 'PUT').map((s) => s.body);\n"
    "const sec = (title) => all(pane(), 'apo-sec').find((s) => text(all(s, 'apo-sec-t')[0]) === title);\n"
    "async function openRhythm() {\n"
    "  P.openApolloPane();\n"
    "  await settle();\n"
    "  button(sec('When Apollo speaks'), 'Briefings and check-ins').click();\n"
    "  await settle();\n"
    "}\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("apollorhythm"), PANE, _SHIM, _STUBS)


def _case(box, script):
    return _run(box, _PREAMBLE + _RHYTHM, script + "\nP.closeApolloPane();\n")


def test_the_main_view_says_when_apollo_speaks_in_one_line(box):
    o = _case(box, """
        P.openApolloPane();
        await settle();
        out({ line: text(all(sec('When Apollo speaks'), 'apo-empty')[0]) });
    """)
    assert o["line"] == ("First light at 07:00, and 1 more briefing. "
                         "Check-ins every 3 hours, only when something changed. Quiet 22:00 to 07:00.")


def test_the_rhythm_view_lists_the_briefings_and_moving_one_sends_the_whole_list(box):
    o = _case(box, """
        await openRhythm();
        const rows = all(sec('Briefings'), 'apo-brief').map((r) => [text(all(r, 'apo-brief-n')[0]),
          all(r, 'apo-time')[0].value]);
        const t = all(sec('Briefings'), 'apo-time')[1];
        t.value = '18:00';
        t.dispatchEvent(new Event('change'));
        await settle();
        out({ rows, put: puts()[0], said: toasts.slice(-1)[0],
              zone: all(pane(), 'apo-empty').map(text).find((x) => x.includes('Times are in')) });
    """)
    assert o["rows"] == [["First light", "07:00"], ["Briefing", "17:30"]]
    assert o["put"] == {"briefings": [{"id": "b1", "time": "07:00", "enabled": True},
                                      {"id": "b2", "time": "18:00", "enabled": True}]}
    assert o["said"] == "Moved."
    assert o["zone"].endswith("Times are in America/Anchorage.")


def test_pausing_removing_and_adding_a_briefing(box):
    o = _case(box, """
        await openRhythm();
        const box1 = all(all(sec('Briefings'), 'apo-brief')[0], 'apo-switch')[0].children[0];
        box1.checked = false;
        box1.dispatchEvent(new Event('change'));
        await settle();
        button(all(sec('Briefings'), 'apo-brief')[1], 'Remove').click();
        await settle();
        button(sec('Briefings'), 'Add a briefing').click();
        await settle();
        out({ puts: puts() });
    """)
    assert o["puts"] == [
        {"briefings": [{"id": "b1", "time": "07:00", "enabled": False},
                       {"id": "b2", "time": "17:30", "enabled": True}]},
        {"briefings": [{"id": "b1", "time": "07:00", "enabled": True}]},
        {"briefings": [{"id": "b1", "time": "07:00", "enabled": True},
                       {"id": "b2", "time": "17:30", "enabled": True},
                       {"time": "12:00", "enabled": True}]},
    ]


def test_check_ins_and_quiet_hours(box):
    o = _case(box, """
        await openRhythm();
        const pick = all(sec('Check-ins'), 'apo-select')[0];
        const labels = pick.children.map((x) => x.textContent);
        const chosen = pick.value;
        pick.value = '0';
        pick.dispatchEvent(new Event('change'));
        await settle();
        const form = all(sec('Quiet hours'), 'apo-quiet')[0];
        const [from, to] = all(form, 'apo-time');
        from.value = '23:00';
        submit(form);
        await settle();
        button(sec('Quiet hours'), 'No quiet hours').click();
        await settle();
        out({ labels, chosen, puts: puts(), said: toasts.slice(-3),
              spoke: all(sec('Check-ins'), 'apo-empty').map(text).slice(-1)[0] });
    """)
    assert o["labels"] == ["Off", "Every hour", "Every 2 hours", "Every 3 hours", "Every 4 hours",
                           "Every 6 hours", "Every 8 hours", "Every 12 hours"]
    assert o["chosen"] == "3"
    assert o["puts"] == [{"checkin_hours": 0},
                         {"quiet": {"start": "23:00", "end": "07:00"}},
                         {"quiet": {"start": None, "end": None}}]
    assert o["said"] == ["Check-ins are off.", "Quiet 23:00 to 07:00.", "Quiet hours are off."]
    assert o["spoke"] == "Apollo hasn’t spoken unasked yet."


def test_with_no_apollo_chat_the_view_says_why_and_offers_nothing_to_set(box):
    o = _case(box, """
        RH = { briefings: [], checkin_hours: 0, timezone: null, has_chat: false, quiet: {}, last_spoke_at: null };
        await openRhythm();
        out({ err: text(all(pane(), 'apo-error')[0]), selects: all(pane(), 'apo-select').length });
    """)
    assert o["err"] == "Open your Apollo chat once first, so Apollo has somewhere to speak."
    assert o["selects"] == 0


def test_the_model_helpers(box):
    o = _case(box, """
        const now = Date.parse('2026-11-23T12:00:00Z');
        out({
          none: M.rhythmLine({ briefings: [], checkin_hours: 0, quiet: {} }),
          paused: M.rhythmLine({ briefings: [{ name: 'First light', time: '07:00', enabled: false }], checkin_hours: 1, quiet: {} }),
          first: M.nextBriefingTime([]),
          next: M.nextBriefingTime([{ time: '07:00' }, { time: '12:00' }]),
          ago: [M.lastSpoke('2026-11-23T11:59:40Z', now), M.lastSpoke('2026-11-23T11:15:00Z', now),
                M.lastSpoke('2026-11-23T09:00:00Z', now), M.lastSpoke('2026-11-21T12:00:00Z', now)],
        });
    """)
    assert o["none"] == "No briefings set. No check-ins."
    assert o["paused"] == "No briefings set. Check-ins every hour, only when something changed."
    assert o["first"] == "07:00" and o["next"] == "13:00"
    assert o["ago"] == ["Apollo last spoke just now.", "Apollo last spoke 45 minutes ago.",
                        "Apollo last spoke 3 hours ago.", "Apollo last spoke 2 days ago."]


def test_the_voice_section_shows_the_dials_the_nudges_and_the_pushback_line(box):
    o = _case(box, """
        P.openApolloPane();
        await settle();
        const v = sec('Voice');
        const chips = all(v, 'apo-chip').map((b) => [b.textContent, b.getAttribute('aria-pressed')]);
        const dials = all(v, 'apo-range').map((r) => [r.getAttribute('aria-label'), r.value, r.getAttribute('aria-valuetext')]);
        const nudge = text(all(v, 'apo-nudge-t')[0]);
        const lines = all(v, 'apo-empty').map(text);
        sent.length = 0;
        button(v, 'Spark').click();
        await settle();
        const warm = all(sec('Voice'), 'apo-range')[0];
        warm.value = '2';
        warm.dispatchEvent(new Event('change'));
        await settle();
        button(sec('Voice'), 'Undo').click();
        await settle();
        out({ chips, dials, nudge, lines,
              asked: sent.filter((s) => s.method !== 'GET').map((s) => [s.method, s.url, s.body || null]),
              said: toasts.slice(-3) });
    """)
    assert o["chips"] == [["Apollo", "false"], ["Razor", "false"], ["Strategist", "true"], ["Spark", "false"]]
    assert o["dials"] == [["Terse to Warm", "0", "Apollo’s own"], ["Dry to Playful", "-1", "A little dry"]]
    assert o["nudge"] == "Apollo made itself terser: They cut my replies short."
    assert o["lines"] == ["Apollo still tells you when a plan has a hole or you’re wrong. No setting turns that off.",
                          "On qwen3:4b, Apollo sometimes caved when pushed. A bigger model holds better."]
    assert o["asked"] == [["PUT", "/api/apollo/voice", {"preset": "spark"}],
                          ["PUT", "/api/apollo/voice", {"warmth": 2}],
                          ["POST", "/api/apollo/voice/undo/c1", None]]
    assert o["said"] == ["Spark it is.", "Warm.", "Put back."]


def test_the_voice_helpers(box):
    o = _case(box, """
        out({ words: [-2, -1, 0, 1, 2].map((v) => M.dialWords('play', v)),
              held: [M.heldLine(null), M.heldLine({ model: 'm', badge: 'not-measured' }),
                     M.heldLine({ model: 'm', badge: 'runs-well' }), M.heldLine({ model: 'm', badge: 'runs-slowly' })] });
    """)
    assert o["words"] == ["Dry", "A little dry", "Apollo’s own", "A little playful", "Playful"]
    assert o["held"] == ["Pushback hasn’t been measured: no talk model is set.",
                         "Pushback hasn’t been measured on m yet.",
                         "On m, Apollo held its ground when pushed.",
                         "On m, Apollo held its ground when pushed."]


def test_an_offer_asks_in_needs_you_and_a_grant_can_be_taken_back(box):
    o = _case(box, """
        let TR = [
          { id: 't1', kind: 'mail reply', tool: 'send_email', state: 'offered',
            words: 'You’ve allowed send_email for mail reply 5 times in a row without a change. Should Apollo just do it for mail reply from now on?' },
          { id: 't2', kind: 'cert renewal', tool: 'bash', state: 'granted', words: 'Apollo just does bash for cert renewal.' },
          { id: 't3', kind: 'calendar move', tool: 'move_event', state: 'drafting', words: 'x' }];
        routes['GET /api/apollo/trust'] = () => [200, { trust: TR }];
        routes['POST /api/apollo/trust/*'] = () => [200, {}];
        routes['DELETE /api/apollo/trust/*'] = () => [200, {}];
        P.openApolloPane();
        await settle();
        const offer = all(sec('Needs you'), 'apo-offer')[0];
        const q = text(all(offer, 'apo-q')[0]);
        const just = all(sec('Apollo just does'), 'apo-nudge-t').map(text);
        const asked = () => sent.filter((s) => s.method !== 'GET').map((s) => [s.method, s.url, s.body || null]);
        sent.length = 0;
        button(offer, 'Just do it').click();
        await settle();
        button(all(sec('Needs you'), 'apo-offer')[0], 'Not now').click();
        await settle();
        button(sec('Apollo just does'), 'Ask me again').click();
        await settle();
        const out1 = asked();
        TR = [];
        P.closeApolloPane();
        P.openApolloPane();
        await settle();
        out({ q, just, asked: out1, said: toasts.slice(-3), gone: [!!sec('Needs you'), !!sec('Apollo just does')] });
    """)
    assert o["q"].startswith("You’ve allowed send_email for mail reply 5 times")
    assert o["just"] == ["Apollo just does bash for cert renewal."]
    assert o["asked"] == [["POST", "/api/apollo/trust/t1", {"answer": "yes"}],
                          ["POST", "/api/apollo/trust/t1", {"answer": "no"}],
                          ["DELETE", "/api/apollo/trust/t2", None]]
    assert o["said"] == ["Apollo will just do send_email for mail reply. Take it back any time.",
                         "Not now. Apollo keeps asking.",
                         "Apollo will ask before bash for cert renewal again."]
    assert o["gone"] == [False, False]
