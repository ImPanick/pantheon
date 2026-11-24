# SPDX-License-Identifier: AGPL-3.0-or-later
"""A task's own chat, driven: the person talks to the agent doing the work.

The outline's fourth layer (*Surfaces*, "Task chat"): *Chat with this agent*
opens a second chat bound to the task's lead, under the report in the pane or
popped out into its own window; what the person types goes to that lead only,
and Apollo gets one line about it. The lead's approvals show in that chat and
in the pane's Needs you. The pane also gains Call and Devices.

Driven under node: the real `apolloPane.js`, `apolloTaskChat.js` and
`apolloPaneModel.js` on the shared DOM shim, the server faked by path (the
harness of `test_apollos_pane_shows_the_work_and_what_it_knows_js`). Each case
says what reached the server or what the person would see.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_apollos_pane_shows_the_work_and_what_it_knows_js import (  # noqa: E402
    PANE, _PREAMBLE, _SHIM, _STUBS,
)
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_TASK = (
    "const t = T('r1', 'working', { hire_id: 'h1', session_id: 's-r1', lead_agent: 'researcher' });\n"
    "routes['GET /api/apollo/tasks'] = () => [200, { tasks: [t] }];\n"
    "routes['GET /api/apollo/tasks/*'] = () => [200, t];\n"
    "routes['GET /api/apollo/tasks/r1/chat'] = () => [200, { task_id: 'r1', session_id: 's-r1', title: t.title,\n"
    "  lead: 'Researcher', lead_agent: 'researcher', state: 'working' }];\n"
    "routes['GET /api/history/*'] = () => [200, { history: [] }];\n"
    "routes['POST /api/apollo/tasks/r1/said'] = (m, u, b) => [200, { line: b.words, posted: true }];\n"
    "const openTask = async () => { P.openApolloPane(); await settle(); all(pane(), 'apo-row-b')[0].click(); await settle(30); };\n"
    "const say = async (words) => {\n"
    "  const form = all(all(pane(), 'apo-chat')[0], 'apo-chat-form')[0];\n"
    "  all(form, 'apo-chat-input')[0].value = words;\n"
    "  submit(form);\n"
    "  await settle(40);\n"
    "};\n"
    "const sse = (...evs) => evs.map((e) => `data: ${JSON.stringify(e)}\\n`).join('\\n') + '\\n';\n"
)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("apollochat"), PANE, _SHIM, _STUBS)


def _case(box, script):
    return _run(box, _PREAMBLE + _TASK, script + "\nP.closeApolloPane();\n")


def test_words_with_no_run_live_start_a_turn_of_the_lead_in_its_chat(box):
    o = _case(box, """
        routes['POST /api/chat/steer/*'] = () => [409, { accepted: false, reason: 'no_active_run' }];
        routes['POST /api/chat_stream'] = () => [200, {}, sse({ delta: 'On it. ' }, { delta: 'Two are open.' })];
        await openTask();
        await say('Which ones take my insurance?');
        const writes = sent.filter((s) => s.method === 'POST');
        out({ writes, mine: all(pane(), 'apo-msg-you').length });
    """)
    steer, stream, said = o["writes"]
    assert steer == {"method": "POST", "url": "/api/chat/steer/s-r1",
                     "body": {"text": "Which ones take my insurance?"}}
    # The lead, summoned as itself in Agent mode, in the task's own chat.
    assert stream["url"] == "/api/chat_stream"
    assert stream["body"] == {"session": "s-r1", "mode": "agent",
                              "message": "Which ones take my insurance?", "agent": "researcher"}
    # Apollo hears one line about it, never the conversation.
    assert said == {"method": "POST", "url": "/api/apollo/tasks/r1/said",
                    "body": {"words": "Which ones take my insurance?"}}


def test_words_while_a_run_works_steer_that_run(box):
    o = _case(box, """
        routes['POST /api/chat/steer/*'] = () => [200, { accepted: true, pending: 1 }];
        await openTask();
        await say('Skip the ones downtown');
        out({ urls: sent.filter((s) => s.method === 'POST').map((s) => s.url), toasts });
    """)
    assert o["urls"] == ["/api/chat/steer/s-r1", "/api/apollo/tasks/r1/said"]
    assert "Researcher takes that at its next step." in o["toasts"]


def test_an_approval_the_lead_asks_for_is_answered_in_the_chat(box):
    o = _case(box, """
        routes['POST /api/chat/steer/*'] = () => [409, { accepted: false }];
        let turn = 0;
        routes['POST /api/chat_stream'] = () => {
          turn += 1;
          if (turn === 1) return [200, {}, sse({ type: 'ask_user', data: { kind: 'tool_approval', approval_id: 'ap-1',
            question: 'Allow this task to continue?', options: [
              { label: 'Allow for this task', value: 'approve_task' }, { label: 'Deny', value: 'deny' }] } })];
          return [200, {}, sse({ delta: 'Booked.' })];
        };
        await openTask();
        await say('Book the 10:30');
        const ask = all(pane(), 'apo-chat-ask')[0];
        const asked = all(ask, 'apo-q').map(text);
        button(ask, 'Allow for this task').click();
        await settle(40);
        const streams = sent.filter((s) => s.url === '/api/chat_stream');
        out({ asked, resume: streams[1].body, after: all(all(pane(), 'apo-chat-ask')[0], 'apo-q').length });
    """)
    assert o["asked"] == ["Allow this task to continue?"]
    assert o["resume"] == {"session": "s-r1", "mode": "agent", "message": "",
                           "tool_approval_id": "ap-1", "tool_approval_decision": "approve_task"}
    assert o["after"] == 0


def test_an_unanswered_approval_is_still_there_when_the_chat_reopens(box):
    o = _case(box, """
        routes['GET /api/history/*'] = () => [200, { history: [
          { role: 'user', content: 'Book it' },
          { role: 'assistant', content: 'Allow this task to continue?', metadata: { tool_events: [
            { tool: 'book', ask_user: { kind: 'tool_approval', approval_id: 'ap-9', question: 'Allow this task to continue?',
              options: [{ label: 'Allow for this task', value: 'approve_task' }, { label: 'Deny', value: 'deny' }] } },
          ] } },
        ] }];
        await openTask();
        const ask = all(pane(), 'apo-chat-ask')[0];
        out({ buttons: buttons(ask).map((b) => b.textContent) });
    """)
    assert o["buttons"] == ["Allow for this task", "Deny"]


def test_a_task_not_started_says_so_and_offers_no_box(box):
    o = _case(box, """
        routes['GET /api/apollo/tasks/r1/chat'] = () => [409, { detail: "This task's chat opens once its lead has started on it." }];
        await openTask();
        const chat = all(pane(), 'apo-chat')[0];
        out({ said: all(chat, 'apo-empty').map(text), hidden: all(chat, 'apo-chat-form')[0].hidden });
    """)
    assert "This task's chat opens once its lead has started on it." in o["said"]
    assert o["hidden"] is True


def test_a_popped_out_chat_is_its_own_window_and_several_stack(box):
    o = _case(box, """
        const t2 = T('r2', 'working', { hire_id: 'h2', session_id: 's-r2' });
        routes['GET /api/apollo/tasks'] = () => [200, { tasks: [t, t2] }];
        routes['GET /api/apollo/tasks/r2/chat'] = () => [200, { task_id: 'r2', session_id: 's-r2', title: t2.title, lead: 'Writer', lead_agent: 'writer' }];
        await openTask();
        button(pane(), 'Pop out chat').click();
        await settle(30);
        const first = document.getElementById('apollo-chat-r1');
        const embeddedAfter = all(pane(), 'apo-chat').length;
        const wide = pane()._classes().includes('apo-wide');
        const label = buttons(pane()).map((b) => b.textContent).includes('Show its chat');
        const T2 = await import('./apolloTaskChat.js');
        T2.popOutTaskChat('r2', { title: t2.title });
        await settle(30);
        const second = document.getElementById('apollo-chat-r2');
        const stack = second.style.getPropertyValue ? second.style.getPropertyValue('--apo-stack') : null;
        T2.closeFloatingTaskChats();
        out({ first: !!first, embeddedAfter, wide, label, second: !!second, stack,
              gone: !document.getElementById('apollo-chat-r1') && !document.getElementById('apollo-chat-r2') });
    """)
    assert o["first"] is True
    assert o["embeddedAfter"] == 0
    assert o["wide"] is False
    assert o["label"] is True
    assert o["second"] is True
    assert o["stack"] in ("1", None)
    assert o["gone"] is True


def test_needs_you_lists_a_leads_approval_and_answers_it_through_the_runs_door(box):
    o = _case(box, """
        routes['GET /api/apollo/approvals'] = () => [200, { approvals: [{ task_id: 'r1', title: 'Task r1',
          run_task_id: 'st-1', run_id: 'run-1', approval_id: 'ap-2', tool: 'send_email',
          question: 'Task r1: allow send_email?', why: 'It writes outside Pantheon.' }] }];
        routes['POST /api/tasks/*'] = () => [200, { outcome: 'allowed' }];
        P.openApolloPane();
        await settle();
        const needs = all(pane(), 'apo-approval')[0];
        const said = all(needs, 'apo-q').map(text);
        button(needs, 'Allow once').click();
        await settle();
        out({ said, write: sent.find((s) => s.method === 'POST'), toasts });
    """)
    assert o["said"] == ["Waiting for your OK to use send_email."]
    assert o["write"] == {"method": "POST", "url": "/api/tasks/st-1/runs/run-1/answer",
                          "body": {"approval_id": "ap-2", "decision": "approve_task"}}
    assert "Allowed. The lead carries on." in o["toasts"]


def test_devices_show_the_phone_and_call_starts_a_voice_call(box):
    o = _case(box, """
        P.openApolloPane();
        await settle();
        const devs = all(pane(), 'apo-dev').map((n) => all(n, 'apo-row-t').map(text).concat(all(n, 'apo-row-s').map(text)));
        all(all(pane(), 'apo-dev')[1], 'apo-dev-b')[0].click();
        await settle();
        button(pane(), 'Call').click();
        await settle();
        out({ devs, opened });
    """)
    assert o["devs"] == [["Workstation", "Running"], ["Pixel 9", "Off"]]
    assert o["opened"]["phone"] == 1
    assert o["opened"]["calls"] == 1
