# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B442` — the deploy sequence lived in a chat transcript, and step 4 was "wait".

The six commands were `git push`, `docker compose build`, `docker compose up
-d`, wait, a hand-written Python probe inside the container, and
`docker compose logs | grep -ci traceback`. Hand-run five times on 2026-09-17,
and twice the wait was too short: the app binds 7000 35-60 s after `up -d`
returns, a probe at 25 s answered `Connection refused` on every route, and the
deploy was believed to have failed when it had not.

`scripts/pantheon-deploy` is that sequence as an artifact. **There is no Docker
daemon in the environment it was written in** (`/var/run/docker.sock` is absent;
`docker` is on PATH and fails), so nothing here runs a container. What these
tests drive is everything around the daemon: the wait's state machine, the
verdict, the byte comparison, the traceback counting, the argument handling and
every failure path — with one fake standing in for the Docker CLI and recording
what it was asked.

What is therefore **unrun and only reasoned** is the exact behaviour of the
`docker` invocations themselves: that `docker inspect --format
'{{.State.Health.Status}}'` prints `<no value>` with no healthcheck, that
`docker compose exec -T` forwards stdin, that `docker tag` accepts an image id.
Those are stated in the script's comments and are not evidence from this file.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from tests.helpers.cli_loader import load_script  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def pd():
    return load_script("pantheon-deploy")


# ─────────────────────────────────────────────────────────────────────────────
# The stand-in for the Docker CLI.

class FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class FakeDocker:
    """Answers `docker ...` from a table, and records every call.

    `health` is consumed one entry per `inspect --format={{.State.Health.Status}}`
    so a test can script `starting, starting, healthy` and assert the wait
    polled rather than slept.
    """

    def __init__(self, health=("healthy",), state="running", cid="c0ffee",
                 probe=None, logs="", rc=None, image_ref="odysseus-pantheon"):
        self.health = list(health)
        self.state = state
        self.cid = cid
        self.probe = probe if probe is not None else _clean_probe()
        self.logs = logs
        self.rc = rc or {}
        self.image_ref = image_ref
        self.calls = []
        self.stdin_seen = []
        self.slept = []

    def run(self, args, capture=True, timeout=None, stdin=None):
        self.calls.append(list(args))
        if stdin is not None:
            self.stdin_seen.append(stdin)
        joined = " ".join(args)
        for key, proc in self.rc.items():
            if key in joined:
                return proc
        if args[:2] == ["compose", "ps"]:
            return FakeProc(stdout=self.cid)
        if args[0] == "inspect" and "State.Health.Status" in joined:
            value = self.health.pop(0) if len(self.health) > 1 else self.health[0]
            return FakeProc(stdout=value)
        if args[0] == "inspect" and "State.Status" in joined:
            return FakeProc(stdout=self.state)
        if args[0] == "inspect" and "State.StartedAt" in joined:
            return FakeProc(stdout="2026-09-17T14:00:00Z")
        if args[0] == "inspect" and "Config.Image" in joined:
            return FakeProc(stdout=self.image_ref)
        if args[0] == "inspect" and ".Image}}" in joined:
            return FakeProc(stdout="sha256:deadbeef")
        if args[0] in ("tag", "image"):
            return FakeProc(stdout="sha256:deadbeef")
        if args[:2] == ["compose", "exec"]:
            return FakeProc(stdout="PANTHEON_PROBE=" + json.dumps(self.probe) + "\n")
        if args[:2] == ["compose", "logs"]:
            return FakeProc(stdout=self.logs)
        return FakeProc()

    def compose(self, args, **kw):
        return self.run(["compose", *args], **kw)


def _clean_probe(manifest=None):
    manifest = manifest or {}
    return {
        "routes": [{"path": "/api/health", "expected": [200], "status": 200,
                    "ok": True, "why": ""}],
        "mcp": [{"module": m, "ok": True, "error": ""} for m in
                ("email_server", "image_gen_server", "memory_server", "rag_server")],
        "bytes": manifest,
    }


# ─────────────────────────────────────────────────────────────────────────────
# The wait. This is the defect the script exists to fix.

def test_waiting_polls_until_healthy_instead_of_sleeping_a_fixed_time(pd):
    docker = FakeDocker(health=["starting", "starting", "starting", "healthy"])
    ticks = []
    clock = iter([0, 5, 10, 15, 20, 25]).__next__
    waited = pd.wait_for_healthy(docker, timeout=300, poll=5,
                                 sleeper=ticks.append, clock=clock)
    assert waited == 20, "returns how long it actually waited, not a constant"
    assert ticks == [5, 5, 5], "polled three times; a fixed sleep would poll none"


