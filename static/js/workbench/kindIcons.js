// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/workbench/kindIcons.js
//
// `B1833`. What a step looks like before it is read: one glyph per kind and
// the family it belongs to, so the canvas, the step picker and a run's record
// draw a kind the same way (`Law 7`). A leaf — it imports nothing — so the
// canvas, `workflowPanels.js` and a test may all import it without a cycle.
//
// **Families are the palette's groups** (`workflow_effects.build_palette`'s
// `group`: "Ask a model", "Run in Pantheon", "Decide and reshape", "Flow",
// "Reach out"), plus the start. The family is the colour key the stylesheet
// tints a step's glyph tile with (`data-cat`); the colours themselves are
// derived from the theme's tokens in `cockpit.css`, never named here.
//
// **Every glyph is built as DOM** (`createElementNS`, attribute by attribute):
// the canvas promises one markup assignment only, and it is not this one.
// Each glyph is a 24-unit stroked drawing that paints with `currentColor`, so
// it takes the colour of whatever it sits in, the way `icons.js`'s do.

const SVG_NS = 'http://www.w3.org/2000/svg';

/** A glyph: a list of `[tag, attrs]`. */
const P = (d) => ['path', { d }];
const C = (cx, cy, r) => ['circle', { cx, cy, r }];
const R = (x, y, width, height, rx) => ['rect', { x, y, width, height, rx }];

export const GLYPHS = Object.freeze({
  // Ask a model
  llm: [P('M12 3.5l1.7 4.3 4.3 1.7-4.3 1.7L12 15.5l-1.7-4.3L6 9.5l4.3-1.7z'),
    P('M18.5 14.5l.8 1.9 1.9.8-1.9.8-.8 1.9-.8-1.9-1.9-.8 1.9-.8z'), P('M5.5 15.5l.5 1.2 1.2.5-1.2.5-.5 1.2-.5-1.2-1.2-.5 1.2-.5z')],
  research: [C(10.5, 10.5, 6.5), P('M20.5 20.5l-5.2-5.2'), P('M8 10.5h5'), P('M10.5 8v5')],
  skill: [P('M2.5 4.5h6a3.5 3.5 0 0 1 3.5 3.5v12a2.6 2.6 0 0 0-2.6-2.6H2.5z'),
    P('M21.5 4.5h-6A3.5 3.5 0 0 0 12 8v12a2.6 2.6 0 0 1 2.6-2.6h6.9z')],
  // Run in Pantheon
  action: [P('M13 2.5L4 13.5h7l-1 8 9-11h-7z')],
  run_task: [R(3.5, 3.5, 17, 17, 3), P('M9 8.5l5 3.5-5 3.5z')],
  workflow: [R(3, 3, 6, 6, 1.5), R(15, 15, 6, 6, 1.5), P('M6 9v2.5A3.5 3.5 0 0 0 9.5 15H15')],
  // Decide and reshape
  if: [C(6, 5.5, 2.2), C(6, 18.5, 2.2), C(18, 8, 2.2), P('M6 7.7v8.6'), P('M18 10.2c0 4.3-4.6 5.2-9.8 6.6')],
  switch: [P('M3 12h5.5'), P('M8.5 12C12 12 12 5 16 5h4.5'), P('M8.5 12h12'), P('M8.5 12C12 12 12 19 16 19h4.5'),
    P('M18.5 3l2 2-2 2'), P('M18.5 10l2 2-2 2'), P('M18.5 17l2 2-2 2')],
  set: [P('M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17z'), P('M13.5 7.5l3 3'), P('M12.5 20h7.5')],
  // Flow
  merge: [P('M6 3.5v4.5c0 3 6 4.5 6 8.5v4'), P('M18 3.5v4.5c0 3-6 4.5-6 8.5'), P('M9 18l3 3 3-3')],
  wait: [P('M6 2.5h12'), P('M6 21.5h12'), P('M7.5 2.5v3.6a2 2 0 0 0 .6 1.4L12 12l3.9-4.5a2 2 0 0 0 .6-1.4V2.5'),
    P('M7.5 21.5v-3.6a2 2 0 0 1 .6-1.4L12 12l3.9 4.5a2 2 0 0 1 .6 1.4v3.6')],
  foreach: [P('M17 2.5l3.5 3.5L17 9.5'), P('M3.5 11v-1A4 4 0 0 1 7.5 6h13'), P('M7 21.5L3.5 18 7 14.5'),
    P('M20.5 13v1a4 4 0 0 1-4 4h-13')],
  // Reach out
  http: [C(12, 12, 9), P('M3 12h18'), P('M12 3c2.6 2.4 3.8 5.4 3.8 9s-1.2 6.6-3.8 9c-2.6-2.4-3.8-5.4-3.8-9S9.4 5.4 12 3z')],
  mcp: [P('M9 2.5v5'), P('M15 2.5v5'), P('M6 7.5h12v4a6 6 0 0 1-12 0z'), P('M12 17.5v4')],
  code: [P('M15.5 6.5l5.5 5.5-5.5 5.5'), P('M8.5 6.5L3 12l5.5 5.5'), P('M13.5 4l-3 16')],
  // The start, by what starts it (`workflow_store.START_TRIGGER_TYPES`, and
  // the task a chain hands on from).
  'start:schedule': [C(12, 12, 9), P('M12 7v5l3.5 2')],
  'start:event': [P('M13 2.5L4 13.5h7l-1 8 9-11h-7z')],
  'start:webhook': [P('M10 14a4.5 4.5 0 0 0 6.4.4l2.6-2.6a4.5 4.5 0 0 0-6.4-6.4l-1.4 1.4'),
    P('M14 10a4.5 4.5 0 0 0-6.4-.4L5 12.2a4.5 4.5 0 0 0 6.4 6.4l1.4-1.4')],
  'start:mail': [R(2.5, 5, 19, 14, 2.5), P('M3 6.5l9 6.5 9-6.5')],
  start: [P('M7 4.5v15l12-7.5z')],
  // A step this person cannot see, or a kind this browser does not know.
  missing: [C(12, 12, 9), P('M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5v.7'), P('M12 17h.01')],
});

