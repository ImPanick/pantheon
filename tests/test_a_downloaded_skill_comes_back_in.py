# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1469` — the file a skill's *Download* gives can be imported again.

`GET /api/skills/{id}/export` has said since `P22-23` that "a download is an
import's inverse", and `SkillsManager.import_bundle_from_files` was written for
it — but no route, tool or button took the file back. The 2026-10-25 dead-code
audit found it. `POST /api/skills/import-file` and Skills → *From a file…* are
the door: admin-only like the URL import beside them, bounded like a fetched
bundle, and a name already taken is kept as a new name with a sentence saying so.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import routes.skills_routes as SR
from services.memory.skills import SkillsManager

ROOT = Path(__file__).resolve().parent.parent


def _client(sm, monkeypatch, *, admin=True):
    def _gate(request):
        if not admin:
            raise HTTPException(403, "Admin only")
    monkeypatch.setattr(SR, "require_admin", _gate)
    app = FastAPI()

    @app.middleware("http")
    async def _person(request: Request, call_next):
        request.state.current_user = "ada"
        return await call_next(request)

    app.include_router(SR.setup_skills_routes(sm))
    return TestClient(app)


def _seed(sm):
    sm.add_skill(name="tidy-downloads", description="Tidy the downloads folder",
                 category="files", when_to_use="when it is full",
                 procedure=["List what is older than a week", "Move it to an archive"], owner="ada")


def test_a_download_imports_back(tmp_path, monkeypatch):
    src = SkillsManager(str(tmp_path / "a"), library_root="")
    _seed(src)
    exported = _client(src, monkeypatch).get("/api/skills/tidy-downloads/export").json()
    assert exported["skill"] == "tidy-downloads" and "SKILL.md" in exported["files"]

    dst = SkillsManager(str(tmp_path / "b"), library_root="")
    res = _client(dst, monkeypatch).post("/api/skills/import-file", json=exported)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True and body["skill"]["name"] == "tidy-downloads" and body["notes"] == []
    md = dst.read_skill_md("tidy-downloads", owner="ada")
    assert "Move it to an archive" in md

    # the same file again: kept under a new name, and the answer says so
    again = _client(dst, monkeypatch).post("/api/skills/import-file", json=exported).json()
    assert again["skill"]["name"] != "tidy-downloads"
    assert "already exists" in again["notes"][0]


def test_a_file_with_no_skill_or_too_much_is_refused(tmp_path, monkeypatch):
    sm = SkillsManager(str(tmp_path), library_root="")
    c = _client(sm, monkeypatch)
    assert c.post("/api/skills/import-file", json={"files": {}}).status_code == 400
    many = {f"f{i}.md": "x" for i in range(SR.SKILL_FILE_MAX_FILES + 1)}
    assert c.post("/api/skills/import-file", json={"files": many}).status_code == 400
    big = {"SKILL.md": "x" * (SR.SKILL_FILE_MAX_BYTES + 1)}
    assert c.post("/api/skills/import-file", json={"files": big}).status_code == 400


def test_only_an_admin_imports_a_file(tmp_path, monkeypatch):
    sm = SkillsManager(str(tmp_path), library_root="")
    res = _client(sm, monkeypatch, admin=False).post(
        "/api/skills/import-file", json={"files": {"SKILL.md": "---\nname: x\n---\n"}})
    assert res.status_code == 403


def test_the_button_is_drawn_and_wired():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "js" / "skills.js").read_text(encoding="utf-8")
    assert 'id="skill-import-file-btn"' in html and 'id="skill-import-file"' in html
    assert "/api/skills/import-file" in js and "importSkillFromFile(m, f)" in js
