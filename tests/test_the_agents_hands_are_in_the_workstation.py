# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P20-03` — when the workstation is on, the agent's hands are in it.

The owner (`D-2026-09-30-03`, answer 4): *when the workstation is on, the
agent's `bash`, `python` and file tools run inside it.* Every test here drives
the real dispatcher (`execute_tool_block`) — or the real agent loop, or the real
chat route — against the real daemon (`tests/helpers/workstation_daemon.py`
runs `workstation/agentd.py` on a local port), so what is asserted is where a
call actually ran and what actually came back (`Law 20`).

Four claims, and the parity half is the one that makes the rest worth having:

  * **it runs there, as the person**: each of the nine tools reaches the
    daemon as the account of the person the turn belongs to, in their home;
  * **it answers as it answers here**: the same command, file or tree gives
    the same `stdout`/`stderr`/`exit_code` (`FORBIDDEN.md`), the same
    `MAX_OUTPUT_CHARS` split, the same `read_file` cut, the same edit and diff
    — each case runs both ways and compares;
  * **never silently here instead**: a down or refusing workstation is a
    sentence, and nothing ran on this machine;
  * **off is today**: with the workstation off, or routing switched off, every
    tool runs exactly where and how it did.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

import src.agent_tools as agent_tools
import src.agent_tools.subprocess_tools as sp
import src.tool_execution as te
from src.agent_tools import ToolBlock
from src.workstation_client import account_for
from tests.helpers.workstation_daemon import running_workstation

ROOT = Path(__file__).resolve().parents[1]

# The row's nine, written out rather than imported, so this file states the
# contract instead of reading it back from the code under test.
WORKSTATION_TOOLS = frozenset({"bash", "python", "read_file", "write_file", "edit_file",
                               "apply_patch", "ls", "glob", "grep"})


def test_the_nine_are_the_ones_that_route():
    from src.agent_tools import workstation_tools
    assert workstation_tools.WORKSTATION_TOOLS == WORKSTATION_TOOLS

# ── the people ────────────────────────────────────────────────────────────────

_USERS: Dict[str, Dict[str, Any]] = {
    "boss": {"admin": True, "privs": {}},
    # Allowed the workstation, not a shell on this machine.
    "ann": {"admin": False, "privs": {"can_use_workstation": True, "can_use_bash": False}},
    "cat": {"admin": False, "privs": {"can_use_workstation": True, "can_use_bash": False}},
    # Allowed neither.
    "bob": {"admin": False, "privs": {"can_use_workstation": False, "can_use_bash": False}},
}


class _Auth:
    """`core.auth.AuthManager`, answering for `_USERS` — the real
    `owner_is_admin_or_single_user`, `may_use` and `resolve_privilege` run on top."""

    is_configured = True

    def is_admin(self, username):
        return bool(_USERS.get(username, {}).get("admin"))

    def get_privileges(self, username):
        # As the real manager does: an admin's map is `ADMIN_PRIVILEGES`, every
        # declared privilege — which is how `P20-02`'s `may_use` knows an admin.
        if self.is_admin(username):
            from core.auth import ADMIN_PRIVILEGES
            return dict(ADMIN_PRIVILEGES)
        return dict(_USERS.get(username, {}).get("privs", {}))


@pytest.fixture
def people(monkeypatch):
    import core.auth
    import src.auth_helpers
    monkeypatch.setattr(src.auth_helpers, "_auth_disabled", lambda: False)
    monkeypatch.setattr(core.auth, "AuthManager", _Auth)


@pytest.fixture
def settings(monkeypatch):
    """The settings store, with the workstation keys answered by the test."""
    import src.settings as S
    from workstation import protocol as P
    real = S.get_setting
    values: Dict[str, Any] = {}
    monkeypatch.setattr(S, "get_setting",
                        lambda key, default=None: values[key] if key in values else real(key, default))
    monkeypatch.delenv(P.URL_ENV, raising=False)
    monkeypatch.delenv(P.TOKEN_ENV, raising=False)
    return values


@pytest.fixture
def ws(tmp_path):
    with running_workstation(tmp_path) as station:
        yield station


def _on(settings, ws, **more):
    # `workstation_sudo` defaults True in the product, and the tools now push
    # it to the daemon before their first call (`ensure_ready`), which lifts
    # the home jail. These cases are about the jail, so they hold sudo off;
    # `test_with_sudo_on_the_jail_is_lifted_as_the_panel_says` is the default.
    settings.update({"workstation_enabled": True, "workstation_url": ws.url,
                     "workstation_token": ws.token, "workstation_sudo": False, **more})


def _home(ws, owner) -> Path:
    return ws.root / account_for(owner)


def _call(tool: str, content: Any, owner: Optional[str], *, session_id: Optional[str] = "s1",
          progress_cb=None, workspace: Optional[str] = None):
    if not isinstance(content, str):
        content = json.dumps(content)
    return asyncio.run(te.execute_tool_block(
        ToolBlock(tool, content), session_id=session_id, owner=owner, progress_cb=progress_cb,
        workspace=workspace, security_context=te.NO_TOOL_SECURITY_CONTEXT))


def _norm(value, *roots):
    """A result with each root replaced by `<ROOT>`, so a result from here and
    one from the workstation can be compared."""
    if isinstance(value, dict):
        return {k: _norm(v, *roots) for k, v in value.items()}
    if isinstance(value, list):
        return [_norm(v, *roots) for v in value]
    if isinstance(value, str):
        for r in roots:
            value = value.replace(str(r), "<ROOT>")
    return value


_WHERE = ("ran_in", "ran_as", "cwd")


def _without_where(result: Dict) -> Dict:
    return {k: v for k, v in result.items() if k not in _WHERE}


@pytest.fixture
def host_dir(tmp_path):
    """A workspace on this machine, the host side of every parity case."""
    d = tmp_path / "host-side"
    d.mkdir()
    return Path(os.path.realpath(d))


# ── it runs there, as the person ─────────────────────────────────────────────


