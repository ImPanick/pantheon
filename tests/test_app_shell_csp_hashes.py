# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B141` — the app shell's inline scripts are authorised by their own bytes.

Until 2026-09-16 `SecurityHeadersMiddleware` minted `secrets.token_hex(16)` per
request, wrote it into `script-src 'nonce-…'` on **every** response, and
`serve_html_with_nonce` substituted it into the 7 `{{CSP_NONCE}}` placeholders
in `static/index.html` and the 3 in `static/login.html`. Those tokens were the
only part of a 285 KB response that varied, and they are why `/` was the one
precached URL of 213 that could carry no validator (`B85`, `B121`).

The blocks are authorised by `'sha256-…'` now. **This file is the security
half**, not the caching half: a policy that got cheaper by getting weaker would
pass every assertion in `test_offline_shell_manifest.py` and fail here. So it
asks three things of the real app's real headers.

* Every inline block the page ships is authorised — the page still runs.
* **Only** those blocks are. The hash-matching rule is the browser's own:
  base64 of the SHA-256 of the script's source text. A block with one byte
  changed — which is what an injection into an authorised block looks like —
  matches nothing in the policy. A nonce could not say that: it authorises
  whatever bytes end up inside a tag carrying it.
* Nothing blanket got added on the way past. No `'unsafe-inline'`, no
  `'unsafe-eval'`, and no inline source at all on a response that served no
  page.

The extraction here is deliberately a **different** implementation from
`src/app_helpers._InlineScriptCollector` — comments stripped, then a regex —
so the two have to agree about what a script is. `index.html:313` has the
string `<script` inside an HTML comment, which is exactly the disagreement
that would ship a hash list one entry long in the wrong direction.
"""
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from tests.helpers.source_text import blank, blank_text  # B290

_REPO = Path(__file__).resolve().parent.parent

_SCRIPT_OPEN = re.compile(r"<script\b([^>]*)>", re.I)
_TYPE = re.compile(r"""type\s*=\s*['"]?([^'">\s]*)""", re.I)
_EXECUTABLE = {"", "module", "text/javascript", "application/javascript",
               "text/ecmascript", "application/ecmascript",
               "application/x-javascript", "text/jscript"}


def _inline_blocks(html: str) -> list:
    """Every inline `<script>` a browser would execute, read a second way."""
    # `embedded=False`: the comment blanker must not touch a `<script>` body,
    # because the body is what gets hashed for the CSP.
    text = blank_text(html, "html", embedded=False)
    out = []
    for m in _SCRIPT_OPEN.finditer(text):
        attrs = m.group(1)
        if re.search(r"\bsrc\s*=", attrs, re.I):
            continue
        kind = _TYPE.search(attrs)
        if (kind.group(1).strip().lower() if kind else "") not in _EXECUTABLE:
            continue
        end = text.find("</script", m.end())
        assert end != -1, "unterminated <script> in the served page"
        out.append(text[m.end():end])
    return out


