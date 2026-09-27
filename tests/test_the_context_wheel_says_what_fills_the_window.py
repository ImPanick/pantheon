# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B892`. The context wheel says what fills the window, and by how much.

The owner, 2026-09-27: *"has the overall context usage in a wheel at the
bottom.. When interacted with, sections it out to the line - and you can see
the breakdown of what is using up the context in that window... then you can
drop down to elaborate even further by tokens of what is precisely using up the
context window."* And the attachment allowance *"moves here"*, labelled for
what an attachment is: *"attachments aren't always documents.. Sometimes its
code, and sometimes its photos"*.

What is pinned, by driving the code:

  * **one request splits into its parts** — system prompt, tool definitions,
    skills, memory, retrieved context, attachments, conversation — and the
    parts add up to what the one estimator says the request costs (`Law 7`);
  * **an attachment is named for what it is**: code, a document, a picture;
    a picture is listed as *not counted* rather than given an invented number;
  * **a part nobody measured says so** — a chat with no reply yet has sent no
    system prompt, and a zero there would read as "costs nothing" (`Law 10`);
  * **the route serves it**: the last reply's own measurement for what is
    assembled per request, history as it stands for the rest;
  * **the panel draws it**: the wheel's arcs, the bar's segments, one row per
    part with its tokens, each part opening onto its items; files waiting to be
    sent listed by kind; the allowance meter adopted, not drawn twice;
  * **the wheel lives in the composer**, and the meter no longer spans it.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.models import ChatMessage
from services.memory.skill_injection import INDEX_HEADING, INDEX_PREAMBLE
from src.context_budget import (
    CONTEXT_BREAKDOWN_CATEGORIES,
    attachment_kind,
    measure_request_segments,
    session_context_breakdown,
)
from src.model_context import estimate_tokens
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.helpers.source_text import blank

ROOT = Path(__file__).resolve().parents[1]
CONTEXT_USAGE = ROOT / "static" / "js" / "contextUsage.js"
INDEX = ROOT / "static" / "index.html"

_SYSTEM = ("You are Pantheon.\n\n" + INDEX_HEADING + "\n" + INDEX_PREAMBLE
           + "\n\n**general**\n- `deploy` — ship it\n- `review` — read a diff\n\n"
           + "Answer plainly.")
