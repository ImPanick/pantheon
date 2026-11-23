# SPDX-License-Identifier: AGPL-3.0-or-later
"""When the roster has a gap (phase 5b): a missing agent is proposed by a lead,
drafted, proven on the model it would run on, and published for every account
only once an admin approves it, versioned so an update or a rollback is one
step.

The outline (*When the roster has a gap*): "The draft can only name tools that
already exist and can't register MCP servers ... It's proven before anyone sees
it ... An admin approves, edits or rejects it ... Nothing ships without that
... Approved agents publish to a platform-wide layer every account can hire
from, versioned." Driven over a temp database and a temp data folder, with the
model calls faked: `src/apollo/gaps.py`, the platform layer of the catalogue,
the fleet's `propose_agent`, and the routes.
"""
import asyncio
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agents import catalogue as C
from src.apollo import gaps as G
from src.apollo import tasks as T
from src.apollo.errors import ApolloRefused
from tests.helpers.apollo_db import apollo_db  # noqa: F401  (fixture)
from tests.helpers.signed_in import ADMIN, MEMBER, as_person, signed_in

ADA = "ada"
SHIPPED = os.path.join(C.SHIPPED_ROOT, "policy-answerer")
with open(os.path.join(SHIPPED, "AGENT.md"), encoding="utf-8") as _fh:
    _TEMPLATE = _fh.read()
with open(os.path.join(SHIPPED, "evals.json"), encoding="utf-8") as _fh:
    EVALS = json.load(_fh)


def agent_text(agent_id="leave-answerer", name="Leave Answerer", version="1.0.0", tools="[manage_documents]"):
    text = _TEMPLATE.replace("id: policy-answerer", f"id: {agent_id}", 1)
    text = text.replace("name: Policy Answerer", f"name: {name}", 1)
    text = text.replace("version: 1.1.0", f"version: {version}", 1)
    return text.replace("tools: [manage_documents]", f"tools: {tools}", 1)


def proof_row(agent_id="leave-answerer", version="1.0.0", passed=3):
    return {"agent": agent_id, "version": version, "model": "qwen3-8b", "runs": 6,
            "cases": {"a": {"passed": passed, "of": 3}, "b": {"passed": 3, "of": 3}},
            "pass_rate": round((passed + 3) / 6, 3), "median_minutes": 1.0, "failures": {},
            "at": "2026-11-23T10:00:00Z"}


@pytest.fixture
def data(tmp_path, monkeypatch):
    import src.constants as constants
    monkeypatch.setattr(constants, "DATA_DIR", str(tmp_path))
    with C._lock:
        C._cache.clear()
    return str(tmp_path)


@pytest.fixture
def db(apollo_db, data):
    d = apollo_db()
    yield d
    d.close()


@pytest.fixture
def models(monkeypatch):
    """The model calls, faked: the endpoint, the draft, the evals, the proof."""
    said = {"text": agent_text(), "evals": EVALS, "proof": proof_row(), "drafts": 0, "proofs": []}
    import src.agents.workshop as WS
    import src.task_endpoint as TE

    async def draft(owner, description):
        said["drafts"] += 1
        said["described"] = description
        return {"ok": True, "text": said["text"], "sentence": "Drafted."}

    async def draft_evals(owner, manifest):
        return said["evals"], ("" if said["evals"] else "The evaluation set didn't pass its check: no cases.")

    async def prove(manifest, *, endpoint, model, **kw):
        said["proofs"].append((manifest.id, manifest.path, endpoint, model))
        row = dict(said["proof"]) if said["proof"] else None
        if row:
            row["agent"], row["version"] = manifest.id, manifest.version
        return row, ("" if row else "The proof run finished without a result.")

    monkeypatch.setattr(TE, "resolve_task_endpoint", lambda **kw: ("http://models.local/v1", "qwen3-8b", {}))
    monkeypatch.setattr(WS, "draft", draft)
    monkeypatch.setattr(G, "draft_evals", draft_evals)
    monkeypatch.setattr(G, "prove", prove)
    return said


