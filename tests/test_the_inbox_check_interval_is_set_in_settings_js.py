# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1152` (f-mail) — an admin sets how often the inbox is checked from
Settings → Email, and the next check follows it.

`email_inbox_check_minutes` (`B1137`, default 5, 0 is off) was settable through
`POST /api/auth/settings`, `manage_settings` or `settings.json` and had no
field: on the tree before this row Settings → Email holds no input for it
(``initInboxCheckInterval`` does not exist; the first case cannot cut it), so an
operator who wanted the check off or faster had to know the key (`Law 15`).

Driven (`Law 20`): the field's own code, ``initInboxCheckInterval`` and the
panel's one settings writer ``_postSettings``, cut out of ``settings.js`` and
run under node, posting to the REAL ``GET``/``POST /api/auth/settings`` served
on a loopback socket as an admin session, over the real settings store on a
temp file — the store the real background check (`B1137`'s world: real
``setup_email_routes()``, real loop, loopback IMAP) reads every time round.
"""

import asyncio
import json
import shutil
import socket
import threading
import time
from pathlib import Path

import pytest

from tests.helpers.imap_server import ImapServer
from tests.helpers.js_source import js_definition
from tests.test_mail_arriving_runs_its_workflow_with_nobody_looking import (  # noqa: F401
    MINUTE, _until, world,
)

pytestmark = [pytest.mark.asyncio,
              pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")]

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_JS = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")


def _cut(signature: str) -> str:
    return js_definition(SETTINGS_JS, SETTINGS_JS.index(signature))


@pytest.fixture()
def served(world, monkeypatch):  # noqa: F811
    """The real auth router — the Settings page's door — on a loopback socket.
    `admin-session` is an admin's cookie, `user-session` a plain user's."""
    import uvicorn
    from fastapi import FastAPI
    import routes.auth_routes as auth_routes

    class _AuthManager:
        is_configured = True

        def get_username_for_token(self, token):
            return {"admin-session": "admin", "user-session": "rowan"}.get(token)

        def is_admin(self, username):
            return username == "admin"

    monkeypatch.setattr(auth_routes, "migrate_from_settings", lambda: None)
    app = FastAPI()
    app.include_router(auth_routes.setup_auth_routes(_AuthManager()))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        assert thread.is_alive() and time.monotonic() < deadline, "the test server did not start"
        time.sleep(0.02)
    world["base"] = f"http://127.0.0.1:{port}"
    world["cookie"] = f"{auth_routes.SESSION_COOKIE}=admin-session"
    try:
        yield world
    finally:
        server.should_exit = True
        thread.join(timeout=10)


_PAGE = r"""
const BASE = __BASE__, COOKIE = __COOKIE__;
const realFetch = globalThis.fetch;
// The page's fetches are same-origin with its session cookie.
globalThis.fetch = (url, init = {}) => realFetch(BASE + url,
  { ...init, headers: { ...(init.headers || {}), Cookie: COOKIE } });
