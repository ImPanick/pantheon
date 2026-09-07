// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/agentDrafts.js

/**
 * Mail the agent composed and is holding, and the two buttons that end the
 * holding. `H01`.
 *
 * ── What this closes ───────────────────────────────────────────────────────
 * `agent_email_confirm` defaults to `True`, so `_send_email` does not SMTP —
 * it stages the message into `scheduled_emails` with `status='agent_draft'` and
 * a far-future `send_at` the poller never reaches. Three endpoints have existed
 * to complete the loop since before the fork. Nothing called them:
 *
 *     grep -rn "email/pending\|agent_draft" static/    →    nothing
 *
 * across 183 frontend files. And three separate places asserted a surface that
 * did not exist — the route comment ("these endpoints let the chat UI surface
 * them"), the stash docstring ("the chat UI can render as an approval card"),
 * and, worst, the model's own tool description, which tells the user their mail
 * "stages for the user to approve in the chat UI". So the agent told people
 * their email was waiting for them, on a screen nobody had built.
 *
 * The default arrived at the fork baseline and is in upstream too, so on every
 * install running it the backlog is as old as the install. That is why this is
 * a drainer and not just a notification: the drafts already staged have no chat
 * message left to attach a card to.
 *
 * ── Why it opens itself ────────────────────────────────────────────────────
 * The panel appears the moment a draft exists and it is not behind a tab, a
 * menu, or a badge. The entire failure being fixed is that data was held
 * somewhere nobody looked, so a fix that requires the user to look somewhere is
 * the same bug with a shorter path. Same dock as the queue panel (`P6-04`),
 * directly above the composer.
 *
 * ── Why the age is the headline ────────────────────────────────────────────
 * "47 drafts" does not say what is wrong. "Oldest: 11 months" does. The row's
 * gating question was *is this backlog a week or a year* precisely because the
 * answer changes what the user should do, so the answer is on the panel.
 *
 * ── Why the body is shown before you can approve ───────────────────────────
 * Approving sends real mail to a real person, composed by a model, possibly a
 * year ago. A card that showed only a subject line would be asking for a
 * signature on an unread document. Recipients — including **bcc** — are shown
 * for the same reason; the endpoint did not return them until this row, which
 * would have made the approval card hide the one field you most need to see.
 *
 * ── Why there is no "Approve all" ──────────────────────────────────────────
 * Discard is bulk, approve is not. A button that sends hundreds of year-old
 * model-composed emails to real people in one press is the auto-send hole
 * `agent_email_confirm` exists to close, rebuilt with a dialog in front of it.
 * Each approval is a separate decision about a separate recipient.
 *
 * No `innerHTML` anywhere below: every draft field is attacker-adjacent text —
 * a subject line and a body the model wrote from content that arrived by email.
 */

const POLL_MS = 60000;
const PREVIEW_CHARS = 400;

let _panel = null;
let _list = null;
let _count = null;
let _state = null;
let _hint = null;
let _foldBtn = null;
let _discardAll = null;
let _timer = null;
let _busy = new Set();
let _expanded = new Set();
let _lastCount = -1;

function _el(id) { return document.getElementById(id); }

function _bind() {
  if (_panel) return true;
  _panel = _el('agent-drafts-panel');
  if (!_panel) return false;
  _list = _el('agent-drafts-list');
  _count = _el('agent-drafts-count');
  _state = _el('agent-drafts-state');
  _hint = _el('agent-drafts-hint');
  _foldBtn = _el('agent-drafts-fold');
  _discardAll = _el('agent-drafts-discard-all');

  if (_foldBtn) {
    _foldBtn.addEventListener('click', () => {
      const body = _el('agent-drafts-body');
      if (!body) return;
      const folded = _panel.classList.toggle('queue-panel-folded');
      body.hidden = folded;
      _foldBtn.setAttribute('aria-expanded', folded ? 'false' : 'true');
    });
  }
  if (_discardAll) {
    _discardAll.addEventListener('click', _onDiscardAll);
  }
  return true;
}

/** Human age. Deliberately coarse above a day — nobody needs "11 months, 3
 *  days"; they need to know it is months. */
function _age(seconds) {
  if (seconds == null || !isFinite(seconds)) return '';
  const s = Math.max(0, Math.floor(seconds));
  const plural = (n, unit) => `${n} ${unit}${n === 1 ? '' : 's'} ago`;
  if (s < 90) return 'just now';
  const m = Math.floor(s / 60);
  if (m < 90) return plural(m, 'min');
  const h = Math.floor(m / 60);
  if (h < 36) return plural(h, 'hr');
  const d = Math.floor(h / 24);
  if (d < 60) return plural(d, 'day');
  const mo = Math.floor(d / 30);
  if (mo < 24) return plural(mo, 'month');
  return plural(Math.floor(d / 365), 'year');
}

