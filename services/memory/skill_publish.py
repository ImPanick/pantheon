# SPDX-License-Identifier: AGPL-3.0-or-later
"""Who publishes a skill, and at what bar — `B2098`.

A published skill rides in the person's later turns as their own context
(`D-2026-10-09-01` §1), so *published* is the state that matters, and this
module is the one place that says how a skill reaches it. The owner's ruling,
by origin:

* **Imported** — from the library, a GitHub/skills.sh link or install line, or
  a skill file (`SkillsManager.install_package`, `import_bundle_from_files`,
  `adopt_library_skill`): published when it lands, because a person chose it.
  An import the agent's own loopback starts is not a person choosing it, so it
  lands a draft (`routes/skills_routes.py`, `request_is_a_person`).
* **Learned from a chat** (`skill_extractor`, `source="learned"`): published at
  once only at or above `learned_publish_floor` with auto-publish on; below it,
  a draft, which the Skills Audit (a dry run and a judge) publishes at the
  person's floor, or the person publishes by hand.
* **Custom-built** — written by a person in the editor, or by the agent through
  `manage_skills add`: a draft until a person publishes it. The agent cannot:
  `manage_skills publish` refuses, its `add` never writes `published`, and its
  edits keep the stored lifecycle (`LIFECYCLE_FIELDS`).

One floor, one setting (`Law 14`): `publish_policy` is what the audit, the
extractor and the slider read. The extractor alone adds `LEARNED_PUBLISH_MINIMUM`
beneath it, because it is the one door that publishes with no review at all.
"""

from __future__ import annotations

from typing import Mapping, Optional, Tuple

# The default of the person's publish bar, `skill_min_confidence`, when neither
# the preference nor the `skill_autosave_min_confidence` setting says otherwise.
PUBLISH_FLOOR_DEFAULT = 0.85

# The lowest confidence at which a skill learned from a chat publishes itself.
# 0.85 because it is the bar the Skills Audit publishes at by default, and the
# audit publishes only after it has run the skill and had a judge pass it — a
# learned skill has been through neither, so it may not clear a lower bar than
# a tested one does. The extractor's own default, when the model names no
# confidence, is 0.7, and the prompt tells it to keep a thin skill's confidence
# low, so a skill reaches 0.85 only when the model says outright that it is
# sure. The person's slider can raise this bar; lowering the slider lowers the
# audit's bar and the teacher-draft floor, never this one (the owner's "at
# least 0.85").
LEARNED_PUBLISH_MINIMUM = 0.85

# What a write the agent makes may not change on a skill: whether it is
# published, how sure the store is of it (a teacher draft is shown to the model
# from the floor up), and who wrote it (`teacher-escalation` is what lets a
# draft be shown at all — `skills.skill_gate`).
LIFECYCLE_FIELDS = ("status", "confidence", "source")

# What the agent is told when it tries to publish. A tool result the model
# reads, so it names the person and the place and stops the search for another
# door (`Law 10`, `Law 15`).
AGENT_CANNOT_PUBLISH = (
    "Publishing a skill is the person's step, not mine: a published skill is "
    "used as their own guidance in every later chat, so it waits for them to "
    "test it and publish it from the Skills window. It stays a draft until then."
)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def publish_policy(owner: Optional[str]) -> Tuple[bool, float]:
    """`(auto_publish, floor)` for this person.

    `auto_publish` is `auto_approve_skills` (on unless set); `floor` is
    `skill_min_confidence`, then the `skill_autosave_min_confidence` setting,
    then `PUBLISH_FLOOR_DEFAULT`, clamped to 0–1. The Skills Audit's bar
    (`routes/skills_routes._audit_finalize_status`) and the slider under
    *Auto-publish skills* are this one number.
    """
    try:
        from routes.prefs_routes import _load_for_user
        prefs = _load_for_user(owner) or {}
    except Exception:
        prefs = {}
    try:
        from src.settings import get_setting
        default_floor = get_setting("skill_autosave_min_confidence", PUBLISH_FLOOR_DEFAULT)
    except Exception:
        default_floor = PUBLISH_FLOOR_DEFAULT
    enabled = bool(prefs.get("auto_approve_skills", True))
    try:
        floor = float(prefs.get("skill_min_confidence", default_floor))
    except (TypeError, ValueError):
        floor = PUBLISH_FLOOR_DEFAULT
    return enabled, _clamp(floor)


def learned_publish_floor(owner: Optional[str]) -> Tuple[bool, float]:
    """`(auto_publish, floor)` for a skill learned from a chat: the person's
    floor, never under `LEARNED_PUBLISH_MINIMUM`."""
    enabled, floor = publish_policy(owner)
    return enabled, max(LEARNED_PUBLISH_MINIMUM, floor)


def learned_status(owner: Optional[str], confidence) -> str:
    """`published` or `draft` for a skill the extractor just learned.

    Anything this cannot read — the preferences, the confidence — answers
    `draft`: a skill that is not published can still be published by a person,
    and one that is published is already in their next chat.
    """
    try:
        enabled, floor = learned_publish_floor(owner)
        conf = float(confidence)
    except Exception:
        return "draft"
    if conf != conf:   # NaN compares false with every floor; say so plainly
        return "draft"
    return "published" if (enabled and conf >= floor) else "draft"


def pin_lifecycle(updates: Mapping, current: Optional[Mapping]) -> dict:
    """`updates` with the `LIFECYCLE_FIELDS` the stored skill has put back.

    For every write the agent makes to an existing skill, so a SKILL.md body
    that says `status: published` — the agent's, or a page's it read — cannot
    publish the skill it is written over. A field the stored skill does not
    carry is left out rather than written as None.
    """
    out = dict(updates)
    current = current or {}
    for key in LIFECYCLE_FIELDS:
        if current.get(key) is not None:
            out[key] = current.get(key)
        else:
            out.pop(key, None)
    return out
