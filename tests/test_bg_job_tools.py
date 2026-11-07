# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for bg_jobs.kill and the manage_bg_jobs agent tool.

Process-free: the store/dir are redirected to tmp, _pid_alive is forced True so
seeded "running" jobs stay running through refresh(), _owned (`B1927`) says each
seeded pid is still its job, and _kill is stubbed so no real signal is sent.
Jobs are scoped to a chat (session_id), which is the main invariant under test.
One Linux case launches a real job, to prove _owned against the real system.
"""
import asyncio
import json
import os
import signal
import subprocess
import sys
import time

import pytest

from src import bg_jobs
from src.agent_tools.bg_job_tools import ManageBgJobsTool


@pytest.fixture
def store(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "bg_jobs"
    jobs_dir.mkdir()
    monkeypatch.setattr(bg_jobs, "_STORE", tmp_path / "bg_jobs.json")
    monkeypatch.setattr(bg_jobs, "_JOBS_DIR", jobs_dir)
    monkeypatch.setattr(bg_jobs, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(bg_jobs, "_owned", lambda rec: "owned")
    killed: list = []
    monkeypatch.setattr(bg_jobs, "_kill", lambda pid: killed.append(pid))
    return {"dir": jobs_dir, "killed": killed}


@pytest.fixture
def bare_store(tmp_path, monkeypatch):
    """The store in tmp and nothing else stood in for: `_owned`'s own cases."""
    jobs_dir = tmp_path / "bg_jobs"
    jobs_dir.mkdir()
    monkeypatch.setattr(bg_jobs, "_STORE", tmp_path / "bg_jobs.json")
    monkeypatch.setattr(bg_jobs, "_JOBS_DIR", jobs_dir)
    return jobs_dir


def _seed(session_id="sess-a", status="running", job_id="job0001", output="", pid=4321):
    rec = {
        "id": job_id, "session_id": session_id, "command": "sleep 60",
        "status": status, "pid": pid, "started_at": time.time(),
        "ended_at": None if status == "running" else time.time(),
        "exit_code": None if status == "running" else 0,
        "max_runtime_s": 3600, "followed_up": False,
        "log_path": str(bg_jobs._JOBS_DIR / f"{job_id}.log"),
        "exit_path": str(bg_jobs._JOBS_DIR / f"{job_id}.exit"),
    }
    if output:
        (bg_jobs._JOBS_DIR / f"{job_id}.log").write_text(output, encoding="utf-8")
    jobs = bg_jobs._load()
    jobs[job_id] = rec
    bg_jobs._save(jobs)
    return rec


def _run(args, session_id="sess-a"):
    return asyncio.run(ManageBgJobsTool().execute(json.dumps(args), {"session_id": session_id, "owner": None}))


# ── bg_jobs.kill ────────────────────────────────────────────────────────────

def test_kill_marks_killed_and_suppresses_followup(store):
    _seed(job_id="job0001", pid=4321)
    rec = bg_jobs.kill("job0001")
    assert rec["status"] == "failed"
    assert rec["killed"] is True
    assert rec["exit_code"] == -1
    # followed_up True so the monitor won't ALSO auto-continue a deliberate kill.
    assert rec["followed_up"] is True
    assert store["killed"] == [4321]


def test_kill_unknown_job_returns_none(store):
    assert bg_jobs.kill("nope") is None


def test_kill_finished_job_is_noop(store):
    _seed(job_id="done01", status="done")
    rec = bg_jobs.kill("done01")
    assert rec["status"] == "done"
    assert store["killed"] == []  # no signal sent to an already-finished job


def test_result_text_reports_killed(store):
    rec = _seed(job_id="job0001")
    bg_jobs.kill("job0001")
    assert "killed" in bg_jobs.result_text(bg_jobs.get("job0001")).lower()


# ── manage_bg_jobs tool ─────────────────────────────────────────────────────

def test_no_session_is_rejected(store):
    out = asyncio.run(ManageBgJobsTool().execute('{"action":"list"}', {"session_id": None}))
    assert "error" in out


def test_list_empty(store):
    assert "No background jobs" in _run({"action": "list"})["output"]


def test_list_scoped_to_session(store):
    _seed(session_id="sess-a", job_id="aaaa")
    _seed(session_id="sess-b", job_id="bbbb")
    out = _run({"action": "list"}, session_id="sess-a")["output"]
    assert "aaaa" in out and "bbbb" not in out


