# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P13-07` — the Brain's reading surface: readable, not navigable-by-dragging.

The row says it twice and `P3-19` is moot because of it: **no canvas, no force
layout.** What a person wants from a memory graph is not to look at it, it is
to answer a question — *what does this thing remember about one project, and
how do I fix the bit that is wrong* — and that is a reading task. So the
surface is a list, six filters, a search box and a detail pane.

Its `Verify` is the hardest kind to test and the easiest to fake, so it is
taken apart into the things it actually asserts:

  * *"a dedicated surface, **not on the main path and not on open**"* — the
    panel has **no tab**. The Brain's four tabs are untouched, nothing reaches
    it by accident, and one small card at the foot of the memories list is the
    only door.
  * *"lists and filters: by project, confidence, category, age, session, and
    edge type"* — six, each driven here.
  * *"open a memory, see what it supersedes and what contradicts it, correct
    it, retire it"* — and the other side of an edge is shown as **its own
    words**, because an id is not a thing anyone can read.
  * *"search that finds a thing in one query rather than a thing you spot in a
    cloud"* — including by project name, because a reader typing a project's
    name means the project.
  * *"state plainly how fresh the analysis is"* — two facts, not one: when the
    page read the store, and how old the newest thing in it is. Either alone
    misleads.

**Retire is not delete.** `MemoryManager.archive` had existed since `P13-04`
and nothing could ask for it: the audit's forecast called it, and a person who
wanted a memory to stop surfacing had only `DELETE`. That is the unwired half
again, and the distinction is the point — a memory that was true last year is
not a memory that was never true.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FILTER = ROOT / "static" / "js" / "brainFilter.js"
SURFACE = ROOT / "static" / "js" / "brainExplore.js"
MEMJS = ROOT / "static" / "js" / "memory.js"
INDEX = ROOT / "static" / "index.html"
STYLE = ROOT / "static" / "style.css"
ROUTES = ROOT / "routes" / "memory" / "memory_routes.py"

sys.path.insert(0, str(ROOT))
from tests.helpers.source_text import blank, blank_text  # noqa: E402  (`B290`)

NOW = 1_000_000
DAY = 86400
CORPUS = [
    {"id": "1", "text": "Elevation is a shadow everywhere, never ink at low alpha",
     "project": "pantheon", "project_label": "Pantheon", "category": "fact",
     "confidence": 0.92, "timestamp": NOW - 3600, "session_id": "s1",
     "edges": [{"type": "supersedes", "target": "3"}]},
    {"id": "2", "text": "Prefers tea in the afternoon", "category": "preference",
     "confidence": None, "timestamp": NOW - 40 * DAY, "session_id": "s2", "edges": []},
    {"id": "3", "text": "Elevation is one hard-coded rgba per surface",
     "project": "odysseus", "project_label": "Odysseus", "category": "fact",
     "confidence": 0.55, "timestamp": NOW - 200 * DAY, "session_id": "s1",
     "edges": [{"type": "contradicts", "target": "1", "note": "measured 2026-10-17"}]},
    {"id": "4", "text": "No date on this one", "category": "fact",
     "confidence": 0.65, "edges": []},
]


def _node(script: str):
    run = subprocess.run(["node", "--input-type=module"], input=textwrap.dedent(script),
                         capture_output=True, text=True, cwd=str(ROOT), timeout=90)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout.strip().splitlines()[-1])


def _filter(**overrides) -> list:
    """The ids that survive a filter, through the real module."""
    return _node("""
    import { apply, emptyFilter } from '%s';
    const rows = %s;
    const kept = apply(rows, { ...emptyFilter(), ...%s }, %d);
    console.log(JSON.stringify(kept.rows.map((r) => r.id)));
    """ % (FILTER.as_posix(), json.dumps(CORPUS), json.dumps(overrides), NOW))


# ── The filters, each one driven ───────────────────────────────────────────

def test_the_surface_opens_full_not_empty():
    """The starting filter returns the whole corpus. A page that opens empty
    makes a reader guess which control to touch first (`Law 15`)."""
    assert _filter() == ["1", "2", "3", "4"]


@pytest.mark.parametrize("given", ["{}", "undefined", "null", '{ project: "any" }'])
def test_a_partial_filter_means_nothing_narrowed(given):
    """`matches` fills its own defaults, and this is the case that proves it.

    The first draft only asserted through `_filter()`, which spreads
    `emptyFilter()` on the **test's** side — so deleting the function's own
    default-spread changed nothing and the mutation survived. A test that
    supplies the thing it is checking for is not checking it.

    The contract worth having is that an absent clause is a pass: a caller
    holding a half-built filter gets the whole corpus, not an empty page."""
    got = _node("""
    import { apply } from '%s';
    const kept = apply(%s, %s, %d);
    console.log(JSON.stringify(kept.rows.map((r) => r.id)));
    """ % (FILTER.as_posix(), json.dumps(CORPUS), given, NOW))
    assert got == ["1", "2", "3", "4"], (
        f"a filter of {given} hid {4 - len(got)} of 4 memories")


