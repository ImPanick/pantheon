# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P2-21` / `P11-10` — the four `/api/skills/builtin` routes, and the list
loader that makes the flag worth flipping.

Three things had to be true before the built-in section could be surfaced, and
the ship line registers only the first of them as blocking:

* **the gate.** `PUT` and `DELETE` call ``require_admin``; the two `GET`s made
  no auth call at all, so any signed-in non-admin could read all 60 built-in
  tool instruction blocks — the same text the model is given. The register's
  reason line is the spec: *"two `builtin` GETs make no auth call beside a
  `require_admin` PUT and DELETE."*
* **the loader.** ``builtinSkills`` was never assigned from any fetch, so
  flipping the flag alone drew a "Built-in capabilities 0" header over nothing.
* **the flag.** ``const showBuiltin = false``.

The gate is driven by **calling the handlers** rather than reading the file
(`Law 20` option 1): a mutation that deletes ``require_admin`` from a route
survives any grep for the word, because the word is still in the file three
routes down. The routes are discovered from the router rather than listed here,
so a fifth `/builtin` route added later is gated or this fails — the defect was
that nobody noticed there were four instead of three.

The loader and the flag are driven under node in the sandbox pattern
`tests/test_the_workshop_surfaces_js.py` owns; the shim, stubs and runner are
imported from it rather than copied (`Law 14`).
"""
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

from services.memory.skills import SkillsManager
from routes.skills_routes import setup_skills_routes

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_a_draft_skill_is_uncatalogued_not_inactive import js_function  # noqa: E402
from test_the_workshop_surfaces_js import (  # noqa: E402
    _SHIM, _SKILLS_PREAMBLE, _STUBS, _index_ids,
)

ROOT = Path(__file__).resolve().parents[1]
SKILLS_JS = ROOT / "static" / "js" / "skills.js"

pytestmark_node = pytest.mark.skipif(
    not shutil.which("node"), reason="node binary not on PATH"
)


# ── the gate ────────────────────────────────────────────────────────────────

class _AuthManager:
    """The shape ``require_admin`` reads: ``is_configured`` + ``is_admin``."""

    is_configured = True

    def __init__(self, admins=()):
        self._admins = set(admins)

    def is_admin(self, user):
        return user in self._admins


def _request(user, *, admins=(), method="GET", body=None):
    app = SimpleNamespace(state=SimpleNamespace(auth_manager=_AuthManager(admins)))
    payload = json.dumps(body).encode() if body is not None else b""
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(
        scope={
            "type": "http",
            "method": method,
            "headers": [(b"content-type", b"application/json")] if body is not None else [],
            "app": app,
            "state": {"current_user": user},
        },
        receive=receive,
    )


def _builtin_routes(router):
    """Every route under `/api/skills/builtin`, discovered rather than listed.

    `P2-CORRECTED`'s finding was a miscount — the roadmap said three routes and
    there were four. A test that names them repeats the mistake it exists to
    catch.
    """
    out = []
    for route in router.routes:
        if not route.path.startswith("/api/skills/builtin"):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            out.append((method, route.path, route.endpoint))
    return sorted(out)


async def _call(method, path, endpoint, request):
    if "{name}" in path:
        return await endpoint("read_file", request)
    return await endpoint(request)


@pytest.fixture()
def router(tmp_path):
    return setup_skills_routes(SkillsManager(str(tmp_path)))


def test_there_are_four_builtin_routes_not_three(router):
    """The count is the premise every other assertion here rests on."""
    found = [(m, p) for m, p, _ in _builtin_routes(router)]
    assert found == [
        ("DELETE", "/api/skills/builtin/{name}"),
        ("GET", "/api/skills/builtin"),
        ("GET", "/api/skills/builtin/{name}"),
        ("PUT", "/api/skills/builtin/{name}"),
    ], found


@pytest.mark.asyncio
async def test_no_builtin_route_answers_a_signed_in_non_admin(router):
    """The gate, driven per route. `dave` is signed in and is not an admin —
    the account `require_admin` exists to refuse. Before `P2-21` the two GETs
    answered him with all 60 instruction blocks."""
    refused = {}
    for method, path, endpoint in _builtin_routes(router):
        req = _request("dave", admins=("root",), method=method,
                       body={"text": "x"} if method == "PUT" else None)
        try:
            await _call(method, path, endpoint, req)
        except HTTPException as exc:
            refused[(method, path)] = exc.status_code
        else:
            refused[(method, path)] = None
    assert all(code == 403 for code in refused.values()), refused


@pytest.mark.asyncio
async def test_an_admin_still_reads_the_list_and_one_block(router):
    """Gating a read that the panel needs is only a fix if the panel still
    works. `root` is an admin; both GETs answer."""
    routes = {(m, p): e for m, p, e in _builtin_routes(router)}
    listing = await routes[("GET", "/api/skills/builtin")](
        _request("root", admins=("root",))
    )
    assert listing["count"] == len(listing["builtin"]) > 0
    names = [row["name"] for row in listing["builtin"]]
    assert "read_file" in names, names[:8]

    block = await routes[("GET", "/api/skills/builtin/{name}")](
        "read_file", _request("root", admins=("root",))
    )
    assert block["name"] == "read_file"
    assert block["text"] and block["text"] == block["default"]
    assert block["is_overridden"] is False


@pytest.mark.asyncio
async def test_the_listing_covers_every_tool_section(router):
    """The section is the agent's whole native surface or it is a sample. 60
    keys, 60 names, AST-counted — the list route must return all of them."""
    from src.agent_loop import TOOL_SECTIONS

    expected = set()
    for key in TOOL_SECTIONS:
        expected.update(key if isinstance(key, tuple) else (key,))
    routes = {(m, p): e for m, p, e in _builtin_routes(router)}
    listing = await routes[("GET", "/api/skills/builtin")](
        _request("root", admins=("root",))
    )
    assert {row["name"] for row in listing["builtin"]} == expected
    assert len(expected) == 60


# ── the loader and the flag ─────────────────────────────────────────────────

_BUILTIN_ROWS = [
    {"name": "read_file", "description": "Read a file from the data dir.",
     "is_overridden": False},
    {"name": "web_search", "description": "Search the web.", "is_overridden": True},
]


def _store(builtin_status=200, builtin=None, skills=None):
    """A fetch handler for the Workshop sandbox, with the built-in route's
    status as the variable under test."""
    return """
    mockFetch((url) => {
      if (url.includes('/api/skills/audit-status')) return res(200, { status: 'idle' });
      if (url.includes('/api/skills/index')) return res(200, { index: [], count: 0 });
      if (url.includes('/api/prefs')) return res(200, {});
      if (url.includes('/api/skills/builtin')) return res(%d, %s);
      if (url.includes('/api/skills')) return res(200, { skills: %s, count: 0 });
      return res(200, {});
    });
    """ % (
        builtin_status,
        json.dumps({"builtin": builtin if builtin is not None else _BUILTIN_ROWS,
                    "count": len(builtin if builtin is not None else _BUILTIN_ROWS)}),
        json.dumps(skills if skills is not None else []),
    )


_REPORT = """
    const list = byId('skills-list');
    const headers = list.querySelectorAll('.skills-section-header')
      .map(h => ({ section: h.dataset.section, text: readable(h) }));
    console.log(JSON.stringify({
      fetched: calls.fetch.map(c => c.url),
      headers,
      builtinCards: list.querySelectorAll('.skill-builtin-card')
        .map(c => c.dataset.builtinName),
      errors: uiCalls.errors,
      text: readable(list),
    }));
