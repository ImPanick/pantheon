# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B03` — what the browser does with the `rejected` half of an upload.

`POST /api/upload` used to fail the whole request when any file was refused.
`P2-11` made a partial batch answer **200** with `{"files": [...], "rejected":
[...]}`, keeping the bytes that landed. `tests/test_upload_multifile.py` pins
that the server reports both halves; nothing pinned that a client reads the
second one, and none of the six frontend call sites did.

Between "the server tells you" and "the browser surfaces errors" sat exactly
the uncovered case, and two defects lived in it:

* the refused files vanished. `pendingFiles` was cleared on any 2xx, so they
  left the composer with no message and nothing to retry.
* **worse, and unstated by the row**: `chat.js` paired `_pendingAttachInfo`
  (input order, five entries) to `ids` (compacted, three) by index, so the
  user's own message bubble showed the wrong thumbnail under the right
  filename. Mis-attribution, not omission, and no toast fixes it.

`Law 20`: these drive the real functions under node rather than reading them.
The pairing in particular is invisible to a source-level check — the defect is
*which of two arrays an index belongs to*, and both are in scope on the same
line.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
H_TOAST = ROOT / "tests" / "harness" / "upload_rejection_toast.js"
H_UPLOAD = ROOT / "tests" / "harness" / "upload_pending_partial.js"
H_PAIR = ROOT / "tests" / "harness" / "attach_bubble_pairing.js"
H_MD = ROOT / "tests" / "harness" / "markdown_image_insert.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _run(harness: Path, *argv: str) -> dict:
    proc = subprocess.run(["node", str(harness), *argv], capture_output=True, text=True)
    assert proc.returncode == 0, f"{harness.name} {argv}: {proc.stderr}"
    return json.loads(proc.stdout)


# ── The message: ui.js's one helper ─────────────────────────────────────────


def test_the_message_names_the_files_that_did_not_upload():
    """The row's `Verify` verbatim: *drop 30 files, see a message naming the 5
    that did not upload.* A count alone does not tell the user which chip to
    retry."""
    out = _run(H_TOAST, "five")
    assert out["namesInText"] == 5, out["text"]
    assert out["returned"] == 5


def test_the_message_carries_the_server_s_reason():
    out = _run(H_TOAST, "one")
    assert "huge.zip" in out["text"]
    assert "File size exceeds 100.0 MB limit" in out["text"], out["text"]


def test_a_shared_reason_is_said_once():
    """A rate limit refuses the tail of a batch, so every entry carries the
    same detail. Five copies of one sentence is not a message."""
    out = _run(H_TOAST, "five")
    assert out["text"].count("Upload rate limit exceeded") == 1, out["text"]


def test_more_names_than_fit_are_counted_not_dropped():
    """Nine rejects, five named. The other four have to be accounted for or
    the user is told less than the truth."""
    out = _run(H_TOAST, "nine")
    assert out["namesInText"] == 5
    assert "and 4 more" in out["text"], out["text"]
    assert out["returned"] == 9


def test_two_different_reasons_are_not_collapsed_into_one():
    """Saying only "File is empty" for a batch where one file was empty and
    another was rate-limited tells the second file's owner the wrong thing."""
    out = _run(H_TOAST, "mixed")
    assert "File is empty" in out["text"]
    assert "other reason" in out["text"], out["text"]


def test_it_goes_to_the_error_toast():
    """`showError` is dismissible and lasts 6s; `showToast` is 1.2s and styled
    as success. A refusal that reads as a success is the defect again in a
    different colour."""
    out = _run(H_TOAST, "five")
    assert out["shown"] is True
    assert out["isErrorToast"] is True


@pytest.mark.parametrize("mode", ["empty", "notanarray"])
def test_a_clean_batch_says_nothing(mode):
    """`rejected` is absent from a clean response, and every caller passes
    whatever it found. A helper that toasts on an empty list puts an error in
    front of a user whose upload worked."""
    out = _run(H_TOAST, mode)
    assert out["returned"] == 0
    assert out["shown"] is False
    assert out["text"] == ""


@pytest.mark.parametrize("mode", ["nameless", "reasonless"])
def test_a_half_filled_rejection_still_produces_a_message(mode):
    """`u.filename` can be empty and the 500 branch writes a generic error. A
    missing field must not silence the whole toast."""
    out = _run(H_TOAST, mode)
    assert out["returned"] == 1
    assert out["shown"] is True
    assert out["text"].strip() != ""


# ── The composer: uploadPending reads both halves ───────────────────────────


def test_the_rejections_are_surfaced_through_the_shared_helper():
    """`Law 13`. Both call sites go through `ui.js`'s helper — the composer
    building its own sentence is how it and the editor end up describing the
    same response differently."""
    out = _run(H_UPLOAD, "partial")
    assert len(out["rejectionCalls"]) == 1
    names = [r["name"] for r in out["rejectionCalls"][0]["rejected"]]
    assert names == ["b.png", "d.png"]


def test_the_refused_files_stay_in_the_composer():
    """`clear only on success` was the rule and a 200 carrying `rejected` is
    not one. The user cannot retry a file that is no longer there."""
    out = _run(H_UPLOAD, "partial")
    assert out["pendingNames"] == ["b.png", "d.png"]


