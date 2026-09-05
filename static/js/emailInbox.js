/**
 * emailInbox.js — Email inbox list in sidebar.
 * Follows the session list pattern: list items, click to open as document, archive, etc.
 */

import spinnerModule from './spinner.js';
import sessionModule from './sessions.js';
import { initEmailLibrary, openEmailLibrary, closeEmailLibrary, isOpen as isLibOpen, prewarmEmailLibrary, prewarmUnreadEmails } from './emailLibrary.js?v=20260815approvalsave1';
import * as Modals from './modalManager.js?v=20260723compareicon2';
import { applyEdgeDock } from './modalSnap.js';
import { buildReplyAllCc, extractEmail } from './emailLibrary/replyRecipients.js';
import { emailApiUrl, emailAccountQuery } from './emailShared.js';
import { bindMenuDismiss, dismissOrRemove } from './escMenuStack.js';

const API_BASE = window.location.origin;
const _acct = () => emailAccountQuery('&');

const _emailSetupHint = () => '<div style="margin-top:6px;opacity:0.72;font-size:11px;">Setup: <span style="color:var(--accent,var(--red));">Settings &rsaquo; Integrations</span></div>';

// SVG icons matching sessions.js dropdown style
const _replyIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/></svg>';
const _archiveIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/></svg>';
const _deleteIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>';
const _unreadIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3" fill="currentColor"/></svg>';
const _starIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>';
const _starFilledIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>';
const _bellIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>';
const _icon = (svg) => `<span class="dropdown-icon">${svg}</span>`;
const _replySeparator = '---------- Previous message ----------';
const _DONE_RESPONSE_TAGS = new Set(['urgent', 'reply-soon', 'action-needed']);

function _splitEmailAddresses(raw) {
  return (typeof raw === 'string' ? raw : '')
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean);
}

function _isMyEmailAddress(addr, myAddresses) {
  const email = extractEmail(addr);
  if (!email) return false;
  return new Set((myAddresses || []).map(a => String(a || '').trim().toLowerCase()).filter(Boolean)).has(email);
}

function _withoutMyAddresses(raw, myAddresses) {
  return _splitEmailAddresses(raw).filter(addr => !_isMyEmailAddress(addr, myAddresses));
}

function _openCalendarEventFromEmail(uid) {
  const target = String(uid || '').trim();
  if (!target) return;
  import('./calendar.js').then(mod => {
    const open = mod.openCalendarTo || (mod.default && mod.default.openCalendarTo);
    if (open) open(target);
  }).catch(() => {});
}

function _openEmailTagFilter(tag) {
  const normalized = String(tag || '').trim().toLowerCase().replace(/_/g, '-');
  if (!normalized || normalized === 'calendar') return;
  try { openEmailLibrary(); } catch (_) {}
  setTimeout(() => {
    document.dispatchEvent(new CustomEvent('pantheon:email-filter-tag', { detail: { tag: normalized } }));
  }, 0);
}

function _emailTagPillHtml(tag, em) {
  const normalized = String(tag || '').trim().toLowerCase().replace(/_/g, '-');
  if (!normalized) return '';
  const eventUid = normalized === 'calendar' && Array.isArray(em?.calendar_event_uids)
    ? String(em.calendar_event_uids[0] || '').trim()
    : '';
  if (normalized === 'calendar') {
    if (!eventUid) return '';
    return `<button type="button" class="email-tag email-tag-${_esc(normalized)} email-tag-clickable" data-calendar-event-uid="${_esc(eventUid)}" title="Open calendar event">${_esc(normalized)}</button>`;
  }
  return `<button type="button" class="email-tag email-tag-${_esc(normalized)} email-tag-clickable" data-email-filter-tag="${_esc(normalized)}" title="Show ${_esc(normalized)} emails">${_esc(normalized)}</button>`;
}

function _emailTagGroupHtml(tags, em) {
  const visible = (Array.isArray(tags) ? tags : [])
    .map(t => _emailTagPillHtml(t, em))
    .filter(Boolean);
  if (!visible.length) return '';
  if (visible.length === 1) return `<span class="email-tags">${visible[0]}</span>`;
  const extra = visible.slice(1).map(html => `<span class="email-tag-extra">${html}</span>`).join('');
  return `<span class="email-tags email-tags-collapsed">${visible[0]}${extra}<button type="button" class="email-tags-more" data-email-tags-more aria-expanded="false" title="Show all tags">+${visible.length - 1}<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"></polyline></svg></button></span>`;
}

function _visibleEmailTagsForRender(em) {
  const tags = Array.isArray(em?.tags) ? em.tags : [];
  if (!em?.is_answered) return tags;
  return tags.filter(t => !_DONE_RESPONSE_TAGS.has(String(t || '').trim().toLowerCase().replace(/_/g, '-')));
}

function _clearDoneResponseTagsLocal(em) {
  if (!em || !Array.isArray(em.tags)) return;
  em.tags = em.tags.filter(t => !_DONE_RESPONSE_TAGS.has(String(t || '').trim().toLowerCase().replace(/_/g, '-')));
}

function _cleanAiReplyText(text) {
  if (!text) return '';
  let t = String(text);
  const open = /<<<\s*(?:REPLY|SUMMARY|OUTPUT)\s*>>+/i;
  const close = /<<<\s*END\s*>>+/i;
  const m = open.exec(t);
  if (m) {
    const rest = t.slice(m.index + m[0].length);
    const c = close.exec(rest);
    t = c ? rest.slice(0, c.index) : rest;
  }
  return t
    .replace(/<<<\s*(?:REPLY|SUMMARY|OUTPUT)\s*>>+/gi, '')
    .replace(/<<<\s*END\s*>>+/gi, '')
    .replace(/<\/?\|(?:assistant|assistan|user|system|tool)\|>?|<\/\|end\|>?/gi, '')
    .trim();
}

let _emails = [];
let _currentFolder = 'INBOX';
let _offset = 0;
let _total = 0;

