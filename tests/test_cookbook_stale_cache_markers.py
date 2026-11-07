# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1932` — an empty retry marker beside a finished blob no longer keeps its
model "downloading".

A Hugging Face client downloads a blob into a `.incomplete` file beside its
final name in the cache's blobs folder; older clients used one shared name for
it, `<etag>.incomplete`. A download that stopped before its first byte leaves
that marker empty, and when another client or process finishes the blob later,
the empty marker stays behind beside it. Every Forge reading of a Hugging Face
cache took the marker at its word: the Cached list's scanner
(`_cached_model_scan_script`) reported the model `has_incomplete`, so it read
"downloading", offered Resume and no Serve, and both dead-session probes
(`HF_CACHE_COMPLETE_PROBE`, `HF_CACHE_INCOMPLETE_PROBE`) called the download
unfinished. The scanner reads the host's shared caches, which other tools and
other environments write too.

Now an `.incomplete` entry counts unless it is empty and its blob, the same
name without `.incomplete`, is a file with something in it. Everything else
counts as it did: a marker with bytes in it, an empty marker alone (a download
that has not had its first byte), an empty marker beside an empty blob, and
the per-process `<etag>.<8 hex>.incomplete` a newer client writes, whose
leftovers beside a finished blob are a question of their own.

Driven: the generated scanner and both probes run as the child Pythons the
Forge runs, against a cache in a directory with spaces, reached the three ways
the Forge reaches one (a task's download directory, `HF_HOME`,
`HUGGINGFACE_HUB_CACHE`). Nothing in the cache is written. Ported from upstream
Odysseus 2b310010 (#6930).
"""
from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from routes.cookbook_helpers import _cached_model_scan_script
from routes.cookbook_output import HF_CACHE_COMPLETE_PROBE, HF_CACHE_INCOMPLETE_PROBE

_BLOB = b"finished model data"

# What each model's blobs folder holds. Only the first two are finished.
_BLOBS = {
    "complete": {"sha": _BLOB},
    "stale-marker": {"sha": _BLOB, "sha.incomplete": b""},
    "marker-alone": {"sha.incomplete": b""},
    "partial": {"sha.incomplete": b"partial"},
    "partial-beside-its-blob": {"sha": _BLOB, "sha.incomplete": b"partial"},
    "marker-beside-an-empty-blob": {"sha": b"", "sha.incomplete": b""},
    "empty-process-temp-beside-its-blob": {"sha": _BLOB, "sha.0123abcd.incomplete": b""},
    "process-temp-beside-its-blob": {"sha": _BLOB, "sha.0123abcd.incomplete": b"partial"},
}
_FINISHED = {"complete", "stale-marker"}


def _repo(state: str) -> str:
    return f"fixture/{state}"


@pytest.fixture(params=["a-download-directory", "HF_HOME", "HUGGINGFACE_HUB_CACHE"])
def cache(request, tmp_path):
    """Every state's model in one cache, and how the Forge would be pointed
    at it: the probes' cache-root argument, the environment, the scanner."""
    root = tmp_path / "cache with spaces"
    hub = root / "hub"
    for state, files in _BLOBS.items():
        model = hub / ("models--" + _repo(state).replace("/", "--"))
        (model / "blobs").mkdir(parents=True)
        for name, data in files.items():
            (model / "blobs" / name).write_bytes(data)
        snapshot = model / "snapshots" / "revision"
        snapshot.mkdir(parents=True)
        (snapshot / "config.json").write_text("{}", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    if request.param == "a-download-directory":
        # The download runner points HF_HOME at the task's directory, so its
        # cache is <directory>/hub; the probes are handed the directory.
        argument, scan = str(root), _cached_model_scan_script(add_hf_cache=str(hub))
    else:
        argument, scan = "", _cached_model_scan_script()
        env[request.param] = str(root if request.param == "HF_HOME" else hub)
    return hub, argument, env, scan


def _cache_bytes(hub: Path) -> dict[str, bytes]:
    return {str(p.relative_to(hub)): p.read_bytes() for p in sorted(hub.rglob("*")) if p.is_file()}


def _probe(script: str, state: str, argument: str, env: dict, *, through_a_shell: bool = False) -> bool:
    cmd = [sys.executable, "-I", "-c", script, _repo(state), argument]
    if through_a_shell:
        # What the remote end of `ssh host <command>` does with the command
        # the Forge quotes for it.
        cmd = [shutil.which("bash") or "/bin/sh", "-c", " ".join(shlex.quote(part) for part in cmd)]
    done = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
    assert done.returncode in (0, 1), done.stderr
    return done.returncode == 0


@pytest.mark.parametrize("probe", ["complete", "incomplete"])
def test_the_dead_download_probes_take_an_empty_marker_beside_its_finished_blob_for_finished(cache, probe):
    hub, argument, env, _ = cache
    before = _cache_bytes(hub)
    script = HF_CACHE_COMPLETE_PROBE if probe == "complete" else HF_CACHE_INCOMPLETE_PROBE

    said_yes = {state: _probe(script, state, argument, env) for state in _BLOBS}

    # The complete probe says yes to a finished download, the incomplete probe
    # to an unfinished one.
    assert said_yes == {state: (state in _FINISHED) == (probe == "complete") for state in _BLOBS}
    assert _cache_bytes(hub) == before


def test_the_cached_list_takes_an_empty_marker_beside_its_finished_blob_for_finished(cache):
    hub, _, env, scan = cache
    before = _cache_bytes(hub)
    # The scan's Ollama lookups stay off the network and off `ollama list`:
    # the address probe opens through `build_opener(ProxyHandler({}))` (`B1262`).
    harness = (
        "import shutil, urllib.request\n"
        "class _NoOllama:\n"
        "    def open(self, *args, **kwargs):\n"
        "        raise OSError('no Ollama in this fixture')\n"
        "urllib.request.build_opener = lambda *handlers: _NoOllama()\n"
        "shutil.which = lambda name: None\n"
    )

    done = subprocess.run([sys.executable, "-I", "-c", harness + scan], env=env,
                          capture_output=True, text=True, timeout=60)

    assert done.returncode == 0, done.stderr
    rows = {row["repo_id"]: row for row in json.loads(done.stdout.strip().splitlines()[-1])}
    assert {state: not rows[_repo(state)]["has_incomplete"] for state in _BLOBS} == {
        state: state in _FINISHED for state in _BLOBS
    }
    # A finished model counts its blob, and an empty marker is not a file of it.
    for state in sorted(_FINISHED):
        assert (rows[_repo(state)]["nb_files"], rows[_repo(state)]["size_bytes"]) == (1, len(_BLOB)), state
    assert _cache_bytes(hub) == before


@pytest.mark.parametrize("script", [HF_CACHE_COMPLETE_PROBE, HF_CACHE_INCOMPLETE_PROBE], ids=["complete", "incomplete"])
def test_a_probe_reads_a_remote_cache_the_same_through_the_quoting_ssh_gives_it(tmp_path, script):
    """Over SSH each probe goes as one shell-quoted `python3 -c` command, and
    it now has a function in it, over several lines."""
    hub = tmp_path / "cache with spaces" / "hub"
    for state in ("stale-marker", "partial"):
        blobs = hub / ("models--" + _repo(state).replace("/", "--")) / "blobs"
        blobs.mkdir(parents=True)
        for name, data in _BLOBS[state].items():
            (blobs / name).write_bytes(data)
        snapshot = blobs.parent / "snapshots" / "revision"
        snapshot.mkdir(parents=True)
        (snapshot / "config.json").write_text("{}", encoding="utf-8")
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    argument = str(hub.parent)

    for state in ("stale-marker", "partial"):
        direct = _probe(script, state, argument, env)
        quoted = _probe(script, state, argument, env, through_a_shell=True)
        assert quoted == direct == ((state in _FINISHED) == (script == HF_CACHE_COMPLETE_PROBE)), state
