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


# ── `B1626`: the volume is mounted where the pinned server writes ──
#
# `chromadb/chroma` 1.x runs `chroma run /config.yaml`, and where it keeps its
# index is that file's `persist_path` — not `/chroma/chroma`, the 0.x image's
# path, which all three files mounted. So `chromadb-data` stayed empty, the
# index lived in the container's writable layer, and every recreate (`docker
# compose up -d --force-recreate chromadb`, a changed image, a changed block)
# dropped every collection.
#
# Where a tag writes is a fact about that image, so it is read from the image
# and written down here with where it was read; the files are then held to it
# with no Docker daemon. 1.5.9, read 2026-10-28 from Docker Hub: the amd64
# image's config is `Entrypoint ["dumb-init", "--", "chroma"]`,
# `Cmd ["run", "/config.yaml"]`, and its 131-byte layer
# `sha256:95ebd62f…41b29e` is that one file, `persist_path: "/data"` — a copy
# of `rust/frontend/sample_configs/docker_single_node.yaml` at the `1.5.9`
# tag. Chroma's v1.0.0 migration note says it in words: "The default data
# location in the container has changed from `/chroma/chroma` to `/data`."
# A pin moved to a tag this table does not hold fails until someone reads the
# new tag the same way.
CHROMA_PERSIST_PATH = {"1.5.9": "/data"}


def _mounts(spec: dict) -> list[tuple[str, str]]:
    """`(source, target)` for each of a service's volumes, short syntax
    (`source:target[:mode]`) or long (`{source, target}`) — compose's two."""
    out = []
    for vol in spec.get("volumes") or []:
        if isinstance(vol, dict):
            out.append((str(vol.get("source") or ""), str(vol.get("target") or "")))
        else:
            parts = str(vol).split(":")
            out.append((parts[0], parts[1]) if len(parts) > 1 else ("", parts[0]))
    return out


def _environment(spec: dict) -> dict:
    env = spec.get("environment") or {}
    if isinstance(env, list):
        env = dict(item.split("=", 1) if "=" in item else (item, "") for item in env)
    return env


def test_chromas_volume_is_mounted_where_the_pinned_server_writes():
    for path in COMPOSE_FILES:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        chroma = [spec for spec in (doc.get("services") or {}).values()
                  if isinstance(spec, dict)
                  and _split_image(spec.get("image") or "")[0].endswith("chromadb/chroma")]
        assert len(chroma) == 1, f"{path.name}: expected one chroma service, found {len(chroma)}"
        spec = chroma[0]
        tag = _split_image(spec["image"])[1]
        assert tag in CHROMA_PERSIST_PATH, (
            f"{path.name} pins chromadb/chroma:{tag}, and where that release keeps its index "
            f"has not been read — find its `persist_path` (the image's command and the config "
            f"file it names) and add it to CHROMA_PERSIST_PATH (`B1626`)")
        # The server reads `CHROMA_`-prefixed variables over its config file,
        # so a `CHROMA_PERSIST_PATH` set here would be where it writes instead.
        writes = _environment(spec).get("CHROMA_PERSIST_PATH") or CHROMA_PERSIST_PATH[tag]
        there = [source for source, target in _mounts(spec) if target.rstrip("/") == writes]
        declared = doc.get("volumes") or {}
        assert there and there[0] in declared, (
            f"{path.name}: chromadb/chroma:{tag} keeps its index in {writes}, and the "
            f"service mounts {_mounts(spec)} — the index is in the container's own layer and "
            f"a recreate loses it (`B1626`). Mount the `chromadb-data` volume at {writes}.")


# ── `B1667`: the same rule for the images the Dockerfiles build `FROM` ──
#
# All three `FROM`s in `Dockerfile` read `python:3.14-slim` — a minor line, not
# a release — so a rebuild could swap the interpreter under the product with no
# change in the tree and no record of which one was working: the class `B445`
# closed for the compose files, one file over. One rule (`Law 14`): a `FROM` is
# judged by the `_split_image` and `_RELEASE_TAG` above, exactly as an `image:`
# is, and a digest passes because a content address does not move.
#
# Every Dockerfile in the tree is read, not just the app's, so a new one is held
# to the rule the day it lands (`Law 13`). The workstation's two are the
# exception, written down with why, keyed by the reference so moving either one
# makes the entry stale and this test says so.

import subprocess  # noqa: E402

MOVING_BASE_ON_PURPOSE = {
    # (file, reference): why it is not held to a release yet
    ("workstation/Dockerfile", "ubuntu:24.04"): (
        "Ubuntu publishes no three-part release tag (its dated `noble-YYYYMMDD` "
        "tags do not fit `_RELEASE_TAG`), so this wants a digest, and the "
        "workstation's own build tests are where that is driven; found while "
        "doing B1667 and filed as its own row"),
    ("workstation/vm.Dockerfile", "ubuntu:24.04"): (
        "the VM image's build stage, on the workstation's base for the same "
        "reason; filed with the row above"),
}


