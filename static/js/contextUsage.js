// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/contextUsage.js
/**
 * `B892`. The context wheel, and the panel it opens.
 *
 * The owner's words: *"has the overall context usage in a wheel at the
 * bottom.. When interacted with, sections it out to the line - and you can see
 * the breakdown of what is using up the context in that window... then you can
 * drop down to elaborate even further by tokens of what is precisely using up
 * the context window."* And: *"the 'files' or 'attachments' context moves
 * here"*, labelled for what an attachment is, because *"attachments aren't
 * always documents.. Sometimes its code, and sometimes its photos"*.
 *
 * So this module draws three things from `GET /api/session/{id}/context`:
 *
 *   * **the wheel** — one ring, each category its own arc, beside the
 *     percentage. It sits in the composer (`#chat-context-pill`, which used
 *     to sit in the chat header);
 *   * **the panel** — how full the window is, one segmented bar, and one row
 *     per category with its tokens and share. Every row that has parts opens
 *     to list them: each tool, each skill, each attachment with its kind;
 *   * **the attachments section** — the files waiting to be sent, named for
 *     what they are, and the attachment allowance meter (`P12-09`,
 *     `fileHandler.renderContextMeter`), which is moved in here rather than
 *     drawn a second time (`Law 14`).
 *
 * The figures are the server's (`src/context_budget.py`,
 * `session_context_breakdown`). A category it could not measure — a chat that
 * has not had a reply yet has sent no system prompt — is drawn as "measured
 * on the next reply", never as a zero (`Law 10`). Tokens throughout; the one
 * figure in characters is the attachment allowance, and it says so.
 *
 * No imports: `chat.js` hands in what it has, and the tests drive this file
 * on its own.
 */

/** Category keys, in the order the server sends and the panel draws them. */
export const CATEGORY_KEYS = [
  'system', 'tools', 'skills', 'memory', 'retrieved', 'attachments', 'conversation',
];

/** What an attachment is, in the words the panel prints. */
export const KIND_LABELS = {
  image: 'Image',
  code: 'Code',
  text: 'Text',
  document: 'Document',
  spreadsheet: 'Spreadsheet',
  audio: 'Audio',
  file: 'File',
};

// The same lists `src/context_budget.py` (`attachment_kind`) classifies with,
// for a file that has not reached the server yet.
const IMAGE_EXT = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'heic', 'heif', 'tif', 'tiff', 'avif', 'ico'];
const AUDIO_EXT = ['mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac', 'opus'];
const SHEET_EXT = ['csv', 'tsv', 'xlsx', 'xls', 'ods', 'numbers'];
const DOCUMENT_EXT = ['pdf', 'docx', 'doc', 'odt', 'rtf', 'epub', 'pptx', 'ppt', 'odp', 'pages'];
const TEXT_EXT = ['txt', 'md', 'markdown', 'rst', 'log', 'text', 'adoc'];
const CODE_EXT = [
  'py', 'js', 'mjs', 'cjs', 'ts', 'tsx', 'jsx', 'java', 'kt', 'kts', 'c', 'h', 'cc', 'cpp',
  'cxx', 'hpp', 'hh', 'cs', 'go', 'rs', 'rb', 'php', 'swift', 'm', 'mm', 'scala', 'lua',
  'pl', 'pm', 'r', 'jl', 'sh', 'bash', 'zsh', 'fish', 'ps1', 'bat', 'cmd', 'sql', 'html',
  'htm', 'css', 'scss', 'sass', 'less', 'vue', 'svelte', 'json', 'jsonc', 'yaml', 'yml',
  'toml', 'ini', 'cfg', 'conf', 'xml', 'proto', 'graphql', 'gql', 'dart', 'ex', 'exs',
  'erl', 'hs', 'clj', 'elm', 'zig', 'nim', 'tf', 'gradle', 'cmake', 'mk', 'dockerfile',
  'ipynb',
];
const CODE_NAMES = ['dockerfile', 'makefile', 'cmakelists.txt', 'gemfile', 'rakefile',
  'procfile', 'jenkinsfile', 'vagrantfile'];

/** One of `KIND_LABELS`' keys, from a file's name and type. */
export function attachmentKind(name, mime = '') {
  const base = String(name || '').split(/[\\/]/).pop().toLowerCase();
  const dot = base.lastIndexOf('.');
  const ext = dot > 0 ? base.slice(dot + 1) : '';
  const type = String(mime || '').toLowerCase();
  if (IMAGE_EXT.includes(ext) || type.startsWith('image/')) return 'image';
  if (AUDIO_EXT.includes(ext) || type.startsWith('audio/')) return 'audio';
  if (SHEET_EXT.includes(ext) || type.includes('spreadsheet')
      || ['text/csv', 'text/tab-separated-values', 'application/vnd.ms-excel'].includes(type)) {
    return 'spreadsheet';
  }
  if (DOCUMENT_EXT.includes(ext) || type === 'application/pdf' || type.includes('wordprocessing')
      || type.includes('presentation') || type === 'application/epub+zip') {
    return 'document';
  }
  if (CODE_EXT.includes(ext) || CODE_NAMES.includes(base)) return 'code';
  if (TEXT_EXT.includes(ext) || type.startsWith('text/')) return 'text';
  return 'file';
}

