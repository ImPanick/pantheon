# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2098` — a skill learned from a chat publishes itself only at the floor.

The row: after an Agent-mode turn of two or more rounds or tool calls,
`services/memory/skill_extractor.py` kept a skill at or above
`MIN_CONFIDENCE = 0.6` and created it `published` whenever `auto_approve_skills`
was on (the default), while the Skills Audit publishes only at
`skill_autosave_min_confidence` (0.85 unless set) and the Brain's switches said
"Audit publishes the ones that pass". A published skill is the person's own
context in every later turn.

The owner's ruling: "Raise this to at least 0.85 … low-confidence system
generated skills get dry-runs or corrective review before published
(manually)". So the extractor keeps a skill from 0.6, publishes it only at the
floor the audit reads — never under 0.85 — and leaves everything below a
draft, which the injection never shows the model.

Driven through `maybe_extract_skill` with the model call stubbed; the store is
a real `SkillsManager` on a temporary directory.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import routes.prefs_routes as prefs_routes
import src.settings as settings
from routes.skills_routes import _audit_finalize_status
from services.memory import skill_extractor
from services.memory.skills import SkillsManager
from test_the_workshop_surfaces_js import _memory, memory_sandbox  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent


class _Session:
    session_id = "s1"

    def get_context_messages(self):
        return [
            {"role": "user", "content": "The nightly backup failed again, fix it"},
            {"role": "assistant", "content": "Rotated the credentials and re-ran it."},
        ]


def _answer(confidence):
    return json.dumps({
        "name": "rerun-the-nightly-backup",
        "description": "Rerun a failed nightly backup after rotating its credentials",
        "category": "ops",
        "when_to_use": "When the nightly backup job reports an authentication failure",
        "procedure": ["Rotate the backup credentials", "Rerun the job", "Read its log"],
        "pitfalls": ["Rerunning before the rotation reaches the agent fails again"],
        "verification": ["The log ends with a completed snapshot"],
        "tags": ["backup"],
        "confidence": confidence,
    })


@pytest.fixture
def prefs(monkeypatch):
    """The person's preferences, as `_load_for_user` answers them."""
    held = {}
    monkeypatch.setattr(prefs_routes, "_load_for_user", lambda owner: dict(held))
    monkeypatch.setattr(settings, "get_setting", lambda key, default=None: default)
    return held


async def _learn(monkeypatch, tmp_path, confidence):
    async def fake_llm_call_async(*a, **k):
        return _answer(confidence)

    monkeypatch.setattr("src.llm_core.llm_call_async", fake_llm_call_async)
    sm = SkillsManager(str(tmp_path), library_root="")
    entry = await skill_extractor.maybe_extract_skill(
        _Session(), sm, endpoint_url="http://endpoint", model="m",
        headers={}, round_count=3, tool_count=3, owner="ada")
    assert entry is not None, "the extractor dropped a skill it should have kept"
    stored = next(s for s in sm.load(owner="ada") if s["name"] == entry["name"])
    return sm, stored


@pytest.mark.parametrize("confidence", [0.6, 0.7, 0.84])
async def test_below_the_floor_a_learned_skill_is_a_draft(monkeypatch, tmp_path, prefs, confidence):
    sm, stored = await _learn(monkeypatch, tmp_path, confidence)
    assert stored["status"] == "draft", (
        f"a skill learned at {confidence} was published with no review: {stored['status']}")
    # …and a draft is not what the model is shown.
    assert stored["name"] not in {s["name"] for s in sm.injectable_skills(owner="ada")}


@pytest.mark.parametrize("confidence", [0.85, 0.95])
async def test_at_the_floor_it_publishes_while_auto_publish_is_on(monkeypatch, tmp_path, prefs, confidence):
    sm, stored = await _learn(monkeypatch, tmp_path, confidence)
    assert stored["status"] == "published"
    assert stored["name"] in {s["name"] for s in sm.injectable_skills(owner="ada")}


