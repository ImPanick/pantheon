# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2214` — a base-image bump moves every place that names the system.

On 2026-11-24 the workstation's Fedora base moved 44 -> 45 and the other three
to their newest dated builds. A distro's major version is said in more places
than the `FROM` line: the name a person picks it by (`workstation/protocol.py`
`SYSTEM_NAMES`), and Ubuntu's digest is repeated in three Dockerfiles. A bump
that moves the `FROM` and not the name tells a person they are on Fedora 44
while they are on 45 — which is what Dependabot's #64 would have done, since it
edits the `FROM` line alone.

Offline, so it cannot say whether a base is the newest one: that reading is
Docker Hub's, and the row records it.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WS = ROOT / "workstation"


def _froms() -> dict[str, str]:
    """`{stage: image reference}` for the four `base-*` stages."""
    text = (WS / "Dockerfile").read_text(encoding="utf-8")
    return dict((m.group(2), m.group(1)) for m in
                re.finditer(r"^FROM (\S+) AS base-(\w+)$", text, re.M))


def _system_names() -> dict[str, str]:
    text = (WS / "protocol.py").read_text(encoding="utf-8")
    block = re.search(r"SYSTEM_NAMES = \{(.*?)\}", text, re.S).group(1)
    return dict(re.findall(r'"(\w+)": "([^"]+)"', block))


def test_every_base_is_a_tag_and_a_digest():
    froms = _froms()
    assert set(froms) == {"ubuntu", "debian", "fedora", "rocky"}, froms
    for stage, ref in froms.items():
        assert re.fullmatch(r"[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}", ref), (stage, ref)


def test_the_name_a_person_picks_says_the_major_the_image_is():
    froms, names = _froms(), _system_names()
    fedora_major = froms["fedora"].split(":")[1].split("@")[0]
    rocky_major = froms["rocky"].split(":")[1].split(".")[0]
    assert names["fedora"] == f"Fedora {fedora_major}", (names["fedora"], froms["fedora"])
    assert names["rocky"] == f"Rocky Linux {rocky_major}", (names["rocky"], froms["rocky"])
    assert froms["debian"].startswith("debian:trixie-") and names["debian"] == "Debian 13"
    assert froms["ubuntu"].startswith("ubuntu:noble-") and names["ubuntu"] == "Ubuntu 24.04"


def test_the_three_ubuntu_images_share_one_base():
    """`vm.Dockerfile` and `android-vm.Dockerfile` build from the workstation's
    own Ubuntu (`B1677`), so one bump moves all three."""
    want = _froms()["ubuntu"]
    for name in ("vm.Dockerfile", "android-vm.Dockerfile"):
        text = (WS / name).read_text(encoding="utf-8")
        got = re.search(r"^FROM (\S+)", text, re.M).group(1)
        assert got == want, (name, got, want)


def test_the_prose_names_the_same_fedora():
    major = _froms()["fedora"].split(":")[1].split("@")[0]
    for rel in ("README.md", "docs/capabilities.md", ".env.example",
                "docker-compose.yml", "workstation/provision.sh"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        stale = sorted(set(re.findall(r"Fedora (\d+)", text)) - {major})
        assert not stale, f"{rel} still says Fedora {stale} beside fedora:{major}"
