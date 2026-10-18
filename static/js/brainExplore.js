// SPDX-License-Identifier: AGPL-3.0-or-later
// `P13-07`. The Brain's reading surface: *"readable, not navigable-by-dragging."*
//
// The row's own instruction, twice: **no canvas, no force layout** — and
// `P3-19`, the row that would have built one, is moot because of it. What a
// person wants from a memory graph is not to look at it, it is to answer a
// question: *what does this thing remember about one project, and how do I fix
// the bit that is wrong.* That is a reading task, so this is a list with
// filters and a detail pane, and the filter itself lives in `brainFilter.js`
// where a test can run it without a DOM (`B61`).
//
// Not on the main path and not on open: the Brain's four tabs are unchanged
// and this panel has no tab at all. It is reached from one small card at the
// foot of the memories list, which is where a person who has run out of list
// looks next.

import { apply, emptyFilter, isNarrowed, sessionIndex, freshness, AGE_BANDS,
         CONFIDENCE_BANDS, EDGE_TYPES } from './brainFilter.js';
import { memoryConfidencePill } from './memoryFacts.js';
import { scrollBehavior } from './motion.js';

const PANEL = 'memory-panel-explore';
const CATEGORIES = ['fact', 'identity', 'preference', 'contact', 'project', 'goal', 'task'];

const state = {
  rows: [],
  projects: [],
  filter: emptyFilter(),
  readAt: 0,
  open: null,          // the memory id whose detail is showing
  loading: false,
};

function _el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function _ago(stamp) {
  if (!stamp) return 'unknown';
  const diff = Math.floor(Date.now() / 1000) - Number(stamp);
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  if (diff < 2592000) return `${Math.floor(diff / 604800)}w ago`;
  if (diff < 31536000) return `${Math.floor(diff / 2592000)}mo ago`;
  return `${Math.floor(diff / 31536000)}y ago`;
}

/** The freshness line, in words. `P13-07`: *"state plainly how fresh the
 *  analysis is."* Two facts, because either alone misleads — when this page
 *  last read the store, and how old the newest thing in it is. Exported so a
 *  test reads the sentence rather than the DOM. */
export function freshnessSentence(rows, { readAt, projects } = {}) {
  const f = freshness(rows, { readAt, projects });
  if (!f.memories) {
    return f.readAt
      ? `Read the Brain ${_ago(f.readAt)} and found nothing stored yet.`
      : 'Nothing read yet.';
  }
  const where = f.projects
    ? `${f.memories} memories across ${f.projects} project${f.projects === 1 ? '' : 's'}`
    : `${f.memories} memories, none filed under a project`;
  const newest = f.newest ? `newest was written ${_ago(f.newest)}` : 'none carries a date';
  return `Read ${where} ${_ago(f.readAt)} — ${newest}.`;
}

async function _load() {
  state.loading = true;
  try {
    const [memRes, projRes] = await Promise.all([
      fetch(`${window.location.origin}/api/memory`),
      fetch(`${window.location.origin}/api/memory/projects`),
    ]);
    state.rows = memRes.ok ? ((await memRes.json()).memory || []) : [];
    state.projects = projRes.ok ? ((await projRes.json()).projects || []) : [];
    state.readAt = Math.floor(Date.now() / 1000);
  } catch (_) {
    state.rows = [];
    state.projects = [];
  } finally {
    state.loading = false;
  }
}

function _select(id, label, options, value, onChange) {
  const wrap = _el('label', 'brain-filter');
  wrap.appendChild(_el('span', 'brain-filter-label', label));
  const select = document.createElement('select');
  select.id = id;
  select.className = 'brain-filter-select';
  select.setAttribute('aria-label', label);
  for (const [optValue, optLabel] of options) {
    const option = document.createElement('option');
    option.value = optValue;
    option.textContent = optLabel;
    if (optValue === value) option.selected = true;
    select.appendChild(option);
  }
  select.addEventListener('change', () => onChange(select.value));
  wrap.appendChild(select);
  return wrap;
}

