# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B885` — a diagram already on screen follows the palette.

**What was on the tree before this, measured 2026-09-19 at `HEAD`.**
`mermaid.run` skips anything carrying `data-processed`
(`static/lib/mermaid.min.js`: `if (u.getAttribute("data-processed")) continue`),
and `markdown.js:_themeMermaid` re-applied the theme for the *next* diagram
only. So a palette switch re-themed nothing already drawn, and its own comment
said so.

The damage, measured with `B872`'s harness against `.mermaid-container`'s panel
on all sixteen palettes — the ink of one scheme against the other scheme's
panel:

    a `dark`-drawn diagram on the four light palettes
        arrows and node outlines      1.17, 1.29, 1.21, 1.29 : 1
    a `neutral`-drawn diagram on the twelve dark palettes
        arrows and node outlines      2.16 - 3.45 : 1
        (eight of the twelve under the 3:1 floor: claude 2.30, copper 2.88,
         dark 2.16, forest 2.34, gpt 2.47, ocean 2.78, retrowave 2.85,
         ume 2.53)

and, in both directions, everything *inside* a box stays legible — node text on
the node fill measures 10.17:1 and 18.10:1, an edge label on its own chip 11.06
and 21.00 — because that ink sits on ink the same theme chose. The failure is
exactly the strokes drawn onto the panel, which is also why re-drawing is the
fix and a per-container backdrop patch would only be a disguise.

**The decision the row asked for, priced.**

  re-draw               N diagrams re-run through mermaid, and only when the
                        `color-scheme` actually moves. Twelve of the sixteen
                        palettes are dark and four are light, so 60% of the 240
                        ordered palette switches cost nothing at all. Measured
                        floor for the rest, `mermaid.parse` alone under node on
                        the vendored 11.17.2 bundle (the grammar half of a draw,
                        no layout, no DOM): 5.68 ms for a 4-node flowchart,
                        8.57 ms for 12 nodes, 15.67 ms for 30. A conversation
                        holding thirty diagrams therefore pays at least ~0.2 s,
                        on an explicit settings action.
  restyle in place      575 CSS declarations across mermaid's diagram
                        stylesheets take their value from a theme variable,
                        drawing on 183 of them. Restyling the drawn SVGs means
                        this repository owning a second copy of that, keyed to
                        upstream's selectors, re-checked at every bump — the
                        ink set in two places, `Law 13` with a 575-line price.
  say it in the UI      Costs a sentence and fixes nothing. `P8-00` asks what a
                        person can do unaided; reading a label that says the
                        diagrams are stale is not it.

Re-draw wins on both numbers: milliseconds against 575 declarations, and it
owns nothing upstream can move.

**How this is driven, and why it is not a grep.** The module under test is the
shipped `static/js/markdown.js`, loaded for real through the loader in
`tests/test_markdown_lazy_lib_loading_js.py` — imported, not copied. `B882` is
about there being four copies of that loader already; a fifth would be this
file's contribution to a defect somebody else is mid-way through fixing
(`Law 14`). Mermaid itself is a stand-in here, but one that behaves the way the
real bundle does at the point that matters: it sets `data-processed` and
replaces the element's content, which is the behaviour this row is about.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

# `Law 14`. The one loader that inlines `markdown.js`'s imports and imports the
# result as a module. `B882` is consolidating the copies of it that already
# exist; this file adds none.
from test_markdown_lazy_lib_loading_js import _run_node, node_available  # noqa: E402,F401

