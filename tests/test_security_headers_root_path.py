# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1957`. Under `--root-path`, no route kept its own security headers.

`SecurityHeadersMiddleware` picks a response's framing and CSP by its path: the
sandbox an upload opened as a page gets, the research report's inline scripts,
the framed PDF preview, tool render, design preview, Python sandbox and desktop
client. It read `request.url.path`, and uvicorn's `--root-path` (a deployment
`docs/setup.md` documents) puts the prefix on every request's path, so no
branch matched: an upload lost its sandbox to the app's policy, and every
framed preview was refused framing. `core/middleware.py` said so in a NOTE.

The branches now match the path Starlette routes by
(`get_application_route_path`), read before the request is dispatched, since
the `/static` mount rewrites the scope's `root_path` in place. Each route is
asked here with and without a prefix, through a real app with a real static
mount, and must be answered the same.

Reported upstream in Odysseus PR #6162 (3e46ced9, a12b6cda); its cases are
adapted here.
"""
import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from core.middleware import SecurityHeadersMiddleware

PREFIX = "/pantheon"
ROUTES = (
    "/api/upload/x",
    "/api/research/report/x",
    "/api/document/x/render-pdf",
    "/api/tools/x/render",
    "/api/design/designs/x/preview",
    "/python-sandbox",
    "/api/workstation/desktop/client/x",
    "/api/other",
)
PYODIDE_ASSET = "/static/lib/pyodide/a.js"
HEADERS = ("x-frame-options", "content-security-policy", "access-control-allow-origin",
           "x-content-type-options", "referrer-policy", "permissions-policy")


def _app(static_dir, routes=ROUTES):
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)
    for route in routes:
        app.add_api_route(route, lambda route=route: HTMLResponse(f"<html>{route}</html>"),
                          methods=["GET"])
    # As app.py mounts it. A Mount rewrites the scope it matched, in place.
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app


@pytest.fixture
def app(tmp_path):
    (tmp_path / "lib" / "pyodide").mkdir(parents=True)
    (tmp_path / "lib" / "pyodide" / "a.js").write_text("// the vendored runtime")
    return _app(tmp_path)


def _ask(app, path, root_path=""):
    """`path` asked the way uvicorn hands it on under `--root-path`: the scope
    keeps the prefixed path, and `root_path` says how much of it to strip."""
    return TestClient(app, root_path=root_path).get(root_path + path)


def _policy(response):
    return {name: response.headers.get(name) for name in HEADERS}


def test_an_upload_keeps_its_sandbox_under_a_prefix(app):
    """The FORBIDDEN Part 2 control: user-supplied bytes served from this
    origin open, if ever opened as a page, in an opaque sandbox."""
    response = _ask(app, "/api/upload/x", PREFIX)

    assert response.status_code == 200
    assert response.headers["x-frame-options"] == "DENY"
    assert "sandbox allow-downloads" in response.headers["content-security-policy"]


def test_every_route_keeps_its_own_headers_under_a_prefix(app):
    for path in (*ROUTES, PYODIDE_ASSET):
        plain, prefixed = _ask(app, path), _ask(app, path, PREFIX)

        assert prefixed.status_code == plain.status_code == 200, path
        assert prefixed.text == plain.text, path
        assert _policy(prefixed) == _policy(plain), path


@pytest.mark.parametrize("prefix, route", [
    ("/api/tools/x", "/render"),
    ("/api/document/x", "/render-pdf"),
    ("/api/research", "/report/x"),
])
def test_a_prefix_that_spells_a_framed_route_does_not_frame_another(tmp_path, prefix, route):
    """What Starlette routes decides the policy, not the URL's spelling: an
    ordinary route under a prefix that makes its URL read like a framed one
    keeps the strict policy."""
    response = _ask(_app(tmp_path, routes=(route,)), route, prefix)

    assert response.status_code == 200 and response.text == f"<html>{route}</html>"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


@pytest.mark.parametrize("root_path", ["", PREFIX])
def test_a_static_file_is_classified_by_the_path_it_was_asked_for(app, root_path):
    """The path is read before the request is dispatched. Read after, the
    `/static` mount has moved its own prefix into `root_path`: a static path
    that reads `/api/tools/x/render` past it would be served with no framing
    headers at all, and the vendored runtime would lose the one header that
    lets the sandboxed frame load it. Both hold before this change as well;
    they are here so that the order cannot move."""
    lookalike = _ask(app, "/static/api/tools/x/render", root_path)
    assert lookalike.status_code == 404
    assert lookalike.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in lookalike.headers["content-security-policy"]

    runtime = _ask(app, PYODIDE_ASSET, root_path)
    assert runtime.status_code == 200
    assert runtime.headers["access-control-allow-origin"] == "*"
