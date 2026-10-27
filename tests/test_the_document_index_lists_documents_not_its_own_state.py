# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1547` — the personal-documents index lists the person's documents, not
the manager's own state.

`PersonalDocsManager` keeps two JSON files — the tracked directories and the
excluded files — in the folder it indexes. Under their visible names, a folder
holding `notes.md` indexed three documents after `save_directories()` and
`exclude_file()`: the note and the manager's two state files, searchable and
listed in Settings beside it, in both indexes (the keyword one and the vector
one walk the same `walk_index_candidates`).

The state is kept as dot-files now, which the walk's existing rule for what is
not a document (`index_walk.is_indexable_file`) already leaves out — and a
folder written by an older build has its state moved onto the hidden names,
read, and kept.
"""
import json

from src.personal_docs import PersonalDocsManager, walk_index_candidates


def _folder(tmp_path):
    base = tmp_path / "personal"
    base.mkdir()
    (base / "notes.md").write_text("# Harbour\nThe tide comes in at six.\n", encoding="utf-8")
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "gone.txt").write_text("excluded", encoding="utf-8")
    return base, other


def test_the_index_lists_only_the_note(tmp_path):
    """The row's `Verify:`."""
    base, other = _folder(tmp_path)
    mgr = PersonalDocsManager(str(base))
    mgr.indexed_directories.append(str(tmp_path / "nowhere"))
    mgr.save_directories()
    mgr.exclude_file(str(other / "gone.txt"))
    mgr.refresh_index()
    assert [f["name"] for f in mgr.index] == ["notes.md"]
    # and the vector indexer's walk over the same folder sees the same one file
    assert [p.rsplit("/", 1)[-1] for p, *_ in walk_index_candidates(str(base))] == ["notes.md"]


def test_the_state_is_kept_and_read_back(tmp_path):
    base, other = _folder(tmp_path)
    mgr = PersonalDocsManager(str(base))
    mgr.exclude_file(str(other / "gone.txt"))
    mgr.indexed_directories.append(str(other))
    mgr.save_directories()
    again = PersonalDocsManager(str(base))
    assert again.indexed_directories == [str(other)]
    assert again.excluded_files == {str(other / "gone.txt")}


def test_a_folder_an_older_build_wrote_is_moved_and_not_indexed(tmp_path):
    base, other = _folder(tmp_path)
    (base / "indexed_directories.json").write_text(json.dumps([str(other)]), encoding="utf-8")
    (base / "excluded_files.json").write_text(json.dumps([str(other / "gone.txt")]),
                                              encoding="utf-8")
    mgr = PersonalDocsManager(str(base))
    assert mgr.indexed_directories == [str(other)]
    assert mgr.excluded_files == {str(other / "gone.txt")}
    assert sorted(p.name for p in base.iterdir()) == [
        ".excluded_files.json", ".indexed_directories.json", "notes.md"]
    assert [f["name"] for f in mgr.index] == ["notes.md"]
