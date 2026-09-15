# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B77` — byte-identical uploads keep their own names, end to end.

`save_upload` matched a new upload against `uploads.json` on ``hash == file_hash
and owner == owner`` and returned the existing row unchanged. Driven through the
real handler: upload `notes.md`, then a byte-identical `config.yaml`, and the
second call answered ``id=<same>.md name=notes.md mime=text/markdown``. The
bytes were by definition right; the identity was the other file's.

Identity is load-bearing downstream, so these tests follow it all the way to the
model rather than stopping at the returned dict: `_process_text_file` takes the
fence language and the ``[Type: …]`` label from the file it is handed, the chat
route hands the model `display_name`, and `download_file` sets
``Content-Disposition: filename=``. Every one of those was answering with the
first file's name.

`Law 1` is the constraint that shapes the fix: dedup must still dedup. The same
file uploaded twice is still one row, one id and one copy on disk.
"""
import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.document_processor import build_user_content, upload_display_name  # noqa: E402
from src.upload_handler import UploadHandler  # noqa: E402

SAME_BYTES = b"shared: true\nvalue: 1\n"


def _handler(tmp_path):
    base = tmp_path / "base"
    uploads = tmp_path / "uploads"
    base.mkdir()
    uploads.mkdir()
    handler = UploadHandler(base_dir=str(base), upload_dir=str(uploads))
    handler.upload_rate_limit = 500
    return handler


def _upload(handler, name, body=SAME_BYTES, owner="owner_a"):
    return handler.save_upload(
        SimpleNamespace(filename=name, file=io.BytesIO(body)), "127.0.0.1", owner
    )


def _index(handler):
    with open(os.path.join(handler.upload_dir, "uploads.json"), encoding="utf-8") as f:
        return json.load(f)


def _render(handler, meta, owner="owner_a"):
    """Drive the real build_user_content over what save_upload actually returned."""
    resolved = {"fid": handler.resolve_upload(meta["id"], owner=owner)}
    out = build_user_content(
        "read this", ["fid"], handler.upload_dir, handler,
        owner=owner, resolved_uploads=resolved,
    )
    return out if isinstance(out, str) else "".join(
        b.get("text", "") for b in out if isinstance(b, dict)
    )


# ---------------------------------------------------------------------------
# The defect
# ---------------------------------------------------------------------------

def test_the_second_file_is_not_served_under_the_first_files_name(tmp_path):
    """The row's `Verify`, at the handler boundary."""
    handler = _handler(tmp_path)
    first = _upload(handler, "notes.md")
    second = _upload(handler, "config.yaml")

    assert second["id"] != first["id"]
    assert second["name"] == "config.yaml"
    assert second["mime"] != first["mime"]
    assert not second.get("is_duplicate")
    assert os.path.exists(first["path"]) and os.path.exists(second["path"])


def test_both_attachments_tell_the_model_what_they_are(tmp_path):
    """The reason the returned dict matters: it decides what the model is told.

    The same bytes rendered as ```markdown under `notes.md` and must render as
    ```yaml under `config.yaml`. This is the assertion a fix that only relabels
    the composer chip cannot pass.
    """
    handler = _handler(tmp_path)
    md = _render(handler, _upload(handler, "notes.md"))
    yml = _render(handler, _upload(handler, "config.yaml"))

    assert "=== File: notes.md ===" in md
    assert "[Type: markdown" in md and "```markdown" in md
    assert "=== File: config.yaml ===" in yml
    assert "[Type: yaml" in yml and "```yaml" in yml


def test_two_extensionless_files_are_told_apart(tmp_path):
    """The row's own headline case, and why the key is the name and not the suffix.

    The row proposed keying on the content hash *and the extension*. Two
    projects' `LICENSE` — and `LICENSE` against `COPYING` — are both
    extensionless, so that key collapses exactly the example the row was filed
    for. Measured before the fix: both returned one id and one name.
    """
    handler = _handler(tmp_path)
    mit = b"MIT License\n\nPermission is hereby granted...\n"
    first = _upload(handler, "LICENSE", mit)
    second = _upload(handler, "COPYING", mit)

    assert first["id"] != second["id"]
    assert {first["name"], second["name"]} == {"LICENSE", "COPYING"}
    assert "COPYING" in _render(handler, second)


def test_the_model_is_told_the_filename_and_not_the_upload_id(tmp_path):
    """`_process_text_file` read its header off the stored path, which is a uuid.

    Not a dedup case at all — this fired on every text attachment ever sent, and
    it is the same defect one layer down, so it is pinned here rather than left
    to be rediscovered.
    """
    handler = _handler(tmp_path)
    meta = _upload(handler, "quarterly.md", b"# Q3\n")
    rendered = _render(handler, meta)
    assert "=== File: quarterly.md ===" in rendered
    assert meta["id"] not in rendered, (
        "the upload id leaked into the message as the filename"
    )


