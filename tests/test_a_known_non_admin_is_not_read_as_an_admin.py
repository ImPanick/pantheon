# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1523` — `viewerIsAdmin()` answered yes for a viewer the server called a
non-admin.

With the table's state unset (`/api/auth/status` answered but named nobody, so
`app.js` hands the applier `isAdmin: null`), the fallback returned
`window._isAdmin !== undefined` — and `app.js` sets `window._isAdmin =
!!d.is_admin`, so a status that said `false` read as an admin. That was
auth-off mode's rule (its one operator was let in by `require_admin`); there is
no auth-off install since `D-2026-10-07-02` §2, and `require_admin` refuses a
caller with no session.

Driven: the real `static/js/ui_visibility.js` is imported under node, once per
case, with `window._isAdmin` set as `app.js` sets it.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UI_VIS = ROOT / "static" / "js" / "ui_visibility.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _viewer_is_admin(tmp_path: Path, said, state=None) -> bool:
    entry = tmp_path / "case.mjs"
    lines = [f"globalThis.window = {{ addEventListener() {{}} }};"]
    if said is not None:
        lines.append(f"window._isAdmin = {json.dumps(said)};")
    lines.append(f"const V = await import({json.dumps(UI_VIS.as_uri())});")
    if state is not None:
        lines.append(f"V.applyToolVisibility({json.dumps(state)}, null);")
    lines.append("console.log(JSON.stringify(V.viewerIsAdmin()));")
    entry.write_text("\n".join(lines) + "\n", encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_status_that_said_false_is_not_an_admin(tmp_path):
    """The row's `Verify:`: state unset, `window._isAdmin = false` → false."""
    assert _viewer_is_admin(tmp_path, False) is False


def test_a_status_that_said_true_is_an_admin(tmp_path):
    assert _viewer_is_admin(tmp_path, True) is True


def test_no_status_yet_is_not_shown_the_admin_panels(tmp_path):
    assert _viewer_is_admin(tmp_path, None) is False


def test_the_tables_answer_outranks_the_page_global(tmp_path):
    """A signed-in person's status reaches the table; that answer is the one."""
    assert _viewer_is_admin(tmp_path, True, {"isAdmin": False, "auth": True}) is False
    assert _viewer_is_admin(tmp_path, False, {"isAdmin": True, "auth": True}) is True
