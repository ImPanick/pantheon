# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1227` — a static text file is compressed once per version, and a
stylesheet's comments go out empty where that cannot change what it does.

The `/static` mount answers with `Cache-Control: no-cache`, so every load
revalidates and every miss is a full answer, and the full answer went through
`GZipMiddleware`, which compresses per request: `style.css` (1.6 MB) took
78 ms to its last byte compressed against 20 ms plain, on every miss, and the
service worker's install walk fetched the whole module graph a second time.
`style.css`'s 2,250 comments were 172 KB of its 365 KB of gzip.

Now `src/static_representations.py` prepares a file's answer once per version
of it (its path and the ETag `FileResponse` makes from its mtime and size),
behind the first answer, and `_RevalidatingStatic` serves that. Driven (`Law 20`): the real app, out of
process, through its whole middleware stack (`TestClient`), and the real mount
over a temporary directory for a file that changes; then Chromium parses the
stylesheets as served and as on disk, and the two are the same sheet.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

SHEETS = ("style.css", "lib/katex/katex.min.css", "lib/swagger-ui/swagger-ui.css")

_PROBE = r'''
import gzip, hashlib, json, os, sys, tempfile, time
import app as app_module
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.routing import Mount
from src import static_representations as kept

out_dir = sys.argv[1]
GZ = {"Accept-Encoding": "gzip, deflate, br"}
PLAIN = {"Accept-Encoding": "identity"}
client = TestClient(app_module.app)
kept.forget()

def ask(c, url, headers):
    r = c.get(url, headers=headers)
    body = r.content     # httpx has undone any Content-Encoding
    return {"status": r.status_code, "encoding": r.headers.get("content-encoding"),
            "etag": r.headers.get("etag"), "vary": r.headers.get("vary"),
            "cache": r.headers.get("cache-control"), "ranges": r.headers.get("accept-ranges"),
            "length": r.headers.get("content-length"), "wire": r.num_bytes_downloaded,
            "sha": hashlib.sha256(body).hexdigest(), "bytes": len(body),
            "prepared": kept.prepared_count}, body

def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()

res = {"files": {}}
# A miss is answered as before and prepared behind the answer.
res["css_miss"], miss_body = ask(client, "/static/style.css", GZ)
res["css_miss_is_the_file"] = miss_body == open(os.path.join(app_module.STATIC_DIR, "style.css"), "rb").read()
res["settled"] = kept.settle(60)
first, css_body = ask(client, "/static/style.css", GZ)
second, again = ask(client, "/static/style.css", GZ)
res["css_first"], res["css_second"] = first, second
res["css_same_bytes"] = css_body == again
res["css_304"] = client.get("/static/style.css", headers={**GZ, "If-None-Match": first["etag"]}).status_code
res["css_plain"], plain = ask(client, "/static/style.css", PLAIN)
res["css_plain_same_text"] = plain == css_body
for name in %(sheets)r:
    ask(client, "/static/" + name, GZ)
    kept.settle(60)
    _, served = ask(client, "/static/" + name, GZ)
    target = os.path.join(out_dir, name.replace("/", "_"))
    open(target, "wb").write(served)
    res["files"][name] = target

js = os.path.join(app_module.STATIC_DIR, "js", "chat.js")
ask(client, "/static/js/chat.js", GZ)
kept.settle(60)
res["js"], _ = ask(client, "/static/js/chat.js", GZ)
res["js_file_sha"] = sha(js)
res["js_plain"], _ = ask(client, "/static/js/chat.js", PLAIN)
r = client.get("/static/js/chat.js", headers={**GZ, "Range": "bytes=0-99"})
res["js_range"] = {"status": r.status_code, "bytes": len(r.content),
                   "encoding": r.headers.get("content-encoding")}
font = next(f for f in sorted(os.listdir(os.path.join(app_module.STATIC_DIR, "fonts")))
            if f.endswith(".woff2"))
res["font"], _ = ask(client, "/static/fonts/" + font, GZ)
res["font_file_sha"] = sha(os.path.join(app_module.STATIC_DIR, "fonts", font))

# A file that changes: the real mount over a directory of its own, behind
# the same middleware app.py gives it.
d = tempfile.mkdtemp()
sheet = os.path.join(d, "a.css")
open(sheet, "w").write("/* the first version */\n.a { color: red; }\n" * 200)
mini = TestClient(Starlette(routes=[Mount("/s", app=app_module._RevalidatingStatic(directory=d))],
                            middleware=[Middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)]))
kept.forget()
ask(mini, "/s/a.css", GZ)
kept.settle(60)
one, b1 = ask(mini, "/s/a.css", GZ)
two, _ = ask(mini, "/s/a.css", GZ)
open(sheet, "w").write("/* the second, longer version */\n.b { color: blue; }\n" * 200)
st = os.stat(sheet)
os.utime(sheet, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
stale, b_stale = ask(mini, "/s/a.css", GZ)
kept.settle(60)
three, b3 = ask(mini, "/s/a.css", GZ)
res["changed"] = {"one": one, "two": two, "stale": stale, "three": three,
                  "stale_text": b_stale.decode()[:60],
                  "first_text": b1.decode()[:60], "third_text": b3.decode()[:60]}
print("RESULT=" + json.dumps(res))
''' % {"sheets": SHEETS}


