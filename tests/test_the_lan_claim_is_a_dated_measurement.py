# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B975` — "the container cannot reach the LAN" is a dated measurement, not a fact.

`P17-01` measured it on the owner's Docker Desktop on 2026-09-11
(`192.168.1.1:80` TimeoutError). The integrator measured the opposite there on
2026-10-01 (Docker Desktop 29.7.2 for Windows, default bridge and a compose
network: `192.168.1.1:80`/`:443` and the host's `:445` open). How much LAN a
container reaches is Docker's answer, and it changed; the places that stated
the old one as a lasting property now say what was measured and when.

These are documents, so this reads them — the one thing `Law 20` allows a file
read to prove is that a sentence is **absent** where its presence would be
wrong. Each claim below is looked for in the file, or in the one docstring or
card that carried it (scoped with `ast`, or the card's own markup).
"""
from __future__ import annotations

import ast
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The old sentences, as they stood (`B975`'s list), and the file each was in.
STALE = [
    ("netagent/README.md", "cannot reach your LAN"),
    ("netagent/README.md", "That is deliberate."),
    ("netagent/__init__.py", "staying unable to reach the LAN is a feature"),
    ("src/netagent_client.py", "The container still cannot reach `192.168.1.1` and that stays true"),
    ("static/index.html", "cannot reach your LAN"),
    ("tests/test_the_network_agent_is_its_own_process.py",
     "staying unable to reach the LAN is a feature"),
    ("tests/test_the_agent_is_a_credential_not_a_hole.py",
     "the container still cannot reach the LAN."),
]


@pytest.mark.parametrize("path, sentence", STALE, ids=[f"{p}:{s[:24]}" for p, s in STALE])
def test_the_old_sentence_is_gone(path, sentence):
    text = (ROOT / path).read_text(encoding="utf-8")
    if path.startswith("tests/") or path.endswith(".py"):
        # In a Python file the claim lived in a docstring; this file's own list
        # above quotes them and is not one of those files.
        text = ast.get_docstring(ast.parse(text)) or ""
    assert sentence not in text, f"{path} still says: {sentence}"


@pytest.mark.parametrize("path", [
    "netagent/__init__.py", "src/netagent_client.py",
    "tests/test_the_network_agent_is_its_own_process.py",
    "tests/test_the_agent_is_a_credential_not_a_hole.py",
])
def test_each_docstring_says_what_was_measured_and_when(path):
    doc = ast.get_docstring(ast.parse((ROOT / path).read_text(encoding="utf-8"))) or ""
    flat = " ".join(doc.split())
    assert "2026-09-11" in flat and "2026-10-01" in flat, path
    assert "Docker Desktop 29.7.2" in flat, path


def test_the_readme_opening_says_it_too():
    readme = (ROOT / "netagent" / "README.md").read_text(encoding="utf-8")
    opening = " ".join(readme.split("## What it is", 1)[0].split())
    assert "2026-09-11" in opening and "2026-10-01" in opening
    assert "Docker Desktop 29.7.2 for Windows" in opening


class _Card(HTMLParser):
    """The text of the admin card whose heading is `title`."""

    def __init__(self, title):
        super().__init__()
        self.title, self.depth, self.cards, self.current = title, 0, [], None

    def handle_starttag(self, tag, attrs):
        if tag == "div":
            if dict(attrs).get("class", "").split()[:1] == ["admin-card"]:
                self.current = {"depth": self.depth, "text": []}
            self.depth += 1

    def handle_endtag(self, tag):
        if tag == "div":
            self.depth -= 1
            if self.current and self.depth == self.current["depth"]:
                self.cards.append(" ".join("".join(self.current["text"]).split()))
                self.current = None

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"].append(data)

    def text(self):
        return next(c for c in self.cards if c.startswith(self.title))


def test_the_network_agent_card_claims_no_reach_for_the_container():
    parser = _Card("Network agent")
    parser.feed((ROOT / "static" / "index.html").read_text(encoding="utf-8"))
    card = parser.text()
    assert "read-only process you run on the host" in card
    assert not re.search(r"cannot reach (your|the) LAN", card), card
    # P23 round 2 (`B1236`): `P23-03` shortened the card to "sees the network
    # Docker cannot" — the same lasting claim in other words (the container
    # sees no network). Held here too, so the next shortening cannot say it.
    assert not re.search(r"network (Docker|the container) cannot", card), card


def test_the_threat_models_shell_gap_says_the_lan_is_in_reach():
    model = (ROOT / "THREAT_MODEL.md").read_text(encoding="utf-8")
    gap = model.split("1. **No OS-level sandbox for `bash`.**", 1)[1].split("\n2. **", 1)[0]
    flat = " ".join(gap.split())
    assert "On Docker Desktop that includes your LAN" in flat
    assert "2026-10-01" in flat and "Docker Desktop 29.7.2 for Windows" in flat
    assert "2026-09-11" in flat
