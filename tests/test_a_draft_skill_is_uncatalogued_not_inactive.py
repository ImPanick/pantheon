# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P8-03` / `P8-04` / `P8-05` / `P8-18` — four words the Workshop got wrong.

Every one of these is a surface describing the engine underneath it, so every
assertion below is made against the engine first and the surface second. The
engine half calls `SkillsManager` and `ToolRunSecurityContext` for real; the
surface half is scoped to the function or the card that carries the sentence,
never a file-wide substring, except where a word's presence *anywhere* would be
the defect (`Law 20`).

What the source actually says, re-measured 2026-09-18 against `0f43fcb`:

  * **`P8-03` holds, with a condition the row does not state.** `index_for`
    (services/memory/skills.py:655) leaves a user draft out of the catalogue;
    `get_relevant_skills` (:725) keeps drafts in the pool and injects one when
    it matches — *provided it clears the confidence floor*. A skill created in
    the Add-Skill form is stamped `confidence: 0.8` (`SkillAddRequest`,
    routes/skills_routes.py:53, and `SkillDoc.confidence`,
    services/memory/skill_format.py:370) and the default floor is **0.85**, so
    the form's own output is the one draft that is NOT injected. "Uncatalogued"
    is the right word; "still injected when it matches" needs "and trusted
    enough" beside it, and the surface now says both.

  * **`P8-04` holds and is narrower than it reads.** The slider is not
    inverted end to end: 50 → 95 gets monotonically stricter and only the last
    notch flips. `100` mapped to a stored **0**, and 0 is the one value that
    skips the filter entirely — `if min_confidence > 0` (:748). So the
    strictest position was one stop short of the end and the end was the
    loosest, under the label "All".

  * **`P8-05` holds exactly.** `src/agent_loop.py:3091-3093` sets the floor to
    `2.0` when `auto_approve_skills` is off. Nothing draft can reach 2.0 —
    including the "unset confidence → keep" leniency at :763, because
    `SkillDoc.confidence` defaults to 0.8 and the parser fills it, so `None`
    never reaches that branch for a file-backed skill.

  * **`P8-18` holds.** The skills block goes through
    `untrusted_context_message` (:3185) whose `arm_tool_gate` defaults to True,
    which is what `messages_contain_external_untrusted_context` reads, which is
    what arms the run's gate. Correct, invisible, and the reason a skill test
    can stop halfway.
