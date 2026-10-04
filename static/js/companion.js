// SPDX-License-Identifier: AGPL-3.0-or-later
// Pip is opt-in. Model events choose fixed local poses; only explicit user
// feedback is sent to the reply-feedback endpoint. Nothing here runs markup.
import Storage from './storage.js';
import { prefersReducedMotion } from './motion.js';

const KEY = 'pantheon-companion-enabled';
const POSES = Object.freeze({
  greet: { art: '  .---.\n / o o \\ \n|   ^   |\n \\_v_/\n   / \\', line: 'Glad you stopped by.' },
  cheer: { art: ' \\ .---. /\n  / ^ ^ \\ \n |  v   |\n  \\___/\n   / \\', line: 'Rooting for you.' },
  ponder: { art: '  .---.\n / o - \\ \n|   ?   |\n \\___/\n   / \\', line: 'Thinking it over.' },
  rest: { art: '  .---.\n / o o \\ \n|  \\_/  |\n \\_____/\n   / \\', line: 'Here for your next idea.' },
});
let resetTimer = null;
let feedbackSeq = 0;
let feedback = { sessionId: '', messageId: '', variantIndex: 0, excerpt: '', loading: false, saving: false,
  raw: '', contentDigest: '', editing: false, saved: null, error: '', status: '' };

const stageEl = () => document.getElementById('companion-stage');
const activeSession = () => typeof window === 'undefined' ? '' : (window.sessionModule?.getCurrentSessionId?.() || '');

function placeCompanion() {
  const stage = stageEl();
  const composer = document.querySelector?.('.chat-input-bar');
  if (!stage || stage.hidden || !composer || typeof window === 'undefined') return;
  stage.style.bottom = '';
  const pip = stage.getBoundingClientRect();
  const input = composer.getBoundingClientRect();
  if (pip.left < input.right && pip.right > input.left && pip.bottom > input.top && pip.top < input.bottom) {
    stage.style.bottom = `${Math.ceil(window.innerHeight - input.top + 12)}px`;
  }
}

export function isCompanionEnabled() {
  return Storage.get(KEY, 'off') === 'on';
}

function latestReply() {
  const sessionId = activeSession();
  if (!sessionId) return null;
  const replies = document.querySelectorAll('#chat-history .msg-ai[data-db-id]');
  const reply = replies[replies.length - 1];
  const messageId = reply?.dataset.dbId;
  if (!messageId) return null;
  const variantIndex = reply.dataset.variantIndex === undefined ? 0 : Number(reply.dataset.variantIndex);
  if (!Number.isSafeInteger(variantIndex) || variantIndex < 0) return null;
  const raw = String(reply.dataset.raw ?? reply.querySelector('.body')?.textContent ?? '');
  const excerpt = raw.trim();
  return { sessionId, messageId, variantIndex, raw,
    excerpt: excerpt.length > 62 ? `${excerpt.slice(0, 62)}...` : excerpt };
}

function renderFeedback() {
  const stage = stageEl();
  if (!stage) return;
  const hint = stage.querySelector('.companion-feedback-hint');
  const actions = stage.querySelector('.companion-feedback-actions');
  const form = stage.querySelector('.companion-feedback-form');
  const status = stage.querySelector('.companion-feedback-status');
  const retry = stage.querySelector('.companion-feedback-retry');
  const use = stage.querySelector('.companion-use-in-chat');
  const helpful = stage.querySelector('.companion-helpful');
  const offTrack = stage.querySelector('.companion-off-track');
  if (!hint || !actions || !form || !status || !retry || !use || !helpful || !offTrack) return;
  const ready = !!feedback.messageId && !feedback.loading && !feedback.error;
  if (!feedback.messageId) hint.textContent = 'No assistant reply to rate in this chat yet.';
  else if (feedback.loading) hint.textContent = 'Checking feedback for the latest reply...';
  else if (feedback.error) hint.textContent = feedback.error;
  else if (feedback.editing) hint.textContent = 'What would have made this reply better?';
  else if (feedback.saved) hint.textContent = feedback.saved.rating === 'helpful'
    ? 'Marked helpful for this reply.'
    : (feedback.saved.correction ? `Off track. Correction: ${feedback.saved.correction}` : 'Marked off track for this reply.');
  else hint.textContent = feedback.excerpt ? `Latest answer: “${feedback.excerpt}”` : 'Rate the latest saved answer in this chat.';
  actions.hidden = !ready || feedback.editing;
  form.hidden = !ready || !feedback.editing;
  retry.hidden = !feedback.error;
  use.hidden = !ready || !feedback.saved?.correction || feedback.saved.rating !== 'off_track' || feedback.editing;
  helpful.disabled = feedback.saving;
  offTrack.disabled = feedback.saving;
  form.querySelector('.companion-save-feedback').disabled = feedback.saving;
  helpful.setAttribute('aria-pressed', String(feedback.saved?.rating === 'helpful'));
  offTrack.setAttribute('aria-pressed', String(feedback.saved?.rating === 'off_track'));
  status.textContent = feedback.status;
  placeCompanion();
}

