# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P26-06` / `P26-07` — a design is files in the project, with versions and
variants, adjusted on a canvas that writes the file.

Driven, not read (`Law 20`): a real project folder on this machine (the host
half of `design_files._Fs`; the workstation half is the same calls through
the client `P20` built and tests), the agent's work simulated the way the agent
does it — files written into the design's folder — and the canvas's changes
read back out of `index.html`. The window's pure parts run under node.

**Measured before this file, on `ae3a838`:** a brief from the Design window
went to the chat and the result was wherever the agent put it; nothing kept
versions, nothing compared variants, nothing changed a design without a
model.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src import design_files as F

PAGE = """<!doctype html><html><head><title>Shop</title>
<link rel="stylesheet" href="style.css">
<style>:root { --gap: 16px; --radius: 8px; --accent: #1a73e8; --scale: 1; }</style></head>
<body><main><h1>Wool &amp; Co</h1><p>Warm socks.</p><img src="logo.svg"></main>
<script src="app.js"></script></body></html>"""


@pytest.fixture()
def project(tmp_path, monkeypatch):
    import src.workstation_access as wa
    import src.tool_security as ts
    monkeypatch.setattr(wa, "routes_tools", lambda owner, **kw: False)
    monkeypatch.setattr(ts, "blocked_tools_for_owner", lambda owner: set())
    p = tmp_path / "shop"
    p.mkdir()
    return p


def run(coro):
    return asyncio.run(coro)


def _agent_writes(folder: Path, page: str = PAGE):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.html").write_text(page)
    (folder / "style.css").write_text("h1 { color: var(--accent); }")
    (folder / "app.js").write_text("document.title += ' ✓'; // </script> inside a string")
    (folder / "logo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")


def test_a_design_is_a_folder_and_every_change_elsewhere_becomes_a_version(project):
    made = run(F.create("alice", str(project), {"name": "Shop home", "kind": "mockup", "brief": "Two products"}))
    assert made["folder"] == "design/shop-home"
    meta = json.loads((project / "design/shop-home/design.json").read_text())
    assert meta["kind"] == "mockup" and "Two products" in (project / "design/shop-home/brief.md").read_text()
    again = run(F.create("alice", str(project), {"name": "Shop home", "kind": "mockup"}))
    assert again["slug"] == "shop-home-2", "a second design with the same name never overwrites the first"

    empty = run(F.opened("alice", str(project), "shop-home"))
    assert empty["page"] == {"html": "", "missing": ["index.html"]} and empty["versions"] == []

    _agent_writes(project / "design/shop-home")
    first = run(F.opened("alice", str(project), "shop-home"))
    assert [v["n"] for v in first["versions"]] == [1] and "the agent" in first["versions"][0]["note"]
    html = first["page"]["html"]
    assert '<style data-from="style.css">' in html and "color: var(--accent)" in html, "its stylesheet inlined"
    assert "document.title" in html and "<\\/script>" in html, "its script inlined, closed safely"
    assert "data:image/svg+xml;base64," in html, "a small image inlined"
    assert run(F.opened("alice", str(project), "shop-home"))["versions"] == first["versions"], \
        "opening again without a change keeps no new version"

    (project / "design/shop-home/index.html").write_text(PAGE.replace("Warm socks.", "Warmer socks."))
    assert [v["n"] for v in run(F.opened("alice", str(project), "shop-home"))["versions"]] == [1, 2]
    listed = run(F.listing("alice", str(project)))
    assert {d["slug"]: d.get("has_page", False) for d in listed} == {"shop-home": True, "shop-home-2": False}


def test_stepping_back_keeps_the_present_and_is_itself_a_version(project):
    run(F.create("alice", str(project), {"name": "Page", "kind": "document"}))
    folder = project / "design/page"
    _agent_writes(folder)
    run(F.opened("alice", str(project), "page"))                      # version 1
    (folder / "index.html").write_text(PAGE.replace("Wool", "Cotton"))
    run(F.opened("alice", str(project), "page"))                      # version 2
    out = run(F.restore("alice", str(project), "page", 1))
    assert out["restored"] == 1 and "Wool" in (folder / "index.html").read_text()
    notes = [v["note"] for v in run(F.opened("alice", str(project), "page"))["versions"]]
    assert notes[-1] == "Stepped back to version 1"
    shown = run(F.opened("alice", str(project), "page", version=2))
    assert "Cotton" in shown["page"]["html"] and shown["showing"] == {"version": 2, "variant": None}
    run(F.restore("alice", str(project), "page", 2))
    assert "Cotton" in (folder / "index.html").read_text(), "stepping back is undoable"


