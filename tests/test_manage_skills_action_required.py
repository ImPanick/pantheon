# SPDX-License-Identifier: AGPL-3.0-or-later
import json

import pytest

from src.tools.system import do_manage_skills


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"action": ""},
        {"action": "   "},
        {"name": "demo", "description": "x", "procedure": ["step"]},
    ],
)
async def test_manage_skills_requires_action(payload):
    result = await do_manage_skills(json.dumps(payload), owner="test")

    # The list is the message: a person or a model that guessed wrong is told
    # every action there is, so `P8-12`'s lint, `P8-11`'s restore and `P8-13`'s
    # improve are discoverable from the error you get by not knowing about them.
    # Pinning the literal is the point — an action added without being named
    # here is an action nobody who needs it can find (`Law 15`), and this test
    # going red is the reminder.
    assert result == {
        "error": ("action is required (list|view|view_ref|add|edit|patch|publish|"
                  "delete|search|lint|improve|versions|restore|export)"),
        "exit_code": 1,
    }
