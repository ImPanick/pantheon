# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B584` — the one confidence setting says both things it sets, at every position.

The row: `skill_min_confidence` is two policies. The injection path reads it as
a floor (`agent_loop`, `0` disables the gate) and the audit reads the same value
as the bar it publishes at (`routes/skills_routes._audit_auto_publish_policy`,
`0` publishes every pass), so the slider's loosest position is simultaneously
the loosest injection policy and the loosest publication policy. Its `Verify:`
— *"either the two policies have two settings, or the one setting says both
things where a person sets it"* — takes the second branch (the split is the
owner's call).

Measured on `ffaf6671`: with auto-publish on, the sentence under the slider
(`skillGateHints`) named only the injection reading at every position; with it
off, it said the number *"still decides what Audit publishes"* — false, because
`_audit_finalize_status` publishes nothing at any confidence while auto-publish
is off. Both readings are driven below against the server's own functions, so
the sentence is checked against what the product does, not against itself.

`Verify:` a reader cannot come away believing they have tightened one when they
loosened the other.
"""
from __future__ import annotations

import pytest

import routes.prefs_routes as prefs_routes
from routes.skills_routes import _audit_finalize_status
from services.memory.skills import SkillsManager
from test_the_workshop_surfaces_js import _memory, memory_sandbox  # noqa: F401

POSITIONS = [0, 0.5, 0.85, 1.0]


def _hints(sandbox):
    return _memory(sandbox, """
        const on = %s.map((v) => mem.skillGateHints({ autoApprove: true, minConfidence: v }).confidence);
        const off = [0, 0.85].map((v) => mem.skillGateHints({ autoApprove: false, minConfidence: v }).confidence);
        console.log(JSON.stringify({ on, off }));
    """ % POSITIONS)


def test_every_on_position_names_both_readings(memory_sandbox):  # noqa: F811
    out = _hints(memory_sandbox)
    for value, sentence in zip(POSITIONS, out["on"]):
        assert "teacher writes" in sentence and "used" in sentence, (value, sentence)
        assert "Audit publishes" in sentence, f"{value}: the publication reading is missing — {sentence}"
        if value:
            pct = f"{round(value * 100)}%"
            assert sentence.count(pct) == 2, f"{value}: one number, said for both — {sentence}"


def test_the_loose_end_says_it_is_loose_for_both(memory_sandbox):  # noqa: F811
    loose = _hints(memory_sandbox)["on"][0]
    assert "No minimum" in loose and "loosest" in loose
    assert "every draft that passes" in loose
    assert "both" in loose


def test_off_says_the_number_decides_nothing(memory_sandbox):  # noqa: F811
    out = _hints(memory_sandbox)
    for sentence in out["off"]:
        assert "Decides nothing" in sentence and "Audit publishes no draft" in sentence, sentence
        assert "still decides" not in sentence


# ── what the sentences claim, driven against the server ─────────────────────

@pytest.fixture
def store(tmp_path):
    sm = SkillsManager(str(tmp_path), library_root="")
    sm.add_skill(name="rotate-logs", description="rotate the logs", when_to_use="logs fill the disk",
                 procedure=["rotate them"], owner="alice", source="user")
    return sm


def _publishes(store, monkeypatch, *, auto, floor, confidence):
    monkeypatch.setattr(prefs_routes, "_load_for_user",
                        lambda owner: {"auto_approve_skills": auto, "skill_min_confidence": floor})
    return _audit_finalize_status(store, "rotate-logs", "alice", "pass", confidence) == "published"


def test_the_audit_reads_the_same_number_the_sentence_says_it_does(store, monkeypatch):
    # On: the slider is the publication bar.
    assert _publishes(store, monkeypatch, auto=True, floor=0.85, confidence=0.9) is True
    assert _publishes(store, monkeypatch, auto=True, floor=0.85, confidence=0.6) is False
    # The loose end publishes every pass — the half the old sentence left out.
    assert _publishes(store, monkeypatch, auto=True, floor=0.0, confidence=0.05) is True
    # Off: nothing is published at any confidence — what the old sentence denied.
    assert _publishes(store, monkeypatch, auto=False, floor=0.0, confidence=1.0) is False
