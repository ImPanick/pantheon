// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/ui_visibility.js
//
// Per-item visibility for the sidebar and collapsed icon rail. Drives the
// Settings → Appearance ("Customize UI") checkboxes, persisted in localStorage
// under `pantheon-ui-visibility` (loaded/saved by app.js).
//
// Each key maps to the CSS selector(s) it controls. Tool/section selectors pair
// the full-sidebar element with its #rail-* launcher so a tab hidden in the
// full view also hides when the sidebar is minimized to the icon rail (id
// mapping mirrors _railToolMap in app.js; #tool-library-btn ↔ #rail-archive).
//
// `P23-03` (C-VIS) adds the one table every door reads — `TOOL_VISIBILITY` —
// and the one applier, below `resolveVisibility`.

// Selector map: UI customization key → CSS selector(s) for its target(s).
export const UI_VIS_MAP = {
  'sidebar-brand':       '.sidebar-brand-title',
  'sidebar-new-chat':    '#sidebar-new-chat-btn',
  'sidebar-search':      '#sidebar-search-btn',
  'sessions-section':   '#sessions-section',
  'email-section':       '#email-section, #rail-email',
  'tools-section':       '#tools-section',
  // Per-tool entries pair the sidebar button with its rail launcher.
  'tool-assistant':      '#tool-assistant-btn, #rail-assistant',   // B1044
  'tool-calendar':       '#tool-calendar-btn, #rail-calendar',
  'tool-compare':        '#tool-compare-btn, #rail-compare',
  'tool-cookbook':       '#tool-cookbook-btn, #rail-cookbook',
  'tool-research':       '#tool-research-btn, #rail-research',
  'tool-gallery':        '#tool-gallery-btn, #rail-gallery',
  'tool-library':        '#tool-library-btn, #rail-archive',
  'tool-memory':         '#tool-memory-btn, #rail-memory',
  'tool-notes':          '#tool-notes-btn, #rail-notes',
  'tool-tasks':          '#tool-tasks-btn, #rail-tasks',
  'tool-theme':          '#tool-theme-btn, #rail-theme',
  'tool-workbench':      '#tool-workbench-btn, #rail-workbench',   // P22-02
  'user-bar':            '#user-bar-profile',
  'sidebar-settings-btn':'#user-bar-settings',
  'chat-meta':           '.chat-meta-overlay',
  'welcome-text':        '.welcome-name, .welcome-sub, #welcome-tip, .welcome-scenery',
  'incognito-btn':       '.incognito-btn',
  'web-toggle-btn':      '#web-toggle-btn',
  'doc-toggle-btn':      '#overflow-doc-btn',
  'rag-toggle-btn':      '#overflow-rag-btn',
  'bash-toggle-btn':     '#bash-toggle-btn',
  'overflow-plus-btn':   '.overflow-wrapper',
  'mode-toggle':         '.mode-toggle',
  'preset-mini-btn':     '#overflow-preset-btn',
  'attach-btn':          '#overflow-attach-btn',
  'research-btn':        '#overflow-research-btn',
  'rail-new-chat':       '#rail-new-session',
};

// Keys hidden by default on first run (no localStorage yet).
export const UI_VIS_DEFAULT_OFF = new Set(['rag-toggle-btn', 'text-emojis', 'chat-fullwidth']);

/**
 * Resolve every UI_VIS_MAP selector to visible (true) or hidden (false) for the
 * given saved state. Pure: no DOM, no localStorage — app.js applies the result.
 *
 * A key is visible when its stored value is not `false`, defaulting to on
 * unless it is in UI_VIS_DEFAULT_OFF. Per-tool entries also require the Tools
 * section to be on: hiding Tools hides every tool, mirroring the full sidebar
 * where the #tools-section container already hides them (the rail has no
 * container, so this rule keeps it in sync).
 *
 * @param {Record<string, boolean>} state
 * @returns {Record<string, boolean>} selector → visible
 */
