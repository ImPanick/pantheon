# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B780` (absorbing `B693`, `B735`, `B762`, `B811`) — what makes an edited
module reach a browser, and therefore what a `?v=` is for.

Five rows asked one question from five directions: six modules could not carry
a cache-buster of their own (`B780`), `skills.js` carried none at four sites
(`B693`), `ui.js` none at 72 (`B735`), "bare everywhere: policy or accident?"
(`B762`), and `modalManager.js` would split its dock if its `?v=` ever forked
(`B811`). Each row also measured the answer and left it unwritten: `app.py`'s
`_RevalidatingStatic` serves `.js`/`.css` `no-cache`, and the service worker is
network-first for them. If those two hold, a `?v=` is not what delivers an
edit, and the rule is the one `.pantheon/AGENTS.md` § Operational facts now
states: a `?v=` is a module's identity, never moved on one site, and an edited
module needs nothing bumped.

The rule rests on two claims, and both are driven here rather than read
(`Law 20`):

  * **The server.** The real `_RevalidatingStatic`, mounted over a directory
    of the test's own: an unchanged module answers its validator with an empty
    304; an EDITED module, asked with the old validator at the same URL,
    answers 200 with the new bytes; and any `?v=` is the same file — the query
    names nothing on this side.
  * **The worker.** The real `static/sw.js` fetch handler, after a real
    install, online, with the server holding a new release: a bare module
    (`skills.js`), a pinned one (`gallery.js?v=20260708match1`) and one on the
    wave string (`modalManager.js?v=20261009census`) are each answered with the
    server's new bytes, and its offline copy follows — under the shipped
    worker, its `CACHE_NAME` as it is.

What a `?v=` *can* do wrong — load a module twice — is
`check-specifiers.py --max 0` and `test_a_module_fetched_twice_is_a_second_module.py`.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from test_offline_shell_manifest import _needs_node, _run

ROOT = Path(__file__).resolve().parents[1]

_SERVER = r'''
import json, os, pathlib, sys
import app as app_module
from starlette.applications import Starlette
from starlette.routing import Mount
from fastapi.testclient import TestClient

d = pathlib.Path(sys.argv[1])
mod = d / "js" / "mod.js"
mod.parent.mkdir(parents=True, exist_ok=True)
mod.write_text("export const release = 1;\n", encoding="utf-8")
web = Starlette(routes=[Mount("/static", app=app_module._RevalidatingStatic(directory=str(d)))])
c = TestClient(web)

def row(res):
    return {"status": res.status_code, "body": res.text,
            "etag": res.headers.get("etag"), "cache_control": res.headers.get("cache-control")}

first = c.get("/static/js/mod.js")
unchanged = c.get("/static/js/mod.js", headers={"If-None-Match": first.headers["etag"]})
# The edit: different bytes at the same path (a different size, so the
# validator moves whatever the clock's resolution).
mod.write_text("export const release = 2; // edited\n", encoding="utf-8")
edited = c.get("/static/js/mod.js", headers={"If-None-Match": first.headers["etag"]})
queried = {q: c.get("/static/js/mod.js" + q).text for q in ("", "?v=20260708match1", "?v=anything")}
print("RESULT=" + json.dumps({"first": row(first), "unchanged": row(unchanged),
                              "edited": row(edited), "queried": queried}))
'''


@pytest.fixture(scope="module")
def served(tmp_path_factory) -> dict:
    tmp = tmp_path_factory.mktemp("revalidating")
    env = os.environ.copy()
    env.update({
        "CHROMADB_CONNECT_TIMEOUT": "0.01", "CHROMADB_HOST": "127.0.0.1", "CHROMADB_PORT": "9",
        "DATABASE_URL": f"sqlite:///{tmp / 'app.db'}", "PANTHEON_DATA_DIR": str(tmp),
        "PANTHEON_DISABLE_MCP": "1", "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1",
    })
    static = tmp / "static"
    static.mkdir()
    result = subprocess.run([sys.executable, "-c", _SERVER, str(static)], cwd=str(ROOT), env=env,
                            capture_output=True, text=True, timeout=300, check=False)
    assert result.returncode == 0, result.stderr[-4000:]
    line = next(l for l in result.stdout.splitlines() if l.startswith("RESULT="))
    return json.loads(line.removeprefix("RESULT="))


def test_the_server_asks_the_browser_to_revalidate_every_module(served):
    first = served["first"]
    assert first["status"] == 200 and first["etag"], first
    assert first["cache_control"] == "no-cache", first


def test_an_unchanged_module_costs_an_empty_304(served):
    assert served["unchanged"]["status"] == 304 and served["unchanged"]["body"] == ""


def test_an_edited_module_comes_back_new_at_the_same_url(served):
    """The browser's cached copy and its validator are what a returning visit
    sends; the server answers it with the edit — no new URL needed."""
    edited = served["edited"]
    assert edited["status"] == 200, edited
    assert edited["body"] == "export const release = 2; // edited\n"
    assert edited["etag"] != served["first"]["etag"]


def test_a_query_string_names_nothing_on_the_server(served):
    """`?v=` is not a version the server can serve: every spelling is the same
    file, so a string that moves buys no freshness — only a second module."""
    assert set(served["queried"].values()) == {"export const release = 2; // edited\n"}, served["queried"]


def _digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


# One module of each kind the rule covers, read from the real tree's install.
_MODULES = {
    "bare": "/static/js/skills.js",
    "pinned": "/static/js/gallery.js?v=20260708match1",
    "wave": "/static/js/modalManager.js?v=20261009census",
}


@_needs_node
def test_the_worker_hands_an_online_page_the_edit_for_every_kind_of_url():
    release = {url: f"export const release = 2; // {kind}" for kind, url in _MODULES.items()}
    before = _run({"op": "install"})
    for url in _MODULES.values():
        assert url in before["cached"], f"{url} is not precached — re-aim this test at a module that is"
    out = _run({"op": "navigate", "online": True, "mode": "cors", "urls": list(_MODULES.values()),
                "serve": release})
    for kind, url in _MODULES.items():
        answer = out["answered"][url]
        assert answer.get("status") == 200 and answer["sha"] == _digest(release[url]), (kind, answer)
        # And the copy kept for offline is the edit too.
        assert out["after"][url] == _digest(release[url]), kind
        assert out["after"][url] != out["hashes"][url], f"{kind}: the release equals what was installed"
