# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P2-19` / `P2-20` — three admin panels that were written, shipped, and never
drawn.

The webhook panel, the RAG index panel and the feature toggles are complete in
`static/js/admin.js` and have complete backends. None of them had a single
element in `static/index.html`, and — the half the roadmap's original story
missed — none of them was in the module's own `inits` or `refreshAll` list
either. **Markup alone leaves all three inert**, which is why these tests drive
`_initData()` rather than asserting that ids exist: a panel whose markup is
present and whose loader is never called looks finished in a diff and shows an
empty box to a person.

Driven under node in the sandbox pattern `tests/test_the_workshop_surfaces_js.py`
owns, with the shim, stubs, sandbox builder and runner imported from it rather
than copied (`Law 14`). The ids come out of the shipped page, and so do the
webhook event values — a rename in the markup fails these rather than passing
against a private copy.

**What is driven and what is read.** `initWebhookForm` and `initRag` build
their behaviour out of real elements, so the click paths are exercised end to
end. The three *lists* are template strings assigned to `innerHTML`, which the
shim stores without parsing; those are asserted against **that node's own
html**, which is `Law 20` option 2 — the scope is resolved first and the
assertion made inside it — and never against the file.
"""
import json
import re
import shutil
from pathlib import Path

import pytest

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_the_workshop_surfaces_js import _SHIM, _STUBS, _index_ids  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ADMIN_JS = ROOT / "static" / "js" / "admin.js"
INDEX = ROOT / "static" / "index.html"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _wh_event_values() -> list:
    """The `value` of every `.adm-wh-event` control in the shipped page.

    Read rather than retyped, for the reason `_index_ids` gives: this is the
    one class `initWebhookForm` queries, and a form with no checkboxes in scope
    reports "Select at least one event" and can never submit.
    """
    html = INDEX.read_text(encoding="utf-8")
    return re.findall(
        r'<input[^>]*class="[^"]*\badm-wh-event\b[^"]*"[^>]*value="([^"]+)"', html
    ) + re.findall(
        r'<input[^>]*value="([^"]+)"[^>]*class="[^"]*\badm-wh-event\b[^"]*"', html
    )


_ADMIN_SHIM = _SHIM + r"""
/** The admin form posts multipart bodies, and the shim's globals do not carry
 *  `FormData`. Minimal, and it records its own fields so a test can read what
 *  the form actually sent rather than that it sent something. */
globalThis.FormData = class {
  constructor() { this._d = []; }
  append(k, v) { this._d.push([k, String(v)]); }
  get(k) { const e = this._d.find((x) => x[0] === k); return e ? e[1] : null; }
};

/** The webhook event checkboxes, lifted from the shipped page and parented to
 *  `#settings-modal` — the scope `initWebhookForm` queries. If the markup does
 *  not declare them this list is empty and the form cannot submit, which is
 *  exactly the failure the panel had. */
const WH_EVENTS = __WH_EVENTS__;
export const whEvents = WH_EVENTS.map((v) => {
  const n = new Node('input');
  n.type = 'checkbox';
  n.className = 'adm-wh-event';
  n.value = v;
  n.checked = false;
  (document.getElementById('settings-modal') || document.body).appendChild(n);
  return n;
});