function _row(draft) {
  const wrap = document.createElement('div');
  wrap.className = 'agent-draft-row';
  wrap.dataset.draftId = draft.id || '';

  const head = document.createElement('div');
  head.className = 'agent-draft-head';

  const subject = document.createElement('span');
  subject.className = 'agent-draft-subject';
  subject.textContent = draft.subject || '(no subject)';
  head.appendChild(subject);

  const age = document.createElement('span');
  age.className = 'agent-draft-age';
  age.textContent = _age(draft.age_seconds);
  head.appendChild(age);
  wrap.appendChild(head);

  // Recipients, every field that will actually receive it. `bcc` is here
  // because a blind copy you cannot see before pressing Send is worse than the
  // black hole this replaces.
  const to = document.createElement('div');
  to.className = 'agent-draft-to';
  const parts = [];
  if (draft.to_addr) parts.push(`To ${draft.to_addr}`);
  if (draft.cc) parts.push(`Cc ${draft.cc}`);
  if (draft.bcc) parts.push(`Bcc ${draft.bcc}`);
  to.textContent = parts.join('  ·  ') || 'No recipient';
  if (draft.bcc) to.classList.add('agent-draft-has-bcc');
  wrap.appendChild(to);

  const body = document.createElement('div');
  body.className = 'agent-draft-body';
  const full = String(draft.body || '');
  const isExpanded = _expanded.has(draft.id);
  body.textContent = isExpanded || full.length <= PREVIEW_CHARS
    ? full
    : full.slice(0, PREVIEW_CHARS) + '…';
  wrap.appendChild(body);

  const actions = document.createElement('div');
  actions.className = 'agent-draft-actions';

  if (full.length > PREVIEW_CHARS) {
    const more = document.createElement('button');
    more.type = 'button';
    more.className = 'agent-draft-more';
    more.textContent = isExpanded ? 'Show less' : 'Show full message';
    more.addEventListener('click', () => {
      if (_expanded.has(draft.id)) _expanded.delete(draft.id);
      else _expanded.add(draft.id);
      refresh();
    });
    actions.appendChild(more);
  }

  const spacer = document.createElement('span');
  spacer.className = 'agent-draft-spacer';
  actions.appendChild(spacer);

  const discard = document.createElement('button');
  discard.type = 'button';
  discard.className = 'agent-draft-discard';
  discard.textContent = 'Discard';
  discard.disabled = _busy.has(draft.id);
  discard.addEventListener('click', () => _act(draft.id, 'discard'));
  actions.appendChild(discard);

  const approve = document.createElement('button');
  approve.type = 'button';
  approve.className = 'agent-draft-approve';
  approve.textContent = 'Approve & send';
  approve.disabled = _busy.has(draft.id);
  approve.addEventListener('click', () => _act(draft.id, 'approve'));
  actions.appendChild(approve);

  wrap.appendChild(actions);
  return wrap;
}

async function _act(id, what) {
  if (!id || _busy.has(id)) return;
  _busy.add(id);
  refresh();
  try {
    const url = what === 'approve'
      ? `/api/email/pending/${encodeURIComponent(id)}/approve`
      : `/api/email/pending/${encodeURIComponent(id)}`;
    const res = await fetch(url, { method: what === 'approve' ? 'POST' : 'DELETE' });
    const data = await res.json().catch(() => ({}));
    if (!data || data.success !== true) {
      _say(data && data.error ? String(data.error) : 'That did not work. The draft is still here.');
      return;
    }
  } catch (e) {
    _say('Could not reach Pantheon. The draft is still here.');
    return;
  } finally {
    _busy.delete(id);
  }
  await refresh();
}

async function _onDiscardAll() {
  const n = _lastCount;
  if (n <= 0) return;
  // A real confirm: this is the one bulk action, and it is irreversible from
  // the UI even though the rows survive in the database.
  const ok = window.confirm(
    `Discard ${n} draft${n === 1 ? '' : 's'}?\n\n` +
    `Nothing is sent. The messages are marked cancelled and stop appearing here.`
  );
  if (!ok) return;
  try {
    const res = await fetch('/api/email/pending/discard-all', { method: 'POST' });
    const data = await res.json().catch(() => ({}));
    if (!data || data.success !== true) {
      _say('Could not discard them. Nothing was changed.');
      return;
    }
  } catch (e) {
    _say('Could not reach Pantheon. Nothing was changed.');
    return;
  }
  await refresh();
}

function _say(message) {
  if (_state) _state.textContent = message;
}

/**
 * The one sentence the panel exists to say. It is written out in words rather
 * than as a count because the failure being fixed is that a number nobody read
 * was the only signal — `pantheon_queue_depth{queue="agent_mail"}` has existed
 * since `P16-12` and told nobody anything.
 */
function _sentence(count, oldestSeconds) {
  if (count === 1) return 'Pantheon wrote this and is holding it. Nothing has been sent.';
  const age = _age(oldestSeconds);
  if (oldestSeconds != null && oldestSeconds > 7 * 86400) {
    return `Pantheon wrote these and is holding them — the oldest since ${age}. Nothing has been sent.`;
  }
  return 'Pantheon wrote these and is holding them. Nothing has been sent.';
}

export async function refresh() {
  if (!_bind()) return;
  let payload = null;
  try {
    const res = await fetch('/api/email/pending');
    if (!res.ok) throw new Error(String(res.status));
    payload = await res.json();
  } catch (e) {
    // A failed poll must not empty the panel: hiding held mail because one
    // request failed is the original bug in miniature.
    return;
  }
  const drafts = Array.isArray(payload && payload.pending) ? payload.pending : [];
  _lastCount = drafts.length;

  if (!drafts.length) {
    _panel.hidden = true;
    if (_list) _list.replaceChildren();
    return;
  }

  _panel.hidden = false;
  if (_count) _count.textContent = String(drafts.length);
  _say(_sentence(drafts.length, payload && payload.oldest_age_seconds));
  if (_discardAll) _discardAll.hidden = drafts.length < 2;
  if (_hint) {
    _hint.textContent = 'Approve sends it now. Discard marks it cancelled — it is not deleted.';
  }
  if (_list) {
    const rows = drafts.map(_row);
    _list.replaceChildren(...rows);
  }
}

export function start() {
  if (!_bind()) return;
  refresh();
  if (_timer) clearInterval(_timer);
  // `P15-10` — a self-rescheduling timeout rather than setInterval, so the tick
  // re-rolls instead of every install polling on the same grid.
  const tick = () => {
    _timer = setTimeout(() => { refresh(); tick(); },
                        POLL_MS + Math.random() * POLL_MS * 0.1);
  };
  tick();
}

export default { start, refresh };
