# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1884` (`identifiers-cannot-be-mapped`) — a setting that picks which thing
a step acts on has a box, *Fill from an earlier step*, wherever the server
says it may be opened; ticking it offers *Insert a field…* and says what that
means; the step it hands over names what is open (`config.filled`).

**Measured before the fix:** an MCP argument like `priority`, an HTTP path, a
query value named `ticket_id` and a Wait's time were typed only, with the
classifier's reason, and nothing on the panel could open one — so "fetch the
item the webhook names" could not be drawn, and the save refused a reference
in any of them.

Driven (`Law 20`): the real `stepFields.js` and `argsForm.js` in node with
the DOM shim, the REAL palette (`workflow_effects.build_palette`: its
`openable` on the path, the time and the MCP arguments is the server's), a
person ticking and typing.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_each_step_form_round_trips_js import _case, box  # noqa: E402,F401

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_HELPERS = """
    const seen = [];
    const pickField = (input, { field, slot }) => { seen.push([field, slot ? slot.mapping : null]); return { destroy() {} }; };
    const lastSlot = (f) => { const s = seen.filter((x) => x[0] === f); return s.length ? s[s.length - 1][1] : null; };
    const boxOf = (h, f) => h.querySelectorAll('input').find((n) => n.dataset && n.dataset.opens === f) || null;
    const noteOf = (h, f) => h.querySelectorAll('p').find((n) => n.dataset && n.dataset.opens === f) || null;
    const tick = (el, on) => { el.checked = on; el.dispatchEvent({ type: 'change', target: el, stopPropagation() {}, preventDefault() {} }); };
    const offered = (h, f) => { const b = boxOf(h, f); return !!(b && !b.parentNode.hidden); };
"""


def test_an_mcp_argument_the_server_says_may_open_has_the_box(box):
    o = _case(box, _HELPERS + """
        const m = mount({ kind: 'mcp', label: 'Post', config: { tool: 'mcp__chat__send_message',
          args: { channel: '#ops', text: 'hi', priority: 2 } } }, { pickField });
        const boxes = ['args.priority', 'args.channel', 'args.text', 'args.meta', 'args.silent', 'args.mood']
          .map((f) => [f, !!boxOf(m.h, f)]);
        const before = { slot: lastSlot('args.priority'), note: noteOf(m.h, 'args.priority').hidden };
        tick(boxOf(m.h, 'args.priority'), true);
        const after = { slot: lastSlot('args.priority'), note: noteOf(m.h, 'args.priority').hidden,
          said: noteOf(m.h, 'args.priority').textContent };
        typed(byField(m.h, 'args.priority'), '{{ steps.start.data.level }}');
        m.done();
        const opened = m.got[0].config;
        const again = mount({ kind: 'mcp', label: 'Post', config: opened }, { pickField });
        const kept = { ticked: boxOf(again.h, 'args.priority').checked, slot: lastSlot('args.priority') };
        tick(boxOf(again.h, 'args.priority'), false);
        typed(byField(again.h, 'args.priority'), '3');
        again.done();
        out({ boxes, before, after, opened, kept, closed: again.got[0].config });
    """)
    assert o["boxes"] == [["args.priority", True], ["args.channel", False], ["args.text", False],
                          ["args.meta", False], ["args.silent", False], ["args.mood", False]], \
        "only an argument of one value whose name picks no one and nowhere"
    assert o["before"] == {"slot": "never", "note": True}
    assert o["after"]["slot"] == "value" and o["after"]["note"] is False
    assert "a webhook or a mail may have written it" in o["after"]["said"]
    assert o["opened"] == {"tool": "mcp__chat__send_message", "filled": ["args.priority"],
                           "args": {"channel": "#ops", "text": "hi", "priority": "{{ steps.start.data.level }}"}}
    assert o["kept"] == {"ticked": True, "slot": "value"}
    assert o["closed"]["filled"] == [] and o["closed"]["args"]["priority"] == 3


def test_an_http_path_opens_and_its_first_part_stays_typed(box):
    o = _case(box, _HELPERS + """
        const r = {};
        let m = mount({ kind: 'http', label: 'Close', config: { integration: 'int1', method: 'POST', path: '/items/1/close' } },
          { pickField });
        r.offered = offered(m.h, 'path');
        tick(boxOf(m.h, 'path'), true);
        r.slot = lastSlot('path');
        typed(byField(m.h, 'path'), '/items/{{ steps.start.data.id }}/close');
        m.done();
        r.config = m.got[0].config;
        m = mount({ kind: 'http', label: 'Close', config: { integration: 'int1', method: 'GET', path: '/x' } }, { pickField });
        tick(boxOf(m.h, 'path'), true);
        typed(byField(m.h, 'path'), '/{{ steps.start.data.id }}/close');
        m.done();
        r.head = [problemOf(m.h), m.got.length];
        m = mount({ kind: 'http', label: 'Close', config: { integration: 'int1', method: 'GET', path: '/x' } }, { pickField });
        m.done();
        r.untouched = m.got[0].config;
        out(r);
    """)
    assert o["offered"] is True and o["slot"] == "value"
    assert o["config"]["path"] == "/items/{{ steps.start.data.id }}/close"
    assert o["config"]["filled"] == ["path"]
    assert o["head"] == [["A path filled from an earlier step starts with a part you type, such as "
                          "/items/{{ steps.read.data.id }}.", "path"], 0]
    assert "filled" not in o["untouched"], "a step that opened nothing stays without the key"


def test_a_query_value_offers_the_box_once_the_rule_says_its_name_may_open(box):
    o = _case(box, _HELPERS + """
        const asked = [];
        const classify = async (node, field) => {
          const name = node.config.query ? node.config.query[0].name : node.config.body[0].name;
          asked.push(name);
          return { ok: true, mapping: 'never', why: 'Typed only: this could be an address or a command.',
            ...(name === 'ticket_id' ? { openable: true } : {}) };
        };
        const m = mount({ kind: 'http', label: 'Find', config: { integration: 'int1', method: 'GET', path: '/v1/find',
          query: [{ name: 'to', value: 'x' }, { name: 'ticket_id', value: '7' }] } }, { pickField, classify });
        await settle(20);
        const shown = { to: offered(m.h, 'query[0].value'), ticket: offered(m.h, 'query[1].value') };
        tick(boxOf(m.h, 'query[1].value'), true);
        const slot = lastSlot('query[1].value');
        typed(byField(m.h, 'query[1].value'), '{{ steps.start.data.ticket }}');
        // The row before it goes: what is open moves with its row.
        fire(m.h.querySelectorAll('.wf-sf-remove')[0], 'click');
        await settle(20);
        const moved = { ticked: boxOf(m.h, 'query[0].value').checked, name: byField(m.h, 'query[0].name').value };
        m.done();
        out({ shown, slot, moved, config: m.got[0].config, asked });
    """)
    assert o["shown"] == {"to": False, "ticket": True}
    assert o["slot"] == "value"
    assert o["moved"] == {"ticked": True, "name": "ticket_id"}
    assert o["config"]["query"] == [{"name": "ticket_id", "value": "{{ steps.start.data.ticket }}"}]
    assert o["config"]["filled"] == ["query[0].value"]


def test_a_wait_takes_its_time_from_an_earlier_step_when_ticked(box):
    o = _case(box, _HELPERS + """
        const r = {};
        let m = mount({ kind: 'wait', label: 'Hold', config: { mode: 'until', time: '08:00' } }, { pickField });
        r.offered = offered(m.h, 'time');
        typed(byField(m.h, 'time'), '{{ steps.start.data.when }}');
        m.done();
        r.unticked = [problemOf(m.h), m.got.length];
        tick(boxOf(m.h, 'time'), true);
        r.slot = lastSlot('time');
        r.note = noteOf(m.h, 'time').textContent;
        r.said = m.h.querySelector('.wf-sf-wait-said').textContent;
        m.done();
        r.config = m.got[0] && m.got[0].config;
        typed(byField(m.h, 'time'), 'soon');
        m.done();
        r.garbage = problemOf(m.h);
        m = mount({ kind: 'wait', label: 'Hold', config: { mode: 'until', time: '{{ steps.start.data.when }}', filled: ['time'] } },
          { pickField });
        changed(m.h.querySelector('select'), 'for');
        m.done();
        r.forAWhile = m.got[0].config;
        out(r);
    """)
    assert o["offered"] is True
    assert o["unticked"] == [["Write the time as HH:MM, such as 08:00.", "time"], 0]
    assert o["slot"] == "value"
    assert "a date and time such as 2026-11-08T09:00, at most 168 hours away" in o["note"]
    assert o["said"] == "It runs at the time an earlier step hands it, or as soon after as Pantheon is idle."
    assert o["config"] == {"mode": "until", "time": "{{ steps.start.data.when }}", "filled": ["time"]}
    assert o["garbage"] == ["Write the time as HH:MM, such as 08:00, or pick it from an earlier step.", "time"]
    assert o["forAWhile"]["mode"] == "for" and o["forAWhile"]["filled"] == []