export const forms = [];
export function mockAdminFetch(handler) {
  mockFetch((url, opts) => {
    if (opts && opts.body && opts.body._d) {
      forms.push({ url: String(url), fields: Object.fromEntries(opts.body._d) });
    }
    return handler(String(url), opts || {});
  });
}
export function html(id) { const n = document.getElementById(id); return n ? n.innerHTML : null; }
"""

_ADMIN_STUBS = dict(_STUBS)
_ADMIN_STUBS.update({
    "settings.js": "export default { open(){}, close(){}, initIntegrations(){} };\n",
    "providers.js": "export function providerLogo(){ return ''; }\n"
                    "export function providerLogoFromUrl(){ return ''; }\n",
    "modelSort.js": "export function sortModelObjects(a){ return a; }\n",
    "providerDeviceFlow.js": "export const PROVIDER_DEVICE_FLOWS = {};\n"
                             "export function formatDeviceFlowError(){ return ''; }\n"
                             "export async function runProviderDeviceFlow(){ return {}; }\n",
    "appConfig.js": "export async function getSettings(){ return {}; }\n"
                    "export async function getTools(){ return {}; }\n"
                    "export function invalidateSettings(){}\n"
                    "export function invalidateTools(){}\n",
})

_PREAMBLE = (
    "import { document, calls, mockFetch, mockAdminFetch, forms, whEvents, res,"
    " fire, ready, byId, setValue, tick, readable, html } from './shim.js';\n"
    "import uiStub, { calls as uiCalls } from './ui.js';\n"
    "const adminModule = (await import('./admin.js')).default;\n"
)


@pytest.fixture(scope="module")
def admin_sandbox(tmp_path_factory):
    shim = (_ADMIN_SHIM
            .replace("__IDS__", json.dumps(_index_ids()))
            .replace("__WH_EVENTS__", json.dumps(_wh_event_values())))
    return _make_sandbox(
        tmp_path_factory.mktemp("adminpanels"), ADMIN_JS, shim, _ADMIN_STUBS
    )


def _admin(sandbox, script):
    return _run(sandbox, _PREAMBLE, script)


_HOOKS = [
    {"id": 1, "name": "deploy bot", "url": "https://hooks.example.com/a",
     "events": ["chat.completed"], "is_active": True, "has_secret": True,
     "last_status_code": 200, "last_triggered_at": None, "last_error": None},
    {"id": 2, "name": "pager", "url": "https://hooks.example.com/b",
     "events": ["session.created"], "is_active": False, "has_secret": False,
     "last_status_code": 500, "last_triggered_at": None,
     "last_error": "connection refused"},
]

_PERSONAL = {
    "directories": ["/srv/handbook"],
    "files": [{"name": "onboarding.md", "path": "/data/onboarding.md", "size": 2048}],
}

_FEATURES = {"web_search": True, "deep_research": False, "memory": True,
             "document_editor": True, "rag": False, "sensitive_filter": True,
             "gallery": True}


def _store(hooks=None, personal=None, features=None):
    return """
    mockAdminFetch((url) => {
      if (url.includes('/api/webhooks')) return res(200, %s);
      if (url.includes('/api/auth/features')) return res(200, %s);
      if (url.includes('/api/personal/add_directory'))
        return res(200, { success: true, indexed_count: 12 });
      if (url.includes('/api/personal/reload')) return res(200, { count: 34 });
      if (url.includes('/api/personal')) return res(200, %s);
      if (url.includes('/api/auth/users')) return res(200, { users: [] });
      return res(200, {});
    });
    """ % (
        json.dumps(_HOOKS if hooks is None else hooks),
        json.dumps(_FEATURES if features is None else features),
        json.dumps(_PERSONAL if personal is None else personal),
    )


# ── P2-19 · webhooks ────────────────────────────────────────────────────────

def test_the_webhook_list_is_fetched_on_a_cold_open(admin_sandbox):
    """The row's `Verify:` line, driven. `loadWebhooks` was absent from
    `refreshAll`, so opening the admin panel fetched users, endpoints, tools,
    MCP servers, tokens and logs — and never the webhooks."""
    out = _admin(admin_sandbox, _store() + """
        adminModule._initData();
        await tick();
        console.log(JSON.stringify({ fetched: calls.fetch.map(c => c.url) }));
    """)
    assert "/api/webhooks" in out["fetched"], out["fetched"]


def test_every_configured_webhook_reaches_the_panel(admin_sandbox):
    """Name, destination, event and delivery status — the four things an
    operator opens this panel to see. Asserted inside `#adm-whList`'s own
    html rather than anywhere in the file."""
    out = _admin(admin_sandbox, _store() + """
        adminModule._initData();
        await tick();
        console.log(JSON.stringify({ list: html('adm-whList') }));
    """)
    body = out["list"]
    assert body is not None, "no #adm-whList in the shipped markup"
    for fragment in ("deploy bot", "https://hooks.example.com/a", "chat.completed",
                     "pager", "connection refused", "500"):
        assert fragment in body, fragment
    assert "disabled" in body, "an inactive webhook must say so"
    assert "signed" in body, "a webhook with a secret must say so"


def test_an_empty_webhook_list_says_so(admin_sandbox):
    out = _admin(admin_sandbox, _store(hooks=[]) + """
        adminModule._initData();
        await tick();
        console.log(JSON.stringify({ list: html('adm-whList') }));
    """)
    assert "No webhooks configured" in out["list"]


def test_the_add_form_posts_the_four_fields_the_route_takes(admin_sandbox):
    """`POST /api/webhooks` takes name, url, secret and a comma-joined event
    list as form fields. The events come from `.adm-wh-event:checked`, which
    is the one part of this panel that is a class rather than an id — and the
    part most likely to be left out of the markup."""
    out = _admin(admin_sandbox, _store() + """
        adminModule._initData();
        await tick();
        setValue('adm-whName', 'deploy bot');
        setValue('adm-whUrl', 'https://hooks.example.com/a');
        setValue('adm-whSecret', 's3cret');
        whEvents.filter(e => e.value !== 'webhook.test').forEach(e => { e.checked = true; });
        forms.length = 0;
        fire(byId('adm-whAddBtn'), 'click');
        await tick();
        console.log(JSON.stringify({ forms, msg: byId('adm-whMsg').textContent }));
    """)
    posted = [f for f in out["forms"] if f["url"].endswith("/api/webhooks")]
    assert posted, out
    fields = posted[0]["fields"]
    assert fields["name"] == "deploy bot"
    assert fields["url"] == "https://hooks.example.com/a"
    assert fields["secret"] == "s3cret"
    assert set(fields["events"].split(",")) == {
        "session.created", "chat.completed", "chat.message"}


def test_the_page_offers_exactly_the_events_the_server_allows(admin_sandbox):
    """A checkbox for an event the validator rejects is a form that fails on
    submit with a server error; a missing one is a capability nobody can
    reach. Read from `ALLOWED_EVENTS` rather than restated."""
    from src.webhook_manager import ALLOWED_EVENTS
    offered = set(_wh_event_values())
    assert offered == set(ALLOWED_EVENTS) - {"webhook.test"}, offered


def test_submitting_with_no_event_checked_explains_itself_and_posts_nothing(admin_sandbox):
    """The server requires at least one. Finding that out from a 400 is the
    `Law 15` failure; the form says it before spending the request."""
    out = _admin(admin_sandbox, _store() + """
        adminModule._initData();
        await tick();
        setValue('adm-whName', 'deploy bot');
        setValue('adm-whUrl', 'https://hooks.example.com/a');
        whEvents.forEach(e => { e.checked = false; });
        forms.length = 0;
        fire(byId('adm-whAddBtn'), 'click');
        await tick();
        console.log(JSON.stringify({ forms, msg: byId('adm-whMsg').textContent }));
    """)
    assert out["forms"] == []
    assert "at least one event" in out["msg"].lower()


def test_the_panel_says_a_private_address_will_be_refused(admin_sandbox):
    """`validate_webhook_url` rejects every RFC1918 and loopback destination,
    and that validator is a `FORBIDDEN.md` Part 2 control — so the panel's job
    is to say so before someone types their own LAN address and gets a bare
    "Failed". `Law 15`: the surface answers the question rather than the
    operator having to run the experiment."""
    html = INDEX.read_text(encoding="utf-8")
    start = html.index('id="adm-whList"')
    card = html[max(0, start - 4000):start + 4000]
    assert re.search(r"private|loopback|local", card, re.I), (
        "the webhook card must name the kind of address that will not work"
    )
    assert re.search(r"refus|reject|not work|won't work", card, re.I), (
        "naming private addresses is not the same as saying they are refused"
    )


# ── P2-20 · the RAG index panel and the feature toggles ─────────────────────

def test_the_rag_panel_and_the_feature_toggles_load_on_a_cold_open(admin_sandbox):
    """`loadRag` and `loadFeatures` were in neither `inits` nor `refreshAll`,
    and `initRag` and `loadFeatures` had zero callers tree-wide."""
    out = _admin(admin_sandbox, _store() + """
        adminModule._initData();
        await tick();
        console.log(JSON.stringify({ fetched: calls.fetch.map(c => c.url) }));
    """)
    assert "/api/personal" in out["fetched"], out["fetched"]
    assert "/api/auth/features" in out["fetched"], out["fetched"]


def test_the_indexed_directories_and_files_both_render(admin_sandbox):
    out = _admin(admin_sandbox, _store() + """
        adminModule._initData();
        await tick();
        console.log(JSON.stringify({
          dirs: html('adm-ragDirList'), files: html('adm-ragFileList'),
        }));
    """)
    assert "/srv/handbook" in out["dirs"]
    assert "onboarding.md" in out["files"]
    assert "2.0 KB" in out["files"]


def test_adding_a_directory_posts_it_and_clears_the_field(admin_sandbox):
    """The three routes this panel is the only door to — add, remove and
    reload — are all `require_admin`, and `POST /api/personal/reload` has no
    other caller in the tree at all."""
    out = _admin(admin_sandbox, _store() + """
        adminModule._initData();
        await tick();
        setValue('adm-ragDirInput', '/srv/manuals');
        calls.fetch.length = 0;
        fire(byId('adm-ragAddDirBtn'), 'click');
        await tick();
        const afterAdd = byId('adm-ragStatus').textContent;
        fire(byId('adm-ragReloadBtn'), 'click');
        await tick();
        console.log(JSON.stringify({
          posts: calls.fetch.filter(c => c.method === 'POST').map(c => c.url),
          left: byId('adm-ragDirInput').value,
          afterAdd,
          afterReload: byId('adm-ragStatus').textContent,
        }));
    """)
    assert any(u.endswith("/api/personal/add_directory") for u in out["posts"]), out
    assert any(u.endswith("/api/personal/reload") for u in out["posts"]), out
    assert out["left"] == ""
    # The operator has to be told what the click did. Indexing a directory is
    # the slowest thing on this panel and the only sign it worked is this line.
    assert "12" in out["afterAdd"], out["afterAdd"]
    assert "34" in out["afterReload"], out["afterReload"]


def test_every_feature_the_module_names_gets_a_switch(admin_sandbox):
    """`featureLabels` is the module's own list. A label without a row is a
    feature an operator cannot turn on, and the backend takes all seven."""
    out = _admin(admin_sandbox, _store() + """
        adminModule._initData();
        await tick();
        console.log(JSON.stringify({ toggles: html('adm-featureToggles') }));
    """)
    body = out["toggles"]
    assert body is not None, "no #adm-featureToggles in the shipped markup"
    for key, label in (("web_search", "Web Search"), ("deep_research", "Deep Research"),
                       ("memory", "Memory"), ("document_editor", "Document Editor"),
                       ("rag", "RAG Knowledge Base"),
                       ("sensitive_filter", "Sensitive Info Filter"),
                       ("gallery", "Gallery")):
        assert f'data-adm-feature="{key}"' in body, key
        assert label in body, label
    # The stored state has to reach the checkbox, or every toggle reads "off"
    # and the first click turns something off that was already on.
    assert body.count("checked") == sum(1 for v in _FEATURES.values() if v)
