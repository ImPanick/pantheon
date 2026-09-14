# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B02` — the backend's decode fallback, reached from the UI.

`POST /api/email/attachment-as-doc` handles six suffixes explicitly and then
sniffs the bytes: anything that decodes as text opens as a markdown document,
extensionless files included. Two independent frontend gates kept that branch
unreachable:

* `emailLibrary.js` rendered the "Open in document editor" button only for
  ``/\\.(pdf|docx|txt|md|markdown|eml)$/i`` — the same six. A `.log`, `.csv`,
  `.json`, `.yaml` or extensionless attachment had **no Open affordance at
  all**, not a disabled one.
* `document.js`'s email-compose attachment strip gated on `isPdf` — ONE suffix.
  The row names only the first, so dropping only the regex would have left this
  one live: `Law 13`, a feature set in one of N places.

Both are gone. The cost of dropping them is an Open button on `photo.png`,
whose answer is `{"error": "Unsupported attachment type: .png"}` — handled by
falling back to the download route, the shape `document.js` already used, and
not by a client-side binary denylist, which would be the same gate inverted.

Everything here drives the real functions under node (`Law 20`). Three
harnesses, because three different things can be wrong: the markup that offers
the affordance, where a click lands when the backend refuses, and whether the
second file's chips still download.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
H_BUTTON = ROOT / "tests" / "harness" / "email_attachment_open_button.js"
H_CLICK = ROOT / "tests" / "harness" / "email_attachment_open_click.js"
H_CHIP = ROOT / "tests" / "harness" / "doc_email_attachment_chip.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The six suffixes the removed gate allowed, and the ones it did not. The
# second list is drawn from the backend's own docstring for the fallback plus
# the extensionless case it calls out.
PRE_EXISTING = ("report.pdf", "letter.docx", "notes.txt", "readme.md", "spec.markdown", "fwd.eml")
NEWLY_REACHABLE = (
    "server.log", "rows.csv", "config.json", "stack.yaml", "setup.ini",
    "script.py", "page.html", "schema.sql", "pyproject.toml", "data.tsv",
    "LICENSE", "Makefile",
)


def _run(harness: Path, *argv: str) -> dict:
    proc = subprocess.run(["node", str(harness), *argv], capture_output=True, text=True)
    assert proc.returncode == 0, f"{harness.name} {argv}: {proc.stderr}"
    return json.loads(proc.stdout)


# ── Gate one: the email reader's chip markup ────────────────────────────────


def test_the_six_suffixes_that_already_worked_still_do():
    """`Law 1` first. The elevation adds; it must not cost the pdf/docx/txt/
    md/markdown/eml attachments the button they have today."""
    out = _run(H_BUTTON)
    for name in PRE_EXISTING:
        assert out["perName"][name]["open"], name


@pytest.mark.parametrize("name", NEWLY_REACHABLE)
def test_a_text_attachment_the_backend_can_open_now_has_a_button(name):
    """The row's `Verify`, generalised: *a `.log` attachment opens in the
    editor*. Each of these decodes as text, so `attachment-as-doc` returns a
    doc_id for it — and until now the user had nothing to click."""
    out = _run(H_BUTTON)
    assert out["perName"][name]["chipped"], f"{name} was not even chipped"
    assert out["perName"][name]["open"], f"{name} still has no Open affordance"


def test_the_open_button_carries_the_filename_it_belongs_to():
    """The chips are built by string concatenation in one template literal, so
    an off-by-one in the markup would attach the wrong `data-open-name` and the
    click handler would open a different attachment."""
    out = _run(H_BUTTON)
    for name, got in out["perName"].items():
        assert got["openName"] == name, f"{name} carries data-open-name={got['openName']}"


def test_every_chip_gets_exactly_one_open_affordance():
    """No gate left, and none accidentally rendered twice."""
    out = _run(H_BUTTON)
    assert out["openCount"] == out["chipCount"] == 20


# ── Gate one, the click: where an unsupported attachment lands ──────────────


