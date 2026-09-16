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
 *   in    the chevron, added by `B230`: 57 sites, five spellings, 23 modules.
 *         `B83` left it out, measured it at 45, and wrote down why; each
 *         reason is answered where the family is defined below, and the count
 *         was nine short of what the tree held.
 *
 *   out   `emojiPicker.js`'s filled and outlined squares, which are the SYMBOLS
 *         ■ and □ in a symbol picker rather than controls, and the seven
 *         chevron literals in `static/index.html`, which is markup and not a
 *         module — nothing there can import a table. Both are measured, and
 *         the second is `B291`.
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
 * `chevronIcon` overrides that default and the reason is written where it does.
 *
 * `strokeWidth`, `linejoin` and `id` were added by `B230` and every default is
 * the value the tree already emitted, so the markup `playIcon`, `stopIcon` and
 * `iconSvg` produce is byte-for-byte what it was: the outline paint was
 * `stroke-width="2"` with a round join, and no play or stop site carried an
 * `id`. They exist because the 45 chevron sites spelled SIX stroke widths
 * (2, 2.2, 2.4, 2.5, 2.6, 3), two of them omitted `stroke-linejoin` so their
 * vertex is mitred rather than rounded, and one carries an `id` the settings
 * page looks up by. Reproducing each site exactly is what makes "this is a
 * move, not a restyle" a measurement instead of a promise — the spread itself
 * is a real defect and is filed as `B290` rather than fixed by stealth here.
 */
