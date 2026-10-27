// SPDX-License-Identifier: AGPL-3.0-or-later
// Memory Management Functions
// This module handles all memory-related operations

import uiModule from './ui.js';
import sessionModule from './sessions.js';
import spinnerModule from './spinner.js';
import { makeWindowDraggable } from './windowDrag.js';
import { topPortalZ } from './toolWindowZOrder.js';
import { setBackgroundWork } from './modalManager.js?v=20261009census';
import { bindMenuDismiss, dismissOrRemove } from './escMenuStack.js';
// C-NAV (`P23-01` builds it): `register(id, { getTab, setTab })`.
import * as Modals from './modalManager.js?v=20261009census';
// C-ERR: a refused response is read once, by the one reader.
import { readRefusal } from './workbench/refusal.js';
// `P13-01`. The memory pills live in a module that imports nothing, because
// `chatRenderer.js` needs them too and cannot import this file —
// `memory.js` -> `sessions.js` -> `chatRenderer.js` is a cycle.
import { memoryCountPills, memoryConfidencePill, memoryStatusBadge,
         memoryStatus, countByStatus, statusChips, memoryFadeLine } from './memoryFacts.js';
// `B710`. The status clause itself, imported rather than rewritten: Explore
// narrows by status through the same function, and two readings of this field
// differ exactly where it matters — on what an unrecognised value means
// (`Law 7`).
import { matches as memoryMatchesFilter } from './brainFilter.js';
import { scrollBehavior } from './motion.js';

var escapeHtml = uiModule.esc;

let memories = [];
let activeCategory = 'all';
// `B710`. `any` and not `binding`: the Brain is the place a person goes to see
// what it knows, and opening it already filtered would hide the proposals this
// row exists to surface — from a control they have not been shown yet, because
// the chip row only appears once something is not committed.
let activeStatus = 'any';
let sortOrder = 'newest';
let selectMode = false;
let selectedIds = new Set();
let memoriesLoading = false;
// `B1070`. Whether `memories` is the store's answer yet, and what went wrong if
// asking failed. Before the first answer the list is unknown, not empty: the
// Brain said "No memories yet" for seconds while eight existed, because its
// door drew the list it had (none) and the store was only asked by a warmup
// 12 s after boot. An empty state that is really a loading state, or a failed
// one, is a false statement (`Law 10`).
let memoriesKnown = false;
let memoriesError = '';
// `PERF-M-7` (P23-02): set by a chat switch, cleared by a load.
let memoriesStale = false;
// `SET-U-15` (P23-02): the server's sentence when it refused the list.
let memoriesRefused = '';


const MEMORY_CATEGORIES = ['fact', 'identity', 'preference', 'contact', 'project', 'goal', 'task'];

// Sort-option icons for the custom Memory sort picker (and Skills picker
// once it reuses the same markup). Each value maps to a 13px Feather-style
// SVG so the icon visually distinguishes Newest / Oldest / A-Z / Most used /
// Most said.
const _MEMORY_SORT_ICONS = {
  newest: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
  oldest: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><polyline points="3 3 3 8 8 8"/><polyline points="12 7 12 12 16 14"/></svg>',
  alpha:  '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 4h6"/><path d="M3 10h6"/><path d="M3 16h4"/><path d="M14 4l4 12"/><path d="M16 12h4"/><polyline points="17 18 21 14 17 10"/><line x1="21" y1="14" x2="13" y2="14"/></svg>',
  uses:   '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/></svg>',
  // `P13-15`. Two speech bubbles: this order is about what you keep saying,
  // where `uses` is about what the assistant keeps reaching for.
  mentions: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 9a2 2 0 0 1-2 2H6l-4 4V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2z"/><path d="M18 9h2a2 2 0 0 1 2 2v11l-4-4h-6a2 2 0 0 1-2-2v-1"/></svg>',
};

function _memorySortIcon(value) {
  return _MEMORY_SORT_ICONS[value] || _MEMORY_SORT_ICONS.newest;
}

function _renderMemorySortPickerCurrent() {
  const sel = document.getElementById('memory-sort');
  const btn = document.getElementById('memory-sort-btn');
  if (!sel || !btn) return;
  const value = sel.value || 'newest';
  const opt = sel.querySelector(`option[value="${CSS.escape(value)}"]`);
  const label = opt ? opt.textContent : value;
  const iconWrap = btn.querySelector('.memory-sort-icon-cur');
  const labelEl = btn.querySelector('.memory-sort-label');
  if (iconWrap) iconWrap.innerHTML = _memorySortIcon(value);
  if (labelEl) labelEl.textContent = label;
}

function _initMemorySortPicker() {
  const sel = document.getElementById('memory-sort');
  const picker = document.getElementById('memory-sort-picker');
  const btn = document.getElementById('memory-sort-btn');
  const menu = document.getElementById('memory-sort-menu');
  if (!sel || !picker || !btn || !menu || picker._wired) return;
  picker._wired = true;

  const items = Array.from(sel.children)
    .filter(o => o.tagName === 'OPTION')
    .map(o => ({ value: o.value, label: o.textContent }));

  menu.innerHTML = items.map(it => `
    <button type="button" role="option" class="memory-sort-item" data-value="${it.value}" aria-selected="false">
      <span class="memory-sort-item-icon" aria-hidden="true">${_memorySortIcon(it.value)}</span>
      <span class="memory-sort-item-label">${it.label}</span>
    </button>
  `).join('');

  // `BRAIN-U-7` (P23-02). Opened, walked and closed through `bindMenuDismiss`,
  // the one menu wrapper (`P10-06`): a keyboard-opened picker takes the focus,
  // the arrows walk it, Escape closes it through the stack and hands the focus
  // back to the button. It used to open on Enter and leave the focus on the
  // button, so ArrowDown did nothing and Enter re-chose *Newest*; and it kept
  // two `document` listeners of its own, one of them an Escape handler in the
  // capture phase (C-NAV: Escape layers go through `escMenuStack`).
  let dismiss = null;
  const close = () => { if (dismiss) dismiss(); };
  const open = () => {
    const fromKeys = (() => { try { return btn.matches(':focus-visible'); } catch (_) { return false; } })();
    menu.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
    const current = sel.value || 'newest';
    let pick = null;
    menu.querySelectorAll('.memory-sort-item').forEach((b) => {
      const on = b.dataset.value === current;
      b.setAttribute('aria-selected', on ? 'true' : 'false');
      if (on) pick = b;
    });
    dismiss = bindMenuDismiss(menu, () => {
      menu.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
      dismiss = null;
    }, (ev) => !picker.contains(ev.target));
    // The chosen one, not the first: Enter straight away keeps the order.
    if (fromKeys && pick) setTimeout(() => { try { pick.focus(); } catch (_) {} }, 0);
  };

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (menu.hidden) open(); else close();
  });
  menu.addEventListener('click', (e) => {
    const item = e.target.closest('.memory-sort-item');
    if (!item) return;
    sel.value = item.dataset.value;
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    _renderMemorySortPickerCurrent();
    close();
  });

  _renderMemorySortPickerCurrent();
}

function _ensureNewMemoryCategorySelect() {
  const sel = document.getElementById('new-memory-category');
  if (!sel || sel.dataset.wired === '1') return;
  sel.dataset.wired = '1';
  MEMORY_CATEGORIES.forEach(cat => {
    const opt = document.createElement('option');
    opt.value = cat;
    opt.textContent = cat;
    if (cat === 'fact') opt.selected = true;
    sel.appendChild(opt);
  });
}

function _readNewMemoryCategory() {
  _ensureNewMemoryCategorySelect();
  const sel = document.getElementById('new-memory-category');
  const cat = sel?.value || 'fact';
  return MEMORY_CATEGORIES.includes(cat) ? cat : 'fact';
}

let _memoryDragWired = false;
function _wireMemoryDrag() {
  if (_memoryDragWired) return;
  const modal = document.getElementById('memory-modal');
  const content = modal && modal.querySelector('.modal-content');
  const header = modal && modal.querySelector('.modal-header');
  if (!modal || !content || !header) return;
  _memoryDragWired = true;
  makeWindowDraggable(modal, {
    content,
    header,
    skipSelector: 'button, input, select, label',
    enableDock: true,
    enableLeftDock: true,
    // `B810`: the top edge is `tileManager.js`'s — it maximises this window as
    // it does every `.modal`. `windowDrag.js` takes no fullscreen callback.
  });
}

function relativeTime(timestamp) {
  const now = Math.floor(Date.now() / 1000);
  const diff = now - timestamp;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  if (diff < 2592000) return `${Math.floor(diff / 604800)}w ago`;
  if (diff < 31536000) return `${Math.floor(diff / 2592000)}mo ago`;
  return `${Math.floor(diff / 31536000)}y ago`;
}

function buildCategoryChips() {
  const container = document.getElementById('memory-category-filters');
  if (!container) return;

  // Hide the chip row entirely when there are no memories — no point showing
  // an "all" chip with nothing to filter.
  if (!memories.length) { container.innerHTML = ''; return; }

  const cats = new Set(memories.map(m => m.category || 'fact'));
  const sorted = ['all', ...Array.from(cats).sort()];

  container.innerHTML = '';
  sorted.forEach(cat => {
    const btn = document.createElement('button');
    btn.className = 'memory-cat-chip' + (cat === activeCategory ? ' active' : '');
    btn.dataset.cat = cat;
    btn.textContent = cat;
    btn.addEventListener('click', () => {
      activeCategory = cat;
      container.querySelectorAll('.memory-cat-chip').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderMemoryList();
      updateMemoryCount();
    });
    container.appendChild(btn);
  });
}

/** `B710`. The status chips, drawn. The decision is `statusChips` in
 *  `memoryFacts.js` — which chips, which counts, whether a row at all — and
 *  this is the loop that turns it into buttons. Split that way for `Law 20`:
 *  a test runs the rule instead of reading it, and `B61` is why that matters
 *  (a helper can be perfect and the page still show nothing).
 *
 *  `buildCategoryChips` hides itself on an empty corpus out of the same
 *  instinct; the rule here applies it to a field rather than to a store.
 */
function buildStatusChips() {
  const container = document.getElementById('memory-status-filters');
  if (!container) return;
  const chips = statusChips(memories, activeStatus);
  if (!chips) {
    container.replaceChildren();
    container.hidden = true;
    // A filter nothing can match is a filter that would empty the list with
    // no visible cause, so putting the row away puts its state back too.
    activeStatus = 'any';
    return;
  }
  container.hidden = false;
  container.replaceChildren();
  for (const chip of chips) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'memory-cat-chip memory-status-chip'
      + (chip.active ? ' active' : '')
      + (chip.value === 'proposed' ? ' memory-status-chip-proposed' : '');
    btn.dataset.status = chip.value;
    btn.textContent = chip.label;
    btn.title = chip.title;
    btn.setAttribute('aria-pressed', chip.active ? 'true' : 'false');
    btn.addEventListener('click', () => {
      activeStatus = chip.value;
      buildStatusChips();
      renderMemoryList();
      updateMemoryCount();
    });
    container.appendChild(btn);
  }
}

/** `B730`. The filtered-to-nothing state's way out: the search box emptied and
 *  both chip rows back on showing everything. */
function clearMemoryFilters() {
  const search = document.getElementById('memory-search');
  if (search) search.value = '';
  activeCategory = 'all';
  activeStatus = 'any';
  buildCategoryChips();
  buildStatusChips();
  renderMemoryList();
  updateMemoryCount();
}

// `PERF-M-8` (P23-02). The Brain's seven switches are read from ONE
// `GET /api/prefs`, once per page, and set in one pass. They were seven serial
// single-key reads (`/api/prefs/<key>`, each awaited before the next) on every
// `loadMemories()` — at load and again 2.8 s after every chat switch (measured
// on `32df791`: 1 + 7 requests each time), and each switch sat at its default
// until its own answer came back (`PERF-U-5`). `fresh` re-reads, still in one
// request: the Brain asks once when it opens, in case another tab moved one.
let _brainPrefs = null;
function _readBrainPrefs(fresh = false) {
  if (!_brainPrefs || fresh) {
    _brainPrefs = fetch(`${window.location.origin}/api/prefs`, { credentials: 'same-origin' })
      .then((r) => (r.ok ? r.json() : null))
      .then((p) => (p && typeof p === 'object' ? p : null))
      .catch(() => null);
  }
  return _brainPrefs;
}

/** A saved switch is what the next redraw shows: the one read is kept current,
 *  so a later `loadMemories()` cannot put a switch back where it was. */
function _rememberPref(key, value) {
  if (_brainPrefs) _brainPrefs = _brainPrefs.then((p) => ({ ...(p || {}), [key]: value }));
}

