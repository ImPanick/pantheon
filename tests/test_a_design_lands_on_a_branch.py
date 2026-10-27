# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P26-08` — *Build it*: a design lands on a branch, and nothing reaches the
base branch without the person's yes.

Driven, not read (`Law 20`): a real git repository in a temporary folder, the
real routes over HTTP, and the agent's side played by the agent's own `git`
tool (`src/agent_tools/git_tools.run_git`, `P25-03`) — the tool the agent
commits with. The base branch's tip is read from git after every step.

The adversary (`Law 17`) is a tool acting on an approval it never got: the
agent's git switching the build onto the base branch, a request that merges
without the person — a token, the assistant, a body that says `"true"` — or a
collaborator merging the owner's design.

**Measured before this file, on `2760dbe1`:** nothing in `routes/design_routes.py`,
`src/design_files.py` or `static/js/design/` made a branch, wrote a brief or
offered *Build it*; a design reached the project only as a chat message.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed here")

PAGE = "<!doctype html><html><body><h1>Wool &amp; Co</h1></body></html>"
TOKENS = {"palette": [{"name": "Ink", "value": "#111827", "role": "text"},
                      {"name": "Paper", "value": "#ffffff", "role": "background"}],
          "type": {"heading": "Inter", "body": "Inter", "mono": "", "scale": [14, 16]},
          "spacing": [4, 8], "radii": [6], "voice": "Plain."}


def git(repo, *argv):
    return subprocess.run(["git", "-C", str(repo), *argv], capture_output=True, text=True, check=True).stdout.strip()


def tip(repo, ref="main"):
    return git(repo, "rev-parse", f"refs/heads/{ref}")


@pytest.fixture()
def world(tmp_path, monkeypatch):
    import core.database as cdb
    import routes.design_routes as R
    import src.design_access as A
    import src.tool_execution as te
    import src.tool_security as ts
    import src.workstation_access as wa
    engine = create_engine(f"sqlite:///{tmp_path / 'p.db'}", connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine, tables=[cdb.DesignSystem.__table__, cdb.DesignShare.__table__,
                                                 cdb.DesignNote.__table__, cdb.GitIdentity.__table__,
                                                 cdb.GitCredential.__table__])
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    monkeypatch.setattr(R, "SessionLocal", factory)
    monkeypatch.setattr(R, "get_current_user", lambda request: request.headers.get("x-user"))
    monkeypatch.setattr(R, "request_is_a_person", lambda request: request.headers.get("x-token") is None)
    monkeypatch.setattr(wa, "routes_tools", lambda owner, **kw: False)
    monkeypatch.setattr(ts, "blocked_tools_for_owner", lambda owner: set())
    monkeypatch.setattr(te, "_owner_is_admin", lambda owner: owner == "alice")
    monkeypatch.setattr(A, "account_exists", lambda name: name in {"alice", "bob"})
    for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(k, raising=False)   # the person's identity is the one a commit carries

    repo = tmp_path / "shop"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    (repo / "app").mkdir()
    (repo / "app" / "index.html").write_text("<h1>old</h1>\n")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "first")

    s = factory()
    s.add(cdb.GitIdentity(account=wa.account_of("alice"), name="Alice", email="alice@example.org"))
    s.commit()
    s.close()

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(R.setup_design_routes())
    c = TestClient(app)
    a = {"x-user": "alice"}
    sid = c.post("/api/design/systems", headers=a, json={"name": "Acme", "scope": "personal", "tokens": TOKENS}).json()["id"]
    made = c.post("/api/design/designs", headers=a,
                  json={"project": str(repo), "name": "Shop home", "kind": "mockup", "brief": "Two products, one cart.",
                        "system": sid})
    assert made.status_code == 200, made.text
    (repo / "design" / "shop-home" / "index.html").write_text(PAGE)
    note = c.post("/api/design/notes", headers=a,
                  json={"kind": "design", "project": str(repo), "ref": "shop-home", "text": "Cart top right",
                        "selector": "body > h1"})
    assert note.status_code == 200
    c.repo = repo
    c.base = tip(repo)
    return c


