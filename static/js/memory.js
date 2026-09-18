// SPDX-License-Identifier: AGPL-3.0-or-later
// Memory Management Functions
// This module handles all memory-related operations

import uiModule from './ui.js';
import sessionModule from './sessions.js';
import spinnerModule from './spinner.js';
import { makeWindowDraggable } from './windowDrag.js';
import { snapModalToZone } from './tileManager.js';
import { topPortalZ } from './toolWindowZOrder.js';

var escapeHtml = uiModule.esc;

let memories = [];
let activeCategory = 'all';
let sortOrder = 'newest';
let selectMode = false;
let selectedIds = new Set();
let memoriesLoading = false;


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

// `P13-15`. The two count pills, as data.
//
// `uses` counts how often the SYSTEM reached for this memory and put it in a
// prompt. `mention_sessions` counts how many separate conversations the PERSON
// raised it in. A memory the assistant keeps injecting and a memory you keep
// bringing up are different kinds of important, and one number cannot mean
// both — so they are two pills, built from two fields, and each title says
// which is which. A bare "11×" beside a bare "said in 3" is a riddle.
//
// Exported as data rather than built inline so a test can run it instead of
// reading it (`Law 20`). `B61` is why: a mutation that computed a value
// correctly and never put it on screen survived every test of the helper.
export function memoryCountPills(memory) {
  const uses = Number((memory && memory.uses) || 0);
  const sessions = Number((memory && memory.mention_sessions) || 0);
  const pills = [];
  if (uses > 0) {
    pills.push({
      className: 'memory-item-uses',
      text: `${uses}×`,
      title: `Injected into chat context ${uses} time${uses === 1 ? '' : 's'}`,
    });
  }
  // Two or more: one conversation is not a pattern, and "said in 1" beside a
  // memory that was created by being said once is noise.
  if (sessions > 1) {
    pills.push({
      className: 'memory-item-mentions',
      text: `said in ${sessions}`,
      title: `You have brought this up in ${sessions} separate conversations`
        + ` — which is why it ranks a little higher. Different from the ${uses}× above,`
        + ` which counts how often it was injected into a chat.`,
    });
  }
  return pills;
}

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
    <button type="button" role="option" class="memory-sort-item" data-value="${it.value}">
      <span class="memory-sort-item-icon">${_memorySortIcon(it.value)}</span>
      <span class="memory-sort-item-label">${it.label}</span>
    </button>
  `).join('');

  const close = () => { menu.hidden = true; btn.setAttribute('aria-expanded', 'false'); };
  const open  = () => { menu.hidden = false; btn.setAttribute('aria-expanded', 'true'); };

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
  document.addEventListener('click', (e) => {
    if (!menu.hidden && !picker.contains(e.target)) close();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !menu.hidden) {
      e.stopPropagation();
      close();
    }
  }, { capture: true });

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
    onEnterFullscreen: () => {
      snapModalToZone(modal, {
        name: 'fullscreen',
        rect: {
          left: 0,
          top: 0,
          width: window.innerWidth || document.documentElement.clientWidth || 0,
          height: window.innerHeight || document.documentElement.clientHeight || 0,
        },
      });
    },
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

async function syncToggles() {
  // The settings tab no longer hosts a separate "Memory in context" toggle —
  // the header toggle owns that pref directly now.
  await syncPrefToggle('memory-enabled-header-toggle', 'memory_enabled', 'Memory enabled', 'Memory disabled', false);
  // The Skills header toggle owns the `skills_enabled` pref (was never wired —
  // toggling it did nothing, so skills stayed on). Now it actually gates skill
  // injection (see chat_helpers.py: uprefs.skills_enabled).
  await syncPrefToggle('skills-enabled-header-toggle', 'skills_enabled', 'Skills enabled', 'Skills disabled', false);
  await syncPrefToggle('auto-memory-toggle', 'auto_memory', 'Auto-extract memories enabled', 'Auto-extract memories disabled', false);
  await syncPrefToggle('auto-skills-toggle', 'auto_skills', 'Auto-extract skills enabled', 'Auto-extract skills disabled', false);
  await syncPrefToggle('auto-approve-skills-toggle', 'auto_approve_skills', 'Auto-approve skills enabled', 'Auto-approve skills disabled', false);
  await syncPrefSlider('skill-confidence-slider', 'skill_min_confidence', 'skill-confidence-label', 0.85);
  await syncPrefNumber('skill-max-input', 'skill_max_injected', 3);

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

  // Reflect the header toggle into the sidebar dim + modal body opacity.
  const headerToggle = document.getElementById('memory-enabled-header-toggle');
  if (headerToggle) {
    const modalBody = document.querySelector('.memory-modal-body');
    if (modalBody) modalBody.style.opacity = headerToggle.checked ? '' : '0.3';
    reflectMemoryToggleInSidebar(headerToggle.checked);
    if (!headerToggle.dataset.boundUx) {
      headerToggle.dataset.boundUx = '1';
      headerToggle.addEventListener('change', () => {
        if (modalBody) modalBody.style.opacity = headerToggle.checked ? '' : '0.3';
        reflectMemoryToggleInSidebar(headerToggle.checked);
      });
    }
  }

  // Same dim treatment for the Skills toggle — dims the skills panel when off.
  const skillsToggle = document.getElementById('skills-enabled-header-toggle');
  if (skillsToggle) {
    const skillsPanel = document.querySelector('[data-memory-panel="skills"]');
    const applyDim = () => { if (skillsPanel) skillsPanel.style.opacity = skillsToggle.checked ? '' : '0.3'; };
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
// `if min_confidence > 0` (services/memory/skills.py:748). So the strictest
// setting was one notch short of the end, the end itself was the loosest
// setting on the control, and it was labelled "All", which reads as a promise
// about coverage rather than a confession that nothing is being checked.
//
// Nothing about what is stored changes: 0 still means "no minimum", 0.85 still
// means 85%. Only which position maps to 0 moves, so a saved preference keeps
// its meaning and the geometry stops lying. `slider.min` is the sentinel stop
// (45, one step below the lowest real percentage) and `min + step` is the
// lowest percentage the control can express — no setting was taken away.
export async function syncPrefSlider(elementId, prefKey, labelId, defaultVal) {
  const slider = document.getElementById(elementId);
  if (!slider) return;
  const label = labelId ? document.getElementById(labelId) : null;
  const allPos = Number(slider.min);
  const maxPos = Number(slider.max);
  const floorPos = allPos + (Number(slider.step) || 5);
  const fmt = (pos) => (Number(pos) <= allPos ? 'All' : `≥ ${pos}%`);
  try {
    const res = await fetch(`${window.location.origin}/api/prefs/${prefKey}`);
    if (res.ok) {
      const data = await res.json();
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
 *  `src/agent_loop.py:3091-3093` sets the injection floor to **2.0** when
 *  auto-approve is off — a number no confidence can reach — so turning off a
 *  toggle whose label only mentions the audit silently makes injection
 *  published-only. It is a real and defensible behaviour; it was simply
 *  invisible, and an invisible coupling is how a person concludes the product
 *  is ignoring them.
 */
export function skillGateHints({ autoApprove = true, minConfidence = 0.85 } = {}) {
  const value = Number(minConfidence) || 0;
  const pct = Math.round(value * 100);
  if (!autoApprove) {
    return {
      confidence: 'Not in use for injection while auto-approve is off — it still decides what Audit all publishes.',
      coupling: 'Auto-approve is off, so only published skills are injected. An uncatalogued skill stays out of every request until you publish it.',
    };
  }
  return {
    confidence: value <= 0
      ? 'No minimum: every uncatalogued skill is injected whenever your message matches it, however little the audit trusted it. This is the loosest setting on this control, not the strictest.'
      : `An uncatalogued skill is injected only at ${pct}% confidence or more; a published one always is. A skill you write here starts at 80%, so at ${pct}% it waits until an audit raises it or you publish it. Audit all publishes at this bar too.`,
    coupling: 'Auto-approve is on, so uncatalogued skills can be injected — the minimum above is what holds them back.',
  };
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
async function syncPrefNumber(elementId, prefKey, defaultVal) {
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
    const res = await fetch(`${window.location.origin}/api/prefs/${prefKey}`);
    if (res.ok) {
      const data = await res.json();
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
        showToast(v === 0 ? 'No skills injected' : `Max injected skills: ${v}`);
      } catch (e) {
        console.error(`Failed to save ${prefKey} pref:`, e);
        showError('Failed to save preference');
      }
    });
  }
}

async function syncPrefToggle(elementId, prefKey, onMsg, offMsg, dimBelow = true) {
  const toggle = document.getElementById(elementId);
  if (!toggle) return;
  try {
    const res = await fetch(`${window.location.origin}/api/prefs/${prefKey}`);
    if (res.ok) {
      const data = await res.json();
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

export async function loadMemories() {
  _ensureNewMemoryCategorySelect();
  memoriesLoading = true;
  renderMemoryList();
  updateMemoryCount();
  try {
    const response = await fetch(`${window.location.origin}/api/memory`);

    if (!response.ok) {
      console.error('Memory fetch failed with status:', response.status);
      memories = [];
      memoriesLoading = false;
      buildCategoryChips();
      renderMemoryList();
      updateMemoryCount();
      syncToggles();
      return;
    }

    const data = await response.json();

    if (data && data.memory) {
      memories = data.memory;
    } else if (Array.isArray(data)) {
      memories = data;
    } else {
      memories = [];
    }

    memoriesLoading = false;
    buildCategoryChips();
    renderMemoryList();
    updateMemoryCount();
  } catch (error) {
    console.error('Failed to load memories:', error);
    memories = [];
    memoriesLoading = false;
    buildCategoryChips();
    renderMemoryList();
    updateMemoryCount();
  }
  // Always wire toggles, even if memory API failed
  syncToggles();
}

// ---- Bulk select mode ----

const _SELECT_BTN_DOT_SVG = '<svg class="memory-select-btn-icon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:3px;"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/></svg>';
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

export async function tidyMemories() {
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
    if ((data.removed || 0) === 0) {
      if (tidySpinner) tidySpinner.destroy();
      if (tidyBtn) { tidyBtn.disabled = false; tidyBtn.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" style="vertical-align:-1px;margin-right:2px;color:var(--accent, var(--red));"><path d="M12 0L14.59 8.41L23 12L14.59 15.59L12 24L9.41 15.59L1 12L9.41 8.41Z"/></svg> Tidy'; }
      showToast('Already clean');
      return;
    }

    // Fetch the new state
    const freshRes = await fetch(`${window.location.origin}/api/memory`);
    const freshData = await freshRes.json();
    const afterList = freshData.memory || freshData || [];
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

    if (tidySpinner) tidySpinner.updateMessage('Tidying memories');

    // Animate the diff on the currently rendered list
    await animateTidyDiff(removed, edited);

    // Now load the clean state
    memories = afterList;
    buildCategoryChips();
    renderMemoryList();
    updateMemoryCount();

    showToast(`Tidied: ${data.removed} removed (${data.before} \u2192 ${data.after})`);
  } catch (error) {
    console.error('Tidy failed:', error);
    showError('Tidy failed — check console');
  } finally {
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
      note.textContent = `${n} memor${n === 1 ? 'y' : 'ies'} would be retrieved. `
        + (_fireResult.queryType
            ? `The retriever reads this as a ${_fireResult.queryType} question.`
            : 'The retriever does not recognise this as any particular kind of question.');
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
    if (memoriesLoading) {
      const row = spinnerModule.createLoadingRow('Loading memories...', 14);
      row.classList.add('memory-empty');
      memoryList.replaceChildren(row);
      return;
    }
    const searchTerm = document.getElementById('memory-search')?.value?.trim() || '';
    const _smiley = '<span style="vertical-align:-3px;margin-left:6px;">' + uiModule.emptyStateIcon('smiley') + '</span>';
    if (searchTerm || activeCategory !== 'all') {
      memoryList.innerHTML = `<div class="memory-empty">No matches.</div>`;
    } else {
      memoryList.innerHTML = `<div class="memory-empty" style="display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;">
        <span>No memories yet${_smiley}</span>
        <span style="opacity:0.7;font-size:11px;display:block;">
          <a href="#" data-mem-goto-add style="color:var(--accent,var(--red));text-decoration:underline;">Import in Add tab</a>
        </span>
      </div>`;
      memoryList.querySelector('[data-mem-goto-add]')?.addEventListener('click', (e) => {
        e.preventDefault();
        document.querySelector('.memory-tab[data-memory-tab="add"]')?.click();
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

    for (const pill of memoryCountPills(memory)) {
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
      menuBtn.className = 'memory-menu-btn';
      menuBtn.innerHTML = '\u22EE';
      menuBtn.title = 'Actions';

      const dropdown = document.createElement('div');
      dropdown.className = 'memory-item-dropdown';

      // Pin / Unpin — bookmark icon matches the chat-session "Favorite" SVG.
      // Filled when pinned, outlined when not.
      const _bookmarkPath = '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>';
      const _pinSvg = memory.pinned
        ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${_bookmarkPath}</svg>`
        : `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${_bookmarkPath}</svg>`;
      const pinItem = document.createElement('div');
      pinItem.className = 'dropdown-item-compact';
      pinItem.innerHTML = `<span class="dropdown-icon">${_pinSvg}</span><span>${memory.pinned ? 'Unpin' : 'Pin'}</span>`;
      pinItem.addEventListener('click', () => { dropdown.style.display = 'none'; togglePin(memory.id, !memory.pinned); });

      const editItem = document.createElement('div');
      editItem.className = 'dropdown-item-compact';
      editItem.textContent = '✎ Edit';
      editItem.addEventListener('click', () => { dropdown.style.display = 'none'; startInlineEdit(item, memory); });

      const deleteItem = document.createElement('div');
      deleteItem.className = 'dropdown-item-compact memory-dropdown-delete';
      deleteItem.textContent = '✕ Delete';
      deleteItem.addEventListener('click', () => { dropdown.style.display = 'none'; deleteMemory(memory.id); });

      // Select — enters bulk-select mode and pre-selects this memory. Same
      // pattern as the email/documents/skills Select item.
      const selectItem = document.createElement('div');
      selectItem.className = 'dropdown-item-compact';
      selectItem.innerHTML = '<span class="dropdown-icon"><span style="font-size:16px;line-height:1;">●</span></span><span>Select</span>';
      selectItem.addEventListener('click', (e) => {
        e.stopPropagation();
        if (dropdown.parentNode) dropdown.remove();
        if (!selectMode) enterSelectMode();
        selectedIds.add(memory.id);
        updateBulkCount();
        renderMemoryList();
      });

      // Mobile-only Cancel — mirrors the email/documents popup pattern. CSS
      // hides `.dropdown-cancel-mobile` on desktop where outside-click already
      // dismisses cleanly.
      const cancelItem = document.createElement('div');
      cancelItem.className = 'dropdown-item-compact dropdown-cancel-mobile';
      cancelItem.textContent = '✕ Cancel';
      cancelItem.addEventListener('click', (e) => { e.stopPropagation(); if (dropdown.parentNode) dropdown.remove(); });

      dropdown.appendChild(pinItem);
      dropdown.appendChild(selectItem);
      dropdown.appendChild(editItem);
      dropdown.appendChild(deleteItem);
      dropdown.appendChild(cancelItem);

      menuBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        // Close any other open dropdowns
        document.querySelectorAll('.memory-item-dropdown').forEach(d => d.remove());
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
        // and it snaps back. Vertical-only; horizontal flicks fall through.
        let _sw = null;
        let _swDy = 0;
        const _onTS = (ev) => {
          if (ev.touches.length !== 1) return;
          _sw = { x: ev.touches[0].clientX, y: ev.touches[0].clientY };
          _swDy = 0;
          dropdown.style.transition = '';
        };
        const _onTM = (ev) => {
          if (!_sw || ev.touches.length !== 1) return;
          const dx = ev.touches[0].clientX - _sw.x;
          const dy = ev.touches[0].clientY - _sw.y;
          if (Math.abs(dy) < Math.abs(dx)) { _sw = null; return; }
          if (dy > 0) {
            _swDy = dy;
            dropdown.style.transform = 'translateY(' + dy + 'px)';
            dropdown.style.opacity = String(Math.max(0.3, 1 - dy / 240));
          }
        };
        const _onTE = () => {
          if (!_sw) return;
          _sw = null;
          if (_swDy > 60) {
            dropdown.style.transition = 'transform 0.15s ease, opacity 0.15s ease';
            dropdown.style.transform = 'translateY(120px)';
            dropdown.style.opacity = '0';
            setTimeout(() => { if (dropdown.parentNode) dropdown.remove(); }, 160);
          } else {
            dropdown.style.transition = 'transform 0.18s ease, opacity 0.18s ease';
            dropdown.style.transform = '';
            dropdown.style.opacity = '';
          }
        };
        dropdown.addEventListener('touchstart', _onTS, { passive: true });
        dropdown.addEventListener('touchmove', _onTM, { passive: true });
        dropdown.addEventListener('touchend', _onTE);
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

      // Close dropdown on outside click
      document.addEventListener('click', () => { if (dropdown.parentNode) dropdown.remove(); }, { once: false });
    }

    memoryList.appendChild(item);
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
  saveBtn.textContent = 'save';
  saveBtn.addEventListener('click', () => saveInlineEdit(memory.id, input.value, catSelect.value));

  const cancelBtn = document.createElement('button');
  cancelBtn.className = 'memory-item-btn';
  cancelBtn.textContent = 'cancel';
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

