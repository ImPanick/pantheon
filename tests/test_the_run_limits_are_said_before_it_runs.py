# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P7-10` — how far an agent run may go, said before it runs.

*"How far can it run unattended" sits in a settings tab, invisible when you
choose.* Measured on the tree this row started from, it was worse than
invisible: the settings tab was not the answer. On local inference `H08` lifts a
step cap nobody pinned to 100,000, so *Max steps per message: 20* described a
run that would go to 100,000. `P4-23` made the loop send the limits it actually
enforces, but only in `agent_budget` frames — once a run was already going.

So the composer now asks `GET /api/chat/agent-limits` about the model it has
selected, and says the answer beside the Agent / Chat toggle. Three properties
make that honest, and each has tests here:

  * **one resolution** (`Law 7`): the route answers with the loop's own helpers,
    so for the same settings and endpoint it says exactly what the run's first
    `agent_budget` frame will say — driven through the real loop, not compared
    against a copy;
  * **one reading of the settings**: the route and `chat_stream` read the two
    caps through `run_limits.configured_agent_caps`, so the number promised is
    the number handed to the loop, clamps and fallbacks included;
  * **the same selection**: the route resolves the selected endpoint the way a
    send does — an id first, owner-scoped — so it cannot describe a different
    endpoint from the one the message will run on.

