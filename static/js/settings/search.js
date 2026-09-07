// SPDX-License-Identifier: AGPL-3.0-or-later
import {
  SETTINGS_GROUPS,
  getSettingsPanel,
  harvestSettingsControlText,
  searchSettingsPanels,
} from './registry.js';

const _boundModals = new WeakSet();

// `H15`. The control index, harvested from the markup the first time somebody
// searches and re-harvested when the modal's contents change.
//
// Lazy rather than at load: panels are populated as they are opened, so
// building this at startup would index whatever happened to exist then and
// quietly miss the rest — which is a subtler version of the bug being fixed.
const _controlText = new WeakMap();

function controlTextFor(modalEl) {
  if (!modalEl) return {};
  const cached = _controlText.get(modalEl);
  // Re-harvest when a panel that had no text now has some: panel bodies are
  // filled in on first open, and a cache taken before that is a cache of
  // nothing.
  const fresh = harvestSettingsControlText(modalEl);
  const gained = !cached || Object.keys(fresh).some(
    id => (fresh[id] || '').length > (cached[id] || '').length);
  if (gained) {
    _controlText.set(modalEl, fresh);
    return fresh;
  }
  return cached;
}

function groupLabelFor(panel) {
  const group = SETTINGS_GROUPS.find(candidate => candidate.id === panel.group);
  return group?.label || '';
}

function clearResults(resultsEl) {
  if (!resultsEl) return;
  resultsEl.replaceChildren();
  resultsEl.classList.add('hidden');
}

function getResultButtons(resultsEl) {
  if (!resultsEl) return [];
  return Array.from(resultsEl.querySelectorAll('[data-settings-search-result]'));
}

function setActiveResult(resultsEl, index) {
  const buttons = getResultButtons(resultsEl);
  if (!buttons.length) return -1;

  let next = index;
  if (next < 0) next = buttons.length - 1;
  if (next >= buttons.length) next = 0;

  buttons.forEach((button, buttonIndex) => {
    const active = buttonIndex === next;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
  });

  if (typeof buttons[next].scrollIntoView === 'function') {
    buttons[next].scrollIntoView({ block: 'nearest' });
  }

  return next;
}

export function bindSettingsSearch(modalEl, options = {}) {
  if (!modalEl || _boundModals.has(modalEl)) return;

  const input = modalEl.querySelector('#settings-nav-search');
  const resultsEl = modalEl.querySelector('#settings-nav-search-results');

  if (!input || !resultsEl) return;
  _boundModals.add(modalEl);

  const isAdmin = typeof options.isAdmin === 'function'
    ? options.isAdmin
    : () => false;

  const openPanel = typeof options.openPanel === 'function'
    ? options.openPanel
    : () => {};

  let activeIndex = -1;

  function reset() {
    input.value = '';
    activeIndex = -1;
    clearResults(resultsEl);
  }

  function activateResult(button) {
    const panelId = button?.dataset?.settingsSearchResult;
    if (!panelId || !getSettingsPanel(panelId)) return;

    openPanel(panelId);
    reset();
  }

  function render() {
    const query = input.value.trim();
    activeIndex = -1;
    resultsEl.replaceChildren();

    if (!query) {
      resultsEl.classList.add('hidden');
      return;
    }

    const matches = searchSettingsPanels(query, {
      isAdmin: isAdmin(),
      controlText: controlTextFor(modalEl),
    });

    if (!matches.length) {
      const empty = document.createElement('div');
      empty.className = 'settings-search-empty';
      empty.textContent = 'No settings found';
      resultsEl.appendChild(empty);
      resultsEl.classList.remove('hidden');
      return;
    }

    for (const panel of matches) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'settings-search-result';
      button.setAttribute('data-settings-search-result', panel.id);
      button.setAttribute('role', 'option');
      button.setAttribute('aria-selected', 'false');

      const label = document.createElement('span');
      label.className = 'settings-search-result-label';
      label.textContent = panel.label;

      const group = document.createElement('span');
      group.className = 'settings-search-result-group';
      group.textContent = groupLabelFor(panel);

      button.append(label, group);
      button.addEventListener('click', () => activateResult(button));
      resultsEl.appendChild(button);
    }

    resultsEl.classList.remove('hidden');
  }

  input.addEventListener('input', render);

  input.addEventListener('focus', () => {
    if (input.value.trim()) render();
  });

  input.addEventListener('keydown', event => {
    const buttons = getResultButtons(resultsEl);

    if (event.key === 'Escape') {
      if (!input.value && resultsEl.classList.contains('hidden')) return;
      event.preventDefault();
      event.stopPropagation();
      reset();
      return;
    }

    if (!buttons.length) return;

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      activeIndex = setActiveResult(resultsEl, activeIndex + 1);
      return;
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      activeIndex = setActiveResult(resultsEl, activeIndex - 1);
      return;
    }

    if (event.key === 'Enter') {
      const target = buttons[activeIndex >= 0 ? activeIndex : 0];
      if (!target) return;
      event.preventDefault();
      activateResult(target);
    }
  });

  modalEl.addEventListener('mousedown', event => {
    if (event.target === input || resultsEl.contains(event.target)) return;
    clearResults(resultsEl);
    activeIndex = -1;
  });

  return { reset, render };
}
