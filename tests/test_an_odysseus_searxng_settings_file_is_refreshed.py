# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1164`: an upgraded Odysseus volume's untouched SearXNG settings are regenerated.

Each compose file's `searxng` entrypoint regenerates `/etc/searxng/settings.yml`
from the template only when the file is one this stack generated. Odysseus's
template shipped a fixed secret, `odysseus-local-searxng-json-2026-05-30`, so a
`searxng-data` volume kept across the upgrade carries it — and the condition
named only Pantheon's spelling, so the file was read as hand-edited and kept.

This runs each file's own shell, with `sh`, against temp settings files: the
compose `$$` escapes are undone and the two container paths pointed at temp
files; nothing else in the script is changed.
"""
import pathlib
import subprocess

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = ["docker-compose.yml", "docker-compose.gpu-amd.yml", "docker-compose.gpu-nvidia.yml"]
TEMPLATE = ROOT / "config" / "searxng" / "settings.yml"


def _refresh_script(compose: str, settings: pathlib.Path) -> str:
    """The entrypoint's own lines from `set -eu` through the regenerate `fi`."""
    doc = yaml.safe_load((ROOT / compose).read_text(encoding="utf-8"))
    script = doc["services"]["searxng"]["entrypoint"][-1]
    lines = script.splitlines()
    end = next(i for i, line in enumerate(lines) if line.strip() == "fi" and not line.startswith(" "))
    body = "\n".join(lines[: end + 1]).replace("$$", "$")
    body = body.replace("/etc/searxng/settings.yml", str(settings))
    return body.replace("/tmp/searxng-settings.yml.template", str(TEMPLATE))


def _run(compose: str, settings: pathlib.Path) -> str:
    subprocess.run(["sh", "-c", _refresh_script(compose, settings)], check=True,
                   env={"PATH": "/usr/bin:/bin", "SEARXNG_SECRET": "fresh-secret"}, timeout=30)
    return settings.read_text(encoding="utf-8")


@pytest.mark.parametrize("compose", COMPOSE)
@pytest.mark.parametrize("marker", [
    "odysseus-local-searxng-json-2026-05-30",   # B1164: an Odysseus volume
    "pantheon-local-searxng-json-2026-05-30",
    "__SEARXNG_SECRET__",
])
def test_a_generated_file_is_regenerated_from_the_template(tmp_path, compose, marker):
    settings = tmp_path / "settings.yml"
    settings.write_text(f'use_default_settings: true\nserver:\n  secret_key: "{marker}"\n',
                        encoding="utf-8")
    out = _run(compose, settings)
    assert marker not in out, f"{compose} kept a file carrying {marker}"
    assert 'secret_key: "fresh-secret"' in out
    assert out == TEMPLATE.read_text(encoding="utf-8").replace("__SEARXNG_SECRET__", "fresh-secret")


@pytest.mark.parametrize("compose", COMPOSE)
def test_a_hand_edited_file_is_kept(tmp_path, compose):
    settings = tmp_path / "settings.yml"
    mine = 'use_default_settings: true\nserver:\n  secret_key: "my-own-secret"\n'
    settings.write_text(mine, encoding="utf-8")
    assert _run(compose, settings) == mine