@pytest.mark.parametrize("overrides,expected", [
    ({"project": "pantheon"}, ["1"]),
    ({"project": "odysseus"}, ["3"]),
    ({"project": "none"}, ["2", "4"]),
    ({"confidence": "high"}, ["1"]),
    ({"confidence": "medium"}, ["3", "4"]),
    ({"confidence": "unrecorded"}, ["2"]),
    ({"category": "preference"}, ["2"]),
    ({"category": "fact"}, ["1", "3", "4"]),
    ({"age": "week"}, ["1"]),
    ({"age": "quarter"}, ["1", "2"]),
    ({"session": "s1"}, ["1", "3"]),
    ({"session": "s2"}, ["2"]),
    ({"edge": "contradicts"}, ["3"]),
    ({"edge": "supersedes"}, ["1"]),
    ({"edge": "none"}, ["2", "4"]),
])
def test_all_six_filters_narrow_the_list(overrides, expected):
    assert _filter(**overrides) == expected


def test_the_filters_combine_rather_than_replace():
    assert _filter(project="pantheon", age="week") == ["1"]
    assert _filter(project="pantheon", age="any", confidence="unrecorded") == []


def test_not_recorded_is_its_own_band_and_not_low():
    """"Nobody assessed this" is a thing a reader goes looking for, and folding
    it into `low` would say the extractor was unsure when it was never asked
    (`P13-01`)."""
    assert _filter(confidence="unrecorded") == ["2"]
    assert "2" not in _filter(confidence="low")


def test_an_undated_memory_fails_an_age_filter_rather_than_passing_it():
    """An unknown age is not "recent". Letting it through would put the oldest
    records in the "last week" list."""
    assert "4" not in _filter(age="week")
    assert "4" in _filter(age="any")


def test_search_finds_a_memory_by_its_project_name():
    """*"Search that finds a thing in one query."* A reader typing a project's
    name means the project, and sending them to the dropdown instead is the
    thing-you-spot-in-a-cloud this row replaces."""
    assert _filter(query="Pantheon") == ["1"]
    assert _filter(query="odysseus") == ["3"]
    assert _filter(query="tea") == ["2"]
    assert _filter(query="elevation") == ["1", "3"]


def test_clear_is_offered_only_when_something_is_narrowed():
    got = _node("""
    import { emptyFilter, isNarrowed } from '%s';
    console.log(JSON.stringify([
      isNarrowed(emptyFilter()),
      isNarrowed({ ...emptyFilter(), query: 'x' }),
      isNarrowed({ ...emptyFilter(), project: 'pantheon' }),
      isNarrowed({ ...emptyFilter(), query: '   ' }),
    ]));
    """ % FILTER.as_posix())
    assert got == [False, True, True, False], (
        "whitespace in the search box counts as narrowed, so Clear appears "
        "for nothing")


# ── Freshness ──────────────────────────────────────────────────────────────

def test_the_freshness_line_states_both_facts():
    """*"State plainly how fresh the analysis is."* When the page read, AND how
    old the newest memory is. A page saying only the first claims freshness it
    cannot vouch for; one saying only the second cannot tell a reader their
    view is stale."""
    sentence = _node("""
    import { freshnessSentence } from '%s';
    console.log(JSON.stringify(freshnessSentence(%s, { readAt: %d, projects: 2 })));
    """ % (SURFACE.as_posix(), json.dumps(CORPUS), NOW))
    assert "4 memories" in sentence
    assert "2 projects" in sentence
    assert "newest" in sentence, "the sentence does not say how old the newest memory is"
    assert re.search(r"(ago|just now)", sentence), "the sentence carries no time at all"


def test_an_empty_brain_says_so_rather_than_claiming_freshness():
    sentence = _node("""
    import { freshnessSentence } from '%s';
    console.log(JSON.stringify(freshnessSentence([], { readAt: %d, projects: 0 })));
    """ % (SURFACE.as_posix(), NOW))
    assert "nothing stored" in sentence.lower()


def test_a_corpus_with_no_projects_does_not_claim_any():
    sentence = _node("""
    import { freshnessSentence } from '%s';
    console.log(JSON.stringify(freshnessSentence(%s, { readAt: %d, projects: 0 })));
    """ % (SURFACE.as_posix(), json.dumps(CORPUS), NOW))
    assert "none filed under a project" in sentence


