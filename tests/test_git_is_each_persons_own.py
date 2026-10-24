# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P25-02` / `P25-03` — git is each person's own: their identity on their
commits, their token for the host a command reaches, and nothing of anyone
else's.

Driven, not read (`Law 20`): real repositories made by the real `git` in a
temporary folder, the tool's own command lines run by the host half of its
runner, and — for the one action that sends something out — a push to a
smart-HTTP git server over **https** on this machine, behind basic auth, so the
token is seen arriving where it belongs and nowhere else.

**Measured before this file, on `386f80f`:** there was no git tool; git was a
command typed into `bash`, as Pantheon's own process, carrying no person's
name, and a push needed a token pasted into a remote URL or a credential file
the next person's shell could read.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from src import git_accounts as G
from src.agent_tools import git_tools as T

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git is not installed")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    import core.database as cdb
    import src.secret_storage as ss
    engine = create_engine(f"sqlite:///{tmp_path / 'git.db'}", connect_args={"check_same_thread": False},
                           poolclass=NullPool)
    cdb.Base.metadata.create_all(engine, tables=[cdb.GitIdentity.__table__, cdb.GitCredential.__table__])
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cdb, "SessionLocal", factory)
    monkeypatch.setattr(ss, "_KEY_PATH", tmp_path / ".app_key")
    monkeypatch.setattr(ss, "_fernet", None)
    import src.workstation_access as wa
    monkeypatch.setattr(wa, "routes_tools", lambda owner, **kw: False)
    return factory


# ── the account ─────────────────────────────────────────────────────────────

def test_a_token_is_kept_encrypted_and_never_said_back(db):
    s = db()
    out = G.change(s, "alice", {"identity": {"name": "Alice Liddell", "email": "alice@example.org"},
                                "hosts": {"https://GitHub.com/": {"username": "alice", "token": "ghp_SECRET1"}}})
    assert out["identity"] == {"name": "Alice Liddell", "email": "alice@example.org"}
    assert [(h["host"], h["username"], h["set"]) for h in out["hosts"]] == [("github.com", "alice", True)]
    assert "ghp_SECRET1" not in json.dumps(out), "the answer never carries a token"
    from core.database import GitCredential
    row = s.query(GitCredential).one()
    assert row.token.startswith("enc:") and "ghp_SECRET1" not in row.token
    assert G.credential_for(s, "alice", "github.com") == ("alice", "ghp_SECRET1")
    assert G.credential_for(s, "bob", "github.com") is None, "another person has nothing of hers"
    assert G.public(s, "bob") == {"identity": None, "hosts": [], "known_hosts": out["known_hosts"]}
    G.change(s, "alice", {"hosts": {"github.com": None}})
    assert G.credential_for(s, "alice", "github.com") is None


@pytest.mark.parametrize("body,words", [
    ({"identity": {"name": "", "email": "a@b.c"}}, "Say the name"),
    ({"identity": {"name": "A <b>", "email": "a@b.c"}}, "without < or >"),
    ({"identity": {"name": "A", "email": "not-mail"}}, "not an email"),
    ({"hosts": {"not a host!": {"token": "x"}}}, "is not a host name"),
    ({"hosts": {"github.com": {"token": ""}}}, "Paste the token"),
    ({"hosts": {"github.com": {"token": "two words"}}}, "one word"),
    ({"hosts": {"github.com": {"token": "t", "username": "a:b"}}}, "without : @ or /"),
    ({"hosts": ["github.com"]}, "{host: {username, token}}"),
])
def test_what_cannot_be_kept_says_why_and_nothing_is_kept(db, body, words):
    s = db()
    with pytest.raises(G.GitRefused, match=words):
        G.change(s, "alice", dict(body, **({"identity": {"name": "Ok", "email": "ok@x.org"}}
                                           if "identity" not in body else {})))
    assert G.identity(s, "alice") is None, "all of it is checked before any of it is written"


# ── what each action is ─────────────────────────────────────────────────────