async function syncToggles({ fresh = false } = {}) {
  const prefs = (await _readBrainPrefs(fresh)) || {};
  // The settings tab no longer hosts a separate "Memory in context" toggle —
  // the header toggle owns that pref directly now.
  await syncPrefToggle('memory-enabled-header-toggle', 'memory_enabled', 'Memories on', 'Memories off', false, prefs);
  // The Skills header toggle owns the `skills_enabled` pref (was never wired —
  // toggling it did nothing, so skills stayed on). Now it actually gates skill
  // injection (see chat_helpers.py: uprefs.skills_enabled).
  await syncPrefToggle('skills-enabled-header-toggle', 'skills_enabled', 'Skills on', 'Skills off', false, prefs);
  await syncPrefToggle('auto-memory-toggle', 'auto_memory', 'Auto-extract memories on', 'Auto-extract memories off', false, prefs);
  await syncPrefToggle('auto-skills-toggle', 'auto_skills', 'Auto-draft skills on', 'Auto-draft skills off', false, prefs);
  await syncPrefToggle('auto-approve-skills-toggle', 'auto_approve_skills', 'Auto-publish on', 'Auto-publish off', false, prefs);
  // `B710`. `auto_approve_memories` has been readable and writable through
  // `PUT /api/prefs` since `P13-05` and had no control anywhere; this is the
  // control. The default matches the server's (`memory_extractor` reads it
  // with `True`), so an install that has never set it shows the switch in the
  // position it is actually in rather than one the page invented.
  await syncPrefToggle('auto-approve-memories-toggle', 'auto_approve_memories',
                       'New memories are used straight away',
                       'New memories wait for you — see "proposed" in the Brain',
                       false, prefs);
  await syncPrefSlider('skill-confidence-slider', 'skill_min_confidence', 'skill-confidence-label', 0.85, prefs);
  await syncPrefNumber('skill-max-input', 'skill_max_injected', 3, prefs);

  // `P8-05`. Both controls feed one sentence apiece, and both have to redraw
  // when either moves — the whole defect is that the toggle changes what the
  // slider means and said nothing.
  const approveToggle = document.getElementById('auto-approve-skills-toggle');
  if (approveToggle && !approveToggle.dataset.boundGateHint) {
    approveToggle.dataset.boundGateHint = '1';
    approveToggle.addEventListener('change', refreshSkillGateHints);
  }
  const confSlider = document.getElementById('skill-confidence-slider');
  if (confSlider && !confSlider.dataset.boundGateHint) {
    confSlider.dataset.boundGateHint = '1';
    confSlider.addEventListener('input', refreshSkillGateHints);
  }
  refreshSkillGateHints();

  // `B710`. The same arrangement one row down: the sentence is rewritten when
  // the switch moves, not only when the Brain reloads.
  const memApprove = document.getElementById('auto-approve-memories-toggle');
  if (memApprove && !memApprove.dataset.boundGateHint) {
    memApprove.dataset.boundGateHint = '1';
    memApprove.addEventListener('change', refreshMemoryGateHint);
  }
  refreshMemoryGateHint();

  // Reflect the header toggle into the sidebar dim + the list's opacity.
  // `BRAIN-U-11` (P23-02): the list only. It dimmed the whole `.memory-modal-
  // body` — the tab strip, RAG, Add and Settings with it, none of which the
  // switch touches — while the list itself stayed at full strength (measured).
  const headerToggle = document.getElementById('memory-enabled-header-toggle');
  if (headerToggle) {
    const dimList = () => {
      const list = document.getElementById('memory-list');
      if (list) list.style.opacity = headerToggle.checked ? '' : '0.4';
    };
    dimList();
    reflectMemoryToggleInSidebar(headerToggle.checked);
    if (!headerToggle.dataset.boundUx) {
      headerToggle.dataset.boundUx = '1';
      headerToggle.addEventListener('change', () => {
        dimList();
        reflectMemoryToggleInSidebar(headerToggle.checked);
      });
    }
  }

  // Same dim treatment for the Skills toggle — the list, not its toolbar
  // (`BRAIN-U-11`).
  const skillsToggle = document.getElementById('skills-enabled-header-toggle');
  if (skillsToggle) {
    const applyDim = () => {
      const list = document.getElementById('skills-list');
      if (list) list.style.opacity = skillsToggle.checked ? '' : '0.4';
    };
    applyDim();
    if (!skillsToggle.dataset.boundUx) {
      skillsToggle.dataset.boundUx = '1';
      skillsToggle.addEventListener('change', applyDim);
    }
  }
}

function reflectMemoryToggleInSidebar(enabled) {
  const btn = document.getElementById('tool-memory-btn');
  if (btn) btn.classList.toggle('tool-disabled', !enabled);
}

function syncToggleDim(toggle) {
  const card = toggle.closest('.admin-card');
  if (!card) return;
  const toggleRow = toggle.closest('div[style*="justify-content"]');
  let sibling = toggleRow ? toggleRow.nextElementSibling : null;
  while (sibling) {
    sibling.style.opacity = toggle.checked ? '' : '0.35';
    sibling.style.pointerEvents = toggle.checked ? '' : 'none';
    sibling = sibling.nextElementSibling;
  }
}

/** Load/save a confidence slider backed by a float pref (0 = "All", else
 *  0.50–1.00). Slider position is the percent; the MAX position means "All"
 *  (no minimum), and sliding down sets the bar to 95%, 90%, 85%… */
// `P8-04`. The "All" stop is at the LEFT end now, and that is the whole fix.
//
// It used to be at the right. Dragging a control labelled "Minimum confidence"
// as far right as it goes stored **0**, and 0 is the single value that turns
// the gate off completely — `get_relevant_skills` only filters at all inside
// `if min_confidence > 0` (services/memory/skills.py, `get_relevant_skills`). So the strictest
// setting was one notch short of the end, the end itself was the loosest
// setting on the control, and it was labelled "All", which reads as a promise
// about coverage rather than a confession that nothing is being checked.
//
// Nothing about what is stored changes: 0 still means "no minimum", 0.85 still
// means 85%. Only which position maps to 0 moves, so a saved preference keeps
// its meaning and the geometry stops lying. `slider.min` is the sentinel stop
// (45, one step below the lowest real percentage) and `min + step` is the
// lowest percentage the control can express — no setting was taken away.
/** `PERF-M-8`. A pref's value: from the prefs already read when the caller has
 *  them (`syncToggles`), else one single-key read. `{ value }` either way. */
async function _prefValue(prefKey, prefs) {
  if (prefs && typeof prefs === 'object') return { value: prefs[prefKey] };
  const res = await fetch(`${window.location.origin}/api/prefs/${prefKey}`);
  if (!res.ok) return null;
  return res.json();
}

export async function syncPrefSlider(elementId, prefKey, labelId, defaultVal, prefs = null) {
  const slider = document.getElementById(elementId);
  if (!slider) return;
  const label = labelId ? document.getElementById(labelId) : null;
  const allPos = Number(slider.min);
  const maxPos = Number(slider.max);
  const floorPos = allPos + (Number(slider.step) || 5);
  const fmt = (pos) => (Number(pos) <= allPos ? 'All' : `≥ ${pos}%`);
  try {
    const data = await _prefValue(prefKey, prefs);
    if (data) {
      let pref = (data.value === undefined || data.value === null) ? defaultVal : Number(data.value);
      // pref 0 (or falsy) = "All" → the sentinel stop at the loose end; else
      // percent, clamped to a position the control can actually express so a
      // stray sub-floor value is shown as the lowest percentage and never
      // mistaken for "no minimum".
      let pos = (!pref || pref <= 0)
        ? allPos
        : Math.max(floorPos, Math.min(maxPos, Math.round(pref * 100)));
      slider.value = String(pos);
    }
  } catch (e) {
    console.error(`Failed to load ${prefKey} pref:`, e);
  }
  if (label) label.textContent = fmt(slider.value);
  if (!slider.dataset.bound) {
    slider.dataset.bound = '1';
    slider.addEventListener('input', () => { if (label) label.textContent = fmt(slider.value); });
    slider.addEventListener('change', async () => {
      const pos = Number(slider.value);
      const pref = pos <= allPos ? 0 : pos / 100;
      try {
        const res = await fetch(`${window.location.origin}/api/prefs/${prefKey}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ value: pref })
        });
        if (!res.ok) { showError('Failed to save preference'); return; }
        _rememberPref(prefKey, pref);
        showToast(pref === 0
          ? 'Skill confidence: no minimum'
          : `Skill confidence ≥ ${Math.round(pref * 100)}%`);
      } catch (e) {
        console.error(`Failed to save ${prefKey} pref:`, e);
        showError('Failed to save preference');
      }
    });
  }
}

/** `P8-04`/`P8-05` — what the two skill-gate controls do, in the words a person
 *  reads, resolved in one pure function so the sentence and the behaviour
 *  cannot drift apart.
 *
 *  `minConfidence` is the stored preference: a fraction, or 0 meaning no
 *  minimum. `autoApprove` is `auto_approve_skills`.
 *
 *  The coupling is the part nobody could see from the surface.
 *  `src/agent_loop.py`'s `_build_system_prompt` sets the injection floor to **2.0** when
 *  auto-approve is off — a number no confidence can reach — so turning off a
 *  toggle whose label only mentions the audit silently makes injection
 *  published-only. It is a real and defensible behaviour; it was simply
 *  invisible, and an invisible coupling is how a person concludes the product
 *  is ignoring them.
 */
export function skillGateHints({ autoApprove = true, minConfidence = 0.85 } = {}) {
  const value = Number(minConfidence) || 0;
  const pct = Math.round(value * 100);
  // `D-9` (P23-02, Doc 2 § 5): one line each, the words of `BRAIN-U-17`
  // (draft / published, auto-publish). The coupling `P8-05` made visible is
  // kept where it bites — auto-publish off — and is silent when it does not.
  //
  // `B584`. **One number, two policies, and the sentence says both.** The
  // injection path reads `skill_min_confidence` as a floor (`agent_loop`, `0`
  // disables it) and the audit reads the same value as the bar it publishes at
  // (`routes/skills_routes._audit_auto_publish_policy`, `0` publishes every
  // pass), so the slider's loose end is the loosest setting of both at once.
  // The on-sentences name both readings at every position, so nobody can come
  // away believing they tightened one when they loosened the other. And the
  // off-sentence was wrong: with auto-publish off `_audit_finalize_status`
  // publishes nothing at any confidence, so the number decides nothing — it
  // said *"it still decides what Audit publishes"*. Splitting it into two
  // settings is the alternative, and the owner's to choose.
  if (!autoApprove) {
    return {
      confidence: 'Decides nothing while auto-publish is off: Audit publishes no draft, and the model is shown published skills only.',
      coupling: 'Auto-publish is off, so only published skills are used. A draft waits until you publish it.',
    };
  }
  // `B581`. The bar applies to the drafts the teacher writes; a draft a person
  // writes is not shown to the model at any confidence (`B1361`), so "a new
  // skill starts at 80%" told them a number that decided nothing.
  return {
    confidence: value <= 0
      ? 'No minimum, for both things this sets: every draft the teacher writes is used when a message matches it, and Audit publishes every draft that passes — the loosest setting.'
      : `One bar for two things: drafts the teacher writes are used from ${pct}%, and Audit publishes a draft that passes at ${pct}% or more. Published skills are always used; a draft you write is used once you publish it.`,
    coupling: '',
  };
}

/** `B710`. What *Use new memories straight away* means, in one line.
 *
 *  `skillGateHints` a few lines up is the precedent and the argument: a switch
 *  whose effect shows up somewhere else is a switch a person turns once, sees
 *  nothing, and concludes is broken. `P8-05` found that with auto-publish, and
 *  this one is worse — off, extraction keeps running and the Brain keeps
 *  growing, but **nothing new reaches a chat** until somebody commits it. A
 *  person who cannot see where the proposals went has watched their assistant
 *  stop learning.
 *
 *  So the off sentence names the place. And when proposals are actually
 *  waiting it says how many, because a count is the difference between a rule
 *  and a queue.
 *
 *  Pure, and exported, so a test can run it over the four states rather than
 *  read the page (`Law 20`).
 */
export function memoryGateHint({ autoApprove = true, proposed = 0 } = {}) {
  const waiting = Math.max(0, Number(proposed) || 0);
  if (autoApprove) {
    // Still honest when something IS waiting — turning the switch back on does
    // not commit what was proposed while it was off, and a reader who is not
    // told that will wonder why the Brain is ignoring six facts.
    return waiting
      ? `On: new memories are used as soon as they are written down.`
        + ` ${waiting} proposed earlier ${waiting === 1 ? 'is' : 'are'} still waiting`
        + ` — turning this on does not commit ${waiting === 1 ? 'it' : 'them'}.`
      : 'On: new memories are used as soon as they are written down.';
  }
  return waiting
    ? `Off: new memories wait for you. ${waiting} proposed —`
      + ` they are in the list above under "proposed", and none reaches a chat yet.`
    : 'Off: new memories are written down and wait for you to commit them.'
      + ' They appear in the list above, marked "proposed".';
}

/** Write the sentence from the live toggle and the corpus the Brain holds. */
export function refreshMemoryGateHint() {
  const hint = document.getElementById('auto-approve-memories-hint');
  if (!hint) return;
  const toggle = document.getElementById('auto-approve-memories-toggle');
  hint.textContent = memoryGateHint({
    autoApprove: toggle ? toggle.checked : true,
    proposed: countByStatus(memories).proposed,
  });
}

/** Write both sentences from the live state of the two controls. */
export function refreshSkillGateHints() {
  const hintEl = document.getElementById('skill-confidence-hint');
  const couplingEl = document.getElementById('skill-approve-coupling');
  if (!hintEl && !couplingEl) return;
  const slider = document.getElementById('skill-confidence-slider');
  const toggle = document.getElementById('auto-approve-skills-toggle');
  const allPos = slider ? Number(slider.min) : 45;
  const pos = slider ? Number(slider.value) : 85;
  const hints = skillGateHints({
    autoApprove: toggle ? !!toggle.checked : true,
    minConfidence: pos <= allPos ? 0 : pos / 100,
  });
  if (hintEl) hintEl.textContent = hints.confidence;
  if (couplingEl) couplingEl.textContent = hints.coupling;
}

/** Load/save an integer-valued pref backed by a <input type="number">. */
async function syncPrefNumber(elementId, prefKey, defaultVal, prefs = null) {
  const input = document.getElementById(elementId);
  if (!input) return;
  const clamp = (raw) => {
    let v = parseInt(raw, 10);
    if (isNaN(v)) v = defaultVal;
    const lo = Number(input.min), hi = Number(input.max);
    if (!isNaN(lo)) v = Math.max(lo, v);
    if (!isNaN(hi)) v = Math.min(hi, v);
    return v;
  };
  try {
    const data = await _prefValue(prefKey, prefs);
    if (data) {
      input.value = String((data.value === undefined || data.value === null) ? defaultVal : clamp(data.value));
    }
  } catch (e) {
    console.error(`Failed to load ${prefKey} pref:`, e);
  }
  if (!input.dataset.bound) {
    input.dataset.bound = '1';
    input.addEventListener('change', async () => {
      const v = clamp(input.value);
      input.value = String(v);
      try {
        const res = await fetch(`${window.location.origin}/api/prefs/${prefKey}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ value: v })
        });
        if (!res.ok) { showError('Failed to save preference'); return; }
        _rememberPref(prefKey, v);
        showToast(v === 0 ? 'No skills injected' : `Max injected skills: ${v}`);
      } catch (e) {
        console.error(`Failed to save ${prefKey} pref:`, e);
        showError('Failed to save preference');
      }
    });
  }
}