# ── Not on the main path ───────────────────────────────────────────────────

def test_the_panel_has_no_tab():
    """*"Not on the main path and not on open."* The Brain's tab strip is
    untouched, so nothing reaches this surface by accident."""
    html = blank(INDEX)
    assert 'data-memory-panel="explore"' in html, "the panel is gone"
    assert 'data-memory-tab="explore"' not in html, (
        "the explore surface grew a tab, which puts it on the main path")
    tabs = re.findall(r'data-memory-tab="([a-z]+)"', html)
    assert tabs == ["browse", "rag", "add", "settings"], (
        f"the tab strip changed: {tabs}")


def test_the_panel_starts_hidden():
    html = blank(INDEX)
    panel = re.search(r'<div class="([^"]*)"[^>]*id="memory-panel-explore"', html)
    assert panel, "the explore panel's markup moved"
    assert "hidden" in panel.group(1), "the explore panel is visible on open"


def test_one_card_is_the_only_door():
    html = blank(INDEX)
    assert html.count('id="brain-explore-open"') == 1, "the door is not unique"
    js = blank(MEMJS)
    assert "brain-explore-open" in js, "nothing wires the card"
    assert "import('./brainExplore.js')" in js, (
        "the surface is imported at module scope; a surface that is "
        "deliberately not-on-open should not cost anything to boot, and a "
        "static import here is the memory.js <-> brainExplore.js cycle")


def test_there_is_no_canvas_and_no_force_layout():
    """The row's own instruction, twice. `P3-19` is moot because of it."""
    source = blank(SURFACE) + blank(FILTER)
    for banned in ("canvas", "getContext", "requestAnimationFrame",
                   "forceSimulation", "d3.", "cytoscape"):
        assert banned not in source, f"the surface reaches for {banned!r}"
    html = blank(INDEX)
    explore = html[html.index('id="memory-panel-explore"'):]
    assert "<canvas" not in explore[:400]


# ── The filter core is runnable without a browser ──────────────────────────

def test_the_filter_rule_imports_nothing():
    """`B61`'s lesson as an arrangement: a helper can be perfect and the page
    still show nothing, so the part a test can execute is kept apart from the
    part that needs a DOM. An import here would make that impossible."""
    source = blank(FILTER)
    assert re.findall(r"^\s*import\s+.*$", source, re.M) == []
    assert "document." not in source and "window." not in source


def test_the_surface_reuses_the_confidence_pill_rather_than_formatting_again():
    source = blank(SURFACE)
    assert "memoryConfidencePill" in source, (
        "the surface formats confidence itself instead of using the one "
        "builder (`Law 7`)")
    assert "%`" not in source.replace("${percent}%`", ""), (
        "the surface builds a percent string of its own")


def test_the_surface_reuses_the_one_correction_writer():
    """A second place that saves an edit is a second place to forget to reload
    the list or report a refusal (`Law 14`)."""
    source = blank(SURFACE)
    assert "saveInlineEdit" in source
    assert "method: 'PUT'" not in source, (
        "the surface sends its own PUT instead of asking the Brain's writer")


def test_the_scroll_honours_reduced_motion():
    source = blank(SURFACE)
    assert "scrollBehavior()" in source
    assert "'smooth'" not in source, "a hard-coded smooth scroll ignores `P1-15`"


# ── Retire is not delete ───────────────────────────────────────────────────

def test_the_archive_route_exists_and_is_privileged():
    source = ROUTES.read_text(encoding="utf-8")
    assert '@router.post("/{memory_id}/archive")' in source, (
        "`MemoryManager.archive` is unreachable again")
    block = source[source.index('@router.post("/{memory_id}/archive")'):]
    block = block[:block.index("# Wildcard routes MUST come last")]
    assert 'require_privilege(request, "can_manage_memory")' in block, (
        "retiring a memory needs the same privilege as adding one")
    assert "_verify_memory_owner(entry, user)" in block, (
        "one tenant can retire another's memory")
    assert "_load_for_update" in block, (
        "an unreadable store would answer 404 rather than 503")


def test_retiring_says_it_keeps_the_memory():
    """Retire is not delete, and a button that does not say so reads as the
    destructive one beside it."""
    source = blank(SURFACE)
    retire = source[source.index("brain-detail-retire"):]
    assert re.search(r"kept, not deleted", retire), (
        "the retire control never says the memory is kept")
    css = blank(STYLE)
    rule = css[css.index(".brain-detail-retire"):]
    rule = rule[:rule.index("}")]
    assert "--color-error" not in rule and "--red" not in rule, (
        "retire is painted like a destructive action; the destructive colour "
        "belongs to the button that destroys")