/** The family each kind belongs to: the palette's group, as a key. */
export const KIND_CATS = Object.freeze({
  llm: 'model', research: 'model', skill: 'model',
  action: 'pantheon', run_task: 'pantheon', workflow: 'pantheon',
  if: 'logic', switch: 'logic', set: 'logic',
  merge: 'flow', wait: 'flow', foreach: 'flow',
  http: 'reach', mcp: 'reach', code: 'reach',
  start: 'trigger',
});

/** The palette's group words, by family — what a picker heads each family
 *  with when the server's palette is not there to say. */
export const CAT_WORDS = Object.freeze({
  trigger: 'Starts', model: 'Ask a model', pantheon: 'Run in Pantheon',
  logic: 'Decide and reshape', flow: 'Flow', reach: 'Reach out',
});

/** The family of `kind` (`'model'` for one this browser does not know: it is
 *  drawn like a Prompt, the kind an unknown task is drawn as elsewhere). */
export function kindCat(kind) {
  return KIND_CATS[String(kind || '')] || 'model';
}

/** The glyph key of a workflow's start, by what starts it: a schedule, an
 *  event (mail arriving has a glyph of its own), a webhook, or another task. */
export function startGlyph(trigger) {
  const t = trigger || {};
  const type = String(t.trigger_type || 'schedule');
  if (type === 'webhook') return 'start:webhook';
  if (type === 'event') return String(t.trigger_event || '') === 'email_received' ? 'start:mail' : 'start:event';
  if (type === 'schedule') return 'start:schedule';
  return 'start';
}

/**
 * The glyph for `key` (a kind, or a `start:*` key) as an `<svg>` element,
 * `size` px square, hidden from assistive technology: every glyph sits beside
 * the words that name the kind.
 */
export function kindIcon(key, { size = 16, strokeWidth = 1.8, cls = 'wb-kind-glyph' } = {}) {
  const parts = GLYPHS[String(key || '')] || GLYPHS.missing;
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', cls);
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', String(size));
  svg.setAttribute('height', String(size));
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', String(strokeWidth));
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  for (const [tag, attrs] of parts) {
    const n = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
    svg.appendChild(n);
  }
  return svg;
}

export default { GLYPHS, KIND_CATS, CAT_WORDS, kindCat, startGlyph, kindIcon };