A = {"x-user": "alice"}


def _build(c, **extra):
    return c.post("/api/design/designs/shop-home/build", headers=A,
                  json={"project": str(c.repo), "acceptance": "Works at 390px wide\nThe cart shows a count", **extra})


def test_build_it_makes_the_branch_and_its_brief_and_moves_nothing_on_the_base(world):
    c = world
    r = _build(c)
    assert r.status_code == 200, r.text
    got = r.json()
    wt = Path(got["worktree"])
    assert got["branch"] == "design/shop-home" and got["base"] == "main" and got["base_sha"] == c.base
    assert wt == c.repo.parent / "shop--design-shop-home" and wt.is_dir()
    assert git(wt, "symbolic-ref", "--short", "HEAD") == "design/shop-home"
    assert tip(c.repo) == c.base, "the base branch did not move"
    assert git(c.repo, "symbolic-ref", "--short", "HEAD") == "main", "the person's checkout did not move"
    brief = git(c.repo, "show", "design/shop-home:design/shop-home/BUILD.md")
    for words in ("# Build: Shop home", "## Screens", f"{c.repo}/design/shop-home/index.html", "## Tokens",
                  "--color-ink: #111827;", "## Notes", "alice (about `body > h1`): Cart top right",
                  "## Acceptance", "- Works at 390px wide", "- The cart shows a count",
                  "never merge", "Two products, one cart."):
        assert words in brief, words
    assert git(c.repo, "log", "-1", "--pretty=%an <%ae> %s", "design/shop-home", "--") == \
        "Alice <alice@example.org> Design brief: Shop home", "committed as the person"
    assert "BUILD.md" in got["message"] and str(wt) in got["message"] and "merging is mine" in got["message"]
    again = _build(c)
    assert again.status_code == 409 and "being built already" in again.json()["detail"]


def test_the_agents_git_works_on_the_branch_and_cannot_switch_it_to_the_base(world):
    from src.agent_tools.git_tools import run_git
    c = world
    wt = Path(_build(c).json()["worktree"])
    (wt / "app" / "index.html").write_text("<h1>Wool &amp; Co</h1>\n")
    done = asyncio.run(run_git({"action": "commit", "message": "Build the shop home page", "repo": str(wt)}, owner="alice"))
    assert done["exit_code"] == 0, done
    switched = asyncio.run(run_git({"action": "branch", "name": "main", "repo": str(wt)}, owner="alice"))
    assert switched["exit_code"] != 0 and "already" in switched["error"], switched
    assert tip(c.repo) == c.base, "the agent's commits are on its branch, never the base"
    st = c.get(f"/api/design/designs/shop-home/build?project={c.repo}", headers=A).json()
    assert [ln.split("  ", 1)[1] for ln in st["commits"]] == ["Build the shop home page", "Design brief: Shop home"]
    assert "app/index.html" in st["changes"] and st["base_moved"] is False and st["uncommitted"] == 0
    from_folder = c.get(f"/api/design/designs/shop-home/build?project={wt}", headers=A).json()
    assert from_folder["commits"] == st["commits"], "asked from the build folder, the same build"