# ── Driven in a real browser ───────────────────────────────────────────────

def _browser():
    """The harness `test_elevation_is_one_idiom.py` uses: `executablePath` is
    explicit because this environment's Chromium lives outside Playwright's own
    cache and `chromium.launch()` with no path reports it as not downloaded."""
    node = shutil.which("node")
    if not node:
        return None, None, "node binary not on PATH"
    probe = subprocess.run(
        [node, "-e",
         "const { chromium } = require('playwright');"
         "const fs = require('fs');"
         "const p = chromium.executablePath();"
         "process.stdout.write(fs.existsSync(p) ? p : '');"],
        capture_output=True, text=True, timeout=60)
    if probe.returncode != 0:
        return None, None, "the playwright node package is not installed"
    path = probe.stdout.strip()
    if not path:
        for candidate in ("/opt/pw-browsers/chromium",
                          "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"):
            if Path(candidate).exists():
                path = candidate
                break
    if not path:
        return None, None, "playwright has no Chromium available"
    return node, path, None


NODE, CHROME, _SKIP = _browser()

_DRIVER = """
const { chromium } = require('playwright');
const { readFileSync } = require('fs');
const css = readFileSync('__STYLE__', 'utf8');
const rows = __ROWS__;
const projects = __PROJECTS__;
// The fixture data is interpolated into the PAGE below, not referenced from
// node: these two are node-side bindings, and the first draft of this driver
// used them bare inside the page's module script, so it threw ReferenceError
// and the surface never appeared -- which the harness could only report as a
// 20-second timeout. The second draft explained that in a comment INSIDE the
// page template, whose backticks closed the template literal. Hence: here.
const html = `<!doctype html><html><head><style>${css}</style></head><body>
<div id="memory-modal">
  <div class="memory-tab-panel" data-memory-panel="browse" id="memory-panel-browse"></div>
  <div class="memory-tab-panel hidden" data-memory-panel="explore" id="memory-panel-explore"></div>
</div>
<script>
  window.__rows = ${JSON.stringify(rows)};
  window.__projects = ${JSON.stringify(projects)};
</script>
<script type="module">
  window.memoryModule = { getBrainTab: () => 'browse',
                          saveInlineEdit: async (id, text) => { window.__saved = [id, text]; } };
  const real = window.fetch;
  window.fetch = async (url, opts) => {
    const u = String(url);
    if (u.endsWith('/api/memory')) return new Response(JSON.stringify({memory: window.__rows}), {status:200});
    if (u.endsWith('/api/memory/projects')) return new Response(JSON.stringify({projects: window.__projects}), {status:200});
    if (u.includes('/archive')) { window.__archived = u; return new Response(JSON.stringify({archived:true}), {status:200}); }
    return real(url, opts);
  };
  const m = await import('/static/js/brainExplore.js');
  window.__surface = m;
</script></body></html>`;
(async () => {
  const b = await chromium.launch({ args: ['--no-sandbox'], executablePath: process.argv[2] });
  const p = await b.newPage();
  await p.route('**/static/js/*.js', (route) => {
    const name = route.request().url().split('/').pop();
    route.fulfill({ contentType: 'text/javascript',
                    body: readFileSync('__JSDIR__/' + name, 'utf8') });
  });
  await p.route('**/brain-explore-fixture', (route) =>
    route.fulfill({ contentType: 'text/html', body: html }));
  await p.goto('http://localhost/brain-explore-fixture', { waitUntil: 'load' });
  await p.waitForFunction(() => window.__surface, null, { timeout: 20000 });
  const out = await p.evaluate(async () => {
    const o = {};
    await window.__surface.showExplore(true);
    const panel = document.getElementById('memory-panel-explore');
    o.exploreShown = !panel.classList.contains('hidden');
    o.browseHidden = document.getElementById('memory-panel-browse').classList.contains('hidden');
    o.fresh = document.getElementById('brain-explore-fresh').textContent;
    o.filters = [...document.querySelectorAll('.brain-filter-select')].map((s) => s.id);
    o.rows = document.querySelectorAll('.brain-explore-row').length;
    o.canvases = document.querySelectorAll('canvas').length;

    const proj = document.getElementById('brain-filter-project');
    proj.value = 'pantheon'; proj.dispatchEvent(new Event('change'));
    o.filteredRows = document.querySelectorAll('.brain-explore-row').length;
    o.count = document.querySelector('.brain-explore-count').textContent;
    document.querySelector('.brain-explore-clear').click();
    o.afterClear = document.querySelectorAll('.brain-explore-row').length;

    document.querySelector('.brain-explore-row[data-memory-id="3"]').click();
    o.detail = !!document.getElementById('brain-explore-detail');
    o.edgeTypes = [...document.querySelectorAll('.brain-edge-type')].map((n) => n.textContent);
    o.edgeTexts = [...document.querySelectorAll('.brain-edge-text')].map((n) => n.textContent);
    o.actions = [...document.querySelectorAll('.brain-detail-btn')].map((n) => n.textContent);

    document.querySelector('.brain-detail-btn').click();        // Correct
    o.editorOpen = !!document.querySelector('.brain-detail-edit');
    const area = document.querySelector('.brain-detail-edit');
    area.value = 'Elevation is one ink token per tier';
    document.querySelector('.brain-detail-save').click();
    await new Promise((r) => setTimeout(r, 120));
    o.saved = window.__saved || null;

    await window.__surface.showExplore(false);
    o.exploreHiddenAfterBack = document.getElementById('memory-panel-explore').classList.contains('hidden');
    o.browseBack = !document.getElementById('memory-panel-browse').classList.contains('hidden');
    return o;
  });
  console.log(JSON.stringify(out));
  await b.close();
})();
"""


