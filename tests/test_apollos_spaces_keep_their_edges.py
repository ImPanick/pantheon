# SPDX-License-Identifier: AGPL-3.0-or-later
"""Spaces keep their edges, on the server (settled calls 11-13).

The outline's *Spaces*: a sub-space sees its parent, a parent sees only a
summary of its children, a grant gives one space read of another (read only,
one way, logged, revocable), and an airgapped space shares nothing in or out.
Every case drives the real code over a temp database and a temp Brain, and
says what a space could or could not read.
"""
import json
import os

import pytest

from src.apollo import frame, knows, notebook, spaces as S, tasks as T
from src.apollo.errors import ApolloRefused
from tests.helpers.apollo_db import apollo_db  # noqa: F401  (fixture)

NO_FIT = lambda owner, text: None  # noqa: E731
ADA, BOB = "ada", "bob"


@pytest.fixture
def db(apollo_db, tmp_path, monkeypatch):
    from src.memory import MemoryManager
    (tmp_path / "brain").mkdir()
    monkeypatch.setattr(knows, "_manager", MemoryManager(str(tmp_path / "brain")))
    monkeypatch.setattr(knows, "_sealed", {})
    d = apollo_db()
    yield d
    d.close()


def _brain(tmp):
    with open(tmp / "brain" / "memory.json") as f:
        return json.load(f)


def _tree(db):
    work = S.create(db, ADA, "CyberKnox")
    sbir = S.create(db, ADA, "SBIR", parent_id=work.id)
    home = S.create(db, ADA, "Home")
    return work, sbir, home


def test_a_sub_space_reads_its_parent_and_the_top_layer_and_nothing_beside_it(db):
    work, sbir, home = _tree(db)
    assert S.scope(db, ADA, sbir.id).reads == [sbir.id, work.id, None]
    assert S.scope(db, ADA, work.id).reads == [work.id, None]
    assert S.scope(db, ADA, None).reads == [None]
    assert home.id not in S.scope(db, ADA, sbir.id).reads


def test_a_parent_sees_counts_of_its_children_never_their_contents(db):
    work, sbir, home = _tree(db)
    T.create(db, ADA, title="Draft the SBIR budget", pick=NO_FIT, space_id=sbir.id)
    t = T.create(db, ADA, title="Ask the PI", pick=NO_FIT, space_id=sbir.id)
    T.set_state(t, "needs_you", question="Which PI?")
    db.flush()
    kids = S.children(db, ADA, work.id)
    assert kids == [{"id": sbir.id, "name": "SBIR", "sealed": False, "open": 2, "needs_you": 1}]
    # The parent's own task list holds none of them.
    assert T.list_for(db, ADA, space=work.id) == []


def test_another_persons_space_is_not_found(db):
    work = S.create(db, ADA, "CyberKnox")
    for call in (lambda: S.get(db, BOB, work.id),
                 lambda: S.scope(db, BOB, work.id),
                 lambda: T.create(db, BOB, title="x", pick=NO_FIT, space_id=work.id),
                 lambda: S.grant(db, BOB, work.id, work.id, "memory")):
        with pytest.raises(ApolloRefused) as no:
            call()
        assert no.value.status == 404


def test_names_are_unique_among_siblings_and_spaces_nest_four_deep(db):
    a = S.create(db, ADA, "A")
    with pytest.raises(ApolloRefused):
        S.create(db, ADA, "a")
    b = S.create(db, ADA, "B", parent_id=a.id)
    c = S.create(db, ADA, "C", parent_id=b.id)
    d = S.create(db, ADA, "D", parent_id=c.id)
    with pytest.raises(ApolloRefused):
        S.create(db, ADA, "E", parent_id=d.id)


