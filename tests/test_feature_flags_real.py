# SPDX-License-Identifier: AGPL-3.0-or-later
"""A flag turned off is off — for the user and for the agent (`H05`).

THE STATE THIS ROW FOUND.

`DEFAULT_FEATURES` has eight switches. Seven of them did nothing.
`load_features()` had three callers and every one was read-write plumbing, so no
server-side code branched on any flag. Enforcement was entirely client-side:
`static/app.js` set `display:none` on four elements, and `censor.js` read
`sensitive_filter`. **`web_fetch`, `memory` and `rag` had no consumer in any
layer.**

And the client-side half did not work either. The features fetch hid nine
elements and then, in the SAME `.then()` callback one line later, called
`applyUIVis(loadUIVis())` — which writes `display` for all 31 selectors in
`UI_VIS_MAP`, every one of which resolves visible for a user with default
Appearance prefs. Replaying the real sequence: nine hidden, then seven shown
again.

So an admin who turned off Deep Research got a `200`, a toggle that stayed off,
and a feature that was still there — still on screen, still answering HTTP, and
still callable by the model.

The row's `Verify:` is one sentence and these tests are it, layer by layer.
"""
import json
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"


# ── the agent: the half the row is really about ─────────────────────────────

def test_every_flag_is_accounted_for_in_the_tool_map():
    """A flag added later with no entry here is a switch that silently does
    nothing for the agent, which is the exact defect being fixed. Every flag is
    either mapped to tools or explicitly noted as having none, and the note says
    why."""
    from src.settings import DEFAULT_FEATURES
    from src.tool_security import _FEATURE_TOOLS, _FEATURE_NOTES

    accounted = set(_FEATURE_TOOLS) | set(_FEATURE_NOTES)
    missing = set(DEFAULT_FEATURES) - accounted
    assert not missing, f"flags with no decision recorded: {sorted(missing)}"
    for flag, names in _FEATURE_TOOLS.items():
        if not names:
            assert flag in _FEATURE_NOTES, \
                f"{flag} maps to no tools and does not say why"
    for flag, note in _FEATURE_NOTES.items():
        assert len(note) > 60, f"{flag}'s note is not a reason"


def test_every_mapped_tool_name_actually_exists():
    """The `B32` family. A denylist entry naming a tool nobody wrote blocks
    nothing and fails silently forever — and here the symptom is a feature
    switch that appears to work and does not."""
    import src.agent_tools  # noqa: F401  (resolves the circular import cluster)
    from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
    from src.tool_security import _FEATURE_TOOLS, _PLAN_MODE_KNOWN_MUTATORS

    known = {(t.get("function") or {}).get("name") for t in FUNCTION_TOOL_SCHEMAS}
    known.discard(None)
    # Some tools are XML-invocable only and never appear in the function
    # schemas; the plan-mode backstop is the existing inventory of those.
    known |= _PLAN_MODE_KNOWN_MUTATORS
    for flag, names in _FEATURE_TOOLS.items():
        for name in names:
            assert name in known, f"{flag} maps to {name!r}, which is not a tool"


@pytest.mark.parametrize("flag,expected", [
    ("deep_research", {"trigger_research", "manage_research"}),
    ("gallery", {"generate_image", "edit_image"}),
    ("web_search", {"web_search"}),
    ("web_fetch", {"web_fetch"}),
    ("memory", {"manage_memory"}),
])
def test_turning_a_flag_off_denies_its_tools(flag, expected):
    from src.tool_security import feature_disabled_tools
    assert feature_disabled_tools({flag: False}) == expected
    assert feature_disabled_tools({flag: True}) == set()


def test_the_denylist_is_empty_when_everything_is_on():
    from src.settings import DEFAULT_FEATURES
    from src.tool_security import feature_disabled_tools
    assert feature_disabled_tools({k: True for k in DEFAULT_FEATURES}) == set()


def test_the_shipped_defaults_only_deny_what_they_ship_off():
    """`deep_research` is the one flag that ships off. Nothing else should be
    denied on a fresh install, or the product arrives with capability missing
    that nobody chose to remove."""
    from src.settings import DEFAULT_FEATURES
    from src.tool_security import feature_disabled_tools
    assert DEFAULT_FEATURES["deep_research"] is False
    assert feature_disabled_tools(dict(DEFAULT_FEATURES)) == {
        "trigger_research", "manage_research"}