let invalidated = 0;
function invalidateSettings() { invalidated++; }
const field = { value: '', listeners: {}, addEventListener(t, fn) { this.listeners[t] = fn; } };
const msg = { textContent: '', style: { color: '' } };
const el = (id) => ({ 'set-emailInboxCheck': field, 'set-emailInboxCheckMsg': msg })[id] || null;
__CUT__
await initInboxCheckInterval();
const shown = [{ value: field.value, said: msg.textContent }];
/** The admin types a value into the field and leaves it. */
async function type(v) {
  field.value = v;
  await field.listeners.change();
  shown.push({ value: field.value, said: msg.textContent, red: msg.style.color === 'var(--red)' });
}
"""


async def _settings_page(served, body: str, cookie: str | None = None) -> dict:
    work = served["seen_db"].parent / "node-settings"
    work.mkdir(parents=True, exist_ok=True)
    cut = "\n".join(_cut(sig) for sig in ("async function _postSettings(",
                                           "async function initInboxCheckInterval("))
    source = (_PAGE.replace("__BASE__", json.dumps(served["base"]))
              .replace("__COOKIE__", json.dumps(cookie or served["cookie"]))
              .replace("__CUT__", cut)
              + body + "\nconsole.log(JSON.stringify({ shown, invalidated }));\n")
    (work / "page.mjs").write_text(source, encoding="utf-8")
    # A subprocess the event loop keeps running beside: the background check
    # lives on this loop, and `subprocess.run` would stop it.
    proc = await asyncio.create_subprocess_exec(
        "node", str(work / "page.mjs"), cwd=work,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={"PATH": __import__("os").environ["PATH"], "NO_PROXY": "127.0.0.1",
             "no_proxy": "127.0.0.1"})
    out, err = await asyncio.wait_for(proc.communicate(), 60)
    assert proc.returncode == 0, err.decode()
    return json.loads(out.decode().strip().splitlines()[-1])


async def test_the_field_shows_the_interval_the_check_uses(served):
    from routes.email_pollers import inbox_check_minutes

    page = await _settings_page(served, "")
    assert inbox_check_minutes() == 5
    assert page["shown"] == [{"value": "5", "said": "Every 5 minutes."}]


async def test_an_admin_turns_it_on_from_the_field_and_the_next_check_follows(served):
    from routes.email_pollers import inbox_check_minutes

    served["set_minutes"](0)                                 # off, as an operator left it
    with ImapServer() as srv:
        served["add_account"](srv.port)
        served["email_routes"].setup_email_routes()          # the real loop, idling at 0
        await asyncio.sleep(MINUTE * 3)
        assert srv.box.logins() == 0
        page = await _settings_page(served, "await type('1');")
        assert page["shown"][0]["said"].startswith("Off.")
        assert page["shown"][1] == {"value": "1", "said": "Every minute.", "red": False}
        assert inbox_check_minutes() == 1 and page["invalidated"] == 1
        await _until(lambda: srv.box.logins() >= 1, MINUTE * 8, "the first check after the field")

        # And off again from the same field: the check stops.
        page = await _settings_page(served, "await type('0');")
        assert page["shown"][1]["said"].startswith("Off.") and inbox_check_minutes() == 0
        await asyncio.sleep(MINUTE * 3)                       # the sleep already begun ends
        settled = srv.box.logins()
        await asyncio.sleep(MINUTE * 4)
        assert srv.box.logins() == settled, "it kept checking after the field turned it off"


async def test_a_number_past_the_range_shows_what_the_server_kept(served):
    from routes.email_pollers import inbox_check_minutes

    page = await _settings_page(served, "await type('5000');")
    assert inbox_check_minutes() == 1440
    assert page["shown"][1] == {
        "value": "1440", "red": False,
        "said": "Every 1440 minutes. (5000 is outside the range, so it was kept at 1440.)"}


async def test_not_a_whole_number_is_refused_in_words_and_nothing_is_sent(served):
    from routes.email_pollers import inbox_check_minutes

    page = await _settings_page(served, "await type('2.5'); await type('');")
    assert inbox_check_minutes() == 5 and page["invalidated"] == 0
    for after in page["shown"][1:]:
        assert after == {"value": "5", "said": "A whole number of minutes; 0 turns it off.",
                         "red": True}


async def test_a_refused_save_leaves_the_field_as_it_was_and_says_so(served):
    """Not an admin: the route answers 403. The field goes back to what is
    stored instead of showing a number nothing is using."""
    import routes.auth_routes as auth_routes
    from routes.email_pollers import inbox_check_minutes

    page = await _settings_page(served, "await type('2');",
                                cookie=f"{auth_routes.SESSION_COOKIE}=user-session")
    assert inbox_check_minutes() == 5
    assert page["shown"][1] == {"value": "5", "said": "Failed to save — left unchanged.", "red": True}


def test_the_field_is_in_settings_email_for_admins_only():
    """Where the page puts it: inside Settings → Email, in a card the panel
    hides from a non-admin (`syncAdminVisibility` hides every `.admin-only`),
    since only an admin's save is accepted. Read as a document tree, scoped to
    the element (`Law 20` option 2), not grepped."""
    from html.parser import HTMLParser

    class _Tree(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.found = [], None

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if a.get("id") == "set-emailInboxCheck":
                self.found = ([dict(x) for _, x in self.stack], a)
            if tag not in ("input", "br", "img", "path", "circle", "line", "rect", "polyline",
                           "polygon", "meta", "link", "source", "hr"):
                self.stack.append((tag, a))

        def handle_endtag(self, tag):
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    break

    tree = _Tree()
    tree.feed((ROOT / "static" / "index.html").read_text(encoding="utf-8"))
    assert tree.found, "no field"
    ancestors, field = tree.found
    assert field.get("type") == "number" and field.get("min") == "0"
    assert any(a.get("data-settings-panel") == "email" for a in ancestors)
    card = next(a for a in reversed(ancestors) if "admin-card" in (a.get("class") or ""))
    assert "admin-only" in card["class"].split()
