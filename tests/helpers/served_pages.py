# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every page the running app will actually serve, asked for by the app itself.

`B212`. There is one enumerator of the served surface in this suite and this is
it. `tests/test_offline_shell_manifest.py`'s `served_routes` fixture (`B120`)
is the same shape — boot the real app out of process, walk `app.routes`, ask
for every GET path that takes no parameter — and it records status and
byte-identity because that is what the offline row needed. This records the
**bodies**, because a CDN scan and a CSP check have to read what was served.
Switching that fixture onto this helper is filed as `B260`; it was held by
another row when this landed and editing it would have broken that merge.

Two things route enumeration alone does not see, and both are the point:

  * **The `/static` mount is not a route.** It is a `Mount` with no `methods`
    and no per-file path, so walking `app.routes` finds `/static` and none of
    the documents under it — which is exactly where `B211`'s two prototype
    pages live, and where the CDN scan that read `static/**` was looking all
    along without ever asking the server for them.
  * **Subresources.** A page that names `/static/lib/x.js` is only fixed if
    that URL answers, so every same-origin `src`/`href` a served document names
    is fetched too and its status recorded. That is what tells a vendoring
    apart from a rename.

Run out of process because importing `app` pulls the whole application up.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

# `src=` / `href=` values that start with a single `/` — this origin's own
# paths. Deliberately a crude regex and deliberately a *second* reading of the
# document from the one the browser does: this is a test, and a test that
# shares its parser with the thing it checks agrees with it by construction.
_SAME_ORIGIN_REF = re.compile(r"""(?:src|href)\s*=\s*["'](/(?!/)[^"'\s>]*)["']""")

_PROBE = r'''
import json, pathlib, re, sys

import app as app_module
from fastapi.testclient import TestClient
from src.constants import STATIC_DIR

SAME_ORIGIN_REF = re.compile(r"""(?:src|href)\s*=\s*["'](/(?!/)[^"'\s>]*)["']""")

client = TestClient(app_module.app)

urls = []
for route in app_module.app.routes:
    path = getattr(route, "path", None)
    methods = getattr(route, "methods", set()) or set()
    if not path or "GET" not in methods:
        continue
    # A path parameter means the route is not a page anyone can simply open.
    if "{" in path:
        continue
    urls.append(path)

# The `/static` mount answers for files, not routes, so its documents have to
# be enumerated from the directory it is pointed at — which is what a browser
# can reach. `lib/` is skipped: vendored bundles carry their own upstream URLs
# internally and are excluded from the CDN scan for that reason.
for f in sorted(pathlib.Path(STATIC_DIR).rglob("*.html")):
    rel = f.relative_to(STATIC_DIR).as_posix()
    if rel.startswith("lib/"):
        continue
    urls.append("/static/" + rel)

def record(url):
    res = client.get(url, follow_redirects=False)
    ctype = res.headers.get("content-type", "")
    textual = ("text/" in ctype or "json" in ctype or "javascript" in ctype
               or "xml" in ctype or not ctype)
    row = {
        "status": res.status_code,
        "content_type": ctype,
        "csp": res.headers.get("content-security-policy", ""),
        "etag": res.headers.get("etag"),
        "bytes": len(res.content),
        "body": res.text if textual else "",
        "is_html": "text/html" in ctype,
    }
    # The conditional answer, which is a different code path and carries its
    # own policy. RFC 9111 §4.3.4 has the client update its stored headers
    # from a `304`, so a `304` whose CSP names no hash leaves that client
    # holding a stored body nothing authorises (`B121`).
    if row["etag"]:
        again = client.get(url, headers={"If-None-Match": row["etag"]},
                           follow_redirects=False)
        row["conditional"] = {
            "status": again.status_code,
            "bytes": len(again.content),
            "csp": again.headers.get("content-security-policy", ""),
        }
    return row

pages = {}
for url in sorted(set(urls)):
    pages[url] = record(url)

# Second pass: everything those documents point at on this origin.
refs = {}
for url, row in sorted(pages.items()):
    if not row["is_html"]:
        continue
    for ref in SAME_ORIGIN_REF.findall(row["body"]):
        ref = ref.split("#")[0]
        if not ref or ref in pages or ref in refs:
            continue
        got = record(ref)
        got["body"] = ""          # assets are not scanned, only resolved
        got["referenced_by"] = url
        refs[ref] = got

print("RESULT=" + json.dumps({"pages": pages, "refs": refs}, sort_keys=True))
'''


def probe_served_surface(tmp_path) -> dict:
    """Boot the real app and return `{"pages": {...}, "refs": {...}}`.

    `pages` is url → `{status, content_type, csp, etag, bytes, body, is_html}`
    for every parameter-free GET route plus every HTML document under the
    `/static` mount. `refs` is the same for every same-origin `src`/`href`
    those documents name, minus the body, plus `referenced_by`.
    """
    env = os.environ.copy()
    env.update({
        "AUTH_ENABLED": "false",
        "CHROMADB_CONNECT_TIMEOUT": "0.01",
        "CHROMADB_HOST": "127.0.0.1",
        "CHROMADB_PORT": "9",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
        "PANTHEON_DATA_DIR": str(tmp_path),
        "PANTHEON_DISABLE_MCP": "1",
        "PYTHONPATH": str(_REPO),
        "PYTHON_DOTENV_DISABLED": "1",
    })
    result = subprocess.run([sys.executable, "-c", _PROBE], cwd=str(_REPO), env=env,
                            capture_output=True, text=True, timeout=600, check=False)
    assert result.returncode == 0, result.stderr[-4000:]
    line = next((l for l in result.stdout.splitlines() if l.startswith("RESULT=")), None)
    assert line is not None, result.stdout[-4000:]
    return json.loads(line.removeprefix("RESULT="))


def same_origin_refs(html: str) -> list:
    """The `src`/`href` values in `html` that point at this origin."""
    return [r.split("#")[0] for r in _SAME_ORIGIN_REF.findall(html)]