def test_waiting_returns_immediately_when_the_container_is_already_healthy(pd):
    docker = FakeDocker(health=["healthy"])
    ticks = []
    assert pd.wait_for_healthy(docker, timeout=300, poll=5, sleeper=ticks.append,
                               clock=iter([0, 0]).__next__) == 0
    assert ticks == []


def test_a_service_with_no_healthcheck_is_an_error_and_not_an_infinite_wait(pd):
    """The state of `docker-compose.yml` before `B440`.

    `docker inspect` prints `<no value>` when there is no healthcheck at all,
    and treating that as "not healthy yet" is a script that waits out its
    timeout on a container that is fine.
    """
    docker = FakeDocker(health=["<no value>"])
    with pytest.raises(pd.DeployError) as e:
        pd.wait_for_healthy(docker, timeout=30, poll=1, sleeper=lambda _: None,
                            clock=iter([0, 1]).__next__)
    assert "no healthcheck" in str(e.value)


def test_an_unhealthy_container_fails_the_deploy_rather_than_timing_out(pd):
    docker = FakeDocker(health=["starting", "unhealthy"])
    with pytest.raises(pd.DeployError) as e:
        pd.wait_for_healthy(docker, timeout=300, poll=1, sleeper=lambda _: None,
                            clock=iter([0, 1, 2, 3]).__next__)
    assert "unhealthy" in str(e.value)


def test_a_container_that_exited_during_startup_is_not_waited_for(pd):
    docker = FakeDocker(health=["starting"], state="exited")
    with pytest.raises(pd.DeployError) as e:
        pd.wait_for_healthy(docker, timeout=300, poll=1, sleeper=lambda _: None,
                            clock=iter([0, 1, 2]).__next__)
    assert "exited" in str(e.value)


def test_no_container_at_all_names_the_command_that_should_have_made_one(pd):
    docker = FakeDocker(cid="")
    with pytest.raises(pd.DeployError) as e:
        pd.wait_for_healthy(docker, timeout=30, poll=1, sleeper=lambda _: None)
    assert "up -d" in str(e.value)


def test_the_wait_gives_up_and_says_how_long_it_waited(pd):
    docker = FakeDocker(health=["starting"])
    with pytest.raises(pd.DeployError) as e:
        pd.wait_for_healthy(docker, timeout=10, poll=1, sleeper=lambda _: None,
                            clock=iter([0, 4, 8, 12]).__next__)
    assert "--timeout" in str(e.value) and "12s" in str(e.value)


# ─────────────────────────────────────────────────────────────────────────────
# The verdict.

def _report(**over):
    base = {
        "routes": [{"path": "/api/health", "expected": [200], "status": 200, "ok": True}],
        "mcp": [{"module": m, "ok": True, "error": ""} for m in
                ("email_server", "image_gen_server", "memory_server", "rag_server")],
        "tracebacks": [],
        "log_lines": 120,
        "bytes_compared": {"matched": ["app.py"], "mismatched": [], "missing": []},
    }
    base.update(over)
    return base


def test_a_clean_report_passes(pd):
    assert pd.verdict(_report())["ok"] is True


def test_a_refused_route_fails_and_says_which(pd):
    """The exact symptom of probing inside the 35-60 s window."""
    v = pd.verdict(_report(routes=[
        {"path": "/api/health", "expected": [200], "status": 0, "ok": False}]))
    assert v["ok"] is False
    row = next(r for r in v["rows"] if r["name"] == "routes")
    assert "connection refused" in row["lines"][0]


def test_a_route_that_answers_the_login_page_fails(pd):
    v = pd.verdict(_report(routes=[
        {"path": "/login", "expected": [200], "status": 302, "ok": False}]))
    assert v["ok"] is False


def test_an_mcp_server_that_cannot_import_fails_the_deploy(pd):
    """`B131`'s outage, which nothing else in this repository sees at deploy
    time: the servers are spawned as fresh interpreters and every test imports
    them into a process that already loaded `src.agent_tools`."""
    mcp = [{"module": m, "ok": True, "error": ""} for m in
           ("email_server", "image_gen_server", "memory_server")]
    mcp.append({"module": "rag_server", "ok": False,
                "error": "ImportError: cannot import name 'FUNCTION_TOOL_SCHEMAS'"})
    v = pd.verdict(_report(mcp=mcp))
    assert v["ok"] is False
    row = next(r for r in v["rows"] if r["name"] == "mcp servers")
    assert "rag_server" in row["lines"][0] and "FUNCTION_TOOL_SCHEMAS" in row["lines"][0]


