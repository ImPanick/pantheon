# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P26-09` — a design or a design system is its owner's, shared by name.

Driven, not read (`Law 20`): the real routes over HTTP, a real SQLite database
holding the sharing table and the notes, and each person's projects as real
folders — one tree per person, as each person's workstation is their own (the
workstation half of `design_files._Fs` is the same calls through the client
`P20` built and tests; here every person's folders are on this disk, rooted at
their own name, so a path that is not yours cannot reach someone else's).

The adversaries (`Law 17`): another account asking for a design with a share
id that is not theirs, or with the owner's path; and a commenter whose window
hid the buttons, pressing them anyway — the server refuses, by role.

**Measured before this file, on `2760dbe1`:** `routes/design_routes.py` said
*"collaborators are `P26-09`'s"*; a design or a design system could not be
shown to anyone but its owner, and there were no notes.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from src import design_access as A
from src import design_files as F

PAGE = "<!doctype html><html><head><style>:root { --gap: 16px; }</style></head><body><h1>Wool</h1></body></html>"
TOKENS = {"palette": [{"name": "Ink", "value": "#111827", "role": "text"},
                      {"name": "Paper", "value": "#ffffff", "role": "background"}],
          "type": {"heading": "Inter", "body": "Inter", "mono": "", "scale": [14, 16]},
          "spacing": [4, 8], "radii": [6], "voice": "Plain."}
ACCOUNTS = {"alice", "bob", "carol", "dave", "mallory"}


@pytest.fixture()
def world(tmp_path, monkeypatch):
    import core.database as cdb
    import routes.design_routes as R
    import src.tool_security as ts
    import src.workstation_access as wa
    engine = create_engine(f"sqlite:///{tmp_path / 'design.db'}", connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine, tables=[cdb.DesignSystem.__table__, cdb.DesignShare.__table__,
                                                 cdb.DesignNote.__table__])
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    monkeypatch.setattr(R, "SessionLocal", factory)
    monkeypatch.setattr(R, "get_current_user", lambda request: request.headers.get("x-user"))
    monkeypatch.setattr(R, "request_is_a_person", lambda request: request.headers.get("x-token") is None)
    monkeypatch.setattr(wa, "routes_tools", lambda owner, **kw: False)
    monkeypatch.setattr(ts, "blocked_tools_for_owner", lambda owner: set())
    monkeypatch.setattr(A, "account_exists", lambda name: name in ACCOUNTS)
    homes = tmp_path / "homes"

    async def own_tree(self):
        # Each person's projects are theirs: `shop` is a folder under their own name.
        if not self.project:
            raise F.DesignFileRefused("Pick a workspace first: a design is files in a project.", 409)
        root = homes / (self.owner or "nobody") / self.project.strip("/").replace("/", "_")
        root.mkdir(parents=True, exist_ok=True)
        self.root = str(root)
        return self

    monkeypatch.setattr(F._Fs, "open", own_tree)
    A._seen.clear()
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(R.setup_design_routes())
    c = TestClient(app)
    made = c.post("/api/design/designs", headers=_as("alice"), json={"project": "shop", "name": "Shop", "kind": "mockup"})
    assert made.status_code == 200, made.text
    page_dir = homes / "alice" / "shop" / "design" / "shop"
    (page_dir / "index.html").write_text(PAGE)
    c.post("/api/design/designs", headers=_as("alice"), json={"project": "shop", "name": "Secret", "kind": "mockup"})
    c.page = page_dir / "index.html"
    return c


def _as(user, **extra):
    return {"x-user": user, **extra}