def test_each_tool_runs_in_the_persons_home_as_their_account(ws, settings, people):
    _on(settings, ws)
    home, acct = _home(ws, "ann"), account_for("ann")

    desc, r = _call("bash", 'echo "$USER"; pwd', "ann")
    assert r["stdout"].splitlines() == [acct, str(home)] and r["exit_code"] == 0
    assert (r["ran_in"], r["ran_as"], r["cwd"]) == ("workstation", acct, str(home))
    assert desc == 'bash: echo "$USER"; pwd'

    _, r = _call("python", "import os; print(os.environ['USER'], os.getcwd())", "ann")
    assert r["stdout"] == f"{acct} {home}" and r["ran_as"] == acct

    _, r = _call("write_file", {"path": "proj/a.txt", "content": "alpha\nbeta\n"}, "ann")
    assert (home / "proj" / "a.txt").read_text() == "alpha\nbeta\n"
    assert r["output"] == f"Wrote 11 bytes to {home}/proj/a.txt" and r["diff"]["new_file"] is True

    _, r = _call("read_file", {"path": "proj/a.txt"}, "ann")
    assert r["output"] == "alpha\nbeta\n"

    desc, r = _call("edit_file", {"path": "proj/a.txt", "old_string": "beta", "new_string": "gamma"}, "ann")
    assert (home / "proj" / "a.txt").read_text() == "alpha\ngamma\n"
    assert desc == r["output"] == f"Edited {home}/proj/a.txt (1 replacement)"
    assert "+gamma" in r["diff"]["text"] and "-beta" in r["diff"]["text"]

    _, r = _call("apply_patch", "*** Begin Patch\n*** Add File: proj/b.txt\n+new\n"
                                "*** Update File: proj/a.txt\n@@\n alpha\n-gamma\n+delta\n*** End Patch", "ann")
    assert r["output"] == "Applied patch (2 files, +2/-1)" and r["diff"]["file"] == "patch"
    assert (home / "proj" / "a.txt").read_text() == "alpha\ndelta\n"
    assert (home / "proj" / "b.txt").read_text() == "new\n"

    _, r = _call("ls", {"path": "proj"}, "ann")
    assert r["output"] == f"{home}/proj:\n  a.txt  (12 B)\n  b.txt  (4 B)"

    _, r = _call("glob", {"pattern": "**/*.txt"}, "ann")
    assert sorted(r["output"].splitlines()) == [f"{home}/proj/a.txt", f"{home}/proj/b.txt"]

    _, r = _call("grep", {"pattern": "delta"}, "ann")
    assert r["output"] == f"{home}/proj/a.txt:2:delta"


def test_two_people_have_two_homes_and_one_cannot_reach_the_other(ws, settings, people):
    _on(settings, ws)
    _call("write_file", {"path": "secret.txt", "content": "ann's"}, "ann")
    _, r = _call("read_file", {"path": str(_home(ws, "ann") / "secret.txt")}, "cat")
    assert r["exit_code"] == 1 and "outside your workstation home" in r["error"]
    assert r["ran_as"] == account_for("cat")
    _, r = _call("bash", "ls", "cat")
    assert r["stdout"] == "" and _home(ws, "cat").is_dir()


def test_with_sudo_on_the_jail_is_lifted_as_the_panel_says(ws, settings, people):
    """The shipped default. The tools push the admin's `sudo` before they run
    (`ensure_ready`), so a daemon that booted with it off is brought into line —
    and with it on, one person's agent can read another's home, which is the
    sentence the Settings panel puts beside the switch."""
    _on(settings, ws, workstation_sudo=True)
    ws.system.set_sudo(False)
    _call("write_file", {"path": "secret.txt", "content": "ann's"}, "ann")
    _, r = _call("read_file", {"path": str(_home(ws, "ann") / "secret.txt")}, "cat")
    assert r["exit_code"] == 0 and "ann's" in r["output"]
    assert ws.system.sudo is True


# ── it answers as it answers here ────────────────────────────────────────────


@pytest.mark.parametrize("tool, command", [
    ("bash", "echo out; echo err >&2; exit 3"),
    ("bash", "seq 1 4000"),                                  # past MAX_OUTPUT_CHARS
    ("bash", "seq 1 3000; seq 1 3000 >&2; exit 1"),          # both streams past it
    ("bash", "printf 'a\\r\\nb\\n\\n\\ncarriage\\r'"),
    ("bash", "printf '\\377\\376 not utf-8\\n'"),       # octal: dash's printf has no \\x
    ("bash", ""),
    ("python", "print('x' * 12000)"),
    ("python", "import sys; print('o'); print('e', file=sys.stderr); sys.exit(4)"),
    ("python", "print('\\u00e9\\u4e2d' * 3)"),
], ids=["exit-code", "long", "both-long", "crlf", "bytes", "empty", "py-long", "py-exit", "py-utf8"])
def test_a_command_answers_in_the_envelope_the_host_answers_in(ws, settings, people, host_dir,
                                                                tool, command):
    here = _call(tool, command, "boss", workspace=str(host_dir))[1]
    assert "ran_in" not in here
    _on(settings, ws)
    there = _call(tool, command, "ann")[1]
    assert there["ran_in"] == "workstation"
    # `stdout`, `stderr` and `exit_code` are the envelope `FORBIDDEN.md`
    # protects; `output` is the model-facing merge, cut at MAX_OUTPUT_CHARS.
    # `cwd`: a chat's shell reports its folder on both machines since `B962`.
    assert _without_where(there) == _without_where(here)


def test_bash_in_the_workstation_is_bash(ws, settings, people, host_dir):
    """The daemon runs `bash`, the shell the tool is named for, so a bashism
    does what the model meant by it. This was the one difference in what a
    command did: here, `bash` was `/bin/sh` — dash on the Debian image (`B961`:
    `[[` was "not found", brace expansion literal). `B961` runs `bash -c` here
    too, so the two machines now agree."""
    command = "[[ 1 == 1 ]] && echo {a,b}"
    here = _call("bash", command, "boss", workspace=str(host_dir))[1]
    _on(settings, ws)
    there = _call("bash", command, "ann")[1]
    assert there["stdout"] == "a b" and there["exit_code"] == 0
    assert here["stdout"] == "a b" and here["exit_code"] == 0


def test_a_command_that_outlives_its_timeout_is_killed_and_said(ws, settings, people, host_dir,
                                                                monkeypatch):
    monkeypatch.setattr(sp, "DEFAULT_BASH_TIMEOUT", 1)
    # `exec`: here a timeout kills the shell and not its children (a B row),
    # so a plain `sleep` would outlive the test holding the pipe open.
    here = _call("bash", "echo before; exec sleep 30", "boss", workspace=str(host_dir))[1]
    _on(settings, ws)
    there = _call("bash", "echo before; exec sleep 30", "ann")[1]
    assert there["exit_code"] == 124 and there["output"] == "before"
    assert there["error"] == "bash: timed out after 1s — process killed" == here["error"]
    assert _without_where(there) == _without_where(here)


def _progress(tool, command, owner, **kw):
    seen = []

    async def cb(payload):
        seen.append(dict(payload))

    result = _call(tool, command, owner, progress_cb=cb, **kw)[1]
    return seen, result


