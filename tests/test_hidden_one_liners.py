"""Three findings from the discovery audit, each a few lines and none cosmetic
(`H14`, `H15`, `H17`).

What they have in common is that every one is a control the product already
built, described to the user in a sentence that was not true:

  * `H14` — a GPU process viewer with per-PID SIGKILL, whose tooltip named a
    gesture that does not open it;
  * `H15` — a Settings search that indexed 13 panel labels and none of the 96
    controls, so the app's only privacy control was unfindable by any word in
    its own label;
  * `H17` — an admin toggle wired to the endpoint whose own docstring calls it
    unsafe and deprecated, and a webhook secret you could copy but not rotate.
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
SERVE_JS = ROOT / "static" / "js" / "cookbookServe.js"
REGISTRY = ROOT / "static" / "js" / "settings" / "registry.js"
SEARCH_JS = ROOT / "static" / "js" / "settings" / "search.js"
ADMIN_JS = ROOT / "static" / "js" / "admin.js"
TASKS_JS = ROOT / "static" / "js" / "tasks.js"
INDEX = ROOT / "static" / "index.html"

pytestmark = pytest.mark.skipif(not shutil.which("node"),
                                reason="node binary not on PATH")


def _code(path: Path) -> str:
    """Source with comments removed, so a sentence explaining a defect is not
    read as the defect being fixed — or as still present."""
    src = path.read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("//"))


# ── H14: the tooltip named a gesture that does not open the killer ──────────

def test_the_tooltip_names_a_gesture_that_actually_opens_it():
    code = _code(SERVE_JS)
    tip = re.search(r"process\(es\) — ([^`]*)`", code)
    assert tip, "the process-count tooltip is gone"
    text = tip.group(1).lower()
    assert "right-click" in text or "double-click" in text
    assert not re.search(r"(?<!right-)(?<!double-)\bclick to view", text), \
        "the tooltip still says plain click opens it"


def test_the_killer_is_still_NOT_on_a_plain_click():
    """The tooltip moved, not the gesture, and that is the safe direction: this
    popup carries per-PID SIGTERM and SIGKILL, and plain click currently means
    *select this GPU*. Binding a kill UI to it would put the most destructive
    control in the panel one accidental click away."""
    code = _code(SERVE_JS)
    handlers = set(re.findall(r"btn\.addEventListener\('(\w+)'", code))
    assert {"contextmenu", "dblclick"} <= handlers
    block = code[code.index("cookbook-gpu-btn'").__index__():][:1200]
    assert "addEventListener('click'" not in block


# ── H15: settings search indexed 13 labels and zero of 96 controls ──────────

def _run_registry(script: str, tmp_path) -> dict:
    """Exercise the real registry module under node against a DOM stub."""
    shutil.copy2(REGISTRY, tmp_path / "registry.js")
    entry = tmp_path / "case.mjs"
    entry.write_text(
        "import { searchSettingsPanels, harvestSettingsControlText, "
        "getSettingsPanelSearchText } from './registry.js';\n"
        + textwrap.dedent(script), encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], cwd=tmp_path,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _modal_stub(panels: dict) -> str:
    """A `[data-settings-panel]` container per id, holding label elements."""
    return f"""
