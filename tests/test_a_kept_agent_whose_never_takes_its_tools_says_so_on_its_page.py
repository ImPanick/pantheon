# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1663` — a kept own agent whose own *never* takes its tools away says so
on its page, instead of listing them under *Tools:* as if its runs had them.

`B1662` refuses such a file when it is saved (`manifest.check_tools_kept`),
but a file kept before stays its person's: `tools: [web_fetch]` with
`network_egress: never` loads, and `hires.kit` hands its runs no tool at all.
**Measured on `edc68aad`:** `GET /api/agents/sealed-reader` answered
`tools: ["web_fetch"]`, `effects: {}`, `lacking: []`, and the hall's
`_renderAgent` drew *Tools: web_fetch* under an empty *What it may do* — a
page that says the agent can fetch pages, for an agent that can only talk.

Now `hires.lacking_tools` — the one list of the agent's tools a run will not
have — names a tool a never it is held to takes away, with the never
(`never`) and why; the page leaves it off *Tools:* and says so in a note of
its own, apart from what this person's account lacks (which other people's
runs do have). A hire's own never that takes a tool is named on the hire's
page the same way. No shipped agent lists a tool its own never takes
(`B1662`), so their pages are drawn exactly as before.

Driven (`Law 20`): the real `/api/agents/{id}` and hire routes on a real
SQLite file, with the files written into the person's own layer as a save
before `B1662` left them, and each route's own answer handed to the hall's
real `agentsWindow.js` under node.
"""

from __future__ import annotations

import json

from src.agents import hires as H
from src.agents.catalogue import catalogue

from tests.test_a_hire_compiles_to_tasks import call, client, hire  # noqa: F401  (fixture)
from tests.test_a_never_that_takes_a_tool_away_draws_none_of_its_rows import (
    CAREFUL, SEALED, _kept_before, _own,
)
from tests.test_a_workflow_is_kept_as_one_document import admins, sched, wf_db  # noqa: F401  (fixtures)
from test_the_agents_hall_js import _hall, sandbox  # noqa: E402,F401  (fixture)

TAKEN = {"tool": "web_fetch", "never": "network_egress",
         "reason": "every call of it has “network_egress”, which its file says is never"}


def _page(client, agent_id, user="alice"):
    res = call(client, "GET", f"/api/agents/{agent_id}", user=user)
    assert res.status_code == 200, res.text
    return res.json()


def _drawn(sandbox, page):
    """The hall's agent page for `page` — the route's own answer, as is."""
    return _hall(sandbox, f"""
        const page = {json.dumps(page)};
        const served = globalThis.fetch;
        globalThis.fetch = async (url, opts = {{}}) => (String(url) === `/api/agents/${{page.id}}`
          ? {{ ok: true, status: 200, json: async () => page }} : served(url, opts));
        await mod.openAgents({{ agent: page.id }}); await settle(30);
        const taken = q('.agents-taken');
        out({{
          view: mod._test.state().view,
          tools: q('.agents-small').map((n) => n.textContent).filter((t) => t.startsWith('Tools:')),
          effects: q('.agents-effect').length,
          taken: taken.map((n) => n.querySelectorAll('p').map((p) => p.textContent)),
          takenItems: taken.map((n) => n.querySelectorAll('li').map((li) => li.textContent)),
          takenRole: taken.map((n) => n.getAttribute('role')),
          lacking: q('.agents-lacking').filter((n) => !taken.includes(n)).map((n) => n.textContent),
        }});
    """)


# ── the row's `Verify:` — the route names them ──────────────────────────────

def test_the_page_of_one_kept_before_names_the_tool_its_never_takes(client, admins):
    _kept_before(SEALED, "sealed-reader")
    page = _page(client, "sealed-reader")
    assert page["tools"] == ["web_fetch"], "the file's own list, as Customise shows it"
    assert page["effects"] == {}
    assert page["lacking"] == [TAKEN], "its runs get no tool, and the page is told which and why"

    admins.add("alice")
    assert _page(client, "sealed-reader")["lacking"] == [TAKEN], \
        "an admin's runs lack it too: it is the file's never, not the account"


def test_one_that_kept_a_tool_names_only_the_one_it_lost(client):
    _kept_before(CAREFUL, "careful-reader")
    page = _page(client, "careful-reader")
    assert page["tools"] == ["web_search", "web_fetch"]
    assert page["lacking"] == [TAKEN]


def test_a_hires_own_never_that_takes_a_tool_is_named_on_the_hires_page(client):
    """Topic Watcher allows `network_egress`; a hire may make it never, and
    then its runs have no `web_fetch` (`hires.kit` on `held_effects`)."""
    h = hire(client, "topic-watcher", inputs={"topics": ["solar"]}, grants={"network_egress": "never"})
    assert h["lacking"] == [{"tool": "web_fetch", "never": "network_egress",
                             "reason": "every call of it has “network_egress”, which this hire says is never"}]
    again = call(client, "GET", f"/api/agents/hires/{h['id']}").json()
    assert again["lacking"] == h["lacking"]
    plain = hire(client, "topic-watcher", inputs={"topics": ["wind"]})
    assert plain["lacking"] == [], "without the never, nothing is lacking"
    assert _page(client, "topic-watcher")["lacking"] == [], "the agent's own page is the file's"


def test_no_shipped_agents_page_names_a_tool_its_never_takes():
    """Their payloads are as before: only what an account lacks."""
    agents, _broken = catalogue(None)
    assert len(agents) >= 173
    for m in agents:
        for owner in ("bob", None):
            assert not [x for x in H.lacking_tools(m, owner) if "never" in x], (m.id, owner)


# ── the row's `Verify:` — the page says why ─────────────────────────────────

def test_the_hall_leaves_it_off_tools_and_says_it_can_only_talk(client, sandbox):  # noqa: F811
    _kept_before(SEALED, "sealed-reader")
    out = _drawn(sandbox, _page(client, "sealed-reader"))
    assert out["view"] == "agent"
    assert out["tools"] == ["Tools: none"], "not Tools: web_fetch"
    assert out["effects"] == 0
    assert out["taken"] == [["A never in its file takes away every tool it lists, so its runs get none "
                             "and it can only talk:",
                             "Edit your file: make that never ask, or take the tool out."]]
    assert out["takenItems"] == [["web_fetch — every call of it has “network_egress”, which its file "
                                  "says is never"]]
    assert out["takenRole"] == ["note"]
    assert out["lacking"] == [], "not said as something this person's account lacks"


def test_the_hall_lists_the_tool_it_kept_and_names_the_one_it_lost(client, sandbox):  # noqa: F811
    _kept_before(CAREFUL, "careful-reader")
    out = _drawn(sandbox, _page(client, "careful-reader"))
    assert out["tools"] == ["Tools: web_search"]
    assert out["taken"] == [["A never in its file takes this tool away, so its runs never get it:",
                             "Edit your file: make that never ask, or take the tool out."]]
    assert out["takenItems"] == [["web_fetch — every call of it has “network_egress”, which its file "
                                  "says is never"]]


def test_two_nevers_that_take_two_tools_are_each_named(client, sandbox):  # noqa: F811
    _kept_before(_own(["web_fetch", "write_file"], "{network_egress: never, write_workspace: never}",
                      "two-nevers", "Two Nevers"), "two-nevers")
    page = _page(client, "two-nevers")
    assert [(x["tool"], x["never"]) for x in page["lacking"]] == [
        ("web_fetch", "network_egress"), ("write_file", "write_workspace")]
    out = _drawn(sandbox, page)
    assert out["tools"] == ["Tools: none"]
    assert out["taken"] == [["Nevers in its file take away every tool it lists, so its runs get none and "
                             "it can only talk:",
                             "Edit your file: make those nevers ask, or take the tools out."]]
    assert out["takenItems"] == [[
        "web_fetch — every call of it has “network_egress”, which its file says is never",
        "write_file — every call of it has “write_workspace”, which its file says is never"]]


def test_the_hires_page_says_its_runs_lack_the_tool_its_never_takes(client, sandbox):  # noqa: F811
    h = hire(client, "topic-watcher", inputs={"topics": ["solar"]}, grants={"network_egress": "never"})
    served = call(client, "GET", f"/api/agents/hires/{h['id']}").json()
    out = _hall(sandbox, f"""
        const h = {json.dumps(served)};
        const served = globalThis.fetch;
        globalThis.fetch = async (url, opts = {{}}) => (String(url) === `/api/agents/hires/${{h.id}}`
          ? {{ ok: true, status: 200, json: async () => h }} : served(url, opts));
        await mod.openAgents({{ hire: h.id }}); await settle(30);
        out({{ view: mod._test.state().view, refused: texts(body(), 'agents-refused') }});
    """)
    assert out == {"view": "hire", "refused": ["Its runs lack: web_fetch."]}


def test_a_shipped_agents_page_is_drawn_as_before(client, sandbox):  # noqa: F811
    """Site Builder for a member: every tool on *Tools:*, and the account's
    lack in its own words — no note of a never."""
    page = _page(client, "site-builder", user="bob")
    assert page["lacking"] and not [x for x in page["lacking"] if "never" in x]
    out = _drawn(sandbox, page)
    assert out["tools"] == [f"Tools: {', '.join(page['tools'])}"]
    assert out["taken"] == []
    n = len(page["lacking"])
    assert out["lacking"] == [
        f"Your runs of it will not have {'this tool' if n == 1 else 'these tools'}, so it may not finish "
        f"every step:" + "".join(f"{x['tool']} — {x['reason']}" for x in page["lacking"])]
