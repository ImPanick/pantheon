# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression tests for endpoint owner scoping in secondary model routes."""

from pathlib import Path


# (`B1453`: the compare-start owner-scope tests lived here. `POST
# /api/compare/start` was retired with no caller — the Compare window opens its
# panes through the ordinary session routes, which carry their own owner
# scoping — so the route and its tests went together.)


def test_gallery_image_endpoint_lookups_are_owner_scoped():
    body = Path("routes/gallery/gallery_routes.py").read_text(encoding="utf-8")
    helper_body = body.split("def _visible_image_endpoint_query", 1)[1].split(
        "def _first_visible_image_endpoint", 1
    )[0]

    assert "owner_filter(q, ModelEndpoint, owner)" in helper_body
    assert body.count("_first_visible_image_endpoint(db, user)") >= 4
    assert body.count("_visible_image_endpoint_for_base(db,") >= 2
    assert "def _current_user_is_admin" in body
    assert body.count('raise HTTPException(403, "Choose a registered image endpoint")') == 2
    for marker in (
        "async def gallery_ai_upscale",
        "async def gallery_style_transfer",
        "async def inpaint_proxy",
        "async def harmonize_image",
    ):
        section = body.split(marker, 1)[1].split("@router.", 1)[0]
        assert "user = require_privilege(request, \"can_generate_images\")" in section
        assert (
            "_first_visible_image_endpoint(db, user)" in section
            or "_visible_image_endpoint_for_base(db," in section
        )


def test_research_endpoint_resolution_passes_owner():
    body = Path("routes/research/research_routes.py").read_text(encoding="utf-8")

    assert "def _resolve_research_endpoint(sess, owner:" in body
    assert 'resolve_endpoint("research", owner=user)' in body
    assert 'resolve_endpoint("utility", owner=user)' in body
    assert 'resolve_endpoint("default", owner=user)' in body
    assert 'resolve_endpoint("chat", owner=user)' in body
    helper_body = body.split("def _owned_enabled_endpoint", 1)[1].split("def setup_research_routes", 1)[0]
    assert "owner_filter(q, ModelEndpoint, owner)" in helper_body
    assert body.count("_owned_enabled_endpoint(db, user") >= 2