def test_a_long_command_streams_its_progress_the_way_it_does_here(ws, settings, people, host_dir,
                                                                  monkeypatch):
    monkeypatch.setattr(sp, "PROGRESS_INTERVAL_S", 0.25)
    command = "echo one; sleep 0.8; echo two >&2; sleep 0.8; echo three; sleep 0.6"
    here, _ = _progress("bash", command, "boss", workspace=str(host_dir))
    _on(settings, ws)
    there, result = _progress("bash", command, "ann")
    assert result["ran_in"] == "workstation" and result["stdout"] == "one\nthree"
    # The payload the card reads (`agentTurn.drawToolProgress`), key for key.
    assert there and {frozenset(p) for p in there} == {frozenset(p) for p in here} \
        == {frozenset({"elapsed_s", "tail"})}
    tails = [p["tail"] for p in there]
    assert "one" in tails[0]
    # Whole lines, stderr marked, in the order they were printed — as here.
    assert tails[-1] == "one\n! two\nthree" == here[-1]["tail"]
    assert [p["elapsed_s"] for p in there] == sorted(p["elapsed_s"] for p in there)


def test_python_streams_too(ws, settings, people, monkeypatch):
    monkeypatch.setattr(sp, "PROGRESS_INTERVAL_S", 0.25)
    _on(settings, ws)
    seen, result = _progress("python", "import time\nprint('a', flush=True)\ntime.sleep(1)", "ann")
    assert result["stdout"] == "a" and any(p["tail"] == "a" for p in seen)


_TEXT_FILES = {
    "plain.txt": b"one\ntwo\nthree\n",
    "crlf.txt": b"first\r\nsecond\r\nthird\rfourth\n",
    "bytes.bin": b"ok \xff\xfe bad\nline two\n",
    "wide.txt": ("é中\U0001F600 " * 4000).encode("utf-8"),        # 28,000 chars
    "long.txt": b"".join(b"line %05d " % i + b"x" * 60 + b"\n" for i in range(1, 900)),
}


@pytest.mark.parametrize("args", [
    {},
    {"offset": 2},
    {"limit": 1},
    {"offset": 3, "limit": 2},
    {"offset": 500, "limit": 400},
], ids=["whole", "from-line-2", "one-line", "window", "past-the-cap"])
@pytest.mark.parametrize("name", sorted(_TEXT_FILES))
def test_read_file_reads_what_it_reads_here(ws, settings, people, host_dir, name, args):
    (host_dir / name).write_bytes(_TEXT_FILES[name])
    home = _home(ws, "ann")
    home.mkdir(parents=True, exist_ok=True)
    (home / name).write_bytes(_TEXT_FILES[name])
    here = _call("read_file", {"path": name, **args}, "boss", workspace=str(host_dir))[1]
    _on(settings, ws)
    there = _call("read_file", {"path": name, **args}, "ann")[1]
    # Decoding, universal newlines, the MAX_READ_CHARS cut and its marker.
    assert _without_where(there) == here


def test_read_file_with_a_bare_path_and_the_errors_here(ws, settings, people, host_dir):
    (host_dir / "sub").mkdir()
    (host_dir / "p.txt").write_text("plain\n")
    home = _home(ws, "ann")
    (home / "sub").mkdir(parents=True)
    (home / "p.txt").write_text("plain\n")
    cases = ["p.txt\nignored second line", json.dumps({"path": "sub"}),
             json.dumps({"path": "nothing.txt"}), json.dumps({"path": ""})]
    here = [_call("read_file", c, "boss", workspace=str(host_dir))[1] for c in cases]
    _on(settings, ws)
    there = [_without_where(_call("read_file", c, "ann")[1]) for c in cases]
    assert _norm(there, home) == _norm(here, host_dir)


_FILE_STEPS = [
    ("write_file", {"path": "proj/a.txt", "content": "alpha\nbeta\nbeta\n"}),
    ("write_file", "proj/a.txt\nalpha\nbeta\nbeta\ngamma\n"),
    ("edit_file", {"path": "proj/a.txt", "old_string": "beta", "new_string": "BETA"}),
    ("edit_file", {"path": "proj/a.txt", "old_string": "beta", "new_string": "BETA", "replace_all": True}),
    ("edit_file", {"path": "proj/a.txt", "old_string": "nope", "new_string": "x"}),
    ("edit_file", {"path": "proj/a.txt", "old_string": "x", "new_string": "x"}),
    ("edit_file", {"path": "proj/a.txt", "old_string": "", "new_string": "x"}),
    ("edit_file", {"path": "proj/missing.txt", "old_string": "a", "new_string": "b"}),
    ("edit_file", {"path": "proj", "old_string": "a", "new_string": "b"}),
    ("edit_file", {"path": "", "old_string": "a", "new_string": "b"}),
    ("apply_patch", "*** Begin Patch\n*** Add File: proj/b.txt\n+one\n+two\n"
                    "*** Update File: proj/a.txt\n@@\n alpha\n-BETA\n+beta\n*** End Patch"),
    # A hunk that does not match rejects the whole patch before anything is written.
    ("apply_patch", "*** Begin Patch\n*** Add File: proj/c.txt\n+never\n"
                    "*** Update File: proj/a.txt\n@@\n-no such line\n+x\n*** End Patch"),
    ("apply_patch", "*** Begin Patch\n*** Add File: proj/b.txt\n+again\n*** End Patch"),
    ("apply_patch", json.dumps({"patch_text": "*** Begin Patch\n*** Delete File: proj/b.txt\n*** End Patch"})),
    ("apply_patch", "*** Begin Patch\n*** Delete File: proj/b.txt\n*** End Patch"),
    ("apply_patch", "*** Begin Patch\n*** Update File: proj/none.txt\n@@\n-a\n+b\n*** End Patch"),
    ("apply_patch", "not a patch"),
    ("apply_patch", ""),
    ("write_file", {"path": "proj", "content": "into a directory"}),
    ("read_file", {"path": "proj/a.txt"}),
    ("ls", {"path": "proj"}),
]


def test_write_edit_and_patch_answer_as_they_do_here_diff_card_and_all(ws, settings, people, host_dir):
    here = [_call(tool, args, "boss", workspace=str(host_dir))[1] for tool, args in _FILE_STEPS]
    _on(settings, ws)
    there = [_call(tool, args, "ann")[1] for tool, args in _FILE_STEPS]
    home = _home(ws, "ann")
    assert all(r["ran_in"] == "workstation" for r in there)
    # The `diff` is what the card draws (`buildDiffHtml`): it is there, and it
    # is the same diff.
    assert sum(1 for r in there if "diff" in r) == sum(1 for r in here if "diff" in r) == 5
    for i, (a, b) in enumerate(zip(here, there)):
        assert _norm(_without_where(b), home) == _norm(a, host_dir), (i, _FILE_STEPS[i])
    assert sorted(p.name for p in (home / "proj").iterdir()) == ["a.txt"]
    assert (home / "proj" / "a.txt").read_text() == (host_dir / "proj" / "a.txt").read_text()


