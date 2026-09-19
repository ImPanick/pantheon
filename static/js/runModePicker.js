// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/runModePicker.js

/**
 * `P5-17`. One run-mode picker.
 *
 * `P6-06` shipped the queue's sequential-vs-parallel popover as a **clone** of
 * `research/panel.js`'s `_promptParallelOrSequential`, and said so in its own
 * comment rather than pretending otherwise. Re-measured 2026-09-19 the two
 * were identical in the popover's class name, both row class names, the two
 * glyphs (byte for byte), the drop-down-or-flip-up positioning arithmetic, the
 * 6px margin, the 8px right clamp, the `rrm-up` / `rrm-down` marker, the
 * `_rrmClose` toggle-shut contract and both capture-phase dismissals.
 *
 * **They differed in four things, not the three the row counted:** the popover
 * id, the row titles and subtitles, what a row calls — and **the row order**.
 * The queue lists sequential first and research lists parallel first. That
 * fourth one is why this module takes an ordered `rows` array rather than a
 * pair of named callbacks: a shared picker that silently reordered one of its
 * two callers would be a `Law 15` regression of the same kind the row warns
 * about, arriving through the parameter list nobody thought to check.
 *
 * **Why parameterised and not simply shared.** The row is explicit and it is
 * right: the queue's subtitle reads *"Opens N new chats, one per message"*,
 * and the research panel opens no chats. Shipping that string to both is worse
 * than the duplication it removes. So every word a caller shows is a caller's
 * word, and this module owns only the mechanism.
 *
 * **The defect that was fixed in two places is now fixable in one.** Both
 * copies leaked their two capture-phase document listeners on the toggle-shut
 * path — clicking the anchor a second time removed the element and left the
 * pair attached to a detached node, accumulating one pair per toggle. Patched
 * in both files on 2026-08-29; one implementation means one patch next time.
 */

/** The parallel / sequential glyphs. Identical in both copies; defined once. */
export const ICON_PARALLEL =
  '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="18" x2="20" y2="18"/></svg>';
export const ICON_SEQUENTIAL =
  '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="8" y1="6" x2="20" y2="6"/><line x1="8" y1="12" x2="20" y2="12"/><line x1="8" y1="18" x2="20" y2="18"/><circle cx="4" cy="6" r="1.5" fill="currentColor"/><circle cx="4" cy="12" r="1.5" fill="currentColor"/><circle cx="4" cy="18" r="1.5" fill="currentColor"/></svg>';

const GLYPHS = { parallel: ICON_PARALLEL, sequential: ICON_SEQUENTIAL };

/** Escape a caller's string before it goes through `innerHTML`.
 *  The queue's subtitle interpolates a count and a caller could one day
 *  interpolate a query, so the label path is not a place to trust input. */
function esc(text) {
  return String(text == null ? '' : text)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Open the run-mode popover anchored to a button, or close it if it is open.
 *
 * `id`      the popover's element id — distinct per caller so two panels open
 *           at once do not close each other.
 * `anchor`  the button it drops from. Falsy is a no-op, as before.
 * `rows`    ordered `[{ mode, title, sub, onSelect }]`. `mode` picks the glyph
 *           and is written to `data-mode`; `sub` is optional and the research
 *           panel deliberately passes none.
 */
export function promptRunMode({ id, anchor, rows }) {
  // Toggle-shut must run the *same* teardown the outside-click path runs.
  // Removing the element alone leaves both capture-phase document listeners
  // attached to a detached popover, and they accumulate one pair per toggle.
  const existing = document.getElementById(id);
  if (existing) {
    if (typeof existing._rrmClose === 'function') existing._rrmClose();
    else existing.remove();
    return null;
  }
  if (!anchor || !Array.isArray(rows) || !rows.length) return null;

  const rect = anchor.getBoundingClientRect();
  const pop = document.createElement('div');
  pop.id = id;
  pop.className = 'research-run-mode-popover';
  pop.innerHTML = rows.map(row => {
    const glyph = GLYPHS[row.mode] || '';
    const label = row.sub
      ? '<span class="rrm-label"><span class="rrm-title">' + esc(row.title)
        + '</span><span class="rrm-sub">' + esc(row.sub) + '</span></span>'
      : '<span class="rrm-title">' + esc(row.title) + '</span>';
    return '<button class="research-run-mode-row" data-mode="' + esc(row.mode) + '">'
      + glyph + label + '</button>';
  }).join('');
  document.body.appendChild(pop);

  // Position: prefer dropping down from the button's bottom-right corner.
  // If there isn't enough room below the viewport, flip to drop-up above.
  const popHeight = pop.offsetHeight;
  const margin = 6;
  const spaceBelow = window.innerHeight - rect.bottom;
  const goUp = spaceBelow < popHeight + margin && rect.top > popHeight + margin;
  const top = goUp ? (rect.top - popHeight - margin) : (rect.bottom + margin);
  // Right-align to the button so the menu doesn't extend off-screen on the right
  const right = Math.max(8, window.innerWidth - rect.right);
  pop.style.top = `${Math.round(top)}px`;
  pop.style.right = `${Math.round(right)}px`;
  pop.classList.add(goUp ? 'rrm-up' : 'rrm-down');

  const close = () => {
    pop.remove();
    document.removeEventListener('click', onDocClick, true);
    document.removeEventListener('keydown', onKey, true);
  };
  pop._rrmClose = close;
  const onDocClick = (e) => {
    if (pop.contains(e.target) || e.target === anchor) return;
    close();
  };
  const onKey = (e) => { if (e.key === 'Escape') { e.preventDefault(); close(); } };
  setTimeout(() => {
    document.addEventListener('click', onDocClick, true);
    document.addEventListener('keydown', onKey, true);
  }, 0);

  const byMode = new Map(rows.map(row => [row.mode, row]));
  pop.querySelectorAll('.research-run-mode-row').forEach(b => {
    b.addEventListener('click', () => {
      const row = byMode.get(b.dataset.mode);
      close();
      if (row && typeof row.onSelect === 'function') row.onSelect();
    });
  });
  return pop;
}

export default { promptRunMode, ICON_PARALLEL, ICON_SEQUENTIAL };