@pytest.mark.parametrize("action,effects,integrity", [
    ("status", {"read_workspace"}, "workspace_untrusted"),
    ("log", {"read_workspace"}, "workspace_untrusted"),
    ("commit", {"write_workspace"}, "workspace_untrusted"),
    ("checkout", {"write_workspace"}, "workspace_untrusted"),
    ("pull", {"network_egress", "write_workspace"}, "external_untrusted"),
    ("push", {"network_egress", "external_side_effect"}, "external_untrusted"),
    ("bogus", {"read_workspace", "write_workspace", "network_egress", "external_side_effect"}, "external_untrusted"),
])
def test_each_action_is_classified_as_what_it_does(action, effects, integrity):
    from src.tool_capabilities import capabilities_for_action
    caps = capabilities_for_action("git", json.dumps({"action": action}))
    assert {e.value for e in caps.effects} == effects and caps.result_integrity.value == integrity


def test_git_is_registered_where_the_shell_is_and_no_wider():
    from src.agent_tools import TOOL_HANDLERS, TOOL_TAGS
    from src.agent_tools.workstation_tools import LIFTED_TOOLS
    from src.tool_security import NON_ADMIN_BLOCKED_REASONS, plan_mode_disabled_tools
    assert "git" in TOOL_TAGS and "git" in TOOL_HANDLERS
    assert "git" in NON_ADMIN_BLOCKED_REASONS, "on this machine it runs beside every secret, as bash does"
    assert "git" in LIFTED_TOOLS, "and is lifted with bash for a person whose tools run in their workstation"
    assert "git" in plan_mode_disabled_tools()


@pytest.mark.parametrize("args,words", [
    ({"action": "commit"}, "needs a message"),
    ({"action": "clone", "url": "http://example.org/x.git"}, "https://"),
    ({"action": "clone", "url": "ext::sh -c touch% /tmp/pwned"}, "https://"),
    ({"action": "clone", "url": "https://user:tok@github.com/a/b.git"}, "without a user or token"),
    ({"action": "push", "remote": "--receive-pack=evil"}, "is not a remote's name"),
    ({"action": "branch", "name": "-f"}, "not a branch name"),
    ({"action": "commit", "message": "x", "files": ["--all"]}, "does not start with"),
    ({"action": "rebase"}, "is not a `git` action"),
])
def test_a_call_that_would_reach_further_is_refused_in_a_sentence(args, words):
    _, problem = T.parse_args(json.dumps(args))
    assert problem and words in problem


def test_every_argument_reaches_git_as_one_word():
    lines = T.plan({"action": "commit", "message": "a; rm -rf ~ $(id)", "files": ["x y.txt"]},
                   {"name": "A", "email": "a@b.c"})
    import shlex
    assert shlex.split(lines[1])[-2:] == ["--message", "a; rm -rf ~ $(id)"]
    assert shlex.split(lines[0])[-2:] == ["--", "x y.txt"]
    assert all("core.hooksPath=/dev/null" in ln and "core.fsmonitor=false" in ln for ln in lines)


# ── on a real repository ────────────────────────────────────────────────────

def _run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True).stdout


def _call(args, monkeypatch, cwd, owner="alice"):
    import src.tool_execution as te
    monkeypatch.setattr(te, "agent_cwd", lambda: str(cwd))
    return asyncio.run(T.run_git(json.dumps(args), owner=owner))


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "proj"
    r.mkdir()
    _run([GIT, "init", "-q", "-b", "main"], r)
    (r / "a.txt").write_text("one\n")
    return r