def _goal(db, owner=ADA):
    t = T.create(db, owner, title="Answer the leave questions", brief="From the handbook", kind="hr",
                 lead_agent="policy-answerer")
    db.flush()
    return t


def _proposed(db, owner=ADA, need="Answer leave questions from the staff handbook"):
    row, made = G.propose(db, owner, need=need, why="Nothing in the roster reads a handbook for leave.",
                          task=_goal(db, owner), from_agent="lead")
    db.commit()
    return row


def _built(db, models, **kw):
    row = _proposed(db, **kw)
    state = asyncio.run(G.build(row.id))
    db.expire_all()
    return G.get(db, row.id), state


# ── a gap, proposed ────────────────────────────────────────────────────────

def test_a_gap_is_proposed_once_logged_on_the_goal_and_capped_per_person(db):
    from src.apollo import fleet as F
    row = _proposed(db)
    assert (row.state, row.owner, row.from_agent) == ("drafting", ADA, "lead")
    again, made = G.propose(db, ADA, need=row.need.upper(), why="Still missing.")
    assert made is False and again.id == row.id
    (msg,) = F.messages(db, ADA, row.task_id)
    assert msg["kind"] == "gap" and msg["body"].startswith("Answer leave questions")
    for n in range(G.OPEN_MAX - 1):
        G.propose(db, ADA, need=f"Job {n}", why="None fits.")
    with pytest.raises(ApolloRefused) as e:
        G.propose(db, ADA, need="One more job", why="None fits.")
    assert e.value.status == 409 and "already being made" in e.value.sentence
    G.propose(db, "bob", need="One more job", why="None fits.")     # another person's cap is their own


@pytest.mark.parametrize("need, why, words", [
    ("", "None fits.", "Say what the missing agent would do."),
    ("Answer leave questions", "  ", "Say why no agent in the roster fits it."),
])
def test_a_proposal_says_what_and_why(db, need, why, words):
    with pytest.raises(ApolloRefused) as e:
        G.propose(db, ADA, need=need, why=why)
    assert e.value.sentence == words


def test_the_pane_names_a_gap_in_the_goals_log():
    import subprocess
    js = ("import('./static/js/apolloPaneModel.js').then((M) => console.log(M.teamLine("
          "{kind: 'gap', from: 'lead', to: null, body: 'Answer leave questions\\n\\nWhy: none'}, {lead: 'Lead'})))")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run(["node", "-e", js], cwd=root, capture_output=True, text=True, timeout=30)
    if out.returncode and "not found" in out.stderr:
        pytest.skip("node binary not on PATH")
    assert out.stdout.strip() == "Lead found no agent for: Answer leave questions"


# ── what a draft may name ──────────────────────────────────────────────────

@pytest.mark.parametrize("tools, words", [
    ("[github__create_issue]", "is not a tool Pantheon has"),
    ("[not_a_tool]", "is not a tool Pantheon has"),
    ("[manage_documents, fleet]", "“fleet” isn't one of Pantheon's own tools"),
])
def test_a_draft_names_only_pantheons_own_tools(tools, words):
    from src.agents.manifest import ManifestRefused
    with pytest.raises(ManifestRefused) as e:
        G.check_platform(agent_text(tools=tools))
    assert words in e.value.sentence


def test_a_new_agent_never_takes_a_shipped_or_published_id(data):
    text, new = G.unique_id(agent_text("policy-answerer"), "policy-answerer")
    assert new == "policy-answerer-2" and "id: policy-answerer-2" in text
    live = os.path.join(C.platform_root(), "policy-answerer-2")
    os.makedirs(live)
    with open(os.path.join(live, "AGENT.md"), "w", encoding="utf-8") as fh:
        fh.write(agent_text("policy-answerer-2"))
    assert G.unique_id(agent_text("policy-answerer"), "policy-answerer")[1] == "policy-answerer-3"
    assert G.unique_id(agent_text(), "leave-answerer")[1] == "leave-answerer"


# ── drafted and proven ─────────────────────────────────────────────────────

