// SPDX-License-Identifier: AGPL-3.0-or-later
// skills.js — the Skills window (`#skills-modal`, `P9-06`) and the Workbench's
// Skills room (`P22-21`).
//
// It was a tab in the Brain until 2026-09-30. The owner asked for skills to be
// groupable — packages that arrive together and groups a person makes — and
// chose a window of its own for them (`D-2026-09-30-01`). The Brain's Skills
// tab now opens this window.
//
// `P22-21` / `D-2026-10-02-02` §2: the window stays, and the Workbench gains a
// Skills room that mounts THIS module — not a copy of it (`Law 7`). So every
// view this file draws is drawn into a *mount* (see `_makeMount`), and the
// window and the room are two mounts of one module reading one store.
//
// Skills are SKILL.md files (frontmatter + body) under data/skills/.
// This UI supports: list, search, view (read SKILL.md), edit (replace
// content), publish/draft toggle, delete, and "run as slash" via the
// /<skill-name> path.

import uiModule from './ui.js';
import * as spinnerModule from './spinner.js';
import { bindMenuDismiss, dismissOrRemove } from './escMenuStack.js';
import { topPortalZ } from './toolWindowZOrder.js';
import { setBackgroundWork } from './modalManager.js?v=20261009census';
import { PLAY_GLYPH, chevronIcon } from './icons.js';
// `P22-17` / `P22-15` (wf-canvas). The gate card and `P8-18`'s sentence, shared
// with the Workbench's workflow steps (one card, one sentence — `Law 14`).
import { approvalBox } from './approvalBox.js';
import { SKILL_GATE_NOTE } from './skillGateNote.js';

const API = window.location.origin;
let skills = [];
let builtinSkills = [];   // read-only agent tool capabilities (TOOL_SECTIONS)
let loaded = false;
let _loadPromise = null;

function esc(s) { return uiModule.esc(String(s ?? '')); }

// ── packages and groups — `P8-49` … `P8-52` ─────────────────────────────────
// `GET /api/skills/collections`: `{ packages, groups, off }`. A group is a list
// of names — a skill in two groups is one skill (`D-2026-09-30-01`) — and
// `off` is `{ name: [what holds it off] }`, read from the server that decides
// injection rather than recomputed here.
let _collections = { packages: [], groups: [], off: {} };
const _SCOPE_KEY = 'skillsScope';

// ── mounts — `P22-21`, `D-2026-10-02-02` §2 ────────────────────────────────
//
// One module, two places. The Skills window (`#skills-modal`) and the
// Workbench's Skills room (`#skills-room`) both draw this module's views, and
// neither holds a copy of its code (`Law 7`). What a *view* owns — its
// controls, and its scope, sort, filter and selection — lives on a mount; what
// is true of the skills themselves — the list, the packages and groups, the
// SKILL.md cache — lives once, at the top of this file. So an edit made in one
// place is drawn in the other the moment the store reloads, and the two can
// still be looking at different packages.
//
// A mount finds its controls by id **with its own prefix**. The window's ids
// are the page's own, unchanged since `P9-06` (prefix ''); the room's copy of
// the same markup — stamped from the window's at first use (`_stampRoom`), so
// the markup is one source too — carries `wb-` in front of every id. Both can
// be on the page at once and no id is declared twice. Anything a mount looks
// for that is not an id, it looks for inside its own host.
const ROOM_PREFIX = 'wb-';
const _ROOM_SCOPE_KEY = 'skillsRoomScope';
const _mounts = [];
// Where a person last pressed or typed. A toast's button (*See what changed*)
// lives outside both mounts; the card it means is the one in this mount.
let _lastMount = null;

function _readScope(key) {
  try {
    const v = JSON.parse(localStorage.getItem(key) || 'null');
    if (v && typeof v.kind === 'string') return v;
  } catch (_) {}
  return { kind: 'all' };
}

/** A place this module draws into: `host` holds the markup, `prefix` is what
 *  its ids carry, and the rest is what that one view has chosen. */
function _makeMount(host, { prefix = '', scopeKey = _SCOPE_KEY } = {}) {
  return {
    host,
    prefix,
    scopeKey,
    el: (id) => document.getElementById(prefix + id),
    scope: _readScope(scopeKey),
    sort: 'confidence',
    draftsOnly: false,
    publishedOnly: false,
    confMax: null,          // confidence ceiling filter (%, e.g. 90 = show ≤90%); null = off
    selectMode: false,
    selected: new Set(),
    cascadeNext: false,     // play the domino-in entrance on this mount's next render
    pendingFocus: null,     // a skill to open once the list has loaded
  };
}

/** The window's mount, made the first time anything asks: its ids are the
 *  page's own, so it exists whether or not the window was ever opened. */
function _windowMount() {
  let m = _mounts.find((x) => x.prefix === '');
  if (!m) {
    m = _makeMount(document.getElementById('skills-modal') || document.body);
    _mounts.unshift(m);
  }
  return m;
}

function _allMounts() { _windowMount(); return _mounts.slice(); }

/** The mount holding `node`, or the window's. */
function _mountOf(node) {
  return (node && _mounts.find((m) => m.host !== document.body && m.host.contains(node)))
    || _windowMount();
}

/** Where the person is working now: the mount holding the focus, else the
 *  one they last pressed or typed in, else the window. */
function _activeMount() {
  const here = document.activeElement && _mounts.find((m) => m.host !== document.body
    && m.host.contains(document.activeElement));
  return here || _lastMount || _windowMount();
}

/** Draw the store into every mount. */
function _renderAll() {
  for (const m of _allMounts()) {
    renderSkillsList(m);
    _renderSkillsSide(m);
  }
  updateCount();
}

async function _fetchCollections() {
  try {
    const res = await fetch(`${API}/api/skills/collections`);
    if (!res.ok) return;
    const data = await res.json();
    _collections = {
      packages: Array.isArray(data && data.packages) ? data.packages : [],
      groups: Array.isArray(data && data.groups) ? data.groups : [],
      off: (data && data.off && typeof data.off === 'object') ? data.off : {},
    };
  } catch (_) {
    // The list is the point of this window; a sidebar that could not load
    // leaves every skill shown as on, which is what the server does too when
    // it cannot read its switches.
  }
}
function _playSkillsCascade(container = document.getElementById('skills-list')) {
  if (!container || !container.querySelector('.skill-card')) return false;
  container.classList.remove('doclib-just-opened');
  void container.offsetWidth;
  container.classList.add('doclib-just-opened');
  setTimeout(() => container.classList.remove('doclib-just-opened'), 900);
  return true;
}

