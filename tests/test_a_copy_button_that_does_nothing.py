# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B59` — one clipboard helper, and the order is the whole row.

**The browser only lets a page write the clipboard while it is still inside the
user's gesture, and an `await` ends that.** The continuation after an `await`
runs in a microtask, by which time the gesture is over. So a helper that tries
`navigator.clipboard.writeText` first and falls back to `execCommand` in its
`catch` has put the reliable path on the far side of the thing that makes it
unreliable. `ui.js` was that helper, with thirteen callers. `codeRunner.js`
argued the correct order in a comment and implemented it twice.

**THE ROW UNDERCOUNTED, AND THE RE-MEASUREMENT IS THE POINT.** It was filed as
*three implementations*. There are eleven files with their own `execCommand`
copy and nineteen touching `navigator.clipboard`, across twenty-three call
sites — and two of those had **no fallback at all**:

  * `admin.js`'s API-token copy button — a bare
    `navigator.clipboard.writeText(v).then(...)`, no `catch`. Over plain `http`
    on a LAN `navigator.clipboard` is `undefined`, so the property access threw,
    nothing was copied, nothing was said. On the one control in this app that
    shows a token **once**.
  * `tasks.js`'s webhook-URL button — same shape, and it said **`Copied`**
    afterwards regardless. The line directly above it in the same template warns
    to rotate the URL if it leaks.

Both are the deployment `Law 17` calls normal. Neither was a hypothetical.

**A checker rather than a sweep.** `check-clipboard.py` counts `writeText` call
sites with no fallback anywhere near them, and the ceiling is **zero** — which
it now is. Image copies via `ClipboardItem` are exempt by the shape of the
problem: `execCommand` cannot copy an image, so there is no legacy path to fall
back to.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HARNESS = ROOT / "tests" / "harness" / "copy_text.js"
CHECKER = ROOT / ".pantheon" / "check-clipboard.py"


def run(mode, wrapper=False):
    proc = subprocess.run(
        ["node", str(HARNESS), mode, "wrapper" if wrapper else "-"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# --------------------------------------------------------------------------
# The property the row asks for, which cannot be read out of the file
# --------------------------------------------------------------------------


def test_the_copy_happens_before_the_first_await():
    """*A test that the gesture path is synchronous* — the row's own `Verify`.

    The harness calls `copyText` and does **not** await it, then looks at what
    has already run. Anything in `synchronous` happened inside what would be
    the user's gesture. Put a single `await` above the `execCommand` and this
    fails.
    """
    out = run("legacy-ok")
    assert "execCommand:copy" in out["synchronous"], (
        "the copy is on the far side of an await — the gesture is gone by then"
    )
    assert out["synchronous"].index("select") < out["synchronous"].index("execCommand:copy")


def test_the_clipboard_api_is_not_touched_when_the_legacy_path_worked():
    """It is a backup. Calling it anyway is a second permission prompt on some
    browsers for a copy that already happened."""
    out = run("legacy-ok")
    assert out["ok"] is True
    assert "writeText" not in out["full"]


def test_the_clipboard_api_is_the_backup_and_still_runs():
    for mode in ("legacy-throws", "no-execCommand"):
        out = run(mode)
        assert out["ok"] is True, mode
        assert "writeText" in out["full"], mode


# --------------------------------------------------------------------------
# The deployment this fork ships for
# --------------------------------------------------------------------------


def test_over_plain_http_it_reports_failure_rather_than_pretending():
    """`insecure`: `execCommand` refused and `isSecureContext` is false, so
    there is nowhere left to go. **Saying so is the feature** — the two call
    sites this row was worth doing for both announced success instead."""
    out = run("insecure")
    assert out["ok"] is False
    assert "writeText" not in out["full"], (
        "the clipboard API was called in a non-secure context, where it throws"
    )


def test_a_missing_clipboard_object_is_a_branch_and_not_an_exception():
    out = run("no-clipboard")
    assert out["ok"] is False


def test_a_rejecting_clipboard_api_reports_failure():
    out = run("clipboard-rejects")
    assert out["ok"] is False


# --------------------------------------------------------------------------
# What the harness found that reading would not have
# --------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["legacy-ok", "legacy-throws", "no-execCommand",
                                  "insecure", "clipboard-rejects", "no-clipboard"])
