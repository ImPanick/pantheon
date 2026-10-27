// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `P26-09`. Collaborators on a design or a design system: who it is shared
// with (its owner invites an account by name as viewer, commenter or editor,
// and revokes), its notes with their authors, and who has it open.
//
// What the window shows follows the role the server answered, and the server
// decides every write by that same role (`src/design_access.py`) — a hidden
// button here is a convenience, never the control.

export const ROLE_WORDS = {
  viewer: 'can look at it',
  commenter: 'can comment on it',
  editor: 'can change it',
  owner: 'yours',
};

/** May a person with `role` do `what` ('note' | 'edit' | 'share')? The
 *  window's mirror of `design_access.RANK`, for what to draw. */
export function may(role, what) {
  const rank = { viewer: 1, commenter: 2, editor: 3, owner: 4 }[role] || 0;
  return rank >= ({ note: 2, edit: 3, share: 4 }[what] || 99);
}

/** The query string naming one design or system, the caller's own or shared. */
export function itemQuery(item) {
  const p = new URLSearchParams({ kind: item.kind, ref: item.ref });
  if (item.share) p.set('share', item.share);
  else if (item.project) p.set('project', item.project);
  return p.toString();
}

function _el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function _btn(cls, text, onClick, label) {
  const b = _el('button', cls, text);
  b.type = 'button';
  if (label) { b.title = label; b.setAttribute('aria-label', label); }
  b.addEventListener('click', (e) => { e.preventDefault(); onClick(e); });
  return b;
}

/** "Open now: you, bob" — or nothing when only the caller has it open. */
export function presenceLine(present, me) {
  const others = (present || []).filter((n) => n !== me);
  if (!others.length) return '';
  return `Open now: ${['you', ...others].join(', ')}`;
}

/**
 * Draw the collaborators' panel into `box`. `item`: { kind, ref, project?,
 * share?, role, owner, name }. `ctx`: { call, say, me, selected?() → selector,
 * onLeave(fn) }. Answers `{ refresh }`.
 */
