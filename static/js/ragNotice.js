// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/ragNotice.js

/**
 * `B1287`. The RAG chip on, with the document index off, said nothing: a turn
 * carried no `rag_sources` and no word that retrieval had not happened, while
 * the RAG window said why (`rag.js`, `_showHealth`). The server now sends a
 * turn like that one `rag_sources` frame with no sources and `off` — the same
 * sentence the RAG window shows — and this module is what the chat does with
 * it: the chip says it (its `title` and `aria-label`), and a toast says it
 * once, not on every turn; a different reason is news again, and a turn that
 * searched clears both.
 *
 * No imports: the chip is found by id in the document handed in, and the toast
 * is the caller's (`uiModule.showToast`), so this runs under node as it runs
 * in the page.
 */

const CHIP_ID = 'rag-indicator-btn';
const CHIP_TITLE = 'RAG';

let _said = '';

/**
 * Read one `rag_sources` frame. `off` is the sentence, or empty when the turn
 * searched (with or without results).
 */
export function noteRagFrame(doc, frame, toast) {
  const off = frame && typeof frame.off === 'string' ? frame.off.trim() : '';
  const chip = doc && typeof doc.getElementById === 'function' ? doc.getElementById(CHIP_ID) : null;
  if (chip) {
    chip.title = off ? `${CHIP_TITLE} — ${off}` : CHIP_TITLE;
    if (off) chip.setAttribute('aria-label', `${CHIP_TITLE} is on, but did not search: ${off}`);
    else chip.removeAttribute('aria-label');
  }
  if (!off) {
    _said = '';
    return false;
  }
  if (off === _said) return false;
  _said = off;
  if (typeof toast === 'function') toast(off, 8000);
  return true;
}

export default { noteRagFrame };
