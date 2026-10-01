# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1050` — Agent mode's force-answer salvage is the answering candidate's request.

When the loop breaker forces a tool-free round and the model still writes no
prose, the loop makes one non-streaming synthesis call over everything the turn
gathered (`src/agent_loop.py`, the `_force_answer` block) before it falls back to
a canned apology. The row read that call as "always the primary's URL, model and
headers, with the primary's lifted length".

**Measured before the fix**, through the real chat route, the real agent loop
and the real fallback wrapper with only the sockets faked: half of that is not
so. Once a fallback answers, the loop pins it and rebinds `endpoint_url`, `model`
and `headers` to it, so the salvage already went to the fallback — its host, its
model, its credentials. The length did not follow: with a local primary down
and a cloud fallback answering, the cloud fallback's rounds were sent 4096 (the
preset, `B1034`) and its salvage 1,000,000 — the local primary's lift; with a
cloud primary down and a LAN fallback, the salvage was sent 4096 where the LAN
fallback's rounds were sent 1,000,000. A cloud provider handed 1,000,000 refuses
it, so the salvage failed and the turn ended on the apology. The fix asks
`B1034`'s one rule (`candidate_max_tokens`) for the salvage too, about the
candidate the call goes to.

`Law 20`: every number asserted is the one on the wire. The sockets faked are
the chat-completions stream and post (a scripted model: a native tool call on
every round it is sent tools, a fenced call and no prose on the round it is
not) and the context-window query; the hosted fallback refuses a `max_tokens`
above 16,384 with a 400, as a hosted provider does.
"""
import json
from types import SimpleNamespace

import pytest

import routes.chat_routes as chat_routes
import src.agent_loop as agent_loop
import src.foreground_model_routing as foreground_model_routing
import src.llm_core as llm_core
import src.model_context as model_context
import src.settings as settings
from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint  # noqa: E402
from test_pr6020_rebase_regressions import _install_route_probe  # noqa: E402
from test_the_operator_s_token_ceiling_wins_on_every_door import (  # noqa: E402,F401
    BRAINSTORM,
    CLOUD,
    LOCAL,
    OTHER,
    REAL_GET_SETTING,
    TASK,
    ceiling,          # a fixture
)

BACKUP_CLOUD = "https://backup.example/v1"
LAN = "http://192.168.1.20:8000/v1"
BACKUP_MODEL = "backup-model"
BACKUP_HEADERS = {"Authorization": "Bearer backup"}
LIFT = agent_loop.LOCAL_MAX_TOKENS_DEFAULT   # 1,000,000: the agent path's untyped ceiling
CLOUD_MOST = 16_384                          # what the fake hosted provider accepts
PLAN = json.dumps({"plan": "- [ ] read every stage"})
SYNTH = "Stage one allocates; stage two spills."
APOLOGY = "couldn't pull a clean answer together"


@pytest.fixture(autouse=True)
def window(monkeypatch):
    """The context-window query is a socket too: answer it, and keep its cache
    out of every other test's way."""
    monkeypatch.setattr(model_context, "_query_context_length",
                        lambda url, model: (32_768, True))
    monkeypatch.setattr(model_context, "_context_cache", {})


def _host(url):
    return url.split("//")[1].split("/")[0]