def _tree(root: Path, binary: bool = False) -> None:
    files = {
        "a.py": "import os\n# needle here\nprint('x')\n",
        "sub/b.txt": "nothing\nNEEDLE upper\n",
        "sub/deep/c.py": "# deep python needle\n",
        "node_modules/dep.py": "needle in dep\n",
        ".git/config": "needle in git\n",
        ".env": "NEEDLE=secret\n",
        "keys/id_rsa": "needle key\n",
        "Known_Hosts": "needle host\n",
        "notes.md": "a needle\n" * 3,
        "long.txt": "needle " + "y" * 900 + "\n",
    }
    for i, (rel, text) in enumerate(sorted(files.items())):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
    if binary:
        # Not UTF-8. The walk skips it; ripgrep prints it, and `text=True`
        # then fails the whole search here and there alike (a B row).
        (root / "bin.dat").write_bytes(b"needle \xff\xfe\n")
        os.utime(root / "bin.dat", (1_600_000_000, 1_600_000_000))
    for i in range(12):
        p = root / "many" / f"f{i:02}.py"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("needle\n" * 3)
        os.utime(p, (1_650_000_000 + i, 1_650_000_000 + i))


_NAV_CALLS = [
    ("glob", {"pattern": "*.py"}),
    ("glob", {"pattern": "**/*.py"}),
    ("glob", {"pattern": "sub/*"}),
    ("glob", {"pattern": "c.py"}),
    ("glob", {"pattern": ".env"}),
    ("glob", {"pattern": "id_rsa"}),
    ("glob", {"pattern": "*.nothing"}),
    ("glob", {"pattern": "*.py", "path": "sub"}),
    ("glob", {"pattern": "*.py", "path": "a.py"}),
    ("glob", {"pattern": ""}),
    ("grep", {"pattern": "needle"}),
    ("grep", {"pattern": "needle", "ignore_case": True}),
    ("grep", {"pattern": "needle", "glob": "*.py"}),
    ("grep", {"pattern": "needle", "max_results": 3}),
    ("grep", {"pattern": "needle", "path": "sub/b.txt", "ignore_case": True}),
    ("grep", {"pattern": "needle", "path": "no/such/dir"}),
    ("grep", {"pattern": "("}),
    ("grep", "needle"),
    ("ls", {}),
    ("ls", {"path": "sub"}),
    ("ls", "many"),
    ("ls", {"path": "a.py"}),
]


def _nav_both(ws, settings, host_dir, calls, *, binary=False):
    _tree(host_dir, binary)
    home = _home(ws, "ann")
    home.mkdir(parents=True, exist_ok=True)
    _tree(home, binary)
    settings.pop("workstation_enabled", None)
    here = [_call(tool, args, "boss", workspace=str(host_dir))[1] for tool, args in calls]
    _on(settings, ws)
    there = [_call(tool, args, "ann")[1] for tool, args in calls]
    return home, here, there


def _sorted_lines(result):
    # `grep`'s rg and walk orders follow the directory walk, which is the
    # filesystem's; the same tree in two directories may list in two orders.
    # And a hit is cut at `_CODENAV_MAX_LINE` *with its path in front*, so a
    # longer root keeps less of a long line: compared up to where both kept it.
    out = dict(result)
    if "output" in out:
        body, _, cap = out["output"].partition("\n... [")
        lines = sorted(ln[:250] for ln in body.splitlines())
        out["output"] = "\n".join(lines) + (("\n... [" + cap) if cap else "")
    return out


def test_ls_glob_and_grep_find_what_they_find_here(ws, settings, people, host_dir):
    home, here, there = _nav_both(ws, settings, host_dir, _NAV_CALLS)
    for i, (a, b) in enumerate(zip(here, there)):
        tool = _NAV_CALLS[i][0]
        a, b = _norm(a, host_dir), _norm(_without_where(b), home)
        if tool == "grep":
            a, b = _sorted_lines(a), _sorted_lines(b)
        if "max_results" in _NAV_CALLS[i][1]:
            # ripgrep searches in parallel, so WHICH hits survive a cap is not
            # fixed even between two runs here; how many, and the marker, are.
            count = lambda r: (len(r["output"].splitlines()), r["output"].rsplit("\n", 1)[-1])
            assert count(b) == count(a) == (4, "... [capped at 3 matches]"), (i, a, b)
            continue
        assert b == a, (i, _NAV_CALLS[i])
    # And what it found is what the tree holds: the junk pruned, the keys skipped.
    grep_all = there[_NAV_CALLS.index(("grep", {"pattern": "needle"}))]["output"]
    assert "a.py:2:" in grep_all and "node_modules" not in grep_all and ".git/" not in grep_all
    assert ".env" not in grep_all and "id_rsa" not in grep_all and "Known_Hosts" not in grep_all
    assert max(len(ln) for ln in grep_all.splitlines()) == 400       # the long line, cut there too


def test_grep_without_ripgrep_walks_the_same_way_in_both_places(ws, settings, people, host_dir,
                                                                monkeypatch, tmp_path):
    # Here: the fallback is taken when `rg` is not on PATH.
    real_which = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None if name == "rg" else real_which(name, *a, **k))
    # There: the daemon's commands see a PATH with python3 and nothing else.
    only_python = tmp_path / "bin-python-only"
    only_python.mkdir()
    (only_python / "python3").symlink_to(real_which("python3"))
    monkeypatch.setenv("PATH", str(only_python))
    calls = [c for c in _NAV_CALLS if c[0] == "grep"]
    home, here, there = _nav_both(ws, settings, host_dir, calls, binary=True)
    for i, (a, b) in enumerate(zip(here, there)):
        assert _sorted_lines(_norm(_without_where(b), home)) == _sorted_lines(_norm(a, host_dir)), calls[i]
    assert "bin.dat" not in there[0]["output"]      # not UTF-8: skipped by the walk