def test_the_files_that_landed_are_dropped_from_the_composer():
    """The other half of that decision: keeping them would re-upload bytes the
    server already has on the retry, and leave chips for files that were sent."""
    out = _run(H_UPLOAD, "partial")
    assert "a.png" not in out["pendingNames"]
    assert out["ids"] == ["id-a.png", "id-c.png", "id-e.png"]


def test_a_clean_batch_still_clears_everything():
    out = _run(H_UPLOAD, "clean")
    assert out["pendingNames"] == []
    assert out["rejectionCalls"] == []
    assert len(out["ids"]) == 5


def test_the_strip_is_re_rendered_so_the_kept_chips_reappear():
    """Keeping the Files is invisible if nothing redraws the strip."""
    out = _run(H_UPLOAD, "partial")
    assert out["renders"] >= 1


def test_the_outcome_reconstructs_which_id_belongs_to_which_file():
    """`files` is compacted, so this correspondence exists nowhere else.
    Rebuilt from `rejected[].name`, which is the RAW form filename — the
    accepted entries come back `secure_filename()`'d (`a.png` → `A_PNG` in the
    harness), so matching on those would find nothing."""
    out = _run(H_UPLOAD, "partial")
    assert [(o["name"], o["accepted"], o["id"]) for o in out["outcome"]] == [
        ("a.png", True, "id-a.png"),
        ("b.png", False, None),
        ("c.png", True, "id-c.png"),
        ("d.png", False, None),
        ("e.png", True, "id-e.png"),
    ]


def test_two_attachments_sharing_a_name_consume_one_rejection_each():
    """A browser will hand you the same filename twice from two folders. A
    membership test would call both copies rejected and shift every id after
    them; the rejections are counted instead."""
    out = _run(H_UPLOAD, "dup")
    assert [(o["name"], o["accepted"]) for o in out["outcome"]] == [
        ("a.png", False), ("a.png", True), ("z.png", True),
    ]
    assert out["pendingNames"] == ["a.png"]


def test_the_wire_name_is_what_the_pairing_keys_on():
    """The FormData append and the pairing have to agree on the name. They did
    not: the append used `'paste.png'` for a nameless blob while
    `getPendingInfo()` used `'pasted-image'`. One `_wireName` now feeds both."""
    out = _run(H_UPLOAD, "partial")
    assert [a["name"] for a in out["appended"]] == ["a.png", "b.png", "c.png", "d.png", "e.png"]
    assert [o["name"] for o in out["outcome"]] == [a["name"] for a in out["appended"]]


def test_the_composer_publishes_the_name_it_posted_under():
    """`getPendingInfo()` is what chat.js pairs on, and it published only the
    DISPLAY name — which diverges from the posted one for a nameless blob
    ('pasted-image' vs 'paste.png'). Both now come off one `_wireName`, and the
    retry chips carry it too."""
    out = _run(H_UPLOAD, "partial")
    posted = [a["name"] for a in out["appended"]]
    assert [i["uploadName"] for i in out["pendingInfo"]] == ["b.png", "d.png"]
    assert all(i["uploadName"] in posted for i in out["pendingInfo"])
    # The display name is unchanged — the second field was added, not swapped.
    assert [i["name"] for i in out["pendingInfo"]] == ["b.png", "d.png"]


def test_a_pairing_that_does_not_add_up_is_not_published():
    """If the rejected names cannot be found among the submitted files, the
    compaction is not recoverable and every id after the first gap would be
    attributed by guesswork. Publish nothing instead, so callers fall back to
    what they did before rather than to something confidently wrong."""
    out = _run(H_UPLOAD, "unreconciled")
    assert out["outcome"] == []
    assert out["pendingNames"] == [], (
        "an unreconciled batch must keep the pre-existing clear, not invent a "
        "set of files to hold back"
    )


def test_a_second_upload_cannot_read_the_first_ones_results():
    """A partial batch leaves two files pending; retrying them fails outright.
    The first batch's outcome and rejections must not still be readable, or
    chat.js pairs this message's attachments against the previous upload."""
    out = _run(H_UPLOAD, "stale")
    assert out["ids"] == []
    assert out["outcome"] == []
    assert out["rejected"] == []
    assert out["pendingNames"] == ["b.png", "d.png"]


# ── The bubble: chat.js stops mis-attributing ───────────────────────────────


def test_a_partial_batch_does_not_shift_ids_onto_the_wrong_attachment():
    """The unstated defect. `[a, b✗, c, d✗, e]` returns three ids; pairing by
    index gave row `b` the id of `c`, so the bubble rendered `c`'s thumbnail
    under the caption `b.png`."""
    out = _run(H_PAIR, "partial")
    stamped = {row["name"]: row["id"] for row in out["stamped"]}
    assert stamped == {
        "a.png": "id-a.png", "b.png": None, "c.png": "id-c.png",
        "d.png": None, "e.png": "id-e.png",
    }


