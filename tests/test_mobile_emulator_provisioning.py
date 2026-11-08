# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run the real scrcpy provisioning function with a local archive as its
download. No network, SDK, Android, apt, or native scrcpy binary is used."""
import hashlib
import io
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SH = shutil.which("sh")
pytestmark = pytest.mark.skipif(SH is None, reason="POSIX shell is not installed")


def run_provision(tmp_path, *, corrupt=False):
    source = (ROOT / "workstation/provision.sh").read_text(encoding="utf-8")
    function = re.search(r"^phone_scrcpy\(\) \(\n.*?^\)\n", source, re.M | re.S).group()
    version = re.search(r"^SCRCPY_VERSION=(.*)$", source, re.M).group(1)
    archive = tmp_path / "fixture.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, body, mode in [
            ("scrcpy", f"#!/bin/sh\necho 'scrcpy {version} <fixture>'\n", 0o755),
            ("scrcpy-server", "fixture server", 0o644),
            ("NOTICE", "fixture upstream notice", 0o644),
        ]:
            data = body.encode()
            entry = tarfile.TarInfo("release/" + name)
            entry.size, entry.mode = len(data), mode
            tar.addfile(entry, io.BytesIO(data))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if corrupt:
        archive.write_bytes(b"corrupted download")
    # Cleanup is a stub too: this test never recursively deletes a shell-built
    # path. Pytest owns the verified workspace tmp_path and cleans it itself.
    prelude = r'''
set -eu
say() { printf '%s\n' "$*"; }
mktemp() { mkdir "$FIXTURE_WORK"; printf '%s\n' "$FIXTURE_WORK"; }
rm() { :; }
curl() {
    output=
    while [ "$#" -gt 0 ]; do
        if [ "$1" = --output ]; then shift; output=$1; fi
        shift
    done
    printf 'fetch\n' >> "$FIXTURE_LOG"
    cp "$FIXTURE_ARCHIVE" "$output"
}
'''
    script = tmp_path / "provision-fixture.sh"
    script.write_text(prelude + f"\nSCRCPY_VERSION={shlex.quote(version)}\nSCRCPY_SHA256={digest}\n"
                      + function + '\nphone_scrcpy "$FIXTURE_SDK"\nphone_scrcpy "$FIXTURE_SDK"\n',
                      encoding="utf-8", newline="\n")
    def shell_path(path):
        text = path.as_posix()
        return "/" + text[0].lower() + text[2:] if os.name == "nt" else text

    env = dict(os.environ, FIXTURE_WORK=shell_path(tmp_path / "work"),
               FIXTURE_ARCHIVE=shell_path(archive), FIXTURE_SDK=shell_path(tmp_path / "sdk"),
               FIXTURE_LOG=shell_path(tmp_path / "calls"))
    run = subprocess.run([SH, str(script)], env=env, cwd=tmp_path, capture_output=True,
                         text=True, timeout=30)
    return run


def test_the_pinned_bundle_installs_client_server_and_notices_once(tmp_path):
    run = run_provision(tmp_path)
    assert run.returncode == 0, run.stdout + run.stderr
    assert (tmp_path / "sdk/scrcpy/scrcpy").is_file()
    assert (tmp_path / "sdk/scrcpy/scrcpy-server").read_text() == "fixture server"
    assert (tmp_path / "sdk/scrcpy/NOTICE").read_text() == "fixture upstream notice"
    assert (tmp_path / "calls").read_text().splitlines() == ["fetch"]


def test_a_corrupt_bundle_is_refused_before_extraction(tmp_path):
    run = run_provision(tmp_path, corrupt=True)
    assert run.returncode != 0
    assert "did not match" in run.stdout
    assert not (tmp_path / "sdk").exists()
