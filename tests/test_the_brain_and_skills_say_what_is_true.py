# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-02` — the server halves of the Brain and Skills findings: what is said
is what happened.

Each case drives the real code — the skills router through `TestClient`, the
store, the rewriter with a scripted model, the research loop with its model
calls stood in — and says what it measured on `32df791` before the fix.

  * `BRAIN-M-2`  a skill's state is `draft` or `published` (the seed wrote
    `active`, which nothing reads; `banana` was stored with a 200);
  * `BRAIN-M-3`  *Fix these with the model* writes only a better SKILL.md (a
    reply of "OK" was written as the skill and reported "Fixed");
  * `BRAIN-M-8`  a group name is one group;
  * `BRAIN-M-12` a failed download is one sentence;
  * `BRAIN-M-13` an unreadable judge says so in words;
  * `BRAIN-M-4/5` RAG says why it is off, on the list and on the upload;
  * `BRAIN-M-6`  a research run that found nothing says why it stopped;
  * `BRAIN-M-14` an empty import says which empty it is;
  * `BRAIN-M-15` / `BRAIN-U-14` the report page carries Pantheon's icon and a
    way back.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import ssl
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pydantic
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes.skills_routes import (
    SkillAddRequest, _eval_skill_run, _fetch_failure_sentence, setup_skills_routes,
)
from services.memory.skill_format import normalize_status
from services.memory.skill_improve import (
    WHY_NOT_A_SKILL, WHY_NOT_BETTER, ImproveOutcome, improve_from_lint,
)
from services.memory.skills import SkillsManager

ROOT = Path(__file__).resolve().parents[1]


# ── the skills router, with a scripted model ────────────────────────────────

def _app(sm: SkillsManager) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def _person(request: Request, call_next):
        request.state.current_user = request.headers.get("x-user") or "rowan"
        return await call_next(request)

    app.include_router(setup_skills_routes(sm))
    return TestClient(app)


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))
    sm = SkillsManager(str(tmp_path), library_root="")
    monkeypatch.setattr("routes.skills_routes._resolve_audit_models",
                        lambda owner=None: ("http://model.test", "scripted", {}, None))
    model = {"replies": []}

    async def _llm(url, model_id, messages, **kw):
        return model["replies"].pop(0) if model["replies"] else ""

    monkeypatch.setattr("src.llm_core.llm_call_async", _llm)
    return {"sm": sm, "client": _app(sm), "model": model, "root": tmp_path}


_THIN = {"name": "rotate-logs", "description": "Rotate the logs", "category": "ops",
         "when_to_use": "", "procedure": ["Rotate"], "source": "user"}


# ── BRAIN-M-2 · two states ──────────────────────────────────────────────────

def test_a_status_is_draft_or_published_on_write(world):
    """Measured on `32df791`: `POST /api/skills/add` with `status: "banana"`
    answered 200 and stored `banana`."""
    with pytest.raises(pydantic.ValidationError):
        SkillAddRequest(name="x", status="banana")
    c = world["client"]
    bad = c.post("/api/skills/add", json={**_THIN, "status": "banana"})
    assert bad.status_code == 422
    ok = c.post("/api/skills/add", json={**_THIN, "status": "published"})
    assert ok.status_code == 200, ok.text
    row = next(s for s in world["sm"].load(owner="rowan") if s["name"] == "rotate-logs")
    assert row["status"] == "published"


@pytest.mark.parametrize("written,read", [
    ("active", "published"), ("Published", "published"), ("approved", "published"),
    ("draft", "draft"), ("banana", "draft"), ("", "draft"), (None, "draft"),
])
def test_a_status_read_from_disk_is_one_of_the_two(world, written, read):
    """The showcase seeded four skills `status: active`: an "active" pill,
    hidden by *Published only*, and never in the catalogue the model is shown
    (`index_for` keeps `published`). A legacy word is read as what its writer
    meant; an unknown one as a draft."""
    assert normalize_status(written) == read
    sm = world["sm"]
    sm.add_skill(name="old-skill", description="An old one", procedure=["Do it"],
                 when_to_use="When asked", owner="rowan", source="user")
    path = next(world["root"].rglob("old-skill/SKILL.md"))
    text = path.read_text(encoding="utf-8")
    line = f"status: {written}" if written is not None else "status:"
    path.write_text("\n".join(line if ln.startswith("status:") else ln for ln in text.splitlines()) + "\n",
                    encoding="utf-8")
    row = next(s for s in sm.load(owner="rowan") if s["name"] == "old-skill")
    assert row["status"] == read
    listed = [e["name"] for e in sm.index_for(owner="rowan")] if hasattr(sm, "index_for") else None
    if listed is not None and read == "published":
        assert "old-skill" in listed, "a published skill is not in the catalogue"


