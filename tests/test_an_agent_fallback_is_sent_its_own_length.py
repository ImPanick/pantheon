# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1034` — Agent mode sends each fallback candidate its own `max_tokens`.

The agent path lifts a preset's `max_tokens` on local inference (`P3-21`,
`D-2026-09-08-02`): the preset is a floor under this machine's ceiling — the one
a person typed, or 1,000,000. It resolved that lift once per run from the
primary's URL and handed the one number to every candidate in the fallback
chain. Measured before this row, through the real chat route, the real agent
loop and the real fallback wrapper with only the sockets faked: a local primary
that answers 503 with a cloud fallback sent the cloud candidate 1,000,000 with no
ceiling typed (32,768 with 32,768 typed) — what the local primary was sent — and
a cloud primary with a local fallback left the local candidate at the preset's
4096. A cloud provider handed 1,000,000 typically refuses it, so the fallback
failed exactly when it was needed.

The call (`D-2026-10-01-04`'s ruling, applied by the integrator's brief): a cloud
fallback gets the preset's own length, never the local lift; a local fallback
behind a cloud primary gets the local lift. One rule, asked per candidate URL —
the one `_resolve_local_lifts` applies to the run, as `B934`'s
`_chat_candidate_request_factory` does for the chat doors (`Law 7`).