/** 812 · 12.4K · 101.7K · 256K · 1.2M — the compact form the panel prints. */
export function formatTokens(n) {
  const v = Number(n);
  if (!Number.isFinite(v) || v < 0) return '?';
  if (v >= 1e6) return `${(v / 1e6).toFixed(v >= 1e7 ? 0 : 1).replace(/\.0$/, '')}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(v >= 1e5 ? 0 : 1).replace(/\.0$/, '')}K`;
  return String(Math.round(v));
}

function _formatBytes(n) {
  const v = Number(n);
  if (!Number.isFinite(v) || v <= 0) return '';
  if (v >= 1024 * 1024) return `${(v / (1024 * 1024)).toFixed(1)} MB`;
  if (v >= 1024) return `${Math.round(v / 1024)} KB`;
  return `${v} B`;
}

function _share(tokens, total) {
  if (!total || !Number.isFinite(Number(tokens))) return '';
  const pct = (Number(tokens) / total) * 100;
  if (pct > 0 && pct < 0.1) return '<0.1%';
  return `${pct.toFixed(pct >= 10 ? 0 : 1)}%`;
}

/** The window's figures, whichever shape the payload came in. */
export function usageFigures(data) {
  const d = data || {};
  const b = d.breakdown && typeof d.breakdown === 'object' ? d.breakdown : null;
  const total = Number(d.context_length || 0);
  const used = Number((b && b.used_tokens) || d.used_tokens || 0);
  const pct = b && Number.isFinite(Number(b.context_percent))
    ? Number(b.context_percent)
    : Number(d.context_percent || 0);
  const categories = b && Array.isArray(b.categories)
    ? b.categories.filter((c) => c && CATEGORY_KEYS.includes(c.key))
    : [];
  return {
    total, used, pct: Math.max(0, Math.min(100, pct)), categories,
    source: (b && b.source) || '',
    uncounted: (b && Array.isArray(b.uncounted)) ? b.uncounted : [],
  };
}

/**
 * The wheel as SVG markup: a faint track, then one arc per measured category
 * in its own colour, in order, each as long as its share of the window. With
 * no breakdown it is the single arc it always was.
 */
export function ringMarkup(data, { size = 16, stroke = 2 } = {}) {
  const { total, pct, categories } = usageFigures(data);
  const c = size / 2;
  const r = c - stroke / 2 - 0.5;
  const circ = 2 * Math.PI * r;
  const arcs = [];
  const measured = categories.filter((cat) => cat.measured !== false && Number(cat.tokens) > 0);
  if (total > 0 && measured.length) {
    let offset = 0;
    for (const cat of measured) {
      const len = Math.min(circ - offset, circ * (Number(cat.tokens) / total));
      if (len <= 0) break;
      arcs.push(`<circle class="ctx-ring-arc" data-key="${cat.key}" cx="${c}" cy="${c}" r="${r}" fill="none"`
        + ` stroke="var(--ctx-seg-${cat.key})" stroke-width="${stroke}"`
        + ` stroke-dasharray="${len.toFixed(2)} ${(circ - len).toFixed(2)}"`
        + ` stroke-dashoffset="${(-offset).toFixed(2)}" transform="rotate(-90 ${c} ${c})"/>`);
      offset += len;
    }
  } else if (pct > 0) {
    const len = circ * (pct / 100);
    arcs.push(`<circle class="ctx-ring-arc" cx="${c}" cy="${c}" r="${r}" fill="none"`
      + ` stroke="var(--ctx-stroke)" stroke-width="${stroke}"`
      + ` stroke-dasharray="${len.toFixed(2)} ${(circ - len).toFixed(2)}"`
      + ` transform="rotate(-90 ${c} ${c})"/>`);
  }
  return `<svg class="ctx-ring-svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true">`
    + `<circle class="ctx-ring-track" cx="${c}" cy="${c}" r="${r}" fill="none" stroke-width="${stroke}"/>`
    + arcs.join('')
    + '</svg>';
}