def test_a_grant_reads_one_way_and_never_changes_what_it_reads(db, tmp_path):
    work, sbir, home = _tree(db)
    knows.remember(ADA, "The garage code changes monthly", where=S.scope(db, ADA, home.id))
    g = S.grant(db, ADA, work.id, home.id, "memory")
    seen = knows.what_apollo_knows(ADA, S.scope(db, ADA, work.id))
    assert [(x["text"], x["via_grant"]) for x in seen] == [("The garage code changes monthly", g.id)]
    # One way: Home reads nothing of CyberKnox.
    knows.remember(ADA, "SBIR is due in March", where=S.scope(db, ADA, work.id))
    assert [x["text"] for x in knows.what_apollo_knows(ADA, S.scope(db, ADA, home.id))] == [
        "The garage code changes monthly"]
    # Read only: changing it from the reading space is refused.
    with pytest.raises(ApolloRefused) as no:
        knows.edit(ADA, seen[0]["id"], "mine now", S.scope(db, ADA, work.id))
    assert no.value.status == 409
    # Revoked: gone at once.
    S.revoke(db, ADA, g.id)
    assert all(x["text"] != "The garage code changes monthly"
               for x in knows.what_apollo_knows(ADA, S.scope(db, ADA, work.id)))


def test_a_grant_to_a_space_already_above_is_refused(db):
    work, sbir, _ = _tree(db)
    with pytest.raises(ApolloRefused):
        S.grant(db, ADA, sbir.id, work.id, "memory")
    with pytest.raises(ApolloRefused):
        S.grant(db, ADA, sbir.id, sbir.id, "memory")
    with pytest.raises(ApolloRefused):
        S.grant(db, ADA, work.id, sbir.id, "files")


def test_an_airgap_shares_nothing_in_or_out(db):
    work, sbir, home = _tree(db)
    g = S.grant(db, ADA, home.id, work.id, "outcomes")
    S.set_airgap(db, ADA, work.id, True)
    # Grants into or out of it, or its sub-spaces, are revoked.
    db.refresh(g)
    assert g.revoked_at is not None
    assert S.scope(db, ADA, work.id).reads == [work.id]
    # Its sub-space reads it, and nothing above it.
    assert S.scope(db, ADA, sbir.id).reads == [sbir.id, work.id]
    for reader, source in ((home.id, work.id), (sbir.id, home.id), (home.id, sbir.id)):
        with pytest.raises(ApolloRefused) as no:
            S.grant(db, ADA, reader, source, "memory")
        assert no.value.status == 409


def test_the_persons_rules_reach_every_space_but_an_airgapped_one(db):
    work, sbir, home = _tree(db)
    knows.remember(ADA, "Never book me before 10", category="rule")
    assert "Never book me before 10" in knows.stated_rules(ADA, where=S.scope(db, ADA, sbir.id))
    S.set_airgap(db, ADA, home.id, True)
    assert knows.stated_rules(ADA, where=S.scope(db, ADA, home.id)) == []


def test_a_line_kept_behind_an_airgap_is_not_in_brain_at_all(db, tmp_path):
    work, sbir, home = _tree(db)
    S.set_airgap(db, ADA, work.id, True)
    knows.remember(ADA, "The SBIR budget is 1.2M", where=S.scope(db, ADA, sbir.id))
    assert all("SBIR" not in str(e.get("text")) for e in _brain(tmp_path))
    sealed = tmp_path / "brain" / "apollo-sealed" / work.id / "memory.json"
    assert "SBIR budget" in sealed.read_text()
    # The All view and every open space read Brain only.
    assert knows.what_apollo_knows(ADA) == []
    assert knows.what_apollo_knows(ADA, S.scope(db, ADA, home.id)) == []
    # Inside the edge it's there.
    assert [x["text"] for x in knows.what_apollo_knows(ADA, S.scope(db, ADA, sbir.id))] == [
        "The SBIR budget is 1.2M"]


