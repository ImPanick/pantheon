# SPDX-License-Identifier: AGPL-3.0-or-later
"""The real app, signed in or not, asked something by three callers.

`B540`, `B541`, `B370`. Each of those rows is a question about who the real
app answers — a caller with no session, a signed-in account that is not an
admin, and the admin — and `Law 20` says the way to answer it is to drive the
real route through the real `AuthMiddleware` and the real `require_admin`, not
to read a handler for the word `require_admin`. Half of each answer lives in
`app.py`'s middleware — installed whatever the environment says since
`D-2026-10-07-02` §2 (it once existed only when `AUTH_ENABLED` was true at
import) — so the app is booted out of process exactly as
`tests/test_static_mount_is_not_a_second_front_door.py` (`B262`) and
`tests/helpers/served_pages.py` (`B212`) boot it.

What this adds to those two is **people**. `B262`'s probe measures a
first-boot instance with no accounts on purpose — the question there is what a
stranger gets before anyone has signed up — and it keeps doing that. Here two
accounts exist, made through the auth manager's own `setup` and `create_user`
(the calls `/api/auth/setup` and `POST /api/auth/users` make), and each gets a
real session token from the same manager the middleware asks:

  * ``ADMIN`` (`ada`) — the instance's first account, so an admin, which is what
    a single-user install's owner is;
  * ``MEMBER`` (`bob`) — a second account, not an admin. `P11-01` measured that
    such accounts are reachable today (`admin_create_user`, and `/signup`
    behind `signup_enabled`), which is why the rows above are live.

The caller's probe body runs after that preamble with ``app_module``,
``client(who)`` and ``RESULT`` in scope, and stubs whatever it must before it
asks — a probe that lets a hardware detection or an SSH session really run is
measuring the machine it runs on. Whatever it puts in ``RESULT`` comes back as
JSON.

The names and the password are `tests/helpers/signed_in.py`'s, the in-process
half of the same question: one way for a test to be a person.
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from tests.helpers.signed_in import ADMIN, MEMBER, PASSWORD

_REPO = Path(__file__).resolve().parents[2]

_PREAMBLE = f'''
import json, os, sys
import app as app_module
from fastapi.testclient import TestClient
from routes.auth_routes import SESSION_COOKIE

ADMIN, MEMBER = {ADMIN!r}, {MEMBER!r}
_auth = app_module.auth_manager
_tokens = {{}}
if ACCOUNTS:
    assert _auth.setup(ADMIN, {PASSWORD!r})
    assert _auth.create_user(MEMBER, {PASSWORD!r})
    _tokens = {{name: _auth.create_session_trusted(name) for name in (ADMIN, MEMBER)}}

def client(who=None, **kwargs):
    """A test client for `who` — `None` is a caller carrying no cookie."""
    c = TestClient(app_module.app, **kwargs)
    if who:
        c.cookies.set(SESSION_COOKIE, _tokens[who])
    return c

CALLERS = (("anonymous", None), ("member", MEMBER), ("admin", ADMIN))

RESULT = {{
    # The premise every assertion rests on: the gate is on, and the two
    # accounts are what their names say. A probe whose app answered a caller
    # with no session would find every route open and prove nothing — so the
    # gate is asked, not read off a flag: a stranger and this machine itself,
    # each with no session, are refused the chat list.
    "premise": {{
        "auth_enabled": TestClient(app_module.app).get("/api/sessions").status_code == 401,
        "localhost_bypass": TestClient(app_module.app, client=("127.0.0.1", 50000))
                            .get("/api/sessions").status_code != 401,
        "admin_is_admin": bool(_auth.is_admin(ADMIN)),
        "member_is_admin": bool(_auth.is_admin(MEMBER)),
    }},
}}
'''

_EPILOGUE = '\nprint("RESULT=" + json.dumps(RESULT, sort_keys=True))\n'


def gated_app_probe(tmp_path, body: str, env_overrides: dict | None = None, *,
                    accounts: bool = True) -> dict:
    """Boot the real app, run ``body`` with three callers, return ``RESULT``.

    ``env_overrides`` is applied last — `tests/test_there_is_always_authentication.py`
    boots the same app with each old no-sign-in variable set, to show it is
    ignored; ``RESULT["premise"]`` says what the booted app answered, so a case
    reads it. ``accounts=False`` boots a first run: no account exists, and
    ``client(who)`` is only ``client(None)``."""
    env = os.environ.copy()
    env.update({
        # Not incidental, though ignored since `D-2026-10-07-02` §2: a tree
        # that honoured either again would answer a caller with no session,
        # and the premise above would say so.
        "AUTH_ENABLED": "true",
        "LOCALHOST_BYPASS": "false",
        "CHROMADB_CONNECT_TIMEOUT": "0.01",
        "CHROMADB_HOST": "127.0.0.1",
        "CHROMADB_PORT": "9",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
        "PANTHEON_DATA_DIR": str(tmp_path),
        "PANTHEON_DISABLE_MCP": "1",
        "PYTHONPATH": str(_REPO),
        "PYTHON_DOTENV_DISABLED": "1",
    })
    env.update(env_overrides or {})
    source = f"ACCOUNTS = {bool(accounts)!r}\n" + _PREAMBLE + textwrap.dedent(body) + _EPILOGUE
    result = subprocess.run([sys.executable, "-c", source], cwd=str(_REPO), env=env,
                            capture_output=True, text=True, timeout=600, check=False)
    assert result.returncode == 0, result.stderr[-4000:]
    line = next((l for l in result.stdout.splitlines() if l.startswith("RESULT=")), None)
    assert line is not None, result.stdout[-4000:]
    return json.loads(line.removeprefix("RESULT="))
