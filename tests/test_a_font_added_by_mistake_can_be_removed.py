# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B937` — a font added by mistake is removed from the theme panel, by an admin.

`P2-24` added fonts and listed them; nothing took one out short of deleting its
file from `DATA_DIR/fonts` on the server, and the panel did not say which fonts
were uploaded and which were dropped into `static/fonts/custom/` by hand.

`DELETE /api/fonts/custom/{filename}` answers the upload's adversaries with the
upload's controls (`Law 17`): an admin only, because a font is every browser's;
the stored-name pattern, so only a file the upload could have written is named;
and the containment check. A hand-dropped font is the operator's file and stays.
The listing now says each variant's `source` (`upload` or `server`), and the
panel lists the families under "Add a font": an uploaded one with **Remove**,
which asks first, a hand-dropped one with where it lives.

Driven, not grepped (`Law 20`): the route through the real router and the real
`require_admin` (the `P2-24` harness, imported); the panel's functions cut out
of the shipped `theme.js` and run under node against the route's own answers.
"""

import json
import shutil
import subprocess

import pytest

from tests.helpers.js_source import js_definition
from test_a_font_can_be_added_from_the_theme_panel import (  # noqa: F401,E402
    INTER, THEME_JS, TTF, _add, _listing, env)


def _remove(client, name, user="admin"):
    return client.delete(f"/api/fonts/custom/{name}", headers={"x-test-user": user})


# ── the route ──────────────────────────────────────────────────────────────

def test_an_admin_removes_an_uploaded_font_and_it_is_gone_everywhere(env):
    assert _add(env, "Inter-Regular.woff2", INTER).status_code == 200
    assert _add(env, "PantheonTest-Regular.ttf", TTF).status_code == 200
    res = _remove(env, "Inter-Regular.woff2")
    assert res.status_code == 200, res.text
    assert res.json() == {"ok": True, "file": "Inter-Regular.woff2", "family": "Inter"}
    assert not (env.uploads / "Inter-Regular.woff2").exists()
    assert "Inter" not in _listing(env)["fonts"], "the Font menu still offers it"
    assert env.get("/api/fonts/custom/Inter-Regular.woff2",
                   headers={"x-test-user": "admin"}).status_code == 404
    assert (env.uploads / "PantheonTest-Regular.ttf").exists(), "only that one went"


def test_only_an_admin_can_remove_a_font(env):
    assert _add(env, "Inter-Regular.woff2", INTER).status_code == 200
    assert _remove(env, "Inter-Regular.woff2", user="bob").status_code == 403
    assert (env.uploads / "Inter-Regular.woff2").exists()


@pytest.mark.parametrize("name", [
    "..%2Fsettings.json", "..%2F..%2Fstatic%2Fcustom.css", "notes.html", ".part",
    "a" * 81 + ".woff2", "missing.woff2", "Inter Regular.woff2",
])
def test_a_name_the_upload_could_not_have_stored_is_not_found(env, name):
    (env.uploads).mkdir(parents=True, exist_ok=True)
    (env.uploads / "notes.html").write_text("keep")
    (env.tmp / "data" / "settings.json").write_text("{}")
    assert _remove(env, name).status_code == 404
    assert (env.uploads / "notes.html").read_text() == "keep"
    assert (env.tmp / "data" / "settings.json").read_text() == "{}"


def test_a_hand_dropped_font_is_the_server_s_and_stays(env):
    (env.legacy / "JetBrainsMono-Regular.woff2").write_bytes(INTER)
    assert _remove(env, "JetBrainsMono-Regular.woff2").status_code == 404
    assert (env.legacy / "JetBrainsMono-Regular.woff2").exists()


def test_the_listing_says_where_each_font_came_from(env):
    (env.legacy / "JetBrainsMono-Regular.woff2").write_bytes(INTER)
    assert _add(env, "PantheonTest-Regular.ttf", TTF).status_code == 200
    fonts = _listing(env)["fonts"]
    assert [v["source"] for v in fonts["JetBrains Mono"]] == ["server"]
    assert [v["source"] for v in fonts["Pantheon Test"]] == ["upload"]


# ── the panel ──────────────────────────────────────────────────────────────

_SHIM = r"""
let _customFonts = {};
const _injectedFonts = new Set(['Inter']);
const DEFAULT_FONT = 'mono';
const changes = [], deletes = [], confirms = [];
class El {
  constructor(tag, id) { Object.assign(this, { tagName: tag.toUpperCase(), id: id || '', children: [],
    dataset: {}, attrs: {}, listeners: {}, value: '', accept: '', textContent: '', hidden: false,
    className: '', type: '', title: '' }); }
  get options() { return this.children; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  replaceChildren() { this.children = []; }
  remove() { const p = this.parentNode; if (p) p.children = p.children.filter((x) => x !== this); }
  querySelectorAll(sel) { return sel === 'option[data-custom-font]' ? this.children.filter((o) => o.dataset.customFont) : []; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  dispatchEvent(e) { if (e.type === 'change') changes.push(this.value); (this.listeners[e.type] || []).forEach((f) => f(e)); }
  click() { this.dispatchEvent({ type: 'click' }); }
}
const els = {};
for (const id of ['theme-font-select', 'theme-font-upload-input', 'theme-font-upload-status', 'theme-font-list']) els[id] = new El('div', id);
els['theme-font-select'].value = '__START__';
const styles = [new El('style'), new El('style')];
styles[0].dataset.customFont = 'Inter'; styles[1].dataset.customFont = 'Other';
const document = {
  getElementById: (id) => els[id] || null,
  createElement: (tag) => new El(tag),
  querySelectorAll: (sel) => sel === 'style[data-custom-font]' ? styles.filter((s) => !s.removed) : [],
};
styles.forEach((s) => { s.remove = () => { s.removed = true; }; });
class Event { constructor(type) { this.type = type; } }
const console = { warn() {}, log() {}, error() {} };
const ANSWER = __ANSWER__;
const uiModule = { styledConfirm: async (msg, opts) => { confirms.push([msg, opts]); return ANSWER.confirm; } };
let listing = ANSWER.before;
const fetch = async (url, opts) => {
  if (opts && opts.method === 'DELETE') {
    deletes.push(url);
    const r = ANSWER.deleted;
    if (r.status < 400) listing = ANSWER.after;
    return { ok: r.status < 400, status: r.status, json: async () => r.body };
  }
  return { ok: true, status: 200, json: async () => listing };
};
const rows = () => els['theme-font-list'].children.map((li) => ({
  name: li.children[0].textContent,
  action: li.children[1].textContent,
  label: li.children[1].attrs['aria-label'] || null,
  title: li.children[1].title || null,
}));
"""


def _panel(script: str, answer: dict) -> dict:
    src = THEME_JS.read_text(encoding="utf-8")
    fns = "\n".join(
        js_definition(src, src.index(sig)).replace("export ", "", 1)
        for sig in ("export function loadCustomFonts(", "function _renderFontList(",
                    "export async function removeCustomFont("))
    code = _SHIM.replace("__ANSWER__", json.dumps(answer)) + fns + "\n(async () => {\n" + script + "\n})();\n"
    proc = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _listings(env):
    (env.legacy / "JetBrainsMono-Regular.woff2").write_bytes(INTER)
    assert _add(env, "Inter-Regular.woff2", INTER).status_code == 200
    return _listing(env)


needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node not on PATH")


@needs_node
def test_the_panel_lists_each_font_with_what_can_be_done_with_it(env):
    before = _listings(env)
    out = _panel("""
        await loadCustomFonts(els['theme-font-select'], 'mono');
        process.stdout.write(JSON.stringify({ rows: rows(), hidden: els['theme-font-list'].hidden }));
    """, {"before": before, "after": before, "confirm": False, "deleted": {"status": 200, "body": {}}})
    assert out["hidden"] is False
    assert out["rows"] == [
        {"name": "Inter", "action": "Remove", "label": "Remove Inter", "title": None},
        {"name": "JetBrains Mono", "action": "On the server", "label": None,
         "title": "In static/fonts/custom/ on the server. Delete the file there to remove it."},
    ]


@needs_node
def test_remove_asks_first_and_a_no_removes_nothing(env):
    before = _listings(env)
    out = _panel("""
        await loadCustomFonts(els['theme-font-select'], 'Inter');
        const got = await removeCustomFont('Inter', ANSWER.before.fonts['Inter']);
        process.stdout.write(JSON.stringify({ got, deletes, confirms, changes }));
    """, {"before": before, "after": before, "confirm": False, "deleted": {"status": 200, "body": {}}})
    assert out["got"] is None and out["deletes"] == [] and out["changes"] == []
    [(msg, opts)] = out["confirms"]
    assert "Inter" in msg and "everyone" in msg
    assert opts["danger"] is True and opts["confirmText"] == "Remove"


@needs_node
def test_a_yes_removes_it_and_the_font_in_use_falls_back_to_the_default(env):
    """Answered by the real route: the DELETE's own response and the listing
    after it."""
    before = _listings(env)
    deleted = _remove(env, "Inter-Regular.woff2")
    after = _listing(env)
    out = _panel("""
        await loadCustomFonts(els['theme-font-select'], 'Inter');
        const got = await removeCustomFont('Inter', ANSWER.before.fonts['Inter']);
        process.stdout.write(JSON.stringify({ got, deletes, changes, value: els['theme-font-select'].value,
          options: els['theme-font-select'].options.map((o) => o.value), rows: rows(),
          status: els['theme-font-upload-status'].textContent, injected: [..._injectedFonts],
          styles: styles.filter((s) => !s.removed).map((s) => s.dataset.customFont) }));
    """, {"before": before, "after": after, "confirm": True,
          "deleted": {"status": deleted.status_code, "body": deleted.json()}})
    assert out["got"] == "Inter"
    assert out["deletes"] == ["/api/fonts/custom/Inter-Regular.woff2"]
    assert out["options"] == ["JetBrains Mono"]
    assert out["value"] == "mono" and out["changes"] == ["mono"], (
        "the font in use went; the menu's own change handler applies and saves the default")
    assert out["status"] == "Removed Inter."
    assert out["injected"] == [] and out["styles"] == ["Other"], "its @font-face is dropped too"
    assert [r["name"] for r in out["rows"]] == ["JetBrains Mono"]


@needs_node
def test_removing_a_font_not_in_use_leaves_the_choice_alone(env):
    before = _listings(env)
    deleted = _remove(env, "Inter-Regular.woff2")
    after = _listing(env)
    out = _panel("""
        await loadCustomFonts(els['theme-font-select'], 'JetBrains Mono');
        await removeCustomFont('Inter', ANSWER.before.fonts['Inter']);
        process.stdout.write(JSON.stringify({ changes, value: els['theme-font-select'].value }));
    """, {"before": before, "after": after, "confirm": True,
          "deleted": {"status": deleted.status_code, "body": deleted.json()}})
    assert out == {"changes": [], "value": "JetBrains Mono"}


@needs_node
def test_a_refusal_says_why_and_changes_nothing(env):
    before = _listings(env)
    refused = _remove(env, "Inter-Regular.woff2", user="bob")
    out = _panel("""
        await loadCustomFonts(els['theme-font-select'], 'Inter');
        const got = await removeCustomFont('Inter', ANSWER.before.fonts['Inter']);
        process.stdout.write(JSON.stringify({ got, changes, value: els['theme-font-select'].value,
          status: els['theme-font-upload-status'].textContent }));
    """, {"before": before, "after": before, "confirm": True,
          "deleted": {"status": refused.status_code, "body": refused.json()}})
    assert out == {"got": None, "changes": [], "value": "Inter",
                   "status": "Only an admin can remove fonts."}