def test_the_dimensions_follow_the_same_pairing():
    """Width/height come from the same compacted array, so they mis-attributed
    with the ids — a portrait skeleton sized from a landscape photo."""
    out = _run(H_PAIR, "partial")
    widths = {row["name"]: row["width"] for row in out["stamped"]}
    assert widths == {"a.png": 10, "b.png": None, "c.png": 11, "d.png": None, "e.png": 12}


def test_a_refused_file_is_not_shown_in_the_users_own_message():
    """It was never sent with that message. Leaving its card in claims
    something that did not happen, and with no id it renders as a pre-upload
    skeleton that never resolves."""
    out = _run(H_PAIR, "partial")
    assert [row["name"] for row in out["rendered"]] == ["a.png", "c.png", "e.png"]


def test_a_clean_batch_pairs_exactly_as_before():
    """`Law 1`. With nothing rejected the two orderings coincide, and every
    attachment must still get its own id."""
    out = _run(H_PAIR, "clean")
    assert [row["id"] for row in out["stamped"]] == [f"id-{n}" for n in
                                                     ("a.png", "b.png", "c.png", "d.png", "e.png")]
    assert len(out["rendered"]) == 5


def test_a_same_length_outcome_from_another_batch_is_rejected_by_name():
    """The length check alone cannot separate this batch from another of the
    same size — a queue drain of five files while five sit in the composer. The
    per-row name is what does it, and without it every row would take an id
    belonging to a different file. Nothing is stamped, so the bubble keeps its
    pre-upload cards rather than showing five wrong thumbnails."""
    out = _run(H_PAIR, "drain-same-size")
    assert [row["id"] for row in out["stamped"]] == [None] * 5
    assert [row["width"] for row in out["stamped"]] == [None] * 5


def test_an_outcome_from_a_different_upload_is_not_believed():
    """A queue drain uploaded its files when the item was queued, so the
    module's last outcome describes somebody else's batch. Length and per-row
    name are both checked before any of it is trusted; failing that check falls
    back to the previous positional behaviour rather than stamping nothing."""
    out = _run(H_PAIR, "drain")
    assert [row["id"] for row in out["stamped"]] == [f"id-{n}" for n in
                                                    ("a.png", "b.png", "c.png", "d.png", "e.png")]


# ── The second consumer: the markdown image insert ──────────────────────────


def test_the_editor_does_not_claim_success_for_images_it_did_not_insert():
    """The editor's own version of the defect: the toast was counted off the
    files the user PICKED, while only `data.files` were inserted. Five chosen,
    two refused, three in the document — and it said "Images inserted"."""
    out = _run(H_MD, "partial")
    assert out["inserted"] == ["one.png", "three.png", "five.png"]
    assert out["toasts"] == [], "a success toast for a batch that was not a success"
    assert out["rejectionCalls"][0]["names"] == ["two.png", "four.png"]
    assert out["rejectionCalls"][0]["opts"]["suffix"] == "3 images inserted.", (
        "the count has to come from what landed, not from what was chosen"
    )


def test_both_consumers_go_through_the_same_helper():
    """`Law 13` stated as a test. The composer and the editor describe the same
    `rejected` array, so they must not each build their own sentence — a copy
    drifts, and the drift is invisible until two users compare screenshots.
    Both harnesses observe a call to `ui.js`'s helper, not a message."""
    composer = _run(H_UPLOAD, "partial")
    editor = _run(H_MD, "partial")
    assert len(composer["rejectionCalls"]) == 1
    assert len(editor["rejectionCalls"]) == 1


@pytest.mark.parametrize("mode,expected", [("clean", "Images inserted"), ("single", "Image inserted")])
def test_a_clean_insert_still_says_what_it_always_said(mode, expected):
    """`Law 1`. The strings and the singular/plural split are unchanged for the
    case that already worked."""
    out = _run(H_MD, mode)
    assert out["toasts"] == [expected]
    assert out["rejectionCalls"] == []


# ── The dead identifier the row's Law 14 note is about ──────────────────────


def test_nothing_reads_window_showtoast():
    """The one text assertion in this file, and deliberately so: the property
    is *this identifier is written by nobody*, and a call that never fires has
    no behaviour to drive (`Law 20` is about grepping INSTEAD of running, not
    about a claim that is only about text).

    `window.showToast` had three readers and zero writers. `fileHandler.js`
    took its private fallback every time — proved by running it, in
    `tests/test_upload_error_surfaced.py` — while `chatRenderer.js:1868` and
    `:1873` simply did nothing at all: attaching a generated image to the
    composer reported neither success nor failure, and had not since the lines
    were written. Both now call `ui.js`.

    A reader coming back is a fourth silent call site, so the count is held at
    zero rather than at three.
    """
    readers = []
    for path in sorted((ROOT / "static").rglob("*.js")):
        if "/lib/" in str(path):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue          # the comments explaining this are not readers
            if "window.showToast" in line:
                readers.append(f"{path.relative_to(ROOT)}:{lineno}")
    assert readers == [], (
        "nothing in the tree assigns `window.showToast`, so each of these is a "
        f"message the user will never see — call ui.js instead: {readers}"
    )
