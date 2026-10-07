# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-01` (NAV-M-8) — every window has a URL the server answers with the app.

Measured on `9560d50`: `/settings`, `/skills`, `/workbench`, `/research`,
`/compare`, `/theme` and `/brain` answered a raw `{"detail":"Not Found"}` — no
app, no way back in but editing the address — while the eight older routes
(`/notes`, `/calendar`, `/cookbook`, `/email`, `/memory`, `/gallery`, `/tasks`,
`/library`) served it. The browser now writes the top window's URL as it opens
(`static/js/backStack.js`), one level deeper for a window's tab
(`/settings/shortcuts`), so a reload — or a link — has to land on the app.

Driven, not read (`Law 20`): the real app booted out of process behind the real
`AuthMiddleware` (`tests/helpers/gated_app.py`), asked as a stranger and as a
signed-in member. What is pinned: every path in `backStack.js`'s own table is
served (the table is read out of the module, so a window added there and not
here fails), a tab below each is too, the gate still stands in front of all of
them, and a path nobody draws still answers 404 — so the new routes cannot
swallow one registered after them.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.gated_app import gated_app_probe

ROOT = Path(__file__).resolve().parents[1]
BACK_JS = ROOT / "static" / "js" / "backStack.js"


def _window_paths() -> list:
    """`ROUTES` and `ROUTE_ALIASES` out of the real `backStack.js` under node:
    every segment the browser writes or reads."""
    script = ("import(%s).then((m) => console.log(JSON.stringify("
              "[...Object.values(m.ROUTES), ...Object.keys(m.ROUTE_ALIASES)])))" % json.dumps(BACK_JS.as_uri()))
    proc = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True,
                          timeout=60, check=True)
    segs = json.loads(proc.stdout.strip().splitlines()[-1])
    assert len(segs) >= 16, segs
    return sorted(set(segs))


_PROBE = r'''
paths = PATHS
def ask(c, url):
    r = c.get(url, follow_redirects=False)
    return {"status": r.status_code, "location": r.headers.get("location"),
            "app": b'id="chat-container"' in r.content}
RESULT["anonymous"] = {p: ask(client(None), p) for p in ["/settings", "/skills/browse"]}
member = client(MEMBER)
RESULT["member"] = {p: ask(member, p) for p in paths}
RESULT["member_tab"] = {p: ask(member, p + "/somewhere") for p in paths}
RESULT["nobody"] = {p: ask(member, p) for p in ["/nope", "/settings/a/b", "/api/nope"]}
'''


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_every_window_url_serves_the_app_behind_the_gate(tmp_path):
    paths = ["/" + s for s in _window_paths()]
    out = gated_app_probe(tmp_path, _PROBE.replace("PATHS", repr(paths)))
    assert out["premise"]["auth_enabled"] is True
    for p, r in out["anonymous"].items():
        assert r["status"] in (302, 303, 307) and "/login" in (r["location"] or ""), (p, r)
    bad = {p: r for p, r in out["member"].items() if r["status"] != 200 or not r["app"]}
    assert not bad, bad
    bad = {p: r for p, r in out["member_tab"].items() if r["status"] != 200 or not r["app"]}
    assert not bad, bad
    for p, r in out["nobody"].items():
        assert r["status"] == 404 and not r["app"], (p, r)