async function syncPrefToggle(elementId, prefKey, onMsg, offMsg, dimBelow = true, prefs = null) {
  const toggle = document.getElementById(elementId);
  if (!toggle) return;
  try {
    const data = await _prefValue(prefKey, prefs);
    if (data) {
      toggle.checked = data.value !== false;
    }
  } catch (e) {
    console.error(`Failed to load ${prefKey} pref:`, e);
  }
  if (dimBelow) syncToggleDim(toggle);
  if (!toggle.dataset.bound) {
    toggle.dataset.bound = '1';
    toggle.addEventListener('change', async () => {
      if (dimBelow) syncToggleDim(toggle);
      try {
        const res = await fetch(`${window.location.origin}/api/prefs/${prefKey}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ value: toggle.checked })
        });
        if (!res.ok) {
          console.error(`PUT ${prefKey} returned ${res.status}`);
          toggle.checked = !toggle.checked; // revert
          if (dimBelow) syncToggleDim(toggle);
          showError('Failed to save preference');
          return;
        }
        _rememberPref(prefKey, toggle.checked);
        showToast(toggle.checked ? onMsg : offMsg);
      } catch (e) {
        console.error(`Failed to save ${prefKey} pref:`, e);
        toggle.checked = !toggle.checked; // revert
        if (dimBelow) syncToggleDim(toggle);
        showError('Failed to save preference');
      }
    });
  }
}

/**
 * `B1071`. The style observer's record — `kind: "style"`
 * (`src/memory_style.py:KIND_STYLE`), which `P13-17` is emphatic is not a
 * memory — is listed by `GET /api/memory` beside the memories so its id can be
 * edited and deleted. Until a profile forms (`style.observed` < `needed`) its
 * text is "", and this list drew it as an empty card reading only *style ·
 * auto · 5m ago*, counted it ("8 memories" over seven) and gave it a *style*
 * chip. A record with nothing on it to read is not drawn, counted or chipped.
 *
 * `B820`. Once a profile forms it is read, corrected and deleted in its own
 * panel (`renderStylePanel`), so it is not a memory card either — when the
 * answer carries the `style` block the panel draws from. Without one (a server
 * older than `P13-17`'s block) the formed record is still drawn as a card, the
 * only place it could be read then (`Law 1`).
 */
const STYLE_KIND = 'style';

function _isUnformedStyleRecord(m) {
  return !!m && m.kind === STYLE_KIND && !String(m.text || '').trim();
}

/** The rows of a `GET /api/memory` answer this list draws. */
function _memoriesFrom(data) {
  let rows = [];
  if (data && Array.isArray(data.memory)) rows = data.memory;
  else if (Array.isArray(data)) rows = data;
  const panelHasIt = !!(data && data.style && data.style.profile);
  return rows.filter((m) => !_isUnformedStyleRecord(m)
    && !(panelHasIt && m && m.kind === STYLE_KIND));
}

// ---- How you write — `B820` ----

/** `GET /api/memory`'s `style` block, as last read: `{profile, observed, needed}`. */
let styleBlock = null;

/** `B820`. The lines the panel shows for a formed profile.
 *
 *  The stored `text` when it has any — after the person edits it that is
 *  *their* wording, which is what the observer then leaves alone
 *  (`style_edited`) and what reaches the model; showing the derived
 *  `sentences` instead would hide the correction they made. The derived
 *  sentences when nothing is stored yet.
 */
export function styleLines(profile) {
  if (!profile) return [];
  const stored = String(profile.text || '').split('\n').map((s) => s.trim()).filter(Boolean);
  if (stored.length) return stored;
  return (Array.isArray(profile.sentences) ? profile.sentences : [])
    .map((s) => String(s || '').trim()).filter(Boolean);
}

/** What deleting the profile does, said where the person decides it. */
export const STYLE_FORGET_CONFIRM = 'Forget how you write? This deletes the profile and the'
  + ' counts it was built from, what your jokes were learned to mean among them — the'
  + ' assistant starts learning again from your next message, from nothing.';

async function _saveStyleLines(id, lines) {
  const text = lines.map((s) => s.trim()).filter(Boolean).join('\n');
  if (!id || !text) return;
  try {
    const response = await fetch(`${window.location.origin}/api/memory/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: new URLSearchParams({ text }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    showToast('Saved — this is how the assistant will describe your writing.');
    await loadMemories();
  } catch (error) {
    console.error('Saving how you write failed:', error);
    showError('Could not save that change to how you write.');
  }
}

async function _forgetStyle(id) {
  if (!id) return;
  if (!await uiModule.styledConfirm(STYLE_FORGET_CONFIRM, { confirmText: 'Forget it', danger: true })) return;
  try {
    const response = await fetch(`${window.location.origin}/api/memory/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    showToast('Forgotten. Learning how you write starts again from your next message.');
    await loadMemories();
  } catch (error) {
    console.error('Forgetting how you write failed:', error);
    showError('Could not delete how you write.');
  }
}

/** `B820`. *How you write*, at the top of the Brain.
 *
 *  `P13-17` … `P13-20` landed the whole server half — a `kind: "style"` record,
 *  `GET /api/memory`'s `style` block, `PUT`/`DELETE` that already set
 *  `style_edited` and write the event — and the Brain drew none of it but the
 *  record as an ordinary card. `D-2026-09-09-01` makes this the acceptance
 *  criterion: *"a profile you cannot see is a profile you cannot correct"*, and
 *  *"edits are the only error signal this feature can have"*. Three things,
 *  each through the routes the page already calls:
 *
 *    * before a profile forms, how far along it is — *"18 of 20 messages
 *      seen"* — because a panel that can only say nothing reads as broken
 *      (`Law 15`);
 *    * once it forms, its lines, each one editable where it is printed; a
 *      change saves the joined lines through the record's `PUT`;
 *    * a delete that says it takes the counters with it and learning starts
 *      over, which a bin icon cannot say.
 *
 *  Everything printed is server text, so it goes in through `textContent` and
 *  `value`, never markup.
 */
export function renderStylePanel() {
  const host = document.getElementById('memory-style-panel');
  if (!host) return;
  const style = styleBlock;
  if (!style || typeof style !== 'object') {
    host.hidden = true;
    host.replaceChildren();
    return;
  }
  host.hidden = false;
  const kids = [];
  const head = document.createElement('div');
  head.className = 'memory-style-head';
  head.textContent = 'How you write';
  kids.push(head);

  const profile = style.profile;
  if (!profile) {
    const seen = Math.max(0, Number(style.observed) || 0);
    const needed = Math.max(0, Number(style.needed) || 0);
    const note = document.createElement('div');
    note.className = 'memory-style-progress';
    // `P13-18`: a person with no history is read as nothing, not as neutral —
    // said, so nobody wonders what a half-learned profile is doing to replies.
    note.textContent = `Still learning — ${seen} of ${needed} messages seen. `
      + 'What it notices about how you write appears here once there are enough;'
      + ' until then it changes nothing about how the assistant answers you.';
    kids.push(note);
    host.replaceChildren(...kids);
    return;
  }

  const sub = document.createElement('div');
  sub.className = 'memory-style-sub';
  sub.textContent = 'What the assistant has noticed about how you write. Change a line that is'
    + ' wrong; it saves when you leave the line.';
  kids.push(sub);

  const lines = styleLines(profile);
  const list = document.createElement('div');
  list.className = 'memory-style-lines';
  const inputs = [];
  lines.forEach((text, i) => {
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'memory-style-line';
    input.value = text;
    input.setAttribute('aria-label', `How you write, line ${i + 1}`);
    input.addEventListener('change', () => {
      _saveStyleLines(profile.id, inputs.map((el) => el.value));
    });
    inputs.push(input);
    list.appendChild(input);
  });
  kids.push(list);

  // `P13-18` … `P13-20`. The rest of what the feature does with this, in the
  // server's sentences (`memory_style.humour_account` / `reading_account`):
  // what the jokes have been learned to mean — stored, so it is part of what
  // *Forget* takes — and what a conversation is compared with this for, which
  // is never stored and so has nothing here to correct, only to read.
  for (const [cls, said] of [['memory-style-humour', profile.humour && profile.humour.sentence],
                             ['memory-style-reading', profile.reading]]) {
    if (typeof said !== 'string' || !said.trim()) continue;
    const line = document.createElement('div');
    line.className = `memory-style-sub ${cls}`;
    line.textContent = said;
    kids.push(line);
  }

  const forget = document.createElement('button');
  forget.type = 'button';
  forget.className = 'memory-toolbar-btn danger memory-style-forget';
  forget.textContent = 'Forget how I write';
  forget.title = 'Deletes the profile, the counts behind it and what your jokes were learned to mean. Learning starts again from nothing.';
  forget.addEventListener('click', () => _forgetStyle(profile.id));
  kids.push(forget);
  host.replaceChildren(...kids);
}

export async function loadMemories() {
  _ensureNewMemoryCategorySelect();
  memoriesLoading = true;
  renderMemoryList();
  updateMemoryCount();
  // `B1070`. Only asking and reading are inside the `try`: a fault while
  // drawing the list is the page's, and catching it here reported it as "the
  // server did not answer" — a false sentence about someone else.
  let data = null;
  try {
    const response = await fetch(`${window.location.origin}/api/memory`);
    if (response.status === 403) {
      // `SET-U-15` (P23-02): a person not allowed the Brain reads the server's
      // own sentence, not "No memories yet" over a refusal.
      memoriesRefused = (await readRefusal(response, 'Your account is not allowed to manage memory.')).sentence;
      memoriesError = memoriesRefused;
    } else if (!response.ok) {
      console.error('Memory fetch failed with status:', response.status);
      memoriesError = `the server answered ${response.status}`;
    } else {
      try {
        data = await response.json();
      } catch (error) {
        console.error('Memory list was not JSON:', error);
        memoriesError = 'its answer could not be read';
      }
    }
  } catch (error) {
    console.error('Failed to load memories:', error);
    memoriesError = 'the server did not answer';
  }

  if (data !== null) {
    memories = _memoriesFrom(data);
    styleBlock = (data && !Array.isArray(data) && data.style) || null;   // `B820`
    memoriesKnown = true;
    memoriesStale = false;
    memoriesError = '';
    memoriesRefused = '';
  } else {
    memories = [];
    styleBlock = null;
    memoriesKnown = false;
  }
  memoriesLoading = false;
  buildCategoryChips();
  buildStatusChips();
  renderStylePanel();
  renderMemoryList();
  updateMemoryCount();
  // Always wire toggles, even if memory API failed
  syncToggles();
}

/**
 * `B1070`. The Brain asks for its own list when it opens and does not know it
 * yet — the first open, or one after a failed load. Before this the window only
 * redrew what it had; the list came from `app.js`'s startup warmup (12 s after
 * boot, then an idle callback) or from `sessions.js` 2.5 s after a chat loaded,
 * so opening the Brain early showed nothing for as long as those took —
 * measured on the seeded demo, `GET /api/memory` 7.4 s after the click. The
 * requests seen before it were other warmups and polls, not a chain it waited
 * on. A list already known is left as it is: the existing refreshes keep it,
 * and redrawing it here would throw away an edit in progress.
 */
export function loadMemoriesIfUnknown() {
  if (memoriesLoading) return null;
  if (memoriesKnown && !memoriesStale) return null;
  return loadMemories();
}

/** `PERF-M-7` (P23-02). A chat switch may have added memories; a closed Brain
 *  is marked stale and re-reads when it next opens, instead of re-reading and
 *  redrawing on every switch whether anyone was looking or not. */
export function markMemoriesStale() { memoriesStale = true; }

// ---- Bulk select mode ----

const _SELECT_BTN_DOT_SVG = '<svg class="memory-select-btn-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:3px;"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/></svg>';
const _SELECT_BTN_X_SVG = '<svg class="memory-select-btn-icon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" style="vertical-align:-2px;margin-right:3px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

function enterSelectMode() {
  selectMode = true;
  selectedIds.clear();
  const bulkBar = document.getElementById('memory-bulk-bar');
  const selectBtn = document.getElementById('memory-select-btn');
  if (bulkBar) bulkBar.classList.remove('hidden');
  if (selectBtn) { selectBtn.classList.add('active'); selectBtn.innerHTML = _SELECT_BTN_X_SVG + 'Cancel'; }
  updateBulkCount();
  renderMemoryList();
}

function exitSelectMode() {
  selectMode = false;
  selectedIds.clear();
  const bulkBar = document.getElementById('memory-bulk-bar');
  const selectBtn = document.getElementById('memory-select-btn');
  const selectAll = document.getElementById('memory-select-all');
  if (bulkBar) bulkBar.classList.add('hidden');
  if (selectBtn) { selectBtn.classList.remove('active'); selectBtn.innerHTML = _SELECT_BTN_DOT_SVG + 'Select'; }
  if (selectAll) selectAll.checked = false;
  renderMemoryList();
}

function toggleSelectItem(id) {
  if (selectedIds.has(id)) {
    selectedIds.delete(id);
  } else {
    selectedIds.add(id);
  }
  updateBulkCount();
}

function updateBulkCount() {
  const countEl = document.getElementById('memory-selected-count');
  const deleteBtn = document.getElementById('memory-bulk-delete');
  if (countEl) countEl.textContent = `${selectedIds.size} Selected`;
  if (deleteBtn) deleteBtn.disabled = selectedIds.size === 0;
}

function toggleSelectAll() {
  const selectAllEl = document.getElementById('memory-select-all');
  if (!selectAllEl) return;

  if (selectAllEl.checked) {
    // Select all currently visible/filtered items
    const visible = getFilteredMemories();
    visible.forEach(m => selectedIds.add(m.id));
  } else {
    selectedIds.clear();
  }
  updateBulkCount();
  renderMemoryList();
}

async function bulkDelete() {
  if (selectedIds.size === 0) return;
  const count = selectedIds.size;
  if (!await uiModule.styledConfirm(`Delete ${count} ${count === 1 ? 'memory' : 'memories'}?`, { confirmText: 'Delete', danger: true })) return;

  let deleted = 0;
  const deletedIds = [];
  for (const id of selectedIds) {
    try {
      const res = await fetch(`${window.location.origin}/api/memory/${id}`, { method: 'DELETE' });
      if (res.ok) {
        deleted++;
        deletedIds.push(id);
      }
    } catch (e) {
      console.error('Failed to delete memory:', id, e);
    }
  }

  await animateMemoryRemoval(deletedIds);
  exitSelectMode();
  await loadMemories();
  showToast(`Deleted ${deleted} ${deleted === 1 ? 'memory' : 'memories'}`);
}

// ---- Tidy (audit) ----

/**
 * What the audit did, from its own response. `P9-10`.
 *
 * `superseded` and `contradictions` have been on `POST /api/memory/audit` since
 * `P13-09` and nothing read them, so the toast said `Tidied: 9 removed` about
 * nine memories of which eight were still on the record with a `supersedes`
 * edge naming what replaced them. *"9 removed"* is true and frightening;
 * *"9 removed \u2014 8 superseded, still on the record"* is the same fact and the
 * one a person can act on.
 *
 * Named and at module scope so a test can call it with a real response shape
 * rather than grep the toast out of a 70-line function (`Law 20`).
 */
export function describeMemoryTidy(data) {
  const d = data || {};
  const superseded = Number(d.superseded) || 0;
  const conflicts = Number(d.contradictions) || 0;
  // `B1569`. How many survivors' text the model rewrote — not on the wire;
  // `tidyMemories` counts it from the list before and after and adds it as
  // `rewritten`. `removed` is `before - after` and cannot see a rewrite.
  const edits = Number(d.rewritten) || 0;
  // `P9-09`. The route names the model that rewrote the memories, and only
  // when one was asked; provenance on what a model produced.
  const model = typeof d.model === 'string' ? d.model.trim() : '';
  let msg = `Tidied${model ? ` by ${model}` : ''}: ${edits ? `${edits} rewritten, ` : ''}${Number(d.removed) || 0} removed (${Number(d.before) || 0} \u2192 ${Number(d.after) || 0})`;
  if (superseded) msg += ` \u2014 ${superseded} superseded, still on the record`;
  if (conflicts) msg += `, ${conflicts} conflict${conflicts === 1 ? '' : 's'} left for you`;
  return msg;
}

/**
 * `B1578`. What the tidy's decay sweep retired, as a sentence, or ''.
 *
 * `P13-04` runs the fade first in every audit — arithmetic over dates, before
 * the model is asked and before `before` is counted — and the route has
 * answered `archived` since; nothing here read it. So a tidy whose sweep
 * retired memories said *Already clean*, or *0 removed*, or only why the model
 * pass stopped, and the memories left the chats with no word about where they
 * went. They are kept: the status row's *retired* filter lists them and *Bring
 * back* in a memory's menu (`B710`) commits one again. The window is the
 * server's (`archive_after_days`), so the page holds no copy of it.
 *
 * Starts with the count, so a caller can lead into it (`Separately, …`).
 */
export function describeTidyRetired(data) {
  const d = data || {};
  const n = Math.max(0, Math.floor(Number(d.archived) || 0));
  if (!n) return '';
  const days = Math.floor(Number(d.archive_after_days) || 0);
  const one = n === 1;
  return `${n} ${one ? 'memory' : 'memories'} nothing had used`
    + `${days > 0 ? ` in ${days} days` : ' for months'} ${one ? 'was' : 'were'} retired:`
    + ` the “retired” filter lists ${one ? 'it' : 'them'}, and Bring back in`
    + ` ${one ? 'its' : 'a memory’s'} menu restores ${one ? 'it' : 'one'}.`;
}

/**
 * `P9-10`. The memory tidy asks before it runs, and says what it found after.
 *
 * The row's premise about this surface is right and understated: the animation
 * is a diff of a change that has **already been committed**. `POST
 * /api/memory/audit` runs the model, writes the result, and only then does this
 * function fetch `/api/memory` again and animate the difference between the
 * list it snapshotted and the list that now exists. Nothing between the click
 * and the write can be reviewed, and there is no dry run to ask for — that is
 * the half named on the row.
 *
 * What was wrong on this side of the wire is the report. `routes/memory/
 * memory_routes.py` answers with `superseded` and `contradictions` beside
 * `removed`, added by `P13-09` with a comment saying exactly why: *"a person
 * reading '9 removed' can be told that 8 of them are recoverable and only one
 * was genuinely junk."* This file read neither. The toast said `Tidied: 9
 * removed` about nine memories of which eight were still on the record with a
 * `supersedes` edge naming what replaced them — the most alarming possible
 * reading of the friendliest possible outcome, and the reassurance that fixes
 * it had been on the wire, unread, since `P13-09`.
 */
export async function tidyMemories() {
  const ok = await uiModule.styledConfirm(
    'Your model merges duplicates and rewrites the survivors.',
    {
      title: 'Tidy memories',
      confirmText: 'Tidy memories',
      danger: true,
      details: {
        heading: 'What Tidy does',
        items: [
          { label: 'Sends your stored memories to your model', note: 'one call' },
          { label: 'Merges duplicates and rewrites the text of the survivor', note: 'rewrites' },
          { label: 'Stops the merged ones surfacing', note: 'mostly recoverable' },
          { label: 'Records conflicts it could not settle', note: 'nothing deleted' },
        ],
        // `D-14` (P23-02, Doc 2 § 5): the four rows stay; two paragraphs go.
        footnote: 'Merged entries are kept, not deleted. No preview.',
      },
    },
  );
  if (!ok) return;
  // `P9-11`. The one call below runs the whole audit — a model reading every
  // memory — and it is the longest thing this modal does. Closing the Brain
  // does not cancel it; `await` keeps going and the list is rewritten on the
  // server whether or not this window is still on screen. The spinner lives on
  // a button inside that window, so before this row the only way to know it was
  // still running was to leave the Brain open and watch it.
  //
  // `key` because the Brain also hosts the skills audit (`skills.js`), and the
  // two can run at once.
  setBackgroundWork('memory-modal', {
    key: 'memory-tidy',
    label: 'Tidying memories',
    detail: 'Brain: tidying memories — your model is reading the list and rewriting it',
  });
  const tidyBtn = document.getElementById('memory-tidy-btn');
  let tidySpinner = null;
  if (tidyBtn) {
    tidyBtn.disabled = true;
    tidyBtn.textContent = '';
    // Drop the button border while the whirlpool spins — just the spinner,
    // no box around it (restored in the finally below).
    tidyBtn.style.border = 'none';
    tidyBtn.style.background = 'none';
    tidySpinner = spinnerModule.create('', 'clean', 'whirlpool');
    const _spEl = tidySpinner.createElement();
    _spEl.style.position = 'relative';
    _spEl.style.top = '1px';
    tidyBtn.appendChild(_spEl);
    tidySpinner.start();
  }

  // Snapshot current state for diffing
  const beforeMap = new Map(memories.map(m => [m.id, { ...m }]));

  try {
    const res = await fetch(`${window.location.origin}/api/memory/audit`, {
      method: 'POST',
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Audit failed');
    }

    const data = await res.json();
    // `B1578`. The decay sweep runs before the model on every path below,
    // including the two early returns, so what it retired is said on each —
    // and the list is drawn again, or the retired rows keep their old badge
    // and the *retired* filter the sentence points at is not there.
    const retired = describeTidyRetired(data);
    // `B1569`. A pass that stopped — the model's reply was not a usable list,
    // it would have removed most of the store, or the store could not be read
    // back — answers 200 with `ok: false` and `before === after`. That read as
    // `removed: 0` and said *Already clean* about a tidy that did nothing.
    if (data && data.ok === false) {
      const why = String(data.reason || 'Tidy stopped and changed nothing. The server log says why.');
      if (retired) await loadMemories();
      showError(retired ? `${why} Separately, ${retired}` : why);
      return;
    }
    // The server skipped the model: nothing changed since the last tidy.
    if (data && data.already_tidy === true && !(Number(data.removed) > 0)) {
      if (retired) await loadMemories();
      showToast(retired ? `Already clean. ${retired}` : 'Already clean', retired ? 9000 : undefined);
      return;
    }

    // Fetch the new state
    const freshRes = await fetch(`${window.location.origin}/api/memory`);
    const freshData = await freshRes.json();
    const afterList = _memoriesFrom(freshData);   // `B1071`: the same rows the list draws
    const afterMap = new Map(afterList.map(m => [m.id, m]));

    // Compute diff
    const removed = [];   // IDs that no longer exist
    const edited = [];    // IDs where text changed
    for (const [id, oldMem] of beforeMap) {
      if (!afterMap.has(id)) {
        removed.push(id);
      } else if (afterMap.get(id).text !== oldMem.text) {
        edited.push({ id, oldText: oldMem.text, newText: afterMap.get(id).text });
      }
    }

    // `B1569`. *Already clean* is decided here, after the diff, and not on
    // `removed` alone: `removed` is `before - after`, so a tidy that merged
    // nothing and rewrote one memory answered 0 and was called clean while
    // the rewritten text sat in the list unannounced.
    if (!removed.length && !edited.length && !(Number(data.removed) > 0)) {
      if (retired) {
        // `B1578`. Nothing merged or rewritten, but the sweep retired some:
        // draw the list the server now holds, then say so.
        memories = afterList;
        buildCategoryChips();
        buildStatusChips();
        renderMemoryList();
        updateMemoryCount();
      }
      showToast(retired ? `Already clean. ${retired}` : 'Already clean', retired ? 9000 : undefined);
      return;
    }

    if (tidySpinner) tidySpinner.updateMessage('Tidying memories');

    // Animate the diff on the currently rendered list
    await animateTidyDiff(removed, edited);

    // Now load the clean state
    memories = afterList;
    buildCategoryChips();
    buildStatusChips();
    renderMemoryList();
    updateMemoryCount();

    const said = describeMemoryTidy({ ...data, rewritten: edited.length });
    showToast(retired ? `${said}. ${retired}` : said, retired ? 9000 : undefined);
  } catch (error) {
    console.error('Tidy failed:', error);
    showError('Tidy failed — check console');
  } finally {
    // The chip goes when the job goes, on every exit — including the early
    // `return`s above for "Already clean" and a stopped pass, which leave
    // through here too (and so does the button's reset they each did by hand).
    setBackgroundWork('memory-modal', { key: 'memory-tidy' });
    if (tidySpinner) tidySpinner.destroy();
    if (tidyBtn) {
      tidyBtn.disabled = false;
      tidyBtn.style.border = '';
      tidyBtn.style.background = '';
      tidyBtn.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" style="vertical-align:-1px;margin-right:2px;color:var(--accent, var(--red));"><path d="M12 0L14.59 8.41L23 12L14.59 15.59L12 24L9.41 15.59L1 12L9.41 8.41Z"/></svg> Tidy';
    }
  }
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

async function animateMemoryRemoval(ids) {
  const idSet = new Set([...ids].map(id => String(id)));
  const memoryList = document.getElementById('memory-list');
  if (!memoryList || !idSet.size) return;
  const items = Array.from(memoryList.querySelectorAll('.memory-item[data-memory-id]'))
    .filter(el => idSet.has(String(el.dataset.memoryId)));
  if (!items.length) return;
  for (const el of items) {
    el.style.maxHeight = `${Math.max(el.getBoundingClientRect().height, el.scrollHeight)}px`;
    el.classList.add('memory-tidy-removing');
  }
  await sleep(520);
}

async function animateTidyDiff(removedIds, editedItems) {
  const memoryList = document.getElementById('memory-list');
  if (!memoryList) return;

  // Tag each rendered item with its memory ID for lookup
  const items = memoryList.querySelectorAll('.memory-item');
  const itemMap = new Map();
  const filtered = getFilteredMemories();
  items.forEach((el, i) => {
    if (filtered[i]) itemMap.set(filtered[i].id, el);
  });

  // Animate edits first — show text morphing
  for (const { id, oldText, newText } of editedItems) {
    const el = itemMap.get(id);
    if (!el) continue;

    const textEl = el.querySelector('.memory-item-text');
    if (!textEl) continue;

    el.classList.add('memory-tidy-editing');
    textEl.classList.add('memory-tidy-text-old');
    await sleep(300);

    textEl.textContent = newText;
    textEl.classList.remove('memory-tidy-text-old');
    textEl.classList.add('memory-tidy-text-new');
    await sleep(400);

    el.classList.remove('memory-tidy-editing');
    textEl.classList.remove('memory-tidy-text-new');
    await sleep(100);
  }

  // Animate removals — strikethrough then fade out
  for (const id of removedIds) {
    const el = itemMap.get(id);
    if (!el) continue;

    el.classList.add('memory-tidy-removing');
    await sleep(200);
  }

  // Let all removals animate together, then wait for them to finish
  if (removedIds.length > 0) {
    await sleep(500);
  }
}

// ---- "Would fire" — the retrieval diagnostic (H11) ----
//
// `POST /api/memory/debug` has been live, owner-scoped and documented as
// "debug which memories would be triggered for a query", with no caller
// anywhere in `static/`. It could only ever answer the WHICH, because the
// scorer computed a score and a boost and dropped both on its last line;
// `explain_relevant_memories` keeps them, and this shows them.
//
// The value of asking without sending: retrieval decides what the agent sees,
// and until you can interrogate it, a wrong answer and a wrong memory look
// identical from the outside. Building this is what surfaced `B40`.
let _fireResult = null;   // { order: [id], byId: {id: {score, reason}}, queryType, query }
let _fireTimer = null;
let _fireSeq = 0;

function _fireMode() {
  return document.getElementById('memory-search-mode')?.value === 'fire';
}

function _clearFire() {
  _fireResult = null;
  const note = document.getElementById('memory-fire-note');
  if (note) { note.hidden = true; note.textContent = ''; }
}

async function _runFireQuery(query) {
  // Sequence guard: a slow response for an earlier keystroke must not
  // overwrite a newer one. Without it the list flickers back to a stale
  // answer, which in a diagnostic is worse than no answer.
  const seq = ++_fireSeq;
  const note = document.getElementById('memory-fire-note');
  try {
    const body = new URLSearchParams();
    body.set('query', query);
    const res = await fetch('/api/memory/debug', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (seq !== _fireSeq) return;
    const byId = {};
    for (const row of (data.explanations || [])) byId[row.id] = row;
    _fireResult = {
      order: (data.memories || []).map((m) => m.id),
      byId,
      queryType: data.query_type,
      query,
    };
    if (note) {
      const n = _fireResult.order.length;
      // The query type is the single most surprising thing a person learns
      // here, so it is stated plainly rather than hidden in a tooltip.
      // `D-12` (P23-02): one line; the question type only when there is one.
      note.textContent = `${n} memor${n === 1 ? 'y' : 'ies'} would be used`
        + (_fireResult.queryType ? ` (read as a ${_fireResult.queryType} question).` : '.');
      note.hidden = false;
    }
  } catch (e) {
    if (seq !== _fireSeq) return;
    _fireResult = null;
    if (note) { note.textContent = 'Could not run the retrieval check.'; note.hidden = false; }
  }
  renderMemoryList();
}

function initMemorySearchMode() {
  const mode = document.getElementById('memory-search-mode');
  const search = document.getElementById('memory-search');
  if (!mode || !search) return;

  const refresh = () => {
    const query = search.value.trim();
    if (!_fireMode() || !query) { _clearFire(); renderMemoryList(); return; }
    clearTimeout(_fireTimer);
    _fireTimer = setTimeout(() => _runFireQuery(query), 250);
  };

  mode.addEventListener('change', refresh);
  search.addEventListener('input', () => { if (_fireMode()) refresh(); });
}

// ---- Filtering helper ----

function getFilteredMemories() {
  const searchTerm = document.getElementById('memory-search')?.value?.toLowerCase().trim() || '';

  // H11. In "would fire" mode the server has already chosen and ordered the
  // memories, and that ORDER is the answer — re-sorting it here by date or
  // pinned-ness would throw away the only thing the diagnostic is for.
  if (_fireResult) {
    const byId = new Map(memories.map((m) => [m.id, m]));
    return _fireResult.order.map((id) => byId.get(id)).filter(Boolean);
  }

  let filtered = searchTerm
    ? memories.filter(m => m.text && m.text.toLowerCase().includes(searchTerm))
    : [...memories];

  if (activeCategory !== 'all') {
    filtered = filtered.filter(m => (m.category || 'fact') === activeCategory);
  }

  // `B710`. Explore's own clause, called rather than copied. `matches` applies
  // every other clause at its `any` default, which passes — so this asks
  // exactly one question, and asks it the way the other surface does.
  if (activeStatus !== 'any') {
    filtered = filtered.filter(m => memoryMatchesFilter(m, { status: activeStatus }, 0));
  }

  const sortSelect = document.getElementById('memory-sort');
  const sort = sortSelect ? sortSelect.value : sortOrder;
  if (sort === 'newest') {
    filtered.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
  } else if (sort === 'oldest') {
    filtered.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
  } else if (sort === 'alpha') {
    filtered.sort((a, b) => (a.text || '').localeCompare(b.text || ''));
  } else if (sort === 'uses') {
    filtered.sort((a, b) => (b.uses || 0) - (a.uses || 0) || (b.timestamp || 0) - (a.timestamp || 0));
  } else if (sort === 'mentions') {
    // `P13-15`. Its own sort rather than a tweak to "Most used", because the
    // two orders answer different questions and merging them would produce a
    // list nobody could interpret.
    filtered.sort((a, b) => (b.mention_sessions || 0) - (a.mention_sessions || 0)
      || (b.mentions || 0) - (a.mentions || 0)
      || (b.timestamp || 0) - (a.timestamp || 0));
  }

  // Pinned always float to top
  filtered.sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0));

  return filtered;
}

// ---- Render ----

export function renderMemoryList() {
  const memoryList = document.getElementById('memory-list');
  if (!memoryList) {
    console.error('Memory list element not found');
    return;
  }

  const filtered = getFilteredMemories();
  memoryList.innerHTML = '';

  if (filtered.length === 0) {
    const selectBtn = document.getElementById('memory-select-btn');
    if (selectBtn) selectBtn.disabled = true;
    if (selectMode) exitSelectMode();
    if (memoriesLoading || (!memoriesKnown && !memoriesError)) {
      const row = spinnerModule.createLoadingRow('Loading memories...', 14);
      row.classList.add('memory-empty');
      memoryList.replaceChildren(row);
      return;
    }
    // `B730`. The three ways this list is empty, each in the one shared shape
    // (`ui.renderEmptyState`) and each with its way out: the store could not
    // be read (its words, and *Try again*), nothing survives the filters
    // (*Clear filters*), and there is nothing at all (*Add one*). The class
    // `memory-empty` rides along so the CSS written for it still applies.
    if (memoriesError) {
      // `B1070`. A failed load is not an empty store either. A refusal is the
      // server's own sentence, and asking again would only be refused again.
      uiModule.renderEmptyState(memoryList, {
        kind: 'error',
        className: 'memory-empty',
        title: memoriesRefused ? 'Not allowed' : 'Could not load memories',
        reason: memoriesRefused || `Could not load memories — ${memoriesError}.`,
        onRetry: memoriesRefused ? undefined : () => { loadMemories(); },
      });
      return;
    }
    const searchTerm = document.getElementById('memory-search')?.value?.trim() || '';
    // `B710` adds the third thing that can empty this list. Without it a
    // status chip with no survivors reads "No memories yet." over a full
    // store, which is the false empty state `B1070` is about wearing a
    // different hat.
    if (searchTerm || activeCategory !== 'all' || activeStatus !== 'any') {
      uiModule.renderEmptyState(memoryList, {
        kind: 'filtered',
        className: 'memory-empty',
        title: 'No matches.',
        message: 'Nothing here fits the search and filters above.',
        action: { label: 'Clear filters', onClick: () => clearMemoryFilters() },
      });
    } else {
      // Doc 2 § 5, rule 8: one line, and the action beside it.
      uiModule.renderEmptyState(memoryList, {
        kind: 'empty',
        className: 'memory-empty',
        title: 'No memories yet.',
        action: { label: 'Add one', onClick: () => showBrainTab('add', { focus: true }) },
      });
    }
    return;
  }

  const selectBtn = document.getElementById('memory-select-btn');
  if (selectBtn) selectBtn.disabled = false;

  filtered.forEach(memory => {
    const item = document.createElement('div');
    item.className = 'memory-item';
    item.dataset.memoryId = String(memory.id);

    // Checkbox for select mode
    if (selectMode) {
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.className = 'memory-select-cb';
      cb.checked = selectedIds.has(memory.id);
      cb.addEventListener('change', () => {
        toggleSelectItem(memory.id);
        const selectAllEl = document.getElementById('memory-select-all');
        if (selectAllEl) selectAllEl.checked = filtered.every(m => selectedIds.has(m.id));
      });
      item.appendChild(cb);
      item.style.cursor = 'pointer';
      item.addEventListener('click', (e) => {
        if (e.target === cb) return;
        cb.checked = !cb.checked;
        cb.dispatchEvent(new Event('change'));
      });
    }

    // Content: text + metadata
    const content = document.createElement('div');
    content.className = 'memory-item-content';

    const textSpan = document.createElement('span');
    textSpan.className = 'memory-item-text';
    textSpan.textContent = memory.text;

    const meta = document.createElement('div');
    meta.className = 'memory-item-meta';

    // `B710`. First in the strip, and before `pinned`, because it qualifies
    // every other chip on the row: a confidence, a use count and a pin on a
    // memory that reaches no chat all mean something different, and a reader
    // who learns that at the end of the line has read the row wrong.
    // `null` for a committed memory — see `memoryStatusBadge`.
    const statusBadge = memoryStatusBadge(memory);
    if (statusBadge) {
      const span = document.createElement('span');
      span.className = statusBadge.className;
      span.textContent = statusBadge.text;
      span.title = statusBadge.title;
      meta.appendChild(span);
      item.classList.add('memory-item-' + statusBadge.status);
    }

    if (memory.pinned) {
      const pinBadge = document.createElement('span');
      pinBadge.className = 'memory-cat-badge memory-cat-pinned';
      pinBadge.textContent = 'pinned';
      meta.appendChild(pinBadge);
    }

    const catBadge = document.createElement('span');
    const cat = memory.category || 'fact';
    catBadge.className = 'memory-cat-badge memory-cat-' + cat;
    catBadge.textContent = cat;
    meta.appendChild(catBadge);

    const srcSpan = document.createElement('span');
    srcSpan.className = 'memory-item-source';
    srcSpan.textContent = memory.source === 'auto' ? 'auto' : 'manual';
    meta.appendChild(srcSpan);

    // H11. Why this one came back, on the row it belongs to. The reason is
    // server-supplied prose, so textContent — and it goes in `title` as well
    // because it is a sentence and the meta row is a strip of chips.
    const fired = _fireResult && _fireResult.byId[memory.id];
    if (fired) {
      const whySpan = document.createElement('span');
      whySpan.className = 'memory-item-why';
      whySpan.style.cssText = 'opacity:0.75;';
      whySpan.textContent = `score ${fired.score}`;
      whySpan.title = fired.reason || '';
      meta.appendChild(whySpan);
      const reasonSpan = document.createElement('span');
      reasonSpan.className = 'memory-item-why-text';
      reasonSpan.style.cssText = 'opacity:0.6;font-style:italic;';
      reasonSpan.textContent = fired.reason || '';
      meta.appendChild(reasonSpan);
    }

    // `P13-01` / `B643`. Confidence goes where it can be CORRECTED, which is
    // this list and not only the chat pill: a confidence a person cannot see
    // is a confidence they cannot fix. It is first because it qualifies the
    // memory itself, where the two counts beside it are about its history.
    for (const pill of [memoryConfidencePill(memory), ...memoryCountPills(memory)]) {
      if (!pill) continue;   // not recorded — no pill, not an empty one
      const span = document.createElement('span');
      span.className = pill.className;
      span.textContent = pill.text;
      span.title = pill.title;
      meta.appendChild(span);
    }

    if (memory.timestamp) {
      const timeSpan = document.createElement('span');
      timeSpan.className = 'memory-item-time';
      timeSpan.textContent = relativeTime(memory.timestamp);
      timeSpan.title = new Date(memory.timestamp * 1000).toLocaleString();
      meta.appendChild(timeSpan);
    }

    content.appendChild(textSpan);
    content.appendChild(meta);
    // `B821`. A memory about to go quiet says so on its card, before the tidy
    // archives it — the server's reason and days (`memoryFadeLine`).
    const fades = memoryFadeLine(memory);
    if (fades) {
      const line = document.createElement('div');
      line.className = 'memory-item-fades';
      line.textContent = fades;
      content.appendChild(line);
    }

    if (memory.pinned) item.classList.add('memory-pinned');

    item.appendChild(content);

    // Double-click text to edit (not in select mode)
    if (!selectMode) {
      textSpan.addEventListener('dblclick', (e) => {
        e.stopPropagation();
        startInlineEdit(item, memory);
      });
      textSpan.style.cursor = 'text';
    }

    // Menu button (hidden in select mode)
    if (!selectMode) {
      const menuBtn = document.createElement('button');
      menuBtn.type = 'button';
      menuBtn.className = 'memory-menu-btn';
      menuBtn.innerHTML = '\u22EE';
      menuBtn.title = 'Actions';
      menuBtn.setAttribute('aria-label', 'Actions');
      menuBtn.setAttribute('aria-haspopup', 'menu');
      menuBtn.setAttribute('aria-expanded', 'false');

      // `PERF-M-3` / `BRAIN-U-6` (P23-02). The menu is built when it opens and
      // dismissed through `bindMenuDismiss`, as the skill kebab is. It used to
      // be built for every memory on every render, each copy adding a
      // `document` click listener that nothing removed — and the list is
      // redrawn on every Brain open, so 67 memories × 6 opens left +402 click
      // listeners on `document` (CDP `getEventListeners`, measured on
      // `32df791`), each holding a detached list alive, and every click
      // anywhere ran all of them. Its items were `<div>`s: Tab and the arrows
      // never reached them.
      menuBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (menuBtn._closeMenu) { menuBtn._closeMenu(); return; }
        _openMemoryMenu(menuBtn, item, memory);
      });

      item.appendChild(menuBtn);

      // Long-press anywhere on the card opens the same dropdown — mirrors the
      // documents library pattern. Skip when the touch starts on the kebab,
      // checkbox, or another button (those have their own click handlers).
      {
        let hold = null;
        let start = null;
        const _lpCancel = () => { if (hold) { clearTimeout(hold); hold = null; } start = null; };
        item.addEventListener('pointerdown', (e) => {
          if (e.target.closest('.memory-menu-btn, .memory-select-cb, button, input')) return;
          start = { x: e.clientX, y: e.clientY };
          hold = setTimeout(() => {
            hold = null;
            item._suppressNextClick = true;
            setTimeout(() => { item._suppressNextClick = false; }, 400);
            if (navigator.vibrate) try { navigator.vibrate(15); } catch {}
            menuBtn.click();
          }, 500);
        });
        item.addEventListener('pointermove', (e) => {
          if (!start) return;
          if (Math.hypot(e.clientX - start.x, e.clientY - start.y) > 10) _lpCancel();
        });
        item.addEventListener('pointerup', _lpCancel);
        item.addEventListener('pointercancel', _lpCancel);
      }

    }

    memoryList.appendChild(item);
  });

}

/** One memory's ⋮ menu, built on open and gone on close (`PERF-M-3`). */
function _openMemoryMenu(menuBtn, item, memory) {
  // One menu at a time, each torn down through its own dismiss so its Escape
  // entry and its outside-click listener go with it.
  document.querySelectorAll('.memory-item-dropdown').forEach(dismissOrRemove);
  const dropdown = document.createElement('div');
  dropdown.className = 'memory-item-dropdown';
  dropdown.setAttribute('role', 'menu');
  const close = bindMenuDismiss(dropdown, () => {
    dropdown.remove();
    menuBtn._closeMenu = null;
    menuBtn.setAttribute('aria-expanded', 'false');
  }, (ev) => !dropdown.contains(ev.target) && !menuBtn.contains(ev.target));
  menuBtn._closeMenu = close;
  menuBtn.setAttribute('aria-expanded', 'true');

  const addItem = (cls, html, onPick) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.setAttribute('role', 'menuitem');
    b.className = 'dropdown-item-compact' + (cls ? ' ' + cls : '');
    b.innerHTML = html;
    b.addEventListener('click', (e) => { e.stopPropagation(); close(); if (onPick) onPick(); });
    dropdown.appendChild(b);
    return b;
  };
  // Pin / Unpin — bookmark icon matches the chat-session "Favorite" SVG.
  // Filled when pinned, outlined when not.
  const _bookmarkPath = '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>';
  const _pinSvg = memory.pinned
    ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${_bookmarkPath}</svg>`
    : `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${_bookmarkPath}</svg>`;
  addItem('', `<span class="dropdown-icon" aria-hidden="true">${_pinSvg}</span><span>${memory.pinned ? 'Unpin' : 'Pin'}</span>`,
    () => togglePin(memory.id, !memory.pinned));
  // Select — enters bulk-select mode and pre-selects this memory. Same
  // pattern as the email/documents/skills Select item.
  addItem('', '<span class="dropdown-icon" aria-hidden="true"><span style="font-size:16px;line-height:1;">●</span></span><span>Select</span>', () => {
    if (!selectMode) enterSelectMode();
    selectedIds.add(memory.id);
    updateBulkCount();
    renderMemoryList();
  });
  // `B710`. Commit, and **only on a memory that is not committed**. A control
  // that is present and refuses is how the Brain ends up teaching everybody a
  // word for a state their store is never in; `commit_memory` already refuses
  // an already-committed record, so this is the menu agreeing with the gate
  // rather than a second rule about it (`Law 14`).
  //
  // Above Edit, because an edit on a proposal is a different act — the import
  // path already treats saving one AS committing it — and a reader who meets
  // Edit first will take the longer way round to the same place.
  if (memoryStatus(memory) !== 'committed') {
    const proposed = memoryStatus(memory) === 'proposed';
    const b = addItem('', '<span class="dropdown-icon" aria-hidden="true">'
      + '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
      + ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
      + '<polyline points="20 6 9 17 4 12"/></svg></span>'
      + `<span>${proposed ? 'Commit' : 'Bring back'}</span>`,
      () => commitMemory(memory.id));
    b.title = proposed
      ? 'Start using this. It can reach chats from now on.'
      : 'Commit it again, so it can reach chats. The gate still refuses a '
        + 'duplicate of something the Brain already holds.';
  }
  addItem('', '<span aria-hidden="true">✎</span> Edit', () => startInlineEdit(item, memory));
  addItem('memory-dropdown-delete', '<span aria-hidden="true">✕</span> Delete', () => deleteMemory(memory.id));
  // Mobile-only Cancel — mirrors the email/documents popup pattern. CSS
  // hides `.dropdown-cancel-mobile` on desktop where outside-click already
  // dismisses cleanly.
  addItem('dropdown-cancel-mobile', '<span aria-hidden="true">✕</span> Cancel', null);

  const rect = menuBtn.getBoundingClientRect();
  dropdown.style.position = 'fixed';
  dropdown.style.top = rect.bottom + 2 + 'px';
  dropdown.style.right = (window.innerWidth - rect.right) + 'px';
  dropdown.style.left = 'auto';
  // Portaled to <body>, so it must outrank the Brain modal it belongs to.
  // Tool modals get a monotonically increasing z-index from modalManager's
  // bring-to-front counter, which climbs unbounded over a long session —
  // once it passed the old hardcoded 10001 the menu rendered behind the
  // panel (#4720). topPortalZ() derives the value from the live tool-window
  // stack so the menu always sits just above, however high it has climbed.
  dropdown.style.zIndex = String(topPortalZ());
  dropdown.style.display = 'block';
  document.body.appendChild(dropdown);
  // Keep on-screen (mobile): flip above the button if it overflows the
  // bottom, clamp the left edge, cap height as a last resort.
  const dr = dropdown.getBoundingClientRect();
  if (dr.bottom > window.innerHeight - 6) {
    dropdown.style.top = Math.max(6, rect.top - dr.height - 2) + 'px';
  }
  if (dr.left < 6) {
    dropdown.style.right = Math.max(6, window.innerWidth - 6 - dr.width) + 'px';
  }
  const dr2 = dropdown.getBoundingClientRect();
  if (dr2.bottom > window.innerHeight - 6) {
    dropdown.style.maxHeight = Math.max(80, window.innerHeight - 12 - dr2.top) + 'px';
    dropdown.style.overflowY = 'auto';
  }

  // Swipe-down-to-dismiss — mirrors the documents library popup gesture.
  // Drag the popup down past ~60px and release to close; release earlier
  // and it snaps back. Vertical-only; horizontal flicks fall through. The
  // three listeners are on the menu, so they go with it.
  let _sw = null;
  let _swDy = 0;
  dropdown.addEventListener('touchstart', (ev) => {
    if (ev.touches.length !== 1) return;
    _sw = { x: ev.touches[0].clientX, y: ev.touches[0].clientY };
    _swDy = 0;
    dropdown.style.transition = '';
  }, { passive: true });
  dropdown.addEventListener('touchmove', (ev) => {
    if (!_sw || ev.touches.length !== 1) return;
    const dx = ev.touches[0].clientX - _sw.x;
    const dy = ev.touches[0].clientY - _sw.y;
    if (Math.abs(dy) < Math.abs(dx)) { _sw = null; return; }
    if (dy > 0) {
      _swDy = dy;
      dropdown.style.transform = 'translateY(' + dy + 'px)';
      dropdown.style.opacity = String(Math.max(0.3, 1 - dy / 240));
    }
  }, { passive: true });
  dropdown.addEventListener('touchend', () => {
    if (!_sw) return;
    _sw = null;
    if (_swDy > 60) {
      dropdown.style.transition = 'transform 0.15s ease, opacity 0.15s ease';
      dropdown.style.transform = 'translateY(120px)';
      dropdown.style.opacity = '0';
      setTimeout(close, 160);
    } else {
      dropdown.style.transition = 'transform 0.18s ease, opacity 0.18s ease';
      dropdown.style.transform = '';
      dropdown.style.opacity = '';
    }
  });
}

// ---- Inline edit with category picker ----

function startInlineEdit(item, memory) {
  item.innerHTML = '';
  item.className = 'memory-item memory-item-editing';

  const editRow = document.createElement('div');
  editRow.className = 'memory-edit-row';

  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'memory-item-edit-input';
  input.value = memory.text;

  const catSelect = document.createElement('select');
  catSelect.className = 'memory-edit-cat-select';
  MEMORY_CATEGORIES.forEach(cat => {
    const opt = document.createElement('option');
    opt.value = cat;
    opt.textContent = cat;
    if (cat === (memory.category || 'fact')) opt.selected = true;
    catSelect.appendChild(opt);
  });

  editRow.appendChild(input);
  editRow.appendChild(catSelect);

  const actions = document.createElement('div');
  actions.className = 'memory-item-actions';
  actions.style.opacity = '1';

  const saveBtn = document.createElement('button');
  saveBtn.className = 'memory-item-btn save';
  saveBtn.textContent = 'Save';
  saveBtn.addEventListener('click', () => saveInlineEdit(memory.id, input.value, catSelect.value));

  const cancelBtn = document.createElement('button');
  cancelBtn.className = 'memory-item-btn';
  cancelBtn.textContent = 'Cancel';
  cancelBtn.addEventListener('click', () => renderMemoryList());

  actions.appendChild(saveBtn);
  actions.appendChild(cancelBtn);

  item.appendChild(editRow);
  item.appendChild(actions);

  input.focus();
  input.select();

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') saveInlineEdit(memory.id, input.value, catSelect.value);
    if (e.key === 'Escape') {
      e.stopPropagation();
      e.stopImmediatePropagation();
      renderMemoryList();
    }
  });
}

/** The one writer of a correction. `P13-07` reuses it rather than sending its
 *  own `PUT`: a second place that saves an edit is a second place to forget to
 *  reload the list, re-index the vector or report a refusal (`Law 14`). */
export async function saveInlineEdit(id, newText, newCategory) {
  newText = newText.trim();
  if (!newText) return;

  const memory = memories.find(m => m.id === id);
  const catChanged = newCategory && newCategory !== (memory?.category || 'fact');
  if (!memory || (newText === memory.text && !catChanged)) {
    renderMemoryList();
    return;
  }

  try {
    const params = new URLSearchParams({ text: newText });
    if (newCategory) params.append('category', newCategory);

    const response = await fetch(`${window.location.origin}/api/memory/${id}`, {
      method: 'PUT',
      body: params
    });

    if (response.ok) {
      await loadMemories();
      showToast('Memory updated');
    } else {
      const errorData = await response.json();
      throw new Error(errorData.detail || 'Failed to update memory');
    }
  } catch (error) {
    console.error('Error updating memory:', error);
    showError('Failed to update memory');
  }
}

export function updateMemoryCount() {
  const h2Count = document.getElementById('memory-count-h2');
  const tabCount = document.getElementById('memory-count'); // optional (may be absent)
  if (!h2Count && !tabCount) return;
  if (memoriesLoading || !memoriesKnown) {
    // `B1070`: "0 memories" before the store has answered is a guess.
    if (h2Count) h2Count.textContent = '';
    if (tabCount) tabCount.textContent = memoriesError ? '' : '...';
    return;
  }

  const searchInput = document.getElementById('memory-search');
  const searchTerm = searchInput ? searchInput.value.toLowerCase().trim() : '';

  let visible = memories;
  const scopeTotal = visible.length;
  if (searchTerm) {
    visible = visible.filter(m => m.text && m.text.toLowerCase().includes(searchTerm));
  }
  if (activeCategory !== 'all') {
    visible = visible.filter(m => (m.category || 'fact') === activeCategory);
  }
  // `B710`. The same clause the list applies, so the header cannot say
  // "7 of 9" over a list of three.
  if (activeStatus !== 'any') {
    visible = visible.filter(m => memoryMatchesFilter(m, { status: activeStatus }, 0));
  }

  // `COPY-U-15` (P23-02). A count is said once: the tab carries it, and the
  // header under it is bare — "Memories 7 memories" under a tab reading
  // "Memories 7" was the same number twice. The header speaks only when a
  // search or a category hides some, and then says how many of how many.
  if (h2Count) h2Count.textContent = visible.length === scopeTotal ? '' : `${visible.length} of ${scopeTotal}`;
  if (tabCount) tabCount.textContent = String(scopeTotal);
}

export async function addNewMemory() {
  const input = document.getElementById('new-memory-input');
  const text = input.value.trim();
  const category = _readNewMemoryCategory();

  if (!text) {
    showError('Memory text cannot be empty');
    return;
  }

  try {
    const response = await fetch(`${window.location.origin}/api/memory/add`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        text: text,
        category: category,
      })
    });

    if (response.ok) {
      input.value = '';
      await loadMemories();
      showToast('Memory added');
    } else {
      throw new Error((await readRefusal(response, 'Could not add the memory.')).sentence);
    }
  } catch (error) {
    console.error('Error adding memory:', error);
    showError((error && error.message) || 'Could not add the memory.');
  }
}

/** `B710`. Bind a proposal, and say what the gate said.
 *
 *  **A refusal is an answer, not a failure**, and the route already says so by
 *  returning 200 with a verdict. The sentence it produces is the most useful
 *  thing on this path — *the Brain already knows this — "User is allergic to
 *  shellfish"* names the memory that makes this one redundant — and a
 *  generic banner would throw it away, which is what `Law 10` is about: a
 *  refusal and an error are different events and one display cannot mean both.
 *
 *  So a refusal is a toast carrying the server's own words, the list is
 *  reloaded either way (the gate records a restatement on a duplicate, so the
 *  row a reader is looking at has genuinely changed even when nothing was
 *  committed), and nothing is phrased as *failed*.
 */
export async function commitMemory(id) {
  try {
    const res = await fetch(`${window.location.origin}/api/memory/${id}/commit`,
                            { method: 'POST', credentials: 'same-origin' });
    if (!res.ok) {
      // A 404 or a 403 is the one case that genuinely is an error: the gate
      // never ran. `readRefusal` is the single reader for those (`C-ERR`).
      throw new Error((await readRefusal(res, 'Could not commit that memory.')).sentence);
    }
    const result = await res.json();
    await loadMemories();
    if (result && result.verdict === 'committed') {
      showToast('Committed — it can reach chats now');
    } else {
      // Deliberately the server's sentence and not a rewrite of it: the reason
      // is written for a person, and the one place that phrasing lives is the
      // gate that made the decision (`Law 7`).
      showToast((result && result.reason) || 'Not committed.', 6000);
    }
    return result;
  } catch (error) {
    console.error('Error committing memory:', error);
    showError((error && error.message) || 'Could not commit that memory.');
    return null;
  }
}

async function togglePin(id, pinned) {
  try {
    const res = await fetch(`${window.location.origin}/api/memory/${id}/pin`, {
      method: 'POST',
      body: new URLSearchParams({ pinned: pinned.toString() })
    });
    if (res.ok) {
      const mem = memories.find(m => m.id === id);
      if (mem) mem.pinned = pinned;
      renderMemoryList();
      // `D-13` (P23-02): "RAG" was the wrong system — an unpinned memory is
      // used when it is relevant, by the memory retriever.
      showToast(pinned ? 'Pinned: always included' : 'Unpinned: included when relevant');
    }
  } catch (e) {
    console.error('Failed to toggle pin:', e);
    showError('Failed to update pin');
  }
}

export async function deleteMemory(id) {
  const memory = memories.find(m => m.id === id);
  if (!memory) return;

  if (!await uiModule.styledConfirm(`Delete this memory?\n"${memory.text}"`, { confirmText: 'Delete', danger: true })) return;

  try {
    const response = await fetch(`${window.location.origin}/api/memory/${id}`, {
      method: 'DELETE'
    });

    if (response.ok) {
      await animateMemoryRemoval([id]);
      await loadMemories();
      showToast('Memory deleted');
    } else {
      throw new Error('Failed to delete');
    }
  } catch (error) {
    showError('Failed to delete memory');
  }
}

export async function extractMemory(sessionId) {
  const res = await fetch(`${window.location.origin}/api/memory/extract`, {
    method: 'POST',
    body: new URLSearchParams({ session: sessionId })
  });
  if (!res.ok) {
    showError('Failed to extract memory suggestions');
    return;
  }
  const data = await res.json();
  const suggestions = data.suggestions || [];

  const modal = document.getElementById('memory-modal');
  const body = document.getElementById('memory-suggestions-body');
  if (!body) {
    console.error('memory-suggestions-body element not found');
    return;
  }

  body.innerHTML = '';
  body.classList.remove('hidden');

  const memList = document.getElementById('memory-list');
  if (memList) memList.classList.add('hidden');

  if (suggestions.length === 0) {
    body.innerHTML = '<div class="memory-empty">Nothing to keep from this chat.</div>';
  } else {
    const header = document.createElement('div');
    header.className = 'memory-suggestions-header';
    header.innerHTML = '<span>Suggested memories</span>';
    const backBtn = document.createElement('button');
    backBtn.className = 'memory-item-btn';
    backBtn.textContent = 'Back';
    backBtn.addEventListener('click', () => {
      body.classList.add('hidden');
      body.innerHTML = '';
      if (memList) memList.classList.remove('hidden');
    });
    header.appendChild(backBtn);
    body.appendChild(header);

    suggestions.forEach(s => {
      const div = document.createElement('div');
      div.className = 'memory-suggestion-item';
      const txt = document.createElement('span');
      txt.className = 'memory-item-text';
      txt.textContent = s;
      const btn = document.createElement('button');
      btn.className = 'memory-item-btn save';
      btn.textContent = 'Save';
      btn.addEventListener('click', async () => {
        await fetch(`${window.location.origin}/api/memory/add`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: s })
        });
        btn.disabled = true;
        btn.textContent = 'Saved';
        showToast('Saved to memory');
      });
      div.appendChild(txt);
      div.appendChild(btn);
      body.appendChild(div);
    });
  }

  modal.classList.remove('hidden');
}