const PANELS = {json.dumps(panels)};
const modal = {{
  querySelectorAll(sel) {{
    if (sel.includes('data-settings-panel')) {{
      return Object.entries(PANELS).map(([id, labels]) => ({{
        dataset: {{ settingsPanel: id }},
        querySelectorAll: () => labels.map(t => ({{
          textContent: t,
          getAttribute: () => null,
        }})),
      }}));
    }}
    return [];
  }},
}};
"""


def test_a_control_is_findable_by_a_word_in_its_own_label(tmp_path):
    """The row's `Verify` line. 31 of the 32 labelled toggles in Appearance were
    unfindable by any word in their own label — including *Incognito Mode*,
    *Deep Research*, *Shell* and *Web Search*."""
    out = _run_registry(_modal_stub({
        "appearance": ["Incognito Mode", "Sensitive Blur Blur emails, tokens, and secrets in AI output"],
        "ai": ["Deep Research"],
    }) + """
        const controlText = harvestSettingsControlText(modal);
        const hits = {};
        for (const q of ['incognito', 'sensitive blur', 'deep research', 'secrets']) {
          hits[q] = searchSettingsPanels(q, { isAdmin: true, controlText }).map(p => p.id);
        }
        console.log(JSON.stringify(hits));
    """, tmp_path)
    assert out["incognito"] == ["appearance"]
    assert out["sensitive blur"] == ["appearance"]
    assert out["deep research"] == ["ai"]
    assert out["secrets"] == ["appearance"]


def test_without_the_harvest_the_control_labels_are_still_unfindable(tmp_path):
    """The state the row found, asserted so the fix is not credited to
    something else that happened to change.

    Deliberately NOT "sensitive blur": the keyword list gained `blur` and
    `sensitive` in the same change, so that phrase now resolves through
    keywords whether or not the harvest works, and using it here would let the
    harvest be deleted with this test still green. `incognito` and
    `deep research` appear in no keyword list — only in the controls' own
    labels, which is the thing being indexed.
    """
    out = _run_registry("""
        const hits = {};
        for (const q of ['incognito', 'deep research']) {
          hits[q] = searchSettingsPanels(q, { isAdmin: true }).map(p => p.id);
        }
        console.log(JSON.stringify(hits));
    """, tmp_path)
    assert out["incognito"] == []
    assert out["deep research"] == []


def test_the_privacy_words_reach_the_panel_that_holds_the_privacy_control(tmp_path):
    """The sharpest case in the row. *Sensitive Blur* is the app's only privacy
    control, ships OFF, and lives under Appearance because there is no Privacy
    or Security panel among the thirteen. Harvesting makes it findable by its
    own label; it cannot make it findable by *privacy* or *security*, because
    neither word is anywhere in the markup — and those are what someone about to
    share their screen actually types."""
    out = _run_registry("""
        const hits = {};
        for (const q of ['privacy', 'security', 'redact', 'blur']) {
          hits[q] = searchSettingsPanels(q, { isAdmin: true }).map(p => p.id);
        }
        console.log(JSON.stringify(hits));
    """, tmp_path)
    for q in ("privacy", "security", "redact", "blur"):
        assert "appearance" in out[q], f"searching {q!r} finds nothing"


def test_the_harvest_reads_the_real_markups_panel_ids():
    """`data-settings-panel="<id>"` is the link between the registry and the
    markup. Harvesting by any other key would index nothing and pass every test
    above that uses a stub."""
    markup_ids = set(re.findall(r'data-settings-panel="([a-z0-9_-]+)"',
                                INDEX.read_text(encoding="utf-8")))
    assert markup_ids, "the markup has no panel containers"
    code = _code(REGISTRY)
    assert "data-settings-panel" in code
    assert "settingsPanel" in code, "the dataset key the browser exposes is not read"


def test_the_search_ui_actually_passes_the_harvest(tmp_path):
    """`Law 15` again: a harvester nobody calls indexes nothing. Parsed with
    comments stripped, because the note beside the call explains the whole row
    and names both functions."""
    code = _code(SEARCH_JS)
    assert "harvestSettingsControlText" in code, "search.js never harvests"
    assert re.search(r"controlText\s*:", code), \
        "the harvest is computed and not passed to the search"


# ── H17: two security controls with the wrong door ──────────────────────────

def test_the_admin_toggle_uses_the_idempotent_endpoint():
    """The deprecated one's own docstring: *"this endpoint uses toggle semantics
    which can lead to unsafe state changes."* Two admins clicking, or one
    double-submit, flips open registration back ON while both switches read
    OFF."""
    code = _code(ADMIN_JS)
    assert "signup-toggle" not in code, "still calling the deprecated toggle endpoint"
    assert "open-signup" in code
    call = code[code.index("open-signup") - 200:code.index("open-signup") + 400]
    assert "'PUT'" in call or '"PUT"' in call
    assert "enabled" in call, "the desired state is not sent"


def test_the_deprecated_endpoint_still_exists_for_anything_else_calling_it():
    """Removing it is a different decision from not calling it. Something
    outside this repository may hold that URL."""
    routes = (ROOT / "routes" / "auth_routes.py").read_text(encoding="utf-8")
    assert '@router.post("/signup-toggle", deprecated=True)' in routes
    assert '@router.put("/open-signup")' in routes


def test_the_switch_reverts_when_the_server_refuses(tmp_path):
    """A refused request must not leave the UI claiming a change that did not
    happen — which on this control means an admin believing open registration is
    off when it is on."""
    code = _code(ADMIN_JS)
    block = code[code.index("open-signup") - 400:code.index("open-signup") + 900]
    assert "!res.ok" in block, "an error response is not distinguished from a success"
    assert re.search(r"toggle\.checked\s*=\s*!desired", block), \
        "the switch does not revert on failure"


def test_the_webhook_token_can_be_rotated():
    """`POST /api/tasks/{id}/webhook-regenerate` existed and had no caller
    anywhere. The URL carries its own bearer token in the path and the UI said
    "No auth needed" — accurate, and exactly why the missing control mattered:
    if it leaked there was no revocation path in the product at all."""
    code = _code(TASKS_JS)
    assert "webhook-regenerate" in code, "there is still no way to rotate the token"
    assert "task-form-webhook-rotate" in code
    block = code[code.index("webhook-regenerate") - 900:code.index("webhook-regenerate") + 700]

    # Not `"confirm(" in block`: `const ok = true || window.confirm(...)` keeps
    # the word and skips the question, and that mutation survived the first
    # version of this. Three things have to hold — the confirm is the WHOLE
    # right-hand side, the answer is checked, and the check comes before the
    # request.
    assign = re.search(r"const\s+ok\s*=\s*(.*?);", block, re.S)
    assert assign, "the rotation does not ask"
    assert assign.group(1).lstrip().startswith(("window.confirm(", "confirm(")), \
        f"the confirm is short-circuited: {assign.group(1)[:60]!r}"
    guard = block.index("if (!ok) return;")
    request = block.index("fetch(")
    assert guard < request, "the request is made before the answer is read"


def test_the_copy_label_no_longer_undersells_the_secret():
    """"No auth needed" is true of the receiver and reads as *this is not a
    secret*. Anyone holding the URL can run the task."""
    code = _code(TASKS_JS)
    assert "No auth needed" not in code
    assert "rotate if it leaks" in code.lower()


def test_a_failed_rotation_says_the_old_url_still_works():
    """The one sentence that matters after a failed rotation: whether the thing
    you were trying to revoke is still live."""
    code = _code(TASKS_JS)
    assert code.count("old URL still works") >= 2, \
        "a failed rotation does not say whether the token was replaced"
