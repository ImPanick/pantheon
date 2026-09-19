// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/markdown/mermaidTheme.js
//
// `B872`. One place decides which Mermaid theme this product draws with.
//
// **What was wrong.** `markdown.js:94` initialised Mermaid with
// `theme: 'dark'` written into the call, once, for every diagram this product
// has ever drawn — chat messages, the document preview, the slash-command
// preview and `P8-34`'s workflow card. Four of the sixteen shipped palettes
// are light (`light`, `paper`, `lavender`, `cute`), and on those the dark
// theme's arrows (`lineColor: lightgrey`) and node outlines (`nodeBorder:
// #ccc`) were drawn onto `.mermaid-container`'s near-white panel at a measured
// **1.17–1.29:1** and **1.26–1.39:1** — the same colour, for practical
// purposes. `P8-34` worked around it for its own surface with a per-diagram
// `%%{init:…}%%` directive and reported the rest; a per-caller workaround is
// not the fix (`Law 13`).
//
// **No DOM, no imports, no module state.** That is deliberate twice over: it
// lets `markdown.js` (which needs a DOM to load at all) and
// `tests/harness/mermaid_diagram_parse.js` (which has none) both drive the
// same code, and it is what lets the harness read a **computed** config
// instead of lifting a literal out of the source with a regex.
//
// **Nothing here invents a colour.** `mermaidTheme()` picks between two names
// Mermaid already ships, and the one stroke override is read back out of
// Mermaid's own answer (see `applyMermaidTheme`) rather than typed in. Sixteen
// palettes ship; a hex in this file would be right in one of them.

/**
 * Which of Mermaid's own themes each `color-scheme` gets.
 *
 * `neutral` rather than `default`: measured against the four light palettes'
 * panels, `neutral`'s arrows come in at 4.50–4.96:1 and its node text at
 * 16.28:1 on the node fill, and it is monochrome — which is the same reason
 * `P8-34` draws node *type* as a shape rather than a colour. `default` draws a
 * purple node outline that measures 2.95–3.25:1, under the 3:1 line on the
 * `light` palette.
 */
export const SCHEME_THEMES = Object.freeze({ light: 'neutral', dark: 'dark' });

/** The shipped default, for a document that has not said (`theme.js:35`). */
export const DEFAULT_SCHEME = 'dark';

/** The Mermaid theme name for a CSS `color-scheme` value. */
export function mermaidTheme(scheme) {
  return SCHEME_THEMES[String(scheme || '').trim()] || SCHEME_THEMES[DEFAULT_SCHEME];
}

/**
 * The `color-scheme` the palette wrote, or the shipped default.
 *
 * `theme.js:292` computes `_isLightBackground(colors.bg)` and writes the
 * answer onto `<html>` with `setProperty` every time a palette is applied —
 * and so do `index.html`'s and `login.html`'s first-paint scripts, which run
 * before any module boots. All three write it as an INLINE declaration on
 * `documentElement`, which is why this reads `.style` rather than deriving
 * luminance a fourth time (`Law 14`). Optional the whole way down: a missing
 * property is not a reason to refuse to draw a diagram.
 */
export function documentScheme(doc) {
  const root = (doc || (typeof document !== 'undefined' ? document : null));
  const el = root && root.documentElement;
  const raw = el && el.style && typeof el.style.getPropertyValue === 'function'
    ? el.style.getPropertyValue('color-scheme')
    : '';
  return String(raw || '').trim() || DEFAULT_SCHEME;
}

/**
 * The object `mermaid.initialize()` is called with.
 *
 * `startOnLoad: false` because every caller renders explicitly through
 * `renderMermaid`; `securityLevel: 'loose'` because labels are rendered as
 * HTML (which is why `workflowDiagram.js:mermaidText` escapes `<` and `>`).
 * Both were already in the call this replaces and neither changes here.
 */
export function mermaidConfig(scheme, themeVariables) {
  const config = {
    startOnLoad: false,
    theme: mermaidTheme(scheme),
    securityLevel: 'loose',
  };
  if (themeVariables && Object.keys(themeVariables).length) {
    config.themeVariables = { ...themeVariables };
  }
  return config;
}

/**
 * The strokes a diagram is read by, given the theme variables Mermaid computed.
 *
 * Mermaid's flowchart stylesheet is
 * `.node rect, .node circle, … { fill: ${mainBkg}; stroke: ${nodeBorder} }`,
 * so `nodeBorder` is the outline of every box and `lineColor` is every arrow.
 * Measured against `.mermaid-container`'s panel, `neutral`'s `nodeBorder`
 * (`#999`) comes in at **2.23–2.46:1** on the four light palettes — visible,
 * but under the 3:1 WCAG 1.4.11 line for a graphical object, and the node
 * fill is no help at 1.00–1.10:1. That matters more here than it would
 * elsewhere, because `P8-34` encodes what a node *is* (prompt / research /
 * action) purely as its shape, so an outline nobody can follow takes the
 * meaning with it.
 *
 * The fix is one line and it invents nothing: a box is outlined in the same
 * ink Mermaid already chose for the arrows between boxes. `lineColor` is read
 * back out of `mermaid.mermaidAPI.getConfig()` — Mermaid's own answer for the
 * theme it just loaded — so this file holds no colour of its own and a theme
 * that changes its palette upstream carries this with it.
 */
export function strokeOverrides(themeVariables) {
  const line = themeVariables && themeVariables.lineColor;
  return line ? { nodeBorder: line } : {};
}

/**
 * Tell a loaded Mermaid which theme to draw in, and answer what it decided.
 *
 * Takes the library rather than reaching for a global, so the test harness
 * drives exactly the function `markdown.js` calls, against the real vendored
 * bundle, with no DOM at all.
 *
 * Two `initialize` calls on purpose, and the second one is the measurement:
 * the first loads the theme, `getConfig()` is then asked what that theme's
 * own `lineColor` is, and the second applies it to `nodeBorder`. Reading the
 * answer back is the same trick `B334` established — a key Mermaid stopped
 * honouring comes back as a different value rather than as an error — and it
 * is what keeps a hex out of this file. Re-initialising does not accumulate:
 * measured on the vendored 11.x bundle, `initialize({theme:'neutral',
 * themeVariables:{nodeBorder:'#666'}})` followed by `initialize({theme:'dark'})`
 * comes back with `nodeBorder: '#ccc'`, not the override.
 *
 * Returns the config actually applied, so a caller can assert on it.
 */
export function applyMermaidTheme(mermaid, scheme) {
  const first = mermaidConfig(scheme);
  mermaid.initialize(first);
  const api = mermaid.mermaidAPI;
  const vars = (api && typeof api.getConfig === 'function' && api.getConfig().themeVariables) || null;
  const overrides = strokeOverrides(vars);
  if (!Object.keys(overrides).length) return first;
  const final = mermaidConfig(scheme, overrides);
  mermaid.initialize(final);
  return final;
}

export default {
  SCHEME_THEMES, DEFAULT_SCHEME, mermaidTheme, documentScheme, mermaidConfig,
  strokeOverrides, applyMermaidTheme,
};
