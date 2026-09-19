// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/tasks/workflowDiagram.js
//
// `P8-34`. One workflow, drawn.
//
// **What this file is not.** It is not a drag-and-drop editor and it does not
// own a graph library. `P8-26` put the graph on the wire — `GET /api/tasks`
// answers `{ tasks, graph: { nodes, edges, conditions, max_depth } }`, derived
// from the two successor columns by `task_edges` (`src/task_scheduler.py:130`)
// — and Mermaid is already vendored at `static/lib/mermaid.min.js` with its
// licence recorded. `Law 14`: the renderer is `markdown.js:renderMermaid`
// (`:1035`), which loads the bundle on first use, finds
// `pre.mermaid:not([data-processed])` in a container and calls
// `mermaid.run({ nodes })`. Three surfaces already call it — `chatRenderer.js`,
// `document.js` and `slashCommands.js` — so this is a fourth caller and not a
// fourth renderer. Nothing here loads, initialises or configures Mermaid.
//
// **What it does own:** turning a graph document plus a set of tasks into the
// Mermaid source text, and the words around it. That is all pure — no DOM, no
// fetch, no module state — so the test drives these functions directly and
// then hands the result to the real vendored Mermaid to parse.
//
// **`P8-00` is the acceptance criterion and it drove three choices.**
//
//   1. **No colour.** Sixteen palettes ship and Mermaid draws its own SVG, so
//      a `classDef fill:#…` would be right in one theme and wrong in fifteen.
//      Every distinction here is a shape or a word: rectangle / rounded /
//      hexagon for prompt / research / action, and `paused` written into the
//      label of a task that is not running. It reads the same in every theme
//      and it survives being printed in black and white.
//   2. **The trigger is in the box.** A stranger looking at boxes and arrows
//      can see the order and cannot see what starts it, which is the first
//      thing they need. Every node with nothing pointing at it carries what
//      fires it — `Daily at 09:00`, `On document updated`, `Webhook`.
//   3. **The arrows are sentences.** `P8-28` gave the engine its first
//      conditional; the wire calls the two conditions `success` and `error`.
//      Those are the stored words and they stay stored. On the diagram they
//      are `if it works` and `if it fails`, which is the same fact in the
//      register of somebody who has never read this tracker.

/** The two edge conditions, as `build_task_graph` emits them, mapped to what a
 *  person reads on the arrow. Keyed by the wire's own word so a third
 *  condition added server-side shows up as itself rather than vanishing. */
export const EDGE_WORDS = Object.freeze({
  success: 'if it works',
  error: 'if it fails',
});

/** Node shape per `task_type`, as Mermaid spells it. */
const SHAPES = Object.freeze({
  llm: ['["', '"]'],
  research: ['(["', '"])'],
  action: ['{{"', '"}}'],
});

export const SHAPE_WORDS = Object.freeze([
  'Rectangle — a prompt sent to the model',
  'Rounded — a research run',
  'Hexagon — a built-in action',
]);

/**
 * Escape text for a **Mermaid** label. Not an HTML escaper.
 *
 * `B866` had just finished sweeping this tree for local HTML escapers that
 * escaped fewer characters than `ui.js:esc`, so the name here says which
 * grammar it is for and the comment says why it cannot be that one: Mermaid
 * labels are delimited by `"` inside a line of its own grammar, and the escape
 * it understands is a numeric or named entity introduced by `#` — `&quot;`
 * from an HTML escaper would be drawn literally, and an unescaped `"` ends the
 * label and turns the rest of a task's name into diagram syntax.
 *
 * `#` goes first, so a person who types `#quot;` into a task name sees
 * `#quot;` rather than a quotation mark. `<` and `>` matter because
 * `markdown.js` initialises Mermaid with `securityLevel: 'loose'`, under which
 * labels are rendered as HTML.
 */