def test_the_workstation_copy_of_the_sensitive_rule_is_the_rule_here():
    """`codenav_walk.is_sensitive_path` runs where Pantheon cannot be imported;
    `_is_sensitive_path` (`FORBIDDEN.md` Part 2) is the rule. Equal over every
    listed name, its case variants, and paths either side of each."""
    from src.agent_tools import codenav_walk
    from src.tool_execution import (_SENSITIVE_BASENAMES, _SENSITIVE_BASENAMES_CF,
                                    _SENSITIVE_FILE_PATTERNS, _SENSITIVE_FILE_PATTERNS_CF,
                                    _is_sensitive_path)
    corpus = ["/home/pw-ann/notes.txt", "/", "", "relative/file", "/home/pw-ann/.sshx/key",
              "/home/pw-ann/x.env.bak", "/home/pw-ann/my_id_rsa.pub", "/home/pw-ann/.config/a"]
    for name in sorted(_SENSITIVE_BASENAMES) + list(_SENSITIVE_FILE_PATTERNS):
        for variant in (name, name.upper(), name.title()):
            corpus += [f"/home/pw-ann/{variant}", f"/home/pw-ann/{variant}/inner",
                       f"/home/pw-ann/{variant}.bak", f"{variant}"]
    for p in corpus:
        mirror = codenav_walk.is_sensitive_path(p, _SENSITIVE_BASENAMES_CF, _SENSITIVE_FILE_PATTERNS_CF)
        assert mirror == _is_sensitive_path(p), p


@pytest.mark.parametrize("tool, args", [
    ("read_file", {"path": ".ssh/id_rsa"}),
    ("read_file", {"path": "~/.bashrc"}),
    ("write_file", {"path": ".ssh/authorized_keys", "content": "ssh-ed25519 AAAA"}),
    ("edit_file", {"path": ".env", "old_string": "a", "new_string": "b"}),
    ("ls", {"path": ".gnupg"}),
    ("glob", {"pattern": "*", "path": ".ssh"}),
    ("grep", {"pattern": "x", "path": ".ssh"}),
])
def test_the_sensitive_path_rule_is_not_lifted_by_moving_the_tool(ws, settings, people, host_dir,
                                                                   tool, args):
    ssh = _home(ws, "ann") / ".ssh"
    ssh.mkdir(parents=True)
    (ssh / "id_rsa").write_text("PRIVATE")
    here = _call(tool, args, "boss", workspace=str(host_dir))[1]
    _on(settings, ws)
    there = _call(tool, args, "ann")[1]
    assert there["exit_code"] == 1 and "sensitive directory" in there["error"]
    assert _without_where(there) == here      # the same sentence, word for word
    assert (ssh / "id_rsa").read_text() == "PRIVATE" and not (ssh / "authorized_keys").exists()


def test_a_symlink_to_a_key_is_refused_once_the_workstation_resolves_it(ws, settings, people):
    home = _home(ws, "ann")
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_rsa").write_text("PRIVATE")
    (home / "innocent.txt").symlink_to(home / ".ssh" / "id_rsa")
    _on(settings, ws)
    r = _call("read_file", {"path": "innocent.txt"}, "ann")[1]
    assert r["exit_code"] == 1 and "sensitive" in r["error"] and "PRIVATE" not in json.dumps(r)


# ── never silently here instead ──────────────────────────────────────────────


_HOST_PROBES = {
    "bash": "touch {marker}",
    "python": "open({marker!r}, 'w').write('ran here')",
    "read_file": {"path": "{marker}"},
    "write_file": {"path": "{marker}", "content": "ran here"},
    "edit_file": {"path": "{marker}", "old_string": "a", "new_string": "b"},
    "apply_patch": "*** Begin Patch\n*** Add File: {marker}\n+ran here\n*** End Patch",
    "ls": {"path": "{dir}"},
    "glob": {"pattern": "*", "path": "{dir}"},
    "grep": {"pattern": "x", "path": "{dir}"},
}


def _probe(tool, marker: Path):
    spec = _HOST_PROBES[tool]
    if isinstance(spec, dict):
        return json.dumps({k: v.format(marker=str(marker), dir=str(marker.parent))
                           for k, v in spec.items()})
    return spec.format(marker=str(marker), dir=str(marker.parent))


@pytest.fixture
def host_spy(monkeypatch):
    """Every way these tools run here, recorded: the handlers `_direct_fallback`
    calls, and the `#!bg` launcher."""
    calls = []
    for name in WORKSTATION_TOOLS:
        async def spy(content, ctx, _name=name):
            calls.append(_name)
            return {"output": "RAN HERE", "exit_code": 0}
        monkeypatch.setitem(agent_tools.TOOL_HANDLERS, name, spy)
    from src import bg_jobs
    monkeypatch.setattr(bg_jobs, "launch", lambda *a, **k: calls.append("bg_jobs.launch") or {"id": "x"})
    return calls


@pytest.mark.parametrize("tool", sorted(WORKSTATION_TOOLS))
def test_a_down_workstation_is_a_sentence_and_nothing_runs_here(settings, people, host_spy,
                                                                  host_dir, tool):
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()            # a port with nobody on it
    settings.update({"workstation_enabled": True, "workstation_url": f"http://127.0.0.1:{port}",
                     "workstation_token": "pws_x"})
    marker = host_dir / "marker.txt"
    for owner in ("ann", "boss"):
        _, r = _call(tool, _probe(tool, marker), owner, workspace=str(host_dir))
        assert r["workstation_error"] == "unavailable" and r["exit_code"] == 1, r
        assert "did not answer" in r["error"] and "Is it running?" in r["error"]
        assert (r["ran_in"], r["ran_as"]) == ("workstation", account_for(owner))
    assert host_spy == [] and not marker.exists()


@pytest.mark.parametrize("tool", sorted(WORKSTATION_TOOLS))
def test_a_workstation_that_refuses_pantheon_is_a_sentence_too(ws, settings, people, host_spy,
                                                                  host_dir, tool):
    _on(settings, ws, workstation_token="pws_not-the-token")
    marker = host_dir / "marker.txt"
    _, r = _call(tool, _probe(tool, marker), "ann", workspace=str(host_dir))
    assert r["workstation_error"] == "unauthorized" and "refused Pantheon's token" in r["error"]
    assert host_spy == [] and not marker.exists()
    assert not _home(ws, "ann").exists()