// Replying to an email marks the source \Answered server-side and fires
// `email-answered`. Reflect it live in the inbox list so it shows as done
// immediately (no manual refresh needed).
window.addEventListener('email-answered', (e) => {
  const uid = e.detail && e.detail.uid;
  if (uid == null) return;
  const em = _emails.find(x => String(x.uid) === String(uid));
  if (em) {
    em.is_answered = true;
    em.is_read = true;
    _clearDoneResponseTagsLocal(em);
  }
  document.querySelectorAll('.email-item[data-uid="' + CSS.escape(String(uid)) + '"]').forEach(item => {
    item.classList.remove('email-unread');
    item.querySelectorAll('.email-tag-urgent, .email-tag-reply-soon, .email-tag-action-needed').forEach(n => n.remove());
    const check = item.querySelector('.email-done-check');
    if (check) check.classList.add('active');
    // Auto-mark from sending a reply — flash the row so the user sees the
    // state change without staring at it. Class self-removes after the
    // animation so it doesn't replay on re-renders.
    item.classList.add('email-auto-done-flash');
    setTimeout(() => item.classList.remove('email-auto-done-flash'), 1200);
  });
});
let _loading = false;
let _expanded = false;
let _docModule = null;
let _listSpinner = null;
let _openEmailRequestSeq = 0;
let _senderFilter = null;       // email address (lowercased) to filter by, or null
let _senderFilterLabel = null;  // display label for the active filter chip
let _showEmailTags = localStorage.getItem('pantheon.email.showTags') !== '0';

export function init(documentModule) {
  _docModule = documentModule;
  _bindEvents();
  document.addEventListener('pantheon:email-tags-toggle', (e) => {
    // Mirror the library's tag-visibility preference. The library repaints its
    // own grid; there is no second list here to re-render.
    _showEmailTags = e.detail?.show !== false;
  });
  // Init the library popup with a callback to open emails
  initEmailLibrary({
    documentModule,
    onEmailClick: async (opts) => {
      // Reply / AI Reply / Compose open a draft in the doc editor.
      //  - Desktop: dock the email to the LEFT so it stays visible beside the
      //    reply draft (which opens on the right) — read-while-you-reply.
      //  - Mobile: there's no room for a split, so minimize the email modal;
      //    the draft comes to the front and the inbox stays a tap away as a
      //    minimized chip.
      // Never call closeEmailLibrary() here — that destroys state.
      try {
        if (Modals.isRegistered('email-lib-modal')) {
          const emailModal = document.getElementById('email-lib-modal');
          if (window.innerWidth > 768 && emailModal && !emailModal.classList.contains('hidden')) {
            applyEdgeDock(emailModal, 'left');
          }
          // Mobile: do NOT pre-mount the pane here. The load path (open/inject)
          // mounts it exactly once when the doc is ready; the doc-view z-index
          // rule slides it up OVER the email (which stays behind). Pre-mounting
          // here caused a double-mount — the early pane was torn down by the
          // compose session-switch, then remounted, which looked like a doc
          // flashing before the smooth slide.
        }
      } catch (_) {}
      if (opts.compose) { _composeNew(); return; }
      if (opts.email) {
        await _openEmail(opts.email, null, opts.emailData, opts.mode || 'reply', opts.noteHint || '', '', opts.mailboxContext || null);
      }
    },
  });
  prewarmEmailLibrary({ delay: 1800 });
  _watchDocOpenToReDockEmail();
}

export async function openReplyDraft(uid, folder = 'INBOX', mode = 'reply', prefilledBody = '') {
  if (!uid) return;
  const previousFolder = _currentFolder;
  _currentFolder = folder || 'INBOX';
  try {
    await _openEmail({ uid: String(uid), subject: '' }, null, null, mode || 'reply', '', prefilledBody || '');
  } finally {
    _currentFolder = previousFolder || _currentFolder;
  }
}

function _bringEmailReplyDraftToFrontOnMobile() {
  if (window.innerWidth > 768) return;
  document.body.classList.remove('email-front', 'email-doc-split-active');
  document.documentElement.style.removeProperty('--email-doc-split-left-x');
  document.documentElement.style.removeProperty('--email-doc-split-email-w');
  document.documentElement.style.removeProperty('--email-doc-split-right-x');
  // Keep the email sheet visible behind the reply document on mobile. The
  // document panel sits above it via the normal doc-view z-index rules, and
  // swiping the document down minimizes it to a chip to reveal the email.
  document.querySelectorAll('#email-lib-modal, .modal[id^="email-reader-"]').forEach(modal => {
    modal.classList.remove('email-snap-left', 'modal-left-docked', 'modal-right-docked');
    modal.style.removeProperty('z-index');
  });
  const docPane = document.getElementById('doc-editor-pane');
  if (docPane) docPane.style.setProperty('z-index', '10010', 'important');
}

// When the document editor pane opens (body.doc-view turns on), make sure the
// email modal is on the LEFT — even if it was previously docked RIGHT or
// floating — so the email and the doc always end up side-by-side. The actual
// width math lives in modalSnap.js (`_anchorLeftDock` shrinks the email when
// the doc is rendered to the right).
let _docOpenObs = null;
function _watchDocOpenToReDockEmail() {
  if (_docOpenObs) return;
  if (typeof MutationObserver === 'undefined') return;
  let last = document.body.classList.contains('doc-view');
  _docOpenObs = new MutationObserver(() => {
    const cur = document.body.classList.contains('doc-view');
    if (cur && !last) {
      if (window.innerWidth > 768) {
        const emailModal = document.getElementById('email-lib-modal');
        if (emailModal && !emailModal.classList.contains('hidden')) {
          // Already left-docked → nothing to do (modalSnap re-anchors on its own).
          if (!emailModal.classList.contains('modal-left-docked')) {
            try { applyEdgeDock(emailModal, 'left'); } catch (_) {}
          }
        }
        // Same treatment for an open email-reader modal (one specific email
        // open standalone — typical "click email, click doc" flow).
        document.querySelectorAll('.modal[id^="email-reader-"]').forEach(m => {
          if (m.classList.contains('hidden')) return;
          if (m.classList.contains('modal-left-docked')) return;
          try { applyEdgeDock(m, 'left'); } catch (_) {}
        });
      }
    }
    last = cur;
  });
  _docOpenObs.observe(document.body, { attributes: true, attributeFilter: ['class'] });
}