// Cache of SKILL.md text by skill name, so a card opened a second time is
// instant (no async fetch + content-settle jump). Populated on expand.
// `B1127`: it also said "eagerly in the background for all visible cards right
// after render" — the function that did that (`_preloadVisibleMarkdown`) had no
// caller, read only the window's `#skills-list` (not a room's, `P22-21`), and
// would cost one request per card per draw for previews most cards never open.
// It was removed rather than wired.
const _mdCache = new Map();
async function _fetchSkillMarkdown(name) {
  if (_mdCache.has(name)) return _mdCache.get(name);
  const res = await fetch(`${API}/api/skills/${encodeURIComponent(name)}/markdown`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  const md = data.markdown || '';
  _mdCache.set(name, md);
  return md;
}

// Collapsed skills sections ("user" / "builtin"), persisted so the
// choice survives reloads. Built-in defaults to collapsed (it's
// reference info, not the user's own skills).
const _collapsedSections = (() => {
  try {
    const raw = localStorage.getItem('skillsSectionsCollapsed');
    if (raw) return new Set(JSON.parse(raw));
  } catch (_) {}
  return new Set(['builtin']);
})();
function _saveCollapsedSections() {
  try { localStorage.setItem('skillsSectionsCollapsed', JSON.stringify([..._collapsedSections])); } catch (_) {}
}
function _applySectionCollapse(container) {
  if (!container) return;
  container.querySelectorAll('.skills-section-header').forEach(h => {
    h.classList.toggle('collapsed', _collapsedSections.has(h.dataset.section));
    h.setAttribute('aria-expanded', String(!_collapsedSections.has(h.dataset.section)));
  });
  container.querySelectorAll('.doclib-card[data-skill-section]').forEach(c => {
    c.classList.toggle('skill-card-section-hidden', _collapsedSections.has(c.dataset.skillSection));
  });
}

export async function loadSkills(cascade = false) {
  // Play the domino-in entrance on this load (set when the tab is opened,
  // not for the silent re-loads after an edit/delete). `true` is the window;
  // a mount is that mount (`P22-21`).
  if (cascade) (cascade === true ? _windowMount() : cascade).cascadeNext = true;
  // Always re-fetch when the tab is explicitly opened — the cascade
  // animation is handled inside renderSkillsList() via the mount's cascadeNext.
  // Skipping the fetch here caused stale data on panel close/reopen (#5870).
  if (_loadPromise) return _loadPromise;
  _loadPromise = (async () => {
  try {
    const [res] = await Promise.all([fetch(`${API}/api/skills`), _fetchCollections()]);
    const data = await res.json();
    // Dedupe by name (case-insensitive) — the API has occasionally
    // returned the same skill twice (built-in shadow + user copy, or
    // a write-then-read race), and rendering both made the duplicate
    // detector mark BOTH entries as the "recommended" keeper.
    const _seen = new Set();
    skills = (data.skills || []).filter(sk => {
      const k = String(sk?.name || sk?.id || '').toLowerCase();
      if (!k) return true;
      if (_seen.has(k)) return false;
      _seen.add(k);
      return true;
    });
    _loadSkillApprovalThreshold();
    await _loadBuiltinCapabilities();
    loaded = true;
    _renderAll();
    for (const m of _allMounts()) {
      if (!m.pendingFocus) continue;
      _focusSkillRow(m, m.pendingFocus);
      m.pendingFocus = null;
    }
    // If a background audit is running, re-show its progress panel.
    if (!_auditPoll) {
      _fetchAuditStatus().then(st => {
        if (st.status === 'running') _showAudit(st);
      }).catch(() => {});
    }
  } catch (e) {
    console.error('Failed to load skills:', e);
  } finally {
    _loadPromise = null;
  }
  })();
  return _loadPromise;
}

// `P2-21`. The list behind the "Built-in capabilities" section. It was never
// written: `builtinSkills` sat at `[]` for the life of the file and nothing in
// the tree fetched `GET /api/skills/builtin`, so flipping the section's flag on
// its own drew a header counting nothing.
//
// The route is admin-gated (`P2-21` / `P11-10`), so most signed-in people get a
// 403 here and that is the ordinary case, not a failure: the list stays empty,
// the section is not drawn at all, and nothing is said about it. A toast for a
// panel the person did not ask for would be worse than the missing panel.
// Errors are swallowed for the same reason — the Workshop's own skills are the
// point of this screen and they have already loaded by the time this runs.
async function _loadBuiltinCapabilities() {
  try {
    const res = await fetch(`${API}/api/skills/builtin`);
    if (!res.ok) { builtinSkills = []; return; }
    const data = await res.json();
    builtinSkills = Array.isArray(data.builtin) ? data.builtin : [];
  } catch (_) {
    builtinSkills = [];
  }
}

function _focusSkillRow(m, name) {
  setTimeout(() => {
    const card = _findSkillCard(name, m);
    if (!card) return;
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    card.classList.add('skill-row-flash');
    setTimeout(() => card.classList.remove('skill-row-flash'), 2000);
    // Expand it so the linked skill opens to its SKILL.md directly.
    _expandSkillCard(card, name);
  }, 200);
}

// Open the Skills window and focus one skill's card. Used by the chat
// anchor-link delegate ([name](#skill-<name>)), the "skills used" pill and an
// import's "Open it". `opts.scope` narrows the list first — an import opens on
// the package it just installed.
//
// `P22-21`. `m` is where to open it: left out — every caller before the room —
// it is the window, as it always was; the room's own import and fork pass the
// room, so they open on the skill where the person is rather than in a second
// window.
export function openSkill(name, opts = {}, m = null) {
  const at = m || _windowMount();
  at.pendingFocus = name || null;
  if (opts && opts.scope) _setScope(at, opts.scope, { render: false });
  else if (name && !_inScope(at, skills.find(s => (s.name || s.id) === name) || {})) {
    _setScope(at, { kind: 'all' }, { render: false });
  }
  if (at.prefix === '') { openSkillsWindow('browse'); return; }
  _showSkillsView(at, 'browse');
  loadSkills();
}

let _skillApprovalThreshold = 0.85;

function updateCount() {
  // The Brain's door to this window carries the total (`P23-02`).
  const el = document.getElementById('skills-count');
  if (el) el.textContent = skills.length || '0';
  for (const m of _allMounts()) _writeShownCount(m);
}

function _sortSkills(m, list) {
  const arr = list.slice();
  if (m.sort === 'confidence') {
    arr.sort((a, b) => (b.confidence || 0) - (a.confidence || 0) || (a.name || '').localeCompare(b.name || ''));
  } else if (m.sort === 'uses') {
    arr.sort((a, b) => (b.uses || 0) - (a.uses || 0) || (a.name || '').localeCompare(b.name || ''));
  } else if (m.sort === 'recent') {
    arr.sort((a, b) => (b.updated_at || b.created_at || 0) - (a.updated_at || a.created_at || 0));
  } else {
    arr.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
  }
  return arr;
}

function _matches(sk, query) {
  const q = query.toLowerCase();
  return (
    (sk.name || '').toLowerCase().includes(q) ||
    (sk.description || '').toLowerCase().includes(q) ||
    (sk.when_to_use || sk.problem || '').toLowerCase().includes(q) ||
    (sk.category || '').toLowerCase().includes(q) ||
    (sk.tags || []).some(t => (t || '').toLowerCase().includes(q))
  );
}

// `P8-03`. What a person reads changes; what is stored does not. `draft` is
// frontmatter, it is compared server-side, and `data-status` is the hook the
// styling and the select-mode code use — `Law 2`. Only the word moves.
//
// A draft is left OUT of the catalogue the model browses (`index_for`) and is
// STILL matched and injected by keyword (`get_relevant_skills`) whenever it
// clears the minimum confidence — not switched off, unlisted. `P8-03` said so
// with the word "uncatalogued"; `BRAIN-U-17` (P23-02, Doc 2 § 5) counted six
// words for these two states (*uncatalogued / published / active*,
// *Uncatalogue / Publish*, *Unpublish*, *Approve*, *Auto-approve*) and settles
// on two, **Draft** and **Published**, with the verbs **Publish** /
// **Unpublish** — and the rule P8-03 cared about carried by the hover, so the
// word can be short and the state still told truly.
const _STATUS_PILL_TITLE = {
  published: 'Published: listed for the model on every request.',
  draft: 'Draft: not listed; used only when a message matches it and it clears the confidence bar in Settings.',
};

function _statusPill(sk) {
  const s = sk.status || (sk._legacy ? 'legacy' : 'draft');
  if (s === 'published') return `<span class="memory-cat-badge skill-status-pill" data-status="published" title="${esc(_STATUS_PILL_TITLE.published)}" style="background:color-mix(in srgb, var(--accent, #4ade80) 30%, transparent)">published</span>`;
  if (s === 'draft')     return `<span class="memory-cat-badge skill-status-pill" data-status="draft" title="${esc(_STATUS_PILL_TITLE.draft)}" style="background:color-mix(in srgb, var(--fg) 14%, transparent)">draft</span>`;
  return `<span class="memory-cat-badge skill-status-pill" data-status="${esc(s)}" style="opacity:0.6">${esc(s)}</span>`;
}

// `P8-51`. A skill whose package or group is switched off is still listed and
// still editable — it is left out of everything the model is shown, and the
// pill says by what.
function _offPill(sk) {
  const why = (_collections.off || {})[sk.name || sk.id];
  if (!Array.isArray(why) || !why.length) return '';
  const title = `Off with ${why.join(' and ')} (sidebar).`;
  return `<span class="memory-cat-badge skill-off-pill" title="${esc(title)}">off</span>`;
}

// Show a "teacher" badge for skills written by the auto-escalation
// teacher loop. Lets the user tell at-a-glance which procedures were
// hand-authored vs auto-generated so they can audit (and demote /
// edit / publish) before trusting them.
function _sourcePill(sk) {
  if (sk.source !== 'teacher-escalation') return '';
  const teacher = sk.teacher_model || 'teacher';
  return `<span class="memory-cat-badge" title="Created by teacher escalation: ${esc(teacher)}" style="background:color-mix(in srgb, var(--color-warning, #f0ad4e) 22%, transparent);">teacher-created</span>`;
}

function _skillTokens(sk) {
  return new Set(String([
    sk.name || '',
    sk.description || '',
    sk.when_to_use || '',
    ...(sk.tags || []),
  ].join(' ')).toLowerCase()
    .replace(/-\d+\b/g, '')
    .split(/[^a-z0-9]+/)
    .filter(t => t.length > 2 && !['the', 'and', 'with', 'for', 'from', 'using'].includes(t)));
}

function _skillSimilarity(a, b) {
  const A = _skillTokens(a), B = _skillTokens(b);
  if (!A.size || !B.size) return 0;
  let inter = 0;
  for (const t of A) if (B.has(t)) inter++;
  return inter / (A.size + B.size - inter);
}

function _baseSkillName(name) {
  return String(name || '').replace(/-\d+$/, '');
}

function _scoreDuplicateKeeper(sk) {
  return [
    (sk.status === 'published') ? 100000 : 0,
    (sk.uses || 0) * 100,
    Math.round((sk.confidence || 0) * 100),
    sk.audit_by_teacher ? -5 : 0,
    -String(sk.name || '').length / 1000,
  ].reduce((a, b) => a + b, 0);
}

function _forkedFrom(sk, origin) {
  const body = String((sk && (sk.body_extra || sk.solution)) || '');
  return !!origin && body.includes('Forked from `' + origin + '`');
}

function _duplicateMeta(list) {
  const parent = new Map();
  const names = list.map(s => s.name || s.id).filter(Boolean);
  names.forEach(n => parent.set(n, n));
  const find = (x) => {
    let p = parent.get(x) || x;
    while (p !== parent.get(p)) p = parent.get(p);
    return p;
  };
  const unite = (a, b) => {
    const pa = find(a), pb = find(b);
    if (pa !== pb) parent.set(pb, pa);
  };
  for (let i = 0; i < list.length; i++) {
    for (let j = i + 1; j < list.length; j++) {
      const a = list[i], b = list[j];
      const an = a.name || a.id, bn = b.name || b.id;
      if (!an || !bn) continue;
      // `BRAIN-M-9` (P23-02). A fork is the one deliberate copy: it is not a
      // duplicate of the skill it was forked from (`fork_skill` writes
      // "Forked from `<name>`." into its body). A fresh fork opened branded
      // "duplicate #1 · lower-priority" of its own origin (measured).
      if (_forkedFrom(a, bn) || _forkedFrom(b, an)) continue;
      if (_baseSkillName(an) === _baseSkillName(bn) || _skillSimilarity(a, b) >= 0.38) {
        unite(an, bn);
      }
    }
  }
  const groups = new Map();
  for (const sk of list) {
    const n = sk.name || sk.id;
    if (!n) continue;
    const root = find(n);
    if (!groups.has(root)) groups.set(root, []);
    groups.get(root).push(sk);
  }
  const meta = new Map();
  let idx = 1;
  for (const group of groups.values()) {
    if (group.length < 2) continue;
    const sorted = group.slice().sort((a, b) => _scoreDuplicateKeeper(b) - _scoreDuplicateKeeper(a));
    const keep = sorted[0].name || sorted[0].id;
    const groupNames = sorted.map(s => s.name || s.id).filter(Boolean);
    for (const sk of sorted) {
      const n = sk.name || sk.id;
      meta.set(n, { group: idx, keep: n === keep, keepName: keep, names: groupNames });
    }
    idx++;
  }
  return meta;
}

function _auditModelPills(sk) {
  const worker = sk.audit_worker_model || '';
  const teacher = sk.audit_teacher_model || '';
  let html = '';
  if (worker) {
    html += `<span class="memory-cat-badge skill-model-pill skill-model-student" title="Last audited by default audit model: ${esc(worker)}">audit</span>`;
  }
  if (sk.audit_by_teacher || teacher) {
    const title = teacher
      ? `Teacher rewrote this skill; audit model passed after the rewrite. Teacher: ${teacher}`
      : 'Teacher rewrote this skill; audit model passed after the rewrite.';
    html += `<span class="memory-cat-badge skill-model-pill skill-model-teacher" title="${esc(title)}">teacher-fixed</span>`;
  }
  return html;
}

function _necessityKind(sk) {
  const nec = sk && sk.necessity;
  if (sk && sk._duplicateGroup) return 'duplicate';
  if (!nec || nec.necessary !== false) return null;
  const reason = String(nec.reason || '').toLowerCase();
  const redundant = (nec.redundant_with || []).filter(Boolean);
  if (redundant.length || /duplicat|redundan|overlap|same skill|same procedure/.test(reason)) return 'duplicate';
  if (/trivial|generic|capable assistant|without a saved|not need|unnecessary/.test(reason)) return 'trivial';
  return 'irrelevant';
}

function _necessityPill(sk) {
  const kind = _necessityKind(sk);
  if (!kind) return '';
  const nec = sk.necessity || {};
  const dup = (nec.redundant_with || []).filter(Boolean);
  const label = kind === 'duplicate' ? (sk._duplicateGroup ? `duplicate #${sk._duplicateGroup}` : 'duplicate')
    : kind === 'trivial' ? 'generic'
    : 'possibly-irrelevant';
  const group = sk._duplicateNames || [];
  const why = sk._duplicateGroup
    ? `Duplicate group #${sk._duplicateGroup}. Recommended keep: ${sk._duplicateKeepName}. Group: ${group.join(', ')}`
    : (nec.reason || 'May not be worth keeping') + (dup.length ? ' | overlaps: ' + dup.join(', ') : '');
  return `<span class="memory-cat-badge skill-necessity-pill skill-necessity-${kind}" title="${esc(why)}">${label}</span>`;
}

function _duplicatePriorityPill(sk) {
  if (!sk._duplicateGroup) return '';
  if (sk._duplicateKeep) {
    return `<span class="memory-cat-badge skill-duplicate-keep" title="Best duplicate candidate by published status, uses, confidence, and specificity">recommended</span>`;
  }
  return `<span class="memory-cat-badge skill-duplicate-lower" title="Lower-priority duplicate. Suggested keeper: ${esc(sk._duplicateKeepName || '')}">lower-priority</span>`;
}

// Verified-by-test indicators shown next to the confidence %. A check when a
// test/audit run passed; a graduation-cap when the teacher model had to
// rewrite the skill to make it pass. SVG (no Unicode emoji).
function _auditMarks(sk) {
  let html = '';
  if (sk.audit_verdict === 'pass') {
    html += `<span class="skill-verified" title="Passed an automated test"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></span>`;
  }
  if (sk.audit_by_teacher) {
    const teacher = sk.audit_teacher_model ? `: ${sk.audit_teacher_model}` : '';
    html += `<span class="skill-teachermark" title="Teacher rewrote this skill; audit model passed after the rewrite${esc(teacher)}"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 10L12 5 2 10l10 5 10-5z"/><path d="M6 12v5c0 1 3 2 6 2s6-1 6-2v-5"/></svg></span>`;
  }
  return html;
}

// Audit verdict dot — removed at user request. The ✓ check-mark next to the
// confidence % still indicates a pass. Stub returns empty so the surrounding
// header HTML still composes without changing other layout.
function _auditDot(sk) { return ''; }

// Confidence → colour. 90%+ is solidly green, scaling down through
// yellow/orange to red at 50% and below (hue 120→0 over 90→50).
function _confColor(conf) {
  const hue = Math.max(0, Math.min(120, ((conf - 50) / 40) * 120));
  return `hsl(${Math.round(hue)}, 70%, 42%)`;
}

// Shared action icons (collapsed kebab menu + expanded footer use the same).
const _ICON = {
  del:   '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
  edit:  '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>',
  approve: '<polyline points="20 6 9 17 4 12"/>',
  unpublish: '<path d="M5 12l5 5L20 7"/>',
  test:  PLAY_GLYPH,
  group: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/>',
  fork:  '<circle cx="6" cy="5" r="2"/><circle cx="18" cy="5" r="2"/><circle cx="12" cy="19" r="2"/><path d="M6 7v2a3 3 0 0 0 3 3h6a3 3 0 0 0 3-3V7"/><line x1="12" y1="12" x2="12" y2="17"/>',
  update: '<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>',
  rename: '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  // `P22-23`. A clock turned back, and the import button's own tray arrow.
  history: '<path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><path d="M12 7v5l4 2"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
};
function _svg(paths, { fill = 'none', size = 13 } = {}) {
  const stroke = fill === 'currentColor' ? '' : 'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="${fill}" ${stroke} style="vertical-align:-2px;flex-shrink:0;">${paths}</svg>`;
}

// Kebab dropdown for a collapsed skill card — same actions + icons as the
// expanded footer (Publish/Unpublish · Edit · Delete).
function _openSkillMenu(m, btn, card, sk, name, isPublished) {
  document.querySelectorAll('.skill-kebab-menu').forEach(dismissOrRemove);
  const menu = document.createElement('div');
  menu.className = 'skill-kebab-menu';
  const mk = (paths, label, opts, onClick) => {
    const item = document.createElement('button');
    item.className = 'skill-kebab-item' + (opts && opts.danger ? ' danger' : '');
    item.innerHTML = _svg(paths, opts) + `<span>${label}</span>`;
    item.addEventListener('click', (e) => { e.stopPropagation(); close(); onClick(); });
    menu.appendChild(item);
  };
  if (isPublished) mk(_ICON.unpublish, 'Unpublish', {}, () => _setSkillStatus(name, 'draft'));
  else mk(_ICON.approve, 'Publish', {}, () => _setSkillStatus(name, 'published'));
  // Select — moved up to 2nd so it sits next to Publish/Unpublish
  // (bulk actions cluster at the top of the menu).
  const selItem = document.createElement('button');
  selItem.className = 'skill-kebab-item';
  selItem.innerHTML = '<svg class="memory-select-btn-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/></svg><span>Select</span>';
  selItem.addEventListener('click', (e) => {
    e.stopPropagation();
    close();
    if (!m.selectMode) _enterSelectMode(m);
    m.selected.add(name);
    renderSkillsList(m);
  });
  menu.appendChild(selItem);

  mk(_ICON.edit, 'Edit', {}, async () => {
    if (!card.classList.contains('doclib-card-expanded')) await _expandSkillCard(card, name);
    _toggleSkillEdit(card, name);
  });
  mk(_ICON.test, 'Test', {}, () => _testSkill(card, name));
  // `P8-09`. Beside Test because it IS the test, run twice — once on the
  // copy your last save replaced and once on what is there now.
  mk(_ICON.test, 'Compare with previous', {}, () => _compareSkill(card, name));
  // Audit kicks off the bulk audit-all loop (test → judge → fix → retry → demote).
  mk(_ICON.test, 'Audit', {}, () => _auditAllSkills(m));
  // `P8-50`. A group lists the skill; it is not copied into it.
  mk(_ICON.group, 'Groups…', {}, () => _openGroupMenu(m, btn, [name]));
  // `P8-52`. The one deliberate copy — a separate skill to change freely.
  mk(_ICON.fork, 'Fork', {}, () => _forkSkill(m, name));
  // `P22-23`. The two things a terminal could do with one skill and a person
  // could not: see and put back its earlier copies, and take it away as a file.
  mk(_ICON.history, 'History', {}, () => _showSkillHistory(card, name));
  mk(_ICON.download, 'Download', {}, () => _downloadSkill(name));
  mk(_ICON.del, 'Delete', { danger: true }, () => _deleteSkill(name, card));

  // Mobile-only Cancel — mirrors the email/documents/brain popup pattern.
  // CSS hides `.dropdown-cancel-mobile` on desktop where outside-click
  // already dismisses cleanly.
  const cancelItem = document.createElement('button');
  cancelItem.className = 'skill-kebab-item dropdown-cancel-mobile';
  cancelItem.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg><span>Cancel</span>';
  cancelItem.addEventListener('click', (e) => { e.stopPropagation(); close(); });
  menu.appendChild(cancelItem);

  document.body.appendChild(menu);
  // Override the CSS z-index (100002) with a value derived from the live
  // tool-window stack so the kebab menu stays above its modal even after the
  // bring-to-front counter climbs past the static value (#4720).
  menu.style.zIndex = String(topPortalZ());
  const r = btn.getBoundingClientRect();
  menu.style.top = (r.bottom + 4) + 'px';
  menu.style.right = Math.max(6, window.innerWidth - r.right) + 'px';
  // Keep it on-screen (mobile): flip above the button if it would overflow the
  // bottom, clamp the left edge, and cap the height as a last resort.
  const mr = menu.getBoundingClientRect();
  if (mr.bottom > window.innerHeight - 6) {
    menu.style.top = Math.max(6, r.top - mr.height - 4) + 'px';
  }
  if (mr.left < 6) {
    menu.style.right = Math.max(6, window.innerWidth - 6 - mr.width) + 'px';
  }
  const mr2 = menu.getBoundingClientRect();
  if (mr2.bottom > window.innerHeight - 6) {
    menu.style.maxHeight = Math.max(80, window.innerHeight - 12 - mr2.top) + 'px';
    menu.style.overflowY = 'auto';
  }
  const close = bindMenuDismiss(menu, () => { menu.remove(); }, (ev) => !menu.contains(ev.target));
}

// The built-ins that survive the toolbar's current filter. They carry no
// `status` and no `confidence`, so the drafts / published / confidence filters
// exclude the whole section rather than quietly matching none of it — a
// "Built-in capabilities 0" header under a drafts filter says the built-ins
// went away, and they did not. The search box does apply, because a person
// typing a tool's name is looking for that tool wherever it lives.
function _getFilteredBuiltins(m) {
  if (m.draftsOnly || m.publishedOnly || m.confMax != null) return [];
  // A package, a group or "Built-in" is a list of SKILL.md files; the native
  // tool capabilities belong to none of them.
  if (m.scope.kind !== 'all') return [];
  const query = (m.el('skills-search')?.value || '').toLowerCase();
  if (!query) return builtinSkills;
  return builtinSkills.filter(b =>
    String(b.name || '').toLowerCase().includes(query) ||
    String(b.description || '').toLowerCase().includes(query));
}

// Cards for the agent's built-in tool capabilities (from
// /api/skills/builtin → TOOL_SECTIONS). Expandable to preview the
// instruction block; editable with a warning + a revert-to-default
// button (overrides stored in settings, applied to the prompt).
function _buildBuiltinCards(rows) {
  return (rows || []).map(b => {
    const card = document.createElement('div');
    card.className = 'doclib-card skill-card skill-builtin-card';
    card.dataset.builtinName = b.name;

    const header = document.createElement('div');
    header.className = 'doclib-card-header skill-card-header';
    // `P10-06`. The name is the card's keyboard control — see `_CARD_OWN`.
    header.innerHTML = `
      <span class="skill-conf-dot" style="display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--accent, var(--red));flex-shrink:0;margin-right:6px;opacity:0.55;"></span>
      <div style="flex:1;min-width:0;">
        <div class="doclib-card-title" style="display:flex;align-items:center;gap:6px;min-width:0;">
          <button type="button" class="skill-card-toggle" aria-expanded="false" style="width:auto;flex:0 1 auto;overflow:hidden;"><code style="display:block;font-weight:600;font-size:0.9em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(b.name)}</code></button>
          <span class="memory-cat-badge" style="background:color-mix(in srgb, var(--fg) 14%, transparent)">built-in</span>
          ${b.is_overridden ? '<span class="memory-cat-badge" title="You have edited this built-in capability" style="background:color-mix(in srgb, var(--color-warning, #f0ad4e) 30%, transparent);">edited</span>' : ''}
        </div>
        ${b.description ? `<div class="doclib-card-session" title="${esc(b.description)}" style="font-size:10px;opacity:0.55;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(b.description)}</div>` : ''}
      </div>
      <span class="doclib-card-chevron">${chevronIcon({ size: 14 })}</span>
    `;
    card.appendChild(header);

    const preview = document.createElement('div');
    preview.className = 'doclib-card-preview skill-card-preview';
    // Warning banner — editing a built-in changes how the assistant uses a native tool.
    const warn = document.createElement('div');
    warn.className = 'skill-builtin-warn';
    // `COPY-U-22` (P23-02): 30 words → one line.
    warn.innerHTML = '⚠ Built in. Edits change how the model uses this tool; Revert restores the default.';
    preview.appendChild(warn);
    const pre = document.createElement('pre');
    pre.className = 'skill-md-pre';
    pre.textContent = '';  // filled on expand
    preview.appendChild(pre);

    // Footer: Revert (left, only meaningful when overridden) · Edit/Save (right).
    const actions = document.createElement('div');
    actions.className = 'doclib-card-expanded-actions';

    const revertBtn = document.createElement('button');
    revertBtn.className = 'doclib-card-text-btn doclib-card-action-btn doclib-card-text-btn-danger';
    revertBtn.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>Revert';
    revertBtn.title = 'Restore the original shipped instructions';
    revertBtn.addEventListener('click', (e) => { e.stopPropagation(); _revertBuiltin(b.name); });

    const editBtn = document.createElement('button');
    editBtn.className = 'doclib-card-text-btn doclib-card-action-btn';
    editBtn.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>Edit';
    editBtn.addEventListener('click', (e) => { e.stopPropagation(); _toggleBuiltinEdit(card, b.name); });

    const rightGroup = document.createElement('div');
    rightGroup.className = 'doclib-action-group';
    const btnRow = document.createElement('div');
    btnRow.className = 'doclib-action-btn-row';
    btnRow.appendChild(editBtn);
    rightGroup.appendChild(btnRow);

    actions.appendChild(revertBtn);
    actions.appendChild(rightGroup);
    preview.appendChild(actions);
    card.appendChild(preview);

    card.addEventListener('click', (e) => {
      if (e.target.closest(_CARD_OWN)) return;
      // Editing in progress → don't collapse on an outside-the-textarea click.
      if (card.querySelector('.skill-md-editor')) return;
      _expandBuiltinCard(card, b.name);
    });
    return card;
  });
}

// `P10-06`. The controls INSIDE a skill card that answer a click themselves,
// so a click on one of them is not also a click on the card. The card's name
// is deliberately not among them: it is a `<button class="skill-card-toggle">`
// so a keyboard can reach and press it — a card holds its own buttons (the
// kebab, Edit, Delete), so the card itself cannot be one (`P10-02`'s rule) —
// and pressing it is a click on the card, which opens it, closes it, or in
// Select mode ticks it, exactly as clicking anywhere else on the card does.
// Measured 2026-09-27 before this: Tab reached a skill card's kebab and
// nothing else, so no card could be opened to read its SKILL.md.
const _CARD_OWN = 'button:not(.skill-card-toggle), input, textarea';

/** `P10-06`. The name button says whether its card is open. The class is the
 *  state every open and close path already writes; this reads it after them.
 *  A card closed with the focus on something in its body — Escape from Edit,
 *  say — would drop the focus to <body> as the body hides (measured: it did);
 *  it goes back to the name instead. */
function _syncCardToggle(card) {
  const toggle = card && card.querySelector('.skill-card-toggle');
  if (!toggle) return;
  const open = card.classList.contains('doclib-card-expanded');
  toggle.setAttribute('aria-expanded', String(open));
  const body = card.querySelector('.doclib-card-preview');
  if (!open && body && body.contains(document.activeElement)) {
    try { toggle.focus(); } catch (_) {}
  }
}

async function _expandBuiltinCard(card, name) {
  const grid = card.closest('.doclib-grid');
  if (card.classList.contains('doclib-card-expanded')) {
    card.classList.remove('doclib-card-expanded');
    _syncCardToggle(card);
    return;
  }
  if (grid) grid.querySelectorAll('.doclib-card-expanded').forEach(c => {
    c.classList.remove('doclib-card-expanded');
    _syncCardToggle(c);
  });
  card.classList.add('doclib-card-expanded');
  _syncCardToggle(card);
  if (grid) grid.scrollTop = 0;
  const pre = card.querySelector('.skill-md-pre');
  if (pre && !card._loaded) {
    pre.textContent = 'Loading…';
    try {
      const res = await fetch(`${API}/api/skills/builtin/${encodeURIComponent(name)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      pre.textContent = data.text || '(empty)';
      card._loaded = true;
      card._text = data.text || '';
      card._default = data.default || '';
    } catch (e) {
      pre.textContent = 'Failed to load.';
    }
  }
}

function _toggleBuiltinEdit(card, name) {
  const preview = card.querySelector('.skill-card-preview');
  if (!preview) return;
  if (preview.querySelector('.skill-md-editor')) { _saveBuiltinEdit(card, name); return; }
  const pre = preview.querySelector('.skill-md-pre');
  const ta = document.createElement('textarea');
  ta.className = 'skill-md-editor';
  ta.spellcheck = false;
  ta.value = (card._text != null ? card._text : (pre ? pre.textContent : '')) || '';
  ta.addEventListener('click', (e) => e.stopPropagation());
  if (pre) pre.style.display = 'none';
  preview.insertBefore(ta, preview.querySelector('.doclib-card-expanded-actions'));
  ta.focus();
  const editBtn = [...preview.querySelectorAll('.doclib-card-action-btn')].find(b => /Edit|Save/.test(b.textContent));
  if (editBtn) editBtn.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>Save';
}

async function _saveBuiltinEdit(card, name) {
  const ta = card.querySelector('.skill-md-editor');
  if (!ta) return;
  try {
    const res = await fetch(`${API}/api/skills/builtin/${encodeURIComponent(name)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: ta.value }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    uiModule.showToast('Built-in capability updated');
    builtinSkills = [];  // force reload of built-in list (refreshes "edited" badge)
    await loadSkills();
  } catch (e) { uiModule.showError('Save failed: ' + e.message); }
}

async function _revertBuiltin(name) {
  if (!(await uiModule.styledConfirm(`Revert "${name}" to its original built-in instructions?`, { confirmText: 'Revert', danger: true }))) return;
  try {
    const res = await fetch(`${API}/api/skills/builtin/${encodeURIComponent(name)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    uiModule.showToast('Reverted to default');
    builtinSkills = [];
    await loadSkills();
  } catch (e) { uiModule.showError('Revert failed: ' + e.message); }
}

function _getFilteredSkills(m) {
  const query = (m.el('skills-search')?.value || '').toLowerCase();
  let filtered = m.scope.kind === 'all' ? skills : skills.filter(sk => _inScope(m, sk));
  if (query) filtered = filtered.filter(sk => _matches(sk, query));
  if (m.draftsOnly) {
    filtered = filtered.filter(sk => (sk.status || 'draft') !== 'published');
  }
  if (m.publishedOnly) {
    filtered = filtered.filter(sk => (sk.status || 'draft') === 'published');
  }
  if (m.confMax != null) {
    // "≤ X%" — surface the lower-confidence skills that may need review.
    filtered = filtered.filter(sk => Math.round((sk.confidence || 0) * 100) <= m.confMax);
  }
  return _sortSkills(m, filtered);
}

/** `BRAIN-M-10` / `COPY-U-15` (P23-02). The header beside "Skills" counts what
 *  is on screen, and only when that is not everything: "5 of 8" under a scope,
 *  a search or a filter; nothing otherwise — the total is on the door. It wrote
 *  `skills.length` whatever was shown ("8 skills" over five cards, and over
 *  none). */
function _writeShownCount(m) {
  const elH = m.el('skills-count-h2');
  if (!elH) return;
  const shown = loaded ? _getFilteredSkills(m).length : skills.length;
  elH.textContent = shown === skills.length ? '' : `${shown} of ${skills.length}`;
}

/** Whether a filter (not the scope or the search) is narrowing the list. */
function _filtering(m) {
  return !!(m.draftsOnly || m.publishedOnly || m.confMax != null);
}

function _clearFilter(m) {
  m.draftsOnly = false; m.publishedOnly = false; m.confMax = null;
  const sel = m.el('skills-filter');
  if (sel) sel.value = 'filter:all';
  renderSkillsList(m);
}

function renderSkillsList(m) {
  const container = m.el('skills-list');
  if (!container) return;
  _writeShownCount(m);
  // Re-render rebuilds the cards (none expanded), so clear the expand flag
  // on the admin-card or it would keep the toolbar hidden with nothing open.
  container.closest('.admin-card')?.classList.remove('skills-has-expanded');

  const sorted = _getFilteredSkills(m);
  // Built-in capabilities show as their own section: the agent's native tools,
  // with the instruction block each one is given and an editor for it.
  //
  // `P2-21`. The flag was a literal `false` over a list nothing populated, so
  // it is now the list itself. That keeps the two halves of this row from ever
  // coming apart again — an empty list draws no header, whether it is empty
  // because the loader has not run yet, because the person is not an admin and
  // the gated route answered 403, or because a filter excluded the section.
  const builtins = _getFilteredBuiltins(m);
  const showBuiltin = builtins.length > 0;

  if (!sorted.length && !showBuiltin) {
    const selectBtn = m.el('skills-select-btn');
    if (selectBtn) selectBtn.disabled = true;
    if (m.selectMode) _exitSelectMode(m);
    // `BRAIN-U-5` (P23-02). A filter that hides everything says so, with the
    // way out beside it; it used to say "No skills yet" over a full library.
    const clear = loaded && _filtering(m)
      ? ' <button type="button" class="memory-toolbar-btn" data-skills-clear-filter>Clear</button>' : '';
    container.innerHTML = `<div style="text-align:center;opacity:0.4;padding:24px 0;font-size:11px;">${loaded ? esc(_emptyListText(m)) : 'Loading…'}${clear}</div>`;
    return;
  }

  const selectBtn = m.el('skills-select-btn');
  if (selectBtn) selectBtn.disabled = false;

  // Library-style cards: a compact bar that expands in-place to show the
  // SKILL.md, with a footer (Delete left; Edit / Run / Approve right).
  // Reuses the proven .doclib-card / .doclib-card-preview /
  // .doclib-card-expanded-actions markup so the desktop+mobile expand +
  // footer behaviour matches the document/chat library exactly.
  //
  // #skills-list itself becomes the .doclib-grid (rather than a nested
  // grid) so the global "hide non-grid children when a card is expanded"
  // rule (.admin-card:has(.doclib-card-expanded) > *:not(.doclib-grid))
  // doesn't hide the list container along with everything else.
  container.classList.add('doclib-grid');
  const cards = [];
  const dupeMeta = _duplicateMeta(sorted);

  for (const sk of sorted) {
    const name = sk.name || sk.id;
    const dm = dupeMeta.get(name);
    if (dm) {
      sk._duplicateGroup = dm.group;
      sk._duplicateKeep = dm.keep;
      sk._duplicateKeepName = dm.keepName;
      sk._duplicateNames = dm.names;
    } else {
      delete sk._duplicateGroup;
      delete sk._duplicateKeep;
      delete sk._duplicateKeepName;
      delete sk._duplicateNames;
    }
    const conf = Math.round((sk.confidence || 0) * 100);
    const uses = sk.uses || 0;
    const isPublished = (sk.status === 'published');
    const confColor = _confColor(conf);

    const card = document.createElement('div');
    card.className = 'doclib-card skill-card';
    card.dataset.skillName = name;
    card.dataset.skillStatus = sk.status || 'draft';

    const checked = m.selected.has(name) ? 'checked' : '';
    const cbHtml = m.selectMode
      ? `<input type="checkbox" class="memory-select-cb skill-select-cb" data-name="${esc(name)}" ${checked} style="margin-right:6px;flex-shrink:0;cursor:pointer;" />`
      : '';

    // Collapsed header bar: dot · name (wraps) · [pills (right) · stats · menu].
    const header = document.createElement('div');
    header.className = 'doclib-card-header skill-card-header';
    header.innerHTML = `
      ${cbHtml}
      ${_auditDot(sk)}
      <div class="skill-card-textcol">
        <button type="button" class="skill-card-toggle" aria-expanded="false"><code class="skill-card-name">${esc(name)}</code></button>
        ${sk.description ? `<div class="skill-card-desc">${esc(sk.description)}</div>` : ''}
      </div>
      <div class="skill-card-right">
        ${_statusPill(sk)}
        ${_offPill(sk)}
        ${_sourcePill(sk)}
        ${_auditModelPills(sk)}
        ${_necessityPill(sk)}
        ${_duplicatePriorityPill(sk)}
        <span class="skill-stats">${_auditMarks(sk)}<span class="skill-conf" style="color:${confColor};">${conf}%</span> · used ${uses}×</span>
        <button type="button" class="skill-chevron-up skill-back-to-list" aria-label="Back to the list">← Skills</button>
        <span class="skill-chevron-up" title="Collapse">${chevronIcon({ direction: 'up', size: 14 })}</span>
        <button class="skill-kebab-btn" title="Actions" aria-label="Actions"><svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="12" cy="19" r="1.6"/></svg></button>
      </div>
    `;
    card.appendChild(header);

    // Kebab dropdown (collapsed-bar quick actions: same set + icons as the
    // expanded footer). Clicking the kebab opens it; it doesn't expand.
    header.querySelector('.skill-kebab-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      _openSkillMenu(m, e.currentTarget, card, sk, name, isPublished);
    });

    // Preview (hidden until expanded) — SKILL.md goes here + footer.
    const preview = document.createElement('div');
    preview.className = 'doclib-card-preview skill-card-preview';
    const pre = document.createElement('pre');
    pre.className = 'skill-md-pre';
    pre.textContent = '';  // filled on expand
    preview.appendChild(pre);

    // Footer: Approve/Unpublish on the left, destructive delete on the right.
    const actions = document.createElement('div');
    actions.className = 'doclib-card-expanded-actions';

    const delBtn = document.createElement('button');
    delBtn.className = 'doclib-card-text-btn doclib-card-action-btn doclib-card-text-btn-danger';
    delBtn.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>Delete';
    delBtn.addEventListener('click', (e) => { e.stopPropagation(); _deleteSkill(name, card); });

    const editBtn = document.createElement('button');
    editBtn.className = 'doclib-card-text-btn doclib-card-action-btn';
    editBtn.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>Edit';
    editBtn.addEventListener('click', (e) => { e.stopPropagation(); _toggleSkillEdit(card, name); });

    const pubBtn = document.createElement('button');
    pubBtn.className = 'doclib-card-text-btn doclib-card-action-btn';
    if (isPublished) {
      pubBtn.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M5 12l5 5L20 7"/></svg>Unpublish';
      pubBtn.addEventListener('click', (e) => { e.stopPropagation(); _setSkillStatus(name, 'draft'); });
    } else {
      pubBtn.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>Publish';
      pubBtn.style.color = 'var(--color-success, #4caf50)';
      pubBtn.addEventListener('click', (e) => { e.stopPropagation(); _setSkillStatus(name, 'published'); });
    }

    // Test/audit this one skill — same action that's in the kebab, surfaced in
    // the footer too so it's not buried under the "⋯" menu.
    const testBtn = document.createElement('button');
    testBtn.className = 'doclib-card-text-btn doclib-card-action-btn';
    testBtn.innerHTML = _svg(_ICON.test, { size: 11 }) + 'Test';
    testBtn.title = 'Test this skill — run it + AI judge';
    testBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      // Immediate visual feedback: previously the click looked like nothing
      // happened because _testSkill awaits a status fetch before overwriting
      // the preview — so users would tap a second time. Mark the button as
      // pending right away so the first tap is obviously registered.
      if (testBtn.dataset.busy === '1') return;  // also dedupe rapid double-tap
      testBtn.dataset.busy = '1';
      testBtn.disabled = true;
      const _origHTML = testBtn.innerHTML;
      testBtn.innerHTML = _svg(_ICON.test, { size: 11 }) + 'Starting…';
      Promise.resolve(_testSkill(card, name)).finally(() => {
        // The preview gets overwritten by _testSkill, which removes the
        // testBtn from the DOM. The cleanup below only matters if the
        // button still exists (e.g. _testSkill bailed early).
        if (document.body.contains(testBtn)) {
          testBtn.disabled = false;
          testBtn.dataset.busy = '';
          testBtn.innerHTML = _origHTML;
        }
      });
    });

    const rightGroup = document.createElement('div');
    rightGroup.className = 'doclib-action-group';
    const btnRow = document.createElement('div');
    btnRow.className = 'doclib-action-btn-row';
    btnRow.appendChild(testBtn);
    btnRow.appendChild(editBtn);
    btnRow.appendChild(delBtn);
    rightGroup.appendChild(btnRow);

    actions.appendChild(pubBtn);
    actions.appendChild(rightGroup);
    preview.appendChild(actions);
    card.appendChild(preview);

    // `BRAIN-U-12` (P23-02). An open card hides the toolbar and every other
    // card (Fork and Import land here), and the way back was an unlabelled ˄.
    // Not while editing: as for the card itself (#4002), Save or Cancel leave
    // the editor, so an edit is never dropped by a way out (the CSS hides it).
    header.querySelector('.skill-back-to-list')?.addEventListener('click', (e) => {
      e.stopPropagation();
      if (card.querySelector('.skill-md-editor')) return;
      if (card.classList.contains('doclib-card-expanded')) _expandSkillCard(card, name);
    });
    // Click to expand/collapse (unless in select mode → toggle checkbox).
    card.addEventListener('click', (e) => {
      if (card._suppressNextClick) { card._suppressNextClick = false; return; }
      // `P10-06`: not the name button — pressing it is a click on the card.
      if (e.target.closest(_CARD_OWN)) return;
      // While editing, a click on the card body (outside the textarea) must
      // NOT collapse the card — that silently discards unsaved edits. Only
      // Save/Cancel exit edit mode.
      if (card.querySelector('.skill-md-editor')) return;
      if (m.selectMode) {
        const cb = card.querySelector('.skill-select-cb');
        if (cb) { cb.checked = !cb.checked; cb.dispatchEvent(new Event('change')); }
        return;
      }
      _expandSkillCard(card, name);
    });

    // Long-press anywhere on the card opens the kebab dropdown — mirrors the
    // documents library + brain memory pattern. Skip when touch starts on a
    // button/input so per-control handlers keep working.
    {
      const kebab = header.querySelector('.skill-kebab-btn');
      let hold = null;
      let start = null;
      const _lpCancel = () => { if (hold) { clearTimeout(hold); hold = null; } start = null; };
      card.addEventListener('pointerdown', (e) => {
        if (e.target.closest('.skill-kebab-btn, .skill-select-cb') || e.target.closest(_CARD_OWN)) return;
        start = { x: e.clientX, y: e.clientY };
        hold = setTimeout(() => {
          hold = null;
          card._suppressNextClick = true;
          setTimeout(() => { card._suppressNextClick = false; }, 400);
          if (navigator.vibrate) try { navigator.vibrate(15); } catch {}
          if (kebab) kebab.click();
        }, 500);
      });
      card.addEventListener('pointermove', (e) => {
        if (!start) return;
        if (Math.hypot(e.clientX - start.x, e.clientY - start.y) > 10) _lpCancel();
      });
      card.addEventListener('pointerup', _lpCancel);
      card.addEventListener('pointercancel', _lpCancel);
    }

    cards.push(card);
  }
  container.innerHTML = '';

  // Two collapsible sections — "Your skills" and "Built-in". Headers and
  // cards are all DIRECT children of the grid (cards tagged with
  // data-skill-section) so the global expand rule — which hides sibling
  // .doclib-card elements by direct-child selector — keeps working.
  // Collapse just toggles display on the tagged cards.
  const _mkSectionHeader = (sectionId, title, count) => _skillsSectionHeader(container, sectionId, title, count);

  // The SKILL.md section — show the header only when there's also a
  // built-in section to distinguish from (otherwise it's just the list).
  //
  // It said "Your skills" until 2026-09-18, and this header had never been
  // drawn, because the built-in flag it is conditional on was a literal
  // `false`. `P2-21` turning that flag on would have made the label appear for
  // the first time over a list that is mostly not the person's: `/api/skills`
  // folds in the 286 read-only bundled library entries (`source: "bundled"`,
  // `owner: null`), and `B590` is open because none of them can be opened.
  // "Skills" is what this section actually holds — SKILL.md files, whoever
  // wrote them — beside "Built-in capabilities", which holds native tools.
  //
  // `B-NEW-5` (round 2). No count on this head: the library column's row
  // counts the scope ("All skills 8") and the header writes "5 of 8" when a
  // search or filter narrows it, so "SKILLS 8" said the number a second time
  // (measured on `a936b5c`). The built-in head keeps its count — nothing else
  // counts the built-in capabilities, and that section ships folded.
  if (cards.length) {
    if (showBuiltin) container.appendChild(_mkSectionHeader('user', 'Skills', null));
    cards.forEach(c => { c.dataset.skillSection = 'user'; container.appendChild(c); });
  }

  // Built-in capabilities — read-only cards (the agent's native tools).
  if (showBuiltin) {
    const builtinCards = _buildBuiltinCards(builtins);
    container.appendChild(_mkSectionHeader('builtin', 'Built-in capabilities', builtinCards.length));
    builtinCards.forEach(c => { c.dataset.skillSection = 'builtin'; container.appendChild(c); });
  }

  _applySectionCollapse(container);

  // Domino-in cascade when the Skills tab is (re)opened — same sleek
  // staggered entrance the document/chat library uses (.doclib-just-opened
  // → section-domino-in on each .doclib-card child). Only consumes the flag
  // set on tab-open, so search/sort/edit re-renders stay instant.
  if (m.cascadeNext && cards.length) {
    m.cascadeNext = false;
    _playSkillsCascade(container);
  }

  // Select-mode checkbox wiring (card-body click is handled in the card's
  // own click listener above).
  if (m.selectMode) {
    container.querySelectorAll('.skill-select-cb').forEach(cb => {
      cb.addEventListener('change', () => {
        const name = cb.dataset.name;
        if (cb.checked) m.selected.add(name); else m.selected.delete(name);
        const all = m.el('skills-select-all');
        if (all) {
          const visible = _getFilteredSkills(m).map(s => s.name || s.id);
          all.checked = visible.length > 0 && visible.every(n => m.selected.has(n));
        }
        _updateBulkBar(m);
      });
    });
  }

  // Do not eager-load every visible SKILL.md. On large skill libraries this
  // creates dozens of simultaneous /api/skills/<name>/markdown requests during
  // app startup and can peg uvicorn. Markdown is fetched lazily when a card is
  // expanded.
}

// ---- Card expand / edit / actions ----

// Collapse an expanded skill card: drop the class AND clear the inline
// heights skills.js pinned on the card/preview/<pre> (otherwise a collapsed
// card keeps its full expanded height) and detach its resize listener.
// One of the two collapsible section headers in the Skills list ("Skills" /
// "Built-in capabilities"). Lifted out of `renderSkillsList` by `P10-06` so a
// test can build one and press it.
function _skillsSectionHeader(container, sectionId, title, count) {
  const collapsed = _collapsedSections.has(sectionId);
  // `P10-06`. A `<button>`, not a `<div>`: the Built-in section ships
  // collapsed, and as a click-only `<div>` its header was the only way in, so
  // every built-in capability — sixty on the install measured, each with its
  // Edit and Revert — had no keyboard path at all (2026-09-27, when this list
  // lived in the Brain: Tab went from the search box straight out of the
  // window). The classes did not move, the tag did (`P10-02`'s shape);
  // `aria-expanded` follows `_applySectionCollapse`.
  const hdr = document.createElement('button');
  hdr.type = 'button';
  hdr.className = 'skills-section-label skills-section-header' + (collapsed ? ' collapsed' : '');
  hdr.setAttribute('aria-expanded', String(!collapsed));
  hdr.dataset.section = sectionId;
  // `B-NEW-5`: a section with no count of its own (`count` null) says only
  // its name — see the "Skills" call in `renderSkillsList`.
  hdr.innerHTML =
    chevronIcon({ className: 'skills-section-chevron' }) +
    `<span>${esc(title)}</span>` +
    (count == null ? '' : `<span class="skills-section-count">${count}</span>`);
  hdr.addEventListener('click', () => {
    if (_collapsedSections.has(sectionId)) _collapsedSections.delete(sectionId);
    else _collapsedSections.add(sectionId);
    _saveCollapsedSections();
    _applySectionCollapse(container);
  });
  return hdr;
}

function _collapseSkillCardEl(c) {
  c.classList.remove('doclib-card-expanded', 'skill-expand-instant');
  _syncCardToggle(c);
  c.style.removeProperty('height');
  const pv = c.querySelector('.doclib-card-preview');
  const pr = c.querySelector('.skill-md-pre') || c.querySelector('.skill-md-editor');
  if (pv) { pv.style.removeProperty('height'); pv.style.removeProperty('flex'); pv.style.removeProperty('max-height'); }
  if (pr) { pr.style.removeProperty('height'); pr.style.removeProperty('flex'); }
  if (c._fillH) window.removeEventListener('resize', c._fillH);
}

async function _expandSkillCard(card, name) {
  const grid = card.closest('.doclib-grid');
  const adminCard = card.closest('.admin-card');
  // Toggle collapse if already open.
  if (card.classList.contains('doclib-card-expanded')) {
    _collapseSkillCardEl(card);
    if (adminCard) adminCard.classList.remove('skills-has-expanded');
    return;
  }
  // Were we already showing another expanded card? If so this is a SWITCH,
  // not a fresh open — skip the fade-in. The fade reveals the previous card
  // collapsing behind the new (semi-transparent) one, which read as a jump.
  const switching = !!(grid && grid.querySelector('.doclib-card-expanded'));
  // Collapse any other expanded sibling (full cleanup, not just the class).
  if (grid) grid.querySelectorAll('.doclib-card-expanded').forEach(_collapseSkillCardEl);
  card.classList.add('doclib-card-expanded');
  _syncCardToggle(card);
  if (switching) card.classList.add('skill-expand-instant');
  // Explicit class on the admin-card so CSS doesn't depend on :has()
  // (Firefox mobile builds without :has left the expand at ~50%).
  if (adminCard) adminCard.classList.add('skills-has-expanded');
  if (grid) grid.scrollTop = 0;

  // Firefox doesn't treat the absolutely-positioned card's stretched height
  // (inset:0) or height:100% as DEFINITE, so grid/flex children won't fill.
  // Pin an explicit px height = the card's already-rendered height. A px
  // value is unambiguously definite, so the preview + <pre> finally fill.
  card._fillH = () => {
    // Reset any prior inline heights so we measure the natural box first
    // (and so switching desktop<->mobile never leaves stale px values).
    card.style.removeProperty('height');
    const preview = card.querySelector('.doclib-card-preview');
    const header = card.querySelector('.skill-card-header');
    const pre = card.querySelector('.skill-md-pre') || card.querySelector('.skill-md-editor');
    if (preview) { preview.style.removeProperty('height'); preview.style.removeProperty('flex'); preview.style.removeProperty('max-height'); }
    if (pre) { pre.style.removeProperty('height'); pre.style.removeProperty('flex'); }

    // The px-pinning is ONLY for the mobile layout (position:absolute fill,
    // where Firefox won't propagate a definite height). On desktop the card
    // expands via normal flex/flow — pinning measured heights there just
    // under-sizes it. So bail on desktop and let the CSS handle it.
    if (!window.matchMedia('(max-width: 768px)').matches) return;

    const cardH = card.getBoundingClientRect().height;
    if (cardH <= 0) return;
    card.style.setProperty('height', cardH + 'px', 'important');
    if (!preview) return;

    const px = (el, prop) => parseFloat(getComputedStyle(el)[prop]) || 0;
    const headerH = header ? header.getBoundingClientRect().height : 0;
    const cardPad = px(card, 'paddingTop') + px(card, 'paddingBottom');
    const previewH = Math.max(0, cardH - headerH - cardPad);
    // Force the preview to an explicit height (flex:none so nothing fights it).
    // A max-height (~335px, resolved from a % rule) was capping it — clear it.
    preview.style.setProperty('flex', '0 0 auto', 'important');
    preview.style.setProperty('max-height', 'none', 'important');
    preview.style.setProperty('height', previewH + 'px', 'important');

    if (pre) {
      // Pre = preview height minus its non-pre siblings (footer, warn banner).
      const prevPad = px(preview, 'paddingTop') + px(preview, 'paddingBottom');
      let siblings = 0;
      for (const child of preview.children) {
        if (child !== pre) siblings += child.getBoundingClientRect().height;
      }
      const preH = Math.max(0, previewH - prevPad - siblings);
      pre.style.setProperty('height', preH + 'px', 'important');
      pre.style.setProperty('flex', '0 0 auto', 'important');
    }
  };
  // Size SYNCHRONOUSLY (not in rAF) so the pinned heights are in place before
  // the browser's first paint of the expanded card. Running it a frame later
  // let the first frame paint at content-height, then snap — the "explosion"
  // that showed on the first expand (when the SKILL.md was still loading).
  card._fillH();
  window.addEventListener('resize', card._fillH);

  const pre = card.querySelector('.skill-md-pre');
  if (pre && !card._mdLoaded) {
    // Use the cache when available (the bg preload usually has it already),
    // so the content is in place synchronously — no async settle/jump.
    if (_mdCache.has(name)) {
      const md = _mdCache.get(name);
      pre.textContent = md || '(empty)';
      card._mdLoaded = true;
      card._md = md || '';
    } else {
      pre.textContent = 'Loading…';
      try {
        const md = await _fetchSkillMarkdown(name);
        pre.textContent = md || '(empty)';
        card._mdLoaded = true;
        card._md = md;
      } catch (e) {
        pre.textContent = 'Failed to load SKILL.md';
      }
    }
  }
}

// Swap the read-only <pre> for an editable <textarea> (and back). The
// Edit button toggles; a Save button commits via the markdown endpoint.
function _toggleSkillEdit(card, name) {
  const preview = card.querySelector('.skill-card-preview');
  if (!preview) return;
  const existing = preview.querySelector('.skill-md-editor');
  if (existing) {
    // Already editing — treat Edit as Save.
    _saveSkillEdit(card, name);
    return;
  }
  const pre = preview.querySelector('.skill-md-pre');
  const ta = document.createElement('textarea');
  ta.className = 'skill-md-editor';
  ta.spellcheck = false;
  ta.value = (card._md != null ? card._md : (pre ? pre.textContent : '')) || '';
  ta.addEventListener('click', (e) => e.stopPropagation());
  if (pre) pre.style.display = 'none';
  preview.insertBefore(ta, preview.querySelector('.doclib-card-expanded-actions'));
  ta.focus();
  // Flip the Edit button label to "Save".
  const editBtn = [...preview.querySelectorAll('.doclib-card-action-btn')].find(b => /Edit|Save/.test(b.textContent));
  if (editBtn) editBtn.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>Save';
}

async function _saveSkillEdit(card, name) {
  const preview = card.querySelector('.skill-card-preview');
  const ta = preview?.querySelector('.skill-md-editor');
  if (!ta) return;
  // `P22-21`. *See what changed* is pressed in a toast, outside both mounts;
  // it means the card in the place this save was made.
  _lastMount = _mountOf(card);
  try {
    const res = await fetch(`${API}/api/skills/${encodeURIComponent(name)}/markdown`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ markdown: ta.value }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    // Refresh the cached markdown so the preload/expand show the new text.
    _mdCache.set(name, ta.value);
    // `P8-09` / `P8-00`. The moment a person has just changed a skill is the
    // only moment "what did that change?" is a live question, and it is the
    // moment they are furthest from the card menu. `P8-10` has already kept
    // the copy this save replaced, so the offer is real rather than a promise.
    uiModule.showToast('Saved', {
      action: 'See what changed',
      actionHint: 'runs the old and new text against one task',
      onAction: () => _compareSkill(null, name),
      duration: 7000,
    });
    await loadSkills();  // re-render (frontmatter changes like name/status may have changed)
  } catch (e) {
    uiModule.showError('Save failed: ' + e.message);
  }
}

async function _deleteSkill(name, card = null) {
  if (!(await uiModule.styledConfirm(`Delete skill "${name}"? This removes the SKILL.md.`, { confirmText: 'Delete', danger: true }))) return;
  // Locate the card if the caller didn't hand one over, so we can collapse it
  // away gracefully (same fade+shrink as the document library) instead of
  // re-rendering the whole list.
  if (!card) {
    card = [...document.querySelectorAll('.skill-card')]
      .find(c => { const n = c.querySelector('.skill-card-name'); return n && n.textContent === name; }) || null;
  }
  try {
    await fetch(`${API}/api/skills/${encodeURIComponent(name)}`, { method: 'DELETE' });
    _mdCache.delete(name);
    if (card) {
      if (card._testPoll) { clearInterval(card._testPoll); card._testPoll = null; }
      _setCardRunning(card, false);
      card.classList.add('doclib-card-deleting');
      card.addEventListener('transitionend', () => card.remove(), { once: true });
      setTimeout(() => { if (card.parentElement) card.remove(); }, 400);
    }
    await loadSkills();
    uiModule.showToast('Skill deleted');
  } catch (e) { uiModule.showError('Delete failed: ' + e.message); }
}

async function _setSkillStatus(name, status) {
  try {
    await fetch(`${API}/api/skills/${encodeURIComponent(name)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    });
    await loadSkills();
    uiModule.showToast(status === 'published' ? `Published ${name}` : `${name} is a draft again`);
  } catch (e) { uiModule.showError('Update failed: ' + e.message); }
}

// ---- Test a skill (sandbox agent run + AI eval) ----

async function _fetchTestStatus(name) {
  try {
    const r = await fetch(`${API}/api/skills/${encodeURIComponent(name)}/test-status`);
    return r.ok ? await r.json() : { status: 'none' };
  } catch { return { status: 'none' }; }
}

/** The gate card for one paused skill-test run.
 *
 * Lifted out of `_renderTestLog` when `P8-09` gave a comparison two runs that
 * can each stop at a gate: the second copy would have been a second set of
 * buttons that could drift from the first (`Law 14`). Nothing about the gate
 * moved — same endpoint, same sealed id, same two decisions, same "Allow once"
 * wording, and the server still re-checks owner and match before consuming.
 */
function _skillApprovalBox(approval, name, { onAnswered, onError } = {}) {
  // `P22-17` (wf-canvas). The card itself is `approvalBox.js`'s, shared with
  // a workflow step's question; what the skill test sends is unchanged: its
  // own route, the sealed id, and `approve` — the chat-scoped yes this run has
  // always taken (`Law 1`). A workflow step sends `approve_task` instead.
  return approvalBox(approval, {
    allowValue: 'approve',
    allowLabel: 'Allow once',
    onDecide: async (decision) => {
      const response = await fetch(
        `${API}/api/skills/${encodeURIComponent(name)}/test-approval`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ approval_id: approval.approval_id, decision }),
        },
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      if (onAnswered) await onAnswered(decision);
    },
    onError: (message) => { if (onError) onError(`Approval failed: ${message}`); },
  });
}

function _renderTestLog(logEl, verdictEl, job, card, name) {
  if (!logEl) return;
  logEl.innerHTML = '';
  const add = (txt, cls) => { const d = document.createElement('div'); if (cls) d.className = cls; d.textContent = txt; logEl.appendChild(d); };
  for (const ev of (job.log || [])) {
    if (ev.type === 'skill_test_start') { add('Task: ' + ev.task, 'skill-test-task'); add('Model: ' + ev.model, 'skill-test-meta'); }
    else if (ev.type === 'agent_step') add('— round ' + ev.round + ' —', 'skill-test-round');
    else if (ev.type === 'tool_start') add('▸ ' + ev.tool + '  ' + String(ev.command || '').slice(0, 200), 'skill-test-tool');
    else if (ev.type === 'tool_output') add(String(ev.output || '').slice(0, 500), 'skill-test-out');
    else if (ev.type === 'approval_granted' || ev.type === 'approval_denied') add(ev.text || '', 'skill-test-meta');
    else if (ev.type === 'say') add(ev.text || '', 'skill-test-say');
    // `BRAIN-M-13` (P23-02): "Evaluating run…" stayed above the verdict it
    // led to, 30 s after it came; once the run is done it is not drawn.
    else if (ev.type === 'evaluating') { if (job.status !== 'done') add('Evaluating run…', 'skill-test-meta'); }
    else if (ev.type === 'error') add('Error: ' + (ev.error || 'run failed'), 'skill-test-err');
  }
  if (job.status === 'awaiting_approval' && job.approval) {
    logEl.appendChild(_skillApprovalBox(job.approval, name, {
      onAnswered: () => _testSkill(card, name, false),
      onError: (msg) => add(msg, 'skill-test-err'),
    }));
  }
  if (job.status === 'running') add('…running (you can close this — it keeps going)', 'skill-test-meta');
  logEl.scrollTop = logEl.scrollHeight;
  if (job.status === 'done' && job.verdict) _renderTestVerdict(verdictEl, job.verdict, card, name);
  else if (verdictEl) verdictEl.innerHTML = '';
}

// `P8-08`. `POST /api/skills/{name}/test` has read `body.task` since it was
// written (routes/skills_routes.py:1499) and the UI had never sent one, so
// every test in the product's history ran the server's invented fallback and
// nothing said so. One textarea closes that, and it also makes the panel
// honest about the two things a first-time user cannot otherwise know: that
// leaving it blank is a real choice with a stated consequence, and that the
// run can stop and ask (`P8-18`).
async function _testSkill(card, name, force = false) {
  if (!card.classList.contains('doclib-card-expanded')) await _expandSkillCard(card, name);
  const preview = card.querySelector('.skill-card-preview');
  if (!preview) return;
  preview.innerHTML =
    '<div class="skill-test">' +
      '<div class="skill-test-ask hidden">' +
        '<label class="skill-test-ask-label">What should it try?' +
          '<textarea class="skill-test-task-input" rows="2" spellcheck="false" placeholder="Blank: the model invents an example."></textarea>' +
        '</label>' +
        '<div class="skill-test-gate-note">' + SKILL_GATE_NOTE + '</div>' +
        '<div class="skill-test-ask-actions">' +
          '<button type="button" class="doclib-card-text-btn doclib-card-action-btn skill-test-compare">Compare with previous</button>' +
          '<button type="button" class="doclib-card-text-btn doclib-card-action-btn skill-test-run">Run test</button>' +
        '</div>' +
      '</div>' +
      '<div class="skill-test-log"></div>' +
      '<div class="skill-test-verdict"></div></div>';
  const askEl = preview.querySelector('.skill-test-ask');
  const taskEl = preview.querySelector('.skill-test-task-input');
  const runBtn = preview.querySelector('.skill-test-run');
  const logEl = preview.querySelector('.skill-test-log');
  const verdictEl = preview.querySelector('.skill-test-verdict');
  if (card._testPoll) { clearInterval(card._testPoll); card._testPoll = null; }

  // Attach to an existing job unless forcing a fresh run.
  let job = force ? { status: 'none' } : await _fetchTestStatus(name);

  if (job.status === 'none') {
    // Ask first. Retry pre-fills with whatever the previous run used, which the
    // status payload already carries, so re-running the same task is one click
    // and changing it is one edit.
    if (taskEl && force) {
      const previous = await _fetchTestStatus(name);
      if (previous && typeof previous.task === 'string') taskEl.value = previous.task;
    }
    askEl?.classList.remove('hidden');
    logEl.innerHTML = '<div class="skill-test-meta">Not started.</div>';
    taskEl?.addEventListener('click', (e) => e.stopPropagation());
    runBtn?.addEventListener('click', async (e) => {
      e.stopPropagation();
      runBtn.disabled = true;
      askEl?.classList.add('hidden');
      await _startSkillTest(card, name, (taskEl && taskEl.value.trim()) || '', logEl, verdictEl);
    });
    // `P8-09`. The same task box, the other question: not "does it work" but
    // "did my edit change what it does". Carrying the typed task across is the
    // whole point — a comparison against a different task compares nothing.
    preview.querySelector('.skill-test-compare')?.addEventListener('click', async (e) => {
      e.stopPropagation();
      await _compareSkill(card, name, (taskEl && taskEl.value.trim()) || '');
    });
    return;
  }

  _renderTestLog(logEl, verdictEl, job, card, name);
  _setCardRunning(card, job.status === 'running');

  _pollSkillTest(card, name, logEl, verdictEl, job);
}

/** POST the run, then hand over to the poller. Split out of `_testSkill` so the
 *  "ask for a task" step and the "watch a run" step are not the same function.
 */
async function _startSkillTest(card, name, task, logEl, verdictEl) {
  logEl.innerHTML = '<div class="skill-test-meta">Starting test…</div>';
  let model = '', endpoint_url = '';
  try {
    const sm = window.sessionModule;
    model = (sm && sm.getCurrentModel && sm.getCurrentModel()) || '';
    endpoint_url = (sm && sm.getCurrentEndpointUrl && sm.getCurrentEndpointUrl()) || '';
  } catch (_) {}
  try {
    const res = await fetch(`${API}/api/skills/${encodeURIComponent(name)}/test`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task, model, endpoint_url }),
    });
    if (!res.ok) { logEl.innerHTML = '<div class="skill-test-err">Test failed: HTTP ' + res.status + '</div>'; return; }
  } catch (e) { logEl.innerHTML = '<div class="skill-test-err">Test failed: ' + (e.message || e) + '</div>'; return; }
  const job = await _fetchTestStatus(name);
  _renderTestLog(logEl, verdictEl, job, card, name);
  _setCardRunning(card, job.status === 'running');
  _pollSkillTest(card, name, logEl, verdictEl, job);
}

function _pollSkillTest(card, name, logEl, verdictEl, job) {
  if (job.status === 'running') {
    card._testPoll = setInterval(async () => {
      // Keep polling even if the card is collapsed (the test runs server-side);
      // only stop once the card itself is gone from the DOM.
      if (!document.body.contains(card)) { clearInterval(card._testPoll); card._testPoll = null; _setCardRunning(card, false); return; }
      const s = await _fetchTestStatus(name);
      // Update the expanded log only while it's still on screen.
      if (document.body.contains(logEl)) _renderTestLog(logEl, verdictEl, s, card, name);
      if (s.status !== 'running') {
        clearInterval(card._testPoll); card._testPoll = null;
        _setCardRunning(card, false);
        // If the log isn't visible (card was collapsed), still update the
        // header dot/% so the result shows on the folded card.
        if (!document.body.contains(logEl) && s.verdict && s.verdict.verdict) {
          _applyVerdictToHeader(card, s.verdict.verdict);
        }
      }
    }, 1300);
  }
}

// Show/hide the app-wide whirlpool spinner next to the skill name while a test
// is in flight. Works on the collapsed header too, since we inject a real DOM
// element rather than a CSS pseudo on a class.
function _setCardRunning(card, on) {
  if (!card) return;
  card.classList.toggle('skill-test-running', !!on);
  if (on) {
    if (card._testSpinner) return;
    const nameEl = card.querySelector('.skill-card-name');
    if (!nameEl) return;
    const wp = spinnerModule.createWhirlpool(12);
    wp.element.style.cssText = 'display:inline-flex;width:12px;height:12px;margin:0 0 0 7px;vertical-align:middle;flex-shrink:0;';
    // Append INSIDE the <code> name (inline-flow), not after it. The textcol
    // is a flex column, so a sibling-after lands on its own line — putting
    // the spinner inside the inline code keeps it on the title row.
    nameEl.appendChild(wp.element);
    card._testSpinner = wp;
  } else if (card._testSpinner) {
    try { card._testSpinner.destroy(); } catch (_) {}
    if (card._testSpinner.element && card._testSpinner.element.parentElement) {
      card._testSpinner.element.remove();
    }
    card._testSpinner = null;
  }
}


// ── `P8-09` · before/after behaviour diff ────────────────────────────────────
//
// The row: *"the runner is parameterised on arbitrary markdown and an arbitrary
// task and never reads from disk — call it twice with old and new against the
// same task."* Two things had to be true on the server first and neither was:
// `_run_skill_test_once` denied the pending approval on its way out (`B592`),
// and the endpoint kept one job slot per skill so the second run destroyed the
// first result (`B879`). Both are fixed in `routes/skills_routes.py`; this is
// the half a person actually touches.

/** The comparison in sentences, from the served diff. Pure — no DOM, no fetch,
 *  no module state — so it is driven directly under node and the words in the
 *  panel are the words under test (`Law 20`).
 *
 *  The order matters: the honesty line comes FIRST when the two texts are the
 *  same, because everything under it is then sampling noise and a reader who
 *  meets that fact last has already believed the rest.
 */
function _skillDiffLines(diff) {
  const d = diff || {};
  const out = [];
  if (d.same_text) {
    out.push('These two runs used the SAME skill text. Anything different below is '
      + 'the model answering twice, not your edit.');
  }
  if (!d.both_finished) {
    const waiting = [];
    if (d.before_status !== 'done') waiting.push(`the ${d.before_source || 'earlier copy'}`);
    if (d.after_status !== 'done') waiting.push(`the ${d.after_source || 'current version'}`);
    out.push(`Not finished yet: ${waiting.join(' and ')} ${waiting.length > 1 ? 'have' : 'has'} not produced a verdict.`);
    return out;
  }
  if (d.verdict_changed) {
    out.push(`The verdict changed: ${d.before_verdict} before your edit, ${d.after_verdict} after.`);
  } else if (d.before_verdict) {
    out.push(`The verdict did not change — ${d.before_verdict} both times.`);
  }
  if (d.tools_changed) {
    const bits = [];
    if ((d.tools_added || []).length) bits.push(`now uses ${d.tools_added.join(', ')}`);
    if ((d.tools_removed || []).length) bits.push(`no longer uses ${d.tools_removed.join(', ')}`);
    if (!bits.length) bits.push('used the same tools in a different order or a different number of times');
    out.push(`Different work: it ${bits.join('; ')}.`);
  } else if ((d.after_tools || []).length) {
    out.push(`Same tools both times: ${(d.after_tools || []).join(', ')}.`);
  } else {
    out.push('Neither run used a tool.');
  }
  if (d.before_rounds !== d.after_rounds) {
    out.push(`It took ${d.after_rounds} round(s) after the edit and ${d.before_rounds} before.`);
  }
  for (const gone of (d.issues_resolved || [])) out.push(`Fixed: ${gone}`);
  for (const added of (d.issues_introduced || [])) out.push(`New problem: ${added}`);
  if (!d.same_text) {
    out.push('The run is sampled, so wording differs between runs on its own. '
      + 'The verdict, the tools and the round count are what to read.');
  }
  return out;
}

/** One half of the comparison: heading, log, verdict, and its own gate card. */
function _renderDiffHalf(title, source, log, approval, verdict, card, name, refresh) {
  const col = document.createElement('div');
  col.style.cssText = 'display:flex;flex-direction:column;gap:4px;min-width:0;';
  const head = document.createElement('div');
  head.className = 'skill-test-task';
  head.textContent = `${title} — ${source}`;
  col.appendChild(head);
  const logEl = document.createElement('div');
  logEl.className = 'skill-test-log';
  for (const ev of (log || [])) {
    const d = document.createElement('div');
    if (ev.type === 'skill_test_start') { d.className = 'skill-test-meta'; d.textContent = 'Task: ' + (ev.task || ''); }
    else if (ev.type === 'agent_step') { d.className = 'skill-test-round'; d.textContent = '— round ' + ev.round + ' —'; }
    else if (ev.type === 'tool_start') { d.className = 'skill-test-tool'; d.textContent = '▸ ' + ev.tool + '  ' + String(ev.command || '').slice(0, 160); }
    else if (ev.type === 'tool_output') { d.className = 'skill-test-out'; d.textContent = String(ev.output || '').slice(0, 400); }
    else if (ev.type === 'say') { d.className = 'skill-test-say'; d.textContent = ev.text || ''; }
    else if (ev.type === 'error') { d.className = 'skill-test-err'; d.textContent = 'Error: ' + (ev.error || 'run failed'); }
    else { d.className = 'skill-test-meta'; d.textContent = ev.text || ev.type || ''; }
    logEl.appendChild(d);
  }
  col.appendChild(logEl);
  if (approval && approval.approval_id) {
    col.appendChild(_skillApprovalBox(approval, name, {
      onAnswered: refresh,
      onError: (msg) => { const e = document.createElement('div'); e.className = 'skill-test-err'; e.textContent = msg; col.appendChild(e); },
    }));
  }
  const v = document.createElement('div');
  v.className = 'skill-test-meta';
  v.textContent = verdict && verdict.verdict
    ? `${verdict.verdict} — ${verdict.summary || ''}`
    : 'no verdict yet';
  col.appendChild(v);
  return col;
}

/** Draw the whole comparison from one `/test-status` payload. */
function _renderSkillDiff(host, status, card, name, refresh) {
  const diff = status && status.diff;
  host.innerHTML = '';
  if (!diff) {
    const d = document.createElement('div');
    d.className = 'skill-test-meta';
    d.textContent = 'Starting comparison…';
    host.appendChild(d);
    return;
  }
  const head = document.createElement('div');
  head.className = 'skill-test-meta';
  head.textContent = `Same task, same model (${diff.model || ''}): ${diff.task || ''}`;
  host.appendChild(head);
  for (const line of _skillDiffLines(diff)) {
    const d = document.createElement('div');
    d.className = diff.same_text ? 'skill-test-err' : 'skill-test-say';
    d.textContent = line;
    host.appendChild(d);
  }
  const cols = document.createElement('div');
  cols.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:10px;min-width:0;margin-top:6px;';
  cols.appendChild(_renderDiffHalf('Before', diff.before_source, diff.before_log,
    diff.before_approval,
    diff.before_verdict ? { verdict: diff.before_verdict, summary: diff.before_summary } : null,
    card, name, refresh));
  cols.appendChild(_renderDiffHalf('After', diff.after_source, diff.after_log,
    diff.after_approval,
    diff.after_verdict ? { verdict: diff.after_verdict, summary: diff.after_summary } : null,
    card, name, refresh));
  host.appendChild(cols);
}

async function _fetchSkillVersions(name) {
  try {
    const r = await fetch(`${API}/api/skills/${encodeURIComponent(name)}/versions`);
    if (!r.ok) return [];
    const d = await r.json();
    return Array.isArray(d.versions) ? d.versions : [];
  } catch { return []; }
}

/** Ask for a task and an earlier copy, then run both halves and watch them.
 *
 * `P8-00`: what a first-time user does is press **Compare with previous** — in
 * the test panel they are already in, or from the card menu beside Test, or
 * from the Saved toast the moment they finish an edit. What they see is two
 * columns against one task and a sentence saying what changed. If the skill has
 * never been edited there is nothing to compare, and the panel says that in
 * those words instead of offering a button that 400s.
 */
async function _compareSkill(card, name, presetTask = '') {
  if (!card) card = _findSkillCard(name);
  if (!card) return;
  if (!card.classList.contains('doclib-card-expanded')) await _expandSkillCard(card, name);
  const preview = card.querySelector('.skill-card-preview');
  if (!preview) return;
  if (card._testPoll) { clearInterval(card._testPoll); card._testPoll = null; }
  preview.innerHTML = '';

  const wrap = document.createElement('div');
  wrap.className = 'skill-test';
  preview.appendChild(wrap);

  const versions = await _fetchSkillVersions(name);
  if (!versions.length) {
    const d = document.createElement('div');
    d.className = 'skill-test-meta';
    d.textContent = 'There is no earlier copy of this skill yet, so there is nothing to '
      + 'compare it with. Edit and save it once — the copy it replaces is kept '
      + 'automatically, and this button then runs both against the same task.';
    wrap.appendChild(d);
    return;
  }

  const ask = document.createElement('div');
  ask.className = 'skill-test-ask';
  const label = document.createElement('label');
  label.className = 'skill-test-ask-label';
  label.textContent = 'What should both versions try?';
  const ta = document.createElement('textarea');
  ta.className = 'skill-test-task-input';
  ta.rows = 2;
  ta.spellcheck = false;
  ta.placeholder = 'Blank: the model invents an example — both halves get the same one.';
  ta.value = presetTask || '';
  ta.addEventListener('click', (e) => e.stopPropagation());
  label.appendChild(ta);
  ask.appendChild(label);

  const pick = document.createElement('label');
  pick.className = 'skill-test-ask-label';
  pick.textContent = 'Compare against';
  const sel = document.createElement('select');
  sel.className = 'skill-test-version-select';
  for (const v of versions) {
    const o = document.createElement('option');
    o.value = v.id;
    const when = v.saved_at ? new Date(v.saved_at * 1000).toLocaleString() : '';
    o.textContent = `${v.id}${when ? ' — saved ' + when : ''}`;
    sel.appendChild(o);
  }
  sel.addEventListener('click', (e) => e.stopPropagation());
  pick.appendChild(sel);
  ask.appendChild(pick);

  const note = document.createElement('div');
  note.className = 'skill-test-gate-note';
  note.textContent = 'Two runs, one after the other, same task and same model. Either can '
    + 'stop and ask you before anything that writes, runs, sends or deletes — and until you '
    + 'answer, neither run has changed anything.';
  ask.appendChild(note);

  const actions = document.createElement('div');
  actions.className = 'skill-test-ask-actions';
  const go = document.createElement('button');
  go.type = 'button';
  go.className = 'doclib-card-text-btn doclib-card-action-btn skill-diff-run';
  go.textContent = 'Compare';
  actions.appendChild(go);
  ask.appendChild(actions);
  wrap.appendChild(ask);

  const host = document.createElement('div');
  host.className = 'skill-diff';
  wrap.appendChild(host);

  const refresh = async () => {
    const st = await _fetchTestStatus(name);
    _renderSkillDiff(host, st, card, name, refresh);
    _setCardRunning(card, !(st.diff && st.diff.both_finished));
    _pollSkillDiff(card, name, host, st, refresh);
  };

  go.addEventListener('click', async (e) => {
    e.stopPropagation();
    go.disabled = true;
    ask.classList.add('hidden');
    host.innerHTML = '<div class="skill-test-meta">Running the earlier copy first…</div>';
    try {
      const res = await fetch(`${API}/api/skills/${encodeURIComponent(name)}/test-diff`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task: ta.value.trim(), version: sel.value }),
      });
      if (!res.ok) {
        let why = `HTTP ${res.status}`;
        try { const j = await res.json(); if (j && j.detail) why = j.detail; } catch (_) {}
        host.innerHTML = '';
        const d = document.createElement('div');
        d.className = 'skill-test-err';
        d.textContent = why;
        host.appendChild(d);
        return;
      }
    } catch (err) {
      host.innerHTML = '';
      const d = document.createElement('div');
      d.className = 'skill-test-err';
      d.textContent = 'Comparison failed: ' + (err.message || err);
      host.appendChild(d);
      return;
    }
    await refresh();
  });
}

function _pollSkillDiff(card, name, host, status, refresh) {
  const d = status && status.diff;
  const waiting = d && !d.both_finished
    && d.before_status !== 'awaiting_approval'
    && d.after_status !== 'awaiting_approval';
  if (!waiting) { _setCardRunning(card, false); return; }
  if (card._testPoll) { clearInterval(card._testPoll); card._testPoll = null; }
  card._testPoll = setInterval(async () => {
    if (!document.body.contains(card)) { clearInterval(card._testPoll); card._testPoll = null; _setCardRunning(card, false); return; }
    const st = await _fetchTestStatus(name);
    if (document.body.contains(host)) _renderSkillDiff(host, st, card, name, refresh);
    const nd = st && st.diff;
    if (!nd || nd.both_finished || nd.before_status === 'awaiting_approval' || nd.after_status === 'awaiting_approval') {
      clearInterval(card._testPoll); card._testPoll = null;
      _setCardRunning(card, false);
      if (nd && nd.after_verdict) _applyVerdictToHeader(card, nd.after_verdict);
    }
  }, 1300);
}

// Reflect a test/audit verdict on the (possibly collapsed) card header without
// a full reload: the glowing audit dot, the confidence %, and the pass check.
// Works whether the card is expanded or folded so a test that finishes after
// you collapse still updates the card.
function _applyVerdictToHeader(card, verdict) {
  if (!card || !verdict) return;
  const dotColor = {
    pass: 'var(--color-success, #4ade80)',
    needs_work: 'var(--color-warning, #f0ad4e)',
    inconclusive: 'var(--color-warning, #f0ad4e)',
    fail: 'var(--color-danger, #e06c75)',
  }[verdict];
  // Audit dot removed at user request — strip any pre-existing one so the
  // post-audit live update doesn't leave a stale dot from an old render.
  const header = card.querySelector('.skill-card-header');
  if (header) {
    header.querySelectorAll('.skill-audit-dot').forEach(n => n.remove());
  }
  const newConf = { pass: 95, needs_work: 60, fail: 40 }[verdict];
  const statsEl = card.querySelector('.skill-stats');
  if (statsEl && newConf != null) {
    const confEl = statsEl.querySelector('.skill-conf');
    if (confEl) { confEl.textContent = newConf + '%'; confEl.style.color = _confColor(newConf); }
  }
  // Fold the verdict into the status (draft / published) pill — colour the
  // pill itself and append a tiny check/warn/cross glyph so the audit result
  // lives next to the label instead of dangling in the stats row.
  const pill = card.querySelector('.skill-status-pill');
  if (pill) {
    // Inline glyphs for the per-verdict pill — appear next to the "checked"
    // label so the verdict reads as a real badge.
    const ICON = {
      pass: '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><polyline points="20 6 9 17 4 12"/></svg>',
      needs_work: '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><line x1="12" y1="8" x2="12" y2="13"/><line x1="12" y1="17" x2="12" y2="17"/></svg>',
      inconclusive: '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><line x1="12" y1="8" x2="12" y2="13"/><line x1="12" y1="17" x2="12" y2="17"/></svg>',
      fail: '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
    }[verdict];
    // Wash the pill's bg + tint the text so a glance at the badge tells you
    // pass/needs-work/fail without expanding the card.
    const tint = {
      pass:       { bg: 'color-mix(in srgb, var(--color-success, #4ade80) 30%, transparent)', fg: 'var(--color-success, #4ade80)' },
      needs_work: { bg: 'color-mix(in srgb, var(--color-warning, #f0ad4e) 30%, transparent)', fg: 'var(--color-warning, #f0ad4e)' },
      inconclusive: { bg: 'color-mix(in srgb, var(--color-warning, #f0ad4e) 30%, transparent)', fg: 'var(--color-warning, #f0ad4e)' },
      fail:       { bg: 'color-mix(in srgb, var(--color-danger, #e06c75) 30%, transparent)',  fg: 'var(--color-danger, #e06c75)' },
    }[verdict];
    // The status pill (draft / published) keeps its own colours now — the
    // verdict lives in a separate "checked" pill that's inserted next to it.
    // Remove any prior audit glyph (was previously inserted inside the pill;
    // now scrub both the in-pill and sibling locations on every refresh).
    pill.querySelectorAll('.skill-pill-verdict').forEach(n => n.remove());
    if (pill.parentElement) {
      pill.parentElement.querySelectorAll(':scope > .skill-pill-verdict').forEach(n => n.remove());
    }
    if (ICON) {
      // Full "checked" pill badge — sits LEFT of the draft/published pill,
      // styled like the other memory-cat-badges so it reads as a real chip.
      const span = document.createElement('span');
      span.className = 'memory-cat-badge skill-pill-verdict';
      span.title = 'Audited: ' + verdict.replace(/_/g, ' ');
      span.innerHTML = ICON + '<span>checked</span>';
      if (tint) {
        span.style.background = tint.bg;
        span.style.color = tint.fg;
      }
      if (pill.parentElement) {
        pill.parentElement.insertBefore(span, pill);
      } else {
        pill.insertAdjacentElement('beforebegin', span);
      }
    }
  }
  // Old free-floating .skill-verified check (next to confidence %) is no
  // longer added — the pill carries the verdict glyph now. Remove a stale
  // one in case the card was rendered by an earlier build.
  card.querySelectorAll('.skill-verified').forEach(n => n.remove());
}

function _renderTestVerdict(el, v, card, name) {
  if (!el) return;
  const verdict = (v && v.verdict) || 'unknown';
  const cls = { pass: 'ok', needs_work: 'warn', fail: 'bad', inconclusive: 'unknown' }[verdict] || 'unknown';
  const label = { pass: 'PASS', needs_work: 'NEEDS WORK', fail: 'FAIL', inconclusive: 'INCONCLUSIVE', unknown: 'UNCLEAR' }[verdict] || 'UNCLEAR';
  const conf = v && typeof v.confidence === 'number' ? Math.round(v.confidence * 100) + '%' : '';
  const issues = Array.isArray(v && v.issues) ? v.issues : [];
  // Reflect the skill's current state: a published skill offers Unpublish; a
  // draft offers Publish only on a pass — `BRAIN-M-13` (P23-02): it was
  // offered on UNCLEAR and FAIL too. The verbs are the two of `BRAIN-U-17`.
  const isPub = card && card.dataset && card.dataset.skillStatus === 'published';
  const offerPublish = isPub || verdict === 'pass';
  const approveLabel = isPub ? 'Unpublish' : 'Publish';
  const approveCls = 'skill-eval-approve' + (isPub ? ' is-approved' : (verdict === 'pass' ? ' suggested' : ''));
  el.innerHTML =
    '<div class="skill-eval-head"><span class="skill-eval-badge skill-eval-' + cls + '">' + label + (conf ? ' · ' + conf : '') + '</span>' +
    '<span class="skill-eval-summary">' + esc((v && v.summary) || '') + '</span></div>' +
    (issues.length ? '<ul class="skill-eval-issues">' + issues.map(i => '<li>' + esc(i) + '</li>').join('') + '</ul>' : '') +
    '<div class="doclib-card-expanded-actions skill-eval-actions-wrap">' +
      (offerPublish ? '<button class="doclib-card-text-btn doclib-card-action-btn ' + approveCls + '" data-act="approve">' + approveLabel + '</button>' : '') +
      '<div class="doclib-action-group"><div class="doclib-action-btn-row">' +
        '<button class="doclib-card-text-btn doclib-card-action-btn" data-act="retry" title="Run the test again">Retry</button>' +
        '<button class="doclib-card-text-btn doclib-card-action-btn" data-act="copy" title="Copy the run output + verdict">Copy</button>' +
        '<button class="doclib-card-text-btn doclib-card-action-btn" data-act="edit">Edit</button>' +
        '<button class="doclib-card-text-btn doclib-card-action-btn doclib-card-text-btn-danger" data-act="del"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>Delete</button>' +
      '</div></div>' +
    '</div>';
  _applyVerdictToHeader(card, verdict);
  el.querySelector('[data-act="approve"]')?.addEventListener('click', async (e) => {
    e.stopPropagation();
    const nowPub = card.dataset.skillStatus === 'published';
    await _setSkillStatus(name, nowPub ? 'draft' : 'published');
    // _setSkillStatus reloads the list, but if this card survives, relabel it.
    card.dataset.skillStatus = nowPub ? 'draft' : 'published';
    const btn = el.querySelector('[data-act="approve"]');
    if (btn) {
      const pub = card.dataset.skillStatus === 'published';
      btn.textContent = pub ? 'Unpublish' : 'Publish';
      btn.classList.toggle('is-approved', pub);
      btn.classList.toggle('suggested', !pub && verdict === 'pass');
    }
  });
  el.querySelector('[data-act="del"]')?.addEventListener('click', (e) => { e.stopPropagation(); _deleteSkill(name, card); });
  el.querySelector('[data-act="edit"]')?.addEventListener('click', (e) => { e.stopPropagation(); _toggleSkillEdit(card, name); });
  el.querySelector('[data-act="retry"]')?.addEventListener('click', (e) => { e.stopPropagation(); _testSkill(card, name, true); });
  el.querySelector('[data-act="copy"]')?.addEventListener('click', (e) => {
    e.stopPropagation();
    const logEl = card.querySelector('.skill-test-log');
    const issuesTxt = issues.length ? '\nIssues:\n- ' + issues.join('\n- ') : '';
    const text = (logEl ? logEl.innerText.trim() + '\n\n' : '') +
      '=== Eval: ' + label + (conf ? ' (' + conf + ')' : '') + ' ===\n' + ((v && v.summary) || '') + issuesTxt;
    // Shared helper falls back to execCommand on plain HTTP (navigator.clipboard
    // is unavailable in non-secure contexts, which is why the raw call failed).
    uiModule.copyToClipboard(text);
  });
}

// ---- Audit all skills (autonomous: test → fix → retry → teacher → flag) ----

let _auditPoll = null;
let _auditSeenResults = 0;

function _confirmAuditSkills(label) {
  return new Promise(resolve => {
    let overlay = document.getElementById('skills-audit-confirm-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'skills-audit-confirm-overlay';
      overlay.className = 'modal';
      overlay.innerHTML =
        '<div class="modal-content styled-confirm-box">' +
          '<div class="modal-header"><h4>Audit Skills</h4></div>' +
          '<div class="modal-body">' +
            '<p id="skills-audit-confirm-msg"></p>' +
            '<label class="memory-bulk-check-all" style="margin-top:10px;display:inline-flex;align-items:center;gap:7px;">' +
              '<input type="checkbox" id="skills-audit-skip-audited" checked />' +
              '<span>Skip already audited</span>' +
            '</label>' +
          '</div>' +
          '<div class="modal-footer">' +
            '<button id="skills-audit-confirm-cancel" class="confirm-btn confirm-btn-secondary">Cancel</button>' +
            '<button id="skills-audit-confirm-ok" class="confirm-btn confirm-btn-primary">Audit</button>' +
          '</div>' +
        '</div>';
      document.body.appendChild(overlay);
    }

    const msg = overlay.querySelector('#skills-audit-confirm-msg');
    const skip = overlay.querySelector('#skills-audit-skip-audited');
    const okBtn = overlay.querySelector('#skills-audit-confirm-ok');
    const cancelBtn = overlay.querySelector('#skills-audit-confirm-cancel');
    msg.textContent = `Test ${label}? Each is published or kept as a draft by the confidence bar in Settings.`;
    skip.checked = true;
    overlay.classList.remove('hidden');
    overlay.style.display = '';

    function cleanup(result) {
      overlay.classList.add('hidden');
      overlay.style.display = 'none';
      okBtn.removeEventListener('click', onOk);
      cancelBtn.removeEventListener('click', onCancel);
      overlay.removeEventListener('click', onBackdrop);
      document.removeEventListener('keydown', onKey);
      resolve(result);
    }
    function onOk() { cleanup({ ok: true, skipAudited: !!skip.checked }); }
    function onCancel() { cleanup({ ok: false, skipAudited: false }); }
    function onBackdrop(e) { if (e.target === overlay) onCancel(); }
    function onKey(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        cleanup({ ok: false, skipAudited: false });
      }
    }

    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
    overlay.addEventListener('click', onBackdrop);
    document.addEventListener('keydown', onKey);
    okBtn.focus();
  });
}

// `P22-21`. There is one audit at a time on the server, so the job is not a
// mount's: it is started from the mount whose list it audits (`m`), and drawn
// into every mount's panel while it runs (`_showAudit`).
async function _auditAllSkills(m, opts = {}) {
  const panel = m.el('skills-audit-panel');
  if (!panel) return;
  // If a run is already going, just (re)attach to it.
  let st = await _fetchAuditStatus();
  if (st.status !== 'running') {
    const explicitNames = Array.isArray(opts.names) ? opts.names.filter(Boolean) : null;
    const visibleNames = _getFilteredSkills(m)
      .map(sk => sk.name || sk.id)
      .filter(Boolean);
    const names = explicitNames || visibleNames;
    const label = explicitNames
      ? `${names.length} selected ${names.length === 1 ? 'skill' : 'skills'}`
      : `${names.length} visible ${names.length === 1 ? 'skill' : 'skills'}`;
    if (!names.length) {
      uiModule.showToast(explicitNames ? 'No selected skills to audit' : 'No visible skills to audit');
      return;
    }
    const confirmed = await _confirmAuditSkills(label);
    if (!confirmed.ok) return;
    try {
      const r = await fetch(`${API}/api/skills/audit-all`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope: explicitNames ? 'selected' : 'all', names, skip_audited: confirmed.skipAudited }),
      });
      if (!r.ok) { uiModule.showError('Audit failed to start (HTTP ' + r.status + ')'); return; }
      st = await _fetchAuditStatus();
    } catch (e) { uiModule.showError('Audit failed: ' + (e.message || e)); return; }
    _auditSeenResults = 0;
  }
  _showAudit(st);
}

function _auditPanels() {
  return _allMounts().map((m) => m.el('skills-audit-panel')).filter(Boolean);
}

/** The audit's progress, in every mount's panel, kept up by one poll. */
function _showAudit(st) {
  const panels = _auditPanels();
  if (!panels.length) return;
  panels.forEach((panel) => panel.classList.remove('hidden'));
  _auditSeenResults = Math.min(_auditSeenResults, (st.results || []).length);
  panels.forEach((panel) => _renderAuditPanel(panel, st));
  _applyAuditResults(st);
  _highlightAuditCard(st.status === 'running' ? st.current : null);
  if (_auditPoll) clearInterval(_auditPoll);
  if (st.status === 'running') {
    _auditPoll = setInterval(async () => {
      const s = await _fetchAuditStatus();
      _auditPanels().forEach((panel) => _renderAuditPanel(panel, s));
      _applyAuditResults(s);
      _highlightAuditCard(s.status === 'running' ? s.current : null);
      if (s.status !== 'running') {
        clearInterval(_auditPoll); _auditPoll = null;
        _highlightAuditCard(null);
        loadSkills();  // refresh statuses (some may have been demoted/edited)
      }
    }, 1500);
  }
}

/** A skill's card in `m`'s list — or, with no mount named, in the one the
 *  person is working in first, then any (`P22-21`). */
function _findSkillCard(name, m = null) {
  if (!name) return null;
  const order = m ? [m] : [_activeMount(), ..._allMounts()];
  for (const at of order) {
    const card = _skillCardsIn(at).find(c => c.dataset.skillName === name);
    if (card) return card;
  }
  return null;
}

function _skillCardsIn(m) {
  const list = m && m.el('skills-list');
  return list ? [...list.querySelectorAll('.skill-card[data-skill-name]')] : [];
}

/** Every mount's card for one skill: an audit's verdict is the skill's, so it
 *  is drawn wherever the skill is listed. */
function _skillCardsNamed(name) {
  return _allMounts().map((m) => _findSkillCard(name, m)).filter(Boolean);
}

function _mergeSkillState(state) {
  if (!state || !state.name) return;
  const idx = skills.findIndex(s => (s.name || s.id) === state.name);
  if (idx >= 0) skills[idx] = { ...skills[idx], ...state };
}

function _applySkillStateToHeader(card, state, fallbackVerdict) {
  if (!card) return;
  const verdict = state?.audit_verdict || fallbackVerdict;
  if (verdict) _applyVerdictToHeader(card, verdict);
  if (state && typeof state.confidence === 'number') {
    const conf = Math.round(state.confidence * 100);
    const confEl = card.querySelector('.skill-conf');
    if (confEl) { confEl.textContent = conf + '%'; confEl.style.color = _confColor(conf); }
  }
  if (state?.status) {
    card.dataset.skillStatus = state.status;
    const oldPill = card.querySelector('.skill-status-pill');
    if (oldPill) {
      const wrap = document.createElement('span');
      wrap.innerHTML = _statusPill(state);
      const next = wrap.firstElementChild;
      if (next) oldPill.replaceWith(next);
    }
  }
  const right = card.querySelector('.skill-card-right');
  if (right && state) {
    right.querySelectorAll('.skill-model-pill, .skill-necessity-pill').forEach(n => n.remove());
    const stats = right.querySelector('.skill-stats');
    const wrap = document.createElement('span');
    wrap.innerHTML = _auditModelPills(state) + _necessityPill(state);
    [...wrap.children].forEach(p => {
      if (stats) right.insertBefore(p, stats);
      else right.appendChild(p);
    });
  }
}

function _applyAuditResults(st) {
  const results = st && Array.isArray(st.results) ? st.results : [];
  if (!results.length) return;
  for (const r of results.slice(_auditSeenResults)) {
    const name = r && r.skill;
    if (!name) continue;
    const state = r.skill_state || null;
    _mergeSkillState(state);
    const verdict = state?.audit_verdict || r.verdict?.verdict || (r.result === 'flagged' ? 'fail' : null);
    for (const card of _skillCardsNamed(name)) _applySkillStateToHeader(card, state, verdict);
  }
  _auditSeenResults = results.length;
}

// Make the card currently being audited glow, so it's obvious which one the
// "Audit now" run is processing. Pass null to clear all highlights.
function _highlightAuditCard(name) {
  document.querySelectorAll('.skill-card.skill-audit-active')
    .forEach(c => { c.classList.remove('skill-audit-active'); _setCardRunning(c, false); });
  if (!name) return;
  for (const card of _skillCardsNamed(name)) {
    card.classList.add('skill-audit-active');
    _setCardRunning(card, true);
    card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
}

async function _fetchAuditStatus() {
  try {
    const r = await fetch(`${API}/api/skills/audit-all/status`);
    return r.ok ? await r.json() : { status: 'none' };
  } catch { return { status: 'none' }; }
}

/**
 * The Brain's dock chip, from the audit's own status. `P9-11`.
 *
 * Running work gets a chip; a finished audit does not, because a chip that
 * lingers after the job is over becomes furniture and stops meaning "look at
 * this". The outcome is said once, through the toast the product already uses
 * for "that finished" (`Law 14`), and `_auditSaid` is what keeps a 1.5s poll
 * from saying it forty times.
 */
let _auditSaid = null;
function _syncAuditChip(st) {
  const status = st && st.status;
  if (status === 'running') {
    const done = st.done || 0, total = st.total || 0;
    _auditSaid = 'running';
    setBackgroundWork('skills-modal', {
      // Keyed although the Skills window holds one job today (`P9-06` moved
      // it out of the Brain, where it shared a window with the memory tidy):
      // a second job here must not erase this one from the dock.
      key: 'skills-audit',
      label: total ? `Auditing ${done}/${total}` : 'Auditing skills',
      detail: st.current
        ? `Skills audit: ${done} of ${total} done, now testing ${st.current}`
        : `Skills audit: ${done} of ${total} done`,
    });
    return;
  }
  setBackgroundWork('skills-modal', { key: 'skills-audit' });
  if (_auditSaid !== 'running') { _auditSaid = status || null; return; }
  _auditSaid = status || null;
  const total = st && st.total ? st.total : 0;
  const bad = ((st && st.results) || []).filter(
    r => r && (r.result === 'fail' || r.result === 'needs_work')).length;
  if (status === 'cancelled') {
    uiModule.showToast(`Skills audit cancelled after ${st.done || 0} of ${total}`);
  } else {
    uiModule.showToast(bad
      ? `Skills audit finished — ${bad} of ${total} need work`
      : `Skills audit finished — all ${total} passed`);
  }
}

function _renderAuditPanel(panel, st) {
  // `P9-11`. Every path that updates this panel comes through here — the
  // re-attach on load, the first render, and the 1.5s poll — so this is the one
  // place that can keep the dock chip honest without a second timer.
  //
  // The audit is the sharpest case the row names: `_auditPoll` keeps running at
  // 1.5s whether or not the Brain is on screen, writing into a panel inside a
  // modal the person may have closed minutes ago. Nothing stopped; only the
  // telling stopped.
  _syncAuditChip(st);
  if (st.status === 'none') { panel.classList.add('hidden'); panel.innerHTML = ''; return; }
  const done = st.done || 0, total = st.total || 0;
  const pct = total ? Math.round((done / total) * 100) : 0;
  const counts = {};
  for (const r of (st.results || [])) counts[r.result] = (counts[r.result] || 0) + 1;
  const summary = Object.entries(counts).map(([k, v]) => v + ' ' + k.replace(/_/g, ' ')).join(' · ');
  const running = st.status === 'running';
  const cancelled = st.status === 'cancelled';
  const head = running
    ? `Auditing ${done}/${total}${st.current ? ' — ' + esc(st.current) : ''}`
    : cancelled
      ? `Audit cancelled — ${done}/${total}`
    : `Audit complete — ${total} skill${total === 1 ? '' : 's'}`;
  panel.innerHTML =
    '<div class="skills-audit-head">' +
      '<span class="skills-audit-title-wrap" style="display:inline-flex;align-items:center;gap:8px;">' +
        '<span class="skills-audit-title">' + head + '</span>' +
      '</span>' +
      (running
        ? '<button class="memory-toolbar-btn" data-act="audit-cancel">Cancel</button>'
        : '<button class="memory-toolbar-btn" data-act="audit-close">Close</button>') +
    '</div>' +
    '<div class="skills-audit-bar"><div class="skills-audit-fill" style="width:' + pct + '%"></div></div>' +
    (summary ? '<div class="skills-audit-summary">' + esc(summary) + (st.teacher ? ' · teacher: ' + esc(st.teacher) : '') + '</div>' : '') +
    '<div class="skills-audit-log">' + (st.log || []).slice(-40).map(l => '<div>' + esc(l) + '</div>').join('') + '</div>';
  // Whirlpool sits next to the title while the audit is actually running.
  if (running) {
    const titleWrap = panel.querySelector('.skills-audit-title-wrap');
    if (titleWrap) {
      const wp = spinnerModule.createWhirlpool(12);
      wp.element.style.cssText = 'display:inline-flex;width:12px;height:12px;margin:0;vertical-align:middle;flex-shrink:0;';
      titleWrap.appendChild(wp.element);
    }
  }
  const cancel = panel.querySelector('[data-act="audit-cancel"]');
  if (cancel) cancel.addEventListener('click', async (e) => {
    e.stopPropagation();
    cancel.disabled = true;
    cancel.textContent = 'Cancelling...';
    try {
      await fetch(`${API}/api/skills/audit-all/cancel`, { method: 'POST', credentials: 'same-origin' });
      const s = await _fetchAuditStatus();
      _renderAuditPanel(panel, { ...s, status: s.status === 'none' ? 'cancelled' : s.status });
      _highlightAuditCard(null);
    } catch {
      cancel.disabled = false;
      cancel.textContent = 'Cancel';
    }
  });
  const close = panel.querySelector('[data-act="audit-close"]');
  if (close) close.addEventListener('click', () => { panel.classList.add('hidden'); panel.innerHTML = ''; });
  const logEl = panel.querySelector('.skills-audit-log');
  if (logEl) logEl.scrollTop = logEl.scrollHeight;
}

// ---- Select mode / bulk actions ----

const _SKILLS_SELECT_BTN_DOT_SVG = '<svg class="memory-select-btn-icon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:3px;"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/></svg>';
const _SKILLS_SELECT_BTN_X_SVG = '<svg class="memory-select-btn-icon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" style="vertical-align:-2px;margin-right:3px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

function _enterSelectMode(m) {
  m.selectMode = true;
  m.selected.clear();
  const bar = m.el('skills-bulk-bar');
  const btn = m.el('skills-select-btn');
  if (bar) bar.classList.remove('hidden');
  if (btn) { btn.classList.add('active'); btn.innerHTML = _SKILLS_SELECT_BTN_X_SVG + 'Cancel'; }
  _updateBulkBar(m);
  renderSkillsList(m);
}

function _exitSelectMode(m) {
  m.selectMode = false;
  m.selected.clear();
  const bar = m.el('skills-bulk-bar');
  const btn = m.el('skills-select-btn');
  const all = m.el('skills-select-all');
  if (bar) bar.classList.add('hidden');
  if (btn) { btn.classList.remove('active'); btn.innerHTML = _SKILLS_SELECT_BTN_DOT_SVG + 'Select'; }
  if (all) all.checked = false;
  renderSkillsList(m);
}

function _updateBulkBar(m) {
  const countEl = m.el('skills-selected-count');
  const delBtn = m.el('skills-bulk-delete');
  const delNonPassingBtn = m.el('skills-bulk-delete-nonpassing');
  const pubBtn = m.el('skills-bulk-publish');
  const auditBtn = m.el('skills-bulk-audit');
  if (countEl) countEl.textContent = `${m.selected.size} Selected`;
  if (delBtn) delBtn.disabled = m.selected.size === 0;
  if (auditBtn) auditBtn.disabled = m.selected.size === 0;
  const groupBtn = m.el('skills-bulk-group');
  if (groupBtn) groupBtn.disabled = m.selected.size === 0;
  if (delNonPassingBtn) {
    const count = _selectedNonPassingSkills(m.selected).length;
    delNonPassingBtn.disabled = count === 0;
    delNonPassingBtn.title = count
      // `P9-12` / `Law 15`. The tooltip is where a person finds out what the
      // button will take before they press it, and the disabled state has to
      // say why it is disabled rather than repeat the label.
      ? `Delete ${count} selected ${count === 1 ? 'skill' : 'skills'}: duplicates, generic or irrelevant ones, and failed audits. Skills that have not been audited yet are left alone.`
      : 'None of the selected skills has failed an audit. Skills that have not been audited yet are never counted here.';
  }
  // Approve is only meaningful when at least one selected skill is still a draft.
  const anyDraft = [...m.selected].some(n => {
    const sk = skills.find(s => (s.name || s.id) === n);
    return sk && (sk.status || 'draft') !== 'published';
  });
  if (pubBtn) pubBtn.disabled = !anyDraft;
}

function _toggleSelectAll(m) {
  const all = m.el('skills-select-all');
  if (!all) return;
  const visible = _getFilteredSkills(m).map(s => s.name || s.id);
  if (all.checked) visible.forEach(n => m.selected.add(n));
  else visible.forEach(n => m.selected.delete(n));
  _updateBulkBar(m);
  renderSkillsList(m);
}

async function _bulkDelete(m) {
  if (!m.selected.size) return;
  const n = m.selected.size;
  const ok = await uiModule.styledConfirm(
    `Delete ${n} ${n === 1 ? 'skill' : 'skills'}? This removes their SKILL.md files.`,
    { confirmText: 'Delete', danger: true }
  );
  if (!ok) return;
  let deleted = 0;
  const deletedNames = [];
  for (const name of m.selected) {
    try {
      const res = await fetch(`${API}/api/skills/${encodeURIComponent(name)}`, { method: 'DELETE' });
      if (res.ok) {
        deleted++;
        deletedNames.push(name);
      }
    } catch {}
  }
  for (const name of deletedNames) {
    for (const card of _skillCardsNamed(name)) card.classList.add('doclib-card-deleting');
  }
  if (deletedNames.length) await new Promise(resolve => setTimeout(resolve, 320));
  _exitSelectMode(m);
  await loadSkills();
  uiModule.showToast(`Deleted ${deleted}`);
}

async function _loadSkillApprovalThreshold() {
  try {
    const res = await fetch(`${API}/api/prefs`, { credentials: 'same-origin' });
    if (!res.ok) return;
    const prefs = await res.json();
    const raw = prefs.skill_min_confidence ?? prefs.skill_autosave_min_confidence;
    const val = Number(raw);
    if (Number.isFinite(val)) _skillApprovalThreshold = Math.max(0, Math.min(1, val));
  } catch {}
}

/**
 * `P9-12`. The verdicts that mean the audit ran and the skill did not pass.
 *
 * `routes/skills_routes.py` writes six values through `set_audit`: `pass`,
 * `needs_work`, `fail`, `inconclusive`, `skipped` and `unknown`. Only two of
 * them are a judgement against the skill. The audit prompt says so in its own
 * words at `routes/skills_routes.py:193-196` — *"if the run could NOT proceed
 * because it lacked an input or target the test never provided … that is NOT
 * the skill's fault. Return verdict 'inconclusive' — do NOT mark it fail or
 * needs_work"* — so deleting on `inconclusive` deletes a skill for the test
 * harness's failure, and `skipped` is written when there was no source to read.
 */
const _FAILING_AUDIT_VERDICTS = new Set(['fail', 'needs_work']);

/**
 * `P9-12` — what "non-passing" means, and the three things it used to mean that
 * cost people files.
 *
 * This is a **data-loss** row: the button it feeds calls
 * `DELETE /api/skills/{name}`, which removes the whole skill directory
 * including its version history (`services/memory/skills.py:938-963`). There is
 * no trash and no server-side restore, which is why the caller below now holds
 * every SKILL.md it is about to remove.
 *
 * **1. NEVER AUDITED IS NOT FAILING, and it was the default state.** The old
 * test was `(sk.audit_verdict || '') !== 'pass'`, and `audit_verdict` is `null`
 * until an audit has actually run — `load_all` reads it out of the usage
 * sidecar and it is absent until `set_audit` writes one. The backend reads the
 * same absence the opposite way, in three places, and every one of them means
 * *this one still needs auditing*: `routes/skills_routes.py:1769`, `:1785` and
 * `src/builtin_actions.py:2211` build the **audit queue** from
 * `not s.get("audit_verdict")`. So a skill written by hand thirty seconds ago
 * was on the audit queue and in the delete set at the same time.
 *
 * **2. THE BUNDLED LIBRARY WAS THE WHOLE SET.** `/api/skills` folds in the
 * read-only bundled entries, and `load_all` does not even *read* a verdict for
 * them (`services/memory/skills.py:659-671` sets `uses` and `last_used` and
 * stops), so all of them matched `!== 'pass'` permanently and could never stop
 * matching. `DELETE` refuses them — `_verify_owner` 404s on `owner: null` and
 * `delete_skill` never walks the library directory — so nothing was destroyed,
 * but "Select all" then "Delete non passing" counted them, put the number in
 * the confirmation, and reported a smaller number afterwards.
 *
 * **3. THE RECOMMENDED KEEPER WAS DELETED WITH ITS DUPLICATES.**
 * `_duplicateMeta` groups client-side at a similarity of 0.38 — the server's
 * own dedup-at-creation uses 0.82 — and marks exactly one member `_duplicateKeep`,
 * which the card renders as *"recommended"*. `_necessityKind` returned
 * `'duplicate'` for **every** member including that one, so the delete took the
 * keeper too and the entire group vanished. The recommendation is now honoured:
 * a group loses its duplicates and keeps the one the UI told you to keep.
 *
 * **4. MISSING CONFIDENCE IS NOT ZERO.** `Number(sk.confidence || 0)` read an
 * absent value as 0, which is below every threshold. `services/memory/skills.py:1100-1119`
 * states the opposite rule for the same field and says why: *"Missing confidence =
 * treat as 1.0 (legacy skills shouldn't silently vanish)."* And the threshold
 * comparison could not have been meaningful before an audit anyway: `add_skill`
 * writes `confidence: 0.8` by default, `skill_autosave_min_confidence` defaults
 * to `0.85` (`src/settings.py:557`), and a pass writes `0.95`
 * (`routes/skills_routes.py:933`) — so every skill is below the bar from the
 * moment it is created until an audit lifts it. The bar therefore applies to
 * skills that have been scored, which is the only time it means anything.
 */
//
// `P22-21`. The selection is a mount's now and is handed in; the parameter
// keeps the name the module-level set had, so the body below — the part of
// this row that decides what a delete takes — is the body it was.
function _selectedNonPassingSkills(_selectedNames) {
  const selected = new Set(_selectedNames);
  return skills.filter(sk => {
    const name = sk.name || sk.id;
    if (!selected.has(name)) return false;
    // Read-only library entries: never audited, never deletable.
    if (sk.bundled || sk.editable === false) return false;

    const necessity = _necessityKind(sk);
    // The keeper of a duplicate group is the one the card recommends keeping.
    if (necessity === 'duplicate' && sk._duplicateGroup && sk._duplicateKeep) return false;
    if (necessity === 'duplicate' || necessity === 'trivial' || necessity === 'irrelevant') return true;

    const verdict = String(sk.audit_verdict || '').toLowerCase();
    if (!verdict) return false;                       // never audited
    if (_FAILING_AUDIT_VERDICTS.has(verdict)) return true;
    if (verdict !== 'pass') return false;             // inconclusive / skipped / unknown
    // Scored and passed — the threshold is the last question.
    const conf = sk.confidence == null ? 1 : Number(sk.confidence);
    return (Number.isFinite(conf) ? conf : 1) < _skillApprovalThreshold;
  });
}

/**
 * `P9-12`, the undo half.
 *
 * `DELETE /api/skills/{name}` removes the skill's whole directory, versions
 * included, and there is no trash on the server — so the only place a restore
 * can come from is the browser that asked for the delete. Every SKILL.md is
 * therefore read **before** anything is removed, and a skill whose source
 * cannot be read is not deleted at all: the alternative is a delete that is
 * knowingly unrecoverable, which is the thing this row exists to stop.
 *
 * Restoring is two calls because there is no create-from-markdown route.
 * `POST /api/skills/add` makes the directory under the same name — free after
 * the delete — with `source: 'user'`, which is what exempts it from
 * `add_skill`'s dedup-at-creation; `POST /{name}/markdown` then writes the
 * exact bytes back, and it pins the stored name rather than the one in the
 * frontmatter (`routes/skills_routes.py:1846-1848`), so the round trip is
 * byte-stable.
 */
async function _restoreDeletedSkills(saved) {
  let restored = 0;
  const failed = [];
  for (const entry of saved) {
    try {
      const add = await fetch(`${API}/api/skills/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({
          name: entry.name,
          description: entry.description || '',
          status: entry.status || 'draft',
          confidence: entry.confidence == null ? 0.8 : Number(entry.confidence),
          source: 'user',
        }),
      });
      if (!add.ok) throw new Error(`HTTP ${add.status}`);
      const created = await add.json();
      const name = (created && created.skill && created.skill.name) || entry.name;
      const put = await fetch(`${API}/api/skills/${encodeURIComponent(name)}/markdown`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ markdown: entry.markdown }),
      });
      if (!put.ok) throw new Error(`HTTP ${put.status}`);
      _mdCache.set(name, entry.markdown);
      restored++;
    } catch {
      failed.push(entry.name);
    }
  }
  await loadSkills();
  if (failed.length) {
    uiModule.showError(`Restored ${restored}; could not restore ${failed.join(', ')}`);
  } else {
    uiModule.showToast(`Restored ${restored} ${restored === 1 ? 'skill' : 'skills'}`);
  }
}