// ---- Export ----

export function exportMemories() {
  if (!memories || memories.length === 0) {
    showToast('No memories to export');
    return;
  }
  const data = JSON.stringify(memories, null, 2);
  const blob = new Blob([data], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'memories.json';
  a.click();
  URL.revokeObjectURL(url);
  showToast(`Exported ${memories.length} memories`);
}

// ---- Import from file ----

/** `B822`. A provider export's one line, or '' for any other upload.
 *
 *  `P13-06`'s route returns `provider`, `conversations`, `messages`,
 *  `dropped_assistant`, `truncated`, `already_known` and `below_floor`, and the
 *  panel drew none of them — so *"0 memories imported"* came with no reason,
 *  which is the failure mode an importer actually has. A file that was misread,
 *  one with none of your own turns in it, one already imported and one cut
 *  short at the reading limit each need a different next step, and these
 *  numbers are what tell them apart:
 *  *"ChatGPT export · 412 conversations · 3,180 of your messages read ·
 *  4,102 assistant replies skipped · 7 already known."*
 *  The provider's name is the server's (`provider_label`). Pure and exported,
 *  so a test can run it over the shapes the route returns (`Law 20`).
 */
export function describeImport(data) {
  if (!data || !data.provider) return '';
  const num = (x) => Number(x || 0).toLocaleString('en-US');
  const many = (x, one, other) => `${num(x)} ${Number(x) === 1 ? one : other}`;
  const parts = [`${data.provider_label || data.provider} export`];
  parts.push(many(data.conversations, 'conversation', 'conversations'));
  parts.push(`${many(data.messages, 'of your messages', 'of your messages')} read`);
  if (Number(data.dropped_assistant) > 0) {
    parts.push(`${many(data.dropped_assistant, 'assistant reply', 'assistant replies')} skipped`);
  }
  if (Number(data.already_known) > 0) parts.push(`${num(data.already_known)} already known`);
  if (Number(data.below_floor) > 0) parts.push(`${num(data.below_floor)} too uncertain to keep`);
  let line = parts.join(' · ') + '.';
  if (data.truncated) {
    line += ' Only the start of it was read — it is longer than one import reads.';
  }
  return line;
}

export async function importMemories() {
  const fileInput = document.getElementById('memory-import-file');
  if (!fileInput) return;
  fileInput.click();
}

async function handleImportFile(file) {
  if (!file) return;

  const sessionId = sessionModule?.getCurrentSessionId?.();

  const importBtn = document.getElementById('memory-import-btn');
  const _origImportHtml = importBtn ? importBtn.innerHTML : '';
  let importSpin = null;
  if (importBtn) {
    importBtn.disabled = true;
    importBtn.innerHTML = '';
    importSpin = spinnerModule.createWhirlpool(12);
    importSpin.element.style.cssText = 'width:12px;height:12px;margin:0 5px 0 0;display:inline-flex;vertical-align:-2px;transform:translateY(-1px);';
    importBtn.appendChild(importSpin.element);
    importBtn.appendChild(document.createTextNode('Importing'));
  }

  try {
    const formData = new FormData();
    formData.append('file', file);
    if (sessionId) {
        formData.append('session', sessionId);
    }

    const res = await fetch(`${window.location.origin}/api/memory/import`, {
      method: 'POST',
      body: formData
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Import failed');
    }

    const data = await res.json();
    const suggestions = data.suggestions || [];

    // Show suggestions using the existing suggestions UI
    const modal = document.getElementById('memory-modal');
    const body = document.getElementById('memory-suggestions-body');
    if (!body) return;

    body.innerHTML = '';
    body.classList.remove('hidden');

    const memList = document.getElementById('memory-list');
    if (memList) memList.classList.add('hidden');

    if (suggestions.length === 0) {
      // `BRAIN-M-14` (P23-02): the server says which empty answer this is.
      const why = {
        empty: 'Nothing readable in that file.',
        model_unparsed: 'The model gave no suggestions.',
      }[data.reason] || 'Nothing to keep from that file.';
      body.innerHTML = '';
      const row = document.createElement('div');
      row.className = 'memory-empty';
      row.textContent = data.message && data.provider ? String(data.message) : why;
      body.appendChild(row);
    } else {
      const reviewItems = suggestions
        .map((s) => ({
          text: typeof s === 'string' ? s : s.text,
          category: (typeof s === 'object' && s.category) || 'fact',
          active: true,
        }))
        .filter((s) => s.text);
      const header = document.createElement('div');
      header.className = 'memory-suggestions-header';
      const headerTitle = document.createElement('span');
      const updateHeaderTitle = () => {
        const remaining = reviewItems.filter((item) => item.active).length;
        headerTitle.textContent = `Imported from ${data.filename || file.name} (${remaining}) Review`;
      };
      updateHeaderTitle();
      const headerActions = document.createElement('div');
      headerActions.className = 'memory-suggestions-actions';
      const backBtn = document.createElement('button');
      backBtn.className = 'memory-item-btn';
      backBtn.textContent = 'Back';
      backBtn.addEventListener('click', () => {
        body.classList.add('hidden');
        body.innerHTML = '';
        if (memList) memList.classList.remove('hidden');
      });
      const saveAllBtn = document.createElement('button');
      saveAllBtn.className = 'memory-item-btn save';
      saveAllBtn.textContent = 'Save all';
      saveAllBtn.addEventListener('click', async () => {
        let saved = 0;
        for (const s of reviewItems) {
          if (!s.active || !s.text) continue;
          try {
            await fetch(`${window.location.origin}/api/memory/add`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ text: s.text, category: s.category })
            });
            saved++;
          } catch (e) { /* skip */ }
        }
        body.classList.add('hidden');
        body.innerHTML = '';
        if (memList) memList.classList.remove('hidden');
        await loadMemories();
        document.querySelector('.memory-tab[data-memory-tab="browse"]')?.click();
        showToast(`Saved ${saved} memories`);
      });
      headerActions.appendChild(saveAllBtn);
      headerActions.appendChild(backBtn);
      header.appendChild(headerTitle);
      header.appendChild(headerActions);
      body.appendChild(header);

      reviewItems.forEach(item => {
        const div = document.createElement('div');
        div.className = 'memory-suggestion-item';

        const content = document.createElement('div');
        content.className = 'memory-item-content';
        const txt = document.createElement('span');
        txt.className = 'memory-item-text';
        txt.textContent = item.text;
        const catBadge = document.createElement('span');
        catBadge.className = 'memory-cat-badge memory-cat-' + item.category;
        catBadge.textContent = item.category;
        content.appendChild(txt);
        content.appendChild(catBadge);

        const actionWrap = document.createElement('div');
        actionWrap.className = 'memory-suggestion-actions';
        const btn = document.createElement('button');
        btn.className = 'memory-item-btn save';
        btn.textContent = 'Save';
        btn.addEventListener('click', async () => {
          await fetch(`${window.location.origin}/api/memory/add`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: item.text, category: item.category })
          });
          item.active = false;
          div.remove();
          updateHeaderTitle();
          btn.disabled = true;
          btn.textContent = 'Saved';
          showToast('Saved to memory');
        });
        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'memory-item-btn delete';
        deleteBtn.textContent = 'Delete';
        deleteBtn.addEventListener('click', () => {
          item.active = false;
          div.remove();
          updateHeaderTitle();
        });
        actionWrap.appendChild(btn);
        actionWrap.appendChild(deleteBtn);

        div.appendChild(content);
        div.appendChild(actionWrap);
        body.appendChild(div);
      });
    }

    // `B822`. A provider export's one line under the list: what was read and
    // what was skipped, from the counts the route returns — the numbers that
    // tell a wrong file, a file of assistant replies and a file already
    // imported apart.
    const summary = describeImport(data);
    if (summary) {
      const line = document.createElement('div');
      line.className = 'memory-import-summary';
      line.textContent = summary;
      body.appendChild(line);
    }

    modal.classList.remove('hidden');
    document.querySelector('.memory-tab[data-memory-tab="browse"]')?.click();
  } catch (error) {
    console.error('Import failed:', error);
    showError('Import failed — ' + error.message);
  } finally {
    if (importSpin) importSpin.destroy();
    if (importBtn) {
      importBtn.disabled = false;
      importBtn.innerHTML = _origImportHtml;
    }
    // Reset file input so the same file can be re-selected
    const fileInput = document.getElementById('memory-import-file');
    if (fileInput) fileInput.value = '';
  }
}

