# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_backend_status_treats_download_exit_zero_as_completed():
    source = _read("routes/cookbook_routes.py")

    assert "exit_match = re.search(r\"=== process exited with code\\s+(-?\\d+)\"" in source
    assert "elif has_exit and task_type == \"download\":" in source
    assert "status = \"completed\" if exit_code == 0 else \"error\"" in source


def test_background_status_poll_reconciles_into_local_tasks():
    source = _read("static/js/cookbookRunning.js")

    assert "const statusById = new Map(tasks.map(t => [t.session_id, t]));" in source
    assert "const completedByOutput = depDone || downloadDone;" in source
    assert "const nextStatus = completedByOutput" in source
    assert "live.status === 'completed'" in source
    assert "? 'done'" in source
    assert ": (live.status === 'error'" in source
    assert "? 'error'" in source
    assert "_saveTasks(localTasks);" in source
    assert "completedDeps.forEach(t => _refreshDepsAfterInstall(t));" in source


def test_windows_session_commands_use_shared_powershell_wrapper_and_local_log_dir():
    source = _read("static/js/cookbookRunning.js")

    assert "const host = task.remoteHost;" in source
    assert "host ? '$env:TEMP\\\\pantheon-sessions' : '$env:TEMP\\\\pantheon-tmux'" in source
    assert "function _winPowerShellCmd(task, ps)" in source
    assert "const command = `powershell -Command \"${ps}\"`;" in source
    assert "if (!host) return command;" in source
    assert "return `ssh ${_sshPrefix(_getPort(task))}${host} ${_shQuote(command)}`;" in source


def test_dep_install_success_recognized_from_exit_sentinel():
    """A pip dependency install reports success via the runner's exit-0
    sentinel / pip's "Successfully installed" line, not the HuggingFace
    download markers. The shared helper must key off those, so an install
    whose tmux pane is gone isn't misread as crashed."""
    source = _read("static/js/cookbookRunning.js")

    assert "function _depInstallSucceeded(output) {" in source
    assert "=== Process exited with code" in source
    assert "Successfully installed" in source


def test_session_gone_heuristic_honors_dep_install_success():
    """The reconnect loop's session-gone branch (download tasks need an HF
    marker to look successful) must also accept a finished dependency install,
    otherwise a clean pip install with no HF markers is marked crashed."""
    source = _read("static/js/cookbookRunning.js")

    assert "const depInstallSucceeded = !!task.payload?._dep && _depInstallSucceeded(lastOutput);" in source
    # Whitespace-normalized so the check survives line-wrapping/formatting while
    # still proving the invariant: a finished dependency install short-circuits
    # looksSuccessful ahead of the download/serve branch.
    normalized = " ".join(source.split())
    assert (
        "const looksSuccessful = depInstallSucceeded "
        "|| (task.type === 'download'"
    ) in normalized


def test_background_poll_recovers_done_for_stopped_dependency_install():
    """When the backend reports a finished dependency install as "stopped"
    (its pip package is never in the HF cache the dead-session check inspects),
    the reconciler must recover "done" from the retained output instead of
    downgrading the card to crashed."""
    source = _read("static/js/cookbookRunning.js")

    assert "const combinedOutput = `${task.output || ''}\\n${live.output_tail || ''}`;" in source
    assert "const depDone = !!task.payload?._dep && _depInstallSucceeded(combinedOutput);" in source
    assert "(depDone || downloadDone) ? 'done' : (task.type === 'download' ? 'crashed' : 'stopped')" in source


def test_background_poll_recovers_done_for_completed_download():
    """When the backend reports a finished model download as "stopped" (its
    tmux pane is gone after DOWNLOAD_OK, so the dead-session check can miss the
    landed snapshot), the reconciler must recover "done" from the terminal
    DOWNLOAD_OK sentinel instead of downgrading the card to crashed. The
    background poll keys off DOWNLOAD_OK only (not the "/snapshots/" path, which
    can appear mid-stream for multi-file downloads)."""
    source = _read("static/js/cookbookRunning.js")

    normalized = " ".join(source.split())
    assert (
        "const downloadDone = task.type === 'download' "
        "&& String(combinedOutput || '').includes('DOWNLOAD_OK');"
    ) in normalized


