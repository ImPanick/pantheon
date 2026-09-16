// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/icons.js

/**
 * `B83`. The glyphs more than one module draws, drawn once.
 *
 * ── What was measured ───────────────────────────────────────────────────────
 * Re-measured 2026-09-16 over `static/js/**` excluding `static/lib/**`, with
 * comments blanked so a comment about a triangle is not counted as one:
 *
 *     play triangle   19 sites in FIVE geometries
 *                     `5 3 19 12 5 21 5 3`   8   cookbook, cookbookServe,
 *                                               document ×3, markdown, skills,
 *                                               tasks
 *                     `6 4 20 12 6 20 6 4`   5   chat, cookbookRunning,
 *                                               queuePanel, tasks ×2
 *                     `5 3 19 12 5 21`       3   compare/icons,
 *                                               compare/selector, research
 *                     `6 3 20 12 6 21 6 3`   2   chat (TTS), tts-ai
 *                     `7 4 19 12 7 20 7 4`   1   tasks (the `active` badge)
 *
 * The fifth was found by the test, not by this list. `tests/test_one_icon_table.py`
 * classifies a polygon by its SHAPE — three points, two on a common x near the
 * left edge, one on the vertical centre near the right — rather than matching
 * the spellings somebody already knew about, and the `active` task badge at
 * `tasks.js:909` came out of it. A census that matches known spellings is how
 * `B12` counted two and `B83` counted seven.
 *
 *     stop square     13 sites in FOUR geometries
 *                     `6 6 12 12 rx=1`       5   cookbook-diagnosis,
 *                                               cookbookRunning, queuePanel,
 *                                               tasks ×2
 *                     `6 6 12 12 rx=2`       4   chat, compare/index ×2,
 *                                               compare/panes
 *                     `5 5 14 14 rx=2`       3   chat (TTS), tts-ai ×2
 *                     `5 5 14 14 rx=1.5`     1   cookbookRunning (Stop all)
 *
 * Two squares that are NOT stop controls stay where they are, and the
 * difference is the point rather than an oversight: `emojiPicker.js` draws a
 * filled and an outlined square as the SYMBOLS ■ and □ in a symbol picker. They
 * are content, not controls, and folding content into a control's glyph is how
 * an icon table starts meaning nothing.
 *
 * `B12` said the play triangle was "hand-written twice"; `B83` re-counted it at
 * seven in two spellings and shared the first pair through `checklist.js`. Both
 * counts were of a narrower scope. The product shipped **five** play triangles
 * and **four** stop squares, and two of the play geometries sat on the same
 * screen — `queuePanel.js`'s docked row and `document.js`'s Run button are a
 * pixel apart in a 24-unit box, which is the `Law 15` failure one size down
 * from `B11`.
 *
 * ── Why a table, and why now ────────────────────────────────────────────────
 * `B83` said the honest home for a glyph five unrelated modules want is a
 * shared icon table, which did not exist, and that building one is a decision
 * about the whole icon surface rather than about a triangle. This is that
 * decision, taken deliberately and deliberately bounded:
 *
 *   in    play and stop. Both are CONTROLS — a person presses them to start or
 *         end a run — and a control drawn two ways is the failure `Law 15`
 *         names. Every site is moved, so each family is one literal.
 *
 *   out   the chevron: 45 sites, four spellings, 22 modules. Left out for two
 *         reasons and neither is "it was hard". First, it is not one glyph —
 *         the four spellings are four DIRECTIONS (down, up, left, right), and
 *         a table entry per direction or a direction argument is a shape
 *         question play and stop do not raise. Second, most chevrons are the
 *         fold affordance on a container, not a control: they carry classes
 *         like `.cookbook-section-chevron` that CSS ROTATES on collapse, so
 *         moving the markup into a builder would put the glyph and the
 *         transform that animates it in two different files. And 12 of the 45
 *         are in `emailLibrary.js` and `notes.js`, which belong to other agents
 *         this wave — moving a family by two thirds is worse than not starting,
 *         because the third left behind is what the next reader copies.
 *         Measured and filed as `B230`, with the count, so the next pass starts
 *         from a number.
 *
 * ── Themes ──────────────────────────────────────────────────────────────────
 * Nothing here names a colour. Every glyph paints with `currentColor` and takes
 * the colour of whatever it sits in, which is what all 32 literals already did;
 * a shared table that invented a token would be a seventeenth theme nobody
 * asked for.
 *
 * ── The geometry that won, and why it is not the one `B12` picked ───────────
 * `5 3 19 12 5 21` — 11 of the 19 sites, counting the closed and open spellings
 * of the same polygon together, which SVG does (a `<polygon>` closes itself).
 * `B12` picked `6 4 20 12 6 20 6 4` as the majority of the seven sites it could
 * see; over the whole surface it is the minority. The two `.plan-inline-execute`
 * builders move with everything else, which is the point — one triangle, not a
 * standoff between two.
 */

/** The play triangle, as points. Exported because `planWindow.js` builds its
 *  polygon as DOM and sets the attribute rather than interpolating markup. */
export const PLAY_POINTS = '5 3 19 12 5 21';

/** The play triangle as a bare SVG child, for the modules that own their own
 *  `<svg>` wrapper — three menu-icon tables and one diagnosis-button builder
 *  hand their glyphs to a local `_svg()` and must keep doing so, because the
 *  wrapper is where those surfaces state their stroke width and their class. */
export const PLAY_GLYPH = `<polygon points="${PLAY_POINTS}"/>`;

/** The stop square, same arrangement. `rx="1"` is the majority of the three
 *  spellings and the one the two surfaces that draw play and stop SIDE BY SIDE
 *  — `queuePanel.js` and the Activity row — already used. */
export const STOP_GLYPH = '<rect x="6" y="6" width="12" height="12" rx="1"/>';

/**
 * A glyph in its own `<svg>`, at a size.
 *
 * `outline` is the one real variation across the sites: two of them draw the
 * play triangle as a stroked outline rather than a filled wedge
 * (`cookbookServe.js`'s serve button, `markdown.js`'s run-code button) and both
 * are kept exactly as they were (`Law 1`). Everything else is the filled form.
 *
 * `aria-hidden` defaults to true because every one of these sits inside a
 * button that carries its own title or label — the glyph is decoration and a
 * screen reader reading "polygon" over the top of "Start now" is noise.
 */
export function iconSvg(glyph, opts = {}) {
  const {
    size = 14, width = size, height = size,
    outline = false, style = '', className = '', ariaHidden = true,
  } = opts;
  const paint = outline
    ? 'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
    : 'fill="currentColor" stroke="none"';
  return `<svg width="${width}" height="${height}" viewBox="0 0 24 24" ${paint}`
    + (className ? ` class="${className}"` : '')
    + (style ? ` style="${style}"` : '')
    + (ariaHidden ? ' aria-hidden="true"' : '')
    + `>${glyph}</svg>`;
}

/** The play triangle, wrapped. */
export function playIcon(opts = {}) {
  return iconSvg(PLAY_GLYPH, opts);
}

/** The stop square, wrapped. */
export function stopIcon(opts = {}) {
  return iconSvg(STOP_GLYPH, opts);
}
