# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P4-06` / `P4-14` / `P4-07` — three rows, one footer and one popup.

The backend halves of all three landed in the merge this file is written
against, and each one's `Verify:` line is a `Law 15` sentence about a surface
that did not exist. Measured 2026-09-18 with the scope stated (`Law 5`): the
metrics footer and the Message Stats popup are drawn in exactly one function,
`displayMetrics` (`static/js/chatRenderer.js`), and before this patch it read
`response_time`, `input_tokens`, `output_tokens`, `tokens_per_second`,
`usage_source`, `context_percent`, `model`, the two prompt-cache counters and
`usage_buckets` — the last of those only to sum a cost out of it. It read
neither `failed` nor `failure`, neither `tps_source` nor any of `prefill_tps`,
`prefill_ms`, `decode_ms`, `prefill_tokens`, `decode_tokens`, and it named no
round.

  * **`P4-06`.** A failed turn's footer had the same shape, the same words and
    the same styling as a successful one. The reply text does carry
    `[Agent stopped: …]`, so the premise correction of 2026-08-27 holds and this
    is narrower than the original row: what renders identically is the footer
    and the popup. The HTTP status — the half a person can act on — existed on
    no surface at all.
  * **`P4-14`.** One `${tps} tok/s` stood for two different measurements of two
    different things. Prefill is the model reading what you sent and decode is
    the model writing the reply; a 40ms prefill and a 4s one produced the
    identical card at the identical rate. And `tps_source` — `backend` or
    `computed`, the enum that says whether anybody measured the number you are
    reading — had never been drawn, which is the distinction the row is named
    for.
  * **`P4-07`.** `_metricsBillableCost` walks `usage_buckets` to price each
    round on the route that answered it and returns one float. Every round's
    model, endpoint, tokens and speed was read and thrown away inside the loop
    that read it.

Driven under node against the real module, in the sandbox
`tests/test_tool_effect_surfaces_js.py` owns — the same one the approval card in
the same file is tested in (`Law 14`: one harness).