function _bindEvents() {
  // Clicking anywhere in the email section header opens the popup
  // (except the compose button which has its own handler)
  const section = document.getElementById('email-section');
  const header = section?.querySelector('.section-header-flex');
  if (header) {
    header.style.cursor = 'pointer';
    header.addEventListener('click', (e) => {
      if (e.target.closest('#email-compose-btn')) return;
      openEmailLibrary();
      markInboxAsSeen();
    });
  }

  // Compose button creates a new email document
  const composeBtn = document.getElementById('email-compose-btn');
  if (composeBtn) {
    composeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      _composeNew();
    });
  }

  // Delay the lightweight unread badge check so opening Pantheon doesn't
  // compete with the initial chat/session paint. The full email list now loads
  // only when the inbox is actually opened.
  // `P15-10` — jittered, and this one reaches a mail provider. `setInterval`
  // is replaced by a self-rescheduling `setTimeout` because an interval fires
  // on a fixed grid: jittering only the FIRST delay would shift the whole grid
  // once and then keep every tick exactly sixty seconds apart forever, which
  // spreads across installs but not across ticks. A drifting timer re-rolls
  // each time, and drift is the point here rather than a defect.
  const _unreadJitter = (base) => base + Math.random() * base * 0.1;
  setTimeout(_refreshUnreadCount, _unreadJitter(8000));
  (function _pollUnread() {
    setTimeout(() => {
      _refreshUnreadCount();
      _pollUnread();
    }, _unreadJitter(60000));
  })();

  // Deep-link: #email=<folder>:<uid> opens the library and expands that card
  _maybeOpenFromHash();
  window.addEventListener('hashchange', _maybeOpenFromHash);
}