def test_the_duplicate_return_spells_the_name_the_way_the_fresh_one_does(tmp_path):
    """One identity, two spellings — the defect `B77` names, one layer down.

    The fresh path returns `file_metadata` whole, whose ``name`` is the
    *sanitized* filename; the duplicate path returned ``original_name``, the raw
    one, and carried no ``original_name`` key at all. So the same file uploaded
    twice came back as `my_report_final.txt` and then `my report (final).txt`.
    """
    handler = _handler(tmp_path)
    first = _upload(handler, "my report (final).txt", b"x=1\n")
    second = _upload(handler, "my report (final).txt", b"x=1\n")

    assert second.get("is_duplicate") is True
    assert second["name"] == first["name"] == "my_report_final.txt"
    assert second["original_name"] == first["original_name"] == "my report (final).txt"


# ---------------------------------------------------------------------------
# `Law 1`: dedup must still dedup
# ---------------------------------------------------------------------------

def test_the_same_file_twice_is_still_one_row_and_one_copy(tmp_path):
    handler = _handler(tmp_path)
    first = _upload(handler, "notes.md")
    second = _upload(handler, "notes.md")

    assert second["is_duplicate"] is True
    assert second["id"] == first["id"]
    assert len(_index(handler)) == 1


def test_a_different_owner_is_still_a_different_row(tmp_path):
    handler = _handler(tmp_path)
    mine = _upload(handler, "notes.md", owner="owner_a")
    theirs = _upload(handler, "notes.md", owner="owner_b")
    assert mine["id"] != theirs["id"]
    assert len(_index(handler)) == 2


def test_different_bytes_under_one_name_stay_two_files(tmp_path):
    handler = _handler(tmp_path)
    first = _upload(handler, "notes.md", b"version one\n")
    second = _upload(handler, "notes.md", b"version two\n")
    assert first["id"] != second["id"]
    assert len(_index(handler)) == 2


def test_the_name_is_compared_after_sanitising_both_sides(tmp_path):
    """`secure_filename` runs on the way in, so the stored name is the safe one.

    A row carrying only the raw name must still dedup against the safe one it
    would be stored as, or every upload of a file with a space in its name
    makes a fresh copy.
    """
    handler = _handler(tmp_path)
    first = _upload(handler, "my report.txt", b"body\n")
    second = _upload(handler, "my report.txt", b"body\n")
    assert second["id"] == first["id"]

    index = _index(handler)
    for row in index.values():
        row.pop("name", None)
    handler._atomic_write_json(
        os.path.join(handler.upload_dir, "uploads.json"), index
    )
    third = _upload(handler, "my report.txt", b"body\n")
    assert third["id"] == first["id"], (
        "a row carrying only original_name stopped deduping"
    )


# ---------------------------------------------------------------------------
# The index format, and what happens to one written before this change
# ---------------------------------------------------------------------------

def test_an_index_written_before_this_change_still_dedups(tmp_path):
    """`Law 1` for the on-disk format: no migration, because none is needed.

    The key shape is unchanged (`{owner}:{hash}`) and every read path in the
    handler and the routes scans rows by field rather than parsing a key. The
    only new thing is that the key can be *taken*, which is why the insert goes
    through the collision helper `rename_owner` already used.
    """
    handler = _handler(tmp_path)
    first = _upload(handler, "notes.md")
    legacy_key = f"owner_a:{first['hash']}"
    assert legacy_key in _index(handler), "the pre-existing key shape changed"

    assert _upload(handler, "notes.md")["id"] == first["id"]


def test_a_second_name_gets_its_own_key_without_displacing_the_first(tmp_path):
    handler = _handler(tmp_path)
    first = _upload(handler, "notes.md")
    second = _upload(handler, "config.yaml")

    index = _index(handler)
    assert len(index) == 2
    assert f"owner_a:{first['hash']}" in index, (
        "the first row was displaced by the second"
    )
    ids = {row["id"] for row in index.values()}
    assert ids == {first["id"], second["id"]}


def test_every_row_is_still_reachable_by_id(tmp_path):
    """Two rows now share a hash. `reserve_upload` and `get_upload_info` look up
    by id, and both must resolve to the row that actually owns that id."""
    handler = _handler(tmp_path)
    first = _upload(handler, "notes.md")
    second = _upload(handler, "config.yaml")

    for meta, name in ((first, "notes.md"), (second, "config.yaml")):
        info = handler.get_upload_info(meta["id"])
        assert info is not None and info["name"] == name
        reserved = handler.reserve_upload(meta["id"], owner="owner_a")
        assert reserved is not None, f"{name} could not be reserved"
        assert upload_display_name(reserved) == name
        assert reserved["path"] == meta["path"]