def test_the_showcase_seeds_only_the_two_states():
    """The seed's own data, loaded and read — it is what the README's Skills
    picture shows."""
    import sys
    sys.path.insert(0, str(ROOT / "scripts" / "showcase"))   # as capture.py does
    try:
        spec = importlib.util.spec_from_file_location("showcase_seed", ROOT / "scripts" / "showcase" / "seed.py")
        seed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(seed)
    finally:
        sys.path.remove(str(ROOT / "scripts" / "showcase"))
    assert {s.get("status", "draft") for s in seed.SKILLS} <= {"draft", "published"}
    assert sum(s.get("status") == "published" for s in seed.SKILLS) == 4


# ── BRAIN-M-3 · only a better SKILL.md is written ───────────────────────────

def _thin_skill(world):
    sm = world["sm"]
    sm.add_skill(name="audit-skill", description="Audit", procedure=["Check"],
                 when_to_use="", owner="rowan", source="user")
    return sm.read_skill_md("audit-skill", owner="rowan")


def test_a_reply_that_is_not_a_skill_is_not_written(world):
    """Measured on `32df791` with a scripted model answering "OK": the file
    became frontmatter + `OK`, the description gone, version 1.0.0 → 1.0.1,
    and the panel said "Fixed … Before: 2 problems … After: 2 problems"."""
    before = _thin_skill(world)
    world["model"]["replies"].append("OK")
    done = asyncio.run(improve_from_lint(world["sm"], "audit-skill", "rowan"))
    assert done.outcome is ImproveOutcome.NO_REWRITE and done.why == WHY_NOT_A_SKILL
    assert world["sm"].read_skill_md("audit-skill", owner="rowan") == before, "the reply was written"
    world["model"]["replies"].append("OK")
    res = world["client"].post("/api/skills/audit-skill/improve")
    assert res.status_code == 422
    assert res.json()["detail"] == ("The model's answer was not a skill (no description or steps). "
                                    "Nothing was written.")


def test_a_rewrite_that_fixes_nothing_is_not_written(world):
    before = _thin_skill(world)
    same_but_reworded = before.replace("1. Check", "1. Check it")
    assert same_but_reworded != before
    world["model"]["replies"].append(same_but_reworded)
    done = asyncio.run(improve_from_lint(world["sm"], "audit-skill", "rowan"))
    assert done.outcome is ImproveOutcome.NO_REWRITE and done.why == WHY_NOT_BETTER
    assert world["sm"].read_skill_md("audit-skill", owner="rowan") == before


def test_a_rewrite_that_scores_better_is_written(world):
    _thin_skill(world)
    better = ("---\nname: audit-skill\ndescription: Audit a service's logs for errors after a deploy\n"
              "version: 1.0.0\ncategory: general\nstatus: draft\n---\n\n"
              "## When to use\nAfter a deploy, when error rates should be checked.\n\n"
              "## Procedure\n1. Open the service's log view for the last hour\n"
              "2. Filter to level ERROR\n3. Compare the count with the hour before the deploy\n\n"
              "## Pitfalls\n- Log rotation hides the start of the window\n\n"
              "## Verification\n- The error count is written down with both hours\n")
    world["model"]["replies"].append(better)
    done = asyncio.run(improve_from_lint(world["sm"], "audit-skill", "rowan"))
    assert done.outcome is ImproveOutcome.REWROTE, done.why
    after = done.after_counts
    assert (after.get("problem", 0), after.get("advisory", 0)) < (
        done.before_counts.get("problem", 0), done.before_counts.get("advisory", 0))


# ── BRAIN-M-8 · one group per name ──────────────────────────────────────────

def test_a_second_group_with_the_same_name_is_refused(world):
    """Measured: "Audit set" made six times gave `audit-set` … `audit-set-6`,
    six sidebar rows reading the same."""
    c = world["client"]
    first = c.post("/api/skills/groups", json={"title": "Audit set", "skills": []})
    assert first.status_code == 200, first.text
    again = c.post("/api/skills/groups", json={"title": "  audit SET ", "skills": []})
    assert again.status_code == 409
    assert again.json()["detail"] == "You already have a group called Audit set."
    other = c.post("/api/skills/groups", json={"title": "Writing", "skills": []}).json()["group"]
    rename = c.patch(f"/api/skills/groups/{other['id']}", json={"title": "Audit Set"})
    assert rename.status_code == 409
    keep = c.patch(f"/api/skills/groups/{first.json()['group']['id']}", json={"title": "Audit set"})
    assert keep.status_code == 200, "renaming a group to its own name was refused"
    assert len(c.get("/api/skills/collections").json()["groups"]) == 2


# ── BRAIN-M-12 · a failed download in one sentence ──────────────────────────

def _status_error(code, url="https://api.github.com/repos/o/r"):
    req = httpx.Request("GET", url)
    return httpx.HTTPStatusError("x", request=req, response=httpx.Response(code, request=req))


