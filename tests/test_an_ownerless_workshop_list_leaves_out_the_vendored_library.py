# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1498` — the Workshop list with no owner leaves the vendored library out,
as the signed-in list does.

The row: *"The sign-in-off Workshop draws all 286 vendored skill cards"* — the
cost that took the Brain's first answer to 4.4–5.3 s when the signed-in list
carried them (`B1421`). `SkillsManager.load_visible(owner, include_vendored=
False)` honoured the flag for a person and returned `load(None)` — the whole
store, library layers included — when there was no person, so
`GET /api/skills` with no current user listed every vendored skill.

`Law 3`, measured 2026-10-26: since `D-2026-10-07-02` §2 (*"there is always
authentication"*) the live app never reaches this route without a user — the
middleware stamps a username, `internal-tool` or `api` — so the case is the
owner-less caller (a direct handler call, a test client, a future route), not a
browser. The flag now means the same thing for both, and the shipped vendored
library is the one this checkout carries (`library/ecc/skills`, 286 skills).

`Verify:` the Brain loading test passes with sign-in off and the vendored
library installed — sign-in cannot be off, so the half of it this row owns is
driven here: the list a Workshop draws with no owner carries no vendored card.
"""
from __future__ import annotations

import textwrap

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.skills_routes import setup_skills_routes
from services.memory.skills import VENDORED_LIBRARY, SkillsManager, _default_library_root


def _own(tmp_path, name):
    d = tmp_path / "skills" / "mine" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(textwrap.dedent(f"""\
        ---
        name: {name}
        description: one of mine
        category: mine
        status: published
        ---

        ## Procedure
        1. do it
        """), encoding="utf-8")


def test_the_shipped_vendored_library_is_present_to_be_left_out(tmp_path):
    sm = SkillsManager(str(tmp_path))
    vendored = [s for s in sm.load_all() if s.get("library") == VENDORED_LIBRARY]
    assert len(vendored) >= 200, (_default_library_root(), len(vendored))


def test_an_ownerless_list_without_the_vendored_library_has_none_of_it(tmp_path):
    _own(tmp_path, "my-own-procedure")
    sm = SkillsManager(str(tmp_path))
    listed = sm.load_visible(None, include_vendored=False)
    assert not [s["name"] for s in listed if s.get("library") == VENDORED_LIBRARY]
    assert "my-own-procedure" in {s["name"] for s in listed}
    # The first-party shipped skills stay, as they do for a person.
    assert any(s.get("bundled") for s in listed), "Pantheon's own shipped skills went too"
    # And the default still means everything — fork and read by name use it.
    assert any(s.get("library") == VENDORED_LIBRARY for s in sm.load_visible(None))


def test_the_workshop_route_with_no_user_draws_no_vendored_card(tmp_path):
    _own(tmp_path, "my-own-procedure")
    app = FastAPI()
    app.include_router(setup_skills_routes(SkillsManager(str(tmp_path))))
    body = TestClient(app).get("/api/skills").json()
    names = {s["name"] for s in body["skills"]}
    vendored = {s["name"] for s in SkillsManager(str(tmp_path)).load_all()
                if s.get("library") == VENDORED_LIBRARY}
    assert not (names & vendored), f"{len(names & vendored)} vendored cards in the list"
    assert "my-own-procedure" in names
    assert body["count"] == len(body["skills"]) < 100
