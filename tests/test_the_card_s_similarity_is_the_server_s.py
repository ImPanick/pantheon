# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B793` (absorbs `B731`) — the similarity a card shows is the server's.

`B731` read the Workshop's 0.38 and `add_skill`'s 0.82 as one question answered
two ways. `P8-15` put the two **server** implementations on one function
(`skill_lint.skill_similarity`) and `B793` found the third: `static/js/skills.js`
carried its own tokenizer (`_skillTokens`, which left `procedure` out) and its
own 0.38, so the number behind a card's *duplicate* pill and the number the
server refuses a creation at were two functions of two field sets — they agreed
on the bundled library only because none of its 286 skills has a populated
procedure.

Now `GET /api/skills` puts on each skill the rows `skill_lint.overlap_map`
reports (`similar`, from `skill_overlaps`, the loop the lint, the audit and
`add_skill` share) and the two points of the scale (`similarity`), and the page
groups by those rows and computes no similarity of its own. The pill's tooltip
says what the pair shares and that the server refuses only at its own point —
`B731`'s second `Verify:` branch.

`Verify:` the similarity a person sees on a card and the similarity the server
refuses a creation at are the same function of the same fields, and one of them
is not a copy.
"""
from __future__ import annotations

import json
import shutil
import textwrap

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.skills_routes import setup_skills_routes
from services.memory.skill_lint import (
    DUPLICATE_REFUSAL,
    DUPLICATE_SIMILARITY,
    skill_similarity,
)
from services.memory.skills import SkillsManager
from test_one_skills_module_two_places_js import PREAMBLE, box  # noqa: F401
from test_the_workshop_surfaces_js import SKILLS_JS
from test_tool_effect_surfaces_js import _run

STEPS = ["rotate the nginx access logs", "compress yesterday's archive",
         "prune archives older than thirty days", "restart nginx gracefully"]


def _write(root, name, description, procedure):
    d = root / "skills" / "ops" / name
    d.mkdir(parents=True)
    body = "\n".join(f"{i}. {s}" for i, s in enumerate(procedure, 1))
    (d / "SKILL.md").write_text(textwrap.dedent(f"""\
        ---
        name: {name}
        description: {description}
        category: ops
        status: published
        ---

        ## Procedure
        """) + body + "\n", encoding="utf-8")


def test_the_list_carries_the_servers_number_for_each_pair(tmp_path):
    """Two skills whose shared words are in the procedure: the old client
    tokenizer, which read no procedure, scored them apart; the server's
    comparison — the one `add_skill` refuses at — scores them together, and
    that number is what the list carries."""
    _write(tmp_path, "log-housekeeping", "keep the web server tidy", STEPS)
    _write(tmp_path, "nightly-cleanup", "what runs after midnight", STEPS)
    app = FastAPI()
    app.include_router(setup_skills_routes(SkillsManager(str(tmp_path), library_root="")))
    body = TestClient(app).get("/api/skills").json()

    assert body["similarity"] == {"advisory": DUPLICATE_SIMILARITY, "refusal": DUPLICATE_REFUSAL}
    by = {s["name"]: s for s in body["skills"]}
    a, b = by["log-housekeeping"], by["nightly-cleanup"]
    expected = round(skill_similarity(a, b), 3)
    assert expected >= DUPLICATE_SIMILARITY, "the pair does not exercise the advisory point"
    assert a["similar"] == [{"name": "nightly-cleanup", "score": expected, "same_base": False}]
    assert b["similar"] == [{"name": "log-housekeeping", "score": expected, "same_base": False}]


def test_the_page_holds_no_comparison_of_its_own():
    """A file-wide absence is the one thing a substring may prove (`Law 20`):
    the tokenizer and the 0.38 the page carried are gone from it."""
    js = SKILLS_JS.read_text(encoding="utf-8")
    for gone in ("function _skillTokens", "function _skillSimilarity", ">= 0.38"):
        assert gone not in js, gone


node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _drawn(box, rows):
    """The real `skills.js`, its cards parsed into real nodes (the two-places
    harness), the list answered with `rows` and the server's scale."""
    return _run(box, PREAMBLE, """
        server.skills = %s;
        const realFetch = globalThis.fetch;
        globalThis.fetch = async (url, init = {}) => {
          const r = await realFetch(url, init);
          const u = String(url).replace('http://test.local', '');
          if (u !== '/api/skills' || (init.method || 'GET') !== 'GET') return r;
          const body = await r.json();
          return { ok: true, status: 200,
                   json: async () => ({ ...body, similarity: { advisory: 0.38, refusal: 0.82 } }) };
        };
        await skills.loadSkills();
        await tick();
        out(cards('skills-list').map((c) => {
          const pill = c.querySelector('.skill-necessity-pill');
          return { name: c.dataset.skillName,
                   label: pill ? pill.textContent : '',
                   title: pill ? (pill.getAttribute('title') || '') : '' };
        }));
    """ % json.dumps(rows))


def _row(name, description, similar):
    return {"name": name, "description": description, "category": "ops",
            "status": "published", "confidence": 0.9, "uses": 0, "version": "1.0.0",
            "similar": similar}


@node
def test_two_skills_the_server_does_not_pair_are_not_drawn_as_duplicates(box):  # noqa: F811
    """Identical descriptions — the page's own tokenizer grouped these at 0.38
    — and no server row between them: no pill."""
    same = "rotate and prune the nginx access logs every night"
    drawn = _drawn(box, [_row("first-way", same, []), _row("second-way", same, [])])
    assert sorted(d["name"] for d in drawn) == ["first-way", "second-way"], drawn
    assert [d for d in drawn if d["label"]] == [], drawn


@node
def test_a_pair_the_server_reports_is_grouped_and_the_pill_says_why(box):  # noqa: F811
    drawn = _drawn(box, [
        _row("log-housekeeping", "keep the web server tidy",
             [{"name": "nightly-cleanup", "score": 0.44, "same_base": False}]),
        _row("nightly-cleanup", "what runs after midnight",
             [{"name": "log-housekeeping", "score": 0.44, "same_base": False}]),
    ])
    assert sorted(d["label"] for d in drawn) == ["duplicate #1", "duplicate #1"], drawn
    title = drawn[0]["title"]
    assert "Shares 44% of its wording with" in title, title
    assert "refused only at 82%" in title, "the server's refusal point is not in the tooltip"