export const resolveVisibility = (state = {}) => {
  const toolsOn = state['tools-section'] !== false;
  const out = {};
  for (const [key, selector] of Object.entries(UI_VIS_MAP)) {
    let visible = key in state ? state[key] !== false : !UI_VIS_DEFAULT_OFF.has(key);
    if (!toolsOn && key.startsWith('tool-')) visible = false;
    out[selector] = visible;
  }
  return out;
};

/* ═══════════════════════════════════════════════════════════════════════════
   `P23-03` — ONE VISIBILITY TABLE FOR THE TOOLS (contract C-VIS).

   The owner's rule: a tool switched off disappears from Tools on the main
   screen and from every other door, and comes back when switched on. Before
   this there were five switch sets, two appliers with different selector sets
   (`init.js`, `app.js`), a four-key feature map, and no door that obeyed all
   of them (audit: SET-M-1…5, SET-M-9, SET-M-15 — a privilege hid the sidebar
   row and left the rail; `/gallery` typed or linked opened a Gallery its admin
   had switched off; the Web chip came back on every mode change).

   THREE COLUMNS, AND SEMANTICS. A tool is shown when
       everyone   — Settings → Agent Tools → *Switched on for everyone* (admin)
     ∧ this person — Settings → Users → *Can use* (admin), and admin-only tools
     ∧ this browser — Settings → Appearance → *Show in this browser* (anyone)
   are all on. An admin's off outranks a browser's on: the browser column can
   only take a tool away. Unknown (before `/api/auth/features` or
   `/api/auth/status` answer) is on, the rule `src/feature_gate.py` follows —
   the server refuses whatever the page offers too early.

   EVERY DOOR. Hidden is hidden at the sidebar row and its rail twin (the
   applier), the Ctrl+K rows (`search-chat.js` reads `toolKeyFor({window})`),
   the slash catalogue and dispatcher (`slashAutocomplete.js`,
   `slashCommands.js`), the URL (`guardRouteOpener`), the `open_*` shortcuts
   and every other button a module presses programmatically (one capture-phase
   click guard, `installToolDoorGuard`), and the cross-window doors
   (`openSkillsWindow`, `openWorkbench`, both `openLibrary`s call
   `window.pantheonToolDoor`). A door refused says why, in the sentence the
   server would have said (`toolRefusal`).
   ═══════════════════════════════════════════════════════════════════════════ */

function _tool(def) {
  return Object.freeze({
    label: '',
    // Door elements: the sidebar row and the rail twin (and Email's section).
    doors: [],
    // Composer controls the tool owns — hidden and shown with it.
    composer: [],
    // Indicators other code shows and hides by state (`display:none` in the
    // markup until something turns them on). Hidden when the tool is off;
    // never re-shown by the applier — their owner shows them when they apply.
    quiet: [],
    windows: [],
    slash: [],
    routes: [],
    shortcut: null,
    feature: null,
    privilege: null,
    adminOnly: false,
    ui: null,
    // A composer control rather than a Tools entry: hidden with its switches,
    // but no door of its own to guard.
    chip: false,
    ...def,
  });
}

/**
 * The table. One row per Tools entry (the audit's § 3 rows, lower-case keys),
 * then the composer chips. `feature` is a key of `DEFAULT_FEATURES`
 * (`src/settings.py`), `privilege` a key of `DEFAULT_PRIVILEGES`
 * (`core/auth.py`) or a function of the state for the one that is not a plain
 * key, `ui` a key of `UI_VIS_MAP` above.
 */
