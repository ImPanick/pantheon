// SPDX-License-Identifier: AGPL-3.0-or-later
// `P13-07`. What the Brain's reading surface shows, as data.
//
// Reaches no DOM, for the reason `memoryFacts.js` reaches none: the surface's
// markup lives in `brainExplore.js` and the rule for *which memories match*
// has to be runnable without a browser. `B61`'s lesson is the whole argument —
// a helper can be perfect and the page still show nothing — so the part a test
// can execute is kept separate from the part that needs a browser.
//
// It imported nothing at all until `B710`, and the one import it has now is
// the exception that keeps the property: `memoryFacts.js` imports nothing
// either, so this file still runs under `node` with no DOM. The alternative
// was a second reading of `status`, whose default decides whether a memory
// that is reaching every chat is visible on a page (`Law 14`).
import { memoryStatus } from './memoryFacts.js';

/** Confidence bands, as the surface offers them.
 *
 *  `unrecorded` is a band and not an absence of one: "nobody assessed this"
 *  is a thing a reader goes looking for, and folding it into `low` would say
 *  the extractor was unsure when in fact it was never asked (`P13-01`).
 */
export const CONFIDENCE_BANDS = {
  any: () => true,
  high: (c) => typeof c === 'number' && c >= 0.8,
  medium: (c) => typeof c === 'number' && c >= 0.5 && c < 0.8,
  low: (c) => typeof c === 'number' && c < 0.5,
  unrecorded: (c) => typeof c !== 'number',
};

/** Age bands in days, open-ended at the top. */
export const AGE_BANDS = {
  any: null,
  week: 7,
  month: 30,
  quarter: 90,
};

export const EDGE_TYPES = ['supersedes', 'contradicts', 'derived_from', 'co_occurs'];

/** The statuses the surface offers, plus the two readings that are not one.
 *
 *  `B710`. The clause lives here and not in `memory.js` because **two surfaces
 *  read it** — the Brain list's chips and Explore's filter bar — and a status
 *  rule with two implementations is how one of them ends up showing a proposal
 *  as though it were binding (`Law 7`, `Law 14`). `memory.js` imports
 *  `matches` for exactly this clause rather than writing a second one.
 *
 *  `binding` is not a synonym for `committed` and the difference is the point:
 *  a reader asking *"what is actually reaching my chats"* is asking about an
 *  effect, and tomorrow a fourth status could have that effect or lose it. The
 *  question survives the vocabulary changing; `status === 'committed'` does
 *  not.
 */
export const STATUS_FILTERS = {
  any: () => true,
  binding: (status) => status === 'committed',
  proposed: (status) => status === 'proposed',
  archived: (status) => status === 'archived',
};

/** The filter nothing is filtered by — the surface's own starting state. */
export function emptyFilter() {
  return {
    query: '', project: 'any', confidence: 'any', category: 'any',
    age: 'any', session: 'any', edge: 'any', status: 'any',
  };
}

/** Whether `memory` survives `filter`, with `now` in seconds.
 *
 *  Every clause is an **and**, and every clause's `any` is a pass — so the
 *  starting filter returns the whole corpus rather than nothing, which is the
 *  difference between a page that opens full and one that opens empty and
 *  makes a reader guess which control to touch first (`Law 15`).
 *
 *  `older` is deliberately absent from `AGE_BANDS`: every band here is "within
 *  the last N days", because a reader looking for something stale is looking
 *  for a *memory* and uses the search, while a reader narrowing to the last
 *  week is narrowing a list. One direction, so the control cannot be read
 *  backwards.
 */