def test_turning_an_airgap_off_and_on_carries_its_lines_across(db, tmp_path):
    work, sbir, _ = _tree(db)
    knows.remember(ADA, "Prefers Signal for SBIR", where=S.scope(db, ADA, sbir.id))
    S.set_airgap(db, ADA, work.id, True)
    assert not any("Signal" in str(e.get("text")) for e in _brain(tmp_path))
    S.set_airgap(db, ADA, work.id, False)
    back = [e for e in _brain(tmp_path) if "Signal" in str(e.get("text"))]
    assert len(back) == 1 and back[0][knows.SPACE_KEY] == sbir.id
    assert not os.path.exists(tmp_path / "brain" / "apollo-sealed" / work.id / "memory.json") or \
        "Signal" not in (tmp_path / "brain" / "apollo-sealed" / work.id / "memory.json").read_text()


def test_the_all_view_leaves_sealed_spaces_out_but_says_one_needs_you(db):
    work, sbir, home = _tree(db)
    T.create(db, ADA, title="Fix the gutter", pick=NO_FIT, space_id=home.id)
    t = T.create(db, ADA, title="Secret thing", pick=NO_FIT, space_id=sbir.id)
    T.set_state(t, "needs_you", question="Go?")
    db.flush()
    S.set_airgap(db, ADA, work.id, True)
    assert [x.title for x in T.list_for(db, ADA)] == ["Fix the gutter"]
    st = T.status(db, ADA)
    assert st["state"] == "working" and st["sealed_needs_you"] is True
    # Its parent (the top layer) sees only that something there needs them.
    assert S.children(db, ADA, None)[0] == {"id": work.id, "name": "CyberKnox", "sealed": True,
                                            "needs_you": True}


def test_apollos_frame_in_a_space_holds_its_own_and_its_parents_never_a_siblings(db):
    work, sbir, home = _tree(db)
    T.create(db, ADA, title="Draft the SBIR budget", pick=NO_FIT, space_id=sbir.id)
    T.create(db, ADA, title="Book the CyberKnox offsite", pick=NO_FIT, space_id=work.id)
    T.create(db, ADA, title="Fix the gutter", pick=NO_FIT, space_id=home.id)
    notebook.add(db, ADA, "Owe Sam the slides", kind="open_loop", space_id=home.id)
    text = frame.build(db, ADA, space_id=sbir.id, knows=knows)
    assert "Draft the SBIR budget" in text
    line = next(x for x in text.splitlines() if "Book the CyberKnox offsite" in x)
    assert line.endswith("(in CyberKnox)")
    assert "gutter" not in text and "Sam" not in text
    assert "“CyberKnox › SBIR”" in text


def test_a_granted_read_shows_in_the_frame_read_only_and_is_logged(db):
    from core.database import ApolloGrantUse
    work, _, home = _tree(db)
    knows.remember(ADA, "Lives in Juneau", where=S.scope(db, ADA, home.id))
    done = T.create(db, ADA, title="Renew the cert", pick=NO_FIT, space_id=home.id)
    T.set_state(done, "done", outcome="Renewed until 2027.")
    gm = S.grant(db, ADA, work.id, home.id, "memory")
    go = S.grant(db, ADA, work.id, home.id, "outcomes")
    text = frame.build(db, ADA, space_id=work.id, knows=knows)
    assert "What they told you in “Home” (read only; inform, never change):\n- Lives in Juneau" in text
    assert "What “Home” finished (read only):\n- Renew the cert: Renewed until 2027." in text
    used = {u.grant_id for u in db.query(ApolloGrantUse).all()}
    assert used == {gm.id, go.id}
    ctx = S.context(db, ADA, home.id)
    assert {(r["name"], r["scope"]) for r in ctx["read_by"]} == {("CyberKnox", "memory"), ("CyberKnox", "outcomes")}
    assert len(ctx["uses"]) == 2


def test_an_airgapped_frame_says_so_and_carries_no_rule_from_outside(db):
    work, sbir, _ = _tree(db)
    knows.remember(ADA, "Never book me before 10", category="rule")
    S.set_airgap(db, ADA, work.id, True)
    text = frame.build(db, ADA, space_id=sbir.id, knows=knows)
    assert "airgapped" in text and "Never book me before 10" not in text


