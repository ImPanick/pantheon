# SPDX-License-Identifier: AGPL-3.0-or-later
"""Upload failures reach the user — the guarantee, not the source text.

This file is named for the property `B03` found broken, and it passed the whole
time it was broken. Two reasons, both worth stating because both are reusable
mistakes:

1. **It asserted a branch, not a behaviour.** `re.search(r"if\\s*\\(\\s*!res\\.ok\\s*\\)")`
   plus `"Upload failed" in body`. Both stayed true when `/api/upload` started
   answering a partial batch with **200 + `rejected`**: that response never
   enters the `!res.ok` branch, so the files the server refused disappeared
   with no message while this test stayed green. A test that greps a file is
   testing the file (`Law 20`).

2. **Its docstring was wrong about what is possible.** It said "fileHandler.js
   pulls in browser globals so it can't run under node; guard the fix at the
   source level." `tests/harness/copy_text.js` had already refuted that for
   `ui.js`, and `tests/harness/upload_pending_partial.js` now runs this very
   function — `uploadPending`, browser globals and all — under node. The claim
   is what licensed the weak assertion, so it is removed rather than softened.

What stays is the guarantee the file is named for, now driven rather than read:
a failed upload tells the user, and does not silently eat the attachments. The
partial-failure half lives in `tests/test_upload_rejections_reach_the_user.py`.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "harness" / "upload_pending_partial.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _run(mode: str) -> dict:
    proc = subprocess.run(["node", str(HARNESS), mode], capture_output=True, text=True)
    assert proc.returncode == 0, f"{mode}: {proc.stderr}"
    return json.loads(proc.stdout)


def test_a_non_ok_response_is_surfaced_and_not_swallowed():
    """The original guarantee (issue #1346): a 429 / 413 must not vanish. The
    server's own reason is shown, because "Upload failed" alone does not tell
    the user whether to wait or to shrink the file."""
    out = _run("http-429")
    assert out["toasts"], "a non-OK upload produced no message at all"
    msg = out["toasts"][0]["msg"]
    assert "Upload failed" in msg
    assert "Maximum concurrent uploads (3) exceeded" in msg, msg


def test_a_failed_upload_keeps_the_attachments_for_a_retry():
    """The other half of #1346 — the files "silently vanished and the chat sent
    with no attachments". Asserted on `pendingFiles` itself, which is what the
    composer re-renders from."""
    out = _run("http-429")
    assert out["pendingNames"] == ["a.png", "b.png", "c.png", "d.png", "e.png"]
    assert out["ids"] == []


def test_a_cancelled_upload_says_so_and_keeps_the_files():
    """An abort is not a failure, but it is also not a send. Both had to keep
    the strip intact."""
    out = _run("abort")
    assert out["toasts"][0]["msg"] == "Upload cancelled"
    assert out["pendingNames"] == ["a.png", "b.png", "c.png", "d.png", "e.png"]


@pytest.mark.parametrize("mode", ["http-429", "abort", "partial"])
def test_the_message_goes_through_ui_js_and_not_a_private_toast(mode):
    """`Law 14`. `_showToast` read `window.showToast` and, failing that, built
    its own `#_attach-toast` div. `window.showToast` is assigned NOWHERE in the
    tree — three files read it, zero write it — so the private div was the only
    path this function had ever taken, and a second toast implementation had
    been living beside `ui.js`'s the whole time.

    The harness's `window` has no `showToast`, exactly like production, and
    records everything parked on `document.body`. A re-introduced fallback
    shows up here as a node, not as a missing message."""
    out = _run(mode)
    assert out["privateToastNodes"] == 0, (
        "fileHandler built its own toast element again instead of calling ui.js"
    )
    assert out["nodesAppendedToBody"] == 0