def _dockerfiles() -> list[str]:
    """Every tracked Dockerfile, as `git ls-files` names it, falling back to
    the tree when this is not a checkout (an sdist, a copied directory)."""
    try:
        out = subprocess.run(["git", "ls-files"], cwd=_ROOT, capture_output=True,
                             text=True, check=True, timeout=60).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        out = [str(p.relative_to(_ROOT)) for p in _ROOT.rglob("*")
               if ".git" not in p.parts and "node_modules" not in p.parts
               and "venv" not in p.parts and p.is_file()]
    return sorted(f for f in out
                  if Path(f).name == "Dockerfile" or Path(f).name.endswith(".Dockerfile"))


def _from_refs(text: str) -> list[str]:
    """The image each `FROM` names, read the way the builder reads the file:
    continuation lines joined, comments dropped, `--platform=` and other flags
    skipped, `$VAR`/`${VAR}` replaced by the default of an `ARG` declared before
    the first `FROM` (the only `ARG`s a `FROM` can see). A stage built `FROM` an
    earlier stage's name is that stage, not an image, so it is left out; so is
    `scratch`, which is no image at all. A variable with no default is kept as
    written, and so fails the rule — a base chosen at build time is not pinned
    in the tree."""
    instructions, buf = [], ""
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.endswith("\\"):
            buf += s[:-1].strip() + " "
            continue
        instructions.append((buf + s).strip())
        buf = ""
    global_args: dict[str, str] = {}
    stages: set[str] = set()
    refs: list[str] = []
    seen_from = False
    for ins in instructions:
        word, _, rest = ins.partition(" ")
        word = word.upper()
        if word == "ARG" and not seen_from:
            name, eq, default = rest.strip().partition("=")
            if eq:
                global_args[name.strip()] = default.strip().strip('"').strip("'")
        if word != "FROM":
            continue
        seen_from = True
        parts = [p for p in rest.split() if not p.startswith("--")]
        ref = re.sub(r"\$\{(\w+)\}|\$(\w+)",
                     lambda m: global_args.get(m.group(1) or m.group(2), m.group(0)), parts[0])
        if len(parts) >= 3 and parts[1].upper() == "AS":
            stages_named = parts[2].lower()
        else:
            stages_named = None
        if ref.lower() not in stages and ref != "scratch":
            refs.append(ref)
        if stages_named:
            stages.add(stages_named)
    return refs


def test_from_refs_reads_the_dockerfile_grammar():
    text = (
        "# a comment FROM nothing:1\n"
        "ARG BASE=python:3.14.10-slim\n"
        "FROM --platform=$BUILDPLATFORM ${BASE} AS build\n"
        "RUN echo \\\n"
        "  FROM not-an-instruction:latest\n"
        "FROM build AS again\n"
        "FROM scratch\n"
        "from debian:trixie as lower\n"
        "FROM $UNSET_BASE\n"
    )
    assert _from_refs(text) == ["python:3.14.10-slim", "debian:trixie", "$UNSET_BASE"]


def test_every_dockerfile_builds_from_a_release_or_a_digest():
    files = _dockerfiles()
    assert "Dockerfile" in files, f"the app's Dockerfile is not where this looks: {files}"
    problems, used_exceptions = [], set()
    for rel in files:
        for ref in _from_refs((_ROOT / rel).read_text(encoding="utf-8")):
            name, tag, digest = _split_image(ref)
            if digest or _RELEASE_TAG.match(tag):
                continue
            if (rel, ref) in MOVING_BASE_ON_PURPOSE:
                used_exceptions.add((rel, ref))
                continue
            problems.append(
                f"{rel}: `FROM {ref}` — `{tag or '(no tag = latest)'}` moves under a "
                f"rebuild, so the base can change with nothing in the tree saying so. Pin "
                f"it to a release tag (`python:3.14.N-slim`) or a digest, the way every "
                f"compose image is (`B445`, `B1667`)")
    stale = set(MOVING_BASE_ON_PURPOSE) - used_exceptions
    assert not problems, "\n".join(problems)
    assert not stale, (
        f"MOVING_BASE_ON_PURPOSE names {sorted(stale)}, which no Dockerfile builds from "
        f"any more (or which is now pinned) — delete the entry so the table says only "
        f"what is true")


def test_the_apps_stages_share_one_pinned_base():
    """`B1591`'s comment-stripping stage runs on the base the other two use, on
    purpose — one image to trust and keep current — so a pin moved in one stage
    and not the others is a second base arriving by accident."""
    refs = _from_refs((_ROOT / "Dockerfile").read_text(encoding="utf-8"))
    assert len(refs) == 3 and len(set(refs)) == 1, refs
    name, tag, digest = _split_image(refs[0])
    assert name == "python" and (digest or _RELEASE_TAG.match(tag)), refs[0]