In the browser the words are the meter's own (`agentMeter.js`), the hint asks
about the route a send would use, and a stale answer cannot overwrite a newer
one. Driven, not read (`Law 20`); the markup and CSS checks at the end are the
two things that only exist as markup and CSS.
"""

import asyncio
import importlib
import json
import shutil
import subprocess
import textwrap
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import routes.chat_routes as chat_routes
import src.agent_loop as agent_loop
import src.runtime_limits as runtime_limits
from core.database import Base, ModelEndpoint
from tests.helpers.js_source import js_definition, js_function
from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
AGENT_METER = ROOT / "static" / "js" / "agentMeter.js"
CHAT_JS = ROOT / "static" / "js" / "chat.js"
SETTINGS_JS = ROOT / "static" / "js" / "settings.js"
INDEX = ROOT / "static" / "index.html"
STYLE = ROOT / "static" / "style.css"

node_only = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

CLOUD = "https://api.example.com/v1/chat/completions"
LOCAL = "http://localhost:1234/v1/chat/completions"
LAN = "http://192.168.1.20:8080/v1/chat/completions"
LIMIT_KEYS = ("round_limit", "round_limit_source", "round_limit_configured", "tool_call_limit")


# ── a settings store of our own ─────────────────────────────────────────────

@pytest.fixture
def stored(tmp_path, monkeypatch):
    """Write `settings.json` into a data dir of our own and read it back the way
    the product does. `setting_is_explicit` — the pin that stops the local
    lift — opens this file, so a stub of `get_setting` alone would not do."""
    monkeypatch.setenv("PANTHEON_DATA_DIR", str(tmp_path))
    import src.constants
    import src.settings as settings
    importlib.reload(src.constants)
    importlib.reload(settings)

    def write(values):
        (tmp_path / "settings.json").write_text(json.dumps(values), encoding="utf-8")
        settings._invalidate_caches()

    yield write
    monkeypatch.delenv("PANTHEON_DATA_DIR", raising=False)
    importlib.reload(src.constants)
    importlib.reload(settings)


# ── one resolution: the route says what the loop's first frame says ────────

def _first_budget_frame(monkeypatch, url, *, max_rounds, max_tool_calls):
    """The real loop, with only the model scripted: one plain reply, no tools."""
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    monkeypatch.setattr(agent_loop, "blocked_tools_for_owner", lambda owner: set(), raising=False)

    async def fake_stream(*args, **kwargs):
        yield f"data: {json.dumps({'delta': 'Done.'})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)

    async def _go():
        return [c async for c in agent_loop.stream_agent_loop(
            url, "m", [{"role": "user", "content": "go"}],
            max_rounds=max_rounds, max_tool_calls=max_tool_calls,
            relevant_tools={"update_plan"})]

    for chunk in asyncio.run(_go()):
        if chunk.startswith("data: {"):
            frame = json.loads(chunk[6:])
            if frame.get("type") == "agent_budget":
                return frame
    raise AssertionError("the loop sent no agent_budget frame")


_SCENARIOS = [
    # (id, endpoint, stored settings, forced unlimited, expected source, expected round limit)
    ("cloud-default", CLOUD, {}, False, "configured", 20),
    ("local-lifted", LOCAL, {}, False, "local_lift", 100_000),
    ("local-pinned", LOCAL, {"agent_max_rounds": 30}, False, "configured", 30),
    ("forced", CLOUD, {}, True, "forced_lift", 100_000),
    ("lan-with-a-tool-limit", LAN, {"agent_max_tool_calls": 7}, False, "local_lift", 100_000),
]


@pytest.mark.parametrize("_id,url,values,forced,source,round_limit", _SCENARIOS,
                         ids=[s[0] for s in _SCENARIOS])
def test_before_a_run_the_route_says_what_the_runs_first_frame_says(
        monkeypatch, stored, _id, url, values, forced, source, round_limit):
    """`Law 7`. The promise before the run and the meter at step 1 are one
    answer, from one set of helpers, for every way the step cap can come out."""
    from src.run_limits import configured_agent_caps

    stored(values)
    monkeypatch.setattr(runtime_limits, "_FORCE_UNLIMITED", forced)
    caps = configured_agent_caps()

    before = agent_loop.agent_run_limits(url, caps.rounds, caps.tool_calls)
    frame = _first_budget_frame(monkeypatch, url, max_rounds=caps.rounds,
                                max_tool_calls=caps.tool_calls)

    assert {k: frame[k] for k in LIMIT_KEYS} == before
    assert (before["round_limit_source"], before["round_limit"]) == (source, round_limit)


def test_a_local_model_is_not_promised_the_number_in_settings(stored):
    """The premise, measured: *Max steps per message* says 20, and a run on a
    local model is held to 100,000. A promise read from the setting would be
    the lie this row exists to stop telling."""
    from src.run_limits import configured_agent_caps

    stored({})
    caps = configured_agent_caps()
    assert caps.rounds == 20
    limits = agent_loop.agent_run_limits(LOCAL, caps.rounds, caps.tool_calls)
    assert limits["round_limit"] == 100_000
    assert limits["round_limit_configured"] == 20
    assert limits["tool_call_limit"] is None, "no tool-call limit is `null`, never `0` (`Law 10`)"


# ── one reading: what the route promises is what chat_stream hands the loop ─

def _limits_endpoint():
    router = chat_routes.setup_chat_routes(
        SimpleNamespace(), SimpleNamespace(), SimpleNamespace(),
        SimpleNamespace(), SimpleNamespace(), SimpleNamespace(),
    )
    return next(r.endpoint for r in router.routes if r.path == "/api/chat/agent-limits")


def _limits(endpoint, **query):
    request = SimpleNamespace(state=SimpleNamespace(current_user="alice"), headers={})
    return asyncio.run(endpoint(request, **query))


@pytest.mark.parametrize("values", [
    {"agent_max_rounds": 35, "agent_max_tool_calls": 12},
    {"agent_max_rounds": 0, "agent_max_tool_calls": "unlimited"},   # falsy → the loop default
    {"agent_max_rounds": 500, "agent_max_tool_calls": 0},           # clamped to 200
    {"agent_max_rounds": "lots", "agent_max_tool_calls": None},     # unparseable
], ids=["typed", "falsy-and-junk", "over-the-range", "unparseable"])
@pytest.mark.asyncio
async def test_the_route_promises_the_caps_chat_stream_hands_the_loop(monkeypatch, values):
    captured = {}
    stream = _chat_stream_endpoint(monkeypatch, "agent", captured,
                                   endpoint_url="https://selected.example/v1")

    async def capturing_loop(endpoint_url, model, messages, **kwargs):
        captured["loop"] = (kwargs["max_rounds"], kwargs["max_tool_calls"])
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat_routes, "stream_agent_loop", capturing_loop)
    import src.settings as settings
    monkeypatch.setattr(settings, "get_setting",
                        lambda key, default=None: values.get(key, default))

    response = await stream(_RouteRequest("agent"))
    async for _ in response.body_iterator:
        pass
    promised = await _limits_endpoint()(
        SimpleNamespace(state=SimpleNamespace(current_user="alice"), headers={}),
        endpoint_id="", endpoint_url="https://selected.example/v1")

    rounds, tool_calls = captured["loop"]
    assert promised["round_limit_configured"] == rounds
    assert promised["tool_call_limit"] == (tool_calls if tool_calls > 0 else None)


# ── the same selection: the route resolves an endpoint the way a send does ──

@pytest.fixture
def endpoints(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autoflush=False)
    db = TestSession()
    db.add_all([
        # OpenAI-compatible bases (`/v1`). Since `B929` the lift classifies an
        # endpoint as `model_context.is_local_endpoint` does, so Ollama's native
        # `/api/chat` is lifted too — driven in
        # `tests/test_the_local_lift_asks_what_everything_else_asks.py`.
        ModelEndpoint(id="ep-local", name="LM Studio", base_url="http://localhost:1234/v1",
                      owner="alice", is_enabled=True),
        ModelEndpoint(id="ep-cloud", name="Cloud", base_url="https://api.example.com/v1",
                      owner="alice", is_enabled=True),
        ModelEndpoint(id="ep-bobs", name="Bob's box", base_url="http://localhost:9999/v1",
                      owner="bob", is_enabled=True),
        ModelEndpoint(id="ep-off", name="Switched off", base_url="http://localhost:7777/v1",
                      owner="alice", is_enabled=False),
    ])
    db.commit()
    db.close()
    monkeypatch.setattr(chat_routes, "SessionLocal", TestSession)
    monkeypatch.setattr(chat_routes, "effective_user", lambda request: "alice")
    import src.settings as settings
    monkeypatch.setattr(settings, "get_setting", lambda key, default=None: default)
    monkeypatch.setattr(agent_loop, "_setting_pinned", lambda key: False)
    return _limits_endpoint()


@pytest.mark.parametrize("query,source", [
    # The registered id wins over whatever URL rides along, as it does on send.
    ({"endpoint_id": "ep-local", "endpoint_url": CLOUD}, "local_lift"),
    ({"endpoint_id": "ep-cloud", "endpoint_url": LOCAL}, "configured"),
    # A URL alone is matched against the caller's own endpoints.
    ({"endpoint_url": "http://localhost:1234/v1/chat/completions"}, "local_lift"),
    # Another owner's endpoint is not the caller's to run on: the id resolves
    # to nothing and the URL the composer sent is what a send would fall back to.
    ({"endpoint_id": "ep-bobs", "endpoint_url": CLOUD}, "configured"),
    # A switched-off endpoint is not a route either.
    ({"endpoint_id": "ep-off", "endpoint_url": CLOUD}, "configured"),
    # Nothing selected: nothing to lift for.
    ({}, "configured"),
], ids=["id-over-url", "cloud-id", "url-only", "not-the-callers", "disabled", "nothing"])
def test_the_route_resolves_the_selection_the_way_a_send_does(endpoints, query, source):
    answer = _limits(endpoints, **{"endpoint_id": "", "endpoint_url": "", **query})
    assert answer["round_limit_source"] == source
    # `P7-12` adds who may raise each limit for a run; still nothing about the
    # endpoint itself.
    raise_keys = {"round_limit_raise", "round_limit_raise_ceiling", "tool_call_limit_raise"}
    assert set(answer) == set(LIMIT_KEYS) | raise_keys, "the answer names no endpoint, host or key"


# ── the words, under node ───────────────────────────────────────────────────

_SHIM = r"""
import { installDom } from './dom.js';
export const document = installDom();
export function hint(node) {
  return { text: node.textContent, title: node.title, hidden: !!node.hidden,
           source: node.dataset.source || '', html: node._html || '' };
}
"""
_PREAMBLE = (
    "import { document, hint } from './shim.js';\n"
    "const m = await import('./agentMeter.js');\n"
)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    return _make_sandbox(tmp_path_factory.mktemp("runlimits"), AGENT_METER, _SHIM, {})


def _preview(sandbox, payload):
    return _run(sandbox, _PREAMBLE, """
        const node = document.createElement('span');
        const view = m.renderLimitsHint(node, %s);
        console.log(JSON.stringify({ view, hint: hint(node) }));
    """ % json.dumps(payload))


@node_only
@pytest.mark.parametrize("payload,text", [
    ({"round_limit": 20, "round_limit_source": "configured", "round_limit_configured": 20,
      "tool_call_limit": None}, "Up to 20 steps"),
    ({"round_limit": 20, "round_limit_source": "configured", "round_limit_configured": 20,
      "tool_call_limit": 10}, "Up to 20 steps · 10 tool calls"),
    ({"round_limit": 150, "round_limit_source": "configured", "round_limit_configured": 150,
      "tool_call_limit": 1}, "Up to 150 steps · 1 tool call"),
    # `P23-04` (CHAT-U-16): no step limit is not said; the tool limit still is.
    ({"round_limit": 100000, "round_limit_source": "forced_lift", "round_limit_configured": 20,
      "tool_call_limit": 5}, "5 tool calls"),
], ids=["steps", "steps-and-calls", "one-call", "forced-lift"])
def test_the_hint_says_the_limit_in_a_few_words(sandbox, payload, text):
    out = _preview(sandbox, payload)
    assert out["hint"]["text"] == text
    assert out["hint"]["hidden"] is False
    assert out["hint"]["source"] == payload["round_limit_source"]
    assert out["hint"]["html"] == "", "the words are text, never markup"


@node_only
def test_a_lifted_limit_is_not_promised_as_a_bar_toward_100000(sandbox):
    """`P4-23`'s rule before the run as during it: a lifted cap is said to be
    lifted, and its number is in the sentence that explains it, not the chip."""
    out = _preview(sandbox, {"round_limit": 100000, "round_limit_source": "local_lift",
                             "round_limit_configured": 20, "tool_call_limit": None})
    assert "100,000" not in out["hint"]["text"]
    # `P23-04` (CHAT-U-16): with no limit at all there is nothing to promise,
    # so the chip is quiet; the run's own meter still says the cap was lifted
    # (`test_the_meter_warns_before_the_stop.py`).
    assert out["view"] is None and out["hint"]["hidden"] is True


@node_only
@pytest.mark.parametrize("payload", [
    None, "junk", {}, {"round_limit": 0, "round_limit_source": "configured"},
    {"round_limit": "<b>20</b>", "round_limit_source": "configured"},
], ids=["nothing", "a-string", "empty", "zero", "markup"])
def test_the_hint_says_nothing_rather_than_guess(sandbox, payload):
    """`Law 10`. No step limit in the answer is not a limit of 0, and not the
    setting either: the chip goes quiet until it knows."""
    out = _preview(sandbox, payload)
    assert out["view"] is None
    assert out["hint"] == {"text": "", "title": "", "hidden": True, "source": "", "html": ""}


@node_only
@pytest.mark.parametrize("payload", [
    {"round_limit": 20, "round_limit_source": "configured", "round_limit_configured": 20,
     "tool_call_limit": 10},
    {"round_limit": 100000, "round_limit_source": "forced_lift", "round_limit_configured": 40,
     "tool_call_limit": 3},
], ids=["configured", "forced-lift"])
def test_the_promise_and_the_meter_are_one_vocabulary(sandbox, payload):
    """The hint's sentence is the meter's hover text at step 1 of the same
    limits, with only the subject changed — *Each message in Agent mode*
    before the run, *This run* during it. A second set of words would drift."""
    out = _run(sandbox, _PREAMBLE, """
        const payload = %s;
        const preview = m.limitsPreview(payload);
        const meter = m.createAgentMeter({ document, setInterval: () => 1, clearInterval: () => {} });
        meter.update({ type: 'agent_budget', round: 1, tool_calls: 0, ...payload });
        console.log(JSON.stringify({ before: preview.title,
          during: meter.node.querySelector('.agent-meter-budget').title }));
    """ % json.dumps(payload))
    assert out["before"].replace("Each message in Agent mode", "This run") == out["during"]


# ── the wiring in chat.js ───────────────────────────────────────────────────

def _chat_fn(signature):
    source = CHAT_JS.read_text(encoding="utf-8")
    return js_definition(source, source.index(signature)).replace("export ", "", 1)


_WIRING = textwrap.dedent("""
    import { document } from './shim.js';
    const { renderLimitsHint } = await import('./agentMeter.js');
    const node = document.createElement('span');
    node.id = 'agent-limits-hint';
    document.body.appendChild(node);
    const asked = [];
    const answers = [];
    let API_BASE = '';
    const window = globalThis;
    globalThis.fetch = (url, opts) => {
      asked.push({ url, credentials: opts && opts.credentials });
      return new Promise((resolve) => answers.push(resolve));
    };
    const answer = (i, body, ok = true) => answers[i]({ ok, json: async () => body });
    const sessionModule = {
      getPendingChat: () => null,
      getCurrentModel: () => 'qwen-local',
      getCurrentEndpointUrl: () => 'http://localhost:1234/v1/chat/completions',
    };
    let _agentLimitsSeq = 0;
    %s
    %s
    const tick = () => new Promise((r) => setTimeout(r, 0));
    const read = () => ({ text: node.textContent, hidden: !!node.hidden, title: node.title });