@pytest.mark.parametrize("exc,said", [
    (httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed "
                        "certificate in certificate chain (_ssl.c:1016)"),
     "Could not reach GitHub (TLS certificate rejected)."),
    (ssl.SSLCertVerificationError("certificate verify failed"), "Could not reach GitHub (TLS certificate rejected)."),
    (_status_error(404), "GitHub has nothing at that link."),
    (_status_error(403), "GitHub refused for now (rate limit). Try again later."),
    (_status_error(500), "Could not download from GitHub (HTTP 500)."),
    (httpx.ReadTimeout("t"), "GitHub did not answer in time."),
    (httpx.ConnectError("refused"), "Could not reach GitHub."),
    (ValueError("a bug"), None),
])
def test_a_failed_download_is_one_sentence(exc, said):
    """Measured: the 502's `detail` was the raw exception —
    `[SSL: CERTIFICATE_VERIFY_FAILED] … (_ssl.c:1016)` — printed twice."""
    assert _fetch_failure_sentence(exc) == said


def test_the_import_route_answers_the_sentence(world, monkeypatch):
    from services.memory import skill_importer as si

    def _boom(*a, **k):
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

    monkeypatch.setattr(si, "fetch_skill_bundle_report", _boom)
    monkeypatch.setattr(si, "is_package_link", lambda url: False)
    monkeypatch.setattr("routes.skills_routes.require_admin", lambda request: None)
    res = world["client"].post("/api/skills/import-from-url",
                               json={"url": "https://github.com/o/r/tree/main/skills/s"})
    assert res.status_code == 502
    assert res.json()["detail"] == "Could not reach GitHub (TLS certificate rejected)."


# ── BRAIN-M-13 · an unreadable judge ────────────────────────────────────────

def test_an_unreadable_judge_is_said_in_words(monkeypatch):
    """Measured: the verdict read `UNCLEAR · 0% Evaluator returned unparseable
    output.`"""
    async def _llm(*a, **k):
        return "I think it went fine overall."

    monkeypatch.setattr("src.llm_core.llm_call_async", _llm)
    verdict = asyncio.run(_eval_skill_run("---\nname: x\n---\n", "task", "transcript",
                                          "http://model.test", "scripted", {}))
    assert verdict["verdict"] == "unknown"
    assert verdict["summary"] == "The judge's answer could not be read — try again."


# ── BRAIN-M-4 / BRAIN-M-5 · RAG says why it is off ──────────────────────────

def test_rag_says_the_embedding_model_is_not_downloaded(monkeypatch):
    """Measured: the upload refused with "RAG system is not available — is the
    embedding service running?" while the log at that moment said the
    embedding model was not downloaded; the list said nothing at all."""
    import src.rag_singleton as rs
    import src.embedding_lanes as el
    from routes import personal_routes

    monkeypatch.setattr(rs, "get_rag_manager", lambda: None)
    monkeypatch.setattr(el, "fastembed_model_is_cached", lambda: False)
    monkeypatch.setattr(el, "model_download_allowed", lambda: False)
    monkeypatch.delenv("EMBEDDING_URL", raising=False)
    sentence = rs.rag_unavailable_reason()
    assert sentence == ("RAG is off: the embedding model is not downloaded — "
                        "Settings › System › Download models from the internet.")

    docs = MagicMock()
    docs.index = [{"name": "a.txt", "size": 3, "path": "/x/a.txt"}]
    docs.get_indexed_directories.return_value = []
    app = FastAPI()
    app.include_router(personal_routes.setup_personal_routes(docs, None, True))
    app.dependency_overrides[personal_routes.require_user] = lambda: "rowan"
    app.dependency_overrides[personal_routes.require_admin] = lambda: None
    listed = TestClient(app).get("/api/personal").json()
    assert listed["healthy"] is False and listed["reason"] == sentence
    assert listed["files"] == [{"name": "a.txt", "size": 3, "path": "/x/a.txt"}]

    monkeypatch.setattr(personal_routes, "get_rag_manager", lambda: None)
    monkeypatch.setattr(personal_routes, "require_privilege", lambda request, key: "rowan")
    up = TestClient(app).post("/api/personal/upload", files=[("files", ("n.txt", b"hello"))])
    assert up.status_code == 503 and up.json()["detail"] == sentence

    monkeypatch.setattr(rs, "get_rag_manager", lambda: object())
    healthy = TestClient(app).get("/api/personal").json()
    assert healthy["healthy"] is True and healthy["reason"] == ""


# ── BRAIN-M-6 · a research run that found nothing says why ──────────────────

