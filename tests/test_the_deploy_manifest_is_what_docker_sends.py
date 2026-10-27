# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B447` — the files the deploy's byte check covers are the tracked files the
image carries, measured with Docker's own code rather than reasoned from its
documentation.

The Dockerfile copies the build context into `/app` (`COPY . .`), so what the
image carries is what `docker build` sends as its context. The real Docker CLI
is run here against a stand-in for the daemon's API that keeps the context it
is sent — no daemon, no image, nothing pulled — and the tar it sends is the
measurement. **On `f3a9150e`:** 1,487 tracked files in the context, 503 of them
`.md` (479 under `library/`, 286 skill `SKILL.md` files), the only top-level
one `CREDITS.md`; the manifest checked 824. Every one of the 824 was in the
context, so the old manifest was not wrong, only short — by the skill library
and everything else `MANIFEST_ROOTS` did not name.

**What this does not measure.** The CLI's own context (the legacy builder's
path, `DOCKER_BUILDKIT=0`). BuildKit — the default builder — filters the
context in `fsutil` with the same `moby/patternmatcher` module, so it gives the
same answer by construction; that is read from its source, not observed here.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKER = shutil.which("docker")
needs_docker_cli = pytest.mark.skipif(DOCKER is None, reason="the docker CLI is not installed here")