""")


def _wiring(script):
    return _WIRING % (_chat_fn("export function selectedRoute"),
                      _chat_fn("export async function refreshAgentLimitsHint")) + textwrap.dedent(script)


@pytest.fixture(scope="module")
def wiring_sandbox(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    return _make_sandbox(tmp_path_factory.mktemp("runlimitswiring"), AGENT_METER, _SHIM, {})


def _drive(wiring_sandbox, script):
    return _run(wiring_sandbox, "", _wiring(script))


_LOCAL_ANSWER = {"round_limit": 100000, "round_limit_source": "local_lift",
                 "round_limit_configured": 20, "tool_call_limit": None}
_CLOUD_ANSWER = {"round_limit": 20, "round_limit_source": "configured",
                 "round_limit_configured": 20, "tool_call_limit": None}


@node_only
def test_the_hint_asks_about_the_route_the_next_send_will_use(wiring_sandbox):
    """A model picked in the last ten minutes is what a send posts as
    `selected_*`, so it is what the hint asks about — id and URL both."""
    out = _drive(wiring_sandbox, """
        window.__pantheonLastPickedRoute = { model: 'gpt-x', endpoint_id: 'ep-cloud',
          endpoint_url: 'https://api.example.com/v1/chat/completions', picked_at: Date.now() };
        const done = refreshAgentLimitsHint();
        answer(0, %s);
        await done;
        console.log(JSON.stringify({ asked, shown: read() }));
    """ % json.dumps(_CLOUD_ANSWER))
    assert out["asked"] == [{
        "url": "/api/chat/agent-limits?endpoint_id=ep-cloud&endpoint_url="
               "https%3A%2F%2Fapi.example.com%2Fv1%2Fchat%2Fcompletions",
        "credentials": "same-origin",
    }]
    assert out["shown"]["text"] == "Up to 20 steps"
    assert out["shown"]["hidden"] is False


@node_only
def test_with_nothing_picked_it_asks_about_the_open_chat(wiring_sandbox):
    out = _drive(wiring_sandbox, """
        const done = refreshAgentLimitsHint();
        answer(0, %s);
        await done;
        console.log(JSON.stringify({ asked, shown: read() }));
    """ % json.dumps(_LOCAL_ANSWER))
    assert out["asked"][0]["url"] == (
        "/api/chat/agent-limits?endpoint_url="
        "http%3A%2F%2Flocalhost%3A1234%2Fv1%2Fchat%2Fcompletions")
    # `P23-04` (CHAT-U-16): a lifted step limit with no tool limit says nothing.
    assert out["shown"]["hidden"] is True


@node_only
def test_a_slow_answer_about_the_last_model_cannot_paint_over_the_new_one(wiring_sandbox):
    """Switch from a local model to a cloud one while the first answer is still
    on its way: the chip must end on the cloud model's limit."""
    out = _drive(wiring_sandbox, """
        const first = refreshAgentLimitsHint();
        window.__pantheonLastPickedRoute = { model: 'gpt-x', endpoint_id: 'ep-cloud',
          endpoint_url: '', picked_at: Date.now() };
        const second = refreshAgentLimitsHint();
        answer(1, %s);
        await second;
        answer(0, %s);
        await first;
        console.log(JSON.stringify({ shown: read(), n: asked.length }));
    """ % (json.dumps(_CLOUD_ANSWER), json.dumps(_LOCAL_ANSWER)))
    assert out["n"] == 2
    assert out["shown"]["text"] == "Up to 20 steps"