@pytest.mark.parametrize("tool, args", [
    ("read_file", {"path": "proj/a.txt"}),
    ("write_file", {"path": "proj/a.txt", "content": "new"}),
    ("edit_file", {"path": "proj/a.txt", "old_string": "alpha", "new_string": "beta"}),
    ("apply_patch", "*** Begin Patch\n*** Update File: proj/a.txt\n@@\n-alpha\n+beta\n*** End Patch"),
])
def test_a_workstation_that_stops_answering_mid_call_is_a_sentence(ws, settings, people, host_spy,
                                                                     monkeypatch, tool, args):
    """Up for `ensure`, gone for the file: the failure is the workstation's, so
    the answer is `as_result()`, not a file error that hides it."""
    from src.workstation_client import WorkstationClient, WorkstationError
    home = _home(ws, "ann")
    (home / "proj").mkdir(parents=True)
    (home / "proj" / "a.txt").write_text("alpha\n")
    _on(settings, ws)

    async def gone(self, *a, **k):
        raise WorkstationError("unavailable", "The workstation stopped answering (ReadError).")

    monkeypatch.setattr(WorkstationClient, "read", gone)
    _, r = _call(tool, args, "ann")
    assert r == {"error": "The workstation stopped answering (ReadError).", "exit_code": 1,
                 "workstation_error": "unavailable", "ran_in": "workstation",
                 "ran_as": account_for("ann")}
    assert (home / "proj" / "a.txt").read_text() == "alpha\n" and host_spy == []


def test_the_lifted_set_is_the_nine_for_whoever_may_use_the_workstation(ws, settings, people):
    from src.agent_tools.workstation_tools import lifted_tools
    assert lifted_tools("ann") == frozenset()          # off
    _on(settings, ws)
    # `B985`: and `get_workspace`, which then answers about the same home.
    assert lifted_tools("ann") == WORKSTATION_TOOLS | {"get_workspace"} == lifted_tools("boss")
    assert lifted_tools("bob") == frozenset()
    settings["workstation_route_tools"] = False
    assert lifted_tools("ann") == frozenset()


def test_an_edit_of_a_file_that_is_not_text_is_refused_as_it_is_here(ws, settings, people, host_dir):
    blob = b"\x89PNG\r\n\x1a\n\xff\x00 alpha"
    (host_dir / "img.png").write_bytes(blob)
    home = _home(ws, "ann")
    home.mkdir(parents=True)
    (home / "img.png").write_bytes(blob)
    steps = [("edit_file", {"path": "img.png", "old_string": "alpha", "new_string": "beta"}),
             # `write_file` over it diffs from "", as here: unreadable as text is new.
             ("write_file", {"path": "img.png", "content": "text now\n"})]
    here = [_call(t, a, "boss", workspace=str(host_dir))[1] for t, a in steps]
    _on(settings, ws)
    edit = _call(*steps[0], "ann")[1]
    assert "not an editable text file" in edit["error"]
    assert (home / "img.png").read_bytes() == blob
    write = _call(*steps[1], "ann")[1]
    assert write["diff"]["new_file"] is True
    assert _norm([_without_where(edit), _without_where(write)], home) == _norm(here, host_dir)


def test_a_background_job_is_refused_there_with_what_to_do_instead(ws, settings, people, host_spy):
    _on(settings, ws)
    # Harmless on purpose: under a mutation that drops the refusal, this
    # really runs, as the user running the tests.
    _, r = _call("bash", "#!bg\necho ran > bg-ran.txt", "ann", session_id="s1")
    assert r["exit_code"] == 1 and r["ran_in"] == "workstation"
    assert "not started" in r["error"] and "without the #!bg line" in r["error"]
    assert "nohup" in r["error"]
    assert host_spy == [] and not _home(ws, "ann").exists()   # the daemon was not asked either
    # Without a session the marker is a comment, as here: the command runs.
    _, r = _call("bash", "#!bg\necho plain", "ann", session_id=None)
    assert r["stdout"] == "plain" and r["exit_code"] == 0


# ── off is today ─────────────────────────────────────────────────────────────


_OFF_CASES = [
    ("bash", "echo here; pwd"),
    ("python", "import os; print(os.getcwd())"),
    ("write_file", {"path": "w.txt", "content": "host\n"}),
    ("read_file", {"path": "w.txt"}),
    ("edit_file", {"path": "w.txt", "old_string": "host", "new_string": "HOST"}),
    ("apply_patch", "*** Begin Patch\n*** Add File: p.txt\n+x\n*** End Patch"),
    ("ls", {}),
    ("glob", {"pattern": "*.txt"}),
    ("grep", {"pattern": "HOST"}),
]


@pytest.mark.parametrize("switch", [
    {},                                                       # never turned on
    {"workstation_enabled": False},
    {"workstation_route_tools": False},                       # on, routing off by an admin
], ids=["unset", "off", "routing-off"])
def test_with_the_workstation_off_every_tool_runs_here_as_before(ws, settings, people, tmp_path,
                                                                 monkeypatch, switch):
    """`Law 1`: the dispatcher's answer is the host handler's answer, key for
    key, and the workstation hears nothing."""
    if "workstation_route_tools" in switch:
        _on(settings, ws)
    settings.update(switch)
    import src.auth_helpers
    for owner in ("boss", None):
        # `None` is the single-user owner: auth switched off by the operator.
        monkeypatch.setattr(src.auth_helpers, "_auth_disabled", lambda: owner is None)
        root = tmp_path / f"off-{owner}"
        root.mkdir()
        root = Path(os.path.realpath(root))
        for tool, args in _OFF_CASES:
            content = args if isinstance(args, str) else json.dumps(args)
            _, got = _call(tool, content, owner, workspace=str(root))
            # What the dispatcher calls for these tools: `_direct_fallback` —
            # with the chat since `B962`, so a shell keeps its folder.
            token = te._active_workspace.set(str(root))
            try:
                direct = asyncio.run(te._direct_fallback(tool, content, session_id="s1",
                                                         owner=owner))
            finally:
                te._active_workspace.reset(token)
            if tool in ("write_file", "edit_file", "apply_patch"):
                # A second run of a write is a different write; compare the
                # shape and that it landed here.
                assert set(got) == {"output", "exit_code", "diff"} and got["exit_code"] == 0
            else:
                assert got == direct, (tool, got, direct)
            assert "ran_in" not in got
    assert (tmp_path / "off-boss" / "w.txt").read_text() == "HOST\n"
    assert list(ws.root.iterdir()) == []


def test_a_non_admin_with_the_workstation_off_is_refused_exactly_as_before(ws, settings, people):
    for switch in ({}, {"workstation_enabled": False}):
        settings.clear()
        settings.update(switch)
        for tool in sorted(WORKSTATION_TOOLS):
            _, r = _call(tool, {"bash": "echo hi", "python": "print(1)"}.get(tool, "{}"), "ann")
            assert r["exit_code"] == 1 and r["error"].startswith(
                f"Tool '{tool}' is restricted to admin users on this deployment."), r
            assert "ran_in" not in r
    assert list(ws.root.iterdir()) == []


