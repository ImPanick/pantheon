# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P22-21` — where a sentence sends a person to add something, in the words
the Workbench's tab strip says.

MCP servers, APIs, mail and calendars are added in one place since `P22-21`:
the Workbench's *MCP & Integrations* room (Settings → Integrations is a door
to it). Before the wave E merge the server named it four ways — "Settings →
Integrations → + → MCP Tool Server" (the scaffold's hint, its README and both
registrations), "Integrations" (an import's missing lines), "Settings → MCP"
(the assistant's refusal, a place that never existed) and "the Workbench's MCP
& Integrations tab" (the palette). Every server-side sentence that sends a
person there now spells it from here, so renaming the tab moves them all
(`Law 7`). The browser's one copy is `static/js/workbench/rooms.js`, which the
tab strip draws from; `tests/test_the_integrations_room_has_one_name.py` holds
the two equal by importing that module, not by reading it.

Plain constants and nothing else: `src/mcp_scaffold.py` (the CLI's) and the
relay import this, and neither may pull in the app.
"""

# The tab's label — `rooms.js`'s `ROOM_NAMES.integrations`.
INTEGRATIONS_ROOM = "MCP & Integrations"
# The Skills room and the Skills window share a name.
SKILLS_ROOM = "Skills"

# A sentence's "in …": where the room is.
INTEGRATIONS_PLACE = f"the Workbench's {INTEGRATIONS_ROOM} tab"
# The clicks to the form an MCP server is registered through — the room's
# *Add Integration* menu, its *MCP Tool Server* entry (`settings.js`).
ADD_MCP_SERVER_PATH = f"Workbench → {INTEGRATIONS_ROOM} → Add Integration → MCP Tool Server"
