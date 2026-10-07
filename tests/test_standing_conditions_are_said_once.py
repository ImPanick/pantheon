# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-07` (`PERF-M-16`, `SET-M-19`, `DOCS-M-9`): log noise.

Measured by the perf audit on `9560d50`: 54 "SMTP/IMAP not configured" WARNING
lines in a 45-minute session with no mail account (a pair per mail request and
per minute's poll), `FastEmbed init failed` at ERROR on every page load (35),
and ≈190 access-log lines per page load for `/static/` files (11,274 in the
session). Now a standing condition is said once per process (then at DEBUG) and
again only after it clears and returns, and a `/static/` file served is a DEBUG
access line. Driven: each logging site called as the app calls it, and the
access-log filter on a real uvicorn logging configuration.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _fresh_memory():
    import src.log_once as lo
    saved = set(lo._said)
    lo._said.clear()
    yield
    lo._said.clear()
    lo._said.update(saved)


def _levels(caplog, text):
    return [r.levelno for r in caplog.records if text in r.getMessage()]


def test_said_once_then_quietly_and_again_after_it_clears(caplog):
    from src.log_once import clear, log_once
    log = logging.getLogger("test.once")
    caplog.set_level(logging.DEBUG, logger="test.once")
    for _ in range(3):
        log_once(log, logging.WARNING, "k", "the thing is off")
    clear("k")
    log_once(log, logging.WARNING, "k", "the thing is off")
    assert _levels(caplog, "the thing is off") == [logging.WARNING, logging.DEBUG, logging.DEBUG, logging.WARNING]


def test_mail_not_configured_is_said_once(caplog, monkeypatch):
    from routes.email_helpers import _get_email_config
    for var in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    caplog.set_level(logging.DEBUG, logger="routes.email_helpers")
    for _ in range(5):
        _get_email_config()
    for kind in ("SMTP", "IMAP"):
        levels = _levels(caplog, f"{kind} not configured")
        assert levels.count(logging.WARNING) == 1, (kind, levels)
        assert len(levels) == 5


def test_fastembed_failing_is_said_once(caplog, monkeypatch):
    import src.embeddings as emb
    import src.embedding_lanes as lanes

    monkeypatch.setattr(emb, "_http_embed_down", True)
    monkeypatch.setattr(emb, "_load_persisted_endpoint", lambda: {})

    def refuse():
        raise RuntimeError("the local embedding model is not downloaded")

    monkeypatch.setattr(lanes, "ensure_fastembed_download_permitted", refuse)
    caplog.set_level(logging.DEBUG, logger="src.embeddings")
    for _ in range(4):
        assert emb.get_embedding_client() is None
    levels = _levels(caplog, "FastEmbed init failed")
    assert levels == [logging.ERROR, logging.DEBUG, logging.DEBUG, logging.DEBUG], levels


_ACCESS_PROBE = textwrap.dedent(
    """
    import logging, sys
    import app as app_module
    import uvicorn
    uvicorn.Config(app_module.app, log_level=sys.argv[1])   # configures logging, as `uvicorn.run` does
    access = logging.getLogger("uvicorn.access")
    line = '%s - "%s %s HTTP/%s" %d'
    for path, status in (("/static/app.js?v=1", 200), ("/static/fonts/a.woff2", 304),
                         ("/static/missing.js", 404), ("/api/sessions", 200)):
        access.info(line, "127.0.0.1:5", "GET", path, "1.1", status)
    """
)


def _access(tmp_path, level):
    env = os.environ.copy()
    env.update({"AUTH_ENABLED": "false", "CHROMADB_CONNECT_TIMEOUT": "0.01", "CHROMADB_HOST": "127.0.0.1",
                "CHROMADB_PORT": "9", "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
                "PANTHEON_DATA_DIR": str(tmp_path), "PANTHEON_DISABLE_MCP": "1",
                "PYTHONPATH": str(_REPO), "PYTHON_DOTENV_DISABLED": "1"})
    done = subprocess.run([sys.executable, "-c", _ACCESS_PROBE, level], cwd=_REPO, env=env,
                          capture_output=True, text=True, timeout=240)
    assert done.returncode == 0, done.stderr[-3000:]
    return [ln for ln in (done.stdout + done.stderr).splitlines() if '127.0.0.1:5 - "GET' in ln]


def test_a_static_file_served_is_not_an_info_line(tmp_path):
    lines = _access(tmp_path, "info")
    assert not any("/static/app.js" in ln or "/static/fonts/a.woff2" in ln for ln in lines), lines
    assert any("/static/missing.js" in ln for ln in lines), "a failed /static/ request must stay"
    assert any("/api/sessions" in ln for ln in lines)


def test_at_debug_the_static_lines_are_kept(tmp_path):
    lines = _access(tmp_path, "debug")
    assert any("/static/app.js" in ln for ln in lines), lines