def _share(c, invitee, role, ref="shop", kind="design", project="shop"):
    r = c.post("/api/design/shares", headers=_as("alice"),
               json={"kind": kind, "project": project, "ref": ref, "invitee": invitee, "role": role})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_a_strangers_request_for_a_design_is_not_found(world):
    c = world
    bobs = _share(c, "bob", "viewer")
    assert c.get(f"/api/design/designs/shop?share={bobs}", headers=_as("bob")).status_code == 200
    for url in (f"/api/design/designs/shop?share={bobs}", f"/api/design/designs/shop/preview?share={bobs}",
                f"/api/design/notes?kind=design&ref=shop&share={bobs}", "/api/design/designs/shop?project=shop",
                "/api/design/designs/shop/preview?project=shop"):
        r = c.get(url, headers=_as("mallory"))
        assert r.status_code == 404, (url, r.status_code, r.text)
        assert "Wool" not in r.text
    r = c.post("/api/design/notes", headers=_as("mallory"),
               json={"kind": "design", "ref": "shop", "share": bobs, "text": "mine now"})
    assert r.status_code == 404
    r = c.post("/api/design/designs/shop/adjust", headers=_as("mallory"),
               json={"share": bobs, "selector": "body > h1", "props": {"text-align": "center"}})
    assert r.status_code == 404 and "data-pantheon-edits" not in c.page.read_text()
    assert c.get("/api/design/shared", headers=_as("mallory")).json() == {"designs": [], "systems": []}


def test_a_share_names_one_design_never_the_rest_of_the_project(world):
    c = world
    bobs = _share(c, "bob", "editor")
    assert c.get(f"/api/design/designs/secret?share={bobs}", headers=_as("bob")).status_code == 404
    r = c.post("/api/design/designs/secret/versions", headers=_as("bob"), json={"share": bobs})
    assert r.status_code == 404


def test_a_commenters_write_is_refused_by_the_server_and_their_note_is_only_a_note(world):
    c = world
    carols = _share(c, "carol", "commenter")
    before = c.page.read_bytes()
    seen = c.get(f"/api/design/designs/shop?share={carols}", headers=_as("carol")).json()
    assert seen["access"]["role"] == "commenter" and seen["access"]["owner"] == "alice"
    assert "Wool" in seen["page"]["html"], "a commenter sees the page"
    for path, body in (("adjust", {"selector": "body > h1", "props": {"color": "#ff0000"}}),
                       ("versions", {}), ("restore", {"version": 1}), ("keep", {"variant": "1"}), ("tweaks", {})):
        r = c.post(f"/api/design/designs/shop/{path}", headers=_as("carol"), json={"share": carols, **body})
        assert r.status_code == 403, (path, r.text)
        assert r.json()["detail"].startswith("You can comment on it, not change it: alice shared this design")
    assert c.page.read_bytes() == before, "the file is untouched"
    note = c.post("/api/design/notes", headers=_as("carol"),
                  json={"kind": "design", "ref": "shop", "share": carols, "text": "Bigger heading?",
                        "selector": "body > h1"})
    assert note.status_code == 200 and note.json()["author"] == "carol"
    assert c.page.read_bytes() == before, "a note changes no file"
    mine = c.get("/api/design/notes?kind=design&ref=shop&project=shop", headers=_as("alice")).json()["notes"]
    assert [(n["author"], n["text"], n["selector"]) for n in mine] == [("carol", "Bigger heading?", "body > h1")]
    nope = c.post("/api/design/shares", headers=_as("carol"),
                  json={"kind": "design", "share": carols, "project": "shop", "ref": "shop", "invitee": "dave",
                        "role": "editor"})
    assert nope.status_code == 404, "a commenter shares nothing: `shop` in her own projects is not there"
    assert c.get("/api/design/shared", headers=_as("dave")).json()["designs"] == []