def test_a_proposal_is_drafted_staged_and_proven_then_waits_on_an_admin(db, models, data):
    row, state = _built(db, models)
    assert state == "waiting" and row.state == "waiting"
    assert (row.agent_id, row.agent_name, row.version, row.model) == ("leave-answerer", "Leave Answerer",
                                                                      "1.0.0", "qwen3-8b")
    assert row.badge == "runs-well" and "Runs well. Waiting on an admin." in row.sentence
    assert "Answer leave questions from the staff handbook" in models["described"]
    ((pid, path, endpoint, model),) = models["proofs"]
    assert path == os.path.join(data, "agent_platform", "proposals", row.id, "leave-answerer", "AGENT.md")
    assert json.load(open(os.path.join(os.path.dirname(path), "evals.json"))) == EVALS
    assert (endpoint, model) == ("http://models.local/v1", "qwen3-8b")
    # Proven isn't published: nobody can hire it yet.
    assert C.get_agent("bob", "leave-answerer") is None
    full = G.to_dict(row, full=True)
    assert full["asks_for"]["tools"] == ["manage_documents"]
    assert full["asks_for"]["effects"]["destructive"] == "never"


def test_a_weak_proof_still_waits_but_says_so(db, models):
    models["proof"] = proof_row(passed=1)
    row, _ = _built(db, models)
    assert row.state == "waiting" and row.badge == "needs-bigger"
    assert "Needs a bigger model" in row.sentence


@pytest.mark.parametrize("change, words", [
    (dict(text=agent_text(tools="[github__create_issue]")), "is not a tool Pantheon has"),
    (dict(text=agent_text(tools="[manage_documents, fleet]")), "isn't one of Pantheon's own tools"),
    (dict(evals=None), "The evaluation set didn't pass its check"),
    (dict(proof=None), "The proof run finished without a result."),
])
def test_a_draft_that_cant_be_made_is_failed_with_the_reason(db, models, change, words):
    models.update(change)
    row, state = _built(db, models)
    assert state == "failed" and words in row.sentence


def test_with_no_model_for_scheduled_work_nothing_is_drafted(db, models, monkeypatch):
    import src.task_endpoint as TE
    monkeypatch.setattr(TE, "resolve_task_endpoint", lambda **kw: (None, None, {}))
    row, state = _built(db, models)
    assert state == "failed" and row.sentence == G.NO_MODEL and models["drafts"] == 0


def test_a_failed_one_can_be_tried_again_by_its_person_only(db, models):
    models["proof"] = None
    row, _ = _built(db, models)
    with pytest.raises(ApolloRefused) as e:
        G.retry(db, "bob", row.id)
    assert e.value.status == 404
    again = G.retry(db, ADA, row.id)
    assert again.state == "drafting" and again.text is None and again.agent_id is None
    with pytest.raises(ApolloRefused):
        G.retry(db, ADA, row.id)


def test_draft_evals_asks_again_when_the_set_fails_its_check(monkeypatch):
    import src.workflow_assist as WA
    from src.agents.manifest import parse_manifest
    asked = []

    async def ask_for_json(owner, messages, *, max_tokens):
        asked.append(messages)
        return ({"cases": []} if len(asked) == 1 else EVALS), None
    monkeypatch.setattr(WA, "ask_for_json", ask_for_json)
    got, why = asyncio.run(G.draft_evals(ADA, parse_manifest(agent_text(), source="platform")))
    assert got == EVALS and why == "" and len(asked) == 2
    assert "doesn't pass its check" in asked[1][-1]["content"]


def test_a_proof_runs_in_its_own_process_on_the_staged_file(tmp_path, monkeypatch):
    from src.agents.manifest import parse_manifest
    path = tmp_path / "leave-answerer" / "AGENT.md"
    path.parent.mkdir()
    path.write_text(agent_text())
    m = parse_manifest(agent_text(), source="platform", path=str(path))
    ran = []

    class Proc:
        async def communicate(self):
            return b"", b""

    async def create(*cmd, **kw):
        ran.append(cmd)
        out = cmd[cmd.index("--out") + 1]
        with open(out, "w") as fh:
            fh.write(json.dumps(proof_row()) + "\n")
        return Proc()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    row, why = asyncio.run(G.prove(m, endpoint="http://models.local/v1", model="qwen3-8b"))
    assert row == proof_row() and why == ""
    (cmd,) = ran
    assert cmd[1:5] == ("-m", "src.agents.evals", "leave-answerer", "--file")
    assert cmd[5] == str(path) and cmd[cmd.index("--runs") + 1] == str(G.PROOF_RUNS)


