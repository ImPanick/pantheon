# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression guard for issue #1414 — a broken upstream `searxng:latest` tag
(2026.6.2 crashed on boot with KeyError: 'default_doi_resolver') failed the
searxng healthcheck, and because `pantheon` waits on it via
`depends_on: condition: service_healthy`, the whole app never started on fresh
Docker installs.

Pin the SearXNG image to a known-good tag so a bad upstream `latest` can't block
startup. This guards that the pin stays in place.
"""
import re
from pathlib import Path

COMPOSE = Path(__file__).resolve().parent.parent / "docker-compose.yml"


def test_searxng_image_is_pinned_not_latest():
    text = COMPOSE.read_text(encoding="utf-8")
    m = re.search(r"image:\s*\S*searxng/searxng:(\S+)", text)
    assert m, "searxng image line not found in docker-compose.yml"
    tag = m.group(1)
    assert tag != "latest", (
        "SearXNG must be pinned, not ':latest' — pantheon startup depends on its "
        "healthcheck, so a broken upstream latest tag blocks the app (issue #1414)"
    )
    # A real version tag (date-based, e.g. 2026.5.31-7159b8aed), not a moving ref.
    assert re.match(r"\d{4}\.\d", tag), f"expected a versioned tag, got {tag!r}"


# ── `B445`: the same rule for every third-party image, in all three files ──
#
# The test above guarded the one image that had already broken. Immediately
# around it `chromadb/chroma` was `:latest` and `binwiederhier/ntfy` had no tag
# at all — `:latest` written shorter — in `docker-compose.yml` and in both
# standalone GPU files. Neither blocks startup the way searxng did (`pantheon`
# waits on chromadb with `service_started`, and nothing waits on ntfy), so the
# cost was quieter: a rebuild that silently swaps two components, with no
# record of which version was working. That is the thing the searxng comment
# was written to prevent, applied at one call site of three (`Law 13`).
#
# Read as YAML, not as text, so a commented-out `image:` line or one moved into
# an anchor is judged the way compose would read it.

import yaml  # noqa: E402

_ROOT = COMPOSE.parent
COMPOSE_FILES = (
    _ROOT / "docker-compose.yml",
    _ROOT / "docker-compose.gpu-amd.yml",
    _ROOT / "docker-compose.gpu-nvidia.yml",
)

# The one image this project builds and publishes itself. Its tag is what
# `.github/workflows/` pushes, and a person updating Pantheon wants the newest
# one; every other image is somebody else's release and is pinned. Named
# exactly, so a new third-party image cannot pass by looking first-party.
FIRST_PARTY = frozenset({"ghcr.io/impanick/pantheon"})

# A release, not a moving reference: three numeric components, optionally
# `v`-prefixed and suffixed (`1.5.9`, `v2.34.0`, `2026.5.31-7159b8aed`).
# `v2`, `2.34`, `stable` and `latest` all move under a rebuild.
_RELEASE_TAG = re.compile(r"^v?\d+\.\d+\.\d+([.+-][0-9A-Za-z.+-]+)?$")


def _split_image(ref: str) -> tuple[str, str, str]:
    """`(name, tag, digest)` the way the Docker reference grammar reads it: the
    tag is after the last `:` **after the last `/`** (a registry may carry a
    port), and an untagged reference has the empty tag compose fills with
    `latest`."""
    name, _, digest = ref.partition("@")
    slash = name.rfind("/")
    colon = name.rfind(":")
    if colon > slash:
        return name[:colon], name[colon + 1:], digest
    return name, "", digest


def _images(path: Path) -> dict[str, str]:
    services = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("services") or {}
    return {svc: spec["image"] for svc, spec in services.items()
            if isinstance(spec, dict) and spec.get("image")}


def test_split_image_reads_the_reference_grammar():
    assert _split_image("docker.io/binwiederhier/ntfy") == ("docker.io/binwiederhier/ntfy", "", "")
    assert _split_image("docker.io/chromadb/chroma:latest") == ("docker.io/chromadb/chroma", "latest", "")
    assert _split_image("registry:5000/x/y") == ("registry:5000/x/y", "", "")
    assert _split_image("registry:5000/x/y:1.2.3") == ("registry:5000/x/y", "1.2.3", "")
    assert _split_image("a/b:1.0.0@sha256:ab") == ("a/b", "1.0.0", "sha256:ab")


def test_the_release_shape_rejects_every_moving_reference():
    for moving in ("", "latest", "v2", "2", "2.34", "v2.34", "stable", "nightly"):
        assert not _RELEASE_TAG.match(moving), moving
    for release in ("1.5.9", "v2.34.0", "2026.5.31-7159b8aed"):
        assert _RELEASE_TAG.match(release), release


def test_every_third_party_image_is_pinned_to_a_release():
    problems = []
    seen_third_party = 0
    for path in COMPOSE_FILES:
        for service, ref in _images(path).items():
            name, tag, digest = _split_image(ref)
            bare = name.removeprefix("docker.io/")
            if name in FIRST_PARTY:
                continue
            seen_third_party += 1
            if digest:
                continue  # a content address does not move at all
            if not _RELEASE_TAG.match(tag):
                problems.append(
                    f"{path.name}: service `{service}` runs `{bare}:{tag or '(no tag = latest)'}` "
                    f"— pin it to a release tag that was booted and seen working, "
                    f"the way searxng is (issue #1414, `B445`)")
    assert seen_third_party, "no third-party image found — the compose files moved"
    assert not problems, "\n".join(problems)


def test_each_image_is_pinned_the_same_in_all_three_files():
    """The GPU files are standalone copies (`tests/test_gpu_compose_standalone.py`
    holds them to the base file), so a pin moved in one and not the others is an
    install that boots a different component depending on which file it used."""
    by_image: dict[str, set[tuple[str, str]]] = {}
    for path in COMPOSE_FILES:
        for ref in _images(path).values():
            name, tag, digest = _split_image(ref)
            by_image.setdefault(name, set()).add((tag, digest))
    split = {name: refs for name, refs in by_image.items() if len(refs) > 1}
    assert not split, f"one image, several pins across the compose files: {split}"


def test_the_chroma_server_is_the_release_its_client_is_pinned_to():
    """`chromadb-client` talks to this server over HTTP. The two are cut from
    one Chroma release, so a Dependabot bump of either one alone is the
    "rebuild that silently changes a component" this row is about, moved one
    file over."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "b445_pins", _ROOT / ".pantheon" / "check-pins.py")
    pins = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pins)
    client = [s for _, _, name, s in pins.parse_requirements(_ROOT / "requirements.txt")
              if name.lower() == "chromadb-client"]
    assert len(client) == 1 and client[0].startswith("=="), client
    client_version = client[0][2:]
    for path in COMPOSE_FILES:
        servers = [_split_image(ref)[1] for ref in _images(path).values()
                   if _split_image(ref)[0].endswith("chromadb/chroma")]
        assert servers == [client_version], (
            f"{path.name}: chroma server {servers} against chromadb-client=={client_version}")