# Prepended to every body below. A page of diagrams, a mermaid that draws the
# way the vendored one does, and a MutationObserver whose callbacks can be
# fired — the harness's own stub takes an observer and never calls it.
_PAGE = r"""
const page = [];
const runs = [];
const observers = [];

globalThis.MutationObserver = class {
  constructor(fn) { this.fn = fn; this.records = []; observers.push(this); }
  observe(target, opts) { this.target = target; this.opts = opts; }
  disconnect() { this.disconnected = true; }
};

function diagram(text) {
  const attrs = {};
  const node = {
    tagName: 'PRE', isConnected: true, textContent: text, attrs,
    id: 'd' + page.length,
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(attrs, k) ? attrs[k] : null; },
    removeAttribute(k) { delete attrs[k]; },
  };
  page.push(node);
  return node;
}

// `document` answers the two selectors `markdown.js` asks it for.
globalThis.document.querySelectorAll = (selector) => {
  if (selector === 'pre.mermaid:not([data-processed])') {
    return page.filter((n) => n.getAttribute('data-processed') === null);
  }
  if (selector.indexOf('[data-processed][data-mermaid-src]') !== -1) {
    return page.filter((n) => n.getAttribute('data-processed') !== null
      && n.getAttribute('data-mermaid-src') !== null);
  }
  return [];
};

// Draws the way the vendored bundle draws: marks the element and overwrites
// its content with the SVG, which is what destroys the diagram's own source.
const DRAW_INK = { dark: 'lightgrey', neutral: '#666' };
const DRAW_LABEL_BKG = { dark: '#181818' };
function drawingMermaid(record) {
  let current = {};
  return {
    initialize(cfg) { current = cfg; record.push(JSON.parse(JSON.stringify(cfg))); },
    run(opts) {
      const nodes = (opts && opts.nodes) || [];
      runs.push(nodes.map((n) => n.id));
      nodes.forEach((n) => {
        n.setAttribute('data-processed', 'true');
        n.textContent = '<svg>drawn as ' + current.theme + '</svg>';
      });
      return Promise.resolve();
    },
    mermaidAPI: {
      getConfig: () => ({
        theme: current.theme,
        themeVariables: Object.assign(
          {
            lineColor: DRAW_INK[current.theme] || null,
            labelBackground: DRAW_LABEL_BKG[current.theme] || null,
          },
          current.themeVariables || {}),
      }),
    },
  };
}

async function settle(turns = 12) {
  for (let i = 0; i < turns; i++) await new Promise((r) => setTimeout(r, 0));
}

// Bring mermaid in the way a first diagram does, and return the config log.
async function firstDraw(text) {
  const seen = [];
  diagram(text);
  const pending = mod.renderMermaid();
  globalThis.window.mermaid = drawingMermaid(seen);
  injected.scripts[0].fire('load');
  await pending;
  return seen;
}

function fireObservers() {
  observers.forEach((o) => o.fn([], o));
}
"""


def run(body: str):
    return _run_node(_PAGE + body)


def test_a_drawn_diagram_carries_its_own_source_and_the_scheme_it_was_drawn_in(node_available):
    """The precondition for ever re-drawing it.

    `mermaid.run` reads the element's `innerHTML` and then overwrites it, so
    after the first draw the fence text exists nowhere on the page. This is the
    one place that sees every diagram — all seven `renderMermaid` call sites
    across six files go through it — so the source is stashed here and not in
    any of the five places the markup is built (`Law 13`).
    """
    out = run(
        """
        setScheme('dark');
        const seen = await firstDraw('graph TD; A-->B;');
        const node = page[0];
        emit({
          themes: seen.map((c) => c.theme),
          src: node.getAttribute('data-mermaid-src'),
          scheme: node.getAttribute('data-mermaid-scheme'),
          drawn: node.textContent,
          processed: node.getAttribute('data-processed'),
        });
        """
    )
    assert out["themes"] == ["dark", "dark"], out["themes"]
    assert out["src"] == "graph TD; A-->B;", out
    assert out["scheme"] == "dark", out
    # And mermaid really did destroy it, which is what the stash is for.
    assert out["drawn"] == "<svg>drawn as dark</svg>", out
    assert out["processed"] == "true", out