def test_finding_fewer_than_four_mcp_servers_fails_rather_than_passing_empty(pd):
    """A check that passes by finding nothing is the failure mode `B360` was
    caught by rather than the one it was looking for."""
    assert pd.verdict(_report(mcp=[]))["ok"] is False
    assert pd.verdict(_report(mcp=[{"module": "rag_server", "ok": True, "error": ""}]))["ok"] is False


def test_a_traceback_in_the_boot_log_fails_the_deploy(pd):
    v = pd.verdict(_report(tracebacks=["ValueError: no such table: crew_members"]))
    assert v["ok"] is False
    assert "1 traceback" in next(r for r in v["rows"] if r["name"] == "startup log")["detail"]


def test_allow_tracebacks_is_a_ratchet_and_not_a_switch(pd):
    assert pd.verdict(_report(tracebacks=["a"]), allow_tracebacks=1)["ok"] is True
    assert pd.verdict(_report(tracebacks=["a", "b"]), allow_tracebacks=1)["ok"] is False


def test_bytes_that_do_not_match_the_repository_fail_the_deploy(pd):
    """`B362`. The deployment host built the image from CRLF-translated copies
    of twelve vendored bundles and `git status` printed nothing."""
    v = pd.verdict(_report(bytes_compared={
        "matched": ["app.py"], "missing": [],
        "mismatched": [("static/lib/docx.umd.min.js", 762974, "aaaabbbbcccc")]}))
    assert v["ok"] is False
    assert "docx.umd.min.js" in next(r for r in v["rows"] if r["name"] == "shipped bytes")["lines"][0]


def test_a_file_missing_from_the_image_fails_the_deploy(pd):
    v = pd.verdict(_report(bytes_compared={
        "matched": ["app.py"], "mismatched": [], "missing": ["static/js/theme.js"]}))
    assert v["ok"] is False


def test_an_empty_byte_comparison_does_not_pass_by_finding_nothing(pd):
    assert pd.verdict(_report(bytes_compared={
        "matched": [], "mismatched": [], "missing": []}))["ok"] is False


# ─────────────────────────────────────────────────────────────────────────────
# The byte comparison itself.

def test_a_declared_crlf_conversion_is_not_drift(pd):
    """`B361` measured exactly three files that legitimately differ from their
    blob — `*.ps1` and `*.bat`, which `.gitattributes` says are checked out
    `eol=crlf` because PowerShell and cmd run them. Flagging those would make
    this check cry wolf on every Windows deploy."""
    manifest = {"launch-windows.ps1": {"blob": "abc123", "eol": "crlf"}}
    actual = {"launch-windows.ps1": {"bytes": 6000, "blob": "zzz999", "blob_lf": "abc123"}}
    out = pd.compare_bytes(manifest, actual)
    assert out["matched"] == ["launch-windows.ps1"] and not out["mismatched"]


def test_an_undeclared_difference_is_drift_even_on_a_file_that_may_convert(pd):
    manifest = {"launch-windows.ps1": {"blob": "abc123", "eol": "crlf"}}
    actual = {"launch-windows.ps1": {"bytes": 9, "blob": "zzz999", "blob_lf": "yyy888"}}
    assert pd.compare_bytes(manifest, actual)["mismatched"]


def test_a_file_the_image_does_not_have_is_reported_missing_not_matched(pd):
    out = pd.compare_bytes({"app.py": {"blob": "a", "eol": "unspecified"}}, {})
    assert out["missing"] == ["app.py"] and not out["matched"]


def test_the_manifest_is_the_bytes_git_has(pd):
    """Not a fixture: the real index of this worktree, hashed the way git does."""
    manifest = pd.build_manifest()
    assert len(manifest) > 500, f"only {len(manifest)} files — this is not the tree"
    assert "app.py" in manifest and "static/lib/docx.umd.min.js" in manifest
    assert pd.blob_id((ROOT / "app.py").read_bytes()) == manifest["app.py"]["blob"]
    for path in ("build-windows-portable.ps1", "launch-windows.ps1", "update_windows.bat"):
        assert manifest[path]["eol"] == "crlf", (
            f"{path} no longer resolves eol=crlf; `B361` says it should")


