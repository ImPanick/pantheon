# SPDX-License-Identifier: AGPL-3.0-or-later
from scripts.claim_ownerless import claim_json_entries, owner_arg


def test_claim_json_entries_skips_invalid_rows():
    rows = [
        {"id": "a"},
        "bad-row",
        None,
        {"id": "b", "owner": "already"},
    ]

    assert claim_json_entries(rows, "admin") == 1
    assert rows == [
        {"id": "a", "owner": "admin"},
        "bad-row",
        None,
        {"id": "b", "owner": "already"},
    ]


def test_owner_arg_rejects_blank_owner():
    assert owner_arg(["claim_ownerless.py"]) is None
    assert owner_arg(["claim_ownerless.py", "   "]) is None
    assert owner_arg(["claim_ownerless.py", " admin "]) == "admin"


# ── `B1270`, `D-2026-10-26-01` §4: everything an install without sign-in made ──

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_DRIVE = r'''
import json, os, sys
sys.path.insert(0, os.getcwd())
from core.database import (init_db, SessionLocal, ScheduledTask, Note, CalendarCal, ToolAllowRule,
                           ModelEndpoint, Session as Chat, PersonNetworks)
from core.auth import AuthManager, DEFAULT_AUTH_PATH
from src.constants import DATA_DIR, SKILLS_DIR
from src.workstation_access import account_of
from workstation import protocol as P
init_db()
mgr = AuthManager(DEFAULT_AUTH_PATH); mgr.setup("ada", "ada-password-1")
db = SessionLocal()
db.add_all([ScheduledTask(id="t1", owner=None, name="nightly"),
            Note(id="n1", owner="__pantheon_local__", title="shopping"),
            CalendarCal(id="c1", owner=None, name="Personal"),
            ToolAllowRule(id="r1", owner="__pantheon_local__", tool_name="bash", match_kind="prefix", pattern="ls"),
            ModelEndpoint(id="e1", owner=None, name="Shared vLLM", base_url="http://gpu.lan:8000/v1"),
            Chat(id="s1", owner=None, name="old chat", endpoint_url="http://x", model="m"),
            PersonNetworks(account=account_of(None), networks="[]")])
db.commit(); db.close()
skill = os.path.join(SKILLS_DIR, "tidy"); os.makedirs(skill)
open(os.path.join(skill, "SKILL.md"), "w").write("---\nname: tidy\ndescription: x\n---\nbody\n")
theirs = os.path.join(SKILLS_DIR, "bobs"); os.makedirs(theirs)
open(os.path.join(theirs, "SKILL.md"), "w").write("---\nname: bobs\nowner: bob\n---\nbody\n")
site = os.path.join(DATA_DIR, "projects", P.project_folder(None), "site"); os.makedirs(site)
open(os.path.join(site, "index.html"), "w").write("<h1>hi</h1>")
json.dump({"theme": "retrowave"}, open(os.path.join(DATA_DIR, "user_prefs.json"), "w"))
sys.argv = ["claim_ownerless.py", "ada"] + sys.argv[1:]
sys.path.insert(0, os.path.join(os.getcwd(), "scripts"))
import claim_ownerless
code = claim_ownerless.main(sys.argv[1:])
db = SessionLocal()
out = {"code": code,
       "task": db.get(ScheduledTask, "t1").owner, "note": db.get(Note, "n1").owner,
       "cal": db.get(CalendarCal, "c1").owner, "rule": db.get(ToolAllowRule, "r1").owner,
       "endpoint": db.get(ModelEndpoint, "e1").owner, "chat": db.get(Chat, "s1").owner,
       "networks": [r.account for r in db.query(PersonNetworks).all()],
       "ada_account": account_of("ada"),
       "skill": open(os.path.join(skill, "SKILL.md")).read(),
       "bobs": open(os.path.join(theirs, "SKILL.md")).read(),
       "site": os.path.exists(os.path.join(DATA_DIR, "projects", P.project_folder("ada"), "site", "index.html")),
       "prefs": json.load(open(os.path.join(DATA_DIR, "user_prefs.json")))}
print("RESULT" + json.dumps(out))
'''


def _run(tmp_path, *args):
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL",)}
    env["PANTHEON_DATA_DIR"] = str(tmp_path)
    done = subprocess.run([sys.executable, "-c", _DRIVE, *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=300)
    assert "RESULT" in done.stdout, done.stderr[-3000:]
    return json.loads(done.stdout.split("RESULT", 1)[1]), done.stdout


def test_one_account_is_given_what_the_install_without_sign_in_made(tmp_path):
    got, out = _run(tmp_path)
    assert got["code"] == 0
    assert got["task"] == got["note"] == got["cal"] == got["rule"] == got["chat"] == "ada"
    assert got["endpoint"] is None, "a shared endpoint stays everyone's"
    assert got["networks"] == [got["ada_account"]], "the account-keyed stores move when ada has none"
    assert "owner: ada" in got["skill"] and "owner: bob" in got["bobs"] and "owner: ada" not in got["bobs"]
    assert got["site"] is True
    assert got["prefs"]["_users"]["ada"] == {"theme": "retrowave"}
    assert "model_endpoints: left as it is" in out and "docker compose exec workstation" in out


def test_a_dry_run_moves_nothing(tmp_path):
    got, out = _run(tmp_path, "--dry-run")
    assert got["code"] == 0 and "would claim" in out
    assert got["task"] is None and got["note"] == "__pantheon_local__" and got["site"] is False
    assert "owner:" not in got["skill"]
