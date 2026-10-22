# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1424`: Pantheon's start-up ownership repair leaves each person's projects
folder alone.

`docker/entrypoint.sh` walks `/app/data` and gives everything not owned by
Pantheon's user back to it. Since `B1417` the workstation writes into
`/app/data/projects`, as each person's own Unix account — so every restart took
every file a person had built and handed it to Pantheon, after which the person
could read their work and no longer change it.

The real function, out of the real script, run by bash as root on a real tree.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
pytestmark = pytest.mark.skipif(os.geteuid() != 0 or not shutil.which("bash"),
                                reason="chown needs root")


def _function(name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", SCRIPT, re.S | re.M)
    assert m, f"{name} is not in docker/entrypoint.sh"
    return m.group(0)


def _repair(tree: Path, puid: int, pgid: int) -> None:
    script = _function("repair_tree_ownership") + f'repair_tree_ownership "{tree}"\n'
    subprocess.run(["bash", "-c", script], check=True,
                   env={**os.environ, "PUID": str(puid), "PGID": str(pgid)})


def test_the_repair_takes_back_pantheons_files_and_not_a_persons(tmp_path):
    data = tmp_path / "data"
    person = data / "projects" / "cy-3d30f595"
    (person / "site").mkdir(parents=True)
    built = person / "site" / "index.html"
    built.write_text("<h1>mine</h1>")
    record = data / "app.db"
    record.write_text("")
    for p in (person, person / "site", built):
        os.chown(p, 20001, 4242)
    os.chown(record, 0, 0)
    os.chown(data / "projects", 0, 0)

    _repair(data, 1000, 1000)

    assert os.stat(record).st_uid == 1000, "Pantheon's own file was not repaired"
    assert os.stat(data / "projects").st_uid == 1000, "the projects root is Pantheon's"
    for p in (person, person / "site", built):
        assert (os.stat(p).st_uid, os.stat(p).st_gid) == (20001, 4242), p
