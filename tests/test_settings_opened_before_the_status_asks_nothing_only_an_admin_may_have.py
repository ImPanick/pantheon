# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1525` — Settings opened before the sign-in status arrives asks for nothing
only an admin may have.

The remainder of `B1192`. `admin.js` `_initData` returned only when the table's
state said `isAdmin === false`, and before `/api/auth/status` has answered that
state is `null` — so Settings opened in that window ran every admin loader
(users, endpoints, tools, webhooks, `/api/personal`, features, logs, …), each a
403 for a guest. Now `_initData` asks `ui_visibility.viewerMayAdminister`, which
waits for the status the page has said it asked for.

Driven under node in the admin sandbox `tests/test_the_admin_panels_that_never_
rendered.py` builds (its shim, stubs and runner, imported rather than copied),
with the real `ui_visibility.js` beside the real `admin.js`: the page notes it
asked for the status, Settings opens, and every request is recorded before and
after the status answers.
"""
import json
import shutil

import pytest

from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from test_the_workshop_surfaces_js import _index_ids  # noqa: E402
from test_the_admin_panels_that_never_rendered import (  # noqa: E402
    ADMIN_JS, _ADMIN_SHIM, _ADMIN_STUBS, _PREAMBLE, _store, _wh_event_values,
)

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

_ADMIN_ONLY = ("/api/auth/users", "/api/personal", "/api/webhooks", "/api/auth/features",
               "/api/tools", "/api/endpoints", "/api/logs")


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    shim = (_ADMIN_SHIM
            .replace("__IDS__", json.dumps(_index_ids()))
            .replace("__WH_EVENTS__", json.dumps(_wh_event_values())))
    return _make_sandbox(tmp_path_factory.mktemp("b1525"), ADMIN_JS, shim, _ADMIN_STUBS)


def _open_early(sandbox, status):
    """The page has asked for the status; Settings opens; then `status` answers."""
    return _run(sandbox, _PREAMBLE + "import * as V from './ui_visibility.js';\n", _store() + """
        V.applyToolVisibility({ features: {} }, null);   // features answer first, as on the page
        V.noteStatusAsked();
        const pending = adminModule._initData();
        const again = adminModule._initData();           // a second open while it waits
        await tick();
        const before = calls.fetch.map((c) => c.url);
        V.applyToolVisibility(%s, null);
        await pending;
        await again;
        await tick();
        console.log(JSON.stringify({ before, after: calls.fetch.map((c) => c.url),
                                     same: pending === again, initialized: adminModule._initialized }));
    """ % json.dumps(status))


def test_a_guest_who_opens_settings_early_is_asked_nothing(sandbox):
    """The row's `Verify:`: no request the server would answer 403."""
    out = _open_early(sandbox, {"isAdmin": False, "auth": True})
    assert out["before"] == [], f"loaders ran before the status said who this is: {out['before']}"
    assert out["after"] == [], f"a guest was asked for admin lists: {out['after']}"
    assert out["initialized"] is False


def test_an_admin_who_opens_settings_early_gets_the_lists_once_the_status_says_so(sandbox):
    """The other half: waiting must not hide an admin's own panels."""
    out = _open_early(sandbox, {"isAdmin": True, "auth": True})
    assert out["before"] == [], out["before"]
    asked = out["after"]
    for path in ("/api/auth/users", "/api/personal", "/api/webhooks", "/api/auth/features"):
        assert any(u.endswith(path) or (path + "?") in u for u in asked), (path, asked)
    assert out["same"] is True, "a second open while waiting started a second set of loaders"
    assert asked.count("/api/webhooks") == 1, asked
    assert out["initialized"] is True


def test_a_status_that_never_answers_does_not_hide_an_admins_lists(sandbox):
    """Unknown asks (`SET-M-8`'s rule): with no status asked for, nothing waits."""
    out = _run(sandbox, _PREAMBLE + "import * as V from './ui_visibility.js';\n", _store() + """
        await adminModule._initData();
        await tick();
        console.log(JSON.stringify({ asked: calls.fetch.map((c) => c.url) }));
    """)
    assert any(u.endswith("/api/webhooks") for u in out["asked"]), out