/** Draw the wheel into the composer's button, and say the same in words. */
export function renderPill(pill, data, { pendingCount = 0 } = {}) {
  if (!pill) return;
  const { total, used, pct } = usageFigures(data);
  const label = data ? `${pct.toFixed(pct >= 10 || pct === 0 ? 0 : 1)}%` : '';
  pill.innerHTML = ringMarkup(data)
    + `<span class="ctx-ring-pct" id="chat-context-pill-label">${label}</span>`;
  const parts = [];
  if (data) parts.push(`Context window: ${label} full, ~${formatTokens(used)} of ${formatTokens(total)} tokens`);
  if (pendingCount) parts.push(`${pendingCount} attachment${pendingCount === 1 ? '' : 's'} waiting to be sent`);
  pill.title = parts.join(' · ') || 'Context window';
  pill.setAttribute('aria-label', pill.title);
  pill.classList.toggle('has-pending', pendingCount > 0);
  pill.classList.remove('warn', 'danger');
  if (data && pct >= 85) pill.classList.add('danger');
  else if (data && pct >= 70) pill.classList.add('warn');
}

function _el(doc, tag, cls, text) {
  const n = doc.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = String(text);
  return n;
}

function _itemRow(doc, item, total) {
  const li = _el(doc, 'li', 'ctx-usage-item');
  const name = _el(doc, 'span', 'ctx-usage-item-name', item && item.name ? item.name : 'part');
  li.appendChild(name);
  if (item && item.kind) {
    li.appendChild(_el(doc, 'span', `ctx-usage-kind ctx-usage-kind-${item.kind}`,
      KIND_LABELS[item.kind] || KIND_LABELS.file));
  }
  if (item && item.count) {
    li.appendChild(_el(doc, 'span', 'ctx-usage-item-count', `×${Number(item.count).toLocaleString()}`));
  }
  const tokens = _el(doc, 'span', 'ctx-usage-item-tokens');
  if (item && item.uncounted) {
    tokens.textContent = 'not counted';
    tokens.title = 'The estimate reads text; pictures and audio are counted by the model, not here.';
  } else {
    tokens.textContent = formatTokens(item && item.tokens);
    tokens.title = `${Number((item && item.tokens) || 0).toLocaleString()} tokens · ${_share(item && item.tokens, total)}`;
  }
  li.appendChild(tokens);
  return li;
}

function _categoryRow(doc, cat, total) {
  const items = Array.isArray(cat.items) ? cat.items : [];
  const unmeasured = cat.measured === false;
  const row = _el(doc, items.length ? 'details' : 'div', 'ctx-usage-cat');
  row.dataset.key = cat.key;
  if (unmeasured) row.classList.add('unmeasured');
  const head = _el(doc, items.length ? 'summary' : 'div', 'ctx-usage-cat-head');
  const swatch = _el(doc, 'span', 'ctx-usage-swatch');
  swatch.dataset.key = cat.key;
  head.appendChild(swatch);
  let label = cat.label || cat.key;
  if (cat.key === 'tools' && cat.count) label += ` (${cat.count})`;
  head.appendChild(_el(doc, 'span', 'ctx-usage-cat-label', label));
  const tokens = _el(doc, 'span', 'ctx-usage-cat-tokens');
  const share = _el(doc, 'span', 'ctx-usage-cat-share');
  if (unmeasured) {
    tokens.textContent = '—';
    share.textContent = 'next reply';
    row.title = 'Measured when this chat gets its next reply: it is assembled per request and not stored in the chat.';
  } else {
    tokens.textContent = formatTokens(cat.tokens);
    share.textContent = _share(cat.tokens, total);
    tokens.title = `${Number(cat.tokens || 0).toLocaleString()} tokens`;
  }
  head.appendChild(tokens);
  head.appendChild(share);
  row.appendChild(head);
  if (items.length) {
    const list = _el(doc, 'ul', 'ctx-usage-items');
    items.forEach((item) => list.appendChild(_itemRow(doc, item, total)));
    row.appendChild(list);
  }
  return row;
}

function _pendingSection(doc, pending, meterHost) {
  const files = Array.isArray(pending) ? pending : [];
  const meterShown = !!(meterHost && !meterHost.hidden);
  if (!files.length && !meterShown) return null;
  const section = _el(doc, 'section', 'ctx-usage-attach');
  section.appendChild(_el(doc, 'div', 'ctx-usage-section-title', 'Attaching to this message'));
  if (files.length) {
    const list = _el(doc, 'ul', 'ctx-usage-items ctx-usage-pending');
    let pictures = 0;
    files.forEach((f) => {
      const kind = attachmentKind(f && f.name, f && f.mime);
      if (kind === 'image') pictures += 1;
      const li = _el(doc, 'li', 'ctx-usage-item');
      li.appendChild(_el(doc, 'span', 'ctx-usage-item-name', (f && f.name) || 'attachment'));
      li.appendChild(_el(doc, 'span', `ctx-usage-kind ctx-usage-kind-${kind}`, KIND_LABELS[kind]));
      li.appendChild(_el(doc, 'span', 'ctx-usage-item-tokens', _formatBytes(f && f.size)));
      list.appendChild(li);
    });
    section.appendChild(list);
    if (pictures) {
      section.appendChild(_el(doc, 'div', 'ctx-usage-note',
        pictures === 1
          ? 'The image is sent as a picture: it does not use the text allowance below.'
          : `The ${pictures} images are sent as pictures: they do not use the text allowance below.`));
    }
  }
  if (meterHost) {
    // `Law 14`: the allowance meter is `fileHandler`'s, moved, not redrawn.
    if (meterHost.parentNode) meterHost.parentNode.removeChild(meterHost);
    section.appendChild(meterHost);
  }
  return section;
}

