# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1978`. A skill could be renamed onto a name its owner already used.

`update_skill` refused a rename only when the folder it would move to,
`<category>/<new name>`, was there already. The owner's skill of that name in
another category lives in another folder, so the rename went through and left
two skills with one name. Edit, delete and the owner's groups find a skill by
its name, so from then on each acted on whichever of the two `os.walk` reached
first. `PUT /api/skills/{name}` with a `name` reaches this, and so does the
model's `manage_skills` edit or patch when the SKILL.md it writes names
another skill; the Skills window never sends a name.

Now a rename onto a name the same owner uses anywhere in their own store is
refused, nothing of that update is written, and the PUT answers 409 rather
than "Skill not found". Another owner's skill, a shipped one (`B1421`: yours
may shadow it) and the skill's own name are not in the way.

Ported from upstream Odysseus 9835c1a7 (#6941), with its cases. The lookup is
`_find_skill_path`, which already applies the owner rule to the own store,
rather than a second one.
"""
import pytest
from fastapi import HTTPException

from routes.skills_routes import SkillUpdateRequest, setup_skills_routes
from services.memory.skills import SkillsManager

from tests.test_skills_routes_owner_update import _request, _route_handler, _write_skill_md


def _two_skills(tmp_path, owner="alice", library_root=""):
    mgr = SkillsManager(str(tmp_path), library_root=library_root)
    mgr.add_skill(name="deploy-app", description="Deploy the web app", category="ops",
                  source="user", procedure=["ship it"], owner=owner)
    mgr.add_skill(name="draft-notes", description="Draft meeting notes", category="writing",
                  source="user", procedure=["write"], owner=owner)
    return mgr


def _names(mgr, owner="alice"):
    return sorted((s["name"], s["category"]) for s in mgr.load(owner=owner))


def test_a_rename_onto_a_name_the_owner_uses_in_another_category_is_refused(tmp_path):
    mgr = _two_skills(tmp_path)
    group = mgr.collections.create_group("alice", "Meetings", ["draft-notes"])

    assert mgr.update_skill("draft-notes", {"name": "deploy-app", "description": "Changed"},
                            owner="alice") is False
    assert _names(mgr) == [("deploy-app", "ops"), ("draft-notes", "writing")]
    notes = next(s for s in mgr.load(owner="alice") if s["name"] == "draft-notes")
    assert notes["description"] == "Draft meeting notes", "part of the refused update was written"
    assert mgr.collections.group("alice", group["id"])["skills"] == ["draft-notes"]   # `P8-50`
    # Each name still means one skill: deleting one leaves the other.
    assert mgr.delete_skill("draft-notes", owner="alice") is True
    assert _names(mgr) == [("deploy-app", "ops")]


def test_only_a_name_the_same_owner_uses_is_in_the_way(tmp_path):
    library = tmp_path / "library"
    _write_skill_md(library, "shipped", "shipped-notes", "")
    _write_skill_md(tmp_path / "skills", "bob-cat", "bob-notes", "bob")
    mgr = _two_skills(tmp_path, library_root=str(library))

    # However it is spelled, the owner's other skill's name is taken...
    assert mgr.update_skill("draft-notes", {"name": "Deploy App"}, owner="alice") is False
    # ...and these are not: the skill's own name, bob's, the library's, a free one.
    for old, new in (("draft-notes", "Draft Notes"), ("draft-notes", "bob-notes"),
                     ("bob-notes", "shipped-notes"), ("shipped-notes", "meeting-notes")):
        assert mgr.update_skill(old, {"name": new}, owner="alice") is True, f"{old} -> {new}"
    assert _names(mgr) == [("deploy-app", "ops"), ("meeting-notes", "writing")]
    assert _names(mgr, "bob") == [("bob-notes", "bob-cat")]


@pytest.mark.asyncio
async def test_the_put_route_answers_409_for_a_taken_name_and_still_renames_to_a_free_one(tmp_path):
    mgr = _two_skills(tmp_path)
    update_route = _route_handler(setup_skills_routes(mgr), "/api/skills/{skill_id}", "PUT")

    with pytest.raises(HTTPException) as exc:
        await update_route(_request("alice"), "draft-notes",
                           SkillUpdateRequest(name="deploy-app", status="published"))
    assert exc.value.status_code == 409
    assert exc.value.detail == "A skill named 'deploy-app' already exists"
    assert _names(mgr) == [("deploy-app", "ops"), ("draft-notes", "writing")]
    assert [s["status"] for s in mgr.load(owner="alice")] == ["draft", "draft"]

    assert await update_route(_request("alice"), "draft-notes",
                              SkillUpdateRequest(name="Meeting Notes")) == {"ok": True}
    assert _names(mgr) == [("deploy-app", "ops"), ("meeting-notes", "writing")]