// ---- The Brain's tabs, and its door to Skills — `P23-02` ----

/** Open the Brain on one memory: `P13-10`'s id, finally used.
 *
 *  That row put `id` on the used-memory payload *"so the panel can open the
 *  memory the pill names rather than matching on text"*, and then nothing
 *  passed it — clicking a row in the chat pill opened the window at whatever
 *  it last showed, which is the behaviour the id was added to replace.
 *
 *  Deliberately the same shape as `_focusSkillRow` in `skills.js`: load if the
 *  list is cold, scroll with `scrollBehavior()` so reduced motion is honoured
 *  (`P1-15`), flash the row with the shared `anchor-item-flash` animation, and
 *  give up quietly if the memory is gone. A reader who knows one knows this.
 *
 *  Returns whether the row was found, so a test can drive it (`Law 20`).
 */
export async function revealMemory(id) {
  if (id === null || id === undefined || id === '') return false;
  showBrainTab('browse');
  try { await loadMemoriesIfUnknown(); } catch (_) {}
  const wanted = String(id);
  const row = document.querySelector(
    `.memory-item[data-memory-id="${(window.CSS && CSS.escape) ? CSS.escape(wanted) : wanted}"]`);
  if (!row) return false;
  try { row.scrollIntoView({ behavior: scrollBehavior(), block: 'center' }); } catch (_) {}
  row.classList.add('memory-row-flash');
  setTimeout(() => row.classList.remove('memory-row-flash'), 2000);
  return true;
}

