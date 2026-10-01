# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P20-04` — the chat draws each screenshot on the tool card, live and after a
reload, with the action and where it happened on the fold's summary line.

The events are the real ones: the real agent loop runs the real `computer` tool
against the real workstation daemon, and this file takes the `tool_start` and
`tool_output` the browser was streamed and the `tool_events` the route saves.
Then, under node, the real `agentTurn.js` draws the live card from the first
two, and the real `chatRenderer.addMessage` draws the reloaded one from the
third — in the page `P4-24`'s resumed-stream file sets up, whose shim parses
markup into nodes, so both cards are read the way a person reads them.

Before this row the history renderer read `screenshot` off a saved event and
nothing ever saved one, so a browser screenshot vanished on every reload; and
both folds said "Screenshot" whatever the picture was of. Nothing here reads a
source file (`Law 20`).
"""
from __future__ import annotations

import base64
import io
import json
import shutil
from pathlib import Path

import pytest

from test_a_resumed_stream_draws_what_the_live_one_drew import _SHIM
from test_tool_effect_surfaces_js import _CARD_STUBS, _make_sandbox, _run
from test_what_a_tool_sees_reaches_the_model import run_loop, station  # noqa: F401 — fixture
from tests.helpers.esc_stub import ui_default_stub
from src.tool_result_images import CARD_MAX_SIZE

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"

node_only = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_STUBS = dict(_CARD_STUBS, **{
    "ui.js": ui_default_stub(
        "showToast: () => {}, copyToClipboard: () => {}, showError: () => {},\n"
        "el: (id) => document.getElementById(id), debounce: (f) => f,\n"
        "autoResize: () => {}, scrollHistory: () => {}, formatBytes: (n) => String(n),"),
})


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    d = _make_sandbox(tmp_path_factory.mktemp("computercard"), JS / "chatRenderer.js", _SHIM,
                      _STUBS)
    shutil.copy(JS / "agentTurn.js", d / "agentTurn.js")
    return d


_PAGE = r"""
import { document, Node } from './shim.js';
const history = document.body.appendChild(new Node('div'));
history.setAttribute('id', 'chat-history');
const { addMessage } = await import('./chatRenderer.js');
const { startToolCard, finishToolCard } = await import('./agentTurn.js');
const words = (n) => (n ? n.textContent.replace(/\s+/g, ' ').trim() : '');
/** Every picture a card shows: the words on its fold, and the image. */
function shots(root) {
  return root.querySelectorAll('.agent-tool-output')
    .filter((d) => d.querySelector('img'))
    .map((d) => {
      const img = d.querySelector('img');
      return { summary: words(d.querySelector('summary')),
               src: img.src || img.getAttribute('src'),
               alt: img.alt || img.getAttribute('alt') };
    });
}
function cardOf(root) {
  const node = root.querySelector('.agent-thread-node');
  return { label: words(node.querySelector('.agent-thread-tool')),
           line: words(node.querySelector('.agent-thread-cmd')), shots: shots(node) };
}
function live(start, output) {
  const wrap = document.body.appendChild(new Node('div'));
  const node = startToolCard(wrap, start, { scroll: null });
  const running = words(node.querySelector('.agent-thread-tool'));
  finishToolCard(node, output, { scroll: null });
  return Object.assign({ running }, cardOf(wrap));
}
function reloaded(metadata) {
  history.childNodes = [];
  addMessage('assistant', 'Done.', 'gpt-4o', metadata);
  return cardOf(history);
}
"""


def _page(sandbox, body: str) -> dict:
    return _run(sandbox, "", _PAGE + body)


def _events_of_a_click(monkeypatch):
    _requests, events = run_loop(monkeypatch, "gpt-4o", [{"action": "click", "x": 640, "y": 400}])
    start = next(e for e in events if e.get("type") == "tool_start" and e.get("tool") == "computer")
    output = next(e for e in events if e.get("type") == "tool_output" and e.get("tool") == "computer")
    metrics = next(e for e in events if e.get("type") == "metrics")["data"]
    return start, output, metrics


def _jpeg_size(src: str):
    from PIL import Image
    prefix = "data:image/jpeg;base64,"
    assert src.startswith(prefix), src[:40]
    with Image.open(io.BytesIO(base64.b64decode(src[len(prefix):]))) as picture:
        return picture.size


@node_only
def test_the_live_card_and_the_reloaded_card_draw_the_same_screen(sandbox, station, monkeypatch):
    start, output, metrics = _events_of_a_click(monkeypatch)
    [saved] = [e for e in metrics["tool_events"] if e.get("tool") == "computer"]
    assert saved["screenshot"] == output["screenshot"], "one copy, streamed and saved"
    out = _page(sandbox, "console.log(JSON.stringify({ live: live(%s, %s), reloaded: reloaded(%s) }));"
                % (json.dumps(start), json.dumps(output), json.dumps(metrics)))
    expected = [{"summary": "Screen after click at (640, 400)", "src": output["screenshot"],
                 "alt": "Screen after click at (640, 400)"}]
    assert out["live"]["shots"] == expected
    assert out["reloaded"]["shots"] == expected, "the reload draws what the live card drew"
    # The card says what was done, on the line a person reads first.
    assert out["live"]["line"] == out["reloaded"]["line"] == "click at (640, 400)"
    assert out["live"]["running"] == "Using computer"
    assert out["live"]["label"] == out["reloaded"]["label"] == "Computer"


@node_only
def test_the_card_draws_a_small_copy_the_model_is_sent_the_original(station, monkeypatch):
    requests, events = run_loop(monkeypatch, "gpt-4o", [{"action": "screenshot"}])
    output = next(e for e in events if e.get("type") == "tool_output" and e.get("tool") == "computer")
    width, height = _jpeg_size(output["screenshot"])
    assert width <= CARD_MAX_SIZE[0] and height <= CARD_MAX_SIZE[1]
    assert (width, height) == (960, 600), "the 1280×800 screen, scaled to the card"
    sent = [p["image_url"]["url"] for m in requests[1] if isinstance(m.get("content"), list)
            for p in m["content"] if p.get("type") == "image_url"]
    assert sent and sent[0].startswith("data:image/png;base64,")
    assert output["screenshot_caption"] == "Screen"


_PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nbrowser").decode()


@node_only
def test_a_browser_screenshot_still_reads_screenshot_and_now_survives_a_reload(sandbox):
    """A picture with no caption keeps the words it always had — on both paths,
    because the reloaded card is drawn by the same function."""
    event = {"type": "tool_output", "tool": "mcp__builtin_browser__browser_take_screenshot",
             "command": "{}", "round": 1, "output": "[Screenshot captured (image/png)]",
             "exit_code": 0, "status": "ok", "screenshot": _PNG}
    saved = {"round_texts": ["Done."], "tool_events": [dict(event, desc="mcp")]}
    out = _page(sandbox, "console.log(JSON.stringify({ live: live(%s, %s), reloaded: reloaded(%s) }));"
                % (json.dumps(dict(event, type="tool_start")), json.dumps(event), json.dumps(saved)))
    expected = [{"summary": "Screenshot", "src": _PNG, "alt": "Screenshot"}]
    assert out["live"]["shots"] == expected and out["reloaded"]["shots"] == expected


@node_only
def test_a_caption_is_text_on_both_paths(sandbox):
    hostile = '<img src=x onerror="alert(1)">'
    event = {"type": "tool_output", "tool": "computer", "command": "type “x”", "round": 1,
             "output": "ok", "exit_code": 0, "status": "ok", "screenshot": _PNG,
             "screenshot_caption": hostile}
    saved = {"round_texts": ["Done."], "tool_events": [dict(event)]}
    out = _page(sandbox, "console.log(JSON.stringify({ live: live(%s, %s), reloaded: reloaded(%s) }));"
                % (json.dumps(dict(event, type="tool_start")), json.dumps(event), json.dumps(saved)))
    for side in ("live", "reloaded"):
        [shot] = out[side]["shots"]
        assert shot["summary"] == hostile, side