function _filterBar() {
  const bar = _el('div', 'brain-filter-bar');
  const set = (key) => (value) => { state.filter = { ...state.filter, [key]: value }; _render(); };

  const search = document.createElement('input');
  search.type = 'search';
  search.id = 'brain-explore-search';
  search.className = 'brain-explore-search';
  // The row asks for *"search that finds a thing in one query rather than a
  // thing you spot in a cloud"*, so the placeholder says what it searches.
  search.placeholder = 'Find a memory — its words, or a project name';
  search.setAttribute('aria-label', 'Find a memory');
  search.value = state.filter.query;
  search.addEventListener('input', () => {
    state.filter = { ...state.filter, query: search.value };
    _render({ keepFocus: 'brain-explore-search' });
  });
  bar.appendChild(search);

  const row = _el('div', 'brain-filter-row');
  row.appendChild(_select('brain-filter-project', 'Project',
    [['any', 'any project'], ['none', 'no project'],
     ...state.projects.map((p) => [p.slug, `${p.label} (${p.memories})`])],
    state.filter.project, set('project')));
  row.appendChild(_select('brain-filter-confidence', 'Confidence',
    [['any', 'any'], ['high', '80% and up'], ['medium', '50–80%'],
     ['low', 'under 50%'], ['unrecorded', 'not recorded']],
    state.filter.confidence, set('confidence')));
  row.appendChild(_select('brain-filter-category', 'Category',
    [['any', 'any'], ...CATEGORIES.map((c) => [c, c])],
    state.filter.category, set('category')));
  row.appendChild(_select('brain-filter-age', 'Age',
    [['any', 'any age'], ['week', 'last 7 days'], ['month', 'last 30 days'],
     ['quarter', 'last 90 days']],
    state.filter.age, set('age')));
  row.appendChild(_select('brain-filter-session', 'Session',
    [['any', 'any chat'], ...sessionIndex(state.rows).map(
      (s) => [s.id, `${_ago(s.newest)} (${s.memories})`])],
    state.filter.session, set('session')));
  row.appendChild(_select('brain-filter-edge', 'Links',
    [['any', 'any'], ['none', 'unlinked'], ...EDGE_TYPES.map(
      (t) => [t, t.replace('_', ' ')])],
    state.filter.edge, set('edge')));
  bar.appendChild(row);
  return bar;
}

function _edgeLines(memory) {
  const byId = new Map(state.rows.map((row) => [row.id, row]));
  const lines = [];
  for (const edge of Array.isArray(memory.edges) ? memory.edges : []) {
    if (!edge || !edge.type) continue;
    const other = byId.get(edge.target || edge.target_id);
    lines.push({
      type: edge.type,
      // The other side's own words, not its id: the row asks a reader to *see
      // what it supersedes and what contradicts it*, and an id is not a thing
      // anyone can read. A target that is gone says so rather than showing a
      // blank — a dangling edge is a fact about the store.
      text: other ? other.text : '(that memory is no longer here)',
      id: edge.target || edge.target_id || null,
      note: edge.note || '',
    });
  }
  // `contradicts` first: it is the one a reader most needs and the one the
  // retriever already surfaces both sides of (`P13-02`).
  const rank = { contradicts: 0, supersedes: 1, derived_from: 2, co_occurs: 3 };
  lines.sort((a, b) => (rank[a.type] ?? 9) - (rank[b.type] ?? 9));
  return lines;
}

function _detail(memory) {
  const box = _el('div', 'brain-detail');
  box.id = 'brain-explore-detail';

  const text = _el('div', 'brain-detail-text', memory.text);
  box.appendChild(text);

  const meta = _el('div', 'brain-detail-meta');
  if (memory.project_label) {
    meta.appendChild(_el('span', 'brain-detail-project', memory.project_label));
  }
  meta.appendChild(_el('span', 'brain-detail-chip', memory.category || 'fact'));
  const pill = memoryConfidencePill(memory);
  if (pill) {
    const span = _el('span', 'memory-confidence', pill.text);
    span.title = pill.title;
    meta.appendChild(span);
  }
  meta.appendChild(_el('span', 'brain-detail-chip', _ago(memory.timestamp)));
  box.appendChild(meta);

  const lines = _edgeLines(memory);
  if (lines.length) {
    const edges = _el('div', 'brain-detail-edges');
    for (const line of lines) {
      const row = _el('div', `brain-detail-edge brain-edge-${line.type}`);
      row.appendChild(_el('span', 'brain-edge-type', line.type.replace('_', ' ')));
      row.appendChild(_el('span', 'brain-edge-text', line.text));
      if (line.note) row.appendChild(_el('span', 'brain-edge-note', line.note));
      edges.appendChild(row);
    }
    box.appendChild(edges);
  }

  const actions = _el('div', 'brain-detail-actions');

  const correct = _el('button', 'brain-detail-btn', 'Correct');
  correct.type = 'button';
  correct.addEventListener('click', () => {
    const area = document.createElement('textarea');
    area.className = 'brain-detail-edit';
    area.value = memory.text;
    area.setAttribute('aria-label', 'Correct this memory');
    const save = _el('button', 'brain-detail-btn brain-detail-save', 'Save');
    save.type = 'button';
    save.addEventListener('click', async () => {
      const next = area.value.trim();
      if (!next || next === memory.text) { _render(); return; }
      // The Brain's own writer, imported rather than reimplemented: a second
      // place that saves an edit is a second place to forget to reload the
      // list or report a refusal (`Law 14`).
      const brain = window.memoryModule;
      if (brain && brain.saveInlineEdit) await brain.saveInlineEdit(memory.id, next);
      await _load();
      _render();
    });
    box.replaceChildren(area, save);
    area.focus();
  });
  actions.appendChild(correct);

  const retire = _el('button', 'brain-detail-btn brain-detail-retire', 'Retire');
  retire.type = 'button';
  // Says what it does before it does it. Retire is not delete — the text, the
  // confidence, the provenance and the edges all stay — and a button that does
  // not say so reads as the destructive one beside it.
  retire.title = 'Stop this memory reaching chats. It is kept, not deleted.';
  retire.addEventListener('click', async () => {
    retire.disabled = true;
    try {
      const res = await fetch(
        `${window.location.origin}/api/memory/${memory.id}/archive`,
        { method: 'POST', body: new URLSearchParams({ reason: 'retired from the Brain' }) });
      const body = res.ok ? await res.json() : null;
      if (body && body.archived === false && body.reason) {
        const said = _el('div', 'brain-detail-said', body.reason);
        box.appendChild(said);
        return;
      }
    } catch (_) { /* the reload below shows whatever actually happened */ }
    state.open = null;
    await _load();
    _render();
  });
  actions.appendChild(retire);

  box.appendChild(actions);
  return box;
}