def test_an_unreadable_features_file_leaves_everything_ON(monkeypatch):
    """Fails open, deliberately. A features file that will not parse must not
    silently take half the product away — and the failure would look identical
    to an admin having turned everything off on purpose."""
    import src.tool_security as ts
    monkeypatch.setattr("src.settings.load_features",
                        lambda: (_ for _ in ()).throw(OSError("disk")))
    assert ts.feature_disabled_tools() == set()


def test_the_agent_loop_contributes_the_feature_denylist():
    """`Law 15` in the form this row keeps producing: a computed denylist nobody
    unions in is a function with no caller.

    Parsed rather than grepped — the comment beside the call explains the whole
    row and names the function, so a substring search passes either way.
    """
    import ast
    tree = ast.parse((ROOT / "src" / "agent_loop.py").read_text(encoding="utf-8"))
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name:
                called.add(name)
    assert "feature_disabled_tools" in called, \
        "the loop never unions the feature denylist"
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(a.name for a in node.names)
    assert "feature_disabled_tools" in imported


def test_the_feature_denylist_reaches_the_same_gate_plan_mode_uses(monkeypatch):
    """`Law 14`. Not a second enforcement path — the same `disabled_tools` set
    `execute_tool_block` already blocks on, so it inherits that gate's tests and
    its fail-closed behaviour rather than growing a parallel one that can
    disagree."""
    import ast
    src = (ROOT / "src" / "agent_loop.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    targets = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "update":
            arg = node.args[0] if node.args else None
            if isinstance(arg, ast.Call):
                inner = getattr(arg.func, "id", None) or getattr(arg.func, "attr", None)
                if inner in ("feature_disabled_tools", "plan_mode_disabled_tools"):
                    targets.add((getattr(node.func.value, "id", None), inner))
    assert ("disabled_tools", "feature_disabled_tools") in targets
    assert ("disabled_tools", "plan_mode_disabled_tools") in targets


# ── the HTTP surface ────────────────────────────────────────────────────────

def test_the_gate_refuses_when_off_and_passes_when_on(monkeypatch):
    from fastapi import HTTPException
    from src.feature_gate import require_feature

    monkeypatch.setattr("src.settings.load_features", lambda: {"gallery": False})
    guard = require_feature("gallery", label="Gallery")
    with pytest.raises(HTTPException) as refused:
        guard()
    assert refused.value.status_code == 403
    assert "Gallery" in str(refused.value.detail)
    assert "administrator" in str(refused.value.detail).lower(), \
        "the refusal does not say who can undo it"

    monkeypatch.setattr("src.settings.load_features", lambda: {"gallery": True})
    assert require_feature("gallery")() is None


def test_it_is_403_and_not_404():
    """`P16-12`'s metrics endpoint returns 404 because off should look like
    never built. That is right for an attack surface and wrong here: this is a
    feature the user can see, that their admin switched off, and 404 is a lie
    they can disprove by asking a colleague."""
    from src.feature_gate import require_feature
    from fastapi import HTTPException
    import src.feature_gate as fg
    guard = require_feature("gallery")
    orig = fg.feature_enabled
    fg.feature_enabled = lambda name, features=None: False
    try:
        with pytest.raises(HTTPException) as e:
            guard()
    finally:
        fg.feature_enabled = orig
    assert e.value.status_code == 403


def test_an_unknown_flag_name_is_ON(monkeypatch):
    """This answers *has somebody switched this off*, and nobody can have
    switched off a flag that does not exist. Treating unknown as off would turn
    a typo in a call site into a silently dead feature — the exact defect."""
    from src.feature_gate import feature_enabled
    assert feature_enabled("nonesuch", {"gallery": False}) is True


def test_an_unreadable_features_file_leaves_the_routes_open(monkeypatch):
    from src.feature_gate import feature_enabled
    monkeypatch.setattr("src.settings.load_features",
                        lambda: (_ for _ in ()).throw(OSError("disk")))
    assert feature_enabled("gallery") is True


@pytest.mark.parametrize("module,flag", [
    ("routes/research/research_routes.py", "deep_research"),
    ("routes/gallery/gallery_routes.py", "gallery"),
    ("routes/memory/memory_routes.py", "memory"),
    ("routes/document/document_routes.py", "document_editor"),
])
def test_the_gate_is_on_the_ROUTER_not_on_individual_routes(module, flag):
    """Router-level is the difference between a gate and a convention.
    Per-route decoration means every future route in the file has to remember,
    and the one that forgets is indistinguishable from the state this row
    found.

    Parsed: each of these files carries a comment naming the flag.
    """
    import ast
    src = (ROOT / module).read_text(encoding="utf-8")
    tree = ast.parse(src)
    ok = False
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "APIRouter"):
            continue
        for kw in node.keywords:
            if kw.arg != "dependencies":
                continue
            rendered = ast.dump(kw.value)
            if "require_feature" in rendered and repr(flag).strip("'\"") in ast.unparse(kw.value):
                ok = True
    assert ok, f"{module} does not gate its router on {flag!r}"