**Assertions read the screen, not the source.** Every case below renders a
footer, clicks it, and reads the popup a person would be looking at. A grep for
`prefill_ms` would pass against a renderer that printed it into a hidden
attribute; `Law 20`'s first preference is to call the thing.
"""

import json
import shutil
from html.parser import HTMLParser
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CHAT_RENDERER = ROOT / "static" / "js" / "chatRenderer.js"
STYLE = ROOT / "static" / "style.css"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


class _Rows(HTMLParser):
    """The popup's row template, as a person reads it.

    The shim stores an `innerHTML` assignment verbatim instead of parsing it, so
    the template comes back as markup and is parsed here. This reads the string
    the browser is handed — not the source that produced it — which is what
    separates a test of the renderer from a test of the file (`Law 20`).
    """

    def __init__(self):
        super().__init__()
        self.rows = []          # text of each top-level <div>
        self.tagged = {}        # class name -> [text, ...]
        self._stack = []

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "").split()
        self._stack.append({"tag": tag, "classes": classes, "text": [],
                            "top": len([f for f in self._stack if f["tag"] == "div"]) == 0})

    def handle_data(self, data):
        for frame in self._stack:
            frame["text"].append(data)

    def handle_endtag(self, tag):
        while self._stack:
            frame = self._stack.pop()
            text = " ".join("".join(frame["text"]).split())
            for name in frame["classes"]:
                self.tagged.setdefault(name, []).append(text)
            if frame["tag"] == "div" and frame["top"] and text:
                self.rows.append(text)
            if frame["tag"] == tag:
                break


def _rows(popup):
    parser = _Rows()
    parser.feed(popup["rowsHtml"] or "")
    parser.close()
    return parser


def _line(popup, prefix):
    """The one row starting with `prefix`, or an assertion naming what there was."""
    parsed = _rows(popup)
    found = [r for r in parsed.rows if r.startswith(prefix)]
    assert found, f"no row starting {prefix!r}; the popup drew {parsed.rows}"
    return found[0]


_STATS_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

globalThis.innerWidth = 1280;
globalThis.innerHeight = 800;

const history = document.body.appendChild(new Node('div'));
history.setAttribute('id', 'chat-history');
export { history };

/** A bare assistant bubble, which is what `displayMetrics` is handed. */
export function bubble() {
  const node = document.body.appendChild(new Node('div'));
  node.className = 'msg msg-ai';
  const body = node.appendChild(new Node('div'));
  body.className = 'body';
  return node;
}

/** Render a footer for `metrics`, then open the popup the way a person does. */
export function open(displayMetrics, metrics) {
  document.querySelectorAll('.ctx-popup').forEach((p) => p.remove());
  const node = bubble();
  displayMetrics(node, metrics);
  const footer = node.querySelector('.response-metrics');
  if (footer) footer.dispatchEvent({ type: 'click', stopPropagation() {} });
  return {
    footer: footer ? {
      text: footer.textContent,
      classes: String(footer.className || '').split(/\s+/).filter(Boolean),
      title: footer.title,
    } : null,
    popup: readPopup(),
  };
}

/** What the Message Stats popup says, read off the screen.
 *
 * The heading, the failure block and the round block are real nodes and are
 * read as nodes. The rows between them are one `innerHTML` template, which this
 * shim stores verbatim rather than parsing — so the markup comes back as a
 * string and the test parses it. Either way it is what the browser is handed,
 * never what the source says (`Law 20`).
 */
export function readPopup() {
  const popup = document.querySelector('.ctx-popup');
  if (!popup) return null;
  const rowsNode = popup.querySelector('.ctx-popup-rows');
  return {
    readable: popup.readable,
    heading: popup.querySelector('.ctx-popup-title')
      ? popup.querySelector('.ctx-popup-title').textContent : null,
    // The order of the blocks a person meets going down the popup.
    order: popup.children.map((n) => String(n.className || '')),
    rowsHtml: rowsNode ? rowsNode._html : null,
    failed: popup.querySelector('.ctx-failed') ? {
      headline: popup.querySelector('.ctx-failed-headline').textContent,
      message: popup.querySelector('.ctx-failed-message')
        ? popup.querySelector('.ctx-failed-message').textContent : null,
      // '' if and only if the renderer used `textContent` for the server's
      // sentence. The popup around it is assembled with `innerHTML`.
      messageHtml: popup.querySelector('.ctx-failed-message')
        ? popup.querySelector('.ctx-failed-message')._html : null,
      at: popup.children.indexOf(popup.querySelector('.ctx-failed')),
    } : null,
    rounds: popup.querySelector('.ctx-rounds') ? {
      title: popup.querySelector('.ctx-rounds-title').textContent,
      rows: popup.querySelectorAll('.ctx-round').map((r) => ({
        n: r.querySelector('.ctx-round-n').textContent,
        model: r.querySelector('.ctx-round-model').textContent,
        tokens: r.querySelector('.ctx-round-tokens').textContent,
        speed: r.querySelector('.ctx-round-speed').textContent,
        cost: r.querySelector('.ctx-round-cost').textContent,
        title: r.title,
        // Raw `_html` per cell: a model name is a string somebody configured.
        html: [
          r.querySelector('.ctx-round-model')._html,
          r.querySelector('.ctx-round-tokens')._html,
        ],
      })),
    } : null,
  };
}
"""