@needs_git
def test_a_commit_carries_the_persons_own_name_and_no_hook_runs(db, repo, tmp_path, monkeypatch):
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\ntouch {tmp_path}/hook-ran\n")
    hook.chmod(0o755)
    refused = _call({"action": "commit", "repo": "proj", "message": "First"}, monkeypatch, tmp_path)
    assert refused["exit_code"] == 1 and refused["error"] == T.NO_IDENTITY
    s = db()
    G.change(s, "alice", {"identity": {"name": "Alice Liddell", "email": "alice@example.org"}})
    st = _call({"action": "status", "repo": "proj"}, monkeypatch, tmp_path)
    assert st["exit_code"] == 0 and "a.txt" in st["output"]
    done = _call({"action": "commit", "repo": "proj", "message": "First"}, monkeypatch, tmp_path)
    assert done["exit_code"] == 0 and "First" in done["output"]
    assert _run([GIT, "log", "-1", "--pretty=%an <%ae>"], repo).strip() == "Alice Liddell <alice@example.org>"
    assert not (tmp_path / "hook-ran").exists(), "a repository's hook never runs for the agent"
    again = _call({"action": "commit", "repo": "proj", "message": "Again"}, monkeypatch, tmp_path)
    assert again == {"output": "Nothing to commit: the working tree is clean.", "exit_code": 0}
    br = _call({"action": "branch", "repo": "proj", "name": "feature/x", "create": True}, monkeypatch, tmp_path)
    assert br["exit_code"] == 0
    assert _run([GIT, "rev-parse", "--abbrev-ref", "HEAD"], repo).strip() == "feature/x"
    log = _call({"action": "log", "repo": "proj", "limit": 5}, monkeypatch, tmp_path)
    assert "Alice Liddell  First" in log["output"]


@needs_git
def test_the_repositories_are_listed_with_their_branch_and_changes(db, repo, tmp_path, monkeypatch):
    import src.tool_execution as te
    monkeypatch.setattr(te, "_owner_is_admin", lambda owner: True)
    got = asyncio.run(T.list_repos("alice", host_workspace=str(tmp_path)))
    assert got["where"] == "server" and got["repos"] == [
        {"path": "proj", "abs": str(repo), "name": "proj", "branch": "main", "changes": 1}], \
        "a branch with no commit yet is still named"
    monkeypatch.setattr(te, "_owner_is_admin", lambda owner: False)
    assert "no shell here" in asyncio.run(T.list_repos("bob", host_workspace=str(tmp_path)))["error"]


# ── a push, over https, with the person's token ─────────────────────────────

class _SmartHTTP(BaseHTTPRequestHandler):
    """`git http-backend` behind basic auth: the push is real git protocol."""
    root = ""
    expect = ""
    seen: list = []

    def log_message(self, *a):
        pass

    def _cgi(self):
        auth = self.headers.get("Authorization") or ""
        self.seen.append(auth)
        if auth != "Basic " + base64.b64encode(self.expect.encode()).decode():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="git"')
            self.end_headers()
            return
        path, _, query = self.path.partition("?")
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        env = dict(os.environ, GIT_PROJECT_ROOT=self.root, GIT_HTTP_EXPORT_ALL="1", PATH_INFO=path,
                   QUERY_STRING=query, REQUEST_METHOD=self.command, REMOTE_USER="alice",
                   CONTENT_TYPE=self.headers.get("Content-Type") or "", CONTENT_LENGTH=str(length),
                   GIT_HTTP_RECEIVE_PACK="1")
        if self.headers.get("Content-Encoding"):
            env["HTTP_CONTENT_ENCODING"] = self.headers["Content-Encoding"]
        out = subprocess.run(["git", "http-backend"], input=body, env=env, capture_output=True).stdout
        head, _, payload = out.partition(b"\r\n\r\n")
        status = 200
        headers = []
        for line in head.decode().split("\r\n"):
            k, _, v = line.partition(": ")
            if k.lower() == "status":
                status = int(v.split()[0])
            elif k:
                headers.append((k, v))
        self.send_response(status)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _cgi
    do_POST = _cgi


