# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1424` — in the workstation window, an admin may watch another person's
screen, and only watch.

The real `static/js/workstationScreen.js` under node, with `P20-05`'s harness
(imported, so the window is the one its own file drives), and the user list
answered as `GET /api/auth/users` answers it: the list for an admin, `403` for
anyone else.
"""
from __future__ import annotations

import shutil

import pytest

from test_the_workstation_screen_window_js import (  # noqa: F401 — fixture
    HOLDING, _window, sandbox)

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_USERS = """
const realFetch = globalThis.fetch;
globalThis.__admin = __ADMIN__;
globalThis.fetch = async (url, opts = {}) => {
  if (String(url) === '/api/auth/users') {
    server.calls.push({ url, method: 'GET' });
    return globalThis.__admin
      ? { ok: true, status: 200, json: async () => ({ users: [
          { username: 'dee' }, { username: 'ada' }, { username: 'cy' }] }) }
      : { ok: false, status: 403, json: async () => ({ detail: 'Admin only' }) };
  }
  return realFetch(url, opts);
};
const picker = () => {
  const w = mod._test.win();
  return { shown: !w.whoLabel.hidden,
           options: Array.from(w.who.childNodes).map((o) => [o.value, o.textContent]) };
};
"""


def _as(admin: bool, script: str):
    return _window(sandbox_ref[0], _USERS.replace("__ADMIN__", "true" if admin else "false")
                   + script)


sandbox_ref = []


@pytest.fixture(autouse=True)
def _keep(sandbox):
    sandbox_ref[:] = [sandbox]


def test_an_admin_is_offered_everyone_in_the_window():
    out = _as(True, "await open(); await settle(30); out(picker());")
    assert out["shown"] is True
    assert out["options"] == [["", "Mine"], ["ada", "ada"], ["cy", "cy"], ["dee", "dee"]]


def test_anyone_else_is_offered_nothing():
    out = _as(False, "await open(); await settle(30); out(picker());")
    assert out["shown"] is False
    assert out["options"] == [["", "Mine"]]


def test_watching_asks_for_their_screen_and_who_holds_it():
    out = _as(True, """
        await open(); await settle(30);
        server.calls.length = 0;
        mod.watchPerson('dee');
        await settle(150);
        const urls = server.calls.map((c) => c.url);
        out({ urls, state: mod._test.state().watching });
    """)
    screens = [u for u in out["urls"] if u.startswith("/api/workstation/screen")]
    holders = [u for u in out["urls"] if u.startswith("/api/workstation/control")]
    assert screens and all("person=dee" in u for u in screens), screens
    assert holders and all(u.endswith("?person=dee") for u in holders), holders
    assert out["state"] == "dee"


def test_watching_offers_no_control_and_sends_nothing_even_while_they_hold_it():
    out = _as(True, """
        await open(); await settle(30);
        mod.watchPerson('dee');
        server.holder = 'person';
        await settle(150);
        const seen = read(mod);
        click(420, 250);
        const k = key('a');
        await done();
        out({ seen, sent: sent(), keyKept: !k.defaultPrevented });
    """)
    seen = out["seen"]
    assert seen["take"] is False and seen["give"] is False and seen["reset"] is False
    assert seen["status"] == HOLDING, "who holds their screen is still said"
    assert "watching another person's screen" in seen["hint"]
    assert "(dee)" in seen["hint"]
    assert out["sent"] == [] and out["keyKept"]


def test_mine_again_is_the_callers_own_screen():
    out = _as(True, """
        await open(); await settle(30);
        mod.watchPerson('dee'); await settle(60);
        mod.watchPerson('');
        server.calls.length = 0;
        await settle(150);
        out({ urls: server.calls.map((c) => c.url), seen: read(mod) });
    """)
    assert out["urls"] and not any("person=" in u for u in out["urls"])
    assert out["seen"]["take"] is True and out["seen"]["reset"] is True


def test_picking_from_the_list_watches_that_person():
    out = _as(True, """
        await open(); await settle(30);
        const w = mod._test.win();
        w.who.value = 'cy';
        w.who.dispatchEvent({ type: 'change', preventDefault() {}, stopPropagation() {} });
        await settle(60);
        out({ watching: mod._test.state().watching });
    """)
    assert out["watching"] == "cy"