export function iconSvg(glyph, opts = {}) {
  const {
    size = 14, width = size, height = size,
    outline = false, strokeWidth = 2, linejoin = true,
    style = '', className = '', id = '', ariaHidden = true,
  } = opts;
  const paint = outline
    ? `fill="none" stroke="currentColor" stroke-width="${strokeWidth}" stroke-linecap="round"`
      + (linejoin ? ' stroke-linejoin="round"' : '')
    : 'fill="currentColor" stroke="none"';
  return `<svg width="${width}" height="${height}" viewBox="0 0 24 24" ${paint}`
    + (className ? ` class="${className}"` : '')
    + (id ? ` id="${id}"` : '')
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

// ── The chevron (`B230`) ────────────────────────────────────────────────────
//
// `B83` measured the chevron at 45 sites in four spellings across 22 modules
// and deliberately did not move it. Re-measured here it is **57 sites in FIVE
// spellings across 23 modules**, and both of the corrections matter more than
// the arithmetic:
//
//     6 9 12 15 18 9   down   43   18 modules
//     15 18 9 12 15 6  left    6   compare/selector, document, emailLibrary,
//                                  gallery ×2, notes
//     18 15 12 9 6 15  up      2   research/panel, skills
//     6 15 12 9 18 15  up      3   document ×2, galleryEditor — the SAME two
//                                  segments as the line above, traversed the
//                                  other way, which is the same stroke
//     9 18 15 12 9 6   right   3   document, emailLibrary, gallery
//
// Where the twelve extra came from, because a count that grows by a quarter on
// re-measurement is a finding and not a footnote:
//
//   NINE were invisible. `B83`'s census blanked comments with
//   `re.sub(r"/\*.*?\*/", …, flags=re.S)`, which cannot tell a comment from a
//   string: `input.accept = 'image/*,video/*'` at `gallery.js:1202` opens a
//   "comment" that the next `*/` in the file closes. Across `static/js/**` that
//   substitution erases **7,203 lines of live code in 77 modules**. Seven of
//   the missing chevrons are in `document.js` and two in `gallery.js`, inside
//   the erased spans — and so were a play triangle (`document.js:4986`) and two
//   stop squares (`notes.js:4517`, `:4586`), which is `B83`'s own `Verify`
//   being false on the day it was ticked. All twelve are moved here. The
//   blanker is copied into about twenty test files; that is `B290`.
//
//   THREE were a fifth spelling. They were found by a detector that classifies
//   a polyline by its SHAPE — two arms level with each other, a vertex off the
//   line between them, alone inside its `<svg>` — instead of matching the four
//   spellings somebody already knew. That is the same technique that found the
//   fifth play geometry for `B83`, and it caught the same class of miss one
//   layer down: a census that matches known spellings can only ever confirm
//   what it was told.
//
// `B83` gave three reasons for leaving the family alone. They were good ones,
// and each is answered rather than waved away.
//
// (1) "It is not one glyph — four spellings are four DIRECTIONS."
//     It IS one glyph, and that is provable rather than assertable: rotating
//     `6 9 12 15 18 9` about the centre of the 24-box by 180° gives
//     `18 15 12 9 6 15` exactly, and by −90° gives `9 18 15 12 9 6` exactly.
//     By +90° it gives the three points of `15 18 9 12 15 6` traversed in the
//     other order, which is the same stroke — every one of the 57 sites sets
//     `stroke-linecap="round"`, so a polyline and its reverse paint the same
//     pixels. The fifth spelling is that fact showing up in the tree already.
//     So the geometry is ONE literal and `direction` is an argument, which is
//     what the row's `Verify` asks for. `chevronPoints` derives the other
//     three; nothing in the tree spells a second chevron.
//
// (2) "Most chevrons are a fold affordance whose CSS rotates them — moving the
//     markup into a builder puts the glyph and the transform in two files."
//     This is the reason the direction is baked into the POINTS and not into a
//     `transform` attribute or a class. FOURTEEN stylesheet rules rotate a
//     chevron by class (`.section.collapsed .section-collapse-chevron`,
//     `.email-quote-fold[open] .email-summary-chevron`, …) and SIX JS handlers
//     set `chevron.style.transform` directly — four in `admin.js`, two in
//     `cookbookRunning.js`. Every one of those twenty rotates a chevron whose
//     base orientation is DOWN. If this table emitted a transform of its own,
//     or shipped a base orientation that was not the one those twenty were
//     written against, all twenty would compose wrongly and the regression
//     would be silent across 23 modules. It emits bare points and no transform,
//     so the stylesheet stays the only thing that rotates a chevron and the
//     arrangement `B83` objected to never appears. The builder is not a second
//     place the rotation lives; it is the same place the literal was.
//
// (3) "12 of the 45 are in `emailLibrary.js` and `notes.js`, another agent's
//     files this wave — moving a family by two thirds is worse than not
//     starting." Correct, and the fix is to own those files rather than to skip
//     them. All 57 move in one commit.
//
// What deliberately does NOT change: not one site's size, stroke width, class,
// inline style, `id`, `aria-hidden` or mitre. The chevron ships at ELEVEN sizes
// (8, 9, 10, 11, 12, 13, 14, 16, 18, 22, 24), SEVEN stroke widths (2, 2.2, 2.4,
// 2.5, 2.6, 3, 3.5), with `stroke-linejoin` omitted at two sites so their vertex
// is mitred rather than rounded, and `aria-hidden` set at only 11 of 57. That
// spread is a `Law 15` defect in its own right and it is filed as `B291`, not
// fixed here by stealth. Every call site states its own, and the test compares
// what each of the 57 now emits against what the literal emitted before,
// attribute by attribute. This is a move, not a restyle.
//
// Not moved, and measured so the next pass starts from a number: `static/index.html`
// spells the chevron SEVEN more times, and markup cannot import a table — that
// is `B292`. And 104 chevron-SHAPED polylines in the client are not this icon:
// they are arms of a composed glyph (a download arrow's head over its shaft, the
// two halves of `< >`, a reply arrow) and they share their `<svg>` with a
// sibling element, which is what tells them apart from an icon that is one
// polyline alone.

/** The chevron, as points: the DOWN arm-vertex-arm polyline, and the only
 *  chevron geometry in the tree. The other three directions are this one
 *  rotated (`chevronPoints`). */
export const CHEVRON_POINTS = '6 9 12 15 18 9';

/**
 * Quarter turns about the centre of the 24-box, one per direction.
 *
 * `reverse` is set on `left` alone, and it is not a fudge: three of the four
 * spellings the product shipped traverse the glyph in the base's own order and
 * `15 18 9 12 15 6` traverses it backwards. A polyline's traversal is not part
 * of its stroke, so this changes nothing a viewer can see — it exists so that
 * all 45 sites emit the exact string they emitted before, which turns "measure
 * before and after" into string equality instead of an argument.
 */
const _CHEVRON_TURNS = {
  down: { angle: 0, reverse: false },
  up: { angle: 180, reverse: false },
  right: { angle: -90, reverse: false },
  left: { angle: 90, reverse: true },
};

/** The chevron's points, in one of four directions. */
export function chevronPoints(direction = 'down') {
  const turn = _CHEVRON_TURNS[direction];
  if (!turn) {
    throw new Error(`icons.js: unknown chevron direction '${direction}'`);
  }
  // Every angle here is a quarter turn, so cos and sin are exactly -1, 0 or 1;
  // rounding removes the 6.1e-17 that `Math.cos(Math.PI / 2)` returns and keeps
  // the emitted points integers. It would be wrong for any other angle, and the
  // table above is the guarantee there is no other angle.
  const rad = (turn.angle * Math.PI) / 180;
  const cos = Math.round(Math.cos(rad));
  const sin = Math.round(Math.sin(rad));
  const n = CHEVRON_POINTS.split(/[\s,]+/).map(Number);
  const out = [];
  for (let i = 0; i < n.length; i += 2) {
    const x = n[i] - 12;
    const y = n[i + 1] - 12;
    out.push(`${12 + x * cos - y * sin} ${12 + x * sin + y * cos}`);
  }
  if (turn.reverse) out.reverse();
  return out.join(' ');
}

/** The chevron as a bare SVG child, for a module that owns its own wrapper. */
export function chevronGlyph(direction = 'down') {
  return `<polyline points="${chevronPoints(direction)}"/>`;
}

/**
 * The chevron in its own `<svg>`.
 *
 * `aria-hidden` defaults to FALSE here where `iconSvg` defaults it to true, and
 * the difference is measured rather than stylistic: a play or stop glyph always
 * sits inside a control that carries its own label, but a chevron is sometimes
 * the entire content of a button (`section-management.js`'s collapse button,
 * `emailLibrary.js`'s previous/next arrows) and sometimes a bare decoration
 * beside a word. The tree set `aria-hidden` at 8 of the 45 sites and not at the
 * other 37. Picking one for all 45 would be a change to what a screen reader
 * says on 37 surfaces, made silently, inside a commit whose whole claim is that
 * it changes nothing visible. Each site keeps what it had; the inconsistency is
 * `B290`.
 *
 * The defaults are the chevron's own majorities — `size: 10` (17 of 45) and
 * `strokeWidth: 2.5` (31 of 45) — so a new caller that states neither gets the
 * common chevron rather than a play triangle's.
 */
export function chevronIcon(opts = {}) {
  const {
    direction = 'down', size = 10, strokeWidth = 2.5, ariaHidden = false, ...rest
  } = opts;
  return iconSvg(chevronGlyph(direction),
    { ...rest, size, strokeWidth, ariaHidden, outline: true });
}