@node_only
def test_a_failed_answer_says_nothing_rather_than_keep_an_old_promise(wiring_sandbox):
    out = _drive(wiring_sandbox, """
        let done = refreshAgentLimitsHint();
        answer(0, %s);
        await done;
        const before = read();
        done = refreshAgentLimitsHint();
        answer(1, { detail: 'boom' }, false);
        await done;
        console.log(JSON.stringify({ before, after: read() }));
    """ % json.dumps(_CLOUD_ANSWER))
    assert out["before"]["hidden"] is False
    assert out["after"] == {"text": "", "hidden": True, "title": ""}


@node_only
def test_the_hint_is_asked_again_whenever_the_answer_can_change(wiring_sandbox):
    """A new model, a new chat, choosing Agent, saving the Agent settings, and
    coming back to the page: each can change the answer, so each asks."""
    wire = _chat_fn("function _wireAgentLimitsHint")
    out = _run(wiring_sandbox, "", textwrap.dedent("""
        const listened = [];
        const clicked = [];
        const document = { addEventListener: (t) => listened.push('document:' + t),
          getElementById: (id) => (id === 'mode-agent-btn'
            ? { addEventListener: (t) => clicked.push(t) } : null) };
        const window = { addEventListener: (t) => listened.push('window:' + t) };
        let asked = 0;
        const refreshAgentLimitsHint = () => { asked += 1; };
        %s
        _wireAgentLimitsHint();
        console.log(JSON.stringify({ listened, clicked, asked }));
    """) % wire)
    assert sorted(out["listened"]) == sorted([
        "document:pantheon:model-picked", "document:pantheon:session-changed",
        "document:pantheon:agent-limits-changed", "window:focus",
    ])
    assert out["clicked"] == ["click"]
    assert out["asked"] == 1, "and once at start, so the first screen already says it"