def test_the_manifest_leaves_out_what_the_image_does_not_carry(pd):
    listing = "\n".join([
        "100644 aaa 0\tsrc/keep.py",
        "100644 bbb 0\tsrc/notes.md",
        "100644 ccc 0\tsrc/app.log",
        "100644 ddd 0\tdata/app.db",
        "100644 eee 0\tservices/node_modules/x/index.js",
        "160000 fff 0\tvendor/submodule",
    ])
    assert [p for p, _ in pd.manifest_paths(listing)] == ["src/keep.py"]


# ─────────────────────────────────────────────────────────────────────────────
# The boot log.

def test_tracebacks_are_counted_by_their_marker_and_not_by_the_word(pd):
    """The hand-run step was `docker compose logs | grep -ci traceback`, which
    counts this sentence."""
    log = (
        "INFO traceback logging is enabled\n"
        "INFO see the Traceback section of the runbook\n"
        'Traceback (most recent call last):\n'
        '  File "/app/app.py", line 1, in <module>\n'
        "RuntimeError: boom\n"
    )
    assert pd.tracebacks_in(log) == ["RuntimeError: boom"]


def test_a_boot_log_with_no_traceback_counts_none(pd):
    assert pd.tracebacks_in("Application startup complete\nUvicorn running\n") == []


def test_two_tracebacks_are_two(pd):
    one = 'Traceback (most recent call last):\n  File "a", line 1\nKeyError: x\n'
    assert len(pd.tracebacks_in(one + one)) == 2


# ─────────────────────────────────────────────────────────────────────────────
# The probe's own plumbing.

def test_a_probe_that_printed_nothing_is_an_error_and_not_an_empty_pass(pd):
    with pytest.raises(pd.DeployError) as e:
        pd.parse_probe_output("bash: python: command not found\n")
    assert "printed no result" in str(e.value)


def test_the_manifest_reaches_the_container_on_stdin(pd):
    """`docker compose exec -T` is the only way in; a probe with no manifest
    checks no bytes and passes."""
    docker = FakeDocker()
    pd.run_probe(docker, {"app.py": {"blob": "abc", "eol": "unspecified"}})
    assert docker.stdin_seen, "nothing was written to the probe's stdin"
    assert json.loads(docker.stdin_seen[0])["manifest"]["app.py"]["blob"] == "abc"
    exec_call = next(c for c in docker.calls if c[:2] == ["compose", "exec"])
    assert "-T" in exec_call and exec_call[-1] == "probe"


def test_the_probe_reads_a_manifest_and_hashes_what_it_finds(pd, tmp_path, capsys, monkeypatch):
    """The in-container half, run here against a tree standing in for `/app`."""
    (tmp_path / "mcp_servers").mkdir()
    (tmp_path / "mcp_servers" / "toy_server.py").write_text("x = 1\n")
    (tmp_path / "app.py").write_text("print('hi')\n")
    manifest = {"app.py": {"blob": pd.blob_id(b"print('hi')\n"), "eol": "unspecified"},
                "gone.py": {"blob": "0" * 40, "eol": "unspecified"}}
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(
        json.dumps({"manifest": manifest})))
    monkeypatch.setattr(pd, "_probe_routes", lambda routes: [])
    args = type("A", (), {"app_root": str(tmp_path)})()
    pd.cmd_probe(args)
    report = pd.parse_probe_output(capsys.readouterr().out)
    assert report["bytes"]["app.py"]["blob"] == manifest["app.py"]["blob"]
    assert "gone.py" not in report["bytes"]
    assert [m["module"] for m in report["mcp"]] == ["toy_server"]
    assert report["mcp"][0]["ok"] is True
    out = pd.compare_bytes(manifest, report["bytes"])
    assert out["matched"] == ["app.py"] and out["missing"] == ["gone.py"]


def test_the_probe_reports_a_server_that_cannot_import(pd, tmp_path, capsys, monkeypatch):
    (tmp_path / "mcp_servers").mkdir()
    (tmp_path / "mcp_servers" / "broken_server.py").write_text(
        "raise ImportError('cannot import name FUNCTION_TOOL_SCHEMAS')\n")
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("{}"))
    monkeypatch.setattr(pd, "_probe_routes", lambda routes: [])
    pd.cmd_probe(type("A", (), {"app_root": str(tmp_path)})())
    report = pd.parse_probe_output(capsys.readouterr().out)
    assert report["mcp"][0]["ok"] is False
    assert "FUNCTION_TOOL_SCHEMAS" in report["mcp"][0]["error"]


