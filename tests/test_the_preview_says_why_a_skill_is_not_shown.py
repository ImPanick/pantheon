# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B586` — "use this one only when the real tool is unavailable" is a line on
the Add form, and the preview says why a skill you wrote is not in the list.

The row: `fallback_for_toolsets` was the fifth field the skills API takes and
the only one still reachable by frontmatter alone (`P8-02` put the other four
on the form), and it is the one that can make a skill you just wrote invisible
for a reason the card does not show. *"What it needs is a phrasing, not a
field."* `B580` (closed) made the preview gate on the person's tools first.

Now: the form has the line *"Use only when these are unavailable"*, which posts
`fallback_for_toolsets`; and `GET /api/skills/index` carries `not_shown` — the
person's own skills the block leaves out, each with the gate that did it in a
sentence (`SkillsManager.withheld_from_index`, read from `skill_gate`, the one
function `injectable_skills` filters with) — which the preview draws under the
block. Measured on `ffaf6671`: no `fallback` anywhere under `static/js`, and the
endpoint returned only the skills that were in.

`Verify:` someone who has never read this tracker can express "use this one
only when the real tool is unavailable" without opening the raw editor, and can
see in the prompt preview why a skill they wrote is not in the list.
"""
from __future__ import annotations

import json
import shutil

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import src.agent_loop as agent_loop
from routes.skills_routes import setup_skills_routes
from services.memory.skills import SkillsManager, skill_gate
from test_the_workshop_surfaces_js import _EMPTY_STORE, _skills, skills_sandbox  # noqa: F401

OWNER = "alice"
FORM = {"name": "search-by-hand", "description": "find it without a search tool",
        "when_to_use": "when web search is not available",
        "procedure": ["ask the person for a link", "fetch it"],
        "fallback_for_toolsets": ["web_search"], "status": "published"}


def _client(sm, monkeypatch):
    monkeypatch.setattr(agent_loop, "get_setting", lambda k, d=None: d, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda o: set(), raising=False)
    app = FastAPI()

    @app.middleware("http")
    async def _person(request: Request, call_next):
        request.state.current_user = OWNER
        return await call_next(request)

    app.include_router(setup_skills_routes(sm))
    return TestClient(app)


# ── the server's half ───────────────────────────────────────────────────────

def test_a_stand_in_is_hidden_while_its_tool_is_on_and_the_preview_says_so(tmp_path, monkeypatch):
    sm = SkillsManager(str(tmp_path), library_root="")
    client = _client(sm, monkeypatch)
    assert client.post("/api/skills/add", json=FORM).status_code == 200
    stored = next(s for s in sm.load(owner=OWNER) if s["name"] == "search-by-hand")
    assert stored["fallback_for_toolsets"] == ["web_search"], "the field did not reach the file"

    idx = client.get("/api/skills/index").json()
    assert "search-by-hand" not in {e["name"] for e in idx["index"]}
    row = next(r for r in idx["not_shown"] if r["name"] == "search-by-hand")
    assert row["gate"] == "fallback" and row["tools"] == ["web_search"]
    assert "Hidden while `web_search` is on" in row["why"]
    assert "unavailable" in row["why"]


def test_with_the_tool_off_the_stand_in_is_in_the_block(tmp_path, monkeypatch):
    sm = SkillsManager(str(tmp_path), library_root="")
    client = _client(sm, monkeypatch)
    client.post("/api/skills/add", json=FORM)
    assert skill_gate(sm.load(owner=OWNER)[0], active_toolsets=["bash"]) is None
    assert skill_gate(sm.load(owner=OWNER)[0], active_toolsets=["web_search"]) == {
        "gate": "fallback", "tools": ["web_search"]}


def test_a_draft_and_a_switched_off_skill_say_why_too(tmp_path, monkeypatch):
    """The two reasons a person meets most. One list, one sentence each."""
    sm = SkillsManager(str(tmp_path), library_root="")
    client = _client(sm, monkeypatch)
    client.post("/api/skills/add", json={**FORM, "name": "half-done",
                                         "fallback_for_toolsets": [], "status": "draft"})
    client.post("/api/skills/add", json={**FORM, "name": "parked",
                                         "fallback_for_toolsets": []})
    group = sm.collections.create_group(OWNER, "Parked", ["parked"])
    sm.collections.update_group(OWNER, group["id"], enabled=False)
    why = {r["name"]: r for r in client.get("/api/skills/index").json()["not_shown"]}
    assert why["half-done"]["gate"] == "status" and "publish it" in why["half-done"]["why"]
    assert why["parked"]["gate"] == "off" and "Switched off" in why["parked"]["why"]


# ── the page's half ─────────────────────────────────────────────────────────

pytestmark_js = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytestmark_js
def test_the_form_posts_the_stand_in_line_and_clears_it(skills_sandbox):  # noqa: F811
    out = _skills(skills_sandbox, _EMPTY_STORE + """
        ready();
        await tick();
        setValue('new-skill-description', 'find it without a search tool');
        setValue('new-skill-fallback', 'web_search , web_fetch');
        calls.fetch.length = 0;
        fire(byId('add-skill-btn'), 'click');
        await tick();
        const post = calls.fetch.find(c => c.method === 'POST' && c.url.endsWith('/api/skills/add'));
        const lint = calls.fetch.find(c => c.method === 'POST' && c.url.endsWith('/api/skills/lint'));
        console.log(JSON.stringify({ body: post.body, lint: lint.body,
                                     left: byId('new-skill-fallback').value }));
    """)
    assert out["body"]["fallback_for_toolsets"] == ["web_search", "web_fetch"]
    assert out["lint"]["fallback_for_toolsets"] == ["web_search", "web_fetch"], \
        "the lint judges what the save sends"
    assert out["left"] == ""


def test_the_line_is_on_the_page_in_words_not_a_field_name():
    from test_the_workshop_surfaces_js import INDEX
    html = INDEX.read_text(encoding="utf-8")
    block = html[html.index('<details class="skill-more">'):html.index('id="add-skill-btn"')]
    assert 'id="new-skill-fallback"' in block
    assert "Use only when these are unavailable" in block
    assert "fallback_for_toolsets" not in block.split("-->")[-1], \
        "the visible line names the field rather than saying what it does"


@pytestmark_js
def test_the_preview_draws_each_left_out_skill_with_its_reason(skills_sandbox):  # noqa: F811
    not_shown = [
        {"name": "search-by-hand", "gate": "fallback", "tools": ["web_search"],
         "why": "Hidden while `web_search` is on: it is set to be used only when that tool is unavailable."},
        {"name": "<img src=x onerror=alert(1)>", "gate": "status", "status": "draft",
         "why": "A draft. The model is shown no draft you write — publish it to use it."},
    ]
    out = _skills(skills_sandbox, """
        mockFetch((url) => {
          if (url.includes('/api/skills/audit-status')) return res(200, { status: 'idle' });
          if (url.includes('/api/skills/index')) return res(200, { index: [], count: 0, not_shown: %s });
          if (url.includes('/api/prefs')) return res(200, {});
          if (url.includes('/api/skills')) return res(200, { skills: [], count: 0 });
          return res(200, {});
        });
        ready();
        await tick();
        fire(byId('skills-preview-btn'), 'click');
        await tick();
        const panel = byId('skills-prompt-panel');
        const rows = panel.querySelectorAll('.skill-prompt-not-shown');
        console.log(JSON.stringify({
          text: readable(panel),
          rows: rows.map(r => ({ gate: r.dataset.gate, text: readable(r) })),
          markup: panel.querySelectorAll('img').length,
        }));
    """ % json.dumps(not_shown))
    assert "not in that block, and why" in out["text"]
    assert [r["gate"] for r in out["rows"]] == ["fallback", "status"]
    assert "search-by-hand" in out["rows"][0]["text"]
    assert "Hidden while `web_search` is on" in out["rows"][0]["text"]
    assert out["markup"] == 0, "a skill name reached the panel as markup"