def test_the_gated_routers_actually_refuse(monkeypatch):
    """Through the real router, not through the dependency in isolation: a
    dependency that is never mounted refuses nothing."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import src.feature_gate as fg

    monkeypatch.setattr(fg, "feature_enabled",
                        lambda name, features=None: name != "gallery")
    from routes.gallery.gallery_routes import setup_gallery_routes
    router = setup_gallery_routes()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    # Paths come off the ROUTER: this FastAPI wraps an included router in an
    # `_IncludedRouter` rather than flattening it into `app.routes`, so reading
    # the app would have found nothing and passed a weaker version of this test.
    paths = [r.path for r in router.routes
             if getattr(r, "path", "").startswith("/api/gallery")]
    assert paths, "no gallery routes were mounted"
    concrete = [p for p in paths if "{" not in p]
    assert concrete, "no parameter-free gallery route to probe"
    for path in concrete[:4]:
        for verb in ("get", "post"):
            res = getattr(client, verb)(path)
            if res.status_code == 405:
                continue
            assert res.status_code == 403, \
                f"{verb.upper()} {path} answered {res.status_code} with gallery off"
            assert "Gallery" in res.text
            break


# ── retrieval: the flag with no tool and no router of its own ───────────────

def test_rag_is_honoured_at_the_retrieval_site():
    """Retrieval is not a tool the model calls — it is context assembled before
    the turn — so there is no name for a denylist and no router that is only
    retrieval. A flag mapped to either would have been decoration. `rag` was one
    of the three flags with NO consumer in any layer; this is its consumer.
    """
    import ast
    src = (ROOT / "src" / "chat_processor.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    guarded = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        rendered = ast.unparse(node.test)
        if "feature_enabled" in rendered and "rag" in rendered:
            guarded = True
    assert guarded, "nothing checks the `rag` flag before retrieving"
    from src.tool_security import _FEATURE_NOTES
    assert "rag" in _FEATURE_NOTES


# ── the UI: the bug that un-hid four elements one line after hiding them ────

_UIVIS_SHIM = r"""
class Node {
  constructor(id) { this.id = id; this.style = { display: '' }; this.className = ''; }
}
const nodes = {};
for (const id of __IDS__) nodes[id] = new Node(id);
export const document = {
  getElementById: (id) => nodes[id] || null,
  querySelectorAll: (sel) => {
    // Every UI_VIS_MAP selector resolves to the ids it names, which is what a
    // user with DEFAULT Appearance prefs sees: everything visible.
    const out = [];
    for (const id of Object.keys(nodes)) if (sel.includes(id)) out.push(nodes[id]);
    return out;
  },
  body: { classList: { toggle: () => {} } },
};
export function state() {
  return Object.fromEntries(Object.keys(nodes).map(id => [id, nodes[id].style.display]));
}
export { nodes };
"""


def test_applyUIVis_re_hides_what_the_admin_turned_off():
    """The measured bug, replayed. Nine hidden by the features fetch, then
    `applyUIVis` shows seven of them again — in the same callback, one line
    later. Both halves are deliberate (the `applyUIVis` call was added to fix
    "deep research only shows after I toggle"), so the fix is PRECEDENCE, not
    ordering: the admin's decision is re-applied last, every time.
    """
    src = APP_JS.read_text(encoding="utf-8")

    # The record-then-rehide pair must both exist, and the re-hide must be the
    # LAST thing the preference pass does.
    assert "__pantheonFeatureHiddenIds" in src
    body_start = src.index("function applyUIVis(state) {")
    body = src[body_start:src.index("\n  }", body_start)]
    assert "_reapplyFeatureHiding()" in body, \
        "applyUIVis does not re-hide admin-disabled elements"
    pref_pass = body.index("resolveVisibility(state)")
    rehide = body.index("_reapplyFeatureHiding()")
    assert rehide > pref_pass, \
        "the admin's hide is applied BEFORE the user's preferences and is undone by them"


def _extract(src: str, start_marker: str, end_marker: str) -> str:
    a = src.index(start_marker)
    b = src.index(end_marker, a)
    return src[a:b]


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_the_admins_hide_survives_the_users_preferences(tmp_path):
    """The measured bug, executed rather than read.

    An earlier version of this asserted that `_reapplyFeatureHiding()` is CALLED
    and that the call comes after the preference pass — and gutting the function
    to `function _reapplyFeatureHiding() {}` passed both. Presence is not
    behaviour, for the fourth time in this project.

    The functions are extracted from the real `static/app.js` at test time, not
    reimplemented here, so a change to the source changes what runs below.
    `app.js` cannot be imported standalone — it wires the whole application —
    which is why this is an extraction and not a plain import.
    """
    src = APP_JS.read_text(encoding="utf-8")
    hiding = _extract(src, "  const _featureHiddenIds = new Set();",
                      "  window.__pantheonFeatureHiddenIds")
    apply_vis = _extract(src, "  function applyUIVis(state) {", "\n  // Rearrange toggles")

    ids = ["rail-research", "tool-gallery-btn", "rail-documents", "web-toggle-btn"]
    harness = f"""