"""


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    shim = _SHIM.replace("__IDS__", json.dumps(_index_ids()))
    return _make_sandbox(tmp_path_factory.mktemp("builtincards"), SKILLS_JS, shim, _STUBS)


@pytestmark_node
def test_opening_the_workshop_fetches_the_builtin_list(sandbox):
    """`builtinSkills` was `[]` at module scope and nothing ever assigned it.
    Nothing in the tree fetched `GET /api/skills/builtin` at all."""
    out = _run(sandbox, _SKILLS_PREAMBLE, _store() + """
        ready();
        await tick();
    """ + _REPORT)
    assert any(u.endswith("/api/skills/builtin") for u in out["fetched"]), out["fetched"]


@pytestmark_node
def test_the_builtin_section_draws_a_card_per_capability(sandbox):
    """The flag, driven rather than grepped: a card per row, under a header
    that counts them."""
    out = _run(sandbox, _SKILLS_PREAMBLE, _store() + """
        ready();
        await tick();
    """ + _REPORT)
    assert out["builtinCards"] == ["read_file", "web_search"], out["builtinCards"]
    builtin_header = [h for h in out["headers"] if h["section"] == "builtin"]
    assert builtin_header, out["headers"]
    assert "Built-in capabilities" in builtin_header[0]["text"]
    assert "2" in builtin_header[0]["text"]


@pytestmark_node
def test_a_non_admin_gets_no_empty_built_in_header_and_no_error(sandbox):
    """The gate answers 403 for everyone who is not an admin, and that is most
    people. A section header over nothing is `Law 15` — and an error toast for
    a panel the person did not ask for is worse."""
    out = _run(sandbox, _SKILLS_PREAMBLE, _store(builtin_status=403, builtin={}) + """
        ready();
        await tick();
    """ + _REPORT)
    assert out["builtinCards"] == []
    assert [h for h in out["headers"] if h["section"] == "builtin"] == []
    assert out["errors"] == [], out["errors"]
    assert "Built-in capabilities" not in out["text"]


@pytestmark_node
def test_the_edited_badge_rides_the_override_flag(sandbox):
    """`is_overridden` is the one field in the row that tells an operator the
    prompt they are running is not the shipped one."""
    out = _run(sandbox, _SKILLS_PREAMBLE, _store() + """
        ready();
        await tick();
        const cards = byId('skills-list').querySelectorAll('.skill-builtin-card');
        console.log(JSON.stringify({
          edited: cards.filter(c => readable(c).includes('edited'))
            .map(c => c.dataset.builtinName),
        }));
    """)
    assert out["edited"] == ["web_search"], out


@pytestmark_node
def test_expanding_a_card_reads_the_block_from_the_gated_detail_route(sandbox):
    """The card's body is the instruction block, fetched on expand. It is the
    thing the gate protects, so the path that reads it is pinned."""
    out = _run(sandbox, _SKILLS_PREAMBLE, _store() + """
        ready();
        await tick();
        mockFetch((url) => {
          if (url.includes('/api/skills/builtin/read_file'))
            return res(200, { name: 'read_file', text: 'BLOCK TEXT',
                              default: 'BLOCK TEXT', is_overridden: false });
          if (url.includes('/api/skills/audit-status')) return res(200, { status: 'idle' });
          return res(200, {});
        });
        const card = byId('skills-list')
          .querySelector('.skill-builtin-card[data-builtin-name="read_file"]');
        card.dispatchEvent({ type: 'click', target: card,
                             stopPropagation(){}, preventDefault(){} });
        await tick();
        console.log(JSON.stringify({
          body: card.querySelector('.skill-md-pre').textContent,
          warned: readable(card).includes('built-in capability'),
        }));
    """)
    assert out["body"] == "BLOCK TEXT"
    assert out["warned"] is True


@pytestmark_node
def test_the_search_box_reaches_the_built_in_section_too(sandbox):
    """A person looking for `web_search` is looking for that capability, not
    for the half of the Workshop it happens to live in."""
    out = _run(sandbox, _SKILLS_PREAMBLE, _store() + """
        ready();
        await tick();
        setValue('skills-search', 'web_');
        fire(byId('skills-search'), 'input');
        await tick();
    """ + _REPORT)
    assert out["builtinCards"] == ["web_search"], out["builtinCards"]


@pytestmark_node
def test_the_drafts_filter_takes_the_whole_built_in_section_away(sandbox):
    """Built-ins carry no `status` and no `confidence`, so "drafts only"
    cannot mean anything for them. Leaving the section up under that filter
    says the built-ins are drafts; leaving an empty header up says they went
    away. The section goes, header included."""
    out = _run(sandbox, _SKILLS_PREAMBLE, _store() + """
        ready();
        await tick();
        const sort = byId('skills-sort');
        sort.value = 'filter:drafts';
        sort.dispatchEvent({ type: 'change', target: sort,
                             stopPropagation(){}, preventDefault(){} });
        await tick();
    """ + _REPORT)
    assert out["builtinCards"] == []
    assert [h for h in out["headers"] if h["section"] == "builtin"] == []


def test_the_skill_section_header_does_not_call_the_bundled_library_yours():
    """`B590`, met head-on rather than inherited.

    This header is conditional on the built-in section existing, so it had
    never been drawn once — flipping the flag draws it for the first time. The
    list under it is `GET /api/skills`, which folds in the 286 read-only
    bundled entries (`source: "bundled"`, `owner: null`, measured on a fresh
    data dir) that `B590` says cannot be opened, viewed, slash-invoked or
    exported. A header reading "Your skills 287" over 286 files the person did
    not write and cannot open is a claim the product cannot support, and it
    would have arrived as a side effect of this row rather than as anybody's
    decision.

    Asserted with `js_function` rather than under node, and the reason is a
    limitation worth writing down: a **user** skill card is built with
    `innerHTML` and then reaches back into it with
    `header.querySelector('.skill-kebab-btn')`, and the shim stores `innerHTML`
    as a string without parsing it — so `renderSkillsList` throws inside its
    caller's `try` the moment `skills` is non-empty, and no test in this repo
    can drive a rendered user card. The built-in cards are `createElement` all
    the way down, which is why everything above this line *is* driven. So:
    `Law 20` option 2 — resolve the scope, then assert inside it.
    """
    body = js_function(SKILLS_JS.read_text(encoding="utf-8"),
                       "function renderSkillsList(")
    assert 2000 < len(body) < 20000, (
        f"js_function handed back {len(body)} characters — that is not this "
        f"function's body, and every assertion below it would be about the "
        f"wrong scope"
    )
    assert "_mkSectionHeader('user'" in body, "the section header call moved"
    assert "'Your skills'" not in body, (
        "the SKILL.md section must not be labelled as the person's own while "
        "`GET /api/skills` folds in the read-only bundled library (`B590`)"
    )
    assert "_mkSectionHeader('user', 'Skills'" in body
