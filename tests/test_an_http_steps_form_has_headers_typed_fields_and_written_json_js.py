# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1885` (`http-body-strings-no-headers`) — the HTTP step's panel shows its
headers, says what each body field is sent as, takes JSON written whole, and
says what the step hands on.

**Measured before the fix:** `buildHttp` drew no headers at all, so a header a
file brought in was sent unseen and could not be removed — and the import's
own need ("sends the header “X-Auth-Token”, and a file never carries its
value. Type it on the step.") pointed at a box that did not exist. Every body
value was written as `String(value)`, there was no body but fields, and no
way to hand on the answer's status or headers.

Driven (`Law 20`): the real `stepFields.js` in node with the DOM shim, opened
and pressed as a person does, with the real palette.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_each_step_form_round_trips_js import _case, box  # noqa: E402,F401

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def test_the_headers_are_listed_typed_only_and_a_key_is_hidden(box):
    o = _case(box, """
        const seen = [];
        const pickField = (input, { field, slot }) => { seen.push([field, slot ? slot.mapping : null, slot ? slot.why : null]); return null; };
        const m = mount({ kind: 'http', label: 'Call', config: { integration: 'int1', method: 'GET', path: '/x',
          headers: [{ name: 'Accept', value: 'application/json' }, { name: 'X-Api-Key', value: 'k-123' }] } }, { pickField });
        const shown = ['headers[0].value', 'headers[1].value'].map((f) => byField(m.h, f).type);
        typed(byField(m.h, 'headers[0].name'), 'Authorization');
        const renamed = byField(m.h, 'headers[0].value').type;
        fire(m.h.querySelectorAll('.wf-sf-add').find((b) => b.textContent === 'Add a header'), 'click');
        typed(byField(m.h, 'headers[2].name'), 'X-Request-Source');
        typed(byField(m.h, 'headers[2].value'), 'pantheon');
        m.done();
        out({ shown, renamed, seen, config: m.got[0] && m.got[0].config });
    """)
    assert o["shown"] == ["text", "password"], "a value whose name says it is a key is hidden"
    assert o["renamed"] == "password"
    assert o["config"]["headers"] == [{"name": "Authorization", "value": "application/json"},
                                      {"name": "X-Api-Key", "value": "k-123"},
                                      {"name": "X-Request-Source", "value": "pantheon"}]
    values = [s for s in o["seen"] if s[0].startswith("headers[") and s[0].endswith(".value")]
    assert values and all(s[1] == "never" for s in values), "a header is never filled from a step"
    from src.workflow_slots import WHY_WHERE
    assert values[0][2] == WHY_WHERE


def test_a_header_a_file_brought_in_is_said_on_its_own_box(box):
    o = _case(box, """
        const m = mount({ kind: 'http', label: 'Call', config: { integration: 'int1', method: 'GET', path: '/x',
          headers: [{ name: 'X-Auth-Token', value: '' }] } },
          { needs: [{ field: 'headers[0].value', name: 'X-Auth-Token' }] });
        const need = m.h.querySelector('.wf-sf-need');
        // The need line carries the field's name too; the box is the other one.
        const box = m.h.querySelectorAll('[data-field]').find((n) => n.dataset.field === 'headers[0].value' && n !== need);
        out({ field: need && need.dataset.field, beside: !!(need && box && need.parentNode === box.parentNode) });
    """)
    assert o == {"field": "headers[0].value", "beside": True}


def test_a_body_field_says_what_it_is_sent_as_and_the_answer_can_be_handed_on_whole(box):
    o = _case(box, """
        const m = mount({ kind: 'http', label: 'Light', config: { integration: 'int1', method: 'POST', path: '/api/services/light',
          body: [{ name: 'brightness', value: '128', type: 'number' }, { name: 'text', value: 'hi' }], body_mode: 'json' } });
        const sentAs = byField(m.h, 'body[0].type').value;
        changed(byField(m.h, 'body[1].type'), 'yes/no');
        typed(byField(m.h, 'body[1].value'), 'yes');
        changed(byField(m.h, 'response'), 'full');
        m.done();
        out({ sentAs, config: m.got[0].config });
    """)
    assert o["sentAs"] == "number"
    assert o["config"]["body"] == [{"name": "brightness", "value": "128", "type": "number"},
                                   {"name": "text", "value": "yes", "type": "yes/no"}]
    assert o["config"]["response"] == "full" and o["config"]["body_mode"] == "json"
    assert "raw_body" not in o["config"] and "headers" not in o["config"], \
        "a key the step did not have and was not given is not added"


def test_json_written_whole_is_sent_and_switching_back_drops_it(box):
    o = _case(box, """
        let m = mount({ kind: 'http', label: 'Post', config: { integration: 'int1', method: 'POST', path: '/x',
          body: [{ name: 'text', value: 'old' }], body_mode: 'json' } });
        const hiddenAtFirst = byField(m.h, 'raw_body').parentNode.hidden;
        changed(byField(m.h, 'body_mode'), 'raw');
        typed(byField(m.h, 'raw_body'), '{"title": "Daily", "text": "{{ steps.read.text }}", "priority": 4}');
        m.done();
        const raw = m.got[0].config;
        m = mount({ kind: 'http', label: 'Post', config: raw });
        const shownAgain = byField(m.h, 'raw_body').value;
        changed(byField(m.h, 'body_mode'), 'json');
        m.done();
        out({ hiddenAtFirst, raw, shownAgain, back: m.got[0].config });
    """)
    assert o["hiddenAtFirst"] is True
    assert o["raw"]["body_mode"] == "raw" and o["raw"]["body"] == []
    assert o["raw"]["raw_body"] == {"title": "Daily", "text": "{{ steps.read.text }}", "priority": 4}
    assert json.loads(o["shownAgain"]) == o["raw"]["raw_body"]
    assert o["back"]["body_mode"] == "json" and "raw_body" not in o["back"]


def test_the_form_refuses_in_words_on_the_field(box):
    o = _case(box, """
        const r = {};
        const base = { integration: 'int1', method: 'POST', path: '/x' };
        let m = mount({ kind: 'http', label: 'A', config: { ...base, body: [{ name: 'brightness', value: 'bright', type: 'number' }] } });
        m.done(); r.number = [problemOf(m.h), m.got.length];
        m = mount({ kind: 'http', label: 'A', config: { ...base, body: [{ name: 'enabled', value: 'maybe', type: 'yes/no' }] } });
        m.done(); r.yesno = [problemOf(m.h), m.got.length];
        m = mount({ kind: 'http', label: 'A', config: { ...base, body: [{ name: 'hs', value: '[300,', type: 'json' }] } });
        m.done(); r.json = [problemOf(m.h), m.got.length];
        m = mount({ kind: 'http', label: 'A', config: { ...base, body_mode: 'raw', raw_body: { a: 1 } } });
        typed(byField(m.h, 'raw_body'), '{"text": {{ steps.read.text }}}');
        m.done(); r.raw = [problemOf(m.h), m.got.length];
        m = mount({ kind: 'http', label: 'A', config: { ...base, body_mode: 'raw', raw_body: { a: 1 } } });
        typed(byField(m.h, 'raw_body'), '"just text"');
        m.done(); r.scalar = [problemOf(m.h), m.got.length];
        m = mount({ kind: 'http', label: 'A', config: { ...base, headers: [{ name: 'Accept', value: 'a' }, { name: 'accept', value: 'b' }] } });
        m.done(); r.twice = [problemOf(m.h), m.got.length];
        m = mount({ kind: 'http', label: 'A', config: { ...base, headers: [{ name: 'My Header', value: 'a' }] } });
        m.done(); r.spaced = [problemOf(m.h), m.got.length];
        out(r);
    """)
    assert o["number"] == [["“brightness” is sent as a number, and “bright” is not one.", "body[0].value"], 0]
    assert o["yesno"] == [["“enabled” is sent as yes or no: write yes or no.", "body[0].value"], 0]
    assert o["json"] == [["“hs” is sent as JSON, and what is written is not JSON.", "body[0].value"], 0]
    assert o["raw"] == [['This is not JSON. A reference goes inside quotes, such as "text": '
                         '"{{ steps.read.text }}".', "raw_body"], 0]
    assert o["scalar"] == [["Write a JSON object { … } or a list [ … ].", "raw_body"], 0]
    assert o["twice"] == [["“accept” is sent twice. Each header once.", "headers[1].name"], 0]
    assert o["spaced"] == [["A header’s name is letters, digits and - with no spaces, such as Accept.",
                            "headers[0].name"], 0]


def test_what_the_form_writes_the_rule_takes_and_the_renderer_sends(box):
    """The config the panel hands over is one `validate_document` accepts and
    `render_call` sends with each value as its type."""
    o = _case(box, """
        const m = mount({ kind: 'http', label: 'Light', config: { integration: 'int1', method: 'POST', path: '/api/services/light' } });
        fire(m.h.querySelectorAll('.wf-sf-add').find((b) => b.textContent === 'Add a body field'), 'click');
        typed(byField(m.h, 'body[0].name'), 'brightness');
        changed(byField(m.h, 'body[0].type'), 'number');
        typed(byField(m.h, 'body[0].value'), '128');
        fire(m.h.querySelectorAll('.wf-sf-add').find((b) => b.textContent === 'Add a header'), 'click');
        typed(byField(m.h, 'headers[0].name'), 'Accept');
        typed(byField(m.h, 'headers[0].value'), 'application/json');
        m.done();
        out(m.got[0]);
    """)
    from src import workflow_document as wd
    from src import workflow_slots as ws
    from tests.test_a_destination_is_never_mapped import RES
    node = {"id": "light", "kind": "http", "label": o["label"], "config": dict(o["config"], integration="miniflux"),
            "position": None, "pinned": None}
    graph = wd.parse_graph({"v": 1, "nodes": [node], "edges": []})
    assert wd.validate_document(graph, owner="alice", tasks_by_id={}, crew_ids=set(),
                                owner_is_admin=True, own_task_id="t", resources=RES) is None
    sent = json.loads(ws.render_call(node, {"steps": {}}).content)
    assert sent["body"] == {"brightness": 128}
    assert sent["headers"] == {"Accept": "application/json"}