def test_keeping_a_variant_makes_it_the_design_and_keeps_the_others(project):
    run(F.create("alice", str(project), {"name": "Deck", "kind": "slides"}))
    folder = project / "design/deck"
    _agent_writes(folder)
    for k, word in (("1", "Bold"), ("2", "Quiet"), ("3", "Playful")):
        (folder / "variants" / k).mkdir(parents=True)
        (folder / "variants" / k / "index.html").write_text(PAGE.replace("Wool &amp; Co", word))
    seen = run(F.opened("alice", str(project), "deck"))
    assert seen["variants"] == ["1", "2", "3"]
    assert "Quiet" in run(F.opened("alice", str(project), "deck", variant="2"))["page"]["html"]
    kept = run(F.keep_variant("alice", str(project), "deck", "2"))
    assert kept["others"] == ["1", "3"]
    assert "Quiet" in (folder / "index.html").read_text() and not (folder / "variants").exists()
    notes = [v["note"] for v in run(F.opened("alice", str(project), "deck"))["versions"]]
    assert notes[:4] == ["Changed in the files (the agent, or a hand)", "Variant 1, not kept",
                         "Variant 3, not kept", "Kept variant 2"]
    with pytest.raises(F.DesignFileRefused):
        run(F.keep_variant("alice", str(project), "deck", "9"))


def test_an_adjustment_is_one_rule_in_one_block_of_the_file_and_a_version(project):
    run(F.create("alice", str(project), {"name": "Home", "kind": "mockup"}))
    folder = project / "design/home"
    _agent_writes(folder)
    out = run(F.adjust("alice", str(project), "home", "body > main > h1", {"color": "var(--color-ink)",
                                                                           "font-size": "var(--text-4)"},
                       tokens_css=":root {\n  --color-ink: #111827;\n}\n"))
    html = (folder / "index.html").read_text()
    assert html.count("<style data-pantheon-edits>") == 1 and html.index("data-pantheon-edits") < html.index("</head>")
    assert "body > main > h1 { color: var(--color-ink); font-size: var(--text-4); }" in html
    assert "--color-ink: #111827;" in html, "the design system's tokens travel with the page"
    assert "<h1>Wool &amp; Co</h1>" in html, "the agent's markup is untouched"
    assert out["edits"] == {"body > main > h1": {"color": "var(--color-ink)", "font-size": "var(--text-4)"}}
    run(F.adjust("alice", str(project), "home", "body > main > h1", {"font-size": None}))
    run(F.adjust("alice", str(project), "home", ":root", {"--gap": "24px"}))
    html = (folder / "index.html").read_text()
    assert F.edits_of(html) == {"body > main > h1": {"color": "var(--color-ink)"}, ":root": {"--gap": "24px"}}
    assert F.root_vars(html)["--gap"] == "24px", "a tweak wins over the page's own value"
    notes = [v["note"] for v in run(F.opened("alice", str(project), "home"))["versions"]]
    assert notes[-1] == "Tweaked --gap 24px" and "Adjusted font-size reset" in notes


@pytest.mark.parametrize("selector,props,words", [
    ("body > main > h1", {"position": "fixed"}, "not something the canvas changes"),
    ("body > main > h1", {"color": "red; } body { display: none"}, "not a value the canvas writes"),
    ("html > head > script", {"color": "#000"}, "cannot be adjusted here"),
    ("body > h1", {"color": "url(javascript:x)"}, "not a value the canvas writes"),
    (":root", {"color": "#000"}, "not a custom property"),
])
def test_what_the_canvas_writes_is_bounded(selector, props, words):
    with pytest.raises(F.DesignFileRefused) as e:
        F.check_change(selector, props)
    assert words in e.value.sentence


def test_tweaks_are_the_pages_own_variables(project, monkeypatch):
    cands = F.tweak_candidates(PAGE)
    by = {c["name"]: c for c in cands}
    assert by["--gap"]["kind"] == "number" and by["--gap"]["unit"] == "px" and by["--gap"]["max"] == 48
    assert by["--accent"] == {"name": "--accent", "kind": "colour", "value": "#1a73e8", "label": "accent"}
    assert by["--scale"]["step"] == 0.05
    run(F.create("alice", str(project), {"name": "T", "kind": "mockup"}))
    _agent_writes(project / "design/t")
    got = run(F.suggest_tweaks("alice", str(project), "t"))
    assert got["chosen_by"] == "page" and len(got["tweaks"]) == 4, "four or fewer: offered as they are"


def test_a_project_the_person_cannot_write_is_refused(tmp_path, monkeypatch):
    import src.workstation_access as wa
    import src.tool_security as ts
    monkeypatch.setattr(wa, "routes_tools", lambda owner, **kw: False)
    monkeypatch.setattr(ts, "blocked_tools_for_owner", lambda owner: {"write_file"})
    with pytest.raises(F.DesignFileRefused) as e:
        run(F.listing("bob", str(tmp_path)))
    assert "workstation" in e.value.sentence
    with pytest.raises(F.DesignFileRefused):
        run(F.opened("alice", "", "x"))