# ── who may: the dispatcher's gate ───────────────────────────────────────────


@pytest.mark.parametrize("owner, switch, where", [
    ("ann", {}, "workstation"),                                   # granted, on
    ("bob", {}, "refused"),                                       # not granted
    ("ann", {"workstation_route_tools": False}, "refused"),       # routing off: the old gate
    ("ann", {"workstation_enabled": False}, "refused"),
    ("boss", {}, "workstation"),                                  # an admin works there too
    ("boss", {"workstation_route_tools": False}, "here"),
], ids=["granted", "not-granted", "routing-off", "off", "admin-on", "admin-routing-off"])
@pytest.mark.parametrize("tool", sorted(WORKSTATION_TOOLS))
def test_the_privilege_matrix(ws, settings, people, host_dir, tool, owner, switch, where):
    _on(settings, ws, **switch)
    content = {"bash": "echo hi", "python": "print('hi')"}.get(tool, "{}")
    _, r = _call(tool, content, owner, workspace=str(host_dir))
    if where == "workstation":
        assert r["ran_in"] == "workstation" and r["ran_as"] == account_for(owner), r
    elif where == "refused":
        assert "ran_in" not in r and "restricted to admin users" in r["error"], r
    else:
        assert "ran_in" not in r, r


# `B985` lifted `get_workspace` with the nine (`test_get_workspace_is_lifted_with_the_nine.py`);
# nothing else is.
@pytest.mark.parametrize("tool", ["manage_bg_jobs", "host_shell", "api_call"])
def test_the_grant_lifts_the_nine_and_nothing_wider(ws, settings, people, tool):
    _on(settings, ws)
    _, r = _call(tool, "{}", "ann")
    assert "restricted to admin users" in r["error"] and "ran_in" not in r


# ── the agent loop: offered, run there, and the card told ───────────────────


def _loop(monkeypatch, reply, *, owner, delegated=False):
    import src.agent_loop as agent_loop
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    replies = iter([reply])

    async def fake_stream(*a, **k):
        yield f"data: {json.dumps({'delta': next(replies, 'Done.')})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "run it"}], max_rounds=2, owner=owner,
            session_id="s1", workspace=None, relevant_tools={"bash"},
            delegated_credential=delegated)]

    events = []
    for chunk in asyncio.run(drain()):
        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
            try:
                events.append(json.loads(chunk[6:]))
            except ValueError:
                pass
    return events


def test_a_person_with_the_workstation_is_offered_the_shell_and_the_card_says_where(
        ws, settings, people, monkeypatch):
    _on(settings, ws)
    events = _loop(monkeypatch, "```bash\necho \"$USER\"\n```", owner="ann")
    out = next(e for e in events if e.get("type") == "tool_output")
    assert out["output"] == account_for("ann") and out["exit_code"] == 0
    assert (out["ran_in"], out["ran_as"]) == ("workstation", account_for("ann"))
    saved = next(e for e in events if e.get("type") == "metrics")["data"]["tool_events"][0]
    assert (saved["ran_in"], saved["ran_as"]) == ("workstation", account_for("ann"))


def test_without_the_grant_the_shell_is_not_offered_and_nothing_runs_anywhere(
        ws, settings, people, monkeypatch, host_spy):
    _on(settings, ws)
    events = _loop(monkeypatch, "```bash\necho hi\n```", owner="bob")
    outs = [e for e in events if e.get("type") in ("tool_output", "tool_blocked")]
    assert all("ran_in" not in e for e in outs)
    assert host_spy == [] and list(ws.root.iterdir()) == []


def test_a_token_run_is_still_capped_even_for_a_person_with_the_grant(
        ws, settings, people, monkeypatch, host_spy):
    # `B70`: a bearer token is capped at the non-admin policy whoever holds the
    # grant; the workstation does not widen what a token may do.
    _on(settings, ws)
    events = _loop(monkeypatch, "```bash\necho hi\n```", owner="ann", delegated=True)
    assert all("ran_in" not in e for e in events if e.get("type") == "tool_output")
    assert host_spy == [] and list(ws.root.iterdir()) == []


def test_the_approved_replay_carries_where_it_ran_too(monkeypatch):
    """The replay the approval card resumes into is its own emit site
    (`test_tool_effect_wire.py`); a field on one path and not the other is the
    `P4-09` shape."""
    from test_tool_effect_wire import _approved_run, _first, _persisted
    events = _approved_run(monkeypatch, tool_name="bash", content="printf hi", results={
        "bash": {"output": "hi", "exit_code": 0, "ran_in": "workstation", "ran_as": "pw-ann-1"}})
    out = _first(events, "tool_output")
    assert (out["ran_in"], out["ran_as"]) == ("workstation", "pw-ann-1")
    saved = _persisted(events)[0]
    assert (saved["ran_in"], saved["ran_as"]) == ("workstation", "pw-ann-1")


# ── the chat route's gate ────────────────────────────────────────────────────


@pytest.mark.parametrize("privs, on, lifted", [
    ({"can_use_bash": False, "can_use_workstation": True}, True, True),
    ({"can_use_bash": False, "can_use_workstation": False}, True, False),
    ({"can_use_bash": False, "can_use_workstation": True}, False, False),
    ({"can_use_bash": True, "can_use_workstation": False}, False, True),   # as before
], ids=["granted-on", "not-granted", "granted-off", "bash-granted"])
@pytest.mark.asyncio
async def test_the_chat_route_lets_the_workstation_grant_stand_for_can_use_bash(
        ws, settings, monkeypatch, privs, on, lifted):
    import core.auth
    import routes.chat_routes as chat_routes
    import src.auth_helpers
    from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint

    captured: Dict[str, Any] = {}
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", captured)

    async def capturing_loop(endpoint_url, model, messages, **kwargs):
        captured["disabled"] = set(kwargs.get("disabled_tools") or ())
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat_routes, "stream_agent_loop", capturing_loop)
    # The route's harness answers every setting with its default; the
    # workstation's keys are answered here, over it.
    import src.settings as S
    base = S.get_setting
    values = {"workstation_enabled": on, "workstation_url": ws.url, "workstation_token": ws.token}
    monkeypatch.setattr(S, "get_setting", lambda k, d=None: values[k] if k in values else base(k, d))

    class _AliceAuth(_Auth):
        def is_admin(self, username):
            return False

        def get_privileges(self, username):
            return dict(privs)

    monkeypatch.setattr(src.auth_helpers, "_auth_disabled", lambda: False)
    monkeypatch.setattr(core.auth, "AuthManager", _AliceAuth)
    request = _RouteRequest("agent", privileges=dict(privs))
    request._form["compare_mode"] = "false"
    response = await endpoint(request)
    async for _ in response.body_iterator:
        pass
    four = {"bash", "python", "read_file", "write_file"}
    assert (four & captured["disabled"]) == (set() if lifted else four), captured["disabled"]


