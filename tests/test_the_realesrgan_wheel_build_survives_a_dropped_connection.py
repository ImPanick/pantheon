# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1972`. One dropped connection to PyPI failed the image build.

The Dockerfile's realesrgan-wheels stage runs docker/build-realesrgan-wheels.sh,
which reads three packages' metadata from PyPI's JSON API and then downloads
their source archives. The metadata came through Python's urllib and the
archives through `curl -fsSL`, neither retried, under `set -euo pipefail`: one
TLS EOF or reset from pypi.org or files.pythonhosted.org failed the stage, and
with it CI's two uncached Trivy builds or a person's `docker build`.

Both fetches now go through curl with `--retry 8 --retry-all-errors` (plain
`--retry` does not retry a dropped TLS connection). The metadata is saved to a
file and removed straight after, because its name, basicsr-1.4.2.json, matches
the `./basicsr-*` that pip wheel is handed. A pin with no source archive still
stops the build and names the pin.

Driven (`Law 20`): the real script, run by bash with `curl` and `pip`
replaced on PATH. The stand-in curl drops every connection unless it is told
to retry on all errors, and otherwise answers as PyPI would, with the JSON and
an archive whose setup.py has the code the script patches. Nothing reaches the
network: anything else that tries meets a proxy that refuses.

From upstream Odysseus 239f09cb (#6407).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "docker" / "build-realesrgan-wheels.sh"
PINS = [("basicsr", "1.4.2"), ("gfpgan", "1.3.8"), ("facexlib", "0.3.0")]

pytestmark = pytest.mark.skipif(os.name == "nt" or not shutil.which("bash"),
                                reason="the wheel builder is a bash script")

_CURL = r'''
import io, json, os, sys, tarfile
args = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(["curl", *args]) + "\n")
if "--retry" not in args or "--retry-all-errors" not in args:
    # What a build saw from PyPI on a bad day: the TLS connection dropped.
    sys.stderr.write("curl: (35) OpenSSL SSL_connect: SSL_ERROR_SYSCALL\n")
    sys.exit(35)
out = args[args.index("-o") + 1]
url = next(a for a in args if a.startswith("https://"))
if url.startswith("https://pypi.org/pypi/"):
    name, ver = url.split("/")[4:6]
    urls = [{"packagetype": "bdist_wheel", "url": f"https://files.example.invalid/{name}-{ver}-py3-none-any.whl"}]
    if name not in os.environ.get("STUB_NO_SDIST", "").split(","):
        urls.append({"packagetype": "sdist", "url": f"https://files.example.invalid/{name}-{ver}.tar.gz"})
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"urls": urls}, f)
    sys.exit(0)
top = url.rsplit("/", 1)[1][:-len(".tar.gz")]
setup = (b"def get_version():\n"
         b"    with open(version_file, 'r') as f:\n"
         b"        exec(compile(f.read(), version_file, 'exec'))\n"
         b"    return locals()['__version__']\n")
with tarfile.open(out, "w:gz") as tar:
    info = tarfile.TarInfo(f"{top}/setup.py")
    info.size = len(setup)
    tar.addfile(info, io.BytesIO(setup))
'''

_PIP = r'''
import json, os, sys
with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(["pip", *sys.argv[1:]]) + "\n")
'''


def _build(tmp_path, **env):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("curl", _CURL), ("pip", _PIP)):
        (bin_dir / f"{name}.py").write_text(body, encoding="utf-8")
        wrapper = bin_dir / name
        wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{bin_dir / name}.py" "$@"\n',
                           encoding="utf-8")
        wrapper.chmod(0o755)
    python = bin_dir / "python"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    python.chmod(0o755)
    log = tmp_path / "calls.jsonl"
    refuse = "http://127.0.0.1:9"
    environ = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
               "STUB_LOG": str(log), "HTTPS_PROXY": refuse, "https_proxy": refuse,
               "HTTP_PROXY": refuse, "http_proxy": refuse, "NO_PROXY": "", "no_proxy": "",
               "TMPDIR": str(tmp_path), **env}
    proc = subprocess.run(["bash", str(SCRIPT), str(tmp_path / "wheels")], env=environ,
                          capture_output=True, text=True, timeout=120)
    calls = ([json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
             if log.exists() else [])
    return proc, calls


def test_a_dropped_connection_to_pypi_is_retried_and_pip_gets_the_three_sources(tmp_path):
    proc, calls = _build(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    fetches = [c[1:] for c in calls if c[0] == "curl"]
    assert [next(a for a in c if a.startswith("https://")) for c in fetches] == [
        url for name, ver in PINS
        for url in (f"https://pypi.org/pypi/{name}/{ver}/json",
                    f"https://files.example.invalid/{name}-{ver}.tar.gz")]
    for args in fetches:
        assert "--fail" in args and "--retry-all-errors" in args, args
    pips = [c[1:] for c in calls if c[0] == "pip"]
    assert len(pips) == 1, pips
    handed = pips[0][pips[0].index("-w") + 2:]
    # No metadata file and no archive is mistaken for a source tree.
    assert handed == [f"./{name}-{ver}" for name, ver in PINS], handed


def test_a_pin_with_no_source_archive_stops_the_build_and_names_the_pin(tmp_path):
    proc, calls = _build(tmp_path, STUB_NO_SDIST="gfpgan")
    assert proc.returncode != 0
    assert "no sdist found for gfpgan==1.3.8" in proc.stderr, proc.stderr
    assert not [c for c in calls if c[0] == "pip"]