@pytest.fixture
def chain(monkeypatch):
    """Every request streamed or posted, as `(kind, host, payload, headers)`. A
    host in `chain.down` answers 503 before any content; a hosted host
    (`*.example`) refuses a `max_tokens` above `CLOUD_MOST` with a 400."""
    sent, down = [], set()

    def _refusal(url, payload):
        if any(d in url for d in down):
            return 503, "down"
        if _host(url).endswith(".example") and (payload.get("max_tokens") or 0) > CLOUD_MOST:
            return 400, (f"max_tokens is too large: {payload['max_tokens']}. This model "
                         f"supports at most {CLOUD_MOST} completion tokens")
        return None

    class _Answer:
        is_success = True
        status_code = 200
        text = ""
        headers = {}

        def json(self):
            return {"choices": [{"message": {"content": SYNTH}}]}

    async def async_post(client, url, headers, json=None, **kwargs):
        sent.append(("post", _host(url), json, dict(headers or {})))
        refused = _refusal(url, json)
        if refused:
            return SimpleNamespace(is_success=False, status_code=refused[0], text=refused[1],
                                   headers={})
        return _Answer()

    class _Stream:
        def __init__(self, url, payload, headers):
            self.url, self.payload, self.headers = url, payload, headers
            self.refused = None

        async def __aenter__(self):
            sent.append(("stream", _host(self.url), self.payload, dict(self.headers or {})))
            self.refused = _refusal(self.url, self.payload)
            return SimpleNamespace(status_code=self.refused[0] if self.refused else 200,
                                   aiter_lines=self._lines, aread=self._aread)

        async def __aexit__(self, *exc):
            return False

        async def _lines(self):
            if self.payload.get("tools"):
                # The same call every round: the loop breaker's case.
                call = {"index": 0, "id": "call_plan", "type": "function",
                        "function": {"name": "update_plan", "arguments": PLAN}}
                yield "data: " + json.dumps({"choices": [{"delta": {"tool_calls": [call]}}]})
                yield "data: " + json.dumps(
                    {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]})
            else:
                # Told to stop calling tools and answer: calls one anyway, in
                # the text, and writes no prose.
                fenced = "```update_plan\n" + PLAN + "\n```"
                yield "data: " + json.dumps({"choices": [{"delta": {"content": fenced}}]})
                yield "data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]})
            yield "data: [DONE]"

        async def _aread(self):
            return (self.refused[1] if self.refused else "").encode()

    monkeypatch.setattr(llm_core, "httpx_post_kimi_aware_async", async_post)
    monkeypatch.setattr(llm_core, "_get_http_client", lambda: SimpleNamespace(
        stream=lambda method, url, json=None, headers=None, **kw: _Stream(url, json, headers)))
    monkeypatch.setattr(llm_core, "_is_host_dead", lambda url: False)
    monkeypatch.setattr(llm_core, "note_model_activity", lambda *a, **k: None)
    llm_core._response_cache.clear()

    async def no_compaction(session, url, model, messages, headers=None, owner=None, **kwargs):
        return list(messages), 4096, False

    monkeypatch.setattr(chat_routes, "maybe_compact", no_compaction)
    monkeypatch.setattr(chat_routes, "trim_for_context", lambda messages, budget: list(messages))
    yield SimpleNamespace(sent=sent, down=down)
    llm_core._response_cache.clear()


def _fallback_to(monkeypatch, url):
    """One backup candidate, with a model and credentials of its own."""
    monkeypatch.setattr(foreground_model_routing, "_load_policy_preferences",
                        lambda owner=None: {
                            "foreground_fallback_enabled": True,
                            "foreground_model_fallbacks": [{"endpoint_id": "backup",
                                                            "model": BACKUP_MODEL}],
                        })
    monkeypatch.setattr(foreground_model_routing, "resolve_fallback_entries",
                        lambda entries, owner=None, require_exact_model=False: [
                            (url, BACKUP_MODEL, dict(BACKUP_HEADERS))])


async def _forced_turn(chain, monkeypatch, primary, backup, *, primary_down):
    """One Agent-mode turn through the real route, loop, fallback wrapper and
    payload builders, which goes round in circles until the loop breaker forces
    an answer. Returns what was sent, the stream's text and the saved replies."""
    if primary_down:
        chain.down.add(_host(primary))
    _install_route_probe(monkeypatch)
    # The probe stands in for the model layer; put the real one back.
    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", llm_core.stream_llm_with_fallback)
    captured: dict = {}
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", captured, model=OTHER,
                                     endpoint_url=primary, capture_completion=True,
                                     context_overrides={"preset": BRAINSTORM, "messages": TASK,
                                                        "route_messages": TASK})
    monkeypatch.setattr(settings, "get_setting", REAL_GET_SETTING)
    # After the helper, which installs a policy of its own.
    _fallback_to(monkeypatch, backup)
    monkeypatch.setattr(chat_routes, "stream_agent_loop", agent_loop.stream_agent_loop)
    response = await endpoint(_RouteRequest("agent"))
    text = ""
    async for chunk in response.body_iterator:
        text += chunk if isinstance(chunk, str) else chunk.decode()
    # `save_assistant_response(sess, session_manager, session_id, full_response, …)`
    saved = [args[3] for args, _kwargs in captured.get("saved", [])]
    return chain.sent, text, saved


