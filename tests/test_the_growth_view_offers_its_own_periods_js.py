# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2159`. `skillGrowth.GROWTH_PERIODS` — *the periods the view offers* — was
exported and read by nothing: the select in `index.html` listed its own three
and `skills.js` sent the server whatever the select held. The loader now asks
for a period the view offers and falls back to the first, and the select's
options are held equal to the constant here, so the two lists cannot drift."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GROWTH = ROOT / "static" / "js" / "skillGrowth.js"


def _periods():
    out = subprocess.run(
        ["node", "--input-type=module", "-e",
         f"const m = await import('{GROWTH.as_posix()}'); console.log(JSON.stringify(m.GROWTH_PERIODS));"],
        capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_select_offers_exactly_the_views_periods():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    select = re.search(r'<select id="skills-growth-days"[^>]*>(.*?)</select>', html, re.S).group(1)
    offered = [int(v) for v in re.findall(r'<option value="(\d+)"', select)]
    assert offered == _periods()


def test_the_loader_asks_for_an_offered_period():
    src = (ROOT / "static" / "js" / "skills.js").read_text(encoding="utf-8")
    assert re.search(r"import \{[^}]*\bGROWTH_PERIODS\b[^}]*\} from './skillGrowth\.js';", src)
    start = src.index("async function _loadGrowth(m)")
    body = src[start:src.index("\n}\n", start)]
    assert "GROWTH_PERIODS.includes(asked) ? asked : GROWTH_PERIODS[0]" in body
    assert "fetchGrowth(days)" in body