def test_output_returns_captured_log(store):
    _seed(job_id="job0001", output="hello from the job\n")
    out = _run({"action": "output", "job_id": "job0001"})["output"]
    assert "hello from the job" in out


def test_output_cross_session_denied(store):
    _seed(session_id="sess-a", job_id="job0001", output="secret")
    out = _run({"action": "output", "job_id": "job0001"}, session_id="sess-b")
    assert "error" in out and "secret" not in out.get("error", "")


def test_kill_via_tool(store):
    _seed(job_id="job0001", pid=999)
    out = _run({"action": "kill", "job_id": "job0001"})
    assert "Killed" in out["output"]
    assert store["killed"] == [999]
    assert bg_jobs.get("job0001")["killed"] is True


def test_kill_cross_session_denied(store):
    _seed(session_id="sess-a", job_id="job0001")
    out = _run({"action": "kill", "job_id": "job0001"}, session_id="sess-b")
    assert "error" in out
    assert store["killed"] == []  # never touched another chat's job


def test_kill_requires_job_id(store):
    assert "error" in _run({"action": "kill"})


def test_unknown_action(store):
    assert "error" in _run({"action": "frobnicate"})


def test_action_aliases(store):
    _seed(job_id="job0001", output="aliased")
    # 'read' aliases to output, 'jobs' to list, 'stop' to kill
    assert "aliased" in _run({"action": "read", "job_id": "job0001"})["output"]
    assert "job0001" in _run({"action": "jobs"})["output"]
    assert "Killed" in _run({"action": "stop", "job_id": "job0001"})["output"]


# ── `B1927`: a stored pid is signalled only while it is still the job ───────

def _past_its_hour(job_id, pid):
    _seed(job_id=job_id, pid=pid)
    jobs = bg_jobs._load()
    jobs[job_id]["started_at"] = time.time() - 2 * 3600
    bg_jobs._save(jobs)


def test_a_job_past_its_hour_is_reaped_only_while_its_pid_is_the_job(store, monkeypatch):
    """`B1927`. The store keeps a job's pid across restarts, and refresh()
    reaped a job past its max runtime by signalling that pid unchecked, from
    the monitor's first tick after boot. After a reboot or a container restart
    (which counts pids from 1 again) the number can belong to another program
    or to one of Pantheon's own threads. Now only a pid still running its job
    is signalled; the other job is closed as timed out with no signal, and the
    agent still hears back, told why."""
    _past_its_hour("mine01", 4321)
    _past_its_hour("reissued", 5555)
    monkeypatch.setattr(bg_jobs, "_owned",
                        lambda rec: "owned" if rec["id"] == "mine01" else "foreign")
    pending = {r["id"]: r for r in bg_jobs.pending_followups()}
    assert store["killed"] == [4321], "only the job's own pid is signalled"
    stale = pending["reissued"]
    assert (stale["status"], stale["timed_out"], stale["not_signalled"]) == ("failed", True, "foreign")
    assert "It was not signalled: its process id now belongs to another program." in (
        bg_jobs.result_text(stale))
    assert pending["mine01"]["timed_out"] is True and "not_signalled" not in pending["mine01"]


def test_kill_sends_nothing_to_a_pid_that_is_no_longer_the_job(store, monkeypatch):
    """`B1927`. `manage_bg_jobs` kill signalled the stored pid whatever now
    held it, and said "Killed" either way. Now that pid gets nothing, the job
    is closed, and the tool says it was not signalled, and why."""
    _seed(job_id="job0001", pid=4321)
    monkeypatch.setattr(bg_jobs, "_owned", lambda rec: "foreign")
    out = _run({"action": "kill", "job_id": "job0001"})
    assert store["killed"] == []
    assert out == {"output": "Job `job0001` was not signalled: its process id now belongs "
                             "to another program.", "exit_code": 0}
    rec = bg_jobs.get("job0001")
    assert (rec["status"], rec["not_signalled"], rec["followed_up"]) == ("failed", "foreign", True)
    assert not rec.get("killed")