@pytest.fixture(scope="module")
def probed(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("b1227")
    env = os.environ.copy()
    env.update({
        "CHROMADB_CONNECT_TIMEOUT": "0.01",
        "CHROMADB_HOST": "127.0.0.1",
        "CHROMADB_PORT": "9",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
        "PANTHEON_DATA_DIR": str(tmp_path),
        "PANTHEON_DISABLE_MCP": "1",
        "PYTHONPATH": str(ROOT),
        "PYTHON_DOTENV_DISABLED": "1",
    })
    served = tmp_path / "served"
    served.mkdir()
    result = subprocess.run([sys.executable, "-c", _PROBE, str(served)], cwd=str(ROOT), env=env,
                            capture_output=True, text=True, timeout=600, check=False)
    assert result.returncode == 0, result.stderr[-4000:]
    line = next((l for l in result.stdout.splitlines() if l.startswith("RESULT=")), None)
    assert line is not None, result.stdout[-4000:]
    return json.loads(line.removeprefix("RESULT="))


def test_a_miss_is_answered_as_before_and_prepared_behind_the_answer(probed):
    """The first load after a restart is the load it was: the file, gzipped
    by the middleware, while the answer is prepared on one background thread."""
    miss = probed["css_miss"]
    assert miss["status"] == 200 and miss["encoding"] == "gzip"
    # The file's own bytes, comments and all: not what is prepared.
    assert probed["css_miss_is_the_file"] is True
    assert probed["settled"] is True


def test_the_stylesheet_is_compressed_once_and_the_next_answer_is_the_same_bytes(probed):
    """The row's `Verify:` — later requests are served from what was
    prepared once, with the encoding and the ETag a fresh answer has."""
    first, second = probed["css_first"], probed["css_second"]
    assert first["etag"] == probed["css_miss"]["etag"]
    assert first["status"] == second["status"] == 200
    assert first["encoding"] == second["encoding"] == "gzip"
    assert first["prepared"] == second["prepared"] == 1, (first, second)
    assert probed["css_same_bytes"] is True
    assert first["etag"] and first["etag"] == second["etag"]
    assert first["cache"] == "no-cache"
    assert "Accept-Encoding" in (first["vary"] or "")
    assert int(first["length"]) == first["wire"]


def test_a_revalidation_is_still_a_304_and_a_plain_client_gets_the_same_sheet(probed):
    assert probed["css_304"] == 304
    plain = probed["css_plain"]
    assert plain["status"] == 200 and plain["encoding"] is None
    assert plain["etag"] == probed["css_first"]["etag"]
    assert probed["css_plain_same_text"] is True


def test_a_module_is_its_files_bytes_compressed_and_the_rest_goes_as_before(probed):
    """JavaScript keeps its comments; a range, a plain request and a font are
    answered from the file, as they were."""
    js = probed["js"]
    assert js["encoding"] == "gzip" and js["sha"] == probed["js_file_sha"]
    assert probed["js_plain"]["encoding"] is None and probed["js_plain"]["sha"] == probed["js_file_sha"]
    assert probed["js_plain"]["ranges"] == "bytes"
    assert probed["js_range"] == {"status": 206, "bytes": 100, "encoding": None}
    font = probed["font"]
    assert font["status"] == 200 and font["encoding"] is None
    assert font["sha"] == probed["font_file_sha"]


def test_a_changed_file_is_prepared_again(probed):
    changed = probed["changed"]
    assert changed["one"]["prepared"] == changed["two"]["prepared"] == 1
    # The new version's first answer is the new file, as a miss always is.
    assert changed["stale_text"].startswith("/* the second, longer version */")
    assert changed["three"]["prepared"] == 2
    assert changed["one"]["etag"] != changed["three"]["etag"]
    assert changed["first_text"].startswith("/**/\n.a { color: red; }")
    assert changed["third_text"].startswith("/**/\n.b { color: blue; }")


def test_the_served_stylesheet_has_fewer_bytes_and_the_same_lines(probed):
    file = (ROOT / "static" / "style.css").read_bytes()
    served = Path(probed["files"]["style.css"]).read_bytes()
    assert len(served) < len(file) * 0.85, (len(served), len(file))
    assert served.count(b"\n") == file.count(b"\n")
    assert served.startswith(b"/* SPDX-License-Identifier: AGPL-3.0-or-later */")


_CSSOM = r"""
const { chromium } = require('playwright');
const fs = require('fs');
const pairs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.setContent('<!doctype html><title>x</title>');
  const out = {};
  for (const [name, [onDisk, asServed]] of Object.entries(pairs)) {
    out[name] = await page.evaluate(([a, b]) => {
      // Every rule, recursively, as the browser serialises what it parsed:
      // selectors, declarations, custom properties' kept text, preludes.
      const flat = (rules, acc) => {
        for (const r of rules) {
          acc.push(r.cssText);
          if (r.cssRules) flat(r.cssRules, acc);
        }
        return acc;
      };
      const parse = (text) => {
        const el = document.createElement('style');
        el.media = 'not all';
        el.textContent = text;
        document.head.appendChild(el);
        const rules = flat(el.sheet.cssRules, []);
        el.remove();
        return rules;
      };
      const x = parse(a), y = parse(b);
      const differ = [];
      for (let i = 0; i < Math.max(x.length, y.length) && differ.length < 5; i++) {
        if (x[i] !== y[i]) differ.push([i, (x[i] || '').slice(0, 200), (y[i] || '').slice(0, 200)]);
      }
      return { rules: x.length, served: y.length, differ };
    }, [fs.readFileSync(onDisk, 'utf8'), fs.readFileSync(asServed, 'utf8')]);
  }
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
"""


@pytest.mark.skipif(NODE is None, reason=_SKIP or "")
def test_chromium_parses_each_served_stylesheet_into_the_same_rules_as_the_file(probed, tmp_path):
    """Why emptying is safe, measured where it matters: every rule the
    browser builds from the served sheet serialises exactly as the one it
    builds from the file — selectors (`.a/**/.b` is `.a.b`), custom
    properties' text, `@font-face` sources (what the service worker's install
    walk follows), all of it."""
    pairs = {name: [str(ROOT / "static" / name), probed["files"][name]] for name in SHEETS}
    (tmp_path / "pairs.json").write_text(json.dumps(pairs))
    (tmp_path / "cssom.cjs").write_text(_CSSOM)
    proc = subprocess.run([NODE, str(tmp_path / "cssom.cjs"), str(tmp_path / "pairs.json")],
                          capture_output=True, text=True, timeout=240, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-4000:]
    parsed = json.loads(proc.stdout.strip().splitlines()[-1])
    for name in SHEETS:
        row = parsed[name]
        assert row["rules"] > 0 and row["rules"] == row["served"], (name, row)
        assert row["differ"] == [], (name, row["differ"])
    assert parsed["style.css"]["rules"] > 5000