export function mermaidText(value) {
  return String(value == null ? '' : value)
    .replace(/[\u0000-\u001f\u007f]+/g, ' ')
    .replace(/#/g, '#35;')
    .replace(/"/g, '#quot;')
    .replace(/</g, '#lt;')
    .replace(/>/g, '#gt;')
    .replace(/&/g, '#amp;')
    .trim();
}

/**
 * The workflow one task belongs to: its whole connected component, following
 * edges in both directions.
 *
 * Both directions on purpose. A person opens the task they were looking at,
 * and the thing they most need to know is often what runs *before* it — a
 * downstream-only walk would draw half a workflow and give no sign that the
 * other half exists.
 */
export function componentOf(graph, rootId) {
  const edges = (graph && graph.edges) || [];
  const byId = new Map(((graph && graph.nodes) || []).map((n) => [String(n.id), n]));
  const neighbours = new Map();
  const link = (a, b) => {
    if (!neighbours.has(a)) neighbours.set(a, new Set());
    neighbours.get(a).add(b);
  };
  for (const e of edges) {
    link(String(e.from), String(e.to));
    link(String(e.to), String(e.from));
  }

  const root = String(rootId);
  const seen = new Set([root]);
  const queue = [root];
  while (queue.length) {
    for (const next of neighbours.get(queue.shift()) || []) {
      if (!seen.has(next)) { seen.add(next); queue.push(next); }
    }
  }
  return {
    ids: seen,
    nodes: [...seen].map((id) => byId.get(id) || { id, missing: true }),
    edges: edges.filter((e) => seen.has(String(e.from))),
  };
}

/**
 * The longest chain in a component, and whether it is at the engine's cap.
 *
 * `build_task_graph` serves `max_depth` (`CHAIN_MAX_DEPTH`, 10) and nothing has
 * ever shown it to anybody, so a workflow that is one step from being refused
 * looks exactly like a workflow that is not. Counted with a visited set per
 * path so a cycle — which the engine refuses but a hand-edited database can
 * still hold — terminates instead of hanging the modal.
 */
export function longestChain(component) {
  const out = new Map();
  for (const e of component.edges) {
    const from = String(e.from);
    if (!out.has(from)) out.set(from, []);
    out.get(from).push(String(e.to));
  }
  let best = component.nodes.length ? 1 : 0;
  const walk = (id, depth, onPath) => {
    if (depth > best) best = depth;
    if (depth > 64) return;
    for (const next of out.get(id) || []) {
      if (onPath.has(next)) continue;
      onPath.add(next);
      walk(next, depth + 1, onPath);
      onPath.delete(next);
    }
  };
  for (const node of component.nodes) walk(String(node.id), 1, new Set([String(node.id)]));
  return best;
}

// **The theme directive that used to live here is gone, and that is the fix.**
//
// `P8-34` shipped a `themeDirective(scheme)` that this module prepended to
// every diagram it generated, because `markdown.js:94` pinned `theme: 'dark'`
// for all sixteen palettes and four of them are light. It said in its own
// comment that a per-surface workaround was not the fix, and reported the rest
// as `B872`.
//
// `B872` is now closed: `markdown/mermaidTheme.js` decides, `ensureMermaid`
// applies it, and all four callers of `renderMermaid` get it — so this module
// has nothing to say about colour at all any more. Leaving the directive in
// would be worse than redundant: a `%%{init: {"theme": …}}%%` line is applied
// per diagram and re-derives the whole theme from that one key, which would
// discard the stroke colour `applyMermaidTheme` puts on `nodeBorder` and hand
// this one surface a fainter outline than every other diagram in the product.
// One place decides (`Law 13`), and this is not it.
//
// What this module still owns is unchanged: shapes, words and arrows.

/**
 * The Mermaid source for one workflow.
 *
 * `view.nodes` is `[{ id, title, kind, trigger, detail, missing, focus }]` and
 * `view.edges` is the graph's own edges. The caller builds the words because
 * that is where the schedule wording and the action palette live
 * (`tasks.js:_scheduleLabel`, `P8-22`'s `/meta/actions`) — duplicating either
 * here would be the `Law 13` shape this phase keeps finding.
 *
 * Ids are minted (`n0`, `n1`, …) rather than carried through. A task id is a
 * database value and Mermaid node ids are grammar; minting removes the whole
 * question, and the map back out is returned for the caller that wants it.
 */
export function workflowMermaid(view) {
  const nodes = (view && view.nodes) || [];
  const edges = (view && view.edges) || [];
  const idFor = new Map();
  nodes.forEach((n, i) => idFor.set(String(n.id), 'n' + i));

  const lines = ['flowchart TD'];
  for (const node of nodes) {
    const [open, close] = SHAPES[node.kind] || SHAPES.llm;
    const label = [node.title, node.trigger, node.detail]
      .filter((part) => String(part || '').trim())
      .map(mermaidText)
      .join('<br/>');
    const classes = [];
    if (node.missing) classes.push('unseen');
    if (node.focus) classes.push('here');
    lines.push('  ' + idFor.get(String(node.id)) + open + label + close
      + (classes.length ? ':::' + classes.join(' ') : ''));
  }
  for (const edge of edges) {
    const from = idFor.get(String(edge.from));
    const to = idFor.get(String(edge.to));
    if (!from || !to) continue;
    const word = EDGE_WORDS[edge.when] || String(edge.when || '');
    const arrow = edge.when === 'error' ? '-.->' : '-->';
    lines.push('  ' + from + ' ' + arrow + (word ? '|"' + mermaidText(word) + '"|' : '') + ' ' + to);
  }
  // Stroke only — see the header. A dash pattern reads in every palette and in
  // print; a fill would be right in one of sixteen.
  lines.push('  classDef unseen stroke-dasharray: 4 3');
  lines.push('  classDef here stroke-width: 3px');
  return lines.join('\n');
}

/**
 * One sentence saying what the workflow does, for the person who came here
 * because the boxes were not enough.
 *
 * Built from the same component the diagram is, so the two cannot disagree.
 */
export function workflowSentence(view) {
  const nodes = (view && view.nodes) || [];
  const edges = (view && view.edges) || [];
  if (!nodes.length) return '';
  const byId = new Map(nodes.map((n) => [String(n.id), n]));
  const targeted = new Set(edges.map((e) => String(e.to)));
  const starts = nodes.filter((n) => !targeted.has(String(n.id)));
  const name = (id) => (byId.get(String(id)) || {}).title || 'a task you cannot see';

  if (!edges.length) {
    const only = nodes[0];
    return only.title + ' runs on its own'
      + (only.trigger ? ' — ' + only.trigger : '')
      + '. Nothing follows it, and nothing leads to it.';
  }
  const parts = [];
  for (const start of (starts.length ? starts : nodes.slice(0, 1))) {
    const outgoing = edges.filter((e) => String(e.from) === String(start.id));
    const success = outgoing.find((e) => e.when === 'success');
    const failure = outgoing.find((e) => e.when === 'error');
    let sentence = start.title + ' runs first';
    if (start.trigger) sentence += ' — ' + start.trigger;
    sentence += '.';
    if (success) sentence += ' If it works, ' + name(success.to) + ' runs next.';
    if (failure) sentence += ' If it fails, ' + name(failure.to) + ' runs instead.';
    if (!success && !failure) sentence += ' Nothing follows it.';
    parts.push(sentence);
  }
  return parts.join(' ');
}

export default {
  mermaidText, componentOf, longestChain, workflowMermaid,
  workflowSentence, EDGE_WORDS, SHAPE_WORDS,
};