function _render(opts = {}) {
  const panel = document.getElementById(PANEL);
  if (!panel) return;
  const now = Math.floor(Date.now() / 1000);
  const { rows, shown, total } = apply(state.rows, state.filter, now);

  panel.replaceChildren();

  const head = _el('div', 'brain-explore-head');
  const back = _el('button', 'brain-explore-back', '← Memories');
  back.type = 'button';
  back.addEventListener('click', () => showExplore(false));
  head.appendChild(back);
  head.appendChild(_el('h3', 'brain-explore-title', 'Explore'));
  panel.appendChild(head);

  const fresh = _el('p', 'brain-explore-fresh',
    freshnessSentence(state.rows, { readAt: state.readAt, projects: state.projects.length }));
  fresh.id = 'brain-explore-fresh';
  panel.appendChild(fresh);

  panel.appendChild(_filterBar());

  const count = _el('div', 'brain-explore-count',
    shown === total ? `${total} memories` : `${shown} of ${total} memories`);
  if (isNarrowed(state.filter)) {
    const clear = _el('button', 'brain-explore-clear', 'Clear filters');
    clear.type = 'button';
    clear.addEventListener('click', () => { state.filter = emptyFilter(); _render(); });
    count.appendChild(clear);
  }
  panel.appendChild(count);

  const list = _el('div', 'brain-explore-list');
  list.id = 'brain-explore-list';
  if (!rows.length) {
    // Says which control is hiding things, rather than "no results".
    list.appendChild(_el('p', 'brain-explore-empty', total
      ? 'Nothing matches those filters. Clear them to see everything again.'
      : 'The Brain has not stored anything yet.'));
  }
  for (const memory of rows) {
    const row = _el('div', 'brain-explore-row');
    row.dataset.memoryId = String(memory.id);
    row.tabIndex = 0;
    row.setAttribute('role', 'button');
    const line = _el('div', 'brain-explore-row-text', memory.text);
    row.appendChild(line);
    const chips = _el('div', 'brain-explore-row-meta');
    if (memory.project_label) {
      chips.appendChild(_el('span', 'brain-detail-project', memory.project_label));
    }
    const pill = memoryConfidencePill(memory);
    if (pill) {
      const span = _el('span', 'memory-confidence', pill.text);
      span.title = pill.title;
      chips.appendChild(span);
    }
    chips.appendChild(_el('span', 'brain-explore-row-age', _ago(memory.timestamp)));
    row.appendChild(chips);
    const openIt = () => {
      state.open = state.open === memory.id ? null : memory.id;
      _render();
    };
    row.addEventListener('click', openIt);
    row.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openIt(); }
    });
    list.appendChild(row);
    if (state.open === memory.id) list.appendChild(_detail(memory));
  }
  panel.appendChild(list);

  if (opts.keepFocus) {
    const field = document.getElementById(opts.keepFocus);
    if (field) {
      field.focus();
      try { field.setSelectionRange(field.value.length, field.value.length); } catch (_) {}
    }
  }
}

/** Show or hide the surface. `P13-07`: not on the main path, not on open.
 *
 *  The four tabs are untouched and this panel has no tab, so nothing reaches
 *  it by accident; the card at the foot of the memories list is the one door.
 *  Returns whether the panel is now on show, so a test can drive it.
 */
export async function showExplore(on = true) {
  const panel = document.getElementById(PANEL);
  if (!panel) return false;
  const modal = document.getElementById('memory-modal');
  const panels = modal
    ? Array.from(modal.querySelectorAll('.memory-tab-panel[data-memory-panel]'))
    : [];
  if (!on) {
    panel.classList.add('hidden');
    // Back to whichever tab the strip says is current, rather than to a
    // hard-coded `browse`: the reader may have arrived from any of them.
    const brain = window.memoryModule;
    const tab = (brain && brain.getBrainTab) ? brain.getBrainTab() : 'browse';
    for (const other of panels) {
      other.classList.toggle('hidden', other.dataset.memoryPanel !== tab);
    }
    return false;
  }
  for (const other of panels) other.classList.add('hidden');
  panel.classList.remove('hidden');
  if (!state.readAt || !state.rows.length) await _load();
  _render();
  try { panel.scrollIntoView({ behavior: scrollBehavior(), block: 'start' }); } catch (_) {}
  return true;
}

export default { showExplore, freshnessSentence };