function _maybeOpenFromHash() {
  const h = window.location.hash || '';
  const m = h.match(/^#email=([^:]+):(\d+)/);
  if (!m) return;
  const folder = decodeURIComponent(m[1]);
  const uid = m[2];
  try { openEmailLibrary({ folder, uid }); } catch (e) { console.error(e); }
  // Clear the hash so reloads don't reopen
  try { history.replaceState(null, '', window.location.pathname + window.location.search); } catch (_) {}
}

// Tint helper — turns the urgent-email-scanner's max_score into a dot color.
// Falls back to the default (blue / unset) when scanner is off or no urgent.
function _urgencyColor(score) {
  if (score >= 3) return 'var(--color-error, #e06c75)';   // red — urgent now
  if (score === 2) return '#f0ad4e';                       // orange — reply soon
  return '';                                                // default (blue / theme)
}

async function _refreshUnreadCount() {
  // Default the dot to hidden — only the verified "new mail above threshold"
  // path below should turn it on. Without this, a fetch error or a backend
  // returning malformed data left a stale dot from a previous account/session.
  const dot = document.getElementById('email-unread-dot');
  if (dot && !dot._stickyState) dot.style.display = 'none';
  try {
    // Parallel: cheap unread state + urgency state.
    const [stateRes, urgRes] = await Promise.all([
      fetch(emailApiUrl('/api/email/unread-state', { folder: 'INBOX' })),
      fetch(`${API_BASE}/api/email/urgency-state`, { credentials: 'same-origin' }).catch(() => null),
    ]);
    if (!stateRes || !stateRes.ok) return;
    const data = await stateRes.json();
    if (!dot) return;

    const unreadCount = Number(data.unread_count || 0);
    if (unreadCount <= 0) {
      dot.style.display = 'none';
      return;
    }

    // Compare highest unread UID to the last-seen threshold in localStorage
    const lastSeen = parseInt(localStorage.getItem('pantheon-email-last-seen-uid') || '0', 10);
    const maxUid = parseInt(data.max_uid || '0', 10) || 0;

    // Only show dot if there's a new email above the threshold
    const hasNewUnread = maxUid > lastSeen;
    dot.style.display = hasNewUnread ? '' : 'none';
    if (hasNewUnread && !isLibOpen()) {
      prewarmUnreadEmails({ limit: Math.min(10, Math.max(1, unreadCount)), maxUid }).catch(() => {});
    }

    // Color the dot by urgency tier. Cache the per-uid map so the per-row
    // renderer can reuse it without a second fetch.
    if (dot.style.display !== 'none' && urgRes && urgRes.ok) {
      try {
        const ud = await urgRes.json();
        window._emailUrgencyState = ud;
        const tint = _urgencyColor(ud.max_score || 0);
        if (tint) dot.style.backgroundColor = tint;
        else dot.style.backgroundColor = '';
      } catch (_) {}
    } else if (dot.style.display !== 'none') {
      dot.style.backgroundColor = '';
    }
  } catch (e) {
    // Network/parse error — keep the dot hidden (default at the top).
    if (dot) dot.style.display = 'none';
  }
}

export function markInboxAsSeen() {
  // Called when the user opens the inbox popup — clears the notif dot
  try {
    // Find current max UID so subsequent arrivals trigger the dot
    fetch(emailApiUrl('/api/email/unread-state', { folder: 'INBOX' }))
      .then(r => r.json())
      .then(data => {
        const maxUid = parseInt(data.max_uid || '0', 10) || 0;
        if (maxUid > 0) {
          localStorage.setItem('pantheon-email-last-seen-uid', String(maxUid));
        }
        const dot = document.getElementById('email-unread-dot');
        if (dot) dot.style.display = 'none';
      })
      .catch(() => {});
  } catch (e) {}
}

// The sidebar inbox list (#email-list / #email-folder-select /
// #email-load-more) is gone. Opening Email from the sidebar opens the email
// library modal instead — #email-lib-grid + #email-lib-folder in
// emailLibrary.js — which is the one inbox surface. Its folder <select> is
// populated with the sortedFolders() / folderDisplayName() helpers below,
// which is why those two stay exported.

export function sortedFolders(folders) {
  const roleOf = (folder) => {
    const f = String(folder || '').toLowerCase();
    if (f === 'inbox') return 'inbox';
    if (f.includes('sent')) return 'sent';
    if (f.includes('starred') || f.includes('flagged')) return 'starred';
    if (f.includes('draft')) return 'drafts';
    if (f.includes('all mail') || f.includes('archive')) return 'archive';
    if (f.includes('spam') || f.includes('junk')) return 'junk';
    if (f.includes('trash') || f.includes('bin') || f.includes('deleted')) return 'trash';
    return '';
  };
  const roleOrder = ['inbox', 'sent', 'starred', 'archive', 'junk', 'trash', 'drafts'];
  const found = new Map();
  const others = [];
  for (const f of folders) {
    const role = roleOf(f);
    if (role && !found.has(role)) found.set(role, f);
    else others.push(f);
  }
  return { priority: roleOrder.map(role => found.get(role)).filter(Boolean), others };
}

export function folderDisplayName(folder) {
  const raw = String(folder || '');
  const f = raw.toLowerCase();
  if (f === 'inbox') return 'INBOX';
  if (f.includes('all mail')) return 'Archive / All Mail';
  if (f.includes('archive')) return 'Archive';
  if (f.includes('spam')) return 'Spam';
  if (f.includes('junk')) return 'Junk';
  if (f.includes('trash') || f.includes('bin') || f.includes('deleted')) return 'Trash';
  if (f.includes('sent')) return 'Sent';
  if (f.includes('draft')) return 'Drafts';
  return raw;
}

async function _openEmail(em, itemEl, preloadedData = null, mode = 'reply', noteHint = '', prefilledBody = '', mailboxContext = null) {
  const openRequestSeq = ++_openEmailRequestSeq;
  const folderAtStart = mailboxContext?.messageFolder || _currentFolder;
  const accountAtStart = mailboxContext?.accountId ?? (window.__pantheonActiveEmailAccount || '');
  const accountQueryAtStart = accountAtStart ? `&account_id=${encodeURIComponent(accountAtStart)}` : '';
  const mailboxContextIsCurrent = typeof mailboxContext?.isCurrent === 'function'
    ? mailboxContext.isCurrent
    : () => (
        folderAtStart === _currentFolder &&
        accountAtStart === (window.__pantheonActiveEmailAccount || '')
      );
  const isCurrentOpen = () => (
    openRequestSeq === _openEmailRequestSeq &&
    mailboxContextIsCurrent()
  );
  const aiReplyMode = mode === 'ai-reply-fast' ? 'fast' : '';
  const wantsAiReply = mode === 'ai-reply' || !!aiReplyMode;
  // Body pre-fill from the agent's open_email_reply tool call takes the
  // same insertion slot as an AI-suggested body — both land just before
  // the quoted-original block.
  let aiSuggestedBody = (typeof prefilledBody === 'string' && prefilledBody.trim()) ? prefilledBody.trim() : null;
  if (wantsAiReply) {
    // Fall through to reply-all (not plain reply) so the generated AI
    // draft addresses everyone on the original thread. On single-
    // recipient emails this collapses to a regular reply since there's
    // no one else to CC.
    mode = 'reply-all';
  }
  // Show whirlpool spinner on the right side of the item (only if from sidebar)
  let spinner = null;
  if (itemEl) {
    const sp = spinnerModule.createWhirlpool(16);
    spinner = sp;
    sp.element.style.cssText = 'margin:0;flex-shrink:0;';
    const menuWrap = itemEl.querySelector('.email-menu-wrap');
    if (menuWrap) menuWrap.style.display = 'none';
    itemEl.appendChild(sp.element);
  }

  try {
    let data = preloadedData;
    if (!data) {
      const fullQS = mode === 'forward' ? '&full=1' : '';
      const res = await fetch(`${API_BASE}/api/email/read/${em.uid}?folder=${encodeURIComponent(folderAtStart)}${accountQueryAtStart}&mark_seen=true${fullQS}`);
      data = await res.json();
    }
    if (!isCurrentOpen()) return;
    if (data.error) {
      console.error('Failed to read email:', data.error);
      return;
    }
    // The list row is already populated from the durable email index. Some
    // IMAP/read paths can return a partial object for long Outlook threads;
    // never let that create a reply draft with blank To/Subject.
    const _fallback = (primary, fallback) => {
      const p = primary == null ? '' : String(primary).trim();
      if (p) return primary;
      return fallback == null ? '' : fallback;
    };
    data = {
      ...em,
      ...data,
      uid: data.uid || em.uid,
      subject: _fallback(data.subject, em.subject),
      from_name: _fallback(data.from_name, em.from_name || em.from_address),
      from_address: _fallback(data.from_address, em.from_address),
      to: _fallback(data.to, em.to),
      cc: _fallback(data.cc, em.cc),
      date: _fallback(data.date, em.date),
      message_id: _fallback(data.message_id, em.message_id),
    };
    if (wantsAiReply) {
      const activeReplyAccount = data.account_id || em.account_id || accountAtStart;
      if (data.cached_ai_reply && !noteHint && !activeReplyAccount) {
        aiSuggestedBody = _cleanAiReplyText(data.cached_ai_reply);
      } else {
        let draftToastTimer = null;
        draftToastTimer = setTimeout(() => {
          import('./ui.js').then(m => m.showToast && m.showToast('Drafting AI reply', { duration: 3000, leadingIcon: 'spinner' })).catch(() => {});
        }, 450);
        try {
          let currentModel = '';
          let currentSessionId = '';
          try {
            currentModel = sessionModule?.getCurrentModel() || '';
            currentSessionId = sessionModule?.getCurrentSessionId() || '';
          } catch (_) {}
          const res = await fetch(`${API_BASE}/api/email/ai-reply`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              to: data.from_address,
              subject: `Re: ${data.subject}`,
              original_body: data.body,
              model: currentModel,
              session_id: currentSessionId,
              message_id: data.message_id || '',
              uid: String(em.uid || ''),
              folder: folderAtStart,
              account_id: activeReplyAccount,
              fast: true,
              user_hint: (noteHint || '').trim() || undefined,
            }),
          });
          const result = await res.json();
          if (draftToastTimer) clearTimeout(draftToastTimer);
          if (!isCurrentOpen()) return;
          if (result.success && result.reply) {
            aiSuggestedBody = _cleanAiReplyText(result.reply);
          } else {
            const _rawMsg = result.error || 'AI reply could not be generated';
            const _msg = /empty response/i.test(_rawMsg)
              ? 'AI returned empty response.'
              : _rawMsg;
            console.error('AI reply generation failed:', _msg);
            import('./ui.js').then(m => m.showError && m.showError('AI reply failed: ' + _msg)).catch(() => {});
            return;
          }
        } catch (e) {
          if (draftToastTimer) clearTimeout(draftToastTimer);
          if (!isCurrentOpen()) return;
          console.error('AI reply generation failed:', e);
          import('./ui.js').then(m => m.showError && m.showError('AI reply failed: ' + (e.message || e))).catch(() => {});
          return;
        }
      }
    }

    if (!isCurrentOpen()) return;
    // Only claim the message is read when the provider accepted the \Seen
    // transition. A failed STORE still opens the message; it just stays unread.
    const markedSeen = !data.mark_seen_failed;
    em.is_read = markedSeen;
    if (itemEl) itemEl.classList.toggle('email-unread', !markedSeen);

    // Addresses to exclude from Reply All. Prefer the full set of configured
    // accounts (so a multi-account user's other mailboxes are excluded too),
    // falling back to the single active address. Empty ⇒ no exclusion.
    const myAddresses = (Array.isArray(window._myEmailAddresses) && window._myEmailAddresses.length)
      ? window._myEmailAddresses
      : (window._myEmailAddress ? [window._myEmailAddress] : []);

    const fromIsMe = _isMyEmailAddress(data.from_address, myAddresses);
    const originalToWithoutMe = _withoutMyAddresses(data.to, myAddresses);
    const originalCcWithoutMe = _withoutMyAddresses(data.cc, myAddresses);

    let toAddress = fromIsMe
      ? (originalToWithoutMe.join(', ') || originalCcWithoutMe[0] || data.from_address)
      : data.from_address;
    let ccAddresses = '';
    let subjectPrefix = 'Re: ';

    if (mode === 'reply-all') {
      if (fromIsMe) {
        // Replying from Sent should go back to the people I originally wrote
        // to, not to myself. Keep original Cc recipients on Cc.
        toAddress = originalToWithoutMe.join(', ') || originalCcWithoutMe[0] || data.from_address;
        ccAddresses = originalCcWithoutMe.filter(addr => !originalToWithoutMe.some(t => extractEmail(t) === extractEmail(addr))).join(', ');
      } else {
        // Build reply-all: TO = original sender, CC = everyone else (To + Cc minus me)
        ccAddresses = buildReplyAllCc(data, myAddresses);
      }
    } else if (mode === 'forward') {
      toAddress = '';
      subjectPrefix = 'Fwd: ';
    }

    // Don't double-prefix `Re:` / `Fwd:` when the subject already starts with one.
    // Replies to replies were producing `Re: Re: Re: …` which can also break
    // some IMAP servers' header parsing on very long subject lines.
    let _baseSubject = (data.subject || '').trim();
    if (subjectPrefix === 'Re: ' && /^re\s*:/i.test(_baseSubject)) subjectPrefix = '';
    else if (subjectPrefix === 'Fwd: ' && /^fwd?\s*:/i.test(_baseSubject)) subjectPrefix = '';
    if (mode !== 'forward' && !String(toAddress || '').trim()) {
      throw new Error('Cannot create reply: sender address is missing from this email.');
    }
    let content = `To: ${toAddress}\nSubject: ${subjectPrefix}${_baseSubject}`;
    if (ccAddresses) content += `\nCc: ${ccAddresses}`;
    if (mode !== 'forward' && data.message_id) content += `\nIn-Reply-To: ${data.message_id}`;
    if (mode !== 'forward' && data.message_id) content += `\nReferences: ${data.references ? data.references + ' ' + data.message_id : data.message_id}`;
    content += `\nX-Source-UID: ${em.uid}`;
    content += `\nX-Source-Folder: ${folderAtStart}`;
    if (data.attachments && data.attachments.length > 0) {
      const attStr = data.attachments.map(a => `${a.index}:${a.filename}:${a.size}`).join('|');
      content += `\nX-Attachments: ${attStr}`;
      if (mode === 'forward') content += `\nX-Forward-Attachments: 1`;
    }
    content += '\n---\n';

    // Format the original date in a human-readable way for the quote header
    let niceDate = data.date || '';
    try {
      if (data.date) {
        const d = new Date(data.date);
        if (!isNaN(d.getTime())) {
          niceDate = d.toLocaleString([], {
            weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
            hour: '2-digit', minute: '2-digit',
          });
        }
      }
    } catch (_) {}

    // Plain-text body, with HTML fallback stripped if no text part exists.
    // Without this, an HTML-only email gives data.body === null/undefined
    // and the reply doc opens empty (data.body.split throws).
    let _origBody = (typeof data.body === 'string' && data.body.length) ? data.body : '';
    if (!_origBody && typeof data.body_html === 'string' && data.body_html) {
      _origBody = data.body_html
        .replace(/<style[\s\S]*?<\/style>/gi, '')
        .replace(/<script[\s\S]*?<\/script>/gi, '')
        .replace(/<br\s*\/?>/gi, '\n')
        .replace(/<\/p>/gi, '\n\n')
        .replace(/<[^>]+>/g, '')
        .replace(/&nbsp;/g, ' ')
        .replace(/&amp;/g, '&')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
    }

    if (mode === 'forward') {
      content += `\n\n---------- Forwarded message ----------\n`;
      content += `From: ${data.from_name} <${data.from_address}>\n`;
      content += `Date: ${niceDate}\n`;
      content += `Subject: ${data.subject}\n`;
      if (data.to) content += `To: ${data.to}\n`;
      content += `\n${_origBody}`;
    } else {
      const quotedBody = _origBody.split('\n').map(l => '> ' + l).join('\n');
      // Inject AI-suggested body if present. No leading newline — the header
      // block already ends with "---\n", so the reply must start on the very
      // first body line, not one row down.
      if (aiSuggestedBody) {
        content += `${aiSuggestedBody}\n\n`;
      } else {
        content += '\n\n';
      }
      content += `${_replySeparator}\nOn ${niceDate}, ${data.from_name} <${data.from_address}> wrote:\n${quotedBody}`;
    }

    if (_docModule) {
      // Agent-provided reply text should land in the email draft the user
      // already has open. Plain Reply clicks must create a fresh draft: reusing
      // old source-UID drafts can reopen stale quote-only/malformed compose docs
      // and block Send on long threads.
      const reuseExisting = mode !== 'forward' && !!aiSuggestedBody;
      const existingDocId = (reuseExisting && _docModule.findEmailDocId)
        ? _docModule.findEmailDocId(em.uid, folderAtStart)
        : null;
      if (existingDocId) {
        if (!_docModule.isPanelOpen()) _docModule.openPanel();
        await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
        if (!isCurrentOpen()) return;
        await _docModule.loadDocument(existingDocId);
        if (!isCurrentOpen()) return;
        if (typeof _docModule.ensureEmailDraftEnvelope === 'function') {
          await _docModule.ensureEmailDraftEnvelope(existingDocId, content);
          if (!isCurrentOpen()) return;
        }
        if (aiSuggestedBody && typeof _docModule.replaceEmailReplyBody === 'function') {
          await _docModule.replaceEmailReplyBody(existingDocId, aiSuggestedBody, { force: false });
          if (!isCurrentOpen()) return;
        }
        _bringEmailReplyDraftToFrontOnMobile();
      } else {
        if (!isCurrentOpen()) return;
        let activeSid = await _createEmailChat(data, { forceNew: true });
        if (!isCurrentOpen()) return;
        if (!activeSid) {
          console.error('reply: could not obtain a session_id');
          import('./ui.js').then(m => m.showError && m.showError('Could not start a reply chat.')).catch(() => {});
          return;
        }

        const createReplyDoc = (sessionId) => fetch(`${API_BASE}/api/document`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: sessionId,
            title: data.subject,
            content: content,
            language: 'email',
          }),
        });
        let docRes = await createReplyDoc(activeSid);
        if (!isCurrentOpen()) return;
        if (docRes.status === 404) {
          console.warn('[reply-debug] draft session rejected; retrying in a fresh email chat', activeSid);
          if (!isCurrentOpen()) return;
          activeSid = await _createEmailChat(data, { forceNew: true });
          if (!isCurrentOpen()) return;
          if (activeSid) {
            docRes = await createReplyDoc(activeSid);
            if (!isCurrentOpen()) return;
          }
        }
        if (!docRes.ok) {
          const errText = await docRes.text();
          if (!isCurrentOpen()) return;
          console.error('[reply-debug] POST /api/document failed', docRes.status, errText);
          // uiModule isn't statically imported here — use the dynamic
          // import pattern the rest of this file uses. (Previously this
          // referenced a bare `uiModule`, throwing a ReferenceError that
          // the outer catch swallowed → reply silently did nothing.)
          import('./ui.js').then(m => m.showError && m.showError('Failed to create reply draft (' + docRes.status + ')')).catch(() => {});
          return;
        }
        const doc = await docRes.json();
        if (!isCurrentOpen()) return;
        if (doc.id) {
          const wasOpen = _docModule.isPanelOpen();
          if (!wasOpen) _docModule.openPanel();
          await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
          if (!isCurrentOpen()) return;
          // Use the doc dict from the POST directly — avoids a 404 race
          // when the GET fires before the new row is visible to the read
          // connection (or when caching is interfering). loadDocument's
          // GET path can still be used as a fallback.
          if (_docModule.injectFreshDoc) {
            _docModule.injectFreshDoc(doc);
          } else {
            await _docModule.loadDocument(doc.id);
            if (!isCurrentOpen()) return;
          }
          _bringEmailReplyDraftToFrontOnMobile();
        }
      }
    }
  } catch (e) {
    if (!isCurrentOpen()) return;
    console.error('Failed to open email:', e);
    // Surface the failure so a silent throw in the reply flow doesn't
    // look like "nothing happened". Dynamic import — uiModule isn't a
    // static import in this file.
    const msg = e && e.message ? e.message : String(e);
    import('./ui.js').then(m => m.showError && m.showError('Reply failed: ' + msg)).catch(() => {});
  } finally {
    if (spinner) { spinner.destroy(); spinner.element.remove(); }
    if (itemEl) {
      const menuWrap = itemEl.querySelector('.email-menu-wrap');
      if (menuWrap) menuWrap.style.display = '';
    }
  }
}

