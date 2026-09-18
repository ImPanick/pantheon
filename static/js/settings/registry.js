// SPDX-License-Identifier: AGPL-3.0-or-later
// Canonical metadata for the existing Settings information architecture.
//
// This module describes Settings; it does not render the sidebar, load panel
// data, or own panel behavior. Keeping those concerns separate lets the
// current markup remain stable while navigation/search code shares one source
// of truth for panel identity and ownership.

function defineGroup(definition) {
  return Object.freeze({ ...definition });
}

function definePanel(definition) {
  return Object.freeze({
    controller: 'settings',
    adminOnly: false,
    icon: '',
    ...definition,
    keywords: Object.freeze([...(definition.keywords || [])]),
  });
}

export const SETTINGS_GROUPS = Object.freeze([
  defineGroup({
    id: 'models',
    label: 'Models & AI',
  }),
  defineGroup({
    id: 'communications',
    label: 'Communications',
  }),
  defineGroup({
    id: 'experience',
    label: 'Experience',
  }),
  defineGroup({
    id: 'account',
    label: 'Account',
  }),
  defineGroup({
    id: 'administration',
    label: 'Administration',
    adminOnly: true,
    // `P9-02`. The nav draws one heading and four dividers. Only this group has
    // ever carried a visible label — the other four are separated by a rule and
    // nothing else — so the heading is a property of the group rather than a
    // rule the renderer invents.
    heading: 'Admin',
  }),
]);

