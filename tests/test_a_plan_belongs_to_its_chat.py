# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B894` — a plan made in one chat followed you into the next.

Reported by the owner 2026-09-27: *"my coding chat — the plan there transfers
into a new chat I just made. It should **stay** with that prior chat."*

**What it was.** `static/js/planWindow.js` kept the plan under ONE
`localStorage` key and its metadata under one more, for the whole browser.
`_meta.sessionId` was only written on Execute, so a draft belonged to no chat
and was drawn in every chat; an approved plan was still drawn everywhere, with
a small "from another chat" tag; and a new chat's Execute button called
`_executeStoredPlan`, whose `getPlan()` handed back the previous chat's plan —
so pressing it ran someone else's steps in a conversation that had never seen
them. `refresh()` also returned early when the window was hidden, so switching
INTO a chat that had a plan could not bring it up.

**What it is.** One pair of keys per chat. Which pair is live is decided by
asking for the current session id every time the plan is read, written or
drawn — the reader `onSessionId` already registered — so a switch path nobody
wired still cannot show, send or execute the wrong plan. A plan is filed under
the chat whose stream produced it, not the chat on screen when it arrived.

Every case drives the real module. None reads the source.
"""
import json
import shutil
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import (  # noqa: E402
    PLAN_WINDOW, _PLAN_SHIM, _PLAN_STUBS, _make_sandbox, _plan_window_ids, _run,
)

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The shared plan stub keeps ONE blob whatever key it is asked for, which is
# exactly the property this row is about — so this file brings a key-aware one
# and a `localStorage` that can be inspected, and reuses everything else.
_STORAGE = """
const mem = { json: {}, plain: {}, toggles: {} };
export function setToggles(t) { mem.toggles = t || {}; }
export function dump() { return JSON.parse(JSON.stringify(mem)); }
export function seedLegacy(text, meta, last) {
  globalThis.localStorage.setItem('pantheon-active-plan', text);
  if (meta) mem.json['pantheon-plan-window'] = meta;
  if (last) mem.plain['lastSessionId'] = last;
}
export default {
  getJSON: (k, fb) => (k in mem.json ? JSON.parse(JSON.stringify(mem.json[k])) : fb),
  setJSON: (k, v) => { mem.json[k] = JSON.parse(JSON.stringify(v)); },
  remove: (k) => { delete mem.json[k]; delete mem.plain[k]; },
  get: (k) => (k in mem.plain ? mem.plain[k] : null),
  loadToggleState: () => mem.toggles,
  KEYS: { TOGGLES: 'toggles' },
};
"""

_LOCAL_STORAGE = """
const _ls = {};
globalThis.localStorage = {
  getItem: (k) => (k in _ls ? _ls[k] : null),
  setItem: (k, v) => { _ls[k] = String(v); },
  removeItem: (k) => { delete _ls[k]; },
  _keys: () => Object.keys(_ls),
};
let _sid = '';
export function setSession(s) { _sid = s || ''; }
export function getSession() { return _sid; }
"""

_PREAMBLE = (
    "import { document } from './shim.js';\n"
    "import { setSession, getSession } from './session_shim.js';\n"
    "import { setToggles, dump, seedLegacy } from './storage.js';\n"
    "const planWindow = (await import('./planWindow.js')).default;\n"
    "planWindow.onSessionId(getSession);\n"
)

PLAN_A = "- [ ] read the failing test\n- [ ] fix the parser\n- [ ] rerun the suite"
PLAN_B = "- [ ] draft the email\n- [ ] send it"


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    shim = _PLAN_SHIM.replace("__PLAN_WINDOW_IDS__", json.dumps(_plan_window_ids()))
    stubs = dict(_PLAN_STUBS)
    stubs["storage.js"] = _STORAGE
    stubs["session_shim.js"] = _LOCAL_STORAGE
    return _make_sandbox(tmp_path_factory.mktemp("planbucket"), PLAN_WINDOW, shim, stubs)


def _drive(sandbox: Path, script: str) -> dict:
    return _run(sandbox, _PREAMBLE, script)


def test_a_plan_made_in_one_chat_is_not_in_the_next(sandbox):
    """The report, exactly."""
    out = _drive(sandbox, """
        setSession('coding-chat');
        planWindow.init();
        planWindow.setPlan(%s);
        const inCoding = planWindow.getPlan();
        setSession('new-chat');
        planWindow.refresh();
        const inNew = planWindow.getPlan();
        const shown = !document.getElementById('plan-window').hidden;
        console.log(JSON.stringify({ inCoding, inNew, shown }));
    """ % json.dumps(PLAN_A))
    assert "fix the parser" in out["inCoding"]
    assert out["inNew"] == "", (
        "the coding chat's plan is in the new chat — this is the defect"
    )
    assert out["shown"] is False, "and the window is still on screen in a chat with no plan"


def test_the_plan_stays_with_its_chat_and_comes_back(sandbox):
    out = _drive(sandbox, """
        setSession('coding-chat');
        planWindow.init();
        planWindow.setPlan(%s);
        setSession('new-chat');
        planWindow.refresh();
        setSession('coding-chat');
        planWindow.refresh();
        const back = planWindow.getPlan();
        const shown = !document.getElementById('plan-window').hidden;
        console.log(JSON.stringify({ back, shown }));
    """ % json.dumps(PLAN_A))
    assert "fix the parser" in out["back"], "the plan was discarded rather than kept with its chat"
    assert out["shown"] is True, "switching back did not bring the window up again"


def test_two_chats_keep_two_plans(sandbox):
    out = _drive(sandbox, """
        setSession('a');
        planWindow.init();
        planWindow.setPlan(%s);
        setSession('b');
        planWindow.setPlan(%s);
        setSession('a');
        const a = planWindow.getPlan();
        setSession('b');
        const b = planWindow.getPlan();
        console.log(JSON.stringify({ a, b }));
    """ % (json.dumps(PLAN_A), json.dumps(PLAN_B)))
    assert "fix the parser" in out["a"] and "send it" not in out["a"]
    assert "send it" in out["b"] and "fix the parser" not in out["b"]


def test_a_plan_is_filed_under_the_chat_that_produced_it(sandbox):
    """A stream that finishes after you switched away must not hand its plan
    to the chat you switched to."""
    out = _drive(sandbox, """
        setSession('b');
        planWindow.init();
        planWindow.setPlan(%s, { sessionId: 'a' });
        const onScreen = planWindow.getPlan();
        setSession('a');
        const inA = planWindow.getPlan();
        console.log(JSON.stringify({ onScreen, inA }));
    """ % json.dumps(PLAN_A))
    assert out["onScreen"] == "", "the plan was filed under the chat on screen"
    assert "fix the parser" in out["inA"]


def test_clearing_a_plan_clears_only_this_chats(sandbox):
    out = _drive(sandbox, """
        setSession('a');
        planWindow.init();
        planWindow.setPlan(%s);
        setSession('b');
        planWindow.setPlan(%s);
        planWindow.clearPlan();
        const b = planWindow.getPlan();
        setSession('a');
        const a = planWindow.getPlan();
        console.log(JSON.stringify({ a, b }));
    """ % (json.dumps(PLAN_A), json.dumps(PLAN_B)))
    assert out["b"] == ""
    assert "fix the parser" in out["a"], "clearing one chat's plan wiped another's"


def test_an_approved_plan_does_not_execute_in_another_chat(sandbox):
    """The half that reaches the model: `isExecuting()` is what makes chat.js
    send `approved_plan` with every turn."""
    out = _drive(sandbox, """
        setToggles({ plan_mode: false });
        setSession('a');
        planWindow.init();
        planWindow.setPlan(%s);
        planWindow.markApproved();
        const inA = planWindow.isExecuting();
        setSession('b');
        const inB = planWindow.isExecuting();
        console.log(JSON.stringify({ inA, inB }));
    """ % json.dumps(PLAN_A))
    assert out["inA"] is True
    assert out["inB"] is False, "another chat's approved plan would be sent with this chat's turns"


def test_an_old_browser_wide_plan_goes_to_the_chat_it_was_approved_in(sandbox):
    """Everyone who already has a plan has it under the old keys. It must land
    in one chat — not stay browser-wide, which is the defect."""
    out = _drive(sandbox, """
        seedLegacy(%s, { v: 1, sessionId: 'coding-chat', approvedAt: 1 }, 'other');
        setSession('new-chat');
        planWindow.init();
        const inNew = planWindow.getPlan();
        setSession('coding-chat');
        const inCoding = planWindow.getPlan();
        const legacyLeft = localStorage.getItem('pantheon-active-plan');
        console.log(JSON.stringify({ inNew, inCoding, legacyLeft }));
    """ % json.dumps(PLAN_A))
    assert out["inNew"] == ""
    assert "fix the parser" in out["inCoding"]
    assert out["legacyLeft"] is None, "the old browser-wide key was left in place"


def test_an_old_draft_goes_to_the_chat_this_browser_last_had_open(sandbox):
    out = _drive(sandbox, """
        seedLegacy(%s, null, 'coding-chat');
        setSession('new-chat');
        planWindow.init();
        const inNew = planWindow.getPlan();
        setSession('coding-chat');
        const inCoding = planWindow.getPlan();
        console.log(JSON.stringify({ inNew, inCoding }));
    """ % json.dumps(PLAN_A))
    assert out["inNew"] == ""
    assert "fix the parser" in out["inCoding"]