def _researcher(**kw):
    from src.deep_research import DeepResearcher
    r = DeepResearcher("http://model.test", "scripted", max_rounds=2, **kw)

    async def _plan(q):
        return "plan"

    async def _cat(q):
        return ""

    r._create_plan = _plan
    r._classify_category = _cat
    return r


def test_a_run_whose_model_gave_no_queries_says_so():
    """Measured: a scripted "OK" plan gave 0 queries, the run "completed
    successfully" in 0.0 s, and the card blamed the question or the search
    engine."""
    r = _researcher()

    async def _none(*a, **k):
        return []

    r._generate_queries = _none
    asyncio.run(r.research("what is new in lisbon"))
    assert r.stopped == "no_queries"


@pytest.mark.parametrize("disabled,why", [(True, "no_search_provider"), (False, "no_results")])
def test_a_run_whose_searches_came_back_empty_says_which(disabled, why):
    r = _researcher(max_empty_rounds=1)

    async def _q(*a, **k):
        return ["lisbon news"]

    async def _empty(queries, question):
        if disabled:
            r._search_disabled = True
        return []

    r._generate_queries = _q
    r._search_and_extract = _empty
    asyncio.run(r.research("what is new in lisbon"))
    assert r.stopped == why


def test_the_stop_reason_reaches_the_card(tmp_path, monkeypatch):
    """`result-peek` carries it, from memory and from the saved file."""
    from src.research_handler import ResearchHandler
    import src.research_handler as rh

    monkeypatch.setattr(rh, "_research_json_path", lambda sid: tmp_path / f"{sid}.json")
    handler = ResearchHandler.__new__(ResearchHandler)
    handler._active_tasks = {}
    (tmp_path / "abc.json").write_text(json.dumps({"stopped": "no_queries"}), encoding="utf-8")
    assert handler.get_stopped("abc") == "no_queries"
    handler._active_tasks["live"] = {"researcher": type("R", (), {"stopped": "no_results"})()}
    assert handler.get_stopped("live") == "no_results"
    assert handler.get_stopped("nothing") == ""


# ── BRAIN-M-14 · which empty an import is ───────────────────────────────────

@pytest.fixture
def memory_client(tmp_path, monkeypatch):
    import routes.memory_routes as mr
    import src.settings as S

    replies = []

    async def fake_llm(url, model, messages, **kwargs):
        return replies.pop(0) if replies else "[]"

    monkeypatch.setattr(S, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    S._invalidate_caches()
    monkeypatch.setattr(mr, "get_current_user", lambda request: "alice", raising=False)
    monkeypatch.setattr("src.auth_helpers.require_privilege", lambda request, key: None)
    monkeypatch.setattr(mr, "resolve_task_endpoint", lambda *a, **k: ("http://llm", "m", {}))
    monkeypatch.setattr(mr, "llm_call_async", fake_llm)
    (tmp_path / "mem").mkdir()
    app = FastAPI()
    app.include_router(mr.setup_memory_routes(mr.MemoryManager(str(tmp_path / "mem")), MagicMock()))
    client = TestClient(app)
    client.replies = replies
    yield client
    S._invalidate_caches()


def test_an_empty_import_says_which_empty_it_is(memory_client):
    """Measured: "No useful information found in file." for a readable `.txt`
    whose model reply was "OK", and for an 8-byte PNG alike."""
    def post(name, data):
        return memory_client.post("/api/memory/import", files={"file": (name, data)}).json()

    memory_client.replies.append("OK")
    assert post("notes.txt", b"Rowan prefers tea to coffee.\n")["reason"] == "model_unparsed"
    memory_client.replies.append("[]")
    assert post("notes.txt", b"Rowan prefers tea to coffee.\n")["reason"] == "none_found"
    png = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4
    assert post("pic.txt", png)["reason"] == "empty"


def test_no_model_says_where_to_add_one(memory_client, monkeypatch):
    import routes.memory_routes as mr
    monkeypatch.setattr(mr, "resolve_task_endpoint", lambda *a, **k: (None, None, {}))
    res = memory_client.post("/api/memory/import", files={"file": ("n.txt", b"hello there")})
    assert res.status_code == 400
    assert res.json()["detail"] == "No model yet. Add one in Settings → Add Models."


# ── BRAIN-M-15 / BRAIN-U-14 · the report page ───────────────────────────────

def test_the_report_page_carries_pantheons_icon_and_a_way_back():
    """Measured: the page's only `<link>` was a data-URI "O" (Odysseus's), and
    nothing on it led back to Pantheon."""
    from src.visual_report import generate_visual_report

    html = generate_visual_report("What is new?", "## Findings\nSomething.", [], {})
    assert '<link rel="icon" href="/static/icon.ico">' in html
    assert "<text y='75' font-size='75'>O</text>" not in html
    assert '<a class="report-back" href="/">&larr; Pantheon</a>' in html
    assert "Generated by Pantheon Deep Research" not in html