_STUBS = {
    "ui.js": """
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
export default {
  esc, showToast: () => {}, showError: () => {}, copyToClipboard: () => {},
  el: (id) => document.getElementById(id), debounce: (f) => f,
  autoResize: () => {}, scrollHistory: () => {}, formatBytes: (n) => String(n),
};
""",
    "markdown.js": """
export function svgifyEmoji(s) { return String(s == null ? '' : s); }
export default {
  renderContent: (c) => String(c), mdToHtml: (s) => String(s),
  processWithThinking: (s) => String(s), squashOutsideCode: (s) => String(s),
};
""",
    "tts-ai.js": "export function addAITTSButton(){}\n",
    "providers.js": "export function providerLogo(){return '';}\nexport function providerLabel(){return '';}\n",
    "settings.js": "export default { get: () => ({}) };\n",
    "spinner.js": """
export function createLoadingRow(){return {};}
export function createWhirlpool(){return { element: { style: {} }, destroy(){} };}
export default { createWhirlpool: () => ({ element: { style: {} }, destroy(){} }) };
""",
    "escMenuStack.js": "export function bindMenuDismiss(){return () => {};}\nexport function dismissOrRemove(){}\n",
    "panels.js": "export function loadPanel(){}\n",
    "appConfig.js": "export function getTools(){return Promise.resolve({ tools: [] });}\nexport function getSettings(){return Promise.resolve({});}\n",
    # `model/matchKey.js` is deliberately NOT stubbed. It is a pure, DOM-free
    # helper and `_copy_unstubbed_imports` brings in the real one — a stub
    # returning `null` prices every round at "not billed", which is exactly the
    # distinction the `P4-07` cost column exists to draw, so the stub would have
    # made the assertion unfalsifiable.
    "trustLadder.js": "export function buildAllowRuleChooser(){ return null; }\n",
}

_PREAMBLE = (
    "import { document, bubble, open, readPopup } from './shim.js';\n"
    "const { displayMetrics } = await import('./chatRenderer.js');\n"
)


@pytest.fixture(scope="module")
def stats_sandbox(tmp_path_factory):
    return _make_sandbox(
        tmp_path_factory.mktemp("msgstats"), CHAT_RENDERER, _STATS_SHIM, _STUBS
    )


def _stats(sandbox, metrics):
    return _run(sandbox, _PREAMBLE, """
        console.log(JSON.stringify(open(displayMetrics, %s)));
    """ % json.dumps(metrics))


# A turn a local llama.cpp measured end to end: both rates, both durations and
# both token counts, which is what a real `timings` block reports.
MEASURED = {
    "response_time": 7.1,
    "input_tokens": 4120,
    "output_tokens": 512,
    "tokens_per_second": 78.4,
    "tps_source": "backend",
    "prefill_tps": 1240.0,
    "prefill_ms": 3320.0,
    "decode_ms": 6530.0,
    "prefill_tokens": 4120,
    "decode_tokens": 512,
    "usage_source": "real",
    "model": "local/qwen3-30b",
    "context_percent": 12.5,
}

# A cloud API that reports tokens and nothing about time. Under the absence
# contract every timing key is simply not there.
UNTIMED = {
    "response_time": 5.0,
    "input_tokens": 900,
    "output_tokens": 300,
    "tokens_per_second": 60.0,
    "tps_source": "computed",
    "usage_source": "real",
    "model": "anthropic/claude",
    "context_percent": 4.0,
}


# ── P4-06 · a turn that stopped is not a turn that finished ─────────────────

def test_a_failed_turn_says_so_in_the_footer(stats_sandbox):
    ok = _stats(stats_sandbox, dict(UNTIMED))
    bad = _stats(stats_sandbox, dict(UNTIMED, failed=True,
                                     failure={"status": 502, "message": "upstream timed out"}))
    assert ok["footer"]["text"] != bad["footer"]["text"], (
        "a failed turn and a finished one produce the identical footer — which "
        "is the row"
    )
    assert "Stopped" in bad["footer"]["text"], bad["footer"]["text"]
    assert "Stopped" not in ok["footer"]["text"]
    assert "response-metrics-failed" in bad["footer"]["classes"]
    assert "response-metrics-failed" not in ok["footer"]["classes"]
    assert "stopped early" in bad["footer"]["title"], (
        "the hover text still invites a click as though nothing happened"
    )