export const TOOL_VISIBILITY = Object.freeze({
  assistant: _tool({
    label: 'Assistant', doors: ['tool-assistant-btn', 'rail-assistant'],
    ui: 'tool-assistant',
  }),
  brain: _tool({
    label: 'Brain', doors: ['tool-memory-btn', 'rail-memory'],
    windows: ['memory-modal', 'skills-modal'],
    slash: ['brain', 'memories', 'memory', 'skills', 'reload-skills', 'forget', 'tour-brain'],
    routes: ['/memory', '/brain', '/skills'], shortcut: 'open_memory',
    feature: 'memory', privilege: 'can_manage_memory', ui: 'tool-memory',
  }),
  calendar: _tool({
    label: 'Calendar', doors: ['tool-calendar-btn', 'rail-calendar'],
    windows: ['calendar-modal'], slash: ['event'], routes: ['/calendar'],
    shortcut: 'open_calendar', ui: 'tool-calendar',
  }),
  compare: _tool({
    label: 'Compare', doors: ['tool-compare-btn', 'rail-compare'],
    windows: ['compare-model-overlay'], slash: ['compare', 'tour-compare'],
    routes: ['/compare'], shortcut: 'open_compare', ui: 'tool-compare',
  }),
  research: _tool({
    label: 'Deep Research', doors: ['tool-research-btn', 'rail-research'],
    quiet: ['research-toggle-btn'],
    windows: ['research-overlay'], slash: ['research', 'tour-research'],
    routes: ['/research'], shortcut: 'open_research',
    feature: 'deep_research', privilege: 'can_use_research', ui: 'tool-research',
  }),
  // `SET-M-9`. Every Forge route is `require_admin` (`routes/cookbook_routes.py`),
  // so for anyone else it is a window of 403s with a Retry that cannot work.
  forge: _tool({
    label: 'Forge', doors: ['tool-cookbook-btn', 'rail-cookbook'],
    windows: ['cookbook-modal'], slash: ['forge', 'cookbook', 'cook', 'tour-forge'],
    routes: ['/cookbook', '/forge'], shortcut: 'open_cookbook',
    adminOnly: true, ui: 'tool-cookbook',
  }),
  // The person's column is *Image generation*: the audit's model (§ 3) gives
  // Gallery that switch, so it hides something a person can see.
  gallery: _tool({
    label: 'Gallery', doors: ['tool-gallery-btn', 'rail-gallery'],
    windows: ['gallery-modal'], slash: ['gallery', 'photos', 'tour-gallery'],
    routes: ['/gallery'], shortcut: 'open_gallery',
    feature: 'gallery', privilege: 'can_generate_images', ui: 'tool-gallery',
  }),
  library: _tool({
    label: 'Library', doors: ['tool-library-btn', 'rail-archive'],
    windows: ['doclib-modal'], slash: ['library', 'tour-library'],
    routes: ['/library'], shortcut: 'open_library',
    feature: 'document_editor', privilege: 'can_use_documents', ui: 'tool-library',
  }),
  notes: _tool({
    label: 'Notes', doors: ['tool-notes-btn', 'rail-notes'],
    windows: ['notes-panel', 'notes-pane'], slash: ['notes', 'note', 'todo'],
    routes: ['/notes'], shortcut: 'open_notes', ui: 'tool-notes',
  }),
  tasks: _tool({
    label: 'Tasks', doors: ['tool-tasks-btn', 'rail-tasks'],
    windows: ['tasks-modal'], slash: ['tasks', 'tour-task-1', 'tour-task-2'],
    routes: ['/tasks'], shortcut: 'open_tasks', ui: 'tool-tasks',
  }),
  theme: _tool({
    label: 'Theme', doors: ['tool-theme-btn', 'rail-theme'],
    windows: ['theme-modal'], slash: ['tour-theme'], routes: ['/theme'],
    shortcut: 'open_theme', ui: 'tool-theme',
  }),
  workbench: _tool({
    label: 'Workbench', doors: ['tool-workbench-btn', 'rail-workbench'],
    windows: ['workbench-modal'], routes: ['/workbench'], ui: 'tool-workbench',
  }),
  email: _tool({
    label: 'Email', doors: ['email-section', 'rail-email'],
    windows: ['email-lib-modal'], slash: ['email'], routes: ['/email'],
    ui: 'email-section',
  }),
  // ── Composer chips ──
  web: _tool({
    label: 'Web search', chip: true, composer: ['web-toggle-btn'],
    feature: 'web_search', ui: 'web-toggle-btn',
  }),
  rag: _tool({
    label: 'RAG', chip: true, composer: ['overflow-rag-btn'], quiet: ['rag-indicator-btn'],
    feature: 'rag', ui: 'rag-toggle-btn',
  }),
  doc: _tool({
    label: 'Document editor', chip: true, composer: ['overflow-doc-btn'],
    quiet: ['doc-indicator-btn', 'rail-documents'],
    feature: 'document_editor', privilege: 'can_use_documents', ui: 'doc-toggle-btn',
  }),
  // `B966`: the Shell switch follows where this person's shell runs
  // (`/api/auth/status` → `shell`), and only falls back to `can_use_bash`.
  shell: _tool({
    label: 'Shell', chip: true, composer: ['bash-toggle-btn'], ui: 'bash-toggle-btn',
    privilege: (s) => {
      if (s.shell) return s.shell !== 'none';
      if (!s.privileges) return null;
      return !!s.privileges.can_use_bash;
    },
  }),
  agent: _tool({
    label: 'Agent mode', chip: true, composer: ['mode-agent-btn'], privilege: 'can_use_agent',
  }),
});