def test_dependency_install_payload_keeps_env_path_for_refresh():
    source = _read("static/js/cookbook.js")

    assert "env_path: targetEnvPath || ''" in source


def test_local_dependency_probe_refreshes_user_site_visibility():
    source = _read("routes/shell_routes.py")

    assert "importlib.invalidate_caches()" in source
    assert "user_site = site.getusersitepackages()" in source
    # addsitedir (not a bare sys.path.append) so user-site `.pth` hooks are
    # replayed when a package is installed into an already-running process —
    # otherwise setuptools' distutils shim never activates and basicsr-based
    # deps (realesrgan) probe as not-installed until a restart. See #4810.
    assert "if user_site and os.path.isdir(user_site):" in source
    assert "site.addsitedir(user_site)" in source


# ── B1931: a llama-server shim the Forge wrote never outlives what it stood in for ──
#
# When the native llama.cpp build failed and llama-cpp-python imported, the
# runner wrote ~/bin/llama-server, a shim that runs `python3 -m
# llama_cpp.server`, and never looked at it again. ~/bin is ahead of Homebrew
# and the system on the runner's PATH, and the build, the pip fallback and the
# shim itself all waited behind `command -v llama-server`. So the shim shadowed
# any native llama-server installed after it, and once the bindings stopped
# importing, every launch died inside it; only Dependencies -> Rebuild removed
# it. The runner now asks which llama-server answers before it decides anything
# (`_pantheon_resolve_llama_server`, routes/cookbook_helpers.py).
#
# The runner tests run the script /api/model/serve writes, in bash, under a
# temporary HOME whose ~/.local/bin, first on the runner's PATH, holds
# stand-ins: a python3 that imports llama_cpp.server only once the stand-in pip
# has "installed" it, and git, cmake, curl and nvidia-smi that fail, so nothing
# is built, installed or fetched. The other tests run the shell functions the
# runner is given on their own.

_needs_bash = pytest.mark.skipif(
    os.name == "nt" or not shutil.which("bash"), reason="the runner is a bash script",
)
_runs_the_linux_runner = pytest.mark.skipif(
    not sys.platform.startswith("linux") or not shutil.which("bash"),
    reason="drives the runner the Forge writes for a Linux host",
)

# Every name the shim has carried: Odysseus's, then Pantheon's before and
# after the Cookbook became the Forge. The test files may spell them out; the
# shipped code recognises the shim without doing so.
_SHIM_NAMES = ("Odysseus Cookbook", "Pantheon Cookbook", "Pantheon Forge")
_BINDINGS = ".stand-in-llama-cpp-python"  # under HOME, once the stand-in pip ran