export function matches(memory, filter, now) {
  if (!memory || typeof memory !== 'object') return false;
  const f = { ...emptyFilter(), ...(filter || {}) };

  const query = String(f.query || '').trim().toLowerCase();
  if (query) {
    // The text, and the project's name — a reader typing a project's name into
    // the search box means the project, and sending them to the dropdown
    // instead is the "thing you spot in a cloud" this row replaces.
    const haystack = [memory.text, memory.project_label, memory.project]
      .map((part) => String(part || '').toLowerCase()).join(' \u0000 ');
    if (!haystack.includes(query)) return false;
  }

  if (f.project !== 'any') {
    const slug = memory.project || null;
    if (f.project === 'none' ? slug !== null : slug !== f.project) return false;
  }

  const band = CONFIDENCE_BANDS[f.confidence] || CONFIDENCE_BANDS.any;
  if (!band(typeof memory.confidence === 'number' ? memory.confidence : null)) return false;

  if (f.category !== 'any' && (memory.category || 'fact') !== f.category) return false;
  if (f.session !== 'any' && (memory.session_id || null) !== f.session) return false;

  // `B710`. `memoryStatus` and not a second reading of the field: the default
  // for an unrecognised value is load-bearing in a direction (`committed`,
  // because a record that stops binding is wrong and invisible), and a filter
  // that defaulted the other way would hide memories that are reaching every
  // chat. One rule, one place, both surfaces (`Law 7`).
  const statusTest = STATUS_FILTERS[f.status] || STATUS_FILTERS.any;
  if (!statusTest(memoryStatus(memory))) return false;

  const days = AGE_BANDS[f.age];
  if (days) {
    const stamp = Number(memory.timestamp || 0);
    // A memory with no timestamp fails an age filter rather than passing it:
    // an unknown age is not "recent", and letting it through would put the
    // oldest records in the "last week" list.
    if (!stamp) return false;
    if ((Number(now || 0) - stamp) / 86400 > days) return false;
  }

  if (f.edge !== 'any') {
    const edges = Array.isArray(memory.edges) ? memory.edges : [];
    if (f.edge === 'none') {
      if (edges.length) return false;
    } else if (!edges.some((e) => e && e.type === f.edge)) {
      return false;
    }
  }
  return true;
}

/** `{shown, total}` plus the surviving rows, in one pass. */
export function apply(memories, filter, now) {
  const rows = Array.isArray(memories) ? memories : [];
  const kept = rows.filter((m) => matches(m, filter, now));
  return { rows: kept, shown: kept.length, total: rows.length };
}

/** Whether anything is narrowed, so the surface knows to offer *Clear*. */
export function isNarrowed(filter) {
  const base = emptyFilter();
  return Object.keys(base).some((key) => {
    const value = (filter || {})[key];
    if (key === 'query') return String(value || '').trim() !== '';
    return value !== undefined && value !== base[key];
  });
}

/** The sessions a corpus mentions, newest first, as `{id, memories, newest}`.
 *
 *  Built from the corpus rather than fetched: the session filter can only
 *  usefully offer sessions some memory came from, and a list of every session
 *  that ever existed would be mostly empty options.
 */
export function sessionIndex(memories) {
  const found = new Map();
  for (const memory of Array.isArray(memories) ? memories : []) {
    if (!memory || typeof memory !== 'object') continue;
    const id = memory.session_id;
    if (!id) continue;
    const stamp = Number(memory.timestamp || 0);
    const known = found.get(id);
    if (!known) found.set(id, { id, memories: 1, newest: stamp });
    else {
      known.memories += 1;
      if (stamp > known.newest) known.newest = stamp;
    }
  }
  return [...found.values()].sort((a, b) => b.newest - a.newest);
}

/** How fresh this reading is, in one sentence.
 *
 *  `P13-07` asks the surface to *"state plainly how fresh the analysis is"*,
 *  and two different facts are needed to do that honestly: when the page last
 *  read the store, and how old the newest thing in it is. A page that says
 *  only the first is claiming freshness it cannot vouch for; one that says
 *  only the second cannot tell a reader their view is stale.
 */
export function freshness(memories, { readAt, projects } = {}) {
  const rows = Array.isArray(memories) ? memories : [];
  const stamps = rows.map((m) => Number((m || {}).timestamp || 0)).filter(Boolean);
  return {
    memories: rows.length,
    projects: Number(projects || 0),
    newest: stamps.length ? Math.max(...stamps) : null,
    readAt: Number(readAt || 0) || null,
  };
}
