# SPDX-License-Identifier: AGPL-3.0-or-later
r"""Two routes in this app answer 404 on purpose, and both answers are decisions.

`B140` established the shape: a route whose page is not shipped answers a 404
naming what is missing, rather than a 500 with a stack trace per request or a
blank page that reaches for hosts nobody chose. `B210` and `B261` are the two
product questions that shape left open, and this file is where their answers
are pinned so neither can be quietly reversed in either direction.

**`B210` — the background sandbox page has never existed.**
`git log --all -- static/backgrounds.html` is empty across all 167 commits and
no deletion commit names it, so shipping it would be authoring a document, not
restoring one. Three places said otherwise, and one of them was **served**:
FastAPI publishes a route's docstring as its `description` in `/openapi.json`,
so `serve_backgrounds`'s opening line — *"Sandbox page for prototyping
background effects"* — was rendered in the API browser at `/docs` and read by
`src/tools/system.py`'s endpoint discovery, describing a page no build has ever
contained. `Law 1` protects a behaviour that exists; a claim that something
exists when it never has is a false statement and gets corrected.

**`B261` — this app ships one API browser.** ReDoc worked at the fork baseline
and `P16-07` removed `cdn.jsdelivr.net` from `script-src` for Pyodide's sake
and took it with it. Bringing it back needs either `'unsafe-eval'` and a
`blob:` worker allowance — the policy does not widen, and `'unsafe-eval'` is in
`.pantheon/FORBIDDEN.md` Part 2 — or 1.1 MB of vendored third-party JavaScript
whose worker path cannot be shown to be reachable or dead without a browser
this project does not have. `/docs` renders the same `/openapi.json` from bytes
this repository ships. So the 404 is the answer, and the assertions below are
what make it an answer rather than a placeholder: the route still exists, the
reply names where to go, and the policy did not get looser on the way.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from tests.helpers.served_pages import probe_served_surface  # noqa: E402


@pytest.fixture(scope="module")
def surface(tmp_path_factory) -> dict:
    """The served surface, from the one enumerator (`B260`)."""
    return probe_served_surface(tmp_path_factory.mktemp("served_surface"))


@pytest.fixture(scope="module")
def schema(surface) -> dict:
    """This app's own OpenAPI document, as served."""
    row = surface["pages"]["/openapi.json"]
    assert row["status"] == 200, row
    return json.loads(row["body"])


def test_the_schema_does_not_advertise_a_page_this_build_has_never_had(schema):
    """`B210`'s `Verify:`, asked of the document the claim is published in.

    Fails on the tree as it stood: the served `description` for
    `GET /backgrounds` was *"Sandbox page for prototyping background
    effects."* followed by `B140`'s reasoning — an API schema telling its
    reader that a route serves a page, when the route's only possible answer
    in this build is 404.

    Note what is asserted and what is not. Nobody has to say *"not shipped"* in
    those words; what may not survive is a description that reads as an
    advertisement for a working page. The 404 the route actually returns is
    checked below, against the same running app.
    """
    op = schema["paths"]["/backgrounds"]["get"]
    described = f"{op.get('summary', '')}\n{op.get('description', '')}"
    assert described.strip(), op

    lowered = described.lower()
    assert "not shipped" in lowered, described
    # The sentence that was there. A description may explain the page that
    # would go here; it may not open by claiming this route is that page.
    first_line = described.strip().splitlines()[0].lower()
    assert "sandbox page for prototyping" not in first_line, described

    # And the description is the short, true one rather than the whole
    # reasoning: FastAPI truncates a docstring at `\f`, which is what keeps the
    # row's argument in the source and out of the published schema.
    assert len(op.get("description", "")) < 600, op["description"]


def test_the_backgrounds_route_still_exists_and_still_names_its_file(surface):
    """`Law 1`. The answer became honest; the route did not go away.

    A deployment that drops `static/backgrounds.html` in is served it from
    here, so the route is kept and the 404 names the file it wants —
    repo-relative, because a reply from an unauthenticated-by-design route must
    not hand out the deployment's absolute paths.
    """
    row = surface["pages"]["/backgrounds"]
    assert row["status"] == 404, row
    assert "static/backgrounds.html" in row["body"], row["body"][:300]
    assert str(ROOT) not in row["body"], row["body"][:300]


def test_the_one_api_browser_is_named_by_the_route_that_is_not_one(surface):
    """`B261`'s `Verify:`, closed as *one API browser is enough*.

    The reply a reader gets has to be usable by a stranger: it says which
    browser this build ships, where the schema is, and why ReDoc is not here —
    not a bare row identifier, which means nothing outside this repository and
    is exactly the placeholder this row exists to replace.

    Fails on the tree as it stood: the body read *"…need CSP allowances this
    app does not grant (B212)"*.
    """
    row = surface["pages"]["/redoc"]
    assert row["status"] == 404, row
    body = row["body"]
    assert "/docs" in body, body
    assert "/openapi.json" in body, body
    # The reason, in the reply rather than only in the commit history.
    assert "worker" in body.lower(), body
    # No internal row identifiers in something a stranger reads.
    assert "(B2" not in body and "(B1" not in body, body

    # And the route is still a route (`Law 1`): a build that vendors ReDoc
    # serves it from here. `include_in_schema=False` keeps FastAPI's own two
    # doc routes out of the schema, so its absence there is not its removal.
    assert surface["pages"]["/docs"]["status"] == 200, surface["pages"]["/docs"]


def test_the_policy_did_not_widen_to_get_redoc_back(surface):
    """The other way `B261` could have been closed, and the one that must fail.

    ReDoc builds its search index in `new Worker(URL.createObjectURL(new
    Blob(…)))` and carries an Ajv `new Function(…)` path. Both are refused
    today because this policy declares no `worker-src` and no `child-src`, so
    workers fall back to `default-src 'self'`, and `script-src` names no
    `'unsafe-eval'`. Adding either — even scoped to one response — is the
    outcome the row forbids, and a `blob:` worker is the standard way a script
    that has reached a page runs code the policy never hashed.
    """
    checked = 0
    for url, row in sorted(surface["pages"].items()):
        csp = row["csp"]
        if not csp:
            continue
        checked += 1
        assert "'unsafe-eval'" not in csp, (url, csp)
        assert "blob:" not in csp.split("img-src")[0], (url, csp)
        for directive in ("worker-src", "child-src"):
            assert directive not in csp, (url, directive, csp)
    assert checked >= 5, f"only {checked} responses carried a policy at all"
