# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1814`. An image chat edited pictures with `edit_image` switched off.

A chat whose model is an image model answers a prompt with a picture, and
with a picture attached it edits that one (`ai_interaction.do_edit_image`),
drawn as an `edit_image` card. The branch refused only when `generate_image`
was off, so where an admin had switched `edit_image` off in Admin > Tools and
left generation on, every attached picture was still edited on request. `H05`
says a capability switched off is off on every channel, and `B1349` keeps
`edit_image` out of the `image_gen_enabled` switch, so the tool switch is the
one that speaks for it here.

Now the edit is refused in the policy's own sentence before anything runs.
`generate_image` is still asked first, unchanged, and a prompt with no picture
still gets a new one when only `edit_image` is off. Upstream Odysseus made the
same check in e5e23e64.

Driven: the real `/api/chat_stream` route, with the two image calls recorded.
"""

import pytest

import routes.chat_routes as chat_routes
import src.ai_interaction as ai_interaction
import src.settings as settings
from src.tool_policy import DISABLED_FOR_REQUEST
from tests.test_foreground_model_routing import _RouteRequest, _chat_stream_endpoint
from tests.test_stream_announces_its_steerability import _drain


@pytest.fixture
def image_chat(monkeypatch, tmp_path):
    """An image-model chat on an install whose admin switched `edit_image` off."""
    endpoint = _chat_stream_endpoint(monkeypatch, "chat", {})
    monkeypatch.setattr(chat_routes, "_is_image_generation_session", lambda *args, **kwargs: True)
    monkeypatch.setattr(settings, "get_setting",
                        lambda key, default=None: ["edit_image"] if key == "disabled_tools" else default)
    picture = tmp_path / "cat.png"
    picture.write_bytes(b"\x89PNG\r\n\x1a\n")
    attached = {}
    monkeypatch.setattr(chat_routes, "_first_image_attachment",
                        lambda *args, **kwargs: attached.get("upload"))
    ran = []

    async def edit(prompt, path, **kwargs):
        ran.append("edit_image")
        return {"results": "Edited.", "image_url": "/api/generated-image/edited.png"}

    async def generate(content, session_id=None, owner=None):
        ran.append("generate_image")
        return {"results": "Generated.", "image_url": "/api/generated-image/new.png"}

    monkeypatch.setattr(ai_interaction, "do_edit_image", edit)
    monkeypatch.setattr(ai_interaction, "do_generate_image", generate)

    async def send(*, with_picture):
        attached["upload"] = ({"id": "u1", "path": str(picture), "name": "cat.png"}
                              if with_picture else None)
        request = _RouteRequest("chat")
        request._form["compare_mode"] = "false"
        return await _drain(await endpoint(request))

    return send, ran


@pytest.mark.asyncio
async def test_a_picture_attached_is_not_edited_when_edit_image_is_switched_off(image_chat):
    send, ran = image_chat

    events = await send(with_picture=True)

    assert ran == []
    assert {"delta": DISABLED_FOR_REQUEST} in events
    assert not [e for e in events if e.get("type") in ("tool_start", "tool_output")]


@pytest.mark.asyncio
async def test_a_prompt_with_no_picture_still_gets_one_when_only_edit_image_is_off(image_chat):
    send, ran = image_chat

    events = await send(with_picture=False)

    assert ran == ["generate_image"]
    assert any(e.get("type") == "generated_image" for e in events)