// Order intentionally mirrors the existing Settings sidebar.
export const SETTINGS_PANELS = Object.freeze([
  definePanel({
    id: 'services',
    icon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14"/><path d="M5 12h14"/></svg>',
    label: 'Add Models',
    group: 'models',
    controller: 'admin',
    keywords: ['models', 'provider', 'endpoint'],
  }),
  definePanel({
    id: 'added-models',
    icon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    label: 'Added Models',
    group: 'models',
    controller: 'admin',
    keywords: ['models', 'configured', 'provider', 'endpoint'],
  }),
  definePanel({
    id: 'ai',
    icon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a4 4 0 0 0-4 4v2H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10a2 2 0 0 0-2-2h-2V6a4 4 0 0 0-4-4z"/></svg>',
    label: 'AI Defaults',
    group: 'models',
    keywords: ['ai', 'defaults', 'model', 'vision', 'image', 'tts', 'stt'],
  }),
  definePanel({
    id: 'search',
    icon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
    label: 'Search',
    group: 'models',
    keywords: ['search', 'research', 'provider'],
  }),

  definePanel({
    id: 'integrations',
    icon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>',
    label: 'Integrations',
    group: 'communications',
    controller: 'admin',
    keywords: ['integrations', 'connections', 'services'],
  }),
  definePanel({
    id: 'email',
    icon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>',
    label: 'Email',
    group: 'communications',
    keywords: ['email', 'imap', 'smtp', 'oauth'],
  }),
  definePanel({
    id: 'reminders',
    icon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>',
    label: 'Reminders',
    group: 'communications',
    keywords: ['reminders', 'notifications', 'alerts'],
  }),

  definePanel({
    id: 'appearance',
    icon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 2a7 7 0 0 0 0 20 4 4 0 0 1 0-8 4 4 0 0 0 0-8"/></svg>',
    label: 'Appearance',
    group: 'experience',
    // `H15` — the four words the row named. Harvesting control text makes
    // "Sensitive Blur" findable by its own label and by "secrets", which is
    // most of the fix; it cannot make it findable by *privacy*, *security* or
    // *redact*, because none of those words is anywhere in the markup. That
    // matters because this panel holds the app's only privacy control, it ships
    // OFF, and there is no Privacy or Security panel among the thirteen — so
    // someone about to share their screen types the category, not the label.
    keywords: ['appearance', 'theme', 'font', 'density', 'peek',
               'privacy', 'security', 'redact', 'blur', 'sensitive'],
  }),
  definePanel({
    id: 'shortcuts',
    icon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h.01M12 12h.01M16 12h.01M7 16h10"/></svg>',
    label: 'Shortcuts',
    group: 'experience',
    keywords: ['shortcuts', 'keyboard', 'hotkeys'],
  }),

  definePanel({
    id: 'account',
    icon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
    label: 'Account',
    group: 'account',
    keywords: ['account', 'password', 'logout'],
  }),

  definePanel({
    id: 'tools',
    icon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
    label: 'Agent Tools',
    group: 'administration',
    controller: 'admin',
    adminOnly: true,
    keywords: ['agent', 'tools'],
  }),
  definePanel({
    id: 'users',
    icon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    label: 'Users',
    group: 'administration',
    controller: 'admin',
    adminOnly: true,
    keywords: ['users', 'accounts', 'admin'],
  }),
  definePanel({
    id: 'embeddings',
    icon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><circle cx="5" cy="6" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="5" cy="18" r="2"/><circle cx="19" cy="18" r="2"/><line x1="7" y1="7" x2="10" y2="10"/><line x1="17" y1="7" x2="14" y2="10"/><line x1="7" y1="17" x2="10" y2="14"/><line x1="17" y1="17" x2="14" y2="14"/></svg>',
    label: 'Embeddings',
    group: 'administration',
    controller: 'admin',
    adminOnly: true,
    // `H04`. Searchable by what a person would actually type when their
    // memory or documents stop being found, which is the symptom that
    // brings anyone here.
    keywords: ['embeddings', 'embedding', 'vector', 'rag', 'memory',
               'fastembed', 'chroma', 'model', 'search'],
  }),
  definePanel({
    id: 'networks',
    icon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="2" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="16" y="16" width="6" height="6" rx="1"/><path d="M12 8v4"/><path d="M5 16v-2h14v2"/></svg>',
    label: 'Networks',
    group: 'administration',
    adminOnly: true,
    // `P9-02`, and the reason this row exists. `P17-09` added the tab, the
    // panel and the module and did not add the registry entry, so Settings
    // search — the registry's only consumer until now — could not find the
    // operator's network allowlist by any word at all. `getSettingsRegistryIssues()`
    // had been reporting it into `console.warn` the whole time.
    //
    // `controller` stays 'settings' DELIBERATELY. Every other Administration
    // panel is 'admin', which routes the click through
    // `openAdminTab` -> `window.adminModule.open(tab)`; `admin.js` has no case
    // for 'networks' and this panel is activated by
    // `onSettingsPanelActivated` in `settings.js`, which lazy-imports
    // `networks.js`. Marking it 'admin' to match its neighbours would send the
    // click somewhere that does not draw it.
    keywords: ['networks', 'network', 'allowlist', 'allow list', 'egress',
               'outbound', 'firewall', 'lan', 'subnet', 'cidr', 'host',
               'blocked', 'internet', 'offline'],
  }),
  definePanel({
    id: 'system',
    icon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v-.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09A1.65 1.65 0 0 0 19.4 15z"/></svg>',
    label: 'System',
    group: 'administration',
    controller: 'admin',
    adminOnly: true,
    // `B95`. The three switches an operator could previously only reach by
    // hand-writing `data/settings.json` live in this panel now, so the words
    // someone types when they want them are here too. `download` and
    // `huggingface` matter most: the `Law 16` gate is the one a person goes
    // looking for after a diagnostic tells them to turn it on.
    keywords: ['system', 'admin', 'server',
               'metrics', 'prometheus', 'scrape',
               'download', 'huggingface', 'model download', 'offline',
               'searxng', 'engines', 'widen'],
  }),
]);

export const DEFAULT_SETTINGS_PANEL_ID = 'services';

const _panelsById = new Map(
  SETTINGS_PANELS.map(panel => [panel.id, panel]),
);

export function getSettingsPanel(id) {
  return _panelsById.get(String(id || '')) || null;
}

export function getSettingsPanelsForGroup(groupId) {
  return SETTINGS_PANELS.filter(panel => panel.group === groupId);
}

export function isAdminManagedSettingsTab(id) {
  return getSettingsPanel(id)?.controller === 'admin';
}

export function isAdminOnlySettingsTab(id) {
  return getSettingsPanel(id)?.adminOnly === true;
}

export function getSettingsPanelSearchText(panelOrId, controlText = '') {
  const panel = typeof panelOrId === 'string'
    ? getSettingsPanel(panelOrId)
    : panelOrId;

  if (!panel) return '';

  return [
    panel.label,
    ...(panel.keywords || []),
    controlText,
  ].join(' ').toLowerCase();
}