# ── the card ─────────────────────────────────────────────────────────────────


node_only = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
_JS = ROOT / "static" / "js"


@pytest.fixture(scope="module")
def card_sandbox(tmp_path_factory):
    from test_tool_effect_surfaces_js import _copy_unstubbed_imports
    from tests.helpers.esc_stub import ui_default_stub
    d = tmp_path_factory.mktemp("wherecard")
    (d / "ui.js").write_text(ui_default_stub("scrollHistory: () => {},"), encoding="utf-8")
    (d / "spinner.js").write_text("export default { create: () => ({}) };\n", encoding="utf-8")
    (d / "chatRenderer.js").write_text(
        "export function buildDiffHtml(d) { return d ? '<div class=\"agent-diff\">changed</div>' : ''; }\n"
        "export function buildTodoCard() { return ''; }\n"
        "export function demoteSupersededTodoCards() {}\n"
        "export function safeToolScreenshotSrc() { return ''; }\n", encoding="utf-8")
    for name in ("agentThread.js", "agentTurn.js"):
        shutil.copy(_JS / name, d / name)
    _copy_unstubbed_imports(d, _JS / "agentThread.js", {"ui.js"})
    return d


def _node(sandbox: Path, script: str):
    entry = sandbox / "case.mjs"
    entry.write_text(
        "const thread = await import('./agentThread.js');\n"
        "const turn = await import('./agentTurn.js');\n"
        "const node = () => { const n = { className: '', innerHTML: '', _q: {},\n"
        "  classList: { contains: (c) => n.className.split(' ').includes(c) },\n"
        "  querySelector: () => null }; return n; };\n"
        + textwrap.dedent(script), encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], cwd=sandbox, capture_output=True, text=True,
                          timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


def _badge(html: str) -> Optional[str]:
    import re
    m = re.search(r'<span class="agent-thread-where" title="([^"]*)">', html)
    return m.group(1) if m else None


@node_only
def test_a_card_that_ran_in_the_workstation_says_so(card_sandbox):
    out = _node(card_sandbox, """
        console.log(JSON.stringify({
          on: thread.agentThreadNodeHtml({ tool: 'bash', state: 'done', ok: true,
                                           ranIn: 'workstation', ranAs: 'pw-ann-1a2b3c4d' }),
          plain: thread.agentThreadNodeHtml({ tool: 'bash', state: 'done', ok: true }),
          noAccount: thread.agentThreadNodeHtml({ tool: 'bash', state: 'done', ok: true,
                                                  ranIn: 'workstation' }),
        }));
    """)
    assert _badge(out["on"]) == "Ran in the workstation, as pw-ann-1a2b3c4d"
    assert ">workstation</span>" in out["on"]
    assert _badge(out["noAccount"]) == "Ran in the workstation"
    assert _badge(out["plain"]) is None and "agent-thread-where" not in out["plain"]


@node_only
@pytest.mark.parametrize("value", [True, "Workstation", "host", 1, None, "", ["workstation"]])
def test_only_the_exact_claim_earns_the_label(card_sandbox, value):
    out = _node(card_sandbox, f"""
        console.log(JSON.stringify({{ html: thread.agentThreadNodeHtml({{
          tool: 'bash', state: 'done', ok: true, ranIn: {json.dumps(value)}, ranAs: 'pw-x' }}) }}));
    """)
    assert "agent-thread-where" not in out["html"]


@node_only
def test_the_account_cannot_write_into_the_card(card_sandbox):
    out = _node(card_sandbox, """
        console.log(JSON.stringify({ html: thread.agentThreadNodeHtml({ tool: 'bash',
          state: 'done', ok: true, ranIn: 'workstation',
          ranAs: '"><img src=x onerror=alert(1)>' }) }));
    """)
    assert "<img" not in out["html"] and "onerror=alert(1)>" not in out["html"]


@node_only
def test_the_live_result_card_draws_the_label_from_the_event(card_sandbox):
    """`agentTurn.finishToolCard` is what the live stream, a resumed stream and
    a compare pane all call with a `tool_output` event."""
    out = _node(card_sandbox, """
        const n = node();
        turn.finishToolCard(n, { type: 'tool_output', tool: 'bash', command: 'pwd',
          output: '/home/pw-ann', exit_code: 0, round: 1,
          ran_in: 'workstation', ran_as: 'pw-ann-1a2b3c4d' }, { scroll: null });
        const m = node();
        turn.finishToolCard(m, { type: 'tool_output', tool: 'bash', command: 'pwd',
          output: '/app/data', exit_code: 0, round: 1 }, { scroll: null });
        console.log(JSON.stringify({ there: n.innerHTML, here: m.innerHTML }));
    """)
    assert _badge(out["there"]) == "Ran in the workstation, as pw-ann-1a2b3c4d"
    assert _badge(out["here"]) is None


@node_only
def test_a_reloaded_card_still_says_where_it_ran(tmp_path_factory):
    from test_tool_effect_surfaces_js import _CARD_SHIM, _CARD_STUBS, _make_sandbox, _run
    sandbox = _make_sandbox(tmp_path_factory.mktemp("wherereload"), _JS / "chatRenderer.js",
                            _CARD_SHIM, _CARD_STUBS)
    events = [
        {"round": 1, "tool": "bash", "command": "pwd", "output": "/home/pw-ann", "exit_code": 0,
         "ran_in": "workstation", "ran_as": "pw-ann-1a2b3c4d"},
        {"round": 1, "tool": "bash", "command": "pwd", "output": "/app/data", "exit_code": 0},
    ]
    out = _run(sandbox, (
        "import { document, history, Node } from './shim.js';\n"
        "const { addMessage } = await import('./chatRenderer.js');\n"
    ), "history.childNodes = [];\n"
       "addMessage('assistant', 'Working on it.', 'test-model', "
       + json.dumps({"round_texts": ["Working on it."], "tool_events": events}) + ");\n"
       "const cards = history.querySelectorAll('.agent-thread-node');\n"
       "console.log(JSON.stringify({ cards: cards.map((c) => c.innerHTML) }));\n")
    assert len(out["cards"]) == 2
    assert _badge(out["cards"][0]) == "Ran in the workstation, as pw-ann-1a2b3c4d"
    assert _badge(out["cards"][1]) is None