# ─────────────────────────────────────────────────────────────────────────────
# `run`, end to end, with the daemon faked.

def _run(pd, monkeypatch, docker, argv):
    monkeypatch.setattr(pd, "Docker", lambda *a, **kw: docker)
    monkeypatch.setattr(pd.time, "sleep", lambda _s: None)
    return pd.main(argv)


def test_run_exits_zero_when_everything_passed(pd, monkeypatch, capsys):
    manifest = pd.build_manifest()
    actual = {p: {"bytes": 1, "blob": v["blob"]} for p, v in manifest.items()}
    docker = FakeDocker(probe=_clean_probe(actual), logs="Application startup complete\n")
    assert _run(pd, monkeypatch, docker, ["run", "--no-build"]) == 0
    assert "deploy ok" in capsys.readouterr().out


def test_run_exits_non_zero_when_the_build_failed(pd, monkeypatch):
    docker = FakeDocker(rc={"compose build": FakeProc(returncode=2)})
    with pytest.raises(SystemExit) as e:
        _run(pd, monkeypatch, docker, ["run"])
    assert e.value.code == 1


def test_run_exits_non_zero_when_up_failed(pd, monkeypatch):
    docker = FakeDocker(rc={"compose up": FakeProc(returncode=1)})
    with pytest.raises(SystemExit) as e:
        _run(pd, monkeypatch, docker, ["run", "--no-build"])
    assert e.value.code == 1


def test_run_exits_non_zero_when_the_container_never_became_healthy(pd, monkeypatch):
    docker = FakeDocker(health=["starting"])
    with pytest.raises(SystemExit) as e:
        _run(pd, monkeypatch, docker, ["run", "--no-build", "--timeout", "0"])
    assert e.value.code == 1


def test_run_exits_non_zero_when_the_verification_failed(pd, monkeypatch, capsys):
    """The case the old sequence could not produce at all: the container is
    healthy, and the deploy is still wrong."""
    probe = _clean_probe({})
    probe["mcp"][0] = {"module": "rag_server", "ok": False, "error": "ImportError: x"}
    docker = FakeDocker(probe=probe, logs="ok\n")
    with pytest.raises(SystemExit) as e:
        _run(pd, monkeypatch, docker, ["run", "--no-build"])
    assert e.value.code == 1
    out = capsys.readouterr().out
    assert "deploy FAILED" in out and "rollback" in out


def test_a_failed_deploy_does_not_roll_back_by_itself(pd, monkeypatch, capsys):
    """Deliberate. `core/database.py` migrates forward on every startup and
    `_migrate_encrypt_email_passwords` rewrites rows the older image cannot
    read, so an automatic rollback can leave a worse state than the failure it
    was recovering from. The script names the one command instead."""
    docker = FakeDocker(probe=_clean_probe({}), logs="ok\n")
    with pytest.raises(SystemExit):
        _run(pd, monkeypatch, docker, ["run", "--no-build"])
    assert not any(c[:2] == ["compose", "up"] and "--no-build" in c
                   for c in docker.calls[docker.calls.index(["compose", "up", "-d", "pantheon"]) + 1:])
    assert "pantheon-deploy rollback" in capsys.readouterr().out


def test_run_parks_the_outgoing_image_before_it_builds(pd, monkeypatch):
    """Rollback needs a handle on the image compose is about to replace, and
    after the build the derived tag points at the new one."""
    manifest = pd.build_manifest()
    docker = FakeDocker(probe=_clean_probe(
        {p: {"bytes": 1, "blob": v["blob"]} for p, v in manifest.items()}), logs="")
    _run(pd, monkeypatch, docker, ["run", "--no-build"])
    tags = [c for c in docker.calls if c[0] == "tag"]
    assert tags and tags[0][1:] == ["sha256:deadbeef", pd.PREVIOUS_TAG]


def test_rollback_refuses_when_there_is_no_previous_image(pd, monkeypatch, capsys):
    docker = FakeDocker(rc={"image inspect": FakeProc(returncode=1, stdout="")})
    with pytest.raises(SystemExit):
        _run(pd, monkeypatch, docker, ["rollback"])
    assert "no image tagged" in capsys.readouterr().err


