# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1166` — upstream's voyage motif is gone from what ships.

`D-2026-10-02-03` §2 took Odysseus's identity out wherever it ships; the voyage
is its motif (the boat, *"Yours for the voyage."*). The guided tour's last line
(*"enjoy the voyage!"*) went in `P23-05` and now ends *"That’s the tour."*;
the row's `Verify:` still found one: Settings → Appearance's *Welcome scene*
hint, *"Logo, tips and the voyage on an empty chat"* — and the scene it names
is Pantheon's own (Olympus, the temple, the sea). It says *scenery* now.

The row's `Verify:` is a tree-wide absence — `Law 20`'s one allowed grep:
`git grep -n voyage -- static ':!static/lib'` finds nothing.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tracked_static() -> list:
    out = subprocess.run(["git", "ls-files", "-z", "--", "static", ":!static/lib"],
                         cwd=ROOT, capture_output=True, check=True).stdout
    return [ROOT / p for p in out.decode("utf-8").split("\0") if p]


def test_nothing_under_static_says_voyage():
    found = []
    for path in _tracked_static():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue    # images and fonts carry no words
        for n, line in enumerate(text.splitlines(), 1):
            if "voyage" in line.lower():
                found.append(f"{path.relative_to(ROOT)}:{n}")
    assert not found, f"upstream's voyage motif still ships: {found}"


def test_the_welcome_scene_switch_names_what_it_hides():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    i = html.index('Welcome scene <span class="vis-hint">')
    hint = html[i:html.index("</span>", i)]
    assert hint.endswith("Logo, tips and the scenery on an empty chat")
