// SPDX-License-Identifier: AGPL-3.0-or-later
/** Build a terminal stream error while preserving provider-supplied text. */
export function createTerminalStreamError(payload = {}) {
  const rawError = payload.error;
  const message = (
    payload.text
    || (typeof rawError === 'string' ? rawError : rawError?.message)
    || `Error ${payload.status || 'unknown'}`
  );
  const error = new Error(message);
  error.name = 'TerminalStreamError';
  error.terminalStreamError = true;
  error.status = payload.status;
  return error;
}

/** Only connection-class stream failures are safe to resubmit automatically. */
export function isRecoverableStreamError(error) {
  if (!error || error.terminalStreamError || error.name === 'TerminalStreamError') return false;
  if (error.name === 'TypeError') return true;
  const message = (error.message || '').toLowerCase();
  if (/\btool\b|unsupported|json|parse|\b4\d\d\b|\b5\d\d\b/.test(message)) return false;
  return /network|fetch|connection|reset|closed|aborted|stream|tim(?:e|ed)\s?out|econn|eof/.test(message);
}

/**
 * `P23-04` (CHAT-M-13, CHAT-U-26, PERF-U-6). What a reply that failed says.
 *
 * It was the provider's text in red italics inside square brackets —
 * "[Error: local endpoint is having an outage (HTTP 500). The model crashed
 * (simulated) — CUDA out of memory]", "[Error: Cannot reach
 * http://127.0.0.1:47111]" — with nothing to do next. Now one sentence a
 * person reads, the model's own words behind *Details*, and *Retry*.
 */
/** The address a "Cannot reach <url>" failure names, or ''. */
export function unreachableUrl(err) {
  const m = /^cannot reach\s+(\S+)/i.exec(String((err && err.message) || ''));
  return m ? m[1].replace(/[.,;]+$/, '') : '';
}

export function replyErrorSentence(err, model = '') {
  const message = String((err && err.message) || '');
  const name = String(model || '').split('/').pop();
  if (/^cannot reach\b/i.test(message)) return `${name || 'The model'} isn't answering.`;
  const status = Number(err && err.status);
  if (Number.isInteger(status) && status >= 400) return `The model didn't answer (HTTP ${status}).`;
  return "The model didn't answer.";
}

/** The failed reply's line: the sentence, *Retry* (when there is a turn to
 *  retry) and *Details* (when the model said more than the sentence does). */
export function buildReplyError(doc, err, { model = '', onRetry = null } = {}) {
  // `P23-04` (CHAT-M-23): tell the model picker its endpoint did not answer.
  const url = unreachableUrl(err);
  if (url) {
    try { globalThis.dispatchEvent(new CustomEvent('pantheon:endpoint-unanswered', { detail: { url } })); } catch (_) {}
  }
  const box = doc.createElement('div');
  box.className = 'reply-error';
  box.setAttribute('role', 'alert');
  box.style.cssText = 'display:flex; flex-wrap:wrap; align-items:center; gap:8px; padding:4px 0; color:var(--color-error);';
  const text = doc.createElement('span');
  text.className = 'reply-error-text';
  text.textContent = replyErrorSentence(err, model);
  box.appendChild(text);
  if (typeof onRetry === 'function') {
    const retry = doc.createElement('button');
    retry.type = 'button';
    retry.className = 'reply-error-retry';
    retry.textContent = 'Retry';
    retry.addEventListener('click', () => { retry.disabled = true; onRetry(); });
    box.appendChild(retry);
  }
  const raw = String((err && err.message) || '').trim();
  if (raw && raw !== text.textContent) {
    const details = doc.createElement('details');
    details.className = 'reply-error-details';
    details.style.cssText = 'flex-basis:100%; color:var(--color-muted-alt); font-size:12px;';
    const summary = doc.createElement('summary');
    summary.textContent = 'Details';
    const pre = doc.createElement('pre');
    pre.style.cssText = 'white-space:pre-wrap; margin:4px 0 0;';
    pre.textContent = raw;   // the provider's words, as text and never markup
    details.appendChild(summary);
    details.appendChild(pre);
    box.appendChild(details);
  }
  return box;
}
