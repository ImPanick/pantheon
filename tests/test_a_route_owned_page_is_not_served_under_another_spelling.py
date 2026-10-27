# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B1142` — the `/static` mount sends a route-owned page to its route whatever the URL spelled.

`B262`'s rule (`_RevalidatingStatic.get_response`, `app.py`) looked the URL's
spelling up in `ROUTE_OWNED_STATIC_PAGES` after `normpath` and `casefold`, and
`StaticFiles.lookup_path` then resolved the same path through
`os.path.realpath` — which on Windows goes through Win32 path normalisation and
opens `index.html` for `index.html.`, `index.html%20`, `index.html::$DATA` and
the 8.3 name `INDEX~1.HTM`. Each missed the table and would have been served:
the app shell, and since `B370` the three sandboxes, to a caller with no
session, on the one shipped platform where that holds.

The row's `Verify:` asks for a Windows host, and none is reachable from here.
What does not need one: the decision no longer rests on the spelling.

  * **by what the file is** — `file_response`, the one place every served byte
    passes, compares the file about to be served with each table entry by
    `os.path.samestat` and redirects a match. Proved here with the spellings a
    Linux filesystem *can* make resolve to the same file: a hard link named
    `INDEX~1.HTM` is exactly what Windows' 8.3 alias is to `stat` (one file,
    two names), and a symlink is a third spelling;
  * **by the spelling Win32 would open** (`win32_folded_spelling`) — trailing
    dots and spaces dropped, an NTFS stream suffix dropped — so those spellings
    are redirected on every platform, including for a table entry a
    deployment names but did not ship.

Driven (`Law 20`) against the real app with `AUTH_ENABLED=true` and no
session, out of process like `tests/test_static_mount_is_not_a_second_front_door.py`;
and the real `_RevalidatingStatic` mounted over a temporary directory that
holds the aliases. On Linux the existing `B262` and `B370` cases still pass
(those files are run beside this one).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_PROBE = r'''
import json, os, shutil, sys, tempfile
import app as app_module
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Mount

client = TestClient(app_module.app)

def ask(c, url):
    r = c.get(url, follow_redirects=False)
    return {"status": r.status_code, "location": r.headers.get("location"),
            "bytes": len(r.content)}

# Spellings Win32 opens as the page itself, asked of the real app.
spelled = {}
for name in ("index.html", "login.html", "wave-variants.html", "backgrounds.html"):
    for url in ("/static/%s." % name, "/static/%s%%20" % name, "/static/%s::$DATA" % name,
                "/static/%s.%%20." % name.upper(), "/static/%s:Zone.Identifier" % name):
        spelled[url] = ask(client, url)
# What must not move: an asset the login page loads, and a near-miss name.
kept = {u: ask(client, u) for u in ("/static/style.css", "/static/index.htmlx")}

# The mount's own class over a directory holding aliases of `index.html`.
d = tempfile.mkdtemp()
shutil.copy(app_module.route_owned_page("index.html"), os.path.join(d, "index.html"))
with open(os.path.join(d, "other.html"), "w") as f:
    f.write("<p>another page</p>")
with open(os.path.join(d, "mod.js"), "w") as f:
    f.write("export const x = 1;")
os.link(os.path.join(d, "index.html"), os.path.join(d, "INDEX~1.HTM"))   # an 8.3 alias, as stat sees one
os.symlink(os.path.join(d, "index.html"), os.path.join(d, "shell-link.html"))
mini = Starlette(routes=[Mount("/static", app=app_module._RevalidatingStatic(directory=d))])
mc = TestClient(mini)
aliased = {u: ask(mc, u) for u in ("/static/INDEX~1.HTM", "/static/shell-link.html",
                                   "/static/other.html", "/static/mod.js")}
head = mc.head("/static/INDEX~1.HTM", follow_redirects=False)
aliased["HEAD /static/INDEX~1.HTM"] = {"status": head.status_code,
                                       "location": head.headers.get("location")}
# A client whose cached copy is still good must not get a 304 for it either.
from starlette.responses import FileResponse
shell = os.path.join(d, "index.html")
etag = FileResponse(shell, stat_result=os.stat(shell)).headers["etag"]   # the copy a client would hold
cond = mc.get("/static/INDEX~1.HTM", headers={"If-None-Match": etag}, follow_redirects=False)
aliased["conditional"] = {"status": cond.status_code, "location": cond.headers.get("location")}
print("RESULT=" + json.dumps({"spelled": spelled, "kept": kept, "aliased": aliased,
                               "owned": app_module.ROUTE_OWNED_STATIC_PAGES}))
'''


