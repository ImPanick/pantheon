# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B481`, the owner's call (`D-2026-10-26-01` §10) — a new chat keeps the mode
the person was in.

The reset that once lived in `_startFreshChat` looked for `#agent-mode-toggle`,
a checkbox that stopped existing when the picker became two buttons, so it had
done nothing for months; the question was whether it should. It should not: the
mode is persisted (`loadToggleState().mode`) and is the person's choice.
"""

from pathlib import Path

from tests.helpers.js_source import js_function

ROOT = Path(__file__).resolve().parents[1]


def test_starting_a_new_chat_does_not_touch_the_mode():
    src = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    body = js_function(src, "function _startFreshChat")
    for reset in ("__pantheonSetChatMode", "agent-mode-toggle", "mode-chat-btn", "setChatMode",
                  ".mode =", "'chat')"):
        assert reset not in body, reset
    assert "B481" in body