def test_a_local_only_space_refuses_a_paid_model_before_anything_leaves(db, monkeypatch):
    from src.apollo import runs
    work, sbir, _ = _tree(db)
    with pytest.raises(ApolloRefused):
        S.set_local_only(db, ADA, work.id, True)       # only behind an airgap
    S.set_airgap(db, ADA, work.id, True)
    S.set_local_only(db, ADA, work.id, True)
    t = T.create(db, ADA, title="Draft the SBIR budget", pick=NO_FIT, space_id=sbir.id)
    t.lead_agent = "writer"
    run, why = runs.prepare(db, ADA, t, endpoint_url="https://api.openai.com/v1")
    assert run is None and "keeps to local models" in why
    assert t.state == "needs_you" and t.question == why
    # A task's chat and the space's own chat are pinned too.
    t.session_id = "s-task"
    db.flush()
    assert S.local_only_for_session(db, ADA, "s-task") == "CyberKnox"
    with pytest.raises(ApolloRefused):
        S.require_local("CyberKnox", "https://api.openai.com/v1")
    S.require_local("CyberKnox", "http://localhost:11434")
    # The pin comes off with the airgap.
    S.set_airgap(db, ADA, work.id, False)
    assert S.get(db, ADA, work.id).local_only is False
    assert S.local_only_for_session(db, ADA, "s-task") is None


def test_a_space_is_deleted_only_when_empty_and_tasks_move_with_their_sub_tasks(db):
    work, sbir, home = _tree(db)
    with pytest.raises(ApolloRefused):
        S.remove(db, ADA, work.id)            # holds SBIR
    top = T.create(db, ADA, title="Plan", pick=NO_FIT, space_id=sbir.id)
    sub = T.create(db, ADA, title="Step", pick=NO_FIT, space_id=sbir.id, parent_id=top.id)
    with pytest.raises(ApolloRefused):
        S.remove(db, ADA, sbir.id)            # holds tasks
    with pytest.raises(ApolloRefused):
        T.update(db, ADA, sub.id, {"space_id": home.id})
    T.update(db, ADA, top.id, {"space_id": home.id})
    assert (top.space_id, sub.space_id) == (home.id, home.id)
    S.remove(db, ADA, sbir.id)
    assert [s["name"] for s in S.tree(db, ADA)] == ["CyberKnox", "Home"]


def test_a_sub_task_lives_in_its_parents_space(db):
    work, _, home = _tree(db)
    top = T.create(db, ADA, title="Plan", pick=NO_FIT, space_id=work.id)
    with pytest.raises(ApolloRefused):
        T.create(db, ADA, title="Step", pick=NO_FIT, space_id=home.id, parent_id=top.id)


def test_a_database_built_from_phase_1_gains_the_space_column(tmp_path, monkeypatch):
    """`apollo_tasks` and `apollo_notes` shipped in phase 1 without `space_id`;
    `create_all` never alters a table, so the migration adds it, once, and
    every earlier row stays on the top layer."""
    import sqlite3
    import core.database as D
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE apollo_tasks (id VARCHAR PRIMARY KEY, owner VARCHAR, title VARCHAR)")
    conn.execute("CREATE TABLE apollo_notes (id VARCHAR PRIMARY KEY, owner VARCHAR, text VARCHAR)")
    conn.execute("INSERT INTO apollo_tasks VALUES ('t1', 'ada', 'Call Mom')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(D, "DATABASE_URL", f"sqlite:///{path}")
    D._migrate_add_apollo_space_columns()
    D._migrate_add_apollo_space_columns()   # a second start changes nothing
    conn = sqlite3.connect(path)
    for table in ("apollo_tasks", "apollo_notes"):
        assert "space_id" in [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    assert list(conn.execute("SELECT id, space_id FROM apollo_tasks")) == [("t1", None)]
    conn.close()
