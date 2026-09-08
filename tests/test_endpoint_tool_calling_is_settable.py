# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P3-22` — an admin can say whether their endpoint speaks native tool calling.

`ModelEndpoint.supports_tools` decides whether an endpoint is sent tool schemas
at all. It is `nullable, default=None`, the create route has always accepted it
as a form field, the PATCH route has always accepted it in a body — and
**nothing in `static/` ever sent it**. The only writers were the Cookbook (when
a vLLM command happens to contain `--enable-auto-tool-choice`) and the Copilot
importer. So an admin who *knew* their runtime spoke native tools had no way to
say so, and the fallback answered instead: a model-name allowlist that an Ollama
or llama.cpp URL short-circuits before it is even consulted.

`B39` made the fallback honest — a route with no native tools now gets the
fenced prompt and works — but *correct by fallback* is not *configurable*, and
the fallback misjudges any runtime whose model names are not on the list.

Three states, not a checkbox. `None` means "work it out", and a checkbox would
collapse that to `false` for every endpoint anybody ever edits.

The second half of the row's `Verify` — *"and see what it currently believes"* —
is why `resolve_tool_transport` was split out of `_agent_route_tool_mode`: what
the panel shows is only worth showing if it is the answer the agent will act on,
so both call the same function rather than the route describing the rules a
second time.
"""

import json
import re
from pathlib import Path

import pytest

from src.agent_loop import resolve_tool_transport
from routes.model_routes import _tool_transport_view

_REPO = Path(__file__).resolve().parent.parent
_ADMIN_JS = _REPO / "static" / "js" / "admin.js"


class _Row:
    def __init__(self, supports_tools, base_url, ep_id="ep1"):
        self.supports_tools = supports_tools
        self.base_url = base_url
        self.id = ep_id


# ── the decision itself ───────────────────────────────────────────────────────


@pytest.mark.parametrize("declared, url, model, native", [
    # An endpoint that declares yes gets native schemas whatever it is called —
    # that is the whole point of the control.
    (True, "http://localhost:11434/v1", "some-local-model", True),
    (True, "http://192.168.1.9:8000/v1", "unknown-model-name", True),
    # And an endpoint that declares no is believed even on a host the allowlist
    # would have said yes to.
    (False, "https://api.openai.com/v1", "gpt-4o", False),
    # Unset falls through to the ladder: known API host, or a model on the list.
    (None, "https://api.openai.com/v1", "gpt-4o", True),
    (None, "http://192.168.1.9:8000/v1", "qwen3:8b", True),
    (None, "http://192.168.1.9:8000/v1", "some-local-model", False),
    # Ollama is off the native path by policy, not capability — model-level tool
    # streaming there is uneven, so schemas stay opt-in.
    (None, "http://localhost:11434/v1", "qwen3:8b", False),
    (None, "http://localhost:11434/api/chat", "qwen3:8b", False),
    # …and the opt-in is exactly what `True` above buys.
    (None, "http://10.0.0.4:8000/v1", "gpt-oss-20b", False),
])
def test_the_ladder_answers_what_the_row_says_it_answers(declared, url, model, native):
    is_api, _ollama_native, _compat = resolve_tool_transport(declared, url, model)
    assert is_api is native


def test_a_declared_answer_does_not_depend_on_the_model():
    # If it did, "you told it so" in the panel would be a lie for every model
    # the endpoint serves except the one the panel happened to sample.
    for model in ("gpt-4o", "gpt-oss-20b", "deepseek-r1", "", "who-knows"):
        assert resolve_tool_transport(True, "http://x:1/v1", model)[0] is True
        assert resolve_tool_transport(False, "http://x:1/v1", model)[0] is False


def test_the_function_is_pure():
    # No database, no headers — the settings panel calls it per row.
    import inspect

    src = inspect.getsource(resolve_tool_transport)
    for forbidden in ("SessionLocal", "db.query", "requests", "httpx"):
        assert forbidden not in src, f"{forbidden} crept into the pure resolver"


# ── B55: one predicate, not two that disagree ─────────────────────────────────


@pytest.mark.parametrize("url, thinking, transport", [
    # Ollama's own /v1: both say yes.
    ("http://localhost:11434/v1", True, True),
    ("http://127.0.0.1:11434/v1/chat/completions", True, True),
    # A local server that is NOT Ollama. `llm_core` says "could be Ollama" —
    # right for its question, which is whether to expect Ollama's thinking
    # behaviour. `agent_loop` says no — right for its question, which is
    # whether to withhold native tool schemas.
    ("http://localhost:1234/v1", True, False),      # LM Studio
    ("http://localhost:8000/v1", True, False),      # local vLLM
    # Remote is neither.
    ("https://api.openai.com/v1", False, False),
])
def test_two_functions_one_name_and_both_answers_are_right(url, thinking, transport):
    # `B55`. `_is_ollama_openai_compat_url` is defined in `llm_core` **and** in
    # `agent_loop`, and they disagree by design — which nothing said, because
    # they share a name. Merging them was tried and is wrong in both
    # directions: `llm_core`'s accepts a local Ollama on any port, deliberately
    # mirroring `_is_ollama_native_url` so a custom OLLAMA_HOST or a container
    # port remap classifies the same on both Ollama surfaces; widening
    # `agent_loop`'s to match takes native tool calling away from **every local
    # server that is not Ollama**, which `test_tool_support_heuristic.py` and
    # `test_ollama_prompt_matches_transport.py` — B39's measurements across LM
    # Studio, vLLM, llama.cpp and both Ollama forms — catch immediately.
    #
    # So the divergence is pinned here rather than removed, and each definition
    # now says which question it answers.
    from src import agent_loop, llm_core

    assert llm_core._is_ollama_openai_compat_url(url) is thinking
    assert agent_loop._is_ollama_openai_compat_url(url) is transport


@pytest.mark.parametrize("url, native", [
    ("http://localhost:11434/v1", False),   # Ollama: schemas stay opt-in
    ("http://localhost:1234/v1", True),     # LM Studio: keeps native tools
    ("http://localhost:8000/v1", True),     # local vLLM: keeps native tools
])
def test_only_ollama_loses_native_schemas_by_default(url, native):
    assert resolve_tool_transport(None, url, "qwen3:8b")[0] is native


@pytest.mark.parametrize("url, native", [
    ("http://localhost:11434", True),
    ("http://localhost:11434/api/chat", True),
    # The port-remap case `llm_core`'s host rule exists for. Nothing pinned it
    # — a mutation narrowing this to `port == 11434` survived the suite — so it
    # is pinned here, beside the `/v1` twin it is deliberately in lockstep with.
    ("http://localhost:8080/api/chat", True),
    ("http://127.0.0.1:9999/api", True),
    ("http://192.168.1.9:8080/api/chat", False),
    ("http://localhost:11434/v1", False),
])
def test_the_native_ollama_surface_follows_the_same_host_rule(url, native):
    from src import llm_core

    assert llm_core._is_ollama_native_url(url) is native


def test_both_definitions_say_which_question_they_answer():
    # The one thing that was actually wrong: a reader of either could not tell
    # there was another, or why it differs.
    hits = {
        path.name: path.read_text(encoding="utf-8")
        for path in (_REPO / "src").rglob("*.py")
        if re.search(r"^def _is_ollama_openai_compat_url", path.read_text(encoding="utf-8"), re.M)
    }
    assert set(hits) == {"llm_core.py", "agent_loop.py"}, (
        f"the set of definitions changed: {sorted(hits)}. If one was removed, "
        "check the local-server tests above still pass — merging them is the "
        "mistake B55 records."
    )
    for name, src in hits.items():
        body = src[src.index("def _is_ollama_openai_compat_url"):]
        body = body[:body.index("\n\n\n")] if "\n\n\n" in body else body[:2000]
        assert "B55" in body or "_is_ollama_native_url" in body, (
            f"{name}'s definition does not say how it relates to the other one"
        )


# ── what the panel is told ────────────────────────────────────────────────────


def test_the_panel_is_told_what_the_agent_will_do():
    auto = _tool_transport_view(_Row(None, "http://localhost:11434/v1"), ["qwen3:8b"])
    assert auto == {"declared": None, "resolved": "fenced",
                    "sample_model": "qwen3:8b", "model_dependent": True}

    told = _tool_transport_view(_Row(True, "http://localhost:11434/v1"), ["qwen3:8b"])
    assert told["declared"] is True
    assert told["resolved"] == "native"
    assert told["model_dependent"] is False, (
        "a declared endpoint answers the same for every model, and the panel "
        "must not name one as though it had a say"
    )


def test_the_view_agrees_with_the_resolver_it_reports_on():
    # The claim that makes this worth showing at all. If these two ever drift,
    # the panel is confidently describing something that does not happen.
    cases = [
        (None, "https://api.openai.com/v1", "gpt-4o"),
        (None, "http://localhost:11434/v1", "qwen3:8b"),
        (True, "http://10.0.0.9:8000/v1", "mystery"),
        (False, "https://api.openai.com/v1", "gpt-4o"),
        (None, "http://10.0.0.9:8000/v1", "deepseek-r1"),
    ]
    for declared, url, model in cases:
        view = _tool_transport_view(_Row(declared, url), [model])
        expected = "native" if resolve_tool_transport(declared, url, model)[0] else "fenced"
        assert view["resolved"] == expected, (declared, url, model)


def test_an_endpoint_with_no_models_still_gets_an_answer():
    # Offline endpoints have an empty model list, and the panel still has to
    # render a row for them.
    view = _tool_transport_view(_Row(None, "https://api.openai.com/v1"), [])
    assert view["resolved"] in {"native", "fenced"}
    assert view["sample_model"] == ""


def test_a_broken_resolver_does_not_take_the_endpoint_list_down(monkeypatch):
    import routes.model_routes as mr
    import src.agent_loop as al

    def _boom(*_a, **_k):
        raise RuntimeError("ladder exploded")

    monkeypatch.setattr(al, "resolve_tool_transport", _boom)
    view = mr._tool_transport_view(_Row(None, "http://x/v1"), ["m"])
    assert view["resolved"] is None, "a badge must not cost the admin their endpoint list"
    assert view["declared"] is None


# ── the control ───────────────────────────────────────────────────────────────


def test_the_row_offers_all_three_states():
    src = _ADMIN_JS.read_text(encoding="utf-8")
    block = src[src.index("adm-ep-tools-row"):src.index("data-adm-copy-url")]
    for value, label in (('value=""', "Auto"), ('value="true"', "Native"), ('value="false"', "Fenced")):
        assert value in block and label in block, f"the {label} state is missing"


def test_choosing_auto_sends_null_rather_than_nothing():
    # The PATCH route reads `"supports_tools" in body`, so omitting the key
    # means "leave it alone" — an admin who picked Native once could then never
    # get back to Auto, and the control would be a one-way door.
    src = _ADMIN_JS.read_text(encoding="utf-8")
    handler = src[src.index("[data-adm-ep-tools]"):src.index("[data-adm-copy-url]")]
    assert "v === '' ? null : (v === 'true')" in handler
    assert "JSON.stringify({ supports_tools })" in handler


@pytest.mark.parametrize("value, parsed", [
    # Auto — the state the whole row is about keeping reachable.
    (None, None), ("", None), ("maybe", None), (2, None), ("2", None),
    # Yes, in every spelling either route has ever accepted.
    (True, True), ("true", True), ("TRUE", True), ("  Yes  ", True),
    ("on", True), ("1", True), (1, True),
    # No, likewise.
    (False, False), ("false", False), ("no", False), ("off", False),
    ("0", False), (0, False),
])
def test_one_parser_for_the_tri_state(value, parsed):
    # `P3-22` found **two** parsers for this field, and they disagreed. The
    # create route read a form string and took `yes`/`no`; the PATCH route read
    # JSON through a dict lookup that did not — so an endpoint created with
    # `supports_tools=yes` silently reverted to Auto the next time anybody
    # saved that row, and nothing said so.
    from routes.model_routes import _parse_supports_tools

    assert _parse_supports_tools(value) is parsed


def test_an_unrecognised_value_means_auto_and_not_no():
    # The alternative — guessing `False` — takes tools away from an endpoint
    # that had them, for a value nobody meant to send.
    from routes.model_routes import _parse_supports_tools

    assert _parse_supports_tools("banana") is None
    assert _parse_supports_tools({}) is None
    assert _parse_supports_tools([]) is None


def test_both_routes_go_through_that_parser():
    src = (_REPO / "routes" / "model_routes.py").read_text(encoding="utf-8")
    assert src.count("_parse_supports_tools(") == 3, (
        "expected the definition plus the create and PATCH call sites; a fourth "
        "spelling of this parse is how the two got out of step in the first place"
    )


def test_the_select_does_not_open_the_model_panel():
    # The row header expands the model list on click, and the select lives
    # inside it.
    src = _ADMIN_JS.read_text(encoding="utf-8")
    handler = src[src.index("[data-adm-ep-tools]"):src.index("[data-adm-copy-url]")]
    assert "stopPropagation" in handler
