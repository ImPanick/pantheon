// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/workbench/rooms.js
//
// `P22-21` / `integrate-e`. The Workbench's rooms, as its tab strip names them —
// in one place (`Law 7`). Before the wave E merge the MCP & Integrations room
// was named three ways in the browser: the tab ("MCP & Integrations"), the
// HTTP step's hints ("Settings → Integrations") and the calendar's CalDAV link
// ("Settings → Integrations"). The tab strip (`workbench.js`'s `ROOMS`), the
// step forms' hints and doors (`stepFields.js`), the calendar's link and
// Settings' door card read these; the server's sentences spell the same name
// from `src/workbench_rooms.py`, and
// `tests/test_the_integrations_room_has_one_name.py` imports this module to
// hold the two equal.
//
// A leaf: it imports nothing, so anything may import it without a cycle
// (`workbench.js` → `workflowRoom.js` → `stepFields.js` already).

export const ROOM_NAMES = Object.freeze({
  automations: 'Automations',
  skills: 'Skills',
  integrations: 'MCP & Integrations',
});