// Indicators are never re-shown by the applier (see `quiet` above).
const _quietIds = new Set(Object.values(TOOL_VISIBILITY).flatMap((d) => d.quiet));

// ── state ──────────────────────────────────────────────────────────────────

const _state = { features: null, privileges: null, isAdmin: null, shell: null, ui: null };
const _known = { features: false, auth: false };
// The one set every pass respects: element ids the table hides right now.
const _hidden = new Set();
const _hooks = [];
let _readyResolve = null;
const _ready = new Promise((resolve) => { _readyResolve = resolve; });

function _uiOn(def, ui) {
  if (!def.ui || !ui) return true;
  const key = def.ui;
  let on = key in ui ? ui[key] !== false : !UI_VIS_DEFAULT_OFF.has(key);
  if (key.startsWith('tool-') && ui['tools-section'] === false) on = false;
  return on;
}

function _personOn(def, s) {
  if (!def.privilege) return true;
  if (typeof def.privilege === 'function') return def.privilege(s) !== false;
  if (!s.privileges) return true;
  return s.privileges[def.privilege] !== false;
}

/**
 * Which column took `key` away, or `null` when it is shown. One of
 * `'everyone'` · `'admin'` · `'person'` · `'browser'` — in that order, so the
 * reason a person is told is the one they cannot undo themselves first.
 */
export function toolOff(key, state = _state) {
  const def = TOOL_VISIBILITY[key];
  if (!def) return null;
  const s = state || {};
  if (def.feature && s.features && s.features[def.feature] === false) return 'everyone';
  if (def.adminOnly && s.isAdmin === false) return 'admin';
  if (!_personOn(def, s)) return 'person';
  if (!_uiOn(def, s.ui)) return 'browser';
  return null;
}

/** Is the tool shown? Every door asks this. */
export function toolShown(key) {
  return toolOff(key) === null;
}

/**
 * What a door says when it is refused — the server's sentence for the column
 * that took the tool away (`src/feature_gate.py` speaks the *everyone* one;
 * `test_one_visibility_table_for_the_tools.py` pins the two to one wording).
 */
export function toolRefusal(key, state = _state) {
  const def = TOOL_VISIBILITY[key];
  const off = toolOff(key, state);
  if (!def || !off) return '';
  const name = def.label;
  if (off === 'everyone') return featureOffSentence(name);
  if (off === 'admin') return `${name} is for admins.`;
  if (off === 'person') return `${name} is switched off for your account. An admin can turn it back on in Settings → Users.`;
  return `${name} is hidden in this browser. Turn it back on in Settings → Appearance.`;
}