async function saveInlineEdit(id, newText, newCategory) {
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
  if (memoriesLoading) {
    if (h2Count) h2Count.textContent = 'loading...';
    if (tabCount) tabCount.textContent = '...';
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

  const num = visible.length === scopeTotal ? `${scopeTotal}` : `${visible.length}/${scopeTotal}`;
  // Header (next to the "Memories" title) reads "N memories", like the
  // Documents header. The bare number still feeds any tab badge if present.
  if (h2Count) h2Count.textContent = `${num} ${scopeTotal === 1 && visible.length === scopeTotal ? 'memory' : 'memories'}`;
  if (tabCount) tabCount.textContent = num;
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
      const errorData = await response.json();
      console.error('Server error details:', errorData);
      throw new Error(errorData.detail || 'Failed to add memory');
    }
  } catch (error) {
    console.error('Error adding memory:', error);
    showError('Failed to add memory');
  }
}

export async function editMemory(id) {
  const memory = memories.find(m => m.id === id);
  if (!memory) return;

  const newText = prompt('Edit memory:', memory.text);
  if (!newText || newText === memory.text) return;

  await saveInlineEdit(id, newText);
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
      showToast(pinned ? 'Pinned — always in context' : 'Unpinned — RAG only');
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
    body.innerHTML = '<div class="memory-empty">No useful information detected.</div>';
  } else {
    const header = document.createElement('div');
    header.className = 'memory-suggestions-header';
    header.innerHTML = '<span>Suggested memories</span>';
    const backBtn = document.createElement('button');
    backBtn.className = 'memory-item-btn';
    backBtn.textContent = 'back';
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
      btn.textContent = 'save';
      btn.addEventListener('click', async () => {
        await fetch(`${window.location.origin}/api/memory/add`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: s })
        });
        btn.disabled = true;
        btn.textContent = 'saved';
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
      body.innerHTML = '<div class="memory-empty">No useful information found in file.</div>';
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
      backBtn.textContent = 'back';
      backBtn.addEventListener('click', () => {
        body.classList.add('hidden');
        body.innerHTML = '';
        if (memList) memList.classList.remove('hidden');
      });
      const saveAllBtn = document.createElement('button');
      saveAllBtn.className = 'memory-item-btn save';
      saveAllBtn.textContent = 'save all';
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
        btn.textContent = 'save';
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
          btn.textContent = 'saved';
          showToast('Saved to memory');
        });
        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'memory-item-btn delete';
        deleteBtn.textContent = 'delete';
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

// Utility aliases (canonical implementations live in uiModule)
var showToast = uiModule.showToast;
var showError = uiModule.showError;

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
  _wireMemoryDrag();

  // Memory modal tabs
  document.querySelectorAll('.memory-tab[data-memory-tab]').forEach(tab => {
    tab.addEventListener('click', () => {
      const target = tab.dataset.memoryTab;
      document.querySelectorAll('.memory-tab').forEach(t => t.classList.toggle('active', t === tab));
      document.querySelectorAll('.memory-tab-panel[data-memory-panel]').forEach(p => {
        p.classList.toggle('hidden', p.dataset.memoryPanel !== target);
      });
      // Lazy-load skills tab (cascade=true → play the domino-in entrance)
      if (target === 'skills') {
        import('./skills.js').then(m => { if (m.loadSkills) m.loadSkills(true); else if (m.default?.loadSkills) m.default.loadSkills(true); });
      }
    });
  });

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
  renderMemoryList,
  updateMemoryCount,
  addNewMemory,
  editMemory,
  deleteMemory,
  extractMemory,
  buildCategoryChips,
  tidyMemories,
  importMemories,
  exportMemories
};

export default memoryModule;
window.memoryModule = memoryModule;
