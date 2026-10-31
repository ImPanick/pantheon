# SPDX-License-Identifier: AGPL-3.0-or-later
"""The codex cookbook routes find the cookbook's own endpoints.

`/api/codex/cookbook/cached`, `/serve` and `/serve-preset` hand the work to
`/api/model/cached` and `/api/model/serve` by looking them up on the app. On
FastAPI 0.14x an included router stays one `_IncludedRouter` in `app.routes`,
so the flat walk they used found nothing and all three answered 503 *"model …
endpoint unavailable"* on every call — measured live with a signed-in admin.
"""
from fastapi import APIRouter, FastAPI

from routes.codex_routes import _app_endpoint


def _app_with(router_prefix: str = "", include_prefix: str = ""):
    router = APIRouter(prefix=router_prefix)

    @router.get("/cached")
    async def cached():
        return {"ok": True}

    @router.post("/serve")
    async def serve():
        return {"ok": True}

    outer = APIRouter()
    outer.include_router(router)
    app = FastAPI()
    app.include_router(outer, prefix=include_prefix)
    return app, cached, serve


def test_an_endpoint_inside_an_included_router_is_found():
    app, cached, serve = _app_with(router_prefix="/api/model")
    assert _app_endpoint(app, "GET", "/api/model/cached") is cached
    assert _app_endpoint(app, "POST", "/api/model/serve") is serve


def test_the_include_prefix_is_part_of_the_path():
    app, cached, _ = _app_with(router_prefix="/model", include_prefix="/api")
    assert _app_endpoint(app, "GET", "/api/model/cached") is cached
    assert _app_endpoint(app, "GET", "/model/cached") is None


def test_the_method_must_match():
    app, _, _ = _app_with(router_prefix="/api/model")
    assert _app_endpoint(app, "POST", "/api/model/cached") is None
    assert _app_endpoint(app, "GET", "/api/model/serve") is None


def test_the_real_app_serves_both_cookbook_endpoints():
    from app import app

    assert _app_endpoint(app, "GET", "/api/model/cached") is not None
    assert _app_endpoint(app, "POST", "/api/model/serve") is not None
