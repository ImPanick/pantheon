// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/pickerKeys.js
//
// The keyboard of the composer's pickers — one implementation for every menu
// that pops up from the chat bar.
//
// `B1706`. This was `_handlePickerKeydown` inside `modelPicker.js`, private to
// the model picker. The approval-mode selector is the composer's second picker,
// and a second copy of the arrow-key walk would be the second scaffold `Law 14`
// forbids, so it moved here whole and both import it. The model picker calls it
// exactly as before: Arrow keys move a `.kb-active` highlight through the
// rendered items while the focus stays in its search box, Enter picks the
// highlighted item (or the first), Escape closes.
//
// A menu with no box to type in passes `{ roving: true }`: the highlight then
// takes the focus with it, so the item a screen reader announces is the item
// Enter will pick, and Space picks it too — in a search box Space is a letter,
// which is why it is opt-in. No module imports, so anything can share it.

/**
 * @param {KeyboardEvent} e
 * @param {Element} listEl        the element holding the items
 * @param {string} itemSelector   what an item is, e.g. `.model-switch-item`
 * @param {Function} closeFn      closes the menu
 * @param {{roving?: boolean}} [opts]
 */
export function handlePickerKeydown(e, listEl, itemSelector, closeFn, opts) {
  const roving = !!(opts && opts.roving);
  if (e.key === 'Escape') { closeFn(); return; }
  if (e.key === 'Enter' || (roving && e.key === ' ')) {
    e.preventDefault();
    const active = listEl.querySelector(itemSelector + '.kb-active') || listEl.querySelector(itemSelector);
    if (active) active.click();
    return;
  }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    const items = [...listEl.querySelectorAll(itemSelector)].filter(el => el.style.display !== 'none');
    if (!items.length) return;
    const cur = items.findIndex(el => el.classList.contains('kb-active'));
    items.forEach(el => el.classList.remove('kb-active'));
    let next;
    if (e.key === 'ArrowDown') next = cur < items.length - 1 ? cur + 1 : 0;
    else next = cur > 0 ? cur - 1 : items.length - 1;
    items[next].classList.add('kb-active');
    if (typeof items[next].scrollIntoView === 'function') items[next].scrollIntoView({ block: 'nearest' });
    // The walk above already brought the row into the list's view; a focus
    // that scrolled as well could slide an `overflow: hidden` ancestor.
    if (roving && typeof items[next].focus === 'function') items[next].focus({ preventScroll: true });
  }
}

export default { handlePickerKeydown };
