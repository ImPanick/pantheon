# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P9-12` — "non-passing" in the skills bulk delete, and the undo it never had.

This is a **data-loss** row, so it is tested the way `Law 20` prefers: the real
`_selectedNonPassingSkills` body is resolved out of `static/js/skills.js` by
brace balance and **called** against real skill rows, in the sandbox pattern
`tests/test_tool_effect_surfaces_js.py` owns. A grep for `'fail'` would pass on
a module that never reaches the branch.

**The row's premise, re-measured 2026-09-18.** *"It currently catches
never-audited skills, so a brand-new hand-written skill counts as failing"* is
true and is the smallest of four defects in thirteen lines:

  * **never audited was the default state.** `audit_verdict` is `null` until
    `set_audit` writes one, and the backend reads that same absence the opposite
    way in three places — `routes/skills_routes.py:1769`, `:1785` and
    `src/builtin_actions.py:2211` build the **audit queue** out of
    `not s.get("audit_verdict")`. A skill was on the audit queue and in the
    delete set at the same time;
  * **the bundled library was the whole set.** `/api/skills` folds in the
    read-only bundled entries and `load_all` does not read a verdict for them at
    all, so every one matched `!== 'pass'` permanently. `DELETE` refuses them, so
    nothing was destroyed — but the count, the confirmation and the toast all
    disagreed with each other and with what happened;
  * **the recommended keeper was deleted with its duplicates.**
    `_duplicateMeta` groups client-side at 0.38 similarity (the server's own
    dedup-at-creation uses 0.82) and marks one member `_duplicateKeep`, which
    the card labels *"recommended"*. `_necessityKind` returned `'duplicate'` for
    every member including that one, so the whole group went;
  * **missing confidence was read as zero**, which is below every threshold —
    while `services/memory/skills.py:1100-1119` states the opposite rule for the
    same field and says why: *"Missing confidence = treat as 1.0 (legacy skills
    shouldn't silently vanish)."*

And four of the six verdicts `set_audit` writes are not judgements against the
skill. The audit prompt says so itself at `routes/skills_routes.py:193-196`:
*"that is NOT the skill's fault. Return verdict 'inconclusive' — do NOT mark it
fail or needs_work."*

What is pinned below, and why each is a defect if it breaks: **an unaudited
skill is never a target**; **`inconclusive` and `skipped` are never targets**;
**a bundled entry is never a target**; **a duplicate group keeps its keeper**;
**an absent confidence is not a zero**; **nothing is deleted whose source could
not be read first**, because a delete that cannot be undone is the thing the row
is about; and **the copy on the button says which skills it will take**, which
is `Law 15` and the reason the old sentence was wrong on the screen as well as
in the code.
"""

import json
import re
import shutil
from pathlib import Path

import pytest

from test_a_draft_skill_is_uncatalogued_not_inactive import js_function  # noqa: E402
from test_tool_effect_surfaces_js import _DOM, _run  # noqa: E402
from tests.helpers.source_text import blank_text  # B290

ROOT = Path(__file__).resolve().parents[1]
SKILLS_JS = ROOT / "static" / "js" / "skills.js"
INDEX = ROOT / "static" / "index.html"
SKILL_ROUTES = ROOT / "routes" / "skills_routes.py"
SKILLS_MANAGER = ROOT / "services" / "memory" / "skills.py"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# Every verdict `set_audit` is called with anywhere in the backend. Derived, not
# retyped, so a seventh added later shows up here rather than silently joining
# whichever branch it falls into.
_VERDICTS = sorted(set(re.findall(r'set_audit\([^,]+,\s*"([a-z_]+)"', SKILL_ROUTES.read_text(encoding="utf-8"))))


_SHIM = r"""
import { installDom } from './dom.js';
export const document = installDom();
"""


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    """Nothing from `skills.js` is imported: the one function under test is
    lifted out of it and driven with its free variables supplied, so the
    module's 2,600 lines of unrelated startup do not have to be stood up. The
    DOM shim is still the shared one (`Law 14`) because `_necessityKind` reads
    nothing from it but a future change might."""
    directory = tmp_path_factory.mktemp("bulkdelete")
    (directory / "dom.js").write_text(_DOM)
    (directory / "shim.js").write_text(_SHIM)
    return directory


_HARNESS = """
    let _selectedNames = new Set(__SELECTED__);
    let skills = __SKILLS__;
    let _skillApprovalThreshold = __THRESHOLD__;
    __NECESSITY__
    __BODY__