const nodes = {{}};
for (const id of {json.dumps(ids)}) nodes[id] = {{ id, style: {{ display: '' }} }};
const el = (id) => nodes[id] || null;
globalThis.document = {{
  getElementById: el,
  // Every UI_VIS_MAP selector resolves visible for a user with default
  // Appearance preferences — which is precisely the condition under which the
  // original bug showed seven of nine hidden elements again.
  querySelectorAll: (sel) => Object.values(nodes).filter(n => sel.includes(n.id)),
  body: {{ classList: {{ toggle: () => {{}} }} }},
}};
const resolveVisibility = () => Object.fromEntries(
  {json.dumps(ids)}.map(id => ['#' + id, true]));
const applyTextEmojis = () => {{}};

{hiding}

{apply_vis}

// The admin turned two features off; the features fetch records and hides them.
for (const id of ['rail-research', 'tool-gallery-btn']) {{
  _featureHiddenIds.add(id);
  nodes[id].style.display = 'none';
}}
const afterHide = Object.fromEntries(Object.entries(nodes).map(([k, v]) => [k, v.style.display]));

// …and then the user's Appearance preferences are applied, in the same
// callback, one line later. This is the exact sequence that produced the bug.
applyUIVis({{}});
const afterPrefs = Object.fromEntries(Object.entries(nodes).map(([k, v]) => [k, v.style.display]));

console.log(JSON.stringify({{ afterHide, afterPrefs }}));
"""
    entry = tmp_path / "case.mjs"
    entry.write_text(harness, encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    assert out["afterHide"]["rail-research"] == "none"
    assert out["afterHide"]["tool-gallery-btn"] == "none"
    # The whole row, in two assertions.
    assert out["afterPrefs"]["rail-research"] == "none", \
        "the user's Appearance preferences un-hid a feature the admin turned off"
    assert out["afterPrefs"]["tool-gallery-btn"] == "none"
    # …and the preferences still work for everything the admin left alone.
    assert out["afterPrefs"]["rail-documents"] == ""
    assert out["afterPrefs"]["web-toggle-btn"] == ""


def test_the_features_fetch_records_the_ids_it_hides():
    """Hiding once is what the old code did, and `applyUIVis` writes `display`
    for 31 selectors on its next pass. The ids have to be remembered, not just
    acted on."""
    src = APP_JS.read_text(encoding="utf-8")
    block_start = src.index("const _prefetchedFeatures")
    block = src[block_start:block_start + 3000]
    assert "__pantheonFeatureHiddenIds" in block
    assert ".add(id)" in block


def test_every_feature_the_ui_hides_is_also_gated_somewhere_real():
    """The row's whole finding: hiding a button was never the problem, it was
    that hiding a button was ALL there was. Every flag the frontend acts on must
    also be enforced by the agent gate or the HTTP gate."""
    src = APP_JS.read_text(encoding="utf-8")
    block = src[src.index("const map = {"):]
    block = block[:block.index("};")]
    ui_flags = set(re.findall(r"^\s*([a-z_]+):", block, re.M))
    assert ui_flags, "could not read the UI's feature map"

    from src.tool_security import _FEATURE_TOOLS
    gated_server_side = set()
    for path in ("routes/research/research_routes.py", "routes/gallery/gallery_routes.py",
                 "routes/memory/memory_routes.py", "routes/document/document_routes.py"):
        text = (ROOT / path).read_text(encoding="utf-8")
        gated_server_side |= set(re.findall(r'require_feature\(\s*"([a-z_]+)"', text))

    for flag in ui_flags:
        assert _FEATURE_TOOLS.get(flag) or flag in gated_server_side, \
            f"{flag} is hidden in the UI and enforced nowhere else"
