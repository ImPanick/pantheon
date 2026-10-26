# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B371` — `with_asgi_root_path` is right for `--root-path` and wrong for an app
mounted inside another app; the second is written down as unsupported rather
than answered with a second derivation of the deployment's prefix.

Driven with the real helper inside a real Starlette mount — the shape `app.py`'s
`/static` mount has — under the two deployments: `uvicorn --root-path /pantheon`
(uvicorn hands the app `/pantheon/...` with that root path) and the app mounted
at `/pantheon` inside an outer Starlette app. In the first the redirect carries
the prefix. In the second it drops it. The row said `request.url_for` drops it
too; measured on Starlette 1.10.0 it does not — it resolves through the
outermost router — so the shape is unsupported by this helper, not by the
framework, and that is what is written down. Then the limitation is asked of
the two places a reader would look: the helper's docstring and the deployment
guide's prefix section (scoped to that section, `Law 20`).
"""
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.testclient import TestClient

from core.middleware import with_asgi_root_path

ROOT = Path(__file__).resolve().parents[1]


def _pantheon_shaped_app():
    """`/` and a `/static` mount whose page redirects to `/`, built the way
    `_RevalidatingStatic` builds its redirect."""
    async def home(request):
        return PlainTextResponse("home")

    async def page(request):
        return JSONResponse({
            "redirect": with_asgi_root_path(request.scope, "/"),
            "url_for": request.url_for("home").path,
        })

    static = Starlette(routes=[Route("/index.html", page)])
    return Starlette(routes=[Route("/", home, name="home"), Mount("/static", app=static)])


def test_under_root_path_the_redirect_carries_the_prefix():
    client = TestClient(_pantheon_shaped_app(), root_path="/pantheon")
    answer = client.get("/pantheon/static/index.html").json()
    assert answer == {"redirect": "/pantheon/", "url_for": "/pantheon/"}


def test_inside_an_outer_mount_the_redirect_drops_the_prefix():
    """The unsupported shape, measured as the docs describe it: the helper's
    redirect loses `/pantheon` while `url_for` keeps it. If either changes,
    this fails and the paragraph is stale."""
    outer = Starlette(routes=[Mount("/pantheon", app=_pantheon_shaped_app())])
    answer = TestClient(outer).get("/pantheon/static/index.html").json()
    assert answer == {"redirect": "/", "url_for": "/pantheon/"}


def test_the_helper_says_which_shape_is_supported():
    doc = with_asgi_root_path.__doc__ or ""
    assert "--root-path" in doc and "B371" in doc
    assert "Not supported" in doc


def test_the_deployment_guide_says_it_too():
    text = (ROOT / "docs" / "setup.md").read_text(encoding="utf-8")
    start = text.index("#### Serving under a path prefix")
    end = text.find("\n#", start + 1)
    section = text[start:end if end != -1 else None]
    assert "--root-path /pantheon" in section
    assert "is not supported" in section and "Mount(" in section