@pytest.fixture()
def https_remote(tmp_path, monkeypatch):
    if GIT is None or not shutil.which("openssl"):
        pytest.skip("git and openssl are needed for a push over https")
    certs = tmp_path / "certs"
    certs.mkdir()
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
                    "-keyout", str(certs / "k.pem"), "-out", str(certs / "c.pem")],
                   check=True, capture_output=True)
    served = tmp_path / "served"
    served.mkdir()
    _run([GIT, "init", "-q", "--bare", "-b", "main", "proj.git"], served)
    _SmartHTTP.root = str(served)
    _SmartHTTP.expect = "alice:tok_PUSH_ME"
    _SmartHTTP.seen = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _SmartHTTP)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certs / "c.pem", certs / "k.pem")
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("GIT_SSL_CAINFO", str(certs / "c.pem"))
    yield f"https://localhost:{srv.server_address[1]}/proj.git", f"localhost:{srv.server_address[1]}", served
    srv.shutdown()


@needs_git
def test_a_push_goes_out_with_the_token_for_that_host_only(db, repo, tmp_path, monkeypatch, https_remote):
    url, host, served = https_remote
    s = db()
    G.change(s, "alice", {"identity": {"name": "Alice", "email": "alice@example.org"}})
    _call({"action": "commit", "repo": "proj", "message": "First"}, monkeypatch, tmp_path)
    _run([GIT, "remote", "add", "origin", url], repo)

    nothing = _call({"action": "push", "repo": "proj"}, monkeypatch, tmp_path)
    assert nothing["exit_code"] != 0 and f"no token for {host}" in nothing["error"], nothing
    assert all(a == "" for a in _SmartHTTP.seen), "with no token for the host, none is sent"

    G.change(s, "alice", {"hosts": {"example.org": {"username": "alice", "token": "tok_WRONG_HOST"}}})
    _SmartHTTP.seen = []
    _call({"action": "push", "repo": "proj"}, monkeypatch, tmp_path)
    assert not any("tok_WRONG_HOST" in base64.b64decode(a.split()[-1]).decode()
                   for a in _SmartHTTP.seen if a), "another host's token is never offered"

    G.change(s, "alice", {"hosts": {host: {"username": "alice", "token": "tok_PUSH_ME"}}})
    pushed = _call({"action": "push", "repo": "proj", "set_upstream": True}, monkeypatch, tmp_path)
    assert pushed["exit_code"] == 0, pushed
    assert pushed["as"] == "your token" and pushed["host"] == host
    assert "tok_PUSH_ME" not in json.dumps(pushed)
    assert _run([GIT, "log", "-1", "--pretty=%s", "main"], served / "proj.git").strip() == "First"
    assert not (repo / ".git" / "config").read_text().count("tok_"), "nothing was written to the repository"
    cfg = Path.home() / ".git-credentials"
    assert not cfg.exists() or "tok_PUSH_ME" not in cfg.read_text()


# ── over HTTP ───────────────────────────────────────────────────────────────

@pytest.fixture()
def client(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routes.git_routes as R
    monkeypatch.setattr(R, "get_current_user", lambda request: request.headers.get("x-user"))
    monkeypatch.setattr(R, "request_is_a_person", lambda request: request.headers.get("x-token") is None)
    app = FastAPI()
    app.include_router(R.setup_git_routes())
    return TestClient(app)


def test_the_routes_answer_only_the_callers_own(client):
    put = client.put("/api/git", headers={"x-user": "alice"},
                     json={"identity": {"name": "Alice", "email": "a@x.org"},
                           "hosts": {"gitlab.com": {"token": "glpat_SECRET"}}})
    assert put.status_code == 200 and "glpat_SECRET" not in put.text
    assert put.json()["hosts"][0]["username"] == "git", "a forge accepts any user name beside a token"
    assert client.get("/api/git", headers={"x-user": "bob"}).json()["hosts"] == []
    bad = client.put("/api/git", headers={"x-user": "alice"}, json={"identity": {"name": "A", "email": "x"}})
    assert bad.status_code == 400 and bad.json()["detail"] == "That is not an email address a commit can carry."
    token = client.put("/api/git", headers={"x-user": "alice", "x-token": "1"}, json={"identity": None})
    assert token.status_code == 403 and "Only a person" in token.json()["detail"]
    assert client.get("/api/git", headers={"x-user": "alice"}).json()["identity"] == {"name": "Alice", "email": "a@x.org"}
