# SPDX-License-Identifier: AGPL-3.0-or-later
"""Owner-scope tests for the remaining _resolve_model call sites.

Both the teacher-escalation path and the skill-audit teacher resolution map a
model spec to an endpoint (and its decrypted api_key). Like /presets/expand,
that lookup must be scoped to the calling user, otherwise it can resolve another
owner's ModelEndpoint in a multi-user deployment. See #2283.
"""

import asyncio

import src.teacher_escalation as teacher_escalation
import routes.skills_routes as skills_routes


def test_call_teacher_scopes_model_resolution_to_owner(monkeypatch):
    seen = {}

    def fake_resolve_model(spec, owner=None):
        seen["spec"] = spec
        seen["owner"] = owner
        return ("http://endpoint.local/v1", "teacher-model", {})

    async def fake_llm_call_async(url, model, messages, **kwargs):
        seen["messages"] = messages
        return "teacher reply"

    from src.agent_tools import model_interaction_tools

    monkeypatch.setattr("src.ai_interaction._resolve_model", fake_resolve_model)
    monkeypatch.setattr(
        model_interaction_tools,
        "_TEACHER_SYSTEM_PROMPT",
        "sys",
    )
    monkeypatch.setattr("src.llm_core.llm_call_async", fake_llm_call_async)

    result = asyncio.run(
        teacher_escalation._call_teacher("teacher-model", "prompt", owner="alice")
    )

    assert result == "teacher reply"
    assert seen["owner"] == "alice"
    assert seen["spec"] == "teacher-model"
    assert seen["messages"][0] == {"role": "system", "content": "sys"}


def test_audit_teacher_resolution_scoped_to_owner(monkeypatch):
    seen = {}

    def fake_resolve_endpoint(role, owner=None):
        return ("http://worker.local/v1", "worker-model", {})

    def fake_get_setting(key, default=None):
        return {"teacher_enabled": True, "teacher_model": "teacher-model"}.get(key, default)

    def fake_resolve_model(spec, owner=None):
        seen["spec"] = spec
        seen["owner"] = owner
        return ("http://endpoint.local/v1", "teacher-model", {})

    monkeypatch.setattr("src.endpoint_resolver.resolve_endpoint", fake_resolve_endpoint)
    monkeypatch.setattr("src.settings.get_setting", fake_get_setting)
    monkeypatch.setattr("src.ai_interaction._resolve_model", fake_resolve_model)
    # list_model_ids is best-effort; force it to no-op so the worker model passes through.
    monkeypatch.setattr("src.llm_core.list_model_ids", lambda url, headers=None: [])

    url, model, headers, teacher = skills_routes._resolve_audit_models(owner="alice")

    assert (url, model) == ("http://worker.local/v1", "worker-model")
    assert teacher == ("http://endpoint.local/v1", "teacher-model", {})
    assert seen["owner"] == "alice"
    assert seen["spec"] == "teacher-model"


def test_the_skills_audit_task_resolves_its_model_for_the_person_it_runs_for(monkeypatch):
    """`B1942`. The Skills Audit task (`action_audit_skills`, the default task
    that fires after every five skills a person adds) refused to run without an
    owner and audited that owner's skills, but asked `_resolve_audit_models`
    for the model with no owner at all. With no owner, `resolve_endpoint`
    skips `owner_filter`, so the run could use another person's private
    endpoint and its API key, and the person's own Utility or Default model
    was never read. Every other caller passes the owner.

    Adapted from upstream Odysseus 84aa9a91
    (`test_task_audit_resolves_the_owners_model_settings`), without its
    background-workload check, which Pantheon does not have.
    """
    from services.memory import skills as skills_module
    from src import builtin_actions, llm_core

    class FakeSkills:
        def load(self, owner=None):
            return [{"name": "release-checklist", "audit_verdict": None}]

    seen = {}

    def fake_resolve_audit_models(owner=None):
        seen["owner"] = owner
        return "http://example.test", "audit-model", None, None

    async def fake_run_audit_all_job(key, skills_manager, names, url, model, headers, teacher, owner):
        job = skills_routes._skill_audit_jobs[key]
        job["done"] = 1
        job["results"] = [{"skill": names[0], "result": "pass"}]

    monkeypatch.setattr(skills_module, "SkillsManager", lambda data_dir: FakeSkills())
    monkeypatch.setattr(skills_routes, "_resolve_audit_models", fake_resolve_audit_models)
    monkeypatch.setattr(skills_routes, "_run_audit_all_job", fake_run_audit_all_job)
    monkeypatch.setattr(llm_core, "seconds_since_model_activity", lambda *a: None)

    try:
        text, ok = asyncio.run(builtin_actions.action_audit_skills("alice"))
    finally:
        skills_routes._skill_audit_jobs.pop(("alice",), None)

    assert ok is True, text
    assert "Audited 1/1" in text
    assert seen["owner"] == "alice"