def test_rollback_retags_the_previous_image_onto_what_compose_runs(pd, monkeypatch):
    manifest = pd.build_manifest()
    docker = FakeDocker(probe=_clean_probe(
        {p: {"bytes": 1, "blob": v["blob"]} for p, v in manifest.items()}), logs="")
    assert _run(pd, monkeypatch, docker, ["rollback"]) == 0
    assert ["tag", pd.PREVIOUS_TAG, "odysseus-pantheon"] in docker.calls
    up = next(c for c in docker.calls if c[:3] == ["compose", "up", "-d"])
    assert "--no-build" in up, "a rollback that rebuilds is not a rollback"


def test_verify_does_not_build_or_restart_anything(pd, monkeypatch):
    manifest = pd.build_manifest()
    docker = FakeDocker(probe=_clean_probe(
        {p: {"bytes": 1, "blob": v["blob"]} for p, v in manifest.items()}), logs="")
    assert _run(pd, monkeypatch, docker, ["verify"]) == 0
    assert not [c for c in docker.calls if c[:2] in (["compose", "build"], ["compose", "up"])]


def test_the_boot_log_is_read_from_this_container_start(pd, monkeypatch):
    """`verify` on a container that has been up for a week must not count a
    traceback from Tuesday against today's deploy."""
    manifest = pd.build_manifest()
    docker = FakeDocker(probe=_clean_probe(
        {p: {"bytes": 1, "blob": v["blob"]} for p, v in manifest.items()}), logs="")
    _run(pd, monkeypatch, docker, ["verify"])
    logs = next(c for c in docker.calls if c[:2] == ["compose", "logs"])
    assert "--since" in logs and "2026-09-17T14:00:00Z" in logs


# ─────────────────────────────────────────────────────────────────────────────
# Arguments, and the other entry points.

def test_an_unknown_subcommand_is_refused(pd):
    with pytest.raises(SystemExit) as e:
        pd.main(["deploooy"])
    assert e.value.code != 0


def test_a_subcommand_is_required(pd):
    with pytest.raises(SystemExit) as e:
        pd.main([])
    assert e.value.code != 0


def test_version_answers_without_a_subcommand(pd, capsys):
    assert pd.main(["--version"]) == 0
    assert "pantheon-deploy" in capsys.readouterr().out


def test_timeout_is_a_number_the_operator_can_set(pd, monkeypatch):
    seen = {}
    manifest = pd.build_manifest()
    docker = FakeDocker(probe=_clean_probe(
        {p: {"bytes": 1, "blob": v["blob"]} for p, v in manifest.items()}), logs="")
    real = pd.wait_for_healthy
    monkeypatch.setattr(pd, "wait_for_healthy",
                        lambda d, s=pd.SERVICE, timeout=300.0, **kw: seen.setdefault("t", timeout) or 1.0)
    _run(pd, monkeypatch, docker, ["run", "--no-build", "--timeout", "45"])
    assert seen["t"] == 45.0
    assert real is not None


def test_the_umbrella_cli_finds_it(pd):
    """`Law 13`. `scripts/pantheon` dispatches to `pantheon-<name>` the way git
    finds `git-foo`, and `scripts/_completion/pantheon.bash` completes whatever
    it finds. A deploy tool that only exists as a path is a second way to do
    the thing, discoverable by nobody."""
    script = ROOT / "scripts" / "pantheon-deploy"
    import os
    assert script.exists() and os.access(script, os.X_OK), (
        "scripts/pantheon must be able to exec it, and it lists only executables")
    dispatcher = load_script("pantheon")
    names = [p.name for p in dispatcher._list_subcommands()]
    assert "pantheon-deploy" in names
    assert dispatcher._short_help(script).startswith("build, restart and verify")


def test_nothing_in_this_script_reaches_off_this_host(pd):
    """`Law 16`. The build pulls its base image; the script itself must talk
    only to the local Docker socket, the local git repository and 127.0.0.1."""
    import re
    source = (ROOT / "scripts" / "pantheon-deploy").read_text(encoding="utf-8")
    code = "\n".join(l for l in source.splitlines() if not l.lstrip().startswith("#"))
    code = re.sub(r'"""(?:.|\n)*?"""', "", code)
    urls = re.findall(r"https?://[^\s\"')]+", code)
    assert urls == ["http://127.0.0.1:7000"], f"unexpected destinations: {urls}"