const BRAIN_ID = 'memory-modal';

/** The four tabs, in strip order. Scoped to the Brain: `.memory-tab` is also
 *  the class of the Tasks, Skills and Workbench tabs. */
function _brainTabs() {
  const modal = document.getElementById(BRAIN_ID);
  return modal ? Array.from(modal.querySelectorAll('.memory-tab[data-memory-tab]')) : [];
}

/** The tab on show: `browse` · `rag` · `add` · `settings` (C-NAV `getTab`). */
export function getBrainTab() {
  const on = _brainTabs().find((t) => t.classList.contains('active'));
  return on ? on.dataset.memoryTab : 'browse';
}

/** Show one tab (C-NAV `setTab`). An unknown name is ignored rather than
 *  emptying the window. Returns whether it is now on show. */
export function showBrainTab(name, { focus = false } = {}) {
  const tabs = _brainTabs();
  const tab = tabs.find((t) => t.dataset.memoryTab === name);
  if (!tab) return false;
  for (const t of tabs) {
    const on = t === tab;
    t.classList.toggle('active', on);
    t.setAttribute('aria-selected', on ? 'true' : 'false');
    t.tabIndex = on ? 0 : -1;
  }
  const modal = document.getElementById(BRAIN_ID);
  (modal ? Array.from(modal.querySelectorAll('.memory-tab-panel[data-memory-panel]')) : []).forEach((p) => {
    p.classList.toggle('hidden', p.dataset.memoryPanel !== name);
  });
  if (focus) { try { tab.focus(); } catch (_) {} }
  return true;
}

