# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P8-13` — "improve this draft", built out of the trick the audit already uses.

The row says: *the existing rewrite prompt with a synthetic verdict, a trick the
audit itself already uses to force a metadata-only fix.* Found before writing
anything, at `routes/skills_routes.py` in `_audit_one_skill`: when
`_eval_skill_retrieval_precision` comes back unhappy, the audit calls
`_improve_skill_md` with a verdict it **constructed by hand** —
`{"verdict": "pass", "confidence": 1.0, "summary": …, "issues": [...]}` — and a
one-sentence transcript reading *"Retrieval audit only: the procedure may work,
but matching metadata is too broad."* There was no test run and no reviewer; the
synthetic verdict is what aims the rewriter at the metadata and away from the
procedure.

So `improve` is that same call with the issues coming from `lint_skill` instead
of from a model. That matters for three reasons and they are the whole row:

  * the lint is **free** — no model call, no timeout, and it works on an install
    with nothing configured, so the issue list is always available;
  * `_improve_skill_md` already refuses to rename, already strips `<think>`
    blocks and already keeps only the last complete frontmatter document, so
    none of that is rebuilt (`Law 14`);
  * `_apply_skill_md` writes through `update_skill` → `_write_skill`, which is
    where `P8-10` keeps the previous copy — so an improvement a person dislikes
    is one `action=restore` away, and the handler says so rather than assuming
    they know.

Every test here drives `do_manage_skills` with a stub standing in for the model,
because the row is about which prompt is sent and what is done with the answer,
and a real model would make that unobservable.
"""

import json

import pytest

from services.memory.skills import SkillsManager
from src.tools.system import do_manage_skills

THIN = {
    "name": "rotate-logs",
    "description": "logs",
    "category": "general",
    "when_to_use": "sometimes",
    "procedure": ["rotate them"],
}

IMPROVED = """---
name: rotate-logs
description: Rotate and prune nginx access logs when /var is full
category: ops
tags: [nginx, logrotate]
status: draft
confidence: 0.8
---

# Rotate logs

## When to Use
When /var/log has filled and nginx still holds the old handles.

## Procedure
1. Run logrotate -f /etc/logrotate.d/nginx
2. Confirm with lsof that nginx reopened

## Pitfalls
- Deleting the open file frees nothing until nginx reopens

