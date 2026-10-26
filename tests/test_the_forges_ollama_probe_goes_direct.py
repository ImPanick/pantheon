# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1262` — the Forge's probe of a local Ollama went through the operator's proxy.

Measured by the row with every proxy variable set and
`NO_PROXY=127.0.0.1,localhost`: each Forge open sent
`GET http://host.docker.internal:11434/api/tags` to the proxy — the model scan
script (`routes/cookbook_helpers._cached_model_scan_script`) probed its three
local addresses with `urllib.request.urlopen`, which honours `HTTP_PROXY`, and
`NO_PROXY` did not name the Docker host. Not `Law 16` (the far end is the
operator's own), but a LAN address handed to a corporate proxy is `B982`'s
shape.

Driven, not read (`Law 20`): the real generated script runs in a child Python
with a real recording proxy on loopback in `HTTP_PROXY`/`http_proxy`, the row's
`NO_PROXY`, and a home directory with no model caches. The proxy must be asked
nothing.
"""
from __future__ import annotations

import http.server
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from routes.cookbook_helpers import _cached_model_scan_script


@pytest.fixture()
def proxy():
    """An HTTP proxy that records what it is asked and answers 502."""
    asked = []

    class _Proxy(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — the stdlib's name
            asked.append(self.path)
            self.send_response(502)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_CONNECT(self):  # noqa: N802
            asked.append(f"CONNECT {self.path}")
            self.send_response(502)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Proxy)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", asked
    finally:
        srv.shutdown()
        srv.server_close()


def _run(script: str, proxy_url: str, home: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k.lower() not in {"http_proxy", "https_proxy", "all_proxy", "no_proxy",
                                "hf_home", "huggingface_hub_cache"}}
    env.update({
        "HOME": str(home), "PATH": "/usr/bin:/bin",   # no `ollama` on the path
        "HTTP_PROXY": proxy_url, "http_proxy": proxy_url,
        "HTTPS_PROXY": proxy_url, "https_proxy": proxy_url,
        "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
    })
    return subprocess.run([sys.executable, "-I", "-c", script], env=env, cwd=str(home),
                          capture_output=True, text=True, timeout=60)


def test_the_ollama_probe_never_asks_the_proxy(proxy, tmp_path):
    """The row's `Verify:` shape: every proxy variable set, and the proxy hears
    nothing from a Forge scan."""
    proxy_url, asked = proxy
    done = _run(_cached_model_scan_script(), proxy_url, tmp_path)

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().splitlines()[-1] == "[]"   # nothing on this machine
    assert asked == [], f"the scan sent {asked} to the operator's proxy"


def test_the_probe_still_asks_all_three_local_addresses(proxy, tmp_path):
    """Direct is not skipped: a recording `urlopen` stand-in in the same child
    sees the three addresses asked, through an opener with no proxy."""
    proxy_url, _ = proxy
    probe = (
        "import urllib.request, json\n"
        "_probed = []\n"
        "_real = urllib.request.build_opener\n"
        "def build_opener(*handlers):\n"
        "    opener = _real(*handlers)\n"
        "    proxies = [h for h in opener.handlers if isinstance(h, urllib.request.ProxyHandler)]\n"
        "    def open(url, timeout=None):\n"
        "        _probed.append((url, [p.proxies for p in proxies]))\n"
        "        raise OSError('no Ollama here')\n"
        "    opener.open = open\n"
        "    return opener\n"
        "urllib.request.build_opener = build_opener\n"
    )
    script = _cached_model_scan_script().replace(
        "print(json.dumps(models))", "print(json.dumps(_probed))")
    done = _run(probe + script, proxy_url, tmp_path)

    assert done.returncode == 0, done.stderr
    import json
    seen = json.loads(done.stdout.strip().splitlines()[-1])
    assert [url for url, _ in seen] == [
        "http://127.0.0.1:11434/api/tags",
        "http://localhost:11434/api/tags",
        "http://host.docker.internal:11434/api/tags",
    ]
    # No proxy handler on the opener at all: an empty `ProxyHandler` has no
    # `*_open` method for urllib to install, and passing it keeps the default
    # one (which reads the environment) out.
    assert all(proxies == [] for _, proxies in seen), seen
