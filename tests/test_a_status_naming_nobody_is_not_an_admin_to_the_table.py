# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1543`: a `/api/auth/status` that names nobody gives the table `isAdmin: false`.

`app.js` handed the visibility table `isAdmin: d.authenticated ? !!d.is_admin :
null`, commented *(auth off): unknown is on* — so with no auth-off install left
(`D-2026-10-07-02` §2), a lapsed session's page read as *unknown*, showed the
admin-only doors, and went on asking for admin lists to 401s.

Driven: `app.js`'s own status block (from `noteStatusAsked()` to its `.catch`)
is cut out and run under node against the real `static/js/ui_visibility.js`,
with a `fetch` that answers the status; then the table is asked.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UI_VIS = ROOT / "static" / "js" / "ui_visibility.js"
APP_JS = ROOT / "static" / "app.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _status_block() -> str:
    src = APP_JS.read_text(encoding="utf-8")
    start = src.index("  noteStatusAsked();")
    end_marker = ".catch(() => { noteStatusFailed(); });"
    end = src.index(end_marker, start) + len(end_marker)
    block = src[start:end]
    # `B1228`: the block reads the status through `appConfig.getAuthStatus`,
    # the one request `init.js` shares, instead of its own `fetch`.
    assert "getAuthStatus()" in block, "the cut is not the status block"
    return block


def _run(tmp_path: Path, status: dict) -> dict:
    entry = tmp_path / "case.mjs"
    entry.write_text(
        "const nodes = {};\n"
        "for (const id of ['tool-cookbook-btn', 'rail-cookbook']) nodes[id] = { id, style: { display: '' } };\n"
        "globalThis.document = { getElementById: (id) => nodes[id] || null };\n"
        "globalThis.window = { addEventListener() {} };\n"
        f"const V = await import({json.dumps(UI_VIS.as_uri())});\n"
        "const { applyToolVisibility, noteStatusAsked, noteStatusFailed, statusVisibility, toolShown } = V;\n"
        "const API_BASE = '';\n"
        "const el = () => null;\n"
        "const asked = [];\n"
        f"const getAuthStatus = async () => {{ asked.push('/api/auth/status'); return ({json.dumps(status)}); }};\n"
        + _status_block() + "\n"
        "await new Promise((r) => setTimeout(r, 20));\n"
        "console.log(JSON.stringify({ asked, isAdmin: V.toolVisibilityState().isAdmin,\n"
        "  forge: toolShown('forge'), door: nodes['tool-cookbook-btn'].style.display,\n"
        "  viewerIsAdmin: V.viewerIsAdmin() }));\n",
        encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_status_with_authenticated_false_gives_the_table_is_admin_false(tmp_path):
    out = _run(tmp_path, {"authenticated": False, "signup_enabled": False})
    assert out["asked"] == ["/api/auth/status"]
    assert out["isAdmin"] is False, "a status naming nobody is not auth-off's unknown"
    assert out["forge"] is False and out["door"] == "none"
    assert out["viewerIsAdmin"] is False


def test_a_signed_in_admin_and_non_admin_read_as_the_status_says(tmp_path):
    admin = _run(tmp_path, {"authenticated": True, "username": "ada", "is_admin": True})
    assert admin["isAdmin"] is True and admin["forge"] is True
    person = _run(tmp_path, {"authenticated": True, "username": "bob", "is_admin": False})
    assert person["isAdmin"] is False and person["forge"] is False


def test_unknown_still_means_not_answered_yet(tmp_path):
    """`null` keeps its one meaning: the status has not answered."""
    entry = tmp_path / "unknown.mjs"
    entry.write_text(
        "globalThis.window = { addEventListener() {} };\n"
        f"const V = await import({json.dumps(UI_VIS.as_uri())});\n"
        "console.log(JSON.stringify({ isAdmin: V.toolVisibilityState().isAdmin,\n"
        "  forge: V.toolShown('forge') }));\n", encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip()) == {"isAdmin": None, "forge": True}