def test_a_viewer_looks_and_an_editor_changes_it_in_the_owners_files(world):
    c = world
    bobs = _share(c, "bob", "viewer")
    daves = _share(c, "dave", "editor")
    r = c.post("/api/design/notes", headers=_as("bob"), json={"kind": "design", "ref": "shop", "share": bobs, "text": "hi"})
    assert r.status_code == 403 and r.json()["detail"].startswith("You can look at it, not comment on it")
    assert c.get(f"/api/design/designs/shop/preview?share={bobs}", headers=_as("bob")).status_code == 200
    r = c.post("/api/design/designs/shop/adjust", headers=_as("dave"),
               json={"share": daves, "selector": "body > h1", "props": {"text-align": "center"}})
    assert r.status_code == 200, r.text
    assert "body > h1 { text-align: center; }" in c.page.read_text(), "the editor's change is in alice's file"
    versions = c.get("/api/design/designs/shop?project=shop", headers=_as("alice")).json()["versions"]
    assert versions[-1]["note"] == "Adjusted text-align center"


def test_the_owner_shares_by_name_changes_a_role_and_revokes(world):
    c = world
    for body, status, words in (
            ({"invitee": "zed", "role": "viewer"}, 404, "no account named “zed”"),
            ({"invitee": "alice", "role": "viewer"}, 400, "yours already"),
            ({"invitee": "bob", "role": "owner"}, 400, "viewer, commenter or editor"),
            ({"invitee": "bob", "role": "viewer", "ref": "nope"}, 404, "no such design")):
        r = c.post("/api/design/shares", headers=_as("alice"),
                   json={"kind": "design", "project": "shop", "ref": "shop", **body})
        assert r.status_code == status and words in r.json()["detail"], (body, r.text)
    token = c.post("/api/design/shares", headers=_as("alice", **{"x-token": "1"}),
                   json={"kind": "design", "project": "shop", "ref": "shop", "invitee": "bob", "role": "viewer"})
    assert token.status_code == 403, "a token never widens who reads its owner's designs"
    bobs = _share(c, "bob", "viewer")
    assert _share(c, "bob", "editor") == bobs, "inviting again changes the role, not a second share"
    shared = c.get("/api/design/shared", headers=_as("bob")).json()["designs"]
    assert shared == [{"share": bobs, "kind": "design", "name": "Shop", "owner": "alice", "role": "editor",
                       "slug": "shop", "system": None}]
    listed = c.get("/api/design/shares?kind=design&project=shop&ref=shop", headers=_as("alice")).json()["shares"]
    assert [(s["invitee"], s["role"]) for s in listed] == [("bob", "editor")]
    assert c.get("/api/design/shares?kind=design&project=shop&ref=shop", headers=_as("bob")).json()["shares"] == [], \
        "bob's own (empty) project, never alice's list"
    assert c.delete(f"/api/design/shares/{bobs}", headers=_as("bob")).status_code == 404, "only the owner revokes"
    assert c.delete(f"/api/design/shares/{bobs}", headers=_as("alice")).json() == {"ok": True}
    assert c.get(f"/api/design/designs/shop?share={bobs}", headers=_as("bob")).status_code == 404, "revoked is gone"
    assert c.get("/api/design/shared", headers=_as("bob")).json()["designs"] == []


def test_notes_carry_their_author_and_only_the_author_or_the_owner_removes_one(world):
    c = world
    carols = _share(c, "carol", "commenter")
    daves = _share(c, "dave", "commenter")
    n = c.post("/api/design/notes", headers=_as("carol"),
               json={"kind": "design", "ref": "shop", "share": carols, "text": "Mine"}).json()
    q = f"kind=design&ref=shop&share={daves}"
    r = c.delete(f"/api/design/notes/{n['id']}?{q}", headers=_as("dave"))
    assert r.status_code == 403 and "carol's" in r.json()["detail"]
    assert c.delete(f"/api/design/notes/{n['id']}?kind=design&ref=shop&project=shop", headers=_as("alice")).json() == {"ok": True}