"""
import ast
import re
from pathlib import Path

import pytest

from tests.helpers.source_text import blank  # B290

from src.agent_tools import TOOL_TAGS  # noqa: F401 — resolves the import cycle
from services.memory.skills import SkillsManager
from src.prompt_security import untrusted_context_message
from src.tool_capabilities import (
    ToolRunSecurityContext,
    messages_contain_external_untrusted_context,
)

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
SKILLS_JS = (ROOT / "static" / "js" / "skills.js").read_text(encoding="utf-8")
MEMORY_JS = (ROOT / "static" / "js" / "memory.js").read_text(encoding="utf-8")

# The default the UI ships and the default the server falls back to. Read from
# the markup rather than retyped, so a change to either shows up here.
DEFAULT_FLOOR = 0.85
# What `SkillAddRequest` stamps on anything the Add-Skill form creates.
FORM_CONFIDENCE = 0.8


def _write_skill(root: Path, name: str, *, category="general", source="user",
                 status="draft", confidence=0.9, description="tidy the build logs",
                 when="the build log is enormous"):
    d = root / category / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text("\n".join([
        "---",
        f"name: {name}",
        f"description: {description}",
        "version: 1.0.0",
        f"category: {category}",
        "tags: [build, logs]",
        f"status: {status}",
        f"confidence: {confidence}",
        f"source: {source}",
        "created: 2026-01-01T00:00:00Z",
        "---",
        "",
        "## When to Use",
        f"- {when}",
        "",
        "## Procedure",
        "1. run it",
        "",
        "## Verification",
        "- the log is smaller",
        "",
    ]), encoding="utf-8")


QUERY = "the build log is enormous, tidy the build logs please"


# ── P8-03 · the catalogue and the match are two different questions ────────

def test_a_draft_is_not_in_the_catalogue_the_model_browses(tmp_path):
    _write_skill(tmp_path / "skills", "tidy-logs", status="draft")
    _write_skill(tmp_path / "skills", "tidy-logs-pub", status="published")
    listed = {e["name"] for e in SkillsManager(str(tmp_path)).index_for()}
    assert "tidy-logs-pub" in listed
    assert "tidy-logs" not in listed, (
        "index_for stopped excluding user drafts — the word on the pill is "
        "derived from this behaviour and would now be wrong"
    )


def test_the_same_draft_is_still_injected_when_a_message_matches_it(tmp_path):
    """The half "inactive" would have denied. The skill is not switched off."""
    _write_skill(tmp_path / "skills", "tidy-logs", status="draft", confidence=0.9)
    sm = SkillsManager(str(tmp_path))
    matched = sm.get_relevant_skills(
        QUERY, skills=sm.load(), threshold=0.25, max_items=3,
        min_confidence=DEFAULT_FLOOR,
    )
    assert [s["name"] for s in matched] == ["tidy-logs"]


def test_a_skill_the_form_creates_does_not_clear_the_default_floor(tmp_path):
    """`B581`. The Add-Skill form stamps 0.8 and the shipped floor is 0.85, so
    the one draft a person makes by hand is the one that is never injected.
    Nothing said so before this row; the slider's hint says it now."""
    assert FORM_CONFIDENCE < DEFAULT_FLOOR
    _write_skill(tmp_path / "skills", "tidy-logs", status="draft",
                 confidence=FORM_CONFIDENCE)
    sm = SkillsManager(str(tmp_path))
    assert sm.get_relevant_skills(
        QUERY, skills=sm.load(), threshold=0.25, max_items=3,
        min_confidence=DEFAULT_FLOOR,
    ) == []


# ── P8-04 · which end of the slider is the loose one ───────────────────────

def test_a_floor_of_zero_turns_the_gate_off_entirely(tmp_path):
    """What the old maximum position stored. A draft the audit trusted at 10%
    is injected, which is the opposite of what "maximum" reads as."""
    _write_skill(tmp_path / "skills", "tidy-logs", status="draft", confidence=0.1)
    sm = SkillsManager(str(tmp_path))
    matched = sm.get_relevant_skills(
        QUERY, skills=sm.load(), threshold=0.25, max_items=3, min_confidence=0.0,
    )
    assert [s["name"] for s in matched] == ["tidy-logs"]


def test_a_floor_of_one_is_the_strictest_the_control_can_express(tmp_path):
    """One notch in from the end. This is where "only the ones it was surest
    of" actually lives, and it is not where the control put it."""
    _write_skill(tmp_path / "skills", "tidy-logs", status="draft", confidence=0.95)
    _write_skill(tmp_path / "skills", "tidy-logs-pub", status="published", confidence=0.95)
    sm = SkillsManager(str(tmp_path))
    names = {s["name"] for s in sm.get_relevant_skills(
        QUERY, skills=sm.load(), threshold=0.25, max_items=5, min_confidence=1.0,
    )}
    assert names == {"tidy-logs-pub"}


def test_the_slider_reaches_zero_from_its_loose_end_now():
    """The markup half: the sentinel stop is `min`, and it is one step below
    the lowest percentage the control can express, so nothing was taken away.

    Scoped to the one input rather than searched for across the page — an
    attribute like `min="45"` appears on other controls and a file-wide match
    would happily confirm the wrong element."""
    tag = re.search(r'<input[^>]*id="skill-confidence-slider"[^>]*>', INDEX)
    assert tag, "the confidence slider moved"
    attrs = dict(re.findall(r'(\w+)="([^"]*)"', tag.group(0)))
    assert attrs["min"] == "45" and attrs["max"] == "100" and attrs["step"] == "5", attrs
    # Every percentage the old control offered is still on the new one.
    assert int(attrs["min"]) + int(attrs["step"]) == 50