export async function syncCompanionFeedback(force = false) {
  if (!isCompanionEnabled()) return;
  const target = latestReply();
  if (!force && target?.sessionId === feedback.sessionId && target?.messageId === feedback.messageId
      && target?.variantIndex === feedback.variantIndex) return;
  const seq = ++feedbackSeq;
  feedback = { sessionId: target?.sessionId || '', messageId: target?.messageId || '',
    variantIndex: target?.variantIndex ?? 0,
    excerpt: target?.excerpt || '', raw: '', contentDigest: '', loading: !!target, saving: false, editing: false,
    saved: null, error: '', status: '' };
  renderFeedback();
  if (!target) return;
  try {
    const url = `/api/session/${encodeURIComponent(target.sessionId)}/message/${encodeURIComponent(target.messageId)}/feedback?variant_index=${target.variantIndex}`;
    const res = await fetch(url, { credentials: 'same-origin' });
    if (!res.ok) throw new Error(res.status === 409 ? 'Reply changed. Open the latest reply and retry.' : 'Feedback is unavailable. Retry when connected.');
    const data = await res.json();
    if (seq !== feedbackSeq || !isCompanionEnabled()) return;
    if (data.content !== target.raw || !/^[0-9a-f]{64}$/.test(data.content_digest))
      throw new Error('Reply changed. Reopen this chat to rate the current answer.');
    feedback.raw = data.content;
    feedback.contentDigest = data.content_digest;
    feedback.saved = data.rating ? { rating: data.rating, correction: data.correction || '' } : null;
    feedback.loading = false;
  } catch (error) {
    if (seq !== feedbackSeq || !isCompanionEnabled()) return;
    feedback.loading = false;
    feedback.error = error.message?.startsWith('Reply changed')
      ? error.message : 'Feedback is unavailable. Retry when connected.';
  }
  renderFeedback();
}

async function submitFeedback(rating, correction = '') {
  if (!isCompanionEnabled() || feedback.loading || feedback.saving || !feedback.messageId
      || !feedback.contentDigest || feedback.error) return;
  const current = latestReply();
  if (!current || current.sessionId !== feedback.sessionId || current.messageId !== feedback.messageId
      || current.variantIndex !== feedback.variantIndex) {
    syncCompanionFeedback(true);
    return;
  }
  const seq = feedbackSeq;
  if (current.raw !== feedback.raw) {
    syncCompanionFeedback(true);
    return;
  }
  feedback.saving = true;
  feedback.status = 'Saving feedback...';
  renderFeedback();
  try {
    const url = `/api/session/${encodeURIComponent(current.sessionId)}/message/${encodeURIComponent(current.messageId)}/feedback`;
    const res = await fetch(url, { method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rating, correction,
        variant_index: current.variantIndex, content_digest: feedback.contentDigest }) });
    if (res.status === 409) {
      if (seq === feedbackSeq) {
        await syncCompanionFeedback(true);
        feedback.status = 'Reply changed. Check the current answer before rating.';
        renderFeedback();
      }
      return;
    }
    if (!res.ok) throw new Error('Could not save feedback. Retry when connected.');
    const data = await res.json();
    if (seq !== feedbackSeq || !isCompanionEnabled()) return;
    feedback.saved = { rating: data.rating, correction: data.correction || '' };
    feedback.editing = false;
    feedback.status = 'Feedback saved for this reply. No model request sent.';
  } catch (error) {
    if (seq !== feedbackSeq || !isCompanionEnabled()) return;
    feedback.status = 'Could not save feedback. Retry when connected.';
  } finally {
    if (seq === feedbackSeq) {
      feedback.saving = false;
      renderFeedback();
    } else if (isCompanionEnabled()) {
      // A reply/variant switch may have loaded feedback before this write
      // finished. Recheck the currently displayed answer after it settles.
      syncCompanionFeedback(true);
    }
  }
}

