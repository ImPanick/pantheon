# SPDX-License-Identifier: AGPL-3.0-or-later
"""The server every browser test boots runs on a database file of its own.

`B1085`. `app_url` (`tests/test_the_command_palette_in_a_browser.py`) handed
the server `dict(os.environ, …)`, and `tests/conftest.py` puts
`DATABASE_URL=sqlite:///:memory:` there — so `app.py` ran on an in-memory
SQLite whose tables existed on one connection. Measured in that fixture's
`app.log`: `/api/default-chat`, `/api/notes`, `/api/sessions` and
`/api/model-endpoints` answered 500 `no such table` from the first page load,
and `/api/assistant/session` answered 200 twice and then 500. Seven browser
files each carried a module fixture pointing `DATABASE_URL` at a file before
`app_url` ran; they are gone, and this file is what holds the fixture to it.

No browser is needed to ask a server for its rows, so this drives the routes
over HTTP — the same requests a first page load makes — enough times to land
on more threads than the old pool kept.
"""
import http.cookiejar
import json
import urllib.error
import urllib.request

import pytest

from test_the_command_palette_in_a_browser import SERVED, app_url  # noqa: F401,E402

#: The rows `B1085` names, each read from the database on every call.
_DATABASE_ROUTES = ("/api/default-chat", "/api/notes", "/api/sessions",
                    "/api/model-endpoints", "/api/assistant/session")


@pytest.fixture(scope="module")
def answered(app_url):  # noqa: F811
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    creds = json.dumps({"username": "tables", "password": "tables-pass-1"}).encode()

    def call(path, body=None):
        req = urllib.request.Request(app_url + path, data=body, method="POST" if body else "GET",
                                     headers={"Content-Type": "application/json"})
        try:
            with opener.open(req, timeout=30) as res:
                return res.status
        except urllib.error.HTTPError as e:
            return e.code

    setup = call("/api/auth/setup", creds)
    login = call("/api/auth/login", creds)
    statuses = {path: [] for path in _DATABASE_ROUTES}
    for _ in range(8):
        for path in _DATABASE_ROUTES:
            statuses[path].append(call(path))
    return {"setup": setup, "login": login, "statuses": statuses,
            "data": SERVED[app_url].data}


def test_the_server_was_given_a_database_file_in_its_data_directory(answered):
    db = answered["data"] / "app.db"
    assert db.is_file() and db.stat().st_size > 0, (
        f"no database file at {db}: the server was handed a database with no file behind it")


def test_every_read_of_the_database_is_answered(answered):
    assert answered["setup"] == 200 and answered["login"] == 200, answered
    failed = {path: codes for path, codes in answered["statuses"].items()
              if any(code >= 500 for code in codes)}
    assert not failed, f"database-backed routes answered 5xx: {failed}"


def test_the_servers_log_has_no_missing_table(answered):
    log = (answered["data"] / "app.log").read_text(encoding="utf-8", errors="replace")
    missing = [line for line in log.splitlines() if "no such table" in line]
    assert not missing, "the server's own log:\n" + "\n".join(missing[:10])