def test_the_proof_runner_takes_a_file_and_refuses_a_broken_one(tmp_path, capsys):
    from src.agents.evals import main
    bad = tmp_path / "AGENT.md"
    bad.write_text("not an agent")
    assert main(["x", "--file", str(bad)]) == 2
    assert "could not be proven" in capsys.readouterr().out


# ── an admin's decision ────────────────────────────────────────────────────

def test_an_approved_agent_is_published_for_everyone_with_its_proof(db, models, data):
    from src.agents import fit
    row, _ = _built(db, models)
    out = G.approve(db, ADMIN, row.id)
    db.commit()
    assert out["state"] == "published" and out["review_note"] is None
    live = os.path.join(data, "agent_platform", "live", "leave-answerer")
    assert os.path.isfile(os.path.join(live, "AGENT.md"))
    assert os.path.isfile(os.path.join(data, "agent_platform", "versions", "leave-answerer", "1.0.0", "AGENT.md"))
    assert not os.path.exists(os.path.join(live, "proof.jsonl"))
    meta = json.load(open(os.path.join(live, "published.json")))
    assert (meta["approved_by"], meta["badge"], meta["proposal"]) == (ADMIN, "runs-well", row.id)
    for who in ("bob", "carol"):
        m = C.get_agent(who, "leave-answerer")
        assert m.source == "platform"
        agents, broken = C.catalogue(who)
        assert "leave-answerer" in [a.id for a in agents] and broken == []
    assert fit.fit(C.get_agent("bob", "leave-answerer"), "qwen3-8b")["badge"] == "runs-well"
    with pytest.raises(ApolloRefused):
        G.approve(db, ADMIN, row.id)


def test_a_shipped_agent_is_never_replaced_and_a_persons_own_still_wins(db, models, data):
    row, _ = _built(db, models)
    G.approve(db, ADMIN, row.id)
    # A platform folder can't shadow a shipped id, however it got there.
    sneaky = os.path.join(C.platform_root(), "policy-answerer")
    os.makedirs(sneaky)
    with open(os.path.join(sneaky, "AGENT.md"), "w", encoding="utf-8") as fh:
        fh.write(agent_text("policy-answerer", name="Not The Real One"))
    agents, _ = C.catalogue("bob")
    assert next(a for a in agents if a.id == "policy-answerer").source == "shipped"
    assert C.get_agent("bob", "policy-answerer").source == "shipped"
    own = os.path.join(C.own_root("bob"), "leave-answerer")
    os.makedirs(own)
    with open(os.path.join(own, "AGENT.md"), "w", encoding="utf-8") as fh:
        fh.write(agent_text(name="Bobs Copy"))
    assert C.get_agent("bob", "leave-answerer").source == "own"
    assert C.get_agent("carol", "leave-answerer").source == "platform"


def test_an_approval_refuses_a_shipped_id(db, models):
    row, _ = _built(db, models)
    row.text = agent_text("policy-answerer")
    with pytest.raises(ApolloRefused) as e:
        G.approve(db, ADMIN, row.id)
    assert "shipped agent's id" in e.value.sentence


def test_reject_closes_it_with_the_admins_note(db, models):
    row, _ = _built(db, models)
    out = G.reject(db, ADMIN, row.id, "We use the HR portal for this.")
    assert out["state"] == "rejected" and out["review_note"] == "We use the HR portal for this."
    with pytest.raises(ApolloRefused):
        G.reject(db, ADMIN, row.id)
    assert C.get_agent("bob", "leave-answerer") is None