def test_a_binary_attachment_falls_back_to_the_download_route():
    """The whole reason the gate could be dropped. The backend answers a
    binary attachment with **HTTP 200** and an `error` key — `res.ok` is true,
    so only `json.doc_id` separates the two outcomes — and this used to end in
    a toast with nothing behind it."""
    out = _run(H_CLICK, "unsupported")
    assert out["opened"] == [
        "https://host/api/email/attachment/42/3?folder=Archive&account_id=a1"
    ], "the click dead-ended instead of handing over the download"
    assert out["toasts"][0]["kind"] == "error"
    assert "photo.png" in out["toasts"][0]["msg"]
    assert "Unsupported attachment type: .png" in out["toasts"][0]["msg"], (
        "the server's reason was swallowed"
    )


def test_the_fallback_url_carries_the_folder_and_the_account():
    """A multi-account mailbox opens the wrong message — or nothing — if the
    download URL drops either query parameter the as-doc call sent."""
    out = _run(H_CLICK, "unsupported")
    url = out["opened"][0]
    assert "folder=Archive" in url
    assert "account_id=a1" in url


def test_a_successful_open_does_not_also_start_a_download():
    """Two tabs for one click is the obvious way to get this wrong."""
    out = _run(H_CLICK, "opened")
    assert out["loaded"] == ["doc-1"]
    assert out["opened"] == []
    assert out["toasts"] == []


def test_a_timeout_is_not_treated_as_a_refusal():
    """The 55s abort already advises downloading. Starting a download a minute
    after the click, unasked, is not a fallback — and the handler cannot know
    the attachment was even unsupported."""
    out = _run(H_CLICK, "timeout")
    assert out["opened"] == []
    assert "timed out" in out["toasts"][0]["msg"]


@pytest.mark.parametrize("mode", ["unsupported", "opened", "timeout", "http-500"])
def test_the_button_is_always_released(mode):
    """`dataset.opening` is the re-entrancy guard. A path that returns without
    clearing it leaves the button permanently dead — and the unsupported path
    is a new early return."""
    out = _run(H_CLICK, mode)
    assert out["stillBusy"] is False
    assert out["loadingClassLeft"] is False
    assert out["innerHtmlRestored"] is True


# ── Gate two: document.js's email-compose attachment strip ──────────────────


def test_a_log_attachment_in_the_compose_strip_can_reach_as_doc():
    """The gate the row never mentions. Before this, only `.pdf` called
    `attachment-as-doc` from this file; a `.log` chip had one behaviour and it
    was download."""
    out = _run(H_CHIP, "log-open")
    assert out["chipHtmlHasOpen"] is True
    assert out["asDocCalls"] == 1
    assert out["loaded"] == ["doc-9"]


def test_the_compose_strip_still_downloads_on_a_chip_click():
    """`Law 1`, and the branch's own comment: the blob path exists because
    `target=_blank` did nothing in some browsers. Adding an Open affordance
    must not take the Save dialog away."""
    out = _run(H_CHIP, "log-chip")
    assert out["asDocCalls"] == 0, "a plain chip click was diverted into the editor"
    assert out["downloadRouteCalls"] == 1
    assert out["downloads"] == [{"href": "blob:1", "name": "server.log"}]


def test_a_pdf_chip_opens_exactly_as_it_did():
    """The one attachment type that could already reach as-doc keeps its
    click, its chip class and its single request."""
    out = _run(H_CHIP, "pdf-chip")
    assert "email-attachment-chip-pdf" in out["chipClass"]
    assert out["asDocCalls"] == 1
    assert out["loaded"] == ["doc-9"]
    assert out["chipHtmlHasOpen"] is False, (
        "the PDF chip's whole body already opens; a second Open is two controls "
        "for one action"
    )


def test_the_compose_strip_falls_back_to_download_too():
    """Both files now answer a refusal the same way. This is the assertion
    that keeps them the same: one `_openAsDoc` serves the PDF chip and the Open
    span, so a fallback removed from either is removed from both and fails
    here."""
    out = _run(H_CHIP, "png-open")
    assert out["opened"] == ["https://host/api/email/attachment/99/7?folder=Archive"]
    assert out["loaded"] == []
    assert "Unsupported attachment type: .png" in out["errors"][0]
