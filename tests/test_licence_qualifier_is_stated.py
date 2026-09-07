# SPDX-License-Identifier: AGPL-3.0-or-later
"""P0-18 — the qualifier lived in one README line and nowhere else.

`AGPL-3.0` and `AGPL-3.0-or-later` are different licences to anyone combining
this with something else, and until 2026-09-07 which one Pantheon is under was
stated exactly once, in a README badge. Not in `LICENSE`, not in `NOTICE`, not
in `package.json`, not on the container image, and in none of the 1,461 files
of program text. `DECISIONS.md` D-2026-08-26-06 settled it as
**`AGPL-3.0-or-later`**, matching upstream.

**`LICENSE` is the one place it is deliberately NOT stated**, and the row asked
for it there. The AGPL text says, in its own second paragraph, that copying it
verbatim is permitted and changing it is not — so a project header prepended to
it is a modification of a document nobody here may modify. The qualifier lives
in `NOTICE`, the README, the package metadata, the image label and the per-file
headers instead, which is where the FSF's own "How to Apply These Terms"
section puts it.

There is no test here that greps for the string in prose and calls it done.
Each of these reads the file that would actually be consulted: `docker inspect`
reads the label, `npm` reads `package.json`, a licence scanner reads the SPDX
headers, and a person reads `NOTICE`.
"""
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
LICENCE = "AGPL-3.0-or-later"

# Every SPDX id that is *not* ours and would be wrong in our own metadata.
# `AGPL-3.0` alone is deprecated by SPDX and ambiguous besides. Matched with a
# leading word boundary, because `GPL-3.0-or-later` is a substring of ours and
# a plain `in` check fails on the correct file — which it did, first try.
WRONG = ("AGPL-3.0-only", "AGPL-3.0+", "GPL-3.0-or-later", "GPL-3.0-only")


def _wrong_ids(text):
    return [w for w in WRONG
            if re.search(rf"(?<![A-Za-z0-9.-]){re.escape(w)}", text)]


def test_notice_carries_the_identifier_and_the_words():
    text = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert f"SPDX-License-Identifier: {LICENCE}" in text
    assert "or (at your option) any" in text and "later version" in text, (
        "the identifier is the machine-readable half; the sentence is the half "
        "that carries the same meaning to a person"
    )
    assert not _wrong_ids(text)


def test_the_readme_says_which_one_and_where_it_is_stated():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert LICENCE in text
    assert "SPDX-License-Identifier" in text, (
        "a reader who finds one file needs to know the headers are there"
    )
    assert not _wrong_ids(text)


def test_package_metadata_declares_it():
    """`npm` and every tool that scans a manifest read this field. Without it
    the project reports as unlicensed, whatever the README says."""
    pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert pkg.get("license") == LICENCE, pkg
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["packages"][""].get("license") == LICENCE, (
        "the lockfile's root entry mirrors package.json; letting them drift "
        "means the next `npm install` produces a diff nobody asked for"
    )


def test_the_container_image_declares_it():
    """A published image is a distribution and `docker inspect` is where its
    licence is looked up. P0-30 is the same failure with a different artefact."""
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert f'org.opencontainers.image.licenses="{LICENCE}"' in text


def test_the_licence_document_itself_is_left_alone():
    """The AGPL says copying it verbatim is permitted and changing it is not.
    A project header prepended to it is a change."""
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.lstrip().startswith("GNU AFFERO GENERAL PUBLIC LICENSE"), (
        "something was prepended to the licence text"
    )
    assert "changing it is not allowed" in text
    for ours in ("Pantheon", "Odysseus", "SPDX-License-Identifier"):
        assert ours not in text, (
            f"{ours!r} appears in LICENSE — the qualifier belongs in NOTICE and "
            "the per-file headers, not in a document this project may not modify"
        )


# --- the headers -----------------------------------------------------------

HEADERED = (
    "app.py",
    "launcher.py",
    "core/api_tokens.py",
    "src/agent_loop.py",
    "routes/api_token_routes.py",
    "static/js/theme.js",
    "static/style.css",
    "static/index.html",
    "docker/entrypoint.sh",
    ".pantheon/check-spdx.py",
)


@pytest.mark.parametrize("rel", HEADERED)
def test_a_sample_of_shipped_files_declare_the_licence(rel):
    """`check-spdx.py` covers all 1,461. This is the sample that fails loudly in
    the suite rather than only in a checker, and it spans every comment syntax
    the stamper knows."""
    text = (ROOT / rel).read_text(encoding="utf-8")
    head = "\n".join(text.split("\n")[:5])
    assert f"SPDX-License-Identifier: {LICENCE}" in head, (
        f"{rel} declares the licence, but not in the first five lines where a "
        "scanner and a person both look"
    )


def test_the_header_never_precedes_something_that_must_come_first():
    """A shebang is only a shebang at byte zero; PEP 263 reads an encoding
    declaration in the first two lines; a comment above `<!DOCTYPE html>` puts
    a browser into quirks mode. Each of those turns a licence header into an
    outage, so the stamper inserts *after* them."""
    for rel in ("docker/entrypoint.sh", "scripts/pantheon-init.sh"):
        first = (ROOT / rel).read_text(encoding="utf-8").split("\n", 1)[0]
        assert first.startswith("#!"), f"{rel} lost its shebang"
    for rel in ("static/index.html", "static/login.html"):
        first = (ROOT / rel).read_text(encoding="utf-8").split("\n", 1)[0]
        assert re.match(r"\s*<!doctype", first, re.I), f"{rel} lost its doctype"


def test_vendored_files_are_not_stamped_with_our_licence():
    """The direction this repository has actually gone wrong in: P0-16's first
    attempt put a licence line on eight files that read as declaring them
    somebody else's licence. Stamping AGPL on a vendored MIT build is the same
    mistake pointed the other way, and this project cannot relicense it."""
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "static/lib", "static/fonts", "static/icons", "library"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    assert tracked, "the vendored roots are empty — this test proves nothing"
    offenders = []
    for rel in tracked:
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if LICENCE in text:
            offenders.append(rel)
    assert not offenders, offenders