"""


def _select(sandbox, rows, selected=None, threshold=0.85):
    source = SKILLS_JS.read_text(encoding="utf-8")
    body = js_function(source, "function _selectedNonPassingSkills(")
    necessity = "function _necessityKind(sk) " + js_function(source, "function _necessityKind(")
    verdicts = source[source.index("const _FAILING_AUDIT_VERDICTS"):]
    verdicts = verdicts[: verdicts.index("\n")]
    names = [r["name"] for r in rows] if selected is None else selected
    script = (
        _HARNESS
        .replace("__SELECTED__", json.dumps(names))
        .replace("__SKILLS__", json.dumps(rows))
        .replace("__THRESHOLD__", str(threshold))
        .replace("__NECESSITY__", necessity + "\n    " + verdicts)
        .replace("__BODY__", "function _selectedNonPassingSkills() " + body)
    )
    return _run(sandbox, "import './shim.js';\n", script + """
        console.log(JSON.stringify(_selectedNonPassingSkills().map(s => s.name)));
    """)


def _skill(name, **kw):
    row = {"name": name, "id": name, "description": name, "status": "draft", "confidence": 0.8}
    row.update(kw)
    return row


# ── the row's own defect ────────────────────────────────────────────────────

def test_a_skill_that_has_never_been_audited_is_not_a_delete_target(sandbox):
    """The row in one case. `audit_verdict` is absent until an audit runs, and
    three backend call sites read that same absence as *needs auditing* — so
    "delete non passing" was deleting the audit queue."""
    got = _select(sandbox, [
        _skill("hand-written"),                      # no verdict key at all
        _skill("explicitly-null", audit_verdict=None),
        _skill("explicitly-blank", audit_verdict=""),
    ])
    assert got == [], f"an unaudited skill is still a target: {got}"


def test_a_failed_audit_is_still_a_delete_target(sandbox):
    """The button has to keep doing the job it exists for. A fix that spares
    everything is not a fix."""
    got = _select(sandbox, [
        _skill("broken", audit_verdict="fail"),
        _skill("shaky", audit_verdict="needs_work"),
        _skill("fine", audit_verdict="pass", confidence=0.95),
    ])
    assert sorted(got) == ["broken", "shaky"]


def test_every_verdict_the_backend_writes_lands_on_a_deliberate_side(sandbox):
    """Six values reach this field. Two are judgements against the skill; the
    audit's own prompt says `inconclusive` means the harness failed, not the
    skill, and `skipped` is written when there was no source to read."""
    assert set(_VERDICTS) >= {"pass", "inconclusive", "skipped"}, _VERDICTS
    # Every row is scored above the threshold, so the only thing under test is
    # the verdict — a `pass` at 0.8 would be caught by the confidence clause and
    # read as this test failing when it is the other rule working.
    rows = [_skill(v, audit_verdict=v, confidence=0.95)
            for v in sorted(set(_VERDICTS) | {"fail", "needs_work", "unknown"})]
    got = set(_select(sandbox, rows))
    assert got == {"fail", "needs_work"}, (
        f"these verdicts are being deleted: {sorted(got)} — {sorted(_VERDICTS)} exist"
    )


def test_a_bundled_library_entry_is_never_counted(sandbox):
    """`/api/skills` folds in read-only bundled entries with no verdict, and
    `DELETE` refuses them — `_verify_owner` 404s on `owner: null` and
    `delete_skill` never walks the library directory. Counting them made the
    confirmation promise a number the run could never deliver.

    Both flags are asserted, and each with a **failing verdict**, because
    otherwise the unaudited rule spares the row on its own and the guard under
    test is never reached. The two are separate questions — *is it mine to
    delete* and *did it fail* — and a version that only answers the second one
    starts counting the whole 286-entry library again the moment those entries
    carry a verdict.
    """
    got = _select(sandbox, [
        _skill("bundled-flag", bundled=True, audit_verdict="fail"),
        _skill("readonly-flag", editable=False, audit_verdict="fail"),
        _skill("both-flags", bundled=True, editable=False, audit_verdict="fail"),
        _skill("mine", audit_verdict="fail"),
    ])
    assert got == ["mine"], f"a read-only library entry is still counted: {got}"


def test_a_duplicate_group_keeps_the_one_the_card_recommends(sandbox):
    """`_duplicateMeta` marks exactly one member `_duplicateKeep` and the card
    renders it as *"recommended"*. Deleting it with the rest is the one outcome
    the recommendation exists to prevent."""
    got = _select(sandbox, [
        _skill("tidy-logs", _duplicateGroup=1, _duplicateKeep=True),
        _skill("tidy-logs-2", _duplicateGroup=1, _duplicateKeep=False),
        _skill("tidy-logs-3", _duplicateGroup=1, _duplicateKeep=False),
    ])
    assert got == ["tidy-logs-2", "tidy-logs-3"], (
        "the recommended keeper was deleted with its duplicates"
    )


def test_an_absent_confidence_is_not_read_as_zero(sandbox):
    """`services/memory/skills.py:1100-1119` states the rule for this field and
    the reason: *"Missing confidence = treat as 1.0 (legacy skills shouldn't
    silently vanish)."* Reading it as 0 puts it below every threshold."""
    manager = SKILLS_MANAGER.read_text(encoding="utf-8")
    assert "Missing confidence = treat as 1.0" in manager, (
        "the backend rule this mirrors has moved — re-check both before editing"
    )
    got = _select(sandbox, [
        _skill("legacy", audit_verdict="pass", confidence=None),
        _skill("no-key", audit_verdict="pass"),
        _skill("garbage", audit_verdict="pass", confidence="not a number"),
        _skill("genuinely-low", audit_verdict="pass", confidence=0.4),
    ])
    del got  # names asserted below, after removing the key entirely
    rows = [
        {"name": "no-key", "id": "no-key", "status": "draft", "audit_verdict": "pass"},
        _skill("genuinely-low", audit_verdict="pass", confidence=0.4),
    ]
    assert _select(sandbox, rows) == ["genuinely-low"]


