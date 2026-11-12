# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2098` — where a skill came from decides whether it is published.

The owner's ruling: "any imported skill gets auto-published. Custom built
skills and low-confidence system generated skills get dry-runs or corrective
review before published (manually)."

* An **import** — a link (GitHub, skills.sh, an install line), a skill file
  *Download* gave, or the bundled library's *Add* — is published when it lands,
  whatever its own frontmatter says. Before this, a SKILL.md with no `status:`
  (every Claude-format skill) arrived a draft the model was never shown.
* An import the agent's own loopback starts (the internal-tool token, which
  `require_admin` accepts) is not a person choosing it, so it lands a draft.
* A skill a **person writes** in the editor is a draft until they publish it,
  and *Publish* — the card's `PUT` — does publish it.

Driven through the real routes on an ASGI client and a real `SkillsManager`;
only the GitHub fetch is stubbed.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.skills_routes as SR
import services.memory.skill_importer as si
from core.middleware import INTERNAL_TOOL_HEADER
from services.memory.skills import SkillsManager

OWNER = "ada"


def _md(name, status=None):
    fm = ["---", f"name: {name}", f"description: Does {name} things for the person."]
    if status:
        fm.append(f"status: {status}")
    return "\n".join(fm + ["---", "", "## Steps", "", "1. Open it", "2. Do it", ""])


def _client(sm, monkeypatch, *, agent=False):
    monkeypatch.setattr(SR, "require_admin", lambda request: None)
    app = FastAPI()

    @app.middleware("http")
    async def _person(request: Request, call_next):
        request.state.current_user = OWNER
        return await call_next(request)

    app.include_router(SR.setup_skills_routes(sm))
    client = TestClient(app)
    if agent:
        client.headers[INTERNAL_TOOL_HEADER] = "loopback-token"
    return client


def _status(sm, name):
    return next(s for s in sm.load(owner=OWNER) if s["name"] == name)["status"]


def _shown(sm):
    return {s["name"] for s in sm.injectable_skills(owner=OWNER)}


@pytest.fixture
def store(tmp_path):
    return SkillsManager(str(tmp_path), library_root="")


@pytest.fixture
def fetched(monkeypatch):
    """A one-skill link, fetched with no network: the folder-link path."""
    def _bundle(url):
        files = {"skills/tidy-logs/SKILL.md": _md("tidy-logs")}
        src = si.ResolvedSource(owner="acme", repo="ops-skills", ref="main", path="skills/tidy-logs")
        return files, src, []

    monkeypatch.setattr(si, "is_package_link", lambda url: False)
    monkeypatch.setattr(si, "fetch_skill_bundle_report", _bundle)


# ── imports publish ──────────────────────────────────────────────────────────

def test_a_link_a_person_imports_is_published(store, monkeypatch, fetched):
    res = _client(store, monkeypatch).post(
        "/api/skills/import-from-url",
        json={"url": "https://github.com/acme/ops-skills/tree/main/skills/tidy-logs"})
    assert res.status_code == 200, res.text
    assert _status(store, "tidy-logs") == "published"
    assert "tidy-logs" in _shown(store)


@pytest.mark.parametrize("declared", [None, "draft", "published"])
def test_a_skill_file_a_person_imports_is_published_whatever_it_says(store, monkeypatch, declared):
    res = _client(store, monkeypatch).post(
        "/api/skills/import-file", json={"files": {"SKILL.md": _md("rotate-keys", declared)}})
    assert res.status_code == 200, res.text
    assert _status(store, "rotate-keys") == "published"
    assert "rotate-keys" in _shown(store)


def test_a_package_installs_published_and_a_refresh_keeps_a_persons_demotion(store):
    files = {"skills/tidy-logs/SKILL.md": _md("tidy-logs", "draft")}
    src = si.ResolvedSource(owner="acme", repo="ops-skills", ref="main", path="skills/tidy-logs")
    store.install_package(si.single_skill_package(files, src), owner=OWNER)
    assert _status(store, "tidy-logs") == "published"
    # The person sends it back to draft; importing the same link again is a
    # refresh, and the refresh keeps what they decided.
    assert store.update_skill("tidy-logs", {"status": "draft"}, owner=OWNER)
    store.install_package(si.single_skill_package(files, src), owner=OWNER)
    assert _status(store, "tidy-logs") == "draft"


def test_the_agents_loopback_imports_a_draft(store, monkeypatch, fetched):
    agent = _client(store, monkeypatch, agent=True)
    res = agent.post("/api/skills/import-from-url",
                     json={"url": "https://github.com/acme/ops-skills/tree/main/skills/tidy-logs"})
    assert res.status_code == 200, res.text
    assert _status(store, "tidy-logs") == "draft"
    res = agent.post("/api/skills/import-file",
                     json={"files": {"SKILL.md": _md("rotate-keys", "published")}})
    assert res.status_code == 200, res.text
    assert _status(store, "rotate-keys") == "draft"
    assert not {"tidy-logs", "rotate-keys"} & _shown(store)


# ── what a person writes waits for them ──────────────────────────────────────

def test_a_skill_a_person_writes_is_a_draft_until_they_publish_it(store, monkeypatch):
    person = _client(store, monkeypatch)
    res = person.post("/api/skills/add", json={
        "name": "clear-print-queue", "description": "Clear a stuck print queue",
        "when_to_use": "jobs pile up", "procedure": ["Stop the spooler", "Start it"]})
    assert res.status_code == 200, res.text
    assert _status(store, "clear-print-queue") == "draft"
    assert "clear-print-queue" not in _shown(store)

    # The dry run is there to be used before publishing; it never publishes.
    # *Publish* on the card is this request, and it is the person's.
    res = person.put("/api/skills/clear-print-queue", json={"status": "published"})
    assert res.status_code == 200, res.text
    assert _status(store, "clear-print-queue") == "published"
    assert "clear-print-queue" in _shown(store)