@pytest.fixture(scope="module")
def driven(tmp_path_factory):
    if NODE is None:
        pytest.skip(_SKIP)
    script = tmp_path_factory.mktemp("brain") / "drive.js"
    script.write_text(_DRIVER
                      .replace("__STYLE__", STYLE.as_posix())
                      .replace("__JSDIR__", (ROOT / "static" / "js").as_posix())
                      .replace("__ROWS__", json.dumps(CORPUS))
                      .replace("__PROJECTS__", json.dumps([
                          {"slug": "pantheon", "label": "Pantheon", "memories": 1},
                          {"slug": "odysseus", "label": "Odysseus", "memories": 1}])),
                      encoding="utf-8")
    run = subprocess.run([NODE, str(script), CHROME], capture_output=True,
                         text=True, cwd=str(ROOT), timeout=300)
    assert run.returncode == 0, run.stdout + run.stderr
    return json.loads(run.stdout.strip().splitlines()[-1])


def test_the_surface_opens_over_the_list_and_goes_back(driven):
    """The door and the way back, both driven. `showExplore(false)` returns to
    whichever tab the strip says is current rather than to a hard-coded
    `browse`, because a reader may have arrived from any of them."""
    assert driven["exploreShown"] and driven["browseHidden"]
    assert driven["exploreHiddenAfterBack"] and driven["browseBack"]


def test_the_six_filters_are_on_the_page(driven):
    assert driven["filters"] == [
        "brain-filter-project", "brain-filter-confidence", "brain-filter-category",
        "brain-filter-age", "brain-filter-session", "brain-filter-edge"]


def test_the_freshness_sentence_reaches_the_page(driven):
    """`B61` again: the helper is tested above, and this is the assertion that
    its output actually renders."""
    assert "memories" in driven["fresh"] and "newest" in driven["fresh"]


def test_filtering_and_clearing_work_on_the_page(driven):
    assert driven["rows"] == len(CORPUS)
    assert driven["filteredRows"] == 1
    assert "1 of 4" in driven["count"]
    assert "Clear filters" in driven["count"]
    assert driven["afterClear"] == len(CORPUS)


def test_a_contradiction_shows_the_other_side_in_its_own_words(driven):
    """*"Open a memory, see what it supersedes and what contradicts it."* The
    other side is resolved to its text, because an id is not a thing anyone can
    read."""
    assert driven["detail"]
    assert driven["edgeTypes"] == ["contradicts"]
    assert driven["edgeTexts"] == [
        "Elevation is a shadow everywhere, never ink at low alpha"], (
        "the edge shows an id or a blank instead of the other memory's words")


def test_correcting_a_memory_reaches_the_brains_own_writer(driven):
    """The Verify's second half — *corrects a wrong memory* — driven all the
    way to the call that saves it."""
    assert driven["actions"] == ["Correct", "Retire"]
    assert driven["editorOpen"], "Correct did not open an editor"
    assert driven["saved"] == ["3", "Elevation is one ink token per tier"], (
        f"the correction did not reach saveInlineEdit: {driven['saved']}")


def test_the_rendered_surface_has_no_canvas(driven):
    """Measured in a browser rather than grepped, because that is the row's
    instruction and a canvas could arrive from any of the modules it loads."""
    assert driven["canvases"] == 0
