# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2006`. An image asked for at medium quality was drawn at the quality in Settings.

Settings > Image Generation > Quality sets the quality an image gets when
the call names none. The agent's `generate_image` (the built-in `image_gen`
MCP server) read a call's quality as unset whenever it said `medium`,
because `medium` was also what it filled in for a missing one: with the
setting on Low or High, *make it medium quality* was drawn at Low or High,
while an explicit `high`, `low` or `auto` was kept. A blank quality (a fenced
JSON `"quality": ""`) went the other way and ignored the setting. The two
copies of the rule in `src/ai_interaction.py` (`do_generate_image` and
`do_edit_image`) had the same defect, though their callers today pass no
quality.

Now a quality the call names is used as named, and only a missing or blank
one takes the setting, or `medium` when none is set (`B152`: a default
answers absence; it does not overrule a field that said something). The
schema the server serves called `medium` the default, which invited a model
to write it on calls nobody had asked a quality for, and after this fix that
echo would overrule the setting; the schema and the fenced template now say
to leave quality out unless the person asked for one.

Ported from upstream Odysseus cfbe4aec (#6915), without its JSON-content and
incognito cases: Pantheon's `do_generate_image` takes lines and has neither.
"""
import asyncio

import pytest
from PIL import Image

#: (quality the call names, quality in Settings, quality sent to the API)
CASES = [
    ("medium", "high", "medium"),
    ("medium", "low", "medium"),
    ("", "low", "low"),
    ("low", "high", "low"),
    ("high", "low", "high"),
    ("auto", "high", "auto"),
    (None, "high", "high"),
    (None, None, "medium"),
]


class _Refusal:
    """The image API's answer: refused, so nothing is saved."""
    status_code = 418
    text = "Fixture captured request"

    def json(self):
        return {"error": {"message": self.text}}


@pytest.fixture()
def quality_sent(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    import httpx
    from mcp_servers.image_gen_server import call_tool
    from src import ai_interaction, settings

    config = {"image_gen_enabled": True, "image_model": "gpt-image-1"}
    monkeypatch.setattr(settings, "load_settings", lambda *a, **k: config)
    monkeypatch.setattr(settings, "get_setting",
                        lambda key, default=None, *a, **k: config.get(key, default))
    monkeypatch.setattr(ai_interaction, "_resolve_model", lambda *a, **k: (
        "http://fixture.invalid/v1/chat/completions", "gpt-image-1", {}))
    sent = []

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            sent.append(kwargs.get("json") or kwargs.get("data"))
            return _Refusal()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    def run(caller, requested, configured):
        config.pop("image_quality", None)
        if configured is not None:
            config["image_quality"] = configured
        sent.clear()
        if caller == "mcp":
            arguments = {"prompt": "Fixture image", "model": "gpt-image-1"}
            if requested is not None:
                arguments["quality"] = requested
            result = asyncio.run(call_tool("generate_image", arguments))[0].text
        elif caller == "lines":
            content = "Fixture image\ngpt-image-1\n1024x1024"
            if requested is not None:
                content += "\n" + requested
            result = asyncio.run(ai_interaction.do_generate_image(content))
        else:
            source = tmp_path / "fixture.png"
            Image.new("RGB", (2, 2), "white").save(source)
            named = {} if requested is None else {"quality": requested}
            result = asyncio.run(ai_interaction.do_edit_image(
                "Fixture image", str(source), size="1024x1024", **named))
        assert "418" in str(result), result
        assert len(sent) == 1
        return sent[0]["quality"]

    return run


@pytest.mark.parametrize("caller", ["mcp", "lines", "edit"])
@pytest.mark.parametrize("requested,configured,expected", CASES)
def test_a_quality_the_call_names_is_kept_and_only_a_missing_one_takes_the_setting(
        quality_sent, caller, requested, configured, expected):
    assert quality_sent(caller, requested, configured) == expected


def test_the_schema_and_the_fenced_template_say_to_leave_quality_out():
    pytest.importorskip("mcp")
    from mcp_servers.image_gen_server import list_tools
    from src.agent_loop import TOOL_SECTIONS

    # `B621`: mcp 2.x's `Tool` keeps `inputSchema` only as the wire alias.
    served = asyncio.run(list_tools())[0].input_schema["properties"]["quality"]["description"]
    assert "default medium" not in served
    assert "Leave it out unless the person asked for one" in served
    assert "line 4 = quality (optional" in TOOL_SECTIONS["generate_image"]