def test_saving_the_agent_settings_tells_the_composer():
    """The one change the page itself makes to the answer. Scoped to the save
    function (`Law 20`, option 2), after the write it announces."""
    source = SETTINGS_JS.read_text(encoding="utf-8")
    start = source.index("async function initAgentSettings")
    save = js_function(source[start:], "async function save")
    posted = save.index("await _postSettings(payload)")
    announced = save.index("new CustomEvent('pantheon:agent-limits-changed')")
    assert posted < announced < save.index("msg.textContent")


# ── the markup and the style: the two things that only exist as such ──────

class _Composer(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.order, self.found = [], [], {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if "chat-input-right" in classes:
            self.stack.append("right")
        if self.stack and self.stack[-1] == "right":
            if a.get("id"):
                self.order.append(a["id"])
            if "mode-toggle" in classes:
                self.order.append(".mode-toggle")
        if a.get("id") in {"agent-limits-hint", "mode-agent-btn"}:
            self.found[a["id"]] = a


def test_the_hint_sits_beside_the_toggle_and_describes_the_agent_button():
    parser = _Composer()
    parser.feed(INDEX.read_text(encoding="utf-8"))
    order = parser.order
    assert order.index("agent-limits-hint") < order.index(".mode-toggle"), \
        "said beside the toggle where Agent is chosen, before the send button"
    assert "hidden" in parser.found["agent-limits-hint"], "nothing is said before it is known"
    assert parser.found["mode-agent-btn"].get("aria-describedby") == "agent-limits-hint"


def _p7_10_block():
    css = STYLE.read_text(encoding="utf-8")
    start = css.index("`P7-10`. How far one message in Agent mode may go")
    return css[start:css.index("\n\n", start)]


def test_the_hint_is_only_drawn_in_agent_mode_and_goes_first_when_narrow():
    block = _p7_10_block()
    assert ".chat-input-right:not(:has(#mode-agent-btn.active)) .agent-limits-hint" in block
    assert "@container chatbar (max-width: 660px)" in block, "before it costs a tool chip"
    assert "var(--color-muted-alt)" in block
    assert "--accent" not in block.split("*/", 1)[1], "no hue carries meaning here"
    assert "transition" not in block and "animation" not in block
