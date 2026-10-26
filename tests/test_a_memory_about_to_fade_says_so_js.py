# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B821` — a memory about to go quiet says so on its card, before it does.

`P13-04` puts an `archive` forecast on every row of `GET /api/memory`
(`{verdict, reason, days}`, computed on read) and the tidy sweeps what has run
out, and nothing drew the forecast: *"nothing is ever silently dropped"* was
the row's own sentence, and an archive nobody was warned about is silent
however reversible. Of the row's three asks the archived filter and the restore
control landed with `B710` (`brainFilter.js`, `memoryFacts.js`'s *retired*
chip, *Bring back* posting to `/commit`); the warning line was still missing —
measured on `ffaf6671`, no reader of `archive` anywhere under `static/js`.

Now the forecast carries `soon` (`ARCHIVE_WARN_DAYS`, on the server, so the
page holds no window of its own — every dated memory `fades` on a 180-day
clock, and a line on every card would be read by nobody), and the card draws
`memoryFadeLine`: *"Fades in 12 days — nothing has used or restated it for 168
days. Pin it to keep it."* A pinned memory is held, which is the way to keep it.

`Verify:` a cold reader sees which memories are about to go quiet, and brings
one back.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.memory import ARCHIVE_AFTER_DAYS, ARCHIVE_WARN_DAYS, archive_forecast
from test_the_brain_says_it_is_loading import _LOADING_STUBS, _PREAMBLE  # noqa: E402
from test_the_workshop_surfaces_js import _SHIM, _index_ids, MEMORY_JS  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FACTS_JS = ROOT / "static" / "js" / "memoryFacts.js"
NOW = 2_000_000_000.0
node = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _quiet(days, **extra):
    stamp = NOW - days * 86400
    return {"id": "m", "text": "x", "timestamp": stamp, "last_mentioned": stamp,
            "status": "committed", **extra}


# ── the server says which ones ──────────────────────────────────────────────

def test_soon_is_the_last_stretch_of_the_window_and_due():
    near = archive_forecast(_quiet(ARCHIVE_AFTER_DAYS - 12), NOW)
    far = archive_forecast(_quiet(10), NOW)
    due = archive_forecast(_quiet(ARCHIVE_AFTER_DAYS + 1), NOW)
    pinned = archive_forecast(_quiet(ARCHIVE_AFTER_DAYS - 2, pinned=True), NOW)
    assert (near["verdict"], near["days"], near["soon"]) == ("fades", 12, True)
    assert (far["verdict"], far["soon"]) == ("fades", False)
    assert (due["verdict"], due["soon"]) == ("due", True)
    assert (pinned["verdict"], pinned["soon"]) == ("held", False)
    edge = archive_forecast(_quiet(ARCHIVE_AFTER_DAYS - ARCHIVE_WARN_DAYS), NOW)
    assert edge["days"] == ARCHIVE_WARN_DAYS and edge["soon"] is True


# ── the page draws it ───────────────────────────────────────────────────────

@node
def test_the_line_is_the_servers_reason_and_days(tmp_path):
    entry = tmp_path / "case.mjs"
    entry.write_text("""
        const { memoryFadeLine } = await import(%s);
        const reason = 'nothing has used or restated it for 168 days';
        console.log(JSON.stringify({
          fades: memoryFadeLine({ archive: { verdict: 'fades', days: 12, reason, soon: true } }),
          one: memoryFadeLine({ archive: { verdict: 'fades', days: 1, reason, soon: true } }),
          due: memoryFadeLine({ archive: { verdict: 'due', days: 0, reason, soon: true } }),
          far: memoryFadeLine({ archive: { verdict: 'fades', days: 170, reason, soon: false } }),
          held: memoryFadeLine({ archive: { verdict: 'held', days: null, reason: 'pinned by you', soon: false } }),
          none: memoryFadeLine({}),
        }));
    """ % json.dumps(FACTS_JS.as_uri()), encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["fades"] == ("Fades in 12 days — nothing has used or restated it for 168 days."
                            " Pin it to keep it.")
    assert out["one"].startswith("Fades in 1 day —")
    assert out["due"].startswith("Fades the next time the Brain is tidied —")
    assert out["far"] == out["held"] == out["none"] == ""


@pytest.fixture(scope="module")
def brain(tmp_path_factory):
    shim = _SHIM.replace("__IDS__", json.dumps(_index_ids()))
    return _make_sandbox(tmp_path_factory.mktemp("fadeline"), MEMORY_JS, shim, _LOADING_STUBS)


@node
def test_the_card_of_a_fading_memory_carries_the_line_and_the_rest_do_not(brain):
    out = _run(brain, _PREAMBLE, """
        const reason = 'nothing has used or restated it for 168 days';
        const rows = [
          { ...ROWS[0], archive: { verdict: 'fades', days: 12, reason, soon: true } },
          { ...ROWS[1], archive: { verdict: 'fades', days: 160, reason: 'nothing has used or restated it for 20 days', soon: false } },
        ];
        mockFetch((url) => (/\\/api\\/memory$/.test(url) ? res(200, { memory: rows, style: STYLE }) : res(200, {})));
        ready(); await tick();
        await openBrain();
        const cards = byId('memory-list').querySelectorAll('.memory-item').map((el) => ({
          text: el.querySelector('.memory-item-text').textContent,
          fades: (el.querySelector('.memory-item-fades') || { textContent: '' }).textContent,
        }));
        console.log(JSON.stringify({ cards }));
    """)
    by = {c["text"]: c["fades"] for c in out["cards"]}
    assert by["Rowan prefers tea to coffee"].startswith("Fades in 12 days — nothing has used")
    assert by["The launch is on the 14th"] == ""
