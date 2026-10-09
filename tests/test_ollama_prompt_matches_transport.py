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
    """The invariant, restated for `tool_schema_offer` (`B-NEW`).

    This asserted the source text `if route_state["is_api_model"]:` — that the
    schema branch and the prompt branch read the one flag. They no longer do,
    deliberately: *"does this request carry a `tools` array"* and *"is the
    fenced channel shut"* are different questions, and answering them with one
    flag is what sent **zero** tools to a local OpenAI-compatible server whose
    model name was not on an allowlist (`tool_schema_offer`'s docstring has the
    measurement).

    What still has to hold is the thing the old assertion was protecting: the
    compact prompt claims the schemas are the *only* channel, so it may only be
    sent where the fenced parser really is shut. That is a property of the two
    functions, so it is asserted by calling them rather than by reading the
    file (`Law 20`).
    """
    # `both` — nobody declared anything: schemas are offered AND the fenced
    # prompt stays, because the compact prompt's claim would be false.
    assert A.tool_schema_offer(None, "http://127.0.0.1:8080/v1", "some-local-build") == "both"
    assert A._compact_prompt_applies(
        A.resolve_tool_transport(None, "http://127.0.0.1:8080/v1", "some-local-build")[0]
    ) is False
    # `native` — the endpoint declared it: compact, and the fence is shut.
    assert A.tool_schema_offer(True, "http://127.0.0.1:8080/v1", "some-local-build") == "native"
    assert A._compact_prompt_applies(
        A.resolve_tool_transport(True, "http://127.0.0.1:8080/v1", "some-local-build")[0]
    ) is True
    # `fenced` — declared False, or Ollama: no `tools` key, full prompt.
    for declared, url in ((False, "http://127.0.0.1:8080/v1"),
                          (None, "http://127.0.0.1:11434/v1")):
        assert A.tool_schema_offer(declared, url, "qwen3:8b") == "fenced"
        assert A._compact_prompt_applies(
            A.resolve_tool_transport(declared, url, "qwen3:8b")[0]
        ) is False


def test_the_compact_prompt_still_claims_native_tools():
    """The invariant only matters because of what the prompt says. If that
    sentence is ever softened, this test should be revisited rather than
    silently protecting a claim nobody is making any more."""
    prompt = A._assemble_prompt({"bash"}, compact=True)
    assert "Only the tool schemas provided by the API are available" in prompt
    assert "do not write tool syntax" in prompt