def test_the_routes(project, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routes.design_routes as R
    monkeypatch.setattr(R, "get_current_user", lambda request: request.headers.get("x-user"))
    monkeypatch.setattr(R, "request_is_a_person", lambda request: request.headers.get("x-token") is None)
    app = FastAPI()
    app.include_router(R.setup_design_routes())
    c = TestClient(app)
    a = {"x-user": "alice"}
    made = c.post("/api/design/designs", headers=a, json={"project": str(project), "name": "Shop", "kind": "mockup"})
    assert made.status_code == 200 and made.json()["slug"] == "shop"
    _agent_writes(project / "design/shop")
    one = c.get(f"/api/design/designs/shop?project={project}", headers=a).json()
    assert one["versions"][0]["n"] == 1 and one["page"]["html"].startswith("<!doctype html>")
    shown = c.get(f"/api/design/designs/shop/preview?project={project}", headers=a)
    assert shown.status_code == 200 and shown.headers["content-type"].startswith("text/html")
    assert "data-pantheon-picker" in shown.text and shown.headers["cache-control"] == "no-store"
    adj = c.post("/api/design/designs/shop/adjust", headers=a,
                 json={"project": str(project), "selector": "body > main > p", "props": {"text-align": "center"}})
    assert adj.status_code == 200 and adj.json()["version"] == 2
    bad = c.post("/api/design/designs/shop/adjust", headers=a,
                 json={"project": str(project), "selector": "body", "props": {"color": "<b>"}})
    assert bad.status_code == 400 and "not a value" in bad.json()["detail"]
    token = c.post("/api/design/designs/shop/restore", headers={"x-user": "alice", "x-token": "1"},
                   json={"project": str(project), "version": 1})
    assert token.status_code == 403
    assert c.post("/api/design/designs/shop/restore", headers=a,
                  json={"project": str(project), "version": 1}).json()["restored"] == 1
    assert c.get(f"/api/design/designs/nope?project={project}", headers=a).status_code == 404


def test_the_picker_and_the_choices_under_node(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here")
    view = Path(__file__).resolve().parents[1] / "static" / "js" / "design" / "designView.js"
    case = tmp_path / "case.mjs"
    case.write_text(f"""
const {{ choicesFor, PICKED_PROPS }} = await import('{view.as_uri()}');
const tokens = {{ palette: [{{ name: 'Ink Dark', value: '#111827', role: 'text' }}],
  type: {{ scale: [12, 16] }}, spacing: [4, 8], radii: [6] }};
console.log(JSON.stringify({{
  props: PICKED_PROPS,
  colour: choicesFor('color', tokens), size: choicesFor('font-size', tokens),
  gap: choicesFor('gap', tokens), align: choicesFor('text-align', tokens).map((c) => c.value),
}}));
""")
    out = json.loads(subprocess.run([node, str(case)], capture_output=True, text=True, check=True).stdout)
    assert "color" in out["props"] and "justify-content" in out["props"], "the picker is asked for every panel property"
    assert out["colour"] == [{"label": "Ink Dark (#111827)", "value": "var(--color-ink-dark)"}]
    assert out["size"][1] == {"label": "16px", "value": "var(--text-2)"} and out["gap"][0]["value"] == "var(--space-1)"
    assert out["align"] == ["left", "center", "right", "justify"]


def test_the_last_variable_needs_no_semicolon():
    assert F.root_vars("<style>:root{--gap:16px;--pad:24px}</style>") == {"--gap": "16px", "--pad": "24px"}


def test_the_preview_is_its_own_sandboxed_document(project, monkeypatch):
    """A `srcdoc` frame inherits the app's CSP, which runs no inline script but
    the app's own — so the design's scripts and the picker never ran. The page
    is its own document now, with its own policy: scripts, in an opaque origin,
    fetching nothing."""
    page = F.with_picker("<html><body><h1>x</h1></body></html>")
    assert page.index("data-pantheon-picker") < page.index("</body>")
    assert F.with_picker("<h1>x</h1>").endswith("</script>")
    assert "parent.postMessage" in F.PICKER and "'pantheon-selected'" in F.PICKER
    src = (Path(__file__).resolve().parents[1] / "core" / "middleware.py").read_text()
    branch = src[src.index("elif is_design_preview:"):src.index("elif is_tool_render:")]
    for need in ("default-src 'none'", "sandbox allow-scripts", "script-src 'unsafe-inline'", "frame-ancestors 'self'"):
        assert need in branch, need
    assert "connect-src" not in branch and "'self'" not in branch.replace("frame-ancestors 'self'", ""), \
        "the page reaches nothing, not even this app"
    view = (Path(__file__).resolve().parents[1] / "static" / "js" / "design" / "designView.js").read_text()
    assert "srcdoc" not in view.split("function _frame", 1)[1].split("}", 1)[0]