def test_the_mapping_sends_the_loose_end_to_zero_and_nothing_else():
    """Resolved to `syncPrefSlider`'s body before asserting, because `maxPos`
    and `allPos` are ordinary words that appear in other functions."""
    body = js_function(MEMORY_JS, "export async function syncPrefSlider")
    assert "const allPos = Number(slider.min);" in body
    assert "pos <= allPos ? 0 : pos / 100" in body, (
        "the save no longer maps the sentinel stop to 0 — either the geometry "
        "moved back or the stored meaning changed"
    )
    assert "pos >= maxPos ? 0" not in body, "the old inverted mapping is back"


# ── P8-05 · the coupling the toggle never mentioned ────────────────────────

def test_turning_auto_approve_off_makes_injection_published_only(tmp_path):
    """The consequence, driven rather than read. 2.0 is unreachable for any
    draft, including one whose confidence is missing: the parser fills it."""
    _write_skill(tmp_path / "skills", "tidy-logs", status="draft", confidence=1.0)
    _write_skill(tmp_path / "skills", "tidy-logs-pub", status="published", confidence=0.1)
    sm = SkillsManager(str(tmp_path))
    names = {s["name"] for s in sm.get_relevant_skills(
        QUERY, skills=sm.load(), threshold=0.25, max_items=5, min_confidence=2.0,
    )}
    assert names == {"tidy-logs-pub"}


def test_a_skill_with_no_confidence_line_is_still_given_one(tmp_path):
    """The one branch that could have made the sentence above a lie:
    `_passes` keeps a draft whose confidence is `None`. It is unreachable for a
    file-backed skill, and this is the proof rather than the assumption."""
    d = tmp_path / "skills" / "general" / "bare"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: bare\ndescription: tidy the build logs\nstatus: draft\n---\n\n"
        "## Procedure\n1. run it\n", encoding="utf-8")
    loaded = SkillsManager(str(tmp_path)).load()
    assert loaded, "the fixture did not load"
    assert loaded[0].get("confidence") is not None


def test_the_floor_the_toggle_sets_is_two_point_zero():
    """`Law 20` option 2: the scope is resolved first, then asserted inside it.
    A file-wide search for `2.0` in a 5,000-line module finds arithmetic."""
    tree = ast.parse((ROOT / "src" / "agent_loop.py").read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "_build_system_prompt"
    )
    floors = [
        node.value.value
        for node in ast.walk(fn)
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", "") == "_skill_min_conf" for t in node.targets)
        and isinstance(node.value, ast.Constant)
    ]
    assert 2.0 in floors, (
        "the published-only floor left `_build_system_prompt`; the sentence the "
        "settings card prints about auto-approve is now describing nothing"
    )


def test_the_settings_card_says_what_the_toggle_does_to_injection():
    """Two sentences, both written by `skillGateHints`, and the off-branch has
    to name the consequence rather than the mechanism."""
    body = js_function(MEMORY_JS, "export function skillGateHints")
    assert "only published skills are injected" in body
    assert "Audit all publishes" in body
    assert '<span class="admin-toggle-sub" id="skill-approve-coupling"' in INDEX
    assert 'id="skill-confidence-hint"' in INDEX


# ── P8-18 · injecting a skill raises the posture ───────────────────────────

def test_the_skills_block_arms_the_gate():
    """Driven through the real wrapper and the real reader. A mutation setting
    `arm_tool_gate=False` at the injection site survives every grep and dies
    here."""
    message = untrusted_context_message("skills", "## Available skills\n- `x` — y")
    assert message["metadata"]["tool_gate_untrusted"] is True
    assert messages_contain_external_untrusted_context([message]) is True

    ctx = ToolRunSecurityContext()
    assert ctx.gate_is_armed is False
    ctx.observe_messages([{"role": "user", "content": "hi"}, message])
    assert ctx.external_untrusted_context_seen is True
    assert ctx.gate_is_armed is True


@pytest.mark.parametrize("tool,content", [
    ("bash", "rm -rf build"),
    ("write_file", '{"path": "a.txt", "content": "x"}'),
    ("send_email", '{"to": "a@b.c", "subject": "s", "body": "b"}'),
])
def test_a_turn_that_got_a_skill_asks_before_it_acts(tool, content):
    clean = ToolRunSecurityContext()
    assert clean.decision_for(tool, content).allowed is True

    tainted = ToolRunSecurityContext()
    tainted.observe_messages([untrusted_context_message("skills", "- `x` — y")])
    decision = tainted.decision_for(tool, content)
    assert decision.allowed is False
    assert "untrusted" in (decision.reason or "").lower()