## Verification
- df -h /var shows the space back
"""


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("src.constants.DATA_DIR", str(tmp_path))
    sm = SkillsManager(str(tmp_path), library_root="")
    sm.add_skill(source="user", owner=None, status="draft", **THIN)
    monkeypatch.setattr("services.memory.skills.SkillsManager",
                        lambda *a, **k: SkillsManager(str(tmp_path), library_root=""))
    monkeypatch.setattr("routes.skills_routes._resolve_audit_models",
                        lambda owner=None: ("http://x", "m", {}, None))
    return sm


def _capture(monkeypatch, reply=IMPROVED):
    seen = {}

    async def _fake(skill_md, verdict, transcript, url, model, headers):
        seen.update({"md": skill_md, "verdict": verdict, "transcript": transcript,
                     "url": url, "model": model})
        return reply

    monkeypatch.setattr("routes.skills_routes._improve_skill_md", _fake)
    return seen


async def _improve(**extra):
    payload = {"action": "improve", "name": "rotate-logs"}
    payload.update(extra)
    return await do_manage_skills(json.dumps(payload), owner=None)


# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_verdict_handed_to_the_rewriter_is_built_from_the_lint(store, monkeypatch):
    seen = _capture(monkeypatch)
    await _improve()
    verdict = seen["verdict"]
    assert verdict["verdict"] == "pass", "a synthetic pass, exactly as the audit does"
    issues = "\n".join(verdict["issues"])
    assert "verification" in issues.lower()
    assert "pitfalls" in issues.lower()
    # The fix, not only the complaint — `lint_skill` carries both and a rewriter
    # given only the complaint has to guess what good looks like.
    assert "Add one check per expected outcome" in issues


@pytest.mark.asyncio
async def test_the_metadata_findings_carry_the_prefix_the_prompt_reads(store, monkeypatch):
    """`_improve_skill_md`'s system prompt says it may correct frontmatter when
    the reviewer flagged it *"(issues prefixed 'metadata:')"*. A lint finding
    about the category that does not carry the prefix is a finding the prompt
    tells the model to leave alone."""
    seen = _capture(monkeypatch)
    await _improve()
    issues = verdict_issues = seen["verdict"]["issues"]
    meta = [i for i in issues if i.startswith("metadata:")]
    assert any("category" in i for i in meta), issues
    assert any("tags" in i for i in meta), issues
    # …and a body-level finding must NOT claim to be metadata.
    assert not any(i.startswith("metadata:") and "verification" in i for i in issues)


@pytest.mark.asyncio
async def test_no_test_is_run_and_the_transcript_says_so(store, monkeypatch):
    seen = _capture(monkeypatch)
    await _improve()
    assert "no test" in seen["transcript"].lower(), seen["transcript"]


@pytest.mark.asyncio
async def test_the_rewrite_lands_on_disk_and_the_old_copy_is_kept(store, monkeypatch):
    _capture(monkeypatch)
    out = await _improve()
    sm = SkillsManager(str(store.data_dir), library_root="")
    md = sm.read_skill_md("rotate-logs", owner=None)
    assert "Verification" in md and "logrotate" in md
    versions = sm.list_versions("rotate-logs", owner=None)
    assert versions, "P8-10 keeps the copy this replaced"
    # Both halves of the undo: where the old text is listed, and what puts it
    # back. Naming only one of them is a hint, not an affordance.
    assert "versions" in out["results"] and "restore" in out["results"], out["results"]


@pytest.mark.asyncio
async def test_the_name_cannot_be_moved_by_the_rewrite(store, monkeypatch):
    _capture(monkeypatch, reply=IMPROVED.replace("name: rotate-logs",
                                                 "name: somewhere-else"))
    await _improve()
    sm = SkillsManager(str(store.data_dir), library_root="")
    names = {s["name"] for s in sm.load(owner=None)}
    assert names == {"rotate-logs"}, names


@pytest.mark.asyncio
async def test_a_clean_skill_is_told_it_is_clean_and_nothing_is_written(store, monkeypatch):
    """Silence reads as *the check did not run*, which is `P8-12`'s own rule
    about the lint panel applied to the same findings in the chat channel."""
    sm = SkillsManager(str(store.data_dir), library_root="")
    sm.update_skill("rotate-logs", {
        "description": "Rotate and prune nginx access logs when /var is full",
        "category": "ops", "tags": ["nginx", "logrotate"],
        "when_to_use": "When /var/log has filled and nginx still holds the handles",
        "procedure": ["Run logrotate -f", "Check lsof"],
        "pitfalls": ["Deleting the open file frees nothing"],
        "verification": ["df -h /var shows the space back"],
    }, owner=None)
    called = _capture(monkeypatch)
    before = SkillsManager(str(store.data_dir),
                           library_root="").read_skill_md("rotate-logs", owner=None)

    out = await _improve()
    assert "nothing the lint can fix" in out["results"], out["results"]
    assert "no missing section" in out["results"], out["results"]
    assert not called, "no model was asked about a skill with nothing wrong"
    assert SkillsManager(str(store.data_dir), library_root="").read_skill_md(
        "rotate-logs", owner=None) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [None, "", "   "], ids=["none", "empty", "blank"])
async def test_a_model_that_returns_nothing_leaves_the_skill_alone(store, monkeypatch, reply):
    _capture(monkeypatch, reply=reply)
    before = SkillsManager(str(store.data_dir),
                           library_root="").read_skill_md("rotate-logs", owner=None)
    out = await _improve()
    assert out.get("exit_code") == 1
    assert "no usable rewrite" in out["error"], out["error"]
    assert SkillsManager(str(store.data_dir), library_root="").read_skill_md(
        "rotate-logs", owner=None) == before


@pytest.mark.asyncio
async def test_a_rewrite_identical_to_the_original_is_not_a_write(store, monkeypatch):
    """A model that echoes the file back has not improved it, and writing it
    anyway would spend a version slot on nothing — `P8-10` keeps twenty."""
    sm = SkillsManager(str(store.data_dir), library_root="")
    same = sm.read_skill_md("rotate-logs", owner=None)
    _capture(monkeypatch, reply=same)
    out = await _improve()
    assert out.get("exit_code") == 1
    assert "no usable rewrite" in out["error"], out["error"]
    assert not (SkillsManager(str(store.data_dir),
                              library_root="").list_versions("rotate-logs", owner=None))


@pytest.mark.asyncio
async def test_with_no_model_configured_the_lint_is_still_handed_over(store, monkeypatch):
    """`Law 16`'s install: nothing configured, nothing reachable. The improve
    cannot run — and the findings it would have sent are free, so they are
    printed instead of swallowed into 'no model configured'."""
    def _boom(owner=None):
        raise ValueError("No model configured — set a Default or Utility model in Settings.")
    monkeypatch.setattr("routes.skills_routes._resolve_audit_models", _boom)
    out = await _improve()
    assert out.get("exit_code") == 1
    assert "No model configured" in out["error"]
    assert "verification" in out["error"].lower(), out["error"]


@pytest.mark.asyncio
async def test_an_unknown_skill_is_an_error_not_a_rewrite(store, monkeypatch):
    _capture(monkeypatch)
    out = await do_manage_skills(json.dumps({"action": "improve", "name": "nope"}),
                                 owner=None)
    assert out.get("exit_code") == 1


@pytest.mark.asyncio
async def test_improve_is_advertised_where_the_other_actions_are(store):
    out = await do_manage_skills(json.dumps({}), owner=None)
    assert "improve" in out["error"], out["error"]
    assert "improve" in (do_manage_skills.__doc__ or "")