async function _bulkDeleteNonPassing(m) {
  const targets = _selectedNonPassingSkills(m.selected);
  if (!targets.length) {
    uiModule.showToast('No selected skills have failed an audit');
    return;
  }
  const thresholdPct = Math.round(_skillApprovalThreshold * 100);
  const names = targets.map(sk => sk.name || sk.id).filter(Boolean);
  // What is about to happen, in the words of what the person selected. The old
  // sentence promised four categories and delivered "everything not yet
  // audited", which is the gap `Law 15` asks you to close on the surface rather
  // than in a comment.
  const ok = await uiModule.styledConfirm(
    `Delete ${names.length} selected ${names.length === 1 ? 'skill' : 'skills'}? `
    + `These are the ones marked duplicate, generic or irrelevant, the ones whose audit `
    + `failed, and the ones that passed below ${thresholdPct}%. Skills that have not been `
    + `audited yet are not included. You can undo this from the message that follows.`,
    { confirmText: 'Delete non passing', danger: true }
  );
  if (!ok) return;

  // Read every source before removing anything.
  const saved = [];
  const unreadable = [];
  for (const sk of targets) {
    const name = sk.name || sk.id;
    try {
      const markdown = await _fetchSkillMarkdown(name);
      if (!markdown) throw new Error('empty');
      saved.push({
        name,
        markdown,
        description: sk.description || '',
        status: sk.status || 'draft',
        confidence: sk.confidence,
      });
    } catch {
      unreadable.push(name);
    }
  }
  if (unreadable.length) {
    uiModule.showError(
      `Nothing deleted. Could not read ${unreadable.join(', ')}, so the delete could not be undone.`,
    );
    return;
  }

  let deleted = 0;
  const deletedNames = [];
  const restorable = [];
  for (const entry of saved) {
    try {
      const res = await fetch(`${API}/api/skills/${encodeURIComponent(entry.name)}`, { method: 'DELETE' });
      if (res.ok) {
        deleted++;
        deletedNames.push(entry.name);
        restorable.push(entry);
        _mdCache.delete(entry.name);
      }
    } catch {}
  }
  for (const name of deletedNames) {
    for (const card of _skillCardsNamed(name)) card.classList.add('doclib-card-deleting');
  }
  if (deletedNames.length) await new Promise(resolve => setTimeout(resolve, 320));
  _exitSelectMode(m);
  await loadSkills();
  if (!restorable.length) {
    uiModule.showToast('Nothing was deleted');
    return;
  }
  uiModule.showToast(`Deleted ${deleted} ${deleted === 1 ? 'skill' : 'skills'}`, {
    duration: 12000,
    action: 'Undo',
    onAction: () => _restoreDeletedSkills(restorable),
  });
}