def test_the_popup_says_what_went_wrong_and_what_the_status_was(stats_sandbox):
    """The HTTP status is the half a person can act on — a 429 is "wait", a 502
    is "the endpoint", a 400 is "the request" — and it existed on no surface."""
    out = _stats(stats_sandbox, dict(UNTIMED, failed=True,
                                     failure={"status": 429, "message": "rate limit reached"}))
    assert out["popup"]["failed"] is not None, "the popup drew no failure at all"
    assert "429" in out["popup"]["failed"]["headline"]
    assert out["popup"]["failed"]["message"] == "rate limit reached"
    assert out["popup"]["heading"] == "Message Stats"
    assert out["popup"]["order"][:2] == ["ctx-popup-title", "ctx-failed"], (
        "the failure is the only thing in this popup that is news; it belongs "
        f"directly under the title, and the popup reads {out['popup']['order']}"
    )


def test_the_servers_sentence_reaches_the_popup_as_text_and_never_as_markup(stats_sandbox):
    """This popup is assembled with `innerHTML` and `failure.message` is a
    sentence chosen by a provider. Read through the raw `_html`, because the
    shim's `textContent` getter strips tags and an `innerHTML` swap is invisible
    to any assertion that goes through text."""
    hostile = '<img src=x onerror="alert(1)">'
    out = _stats(stats_sandbox, dict(UNTIMED, failed=True,
                                     failure={"status": 500, "message": hostile}))
    assert out["popup"]["failed"]["messageHtml"] == ""
    assert out["popup"]["failed"]["message"] == hostile


def test_a_failure_with_no_figures_at_all_still_draws_a_footer(stats_sandbox):
    """A turn that died before any measurement is exactly the turn whose reader
    has nothing else to go on. The old bail-out returned before drawing
    anything, so the only surface that could say "this stopped" said nothing."""
    out = _stats(stats_sandbox, {"failed": True,
                                 "failure": {"status": 503, "message": "no route answered"},
                                 "model": "local/qwen3-30b"})
    assert out["footer"] is not None, "nothing was drawn for a failure with no metrics"
    assert out["footer"]["text"] == "Stopped"
    assert out["popup"]["failed"]["message"] == "no route answered"


def test_a_finished_turn_draws_no_failure_block(stats_sandbox):
    out = _stats(stats_sandbox, dict(MEASURED))
    assert out["popup"]["failed"] is None
    assert "Stopped" not in out["popup"]["readable"]


# ── P4-14 · prefill and decode, measured or estimated ───────────────────────

def test_the_one_speed_row_became_prefill_and_decode(stats_sandbox):
    """Two phases, two rows, in the order they happen. One number standing for
    both is the row."""
    out = _stats(stats_sandbox, dict(MEASURED))
    rows = _rows(out["popup"]).rows
    prefill = next(i for i, r in enumerate(rows) if r.startswith("Prefill"))
    decode = next(i for i, r in enumerate(rows) if r.startswith("Decode"))
    assert prefill < decode, f"decode is drawn before prefill: {rows}"
    assert "1,240 tok/s" in rows[prefill], rows[prefill]
    assert "78.4 tok/s" in rows[decode], rows[decode]
    assert not [r for r in rows if r.startswith("Speed")], (
        f"the single Speed row survived beside the two that replace it: {rows}"
    )


def test_each_rate_is_shown_beside_what_it_is_a_quotient_of(stats_sandbox):
    """A rate nobody can divide back out is a claim. The durations and the token
    counts were measured, passed through and dropped on the floor, and without
    them nothing could separate prefill from decode *in time*."""
    out = _stats(stats_sandbox, dict(MEASURED))
    subs = " | ".join(_rows(out["popup"]).tagged.get("ctx-sub", []))
    assert "4,120 tokens" in subs and "3.32s" in subs, subs
    assert "512 tokens" in subs and "6.53s" in subs, subs
    assert "reading your prompt" in subs and "writing the answer" in subs, (
        "the two phases are named in jargon and explained nowhere — `Law 15`"
    )