function _showEmailMenu(em, anchor, itemEl) {
  document.querySelectorAll('.email-dropdown').forEach(dismissOrRemove);

  const dropdown = document.createElement('div');
  dropdown.className = 'dropdown email-dropdown show';

  const actions = [
    { label: 'Open', icon: _replyIcon, action: () => _openEmail(em, itemEl) },
    { label: 'Remind to reply', icon: _bellIcon, submenu: 'remind' },
    { label: 'Archive', icon: _archiveIcon, action: () => _archiveEmail(em) },
    { label: 'Delete', icon: _deleteIcon, danger: true, action: () => _deleteEmail(em) },
  ];

  for (const a of actions) {
    const menuItem = document.createElement('div');
    menuItem.className = 'dropdown-item-compact' + (a.danger ? ' dropdown-item-danger' : '');
    const arrow = a.submenu ? ' <span style="margin-left:auto;opacity:0.5;">›</span>' : '';
    menuItem.innerHTML = _icon(a.icon) + `<span>${a.label}</span>${arrow}`;
    menuItem.addEventListener('click', (e) => {
      e.stopPropagation();
      if (a.submenu === 'remind') {
        _showRemindSubmenu(em, dropdown);
        return;
      }
      close();
      a.action();
    });
    dropdown.appendChild(menuItem);
  }

  anchor.appendChild(dropdown);

  const close = bindMenuDismiss(dropdown, () => { dropdown.remove(); }, (ev) => !dropdown.contains(ev.target) && !anchor.contains(ev.target));
}

