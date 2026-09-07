# SPDX-License-Identifier: AGPL-3.0-or-later
"""B39 — on a default Ollama endpoint, both tool channels were closed at once.

Not the two tools `H09` names. Every tool.

`_agent_route_tool_mode` forces `is_api_model = False` for any Ollama URL unless
the endpoint row declares `supports_tools` — which is `nullable, default=None`,
and the add-endpoint form has no field for it, so an admin who adds Ollama
through Settings gets None. Three things follow from that one value:

  * `_tool_schemas_for_route` returns `[]` for a non-API route, so **nothing is
    sent**;
  * `skip_fenced = is_api_model and ...` is False, so the **fenced parser is the
    only live channel**;
  * `compact` was `is_api or is_native_ollama or is_ollama_compat` — **True** —
    so the prompt said *"Only the tool schemas provided by the API are available
    for this turn… do not write tool syntax or tool instructions in chat"* and
    listed bare names with no fenced syntax, because only the full prompt
    carries that.

The rest of the product already gets this right, which is what makes it an
oversight rather than a trade: a `gpt-oss` model on llama.cpp is also
`is_api_model = False`, is not Ollama, and therefore gets the full prompt with
the fenced syntax its parser is running. Ollama was the only family routed away
from the handling that already worked.

So these tests assert the INVARIANT — the prompt that says "use native tool
calls" goes only to routes that are sent native tool schemas — over a table of
real endpoint shapes, rather than asserting anything about Ollama specifically.
A rule written about the family that broke is a rule that catches that family.
"""
import ast
import pathlib

import pytest

import src.agent_loop as A

SOURCE = pathlib.Path(A.__file__)

# label, url, model, expected is_api_model
ROUTES = [
    ("LM Studio",        "http://localhost:1234/v1",             "qwen3-8b",     True),
    ("LM Studio docker", "http://host.docker.internal:1234/v1",  "llama-3.1-8b", True),
    ("vLLM local",       "http://localhost:8000/v1",             "qwen3-32b",    True),
    ("vLLM on the LAN",  "http://192.168.1.50:8000/v1",          "qwen3-32b",    True),
    ("OpenAI",           "https://api.openai.com/v1",            "gpt-5",        True),
    ("llama.cpp gpt-oss","http://localhost:8080/v1",             "gpt-oss-20b",  False),
    ("Ollama native",    "http://localhost:11434",               "qwen3:8b",     False),
    ("Ollama compat",    "http://localhost:11434/v1",            "qwen3:8b",     False),
]


@pytest.mark.parametrize("label,url,model,expected_api", ROUTES,
                         ids=[r[0] for r in ROUTES])
def test_the_prompt_matches_the_transport_on_every_route(label, url, model, expected_api):
    """The invariant. Compact prompt if and only if native schemas are sent."""
    is_api, _native, _compat = A._agent_route_tool_mode(url, model)
    assert is_api is expected_api, f"route classification moved for {label}"
    assert A._compact_prompt_applies(is_api) is is_api, (
        f"{label}: compact prompt and schema transport disagree"
    )


def test_ollama_is_not_special_cased_back_into_the_compact_prompt():
    """The literal regression. Both URL forms are recognised as Ollama — so the
    detection is working — and neither may take the compact branch while
    `is_api_model` is False."""
    for url in ("http://localhost:11434", "http://localhost:11434/v1"):
        is_api, native, compat = A._agent_route_tool_mode(url, "qwen3:8b")
        assert native or compat, f"{url} should still be detected as Ollama"
        assert is_api is False
        assert A._compact_prompt_applies(is_api) is False


def test_a_declared_tool_capable_route_keeps_the_compact_prompt():
    """The fix must not cost anything. An endpoint that declares
    `supports_tools=True` resolves to `is_api_model=True` — Ollama or not — and
    is still sent schemas, so it still gets the compact prompt."""
    assert A._compact_prompt_applies(True) is True


def test_the_call_site_uses_the_named_predicate():
    """One line unreachable from a unit test: the keyword at the call site.

    Source text, with the limits `B38` established — it cannot tell whether the
    name resolves, which is what `test_agent_loop_names_resolve.py` is for. What
    it can do is stop the two Ollama terms being pasted back in, which is the
    exact edit that caused this."""
    src = SOURCE.read_text(encoding="utf-8")
    assert "compact=_compact_prompt_applies(is_api)," in src
    assert "compact=is_api or is_native_ollama or is_ollama_compat," not in src


def test_the_schema_gate_and_the_prompt_gate_read_the_same_flag():
    """Belt and braces on the invariant, at the level of the source: the schema
    branch keys off `is_api_model` and so must the prompt. If someone changes
    one gate to consult something else, the two can silently drift apart again
    without either being obviously wrong on its own."""
    src = SOURCE.read_text(encoding="utf-8")
    assert 'if route_state["is_api_model"]:' in src, (
        "the schema gate moved — re-derive the invariant before editing this test"
    )


def test_the_compact_prompt_still_claims_native_tools():
    """The invariant only matters because of what the prompt says. If that
    sentence is ever softened, this test should be revisited rather than
    silently protecting a claim nobody is making any more."""
    prompt = A._assemble_prompt({"bash"}, compact=True)
    assert "Only the tool schemas provided by the API are available" in prompt
    assert "do not write tool syntax" in prompt