async function _bulkApprove(m) {
  if (!m.selected.size) return;
  let published = 0;
  for (const name of m.selected) {
    const sk = skills.find(s => (s.name || s.id) === name);
    if (sk && sk.status === 'published') continue;
    try {
      const res = await fetch(`${API}/api/skills/${encodeURIComponent(name)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'published' }),
      });
      if (res.ok) published++;
    } catch {}
  }
  _exitSelectMode(m);
  await loadSkills();
  uiModule.showToast(`Published ${published}`);
}

async function _bulkAudit(m) {
  if (!m.selected.size) return;
  const selected = new Set(m.selected);
  const ordered = _getFilteredSkills(m)
    .map(sk => sk.name || sk.id)
    .filter(n => selected.has(n));
  _exitSelectMode(m);
  await _auditAllSkills(m, { names: ordered });
}

// ---- The prompt preview: what the AI is actually handed (`P8-06`/`P8-07`) ----

// `GET /api/skills/index` was written to answer exactly this question, and no
// frontend file had ever called it: `grep -rn "api/skills/index" static/`
// returned nothing across the tree until this function.
//
// It renders what that endpoint returns and nothing else. It does not re-derive
// the catalogue in the browser. A preview that computes its own answer is a
// second renderer (`Law 14`) and stops being the truth the first time the
// server's rules move, which is the failure mode a preview exists to prevent.
//
// `P8-07` is the other half and it is the part people are surprised by: the
// catalogue carries a name and a description, a match adds the procedure and
// the pitfalls, and the verification steps and the body of SKILL.md are never
// sent at all. They are reachable — open the card, or the model asks for the
// whole file — but nothing said so.
const _PROMPT_PREVIEW_FACTS = [
  ['In the block above', 'each skill’s name and description, filed under its category.'],
  ['Added when your message matches one', 'its when-to-use, its numbered procedure, and its pitfalls.'],
  ['Never sent', 'its verification steps, and everything below the frontmatter in SKILL.md. Open a skill here to read them — the model can ask for the whole file, one skill at a time.'],
];

// `P8-18` on the surface that shows the injected text; `D-11` (P23-02)
// shortened it to the one sentence Skills › Settings says too.
const _PROMPT_PREVIEW_GATE =
  'Skills are untrusted text, so a reply that uses one asks before it writes, runs, sends or deletes.';

function _closePromptPreview(m) {
  const panel = m.el('skills-prompt-panel');
  if (panel) { panel.classList.add('hidden'); panel.replaceChildren(); }
  const btn = m.el('skills-preview-btn');
  if (btn) btn.setAttribute('aria-expanded', 'false');
}

function _el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}

// The panel's own title. It named the *list* — "The catalogue the AI browses" —
// because when it was written the endpoint had no `prompt` to render. It has
// one now, the panel leads with it, and a title promising a catalogue in front
// of a block of prompt text would be the preview lying about itself.
const _PROMPT_PREVIEW_TITLE = 'What the model is shown';

function _formatChars(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return '';
  return v.toLocaleString ? v.toLocaleString() : String(v);
}

async function _renderPromptPreview(m) {
  const panel = m.el('skills-prompt-panel');
  if (!panel) return;
  const btn = m.el('skills-preview-btn');
  if (!panel.classList.contains('hidden')) { _closePromptPreview(m); return; }
  panel.classList.remove('hidden');
  if (btn) btn.setAttribute('aria-expanded', 'true');
  panel.replaceChildren(_el('div', 'skills-audit-summary', 'Reading the catalogue…'));

  let index = [];
  let promptText = '';
  let promptChars = 0;
  let withheld = [];
  try {
    const res = await fetch(`${API}/api/skills/index`, { credentials: 'same-origin' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    index = Array.isArray(data && data.index) ? data.index : [];
    // `P8-06`'s closing half. `prompt` is the string
    // `services/memory/skill_injection.py::render_skill_index_block` returns —
    // the same call `agent_loop._build_base_prompt` makes — so what is drawn
    // below is the characters the model is handed, not a list re-rendered to
    // look like them. It is taken verbatim: no trim, no re-wrap, no re-sort.
    // The moment this file formats it, the preview stops being evidence.
    promptText = typeof (data && data.prompt) === 'string' ? data.prompt : '';
    promptChars = Number.isFinite(data && data.prompt_chars) ? data.prompt_chars : promptText.length;
    withheld = Array.isArray(data && data.withheld_fields) ? data.withheld_fields : [];
  } catch (e) {
    panel.replaceChildren(
      _el('div', 'skills-audit-title', _PROMPT_PREVIEW_TITLE),
      _el('div', 'skill-prompt-note', 'Could not read it: ' + (e.message || String(e))),
    );
    return;
  }

  // Every string below this line is skill text a person or a model wrote, so it
  // reaches the DOM through `textContent` and never through markup. The drafts
  // panel (`H01`) is the precedent: a skill description is a perfectly good XSS
  // payload and this is the one surface whose job is to show it verbatim.
  const head = _el('div', 'skills-audit-head');
  head.appendChild(_el('span', 'skills-audit-title', _PROMPT_PREVIEW_TITLE));
  const close = _el('button', 'memory-toolbar-btn skill-prompt-close', 'Close');
  close.type = 'button';
  close.addEventListener('click', (e) => { e.stopPropagation(); _closePromptPreview(m); });
  head.appendChild(close);

  // ---- The text itself, which is the answer this panel exists to give. ----
  const exact = _el('div', 'skill-prompt-exact');
  exact.appendChild(_el('div', 'skill-prompt-exact-label',
    promptText
      ? `Injected into every system prompt, exactly as shown — ${_formatChars(promptChars)} characters.`
      : 'Nothing is injected. No line about skills reaches the system prompt at all.'));
  if (promptText) {
    const pre = _el('pre', 'skill-prompt-text');
    // `textContent`, not `innerHTML`: this is the one node in the app whose
    // contents are a prompt assembled out of user-written descriptions.
    pre.textContent = promptText;
    exact.appendChild(pre);
  }

  const body = _el('div', 'skill-prompt-body');
  if (index.length) {
    body.appendChild(_el('div', 'skill-prompt-subhead',
      'Every entry in that block, and what its status means:'));
  }
  if (!index.length) {
    body.appendChild(_el('div', 'skill-prompt-empty',
      'Empty. The model is shown no skills — publish one and it appears here.'));
  } else {
    const byCat = new Map();
    for (const entry of index) {
      const cat = (entry && entry.category) || 'general';
      if (!byCat.has(cat)) byCat.set(cat, []);
      byCat.get(cat).push(entry);
    }
    for (const cat of [...byCat.keys()].sort()) {
      body.appendChild(_el('div', 'skill-prompt-cat', cat));
      for (const entry of byCat.get(cat)) {
        const row = _el('div', 'skill-prompt-row');
        row.appendChild(_el('code', 'skill-prompt-name', (entry && entry.name) || ''));
        row.appendChild(_el('span', 'skill-prompt-desc', (entry && entry.description) || ''));
        if (entry && entry.status === 'draft') {
          row.appendChild(_el('span', 'skill-prompt-tag',
            'draft — listed because the teacher wrote it'));
        }
        body.appendChild(row);
      }
    }
  }

  const facts = _el('div', 'skill-prompt-facts');
  for (const [label, text] of _PROMPT_PREVIEW_FACTS) {
    const row = _el('div', 'skill-prompt-fact');
    row.appendChild(_el('span', 'skill-prompt-fact-k', label + ':'));
    row.appendChild(_el('span', 'skill-prompt-fact-v', text));
    facts.appendChild(row);
  }
  // The sentence above is English and the server derives the same answer from
  // the schema (`WITHHELD_FIELDS`, built from `Skill.to_dict()`). Printing the
  // served list beside the sentence is what stops a field added to the schema
  // being silently missing from the prose — one source of truth, restated by
  // nobody (`Law 7`).
  if (withheld.length) {
    const row = _el('div', 'skill-prompt-fact');
    row.appendChild(_el('span', 'skill-prompt-fact-k', 'Withheld, field by field:'));
    row.appendChild(_el('code', 'skill-prompt-fact-v skill-prompt-withheld', withheld.join(', ')));
    facts.appendChild(row);
  }
  facts.appendChild(_el('div', 'skill-prompt-note', _PROMPT_PREVIEW_GATE));

  panel.replaceChildren(head, exact, body, facts);
}

// `B926`. The import's own status line (`#skill-import-status`), under the box
// it was started from. Everything it says is text.
function _importStatus(m, kind, lines, openName) {
  const el = m.el('skill-import-status');
  if (!el) return null;
  el.hidden = false;
  el.className = `memory-desc skill-import-status${kind ? ` is-${kind}` : ''}`;
  el.replaceChildren();
  (Array.isArray(lines) ? lines : [lines]).filter(Boolean).forEach((line, i) => {
    if (i) el.appendChild(document.createElement('br'));
    el.appendChild(document.createTextNode(String(line)));
  });
  if (openName) {
    el.appendChild(document.createTextNode(' '));
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'skill-import-open';
    open.textContent = 'Open it';
    open.addEventListener('click', () => openSkill(openName, {}, m));
    el.appendChild(open);
  }
  return el;
}

let _importInFlight = false;

async function importSkillFromUrl(m) {
  const input = m.el('skill-import-url');
  const url = (input?.value || '').trim();
  if (!url) {
    _importStatus(m, 'error', 'Paste a GitHub or skills.sh link to a skill folder or its SKILL.md first.');
    uiModule.showError('Paste a GitHub or skills.sh URL first');
    return;
  }
  // `B926`. Enter while an import runs used to start a second one.
  if (_importInFlight) return;
  _importInFlight = true;
  const btn = m.el('skill-import-url-btn');
  const btnHtml = btn ? btn.innerHTML : '';
  if (btn) {
    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');
    btn.textContent = 'Importing…';
  }
  // `B926`. The fetch is paced — about a request a second to GitHub — so a
  // folder of files takes a while, and nothing on screen used to say anything
  // was happening. Count the wait, and say why it can be long.
  const started = Date.now();
  const tick = () => {
    const s = Math.round((Date.now() - started) / 1000);
    _importStatus(m, 'busy', [
      `Downloading from GitHub… ${s}s`,
      s >= 8 ? 'Pantheon asks GitHub for about one file a second, so a skill with many files takes a while.' : '',
    ]);
  };
  tick();
  const timer = setInterval(tick, 1000);
  try {
    const res = await fetch(`${API}/api/skills/import-from-url`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
    if (input) input.value = '';
    const name = data.skill?.name || 'skill';
    const count = Number(data.files || 1);
    const notes = Array.isArray(data.notes) ? data.notes : [];
    // `P8-49`. A package is said as a package: how many skills, how many
    // were new, and the window opens on it rather than on one of them.
    const pkg = data.package && data.package.id ? data.package : null;
    const fresh = Array.isArray(data.installed) ? data.installed.length : 0;
    const again = Array.isArray(data.updated) ? data.updated.length : 0;
    const many = pkg && fresh + again > 1;
    const headline = many
      ? `Imported ${pkg.title} — ${fresh + again} skills${again ? ` (${fresh} new, ${again} refreshed)` : ''}.`
      : `Imported ${name} — ${count} file${count === 1 ? '' : 's'}.`;
    clearInterval(timer);
    _importStatus(m, notes.length ? 'warn' : 'ok', [headline, ...notes], name);
    uiModule.showToast(many ? `Imported ${pkg.title} (${fresh + again} skills)`
                            : `Imported ${name} (${count} file${count === 1 ? '' : 's'})`);
    await loadSkills();
    if (name) openSkill(name, many ? { scope: { kind: 'package', id: pkg.id } } : undefined, m);
  } catch (err) {
    clearInterval(timer);
    const msg = (err && err.message) || String(err);
    // `BRAIN-M-12` (P23-02): said once, beside the box it was started from —
    // the status line exists for this (`B926`); a toast repeated it.
    _importStatus(m, 'error', `Import failed: ${msg}`);
  } finally {
    clearInterval(timer);
    _importInFlight = false;
    if (btn) {
      btn.disabled = false;
      btn.removeAttribute('aria-busy');
      btn.innerHTML = btnHtml;
    }
  }
}

/** One step per line, bullet/number prefix stripped. */
function _linesOf(raw) {
  return raw
    ? raw.split('\n').map(s => s.replace(/^\s*(?:[-*]|\d+[.)])\s+/, '').trim()).filter(Boolean)
    : [];
}

/** Comma-separated list. */
function _csvOf(raw) {
  return raw ? raw.split(',').map(t => t.trim()).filter(Boolean) : [];
}

/** The Add-Skill form, read once, in one place.
 *
 * `P8-12`. The lint and the save ask the same question of the same eight
 * fields, so they read them through the same function. Two readers would be two
 * chances to disagree about whether the procedure box was empty, and the whole
 * point of linting before a save is that it is judging what the save will send.
 */
function _draftFromForm(m) {
  const v = (id) => m.el(id)?.value.trim() || '';
  const name = v('new-skill-name') || v('new-skill-title');
  const description = v('new-skill-description') || v('new-skill-title');
  return {
    name,
    description,
    category: v('new-skill-category') || 'general',
    when_to_use: v('new-skill-when') || v('new-skill-problem'),
    procedure: _linesOf(v('new-skill-procedure') || v('new-skill-solution')),
    tags: _csvOf(v('new-skill-tags')),
    pitfalls: _linesOf(v('new-skill-pitfalls')),
    verification: _linesOf(v('new-skill-verification')),
    platforms: _csvOf(v('new-skill-platforms')),
    requires_toolsets: _csvOf(v('new-skill-toolsets')),
  };
}

/** True when the form holds nothing worth judging. */
function _draftIsEmpty(draft) {
  return !draft.name && !draft.description && !draft.when_to_use
    && !draft.procedure.length && !draft.tags.length
    && !draft.pitfalls.length && !draft.verification.length;
}

// `P8-12`. The lint advises; it never gates. Every path through this file that
// runs it goes on to do what it was going to do — the panel is beside the Save
// button, not in front of it, and its own heading says so, because a person who
// sees red beside a button reasonably assumes the button is now refusing.
const _LINT_NEVER_BLOCKS = 'None of this stops you saving.';

function _renderLint(m, result, opts) {
  const panel = m.el('skill-lint-panel');
  if (!panel) return;
  const o = opts || {};
  const findings = Array.isArray(result && result.findings) ? result.findings : [];
  const counts = (result && result.counts) || {};
  const problems = Number(counts.problem) || 0;
  const advisories = Number(counts.advisory) || 0;

  if (!findings.length && !o.saved) {
    // Clean is worth saying out loud: silence reads as "the check did not run".
    panel.classList.remove('hidden');
    panel.replaceChildren(_el('div', 'skill-lint-head skill-lint-clean',
      'Nothing to fix — this has a name, a description, when to use it, steps, '
      + 'pitfalls, verification and tags.'));
    return;
  }

  panel.classList.remove('hidden');
  const kids = [];
  const parts = [];
  if (problems) parts.push(`${problems} ${problems === 1 ? 'problem' : 'problems'}`);
  if (advisories) parts.push(`${advisories} ${advisories === 1 ? 'suggestion' : 'suggestions'}`);
  const head = _el('div', 'skill-lint-head',
    // `P22-23`. With *Fix these with the model* below it, the line says so
    // rather than sending the person to the card for what this panel offers.
    (o.saved ? `Saved as a draft. ${parts.length ? parts.join(', ') + (o.name
      ? ' — fix them with the model below, or open its card to fix them by hand. '
      : ' — open its card to fix them. ') : ''}`
             : (parts.length ? parts.join(', ') + '. ' : ''))
    + (o.saved ? '' : _LINT_NEVER_BLOCKS));
  kids.push(head);

  for (const f of findings) {
    const severity = f && f.severity === 'problem' ? 'problem' : 'advisory';
    const row = _el('div', `skill-lint-finding skill-lint-${severity}`);
    row.appendChild(_el('span', 'skill-lint-field', (f && f.field) || 'skill'));
    // `message` then `fix`, in that order and visibly different: the first says
    // what is wrong, the second says what to type. A finding with only the
    // first is a complaint.
    row.appendChild(_el('span', 'skill-lint-message', (f && f.message) || ''));
    if (f && f.fix) row.appendChild(_el('span', 'skill-lint-fix', f.fix));
    kids.push(row);
  }
  // `P22-23`. Once the skill exists, the model can fix what the lint found —
  // `manage_skills action=improve`'s button. Before it is saved there is no
  // skill to rewrite, and the panel says only that nothing stops a save.
  if (o.saved && o.name && findings.length) {
    const fix = _el('button', 'doclib-card-text-btn doclib-card-action-btn skill-lint-fix-btn',
      'Fix these with the model');
    fix.type = 'button';
    fix.title = 'The model rewrites the skill to answer these findings. It cannot publish it '
      + 'or change who can use it, and the text it replaces is kept in History.';
    fix.addEventListener('click', () => _fixWithModel(m, o.name, fix));
    kids.push(fix);
  }
  panel.replaceChildren(...kids);
}

function _clearLint(m) {
  const panel = m.el('skill-lint-panel');
  if (!panel) return;
  panel.classList.add('hidden');
  panel.replaceChildren();
}

/**
 * Ask the server what is wrong with what is currently typed.
 *
 * `POST /api/skills/lint` runs `lint_skill` — the same function
 * `manage_skills action=lint` runs — and writes nothing. It is pure and makes
 * no model call, so it answers while somebody is still typing; that is the
 * whole reason `P8-12`'s premise correction moved the two `llm_call_async`
 * judges out of scope.
 *
 * Returns the result, or `null` when the check could not run. A failed lint is
 * silent by design: the check is advice, and an error toast for advice nobody
 * asked for would punish the person for the network.
 */
async function _runSkillLint(m, opts) {
  const draft = _draftFromForm(m);
  if (_draftIsEmpty(draft)) { _clearLint(m); return null; }
  try {
    const res = await fetch(`${API}/api/skills/lint`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(draft),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const result = await res.json();
    _renderLint(m, result, opts);
    return result;
  } catch (e) {
    return null;
  }
}

// `P8-02`. The four fields below were never a wiring gap — `SkillAddRequest`
// (routes/skills_routes.py:38) has taken `pitfalls`, `verification`,
// `platforms` and `requires_toolsets` all along, and the raw SKILL.md editor
// reaches every one of them. They were a `Law 15` failure: the only route to
// them was knowing the frontmatter format. So they go on the form that already
// posts to this endpoint. No second write path.
async function addSkill(m) {
  const draft = _draftFromForm(m);
  const { name, description, category, when_to_use: whenToUse,
          procedure, tags, pitfalls, verification, platforms,
          requires_toolsets } = draft;

  if (!description && !name) {
    uiModule.showError('Description (or name) is required');
    return;
  }

  // `P8-12`. The lint runs on the way past and the save does not wait on its
  // verdict beyond drawing it: `_runSkillLint` never throws, never returns
  // early, and no branch below reads the verdict. Someone saving a skill with
  // four problems gets the skill AND the list. It is drawn here rather than
  // after the POST so a save that fails still leaves the findings on screen.
  const lint = await _runSkillLint(m);

  try {
    const res = await fetch(`${API}/api/skills/add`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: name || undefined,
        description,
        category,
        when_to_use: whenToUse,
        procedure,
        tags,
        pitfalls,
        verification,
        platforms,
        requires_toolsets,
        status: 'draft',
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const added = await res.json().catch(() => ({}));
    const savedName = (added && added.skill && added.skill.name) || name;
    ['new-skill-name', 'new-skill-title', 'new-skill-description', 'new-skill-when',
     'new-skill-problem', 'new-skill-procedure', 'new-skill-solution', 'new-skill-tags',
     'new-skill-category', 'new-skill-pitfalls', 'new-skill-verification',
     'new-skill-platforms', 'new-skill-toolsets']
      .forEach(id => { const el = m.el(id); if (el) el.value = ''; });
    _clearDraftNote(m);
    // The form is empty again, so the findings have to say which skill they are
    // about or they read as a verdict on the blank form in front of them.
    if (lint) _renderLint(m, lint, { saved: true, name: savedName });
    await loadSkills();
    uiModule.showToast('Skill added (draft)');
  } catch (err) {
    uiModule.showError('Failed to add skill: ' + err.message);
  }
}

// ── scope: which skills the list shows — `P8-49` / `P8-50` ─────────────────

function _isBundled(sk) { return !!(sk && (sk.bundled || sk.source === 'bundled')); }

function _packageOf(name) {
  return _collections.packages.find(p => (p.skills || []).includes(name)) || null;
}

function _scopeNames(m) {
  const sc = m.scope;
  if (sc.kind === 'package' || sc.kind === 'section') {
    const p = _collections.packages.find(x => x.id === sc.id);
    if (!p) return null;
    if (sc.kind === 'package') return new Set(p.skills || []);
    const sec = (p.sections || []).find(x => x.id === sc.section);
    return sec ? new Set(sec.skills || []) : null;
  }
  if (sc.kind === 'group') {
    const g = _collections.groups.find(x => x.id === sc.id);
    return g ? new Set(g.skills || []) : null;
  }
  return null;
}

function _inScope(m, sk) {
  const kind = m.scope.kind;
  if (kind === 'all') return true;
  const name = sk.name || sk.id;
  if (kind === 'bundled') return _isBundled(sk);
  if (kind === 'mine') return !_isBundled(sk) && !_packageOf(name);
  const names = _scopeNames(m);
  // A package or group removed elsewhere leaves nothing to narrow to.
  return names ? names.has(name) : true;
}

function _setScope(m, scope, { render = true } = {}) {
  m.scope = (scope && typeof scope.kind === 'string') ? scope : { kind: 'all' };
  try { localStorage.setItem(m.scopeKey, JSON.stringify(m.scope)); } catch (_) {}
  if (!render) return;
  renderSkillsList(m);
  _renderSkillsSide(m);
}

function _scopeTitle(m) {
  const sc = m.scope;
  if (sc.kind === 'package' || sc.kind === 'section') {
    const p = _collections.packages.find(x => x.id === sc.id);
    const sec = p && sc.kind === 'section' ? (p.sections || []).find(x => x.id === sc.section) : null;
    return sec ? sec.title : (p ? p.title : '');
  }
  if (sc.kind === 'group') return (_collections.groups.find(x => x.id === sc.id) || {}).title || '';
  return '';
}

function _emptyListText(m) {
  const sc = m.scope;
  // `BRAIN-U-5`: a filter is said first — it is the reason, whatever the scope.
  if (_filtering(m) && skills.length) return 'No skills match this filter.';
  if (sc.kind === 'group') return `Nothing in “${_scopeTitle(m)}” yet. Add skills from a card's ⋯ → Groups.`;
  if (sc.kind === 'package' || sc.kind === 'section') return 'This package has no skills left here.';
  if (sc.kind === 'mine') return 'None yet. Skills you write, and the ones Pantheon drafts, appear here.';
  if (sc.kind === 'bundled') return 'No built-in skills on this install.';
  if ((m.el('skills-search')?.value || '').trim()) return 'No skill matches that search.';
  return 'No skills yet.';
}

// ── the sidebar — `P9-06` ────────────────────────────────────────────────────

function _sideHead(title, extra) {
  const h = document.createElement('div');
  h.className = 'skills-side-head';
  const t = document.createElement('span');
  t.textContent = title;
  h.appendChild(t);
  if (extra) h.appendChild(extra);
  return h;
}

function _sameScope(a, b) {
  return a.kind === b.kind && (a.id || '') === (b.id || '') && (a.section || '') === (b.section || '');
}

function _sideRow(m, { title, count, scope, hint = '', sub = false, toggle = null, menu = null }) {
  const row = document.createElement('div');
  row.className = 'skills-side-row' + (sub ? ' skills-side-sub' : '')
    + (_sameScope(scope, m.scope) ? ' is-active' : '')
    + (toggle && !toggle.on ? ' is-off' : '');
  const pick = document.createElement('button');
  pick.type = 'button';
  pick.className = 'skills-side-pick';
  if (hint) pick.title = hint;
  if (_sameScope(scope, m.scope)) pick.setAttribute('aria-current', 'true');
  const t = document.createElement('span');
  t.className = 'skills-side-title';
  t.textContent = title;
  const c = document.createElement('span');
  c.className = 'skills-side-count';
  c.textContent = String(count);
  pick.appendChild(t);
  pick.appendChild(c);
  pick.addEventListener('click', () => _setScope(m, scope));
  row.appendChild(pick);
  if (toggle) {
    const label = document.createElement('label');
    label.className = 'admin-switch skills-side-switch';
    label.title = toggle.on ? 'On' : 'Off';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = !!toggle.on;
    input.setAttribute('aria-label', `Use the skills in ${title}`);
    input.addEventListener('change', () => toggle.onChange(input.checked, input));
    const slider = document.createElement('span');
    slider.className = 'admin-slider';
    label.appendChild(input);
    label.appendChild(slider);
    row.appendChild(label);
  }
  if (menu) {
    const kb = document.createElement('button');
    kb.type = 'button';
    kb.className = 'skills-side-kebab';
    kb.setAttribute('aria-label', `More for ${title}`);
    kb.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>';
    kb.addEventListener('click', (e) => { e.stopPropagation(); _popMenu(kb, menu()); });
    row.appendChild(kb);
  }
  return row;
}

function _renderSkillsSide(m) {
  const side = m.el('skills-side');
  if (!side) return;
  // A scope whose package or group has gone is not a place to leave someone.
  if (['package', 'section', 'group'].includes(m.scope.kind) && !_scopeNames(m)) {
    m.scope = { kind: 'all' };
  }
  const bundled = skills.filter(_isBundled).length;
  const mine = skills.filter(sk => !_isBundled(sk) && !_packageOf(sk.name || sk.id)).length;
  side.replaceChildren();
  side.appendChild(_sideHead('Library'));
  side.appendChild(_sideRow(m, { title: 'All skills', count: skills.length, scope: { kind: 'all' } }));
  side.appendChild(_sideRow(m, {
    title: 'Yours', count: mine, scope: { kind: 'mine' },
    hint: 'Skills you wrote and skills Pantheon learned',
  }));
  if (bundled) {
    side.appendChild(_sideRow(m, {
      title: 'Built-in', count: bundled, scope: { kind: 'bundled' },
      hint: 'Shipped with Pantheon. Fork one to make a copy you can change.',
    }));
  }

  side.appendChild(_sideHead('Packages'));
  if (!_collections.packages.length) {
    const e = document.createElement('div');
    e.className = 'skills-side-empty';
    e.textContent = 'Import a skills.sh page or a GitHub repository under Add, and its skills arrive here together.';
    side.appendChild(e);
  }
  for (const p of _collections.packages) {
    const count = (p.skills || []).length;
    const src = p.source && p.source.owner ? `${p.source.owner}/${p.source.repo}` : '';
    side.appendChild(_sideRow(m, {
      title: p.title || p.id, count, scope: { kind: 'package', id: p.id },
      hint: [p.description, src && `From ${src}${p.version ? ` · version ${p.version}` : ''}`,
             p.mode === 'partial' ? 'Imported one skill at a time' : ''].filter(Boolean).join('\n'),
      toggle: { on: p.enabled !== false, onChange: (on, input) => _switchPackage(p, on, input) },
      menu: () => [
        { icon: _ICON.update, label: 'Update from GitHub', onClick: () => _updatePackage(p) },
        { icon: _ICON.del, label: `Remove package and its ${count} ${count === 1 ? 'skill' : 'skills'}`,
          danger: true, onClick: () => _removePackage(p, false) },
        { icon: _ICON.del, label: 'Remove package, keep its skills', onClick: () => _removePackage(p, true) },
      ],
    }));
    if ((p.sections || []).length > 1) {
      for (const sec of p.sections) {
        side.appendChild(_sideRow(m, {
          title: sec.title || sec.id, count: (sec.skills || []).length, sub: true,
          scope: { kind: 'section', id: p.id, section: sec.id }, hint: sec.description || '',
        }));
      }
    }
  }

  const add = document.createElement('button');
  add.type = 'button';
  add.className = 'skills-side-new';
  add.textContent = '+ New';
  add.title = 'Make a group';
  add.addEventListener('click', () => _newGroup(m, []));
  side.appendChild(_sideHead('Groups', add));
  if (!_collections.groups.length) {
    const e = document.createElement('div');
    e.className = 'skills-side-empty';
    e.textContent = 'Make a group to keep skills together. A skill can be in as many groups as you like and is still one skill — change it once, and every group has the change.';
    side.appendChild(e);
  }
  for (const g of _collections.groups) {
    const count = (g.skills || []).length;
    side.appendChild(_sideRow(m, {
      title: g.title || g.id, count, scope: { kind: 'group', id: g.id },
      toggle: { on: g.enabled !== false, onChange: (on, input) => _switchGroup(g, on, input) },
      menu: () => [
        { icon: _ICON.rename, label: 'Rename', onClick: () => _renameGroup(g) },
        { icon: _ICON.del, label: 'Delete group', danger: true, onClick: () => _deleteGroup(g) },
      ],
    }));
  }
}

// ── menus ────────────────────────────────────────────────────────────────────

function _placeMenu(menu, btn) {
  document.body.appendChild(menu);
  menu.style.zIndex = String(topPortalZ());
  const r = btn.getBoundingClientRect();
  menu.style.top = (r.bottom + 4) + 'px';
  menu.style.right = Math.max(6, window.innerWidth - r.right) + 'px';
  const mr = menu.getBoundingClientRect();
  if (mr.bottom > window.innerHeight - 6) menu.style.top = Math.max(6, r.top - mr.height - 4) + 'px';
  if (mr.left < 6) menu.style.right = Math.max(6, window.innerWidth - 6 - mr.width) + 'px';
  const mr2 = menu.getBoundingClientRect();
  if (mr2.bottom > window.innerHeight - 6) {
    menu.style.maxHeight = Math.max(80, window.innerHeight - 12 - mr2.top) + 'px';
    menu.style.overflowY = 'auto';
  }
  return bindMenuDismiss(menu, () => { menu.remove(); }, (ev) => !menu.contains(ev.target));
}

/** `items`: `[{ icon, label, onClick, danger, checked }]` — `checked` draws a
 *  tick column, for a menu that is a list of memberships. */
function _popMenu(btn, items) {
  document.querySelectorAll('.skill-kebab-menu').forEach(dismissOrRemove);
  const menu = document.createElement('div');
  menu.className = 'skill-kebab-menu';
  let close = () => menu.remove();
  for (const it of items) {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'skill-kebab-item' + (it.danger ? ' danger' : '');
    if (typeof it.checked === 'boolean') {
      item.setAttribute('role', 'menuitemcheckbox');
      item.setAttribute('aria-checked', it.checked ? 'true' : 'false');
      item.innerHTML = `<span class="skill-group-menu-check">${it.checked ? _svg(_ICON.check) : ''}</span>`;
    } else {
      item.innerHTML = it.icon ? _svg(it.icon) : '';
    }
    const label = document.createElement('span');
    label.textContent = it.label;
    item.appendChild(label);
    item.addEventListener('click', (e) => { e.stopPropagation(); close(); it.onClick(); });
    menu.appendChild(item);
  }
  close = _placeMenu(menu, btn);
}

// ── packages, groups, fork — the calls ───────────────────────────────────────

async function _skillsApi(method, path, body) {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

async function _refreshAfterCollections() {
  await _fetchCollections();
  _renderAll();
}

async function _switchPackage(p, on, input) {
  try {
    await _skillsApi('PATCH', `/api/skills/packages/${encodeURIComponent(p.id)}`, { enabled: on });
    uiModule.showToast(on ? `${p.title}: on` : `${p.title}: off — its skills are left out`);
  } catch (e) {
    if (input) input.checked = !on;
    uiModule.showError('Could not switch the package: ' + e.message);
    return;
  }
  await _refreshAfterCollections();
}

async function _switchGroup(g, on, input) {
  try {
    await _skillsApi('PATCH', `/api/skills/groups/${encodeURIComponent(g.id)}`, { enabled: on });
    uiModule.showToast(on ? `${g.title}: on` : `${g.title}: off — its skills are left out`);
  } catch (e) {
    if (input) input.checked = !on;
    uiModule.showError('Could not switch the group: ' + e.message);
    return;
  }
  await _refreshAfterCollections();
}

async function _updatePackage(p) {
  uiModule.showToast(`Updating ${p.title} from GitHub…`);
  try {
    const data = await _skillsApi('POST', `/api/skills/packages/${encodeURIComponent(p.id)}/update`);
    const fresh = (data.installed || []).length;
    const again = (data.updated || []).length;
    const notes = Array.isArray(data.notes) ? data.notes : [];
    uiModule.showToast(`${p.title}: ${again} refreshed${fresh ? `, ${fresh} new` : ''}${notes.length ? ` — ${notes[0]}` : ''}`);
  } catch (e) {
    uiModule.showError(`Could not update ${p.title}: ${e.message}`);
    return;
  }
  _mdCache.clear();
  await loadSkills();
}

async function _removePackage(p, keepSkills) {
  const n = (p.skills || []).length;
  const q = keepSkills
    ? `Forget the package “${p.title}”? Its ${n} ${n === 1 ? 'skill stays' : 'skills stay'}, filed under Yours.`
    : `Remove “${p.title}” and delete its ${n} ${n === 1 ? 'skill' : 'skills'}? Import it again to get them back.`;
  if (!(await uiModule.styledConfirm(q, { confirmText: keepSkills ? 'Forget it' : 'Remove', danger: !keepSkills }))) return;
  try {
    await _skillsApi('DELETE', `/api/skills/packages/${encodeURIComponent(p.id)}${keepSkills ? '?keep_skills=true' : ''}`);
    uiModule.showToast(keepSkills ? `Forgot ${p.title}` : `Removed ${p.title}`);
  } catch (e) {
    uiModule.showError('Could not remove the package: ' + e.message);
    return;
  }
  for (const m of _allMounts()) if (m.scope.id === p.id) m.scope = { kind: 'all' };
  await loadSkills();
}

async function _newGroup(m, names) {
  const title = await uiModule.styledPrompt(
    names.length
      ? `Name a group for ${names.length === 1 ? `“${names[0]}”` : `these ${names.length} skills`}. They stay one skill each, wherever they are listed.`
      : 'Name the group. A skill can be in as many groups as you like and is still one skill.',
    { title: 'New group', placeholder: 'e.g. Design', confirmText: 'Make group', maxLength: 60 });
  if (!title || !String(title).trim()) return;
  try {
    const data = await _skillsApi('POST', '/api/skills/groups', { title: String(title).trim(), skills: names });
    uiModule.showToast(names.length ? `Made ${data.group.title} with ${names.length} ${names.length === 1 ? 'skill' : 'skills'}` : `Made ${data.group.title}`);
    if (!names.length) m.scope = { kind: 'group', id: data.group.id };
  } catch (e) {
    uiModule.showError(e.message);   // `BRAIN-M-8`: the server's sentence
    return;
  }
  if (m.selectMode && names.length) _exitSelectMode(m);
  await _refreshAfterCollections();
}

/** A skill's groups, or a selection's: tick to add, untick to take out. */
function _openGroupMenu(m, btn, names) {
  names = (names || []).filter(Boolean);
  if (!names.length) return;
  const items = _collections.groups.map(g => {
    const have = names.every(n => (g.skills || []).includes(n));
    return {
      label: g.title || g.id,
      checked: have,
      onClick: async () => {
        try {
          await _skillsApi('PATCH', `/api/skills/groups/${encodeURIComponent(g.id)}`,
                           have ? { remove: names } : { add: names });
          uiModule.showToast(have
            ? `Took ${names.length === 1 ? names[0] : `${names.length} skills`} out of ${g.title}`
            : `Added ${names.length === 1 ? names[0] : `${names.length} skills`} to ${g.title}`);
        } catch (e) {
          uiModule.showError('Could not change the group: ' + e.message);
          return;
        }
        await _refreshAfterCollections();
      },
    };
  });
  items.push({ icon: _ICON.group, label: 'New group…', onClick: () => _newGroup(m, names) });
  _popMenu(btn, items);
}

async function _renameGroup(g) {
  const title = await uiModule.styledPrompt('Rename the group. Its skills are not touched.',
    { title: 'Rename group', defaultValue: g.title || '', confirmText: 'Rename', maxLength: 60 });
  if (!title || !String(title).trim() || String(title).trim() === g.title) return;
  try {
    await _skillsApi('PATCH', `/api/skills/groups/${encodeURIComponent(g.id)}`, { title: String(title).trim() });
  } catch (e) {
    uiModule.showError('Could not rename the group: ' + e.message);
    return;
  }
  await _refreshAfterCollections();
}

async function _deleteGroup(g) {
  const n = (g.skills || []).length;
  if (!(await uiModule.styledConfirm(
    `Delete the group “${g.title}”? Its ${n} ${n === 1 ? 'skill is' : 'skills are'} not touched — a group only lists them.`,
    { confirmText: 'Delete group', danger: true }))) return;
  try {
    await _skillsApi('DELETE', `/api/skills/groups/${encodeURIComponent(g.id)}`);
  } catch (e) {
    uiModule.showError('Could not delete the group: ' + e.message);
    return;
  }
  for (const m of _allMounts()) if (m.scope.kind === 'group' && m.scope.id === g.id) m.scope = { kind: 'all' };
  await _refreshAfterCollections();
}

async function _forkSkill(m, name) {
  const title = await uiModule.styledPrompt(
    'Name the copy.',
    { title: 'Fork skill', defaultValue: `${name}-fork`, confirmText: 'Fork', maxLength: 80 });
  if (!title || !String(title).trim()) return;
  let made;
  try {
    made = (await _skillsApi('POST', `/api/skills/${encodeURIComponent(name)}/fork`, { name: String(title).trim() })).skill;
  } catch (e) {
    uiModule.showError(e.message);
    return;
  }
  uiModule.showToast(`Forked ${name} as ${made.name}`);
  await loadSkills();
  openSkill(made.name, { scope: { kind: 'mine' } }, m);
}

// ── `P22-23` · the actions only a terminal could reach ──────────────────────
//
// Draft from a description, *Fix these with the model*, History with *Put this
// back*, and Download. Each was a `manage_skills` action and nothing else
// (design § 0.9); each is now a route (`routes/skills_routes.py`) called from
// here, in whichever mount the person pressed it.

/** `skill-draft-status`: what the drafter did, said as text beside its box. */
function _draftNote(m, kind, text) {
  const el = m.el('skill-draft-status');
  if (!el) return;
  el.hidden = !text;
  el.className = `memory-desc skill-import-status${kind ? ` is-${kind}` : ''}`;
  el.textContent = text || '';
}

function _clearDraftNote(m) { _draftNote(m, '', ''); }

let _draftInFlight = false;

/** *Draft from a description*: `POST /api/skills/draft` fills the Add form.
 *  Nothing is saved — the person reads it and presses *Add Skill*. */
async function _draftFromDescription(m) {
  const box = m.el('skill-draft-text');
  const text = (box?.value || '').trim();
  if (!text) {
    _draftNote(m, 'error', 'Say what the skill is for first — one sentence is enough.');
    return;
  }
  if (_draftInFlight) return;
  _draftInFlight = true;
  const btn = m.el('skill-draft-btn');
  if (btn) { btn.disabled = true; btn.setAttribute('aria-busy', 'true'); }
  _draftNote(m, 'busy', 'Asking the model for a draft…');
  try {
    const res = await fetch(`${API}/api/skills/draft`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description: text }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    const d = data.draft || {};
    const put = (id, value) => { const el = m.el(id); if (el) el.value = value || ''; };
    put('new-skill-name', d.name);
    put('new-skill-description', d.description);
    put('new-skill-when', d.when_to_use);
    put('new-skill-procedure', (d.procedure || []).join('\n'));
    put('new-skill-category', d.category && d.category !== 'general' ? d.category : '');
    put('new-skill-tags', (d.tags || []).join(', '));
    put('new-skill-pitfalls', (d.pitfalls || []).join('\n'));
    put('new-skill-verification', (d.verification || []).join('\n'));
    if ((d.pitfalls || []).length || (d.verification || []).length) {
      const more = m.host.querySelector('details.skill-more');
      if (more) more.open = true;
    }
    _draftNote(m, 'ok', `Drafted by ${data.model || 'the model'}. Read it and change anything — `
      + 'nothing is saved until you press Add Skill.');
    _runSkillLint(m);
  } catch (err) {
    _draftNote(m, 'error', (err && err.message) || String(err));
  } finally {
    _draftInFlight = false;
    if (btn) { btn.disabled = false; btn.removeAttribute('aria-busy'); }
  }
}

/** *Fix these with the model*: `POST /api/skills/{name}/improve`, and the
 *  lint's counts before and after, in the panel the findings were in. */
async function _fixWithModel(m, name, btn) {
  const panel = m.el('skill-lint-panel');
  if (btn) { btn.disabled = true; btn.textContent = 'Fixing…'; }
  try {
    const res = await fetch(`${API}/api/skills/${encodeURIComponent(name)}/improve`, { method: 'POST' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    // `D-31` (P23-02). The server writes a rewrite only when it scores better
    // (`BRAIN-M-3`), so this line is only ever said of a real fix.
    const n = (c, k) => Number(c && c[k]) || 0;
    const line = data.outcome === 'nothing_to_fix'
      ? `Nothing left to fix in ${name}.`
      : `Fixed ${name}: problems ${n(data.before, 'problem')} → ${n(data.after, 'problem')}, `
        + `suggestions ${n(data.before, 'advisory')} → ${n(data.after, 'advisory')}. Undo in History.`;
    if (panel) {
      panel.classList.remove('hidden');
      panel.replaceChildren(_el('div', 'skill-lint-head skill-lint-fixed', line));
    }
    _mdCache.delete(name);
    await loadSkills();
  } catch (err) {
    if (btn) { btn.disabled = false; btn.textContent = 'Fix these with the model'; }
    const msg = (err && err.message) || String(err);
    if (panel) panel.appendChild(_el('div', 'skill-lint-finding skill-lint-problem', msg));
    else uiModule.showError(msg);
  }
}

function _when(seconds) {
  // `D-30` (P23-02): "3 Oct, 03:33", not "10/3/2026, 3:33:40 AM".
  return seconds ? new Date(seconds * 1000).toLocaleString(undefined, {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
  }) : '';
}

/** *History*: a skill's earlier copies, newest first, each with *View* and
 *  *Put this back* — `P8-11`'s rollback, reachable from the card at last. */
async function _showSkillHistory(card, name) {
  if (!card) return;
  if (!card.classList.contains('doclib-card-expanded')) await _expandSkillCard(card, name);
  const preview = card.querySelector('.skill-card-preview');
  if (!preview) return;
  if (card._testPoll) { clearInterval(card._testPoll); card._testPoll = null; }
  const wrap = _el('div', 'skill-test skill-history');
  preview.replaceChildren(wrap);
  wrap.appendChild(_el('div', 'skill-test-task', `History — ${name}`));
  const versions = await _fetchSkillVersions(name);
  if (!versions.length) {
    wrap.appendChild(_el('div', 'skill-test-meta',
      'No earlier copies yet. One is kept each time this skill is saved, so the next edit will be here.'));
    return;
  }
  const current = skills.find((s) => (s.name || s.id) === name) || {};
  wrap.appendChild(_el('div', 'skill-test-meta',
    `Earlier copies. Now: ${current.version || '—'}.`));
  const list = _el('div', 'skill-history-list');
  wrap.appendChild(list);
  const text = _el('pre', 'skill-md-pre skill-history-text');
  text.hidden = true;
  for (const v of versions) {
    const row = _el('div', 'skill-history-row');
    row.appendChild(_el('span', 'skill-history-when',
      `Saved ${_when(v.saved_at)} — was version ${v.version}`));
    const view = _el('button', 'doclib-card-text-btn doclib-card-action-btn', 'View');
    view.type = 'button';
    view.addEventListener('click', async (e) => {
      e.stopPropagation();
      try {
        const res = await fetch(`${API}/api/skills/${encodeURIComponent(name)}/versions/${encodeURIComponent(v.id)}`);
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        text.textContent = data.markdown || '';
      } catch (err) {
        text.textContent = `Could not read it: ${(err && err.message) || err}`;
      }
      text.hidden = false;
    });
    const back = _el('button', 'doclib-card-text-btn doclib-card-action-btn', 'Put this back');
    back.type = 'button';
    back.addEventListener('click', async (e) => {
      e.stopPropagation();
      const ok = await uiModule.styledConfirm(
        `Put back ${v.version} (${_when(v.saved_at)})? The current copy (${current.version || '—'}) stays in History.`,
        { confirmText: 'Put this back' });
      if (!ok) return;
      try {
        const res = await fetch(`${API}/api/skills/${encodeURIComponent(name)}/versions/${encodeURIComponent(v.id)}/restore`,
          { method: 'POST' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        _mdCache.delete(name);
        uiModule.showToast(`Restored ${v.version}. The old copy is in History.`);
        await loadSkills();
      } catch (err) {
        uiModule.showError(`Could not put it back: ${(err && err.message) || err}`);
      }
    });
    row.appendChild(view);
    row.appendChild(back);
    list.appendChild(row);
  }
  wrap.appendChild(text);
}

/** *Download*: the skill as `<name>.json` — `{skill, files}`, what an import
 *  reads back. A blob saved through a link the page makes, so nothing opens
 *  inline (the route answers `attachment` too). */
async function _downloadSkill(name) {
  try {
    const res = await fetch(`${API}/api/skills/${encodeURIComponent(name)}/export`);
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${name}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) {
    uiModule.showError(`Could not download ${name}: ${(err && err.message) || err}`);
  }
}

// ── the window — `P9-06` — and the room — `P22-21` ──────────────────────────

let _windowWired = false;

const _SKILLS_VIEWS = ['browse', 'add', 'settings'];

function _showSkillsView(m, view) {
  if (!m || !m.host || m.host === document.body) return;
  // `BRAIN-U-10` (P23-02): a third view, the skill settings.
  const want = _SKILLS_VIEWS.includes(view) ? view : 'browse';
  m.host.querySelectorAll('[data-skills-view]').forEach(tab => {
    const on = tab.getAttribute('data-skills-view') === want;
    tab.classList.toggle('active', on);
    tab.setAttribute('aria-selected', on ? 'true' : 'false');
    tab.tabIndex = on ? 0 : -1;
  });
  m.host.querySelectorAll('[data-skills-view-panel]').forEach(panel => {
    panel.classList.toggle('hidden', panel.getAttribute('data-skills-view-panel') !== want);
  });
  if (want === 'add') setTimeout(() => m.el('skill-import-url')?.focus(), 60);
}

function _wireSkillsWindow() {
  if (_windowWired) return;
  const modal = document.getElementById('skills-modal');
  if (!modal) return;
  _windowWired = true;
  document.getElementById('close-skills-modal')?.addEventListener('click', closeSkillsWindow);
  const content = modal.querySelector('.modal-content');
  const header = modal.querySelector('.modal-header');
  if (content && header) {
    import('./windowDrag.js').then(m => m.makeWindowDraggable(modal, {
      content, header, skipSelector: 'button, input, select, label',
      enableDock: true, enableLeftDock: true,
    })).catch(() => {});
  }
}

/** Open the Skills window on `view` ('browse' | 'add' | 'settings'), or bring
 *  it forward.
 *
 *  C-NAV (`P23-01` provides it; `P23-02` consumes it): `from` is the opener's
 *  window id and `tab` the opener's tab at that moment, both passed through to
 *  `Modals.showWindow`, which draws `← <opener>` in this window's header and
 *  re-raises the opener on that tab when this one closes. `showWindow` is the
 *  three cases this function used to spell out — minimized → restore, open →
 *  raise, closed → `openClosedWindow` — so without the other half (`from`
 *  ignored) nothing here behaves differently. */
export async function openSkillsWindow(view, { from = null, tab = null } = {}) {
  if (window.pantheonToolDoor && !window.pantheonToolDoor('brain')) return false;   // `P23-03`: the Brain's door
  const modal = document.getElementById('skills-modal');
  if (!modal) return false;
  _wireSkillsWindow();
  if (view) _showSkillsView(_windowMount(), view);
  try {
    const Modals = await import('./modalManager.js?v=20261009census');
    const nav = {};
    if (from) nav.from = from;
    if (from && tab != null) nav.tab = tab;
    Modals.showWindow('skills-modal', nav);
  } catch (_) {
    modal.classList.remove('hidden');
    modal.style.display = '';
  }
  loadSkills(true);
  return true;
}

export function closeSkillsWindow() {
  const modal = document.getElementById('skills-modal');
  if (!modal || modal.classList.contains('hidden')) return;
  const m = _windowMount();
  if (m.selectMode) _exitSelectMode(m);
  const content = modal.querySelector('.modal-content');
  const done = () => {
    modal.classList.add('hidden');
    if (content) content.classList.remove('modal-closing');
  };
  if (!content) { done(); return; }
  content.classList.add('modal-closing');
  content.addEventListener('animationend', done, { once: true });
  setTimeout(() => { if (!modal.classList.contains('hidden')) done(); }, 250);
}

/** Every control one mount holds, wired to that mount. Was this file's
 *  `DOMContentLoaded` handler, reaching each control by its page-wide id
 *  (`:3616-3674` when design § 2 measured it); `P22-21` gave it the mount, so
 *  the same lines wire the window and the room. */
function _wireMount(m) {
  if (m.wired) return;
  m.wired = true;
  const on = (id, type, fn) => { m.el(id)?.addEventListener(type, fn); };
  on('skill-import-url-btn', 'click', () => importSkillFromUrl(m));
  on('skill-import-url', 'keydown', (e) => {
    if (e.key === 'Enter') importSkillFromUrl(m);
  });
  on('add-skill-btn', 'click', () => addSkill(m));
  on('skills-search', 'input', () => renderSkillsList(m));
  // `BRAIN-U-5` (P23-02). Sort and filter are two selects now; one handler
  // reads either, by the prefix each option carries.
  const onSortOrFilter = (e) => {
    const v = e.target.value || '';
    if (v.startsWith('sort:')) {
      m.sort = v.slice(5);
    } else if (v.startsWith('filter:')) {
      const f = v.slice(7);
      if (f === 'all') { m.draftsOnly = false; m.publishedOnly = false; m.confMax = null; }
      else if (f === 'drafts') { m.draftsOnly = true; m.publishedOnly = false; m.confMax = null; }
      else if (f === 'published') { m.publishedOnly = true; m.draftsOnly = false; m.confMax = null; }
      else if (f.startsWith('conf')) { m.draftsOnly = false; m.publishedOnly = false; m.confMax = parseInt(f.slice(4), 10) || null; }
    }
    renderSkillsList(m);
  };
  on('skills-sort', 'change', onSortOrFilter);
  on('skills-filter', 'change', onSortOrFilter);
  on('skills-list', 'click', (e) => {
    if (e.target && e.target.closest && e.target.closest('[data-skills-clear-filter]')) _clearFilter(m);
  });
  on('skills-select-btn', 'click', () => {
    if (m.selectMode) _exitSelectMode(m); else _enterSelectMode(m);
  });
  on('skills-audit-btn', 'click', () => _auditAllSkills(m));
  on('skills-preview-btn', 'click', () => _renderPromptPreview(m));
  on('skills-select-all', 'change', () => _toggleSelectAll(m));
  on('skills-bulk-cancel', 'click', () => _exitSelectMode(m));
  on('skills-bulk-audit', 'click', () => _bulkAudit(m));
  on('skills-bulk-delete', 'click', () => _bulkDelete(m));
  on('skills-bulk-delete-nonpassing', 'click', () => _bulkDeleteNonPassing(m));
  on('skills-bulk-publish', 'click', () => _bulkApprove(m));
  on('skills-bulk-group', 'click', (e) => {
    _openGroupMenu(m, e.currentTarget, [...m.selected]);
  });
  on('new-skill-title', 'keydown', (e) => {
    if (e.key === 'Enter') addSkill(m);
  });
  on('new-skill-name', 'keydown', (e) => {
    if (e.key === 'Enter') addSkill(m);
  });
  // `P22-23`. *Draft from a description*, beside the form it fills.
  on('skill-draft-btn', 'click', () => _draftFromDescription(m));
  // `P8-12`. On blur, because that is the moment a person has finished saying
  // one thing and has not yet committed to the whole — early enough to be
  // advice, late enough not to be nagging at them mid-word. Every field is
  // wired, so the panel keeps up with whichever one they leave last.
  for (const id of ['new-skill-name', 'new-skill-description', 'new-skill-when',
                    'new-skill-procedure', 'new-skill-category', 'new-skill-tags',
                    'new-skill-pitfalls', 'new-skill-verification',
                    'new-skill-title', 'new-skill-problem', 'new-skill-solution']) {
    on(id, 'blur', () => { _runSkillLint(m); });
  }
  // The view tabs (Skills · Add) are this mount's own.
  if (m.host && m.host !== document.body) {
    const viewTabs = Array.from(m.host.querySelectorAll('[data-skills-view]'));
    viewTabs.forEach(tab => {
      tab.addEventListener('click', () => _showSkillsView(m, tab.getAttribute('data-skills-view')));
      // `BRAIN-U-8` (P23-02): one tab-strip behaviour in the three windows —
      // Left/Right (wrapping), Home/End; the view follows the focus.
      tab.addEventListener('keydown', (e) => {
        const keys = { ArrowLeft: -1, ArrowRight: 1, Home: 'first', End: 'last' };
        if (!(e.key in keys)) return;
        const i = viewTabs.indexOf(tab);
        const step = keys[e.key];
        const next = viewTabs[step === 'first' ? 0 : step === 'last' ? viewTabs.length - 1
          : (i + step + viewTabs.length) % viewTabs.length];
        e.preventDefault();
        _showSkillsView(m, next.getAttribute('data-skills-view'));
        try { next.focus(); } catch (_) {}
      });
    });
    m.host.addEventListener('focusin', () => { _lastMount = m; });
    m.host.addEventListener('pointerdown', () => { _lastMount = m; });
  }
}

// The window's body as the page shipped it, read before anything draws into
// it: the room is stamped from this, so the Skills markup has one source as
// well as the code (`Law 7`). Module scripts run after the page is parsed and
// before `DOMContentLoaded`, which is when this file first draws.
const _pristineBody = (() => {
  try {
    const body = document.getElementById('skills-modal')?.querySelector('.skills-modal-body');
    return body && typeof body.cloneNode === 'function' ? body.cloneNode(true) : null;
  } catch (_) { return null; }
})();

const _ID_REF_ATTRS = ['for', 'aria-labelledby', 'aria-describedby', 'aria-controls', 'list'];

/** Copy the window's markup into `host` with every id — and every attribute
 *  that names an id — given the room's prefix. */
function _stampRoom(host) {
  if (!_pristineBody) return false;
  const body = _pristineBody.cloneNode(true);
  const visit = (n) => {
    if (typeof n.getAttribute !== 'function') return;   // text
    if (n.id) n.id = ROOM_PREFIX + n.id;
    for (const a of _ID_REF_ATTRS) {
      const v = n.getAttribute(a);
      if (v) n.setAttribute(a, v.trim().split(/\s+/).map((x) => ROOM_PREFIX + x).join(' '));
    }
    for (const c of [...(n.childNodes || [])]) visit(c);
  };
  visit(body);
  host.replaceChildren(...body.childNodes);
  return true;
}

// `P22-21`. The *Skills enabled* switch at the head of the list belongs to
// `memory.js` (`syncPrefToggle`, by its page id), which reads and writes the
// `skills_enabled` preference. The room's copy is a second view of that one
// switch, not a second writer (`Law 14`): pressing it presses the window's, the
// window's moving moves it, and it dims the room's list the way `memory.js`
// dims the window's.
//
// `BRAIN-U-10` (P23-02). The skill settings moved into this window (a third
// view), so the room's stamp carries copies of them too, and they are mirrored
// the same way: each is pressed through the window's control, which
// `memory.js` owns, and the sentences it writes beside them are copied back.
const _MIRRORED = [
  ['skills-enabled-header-toggle', 'check'],
  ['auto-skills-toggle', 'check'],
  ['auto-approve-skills-toggle', 'check'],
  ['skill-confidence-slider', 'value'],
  ['skill-max-input', 'value'],
];
const _MIRRORED_TEXT = ['skill-confidence-label', 'skill-confidence-hint', 'skill-approve-coupling'];

function _mirrorSkillControls(m) {
  const pairs = _MIRRORED
    .map(([id, kind]) => ({ id, kind, mine: m.el(id), theirs: document.getElementById(id) }))
    .filter((p) => p.mine && p.theirs && p.mine !== p.theirs);
  if (!pairs.length) return () => {};
  const sync = () => {
    for (const p of pairs) {
      if (p.kind === 'check') p.mine.checked = !!p.theirs.checked;
      else p.mine.value = p.theirs.value;
    }
    for (const id of _MIRRORED_TEXT) {
      const mine = m.el(id), theirs = document.getElementById(id);
      if (mine && theirs && mine !== theirs) mine.textContent = theirs.textContent;
    }
    const sw = document.getElementById('skills-enabled-header-toggle');
    const list = m.el('skills-list');
    if (sw && list) list.style.opacity = sw.checked ? '' : '0.4';
  };
  for (const p of pairs) {
    for (const type of (p.kind === 'check' ? ['change'] : ['input', 'change'])) {
      p.mine.addEventListener(type, () => {
        if (p.kind === 'check') {
          if (p.theirs.checked !== p.mine.checked) {
            p.theirs.checked = p.mine.checked;
            p.theirs.dispatchEvent(new Event(type));
          }
        } else {
          p.theirs.value = p.mine.value;
          p.theirs.dispatchEvent(new Event(type));
        }
        sync();
      });
      p.theirs.addEventListener(type, sync);
    }
  }
  sync();
  return sync;
}

/**
 * `P22-21`. Mount the Skills views into `host` — the Workbench's Skills room.
 *
 * The first call stamps the window's markup into `host` (ids prefixed), makes
 * the mount and wires it; later calls find it. `view` ('browse' | 'add') and
 * `skill` (a name to open) are where to land. Returns the room's handle:
 * `shown()` when the room comes back into view (reload, as opening the window
 * does), `showView(view)`, `focusSkill(name)`.
 */
export function mountSkills(host, { view = null, skill = null } = {}) {
  if (!host) return null;
  let m = _mounts.find((x) => x.host === host);
  if (!m) {
    if (!_stampRoom(host)) return null;
    _windowMount();   // the window's mount is always the first
    m = _makeMount(host, { prefix: ROOM_PREFIX, scopeKey: _ROOM_SCOPE_KEY });
    _mounts.push(m);
    _wireMount(m);
    m.syncSwitch = _mirrorSkillControls(m);
  }
  const handle = {
    mount: m,
    shown() { m.syncSwitch?.(); return loadSkills(m); },
    showView(v) { _showSkillsView(m, v); },
    focusSkill(name) { if (name) openSkill(name, {}, m); },
  };
  if (view) handle.showView(view);
  if (skill) handle.focusSkill(skill);
  else handle.shown();
  return handle;
}

document.addEventListener('DOMContentLoaded', () => {
  _wireMount(_windowMount());
  // `P9-06`. Every "Open Skills" door — the Brain's launcher card and its Add
  // tab — is one delegated listener, so a door added later needs no wiring.
  // `P23-02`: a door inside another window opens Skills *from* it (C-NAV).
  document.addEventListener('click', (e) => {
    const door = e.target && e.target.closest && e.target.closest('[data-open-skills]');
    if (!door) return;
    const host = door.closest('.modal[id]');
    openSkillsWindow(door.getAttribute('data-open-skills') || 'browse', host ? { from: host.id } : {});
  });
});

export default { loadSkills, openSkill, openSkillsWindow, closeSkillsWindow, mountSkills };

// Populate the Skills badge on first load so the count is right before the
// user clicks into the tab. Cheap fetch — same as the lazy path.
document.addEventListener('DOMContentLoaded', () => { loadSkills(); });
