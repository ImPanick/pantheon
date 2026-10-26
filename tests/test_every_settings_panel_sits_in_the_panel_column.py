# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every Settings panel is a child of `.settings-panels`.

**Measured:** removing the retired *Model Defaults* card (`B1479`) left one
`</div>` behind, which closed `.settings-panels` early. Thirteen panels —
Services through System — then sat beside the column instead of in it, and at
phone width the visible panel got 260px of an 844px sheet. The phone-layout
test caught it only in a browser; this is the same fact read from the markup,
so a stray closing tag fails in a second.
"""

from html.parser import HTMLParser
from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "static" / "index.html"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "source", "track", "wbr"}


class _Panels(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.found = {}

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        a = dict(attrs)
        if "data-settings-panel" in a:
            self.found[a["data-settings-panel"]] = any(
                "settings-panels" in (cls or "").split() for _t, cls in self.stack)
        self.stack.append((tag, a.get("class")))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        while self.stack:
            if self.stack.pop()[0] == tag:
                break


def test_no_panel_is_outside_the_column():
    p = _Panels()
    p.feed(INDEX.read_text(encoding="utf-8"))
    assert len(p.found) >= 20, sorted(p.found)
    outside = sorted(name for name, inside in p.found.items() if not inside)
    assert outside == [], f"outside .settings-panels: {outside}"