def test_presence_says_who_has_it_open(world):
    c = world
    bobs = _share(c, "bob", "viewer")
    c.get("/api/design/designs/shop?project=shop", headers=_as("alice"))
    seen = c.post("/api/design/presence", headers=_as("bob"), json={"kind": "design", "ref": "shop", "share": bobs})
    assert seen.json()["present"] == ["alice", "bob"]
    assert c.post("/api/design/presence", headers=_as("mallory"),
                  json={"kind": "design", "ref": "shop", "share": bobs}).status_code == 404


def test_a_design_system_is_shared_the_same_way(world):
    c = world
    sid = c.post("/api/design/systems", headers=_as("alice"),
                 json={"name": "Acme", "scope": "personal", "tokens": TOKENS}).json()["id"]
    assert c.put(f"/api/design/systems/{sid}", headers=_as("mallory"), json={"name": "x"}).status_code == 404
    _share(c, "bob", "viewer", ref=sid, kind="system", project="")
    bobs = c.get("/api/design/systems", headers=_as("bob")).json()["systems"]
    assert [(s["name"], s["shared"]["owner"], s["shared"]["role"]) for s in bobs] == [("Acme", "alice", "viewer")]
    assert c.get("/api/design/systems", headers=_as("mallory")).json()["systems"] == []
    r = c.put(f"/api/design/systems/{sid}", headers=_as("bob"), json={"name": "Bob's now"})
    assert r.status_code == 403 and "not change it" in r.json()["detail"]
    _share(c, "bob", "editor", ref=sid, kind="system", project="")
    r = c.put(f"/api/design/systems/{sid}", headers=_as("bob"),
              json={"name": "Acme 2", "scope": "project", "project": "/elsewhere"})
    assert r.status_code == 200 and r.json()["name"] == "Acme 2" and r.json()["scope"] == "personal", \
        "an editor changes its name and tokens; where it lives stays the owner's"
    assert [s["name"] for s in c.get("/api/design/systems", headers=_as("alice")).json()["systems"]] == ["Acme 2"]
    assert c.delete(f"/api/design/systems/{sid}", headers=_as("bob")).status_code == 403
    note = c.post("/api/design/notes", headers=_as("bob"), json={"kind": "system", "ref": sid, "text": "Warmer red?"})
    assert note.status_code == 200 and note.json()["author"] == "bob"
    assert c.delete(f"/api/design/systems/{sid}", headers=_as("alice")).json() == {"ok": True}
    assert c.get("/api/design/shared", headers=_as("bob")).json()["systems"] == [], "its shares went with it"


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_the_window_draws_what_the_role_allows(tmp_path):
    mod = (Path(__file__).resolve().parents[1] / "static/js/design/collab.js").as_uri()
    case = tmp_path / "case.mjs"
    case.write_text(f"""
import {{ may, itemQuery, presenceLine }} from '{mod}';
console.log(JSON.stringify({{
  viewer: ['note', 'edit', 'share'].map((w) => may('viewer', w)),
  commenter: ['note', 'edit', 'share'].map((w) => may('commenter', w)),
  editor: ['note', 'edit', 'share'].map((w) => may('editor', w)),
  owner: ['note', 'edit', 'share'].map((w) => may('owner', w)),
  shared: itemQuery({{ kind: 'design', ref: 'shop', share: 'abc', project: '/home/alice/shop' }}),
  own: itemQuery({{ kind: 'design', ref: 'shop', project: 'shop' }}),
  alone: presenceLine(['bob'], 'bob'), two: presenceLine(['alice', 'bob'], 'bob'),
}}));
""")
    out = json.loads(subprocess.run(["node", str(case)], capture_output=True, text=True, check=True).stdout)
    assert out["viewer"] == [False, False, False] and out["commenter"] == [True, False, False]
    assert out["editor"] == [True, True, False] and out["owner"] == [True, True, True]
    assert out["shared"] == "kind=design&ref=shop&share=abc", "a shared design is named by its share, never a path"
    assert out["own"] == "kind=design&ref=shop&project=shop"
    assert out["alone"] == "" and out["two"] == "Open now: you, alice"