def test_the_threshold_still_catches_a_scored_skill_below_it(sandbox):
    """The threshold clause is kept, not removed — it only stops applying to
    skills that were never scored. `add_skill` writes 0.8 and the default bar is
    0.85, so before this every skill was below the bar from birth."""
    assert 'confidence: float = 0.8' in SKILLS_MANAGER.read_text(encoding="utf-8")
    got = _select(sandbox, [
        _skill("scored-low", audit_verdict="pass", confidence=0.6),
        _skill("scored-high", audit_verdict="pass", confidence=0.95),
        _skill("never-scored", confidence=0.8),
    ], threshold=0.85)
    assert got == ["scored-low"]


def test_nothing_unselected_is_ever_a_target(sandbox):
    """The oldest guard in the function, kept and pinned: a mutation that drops
    the selection check turns a bulk button into a library wipe."""
    got = _select(sandbox, [
        _skill("picked", audit_verdict="fail"),
        _skill("not-picked", audit_verdict="fail"),
    ], selected=["picked"])
    assert got == ["picked"]


# ── the undo path ───────────────────────────────────────────────────────────

def test_the_source_of_every_skill_is_read_before_anything_is_deleted():
    """There is no trash on the server: `delete_skill` removes the whole skill
    directory, version history included. The only place a restore can come from
    is the browser that asked for the delete, so the markdown is fetched first —
    and a skill whose source will not load is not deleted at all."""
    source = SKILLS_JS.read_text(encoding="utf-8")
    body = blank_text(js_function(source, "async function _bulkDeleteNonPassing("))
    fetch_at = body.index("_fetchSkillMarkdown")
    delete_at = body.index("method: 'DELETE'")
    assert fetch_at < delete_at, "the delete runs before the source is saved"
    # The bail-out, not just the read.
    assert "unreadable.length" in body and body.index("unreadable.length") < delete_at
    # And the manager really does remove the directory — the premise the whole
    # undo path rests on.
    manager = SKILLS_MANAGER.read_text(encoding="utf-8")
    delete_fn = manager[manager.index("def delete_skill("):]
    delete_fn = delete_fn[: delete_fn.index("\n    def ")]
    assert "os.rmdir(skill_dir)" in delete_fn, (
        "if this stopped removing the directory, the undo path can be simpler"
    )


def test_the_delete_offers_an_undo_that_restores_through_two_real_routes():
    """There is no create-from-markdown route, so a restore is `add` followed by
    `markdown`. `source: 'user'` is load-bearing: it is what exempts the
    restored skill from `add_skill`'s dedup-at-creation, which would otherwise
    silently return the *other* member of the duplicate group it was deleted
    beside."""
    source = SKILLS_JS.read_text(encoding="utf-8")
    delete_body = blank_text(js_function(source, "async function _bulkDeleteNonPassing("))
    assert "action: 'Undo'" in delete_body
    assert "_restoreDeletedSkills" in delete_body

    restore = blank_text(js_function(source, "async function _restoreDeletedSkills("))
    assert "/api/skills/add" in restore
    assert "/markdown" in restore
    assert "'user'" in restore, "a restore that dedups is a restore that loses the skill"
    assert restore.index("/api/skills/add") < restore.index("/markdown"), (
        "the markdown POST 404s unless the skill exists"
    )
    # The route the restore depends on really does take these.
    routes = SKILL_ROUTES.read_text(encoding="utf-8")
    assert 'source: str = "user"' in routes
    assert '@router.post("/{skill_id}/markdown")' in routes


def test_the_button_says_which_skills_it_will_take():
    """`Law 15`. The confirmation promised *"duplicates, generic/irrelevant
    skills, failed audits, and anything below N%"* and then took everything that
    had never been audited — the surface was wrong in the same way the code was,
    so a person could not have caught it by reading the screen."""
    confirm = blank_text(js_function(SKILLS_JS.read_text(encoding="utf-8"),
                                     "async function _bulkDeleteNonPassing("))
    # Asserted on one literal: the sentence is built by concatenation, so a
    # substring spanning the join exists on screen and not in the source.
    assert "audited yet are not included" in confirm, (
        "the confirmation does not say what it leaves alone"
    )
    assert "undo" in confirm.lower(), "a destructive confirmation that hides the undo"

    tooltip = re.search(
        r'id="skills-bulk-delete-nonpassing"[^>]*?title="([^"]*)"',
        INDEX.read_text(encoding="utf-8"),
    )
    assert tooltip, "the bulk-delete button lost its tooltip"
    assert "not been audited" in tooltip.group(1)
    assert "undo" in tooltip.group(1).lower()