def _salvage(sent):
    posts = [(host, payload, headers) for kind, host, payload, headers in sent if kind == "post"]
    assert len(posts) == 1, [(k, h) for k, h, _p, _h in sent]
    return posts[0]


def _rounds_to(sent, host):
    """The `max_tokens` each streamed round sent `host` was handed."""
    return {payload.get("max_tokens") for kind, h, payload, _h in sent
            if kind == "stream" and h == host}


# ── the row: the salvage is the answering fallback's request ────────────────

CHAINS = [
    # typed ceiling, primary (down), fallback (answers), the salvage's max_tokens
    (None, LOCAL, BACKUP_CLOUD, 4096),        # the row: the preset, never the local lift
    (32_768, LOCAL, BACKUP_CLOUD, 4096),      # nor the ceiling a person typed
    (None, CLOUD, LAN, LIFT),                 # the reverse: a local fallback gets the lift
    (32_768, CLOUD, LAN, 32_768),             # the reverse, typed
]


@pytest.mark.asyncio
@pytest.mark.parametrize("typed, primary, backup, want", CHAINS, ids=[
    "local-then-cloud", "local-then-cloud-typed", "cloud-then-local", "cloud-then-local-typed"])
async def test_the_salvage_goes_to_the_fallback_that_answered_with_its_own_length(
        chain, monkeypatch, ceiling, typed, primary, backup, want):
    ceiling(typed)
    sent, _text, _saved = await _forced_turn(chain, monkeypatch, primary, backup,
                                             primary_down=True)
    host, payload, headers = _salvage(sent)
    assert (host, payload["model"], headers.get("Authorization")) == (
        _host(backup), BACKUP_MODEL, BACKUP_HEADERS["Authorization"])
    assert payload.get("max_tokens") == want
    assert not payload.get("tools")
    # One rule: the salvage is sent what the same candidate's rounds were sent.
    assert _rounds_to(sent, _host(backup)) == {want}


@pytest.mark.asyncio
async def test_the_turn_ends_with_the_fallback_s_answer_not_the_apology(chain, monkeypatch,
                                                                      ceiling):
    """The row's `Verify:`. A local primary down, a hosted fallback answering and
    going round in circles: the forced answer's salvage is accepted and the turn
    ends with its synthesis, streamed and saved — not the canned apology."""
    ceiling(None)
    _sent, text, saved = await _forced_turn(chain, monkeypatch, LOCAL, BACKUP_CLOUD,
                                            primary_down=True)
    assert '"type": "loop_breaker_triggered"' in text
    assert SYNTH in text and APOLOGY not in text
    assert len(saved) == 1 and SYNTH in saved[0] and APOLOGY not in saved[0]


# ── what does not move: no fallback answered ────────────────────────────────

PRIMARY_ANSWERS = [
    (None, LOCAL, LIFT),
    (32_768, LOCAL, 32_768),
    (None, CLOUD, 4096),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("typed, primary, want", PRIMARY_ANSWERS, ids=[
    "local", "local-typed", "cloud"])
async def test_with_the_primary_answering_the_salvage_is_what_it_was(chain, monkeypatch,
                                                                     ceiling, typed, primary,
                                                                     want):
    """The primary answered every round: the salvage goes to it with the run's
    own number, exactly as before this row."""
    ceiling(typed)
    sent, text, _saved = await _forced_turn(chain, monkeypatch, primary, BACKUP_CLOUD,
                                            primary_down=False)
    host, payload, headers = _salvage(sent)
    assert (host, payload["model"], headers.get("Authorization")) == (
        _host(primary), OTHER, "Bearer selected")
    assert payload.get("max_tokens") == want
    assert _rounds_to(sent, _host(primary)) == {want}
    assert _host(BACKUP_CLOUD) not in {h for _k, h, _p, _h in sent}
    assert SYNTH in text
