// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/markdown/math.js
//
// `B1996`. The chat's deferred KaTeX renderer, in a module of its own.
//
// A Deep Research report page (`src/visual_report.py`) typesets the formulas
// its Markdown left pending with the renderer the chat uses. It cannot import
// `markdown.js` to get it: that imports `ui.js`, which imports `theme.js`, and
// at import they add document listeners and a MutationObserver, fetch
// `/api/img/mode` and `/api/prefs/theme`, and write the chat's palette over
// the CSS variables the report page styles itself with. This module imports
// nothing and does nothing until it is called. `markdown.js` imports its
// loader and its placeholder class from here, so the chat and the report keep
// one renderer between them.

// KaTeX is vendored under /static/lib and fetched on first use, like Mermaid
// (see `markdown.js`).
const KATEX_SRC = '/static/lib/katex/katex.min.js';
const KATEX_CSS = '/static/lib/katex/katex.min.css';
// Marks math emitted before KaTeX finished loading; renderMath() swaps these
// for typeset output. The source stays as readable text inside the span, so a
// load that never completes degrades to plain text rather than to nothing.
const MATH_PENDING_CLASS = 'pan-math-pending';

let _katexPromise = null;

function _loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = src;
    script.addEventListener('load', () => resolve(), { once: true });
    script.addEventListener('error', () => reject(new Error('Failed to load ' + src)), { once: true });
    document.head.appendChild(script);
  });
}

function _loadStylesheet(href) {
  // Resolves either way: without the stylesheet KaTeX still produces correct
  // markup, just unstyled, which beats failing the whole math render.
  return new Promise((resolve) => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    link.addEventListener('load', () => resolve(), { once: true });
    link.addEventListener('error', () => resolve(), { once: true });
    document.head.appendChild(link);
  });
}

/**
 * Load KaTeX (script + stylesheet) on first use.
 */
function ensureKatex() {
  return (_katexPromise ??= Promise.all([_loadScript(KATEX_SRC), _loadStylesheet(KATEX_CSS)])
    .then(() => {
      if (!window.katex) throw new Error('katex global missing after load');
      return window.katex;
    })
    .catch((err) => {
      _katexPromise = null;
      throw err;
    }));
}

/**
 * Typeset any math that mdToHtml() had to defer because KaTeX was not loaded
 * yet. Once KaTeX is in, mdToHtml() renders inline and this finds nothing.
 * A research report's page calls it for the placeholders `src/report_math.py`
 * leaves in the report (`B1996`).
 */
function renderMath(container) {
  const target = container || document;
  if (!target || typeof target.querySelectorAll !== 'function') return Promise.resolve();
  if (target.querySelectorAll('.' + MATH_PENDING_CLASS).length === 0) return Promise.resolve();
  return ensureKatex()
    .then((katex) => {
      target.querySelectorAll('.' + MATH_PENDING_CLASS).forEach((el) => {
        const displayMode = el.getAttribute('data-display') === 'true';
        try {
          el.outerHTML = katex.renderToString(el.textContent || '', { displayMode, throwOnError: false });
        } catch (e) {
          // Leave the source visible — readable, just not typeset.
          el.classList.remove(MATH_PENDING_CLASS);
        }
      });
    })
    .catch((e) => { console.warn('KaTeX render error:', e); });
}

export { KATEX_SRC, KATEX_CSS, MATH_PENDING_CLASS, _loadScript, _loadStylesheet, ensureKatex, renderMath };