/** The *everyone* sentence, as `src/feature_gate.py:require_feature` words it. */
export function featureOffSentence(label) {
  return `${label} is switched off for everyone. An admin can turn it back on in Settings → Agent Tools.`;
}

/** The Tools entries (and chips) a switch hides — for the "Off hides …" lines. */
export function toolsHiddenBy({ feature = null, privilege = null } = {}) {
  return Object.entries(TOOL_VISIBILITY)
    .filter(([, def]) => (feature && def.feature === feature)
      || (privilege && def.privilege === privilege))
    .map(([key, def]) => ({ key, label: def.label, chip: def.chip }));
}

/** The tool a door belongs to, by any of its names, or `null`. */
export function toolKeyFor(spec) {
  if (!spec) return null;
  if (typeof spec === 'string') return TOOL_VISIBILITY[spec] ? spec : null;
  for (const [key, def] of Object.entries(TOOL_VISIBILITY)) {
    if (spec.slash && def.slash.includes(String(spec.slash).toLowerCase())) return key;
    if (spec.window && def.windows.includes(spec.window)) return key;
    if (spec.shortcut && def.shortcut === spec.shortcut) return key;
    if (spec.element && !def.chip && def.doors.includes(spec.element)) return key;
    if (spec.route) {
      const path = String(spec.route).replace(/\/+$/, '') || '/';
      if (def.routes.some((r) => path === r || path.startsWith(r + '/'))) return key;
    }
  }
  return null;
}

/**
 * The door check. `spec` is a tool key, a list of them, or a lookup
 * (`{slash}`, `{route}`, `{window}`, `{shortcut}`, `{element}`). A door that
 * belongs to no tool is open. Refused, it says the sentence through `say`
 * (a toast by default) and answers `false`.
 */
export function toolDoor(spec, { say } = {}) {
  const keys = Array.isArray(spec) ? spec.map(toolKeyFor) : [toolKeyFor(spec)];
  for (const key of keys) {
    if (!key || toolShown(key)) continue;
    _say(toolRefusal(key), say);
    return false;
  }
  return true;
}

function _say(sentence, say) {
  if (!sentence) return;
  try {
    if (typeof say === 'function') { say(sentence); return; }
    const ui = typeof window !== 'undefined' ? window.uiModule : null;
    if (ui && typeof ui.showToast === 'function') ui.showToast(sentence, 5000);
  } catch (_) { /* a refusal that cannot be said is still a refusal */ }
}

/** Resolves once the features and the person's status have both been applied
 *  (or after `ms`, on whatever is known — unknown is on). */
export function whenToolVisibilityReady(ms = 4000) {
  if (_known.features && _known.auth) return Promise.resolve();
  return Promise.race([_ready, new Promise((r) => setTimeout(r, ms))]);
}

/**
 * The URL door. Wraps a deep-link opener so a path that names a hidden tool
 * says why instead of opening it — after the switches are known, because a
 * link is followed at load, before `/api/auth/features` has answered.
 */
export function guardRouteOpener(path, opener, { say } = {}) {
  if (typeof opener !== 'function') return opener;
  const key = toolKeyFor({ route: path });
  if (!key) return opener;
  return async (...args) => {
    await whenToolVisibilityReady();
    if (!toolDoor(key, { say })) return undefined;
    return opener(...args);
  };
}

/** Called after every apply with `{ hidden, restored, state }`. */
export function onToolVisibilityApplied(fn) {
  if (typeof fn === 'function') _hooks.push(fn);
}

function _ids(def) {
  return [...def.doors, ...def.composer];
}

/**
 * The applier. `patch` updates what is known — `features`
 * (`/api/auth/features`), `privileges` / `isAdmin` / `shell`
 * (`/api/auth/status`), `ui` (Appearance, this browser) — and the whole table
 * is applied again: every element of a hidden tool gets `display:none` and is
 * recorded; an element this applier hid before and no longer hides gets its
 * `display` back. Live: the admin's switch, a person's Appearance switch, and
 * the load path all come here (`SET-M-12`).
 */