/** Left/Right walk the tabs (and wrap), Home/End jump to the ends; the panel
 *  follows the focus — the Workbench's rooms do the same (`workbench.js`). */
function _onBrainTabKey(e) {
  const keys = { ArrowLeft: -1, ArrowRight: 1, Home: 'first', End: 'last' };
  if (!(e.key in keys)) return;
  const tabs = _brainTabs();
  if (!tabs.length) return;
  const i = Math.max(0, tabs.findIndex((t) => t.dataset.memoryTab === getBrainTab()));
  const step = keys[e.key];
  const next = step === 'first' ? 0 : step === 'last' ? tabs.length - 1
    : (i + step + tabs.length) % tabs.length;
  if (e.preventDefault) e.preventDefault();
  showBrainTab(tabs[next].dataset.memoryTab, { focus: true });
}

/**
 * `NAV-U-1` / `BRAIN-U-1` (P23-02) — the owner's example: Brain → RAG →
 * Skills, then back. The Skills door opens the Skills window *from* the Brain
 * (C-NAV: `from` is the opener's window id, `tab` its tab at that moment), so
 * the window can say `← Brain` and closing it re-raises the Brain on that tab.
 * The Brain's own tab is not touched: it used to switch to a Skills launcher
 * card first, and the window then covered it — closing Skills landed on that
 * card, and the Brain reopened on it next time (`NAV-M-14`).
 */