@pytest.fixture(scope="module")
def probed(tmp_path_factory) -> dict:
    tmp_path = tmp_path_factory.mktemp("b1142")
    env = os.environ.copy()
    env.update({
        "AUTH_ENABLED": "true",
        "LOCALHOST_BYPASS": "false",
        "CHROMADB_CONNECT_TIMEOUT": "0.01",
        "CHROMADB_HOST": "127.0.0.1",
        "CHROMADB_PORT": "9",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
        "PANTHEON_DATA_DIR": str(tmp_path),
        "PANTHEON_DISABLE_MCP": "1",
        "PYTHONPATH": str(ROOT),
        "PYTHON_DOTENV_DISABLED": "1",
    })
    result = subprocess.run([sys.executable, "-c", _PROBE], cwd=str(ROOT), env=env,
                            capture_output=True, text=True, timeout=600, check=False)
    assert result.returncode == 0, result.stderr[-4000:]
    line = next((l for l in result.stdout.splitlines() if l.startswith("RESULT=")), None)
    assert line is not None, result.stdout[-4000:]
    return json.loads(line.removeprefix("RESULT="))


def test_each_spelling_win32_folds_answers_302_to_the_route(probed):
    """The row's spellings, and the stream and case variants beside them,
    asked of the real app with no session."""
    owned = probed["owned"]
    for url, row in probed["spelled"].items():
        name = url.split("/static/", 1)[1]
        page = next(n for n in owned if name.casefold().startswith(n.casefold()))
        assert row["status"] == 302, (url, row)
        assert row["location"] == owned[page], (url, row)
        assert row["bytes"] == 0, (url, row)


def test_a_name_that_resolves_to_the_page_is_sent_to_its_route(probed):
    """By what the file is: an 8.3-style alias (a hard link — one file, two
    names, as Windows' short name is) and a symlink. (A case-insensitive
    volume resolving `index~1.htm` too is the same file again; this one is
    not, so it is not asked.)"""
    for url in ("/static/INDEX~1.HTM", "/static/shell-link.html",
                "HEAD /static/INDEX~1.HTM", "conditional"):
        row = probed["aliased"][url]
        assert row["status"] == 302 and row["location"] == "/", (url, row)


def test_everything_else_under_the_mount_is_served_as_before(probed):
    assert probed["aliased"]["/static/other.html"]["status"] == 200
    assert probed["aliased"]["/static/mod.js"]["status"] == 200
    assert probed["kept"]["/static/style.css"]["status"] == 200
    assert probed["kept"]["/static/index.htmlx"]["status"] == 404


def test_the_fold_is_the_one_win32_applies():
    """`win32_folded_spelling` by itself, imported without booting the app:
    trailing dots and spaces and a stream suffix go; nothing else does."""
    import ast

    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "win32_folded_spelling")
    scope: dict = {}
    exec(compile(ast.Module([fn], []), "app.py", "exec"), scope)
    fold = scope["win32_folded_spelling"]
    assert fold("index.html. .") == "index.html"
    assert fold("INDEX.HTML::$DATA") == "index.html"
    assert fold("index.html:Zone.Identifier") == "index.html"
    assert fold("sub/index.html") == "sub/index.html"
    assert fold("index.htmlx") == "index.htmlx"
    assert fold("theme.js") == "theme.js"