// ---- Reminder submenu (creates a Note with a reminder for this email) ----

function _showRemindSubmenu(em, parentDropdown) {
  // Replace content of parent dropdown with time presets
  parentDropdown.innerHTML = '';
  const header = document.createElement('div');
  header.className = 'dropdown-item-compact';
  header.style.cssText = 'opacity:0.5;font-size:10px;pointer-events:none;text-transform:uppercase;letter-spacing:0.5px;padding-top:6px;';
  header.innerHTML = '<span>Remind me</span>';
  parentDropdown.appendChild(header);

  const now = new Date();
  const laterToday = new Date(now);
  const sixPm = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 18, 0);
  if (sixPm - now < 60*60*1000) laterToday.setTime(now.getTime() + 3 * 60 * 60 * 1000);
  else laterToday.setTime(sixPm.getTime());

  const tomorrow = new Date(now); tomorrow.setDate(tomorrow.getDate() + 1); tomorrow.setHours(8, 0, 0, 0);
  const daysUntilMon = (8 - now.getDay()) % 7 || 7;
  const nextWeek = new Date(now); nextWeek.setDate(now.getDate() + daysUntilMon); nextWeek.setHours(8, 0, 0, 0);

  const presets = [
    { label: 'Later today', sub: laterToday.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }), date: laterToday },
    { label: 'Tomorrow', sub: tomorrow.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }), date: tomorrow },
    { label: 'Next week', sub: nextWeek.toLocaleDateString([], { weekday: 'short' }) + ' ' + nextWeek.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }), date: nextWeek },
  ];
  for (const p of presets) {
    const item = document.createElement('div');
    item.className = 'dropdown-item-compact';
    item.innerHTML = `<span>${p.label}</span><span style="margin-left:auto;opacity:0.5;font-size:10px;">${p.sub}</span>`;
    item.addEventListener('click', async (e) => {
      e.stopPropagation();
      dismissOrRemove(parentDropdown);
      await _createReplyReminder(em, p.date);
    });
    parentDropdown.appendChild(item);
  }
  const customItem = document.createElement('div');
  customItem.className = 'dropdown-item-compact';
  customItem.innerHTML = '<span>Pick date and time…</span>';
  customItem.addEventListener('click', async (e) => {
    e.stopPropagation();
    dismissOrRemove(parentDropdown);
    const tmp = document.createElement('input');
    tmp.type = 'datetime-local';
    const def = new Date(tomorrow);
    const pad = n => String(n).padStart(2, '0');
    tmp.value = `${def.getFullYear()}-${pad(def.getMonth()+1)}-${pad(def.getDate())}T${pad(def.getHours())}:${pad(def.getMinutes())}`;
    tmp.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:99999;padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;font-size:13px;';
    document.body.appendChild(tmp);
    tmp.focus();
    if (typeof tmp.showPicker === 'function') { try { tmp.showPicker(); } catch {} }
    // Cleanup helper — also unwires the global listeners so they don't
    // linger after dismiss.
    const _cleanup = () => {
      tmp.remove();
      document.removeEventListener('keydown', _onKey);
      document.removeEventListener('mousedown', _onDocClick, true);
    };
    const _onKey = (ev) => { if (ev.key === 'Escape') _cleanup(); };
    // Click-outside dismiss. Replaces the old blur-based auto-remove —
    // blur fires whenever the native datetime popup steals focus, so
    // the input vanished before the user could click any date. Now we
    // only dismiss when the user clicks something that is NOT the
    // input itself (the native picker popup is a browser-owned overlay
    // OUTSIDE the document, so its clicks don't fire here at all — no
    // false dismissals).
    const _onDocClick = (ev) => { if (ev.target !== tmp) _cleanup(); };
    tmp.addEventListener('change', async () => {
      if (tmp.value) {
        await _createReplyReminder(em, new Date(tmp.value));
      }
      _cleanup();
    });
    document.addEventListener('keydown', _onKey);
    // Defer the click-outside listener so the click that opened this
    // input doesn't immediately close it.
    setTimeout(() => document.addEventListener('mousedown', _onDocClick, true), 50);
  });
  parentDropdown.appendChild(customItem);
}