`Law 20`: every number asserted is the one on the wire. The sockets faked are
the chat-completions post (`B935`'s `wire`) and the context-window query each
candidate's compaction asks (`model_context._query_context_length`), which on a
LAN address would otherwise wait out a real connect timeout.
"""
import pytest

import routes.chat_routes as chat_routes
import src.agent_loop as agent_loop
import src.llm_core as llm_core
import src.model_context as model_context
import src.runtime_limits as runtime_limits
import src.settings as settings
from test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint  # noqa: E402
from test_pr6020_rebase_regressions import _install_route_probe  # noqa: E402
from test_the_operator_s_token_ceiling_wins_on_every_door import (  # noqa: E402,F401
    BRAINSTORM,
    CLOUD,
    LOCAL,
    MINIMAX,
    NO_PRESET,
    OTHER,
    REAL_GET_SETTING,
    TASK,
    _drain,
    _fallback_to,
    ceiling,          # a fixture
)
from test_the_qwen3_cap_guards_every_door import wire  # noqa: E402,F401  (a fixture)

BACKUP_CLOUD = "https://backup.example/v1"
LAN = "http://192.168.1.20:8000/v1"
LIFT = agent_loop.LOCAL_MAX_TOKENS_DEFAULT   # 1,000,000: the agent path's untyped ceiling


@pytest.fixture(autouse=True)
def window(monkeypatch):
    """The context-window query is a socket too: answer it, and keep its cache
    out of every other test's way."""
    monkeypatch.setattr(model_context, "_query_context_length",
                        lambda url, model: (32_768, True))
    monkeypatch.setattr(model_context, "_context_cache", {})


async def _agent_turn(monkeypatch, url, model, preset, backup=None):
    """One Agent-mode turn through the real route and the real loop, the real
    fallback wrapper and the real payload builders below it."""
    _install_route_probe(monkeypatch)
    # The probe stands in for the model layer; put the real one back.
    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", llm_core.stream_llm_with_fallback)
    endpoint = _chat_stream_endpoint(monkeypatch, "agent", {}, model=model, endpoint_url=url,
                                     context_overrides={"preset": preset, "messages": TASK,
                                                        "route_messages": TASK})
    monkeypatch.setattr(settings, "get_setting", REAL_GET_SETTING)
    if backup:
        # After the helper, which installs a policy of its own.
        _fallback_to(monkeypatch, backup, model)
    monkeypatch.setattr(chat_routes, "stream_agent_loop", agent_loop.stream_agent_loop)
    await _drain(await endpoint(_RouteRequest("agent")))


def _host(url):
    return url.split("//")[1].split("/")[0]


async def _sent_down_the_chain(wire, monkeypatch, primary, backup, preset, model=OTHER):
    """`(host, max_tokens)` for each request the turn made, in order: the
    primary answers 503, so the wrapper moves on to the backup."""
    wire.down.add(_host(primary))
    await _agent_turn(monkeypatch, primary, model, preset, backup=backup)
    sent = [(_host(url), payload.get("max_tokens", "unset")) for url, payload in wire.sent]
    assert [h for h, _m in sent] == [_host(primary), _host(backup)], sent
    return [m for _h, m in sent]


# ── the row: each candidate is sent its own length ──────────────────────────

CHAINS = [
    # typed ceiling, primary, backup, preset, sent to (primary, backup)
    (None, LOCAL, BACKUP_CLOUD, BRAINSTORM, [LIFT, 4096]),         # the row, untyped
    (32_768, LOCAL, BACKUP_CLOUD, BRAINSTORM, [32_768, 4096]),     # the row, typed
    (None, CLOUD, LAN, BRAINSTORM, [4096, LIFT]),                  # the reverse, untyped
    (32_768, CLOUD, LAN, BRAINSTORM, [4096, 32_768]),              # the reverse, typed
]


@pytest.mark.asyncio
@pytest.mark.parametrize("typed, primary, backup, preset, want", CHAINS, ids=[
    "local-then-cloud", "local-then-cloud-typed", "cloud-then-local", "cloud-then-local-typed"])
async def test_each_candidate_is_sent_its_own_length(wire, monkeypatch, ceiling, typed,
                                                     primary, backup, preset, want):
    ceiling(typed)
    assert await _sent_down_the_chain(wire, monkeypatch, primary, backup, preset) == want


# ── what does not move ──────────────────────────────────────────────────────

GUARDS = [
    (None, LOCAL, LAN, BRAINSTORM, [LIFT, LIFT]),                  # two local: both lifted
    (32_768, CLOUD, BACKUP_CLOUD, BRAINSTORM, [4096, 4096]),       # two cloud: neither
    (32_768, LOCAL, BACKUP_CLOUD, NO_PRESET, ["unset", "unset"]),  # nothing named, nothing lifted
    (0, LOCAL, BACKUP_CLOUD, BRAINSTORM, [4096, 4096]),            # a typed 0 is "no lift"
    (1_024, CLOUD, LAN, BRAINSTORM, [4096, 4096]),                 # the preset is a floor
]


@pytest.mark.asyncio
@pytest.mark.parametrize("typed, primary, backup, preset, want", GUARDS, ids=[
    "local-then-local", "cloud-then-cloud", "no-preset", "typed-zero", "preset-above-ceiling"])
async def test_what_the_chain_sent_before_it_still_sends(wire, monkeypatch, ceiling, typed,
                                                         primary, backup, preset, want):
    ceiling(typed)
    assert await _sent_down_the_chain(wire, monkeypatch, primary, backup, preset) == want


@pytest.mark.asyncio
async def test_with_the_local_lift_switched_off_no_candidate_is_lifted(wire, monkeypatch,
                                                                       ceiling):
    """`PANTHEON_UNLIMITED_LOCAL=0` keeps caps on local inference, for every
    candidate in the chain."""
    ceiling(32_768)
    monkeypatch.setattr(runtime_limits, "_LIFT_WHEN_LOCAL", False)
    assert await _sent_down_the_chain(wire, monkeypatch, CLOUD, LAN, BRAINSTORM) == [4096, 4096]


@pytest.mark.asyncio
async def test_the_force_switch_still_lifts_every_candidate(wire, monkeypatch, ceiling):
    """`PANTHEON_FORCE_UNLIMITED=1` is the operator lifting caps for every
    endpoint (`runtime_limits`); a cloud fallback is one, as a cloud primary is."""
    ceiling(None)
    monkeypatch.setattr(runtime_limits, "_FORCE_UNLIMITED", True)
    assert await _sent_down_the_chain(wire, monkeypatch, LOCAL, BACKUP_CLOUD,
                                      BRAINSTORM) == [LIFT, LIFT]


@pytest.mark.asyncio
async def test_a_local_minimax_fallback_with_no_preset_gets_the_typed_ceiling(wire, monkeypatch,
                                                                              ceiling):
    """`B934`'s profile fills an unset length on a local MiniMax; nothing here
    names one, so that stays the profile's to fill — the typed ceiling."""
    ceiling(32_768)
    sent = await _sent_down_the_chain(wire, monkeypatch, CLOUD, LAN, NO_PRESET, model=MINIMAX)
    assert sent == ["unset", 32_768]


# ── one rule ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [LOCAL, LAN, "http://localhost:11434", CLOUD, BACKUP_CLOUD])
def test_a_candidate_is_asked_the_question_the_run_is_asked(ceiling, url):
    """A candidate's length is `_resolve_local_lifts`' own answer for that URL —
    the run's rule asked of one candidate, never a second reading of it."""
    for typed in (None, 0, 1_024, 32_768):
        ceiling(typed)
        for preset in (0, 4096, 8000):
            run = agent_loop._resolve_local_lifts(
                20, preset, unlimited=agent_loop.run_is_unlimited(url))
            assert agent_loop.candidate_max_tokens(preset, url) == run[1], (typed, preset)
