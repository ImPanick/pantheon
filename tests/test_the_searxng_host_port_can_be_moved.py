# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2015`. SearXNG's host port was fixed at 8080, the port llama-server takes.

All three compose files published the bundled SearXNG on `127.0.0.1:8080:8080`,
written out. 8080 is llama-server's default, and Pantheon's own `/setup` guide
and model discovery look for a model server there. On a host running one the
publish failed ("port is already allocated"), and `pantheon`, which waits for
SearXNG to be healthy, never started. The only way out was to edit a tracked
compose file, because an override file's `ports` adds to the list rather than
replacing it.

Now the host side is `${SEARXNG_HOST_PORT:-8080}`, still on loopback, so an
install that sets nothing is unchanged. The variable moves only what a browser
on the host uses: the publish, and `SEARXNG_BASE_URL`, the address SearXNG's
own pages link to. What the app dials is the container's port on the compose
network (`SEARXNG_INSTANCE=http://searxng:8080`), and the healthcheck dials it
from inside the container, so neither follows the variable.

Ported from upstream Odysseus 12b9c5f2 (#6598). Pure YAML, no Docker.
"""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = (
    ROOT / "docker-compose.yml",
    ROOT / "docker-compose.gpu-nvidia.yml",
    ROOT / "docker-compose.gpu-amd.yml",
)
VARIABLE = "SEARXNG_HOST_PORT"


def _services(path: Path) -> dict:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("services") or {}


def _environment(spec: dict) -> dict:
    env = spec.get("environment") or {}
    if isinstance(env, list):
        env = dict(item.split("=", 1) if "=" in item else (item, "") for item in env)
    return env


def _strings(node):
    """Every string in a parsed compose document, keys and values."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(key)
            yield from _strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _strings(item)
    elif isinstance(node, str):
        yield node


@pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: p.name)
def test_searxng_is_published_on_a_host_port_a_person_can_move(path):
    searxng = _services(path)["searxng"]
    assert searxng["ports"] == ["127.0.0.1:${SEARXNG_HOST_PORT:-8080}:8080"], (
        f"{path.name}: SearXNG's host port is fixed, so a host whose llama-server has "
        f"8080 cannot start the stack; it stays on loopback and defaults to 8080")


@pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: p.name)
def test_the_port_moves_searxngs_own_address_and_nothing_the_app_dials(path):
    services = _services(path)
    searxng = services["searxng"]
    assert sorted(s for s in _strings(services) if VARIABLE in s) == [
        "127.0.0.1:${SEARXNG_HOST_PORT:-8080}:8080",
        "SEARXNG_BASE_URL=http://localhost:${SEARXNG_HOST_PORT:-8080}/",
    ], f"{path.name}: {VARIABLE} reaches something other than the publish and SearXNG's own address"
    assert _environment(searxng)["SEARXNG_BASE_URL"] == (
        "http://localhost:${SEARXNG_HOST_PORT:-8080}/")
    assert _environment(services["pantheon"])["SEARXNG_INSTANCE"] == "http://searxng:8080", (
        f"{path.name}: the app reaches SearXNG on the compose network, at the container's port")
    probe = " ".join(searxng["healthcheck"]["test"])
    assert "http://localhost:8080/" in probe, (
        f"{path.name}: the healthcheck runs inside the container, where SearXNG is on 8080")


def test_an_operator_finds_the_variable_where_they_look():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(rf"^# {VARIABLE}=8080$", example, re.M), (
        f".env.example does not declare {VARIABLE} with its default")
    setup = (ROOT / "docs" / "setup.md").read_text(encoding="utf-8")
    assert re.search(rf"^\| `8080` \| SearXNG\b.*`{VARIABLE}`", setup, re.M), (
        "docs/setup.md's port table does not say how SearXNG's port moves")
    assert re.search(rf"^\| `{VARIABLE}` \| `8080` \|", setup, re.M), (
        f"docs/setup.md's settings table has no {VARIABLE} row")