def _hash_source(script_text: str) -> str:
    """The CSP source that matches `script_text`, by the browser's own rule."""
    digest = hashlib.sha256(script_text.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


def _script_src(csp: str) -> str:
    for directive in csp.split(";"):
        directive = directive.strip()
        if directive.startswith("script-src "):
            return directive
    raise AssertionError(f"no script-src in {csp!r}")


def _probe(tmp_path, auth_enabled: str, paths) -> dict:
    """Ask the real app for each path's body and headers, out of process.

    Same shape as `test_offline_shell_manifest`'s probes, and for the same
    reason: importing `app` pulls the whole application up, and the subject
    here is what goes on the wire rather than what a function returns.
    """
    env = os.environ.copy()
    env.update({
        "AUTH_ENABLED": auth_enabled,
        "CHROMADB_CONNECT_TIMEOUT": "0.01",
        "CHROMADB_HOST": "127.0.0.1",
        "CHROMADB_PORT": "9",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
        "PANTHEON_DATA_DIR": str(tmp_path),
        "PANTHEON_DISABLE_MCP": "1",
        "PYTHONPATH": str(_REPO),
        "PYTHON_DOTENV_DISABLED": "1",
    })
    probe = textwrap.dedent(
        """
        import json
        import sys
        import app as app_module
        from fastapi.testclient import TestClient

        client = TestClient(app_module.app)
        out = {}
        for path in json.loads(sys.argv[1]):
            res = client.get(path, follow_redirects=False)
            out[path] = {
                "status": res.status_code,
                "csp": res.headers.get("content-security-policy"),
                "body": res.text,
            }
        print("RESULT=" + json.dumps(out))
        """
    )
    result = subprocess.run([sys.executable, "-c", probe, json.dumps(list(paths))],
                            cwd=str(_REPO), env=env, capture_output=True,
                            text=True, timeout=300, check=False)
    assert result.returncode == 0, result.stderr
    line = next((l for l in result.stdout.splitlines() if l.startswith("RESULT=")), None)
    assert line is not None, result.stdout
    return json.loads(line.removeprefix("RESULT="))


@pytest.fixture(scope="module")
def shell(tmp_path_factory) -> dict:
    return _probe(tmp_path_factory.mktemp("csp_shell"), "false",
                  ["/", "/api/health", "/static/style.css"])


@pytest.fixture(scope="module")
def login(tmp_path_factory) -> dict:
    # `/` redirects to `/login` with auth on; `/login` redirects to `/` with it
    # off (`app.py`), so the login page can only be measured in this mode.
    return _probe(tmp_path_factory.mktemp("csp_login"), "true", ["/login"])


@pytest.mark.parametrize("page", ["/", "/login"])
def test_every_inline_block_the_page_ships_is_authorised(page, shell, login):
    """The page still runs. On the tree before `B141` the policy named a nonce
    and no hash at all, so this fails there for every block."""
    row = (login if page == "/login" else shell)[page]
    assert row["status"] == 200, row["status"]
    blocks = _inline_blocks(row["body"])
    assert len(blocks) >= 3, f"{page} parsed as {len(blocks)} inline blocks"
    script_src = _script_src(row["csp"])
    for i, block in enumerate(blocks):
        assert _hash_source(block) in script_src, (
            f"{page} inline block {i} ({len(block)} bytes) is in the document "
            "and in no source of the policy — it is blocked and the page does "
            "not run"
        )


@pytest.mark.parametrize("page", ["/", "/login"])
def test_the_policy_authorises_those_blocks_and_nothing_else(page, shell, login):
    """The half a nonce cannot do.

    A `'nonce-…'` authorises whatever ends up inside a tag carrying it, so an
    injection into an already-authorised block executes. A hash is over the
    bytes: change one and it matches nothing. Both directions are asserted —
    the mutated block is refused, and the count of hash sources equals the
    count of blocks, so no spare authorisation is riding along.
    """
    row = (login if page == "/login" else shell)[page]
    script_src = _script_src(row["csp"])
    blocks = _inline_blocks(row["body"])
    sources = re.findall(r"'sha256-[^']+'", script_src)
    assert len(sources) == len({_hash_source(b) for b in blocks}), (
        page, len(sources), len(blocks))

    injected = blocks[0] + "\nfetch('/api/admin/export').then(r=>r.text())"
    assert _hash_source(injected) not in script_src
    # A single byte, not a whole appended statement: the hash has to be exact
    # or this assertion is about the size of the change rather than the rule.
    tweaked = blocks[0].replace(";", ";;", 1) if ";" in blocks[0] else blocks[0] + " "
    assert tweaked != blocks[0]
    assert _hash_source(tweaked) not in script_src


@pytest.mark.parametrize("page", ["/", "/login"])
def test_the_policy_gained_no_blanket_source(page, shell, login):
    """`FORBIDDEN.md` Part 2. The caching row must not buy its 304 with a
    widening — and `'unsafe-inline'` is *ignored* by a browser whenever a hash
    or nonce source is present, so a policy carrying both would read as safe
    and behave as safe right up until the hashes were removed."""
    row = (login if page == "/login" else shell)[page]
    script_src = _script_src(row["csp"])
    assert "'unsafe-inline'" not in script_src
    assert "'unsafe-eval'" not in script_src.replace("'wasm-unsafe-eval'", "")
    assert "'strict-dynamic'" not in script_src
    assert "'wasm-unsafe-eval'" in script_src, "P16-07: Python stops running without it"
    # Every source is one of: the origin, a hash, or the wasm allowance.
    for source in script_src.removeprefix("script-src ").split():
        assert source == "'self'" or source == "'wasm-unsafe-eval'" \
            or source.startswith("'sha256-"), source
    # `style-src 'unsafe-inline'` is separately retained with a written reason
    # at core/middleware.py; this row does not touch it in either direction.
    assert "style-src 'self' 'unsafe-inline'" in row["csp"]


def test_a_response_that_served_no_page_carries_no_inline_allowance(shell):
    """The nonce used to go out on every response in the app, including JSON
    and static assets that have no inline script to authorise. Nothing loses a
    script by its absence: a `script-src` naming any hash or nonce source
    already refused every inline block it did not name."""
    for path in ("/api/health", "/static/style.css"):
        row = shell[path]
        assert row["status"] == 200, (path, row["status"])
        script_src = _script_src(row["csp"])
        assert script_src == "script-src 'self' 'wasm-unsafe-eval'", (path, script_src)


def test_no_response_carries_a_per_request_nonce(shell, login):
    """The caching claim in `B121`, stated as a property of the header rather
    than of the body: a `'nonce-…'` in `script-src` is per-request by
    construction, and a `304` updates the stored response's headers from it
    (RFC 9111 §4.3.4). One left in here is a cached shell under a policy naming
    a nonce its own body never contained."""
    for row in list(shell.values()) + list(login.values()):
        if row["csp"]:
            assert "'nonce-" not in row["csp"], row["csp"]
        assert "{{CSP_NONCE}}" not in row["body"]