export function drawCollab(box, item, ctx) {
  const wrap = _el('div', 'design-collab');
  box.appendChild(wrap);
  const who = _el('p', 'design-section-sub design-collab-who');
  const presence = _el('p', 'design-section-sub design-presence');
  presence.setAttribute('aria-live', 'polite');
  wrap.appendChild(who);
  wrap.appendChild(presence);
  if (item.role === 'owner') who.textContent = 'Yours. Share it with another account by name.';
  else who.textContent = `Shared with you by ${item.owner}: you ${ROLE_WORDS[item.role] || 'can look at it'}.`;

  // ── people (the owner's) ──
  if (item.role === 'owner') {
    wrap.appendChild(_el('h3', 'design-section-title', 'People'));
    const list = _el('ul', 'design-shares');
    wrap.appendChild(list);
    const form = _el('form', 'design-share-form');
    const name = document.createElement('input');
    name.type = 'text';
    name.placeholder = 'Account name';
    name.autocomplete = 'off';
    name.spellcheck = false;
    name.setAttribute('aria-label', 'Account to invite');
    const role = document.createElement('select');
    role.setAttribute('aria-label', 'What they may do');
    ['viewer', 'commenter', 'editor'].forEach((r) => {
      const o = document.createElement('option'); o.value = r; o.textContent = r[0].toUpperCase() + r.slice(1); role.appendChild(o);
    });
    role.value = 'commenter';
    const go = _el('button', 'design-btn', 'Invite');
    go.type = 'submit';
    form.appendChild(name);
    form.appendChild(role);
    form.appendChild(go);
    wrap.appendChild(form);
    const drawShares = async () => {
      const r = await ctx.call('GET', `/api/design/shares?${itemQuery(item)}`);
      list.textContent = '';
      if (!r.ok) { list.appendChild(_el('li', 'design-section-sub', r.sentence)); return; }
      if (!r.data.shares.length) list.appendChild(_el('li', 'design-section-sub', 'Nobody else yet.'));
      r.data.shares.forEach((s) => {
        const li = _el('li', 'design-share');
        li.appendChild(_el('span', 'design-share-name', s.invitee));
        const pick = document.createElement('select');
        pick.setAttribute('aria-label', `What ${s.invitee} may do`);
        ['viewer', 'commenter', 'editor'].forEach((x) => { const o = document.createElement('option'); o.value = x; o.textContent = x; pick.appendChild(o); });
        pick.value = s.role;
        pick.addEventListener('change', async () => {
          const u = await ctx.call('POST', '/api/design/shares', { kind: item.kind, project: item.project, ref: item.ref, invitee: s.invitee, role: pick.value });
          if (!u.ok) { ctx.say(u.sentence, { error: true }); return; }
          ctx.say(`${s.invitee} ${ROLE_WORDS[pick.value]} now.`);
        });
        li.appendChild(pick);
        li.appendChild(_btn('design-x', '×', async () => {
          const u = await ctx.call('DELETE', `/api/design/shares/${encodeURIComponent(s.id)}`);
          if (!u.ok) { ctx.say(u.sentence, { error: true }); return; }
          ctx.say(`${s.invitee} no longer has it.`);
          drawShares();
        }, `Stop sharing with ${s.invitee}`));
        list.appendChild(li);
      });
    };
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const r = await ctx.call('POST', '/api/design/shares', { kind: item.kind, project: item.project, ref: item.ref, invitee: name.value.trim(), role: role.value });
      if (!r.ok) { ctx.say(r.sentence, { error: true }); return; }
      ctx.say(`Shared with ${r.data.invitee}: they ${ROLE_WORDS[r.data.role]}. They find it under Shared with me.`);
      name.value = '';
      drawShares();
    });
    drawShares();
  }

  // ── notes ──
  wrap.appendChild(_el('h3', 'design-section-title', 'Notes'));
  const notes = _el('ol', 'design-notes');
  wrap.appendChild(notes);
  let add = null;
  if (may(item.role, 'note')) {
    add = _el('form', 'design-note-form');
    const text = document.createElement('textarea');
    text.rows = 2;
    text.placeholder = 'A note for the people working on it';
    text.setAttribute('aria-label', 'New note');
    const go = _el('button', 'design-btn', 'Add note');
    go.type = 'submit';
    add.appendChild(text);
    add.appendChild(go);
    add.addEventListener('submit', async (e) => {
      e.preventDefault();
      const selector = ctx.selected ? ctx.selected() : null;
      const body = { kind: item.kind, ref: item.ref, text: text.value };
      if (item.share) body.share = item.share; else body.project = item.project;
      if (selector) body.selector = selector;
      const r = await ctx.call('POST', '/api/design/notes', body);
      if (!r.ok) { ctx.say(r.sentence, { error: true }); return; }
      text.value = '';
      drawNotes();
    });
    wrap.appendChild(add);
  }
  async function drawNotes() {
    const r = await ctx.call('GET', `/api/design/notes?${itemQuery(item)}`);
    notes.textContent = '';
    if (!r.ok) { notes.appendChild(_el('li', 'design-section-sub', r.sentence)); return; }
    if (!r.data.notes.length) notes.appendChild(_el('li', 'design-section-sub', 'No notes yet.'));
    r.data.notes.forEach((n) => {
      const li = _el('li', 'design-note-item');
      const head = _el('div', 'design-note-head');
      head.appendChild(_el('strong', 'design-note-author', n.author === ctx.me ? 'You' : n.author));
      if (n.at) head.appendChild(_el('span', 'design-version-when', new Date(n.at).toLocaleString()));
      li.appendChild(head);
      if (n.selector) li.appendChild(_el('code', 'design-selector', n.selector));
      li.appendChild(_el('p', 'design-note-text', n.text));
      if (n.author === ctx.me || item.role === 'owner') {
        li.appendChild(_btn('design-x', '×', async () => {
          const u = await ctx.call('DELETE', `/api/design/notes/${encodeURIComponent(n.id)}?${itemQuery(item)}`);
          if (!u.ok) { ctx.say(u.sentence, { error: true }); return; }
          drawNotes();
        }, 'Remove this note'));
      }
      notes.appendChild(li);
    });
  }
  drawNotes();

  // ── presence: a beat while it is open ──
  const beat = async () => {
    const r = await ctx.call('POST', '/api/design/presence', { kind: item.kind, ref: item.ref, ...(item.share ? { share: item.share } : { project: item.project }) });
    if (r.ok) presence.textContent = presenceLine(r.data.present, ctx.me);
  };
  beat();
  const timer = setInterval(beat, 20_000);
  if (ctx.onLeave) ctx.onLeave(() => clearInterval(timer));
  return { refresh: drawNotes };
}

export default { drawCollab, may, itemQuery, presenceLine, ROLE_WORDS };