async def test_auto_publish_off_keeps_even_a_sure_one_a_draft(monkeypatch, tmp_path, prefs):
    prefs["auto_approve_skills"] = False
    _sm, stored = await _learn(monkeypatch, tmp_path, 0.99)
    assert stored["status"] == "draft"


async def test_a_raised_floor_raises_the_learned_bar(monkeypatch, tmp_path, prefs):
    prefs["skill_min_confidence"] = 0.95
    _sm, stored = await _learn(monkeypatch, tmp_path, 0.9)
    assert stored["status"] == "draft"


async def test_a_lowered_floor_never_takes_the_learned_bar_under_085(monkeypatch, tmp_path, prefs):
    """The slider's loose end loosens the audit (which has run the skill and had
    a judge pass it); a learned skill has had neither, so it stays at 0.85."""
    prefs["skill_min_confidence"] = 0.5
    _sm, stored = await _learn(monkeypatch, tmp_path, 0.7)
    assert stored["status"] == "draft"


async def test_a_confidence_the_model_did_not_give_is_a_draft(monkeypatch, tmp_path, prefs):
    async def fake_llm_call_async(*a, **k):
        data = json.loads(_answer(0.9))
        data.pop("confidence")
        return json.dumps(data)

    monkeypatch.setattr("src.llm_core.llm_call_async", fake_llm_call_async)
    sm = SkillsManager(str(tmp_path), library_root="")
    entry = await skill_extractor.maybe_extract_skill(
        _Session(), sm, endpoint_url="http://endpoint", model="m",
        headers={}, round_count=3, tool_count=3, owner="ada")
    stored = next(s for s in sm.load(owner="ada") if s["name"] == entry["name"])
    assert stored["status"] == "draft" and float(stored["confidence"]) == 0.7


@pytest.mark.parametrize("floor", [0.85, 0.9, 1.0])
async def test_the_audit_and_the_extractor_read_one_floor(monkeypatch, tmp_path, prefs, floor):
    """At or above 0.85 the slider is one bar for both doors: a skill at the
    floor publishes from either, a hair under it publishes from neither."""
    prefs["skill_min_confidence"] = floor
    for confidence, want in ((floor, "published"), (round(floor - 0.01, 2), "draft")):
        sub = tmp_path / f"{floor}-{confidence}"
        sm, stored = await _learn(monkeypatch, sub, confidence)
        assert stored["status"] == want, ("extractor", floor, confidence, stored["status"])
        sm.update_skill(stored["name"], {"status": "draft"}, owner="ada")
        audited = _audit_finalize_status(sm, stored["name"], "ada", "pass", confidence)
        assert audited == want, ("audit", floor, confidence, audited)


def test_the_page_says_the_learned_bar_the_server_uses(memory_sandbox):  # noqa: F811
    """`memory.js` carries the minimum to say it under the slider; the server's
    constant is the one that decides. Run the page's own function and hold the
    two to one value, at both ends of the slider."""
    from services.memory.skill_publish import LEARNED_PUBLISH_MINIMUM

    out = _memory(memory_sandbox, """
        console.log(JSON.stringify({
          min: mem.LEARNED_PUBLISH_MINIMUM,
          loose: mem.skillGateHints({ autoApprove: true, minConfidence: 0.5 }).coupling,
          strict: mem.skillGateHints({ autoApprove: true, minConfidence: 0.95 }).coupling,
          off: mem.skillGateHints({ autoApprove: false, minConfidence: 0.95 }).coupling,
        }));
    """)
    assert out["min"] == LEARNED_PUBLISH_MINIMUM
    assert "learned from a chat" in out["loose"] and "85%" in out["loose"], out["loose"]
    assert "95%" in out["strict"], out["strict"]
    assert "Imported skills are published" in out["strict"]
    assert "only published skills are used" in out["off"]


def test_the_switches_say_what_the_extractor_does():
    """The two sentences the row quoted, gone from the page that said them."""
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert "Draft skills from what you do. Audit publishes the ones that pass." not in index
    assert "Publish audited skills at or above this confidence. Off keeps them drafts." not in index