/**
 * The text of every control inside a panel, harvested from the markup (`H15`).
 *
 * Settings search indexed 13 panel labels and **zero of the 96 controls**, so
 * 31 of the 32 labelled toggles in Appearance were unfindable by any word in
 * their own label — *Incognito Mode*, *Deep Research*, *Shell*, *Web Search*.
 *
 * The sharpest case is why this is not cosmetic. **Sensitive Blur** — *"blur
 * emails, tokens, and secrets in AI output"* — is the app's only privacy
 * control, ships OFF, and lives under Appearance, because there is no Privacy
 * or Security panel among the thirteen. Typing *privacy*, *secret*, *redact* or
 * *security* returned nothing. Someone about to share their screen could not
 * find the feature that hides their API keys.
 *
 * HARVESTED, NOT LISTED. A hand-written keyword list for 96 controls is a
 * second copy of the labels that starts drifting the day someone renames one,
 * and this codebase has spent several rows on exactly that failure. The markup
 * is the source of truth; `data-settings-panel="<id>"` already links a panel to
 * its subtree.
 */
export function harvestSettingsControlText(modalEl) {
  if (!modalEl || typeof modalEl.querySelectorAll !== 'function') return {};
  const out = {};
  for (const container of modalEl.querySelectorAll('[data-settings-panel]')) {
    const id = container.dataset && container.dataset.settingsPanel;
    if (!id) continue;
    const parts = [];
    // Labels, headings and the sentence under a toggle — the words a person
    // would actually type. Not `input` values or ids, which are machine names
    // and would match half the app on a two-letter query.
    for (const el of container.querySelectorAll(
      'label, h2, h3, h4, legend, option, .settings-row-title, .settings-row-desc, ' +
      '[data-search-text], [placeholder], [title]')) {
      const text = (el.textContent || '').trim();
      if (text && text.length < 200) parts.push(text);
      for (const attr of ('placeholder', 'title', 'data-search-text')) {
        const value = el.getAttribute && el.getAttribute(attr);
        if (value && value.length < 200) parts.push(value);
      }
    }
    out[id] = parts.join(' ').toLowerCase();
  }
  return out;
}

function normalizeSettingsSearch(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ');
}

export function searchSettingsPanels(query, options = {}) {
  const normalized = normalizeSettingsSearch(query);
  if (!normalized) return [];

  const terms = normalized.split(' ');
  const isAdmin = options.isAdmin === true;

  return SETTINGS_PANELS.filter(panel => {
    if (panel.adminOnly && !isAdmin) return false;

    const haystack = getSettingsPanelSearchText(
      panel, (options.controlText || {})[panel.id] || '');
    return terms.every(term => haystack.includes(term));
  });
}

export function getSettingsRegistryIssues(modalEl) {
  if (!modalEl) return ['Settings modal is unavailable'];

  const tabIds = Array.from(
    modalEl.querySelectorAll('[data-settings-tab]'),
    element => element.dataset.settingsTab,
  ).filter(Boolean);

  const panelIds = Array.from(
    modalEl.querySelectorAll('[data-settings-panel]'),
    element => element.dataset.settingsPanel,
  ).filter(Boolean);

  const registryIds = SETTINGS_PANELS.map(panel => panel.id);
  const issues = [];

  const duplicates = ids => ids.filter(
    (id, index) => ids.indexOf(id) !== index,
  );

  for (const id of new Set(duplicates(tabIds))) {
    issues.push(`Duplicate Settings tab: ${id}`);
  }
  for (const id of new Set(duplicates(panelIds))) {
    issues.push(`Duplicate Settings panel: ${id}`);
  }

  for (const id of registryIds) {
    if (!tabIds.includes(id)) issues.push(`Registry tab missing from DOM: ${id}`);
    if (!panelIds.includes(id)) issues.push(`Registry panel missing from DOM: ${id}`);
  }

  for (const id of tabIds) {
    if (!registryIds.includes(id)) issues.push(`DOM tab missing from registry: ${id}`);
  }
  for (const id of panelIds) {
    if (!registryIds.includes(id)) issues.push(`DOM panel missing from registry: ${id}`);
  }

  return issues;
}