def test_measured_and_estimated_are_told_apart_on_the_screen(stats_sandbox):
    """`tps_source` is the word this row is named for. `backend` means
    llama.cpp's own `timings` block reported it; `computed` means tokens over a
    wall clock that includes the prefill and the overhead, so it reads low.
    Before this, both printed the identical row."""
    measured = _stats(stats_sandbox, dict(MEASURED))
    estimated = _stats(stats_sandbox, dict(UNTIMED))
    m_tags = _rows(measured["popup"]).tagged.get("ctx-measure", [])
    e_tags = _rows(estimated["popup"]).tagged.get("ctx-measure", [])
    assert "measured" in m_tags, m_tags
    assert "estimated" in e_tags, e_tags
    assert "estimated" not in m_tags, m_tags
    decode_measured = _line(measured["popup"], "Decode")
    decode_estimated = _line(estimated["popup"], "Decode")
    assert decode_measured != decode_estimated, (
        "a backend-measured decode speed and a wall-clock estimate read the same"
    )
    assert "measured" in decode_measured and "estimated" in decode_estimated


def test_an_unreported_prefill_says_so_rather_than_drawing_a_zero(stats_sandbox):
    """The absence contract, which is the whole reason these keys are optional:
    `prefill_ms: 0` on a cloud API would read as an instantaneous prefill rather
    than as a backend that does not say."""
    out = _stats(stats_sandbox, dict(UNTIMED))
    prefill = _line(out["popup"], "Prefill")
    assert "not reported" in prefill, prefill
    assert "0 tok/s" not in prefill and "0ms" not in prefill, prefill


def test_a_partial_timings_block_carries_what_it_measured(stats_sandbox):
    """Some builds report the prompt half and not the predicted half. It shows
    what it has and invents nothing."""
    out = _stats(stats_sandbox, dict(UNTIMED, prefill_tps=980.0,
                                     prefill_ms=1400.0, prefill_tokens=1372))
    prefill = _line(out["popup"], "Prefill")
    assert "980 tok/s" in prefill, prefill
    subs = " | ".join(_rows(out["popup"]).tagged.get("ctx-sub", []))
    assert "1,372 tokens" in subs and "1.40s" in subs, subs
    # The decode half was not measured, and the estimate must still say so.
    assert "estimated" in _rows(out["popup"]).tagged.get("ctx-measure", [])


# ── P4-07 · one line per round ──────────────────────────────────────────────

_BUCKETS = [
    {"round": 1, "model": "local/qwen3-30b", "endpoint_id": "e1",
     "endpoint_label": "Workshop GPU", "input_tokens": 40120, "output_tokens": 210,
     "usage_source": "real", "endpoint_cost_tracked": False, "gen_tps": 91.2},
    {"round": 2, "model": "local/qwen3-30b", "endpoint_id": "e1",
     "endpoint_label": "Workshop GPU", "input_tokens": 41010, "output_tokens": 180,
     "usage_source": "real", "endpoint_cost_tracked": False, "gen_tps": 62.7},
    {"round": 3, "model": "anthropic/claude-sonnet-4", "endpoint_id": "e2",
     "endpoint_label": "Anthropic", "input_tokens": 41900, "output_tokens": 640,
     "usage_source": "real", "endpoint_cost_tracked": True},
]


def test_every_round_gets_its_own_line(stats_sandbox):
    """"See which round cost what — without knowing that a bucket exists." A
    five-round turn reported one model, one cost and the *fifth* round's decode
    speed as the turn's."""
    out = _stats(stats_sandbox, dict(MEASURED, usage_buckets=_BUCKETS))
    rounds = out["popup"]["rounds"]
    assert rounds is not None, "the buckets were walked for a cost and drawn nowhere"
    assert [r["n"] for r in rounds["rows"]] == ["1", "2", "3"]
    assert "3" in rounds["title"], rounds["title"]