def test_switching_scheme_redraws_the_diagram_already_on_the_page(node_available):
    """The row. A dark palette, a diagram, then a light palette.

    Before this, the second `initialize` never happened and `run` was never
    called again: the diagram stayed `dark` — `lightgrey` arrows on a near-white
    panel at 1.17-1.29:1.
    """
    out = run(
        """
        setScheme('dark');
        const seen = await firstDraw('graph TD; A-->B;');
        const node = page[0];
        const beforeSwitch = { theme: seen[seen.length - 1].theme, drawn: node.textContent };

        setScheme('light');
        fireObservers();
        await settle();

        emit({
          beforeSwitch,
          themes: seen.map((c) => c.theme),
          drawn: node.textContent,
          scheme: node.getAttribute('data-mermaid-scheme'),
          src: node.getAttribute('data-mermaid-src'),
          processed: node.getAttribute('data-processed'),
          redrawn: runs.length,
        });
        """
    )
    assert out["beforeSwitch"] == {"theme": "dark", "drawn": "<svg>drawn as dark</svg>"}
    assert out["themes"] == ["dark", "dark", "neutral", "neutral"], out["themes"]
    assert out["drawn"] == "<svg>drawn as neutral</svg>", out
    assert out["scheme"] == "light", out
    # The source survived the round trip, so it can be re-drawn again.
    assert out["src"] == "graph TD; A-->B;", out
    assert out["processed"] == "true", out
    assert out["redrawn"] == 2, out


def test_a_palette_change_inside_one_scheme_redraws_nothing(node_available):
    """The cost claim, driven rather than argued.

    Twelve of the sixteen palettes are dark. Switching `midnight` -> `terminal`
    writes ten inline properties onto `<html>` and moves no `color-scheme`, so
    the observer fires, compares one string and stops: no `initialize`, no
    re-draw, nothing. That is 60% of the 240 ordered palette switches.
    """
    out = run(
        """
        setScheme('dark');
        const seen = await firstDraw('graph TD; A-->B;');
        const before = seen.length;

        // A second dark palette: same scheme, new colours.
        document.documentElement.style.setProperty('--bg', '#000d03');
        setScheme('dark');
        fireObservers();
        await settle();

        emit({
          before,
          after: seen.length,
          redrawn: runs.length,
          drawn: page[0].textContent,
        });
        """
    )
    assert out["before"] == 2, out
    assert out["after"] == 2, out
    assert out["redrawn"] == 1, out
    assert out["drawn"] == "<svg>drawn as dark</svg>", out


def test_a_new_diagram_arriving_after_the_switch_does_not_strand_the_old_ones(node_available):
    """The trap this design had to step around, driven.

    An ordinary draw moves the module's idea of which scheme Mermaid is in, as
    a side effect of theming the NEW diagram. A watcher that compared against
    that would look at a page where a message had just arrived, decide the
    palette change had already been handled and leave every older diagram
    drawn in the old theme — for good, because nothing else ever revisits them.
    So the watcher keeps its own `_watchedScheme` and this is the case that
    says why: `d1` is drawn under the new palette first, and `d0` is still
    swept afterwards.

    It is also the per-diagram half of the claim: the scheme is stamped on each
    diagram, so the sweep is the stale ones and nothing else — `d1` is not
    re-drawn.
    """
    out = run(
        """
        setScheme('dark');
        const seen = await firstDraw('graph TD; A-->B;');

        setScheme('light');
        // A new message arrives before the switch is swept, and is drawn in
        // the palette that is up.
        diagram('graph TD; C-->D;');
        await mod.renderMermaid();
        const fresh = page[1];

        fireObservers();
        await settle();

        emit({
          themes: seen.map((c) => c.theme),
          runs,
          old: { scheme: page[0].getAttribute('data-mermaid-scheme'), drawn: page[0].textContent },
          fresh: { scheme: fresh.getAttribute('data-mermaid-scheme'), drawn: fresh.textContent },
        });
        """
    )
    # Two initialise pairs: dark on the first draw, neutral for the new
    # diagram. The sweep that follows needs no third.
    assert out["themes"] == ["dark", "dark", "neutral", "neutral"], out["themes"]
    # d0 drawn, then d1 drawn, then d0 swept — and d1 never twice.
    assert out["runs"] == [["d0"], ["d1"], ["d0"]], out["runs"]
    assert out["old"] == {"scheme": "light", "drawn": "<svg>drawn as neutral</svg>"}, out
    assert out["fresh"] == {"scheme": "light", "drawn": "<svg>drawn as neutral</svg>"}, out