def test_the_textarea_is_always_removed(mode):
    """A failed copy must not leave an off-screen textarea in the page.

    `ta.remove()` was the last statement of the `try`, so an `execCommand` that
    **throws** — a permissions policy can make it — skipped the removal and
    leaked one element per failed copy, forever. Found by running the six
    branches, not by reading them: the leak is invisible in the source because
    the removal is right there in the block.
    """
    assert "remove" in run(mode)["full"], f"{mode} leaked the textarea"


def test_the_value_reaches_the_textarea():
    assert run("legacy-ok")["value"] == "hello"


# --------------------------------------------------------------------------
# The ratchet
# --------------------------------------------------------------------------


def test_no_clipboard_call_anywhere_is_left_without_a_fallback():
    proc = subprocess.run([sys.executable, str(CHECKER), "--max", "0", "--list"],
                          capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "unguarded 0" in proc.stdout


def test_the_checker_catches_a_bare_call(tmp_path, monkeypatch):
    """The checker's own claim, against a file that has the defect.

    Written because a checker reporting zero is indistinguishable from a
    checker that cannot see anything.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_clipboard", CHECKER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    bad = ROOT / "static" / "js" / "__b59_probe.js"
    bad.write_text("function f(){ navigator.clipboard.writeText('x'); }\n", encoding="utf-8")
    try:
        monkeypatch.setattr(mod, "tracked", lambda: ["static/js/__b59_probe.js"])
        problems = mod.unguarded()
        assert len(problems) == 1
        assert problems[0][0] == "static/js/__b59_probe.js"

        good = "function f(){ if (!await uiModule.copyText('x')) {} }\n"
        bad.write_text(good, encoding="utf-8")
        assert mod.unguarded() == []
    finally:
        bad.unlink(missing_ok=True)


def test_an_image_copy_is_exempt_by_shape_not_by_name(monkeypatch):
    """`execCommand` cannot copy an image, so there is no fallback to demand.

    Asserted as behaviour rather than as an allowlist entry: the rule matches
    `writeText` and an image copy uses `write`.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_clipboard", CHECKER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    probe = ROOT / "static" / "js" / "__b59_img.js"
    probe.write_text(
        "navigator.clipboard.write([new ClipboardItem({'image/png': b})]);\n",
        encoding="utf-8")
    try:
        monkeypatch.setattr(mod, "tracked", lambda: ["static/js/__b59_img.js"])
        assert mod.unguarded() == []
    finally:
        probe.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# The two sites the row was worth doing for
# --------------------------------------------------------------------------


def test_the_token_button_does_not_claim_success_it_did_not_have():
    """A checkmark on a failed copy is worse than no button: it says the token
    is on the clipboard when it is not, and it is shown once."""
    admin = (ROOT / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    handler = admin[admin.index("adm-tokenCopyBtn').addEventListener"):]
    handler = handler[: handler.index("}, 1600);")]
    assert "copyText" in handler
    assert "if (!ok)" in handler, "the success path runs whatever happened"
    assert handler.index("if (!ok)") < handler.index("TOKEN_CHECK_ICON")


def test_the_webhook_button_no_longer_says_copied_regardless():
    tasks = (ROOT / "static" / "js" / "tasks.js").read_text(encoding="utf-8")
    # The listener, not the button markup 3 lines above it that shares the id.
    handler = tasks[tasks.index("task-form-webhook-copy')?.addEventListener"):]
    handler = handler[: handler.index("task-form-webhook-rotate")]
    assert "copyText" in handler
    assert "'Copied' : 'Copy failed'" in handler


def test_the_shared_helper_keeps_its_thirteen_callers_working():
    """`Law 1`. `copyToClipboard` still toasts, because every existing caller
    relies on it doing so; only the mechanism moved."""
    out = run("legacy-ok", wrapper=True)
    assert out["ok"] is True
    assert out["toasts"] == ["Copied"]
    assert "execCommand:copy" in out["synchronous"], (
        "the wrapper lost the synchronous path its callers inherit"
    )


def test_the_shared_wrapper_does_not_claim_success_it_did_not_have():
    """**The mutation that survived the first run.**

    Every assertion above pinned `copyText`, and `copyToClipboard` — the
    function thirteen callers actually use — could still say `Copied`
    unconditionally. That is the exact defect this row is about, in the one
    place it would reach the most buttons: a toast saying the text is on your
    clipboard when nothing is.

    The wrapper's text was asserted, and reading that `showToast` appears says
    nothing about what it is handed.
    """
    out = run("insecure", wrapper=True)
    assert out["ok"] is False
    assert out["toasts"] == ["Copy failed"], (
        "the shared wrapper announces a copy that did not happen"
    )
