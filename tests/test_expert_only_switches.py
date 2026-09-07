"""H16 — three shipped capabilities with no switch a person can reach.

`(b)` is `P2-21`'s and is not touched here. What is left is a shape worth
naming: **`DEFAULT_SETTINGS` is an allowlist, not a list of defaults.**
`POST /api/auth/settings` iterates `for key in DEFAULT_SETTINGS`, so a key that
is not in that dict is silently dropped from every save, and `manage_settings`
refuses it. Four keys were read by live code and absent from it — a verifier
that checks effectful turns, and the three knobs of a `while True` nightly loop
— so the only writer was hand-editing `data/settings.json`, and a save through
the UI dropped them without saying so.

`tool_path_extra_roots` is the one that deliberately does NOT get a control, and
that is the row's own second option: it widens where the agent's file tools may
reach, `_resolve_tool_path` is a `FORBIDDEN.md` Part 2 control, and while the
sensitive-basename block holds whatever roots are listed, a UI would put "point
the agent at my home directory" one click away.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
SETTINGS_JS = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")
AUTH = (ROOT / "routes" / "auth_routes.py").read_text(encoding="utf-8")
SETTINGS_PY = (ROOT / "src" / "settings.py").read_text(encoding="utf-8")


def _js_fn(source, header):
    start = source.index(header)
    i = source.index("{", start)
    depth, j = 0, i
    while j < len(source):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[start:j + 1]
        j += 1
    raise AssertionError(f"unbalanced braces reading {header}")


# ── the allowlist ──

@pytest.mark.parametrize("key,default", [
    ("agent_verifier_subagent", False),
    ("skill_audit_nightly", True),
    ("skill_audit_hour", 2),
    ("skill_audit_batch", 8),
])
def test_the_key_is_declared_with_the_default_its_reader_already_used(key, default):
    """Declared with the EXACT fallback the reader already had, so declaring
    them changes nothing today — it only makes them reachable. A different
    default here would silently change what every install does."""
    from src.settings import DEFAULT_SETTINGS
    assert key in DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS[key] == default
    assert type(DEFAULT_SETTINGS[key]) is type(default)


def test_the_readers_fallbacks_still_match_the_declarations():
    """The two sides are in different files and nothing joins them. If someone
    changes `get_setting("skill_audit_hour", 2)` to 3 and not this dict, the
    stored value and the fallback disagree and only one of them is visible."""
    from src.settings import DEFAULT_SETTINGS
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    loop_py = (ROOT / "src" / "agent_loop.py").read_text(encoding="utf-8")
    assert f'get_setting("skill_audit_hour", {DEFAULT_SETTINGS["skill_audit_hour"]})' in app_py
    assert f'get_setting("skill_audit_batch", {DEFAULT_SETTINGS["skill_audit_batch"]})' in app_py
    assert 'get_setting("skill_audit_nightly", True)' in app_py
    assert 'get_setting("agent_verifier_subagent", False)' in loop_py


def test_a_save_would_have_dropped_them_before():
    """The mechanism, asserted so the reason survives: the route's loop is over
    `DEFAULT_SETTINGS`, which is why absence meant silence."""
    assert "for key in DEFAULT_SETTINGS:" in AUTH


# ── the two numbers feed a while-loop ──

def test_the_audit_numbers_are_clamped_at_the_door():
    """An hour of 25 makes `next_daily_run` wait for a time that never comes; a
    batch of 0 audits nothing, every night, forever."""
    ranges = AUTH.split("_INT_RANGES = {", 1)[1].split("}", 1)[0]
    assert '"skill_audit_hour": (0, 23)' in ranges
    assert '"skill_audit_batch": (1, 100)' in ranges


def test_the_ui_clamps_to_the_same_range_the_server_does():
    """So the number on screen is the number that will run."""
    body = _js_fn(SETTINGS_JS, "async function initSkillAudit(")
    assert "clampInt(hourInput.value, 0, 23, 2)" in body
    assert "clampInt(batchInput.value, 1, 100, 8)" in body
    assert "hourInput.value = hour;" in body, "the clamped value must be reflected"


# ── the controls ──

def test_the_verifier_has_a_switch():
    assert 'id="set-agentVerifier"' in INDEX
    body = _js_fn(SETTINGS_JS, "async function initAgentSettings(")
    assert "payload.agent_verifier_subagent = !!verInput.checked" in body
    assert "verInput.addEventListener('change', save)" in body


def test_the_verifier_switch_explains_why_it_is_off():
    """Off by default for a reason — a weak local model false-rejects its own
    work and costs an extra round every effectful turn. A toggle with no
    explanation gets flipped by whoever is feeling optimistic."""
    card = INDEX.split('id="set-agentVerifier"', 1)[1][:700]
    assert "weak local model" in card
    assert "extra round" in card


def test_the_nightly_audit_has_its_three_controls():
    for element_id in ("set-skillAuditOn", "set-skillAuditHour", "set-skillAuditBatch"):
        assert f'id="{element_id}"' in INDEX
    assert "initSkillAudit();" in SETTINGS_JS
    assert re.search(r"async function initSkillAudit\(", SETTINGS_JS)


def test_a_stored_false_is_not_read_as_missing():
    """`skill_audit_nightly: false` is a real value. Reading it with a
    truthiness test would turn the audit back on every time the panel opened."""
    body = _js_fn(SETTINGS_JS, "async function initSkillAudit(")
    assert "settings.skill_audit_nightly !== undefined" in body


def test_the_panel_says_what_the_setting_does_in_words():
    """"8" and "2" mean nothing on their own."""
    body = _js_fn(SETTINGS_JS, "async function initSkillAudit(")
    assert "function describe(" in body
    assert "skills are only checked when you ask" in body


# ── the one that deliberately has no control ──

def test_the_filesystem_root_setting_stays_expert_only():
    """The row's own `Verify` allows "documented as deliberately expert-only",
    and this is the case for it. If a control is ever added, this test should
    be the thing that makes someone argue for it rather than the thing they
    delete on the way past."""
    assert not re.search(r"tool_path_extra_roots", INDEX), \
        "a UI appeared for tool_path_extra_roots — read FORBIDDEN.md Part 2 first"
    assert not re.search(r"tool_path_extra_roots", SETTINGS_JS)
    note = SETTINGS_PY.split('"tool_path_extra_roots"', 1)[0][-1400:]
    assert "FORBIDDEN" in note, "the reason it has no control must be written down"
    assert "expert-only" in note


def test_the_sensitive_path_block_is_still_what_makes_that_safe():
    """The reason a UI *would* be defensible is that this block holds whatever
    roots are listed. If it ever stops holding, the expert-only note above is
    no longer the whole argument."""
    tools = (ROOT / "src" / "tool_utils.py").read_text(encoding="utf-8")
    joined = tools + (ROOT / "src" / "settings.py").read_text(encoding="utf-8")
    assert ".ssh" in joined and ".gnupg" in joined
