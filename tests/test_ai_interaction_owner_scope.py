# SPDX-License-Identifier: AGPL-3.0-or-later
import inspect

import pytest

from src import ai_interaction
from src.agent_tools import model_interaction_tools


def _source(fn) -> str:
    return inspect.getsource(fn)


def test_model_resolver_applies_owner_filter():
    body = _source(ai_interaction._resolve_model)

    assert "owner: Optional[str] = None" in body
    assert "from src.auth_helpers import owner_filter" in body
    assert "owner_filter(query, ModelEndpoint, owner)" in body


def test_model_listing_and_image_fallback_are_owner_scoped():
    # list_models moved to agent_tools.model_interaction_tools (#3629).
    list_body = _source(model_interaction_tools.list_models)
    image_body = _source(ai_interaction.do_generate_image)

    assert "owner: Optional[str] = None" in list_body
    assert "owner_filter(query, ModelEndpoint, owner)" in list_body
    # _resolve_model is offloaded to a worker thread (#4589) but stays owner-scoped.
    assert "asyncio.to_thread(_resolve_model, candidate, owner=owner)" in image_body
    assert "owner_filter(_img_q, ModelEndpoint, owner)" in image_body
    assert "asyncio.to_thread(_resolve_model, model_spec, owner=owner)" in image_body


# chat_with_model, list_models and ask_teacher moved to the registry (#3629)
# and no longer route through dispatch_ai_tool; their owner threading is covered
# by tests/test_model_interaction_registry.py. The remaining model-ish tools
# still dispatched here:
@pytest.mark.parametrize("tool,content", [
    ("pipeline", "gpt-test | summarize this"),
    ("ui_control", "switch_model gpt-test"),
])
async def test_dispatch_passes_owner_to_model_tools(monkeypatch, tool, content):
    seen = {}

    async def capture(name, content, session_id=None, owner=None):
        seen[name] = {"content": content, "session_id": session_id, "owner": owner}
        return {"ok": True}

    monkeypatch.setattr(
        ai_interaction,
        "do_pipeline",
        lambda content, session_id=None, owner=None: capture("pipeline", content, session_id, owner),
    )
    monkeypatch.setattr(
        ai_interaction,
        "do_ui_control",
        lambda content, session_id=None, owner=None: capture("ui_control", content, session_id, owner),
    )

    _desc, result = await ai_interaction.dispatch_ai_tool(tool, content, session_id="sid1", owner="alice")

    assert result == {"ok": True}
    assert seen[tool]["owner"] == "alice"
    assert seen[tool]["session_id"] == "sid1"


async def test_set_theme_finds_the_askers_own_custom_theme_and_nobody_elses(monkeypatch):
    """`B2028`. `ui_control set_theme` looked for custom themes at the root of
    the prefs file, but the theme editor syncs each person's into their own
    record (`_users[<person>]`), so asking the agent for your own theme was
    refused as "Unknown theme". Now it reads the asker's record only: another
    person, or a call with no owner, is not offered it (upstream Odysseus
    218d7624's `_load_for_user(owner)` hands an owner-less call the first
    person's record)."""
    from routes import prefs_routes

    monkeypatch.setattr(prefs_routes, "_load", lambda: {
        "_users": {"alice": {"custom-themes": {"sunset": {"bg": "#000000"}}}, "bob": {}},
    })

    mine = await ai_interaction.do_ui_control("set_theme sunset", owner="alice")
    assert (mine.get("ui_event"), mine.get("theme_name")) == ("set_theme", "sunset"), mine

    for other in ("bob", None):
        theirs = await ai_interaction.do_ui_control("set_theme sunset", owner=other)
        assert theirs.get("error", "").startswith("Unknown theme 'sunset'"), theirs
        assert "sunset" not in theirs["error"].split("Available:", 1)[1]