export function applyToolVisibility(patch = {}, doc = (typeof document !== 'undefined' ? document : null)) {
  const p = patch || {};
  if ('features' in p) { _state.features = p.features || null; _known.features = true; }
  if ('privileges' in p) _state.privileges = p.privileges || null;
  if ('isAdmin' in p) _state.isAdmin = p.isAdmin === null || p.isAdmin === undefined ? null : !!p.isAdmin;
  if ('shell' in p) _state.shell = p.shell || null;
  if (p.auth) _known.auth = true;
  if ('ui' in p) _state.ui = p.ui || {};
  if (_known.features && _known.auth && _readyResolve) { _readyResolve(); _readyResolve = null; }

  const next = new Set();
  for (const [key, def] of Object.entries(TOOL_VISIBILITY)) {
    if (toolShown(key)) continue;
    _ids(def).forEach((id) => next.add(id));
    def.quiet.forEach((id) => next.add(id));
  }
  const restored = [];
  if (doc) {
    for (const id of _hidden) {
      if (next.has(id) || _quietIds.has(id)) continue;
      const e = doc.getElementById(id);
      if (e && e.style && e.style.display === 'none') { e.style.display = ''; restored.push(id); }
    }
  }
  _hidden.clear();
  next.forEach((id) => _hidden.add(id));
  if (doc) {
    for (const id of _hidden) {
      const e = doc.getElementById(id);
      if (e && e.style) e.style.display = 'none';
    }
  }
  for (const fn of _hooks) {
    try { fn({ hidden: _hidden, restored, state: _state }); } catch (_) { /* one hook does not stop the next */ }
  }
  return _hidden;
}

/** May the person signed in see the admin's Settings? The status's answer
 *  when someone is signed in. Nobody signed in once `/api/auth/status` has
 *  answered (`window._isAdmin` set, to `false`) is an install with auth off,
 *  whose one operator the server's `require_admin` lets in — the owner. Not
 *  answered yet: not shown, until it says. */
export function viewerIsAdmin() {
  if (_state.isAdmin !== null) return _state.isAdmin;
  const said = typeof window !== 'undefined' ? window._isAdmin : undefined;
  return said !== undefined;
}

/** A read-only view of what is known, for the Settings rows that explain a
 *  switch they cannot undo. */
export function toolVisibilityState() {
  return { ..._state };
}

/** Every door a person can press is a button the applier hides; a module that
 *  presses one programmatically (`el.click()` — the `open_*` shortcuts, the
 *  rail delegating to the sidebar, a deep link, `/open`) is refused here, in
 *  the capture phase on `window`, before any handler of the button runs. */
export function installToolDoorGuard(win = (typeof window !== 'undefined' ? window : null)) {
  if (!win || win.__pantheonToolDoorGuard) return;
  win.__pantheonToolDoorGuard = true;
  const doorOf = new Map();
  for (const [key, def] of Object.entries(TOOL_VISIBILITY)) {
    if (def.chip) continue;
    def.doors.forEach((id) => doorOf.set(id, key));
  }
  win.addEventListener('click', (e) => {
    let node = e.target;
    for (let hops = 0; node && hops < 8; hops += 1, node = node.parentNode) {
      const key = node.id ? doorOf.get(node.id) : null;
      if (!key) continue;
      if (toolShown(key)) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      _say(toolRefusal(key));
      return;
    }
  }, true);
}

if (typeof window !== 'undefined') {
  window.__pantheonFeatureHiddenIds = _hidden;
  // `SET-M-12`: the admin's own page applies a feature switch at once; others
  // see it after their next reload.
  window.applyFeatureFlags = (features) => applyToolVisibility(features ? { features } : {});
  // The cross-window doors in other modules call these (one line each).
  window.pantheonToolDoor = toolDoor;
  window.pantheonToolShown = toolShown;
}
