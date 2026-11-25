// SPDX-License-Identifier: AGPL-3.0-or-later
//
// apolloText.js — a lead's report, drawn as a report.
//
// A lead ends its run with Markdown (`**Built**`, `## Report`, `- a line`).
// Apollo's deck and a task's chat used to set that as plain text, so the
// person read the asterisks and hashes (owner's test, 2026-11-24: "this looks
// extremely sloppy"). This draws the few marks a report uses (headings, bullet
// and numbered lists, bold, inline code, fenced code) as elements. It builds
// nodes and sets text only: nothing a model wrote is ever parsed as HTML, so a
// lead's words can't put markup or script on the page.

function _el(tag, cls) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  return n;
}

/** Append `text` to `parent`, with `**bold**` and `` `code` `` as elements. */
export function inline(parent, text) {
  const s = String(text ?? '');
  const re = /(\*\*([^*]+)\*\*|`([^`]+)`)/g;
  let at = 0;
  let m;
  while ((m = re.exec(s)) !== null) {
    if (m.index > at) parent.appendChild(document.createTextNode(s.slice(at, m.index)));
    if (m[2] !== undefined) {
      const b = _el('strong');
      b.textContent = m[2];
      parent.appendChild(b);
    } else {
      const c = _el('code', 'apo-tx-code');
      c.textContent = m[3];
      parent.appendChild(c);
    }
    at = m.index + m[0].length;
  }
  if (at < s.length) parent.appendChild(document.createTextNode(s.slice(at)));
  return parent;
}

/** The blocks of a report: `{ kind: 'h'|'p'|'ul'|'ol'|'pre', text?, items? }`. */
export function blocks(text) {
  const lines = String(text ?? '').replace(/\r\n/g, '\n').split('\n');
  const out = [];
  let para = [];
  let list = null;
  const endPara = () => { if (para.length) { out.push({ kind: 'p', text: para.join(' ') }); para = []; } };
  const endList = () => { if (list) { out.push(list); list = null; } };
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (/^\s*```/.test(line)) {
      endPara(); endList();
      const code = [];
      i += 1;
      while (i < lines.length && !/^\s*```/.test(lines[i])) { code.push(lines[i]); i += 1; }
      out.push({ kind: 'pre', text: code.join('\n') });
      continue;
    }
    const h = /^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$/.exec(line);
    const lone = /^\s*\*\*([^*]+)\*\*\s*:?\s*$/.exec(line);
    const ul = /^\s*[-*•]\s+(.*)$/.exec(line);
    const ol = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (!line.trim()) { endPara(); endList(); continue; }
    if (h || lone) { endPara(); endList(); out.push({ kind: 'h', text: (h ? h[1] : lone[1]).trim() }); continue; }
    if (ul || ol) {
      endPara();
      const kind = ul ? 'ul' : 'ol';
      if (!list || list.kind !== kind) { endList(); list = { kind, items: [] }; }
      list.items.push((ul || ol)[1]);
      continue;
    }
    endList();
    para.push(line.trim());
  }
  endPara(); endList();
  return out;
}

/** Fill `container` with `text` drawn as a report. Returns the container. */
export function renderText(container, text) {
  container.textContent = '';
  container.classList.add('apo-tx');
  for (const b of blocks(text)) {
    if (b.kind === 'h') container.appendChild(inline(_el('p', 'apo-tx-h'), b.text));
    else if (b.kind === 'p') container.appendChild(inline(_el('p', 'apo-tx-p'), b.text));
    else if (b.kind === 'pre') {
      const pre = _el('pre', 'apo-tx-pre');
      pre.textContent = b.text;
      container.appendChild(pre);
    } else {
      const list = _el(b.kind, 'apo-tx-list');
      for (const item of b.items) list.appendChild(inline(_el('li'), item));
      container.appendChild(list);
    }
  }
  return container;
}
