# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1188` — a Deep Research report re-loaded from the Library says why it
found nothing.

`P23-02` (`BRAIN-M-6`) saves `stopped` (`no_queries` / `no_results` /
`no_search_provider`) with the result, and `result-peek` serves it, so a run
finished in this page says why. Measured on `03f50081`: a card drawn from
`GET /api/research/library` after a reload (`static/js/research/jobs.js`'s
`_fromLibrary` rows) had no `stopped` — the route did not list it and the job
was built without it — so the card fell back to "Nothing was found.".

Driven (`Law 20`):

  * the real `ResearchHandler._save_result` persists a run that stopped with no
    search provider, and the real `/api/research/library` handler lists it;
  * the real `jobs.js` is imported under node, `refreshLibrary` reads that row
    (as the page does after a reload), and the panel's own `_FAIL_NOTE` table,
    cut out of `panel.js`, words the card's note from the job it built.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.helpers.js_source import js_binding

ROOT = Path(__file__).resolve().parents[1]
JOBS_JS = ROOT / "static" / "js" / "research" / "jobs.js"
PANEL_JS = ROOT / "static" / "js" / "research" / "panel.js"


@pytest.fixture
def research_dir(tmp_path, monkeypatch):
    d = tmp_path / "deep_research"
    d.mkdir()
    monkeypatch.setattr("src.research_handler.RESEARCH_DATA_DIR", d)
    monkeypatch.setattr("routes.research.research_routes.DEEP_RESEARCH_DIR", str(d))
    return d


def _library_rows(user: str = "alice") -> list[dict]:
    from unittest.mock import MagicMock

    from routes.research.research_routes import setup_research_routes
    handler = MagicMock()
    handler._active_tasks = {}
    router = setup_research_routes(handler)
    endpoint = next(r.endpoint for r in router.routes
                    if getattr(r, "path", "") == "/api/research/library" and "GET" in r.methods)
    out = asyncio.run(endpoint(request=SimpleNamespace(state=SimpleNamespace(current_user=user)),
                               search=None, sort="recent", limit=50, archived=False))
    return out["research"]


def _save(session_id: str, stopped: str) -> None:
    from src.research_handler import ResearchHandler
    handler = ResearchHandler()
    researcher = SimpleNamespace(findings=[], stopped=stopped)
    handler._save_result(session_id, {
        "query": "ferry times to the island", "status": "done", "result": "",
        "researcher": researcher, "stats": {"Duration": "12s", "Rounds": 1},
        "category": "", "started_at": 1_700_000_000, "owner": "alice",
    })


def test_the_library_lists_why_a_saved_run_stopped(research_dir):
    _save("res-noprovider", "no_search_provider")
    _save("res-noqueries", "no_queries")
    # A report saved before `BRAIN-M-6` carries no reason at all.
    (research_dir / "res-legacy.json").write_text(json.dumps({
        "query": "old", "status": "done", "owner": "alice", "sources": []}), encoding="utf-8")
    rows = {r["id"]: r for r in _library_rows()}
    assert rows["res-noprovider"]["stopped"] == "no_search_provider"
    assert rows["res-noqueries"]["stopped"] == "no_queries"
    assert rows["res-legacy"]["stopped"] == ""


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_a_card_drawn_from_the_library_after_a_reload_says_why(research_dir, tmp_path):
    """`Verify:` a run that stopped with no search provider still says so after
    a reload."""
    _save("res-noprovider", "no_search_provider")
    rows = _library_rows()
    box = tmp_path / "box"
    (box / "research").mkdir(parents=True)
    shutil.copy(JOBS_JS, box / "research" / "jobs.js")
    (box / "modalManager.js").write_text("export function setBackgroundWork() {}\n")
    table = js_binding(PANEL_JS.read_text(encoding="utf-8"), "_FAIL_NOTE")
    entry = box / "case.mjs"
    entry.write_text(textwrap.dedent(f"""
        const store = {{}};
        globalThis.localStorage = {{ getItem: (k) => store[k] ?? null, setItem: (k, v) => {{ store[k] = String(v); }} }};
        globalThis.document = {{ visibilityState: 'visible', addEventListener() {{}} }};
        globalThis.window = globalThis;
        const rows = {json.dumps(rows)};
        globalThis.fetch = async (url) => ({{ ok: true, status: 200,
          json: async () => (String(url).includes('/api/research/library') ? {{ research: rows, total: rows.length }} : {{}}) }});
        const jobs = await import('./research/jobs.js');
        await jobs.refreshLibrary({{ force: true }});
        const job = jobs.getJobs().find((j) => j.id === 'res-noprovider');
        {table}
        // What the card's fail note says (`panel.js`, the `failNote` line).
        const note = _FAIL_NOTE[job.stopped] || _FAIL_NOTE[''];
        // A second sync over a job already in the list keeps the reason.
        await jobs.refreshLibrary({{ force: true }});
        console.log(JSON.stringify({{ fromLibrary: job._fromLibrary, stopped: job.stopped, note,
          again: jobs.getJobs().find((j) => j.id === 'res-noprovider').stopped }}));
    """), encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], cwd=box, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out == {"fromLibrary": True, "stopped": "no_search_provider",
                   "note": "No search engine is set up — Settings → Search.",
                   "again": "no_search_provider"}