function useCorrectionInChat() {
  const current = latestReply();
  if (!current || current.sessionId !== feedback.sessionId || current.messageId !== feedback.messageId
      || current.variantIndex !== feedback.variantIndex) {
    syncCompanionFeedback(true);
    return;
  }
  const input = document.getElementById('message');
  if (!input || !feedback.saved?.correction) return;
  if (input.value.trim()) {
    feedback.status = 'Finish your current draft before using this correction.';
  } else {
    input.value = `About your last reply: ${feedback.saved.correction}`;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.focus();
    feedback.status = 'Correction is in the composer. Press Send to tell the model.';
  }
  renderFeedback();
}

function renderEnabled() {
  const stage = stageEl();
  const toggle = document.getElementById('companion-toggle');
  const enabled = isCompanionEnabled();
  if (stage) stage.hidden = !enabled;
  if (toggle) toggle.checked = enabled;
  if (!enabled) {
    ++feedbackSeq;
    if (resetTimer) clearTimeout(resetTimer);
    resetTimer = null;
    feedback = { sessionId: '', messageId: '', variantIndex: 0, excerpt: '', loading: false, saving: false,
      raw: '', contentDigest: '', editing: false, saved: null, error: '', status: '' };
  } else {
    syncCompanionFeedback(true);
  }
}

export function setCompanionEnabled(enabled) {
  Storage.set(KEY, enabled ? 'on' : 'off');
  renderEnabled();
  if (enabled) companionAction('rest');
}

export function companionAction(action) {
  if (!isCompanionEnabled() || !Object.hasOwn(POSES, action)) return false;
  const stage = stageEl();
  const art = stage?.querySelector('.companion-art');
  const line = stage?.querySelector('.companion-line');
  if (!art || !line) return false;
  if (resetTimer) clearTimeout(resetTimer);
  resetTimer = null;
  art.textContent = POSES[action].art;
  line.textContent = POSES[action].line;
  stage.dataset.pose = action;
  if (action !== 'rest') {
    resetTimer = setTimeout(() => {
      resetTimer = null;
      if (isCompanionEnabled()) companionAction('rest');
    }, prefersReducedMotion() ? 2500 : 5000);
  }
  return true;
}

export function initCompanion() {
  const toggle = document.getElementById('companion-toggle');
  const stage = stageEl();
  if (!toggle || !stage || toggle.dataset.bound === '1') return;
  toggle.dataset.bound = '1';
  toggle.addEventListener('change', () => setCompanionEnabled(toggle.checked));
  stage.querySelector('.companion-character')?.addEventListener('click', () => companionAction('greet'));
  stage.querySelector('.companion-cheer')?.addEventListener('click', () => companionAction('cheer'));
  stage.querySelector('.companion-rest')?.addEventListener('click', () => companionAction('rest'));
  stage.querySelector('.companion-hide')?.addEventListener('click', () => setCompanionEnabled(false));
  stage.querySelector('.companion-helpful')?.addEventListener('click', () => submitFeedback('helpful'));
  stage.querySelector('.companion-off-track')?.addEventListener('click', () => {
    feedback.editing = true;
    feedback.status = '';
    renderFeedback();
    const correction = stage.querySelector('#companion-correction');
    correction.value = feedback.saved?.rating === 'off_track' ? feedback.saved.correction : '';
    correction.focus();
  });
  stage.querySelector('.companion-feedback-form')?.addEventListener('submit', event => {
    event.preventDefault();
    submitFeedback('off_track', stage.querySelector('#companion-correction').value.trim());
  });
  stage.querySelector('.companion-cancel-feedback')?.addEventListener('click', () => {
    feedback.editing = false;
    feedback.status = '';
    renderFeedback();
  });
  stage.querySelector('.companion-feedback-retry')?.addEventListener('click', () => syncCompanionFeedback(true));
  stage.querySelector('.companion-use-in-chat')?.addEventListener('click', useCorrectionInChat);
  document.addEventListener('pantheon:session-changed', () => syncCompanionFeedback(true));
  document.addEventListener('pantheon:message-saved', () => syncCompanionFeedback(true));
  document.addEventListener('pantheon:reply-list-changed', () => syncCompanionFeedback(true));
  const composer = document.querySelector?.('.chat-input-bar');
  if (composer && typeof ResizeObserver !== 'undefined') new ResizeObserver(placeCompanion).observe(composer);
  if (typeof window !== 'undefined') window.addEventListener('resize', placeCompanion);
  renderEnabled();
  if (isCompanionEnabled()) companionAction('rest');
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initCompanion);
else initCompanion();
