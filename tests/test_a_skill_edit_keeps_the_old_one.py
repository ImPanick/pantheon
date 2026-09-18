# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P8-10` / `P8-11` — what an edit destroyed, and getting it back.

Every write to a skill overwrote `SKILL.md` in place. The nightly audit is the
worst case: `_improve_skill_md` hands a model the current markdown, the model
returns a rewrite, and `_apply_skill_md` puts it on disk — **while the old text
is still sitting in the caller's `md` local**. A procedure somebody spent an
afternoon getting right could be replaced overnight by a smaller model's idea of
it, and there was nothing to compare against and nothing to go back to. The
`version:` field was decorative: `1.0.0` from the day the skill was written to
the day it was deleted, however many times its body had changed underneath.

The first test in this file is the one that matters most, because it is the test
that had to be written before the fix: **it names what today's code loses.**

A skill is a directory, so the copy goes in a `versions/` sibling and travels
with the skill when it is renamed or recategorised. Two things deliberately do
NOT make a version: a status flip and a confidence nudge. The audit performs
several of those per skill per night, and a history that records them is a
history nobody can find the real edit in.
"""

import json
import textwrap
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.datastructures import State

from routes.skills_routes import _apply_skill_md, setup_skills_routes
from services.memory.skill_format import Skill
from services.memory.skills import SkillsManager

ORIGINAL_PROCEDURE = "Run `logrotate -f /etc/logrotate.d/app` and keep 14 days"
REWRITTEN_PROCEDURE = "Delete everything in /var/log and restart"


def _md(name: str, *, procedure: str, version: str = "1.0.0",
        description: str = "rotate the application logs", owner: str = "alice",
        status: str = "published", confidence: float = 0.8) -> str:
    return textwrap.dedent(f"""\
        ---
        name: {name}
        description: {description}
        version: {version}
        category: ops
        tags: [logs]
        status: {status}
        confidence: {confidence}
        source: user
        owner: {owner}
        created: 2026-01-01T00:00:00Z
        ---

        ## When to Use

        when the disk fills up

        ## Procedure

        1. {procedure}
        """)


def _write(skills_root: Path, name: str, **kw) -> Path:
    d = skills_root / "ops" / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text(_md(name, **kw), encoding="utf-8")
    return p


def _request(user, body=None):
    scope = {"type": "http", "app": type("App", (), {"state": State()})(),
             "state": {"current_user": user}, "headers": []}
    if body is None:
        return Request(scope=scope)

    async def _receive():
        return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}

    return Request(scope=scope, receive=_receive)


def _handler(router, path: str, method: str):
    return next(r.endpoint for r in router.routes
                if r.path == path and method in r.methods)


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "skills"
    _write(root, "rotate-logs", procedure=ORIGINAL_PROCEDURE)
    return SkillsManager(str(tmp_path), library_root="")


# ---------------------------------------------------------------------------
# What it destroyed
# ---------------------------------------------------------------------------

def test_the_audits_rewrite_leaves_the_previous_text_recoverable(store):
    # The audit's own writer, driven directly — not a stand-in for it. Before
    # this row, the only copy of ORIGINAL_PROCEDURE after this call was the
    # caller's local variable, which goes out of scope.
    assert _apply_skill_md(store, "rotate-logs",
                           _md("rotate-logs", procedure=REWRITTEN_PROCEDURE),
                           "alice") is True

    live = store.read_skill_md("rotate-logs", owner="alice")
    assert REWRITTEN_PROCEDURE in live, "the rewrite did not apply, so nothing is proven"

    versions = store.list_versions("rotate-logs", owner="alice")
    assert versions, "the audit overwrote the skill and kept no copy"
    kept = store.read_version("rotate-logs", versions[0]["id"], owner="alice")
    assert ORIGINAL_PROCEDURE in kept, (
        "a copy was kept but it is not the text that was replaced"
    )


@pytest.mark.asyncio
async def test_the_markdown_editor_keeps_the_previous_text_too(store):
    # The other write path a person can reach: the raw SKILL.md card editor.
    router = setup_skills_routes(store)
    save = _handler(router, "/api/skills/{skill_id}/markdown", "POST")
    await save(_request("alice", {"markdown": _md("rotate-logs",
                                                  procedure=REWRITTEN_PROCEDURE)}),
               "rotate-logs")

    versions = store.list_versions("rotate-logs", owner="alice")
    assert len(versions) == 1, versions
    assert ORIGINAL_PROCEDURE in store.read_version(
        "rotate-logs", versions[0]["id"], owner="alice")


# ---------------------------------------------------------------------------
# The version field stops being decorative
# ---------------------------------------------------------------------------

def test_a_content_edit_bumps_the_version(store):
    before = next(s for s in store.load(owner="alice") if s["name"] == "rotate-logs")
    assert before["version"] == "1.0.0"

    _apply_skill_md(store, "rotate-logs",
                    _md("rotate-logs", procedure=REWRITTEN_PROCEDURE), "alice")

    after = next(s for s in store.load(owner="alice") if s["name"] == "rotate-logs")
    assert after["version"] == "1.0.1", (
        f"version stayed at {after['version']} across a body rewrite"
    )


def test_an_explicit_version_is_respected_rather_than_overridden(store):
    # An author who types a version means it. Auto-bumping only fills the gap
    # where nobody said anything, which is every caller in this repo today.
    _apply_skill_md(store, "rotate-logs",
                    _md("rotate-logs", procedure=REWRITTEN_PROCEDURE, version="2.0.0"),
                    "alice")
    after = next(s for s in store.load(owner="alice") if s["name"] == "rotate-logs")
    assert after["version"] == "2.0.0"


def test_bookkeeping_writes_make_no_version_and_no_bump(store):
    # `_set_conf` and `_audit_finalize_status` write confidence and status
    # several times per skill per audit. A history full of those is a history
    # with the real edit buried in it.
    store.update_skill("rotate-logs", {"confidence": 0.95}, owner="alice")
    store.update_skill("rotate-logs", {"status": "draft"}, owner="alice")

    assert store.list_versions("rotate-logs", owner="alice") == []
    after = next(s for s in store.load(owner="alice") if s["name"] == "rotate-logs")
    assert after["version"] == "1.0.0"
    assert after["confidence"] == 0.95, "the bookkeeping write itself must still land"
    assert after["status"] == "draft"


def test_history_travels_with_the_skill_when_it_is_renamed(store):
    _apply_skill_md(store, "rotate-logs",
                    _md("rotate-logs", procedure=REWRITTEN_PROCEDURE), "alice")
    assert store.update_skill("rotate-logs", {"name": "prune-logs"}, owner="alice")

    assert store.list_versions("prune-logs", owner="alice"), (
        "the rename moved the skill directory and left its history behind"
    )


def test_the_history_is_capped_so_a_nightly_audit_cannot_fill_the_disk(store):
    # Written the way the audit writes: read what is on disk, change the body,
    # put it back. So the version carried forward each time is the stored one,
    # which is what makes the bump accumulate.
    previous = ORIGINAL_PROCEDURE
    for i in range(30):
        live = store.read_skill_md("rotate-logs", owner="alice")
        _apply_skill_md(store, "rotate-logs",
                        live.replace(previous, f"revision {i}"), "alice")
        previous = f"revision {i}"

    kept = store.list_versions("rotate-logs", owner="alice")
    assert 0 < len(kept) <= 20, len(kept)
    # …and what survives is the recent end, not the oldest.
    assert "revision 28" in store.read_version("rotate-logs", kept[0]["id"], owner="alice")
    final = next(s for s in store.load(owner="alice") if s["name"] == "rotate-logs")
    assert final["version"] == "1.0.30", (
        f"thirty body rewrites moved the version to {final['version']}"
    )


# ---------------------------------------------------------------------------
# `P8-11` — getting it back
# ---------------------------------------------------------------------------

def test_a_rollback_restores_the_text_and_is_itself_undoable(store):
    _apply_skill_md(store, "rotate-logs",
                    _md("rotate-logs", procedure=REWRITTEN_PROCEDURE), "alice")
    target = store.list_versions("rotate-logs", owner="alice")[0]["id"]

    assert store.restore_version("rotate-logs", target, owner="alice") is True
    live = store.read_skill_md("rotate-logs", owner="alice")
    assert ORIGINAL_PROCEDURE in live
    assert REWRITTEN_PROCEDURE not in live

    # The thing you rolled back FROM is now itself a version, so a rollback made
    # by mistake costs one more click rather than the work it replaced.
    newest = store.read_version(
        "rotate-logs", store.list_versions("rotate-logs", owner="alice")[0]["id"],
        owner="alice")
    assert REWRITTEN_PROCEDURE in newest


def test_a_rollback_never_moves_the_skill_or_its_owner(store):
    # The same guarantee `_apply_skill_md` and the markdown save already make:
    # a name is the identity, the directory and the API id, and two independent
    # guards enforce never-rename-on-save. A restore reads a file a person can
    # hand-edit, so it needs the guard too — a snapshot whose frontmatter says
    # something else must not move the directory and orphan the id the UI holds.
    _apply_skill_md(store, "rotate-logs",
                    _md("rotate-logs", procedure=REWRITTEN_PROCEDURE), "alice")
    vid = store.list_versions("rotate-logs", owner="alice")[0]["id"]

    tampered = Path(store.skills_root) / "ops" / "rotate-logs" / "versions" / f"{vid}.md"
    tampered.write_text(
        _md("somewhere-else", procedure=ORIGINAL_PROCEDURE, owner="mallory")
        .replace("category: ops", "category: elsewhere"),
        encoding="utf-8")

    assert store.restore_version("rotate-logs", vid, owner="alice") is True
    restored = Skill.from_markdown(store.read_skill_md("rotate-logs", owner="alice"))
    assert ORIGINAL_PROCEDURE in restored.body_extra + " ".join(restored.procedure)
    assert restored.name == "rotate-logs"
    assert restored.owner == "alice"
    assert restored.category == "ops"
    assert (Path(store.skills_root) / "ops" / "rotate-logs" / "SKILL.md").exists()
    assert not (Path(store.skills_root) / "elsewhere").exists()


@pytest.mark.parametrize("version_id", [
    "../../../etc/passwd",
    "../SKILL",
    "0001-1.0.0/../../../SKILL",
    "",
    "not-a-version",
])
def test_a_version_id_cannot_address_anything_outside_the_skill(store, version_id):
    _apply_skill_md(store, "rotate-logs",
                    _md("rotate-logs", procedure=REWRITTEN_PROCEDURE), "alice")
    assert store.read_version("rotate-logs", version_id, owner="alice") is None
    assert store.restore_version("rotate-logs", version_id, owner="alice") is False


def test_another_users_skill_has_no_history_you_can_read(tmp_path):
    root = tmp_path / "skills"
    _write(root, "rotate-logs", procedure=ORIGINAL_PROCEDURE, owner="alice")
    sm = SkillsManager(str(tmp_path), library_root="")
    _apply_skill_md(sm, "rotate-logs", _md("rotate-logs",
                                           procedure=REWRITTEN_PROCEDURE), "alice")
    vid = sm.list_versions("rotate-logs", owner="alice")[0]["id"]

    assert sm.list_versions("rotate-logs", owner="bob") is None
    assert sm.read_version("rotate-logs", vid, owner="bob") is None
    assert sm.restore_version("rotate-logs", vid, owner="bob") is False


def test_a_deleted_skill_takes_its_history_with_it(store):
    _apply_skill_md(store, "rotate-logs",
                    _md("rotate-logs", procedure=REWRITTEN_PROCEDURE), "alice")
    assert store.delete_skill("rotate-logs", owner="alice") is True
    assert not (Path(store.skills_root) / "ops" / "rotate-logs").exists(), (
        "the versions directory kept the skill directory alive after a delete"
    )