def test_a_round_names_the_model_that_answered_it(stats_sandbox):
    """Two rounds on two models is the case the row is about: a fallback to a
    paid route showed a single model name and a single cost."""
    out = _stats(stats_sandbox, dict(MEASURED, usage_buckets=_BUCKETS))
    models = [r["model"] for r in out["popup"]["rounds"]["rows"]]
    assert models == ["qwen3-30b", "qwen3-30b", "claude-sonnet-4"], models
    labels = [r["title"] for r in out["popup"]["rounds"]["rows"]]
    assert "Workshop GPU" in labels[0] and "Anthropic" in labels[2], labels


def test_a_round_says_what_it_spent_and_what_it_cost(stats_sandbox):
    out = _stats(stats_sandbox, dict(MEASURED, usage_buckets=_BUCKETS))
    rows = out["popup"]["rounds"]["rows"]
    assert "40,120 in" in rows[0]["tokens"] and "210 out" in rows[0]["tokens"], rows[0]
    # `endpoint_cost_tracked: False` is the local route; it is not billed, and
    # saying "$0.000" there would be a claim about a price that does not exist.
    assert rows[0]["cost"] == "not billed", rows[0]
    assert rows[2]["cost"].startswith("$"), rows[2]


def test_a_rounds_own_speed_is_the_one_drawn_beside_it(stats_sandbox):
    """`backend_gen_tps` was one variable every round overwrote. Round 1 against
    a 40k prompt and round 5 against a 200-token continuation are not the same
    measurement, and the turn reported only the last."""
    out = _stats(stats_sandbox, dict(MEASURED, usage_buckets=_BUCKETS))
    speeds = [r["speed"] for r in out["popup"]["rounds"]["rows"]]
    assert speeds[0] == "91.2 tok/s" and speeds[1] == "62.7 tok/s", speeds
    assert speeds[0] != speeds[1], "every round drew the same speed"
    # Round 3's provider reported none. Absence is a dash, never a zero.
    assert speeds[2] == "—", speeds


def test_a_model_name_reaches_the_round_row_as_text(stats_sandbox):
    """`model` and `endpoint_label` are strings whoever configured the endpoint
    chose, and this popup is built with `innerHTML`."""
    hostile = "<img src=x onerror=alert(1)>"
    buckets = [dict(_BUCKETS[0], model=hostile), dict(_BUCKETS[1])]
    out = _stats(stats_sandbox, dict(MEASURED, usage_buckets=buckets))
    rows = out["popup"]["rounds"]["rows"]
    assert rows[0]["html"] == ["", ""], rows[0]["html"]
    assert rows[0]["model"] == hostile


def test_a_turn_with_one_round_draws_no_round_block(stats_sandbox):
    """One bucket says nothing the Model and token rows above it do not already
    say, and a block that repeats its own summary is noise a reader learns to
    skip past — including past the case where it matters."""
    out = _stats(stats_sandbox, dict(MEASURED, usage_buckets=[dict(_BUCKETS[0])]))
    assert out["popup"]["rounds"] is None
    plain = _stats(stats_sandbox, dict(MEASURED))
    assert plain["popup"]["rounds"] is None


# ── the stylesheet half ─────────────────────────────────────────────────────

def test_the_new_surfaces_add_no_full_strength_accent_colour():
    """`tests/test_accent_fallback_semantics_css.py` pins the sheet at 814 uses
    of `--accent` and says in its own words that a new full-strength accent
    `color:` is a new instance of a known defect — it fails 4.5:1 on seven of
    the sixteen palettes. This asserts the *absence* of a string from a bounded
    region, which is the one thing `Law 20` permits a substring search for."""
    css = STYLE.read_text(encoding="utf-8")
    start = css.index("P4-04 / P4-06 / P4-07 / P4-14 / P12-09")
    block = css[start:]
    assert "var(--accent" not in block, (
        "the surface halves introduced an accent site; borders, left rules and "
        "currentColor are the house alternative"
    )
    assert "--accent:" not in block