_TOOLS = [
    {"type": "function", "function": {"name": "web_search", "description": "Search the web",
                                      "parameters": {"type": "object", "properties": {
                                          "query": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read a file",
                                      "parameters": {"type": "object", "properties": {}}}},
]


def _request():
    return [
        {"role": "system", "content": _SYSTEM, "_agent_injected": "prompt"},
        {"role": "user", "content": "Saved user memory facts\n- likes tea",
         "metadata": {"source": "saved memory: minimal context", "trusted": False}},
        {"role": "user", "content": "result one\nresult two",
         "metadata": {"source": "prefetched search context", "trusted": False}},
        {"role": "user", "content": (
            "why does this fail?"
            "\n=== File: main.py ===\n[Type: python, Lines: 2, Size: 20 bytes]\n"
            "```python\nprint(1/0)\n```"
            "\n\n[PDF content — report.v2.pdf]:\nquarterly numbers")},
        {"role": "assistant", "content": "Division by zero.",
         "tool_calls": [{"function": {"name": "read_file", "arguments": "{\"p\": 1}"}}]},
        {"role": "tool", "content": "file body"},
        {"role": "user", "content": [
            {"type": "text", "text": "and this screenshot?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]},
    ]


def _by_key(report):
    return {c["key"]: c for c in report["categories"]}


# ── the measurement ─────────────────────────────────────────────────────────

def test_one_request_splits_into_every_part_it_is_made_of():
    cats = _by_key(measure_request_segments(_request(), _TOOLS))
    assert [k for k, _ in CONTEXT_BREAKDOWN_CATEGORIES] == list(cats)
    for key in ("system", "tools", "skills", "memory", "retrieved",
                "attachments", "conversation"):
        assert cats[key]["tokens"] > 0, (key, cats[key])
    assert [i["name"] for i in cats["skills"]["items"]] == ["deploy", "review"] or \
        sorted(i["name"] for i in cats["skills"]["items"]) == ["deploy", "review"]
    assert sorted(i["name"] for i in cats["tools"]["items"]) == ["read_file", "web_search"]
    assert cats["tools"]["count"] == 2
    assert cats["retrieved"]["items"][0]["name"] == "prefetched search context"


def test_the_parts_add_up_to_what_the_one_estimator_says():
    """`Law 7`: a meter that disagrees with the gate it is metering is worse
    than no meter. The messages' parts sum to `estimate_tokens` exactly; the
    tool schemas are the one addition, measured by the same rule."""
    report = measure_request_segments(_request(), _TOOLS)
    tools = _by_key(report)["tools"]["tokens"]
    assert report["total_tokens"] - tools == estimate_tokens(_request())
    assert sum(c["tokens"] for c in report["categories"]) == report["total_tokens"]


def test_an_attachment_is_named_for_what_it_is():
    items = _by_key(measure_request_segments(_request(), _TOOLS))["attachments"]["items"]
    kinds = {i["name"]: i["kind"] for i in items}
    assert kinds["main.py"] == "code"
    assert kinds["report.v2.pdf"] == "document"
    assert kinds["Image"] == "image"


def test_a_picture_is_listed_as_not_counted_rather_than_given_a_number():
    report = measure_request_segments(_request(), _TOOLS)
    picture = [i for i in _by_key(report)["attachments"]["items"] if i["kind"] == "image"]
    assert picture and picture[0]["tokens"] is None and picture[0]["uncounted"] is True
    assert report["uncounted"] == [{"name": "Image", "kind": "image", "tokens": None,
                                    "uncounted": True}]


@pytest.mark.parametrize("name,mime,kind", [
    ("main.py", "", "code"), ("App.TSX", "text/plain", "code"), ("Dockerfile", "", "code"),
    ("shot.PNG", "", "image"), ("pasted", "image/jpeg", "image"),
    ("q3.xlsx", "", "spreadsheet"), ("rows.csv", "text/csv", "spreadsheet"),
    ("paper.pdf", "", "document"), ("memo.docx", "", "document"),
    ("notes.md", "", "text"), ("server.log", "", "text"), ("voice.m4a", "", "audio"),
    ("blob.bin", "application/octet-stream", "file"),
])
def test_the_kind_comes_from_the_name_first(name, mime, kind):
    assert attachment_kind(name, mime) == kind


def test_a_part_nobody_measured_says_so_instead_of_drawing_a_zero():
    history = _request()[3:]
    out = _by_key(session_context_breakdown(history, None))
    for key in ("system", "tools", "skills", "memory", "retrieved"):
        assert out[key]["measured"] is False, key
    assert out["conversation"]["measured"] is True
    assert out["attachments"]["measured"] is True


def test_the_last_reply_supplies_what_history_cannot():
    last = measure_request_segments(_request(), _TOOLS)
    history = _request()[3:]
    out = session_context_breakdown(history, last)
    cats = _by_key(out)
    assert out["source"] == "last_request"
    assert cats["tools"]["tokens"] == _by_key(last)["tools"]["tokens"]
    assert cats["system"]["source"] == "last_request"
    assert cats["conversation"]["source"] == "history"
    assert out["total_tokens"] == sum(c["tokens"] for c in out["categories"])


# ── the route ───────────────────────────────────────────────────────────────

class _Session:
    id = "s-1"
    endpoint_url = "http://example.test/v1"
    model = "test-model"

    def __init__(self, history):
        self.history = history

    def get_context_messages(self):
        return [m.to_dict() if isinstance(m, ChatMessage) else m for m in self.history]


class _Manager:
    def __init__(self, session):
        self.session = session

    def get_session(self, session_id):
        if session_id != self.session.id:
            raise KeyError(session_id)
        return self.session


def _context(monkeypatch, history):
    import routes.history_routes as history_routes
    import src.model_context as model_context
    monkeypatch.setattr(history_routes, "_verify_session_owner", lambda request, sid: None)
    monkeypatch.setattr(model_context, "get_context_length", lambda url, model: 100_000)
    app = FastAPI()
    app.include_router(history_routes.setup_history_routes(_Manager(_Session(history))))
    res = TestClient(app).get("/api/session/s-1/context")
    assert res.status_code == 200, res.text
    return res.json()


def test_the_route_reads_the_last_replys_overhead_back(monkeypatch):
    breakdown = measure_request_segments(_request(), _TOOLS)
    history = [
        ChatMessage("user", _request()[3]["content"]),
        ChatMessage("assistant", "Division by zero.",
                    metadata={"context_breakdown": breakdown}),
    ]
    out = _context(monkeypatch, history)
    cats = _by_key(out["breakdown"])
    assert out["breakdown"]["source"] == "last_request"
    assert cats["tools"]["tokens"] == _by_key(breakdown)["tools"]["tokens"]
    assert cats["attachments"]["items"][0]["kind"] == "code"
    # The wheel's figure is the whole window, not the history alone.
    assert out["breakdown"]["used_tokens"] >= out["used_tokens"]
    assert out["breakdown"]["used_tokens"] == out["breakdown"]["total_tokens"]
    assert out["breakdown"]["context_percent"] == round(
        out["breakdown"]["used_tokens"] / 100_000 * 100, 1)


def test_a_chat_with_no_measured_reply_is_honest_about_it(monkeypatch):
    out = _context(monkeypatch, [ChatMessage("user", "hello")])
    cats = _by_key(out["breakdown"])
    assert out["breakdown"]["source"] == "history"
    assert cats["system"]["measured"] is False
    assert cats["conversation"]["tokens"] > 0


def test_the_agent_loop_hands_the_measurement_to_the_reply():
    """The emit is one call on the list that was actually sent. Read from the
    loop's source because running a whole turn to see one key is the wrong
    trade; the measurement itself is driven above."""
    src = blank(ROOT / "src" / "agent_loop.py")
    assert re.search(r'metrics\["context_breakdown"\]\s*=\s*measure_request_segments\(\s*'
                     r'_last_route_request_messages or messages,\s*_last_sent_tool_schemas\)', src)
    assert "_last_sent_tool_schemas = all_tool_schemas" in src


# ── the panel ───────────────────────────────────────────────────────────────

pytestmark_node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };
export function read(panel) {
  const text = (n, sel) => { const x = n.querySelector(sel); return x ? x.textContent : null; };
  return {
    title: text(panel, '.ctx-usage-title'),
    pct: text(panel, '.ctx-usage-pct'),
    sub: text(panel, '.ctx-usage-sub'),
    segments: panel.querySelectorAll('.ctx-usage-seg').map((s) => ({ key: s.dataset.key, width: s.style.width })),
    rows: panel.querySelectorAll('.ctx-usage-cat').map((r) => ({
      key: r.dataset.key || 'free',
      tag: r.tagName,
      label: text(r, '.ctx-usage-cat-label'),
      tokens: text(r, '.ctx-usage-cat-tokens'),
      share: text(r, '.ctx-usage-cat-share'),
      unmeasured: r.classList.contains('unmeasured'),
      items: r.querySelectorAll('.ctx-usage-item').map((i) => ({
        name: text(i, '.ctx-usage-item-name'),
        nameHtml: i.querySelector('.ctx-usage-item-name')._html,
        kind: text(i, '.ctx-usage-kind'),
        tokens: text(i, '.ctx-usage-item-tokens'),
      })),
    })),
    notes: panel.querySelectorAll('.ctx-usage-note').map((n) => n.textContent),
    attach: panel.querySelector('.ctx-usage-attach') ? {
      title: text(panel.querySelector('.ctx-usage-attach'), '.ctx-usage-section-title'),
      pending: (panel.querySelector('.ctx-usage-pending')
        ? panel.querySelector('.ctx-usage-pending').querySelectorAll('.ctx-usage-item') : []).map((i) => ({
        name: text(i, '.ctx-usage-item-name'), kind: text(i, '.ctx-usage-kind'),
        size: text(i, '.ctx-usage-item-tokens') })),
      meterAdopted: !!panel.querySelector('#context-meter'),
    } : null,
  };
}
"""

_PREAMBLE = "import { document, read } from './shim.js';\nconst cu = await import('./contextUsage.js');\n"


@pytest.fixture(scope="module")
def panel_sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("ctxusage"), CONTEXT_USAGE, _SHIM, {})


def _payload(breakdown=None):
    last = measure_request_segments(_request(), _TOOLS)
    history = _request()[3:]
    b = breakdown if breakdown is not None else session_context_breakdown(history, last)
    b["used_tokens"] = b["total_tokens"]
    b["context_percent"] = round(b["total_tokens"] / 2000 * 100, 1)
    return {"model": "org/test-model", "context_length": 2000, "used_tokens": 50,
            "context_percent": 2.5, "messages": 4, "breakdown": b}


def _panel(sandbox, data, opts="{}"):
    return _run(sandbox, _PREAMBLE, """
        const data = %s;
        const opts = %s;
        const panel = cu.buildUsagePanel(document, data, opts);
        const pill = document.createElement('button');
        cu.renderPill(pill, data, { pendingCount: (opts.pending || []).length });
        console.log(JSON.stringify({ panel: read(panel), pill: { html: pill.innerHTML,
          title: pill.title, classes: pill.className } }));
    """ % (json.dumps(data), opts))


@pytestmark_node
def test_the_panel_draws_one_row_per_part_with_its_tokens(panel_sandbox):
    out = _panel(panel_sandbox, _payload())["panel"]
    assert out["title"] == "Context window"
    assert out["pct"].endswith("% full")
    assert re.match(r"^~[\d.]+K? / 2K tokens$", out["sub"]), out["sub"]
    keys = [r["key"] for r in out["rows"]]
    assert keys == ["system", "tools", "skills", "memory", "retrieved",
                    "attachments", "conversation", "free"], keys
    assert [s["key"] for s in out["segments"]] == keys[:-1]
    assert all(r["tokens"] not in (None, "", "?") for r in out["rows"]), out["rows"]


@pytestmark_node
def test_each_part_opens_onto_what_it_is_made_of(panel_sandbox):
    rows = {r["key"]: r for r in _panel(panel_sandbox, _payload())["panel"]["rows"]}
    assert rows["tools"]["tag"] == "DETAILS"
    assert rows["tools"]["label"] == "Tool definitions (2)"
    assert sorted(i["name"] for i in rows["tools"]["items"]) == ["read_file", "web_search"]
    attach = {i["name"]: i for i in rows["attachments"]["items"]}
    assert attach["main.py"]["kind"] == "Code"
    assert attach["report.v2.pdf"]["kind"] == "Document"
    assert attach["Image"]["kind"] == "Image"
    assert attach["Image"]["tokens"] == "not counted"
    assert rows["free"]["label"] == "Free space"


@pytestmark_node
def test_an_unmeasured_part_says_next_reply_and_draws_no_segment(panel_sandbox):
    history = _request()[3:]
    b = session_context_breakdown(history, None)
    out = _panel(panel_sandbox, _payload(b))["panel"]
    rows = {r["key"]: r for r in out["rows"]}
    assert rows["system"]["unmeasured"] is True
    assert rows["system"]["tokens"] == "—" and rows["system"]["share"] == "next reply"
    assert "system" not in [s["key"] for s in out["segments"]]
    assert any("next reply" in n for n in out["notes"]), out["notes"]


@pytestmark_node
def test_waiting_files_are_listed_by_kind_and_pictures_are_told_apart(panel_sandbox):
    opts = json.dumps({"pending": [
        {"name": "main.py", "mime": "text/x-python", "size": 2048},
        {"name": "shot.png", "mime": "image/png", "size": 512000},
    ]})
    out = _panel(panel_sandbox, None, opts)
    panel = out["panel"]
    assert panel["sub"] == "Nothing has been sent in this chat yet."
    assert panel["attach"]["title"] == "Attaching to this message"
    assert panel["attach"]["pending"] == [
        {"name": "main.py", "kind": "Code", "size": "2 KB"},
        {"name": "shot.png", "kind": "Image", "size": "500 KB"},
    ]
    assert any("sent as a picture" in n for n in panel["notes"]), panel["notes"]
    assert "has-pending" in out["pill"]["classes"]
    assert "2 attachments waiting" in out["pill"]["title"]


@pytestmark_node
def test_the_allowance_meter_is_adopted_not_drawn_twice(panel_sandbox):
    out = _run(panel_sandbox, _PREAMBLE, """
        const home = document.body.appendChild(document.createElement('div'));
        home.setAttribute('id', 'context-meter-home');
        const meter = home.appendChild(document.createElement('div'));
        meter.setAttribute('id', 'context-meter');
        meter.hidden = false;
        const panel = cu.buildUsagePanel(document, null, { pending: [], meterHost: meter });
        console.log(JSON.stringify({ inPanel: !!panel.querySelector('#context-meter'),
          leftHome: home.childNodes.length, meters: document.body.querySelectorAll('#context-meter').length }));
    """)
    assert out == {"inPanel": True, "leftHome": 0, "meters": 0}


@pytestmark_node
def test_a_name_reaches_the_panel_as_text_and_never_as_markup(panel_sandbox):
    hostile = '<img src=x onerror="alert(1)">.py'
    b = session_context_breakdown([{"role": "user", "content": f"x\n=== File: {hostile} ===\nbody"}], None)
    rows = {r["key"]: r for r in _panel(panel_sandbox, _payload(b))["panel"]["rows"]}
    item = rows["attachments"]["items"][0]
    assert item["name"] == hostile and item["nameHtml"] == ""


@pytestmark_node
def test_the_wheel_draws_one_arc_per_measured_part(panel_sandbox):
    pill = _panel(panel_sandbox, _payload())["pill"]
    arcs = re.findall(r'class="ctx-ring-arc" data-key="([a-z]+)"', pill["html"])
    assert arcs == ["system", "tools", "skills", "memory", "retrieved",
                    "attachments", "conversation"], arcs
    assert "var(--ctx-seg-tools)" in pill["html"]
    assert pill["title"].startswith("Context window: ")


@pytestmark_node
def test_the_kind_lists_agree_between_the_browser_and_the_server(panel_sandbox):
    cases = [("main.py", ""), ("App.TSX", "text/plain"), ("Dockerfile", ""), ("shot.PNG", ""),
             ("pasted", "image/jpeg"), ("q3.xlsx", ""), ("rows.csv", "text/csv"),
             ("paper.pdf", ""), ("memo.docx", ""), ("notes.md", ""), ("server.log", ""),
             ("voice.m4a", ""), ("blob.bin", "application/octet-stream")]
    out = _run(panel_sandbox, _PREAMBLE, """
        const cases = %s;
        console.log(JSON.stringify(cases.map(([n, m]) => cu.attachmentKind(n, m))));
    """ % json.dumps(cases))
    assert out == [attachment_kind(n, m) for n, m in cases]


# ── the markup ──────────────────────────────────────────────────────────────
# Claims about where the markup puts things, so read from the markup.

def test_the_wheel_is_in_the_composer_and_not_the_header():
    html = blank(INDEX)
    right = html.index('<div class="chat-input-right">')
    pill = html.index('id="chat-context-pill"')
    assert html.count('id="chat-context-pill"') == 1
    assert right < pill < html.index('class="mode-toggle"', right)
    assert 'id="chat-context-pill"' not in html[html.index('class="chat-meta-overlay"'):right][:4000]


def test_the_meter_no_longer_spans_the_composer():
    html = blank(INDEX)
    home = re.search(r'<div id="context-meter-home"[^>]*\bhidden\b[^>]*>\s*<div id="context-meter"', html)
    assert home, "the allowance meter is not inside its hidden home"


# ── the allowance meter, inside the panel ───────────────────────────────────

from test_context_meter_js import (  # noqa: E402
    FILE_HANDLER, _PREAMBLE as _METER_PREAMBLE, _SHIM as _METER_SHIM,
    _STUBS as _METER_STUBS, _report,
)


@pytest.fixture(scope="module")
def meter_sandbox(tmp_path_factory):
    return _make_sandbox(tmp_path_factory.mktemp("ctxmeterkind"), FILE_HANDLER,
                         _METER_SHIM, _METER_STUBS)


@pytestmark_node
def test_a_meter_chip_says_what_the_file_is(meter_sandbox):
    report = _report()
    report["segments"][3]["items"] = [
        {"id": "a", "name": "main.py", "chars": 100, "state": "full", "kind": "code"},
        # A report from before the server said: classified from the name.
        {"id": "b", "name": "q3.xlsx", "chars": 100, "state": "full"},
    ]
    out = _run(meter_sandbox, _METER_PREAMBLE, """
        serve(%s, true);
        fh.init('');
        await tick();
        console.log(JSON.stringify({
          kinds: meter.querySelectorAll('.context-chip-kind').map((n) => n.textContent),
          title: meter.querySelector('.context-meter-title').textContent,
        }));
    """ % json.dumps(report))
    assert out["kinds"] == ["Code", "Spreadsheet"]
    # Named for what the characters are, not "context" and never "words".
    assert out["title"] == "Attachment text allowance"


@pytestmark_node
def test_the_meter_tells_the_wheel_when_attachments_change(meter_sandbox):
    out = _run(meter_sandbox, _METER_PREAMBLE, """
        const seen = [];
        globalThis.dispatchEvent = (ev) => { seen.push(ev.type); return true; };
        serve(%s, true);
        fh.init('');
        await tick();
        fh.renderContextMeter();
        console.log(JSON.stringify(seen));
    """ % json.dumps(_report()))
    assert "pantheon:attachments-changed" in out