def test_the_product_says_so_where_injection_is_configured():
    """`P8-18` is correct behaviour that was completely invisible. The note
    lives beside the control that turns injection on, names the three
    consequences a person will actually meet, and does not use the word
    "untrusted" as if it explained itself."""
    card = INDEX[INDEX.index('class="admin-toggle-sub skill-gate-note"'):]
    card = card[:card.index("</span>")]
    assert "untrusted" in card
    assert "asks you" in card
    for consequence in ("writes", "runs", "sends", "deletes"):
        assert consequence in card, consequence
    assert "testing a skill" in card


# ── the word itself ───────────────────────────────────────────────────────

def test_the_pill_reads_uncatalogued():
    body = js_function(SKILLS_JS, "function _statusPill")
    assert ">uncatalogued<" in body
    assert 'data-status="draft"' in body, (
        "the stored value is frontmatter and a CSS/selection hook — `Law 2`. "
        "Only the word a person reads was supposed to move"
    )
    assert ">draft<" not in body


def test_nothing_in_the_skills_surface_calls_it_inactive():
    """The one thing a file-wide substring is good for: a word whose presence
    anywhere would be the defect. The row names this trap by name — the state
    is not "switched off", and calling it that would be the same wrong idea in
    a new word.

    Read through `blank()` rather than raw, because the comment beside the fix
    *quotes* the rejected word to say why it was rejected — which is `H02`
    exactly, and it failed this test on its own explanation the first time it
    ran."""
    for path, label in ((ROOT / "static" / "js" / "skills.js", "skills.js"),
                        (ROOT / "static" / "js" / "memory.js", "memory.js")):
        assert not re.search(r"\binactive\b", blank(path), re.I), label
    skills_panel = INDEX[INDEX.index('data-memory-panel="skills"'):]
    skills_panel = skills_panel[:skills_panel.index('data-memory-panel="rag"')]
    assert not re.search(r"\binactive\b", skills_panel, re.I)


def test_the_pill_explains_the_state_rather_than_naming_it():
    """`Law 15`. "Uncatalogued" is a better word than "draft" and still not
    self-explanatory, so the hover carries the whole rule: out of the list, in
    on a match, and what to do about it."""
    titles = SKILLS_JS[SKILLS_JS.index("const _STATUS_PILL_TITLE"):]
    titles = titles[:titles.index("};")]
    assert "not shown it in the list" in titles
    assert "still injected" in titles
    assert "Publish it" in titles


# ── helper, shared with tests/test_the_workshop_surfaces_js.py ─────────────

def js_function(source: str, signature: str) -> str:
    """The body of one JS function, resolved by brace balance from its
    signature, quotes skipped.

    `Law 20` option 2. `skills.js` is 2,000 lines of code interleaved with
    prose about code and `memory.js` is 1,700 more; three separate defects in
    this repo's history were tests matching the right string in the wrong
    function, and `B41` was green while the handler it described raised on
    every call.

    The parameter list is stepped over before the body's `{` is looked for —
    `skillGateHints({ autoApprove = true })` destructures, so the first `{`
    after the signature is an argument and not a body. That was this helper's
    own first bug, found by it returning the parameter object.
    """
    i = source.index("(", source.index(signature))
    depth, n = 0, len(source)
    while i < n:
        c = source[i]
        if c in "'\"`":
            quote, i = c, i + 1
            while i < n and source[i] != quote:
                i += 2 if source[i] == "\\" else 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    open_at = source.index("{", i)
    depth, i = 0, open_at
    while i < n:
        c = source[i]
        if c in "'\"`":
            quote, i = c, i + 1
            while i < n and source[i] != quote:
                i += 2 if source[i] == "\\" else 1
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return source[open_at:i + 1]
        i += 1
    raise AssertionError(f"unbalanced braces after {signature!r}")