/**
 * The panel. `data` is the `/context` payload or `null` (a new chat with
 * nothing sent yet); `pending` is `fileHandler.getPendingInfo()`; `meterHost`
 * is `#context-meter`, which the panel adopts for as long as it is open.
 */
export function buildUsagePanel(doc, data, { pending = [], meterHost = null } = {}) {
  const panel = _el(doc, 'div', 'ctx-usage');
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', 'Context window');
  const { total, used, pct, categories, source, uncounted } = usageFigures(data);

  const head = _el(doc, 'div', 'ctx-usage-head');
  head.appendChild(_el(doc, 'span', 'ctx-usage-title', 'Context window'));
  head.appendChild(_el(doc, 'span', 'ctx-usage-pct', data ? `${pct.toFixed(pct >= 10 || pct === 0 ? 0 : 1)}% full` : ''));
  panel.appendChild(head);

  if (data) {
    panel.appendChild(_el(doc, 'div', 'ctx-usage-sub',
      `~${formatTokens(used)} / ${formatTokens(total)} tokens`));

    const bar = _el(doc, 'div', 'ctx-usage-bar');
    bar.setAttribute('role', 'img');
    const described = [];
    categories.forEach((cat) => {
      if (cat.measured === false || !(Number(cat.tokens) > 0) || !total) return;
      const seg = _el(doc, 'span', 'ctx-usage-seg');
      seg.dataset.key = cat.key;
      seg.style.width = `${Math.min(100, (Number(cat.tokens) / total) * 100).toFixed(2)}%`;
      seg.title = `${cat.label}: ${formatTokens(cat.tokens)} tokens`;
      bar.appendChild(seg);
      described.push(`${cat.label} ${_share(cat.tokens, total)}`);
    });
    if (!described.length && pct > 0) {
      const seg = _el(doc, 'span', 'ctx-usage-seg');
      seg.style.width = `${pct}%`;
      bar.appendChild(seg);
    }
    bar.setAttribute('aria-label', `${pct}% of the window used${described.length ? `: ${described.join(', ')}` : ''}`);
    panel.appendChild(bar);

    const list = _el(doc, 'div', 'ctx-usage-list');
    categories.forEach((cat) => {
      if (cat.measured !== false && !(Number(cat.tokens) > 0) && !(cat.items || []).length) return;
      list.appendChild(_categoryRow(doc, cat, total));
    });
    if (total) {
      const free = _el(doc, 'div', 'ctx-usage-cat ctx-usage-free');
      const fh = _el(doc, 'div', 'ctx-usage-cat-head');
      fh.appendChild(_el(doc, 'span', 'ctx-usage-swatch ctx-usage-swatch-free'));
      fh.appendChild(_el(doc, 'span', 'ctx-usage-cat-label', 'Free space'));
      fh.appendChild(_el(doc, 'span', 'ctx-usage-cat-tokens', formatTokens(Math.max(0, total - used))));
      fh.appendChild(_el(doc, 'span', 'ctx-usage-cat-share', _share(Math.max(0, total - used), total)));
      free.appendChild(fh);
      list.appendChild(free);
    }
    panel.appendChild(list);

    const notes = [];
    if (uncounted.length) {
      const pictures = uncounted.filter((u) => u && u.kind === 'image').length;
      const clips = uncounted.length - pictures;
      const what = [];
      if (pictures) what.push(`${pictures} image${pictures === 1 ? '' : 's'}`);
      if (clips) what.push(`${clips} audio clip${clips === 1 ? '' : 's'}`);
      notes.push(`${what.join(' and ')} not counted — the estimate reads text.`);
    }
    if (source === 'history') {
      notes.push('System prompt, tools, skills and memory are measured when this chat gets its next reply.');
    } else if (source === 'last_request') {
      notes.push('Estimated. System prompt, tools, skills, memory and retrieved context are as the last reply sent them.');
    }
    notes.forEach((text) => panel.appendChild(_el(doc, 'div', 'ctx-usage-note', text)));
  } else {
    panel.appendChild(_el(doc, 'div', 'ctx-usage-sub', 'Nothing has been sent in this chat yet.'));
  }

  const attach = _pendingSection(doc, pending, meterHost);
  if (attach) panel.appendChild(attach);
  return panel;
}