def test_an_edit_keeps_the_id_and_is_proven_again_before_approval(db, models):
    row, _ = _built(db, models)
    with pytest.raises(ApolloRefused) as e:
        G.edit(db, ADMIN, row.id, agent_text("other-id"))
    assert "keeps the agent's id, leave-answerer" in e.value.sentence
    with pytest.raises(ApolloRefused) as bad:
        G.edit(db, ADMIN, row.id, agent_text(tools="[manage_documents, fleet]"))
    assert "doesn't pass its check" in bad.value.sentence
    edited = agent_text(name="Leave Questions")
    assert G.edit(db, ADMIN, row.id, edited)["state"] == "proving"
    db.commit()
    with pytest.raises(ApolloRefused):
        G.approve(db, ADMIN, row.id)        # not until it's proven again
    assert asyncio.run(G.build(row.id, text=edited)) == "waiting"
    db.expire_all()
    assert G.get(db, row.id).agent_name == "Leave Questions" and models["drafts"] == 1
    assert G.approve(db, ADMIN, row.id)["state"] == "published"
    assert C.get_agent("bob", "leave-answerer").name == "Leave Questions"


def test_a_new_version_is_proven_approved_and_rolled_back_in_one_step(db, models):
    row, _ = _built(db, models)
    G.approve(db, ADMIN, row.id)
    with pytest.raises(ApolloRefused) as same:
        G.propose_update(db, ADMIN, "leave-answerer", agent_text())
    assert "Version 1.0.0 is already published" in same.value.sentence
    with pytest.raises(ApolloRefused) as shipped:
        G.propose_update(db, ADMIN, "policy-answerer", agent_text("policy-answerer", version="9.0.0"))
    assert shipped.value.status == 404
    models["proof"] = None
    broken = G.propose_update(db, ADMIN, "leave-answerer", agent_text(version="1.0.5"))
    db.commit()
    assert asyncio.run(G.build(broken.id, text=agent_text(version="1.0.5"))) == "failed"
    db.expire_all()
    with pytest.raises(ApolloRefused) as no_retry:
        G.retry(db, ADMIN, broken.id)
    assert "sending the new version again" in no_retry.value.sentence
    models["proof"] = proof_row()
    v2 = agent_text(name="Leave Answerer Two", version="1.1.0")
    up = G.propose_update(db, ADMIN, "leave-answerer", v2)
    db.commit()
    assert asyncio.run(G.build(up.id, text=v2)) == "waiting"
    db.expire_all()
    G.approve(db, ADMIN, up.id)
    assert C.get_agent("bob", "leave-answerer").version == "1.1.0"
    (agent,) = G.published()
    assert agent["live"] == "1.1.0" and [v["version"] for v in agent["versions"]] == ["1.0.0", "1.1.0"]
    back = G.rollback("leave-answerer", "1.0.0")
    assert back["live"] == "1.0.0" and C.get_agent("bob", "leave-answerer").version == "1.0.0"
    for agent_id, version in (("leave-answerer", "3.0.0"), ("../x", "1.0.0"), ("leave-answerer", "../1")):
        with pytest.raises(ApolloRefused) as e:
            G.rollback(agent_id, version)
        assert e.value.status == 404


# ── the fleet proposes ─────────────────────────────────────────────────────

def test_a_lead_proposes_through_the_fleet_and_the_build_starts(db, monkeypatch):
    from src.apollo import fleet_tool as FT
    goal = _goal(db)
    result, runs = FT._do(db, ADA, goal, "lead", {"action": "propose_agent",
                                                  "need": "Answer leave questions", "why": "None fits."})
    assert runs == [] and result["build"] and "Proposed." in result["output"]
    assert G.get(db, result["build"], owner=ADA).from_agent == "policy-answerer"
    again, _ = FT._do(db, ADA, goal, "lead", {"action": "propose_agent",
                                              "need": "answer leave questions", "why": "Still none."})
    assert "already being made (Drafting it)" in again["output"] and "build" not in again
    started = []
    monkeypatch.setattr(FT, "run_sync", lambda *a: ({"output": "Proposed.", "build": "p1", "exit_code": 0}, []))
    monkeypatch.setattr(G, "start_build", lambda pid, **kw: started.append(pid))
    out = asyncio.run(FT.fleet('{"action": "propose_agent"}', {"owner": ADA, "session_id": "s"}))
    assert started == ["p1"] and "build" not in out