export async function openSkillsFromBrain(view = 'browse') {
  const opts = { from: BRAIN_ID, tab: getBrainTab() };
  const m = await import('./skills.js');
  const mod = m.openSkillsWindow ? m : (m.default || {});
  // The Brain tour points at the door without pressing it.
  if (document.body.classList.contains('tour-active')) { mod.loadSkills?.(); return false; }
  return mod.openSkillsWindow ? mod.openSkillsWindow(view, opts) : false;
}

/** C-NAV: the Brain is a window with tabs, so it gives `getTab` and `setTab`.
 *  The rest is what `_AUTO_WIRE` registers it with on a minimize, so a
 *  registration made here changes nothing else about the window. */
function _registerBrainWindow() {
  if (typeof Modals.register !== 'function') return;
  if (typeof Modals.isRegistered === 'function' && Modals.isRegistered(BRAIN_ID)) return;
  Modals.register(BRAIN_ID, {
    sidebarBtnId: 'tool-memory-btn',
    closeFn: () => {
      const btn = document.getElementById('close-memory-modal');
      if (btn) btn.click();
    },
    restoreFn: () => {},
    getTab: getBrainTab,
    setTab: (tab) => { showBrainTab(tab); },
  });
}

// Utility aliases (canonical implementations live in uiModule)
var showToast = uiModule.showToast;
var showError = uiModule.showError;

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
  _wireMemoryDrag();

  // `P13-07`. The card at the foot of the memories list is the surface's one
  // door. Imported lazily on the click rather than at module scope, for two
  // reasons: a surface that is deliberately *not on open* should not cost
  // anything to boot, and `brainExplore.js` reads this module through
  // `window.memoryModule`, so a static import here would be the
  // `memory.js` <-> `brainExplore.js` cycle that `memoryFacts.js` exists to
  // avoid in the other direction.
  const exploreBtn = document.getElementById('brain-explore-open');
  if (exploreBtn) {
    exploreBtn.addEventListener('click', async () => {
      try {
        const surface = await import('./brainExplore.js');
        await surface.showExplore(true);
      } catch (err) {
        showError('Could not open the memory explorer');
        console.warn('[P13-07] explore surface failed to load', err);
      }
    });
  }

  // `B1070`. Every door into the Brain — the sidebar row, the rail, `/memory`,
  // the shortcut, a chat's "memories used" row — un-hides this window, so the
  // window itself is what asks for its list.
  const memModal = document.getElementById('memory-modal');
  if (memModal && typeof MutationObserver === 'function') {
    new MutationObserver(() => {
      if (memModal.classList.contains('hidden')) return;
      loadMemoriesIfUnknown();
      // A dock chip's × forgets the window (`Modals.close`); the next open
      // registers it again, so `getTab`/`setTab` are always there to read.
      _registerBrainWindow();
    }).observe(memModal, { attributes: true, attributeFilter: ['class'] });
  }

  // Memory modal tabs — `BRAIN-U-8` (P23-02): a WAI-ARIA tablist, the same
  // keys as the Skills window's and the Workbench's.
  _brainTabs().forEach(tab => {
    tab.addEventListener('click', () => showBrainTab(tab.dataset.memoryTab));
    tab.addEventListener('keydown', _onBrainTabKey);
  });
  // `NAV-U-1` (P23-02). The Brain's doors to Skills — beside the tabs, and on
  // the Add tab — open the window with the Brain as its opener (C-NAV).
  document.querySelectorAll('[data-brain-skills]').forEach(door => {
    door.addEventListener('click', () => openSkillsFromBrain(door.getAttribute('data-brain-skills') || 'browse'));
  });
  _registerBrainWindow();

  const sortSelect = document.getElementById('memory-sort');
  if (sortSelect) {
    sortSelect.addEventListener('change', () => {
      sortOrder = sortSelect.value;
      renderMemoryList();
    });
  }
  _initMemorySortPicker();
  initMemorySearchMode();  // H11

  const tidyBtn = document.getElementById('memory-tidy-btn');
  if (tidyBtn) tidyBtn.addEventListener('click', tidyMemories);

  const selectBtn = document.getElementById('memory-select-btn');
  if (selectBtn) selectBtn.addEventListener('click', () => {
    if (selectMode) exitSelectMode();
    else enterSelectMode();
  });

  const selectAll = document.getElementById('memory-select-all');
  if (selectAll) selectAll.addEventListener('change', toggleSelectAll);

  const bulkBar = document.getElementById('memory-bulk-bar');
  if (bulkBar) bulkBar.addEventListener('click', (e) => {
    if (e.target.closest('button') || e.target === selectAll) return;
    selectAll.checked = !selectAll.checked;
    selectAll.dispatchEvent(new Event('change'));
  });

  const bulkDeleteBtn = document.getElementById('memory-bulk-delete');
  if (bulkDeleteBtn) bulkDeleteBtn.addEventListener('click', bulkDelete);

  const bulkCancelBtn = document.getElementById('memory-bulk-cancel');
  if (bulkCancelBtn) bulkCancelBtn.addEventListener('click', exitSelectMode);

  const exportBtn = document.getElementById('memory-export-btn');
  if (exportBtn) exportBtn.addEventListener('click', exportMemories);

  const importBtn = document.getElementById('memory-import-btn');
  if (importBtn) importBtn.addEventListener('click', importMemories);

  const importFile = document.getElementById('memory-import-file');
  if (importFile) importFile.addEventListener('change', (e) => {
    if (e.target.files[0]) handleImportFile(e.target.files[0]);
  });

  window.addEventListener('memory-refresh', () => {
    loadMemories();
  });
});

const memoryModule = {
  loadMemories,
  loadMemoriesIfUnknown,
  markMemoriesStale,
  getBrainTab,
  showBrainTab,
  openSkillsFromBrain,
  renderMemoryList,
  updateMemoryCount,
  addNewMemory,
  deleteMemory,
  extractMemory,
  buildCategoryChips,
  // `B710`. On the module object because Explore reaches the Brain's writers
  // through `window.memoryModule` and not by importing this file — the cycle
  // `memoryFacts.js` explains — and a second commit call there would be a
  // second place to forget to reload the list or to report the gate's words.
  buildStatusChips,
  commitMemory,
  tidyMemories,
  describeMemoryTidy,
  describeTidyRetired,
  importMemories,
  exportMemories,
  revealMemory,
  saveInlineEdit
};

export default memoryModule;
window.memoryModule = memoryModule;
