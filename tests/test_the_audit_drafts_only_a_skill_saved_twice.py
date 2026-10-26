# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B790` — identity demotes; topic only flags.

The nightly audit drafted a skill on `DUPLICATE_SIMILARITY` (0.38), a score whose
measured precision on the shipped library is 0 of 24 — every pair reaching it is
the same procedure for a different technology (`django-security |
laravel-security`). On a default install (`get_current_user` is None with sign-in
off) `load(owner=None)` holds every bundled skill, so a person's own skill about
their framework was measured against a shipped one and drafted overnight, at 35%,
with a necessity record that named the keeper and not the reason.

Now the audit drafts a skill only when it is the same skill twice — the shared
base name a save appends `-<n>` to, or a score at `DUPLICATE_REFUSAL` — and the
record says which copy was kept and why. A topic overlap is the lint's advisory
and the card's grouping, and changes nothing on disk.

Driven through the real `run_scheduled_skill_audit` / `_audit_one_skill` on a
real store, with only the model scripted.
"""
from __future__ import annotations

import asyncio
import json
import textwrap

import pytest

import routes.skills_routes as skills_routes
from services.memory.skill_lint import DUPLICATE_REFUSAL, DUPLICATE_SIMILARITY, skill_similarity
from services.memory.skills import SkillsManager

PASS = {"verdict": "pass", "confidence": 0.9, "summary": "It worked.", "issues": []}

DJANGO = dict(
    name="django-security",
    description="Harden a Django web application against common security attacks",
    when_to_use="auditing the security settings of a Django project before it ships",
    procedure=["Set SECURE_SSL_REDIRECT and SESSION_COOKIE_SECURE in settings.py",
               "Keep CsrfViewMiddleware enabled",
               "Run manage.py check --deploy and fix every warning",
               "Confirm the web server sends HSTS and a strict Content-Security-Policy header"],
    tags=["django", "security"], category="security",
)
LARAVEL_MD = textwrap.dedent("""\
    ---
    name: laravel-security
    description: Harden a Laravel web application against common security attacks
    category: security
    tags: [laravel, security]
    status: published
    confidence: 0.9
    ---

    ## When to Use
    auditing the security settings of a Laravel project before it ships

    ## Procedure
    1. Force HTTPS in AppServiceProvider and set secure session cookies in config/session.php
    2. Keep the VerifyCsrfToken middleware on every web route
    3. Run php artisan config:cache and review .env for APP_DEBUG=false
    4. Confirm the web server sends HSTS and a strict Content-Security-Policy header
    """)


class Model:
    def __init__(self, necessity_ok=True):
        self.necessity_ok = necessity_ok

    async def __call__(self, url, model, messages, **kw):
        system = messages[0]["content"]
        if system.startswith("You assess whether a reusable AI 'skill'"):
            if not self.necessity_ok:
                return "not json at all"
            return json.dumps({"necessary": True, "redundant_with": [],
                               "reason": "A specific procedure worth keeping."})
        if system.startswith("You are auditing retrieval metadata"):
            return json.dumps({"ok": True, "summary": "Narrow enough.", "issues": []})
        if system.startswith("You are a strict QA reviewer"):
            return json.dumps(PASS)
        raise AssertionError(f"unscripted model call: {system[:80]!r}")


async def _loop(url, model, messages, **kw):
    yield "data: " + json.dumps({"delta": "Ran it on a sample project."}) + "\n\n"
    yield "data: [DONE]\n\n"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    lib = tmp_path / "library"
    (lib / "laravel-security").mkdir(parents=True)
    (lib / "laravel-security" / "SKILL.md").write_text(LARAVEL_MD, encoding="utf-8")
    sm = SkillsManager(str(tmp_path / "data"), library_root=str(lib))
    monkeypatch.setattr(skills_routes, "_skill_audit_jobs", {})
    monkeypatch.setattr(skills_routes, "_audit_auto_publish_policy", lambda owner: (True, 0.85))
    monkeypatch.setattr(skills_routes, "_resolve_audit_models",
                        lambda owner=None: ("http://model.test", "scripted", {}, None))
    monkeypatch.setattr("src.agent_loop.stream_agent_loop", _loop)

    def model(**kw):
        monkeypatch.setattr("src.llm_core.llm_call_async", Model(**kw))
    model()
    return sm, model


def _live(sm, name, owner=None):
    return next(s for s in sm.load(owner=owner) if s["name"] == name)


def test_the_fixture_is_a_topic_pair_not_a_copy(world):
    sm, _ = world
    sm.add_skill(**DJANGO, status="published", confidence=0.85, source="user")
    score = skill_similarity(_live(sm, "django-security"), _live(sm, "laravel-security"))
    assert DUPLICATE_SIMILARITY <= score < DUPLICATE_REFUSAL, score


def test_a_skill_about_your_own_framework_is_still_published_in_the_morning(world):
    """The row's `Verify:`, first half. Default install, owner None, so the
    blocker sees the shipped `laravel-security` — which, published at 90%, out-
    ranks the person's skill at 85% and drafted it on the old rule."""
    sm, _ = world
    sm.add_skill(**DJANGO, status="published", confidence=0.85, source="user")

    out = asyncio.run(skills_routes.run_scheduled_skill_audit(sm, owner=None, max_skills=8))
    mine = next(r for r in out["results"] if r["skill"] == "django-security")
    assert mine["result"] == "pass", mine
    live = _live(sm, "django-security")
    assert live["status"] == "published"
    assert live["confidence"] == 0.95
    assert (live.get("necessity") or {}).get("necessary") is not False


def test_the_same_skill_saved_twice_is_drafted_and_says_which_was_kept_and_why(world):
    """The second half: two names, one skill. The copy is drafted, the record
    names the keeper and the deciding fact, and the keeper is left alone."""
    sm, _ = world
    body = dict(description="Rotate and prune application log files on a server",
                when_to_use="the log files on a server have filled the disk",
                procedure=["stop the writer", "rotate", "prune older than 7 days"],
                tags=["logs"], category="ops", status="published", confidence=0.9,
                source="user")
    sm.add_skill(name="rotate-logs", **body)
    sm.add_skill(name="rotate-logs", **body)            # saved again: `rotate-logs-2`
    for _ in range(3):
        sm.record_use("rotate-logs")

    copy = _live(sm, "rotate-logs-2")
    res = asyncio.run(skills_routes._audit_one_skill(
        sm, copy, "http://model.test", "scripted", {}, None, None, lambda m: None))
    assert res["result"] == "skipped" and res["status"] == "draft", res
    reason = _live(sm, "rotate-logs-2")["necessity"]["reason"]
    assert "rotate-logs" in reason
    assert "used 3 times" in reason, reason
    assert "the number a save adds" in reason, reason
    assert _live(sm, "rotate-logs-2")["status"] == "draft"
    assert _live(sm, "rotate-logs")["status"] == "published"


def test_a_verdict_the_old_rule_wrote_does_not_keep_drafting_the_skill(world):
    """An install upgraded from the 0.38 rule carries its records. With the
    necessity judge unable to answer, nothing else would ever replace one."""
    sm, model = world
    model(necessity_ok=False)
    sm.add_skill(**DJANGO, status="draft", confidence=0.35, source="user")
    sm.set_necessity("django-security", False, ["laravel-security"],
                     "Lower-priority duplicate of laravel-security")

    res = asyncio.run(skills_routes._audit_one_skill(
        sm, _live(sm, "django-security"), "http://model.test", "scripted", {}, None,
        None, lambda m: None))
    assert res["result"] == "pass", res
    assert _live(sm, "django-security")["status"] == "published"