async function _createReplyReminder(em, dueDate) {
  const pad = n => String(n).padStart(2, '0');
  const iso = `${dueDate.getFullYear()}-${pad(dueDate.getMonth()+1)}-${pad(dueDate.getDate())}T${pad(dueDate.getHours())}:${pad(dueDate.getMinutes())}`;
  const from = em.from || em.sender || 'someone';
  const payload = {
    title: `Reply: ${em.subject || '(no subject)'}`,
    content: `From: ${from}\n\nRemember to reply to this email.`,
    note_type: 'note',
    label: 'email',
    due_date: iso,
    source: 'email',
  };
  try {
    const res = await fetch(`${API_BASE}/api/notes`, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error('Failed');
    const { showToast } = await import('./ui.js');
    const fmt = dueDate.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
    showToast(`Reminder set for ${fmt}`);
    // Request notification permission if needed
    if ('Notification' in window && Notification.permission === 'default') {
      try { Notification.requestPermission(); } catch {}
    }
  } catch (e) {
    const { showError } = await import('./ui.js');
    showError('Failed to create reminder');
  }
}

async function _archiveEmail(em) {
  try {
    await fetch(`${API_BASE}/api/email/archive/${em.uid}?folder=${encodeURIComponent(_currentFolder)}${_acct()}`, { method: 'POST' });
    _emails = _emails.filter(e => e.uid !== em.uid);
  } catch (e) {
    console.error('Failed to archive:', e);
  }
}

async function _deleteEmail(em) {
  const subject = em.subject || '(no subject)';
  const { styledConfirm } = await import('./ui.js');
  const ok = await styledConfirm(`Delete "${subject}"?`, { confirmText: 'Delete', cancelText: 'Cancel', danger: true });
  if (!ok) return;
  const row = document.querySelector(`.email-item[data-uid="${CSS.escape(String(em.uid))}"]`);
  const busy = _showEmailDeleteOverlay(row);
  await busy?.ready;
  try {
    await fetch(`${API_BASE}/api/email/delete/${em.uid}?folder=${encodeURIComponent(_currentFolder)}${_acct()}`, { method: 'DELETE' });
    busy?.remove?.();
    _emails = _emails.filter(e => e.uid !== em.uid);
  } catch (e) {
    busy?.remove?.();
    console.error('Failed to delete:', e);
  }
}

function _showEmailDeleteOverlay(target) {
  if (!target) return null;
  const wp = spinnerModule.createWhirlpool(16);
  const overlay = document.createElement('div');
  overlay.className = 'email-delete-overlay';
  overlay.appendChild(wp.element);
  const prevPos = target.style.position;
  const prevPointerEvents = target.style.pointerEvents;
  if (getComputedStyle(target).position === 'static') target.style.position = 'relative';
  target.style.pointerEvents = 'none';
  target.classList.add('email-delete-busy');
  target.appendChild(overlay);
  const ready = new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  return {
    ready,
    remove() {
      try { wp.destroy?.(); } catch (_) {}
      overlay.remove();
      target.classList.remove('email-delete-busy');
      target.style.pointerEvents = prevPointerEvents;
      target.style.position = prevPos;
    }
  };
}

async function _toggleDone(em, itemEl) {
  const newState = !em.is_answered;
  em.is_answered = newState;
  if (newState) em.is_read = true; // mark-done implies mark-read
  if (itemEl) {
    if (newState) {
      _clearDoneResponseTagsLocal(em);
      itemEl.classList.remove('email-unread');
      // Also drop any inline unread indicator dots the renderer may have added
      itemEl.querySelectorAll('.email-unread-dot, [data-unread-dot]').forEach(n => n.remove());
      itemEl.querySelectorAll('.email-tag-urgent, .email-tag-reply-soon, .email-tag-action-needed').forEach(n => n.remove());
    }
    const check = itemEl.querySelector('.email-done-check');
    if (check) check.classList.toggle('active', newState);
  }
  try {
    if (newState) {
      await fetch(`${API_BASE}/api/email/mark-answered/${em.uid}?folder=${encodeURIComponent(_currentFolder)}${_acct()}`, { method: 'POST' });
      await fetch(`${API_BASE}/api/email/mark-read/${em.uid}?folder=${encodeURIComponent(_currentFolder)}${_acct()}`, { method: 'POST' });
    } else {
      await fetch(`${API_BASE}/api/email/clear-answered/${em.uid}?folder=${encodeURIComponent(_currentFolder)}${_acct()}`, { method: 'POST' });
    }
  } catch (e) {
    console.error('Failed to toggle done:', e);
  }
}

async function _createEmailChat(emailData, opts = {}) {
  const subject = String(emailData?.subject || 'New Email').trim() || 'New Email';
  const title = subject === 'New Email' ? 'New Email' : `Email: ${subject.slice(0, 60)}`;
  const forceNew = !!opts.forceNew;
  try {
    const currentSid = sessionModule.getCurrentSessionId?.() || '';
    const current = sessionModule.getSessions?.().find(s => s.id === currentSid);
    const currentIsBlank = !!current
      && !current.archived
      && !current.has_documents
      && !current.has_images
      && Number(current.message_count || 0) === 0
      && current.folder !== 'Assistant'
      && current.folder !== 'Tasks';
    if (!forceNew && currentIsBlank) {
      const meta = document.getElementById('current-meta');
      if (meta) meta.textContent = title;
      return current.id;
    }
    let url = current?.endpoint_url || '';
    let model = current?.model || '';
    let endpointId = current?.endpoint_id || '';
    if (!url || !model) {
      try {
        const dcRes = await fetch(`${API_BASE}/api/default-chat`, { credentials: 'same-origin' });
        const dc = dcRes.ok ? await dcRes.json() : {};
        url = dc.endpoint_url || '';
        model = dc.model || '';
        endpointId = dc.endpoint_id || '';
      } catch (_) {}
    }

    const fd = new FormData();
    fd.append('name', title);
    fd.append('skip_validation', 'true');
    if (url) fd.append('endpoint_url', url);
    if (model) fd.append('model', model);
    if (endpointId) fd.append('endpoint_id', endpointId);
    const res = await fetch(`${API_BASE}/api/session`, { method: 'POST', body: fd, credentials: 'same-origin' });
    if (!res.ok) {
      console.error('email chat create failed', res.status, await res.text().catch(() => ''));
      return '';
    }
    const payload = await res.json().catch(() => ({}));
    const sid = payload?.id || '';
    if (!sid) return '';
    if (sessionModule?.loadSessions) await sessionModule.loadSessions();
    if (sessionModule?.selectSession) await sessionModule.selectSession(sid);
    const meta = document.getElementById('current-meta');
    if (meta) meta.textContent = title;
    return sid;
  } catch (e) {
    console.error('Failed to create email chat:', e);
    return '';
  }
}

async function _composeNew() {
  if (!_docModule) return;
  // NOTE: don't open the panel here. Creating the email-scoped chat below can
  // switch sessions, which tears the panel down — so an early open would mount
  // the pane, get closed, then injectFreshDoc remounts it: a visible flash
  // (doc shows for a frame, then slides up again). Mount once, at injectFreshDoc,
  // after the session + doc exist.
  try {
    let sid = await _createEmailChat({ subject: 'New Email' });
    if (!sid) {
      console.error('compose: could not obtain a session_id');
      import('./ui.js').then(m => m.showError && m.showError('Could not start a new email (no session).')).catch(() => {});
      return;
    }
    const createComposeDoc = (sessionId) => fetch(`${API_BASE}/api/document`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        title: 'New Email',
        content: 'To: \nSubject: \n---\n',
        language: 'email',
      }),
    });
    let res = await createComposeDoc(sid);
    if (res.status === 404) {
      console.warn('[compose-debug] draft session rejected; retrying in a fresh email chat', sid);
      sid = await _createEmailChat({ subject: 'New Email' }, { forceNew: true });
      if (sid) res = await createComposeDoc(sid);
    }
    if (!res.ok) {
      console.error('compose POST failed', res.status, await res.text().catch(() => ''));
      import('./ui.js').then(m => m.showError && m.showError('Failed to create new email (' + res.status + ')')).catch(() => {});
      return;
    }
    const doc = await res.json();
    if (doc.id) {
      await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
      // Use the doc dict from POST directly to avoid the GET 404 race that
      // hits a freshly-created doc on a separate read connection.
      if (_docModule.injectFreshDoc) {
        _docModule.injectFreshDoc(doc);
      } else {
        _docModule.loadDocument(doc.id);
      }
    }
  } catch (e) {
    console.error('Failed to create email:', e);
  }
}

function _esc(text) {
  const div = document.createElement('div');
  div.textContent = text || '';
  return div.innerHTML;
}

function _senderColor(name) {
  if (!name) return 'hsl(220, 55%, 65%)';
  const key = name.toLowerCase();
  let hash = 0;
  for (let i = 0; i < key.length; i++) {
    hash = ((hash << 5) - hash + key.charCodeAt(i)) | 0;
  }
  const hue = ((hash % 360) + 360) % 360;
  return `hsl(${hue}, 55%, 65%)`;
}
