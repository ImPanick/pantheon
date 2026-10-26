# SPDX-License-Identifier: AGPL-3.0-or-later
import ast
from pathlib import Path


GATED_IMAGE_FUNCTIONS = {
    "gallery_ai_upscale",
    "gallery_style_transfer",
    "inpaint_proxy",
    "harmonize_image",
    "denoise_image",
    "upscale_image_local",
    "remove_background",
    "enhance_face",
}


def _gallery_source():
    return Path("routes/gallery/gallery_routes.py").read_text(encoding="utf-8")


def _function_sources(source):
    tree = ast.parse(source)
    return {
        node.name: ast.get_source_segment(source, node) or ""
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_image_generation_endpoints_require_image_privilege():
    source = _gallery_source()
    functions = _function_sources(source)

    for name in GATED_IMAGE_FUNCTIONS:
        assert name in functions
        assert 'require_privilege(request, "can_generate_images")' in functions[name]


def test_gallery_routes_imports_privilege_helper():
    source = _gallery_source()
    assert "get_current_user" in source
    assert "require_privilege" in source


def test_without_image_generation_a_persons_own_gallery_stays_theirs():
    """`B1195`, `D-2026-10-26-01` §6. The person's switch is *Image
    generation*: the AI image routes ask for it, and the routes that list and
    show their own images do not — nor does the Tools entry hide."""
    import re
    source = _gallery_source()
    functions = _function_sources(source)
    for route in ("/api/gallery/library", "/api/gallery/albums", "/api/gallery/{image_id}"):
        m = re.search(r'@router\.get\("' + re.escape(route) + r'"\)\s*\n\s*(?:async )?def (\w+)', source)
        assert m, route
        assert "can_generate_images" not in functions[m.group(1)], route
    vis = Path("static/js/ui_visibility.js").read_text(encoding="utf-8")
    entry = vis[vis.index("  gallery: _tool({"):]
    entry = entry[:entry.index("}),")]
    assert "privilege" not in entry and "feature: 'gallery'" in entry