def test_renaming_an_owner_moves_both_rows_of_one_hash(tmp_path):
    """`rename_owner` re-keys on `{new_owner}:{hash}`, which two rows now want.

    It has always fed that base key through `_unique_upload_index_key`, so this
    needed no change — which is the reason the insert reuses the same helper
    instead of inventing a key shape.
    """
    handler = _handler(tmp_path)
    first = _upload(handler, "notes.md")
    second = _upload(handler, "config.yaml")

    assert handler.rename_owner("owner_a", "owner_b") == 2
    index = _index(handler)
    assert len(index) == 2
    assert {row["owner"] for row in index.values()} == {"owner_b"}
    assert {row["id"] for row in index.values()} == {first["id"], second["id"]}
    assert {row["name"] for row in index.values()} == {"notes.md", "config.yaml"}


def test_the_write_back_re_resolves_to_the_row_it_matched(tmp_path):
    """The duplicate branch re-scans the index under the lock, and that scan is
    the same question as the lookup — so it needs the same predicate.

    `save_upload` looks the duplicate up, then re-reads the index *strictly*
    inside `_index_lock` before writing `last_accessed` back, because a
    concurrent insert may have re-keyed things. If that re-scan matches on hash
    and owner alone, it binds to whichever same-hash row iterates first — and
    then returns that row, which is `B77` again, reachable only in the race the
    re-read exists to survive.

    Driven by making the strict re-read return a re-keyed index with the *other*
    name's row first, which is exactly the state the re-scan is written for.
    """
    handler = _handler(tmp_path)
    first = _upload(handler, "notes.md")
    other = _upload(handler, "config.yaml")

    real_load = handler._load_upload_index
    calls = {"n": 0}

    def rekeyed(*a, **kw):
        index = real_load(*a, **kw)
        calls["n"] += 1
        if calls["n"] < 2:
            return index
        # config.yaml first, and every key moved so `live_key not in current`.
        rows = sorted(index.values(), key=lambda r: r["name"] != "config.yaml")
        return {f"moved-{i}": row for i, row in enumerate(rows)}

    handler._load_upload_index = rekeyed
    try:
        again = _upload(handler, "notes.md")
    finally:
        handler._load_upload_index = real_load

    assert again["id"] == first["id"], "the re-scan bound to the other name's row"
    assert again["name"] == "notes.md"
    assert again["id"] != other["id"]


def test_a_stale_row_under_another_name_is_still_cleaned(tmp_path):
    """Staleness is a property of the file, not of the name.

    Narrowing the dead-row sweep to same-name rows would leave every other
    name's dead row behind, so the sweep stayed on hash + owner while only the
    *match* gained the name.
    """
    handler = _handler(tmp_path)
    first = _upload(handler, "notes.md")
    os.remove(first["path"])

    second = _upload(handler, "config.yaml")
    index = _index(handler)
    assert {row["id"] for row in index.values()} == {second["id"]}


@pytest.mark.parametrize("info,expected", [
    ({"name": "a.md", "original_name": "b.md"}, "a.md"),
    ({"original_name": "b.md"}, "b.md"),
    ({"name": "", "original_name": "b.md"}, "b.md"),
    ({}, "c.md"),
])
def test_one_derivation_answers_what_this_file_is_called(info, expected):
    """`Law 13`: the dedup key and the name the model is told are one question.

    `save_upload` and `build_user_content` both route through this, so a row the
    dedup calls identical is by construction one the model would be told the
    same thing about.
    """
    assert upload_display_name(info, "/var/uploads/2026/09/c.md") == expected


@pytest.mark.parametrize("name,body", [
    ("notes.md", b"# heading\n"),
    # The banner path is the one that prints `display_name` verbatim, so it is
    # where a full-path fallback actually shows up. `_process_text_file`
    # basenames whatever it is handed and would hide it.
    ("scan.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64),
])
def test_a_nameless_row_does_not_put_the_upload_directory_in_the_prompt(
    tmp_path, name, body
):
    """The old fallback was `... or path`, the whole server-side path."""
    handler = _handler(tmp_path)
    meta = _upload(handler, name, body)
    resolved = {"fid": {"path": meta["path"], "mime": meta["mime"]}}
    out = build_user_content(
        "read this", ["fid"], handler.upload_dir, handler,
        owner="owner_a", resolved_uploads=resolved,
    )
    text = out if isinstance(out, str) else "".join(
        b.get("text", "") for b in out if isinstance(b, dict)
    )
    assert os.path.dirname(meta["path"]) not in text, text
    assert os.path.basename(meta["path"]) in text
