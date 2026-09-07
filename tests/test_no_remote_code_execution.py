# SPDX-License-Identifier: AGPL-3.0-or-later
"""Nothing in the app downloads code from a third party and runs it.

`trust_remote_code=True` tells `transformers` to fetch Python from a model
repository and **execute it**, in this process, with this process's
permissions. Until 2026-09-01 the "remove background" button did exactly that
when rembg was absent: an ordinary user click, no consent, nothing on screen
saying so. `Law 16` is about defaults reaching the network — this is worse than
that, because what comes back is not data.

`scripts/diffusion_server.py` is deliberately out of scope. An operator who
starts a diffusion server has chosen to load models, and most diffusion
pipelines need remote code. Loading models is that script's entire purpose. It
is not the app's, and the app is what a user clicks buttons in.
"""
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
APP_ROOTS = ("routes", "src", "services", "core", "companion", "integrations", "mcp_servers")


def _app_sources():
    for root in APP_ROOTS:
        d = REPO / root
        if not d.is_dir():
            continue
        for p in d.rglob("*.py"):
            if "test" in p.parts or p.name.startswith("test_"):
                continue
            yield p
    yield REPO / "app.py"


def _uncommented_lines(text: str):
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        yield i, line


def test_no_app_path_executes_code_fetched_at_runtime():
    hits = []
    for f in _app_sources():
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "trust_remote_code" not in text:
            continue
        for i, line in _uncommented_lines(text):
            if "trust_remote_code" in line and "False" not in line:
                hits.append(f"{f.relative_to(REPO)}:{i}")
    assert not hits, (
        "an app path passes trust_remote_code, which downloads and executes "
        f"third-party Python in this process: {hits}"
    )


def test_the_removal_left_an_actionable_message():
    """A deletion under `Law 1` has to leave the user better off, not stuck."""
    src = (REPO / "routes/gallery/gallery_routes.py").read_text(encoding="utf-8")
    i = src.index("Background removal needs rembg")
    msg = src[i:i + 320]
    assert "pip install rembg" in msg, "the error does not say how to fix it"
    assert "will not" in msg, "the error does not say why Pantheon stopped short"


def test_the_reason_is_recorded_where_the_code_was():
    """So the next person to 'restore' it reads why it went first."""
    src = (REPO / "routes/gallery/gallery_routes.py").read_text(encoding="utf-8")
    i = src.index("Background removal needs rembg")
    preamble = src[max(0, i - 1800):i]
    assert "P16-09" in preamble
    assert "executes it" in preamble or "execute" in preamble


def test_the_diffusion_server_exclusion_is_deliberate_and_written_down():
    """It still passes trust_remote_code and that is a decision, not an oversight.

    If this file ever stops explaining the distinction, the exclusion above
    becomes an unexplained hole rather than a scoped one.
    """
    script = REPO / "scripts/diffusion_server.py"
    if not script.exists():
        pytest.skip("diffusion server not present")
    assert "trust_remote_code" in script.read_text(encoding="utf-8")

    src = (REPO / "routes/gallery/gallery_routes.py").read_text(encoding="utf-8")
    assert "diffusion_server.py" in src, (
        "the app no longer records why the diffusion server is treated differently"
    )
