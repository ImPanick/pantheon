// SPDX-License-Identifier: AGPL-3.0-or-later
// Settings navigation primitives.
//
// This module owns panel activation and sidebar click routing only. Individual
// panels continue to own their data loading and side effects.

import {
  DEFAULT_SETTINGS_PANEL_ID,
  SETTINGS_GROUPS,
  SETTINGS_PANELS,
  isAdminManagedSettingsTab,
} from './registry.js';

const _boundModals = new WeakSet();

export function activateSettingsPanel(modalEl, tab) {
  if (!modalEl || !tab) return null;

  modalEl.querySelectorAll('[data-settings-tab]').forEach(button => {
    button.classList.toggle('active', button.dataset.settingsTab === tab);
  });
  modalEl.querySelectorAll('[data-settings-panel]').forEach(panel => {
    panel.classList.toggle('hidden', panel.dataset.settingsPanel !== tab);
  });
  return tab;
}

export function getActiveSettingsTab(modalEl, fallback = DEFAULT_SETTINGS_PANEL_ID) {
  if (!modalEl) return fallback;
  const active = modalEl.querySelector('[data-settings-tab].active');
  return active?.dataset?.settingsTab || fallback;
}

export function bindSettingsNavigation(modalEl, options = {}) {
  if (!modalEl || _boundModals.has(modalEl)) return;
  _boundModals.add(modalEl);

  const openAdminTab = options.openAdminTab;
  const onPanelActivated = options.onPanelActivated;

  modalEl.querySelectorAll('[data-settings-tab]').forEach(button => {
    button.addEventListener('click', () => {
      const tab = button.dataset.settingsTab;
      if (!tab) return;

      // Preserve the existing lazy-admin path: when the admin module accepts
      // the tab, it owns activation/rendering and the Settings shell does not
      // perform a second local switch.
      if (
        isAdminManagedSettingsTab(tab)
        && typeof openAdminTab === 'function'
        && openAdminTab(tab, button) === true
      ) {
        return;
      }

      activateSettingsPanel(modalEl, tab);
      if (typeof onPanelActivated === 'function') {
        onPanelActivated(tab, button);
      }
    });
  });
}


/**
 * `P9-02` — the Settings navigation, drawn from the registry that describes it.
 *
 * **The row's premise, confirmed and then made concrete 2026-09-18.** It said
 * there were two sources of truth for one information architecture and that the
 * registry was consumed only by search. Both are still true, and running the
 * self-check the row points at — `getSettingsRegistryIssues()`, which
 * `settings.js` has called on every init since it was written — shows they had
 * **already diverged**: the markup carried fifteen tabs and fifteen panels, the
 * registry carried fourteen, and the missing one was `networks`.
 *
 * That is not a tidiness defect. `P17-09` shipped the operator's network
 * allowlist — the thing `Law 16` is enforced with — as a tab, a panel and a
 * module, and without a registry entry it was **unfindable in Settings search
 * by any word**, including its own name. The self-check said so, into
 * `console.warn`, where nobody reads it. `Law 15`: a check whose output nobody
 * sees is not a check.
 *
 * **What moved and what did not.** The class name and the data attribute are
 * untouched — `.settings-nav-item` and `data-settings-tab` are queried by
 * `slashCommands.js` (nine selectors, for the tour), `calendar.js` (four),
 * `admin.js`, `emailLibrary.js` and `settings.js` itself, and the CSS keys off
 * both. `admin-only` is untouched too, because `syncAdminVisibility()` hides by
 * that class. The order is the registry's order, which was already written to
 * mirror the sidebar, and the group dividers and the one heading are now
 * properties of `SETTINGS_GROUPS` rather than markup a person keeps in step by
 * hand.
 *
 * **Why this runs at module load rather than in `initAll()`.** `settings.js`
 * initialises lazily, on the first `open()`. Four call sites in `calendar.js`
 * and one in `emailLibrary.js` reach past that API — they un-hide
 * `#settings-modal` themselves and then `querySelector('[data-settings-tab=…]')
 * .click()` — so a nav built inside `initAll` would not exist yet for any of
 * them. Rendering when the module is evaluated keeps every one of those paths
 * working exactly as before.
 *
 * The icons are fixed strings defined in `registry.js` in this repository; no
 * caller text reaches `innerHTML`.
 */
export function renderSettingsNav(modalEl, options = {}) {
  if (!modalEl || typeof modalEl.querySelector !== 'function') return null;
  const list = modalEl.querySelector('.settings-nav-list');
  if (!list) return null;

  const active = options.active
    || modalEl.querySelector('[data-settings-tab].active')?.dataset?.settingsTab
    || DEFAULT_SETTINGS_PANEL_ID;

  const doc = list.ownerDocument || (typeof document === 'undefined' ? null : document);
  if (!doc) return null;
  const make = (tag, className) => {
    const node = doc.createElement(tag);
    if (className) node.className = className;
    return node;
  };

  list.innerHTML = '';
  let drawn = 0;
  for (const group of SETTINGS_GROUPS) {
    const panels = SETTINGS_PANELS.filter(panel => panel.group === group.id);
    if (!panels.length) continue;

    // A rule between groups, never above the first one — the same shape the
    // markup drew, and the reason the divider is derived rather than listed.
    if (drawn) list.appendChild(make('div', 'settings-sidebar-divider' + (group.adminOnly ? ' admin-only' : '')));
    if (group.heading) {
      const heading = make('div', 'settings-sidebar-label' + (group.adminOnly ? ' admin-only' : ''));
      heading.textContent = group.heading;
      list.appendChild(heading);
    }

    for (const panel of panels) {
      const button = make(
        'button',
        'settings-nav-item'
          + (panel.id === active ? ' active' : '')
          + (panel.adminOnly ? ' admin-only' : ''),
      );
      // `P10-02`'s reason, one row over: without an explicit type a <button>
      // inside a form submits it, and "none of these is in a form" is the kind
      // of fact that changes later and takes the page's state with it.
      button.type = 'button';
      // Both spellings on purpose. In a browser these are one thing, but the
      // readers are split: `navigation.js` and `search.js` read
      // `dataset.settingsTab`, while `slashCommands.js`, `calendar.js`,
      // `admin.js` and `emailLibrary.js` use `[data-settings-tab="…"]`
      // selectors — and the DOM shim the tests drive keeps the two apart.
      button.dataset.settingsTab = panel.id;
      button.setAttribute('data-settings-tab', panel.id);
      if (panel.icon) {
        const icon = make('span', 'settings-nav-item-icon');
        icon.innerHTML = panel.icon;
        button.appendChild(icon);
      }
      const label = make('span', '');
      label.textContent = panel.label;
      button.appendChild(label);
      list.appendChild(button);
    }
    drawn += 1;
  }
  return list;
}