@pytest.fixture(scope="module")
def pd():
    loader = importlib.machinery.SourceFileLoader("pantheon_deploy_b447", str(ROOT / "scripts" / "pantheon-deploy"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class _Daemon(BaseHTTPRequestHandler):
    """Just enough of the Engine API for `docker build` to send its context."""

    protocol_version = "HTTP/1.1"
    received: dict = {}

    def log_message(self, *a):
        pass

    def _answer(self, body=b"OK", ctype="text/plain"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Api-Version", "1.47")
        self.send_header("Ostype", "linux")
        self.send_header("Builder-Version", "1")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self._answer()

    def do_GET(self):
        self._answer()

    def do_POST(self):
        data = bytearray()
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            while True:
                size = int(self.rfile.readline().strip(), 16)
                if size == 0:
                    self.rfile.readline()
                    break
                data += self.rfile.read(size)
                self.rfile.readline()
        else:
            data += self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if "/build" in self.path:
            type(self).received["context"] = bytes(data)
        self._answer(b'{"stream":"received\\n"}\r\n', "application/json")


def _context_docker_sends(directory: Path) -> set:
    """Every file path in the build context the real `docker build` sends for
    `directory` — read from the tar it posts."""
    _Daemon.received = {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Daemon)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        env = dict(os.environ, DOCKER_HOST=f"tcp://127.0.0.1:{server.server_address[1]}",
                   DOCKER_BUILDKIT="0", NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost",
                   DOCKER_CONFIG=str(directory.parent / ".docker-config"))
        proc = subprocess.run([DOCKER, "build", "-q", "-f", str(directory / "Dockerfile"), str(directory)],
                              env=env, capture_output=True, text=True, timeout=180)
    finally:
        server.shutdown()
        server.server_close()
    raw = _Daemon.received.get("context")
    if raw is None:
        pytest.skip(f"this docker CLI sent no build context to the API (legacy builder gone?): "
                    f"{(proc.stderr or proc.stdout)[-400:]}")
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        return {m.name for m in tar.getmembers() if not m.isdir()}


# ── the measurement the row asks for ──────────────────────────────────────────

@needs_docker_cli
def test_the_manifest_is_every_tracked_file_docker_sends(pd, tmp_path):
    """`Verify:` the number of files the manifest checks equals the number of
    tracked files the image carries, measured. The checkout is sent as it is
    (untracked files too, as an operator's would be); only tracked files are
    compared, because only those have a blob to compare against."""
    tracked = set(subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                                 text=True, check=True).stdout.splitlines())
    sent = _context_docker_sends(ROOT)
    carried = tracked & sent
    manifest = set(pd.build_manifest())
    assert manifest == carried, (
        f"the manifest checks {len(manifest)} files and the image carries {len(carried)} tracked "
        f"files; carried and unchecked: {sorted(carried - manifest)[:12]}; checked and not "
        f"carried: {sorted(manifest - carried)[:12]}")
    skills = [p for p in carried if p.startswith("library/") and p.endswith("/SKILL.md")]
    assert len(skills) > 200, "the skill library is in the image and in the check"
    assert [p for p in carried if p.endswith(".md") and "/" not in p] == ["CREDITS.md"]


# ── the rules, against the real CLI ───────────────────────────────────────────

#: Every shape of line `moby/patternmatcher` treats differently.
_IGNORE = """# a comment line, and the next is blank

*.md
!KEEP.md
/anchored/
deep/**
**/cache
**/*.tmp
*/one-level*
temp?
venv/
!venv/keep.txt
a\\.b
"""
_FILES = [
    "README.md", "KEEP.md", "src/notes.md", "src/deeper/SKILL.md",
    "anchored/x.txt", "src/anchored/x.txt", "deep/a/b.txt", "deeper/x.txt",
    "cache", "src/cache/x.py", "src/cachex/y.py", "x.tmp", "src/a/b.tmp",
    "src/one-level-x", "src/sub/one-level-y", "temp1", "temp12", "src/temp1",
    "venv/lib/x.py", "venv/keep.txt", "a.b", "axb", "src/main.py",
]


@needs_docker_cli
def test_the_rules_answer_what_docker_answers_for_every_kind_of_line(pd, tmp_path):
    context = tmp_path / "ctx"
    for name in _FILES:
        (context / name).parent.mkdir(parents=True, exist_ok=True)
        (context / name).write_text(name)
    (context / ".dockerignore").write_text(_IGNORE)
    (context / "Dockerfile").write_text("FROM scratch\nCOPY . /app\n")
    sent = _context_docker_sends(context)
    patterns = pd.dockerignore_patterns(_IGNORE)
    ours = {name for name in _FILES if not pd.dockerignored(name, patterns)}
    assert ours == {name for name in _FILES if name in sent}, (
        f"docker sends {sorted(set(_FILES) & sent)}; the rules here keep {sorted(ours)}")
    # And what that is, so a reader need not run Docker to know.
    assert sorted(ours) == sorted([
        "KEEP.md", "src/notes.md", "src/deeper/SKILL.md", "src/anchored/x.txt",
        "deeper/x.txt", "src/cachex/y.py", "src/sub/one-level-y", "temp12",
        "src/temp1", "venv/keep.txt", "axb", "src/main.py"])   # `a\.b` keeps out `a.b`


# ── the rules, as Docker's documentation states them ─────────────────────────

def test_the_documentations_own_examples(pd):
    """docs.docker.com, *Build context* § `.dockerignore` files: `*/temp*`
    excludes `/somedir/temporary.txt`; `*/*/temp*` excludes
    `/somedir/subdir/temporary.txt`; `temp?` excludes `/tempa` and `/tempb`;
    `**/*.go` excludes every `.go` file; and `*.md` with `!README*.md` and
    `README-secret.md` keeps every README but the secret one."""
    p = pd.dockerignore_patterns("*/temp*\n*/*/temp*\ntemp?\n**/*.go\n")
    assert pd.dockerignored("somedir/temporary.txt", p)
    assert pd.dockerignored("somedir/subdir/temporary.txt", p)
    assert pd.dockerignored("tempa", p) and pd.dockerignored("tempb", p)
    assert not pd.dockerignored("temporary.txt", p)
    assert pd.dockerignored("main.go", p) and pd.dockerignored("a/b/c.go", p)
    q = pd.dockerignore_patterns("*.md\n!README*.md\nREADME-secret.md\n")
    assert not pd.dockerignored("README.md", q) and not pd.dockerignored("README-x.md", q)
    assert pd.dockerignored("README-secret.md", q) and pd.dockerignored("NOTES.md", q)


def test_the_repositorys_ignore_file_keeps_the_skill_library_and_drops_the_top_level_markdown(pd):
    patterns = pd.read_dockerignore()
    assert pd.dockerignored("README.md", patterns)
    assert not pd.dockerignored("CREDITS.md", patterns)          # `!CREDITS.md`: the notice ships
    assert not pd.dockerignored("library/ecc/skills/x/SKILL.md", patterns)
    assert pd.dockerignored("tests/test_x.py", patterns)
    assert pd.dockerignored("docs/media/a.png", patterns)
    assert not pd.dockerignored("static/js/theme.js", patterns)
    assert pd.dockerignored("services/node_modules/x/index.js", patterns)