def test_the_fleet_tool_offers_propose_agent_as_a_write():
    from src.tool_capabilities import _PRIVATE_ACTION_WRITES as WRITE_ACTIONS_BY_TOOL
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    (schema,) = [s for s in FUNCTION_TOOL_SCHEMAS if (s.get("function") or {}).get("name") == "fleet"]
    props = schema["function"]["parameters"]["properties"]
    assert "propose_agent" in props["action"]["enum"] and "why" in props
    assert "propose_agent" in WRITE_ACTIONS_BY_TOOL["fleet"]


# ── the routes ─────────────────────────────────────────────────────────────

@pytest.fixture
def client_as(apollo_db, data, tmp_path, monkeypatch):
    manager = signed_in(monkeypatch, tmp_path / "auth")
    import routes.apollo_routes as apollo_routes

    def client(who):
        app = as_person(FastAPI(), who, auth_manager=manager)
        app.include_router(apollo_routes.setup_apollo_routes())
        return TestClient(app)
    return client


def test_a_person_sees_their_own_proposals_and_only_an_admin_reviews(client_as, apollo_db, models, monkeypatch):
    builds = []
    monkeypatch.setattr(G, "start_build", lambda pid, **kw: builds.append((pid, kw)))
    db = apollo_db()
    row = _proposed(db, owner=MEMBER)
    pid = row.id
    asyncio.run(G.build(pid))
    db.close()
    admin, member = client_as(ADMIN), client_as(MEMBER)
    (mine,) = member.get("/api/apollo/agents/proposals").json()["proposals"]
    assert mine["state"] == "waiting" and mine["badge"] == "runs-well" and "text" not in mine
    assert admin.get("/api/apollo/agents/proposals").json()["proposals"] == []
    for method, path, body in (("get", "/api/apollo/agents/review", None),
                               ("post", f"/api/apollo/agents/review/{pid}/approve", {}),
                               ("post", f"/api/apollo/agents/review/{pid}/edit", {"text": agent_text()}),
                               ("post", f"/api/apollo/agents/review/{pid}/reject", {}),
                               ("post", "/api/apollo/agents/platform/leave-answerer/update", {"text": agent_text()}),
                               ("post", "/api/apollo/agents/platform/leave-answerer/rollback", {"version": "1.0.0"})):
        got = getattr(member, method)(path, **({"json": body} if body is not None else {}))
        assert got.status_code == 403, path
    review = admin.get("/api/apollo/agents/review").json()
    (waiting,) = review["waiting"]
    assert waiting["owner"] == MEMBER and waiting["asks_for"]["tools"] == ["manage_documents"]
    assert waiting["proof"]["runs"] == 6 and review["published"] == []
    assert admin.post(f"/api/apollo/agents/review/{pid}/approve").json()["state"] == "published"
    assert member.get("/api/apollo/agents/proposals").json()["proposals"][0]["state_words"] == "Ready to hire"
    assert admin.get("/api/apollo/agents/review").json()["published"][0]["live"] == "1.0.0"
    up = admin.post("/api/apollo/agents/platform/leave-answerer/update",
                    json={"text": agent_text(version="1.1.0")}).json()
    assert up["state"] == "proving" and builds == [(up["id"], {"text": agent_text(version="1.1.0")})]
    assert admin.post("/api/apollo/agents/platform/leave-answerer/rollback",
                      json={"version": "2.0.0"}).status_code == 404


def test_retry_is_the_persons_own_and_starts_a_build(client_as, apollo_db, models, monkeypatch):
    builds = []
    monkeypatch.setattr(G, "start_build", lambda pid, **kw: builds.append(pid))
    models["proof"] = None
    db = apollo_db()
    pid = _proposed(db, owner=MEMBER).id
    asyncio.run(G.build(pid))
    db.close()
    assert client_as(ADMIN).post(f"/api/apollo/agents/proposals/{pid}/retry").status_code == 404
    out = client_as(MEMBER).post(f"/api/apollo/agents/proposals/{pid}/retry").json()
    assert out["state"] == "drafting" and builds == [pid]