def test_kill_leaves_a_job_it_cannot_identify_running_and_says_so(store, monkeypatch):
    """`B1927`. A Windows job started before this check kept no start time,
    so nothing proves its pid is still the job. It is not signalled, and not
    closed either: it may still be running, and closing it would lose its
    result. The tool says it could not stop it."""
    _seed(job_id="job0001", pid=4321)
    monkeypatch.setattr(bg_jobs, "_owned", lambda rec: "unverifiable")
    out = _run({"action": "kill", "job_id": "job0001"})
    assert store["killed"] == [] and out["exit_code"] == 1
    assert out["error"].startswith("Job `job0001` was not signalled: Pantheon cannot confirm")
    assert "may still be running" in out["error"]
    assert bg_jobs.get("job0001")["status"] == "running"


def test_on_windows_the_start_time_kept_at_launch_decides(bare_store, monkeypatch):
    """`B1927`. Windows hands a pid out again quickly and has no /proc, so
    `launch` keeps when the job's process started (`process_start_token`) and
    `_owned` compares it before a signal. A record from before this has none,
    so nothing can prove it is still the job."""
    monkeypatch.setattr(bg_jobs, "IS_WINDOWS", True)
    monkeypatch.setattr(bg_jobs, "process_start_token", {4321: "T1"}.get)
    monkeypatch.setattr(bg_jobs, "_pid_alive", lambda pid: pid == 4321)
    job = {"id": "job0001", "pid": 4321, "start_token": "T1"}
    assert bg_jobs._owned(job) == "owned"
    assert bg_jobs._owned({**job, "start_token": "T0"}) == "foreign", "the pid was handed out again"
    assert bg_jobs._owned({**job, "pid": 999}) == "gone"
    assert bg_jobs._owned({"id": "job0001", "pid": 4321}) == "unverifiable"


def _ends(pid, within=10.0):
    """Whether the child `pid` ends within `within` seconds (it is reaped)."""
    deadline = time.time() + within
    while time.time() < deadline:
        try:
            done, _status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return True      # reaped already, by subprocess's own clean-up
        if done:
            return True
        time.sleep(0.05)
    return False


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc")
def test_a_launched_job_is_its_own_and_another_pid_is_not(bare_store, monkeypatch):
    """`B1927`, on the real system. `launch` starts the job's wrapper as
    ``bash <jobs dir>/<id>.sh``, so its command line names the job, with
    nothing new kept for it on POSIX; the start time `launch` keeps for
    Windows rides along. This test's own process is `foreign`, a pid nobody
    holds is `gone`, and `kill` still stops the job for real."""
    monkeypatch.setattr(bg_jobs, "process_start_token", lambda pid: f"T{pid}")
    rec = bg_jobs.launch("sleep 30", "sess-a")
    pid = rec["pid"]
    try:
        assert rec["start_token"] == f"T{pid}"
        assert bg_jobs._owned(rec) == "owned"
        assert bg_jobs._owned({**rec, "id": "0123456789ab"}) == "foreign", "another job's id"
        assert bg_jobs._owned({**rec, "pid": os.getpid()}) == "foreign"
        ended = subprocess.Popen(["true"])
        ended.wait()
        assert bg_jobs._owned({**rec, "pid": ended.pid}) == "gone"
        assert bg_jobs.kill(rec["id"])["killed"] is True
        assert _ends(pid), "the job's wrapper did not stop"
    finally:
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        _ends(pid, within=2.0)


# ── intent classifier: short bg-job commands must not be dropped as low-signal ─
# A short imperative ("kill that job") otherwise trips the low-signal gate, which
# skips tool retrieval entirely and never surfaces manage_bg_jobs (the live bug
# this feature hit). These lock in that bg-job control reaches the files domain.


@pytest.mark.parametrize("msg", [
    "stop the job",
    "kill that job",
    "Now kill that background job.",
    "is the job done?",
    "check the job output",
    "list my jobs",
    "kill the bg task",
])
def test_bg_job_commands_are_not_low_signal(msg):
    from src.agent_loop import _classify_agent_request, _DOMAIN_TOOL_MAP
    r = _classify_agent_request([{"role": "user", "content": msg}], msg)
    assert r["low_signal"] is False
    assert "files" in r["domains"]
    # files domain seeds manage_bg_jobs, so it gets offered to the model.
    assert "manage_bg_jobs" in _DOMAIN_TOOL_MAP["files"]


@pytest.mark.parametrize("msg", [
    "run this in the background",   # launching, not managing
    "find me a job listing",        # unrelated use of "job"
])
def test_non_bg_messages_do_not_trip_files_domain(msg):
    from src.agent_loop import _classify_agent_request
    r = _classify_agent_request([{"role": "user", "content": msg}], msg)
    assert "files" not in r["domains"]