def _write_script(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/bash\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _write_forge_shim(path: Path, name: str = "Pantheon Forge") -> None:
    """The shim as a runner wrote it under `name`: its opening lines, which
    are the same under every name but for the name, and a plain body."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/usr/bin/env bash\n"
        f"# Auto-generated by {name}: a `llama-server` lookalike\n"
        "# that translates the native CLI to `python -m llama_cpp.server`.\n"
        "# Lets cookbook-generated launch commands run unchanged on hosts\n"
        "# where only the pip llama-cpp-python package is installed.\n"
        'exec python3 -m llama_cpp.server "$@"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_native(path: Path, *, works: bool = True) -> None:
    """A native llama-server that answers --version and serves, or one whose
    libraries are gone."""
    if works:
        _write_script(path, (
            'if [ "$1" = --version ]; then echo "version: 1 (stand-in)"; exit 0; fi\n'
            f'echo "RUN_NATIVE {path}: $*"\n'
        ))
    else:
        _write_script(path, 'echo "error while loading shared libraries: libllama.so" >&2; exit 127\n')


def _stand_ins(home: Path, *, bindings: bool) -> Path:
    """~/.local/bin under `home`, holding the stand-ins; returns it."""
    tools = home / ".local" / "bin"
    marker = f'"$HOME/{_BINDINGS}"'
    _write_script(tools / "python3", (
        'case "$*" in\n'
        f'  "-c "*llama_cpp*) [ -e {marker} ] ;;\n'
        f'  "-m llama_cpp.server"*) [ -e {marker} ] || {{ echo "No module named llama_cpp" >&2; exit 1; }}\n'
        '    shift 2; echo "RUN_PYTHON_SERVER: $*" ;;\n'
        '  *) echo "the stand-in python3 was not expecting: $*" >&2; exit 2 ;;\n'
        'esac\n'
    ))
    _write_script(tools / "pip", f'touch {marker}; echo "STAND_IN_PIP: $*"\n')
    for name in ("git", "cmake", "curl", "nvidia-smi", "gcc", "g++", "sudo", "lspci"):
        _write_script(tools / name, f'echo "stand-in {name}: not here" >&2; exit 1\n')
    if bindings:
        (home / _BINDINGS).touch()
    return tools


def _bash(home: Path, lines: list[str], *, path: str, cwd: Path | None = None):
    return subprocess.run(
        [shutil.which("bash"), "-c", "\n".join(lines)],
        cwd=str(cwd or home), env={"HOME": str(home), "PATH": path, "LANG": "C.UTF-8"},
        stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace", timeout=60,
    )


def _resolver_lines(*, launches_binary: bool = True) -> list[str]:
    """What the runner runs before it decides whether to build: the shell
    functions, then the resolution, then what it chose."""
    from routes.cookbook_helpers import _append_llama_server_shim_reconciliation_lines

    lines: list[str] = []
    _append_llama_server_shim_reconciliation_lines(lines, launches_binary=launches_binary)
    lines.append('echo "RESOLVED=$_pantheon_llama_bin"')
    return lines


def _finalization_lines(*, launches_binary: bool = True) -> list[str]:
    """The resolution, then what the runner runs once the build and the pip
    fallback have had their turn."""
    from routes.cookbook_helpers import (
        _append_llama_server_finalization_lines,
        _append_llama_server_shim_reconciliation_lines,
    )

    lines = ['PANTHEON_PREFLIGHT_EXIT=""']
    _append_llama_server_shim_reconciliation_lines(lines, launches_binary=launches_binary)
    _append_llama_server_finalization_lines(lines)
    lines.append('echo "EXIT=$PANTHEON_PREFLIGHT_EXIT RESOLVED=$_pantheon_llama_bin"')
    return lines


def _create_shim_lines() -> list[str]:
    from routes.cookbook_helpers import _append_llama_server_shim_definition_lines

    lines: list[str] = []
    _append_llama_server_shim_definition_lines(lines)
    lines.append("_pantheon_create_llama_shim")
    return lines


@pytest.fixture
def forge_runner(tmp_path, monkeypatch):
    """`run(cmd)` writes the runner /api/model/serve writes for `cmd` (the
    real route; only the tmux launch is stopped) and runs it in bash under
    `run.home`. Returns the script and everything it printed."""
    import routes.cookbook_routes as cookbook_routes
    from routes.cookbook_helpers import ServeRequest
    from starlette.requests import Request

    seen = shutil.which("llama-server", path=os.pathsep.join(
        ["/opt/homebrew/bin", "/usr/local/bin", os.path.dirname(sys.executable), "/usr/bin", "/bin"]))
    if seen:
        pytest.skip(f"this machine's own llama-server ({seen}) is on the runner's PATH")

    runners = tmp_path / "runners"
    monkeypatch.setattr(cookbook_routes, "TMUX_LOG_DIR", runners)
    monkeypatch.setattr(cookbook_routes, "COOKBOOK_STATE_FILE", str(tmp_path / "cookbook_state.json"))
    monkeypatch.setattr(cookbook_routes, "require_admin", lambda request: None)
    monkeypatch.setattr(cookbook_routes, "require_operator", lambda request: None)
    monkeypatch.setattr(cookbook_routes, "load_stored_hf_token", lambda **kwargs: "")

    async def _available(*args, **kwargs):
        return True

    class _Stderr:
        async def read(self):
            return b"launch stopped by the test"

    class _Stopped:
        returncode = 1
        stderr = _Stderr()

        async def wait(self):
            return 1

    async def _launch(command, **kwargs):
        return _Stopped()

    monkeypatch.setattr(cookbook_routes, "_binary_available", _available)
    monkeypatch.setattr(cookbook_routes.asyncio, "create_subprocess_shell", _launch)
    serve = next(route.endpoint for route in cookbook_routes.setup_cookbook_routes().routes
                 if route.path == "/api/model/serve" and "POST" in route.methods)
    home = tmp_path / "home"
    home.mkdir()

    def run(cmd: str):
        request = Request({"type": "http", "method": "POST", "path": "/api/model/serve", "headers": [], "state": {}})
        request.state.current_user = "admin"
        out = asyncio.run(serve(request, ServeRequest(repo_id="test/repo", cmd=cmd)))
        runner = runners / f"{out['session_id']}_run.sh"
        script = runner.read_text(encoding="utf-8").replace("/tmp/pantheon-tmux", str(tmp_path / "pane"))
        runner.write_text(script, encoding="utf-8")
        done = subprocess.run(
            [shutil.which("bash"), str(runner)],
            env={"HOME": str(home), "PATH": "/usr/bin:/bin", "SHELL": shutil.which("true"), "LANG": "C.UTF-8"},
            stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace", timeout=120,
        )
        return script, done.stdout + done.stderr

    run.home = home
    return run


@_runs_the_linux_runner
@pytest.mark.parametrize("name", _SHIM_NAMES)
def test_a_shim_under_any_of_the_forges_names_gives_way_to_a_native_llama_server_installed_after_it(forge_runner, name):
    home = forge_runner.home
    _stand_ins(home, bindings=True)
    shim = home / "bin" / "llama-server"
    _write_forge_shim(shim, name)
    native = home / "llama.cpp" / "build" / "bin" / "llama-server"
    _write_native(native)

    script, out = forge_runner("llama-server -m /dummy/model.gguf --port 8085")

    assert f"RUN_NATIVE {native}: -m /dummy/model.gguf --port 8085" in out, out
    assert "RUN_PYTHON_SERVER" not in out
    assert not shim.exists()
    assert "building from source" not in out
    # Settled before the runner decides whether this host needs a build.
    assert (script.index("_pantheon_resolve_llama_server || true")
            < script.index("if [ -d /data/data/com.termux ]; then")
            < script.index('elif [ -z "$_pantheon_llama_bin" ]; then'))


@_runs_the_linux_runner
def test_a_shim_whose_bindings_are_gone_is_removed_and_the_same_launch_installs_them_and_writes_a_new_one(forge_runner):
    home = forge_runner.home
    _stand_ins(home, bindings=False)
    shim = home / "bin" / "llama-server"
    _write_forge_shim(shim, "Pantheon Cookbook")

    _, out = forge_runner("llama-server -m /dummy/model.gguf --port 8085")

    assert "No module named llama_cpp" not in out, out
    assert "Removing the Forge's stale llama-server shim" in out
    assert "building from source" in out
    assert "installing Python bindings as fallback" in out and "STAND_IN_PIP: install" in out
    assert "Created llama-server shim" in out
    assert "RUN_PYTHON_SERVER: -m /dummy/model.gguf --port 8085" in out
    assert "=== Process exited with code 0 ===" in out
    assert shim.read_text(encoding="utf-8").splitlines()[1] == "# Auto-generated by Pantheon Forge: a `llama-server` lookalike"


@_runs_the_linux_runner
def test_a_broken_llama_server_early_on_path_does_not_hide_a_working_one_later(forge_runner):
    home = forge_runner.home
    _stand_ins(home, bindings=False)
    _write_native(home / ".local" / "bin" / "llama-server", works=False)
    native = home / "llama.cpp" / "build" / "bin" / "llama-server"
    _write_native(native)

    _, out = forge_runner("llama-server -m /dummy/model.gguf --port 8085")

    assert f"RUN_NATIVE {native}: -m /dummy/model.gguf --port 8085" in out, out
    assert "libllama.so" not in out
    assert "building from source" not in out


@_runs_the_linux_runner
def test_a_python_launch_behind_a_stale_shim_installs_its_bindings_and_keeps_its_python3(forge_runner):
    home = forge_runner.home
    _stand_ins(home, bindings=False)
    _write_forge_shim(home / "bin" / "llama-server")
    # ~/bin is behind ~/.local/bin on the runner's PATH. A runner that put the
    # directory of the llama-server it settled on first would launch this
    # python3 instead of the one the command has always had.
    _write_script(home / "bin" / "python3", 'echo "WRONG_PYTHON3: $*"\n')

    _, out = forge_runner("python3 -m llama_cpp.server --model /dummy/model.gguf --port 8086")

    assert "installing Python bindings as fallback" in out, out
    assert "RUN_PYTHON_SERVER: --model /dummy/model.gguf --port 8086" in out
    assert "WRONG_PYTHON3" not in out


@_needs_bash
def test_the_shim_is_never_written_over_a_file_of_the_users(tmp_path):
    users = tmp_path / "bin" / "llama-server"
    users.parent.mkdir(parents=True)
    users.write_text("a file of the user's, not a script\n", encoding="utf-8")

    res = _bash(tmp_path, _create_shim_lines(), path="/usr/bin:/bin")

    assert res.returncode != 0
    assert users.read_text(encoding="utf-8") == "a file of the user's, not a script\n"
    assert "is not a llama-server shim the Forge wrote" in res.stderr


@_needs_bash
@pytest.mark.parametrize("dangling", [False, True], ids=["to-a-file-of-theirs", "dangling"])
def test_the_shim_is_never_written_through_a_symlink_of_the_users(tmp_path, dangling):
    theirs = tmp_path / "theirs.txt"
    if not dangling:
        theirs.write_text("precious\n", encoding="utf-8")
    link = tmp_path / "bin" / "llama-server"
    link.parent.mkdir(parents=True)
    link.symlink_to(theirs)

    res = _bash(tmp_path, _create_shim_lines(), path="/usr/bin:/bin")

    assert res.returncode != 0
    assert link.is_symlink() and os.readlink(link) == str(theirs)
    if dangling:
        assert not theirs.exists()
    else:
        assert theirs.read_text(encoding="utf-8") == "precious\n"


@_needs_bash
@pytest.mark.parametrize("name", _SHIM_NAMES)
def test_the_shim_replaces_one_the_forge_wrote_under_any_of_its_names(tmp_path, name):
    shim = tmp_path / "bin" / "llama-server"
    _write_forge_shim(shim, name)

    res = _bash(tmp_path, _create_shim_lines(), path="/usr/bin:/bin")

    assert res.returncode == 0, res.stderr
    text = shim.read_text(encoding="utf-8")
    assert text.splitlines()[1] == "# Auto-generated by Pantheon Forge: a `llama-server` lookalike"
    assert 'exec python3 -m llama_cpp.server "${ARGS[@]}"' in text
    assert os.access(shim, os.X_OK)


@_needs_bash
def test_the_shim_is_written_through_a_private_temporary_file(tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("DO_NOT_TOUCH\n", encoding="utf-8")
    # A predictable temporary name, planted as a symlink, is not followed.
    lines = ['mkdir -p "$HOME/bin"', 'ln -s "$HOME/victim" "$HOME/bin/.llama-server.pantheon.tmp.$$"'] + _create_shim_lines()

    res = _bash(tmp_path, lines, path="/usr/bin:/bin")

    assert res.returncode == 0, res.stderr
    assert victim.read_text(encoding="utf-8") == "DO_NOT_TOUCH\n"
    shim = tmp_path / "bin" / "llama-server"
    assert not shim.is_symlink() and "Auto-generated by Pantheon Forge" in shim.read_text(encoding="utf-8")
    assert os.access(shim, os.X_OK)


@_needs_bash
@pytest.mark.parametrize("shape", [*_SHIM_NAMES, "another second line", "another third line", "a symlink to a shim"])
def test_only_a_file_that_opens_like_the_forges_shim_is_taken_for_one(tmp_path, shape):
    tools = _stand_ins(tmp_path, bindings=False)  # a shim of the Forge's would be removed
    target = tmp_path / "bin" / "llama-server"
    if shape == "a symlink to a shim":
        _write_forge_shim(tmp_path / "elsewhere" / "llama-server")
        target.parent.mkdir(parents=True)
        target.symlink_to(tmp_path / "elsewhere" / "llama-server")
    else:
        _write_forge_shim(target, shape if shape in _SHIM_NAMES else "Pantheon Forge")
    if shape == "another second line":
        target.write_text(target.read_text(encoding="utf-8").replace(
            "Auto-generated by Pantheon Forge", "Written by hand"), encoding="utf-8")
    elif shape == "another third line":
        target.write_text(target.read_text(encoding="utf-8").replace(
            "translates the native CLI to", "does something else than"), encoding="utf-8")
    before = target.read_bytes()

    res = _bash(tmp_path, _resolver_lines(), path=f"{tmp_path / 'bin'}:{tools}:/usr/bin:/bin")

    if shape in _SHIM_NAMES:
        assert not target.exists(), res.stdout
        assert "Removing the Forge's stale llama-server shim" in res.stdout
    else:
        assert target.is_symlink() == (shape == "a symlink to a shim")
        assert target.read_bytes() == before
        assert "stale llama-server shim" not in res.stdout


@_needs_bash
def test_a_working_shim_stays_while_nothing_native_answers(tmp_path):
    tools = _stand_ins(tmp_path, bindings=True)
    shim = tmp_path / "bin" / "llama-server"
    _write_forge_shim(shim)
    broken = tmp_path / "llama.cpp" / "build" / "bin" / "llama-server"
    _write_native(broken, works=False)

    res = _bash(tmp_path, _resolver_lines() + ["command -v llama-server"],
                path=f"{tmp_path / 'bin'}:{broken.parent}:{tools}:/usr/bin:/bin")

    assert shim.exists()
    assert f"RESOLVED={shim}" in res.stdout
    assert res.stdout.rstrip().endswith(str(shim))


@_needs_bash
@pytest.mark.parametrize("where", ["llama.cpp/build/bin", "opt/custom/bin", "custom[dir]/bin", "a path with spaces/bin"])
def test_a_working_native_llama_server_anywhere_on_path_retires_the_shim_and_is_what_runs(tmp_path, where):
    tools = _stand_ins(tmp_path, bindings=True)  # the shim itself still works
    shim = tmp_path / "bin" / "llama-server"
    _write_forge_shim(shim)
    native = tmp_path / where / "llama-server"
    _write_native(native)
    (tmp_path / "customd" / "bin").mkdir(parents=True)  # what `custom[dir]` would glob to
    model = tmp_path / "models with spaces" / "my model.gguf"
    model.parent.mkdir()
    model.write_text("gguf", encoding="utf-8")

    res = _bash(tmp_path, _resolver_lines() + [f'llama-server -m "{model}" --port 8080'],
                path=f"{tmp_path / 'bin'}:{native.parent}:{tools}:/usr/bin:/bin")

    assert not shim.exists()
    assert f"RESOLVED={native}" in res.stdout
    assert f"RUN_NATIVE {native}: -m {model} --port 8080" in res.stdout


@_needs_bash
@pytest.mark.parametrize("case", ["off-path", "in-the-working-directory", "bin-with-a-trailing-slash"])
def test_a_llama_server_the_path_does_not_name_is_not_taken_for_a_native_one(tmp_path, case):
    tools = _stand_ins(tmp_path, bindings=True)
    shim = tmp_path / "bin" / "llama-server"
    _write_forge_shim(shim)
    work = tmp_path / "work"
    work.mkdir()
    if case == "off-path":
        _write_native(tmp_path / "not-on-path" / "llama-server")
    elif case == "in-the-working-directory":
        _write_native(work / "llama-server")
    bin_entry = f"{tmp_path / 'bin'}/" if case == "bin-with-a-trailing-slash" else str(tmp_path / "bin")

    res = _bash(tmp_path, _resolver_lines(), path=f"{bin_entry}:{tools}:/usr/bin:/bin", cwd=work)

    assert shim.exists()
    assert f"RESOLVED={shim}\n" in res.stdout


@_needs_bash
@pytest.mark.parametrize("native_later", [True, False], ids=["with-a-native-one-later-on-path", "alone"])
def test_a_llama_server_in_bin_the_forge_did_not_write_is_never_removed(tmp_path, native_later):
    tools = _stand_ins(tmp_path, bindings=False)
    users = tmp_path / "bin" / "llama-server"
    _write_script(users, '# my own wrapper\nexec /opt/custom/llama-server "$@"\n')
    content = users.read_bytes()
    native = tmp_path / "llama.cpp" / "build" / "bin" / "llama-server"
    if native_later:
        _write_native(native)

    res = _bash(tmp_path, _resolver_lines(), path=f"{tmp_path / 'bin'}:{native.parent}:{tools}:/usr/bin:/bin")

    assert users.read_bytes() == content
    if native_later:
        assert f"RESOLVED={native}" in res.stdout
    else:
        # Nothing else answers: it is launched as it is, as it was before, and
        # no build is started that would link over it.
        assert f"RESOLVED={users}" in res.stdout
        assert "launching it as it is" in res.stdout


@_needs_bash
def test_a_lookup_bash_cached_before_the_shim_was_retired_does_not_outlive_it(tmp_path):
    tools = _stand_ins(tmp_path, bindings=True)
    shim = tmp_path / "bin" / "llama-server"
    _write_forge_shim(shim)
    native = tmp_path / "native" / "llama-server"
    _write_native(native)
    lines = ["llama-server --warm-the-cache >/dev/null 2>&1 || true", "hash"]
    lines += _resolver_lines() + ["llama-server -m /m.gguf"]

    res = _bash(tmp_path, lines, path=f"{tmp_path / 'bin'}:{native.parent}:{tools}:/usr/bin:/bin")

    assert str(shim) in res.stdout  # what bash had cached
    assert not shim.exists()
    assert f"RUN_NATIVE {native}: -m /m.gguf" in res.stdout, res.stdout + res.stderr


@_needs_bash
def test_a_llama_server_whose_version_never_answers_is_given_ten_seconds(tmp_path):
    real_timeout = shutil.which("timeout")
    if not real_timeout:
        pytest.skip("no timeout(1) on this machine")
    tools = _stand_ins(tmp_path, bindings=False)
    hangs = tmp_path / "hangs" / "llama-server"
    _write_script(hangs, 'if [ "$1" = --version ]; then exec sleep 120; fi\necho "RUN_HANGING: $*"\n')
    native = tmp_path / "works" / "llama-server"
    _write_native(native)
    # The runner's timeout(1), with the limit it was given written down and
    # cut to a second, so the test does not wait the ten.
    _write_script(tools / "timeout", f'echo "$1" >> "$HOME/limits"\nshift\nexec {real_timeout} 1 "$@"\n')

    res = _bash(tmp_path, _resolver_lines() + ["llama-server -m /m.gguf"],
                path=f"{hangs.parent}:{tools}:{native.parent}:/usr/bin:/bin")

    assert f"RESOLVED={native}" in res.stdout
    assert f"RUN_NATIVE {native}: -m /m.gguf" in res.stdout
    assert set((tmp_path / "limits").read_text(encoding="utf-8").split()) == {"10"}


@_needs_bash
def test_a_python_launch_keeps_its_path_and_its_python3(tmp_path):
    tools = _stand_ins(tmp_path, bindings=True)
    broken = tmp_path / "broken" / "llama-server"
    _write_native(broken, works=False)
    # A distribution's llama.cpp: its llama-server sits beside a python3 of the
    # distribution's own, which is not the one the launch runs.
    distro = tmp_path / "usr" / "bin"
    _write_native(distro / "llama-server")
    _write_script(distro / "python3", 'echo "WRONG_PYTHON3: $*"\n')
    path = f"{broken.parent}:{tools}:{distro}:/usr/bin:/bin"
    show = ['echo "PATH=$PATH"', 'echo "PYTHON3=$(command -v python3)"', 'echo "LLAMA=$(command -v llama-server)"']

    python = _bash(tmp_path, _resolver_lines(launches_binary=False) + show, path=path)
    binary = _bash(tmp_path, _resolver_lines(launches_binary=True) + show, path=path)

    assert f"RESOLVED={distro}/llama-server" in python.stdout
    assert f"PATH={path}\n" in python.stdout
    assert f"PYTHON3={tools}/python3\n" in python.stdout
    # A launch of the binary has the working llama-server win over the broken one.
    assert f"LLAMA={distro}/llama-server\n" in binary.stdout


@_needs_bash
def test_once_the_bindings_import_the_launch_that_installed_them_gets_a_working_shim(tmp_path):
    tools = _stand_ins(tmp_path, bindings=True)
    shim = tmp_path / "bin" / "llama-server"
    lines = _finalization_lines() + ["command -v llama-server", "llama-server -m /m.gguf -c 4096 -ngl 99"]

    res = _bash(tmp_path, lines, path=f"{tmp_path / 'bin'}:{tools}:/usr/bin:/bin")

    assert shim.read_text(encoding="utf-8").splitlines()[1] == "# Auto-generated by Pantheon Forge: a `llama-server` lookalike"
    assert f"EXIT= RESOLVED={shim}\n{shim}\n" in res.stdout
    assert "RUN_PYTHON_SERVER: -m /m.gguf --n_ctx 4096 --n_gpu_layers 99" in res.stdout


@_needs_bash
@pytest.mark.parametrize("broken_native", [False, True], ids=["nothing-at-all", "only-a-broken-native-one"])
def test_with_nothing_that_can_serve_a_llama_server_launch_stops_with_127(tmp_path, broken_native):
    tools = _stand_ins(tmp_path, bindings=False)
    broken = tmp_path / "broken" / "llama-server"
    if broken_native:
        _write_native(broken, works=False)

    res = _bash(tmp_path, _finalization_lines(), path=f"{tmp_path / 'bin'}:{broken.parent}:{tools}:/usr/bin:/bin")

    assert "EXIT=127 RESOLVED=\n" in res.stdout
    assert "llama.cpp serving is not available after install/build attempts" in res.stdout
    assert not (tmp_path / "bin" / "llama-server").exists()


@_needs_bash
@pytest.mark.parametrize("bindings", [True, False], ids=["bindings-import", "bindings-do-not-import"])
def test_a_python_launch_is_stopped_only_when_its_bindings_do_not_import(tmp_path, bindings):
    tools = _stand_ins(tmp_path, bindings=bindings)
    # A dangling symlink of the user's where the shim would go: no shim can be
    # written, and `python3 -m llama_cpp.server` does not need one.
    link = tmp_path / "bin" / "llama-server"
    link.parent.mkdir(parents=True)
    link.symlink_to(tmp_path / "gone")

    res = _bash(tmp_path, _finalization_lines(launches_binary=False), path=f"{tmp_path / 'bin'}:{tools}:/usr/bin:/bin")

    assert link.is_symlink() and not (tmp_path / "gone").exists()
    assert ("EXIT= RESOLVED=\n" if bindings else "EXIT=127 RESOLVED=\n") in res.stdout


def test_every_readiness_check_asks_for_llama_cpp_server_and_the_gpu_check_still_reads_llama_cpp():
    """A shim runs `python3 -m llama_cpp.server`, which the bare bindings do
    not provide without the [server] extra, so that is what each check asks
    for. Whether the installed wheel offloads to a GPU is a question about
    `llama_cpp` itself and stays one."""
    routes_source = _read("routes/cookbook_routes.py")
    helpers_source = _read("routes/cookbook_helpers.py")

    assert 'try { python -c "import llama_cpp.server" 2>$null } catch {}' in routes_source  # Windows
    assert 'if ! python3 -c "import llama_cpp.server" 2>/dev/null; then' in routes_source  # Termux
    assert 'if [ -z "$_pantheon_llama_bin" ] && ! python3 -c "import llama_cpp.server" 2>/dev/null; then' in routes_source
    assert 'elif python3 -c "import llama_cpp.server" 2>/dev/null; then' in helpers_source
    assert 'if [ -z "$_pantheon_llama_bin" ] && python3 -c "import llama_cpp.server" 2>/dev/null; then' in helpers_source
    assert "llama_cpp.llama_supports_gpu_offload()" in routes_source
