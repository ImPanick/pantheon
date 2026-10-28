# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-27` — `manage_rag` never indexes a folder named relative to the install.

Found bringing RAG Builder to the bar. `add_directory` resolved its folder
with `os.path.abspath`, against the RAG server's own working directory —
Pantheon's install. An agent hired with "the documents folder, inside your
projects folder" passes `docs`, and the server indexed **Pantheon's own
`docs/` folder** into the person's index, answering "added to RAG index (81
chunks indexed)" as if it were theirs. A relative folder is now refused in a
sentence that says what to give instead; a full path works as before.

Driven through the server's real `call_tool`, with its index stood in so
nothing is embedded.
"""

from __future__ import annotations

import asyncio
import os

import mcp_servers.rag_server as rag_server


class _Index:
    def __init__(self):
        self.indexed = []

    def index_personal_documents(self, directory):
        self.indexed.append(directory)
        return {"indexed_count": 1}


class _Docs:
    def add_directory(self, directory, index=False):
        pass


def _add(directory, monkeypatch):
    index = _Index()
    monkeypatch.setattr(rag_server, "_rag_manager", index)
    monkeypatch.setattr(rag_server, "_personal_docs_manager", _Docs())
    monkeypatch.setattr(rag_server, "_initialized", True)
    parts = asyncio.run(rag_server.call_tool("manage_rag", {"action": "add_directory", "directory": directory}))
    return parts[0].text, index.indexed


def test_a_relative_folder_is_refused_and_nothing_is_indexed(monkeypatch):
    assert os.path.isdir("docs"), "the test runs where the install has a docs folder"
    said, indexed = _add("docs", monkeypatch)
    assert indexed == [], f"the server indexed {indexed} — the install's own folder"
    assert said.startswith("Error:") and "full path" in said and "ls" in said, said


def test_a_full_path_is_indexed_as_before(monkeypatch, tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    said, indexed = _add(str(folder), monkeypatch)
    assert indexed == [str(folder)], indexed
    assert "added to RAG index (1 chunks indexed)" in said, said
