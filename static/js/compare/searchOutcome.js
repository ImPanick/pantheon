// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/compare/searchOutcome.js

/**
 * `B492`. What one Compare search pane shows for one provider's answer — the
 * one place the three render sites (`index.js`'s parallel and sequential runs,
 * `panes.js`'s re-run) decide it, where each used to carry its own copy.
 *
 * A provider the outbound limiter is holding answers with `sync` (`{ source:
 * 'throttled', retry_in }`, `routes/search/search_routes.py`). It used to land
 * in the red `Error:` branch as the limiter's own sentence; it is a pause, not
 * a fault, and it says when it clears, in `runStatus.js`'s words — pressing
 * Search again is what deepens a rate limit.
 *
 * Imports only the words, so it runs under node as it runs in the page.
 */

import { syncNotice } from '../runStatus.js';

/** `{ kind: 'held' | 'error' | 'empty' | 'results', text }` for one answer. */
export function searchOutcome(data) {
  const d = data && typeof data === 'object' ? data : {};
  const held = syncNotice(d.sync, d.label || 'This search engine');
  if (held) return { kind: 'held', text: held };
  if (d.error) return { kind: 'error', text: `Error: ${d.error}` };
  if (!Array.isArray(d.results) || d.results.length === 0) return { kind: 'empty', text: 'No results found' };
  return { kind: 'results', text: '' };
}

const STYLE = {
  held: 'color:color-mix(in oklab, var(--fg) 70%, var(--fg-muted));font-size:0.85em;',
  error: 'color:var(--color-error);font-size:0.85em;',
  empty: 'color:color-mix(in oklab, var(--fg) 50%, var(--fg-muted));font-size:0.85em;font-style:italic;',
};

/**
 * The pane body's content for one answer, as a node. `renderResults` is
 * `stream.js:_renderSearchResults`, handed in. Text is set with
 * `textContent`: an error can carry a provider's own words.
 */
export function searchOutcomeNode(doc, data, renderResults) {
  const outcome = searchOutcome(data);
  if (outcome.kind === 'results') return renderResults(data);
  const node = doc.createElement('div');
  node.className = `compare-search-${outcome.kind}`;
  node.setAttribute('style', STYLE[outcome.kind]);
  if (outcome.kind === 'held') node.setAttribute('role', 'status');
  node.textContent = outcome.text;
  return node;
}

export default { searchOutcome, searchOutcomeNode };