def test_a_palette_clicked_again_mid_sweep_settles_on_the_last_one(node_available):
    """Re-entrancy, which a settings panel produces for free.

    Each pass reads the watcher's note and clears it at call time rather than
    when it lands, so a second click during the first sweep gets its own pass
    instead of finding the note already taken. The page ends in the palette
    that is up, not in the one that was up when the first pass started.
    """
    out = run(
        """
        setScheme('dark');
        const seen = await firstDraw('graph TD; A-->B;');

        setScheme('light');
        fireObservers();
        await settle(1);          // the first sweep is away

        setScheme('dark');        // clicked again
        fireObservers();
        await settle();

        emit({
          themes: seen.map((c) => c.theme),
          runs,
          scheme: page[0].getAttribute('data-mermaid-scheme'),
          drawn: page[0].textContent,
        });
        """
    )
    assert out["scheme"] == "dark", out
    assert out["drawn"] == "<svg>drawn as dark</svg>", out
    # One first draw and two sweeps, over the same one diagram, and no spin.
    assert out["runs"] == [["d0"], ["d0"], ["d0"]], out["runs"]
    assert out["themes"] == ["dark", "dark", "neutral", "neutral", "dark", "dark"], out["themes"]


def test_two_clicks_that_cancel_out_redraw_nothing(node_available):
    """The other half of the same guard. Dark -> light -> dark inside one tick
    leaves every diagram already correct, and the sweep that follows finds
    nothing stale to do. A settings panel that fires twice costs one string
    compare and a `querySelectorAll`, not a re-draw."""
    out = run(
        """
        setScheme('dark');
        const seen = await firstDraw('graph TD; A-->B;');

        setScheme('light');
        fireObservers();
        setScheme('dark');
        fireObservers();
        await settle();

        emit({
          themes: seen.map((c) => c.theme),
          runs,
          scheme: page[0].getAttribute('data-mermaid-scheme'),
          drawn: page[0].textContent,
        });
        """
    )
    assert out["runs"] == [["d0"]], out["runs"]
    assert out["themes"] == ["dark", "dark"], out["themes"]
    assert out["scheme"] == "dark", out
    assert out["drawn"] == "<svg>drawn as dark</svg>", out


def test_a_page_with_no_diagram_on_it_watches_nothing(node_available):
    """`renderMermaid` returns before fetching when there is no fence, and the
    observer is installed on the first draw rather than at module load — so a
    chat that never contains a diagram neither downloads 3.5 MB nor observes
    anything."""
    out = run(
        """
        setScheme('dark');
        await mod.renderMermaid();
        emit({ observers: observers.length, scripts: injected.scripts.length });
        """
    )
    assert out == {"observers": 0, "scripts": 0}, out


def test_the_observer_watches_the_one_element_every_palette_writer_writes(node_available):
    """`theme.js:292` and the two first-paint scripts all set `color-scheme` as
    an inline declaration on `<html>`; `documentScheme()` reads it back off
    `.style`. Watching that attribute is why this needs no new event and no
    second list of palette writers to keep in step (`Law 14`)."""
    out = run(
        """
        setScheme('dark');
        await firstDraw('graph TD; A-->B;');
        const o = observers[0];
        emit({
          count: observers.length,
          isDocumentElement: o.target === document.documentElement,
          opts: o.opts,
        });
        """
    )
    assert out["count"] == 1, out
    assert out["isDocumentElement"] is True, out
    assert out["opts"] == {"attributes": True, "attributeFilter": ["style"]}, out
