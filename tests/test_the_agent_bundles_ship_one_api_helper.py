# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2176`: the Codex plugin and the Claude Code skill ship the same API helper.

`integrations/codex/scripts/pantheon_api.py` and
`integrations/claude/skills/pantheon/scripts/pantheon_api.py` are one script in
two places. Each bundle is its own download (`GET /api/codex/plugin.zip` zips
`integrations/codex/`, `GET /api/claude/plugin.zip` zips
`integrations/claude/skills/`), is unpacked on its own (`~/plugins/pantheon/`,
`~/.claude/skills/pantheon/`), and each `SKILL.md` runs the copy beside it — so
each bundle needs its own file, and the duplicate is kept on purpose
(`D-2026-11-24-02`). Nothing held them equal; this does, and checks each zip
carries the script byte for byte.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CODEX = REPO / "integrations" / "codex" / "scripts" / "pantheon_api.py"
CLAUDE = REPO / "integrations" / "claude" / "skills" / "pantheon" / "scripts" / "pantheon_api.py"


def test_the_two_copies_are_byte_identical():
    assert CODEX.read_bytes() == CLAUDE.read_bytes(), (
        "integrations/codex/scripts/pantheon_api.py and "
        "integrations/claude/skills/pantheon/scripts/pantheon_api.py differ: edit one, "
        "copy it over the other — both bundles ship this script.")


def _download(monkeypatch, bundle: str) -> zipfile.ZipFile:
    """The bundle as its route serves it, signed in."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import routes.codex_routes as codex_routes

    monkeypatch.setattr(codex_routes, "require_authenticated_request", lambda request: "alice")
    app = FastAPI()
    app.include_router(codex_routes.setup_codex_routes() if bundle == "codex"
                       else codex_routes.setup_claude_routes())
    res = TestClient(app).get(f"/api/{bundle}/plugin.zip")
    assert res.status_code == 200, res.text
    return zipfile.ZipFile(io.BytesIO(res.content))


def test_each_download_carries_the_script_byte_for_byte(monkeypatch):
    codex = _download(monkeypatch, "codex")
    claude = _download(monkeypatch, "claude")
    assert codex.read("pantheon/scripts/pantheon_api.py") == CODEX.read_bytes()
    assert claude.read("skills/pantheon/scripts/pantheon_api.py") == CLAUDE.read_bytes()