def test_nothing_reaches_the_base_without_the_persons_yes(world, monkeypatch):
    from src.agent_tools.git_tools import run_git
    c = world
    wt = Path(_build(c).json()["worktree"])
    (wt / "app" / "index.html").write_text("<h1>new</h1>\n")
    asyncio.run(run_git({"action": "commit", "message": "New page", "repo": str(wt)}, owner="alice"))
    url = "/api/design/designs/shop-home/build/merge"
    body = {"project": str(c.repo)}
    for headers, extra, status in ((A, {}, 400), (A, {"yes": "true"}, 400), (A, {"yes": 1}, 400),
                                   ({"x-user": "alice", "x-token": "1"}, {"yes": True}, 403)):
        r = c.post(url, headers=headers, json={**body, **extra})
        assert r.status_code == status, (extra, r.text)
        assert tip(c.repo) == c.base, f"{extra} moved the base"
    import src.design_access as DA
    s = __import__("core.database", fromlist=["SessionLocal"]).SessionLocal()
    share = DA.share(s, "alice", DA.Access("design", "alice", str(c.repo), "shop-home", "owner", None, "Shop home"),
                     "bob", "editor")["id"]
    s.close()
    r = c.post(url, headers={"x-user": "bob"}, json={"share": share, "yes": True})
    assert r.status_code == 403 and "Only alice" in r.json()["detail"], "an editor does not merge the owner's design"

    (c.repo / "app" / "index.html").write_text("<h1>my own edit</h1>\n")
    dirty = c.post(url, headers=A, json={**body, "yes": True})
    assert dirty.status_code == 409 and "changes of its own" in dirty.json()["detail"]
    git(c.repo, "checkout", "--", "app/index.html")
    (wt / "loose.txt").write_text("not committed")
    loose = c.post(url, headers=A, json={**body, "yes": True})
    assert loose.status_code == 409 and "not committed" in loose.json()["detail"]
    (wt / "loose.txt").unlink()
    assert tip(c.repo) == c.base

    yes = c.post(url, headers=A, json={**body, "yes": True})
    assert yes.status_code == 200, yes.text
    assert (c.repo / "app" / "index.html").read_text() == "<h1>new</h1>\n", "with the yes, it is in"
    assert git(c.repo, "log", "-1", "--pretty=%an %s") == "Alice Merge design/shop-home: Shop home"
    meta = json.loads((c.repo / "design" / "shop-home" / "design.json").read_text())
    assert meta["build"]["status"] == "merged" and meta["build"]["merged_by"] == "alice"
    closed = c.post("/api/design/designs/shop-home/build/close", headers=A, json=body)
    assert closed.status_code == 200 and not wt.exists()
    assert git(c.repo, "rev-parse", "--verify", "-q", "refs/heads/design/shop-home"), "closing keeps the branch"
    again = _build(c)
    assert again.status_code == 200 and again.json()["base_sha"] == tip(c.repo), \
        "built again: the merged branch makes way for a new one from the base as it is now"


def test_a_conflict_is_undone_and_named(world):
    from src.agent_tools.git_tools import run_git
    c = world
    wt = Path(_build(c).json()["worktree"])
    (wt / "app" / "index.html").write_text("<h1>theirs</h1>\n")
    asyncio.run(run_git({"action": "commit", "message": "Theirs", "repo": str(wt)}, owner="alice"))
    (c.repo / "app" / "index.html").write_text("<h1>mine</h1>\n")
    git(c.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-am", "mine")
    moved = tip(c.repo)
    st = c.get(f"/api/design/designs/shop-home/build?project={c.repo}", headers=A).json()
    assert st["base_moved"] is True
    r = c.post("/api/design/designs/shop-home/build/merge", headers=A, json={"project": str(c.repo), "yes": True})
    assert r.status_code == 409 and "app/index.html" in r.json()["detail"] and "undone" in r.json()["detail"]
    assert tip(c.repo) == moved and git(c.repo, "status", "--porcelain", "--untracked-files=no") == "", \
        "nothing half-merged is left"


def test_a_project_that_is_not_a_repository_is_said(world, tmp_path):
    c = world
    plain = tmp_path / "plain"
    plain.mkdir()
    c.post("/api/design/designs", headers=A, json={"project": str(plain), "name": "P", "kind": "mockup"})
    r = c.post("/api/design/designs/p/build", headers=A, json={"project": str(plain)})
    assert r.status_code == 409 and "not a git repository" in r.json()["detail"]
