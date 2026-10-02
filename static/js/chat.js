// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/chat.js

/**
 * Main chat functionality - message handling and streaming
 */
// ES6 module — IIFE removed

import Storage from './storage.js';
import uiModule from './ui.js';
import sessionModule from './sessions.js';
import chatRenderer, { buildDiffHtml } from './chatRenderer.js?v=20261002workbenchef';
import chatStream from './chatStream.js?v=20261002workbenchef';
import { addAITTSButton } from './tts-ai.js';
import { prefersReducedMotion } from './motion.js';
import markdownModule from './markdown.js';
import spinnerModule from './spinner.js';
import presetsModule from './presets.js';
import fileHandlerModule from './fileHandler.js?v=20261002workbenchef';
import searchModule from './search.js';
import documentModule from './document.js?v=20260815approvalsave1';
import * as emailInbox from './emailInbox.js?v=20260815approvalsave1';
import codeRunnerModule from './codeRunner.js';
import slashCommands, { initSlashCommands, isCommand, handleSlashCommand, handleSetupInput, handleSetupWizard, typewriterInto } from './slashCommands.js?v=20260815approvalsave1';
import createResearchSynapse from './researchSynapse.js';
import { createStreamRenderer } from './streamingRenderer.js';
import { applyAgentThreadNode, verifierCardOptions, blockedCardOptions,
         toolOutputPanesHtml, agentThreadContent, ensureThreadToggleAll,
         toggleThreadAll, syncThreadToggleAll, TOOL_LABELS } from './agentThread.js';
// `B918` / `B916`. A tool card's life on screen, and the spinner a new step
// opens with, shared with a compare pane.
import { startToolCard as _startToolCard, drawToolProgress as _drawToolProgress,
         finishToolCard as _finishToolCard, stopCardTickers as _stopCardTickers,
         openRoundSpinner as _openRoundSpinner } from './agentTurn.js';
// `P4-10`. The line that says why the agent stopped itself — and (`B915`) the
// turn's other notes, drawn by the same module for the reload; (`B921`) the
// compaction notice's words.
import { renderAgentStop, renderAgentNote, compactionNoticeText } from './agentStops.js';
import { wireArrowUpRecall, getUserMessagesFromChatHistory } from './composerArrowUpRecall.js?v=20260714promptrecall';
import {
  createIncrementalDisplayProjector,
  createLiveThinkingThrottle,
  createThinkingAnalysisGate,
  stripLiveThinkingTags,
} from './liveThinkingThrottle.js';
import {
  applyModelMetricsState,
  applyModelRouteEventState,
  inheritModelRouteState,
} from './chatModelProvenance.js';
import { createTerminalStreamError, isRecoverableStreamError } from './chatStreamErrors.js';
import { createAgentMeter, presentMeterEvent, METER_EVENT_TYPES, renderLimitsHint } from './agentMeter.js';   // P4-08 / P4-23 / P4-24 / P7-10
import { loadPanel } from './panels.js';
import planWindow from './planWindow.js';
import * as contextUsage from './contextUsage.js';
// `P10-06`. The context panel closes through the one popup registry, like
// every other popup appended to <body> (see `_openContextPanel`).
import { bindMenuDismiss, dismissOrRemove } from './escMenuStack.js';
import queuePanel from './queuePanel.js?v=20261002workbenchef';
import { runStatusLabel } from './runStatus.js';
import { playIcon, stopIcon } from './icons.js';
import {
  documentLanguage,
  ingestKindFromName,
  isExtractedExtension,
  INGEST_KIND_TEXT,
  INGEST_KIND_DOCUMENT,
} from './attachmentLanguage.js';
import agentDrafts from './agentDrafts.js';   // H01
import { FIRST_TOKEN_WAIT_FROM_MS, endsFirstTokenWait, firstTokenWaitText } from './agentMeter.js';   // B907

  const RESEARCH_TIMEOUT_MS = 360000;
  const DEFAULT_TIMEOUT_MS = 120000;
  const RUN_ID_ABORT_GRACE_MS = 2000; // timeout waits this long for a run-id header before hard-aborting
  const RESEARCH_SVG = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>';

  let API_BASE = '';
  let currentAbort = null;
  let isStreaming = false;
  // Continuous stall watchdog: while streaming, if the SSE stream produces
  // NOTHING for STALL_THRESHOLD_MS (no deltas, no tool heartbeat — tools beat
  // every 2s, so a full minute of silence means it's genuinely stuck or the
  // model quietly stopped), surface a non-destructive "still working?" prompt
  // instead of silently hanging. Replaces relying only on the tab-refocus
  // recovery (which fired only on visibilitychange and silently reloaded).
  let _stallWatchdog = null;
  let _stallBannerShown = false;
  const STALL_THRESHOLD_MS = 60000;
  let _sendInFlight = false;   // covers the window from click → streaming start
  let _displayOverride = null; // Override visible user bubble text (hides injected prompts)
  let _hideUserBubble = false; // Skip user bubble entirely (e.g. continue after stop)
  let _contextHeaderSeq = 0;
  let _contextHeaderData = null;
  let _contextHeaderBound = false;
  let _pendingToolApproval = null;

  /**
   * The model route a send would use right now: the one picked in the last ten
   * minutes, else the pending chat's, else the open chat's. It is what
   * `handleChatSubmit` posts as `selected_*`, and `P7-10` lifted it out of that
   * function unchanged so the composer's limits hint asks the server about the
   * very route the next send will run on, rather than a second guess at it.
   */
  export function selectedRoute() {
    try {
      const lastPicked = window.__pantheonLastPickedRoute || null;
      if (lastPicked && lastPicked.model && Date.now() - (lastPicked.picked_at || 0) < 10 * 60 * 1000) {
        return {
          model: lastPicked.model || '',
          endpoint_url: lastPicked.endpoint_url || '',
          endpoint_id: lastPicked.endpoint_id || '',
          source: 'last-picked',
        };
      }
      const pending = sessionModule.getPendingChat && sessionModule.getPendingChat();
      if (pending && pending.modelId) {
        return {
          model: pending.modelId || '',
          endpoint_url: pending.url || '',
          endpoint_id: pending.endpointId || '',
          source: pending.source || '',
        };
      }
      return {
        model: sessionModule.getCurrentModel ? (sessionModule.getCurrentModel() || '') : '',
        endpoint_url: sessionModule.getCurrentEndpointUrl ? (sessionModule.getCurrentEndpointUrl() || '') : '',
        endpoint_id: '',
        source: '',
      };
    } catch (_) {
      return { model: '', endpoint_url: '', endpoint_id: '', source: '' };
    }
  }

  // `P7-10`. How far one message in Agent mode may go, said beside the mode
  // toggle before it is sent. The server answers with the limits the loop will
  // enforce on the selected route — the step cap after the local lift, and the
  // tool-call cap — and `agentMeter.renderLimitsHint` says them in the meter's
  // own words. Asked again whenever the answer can have changed: the model or
  // chat changes, Agent is chosen, the Agent settings are saved, or the page
  // comes back into view. The sequence number drops an answer that arrives
  // after a newer question, so a slow reply cannot paint a stale model's limit.
  let _agentLimitsSeq = 0;
  export async function refreshAgentLimitsHint() {
    const node = document.getElementById('agent-limits-hint');
    if (!node) return null;
    const route = selectedRoute();
    const query = new URLSearchParams();
    if (route.endpoint_id) query.set('endpoint_id', route.endpoint_id);
    if (route.endpoint_url) query.set('endpoint_url', route.endpoint_url);
    const qs = query.toString();
    const seq = ++_agentLimitsSeq;
    let limits = null;
    try {
      const res = await fetch(API_BASE + '/api/chat/agent-limits' + (qs ? '?' + qs : ''),
        { credentials: 'same-origin' });
      if (res && res.ok) limits = await res.json();
    } catch (_) {
      limits = null;
    }
    if (seq !== _agentLimitsSeq) return null;
    return renderLimitsHint(node, limits);
  }

  function _wireAgentLimitsHint() {
    const refresh = () => { refreshAgentLimitsHint(); };
    document.addEventListener('pantheon:model-picked', refresh);
    document.addEventListener('pantheon:session-changed', refresh);
    document.addEventListener('pantheon:agent-limits-changed', refresh);
    const agentBtn = document.getElementById('mode-agent-btn');
    if (agentBtn) agentBtn.addEventListener('click', refresh);
    window.addEventListener('focus', refresh);
    refresh();
  }

  function _submitToolApprovalWhenIdle(approvalId) {
    if (
      !_pendingToolApproval
      || _pendingToolApproval.approval_id !== approvalId
    ) return;
    if (isStreaming || _sendInFlight) {
      setTimeout(() => _submitToolApprovalWhenIdle(approvalId), 120);
      return;
    }
    const input = document.getElementById('message');
    if (input) {
      _pendingToolApproval.draft = input.value || '';
    }
    const sendButton = document.querySelector('.send-btn');
    if (sendButton) sendButton.click();
  }

  document.addEventListener('pantheon:tool-approval', (event) => {
    const detail = event && event.detail ? event.detail : {};
    const decision = String(detail.decision || '').toLowerCase();
    if (!detail.approval_id || !['approve', 'approve_task', 'deny'].includes(decision)) return;
    _pendingToolApproval = {
      approval_id: String(detail.approval_id),
      decision,
      document_id: String(detail.document_id || ''),
    };
    _submitToolApprovalWhenIdle(_pendingToolApproval.approval_id);
  });

  function _contextColorClass(pct) {
    const n = Number(pct || 0);
    if (n >= 85) return 'danger';
    if (n >= 70) return 'warn';
    return '';
  }

  function _contextRingColor(pct) {
    const n = Number(pct || 0);
    if (n >= 85) return 'var(--red, #e06c75)';
    if (n >= 70) return '#ff9900';
    return 'var(--green, #98c379)';
  }

  function _contextRingMarkup(pct, { includeLabel = true, labelId = '' } = {}) {
    const value = Math.max(0, Math.min(100, Number(pct || 0)));
    const r = 6;
    const stroke = 1.5;
    const circ = 2 * Math.PI * r;
    const fill = circ * (value / 100);
    const label = value.toFixed(value >= 10 ? 0 : 1);
    const idAttr = labelId ? ` id="${labelId}"` : '';
    return `<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
        <circle cx="7" cy="7" r="${r}" fill="none" stroke="var(--border, #333)" stroke-width="${stroke}" opacity="0.3"/>
        <circle cx="7" cy="7" r="${r}" fill="none" stroke="var(--ctx-stroke)" stroke-width="${stroke}"
          stroke-dasharray="${fill} ${circ - fill}" stroke-dashoffset="${circ * 0.25}"
          stroke-linecap="round" transform="rotate(-90 7 7)"/>
      </svg>${includeLabel ? `<span class="ctx-ring-pct"${idAttr}>${label}%</span>` : ''}`;
  }

  // `B892`. The wheel draws each category as its own arc; `contextUsage.js`
  // owns the drawing so the panel and the wheel read one payload one way.
  function _renderContextHeaderRing(pill, data) {
    const pct = contextUsage.usageFigures(data).pct;
    pill.style.setProperty('--ctx-color', _contextRingColor(pct));
    contextUsage.renderPill(pill, data, { pendingCount: _pendingAttachmentCount() });
  }

  function _pendingAttachmentCount() {
    try { return Number(fileHandlerModule.getPendingCount()) || 0; } catch (_) { return 0; }
  }

  function _renderCompactMenuContextIcon(pct) {
    const icon = document.querySelector('#export-compact-btn .dropdown-icon');
    if (!icon) return;
    const value = Math.max(0, Math.min(100, Number(pct || 0)));
    const row = document.getElementById('export-compact-btn');
    const color = _contextRingColor(value);
    if (row) row.style.setProperty('--ctx-color', color);
    icon.style.setProperty('--ctx-color', color);
    icon.innerHTML = _contextRingMarkup(value, { includeLabel: false });
  }

  function _liveSessionModule() {
    return (window.sessionModule && window.sessionModule.getCurrentSessionId)
      ? window.sessionModule
      : sessionModule;
  }

  // `B892`. The allowance meter's home while the panel is shut: a hidden
  // wrapper in the composer. The panel adopts `#context-meter` when it opens
  // and hands it back here when it closes.
  function _returnContextMeterHome() {
    const meter = document.getElementById('context-meter');
    const home = document.getElementById('context-meter-home');
    if (meter && home && meter.parentNode !== home) {
      if (meter.parentNode) meter.parentNode.removeChild(meter);
      home.appendChild(meter);
    }
  }

  function _closeContextHeaderPopup() {
    // `P10-06`. Through the panel's own dismiss, so its Escape-stack entry and
    // outside-click listener go with it; a bare `remove()` left both behind.
    document.querySelectorAll('.chat-context-popup').forEach(dismissOrRemove);
    _returnContextMeterHome();
    const pill = document.getElementById('chat-context-pill');
    if (pill) {
      pill.classList.remove('open');
      pill.setAttribute('aria-expanded', 'false');
    }
  }

  // The wheel sits at the bottom of the screen, so the panel opens upward and
  // right-aligned to it, and only drops below when there is no room above.
  function _positionContextHeaderPopup(popup, pill) {
    const rect = pill.getBoundingClientRect();
    document.body.appendChild(popup);
    const pRect = popup.getBoundingClientRect();
    const above = rect.top - 8;
    const below = window.innerHeight - rect.bottom - 8;
    const openUp = above >= pRect.height || above >= below;
    const room = Math.max(160, (openUp ? above : below) - 8);
    popup.style.maxHeight = `${Math.round(room)}px`;
    const height = Math.min(pRect.height, room);
    popup.style.top = openUp
      ? `${Math.round(Math.max(8, rect.top - height - 8))}px`
      : `${Math.round(rect.bottom + 8)}px`;
    let left = rect.right - pRect.width;
    left = Math.max(8, Math.min(left, window.innerWidth - pRect.width - 8));
    popup.style.left = `${Math.round(left)}px`;
  }

  function _showContextHeaderPopup() {
    const pill = document.getElementById('chat-context-pill');
    if (!pill || pill.hidden) return;
    const wasOpen = pill.classList.contains('open');
    _closeContextHeaderPopup();
    if (wasOpen) return;
    _openContextPanel(pill);
  }

  function _openContextPanel(pill) {
    const d = _contextHeaderData;
    const pct = Number(contextUsage.usageFigures(d).pct || 0);
    const colorClass = d ? _contextColorClass(pct) : '';
    let pending = [];
    try { pending = fileHandlerModule.getPendingInfo() || []; } catch (_) { pending = []; }
    const popup = contextUsage.buildUsagePanel(document, d, {
      pending,
      meterHost: document.getElementById('context-meter'),
    });
    popup.classList.add('chat-context-popup');
    if (colorClass) popup.classList.add(colorClass);

    if (d) {
      // What the header popup always said, kept (`Law 1`): the model the
      // window belongs to, how many messages it holds, and where compaction
      // starts on its own.
      const modelShort = String(d.model || 'Unknown').split('/').pop();
      const rows = [
        ['Window model', modelShort],
        ['Messages', `${Number(d.messages || 0).toLocaleString()}`],
        ['Auto compact', `at ${Number(d.auto_compact_threshold || 85)}%`],
      ];
      const facts = document.createElement('div');
      facts.className = 'chat-context-popup-facts';
      rows.forEach(([label, value]) => {
        const row = document.createElement('div');
        row.className = 'chat-context-popup-row';
        const a = document.createElement('span');
        a.textContent = label;
        const b = document.createElement('span');
        b.textContent = value;
        row.appendChild(a);
        row.appendChild(b);
        facts.appendChild(row);
      });
      popup.appendChild(facts);
    }

    if (d && d.can_compact) {
      const compactBtn = document.createElement('button');
      compactBtn.type = 'button';
      compactBtn.className = 'chat-context-compact-btn';
      compactBtn.textContent = 'Compact';
      compactBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        compactBtn.disabled = true;
        compactBtn.replaceChildren();
        try {
          const wp = spinnerModule.createWhirlpool(13);
          wp.element.style.margin = '0 5px 0 0';
          compactBtn.appendChild(wp.element);
        } catch (_) {}
        compactBtn.appendChild(document.createTextNode('Compacting'));
        const ok = await compactCurrentChatContext();
        if (!ok) {
          compactBtn.disabled = false;
          compactBtn.textContent = 'Compact failed';
        }
      });
      popup.appendChild(compactBtn);
    }

    pill.classList.add('open');
    pill.setAttribute('aria-expanded', 'true');
    _positionContextHeaderPopup(popup, pill);
    // `P10-06`. This panel is one of the popups `escMenuStack.js` exists for,
    // and it was the one that did not use it: it put a `pointerdown` and a
    // capture-phase `keydown` listener on `document` and took them off only
    // from inside its own handler. Measured 2026-09-27 in Chromium against the
    // running app: (1) closed from the wheel and opened again, the first
    // panel's listeners were still there, so a click INSIDE the second panel
    // closed it; (2) with the docked Notes pane open, one Escape closed the
    // panel AND Notes — the arbiter in `ui.js` did not know the panel existed,
    // so it let the key through to the next listener; (3) opened with Enter,
    // the focus stayed on the wheel, six Tab presses (Agent, Chat, Send, the
    // scroll button, a toast) from the panel's first row. `bindMenuDismiss`
    // answers all three: one entry on the Escape stack, one outside-click
    // listener that goes when the panel goes, and — opened from the keyboard —
    // the focus on the panel's first row and back on the wheel when it shuts.
    //
    // The allowance meter goes home BEFORE the panel leaves the page. The
    // other order — which the old close had — detaches the meter inside the
    // panel, `getElementById('context-meter')` no longer finds it, and it is
    // gone until a reload: measured the same day, one file waiting, panel
    // opened and closed, `#context-meter` absent from the document.
    bindMenuDismiss(popup, () => {
      _returnContextMeterHome();
      popup.remove();
      pill.classList.remove('open');
      pill.setAttribute('aria-expanded', 'false');
    }, (ev) => !popup.contains(ev.target) && !pill.contains(ev.target));
  }

  // `B892`. The attachments section of an open panel follows the composer: a
  // file added or removed while it is open is listed or dropped at once, and
  // the wheel itself appears for a new chat as soon as something is attached.
  function _syncContextPillToAttachments() {
    const pill = document.getElementById('chat-context-pill');
    if (!pill) return;
    const pending = _pendingAttachmentCount();
    const sm = _liveSessionModule();
    const sid = sm && sm.getCurrentSessionId && sm.getCurrentSessionId();
    pill.hidden = !sid && !pending;
    if (!sid) _contextHeaderData = null;
    _renderContextHeaderRing(pill, _contextHeaderData);
    if (pill.hidden) { _closeContextHeaderPopup(); return; }
    if (pill.classList.contains('open')) {
      _closeContextHeaderPopup();
      _openContextPanel(pill);
    }
  }
  let _attachSyncQueued = false;
  try {
    window.addEventListener('pantheon:attachments-changed', () => {
      if (_attachSyncQueued) return;
      _attachSyncQueued = true;
      setTimeout(() => { _attachSyncQueued = false; _syncContextPillToAttachments(); }, 0);
    });
  } catch (_) {}

  function _bindContextHeaderPill() {
    if (_contextHeaderBound) return;
    _contextHeaderBound = true;
    const pill = document.getElementById('chat-context-pill');
    if (!pill) return;
    pill.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      _showContextHeaderPopup();
    });
  }

  export async function compactCurrentChatContext() {
    const sm = _liveSessionModule();
    const sid = sm && sm.getCurrentSessionId && sm.getCurrentSessionId();
    if (!sid) {
      uiModule.showToast('Open a chat first');
      return false;
    }
    try {
      const res = await fetch(`/api/session/${encodeURIComponent(sid)}/compact`, { method: 'POST' });
      if (!res.ok) throw new Error(await res.text());
      uiModule.showToast('Context compacted');
      _closeContextHeaderPopup();
      if (sm && sm.selectSession) await sm.selectSession(sid, { keepSidebar: true, showLoading: false });
      refreshChatContextHeader('compact');
      return true;
    } catch (err) {
      uiModule.showError(`Compact failed: ${err.message || err}`);
      return false;
    }
  }
  try { window.compactCurrentChatContext = compactCurrentChatContext; } catch (_) {}

  export async function refreshChatContextHeader(reason = '') {
    _bindContextHeaderPill();
    const pill = document.getElementById('chat-context-pill');
    if (!pill) return;
    const sm = _liveSessionModule();
    const sid = sm && sm.getCurrentSessionId && sm.getCurrentSessionId();
    const seq = ++_contextHeaderSeq;
    if (!sid) {
      // `B892`. A new chat has no window yet, but a file attached to its
      // first message still has somewhere to be seen.
      _contextHeaderData = null;
      pill.hidden = !_pendingAttachmentCount();
      _renderContextHeaderRing(pill, null);
      if (pill.hidden) _closeContextHeaderPopup();
      return;
    }
    pill.hidden = false;
    pill.classList.add('loading');
    try {
      const res = await fetch(`/api/session/${encodeURIComponent(sid)}/context`, { credentials: 'same-origin' });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      if (seq !== _contextHeaderSeq) return;
      const latestSm = _liveSessionModule();
      if (!latestSm.getCurrentSessionId || latestSm.getCurrentSessionId() !== sid) return;
      _contextHeaderData = data;
      const pct = Number(contextUsage.usageFigures(data).pct || 0);
      _renderContextHeaderRing(pill, data);
      _renderCompactMenuContextIcon(pct);
      pill.classList.remove('loading');
      if (pill.classList.contains('open')) {
        _closeContextHeaderPopup();
        _showContextHeaderPopup();
      }
    } catch (err) {
      if (seq !== _contextHeaderSeq) return;
      _contextHeaderData = null;
      pill.hidden = !_pendingAttachmentCount();
      pill.classList.remove('loading', 'warn', 'danger');
      _renderContextHeaderRing(pill, null);
      _closeContextHeaderPopup();
      console.warn('context header refresh failed:', reason, err);
    }
  }
  try { window.refreshChatContextHeader = refreshChatContextHeader; } catch (_) {}

  /** `B81`. The composer's own answer to "can a steer reach the run this turn
   *  is about to start", computed where the terms actually live.
   *
   *  `routes/chat_routes.py` `_stream_is_steerable` decides it from four terms:
   *  `chat_mode`, `do_research`, `is_image_session` and `compare_mode`. Two of
   *  them are readable here, at the moment of sending, and this reads exactly
   *  those two and no more — it is not a second copy of the predicate, it is
   *  the terms the client can honestly evaluate, and the run's own
   *  `stream_steerable` (`B14`) still overrules it in both directions.
   *
   *  `chatStream.js` used to guess from the mode toggle alone, which is why a
   *  research turn drew a bar: research is sent in agent mode, so the mode term
   *  says nothing about it. The research toggle is still checked at this point
   *  in the send path — it is cleared further down, just before the POST, which
   *  is precisely why the guess had to be made HERE and not read back later.
   *
   *  The two it cannot answer, stated rather than faked:
   *    · `is_image_session` is a model/endpoint-registry question the client
   *      has no equivalent of, and inventing one would be a second predicate
   *      (`Law 14`);
   *    · `compare_mode` never reaches this edge at all — `compare/stream.js`
   *      POSTs `/api/chat_stream` itself and never calls this function, so no
   *      bar is drawn from a compare pane in the first place.
   *  Both are left to the run's answer, which is the only thing that can know.
   *
   *  Returns true when nothing the composer can see argues against it: an old
   *  server that never sends `stream_steerable` then behaves exactly as it does
   *  today, which is the half of this that must not regress.
   */
  function _composerTurnSteerable() {
    try {
      const el = uiModule.el;
      const research = el && el('research-toggle');
      if (research && research.checked) return false;
      const mode = window.__pantheonGetChatMode && window.__pantheonGetChatMode();
      if (mode === 'chat') return false;
      return true;
    } catch (_) {
      return true;
    }
  }

  /** `steerable` is this turn's provisional verdict (`B81`), or undefined from
   *  the call sites that are re-announcing a busy state rather than starting a
   *  turn — notably `setStreamingState('streaming')`, which fires AFTER the
   *  research toggle has been cleared and would compute the wrong answer if it
   *  tried. Listeners keep the last verdict they were given until the run ends. */
  function _setForegroundChatBusy(active, steerable) {
    try {
      window.__pantheonChatBusy = !!active;
      window.__pantheonChatBusyUntil = active ? Date.now() + 120000 : Date.now() + 1200;
      const detail = { active: !!active };
      if (typeof steerable === 'boolean') detail.steerable = steerable;
      window.dispatchEvent(new CustomEvent('pantheon:chat-busy-change', { detail }));
    } catch (_) {}
  }
  let _pendingContinue = null; // Stores the stopped AI element to merge with new response
  // `B941`: the pending continue carries on an agent run's steps (Continue ▸
  // after the step limit) rather than a stopped reply's text.
  let _pendingContinueSteps = false;
  function _createChatSendPerf() {
    const started = (performance && performance.now) ? performance.now() : Date.now();
    let last = started;
    let reported = false;
    const stages = [];
    const now = () => (performance && performance.now) ? performance.now() : Date.now();
    return {
      mark(name) {
        const t = now();
        stages.push({ name, delta_ms: Math.round(t - last), at_ms: Math.round(t - started) });
        last = t;
      },
      report(extra) {
        if (reported) return;
        const total = Math.round(now() - started);
        const slowStage = stages.some(s => (s.delta_ms || 0) >= 1500);
        if (total < 1500 && !slowStage) return;
        reported = true;
        const payload = JSON.stringify({
          type: 'chat_send',
          total_ms: total,
          stages,
          extra: extra || '',
          session: sessionModule && sessionModule.getCurrentSessionId ? sessionModule.getCurrentSessionId() : '',
        });
        try {
          if (navigator.sendBeacon) {
            navigator.sendBeacon(`${API_BASE}/api/client-perf`, new Blob([payload], { type: 'application/json' }));
            return;
          }
        } catch (_) {}
        try {
          fetch(`${API_BASE}/api/client-perf`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: payload,
            keepalive: true,
            credentials: 'same-origin',
          }).catch(() => {});
        } catch (_) {}
      }
    };
  }

  function _hashSessionCandidate() {
    try {
      const hashId = String(window.location.hash || '').replace(/^#/, '').trim();
      if (!hashId) return '';
      if (/^(document|note|image|email|event|task|skill|research)-/.test(hashId) || /^open=notes&note=/.test(hashId)) return '';
      return hashId;
    } catch (_) {
      return '';
    }
  }

  async function _adoptOpenedSessionBeforeAutoCreate() {
    if (!sessionModule || !sessionModule.getCurrentSessionId || sessionModule.getCurrentSessionId()) return true;
    // Don't adopt a stale session when the user explicitly started a New Chat
    // (pending state set) — the send path must materialize the pending session.
    if (sessionModule.hasPendingChat && sessionModule.hasPendingChat()) return false;
    const activeRowId = document.querySelector('.list-item.active-session[data-session-id], .session-item.active[data-session-id]')?.dataset?.sessionId || '';
    const hashId = _hashSessionCandidate();
    const lastSelectedId = String(window.__pantheonLastSelectedSessionId || '').trim();
    const targetId = activeRowId || hashId || lastSelectedId;
    if (!targetId) return false;
    try {
      window.__pantheonComposerUserEdited = true;
      if (sessionModule.selectSession) {
        await sessionModule.selectSession(targetId, { keepSidebar: true, showLoading: false });
      } else if (sessionModule.setCurrentSessionId) {
        sessionModule.setCurrentSessionId(targetId);
      }
      return !!(sessionModule.getCurrentSessionId && sessionModule.getCurrentSessionId());
    } catch (_) {
      return false;
    }
  }

  // ── Auto-recovery: when a turn's stream silently dies (connection drop) or
  // goes quiet while the connection is alive, re-engage the model with a
  // completion handshake instead of leaving it hung. Capped so it can't loop.
  let _autoNudges = 0;             // handshakes fired for the CURRENT user turn
  let _autoContinuePending = false; // marks the next submit as an auto-continue (don't reset the counter)
  const _AUTO_NUDGE_CAP = 3;

  // shortModel and modelColor are now in chatRenderer.js
  var _shortModel = chatRenderer.shortModel;
  var _modelRouteLabel = chatRenderer.modelRouteLabel;
  var _sameModelName = chatRenderer.sameModelName;
  var _applyModelColor = chatRenderer.applyModelColor;
  function _setRoleModelLabel(roleEl, requestedModel, actualModel, opts) {
    if (!roleEl) return;
    opts = opts || {};
    const tsSpan = roleEl.querySelector('.role-timestamp');
    const req = requestedModel || actualModel || '';
    const actual = actualModel || requestedModel || '';
    let label = _modelRouteLabel(
      req,
      actual,
      opts.requestedEndpointLabel,
      opts.actualEndpointLabel,
      opts.requestedEndpointId,
      opts.actualEndpointId,
    );
    if (opts.suffix) label += ' (' + opts.suffix + ')';
    if (opts.characterName) label = opts.characterName;
    roleEl.textContent = label + ' ';
    _applyModelColor(roleEl, actual || req);
    const endpointChanged = Boolean(
      opts.requestedEndpointId
      && opts.actualEndpointId
      && opts.requestedEndpointId !== opts.actualEndpointId
    );
    if (req && actual && (!_sameModelName(req, actual) || endpointChanged)) {
      roleEl.title = req + ' -> ' + actual
        + (endpointChanged ? ' (' + opts.requestedEndpointLabel + ' -> ' + opts.actualEndpointLabel + ')' : '')
        + (opts.reason ? ': ' + opts.reason : '');
    } else if (!opts.reason) {
      roleEl.removeAttribute('title');
    }
    if (tsSpan) roleEl.appendChild(tsSpan);
  }

  function _bestKnownStreamModel(routeSnapshot) {
    try {
      const current = sessionModule.getCurrentModel ? sessionModule.getCurrentModel() : '';
      if (current) return current;
    } catch (_) {}
    try {
      const pending = sessionModule.getPendingChat && sessionModule.getPendingChat();
      if (pending && pending.modelId) return pending.modelId;
    } catch (_) {}
    try {
      const lastPicked = window.__pantheonLastPickedRoute || null;
      if (lastPicked && lastPicked.model && Date.now() - (lastPicked.picked_at || 0) < 10 * 60 * 1000) {
        return lastPicked.model;
      }
    } catch (_) {}
    if (routeSnapshot && routeSnapshot.model) return routeSnapshot.model;
    try {
      const dc = window.__pantheonDefaultChat || JSON.parse(localStorage.getItem('pantheon-default-chat-cache') || 'null');
      if (dc && dc.model) return dc.model;
    } catch (_) {}
    return '';
  }
  // Per-session research tracking (supports concurrent research across sessions)
  const _researchingStreamIds = new Set();
  let _researchTimerEl = null, _researchTimerInterval = null;
  let _researchStartTime = 0, _researchAvgDuration = null;
  let _researchSynapse = null;
  function _clearResearchTimer() {
    if (_researchTimerInterval) { clearInterval(_researchTimerInterval); _researchTimerInterval = null; }
    if (_researchTimerEl) { _researchTimerEl.remove(); _researchTimerEl = null; }
    if (_researchSynapse) {
      // Mark complete first so the user briefly sees the "done" state,
      // then tear it down on next tick.
      try { _researchSynapse.complete(); } catch {}
      const s = _researchSynapse;
      _researchSynapse = null;
      setTimeout(() => { try { s.destroy(); } catch {} }, 800);
    }
    _researchStartTime = 0;
    _researchAvgDuration = null;
  }

  /** Append a "Generate Visual Report" button — delegates to chatRenderer. */
  function _appendViewReportLink(msgEl, sessionId) {
    const body = msgEl.querySelector('.body');
    if (body) chatRenderer.appendReportButton(body, sessionId);
  }

  function _stripDocumentFenceForChat(text, { final = false } = {}) {
    let s = String(text || '').replace(/<?\|end\|>?/g, '');
    const markerMatch = /```(?:create_document|documen(?:t)?)\s*\n/i.exec(s);
    if (!markerMatch) return s;
    const before = s.slice(0, markerMatch.index).trimEnd();
    const fenceStart = markerMatch.index;
    const openingEnd = s.indexOf('\n', fenceStart);
    const closeIdx = openingEnd >= 0 ? s.indexOf('\n```', openingEnd + 1) : -1;
    const after = closeIdx >= 0 ? s.slice(closeIdx + 4).trimStart() : '';
    const visible = [before, after].filter(Boolean).join('\n\n').trim();
    return final && !visible ? 'Done.' : visible;
  }

  function _stripIncompleteRawToolJsonForChat(text) {
    const s = String(text || '');
    const starts = ['[{"function"', '[\n{"function"', '{"function"'];
    let idx = -1;
    for (const marker of starts) idx = Math.max(idx, s.lastIndexOf(marker));
    if (idx < 0) return s;
    const tail = s.slice(idx);
    // Complete raw OpenAI-style function blobs are removed by stripToolBlocks.
    // While the stream is still mid-JSON, hide the tail so it never flashes in
    // the chat bubble as prose.
    if (!/"type"\s*:\s*"function"/.test(tail) || !/\}\s*\]?\s*(?:<\/?\|(?:assistant|assistan|user|system|tool)\|>?)?\s*$/i.test(tail)) {
      return s.slice(0, idx);
    }
    return s;
  }

  function _streamDisplayText(text, opts = {}) {
    return stripToolBlocks(_stripIncompleteRawToolJsonForChat(_stripDocumentFenceForChat(text, opts)));
  }

  function _showDocumentWritingStatus(contentEl) {
    const msg = contentEl && contentEl.closest ? contentEl.closest('.msg') : null;
    const chatBox = document.getElementById('chat-history');
    if (!msg || !chatBox) {
      if (contentEl) contentEl.textContent = 'Writing...';
      return;
    }
    let thread = msg._docWritingThread;
    if (!thread || !thread.isConnected) {
      thread = document.createElement('div');
      thread.className = 'agent-thread streaming has-bottom';
      thread.dataset.docWriting = '1';
      const prev = msg.previousElementSibling;
      if (prev && (prev.classList.contains('msg') || prev.classList.contains('agent-thread'))) {
        thread.classList.add('has-top');
      }
      const node = document.createElement('div');
      // Not a tool call — the document writer's own thread — so the label is
      // given rather than looked up. Same shell as every other card (`P4-01`).
      applyAgentThreadNode(node, { tool: '', state: 'running', label: 'Writing' });
      thread.appendChild(node);
      chatBox.insertBefore(thread, msg);
      msg._docWritingThread = thread;

      const waveEl = node.querySelector('.agent-thread-wave');
      if (waveEl) {
        const waveFrames = ['▁▂▃', '▂▃▄', '▃▄▅', '▄▅▆', '▅▆▇', '▆▅▄', '▅▄▃', '▄▃▂'];
        let waveIdx = 0;
        node._waveInterval = setInterval(() => {
          waveIdx = (waveIdx + 1) % waveFrames.length;
          waveEl.textContent = waveFrames[waveIdx];
        }, 100);
      }
      node._startTime = Date.now();
      node._elapsedTicker = setInterval(() => {
        const hdr = node.querySelector('.agent-thread-header');
        if (!hdr) return;
        let el = hdr.querySelector('.agent-thread-elapsed');
        if (!el) {
          el = document.createElement('span');
          el.className = 'agent-thread-elapsed';
          const icon = hdr.querySelector('.agent-thread-icon');
          if (icon && icon.nextSibling) hdr.insertBefore(el, icon.nextSibling);
          else hdr.appendChild(el);
        }
        const s = (Date.now() - node._startTime) / 1000;
        el.textContent = s < 60 ? `${s.toFixed(2)}s` : `${Math.floor(s / 60)}m ${(s % 60).toFixed(2).padStart(5, '0')}s`;
      }, 50);
    }
    msg.style.display = 'none';
  }

  function _finishDocumentWritingStatus(msg, ok = true) {
    const thread = msg && msg._docWritingThread;
    if (!thread || !thread.isConnected) return;
    thread.classList.remove('streaming');
    const node = thread.querySelector('.agent-thread-node');
    if (!node) return;
    if (node._waveInterval) { clearInterval(node._waveInterval); node._waveInterval = null; }
    if (node._elapsedTicker) { clearInterval(node._elapsedTicker); node._elapsedTicker = null; }
    node.classList.remove('running');
    if (!ok) node.classList.add('error');
    const icon = node.querySelector('.agent-thread-icon');
    if (icon) icon.textContent = ok ? '✓' : '✗';
    const wave = node.querySelector('.agent-thread-wave');
    if (wave) wave.remove();
    if (!node.querySelector('.agent-thread-status')) {
      const status = document.createElement('span');
      status.className = 'agent-thread-status';
      status.textContent = ok ? 'done' : 'failed';
      const header = node.querySelector('.agent-thread-header');
      if (header) header.appendChild(status);
    }
  }

  let currentAccumulated = ''; // Track accumulated text across function scope
  let currentHolder = null; // Track current message holder
  let currentSpinner = null; // Track current spinner for stop cleanup

  // Background streaming support
  const _backgroundStreams = new Map(); // sessionId -> { status, accumulated, sourcesHtml, abortCtrl, query, metrics }
  const _activeStreams = new Map();     // sessionId -> { abortCtrl, holder, query, startedAt, cancelViewWork, finalizeView }
  const _resumingStreams = new Set();   // sessionId -> a resumeStream() reader is live (re-attach lock)
  const _terminalSavedStreams = new Set(); // sessionId -> canonical terminal event seen by active reader
  const _streamRunIds = new Map();      // sessionId -> opaque identity of the current send's detached run
  const _streamGenerations = new Map(); // sessionId -> generation of the current (latest) send
  const _sendStates = new Map();        // sessionId -> { generation, abortCtrl } of the current send, installed synchronously at send commit so Stop never has to borrow an older send's controller
  const _pendingRunStops = new Map();   // 'sessionId:generation' -> abortCtrl|null; Stop queued for that send while it awaits headers. Keyed per send so concurrent sends' cancellation intents never displace each other.
  let _streamSessionId = null; // Session ID for the currently active reader loop
  let _lastReaderActivity = 0; // Timestamp of last reader.read() success — used to detect frozen streams
  let _webLockRelease = null;  // Function to release the Web Lock held during streaming
  let _staleStreamProbeInFlight = false;
  const STALE_LOCAL_STREAM_MS = 15000;

  /** Check if an SSE reader is still actively connected for a session. */
  function hasActiveStream(sessionId) {
    return _activeStreams.has(sessionId) || _streamSessionId === sessionId || _backgroundStreams.has(sessionId) ||
           _resumingStreams.has(sessionId);
  }

  function _getForegroundStreamState() {
    try {
      const sid = sessionModule && sessionModule.getCurrentSessionId && sessionModule.getCurrentSessionId();
      return sid ? (_activeStreams.get(sid) || null) : null;
    } catch (_) {
      return null;
    }
  }

  function _syncForegroundStreamGlobals() {
    const active = _getForegroundStreamState();
    isStreaming = !!active;
    currentAbort = active ? active.abortCtrl : null;
    currentHolder = active ? active.holder : null;
    _setForegroundChatBusy(!!active || !!_sendInFlight);
    return active;
  }

  function _touchStreamActivity(sessionId) {
    const now = Date.now();
    _lastReaderActivity = now;
    const active = sessionId ? _activeStreams.get(sessionId) : null;
    if (active) active.lastActivity = now;
    return now;
  }

  /** Stable cost identity for one logical metrics segment within a run. */
  function _metricsCostRecordId(runId, event) {
    if (!runId) return '';
    return `${runId}:${event && event.teacher ? 'teacher' : 'primary'}`;
  }

  /** POST the exact Stop for one observed run identity. */
  function _postExactStop(sessionId, runId) {
    fetch(`/api/chat/stop/${encodeURIComponent(sessionId)}`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-Pantheon-Run-Id': runId },
    }).catch(() => {});
  }

  /** Stop only the exact detached run whose identity this browser observed. */
  function _stopExactRun(sessionId, abortCtrl = null) {
    if (!sessionId) return false;
    const runId = _streamRunIds.get(sessionId);
    if (!runId) {
      // Queue against the CURRENT send's generation: its POST is the only
      // identity channel that can name the run, so the Stop fires from that
      // send's own header arrival even if a replacement starts meanwhile.
      const generation = _streamGenerations.get(sessionId) || 0;
      const pendingKey = sessionId + ':' + generation;
      if (abortCtrl || !_pendingRunStops.has(pendingKey)) {
        _pendingRunStops.set(pendingKey, abortCtrl);
      }
      return false;
    }
    _postExactStop(sessionId, runId);
    return true;
  }

  function _rememberStreamRunId(sessionId, runId, generation) {
    if (!sessionId || !runId) return;
    // A superseded send must not record its run id as the session's current
    // identity, but it must still flush its own queued Stop: this is the only
    // channel that can cancel that run when the replacement dies before its
    // own POST reaches the server.
    if (_streamGenerations.get(sessionId) === generation) {
      _streamRunIds.set(sessionId, runId);
    }
    const pendingKey = sessionId + ':' + generation;
    if (!_pendingRunStops.has(pendingKey)) return;
    const pendingAbort = _pendingRunStops.get(pendingKey);
    _pendingRunStops.delete(pendingKey);
    _postExactStop(sessionId, runId);
    if (pendingAbort && !pendingAbort.signal.aborted) {
      pendingAbort._reason = 'user-stop';
      pendingAbort.abort();
    }
  }

  // Sources box builder and toggleSources are now in chatRenderer.js
  var _buildSourcesBox = chatRenderer.buildSourcesBox;

  // Browser notifications now in chatStream.js
  var _notifyResearchComplete = chatStream.notifyResearchComplete;

  // Model/image pricing, _buildImageBubble now in chatRenderer.js
  var _buildImageBubble = chatRenderer.buildImageBubble;
  var getModelCost = chatRenderer.getModelCost;
  var getImageCost = chatRenderer.getImageCost;

  function _appendGeneratedImageBubble(data) {
    const imageUrl = data?.image_url || data?.url || '';
    if (!imageUrl) return false;
    const chatBox = document.getElementById('chat-history');
    if (!chatBox) return false;
    const imageKey = String(data.image_id || imageUrl);
    const exists = Array.from(chatBox.querySelectorAll('.generated-image-wrap')).some(el => (
      el.dataset.imageKey === imageKey ||
      el.dataset.imageUrl === imageUrl ||
      el.querySelector('img.generated-image')?.getAttribute('src') === imageUrl
    ));
    if (exists) return false;
    const bubble = _buildImageBubble(
      imageUrl,
      data.image_prompt,
      data.image_model,
      data.image_size,
      data.image_quality,
      data.image_id
    );
    bubble.dataset.imageKey = imageKey;
    bubble.dataset.imageUrl = imageUrl;
    chatBox.appendChild(bubble);
    uiModule.scrollHistory();
    window.dispatchEvent(new CustomEvent('gallery-refresh'));
    return true;
  }

  // stripToolBlocks and roleTimestamp now in chatRenderer.js
  var stripToolBlocks = chatRenderer.stripToolBlocks;

  function _normalizeEndpointForCompare(url) {
    if (!url) return '';
    try {
      const u = new URL(String(url), window.location.origin);
      let path = u.pathname.replace(/\/+$/, '');
      const suffixes = [
        '/v1/chat/completions', '/chat/completions',
        '/v1/completions', '/completions',
        '/v1/messages', '/messages',
        '/v1/models', '/models',
      ];
      for (const suffix of suffixes) {
        if (path.toLowerCase().endsWith(suffix)) {
          path = path.slice(0, -suffix.length).replace(/\/+$/, '');
          break;
        }
      }
      return (u.origin + path).toLowerCase();
    } catch (_) {
      return String(url).trim().replace(/\/+$/, '').toLowerCase();
    }
  }

  async function _probeCurrentEndpointStatus(endpointUrl, signal) {
    const target = _normalizeEndpointForCompare(endpointUrl);
    if (!target) return null;
    const modelsRes = await fetch(`${API_BASE}/api/models`, { credentials: 'same-origin', signal });
    if (!modelsRes.ok) return null;
    const modelsData = await modelsRes.json().catch(() => ({}));
    const item = (modelsData.items || []).find(ep =>
      _normalizeEndpointForCompare(ep.url || ep.endpoint_url || ep.base_url) === target
    );
    if (!item || !item.endpoint_id) return null;

    const probesRes = await fetch(`${API_BASE}/api/model-endpoints/probe-local`, {
      credentials: 'same-origin',
      signal,
    });
    if (!probesRes.ok) return null;
    const probes = await probesRes.json().catch(() => ({}));
    return probes[item.endpoint_id] || null;
  }

  /**
   * Initialize with dependencies
   */
  export function init(apiBase) {
    API_BASE = apiBase;
    initSlashCommands({ apiBase, isStreaming: () => !!_getForegroundStreamState() });
    // Initialize email inbox
    emailInbox.init(documentModule);
    // Wire the slash-command autocomplete popup on the chat composer. The
    // dispatcher already handles the typed command — this just surfaces the
    // registry as a discoverable menu when the user starts a message with /.
    import('./slashAutocomplete.js').then(mod => {
      const ta = document.getElementById('message');
      if (ta && mod.initSlashAutocomplete) mod.initSlashAutocomplete(ta);
    }).catch(() => {});

    // ArrowUp on the composer recalls previous user prompts from this chat.
    const _wireArrowUpRecall = (composer) =>
      wireArrowUpRecall(composer, () => getUserMessagesFromChatHistory(), {
        autoResize: uiModule?.autoResize,
      });

    const composer = document.getElementById('message');
    if (!_wireArrowUpRecall(composer)) {
      // Init can run before #message exists (templated UI); short retries only.
      try { requestAnimationFrame(() => _wireArrowUpRecall(document.getElementById('message'))); } catch (_) {}
      setTimeout(() => _wireArrowUpRecall(document.getElementById('message')), 250);
    }

    // Restore the persisted message queue and start watching #chat-history so
    // queued bubbles are re-drawn after every session switch (P6-01, P6-02).
    _initQueuedRequests();

    // `P7-10`. The run limits beside the mode toggle.
    _wireAgentLimitsHint();
  }

  // addMessage, createMsgFooter, displayMetrics, hideWelcomeScreen, showWelcomeScreen
  // are now in chatRenderer.js — referenced via the public API delegation above.
  var addMessage = chatRenderer.addMessage;
  var createMsgFooter = chatRenderer.createMsgFooter;
  var displayMetrics = chatRenderer.displayMetrics;
  var hideWelcomeScreen = chatRenderer.hideWelcomeScreen;
  var showWelcomeScreen = chatRenderer.showWelcomeScreen;

  /**
   * Update submit button state
   */
  function updateSubmitButton(state, submitBtn) {
    if (!submitBtn) return;

    if (state === 'streaming') {
      // Clear any pending transitions from + → arrow swap
      submitBtn.classList.remove('anim-spin', 'anim-spin-swap', 'anim-land', 'mic-mode', 'newchat-mode', 'newchat-expanded', 'recording');
      // Ensure arrow icon is showing before launch
      var icons = window._pantheonBtnIcons;
      if (icons) submitBtn.innerHTML = icons.send;
      void submitBtn.offsetWidth;
      // Arrow launches up, then stop icon lands in
      submitBtn.classList.add('anim-launch');
      const _stopSvg = stopIcon({ size: 14 });
      // Wait for the launch keyframe to finish (0.3s) before swapping the
      // arrow out for the stop icon — otherwise the swap happens mid-flight
      // and the user sees nothing fly out.
      setTimeout(() => {
        if (submitBtn.dataset.mode !== 'streaming') return;
        const msgInput = uiModule.el('message');
        const hasQueuedText = !!(msgInput && msgInput.value && msgInput.value.trim());
        submitBtn.innerHTML = hasQueuedText && icons ? icons.send : _stopSvg;
        submitBtn.dataset.phase = hasQueuedText ? 'queue' : 'processing';
        submitBtn.title = hasQueuedText ? 'Queue message' : 'Stop generation';
        submitBtn.classList.remove('anim-launch');
        void submitBtn.offsetWidth;
        submitBtn.classList.add('anim-land');
        submitBtn.addEventListener('animationend', () => submitBtn.classList.remove('anim-land'), { once: true });
      }, 300);
      submitBtn.title = 'Stop generation';
      submitBtn.dataset.mode = 'streaming';
      submitBtn.dataset.phase = 'processing';
      isStreaming = true;
      _setForegroundChatBusy(true);
      _startStallWatchdog();
    } else if (state === 'idle') {
      submitBtn.dataset.mode = '';
      delete submitBtn.dataset.phase;
      submitBtn.classList.remove('recording');
      isStreaming = false;
      _setForegroundChatBusy(false);
      _stopStallWatchdog();
      // Defer to global updater which handles mic/newchat/send modes
      if (window._updateSendBtnIcon) {
        setTimeout(window._updateSendBtnIcon, 50);
      } else {
        var icons = window._pantheonBtnIcons;
        submitBtn.innerHTML = icons ? icons.send : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>';
        submitBtn.title = 'Send message';
        submitBtn.classList.remove('mic-mode', 'newchat-mode');
      }
    }
  }

  // -----------------------------------------------------------------------
  // Slash commands — now in slashCommands.js
  // -----------------------------------------------------------------------

  // API key pattern for the guard in handleChatSubmit
  const API_KEY_RE = /^(sk-[a-zA-Z0-9_\-]{20,}|gsk_[a-zA-Z0-9]{20,}|AIza[a-zA-Z0-9_\-]{30,}|xai-[a-zA-Z0-9]{20,})$/;
  // The active-plan storage key now lives in planWindow.js (one literal, one
  // owner): the plan store and the docked window that draws it are the same
  // module, so a write cannot land without the window following it (P6-11).

  const _queuedAgentRequests = [];
  // P6-04 — the queue panel's Pause. Deliberately NOT persisted: a queue that
  // silently stays paused across a reload is a trap, and restored items do not
  // auto-fire anyway (P6-02), so an unpaused reload cannot stampede.
  let _queuePaused = false;
  let _queuedDrainTimer = null;
  let _queuedPromoteTimer = null;
  let _queuedRequestSeq = 0;
  let _queuedBubbleHost = null;
  let _queuedRerenderTimer = null;
  let _queuedHistoryObserver = null;
  let _queuedRestoreDone = false;
  // `B06`. There is no `_pendingApprovedPlan` any more, and its absence is the
  // fix. It was a module-level `let` holding a copy of the approved plan text,
  // appended to the first turn and then blanked — so every continuation turn
  // sent no `approved_plan`, and `build_active_plan_note` returned "" for the
  // rest of the run. The agent lost the checklist it was executing, lost the
  // agent-mode forcing at the send site, and on a Pantheon-finetuned local
  // model lost its tool schemas entirely (`agent_loop.py` gates three
  // `route_mcp_schemas` branches on `and not approved_plan`).
  //
  // It was also a second plan store, and the only one that did not survive a
  // reload — `planWindow` keeps the plan in `localStorage` and the approval in
  // its own meta. The plan is sourced from there at send time now, and
  // `planWindow.isExecuting()` is the stop condition: approved, unfinished, and
  // belonging to this chat, which is the same rule the tool binding already
  // used rather than a second one (`Law 14`).
  // Attachment meta for a send whose bytes were uploaded earlier (a queue
  // drain). Consumed in the same place, and by the same rule, as
  // `_pendingRegenAttachments` — one attachment path, not two.
  let _pendingSendAttachInfo = null;

  // P6-02 — the queue survives a reload. Stored through the same `Storage`
  // helper every other per-session browser preference in this app already uses
  // (`lastSessionId` in sessions.js, the active plan in planWindow.js). No
  // second store.
  const QUEUE_STORAGE_KEY = 'pantheon-queued-requests';
  const QUEUE_MAX_PERSISTED = 20;          // bound the row; a queue is not an archive
  const QUEUE_MAX_AGE_MS = 24 * 60 * 60 * 1000;  // a day-old prompt is stale, not queued

  // The plan store moved into planWindow.js so that storing a plan and drawing
  // it are one call (P6-11). These four keep their names and their contracts —
  // every existing call site is unchanged — and now every write repaints the
  // docked window instead of vanishing into localStorage.
  function _extractPlanText(text) {
    return planWindow.extractPlanText(text);
  }

  function _getStoredPlan() {
    return planWindow.getPlan();
  }

  // `B894`. `sessionId` is the chat whose stream produced the plan. Without it
  // the plan went to whichever chat was on screen when the event arrived.
  function _setStoredPlan(plan, sessionId) {
    planWindow.setPlan(plan, sessionId ? { sessionId: String(sessionId) } : {});
  }

  function _clearStoredPlan() {
    planWindow.clearPlan();
  }

  // ONE execute path (Law 14). The inline plan actions on the last plan-mode
  // bubble and the docked window's Execute button are two entry points into
  // this function, never two implementations of it.
  function _executeStoredPlan(fallbackPlan) {
    const approved = _getStoredPlan() || _extractPlanText(fallbackPlan || '');
    if (!approved.trim()) return false;
    // `B06`. `markApproved()` IS the record that this plan is executing — it
    // is persisted, session-bound, and survives a reload. Nothing is copied
    // into this module.
    if (!_getStoredPlan()) _setStoredPlan(approved);
    planWindow.markApproved();
    if (window.__pantheonSetPlanMode) window.__pantheonSetPlanMode(false);
    if (window.__pantheonSetChatMode) window.__pantheonSetChatMode('agent');
    _setComposerAndSend('Execute the approved plan.');
    return true;
  }

	  function _attachPlanActions(target, plan) {
	    if (!target || !String(plan || '').trim() || target.querySelector('.plan-inline-actions')) return;
	    const actions = document.createElement('div');
	    actions.className = 'plan-inline-actions';
	    actions.innerHTML = `
	      <button type="button" class="plan-inline-execute">
	        ${playIcon({ size: 12 })}
	        Execute
	      </button>
	      <button type="button" class="plan-inline-clear">Clear</button>`;
	    actions.querySelector('.plan-inline-execute')?.addEventListener('click', () => {
	      _executeStoredPlan(plan);
	    });
	    actions.querySelector('.plan-inline-clear')?.addEventListener('click', () => {
	      _clearStoredPlan();
	      actions.remove();
	    });
	    (target.querySelector('.body') || target).appendChild(actions);
	  }

  function _escapeQueueText(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  // ── Queue identity + persistence (P6-01, P6-02) ─────────────────────────

  function _currentSessionIdSafe() {
    try {
      return (sessionModule && sessionModule.getCurrentSessionId && sessionModule.getCurrentSessionId()) || '';
    } catch (_) { return ''; }
  }

  function _queuedItemsForSession(sid) {
    return sid ? _queuedAgentRequests.filter(it => it && it.sessionId === sid) : [];
  }

  /** Write the queue to localStorage. `previewUrl` is a blob: URL and is dead
   *  the moment the page reloads, so it is deliberately not stored; an item
   *  still uploading is not stored either, because its ids do not exist yet. */
  function _persistQueuedRequests() {
    try {
      const rows = _queuedAgentRequests
        .filter(it => it && it.sessionId && !it.pendingUpload)
        .slice(0, QUEUE_MAX_PERSISTED)
        .map(it => ({
          sessionId: it.sessionId,
          message: it.message,
          createdAt: it.createdAt,
          // P6-04's per-item route. Without these a restored item sent under
          // whatever the composer happened to be set to, which is the opposite
          // of what choosing a per-item model means.
          mode: it.mode || '',
          model: it.model || '',
          endpointUrl: it.endpointUrl || '',
          endpointId: it.endpointId || '',
          attachmentIds: Array.isArray(it.attachmentIds) ? it.attachmentIds.slice() : [],
          attachments: (it.attachments || []).map(a => ({
            name: a.name || '', size: a.size || 0, mime: a.mime || '',
            id: a.id || '', width: a.width || 0, height: a.height || 0,
          })),
        }));
      if (rows.length) Storage.setJSON(QUEUE_STORAGE_KEY, rows);
      else Storage.remove(QUEUE_STORAGE_KEY);
    } catch (_) { /* best-effort — the live queue still works without it */ }
    // Every queue mutation already funnels through here, so this is the one
    // hook both views need — no second change-notification path (Law 14).
    try { queuePanel.refresh(); } catch (_) {}
    try { _refreshQueueActivityView(); } catch (_) {}
  }

  /** Read the queue back after a reload. Restored items are marked `restored`
   *  and NEVER auto-fire: the stream they were waiting behind belongs to a page
   *  load that no longer exists, so firing them would replay a stale prompt.
   *  They re-arm only when a stream for their own session ends in THIS load
   *  (see `_drainQueuedAgentRequests`); otherwise they wait for a click. */
  function _restoreQueuedRequests() {
    if (_queuedRestoreDone) return;
    _queuedRestoreDone = true;
    let rows = [];
    try { rows = Storage.getJSON(QUEUE_STORAGE_KEY, []) || []; } catch (_) { rows = []; }
    if (!Array.isArray(rows) || !rows.length) return;
    const now = Date.now();
    let dropped = false;
    for (const row of rows.slice(0, QUEUE_MAX_PERSISTED)) {
      const sid = row && String(row.sessionId || '');
      const msg = row && String(row.message || '');
      const created = Number(row && row.createdAt) || 0;
      const atts = (row && Array.isArray(row.attachmentIds)) ? row.attachmentIds.filter(Boolean) : [];
      if (!sid || (!msg.trim() && !atts.length) || !created || now - created > QUEUE_MAX_AGE_MS) {
        dropped = true;
        continue;
      }
      _queuedAgentRequests.push({
        id: `q${++_queuedRequestSeq}`,
        sessionId: sid,
        message: msg,
        createdAt: created,
        // Paired with _persistQueuedRequests. Written and not read is the same
        // defect as read and not written.
        mode: (row.mode === 'agent' || row.mode === 'chat') ? row.mode : '',
        model: String(row.model || ''),
        endpointUrl: String(row.endpointUrl || ''),
        endpointId: String(row.endpointId || ''),
        attachmentIds: atts,
        attachments: Array.isArray(row.attachments) ? row.attachments : [],
        pendingUpload: false,
        restored: true,
        el: null,
      });
    }
    if (dropped) _persistQueuedRequests();
  }

  function _ensureQueuedBubbleHost() {
    const chatBox = document.getElementById('chat-history');
    if (!chatBox) return null;
    if (_queuedBubbleHost && _queuedBubbleHost.isConnected) return _queuedBubbleHost;
    let host = document.getElementById('chat-queued-bubble-host');
    if (!host) {
      host = document.createElement('div');
      host.id = 'chat-queued-bubble-host';
      host.className = 'chat-queued-bubble-host';
    }
    chatBox.appendChild(host);
    _queuedBubbleHost = host;
    return host;
  }

  /** The bubble's inner markup. `.msg`/`.msg-user`/`.body`/`.queued-pill` are
   *  load-bearing names (FORBIDDEN.md) and the pill markup is reproduced
   *  exactly; the attachment count reuses `.queued-pill` so it needs no new CSS. */
  function _queuedBubbleHtml(item) {
    const n = (item.attachments && item.attachments.length) || 0;
    const play = playIcon({ size: 8 });
    const clip = '<svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="M21 12.8L12.2 21.6a5 5 0 0 1-7-7L14 5.7a3.3 3.3 0 0 1 4.7 4.7l-8.8 8.8a1.7 1.7 0 0 1-2.4-2.4l8.2-8.1"/></svg>';
    // `B13`: the pill said "Queued" while the docked panel said "Waiting" about
    // this same message, three inches below it. One word, from `runStatus.js`,
    // asked for as a message — which is what a composer queue item is.
    const word = runStatusLabel('queued', 'message');
    let label;
    if (item.pendingUpload) label = `<span class="queued-pill">Uploading…</span>`;
    else if (item.restored) label = `<span class="queued-pill">${play}${word} · click to send</span>`;
    else label = `<span class="queued-pill">${play}${word}</span>`;
    const attach = n ? ` <span class="queued-pill">${clip}${n}</span>` : '';
    return `<div class="role">You ${label}${attach}</div><div class="body">${_escapeQueueText(item.message)}</div>`;
  }

  function _paintQueuedBubble(item) {
    if (!item || !item.el || !item.el.isConnected) return;
    item.el.innerHTML = _queuedBubbleHtml(item);
    // The tooltip opens with the same word the pill shows, derived rather than
    // retyped — a pill reading "Waiting" over a tooltip reading "Queued" is the
    // two-vocabulary defect again, one hover deep.
    const word = runStatusLabel('queued', 'message');
    item.el.title = item.pendingUpload
      ? 'Uploading attachment - this sends when the current response finishes'
      : (item.restored
        ? `${word} since before a reload - click to send it now`
        : `${word} to send - click to send now and stop the current response`);
  }

  function _createQueuedBubble(item) {
    const host = _ensureQueuedBubbleHost();
    if (!host) return null;
    const wrap = document.createElement('div');
    wrap.className = 'msg msg-user msg-user-queued';
    wrap.dataset.queueId = item.id;
    wrap.addEventListener('click', (ev) => {
      if (ev.target && ev.target.closest && ev.target.closest('button, a, textarea, input')) return;
      _promoteQueuedRequest(item.id);
    });
    host.appendChild(wrap);
    item.el = wrap;
    _paintQueuedBubble(item);
    uiModule.scrollHistory();
    return wrap;
  }

  /** P6-01: bubbles live in `#chat-history`, which every session switch wipes.
   *  Re-draw this session's queue and drop any bubble belonging to another. */
  function _renderQueuedRequestsForCurrentSession() {
    const sid = _currentSessionIdSafe();
    for (const it of _queuedAgentRequests) {
      if (!it) continue;
      if (it.el && it.sessionId !== sid && it.el.parentNode) it.el.remove();
      if (it.el && !it.el.isConnected) it.el = null;
    }
    // The panel is session-scoped too, so it repaints on the same hook the
    // bubbles do — one queue, two views, never two states (Law 7).
    try { queuePanel.refresh(); } catch (_) {}
    const mine = _queuedItemsForSession(sid);
    if (!mine.length) return;
    if (!document.getElementById('chat-history')) return;
    for (const it of mine) {
      if (it.el && it.el.isConnected) continue;
      _createQueuedBubble(it);
    }
  }

  /** Nothing in this app broadcasts a session switch, and `#chat-history` is
   *  owned by sessions.js. Watching its child list is the one hook chat.js has
   *  that catches every wipe — switch, new chat, delete, history re-page. */
  function _watchChatHistoryForQueue() {
    if (_queuedHistoryObserver) return true;
    const box = document.getElementById('chat-history');
    if (!box || typeof MutationObserver !== 'function') return false;
    _queuedHistoryObserver = new MutationObserver(() => {
      // Same hook, same reason: the plan window's "from another chat" tag has to
      // be recomputed when the session changes under it (P6-11). One observer.
      planWindow.refresh();
      if (!_queuedAgentRequests.length) return;
      const sid = _currentSessionIdSafe();
      const mine = _queuedItemsForSession(sid);
      const strays = _queuedAgentRequests.some(it => it && it.el && it.el.isConnected && it.sessionId !== sid);
      if (!strays && mine.every(it => it.el && it.el.isConnected)) return;
      if (_queuedRerenderTimer) return;
      _queuedRerenderTimer = setTimeout(() => {
        _queuedRerenderTimer = null;
        if (!_queuedBubbleHost || !_queuedBubbleHost.isConnected) _queuedBubbleHost = null;
        _renderQueuedRequestsForCurrentSession();
        _drainQueuedAgentRequests();
      }, 60);
    });
    _queuedHistoryObserver.observe(box, { childList: true });
    return true;
  }

  function _initQueuedRequests() {
    _restoreQueuedRequests();
    _watchChatHistoryForQueue();
    _renderQueuedRequestsForCurrentSession();
    // Two short retries, unconditionally: #chat-history can be templated in
    // after init, and the startup session restore can render into an already
    // empty node — which produces no mutation record for the observer to see.
    setTimeout(() => { _watchChatHistoryForQueue(); _renderQueuedRequestsForCurrentSession(); }, 400);
    setTimeout(() => { _watchChatHistoryForQueue(); _renderQueuedRequestsForCurrentSession(); }, 2000);
  }

  function _removeQueuedRequest(id) {
    const idx = _queuedAgentRequests.findIndex(item => item.id === id);
    if (idx < 0) return null;
    const [item] = _queuedAgentRequests.splice(idx, 1);
    if (item && item.el && item.el.parentNode) item.el.remove();
    _persistQueuedRequests();
    return item;
  }

  function _clearComposerAfterQueue(input) {
    if (!input) return;
    input.value = '';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    if (uiModule.autoResize) uiModule.autoResize(input);
    try { window._updateSendBtnIcon && window._updateSendBtnIcon(); } catch (_) {}
  }

  /** Put a queued item's text back where the user typed it. Used when the
   *  queue cannot honour the item — never drop the text on the floor. */
  function _restoreComposerFromQueueItem(item) {
    const input = uiModule.el('message');
    if (!input || !item) return;
    const typed = input.value || '';
    input.value = (item.message || '') + (typed.trim() ? '\n' + typed : '');
    input.dispatchEvent(new Event('input', { bubbles: true }));
    if (uiModule.autoResize) uiModule.autoResize(input);
    try { window._updateSendBtnIcon && window._updateSendBtnIcon(); } catch (_) {}
  }

  function _setComposerAndSend(message, item) {
    const input = uiModule.el('message');
    if (!input) return false;
    // Every path that carries a queued item must arrive here already checked.
    // This is the backstop, not the guard: a queued item is addressed to one
    // session and posting it anywhere else is the P6-01 defect.
    if (item && item.sessionId && item.sessionId !== _currentSessionIdSafe()) {
      _requeueAfterSessionChange(item);
      return false;
    }
    if (item && Array.isArray(item.attachmentIds) && item.attachmentIds.length) {
      // P6-03: the files were uploaded when the item was queued. Re-carry their
      // ids through the slot a resend/regenerate already uses, so the queued
      // send goes down exactly one attachment path.
      _pendingRegenAttachments = (_pendingRegenAttachments || []).concat(item.attachmentIds);
      const stillPending = (fileHandlerModule.getPendingCount && fileHandlerModule.getPendingCount()) || 0;
      if (!stillPending && item.attachments && item.attachments.length) {
        _pendingSendAttachInfo = item.attachments;
      }
    }
    input.value = message;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    if (uiModule.autoResize) uiModule.autoResize(input);
    setTimeout(() => {
      handleChatSubmit({ preventDefault() {} }).catch(err => {
        console.error('queued send failed', err);
        try { uiModule.showError && uiModule.showError('Queued send failed: ' + (err?.message || err)); } catch (_) {}
      });
    }, 0);
    return true;
  }

  function _sendQueuedWhenIdle(item) {
    if (!item) return;
    const trySend = () => {
      if (isStreaming || _sendInFlight) {
        _queuedPromoteTimer = setTimeout(trySend, 220);
        return;
      }
      _queuedPromoteTimer = null;
      // The click-time guard in _promoteQueuedRequest is not enough. This poller
      // waits out the whole abort round trip — first retry at +320ms, then every
      // 220ms — and the user can switch chats inside that window. Send time is
      // the only moment worth trusting, so check again here.
      if (item.sessionId && item.sessionId !== _currentSessionIdSafe()) {
        _requeueAfterSessionChange(item);
        return;
      }
      _setComposerAndSend(item.message, item);
    };
    if (_queuedPromoteTimer) clearTimeout(_queuedPromoteTimer);
    _queuedPromoteTimer = setTimeout(trySend, 320);
  }

  /** The item was promoted out of the queue and then its session went away
   *  before it could send. Put it back where it came from rather than dropping
   *  it — it is still the user's message, and it is still addressed to a real
   *  conversation. It re-renders when they return to that session. */
  function _requeueAfterSessionChange(item) {
    if (!item) return;
    item.el = null;
    if (!_queuedAgentRequests.some(q => q && q.id === item.id)) {
      _queuedAgentRequests.push(item);
      _persistQueuedRequests();
    }
    _renderQueuedRequestsForCurrentSession();
  }

  function _promoteQueuedRequest(id) {
    const peek = _queuedAgentRequests.find(it => it && it.id === id);
    if (!peek) return;
    if (peek.pendingUpload) {
      try { uiModule.showToast && uiModule.showToast('Still uploading the attachment…'); } catch (_) {}
      return;
    }
    // A bubble is only ever drawn inside its own session, but the click can
    // still land during a switch. Never post one session's text into another.
    if (peek.sessionId && peek.sessionId !== _currentSessionIdSafe()) return;
    const item = _removeQueuedRequest(id);
    if (!item) return;
    // Per-item mode/model applies on every promote path — the bubble click and
    // the panel's "Start now" are two entry points into this one function.
    _applyQueueItemRoute(item, item.sessionId);
    if (!isStreaming && !_sendInFlight) {
      _setComposerAndSend(item.message, item);
      return;
    }
    try { uiModule.showToast && uiModule.showToast('Sending queued request now'); } catch (_) {}
    const input = uiModule.el('message');
    const submitBtn = document.querySelector('.send-btn');
    if (input) {
      input.value = '';
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
    if (submitBtn) submitBtn.click();
    _sendQueuedWhenIdle(item);
  }

  /** Returns the created item, or null. (It used to return a boolean; the
   *  caller now needs the item to finish an in-flight attachment upload.) */
  function _queueAgentRequest(message, opts = {}) {
    const msg = String(message || '').trim();
    const attachments = Array.isArray(opts.attachments) ? opts.attachments : [];
    if (!msg && !attachments.length) return null;
    const sid = _currentSessionIdSafe();
    if (!sid) {
      // No session to bind to means no way to know where this belongs later.
      // Refuse rather than queue an item that could fire into another chat.
      return null;
    }
    const item = {
      id: `q${++_queuedRequestSeq}`,
      sessionId: sid,
      message: msg,
      createdAt: Date.now(),
      attachments,
      attachmentIds: Array.isArray(opts.attachmentIds) ? opts.attachmentIds : [],
      pendingUpload: !!opts.pendingUpload,
      restored: false,
      el: null,
    };
    _createQueuedBubble(item);
    _queuedAgentRequests.push(item);
    _persistQueuedRequests();
    const mine = _queuedItemsForSession(sid).length;
    try { uiModule.showToast && uiModule.showToast(mine === 1 ? 'Queued for after this response' : `${mine} requests queued`); } catch (_) {}
    return item;
  }

  export function queueStreamingComposerRequest() {
    if (!isStreaming) return false;
    const queuedInput = uiModule.el('message');
    const queuedText = (queuedInput && queuedInput.value || '').trim();
    const pendingCount = (fileHandlerModule.getPendingCount && fileHandlerModule.getPendingCount()) || 0;
    if (!queuedText && !pendingCount) return false;

    // P6-03. This used to refuse outright — an error toast, `return true`, and
    // every caller then skipped the submit, so Enter sent nothing at all. The
    // attachment now rides the queue: upload it here, keep the ids on the item,
    // and re-carry them at drain. Snapshot the meta BEFORE the upload, because
    // uploadPending() empties the pending list on success.
    const attachInfo = (pendingCount && fileHandlerModule.getPendingInfo)
      ? fileHandlerModule.getPendingInfo()
      : [];
    const item = _queueAgentRequest(queuedText, {
      attachments: attachInfo,
      pendingUpload: pendingCount > 0,
    });
    if (!item) return false;
    _clearComposerAfterQueue(queuedInput);
    if (!pendingCount) return true;

    Promise.resolve()
      .then(() => fileHandlerModule.uploadPending({ sessionId: item.sessionId }))
      .then((ids) => {
        if (!Array.isArray(ids) || !ids.length) throw new Error('attachment upload returned no ids');
        const meta = (fileHandlerModule.getLastUploadedMeta && fileHandlerModule.getLastUploadedMeta()) || [];
        for (let i = 0; i < attachInfo.length && i < ids.length; i++) {
          attachInfo[i].id = ids[i];
          const m = meta[i];
          if (m) {
            if (m.width) attachInfo[i].width = m.width;
            if (m.height) attachInfo[i].height = m.height;
          }
        }
        item.attachmentIds = ids;
        item.pendingUpload = false;
        _paintQueuedBubble(item);
        _persistQueuedRequests();
        _drainQueuedAgentRequests();
      })
      .catch(() => {
        // Never swallow the send. uploadPending() keeps pendingFiles on
        // failure, so the strip still holds the files; put the text back too
        // and the user can simply press Enter again.
        _removeQueuedRequest(item.id);
        _restoreComposerFromQueueItem(item);
        try {
          uiModule.showError && uiModule.showError('Attachment upload failed - your message and files were put back, try again.');
        } catch (_) {}
      });
    return true;
  }

  /** `endedSessionId` names the session whose stream just finished in THIS page
   *  load. It re-arms that session's restored items — their wait is genuinely
   *  over — and nothing else. The drain itself only ever fires an item into the
   *  session it was queued from (P6-01). */
  function _drainQueuedAgentRequests(endedSessionId = null) {
    if (endedSessionId) {
      let rearmed = false;
      for (const it of _queuedAgentRequests) {
        if (it && it.restored && it.sessionId === endedSessionId) { it.restored = false; rearmed = true; }
      }
      if (rearmed) {
        _persistQueuedRequests();
        if (endedSessionId === _currentSessionIdSafe()) {
          _queuedItemsForSession(endedSessionId).forEach(_paintQueuedBubble);
        }
      }
    }
    if (!_queuedAgentRequests.length) return;
    // P6-04 Pause. Held here rather than at the call sites so every path that
    // can fire the queue — stream end, upload finish, session re-render — is
    // covered by the one check the panel's button flips.
    if (_queuePaused) return;
    if (_queuedDrainTimer) return;
    _queuedDrainTimer = setTimeout(() => {
      _queuedDrainTimer = null;
      if (_queuePaused) return;
      if (isStreaming || _sendInFlight || !_queuedAgentRequests.length) return;
      const sid = _currentSessionIdSafe();
      if (!sid) return;
      const next = _queuedAgentRequests.find(
        it => it && it.sessionId === sid && !it.pendingUpload && !it.restored
      );
      if (!next) return;
      _removeQueuedRequest(next.id);
      _applyQueueItemRoute(next, sid);
      _setComposerAndSend(next.message, next);
    }, 180);
  }

  // ── Queue panel driver (P6-04 · P6-06 · P6-07) ─────────────────────────────
  // chat.js keeps ownership of `_queuedAgentRequests`, its persistence and the
  // send path; `queuePanel.js` owns the surface and asks for changes through
  // the functions below. One queue, one store, one send path.

  /**
   * Per-item mode and model (P6-04), applied through the mechanisms that
   * already exist: `window.__pantheonSetChatMode` is the composer's own mode
   * setter (`app.js:1842`) and `window.__pantheonLastPickedRoute` is the route
   * override the model picker writes (`modelPicker.js:647`) and the send path
   * already reads (`chat.js` `selectedRouteForSend`). No second per-send model
   * channel, and no new wire field.
   *
   * The route override is honoured for ten minutes, so leaving one item's model
   * in place would silently re-route the user's NEXT hand-typed message. The
   * previous value is restored as soon as the send has committed — identified
   * by `hasActiveStream(sid)`, which flips true at `chat.js` line ~1799, well
   * after `selectedRouteForSend` has read it.
   */
  function _applyQueueItemRoute(item, targetSessionId) {
    if (!item) return;

    // A per-item mode or model is a property of THAT message, not a change to
    // the user's composer. Both are applied for the send and put back after it.
    //
    // Two bugs lived here. (1) mode was applied and never restored at all, and
    // `app.js`'s setMode persists to storage — so one queued agent-mode item
    // permanently flipped the composer and survived a reload. (2) the model
    // restore probe treated "a stream is live" as "my send is done", but on the
    // promote path the OLD stream is still unwinding when the first probe fires
    // at +250ms, so it restored the route before the queued send went out and
    // the per-item model was silently discarded.
    //
    // Both now wait for the same thing: our send to START and then FINISH.
    const prevMode = (() => {
      try { return window.__pantheonGetChatMode && window.__pantheonGetChatMode(); }
      catch (_) { return null; }
    })();
    const wantMode = (item.mode === 'agent' || item.mode === 'chat') ? item.mode : null;
    if (wantMode) {
      try { window.__pantheonSetChatMode && window.__pantheonSetChatMode(wantMode); } catch (_) {}
    }

    let mine = null;
    const prevRoute = window.__pantheonLastPickedRoute || null;
    if (item.model) {
      try {
        mine = {
          model: item.model,
          endpoint_url: item.endpointUrl || '',
          endpoint_id: item.endpointId || '',
          display: String(item.model).split('/').pop(),
          picked_at: Date.now(),
        };
        window.__pantheonLastPickedRoute = mine;
      } catch (_) { mine = null; }
    }
    if (!wantMode && !mine) return;

    let started = false;
    let tries = 0;
    const putBack = () => {
      // Identity guard: if the user picked a model in the meantime, theirs wins.
      if (mine && window.__pantheonLastPickedRoute === mine) {
        window.__pantheonLastPickedRoute = prevRoute;
      }
      if (wantMode && prevMode && prevMode !== wantMode) {
        try { window.__pantheonSetChatMode && window.__pantheonSetChatMode(prevMode); } catch (_) {}
      }
    };
    const probe = () => {
      tries++;
      const busy = !!(_sendInFlight || isStreaming);
      if (!started && busy) { started = true; }
      // Put back once OUR send has started and then ended, or if it never
      // started at all within ~20s (the send was refused or superseded).
      if ((started && !busy) || tries > 80) { putBack(); return; }
      setTimeout(probe, 250);
    };
    setTimeout(probe, 250);
  }

  /**
   * Queue rows in the shape `static/js/tasks.js` `_runToActivityEntry` emits
   * (`tasks.js:2020`). This is `P6-07`'s half that lives in this file: the
   * queue panel renders these, and so does the Tasks activity view once
   * `tasks.js`'s activity-source registry has them, because they already speak
   * its vocabulary — the six `TaskRun.status` values documented at
   * `core/database.py:810+`.
   *
   * `aborted` is never folded into `error` here. `skipped` is used for an item
   * whose chat no longer exists: it deliberately did not run, and calling that
   * a failure is what corrupts error-rate statistics.
   *
   * `scope` is an enum, not a boolean or a magic id (Law 10):
   *   'session' — the chat currently on screen. What the docked panel wants.
   *   'all'     — every chat's queue. What a global Activity view wants; rows
   *               carry their chat's name as `category` so they group by chat.
   * The `onForce` / `onStop` / `onOpen` callbacks are the ones `tasks.js`
   * `activityEntryControls` looks for, so a queue row gets the activity view's
   * existing Start-now and stop buttons without that file learning what a
   * queue item is.
   */
  export function getQueueActivityEntries(scope = 'session') {
    const current = _currentSessionIdSafe();
    const all = scope === 'all';
    if (!all && !current) return [];
    const names = new Map();
    try {
      for (const s of (sessionModule.getSessions() || [])) {
        if (s && s.id) names.set(s.id, s.name || '');
      }
    } catch (_) { /* session list not loaded yet — treat every item as live */ }
    const rows = [];
    const seat = new Map();
    for (const it of _queuedAgentRequests) {
      if (!it) continue;
      if (!all && it.sessionId !== current) continue;
      const position = (seat.get(it.sessionId) || 0) + 1;
      seat.set(it.sessionId, position);
      // `gone` used to be derived from absence in /api/sessions. That payload
      // excludes archived sessions, Incognito, and hidden system sessions
      // (`routes/session_routes.py`), so a live chat could render as a dead row
      // with no way back to it — the queue telling the user their message was
      // orphaned when it was fine. We cannot know a session is gone from a list
      // that is documented to omit live ones, so we no longer claim it: the row
      // stays queued, and a send into a session that really has vanished fails
      // and says so, which is the honest place for that signal.
      const status = 'queued';
      const id = it.id;
      rows.push({
        queueId: id,
        kind: 'llm',
        taskName: it.message || '',
        taskId: '',
        action: '',
        prompt: '',
        category: all ? (names.get(it.sessionId) || 'Queued') : '',
        // Pin the row hue so a batch of queued messages reads as one group in
        // the Activity view instead of each hashing its own text to a different
        // colour. 45 is the amber the `queued` status dot already uses.
        hue: 45,
        result: it.pendingUpload ? 'Uploading the attachment…' : '',
        // ISO 8601, because that is what `tasks.js`'s activity rows carry and
        // what its source contract asks for — `_relativeTime` would survive an
        // epoch number, but a contract honoured only by accident is not one.
        ts: new Date(it.createdAt || Date.now()).toISOString(),
        status,
        // What the row is ABOUT, which is what picks its wording (`B13`). The
        // queue holds messages; the Tasks list holds jobs; the Activity view
        // renders both and cannot tell them apart from the status alone. Set
        // here, at the one place these rows are built, so the panel, the
        // Activity view and the bubble cannot end up with three names for it.
        subject: 'message',
        model: it.model || '',
        endpointUrl: it.endpointUrl || '',
        endpointId: it.endpointId || '',
        mode: it.mode || '',
        sessionId: it.sessionId,
        researchId: '',
        output_target: 'session',
        attachmentCount: (it.attachments && it.attachments.length) || 0,
        editable: !it.pendingUpload,
        // Distinct from `editable`, which is also false for a launched
        // parallel run. `sendable` means "the drain would actually take this
        // one": `_drainQueuedRequests` filters `!it.pendingUpload`, so a row
        // still uploading its attachment cannot be sent no matter what the
        // panel offers. Consumers count on this to avoid advertising a Send
        // button that is a guaranteed no-op.
        sendable: !it.pendingUpload,
        position,
        // Start now: the same promote path the bubble and the panel use.
        onForce: it.pendingUpload ? undefined : (() => _promoteQueuedRequest(id)),
        // Stop, on a message that has not run yet, means "do not run this".
        onStop: () => { _removeQueuedRequest(id); },
        onOpen: () => sessionModule.selectSession(it.sessionId).catch(() => {}),
      });
    }
    return rows;
  }

  function _queueItemById(id) {
    return _queuedAgentRequests.find(it => it && it.id === id) || null;
  }

  /** Apply a new order to this session's items, leaving other sessions alone. */
  function _reorderQueuedRequests(ids) {
    if (!Array.isArray(ids) || !ids.length) return;
    const rank = new Map();
    ids.forEach((id, i) => rank.set(id, i));
    // Stable partition: pull this session's items out, sort by the new order,
    // then put them back into the slots they occupied. Items belonging to other
    // sessions never move, so a reorder here cannot reshuffle another chat.
    const slots = [];
    const mine = [];
    _queuedAgentRequests.forEach((it, i) => {
      if (it && rank.has(it.id)) { slots.push(i); mine.push(it); }
    });
    mine.sort((a, b) => rank.get(a.id) - rank.get(b.id));
    slots.forEach((slot, i) => { _queuedAgentRequests[slot] = mine[i]; });
    // The transcript bubbles are appended in array order and never move on
    // their own, so a reorder that only touched the array would leave the two
    // views disagreeing about what sends next. Drop this session's bubbles and
    // let the existing renderer re-append them in the new order.
    for (const it of mine) {
      if (it && it.el && it.el.parentNode) it.el.remove();
      if (it) it.el = null;
    }
    _persistQueuedRequests();
    _renderQueuedRequestsForCurrentSession();
  }

  /** Edit in place: message text, per-item mode, per-item model. */
  function _updateQueuedRequest(id, patch) {
    const item = _queueItemById(id);
    if (!item || !patch) return;
    if (typeof patch.message === 'string') {
      const next = patch.message.trim();
      // An emptied row with no attachment is a removal, not an empty prompt.
      if (!next && !(item.attachmentIds && item.attachmentIds.length)) {
        _removeQueuedRequest(id);
        return;
      }
      item.message = next;
      _paintQueuedBubble(item);
    }
    if ('mode' in patch) item.mode = patch.mode || '';
    if ('model' in patch) {
      item.model = patch.model || '';
      item.endpointUrl = patch.endpointUrl || '';
      item.endpointId = patch.endpointId || '';
    }
    _persistQueuedRequests();
  }

  /** Wait for a send to actually leave — the same signal the route restore uses. */
  function _waitForSendCommit(sid, timeoutMs = 20000) {
    return new Promise(resolve => {
      const started = Date.now();
      const tick = () => {
        if (hasActiveStream(sid)) return resolve(true);
        if (Date.now() - started > timeoutMs) return resolve(false);
        setTimeout(tick, 200);
      };
      setTimeout(tick, 120);
    });
  }

  /**
   * Parallel run (P6-06): **one session per item.**
   *
   * Verified in the source before building against it — `src/agent_runs.py`
   * `start()` keys its run registry by session id and *cancels* whatever run is
   * already in flight for that session before installing the new one. So a
   * "parallel" mode that reused one session would not merely serialise: each
   * launch would kill its predecessor, and only the last would survive. A
   * session per item is the only shape that can run these at the same time.
   *
   * The launches are issued one after another on purpose — the composer, the
   * mode toggle and the route override are single-instance, so two launches in
   * the same tick would race each other. Each send is only awaited until it has
   * *committed*, not until it finishes; switching to the next item detaches the
   * previous stream to the background (`sessions.js selectSession` →
   * `detachCurrentStream`), which is what makes them concurrent.
   */
  async function _runQueueParallel() {
    const home = _currentSessionIdSafe();
    if (!home) return;
    const mine = _queuedItemsForSession(home).filter(it => it && !it.pendingUpload);
    if (!mine.length) return;
    const wasPaused = _queuePaused;
    // Hold the sequential drain for the duration: it fires into the *current*
    // session, and this loop is deliberately changing which session that is.
    _queuePaused = true;
    try { queuePanel.refresh(); } catch (_) {}
    try {
      for (const item of mine) {
        if (!_queuedAgentRequests.includes(item)) continue;  // removed mid-run
        let sid = '';
        try { sid = await _createSessionForQueueItem(item); } catch (_) { sid = ''; }
        if (!sid) {
          try {
            queuePanel.noteLaunchResult(
              queuePanel.noteLaunched(item, '', home), 'error', 'Could not open a new chat for this message.');
          } catch (_) {}
          continue;
        }
        _removeQueuedRequest(item.id);
        item.sessionId = sid;
        item.el = null;
        // Attachments ride along unchanged: `uploadPending` already ran at
        // queue time and its `session_id` only steers gallery promotion, so the
        // ids are not re-bound by moving the message to another chat (P6-03's
        // one attachment path is untouched).
        let rec = null;
        try { rec = queuePanel.noteLaunched(item, sid, home); } catch (_) {}
        try {
          await sessionModule.selectSession(sid, { showLoading: false });
        } catch (_) {
          try { queuePanel.noteLaunchResult(rec, 'error', 'Could not open the new chat.'); } catch (_) {}
          // Re-address it to the chat it came from, not to the new session the
          // user was never taken to — otherwise it is orphaned in a chat that
          // is not open and nothing will ever drain it.
          item.sessionId = home;
          _requeueAfterSessionChange(item);
          continue;
        }
        _applyQueueItemRoute(item, sid);
        _setComposerAndSend(item.message, item);
        const committed = await _waitForSendCommit(sid);
        if (!committed) {
          try { queuePanel.noteLaunchResult(rec, 'aborted', 'The send did not start in time.'); } catch (_) {}
        }
      }
    } finally {
      _queuePaused = wasPaused;
      // Land the user back where they pressed the button.
      try { await sessionModule.selectSession(home, { showLoading: false }); } catch (_) {}
      try { queuePanel.refresh(); } catch (_) {}
    }
  }

  /**
   * A chat for one parallel queue item. Uses the same `POST /api/session`
   * contract `sessions.js materializePendingSession` uses — same form fields,
   * same `skip_validation` rule — so there is one session-create shape.
   */
  async function _createSessionForQueueItem(item) {
    const model = (item && item.model)
      || (sessionModule.getCurrentModel ? (sessionModule.getCurrentModel() || '') : '');
    const url = (item && item.endpointUrl)
      || (sessionModule.getCurrentEndpointUrl ? (sessionModule.getCurrentEndpointUrl() || '') : '');
    const label = String(item && item.message || '').replace(/\s+/g, ' ').trim().slice(0, 40);
    const sess = (sessionModule.getSessions && sessionModule.getSessions() || [])
      .find(s => s && s.id === _currentSessionIdSafe());
    const endpointId = (item && item.endpointId)
      || (sess && (sess.endpoint_id || sess.endpointId)) || '';
    const fd = new FormData();
    fd.append('name', label || `Queued ${new Date().toLocaleTimeString()}`);
    fd.append('model', model);
    // `_reject_raw_endpoint_url_for_non_admin` (routes/session_routes.py) lets a
    // request through when endpoint_id is set, or when no endpoint_url is sent —
    // and 403s a signed-in non-admin otherwise. Sending the URL unconditionally
    // while sending the id only for per-item models meant parallel mode failed
    // for every non-admin who had not overridden the model, which is the common
    // case. Send the id we have; without one, send no raw URL and let the server
    // apply the session default, which is what "no per-item model" means anyway.
    if (endpointId) {
      fd.append('endpoint_id', endpointId);
      fd.append('endpoint_url', url);
      if (url && model) fd.append('skip_validation', 'true');
    }
    const res = await fetch(`${API_BASE}/api/session`, {
      method: 'POST', body: fd, credentials: 'same-origin',
    });
    if (!res.ok) return '';
    const payload = await res.json();
    if (payload && payload.id && sessionModule.loadSessions) {
      sessionModule.loadSessions().catch(() => {});
    }
    return (payload && payload.id) || '';
  }

  /**
   * Is a run this panel launched still going?
   *
   * NOT `hasActiveStream`: that one deliberately answers "is this session
   * spoken for", and it stays true for a *finished* background stream, because
   * the `_backgroundStreams` entry survives until the user next opens that
   * session (`checkBackgroundStream` is what deletes it). A queue row driven by
   * that probe would say "Sending" forever. This one asks the narrower
   * question — is a reader loop still attached — which is what an elapsed timer
   * and a Stop button need to be true.
   */
  function _isQueueRunLive(sid) {
    if (!sid) return false;
    if (_activeStreams.has(sid)) return true;
    if (_resumingStreams.has(sid)) return true;
    const bg = _backgroundStreams.get(sid);
    return !!(bg && bg.status === 'running');
  }

  /** Stop a run this panel launched. Terminal status is `aborted`, never `error`. */
  function _stopLaunchedQueueRun(rowId) {
    let rec = null;
    try { rec = queuePanel.launchedById(rowId); } catch (_) {}
    if (!rec || !rec.sessionId) return;
    try {
      fetch(`${API_BASE}/api/chat/stop/${encodeURIComponent(rec.sessionId)}`, {
        method: 'POST', credentials: 'same-origin',
      }).catch(() => {});
    } catch (_) {}
    if (rec.sessionId === _currentSessionIdSafe()) abortCurrentRequest(true);
    try { queuePanel.noteLaunchResult(rec, 'aborted', 'Stopped from the queue panel.'); } catch (_) {}
  }

  const _queuePanelDriver = {
    getEntries: () => getQueueActivityEntries('session'),
    getSessionId: () => _currentSessionIdSafe(),
    isBusy: () => isStreaming || _sendInFlight,
    isPaused: () => _queuePaused,
    setPaused: (paused) => {
      _queuePaused = !!paused;
      if (!_queuePaused) _drainQueuedAgentRequests();
    },
    reorder: _reorderQueuedRequests,
    update: _updateQueuedRequest,
    remove: (id) => { _removeQueuedRequest(id); },
    // Force bypass: the same promote path a queued bubble's click uses (which
    // is where the per-item route is applied), so there is one "send this one
    // now" reachable from two places rather than two implementations of it.
    startNow: (id) => { _promoteQueuedRequest(id); },
    stopRun: _stopLaunchedQueueRun,
    runSequential: () => {
      _queuePaused = false;
      // "Send now" has to mean "stop this reply and send" — because the queue
      // panel only ever exists WHILE a reply is streaming (queueing is refused
      // otherwise, see queueStreamingComposerRequest), and _drainQueued...'s own
      // first guard is `if (isStreaming || _sendInFlight) return`. Calling the
      // drain alone made the panel's primary button a guaranteed no-op in the
      // only state the panel can be in. Stop first, exactly as promoting a
      // single row already does, then let the drain fire when the stream ends.
      if (isStreaming || _sendInFlight) {
        try { uiModule.showToast && uiModule.showToast('Stopping the reply, then sending the queue'); } catch (_) {}
        const submitBtn = document.querySelector('.send-btn');
        if (submitBtn) submitBtn.click();
      }
      _drainQueuedAgentRequests();
      try { queuePanel.refresh(); } catch (_) {}
    },
    runParallel: () => { _runQueueParallel().catch(() => {}); },
    isStreamLive: _isQueueRunLive,
  };


  /**
   * Handle chat form submission
   */
  export async function handleChatSubmit(e) {
    e.preventDefault();
    // Cancel research clarification timeout if active
    if (window._researchTimeoutTimer) {
      clearTimeout(window._researchTimeoutTimer);
      window._researchTimeoutTimer = null;
    }
    // Get current session
    const sessionId = sessionModule.getCurrentSessionId();
    const session = sessionModule.getSessions().find(s => s.id === sessionId);
    
    const submitBtn = document.querySelector('.send-btn');
    
    // If compare is active, stop all compare streams
    if (window.compareModule && window.compareModule.isActive()) {
      window.compareModule.handleCompareSubmit();
      return;
    }

    // If currently streaming, keyboard Enter can queue a non-empty composer.
    // Clicking the stop icon should still stop normally, even if text exists.
    if (isStreaming) {
      const queueRequestedAt = Number(window.__pantheonQueueStreamingSubmit || 0);
      const shouldQueueStreamingSubmit = queueRequestedAt && Date.now() - queueRequestedAt < 1200;
      window.__pantheonQueueStreamingSubmit = 0;
      if (shouldQueueStreamingSubmit && queueStreamingComposerRequest()) {
        return;
      }
      if (fileHandlerModule.isUploading && fileHandlerModule.isUploading()) {
        fileHandlerModule.cancelUpload && fileHandlerModule.cancelUpload();
      }
      // Cancel server-side research if in progress
      const _cancelSid = sessionModule.getCurrentSessionId();
      if (_cancelSid && _researchingStreamIds.has(_cancelSid)) {
        fetch(`${API_BASE}/api/research/cancel/${_cancelSid}`, { method: 'POST' }).catch(e => console.warn('Research cancel failed:', e));
        _researchingStreamIds.delete(_cancelSid);
        _clearResearchTimer();
      }
      abortCurrentRequest(true);  // explicit user Stop → also cancel the detached server run

      // Clean up any running agent thread nodes (stop wave animation, remove "running" state)
      document.querySelectorAll('.agent-thread-node.running').forEach(node => {
        if (node._waveInterval) { clearInterval(node._waveInterval); node._waveInterval = null; }
        if (node._elapsedTicker) { clearInterval(node._elapsedTicker); node._elapsedTicker = null; }
        node.classList.remove('running');
        const wave = node.querySelector('.agent-thread-wave');
        if (wave) wave.textContent = '';
        const icon = node.querySelector('.agent-thread-icon');
        if (icon) icon.textContent = '\u25A0'; // stop square
        const statusEl = node.querySelector('.agent-thread-status');
        if (!statusEl) {
          const header = node.querySelector('.agent-thread-header');
          if (header) {
            const s = document.createElement('span');
            s.className = 'agent-thread-status';
            s.textContent = 'stopped';
            header.appendChild(s);
          }
        }
      });
      document.querySelectorAll('.agent-thread.streaming').forEach(t => t.classList.remove('streaming'));

      // Clean up any thinking spinners
      document.querySelectorAll('.agent-thinking-dots').forEach(el => {
        if (el._spinner) el._spinner.destroy();
        el.remove();
      });
      // No text accumulated — remove the empty holder with spinner
      if (currentHolder && !currentAccumulated) {
        if (currentSpinner) { currentSpinner.destroy(); currentSpinner = null; }
        // Empty cancel — keep the assistant bubble around with a "Cancelled
        // by user" indicator and persist a placeholder server-side so the
        // turn survives a refresh instead of vanishing without a trace.
        _renderCancelledBubble(currentHolder);
        currentHolder = null;
        updateSubmitButton('idle', submitBtn);
        const messageInput = uiModule.el('message');
        if (messageInput) messageInput.disabled = false;
        currentAccumulated = '';
        _drainQueuedAgentRequests(sessionId);
        return;
      }
      // Render whatever was accumulated so far
      if (currentHolder && currentAccumulated) {
        const _activeStopStream = _getForegroundStreamState();
        const _terminalView = _activeStopStream?.finalizeView?.() || null;
        const _stoppedViewHolder = _terminalView?.holder || currentHolder;
        const _viewPreparedByStream = !!_terminalView;
        // The stream finalizer may close a synthetic reasoning tag. Capture the
        // durable raw value only after that canonical terminal preparation.
        const stoppedContent = _terminalView?.raw || currentAccumulated;
        _stoppedViewHolder.dataset.raw = stoppedContent;
        if (!_viewPreparedByStream) {
          _stoppedViewHolder.querySelector('.body').innerHTML = markdownModule.processWithThinking(
            markdownModule.squashOutsideCode(stoppedContent)
          );
        }
        
        // Highlight code blocks
        if (window.hljs) {
          _stoppedViewHolder.querySelectorAll('pre code').forEach((block) => {
            window.hljs.highlightElement(block);
          });
        }
        
        // Add the stopped indicator with continue button
        const stoppedIndicator = document.createElement('div');
        stoppedIndicator.className = 'stopped-indicator';
        const stoppedLabel = document.createElement('span');
        stoppedLabel.textContent = '[Message interrupted]';
        stoppedIndicator.appendChild(stoppedLabel);
        const continueBtn = document.createElement('button');
        continueBtn.className = 'continue-btn';
        continueBtn.title = 'Continue';
        continueBtn.textContent = '\u25B8';
        const _stoppedHolder = _stoppedViewHolder; // capture before globals are cleared
        continueBtn.addEventListener('click', () => {
          stoppedIndicator.remove();
          _hideUserBubble = true;
          _pendingContinue = _stoppedHolder;
          _pendingContinueSteps = false;   // `B941`: a stopped reply's text
          const cutoff = stoppedContent;
          const msgInput = uiModule.el('message');
          if (msgInput) {
            msgInput.value = 'Your previous response was interrupted. It ended with:\n\n' + cutoff.slice(-500) + '\n\nDo NOT repeat what you already said. Continue exactly from where you were cut off.';
            const sb = document.querySelector('.send-btn');
            if (sb) sb.click();
          }
        });
        stoppedIndicator.appendChild(continueBtn);
        _stoppedViewHolder.querySelector('.body').appendChild(stoppedIndicator);

        // Tell server to mark this message as stopped
        const _sid = sessionModule.getCurrentSessionId();
        if (_sid) fetch(`${API_BASE}/api/session/${_sid}/mark-stopped`, { method: 'POST' }).catch(e => console.warn('mark-stopped failed:', e));

        // Add footer with copy/regen if not already present
        if (!_stoppedViewHolder.querySelector('.msg-footer')) {
          _stoppedViewHolder.dataset.raw = stoppedContent;
          // `B920`: the reply may end in a later step's bubble than the one the pills are on.
          _stoppedViewHolder.appendChild(createMsgFooter(_withTurnPills(_stoppedViewHolder, currentHolder)));
        }

        uiModule.scrollHistory();
      }
      
      // Reset button state
      updateSubmitButton('idle', submitBtn);
      
      // Re-enable message input
      const messageInput = uiModule.el('message');
      if (messageInput) messageInput.disabled = false;
      
      // Clear tracking variables
      currentAccumulated = '';
      currentHolder = null;

      return;
    }

    // --- Send-path entry: block re-clicks between submit and stream start ---
    if (_sendInFlight) return;
    const _sendPerf = _createChatSendPerf();
    _sendInFlight = true;
    const approvalForSend = _pendingToolApproval;
    // `B81`. The verdict travels with the edge that raises the bar, so the bar
    // is never painted for a turn the composer already knows cannot take a
    // steer — instead of being painted here and withdrawn ~880 lines and one
    // round trip later when `stream_steerable` contradicts it.
    _setForegroundChatBusy(true, _composerTurnSteerable());
    // Instant visual feedback so the user sees their click was accepted
    // even before the streaming button state kicks in below.
    const _earlyMessageInput = uiModule.el('message');
    if (_earlyMessageInput) _earlyMessageInput.disabled = true;
    if (submitBtn) submitBtn.classList.add('send-pending');
    const _releaseSendFlag = () => {
      _sendInFlight = false;
      _syncForegroundStreamGlobals();
      if (_earlyMessageInput) _earlyMessageInput.disabled = false;
      if (submitBtn) submitBtn.classList.remove('send-pending');
    };

    // --- Setup mode: intercept next message (but let slash commands through) ---
    if (!approvalForSend) {
      const el = uiModule.el;
      const rawMsg = (el('message').value || '').trim();
      const currentSetupMode = slashCommands.getSetupMode();
      if (currentSetupMode && rawMsg && !isCommand(rawMsg)) {
        const mode = currentSetupMode;
        slashCommands.clearSetupMode(mode === 'endpoint-provider' || mode === 'endpoint-key-for-provider');
        el('message').value = '';
        if (window._syncModelPickerAutohide) window._syncModelPickerAutohide();
        if (uiModule.autoResize) uiModule.autoResize(el('message'));
        if (mode === true || mode === 'endpoint') {
          handleSetupInput(rawMsg);
        } else {
          handleSetupWizard(mode, rawMsg);
        }
        _releaseSendFlag();
        return;
      }
      if (currentSetupMode && rawMsg && isCommand(rawMsg)) {
        slashCommands.clearSetupMode();  // Clear setup mode, fall through to slash handler
      }
    }

    const el = uiModule.el;
    const msg = approvalForSend ? '' : el('message').value;
    // Allow empty text when a regen carries over the original message's
    // attachment ids — a photo-only message still has something to send.
    if (!msg.trim() && !approvalForSend && !fileHandlerModule.getPendingCount() && !(_pendingRegenAttachments && _pendingRegenAttachments.length)) { _releaseSendFlag(); return; }

    // --- Slash commands: execute directly without AI (no session needed) ---
    if (!approvalForSend && isCommand(msg.trim())) {
      const handled = await handleSlashCommand(msg.trim());
      if (handled) {
        el('message').value = '';
        if (window._syncModelPickerAutohide) window._syncModelPickerAutohide();
        if (uiModule.autoResize) uiModule.autoResize(el('message'));
        _releaseSendFlag();
        return;
      }
    }

    const incognitoChkForSend = el('incognito-toggle');
    const isIncognitoForSend = !!(incognitoChkForSend && incognitoChkForSend.checked);

    if (!isIncognitoForSend) {
      await _adoptOpenedSessionBeforeAutoCreate();
    }

    const selectedRouteForSend = selectedRoute();

    // Materialize pending session (deferred from model click) on first message
    if (sessionModule.hasPendingChat && sessionModule.hasPendingChat()) {
      _sendPerf.mark('pending_session_begin');
      const ok = await sessionModule.materializePendingSession();
      _sendPerf.mark('pending_session_done');
      if (!ok || !sessionModule.getCurrentSessionId()) { _releaseSendFlag(); return; }
    }

    if (!sessionModule.getCurrentSessionId()) {
      // Auto-create a session using default chat config. Always fetch fresh
      // so that a recent Settings change takes effect without a page reload.
      try {
        const pending = sessionModule.getPendingChat && sessionModule.getPendingChat();
        if (pending && pending.url && pending.modelId) {
          const ok = await sessionModule.materializePendingSession();
          if (!ok || !sessionModule.getCurrentSessionId()) { _releaseSendFlag(); return; }
        }
      } catch (_) {}
    }

    if (!sessionModule.getCurrentSessionId()) {
      // Auto-create a session using default chat config. Always fetch fresh
      // so that a recent Settings change takes effect without a page reload.
      try {
        let dc = (typeof window !== 'undefined' && window.__pantheonDefaultChat) || null;
        if (!dc || !dc.endpoint_url || !dc.model) {
          try {
            dc = JSON.parse(localStorage.getItem('pantheon-default-chat-cache') || 'null');
          } catch (_) {}
        }
        try {
          if (!dc || !dc.endpoint_url || !dc.model) {
            _sendPerf.mark('default_chat_fetch_begin');
            const dcRes = await fetch('/api/default-chat');
            dc = await dcRes.json();
            _sendPerf.mark('default_chat_fetch_done');
            if (dc && dc.endpoint_url && dc.model) {
              try {
                window.__pantheonDefaultChat = dc;
                localStorage.setItem('pantheon-default-chat-cache', JSON.stringify(dc));
              } catch (_) {}
            }
          }
        } catch (_) {
          dc = (typeof window !== 'undefined' && window.__pantheonDefaultChat) || null;
        }
        if (dc.endpoint_url && dc.model) {
          _sendPerf.mark('direct_chat_create_begin');
          await sessionModule.createDirectChat(dc.endpoint_url, dc.model, dc.endpoint_id, { source: 'default' });
          _sendPerf.mark('direct_chat_create_done');
          const ok = await sessionModule.materializePendingSession();
          _sendPerf.mark('direct_chat_materialize_done');
          if (!ok || !sessionModule.getCurrentSessionId()) { _releaseSendFlag(); return; }
        } else {
          el('message').value = '';
          if (uiModule.autoResize) uiModule.autoResize(el('message'));
          addMessage('assistant',
            'No chat session active. You can:\n\n' +
            '- Open the model picker in the chat box and pick a model\n' +
            '- Use the `+` button in the model picker to add a model endpoint\n' +
            '- Use `/help` to see all available commands');
          _releaseSendFlag();
          return;
        }
      } catch (e) {
        el('message').value = '';
        if (uiModule.autoResize) uiModule.autoResize(el('message'));
        addMessage('assistant',
          'No chat session active. You can:\n\n' +
          '- Open the model picker in the chat box and pick a model\n' +
          '- Use the `+` button in the model picker to add a model endpoint\n' +
          '- Use `/help` to see all available commands');
        _releaseSendFlag();
        return;
      }
    }

    // --- API key guard: warn if message looks like an API key ---
    if (!approvalForSend && API_KEY_RE.test(msg.trim())) {
      if (!await window.styledConfirm('This looks like an API key. Sending it to the AI could expose it.\n\nDid you mean to use /setup instead?', { confirmText: 'Send anyway', danger: true })) {
        _releaseSendFlag();
        return;
      }
    }


    const messageInput = el('message');
    const originalBtnText = submitBtn ? submitBtn.innerHTML : '';

    // Re-enable the textarea now that we've handed off to the stream: the
    // user wants to compose the next message while the AI is still talking.
    // The `isStreaming` flag is the re-click guard for the send button.
    if (messageInput) messageInput.disabled = false;
    updateSubmitButton('streaming', submitBtn);
    if (submitBtn) submitBtn.classList.remove('send-pending');
    // Per-send generation, reserved SYNCHRONOUSLY before the send gate clears
    // and before the first await: from this instant the superseded send may
    // not clean session state, register, or POST (each checked at its own
    // await boundaries). Session-keyed state (run id, queued Stop, cleanup
    // rights) belongs to the latest generation only. A queued Stop from the
    // superseded send is deliberately left in place, tagged with ITS
    // generation: that send's still-alive POST is the only identity channel
    // able to name its run, so the Stop fires from its own header arrival
    // (see _rememberStreamRunId) even if this replacement dies before fetch.
    const streamSessionId = sessionModule.getCurrentSessionId();
    const streamGeneration = (_streamGenerations.get(streamSessionId) || 0) + 1;
    _streamGenerations.set(streamSessionId, streamGeneration);
    const _sendState = { generation: streamGeneration, abortCtrl: null };
    _sendStates.set(streamSessionId, _sendState);
    // The previous send's run identity dies with its ownership: a Stop after
    // this instant must queue for THIS send, not fire against the old run.
    // (The old send's own queued Stop still works — its flush carries the run
    // id from its header, and its stale generation cannot repopulate this map.)
    _streamRunIds.delete(streamSessionId);
    _streamSessionId = streamSessionId;
    _sendInFlight = false;

    try {
      const pendingSwitch = window.__pantheonModelSwitchPromise;
      if (pendingSwitch && typeof pendingSwitch.then === 'function') {
        await pendingSwitch;
      }
    } catch (_) {}
    // Superseded while awaiting the model switch: the replacement owns the
    // session now, and everything below (state resets, registration, POST)
    // is its business alone.
    if (_streamGenerations.get(streamSessionId) !== streamGeneration) return;

    _terminalSavedStreams.delete(streamSessionId);
    const streamQuery = msg;
    _touchStreamActivity(streamSessionId);

    // Acquire Web Lock to hint browser not to discard this tab while streaming
    if (navigator.locks) {
      navigator.locks.request('pantheon-stream-' + streamSessionId, { mode: 'exclusive', ifAvailable: true }, lock => {
        if (!lock) return; // Another stream already holds a lock — fine
        return new Promise(resolve => { _webLockRelease = resolve; });
      }).catch(e => console.warn('web lock acquire failed:', e)); // Ignore lock errors — best-effort
    }

    // Declare accumulated outside try block so it's accessible in catch
    let accumulated = '';
    // Are we currently inside an unclosed <think> block? Toggled per think/answer
    // cycle so a multi-round agent response (one reasoning phase PER round) wraps each
    // round's reasoning in its own <think>…</think> instead of leaking rounds 2+ as text.
    let _thinkOpen = false;
    let holder = null;
    let finalMeta = null;
    let _canonicalTerminalSaved = false;
    let spinner = null;
    let timedOut = false;
    let processingProbeTimer = null;
    let processingProbeAbort = null;
    let _renderStream = () => {};
    let _finalizeRoundRender = () => {};
    let _finalizeInterruptedView = () => null;
    let _cancelThinkingTimer = () => {};
    let _removeThinkingSpinner = () => {};
    let _flushLiveThinking = () => '';
    let _cancelLiveThinkingWork = () => {};
    // Declared out here, not inside the try: in an ES module a function declared
    // in the try block is scoped to that block, so `catch` (a sibling scope)
    // cannot see it. Calling one from catch throws ReferenceError and kills the
    // rest of the error path — the stream never finalizes and the partial
    // message is lost. Assigned below, alongside the two helpers above.
    let _closeOpenThinkingMarkup = () => {};
    let _endThinkingOnTerminalPath = () => {};
    let timeoutId = null;
    let responseTimeoutCleared = false;
    let clearResponseTimeout = () => {};
    let firstTokenWaitTimers = [];
    // `B907`. The turn's meter, for the wait messages to read what preparation
    // has reported; set once the meter exists, after the POST returns.
    let firstTokenWaitMeter = null;
    const clearFirstTokenWaitTimers = () => {
      firstTokenWaitTimers.forEach(t => { try { clearTimeout(t); clearInterval(t); } catch (_) {} });
      firstTokenWaitTimers = [];
    };
    // `B907`. What the reply's spinner says while the model's first token is
    // slow in coming. These were three fixed sentences at 20s, 60s and 120s,
    // and the middle one stated a guess as a fact ("Large local model is
    // pre-filling context"). They were also never seen: the first `data:` line
    // of any kind called them off, and every stream opens with
    // `stream_steerable`. Now the model's first output calls them off
    // (`markFirstVisibleOutput`), and the words are `firstTokenWaitText`'s —
    // only what the page knows. From 20s they are re-read every second, so a
    // count on the spinner is never a stale one.
    const scheduleFirstTokenWaitMessages = () => {
      clearFirstTokenWaitTimers();
      const sentAt = Date.now();
      const say = () => {
        if (accumulated || !spinner || !spinner.element || (abortCtrl && abortCtrl.signal.aborted)) return;
        const text = firstTokenWaitText(firstTokenWaitMeter ? firstTokenWaitMeter.state : null,
          Date.now() - sentAt, Date.now());
        if (text && text !== spinner.message) spinner.updateMessage(text);
      };
      firstTokenWaitTimers.push(setTimeout(() => {
        say();
        firstTokenWaitTimers.push(setInterval(say, 1000));
      }, FIRST_TOKEN_WAIT_FROM_MS));
    };
    const clearProcessingProbe = () => {
      if (processingProbeTimer) {
        clearTimeout(processingProbeTimer);
        processingProbeTimer = null;
      }
      if (processingProbeAbort) {
        try { processingProbeAbort.abort(); } catch (_) {}
        processingProbeAbort = null;
      }
    };

    // Reset tracking variables at start
    currentAccumulated = '';
    currentHolder = null;
    
    let abortCtrl = null;
    let streamingTTS = false;
    try {
      // Re-enable auto-scroll when user sends a message
      uiModule.setAutoScroll(true);
      uiModule.scrollHistoryInstant();
      // Clear completed dot now that user is interacting
      if (sessionModule.clearStreamComplete) sessionModule.clearStreamComplete(sessionModule.getCurrentSessionId());

      // Check for document selection context before consuming display override
      const docSel = !approvalForSend && documentModule
        ? documentModule.getSelectionContext()
        : null;
      if (docSel) {
        const sels = Array.isArray(docSel) ? docSel : [docSel];
        const lineRefs = sels.map(s =>
          s.startLine === s.endLine ? `L${s.startLine}` : `L${s.startLine}-${s.endLine}`
        );
        _displayOverride = `[Doc edit: ${lineRefs.join(', ')}] ${msg}`;
      }

      const userDisplay = _displayOverride || msg;
      _displayOverride = null;
      const skipBubble = _hideUserBubble || !!approvalForSend;
      _hideUserBubble = false;
      // Auto-recovery counter: carries across a turn's auto-continues, but resets
      // when the user genuinely sends a new message (so each task gets a fresh cap).
      // A real user turn (visible bubble) ALWAYS resets the budget — even if a
      // prior auto-continue's deferred click never cleared the pending flag — so a
      // stuck flag can't silently eat the next turn's recovery budget.
      if (!skipBubble) { _autoNudges = 0; _autoContinuePending = false; }
      else if (_autoContinuePending) { _autoContinuePending = false; }
      const _pendingAttachInfo = !approvalForSend && fileHandlerModule.getPendingCount()
        ? fileHandlerModule.getPendingInfo()
        // A queue drain uploaded its files back when the item was queued, so
        // there is nothing pending to read the meta from: it travels on the
        // item instead, through the slot `_setComposerAndSend` filled.
        : (!approvalForSend && _pendingSendAttachInfo && _pendingSendAttachInfo.length
          ? _pendingSendAttachInfo
          : null);
      if (!approvalForSend) _pendingSendAttachInfo = null;
      // `B232`. A 38-extension regex used to sit here and decide which files
      // the "Import to document library" banner offers, in front of a backend
      // that derives the answer. Measured against the real registers it was
      // wrong in BOTH directions: 10 ingestible extensions were never offered
      // (`.bash .doc .docx .epub .nix .odt .pdf .pptx .xls .xlsx`, five of them
      // formats the server has a bundled extractor for) and 9 offered
      // extensions no register names (`.conf .env .ini .less .sass .scss
      // .svelte .toml .vue`) — the second nine being the RIGHT answer, since
      // `looks_like_text` rescues them on the server (`B76`), and therefore the
      // evidence that the question was never "is the extension on a list".
      //
      // **Swapping the regex for `INGESTIBLE_EXTS` would have been the trap.**
      // That set is `TEXT_EXTS | OFFICE_EXTS | PDF_EXTS`, so using it verbatim
      // offers `.pdf`, `.docx`, `.xlsx`, `.pptx` and `.epub` to the loop below,
      // which reads the raw `File` **as text**. Those are containers: they have
      // to be POSTed and extracted server-side, which is what `kind ===
      // 'document'` routes them to (`B233`'s `import-office`, and the
      // `import-pdf` route that already existed).
      //
      // So this now reads the server's own verdict — `kind` on each file of the
      // upload response, from `document_processor.ingest_kind` — which is why
      // it has to run AFTER the upload rather than before it. The raw `File` is
      // still reachable: `getLastUploadOutcome()` carries `{name, accepted, id,
      // meta, file}` per submitted file (`B03`), so nothing had to be pre-read.
      const _importableFiles = [];
      const _collectImportable = () => {
        if (!_pendingAttachInfo || !documentModule) return;
        const outcome = fileHandlerModule.getLastUploadOutcome?.() || [];
        if (outcome.length !== _pendingAttachInfo.length) return;
        for (let i = 0; i < _pendingAttachInfo.length; i++) {
          const info = _pendingAttachInfo[i];
          const o = outcome[i];
          if (!o || !o.accepted || !o.file) continue;
          // Same per-row name check the bubble pairing does: a mismatch means
          // these two lists are not describing the same batch.
          if (o.name !== (info.uploadName || info.name)) continue;
          const kind = o.meta && o.meta.kind;
          if (kind !== INGEST_KIND_TEXT && kind !== INGEST_KIND_DOCUMENT) continue;
          _importableFiles.push({ info, file: o.file, kind });
        }
      };
      let _userMsgEl = null;
      if (!skipBubble) {
        _userMsgEl = addMessage('user', userDisplay, null, _pendingAttachInfo ? { attachments: _pendingAttachInfo } : null);
      }
      _sendPerf.mark('user_bubble_visible');
      messageInput.value = approvalForSend ? (approvalForSend.draft || '') : '';
      messageInput.style.height = '';
      messageInput.dispatchEvent(new Event('input'));
      // Mobile: dismiss the on-screen keyboard after sending. iOS in
      // particular ignores a bare blur() in some cases (or some other
      // listener refocuses straight after), so we temporarily mark the
      // input readonly which forces the keyboard to retract, then blur,
      // then drop the readonly attribute after the keyboard is gone so
      // typing still works for the next message.
      if (window.innerWidth <= 768) {
        try {
          messageInput.setAttribute('readonly', 'readonly');
          messageInput.blur();
          const _dropReadonly = () => { try { messageInput.removeAttribute('readonly'); } catch {} };
          setTimeout(() => {
            // If the blur stuck, the input is no longer the active element —
            // safe to drop readonly now so the next message can be typed.
            // If it did NOT stick (some mobile browsers keep the textarea
            // focused after a programmatic blur), removing readonly here would
            // re-summon the keyboard mid-stream — the "bounce up" that then
            // lingers until the end-of-stream blur. In that case keep readonly
            // on (keyboard stays down) and drop it the moment the user taps to
            // type again, so typing still works without the bounce.
            if (document.activeElement === messageInput) {
              messageInput.addEventListener('pointerdown', _dropReadonly, { once: true });
              messageInput.addEventListener('focus', _dropReadonly, { once: true });
            } else {
              _dropReadonly();
            }
          }, 120);
        } catch {}
      }

      let ids = [];
      if (!approvalForSend) {
        try {
          _sendPerf.mark('upload_begin');
          ids = await fileHandlerModule.uploadPending({ sessionId: sessionModule.getCurrentSessionId() });
          _sendPerf.mark('upload_done');
        } catch(e) {
          console.error('upload failed', e);
          _sendPerf.mark('upload_failed');
        }
      }
      if (_pendingAttachInfo && !ids.length && !(_pendingRegenAttachments && _pendingRegenAttachments.length)) {
        if (_userMsgEl && _userMsgEl.parentNode) _userMsgEl.remove();
        if (fileHandlerModule.wasLastUploadCancelled && !fileHandlerModule.wasLastUploadCancelled()) {
          uiModule.showError && uiModule.showError('Upload failed. Attachment kept so you can retry.');
        }
        updateSubmitButton('idle', submitBtn);
        _releaseSendFlag();
        return;
      }

      // Carry over the original message's file-ids on a regenerate so the new
      // send still references the same photos / docs (and picks up the user's
      // edited OCR text via the server-side .vision cache). Always CONSUME the
      // slot — even when empty / errored — so the regen ids can't bleed into
      // an unrelated next message if uploadPending() above had thrown.
      if (!approvalForSend && _pendingRegenAttachments && _pendingRegenAttachments.length) {
        ids = ids.concat(_pendingRegenAttachments);
      }
      if (!approvalForSend) _pendingRegenAttachments = null;

      // The upload has resolved, so the server's per-file verdict is readable.
      _collectImportable();

      // The optimistic user bubble was rendered before the upload assigned ids,
      // so image previews couldn't show (the renderer needs att.id). Now that
      // the upload resolved, stamp the ids — plus width/height for images so
      // the skeleton can size itself to the photo's aspect ratio — and
      // re-render so the thumbnail appears live, no refresh needed.
      if (_userMsgEl && _pendingAttachInfo && ids.length) {
        const _meta = fileHandlerModule.getLastUploadedMeta?.() || [];
        // `B03`. This paired `_pendingAttachInfo[i]` — one entry per file the
        // user attached, in input order — with `ids[i]`. `ids` comes from the
        // server's `files` array, which preserves input order but SKIPS every
        // file it rejected, so a partial batch compacts it: [f0, f1✗, f2, f3✗,
        // f4] returns three ids and this loop gave f1's row f2's id. The
        // bubble then showed the WRONG THUMBNAIL under the RIGHT FILENAME —
        // mis-attribution, not the omission the row describes, and independent
        // of whether any toast is shown.
        //
        // `getLastUploadOutcome()` is the same length as the submitted batch
        // and carries the rejections in place, so each row can be keyed to the
        // file it actually describes. It is empty whenever the module has
        // nothing trustworthy to say (request failed, cancelled, or the
        // rejections did not reconcile), and empty on a queue drain, where
        // `_pendingAttachInfo` travelled on the queued item and the last
        // upload was somebody else's — hence the length and per-row NAME
        // check before any of it is believed.
        const _outcome = fileHandlerModule.getLastUploadOutcome?.() || [];
        const _aligned = _outcome.length === _pendingAttachInfo.length;
        // What the bubble should show. A refused file was never sent with this
        // message, so leaving its card in the user's own turn claims something
        // that did not happen — and with no id it would sit as a permanent
        // pre-upload skeleton. It is still in the composer strip, and the
        // toast named it.
        const _shown = [];
        for (let i = 0; i < _pendingAttachInfo.length; i++) {
          const _info = _pendingAttachInfo[i];
          let _id = null;
          let _m = null;
          if (_aligned) {
            const _o = _outcome[i];
            // The name each file was POSTed under. A mismatch means these two
            // lists are not describing the same batch, so stamp nothing rather
            // than stamp something wrong.
            if (!_o || _o.name !== (_info.uploadName || _info.name)) continue;
            if (!_o.accepted) continue;   // rejected: it has no id, and must not borrow one
            _id = _o.id;
            _m = _o.meta;
          } else {
            if (i >= ids.length) break;
            _id = ids[i];
            _m = _meta[i];
          }
          if (!_id) continue;
          _info.id = _id;
          // Never overwrite a dimension the info already carries: on a queue
          // drain it was stamped from that item's own upload, and
          // getLastUploadedMeta() now describes some later upload.
          if (_m) {
            if (_m.width && !_info.width)   _info.width  = _m.width;
            if (_m.height && !_info.height) _info.height = _m.height;
          }
          _shown.push(_info);
        }
        chatRenderer.updateMessageAttachments(
          _userMsgEl,
          _aligned && _shown.length ? _shown : _pendingAttachInfo,
        );
      }

      // Offer to import text files to document library
      if (_importableFiles.length > 0) {
        const existing = document.getElementById('import-prompt-banner');
        if (existing) existing.remove();
        const banner = document.createElement('div');
        banner.id = 'import-prompt-banner';
        banner.className = 'import-prompt-banner';
        const label = _importableFiles.length === 1
          ? `Import "${_importableFiles[0].info.name}" to document library?`
          : `Import ${_importableFiles.length} files to document library?`;
        const textEl = document.createElement('span');
        textEl.textContent = label;
        banner.appendChild(textEl);
        const importBtn = document.createElement('button');
        importBtn.textContent = 'Import';
        importBtn.addEventListener('click', async () => {
          importBtn.disabled = true;
          importBtn.textContent = 'Importing…';
          // `B161`. A 21-entry extension→language map used to be inlined on
          // this line — the smallest and stalest of the browser's three. It
          // knew neither `.toml` nor `.markdown`, so the banner that offers to
          // import the file you just attached stored it with no language while
          // the composer beside it labelled the same bytes `toml`.
          let imported = 0;
          for (const { info, file, kind } of _importableFiles) {
            try {
              // `B232`/`B233`. Two doors, because there are two kinds of file
              // and only one of them can be read in the browser. A container
              // (`.pdf`, `.doc`, `.docx`, `.odt`, `.pptx`, `.xls`, `.xlsx`,
              // `.epub`) is posted and the server extracts it with the readers
              // `B102` bundled; everything the server said reads as text is
              // read here, exactly as before.
              if (kind === INGEST_KIND_DOCUMENT) {
                await _importFileAsDocument(file, info.name);
              } else {
                const content = await file.text();
                const dotIdx = info.name.lastIndexOf('.');
                const title = dotIdx > 0 ? info.name.slice(0, dotIdx) : info.name;
                const r = await fetch(`${API_BASE}/api/document`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ title, language: documentLanguage(info.name), content }),
                });
                if (!r.ok) throw new Error('document ' + r.status);
              }
              imported++;
            } catch (e) { console.error('Import failed:', info.name, e); }
          }
          banner.textContent = `Imported ${imported} file${imported !== 1 ? 's' : ''}`;
          setTimeout(() => banner.remove(), 2000);
        });
        banner.appendChild(importBtn);
        const dismissBtn = document.createElement('button');
        dismissBtn.textContent = '\u00d7';
        dismissBtn.className = 'import-prompt-dismiss';
        dismissBtn.setAttribute('aria-label', 'Dismiss');
        dismissBtn.title = 'Dismiss';
        dismissBtn.addEventListener('click', () => banner.remove());
        banner.appendChild(dismissBtn);
        const chatBar = document.querySelector('.chat-input-bar');
        if (chatBar) chatBar.parentNode.insertBefore(banner, chatBar);
        // Auto-dismiss after 15 seconds
        setTimeout(() => { if (banner.parentNode) banner.remove(); }, 15000);
      }

      // Auto-save document editor content before sending so the AI sees latest text
      const activeEmailComposerCtx = documentModule && typeof documentModule.getActiveEmailComposerContext === 'function'
        ? documentModule.getActiveEmailComposerContext()
        : null;
      let activeDocIdForSend = documentModule && typeof documentModule.getCurrentDocId === 'function'
        ? documentModule.getCurrentDocId()
        : null;
      if (activeEmailComposerCtx?.docId) {
        activeDocIdForSend = activeEmailComposerCtx.docId;
      }
      const shouldSaveActiveDoc = !approvalForSend || (
        approvalForSend.document_id
        && approvalForSend.document_id === activeDocIdForSend
      );
      if (documentModule && activeDocIdForSend && shouldSaveActiveDoc) {
        try {
          _sendPerf.mark('doc_save_begin');
          const documentSaved = await documentModule.saveDocument({
            silent: !!approvalForSend,
          });
          _sendPerf.mark('doc_save_done');
          if (approvalForSend && documentSaved === false) {
            if (_userMsgEl && _userMsgEl.parentNode) _userMsgEl.remove();
            if (
              _pendingToolApproval
              && _pendingToolApproval.approval_id === approvalForSend.approval_id
            ) {
              _pendingToolApproval = null;
            }
            uiModule.showError && uiModule.showError(
              'Document could not be saved, so the action was not approved. Reload the chat to retry.'
            );
            updateSubmitButton('idle', submitBtn);
            _releaseSendFlag();
            return;
          }
        } catch(e) {
          console.warn('doc auto-save failed', e);
          _sendPerf.mark('doc_save_failed');
          if (approvalForSend) {
            if (_userMsgEl && _userMsgEl.parentNode) _userMsgEl.remove();
            if (
              _pendingToolApproval
              && _pendingToolApproval.approval_id === approvalForSend.approval_id
            ) {
              _pendingToolApproval = null;
            }
            uiModule.showError && uiModule.showError(
              'Document could not be saved, so the action was not approved. Reload the chat to retry.'
            );
            updateSubmitButton('idle', submitBtn);
            _releaseSendFlag();
            return;
          }
        }
      }

      // Inject document selection context if present
      let finalMsg = msg;
      if (docSel) {
        const sels = Array.isArray(docSel) ? docSel : [docSel];
        if (sels.length === 1) {
          const s = sels[0];
          const lineRef = s.startLine === s.endLine ? `line ${s.startLine}` : `lines ${s.startLine}-${s.endLine}`;
          finalMsg = `In the document, edit this specific text (${lineRef}):\n\`\`\`\n${s.text}\n\`\`\`\n\nInstruction: ${msg}`;
        } else {
          const parts = sels.map((s, i) => {
            const lineRef = s.startLine === s.endLine ? `line ${s.startLine}` : `lines ${s.startLine}-${s.endLine}`;
            return `Selection ${i + 1} (${lineRef}):\n\`\`\`\n${s.text}\n\`\`\``;
          });
          finalMsg = `In the document, edit these specific sections:\n\n${parts.join('\n\n')}\n\nInstruction: ${msg}`;
        }
      }

      // Apply inject prefix/suffix
      const _inject = presetsModule.getInject ? presetsModule.getInject() : { prefix: '', suffix: '' };
      let _finalMsgWithInject = finalMsg;
      if (_inject.prefix) _finalMsgWithInject = _inject.prefix + ' ' + _finalMsgWithInject;
      if (_inject.suffix) _finalMsgWithInject = _finalMsgWithInject + ' ' + _inject.suffix;

      const fd = new FormData();
      fd.append('message', approvalForSend ? '' : _finalMsgWithInject);
      fd.append('session', streamSessionId);
      if (approvalForSend) {
        fd.append('tool_approval_id', approvalForSend.approval_id);
        fd.append('tool_approval_decision', approvalForSend.decision);
        if (
          _pendingToolApproval
          && _pendingToolApproval.approval_id === approvalForSend.approval_id
        ) {
          _pendingToolApproval = null;
        }
      }
      if (selectedRouteForSend.model) fd.append('selected_model', selectedRouteForSend.model);
      if (selectedRouteForSend.endpoint_url) fd.append('selected_endpoint_url', selectedRouteForSend.endpoint_url);
      if (selectedRouteForSend.endpoint_id) fd.append('selected_endpoint_id', selectedRouteForSend.endpoint_id);
      if (ids.length) fd.append('attachments', JSON.stringify(ids));
      // Auto-save & send active doc ID so the backend sees latest content
      if (documentModule && activeDocIdForSend && shouldSaveActiveDoc) {
        if (!approvalForSend) {
          try {
            _sendPerf.mark('doc_silent_save_begin');
            await documentModule.saveDocument({ silent: true });
            _sendPerf.mark('doc_silent_save_done');
          } catch (_e) {
            _sendPerf.mark('doc_silent_save_failed');
          }
        }
        fd.append('active_doc_id', activeDocIdForSend);
      }
      // Active email context — when an email reader is open, pass its
      // uid/folder/account so "reply", "summarize", "what does this say"
      // resolve to the email the user is actually looking at instead of
      // making the agent invent a new markdown draft with fake headers.
      try {
        const getEmailCtx = window.__pantheonGetActiveEmailContext;
        const emCtx = typeof getEmailCtx === 'function' ? getEmailCtx() : null;
        if (activeEmailComposerCtx && activeEmailComposerCtx.sourceUid) {
          fd.append('active_email_uid', String(activeEmailComposerCtx.sourceUid));
          fd.append('active_email_folder', String(activeEmailComposerCtx.sourceFolder || 'INBOX'));
        } else if (emCtx && emCtx.uid) {
          fd.append('active_email_uid', String(emCtx.uid));
          fd.append('active_email_folder', String(emCtx.folder || 'INBOX'));
          if (emCtx.account) fd.append('active_email_account', String(emCtx.account));
        }
      } catch (_e) { /* best-effort */ }
      // Web toggle: pre-search in Chat mode only. Agent mode should not
      // opportunistically hit SearXNG just because the chat search toggle is
      // on; explicit web/current-info requests are handled by the backend
	      // intent gate.
	      const toggleState = Storage.loadToggleState();
	      const isPlanMode = !!toggleState.plan_mode && !(el('research-toggle') && el('research-toggle').checked);
	      let isAgentMode = (toggleState.mode || 'chat') === 'agent';
      const isIncognito = isIncognitoForSend;
	      const workspaceAgentIntent = !isIncognito && /\b(fix|debug|implement|change|update|refactor|patch|review|test|run|execute|start|launch|build|lint|typecheck|benchmark|eval|terminal[- ]bench|tbench|repo|repository|codebase|project|app|server|api|frontend|backend|bug|issue|pr|file|folder|directory|source|logs?|trace|stacktrace|traceback|docker|container|tmux|terminal|shell|git|branch|commit|diff|pytest|process|port|endpoint|computer|machine|laptop|device|system)\b/i.test(String(msg || ''));
	      // `B06`. Asked of `planWindow` rather than of a local copy, so it is
	      // still true on turn two.
	      const executingPlan = (!isPlanMode && planWindow.isExecuting())
	        ? (_getStoredPlan() || '')
	        : '';
	      if (isPlanMode || executingPlan) {
	        isAgentMode = true;
	      }
	      if (!isAgentMode && workspaceAgentIntent) {
	        isAgentMode = true;
	      }
	      // Auto-escalate to agent mode when a document is open — the user expects
	      // the AI to see the document and have tools to edit it
	      if (!isIncognito && !isAgentMode && documentModule && activeDocIdForSend) {
	        isAgentMode = true;
	      }
	      fd.append('mode', isAgentMode ? 'agent' : 'chat');
	      fd.append('plan_mode', isPlanMode ? 'true' : 'false');
	      if (executingPlan) {
	        // Every turn, not just the first — `build_active_plan_note`'s
	        // docstring asks for exactly that. `planWindow.clearPlan()` and the
	        // last step being ticked are the two ways this stops.
	        fd.append('approved_plan', executingPlan.slice(0, 8192));
	      }
	      if (el('web-toggle').checked) {
	        if (!isAgentMode) {
	          fd.append('use_web', 'true');
        }
      }
      if (isAgentMode) {
        fd.append('allow_web_search', el('web-toggle').checked ? 'true' : 'false');
      }
	      if (!approvalForSend && el('research-toggle').checked) {
	        fd.append('use_research', 'true');
	        // Research always runs in chat mode — override agent if set
	        fd.set('mode', 'chat');
	        fd.set('plan_mode', 'false');
	      }
      fd.append('allow_bash', el('bash-toggle').checked ? 'true' : 'false');
      if (workspaceAgentIntent) fd.set('allow_bash', 'true');
      const ragChk = el('rag-toggle');
      if (ragChk && !ragChk.checked) {
        fd.append('use_rag', 'false');
      }
      if (isIncognito) {
        fd.append('incognito', 'true');
      }
      const _ws = (Storage.KEYS && Storage.get(Storage.KEYS.WORKSPACE, '')) || '';
      if (_ws) {
        fd.append('workspace', _ws);
      }
      if (presetsModule.getSelectedPreset()) {
        fd.append('preset_id', presetsModule.getSelectedPreset());
      }


      // Superseded during preflight (uploads, document saves): a newer send
      // owns the session. Bailing here — before registration and before the
      // POST — keeps this stale send from overwriting the replacement's
      // stream entry or reaching the server last, where agent_runs.start
      // would cancel the newer run in favor of this old one.
      if (_streamGenerations.get(streamSessionId) !== streamGeneration) {
        // The optimistic user bubble is already in the DOM looking sent, but
        // this message never reaches the server. Say so instead of leaving a
        // ghost that vanishes on refresh.
        if (_userMsgEl && _userMsgEl.parentNode) {
          const _notSentNote = document.createElement('div');
          _notSentNote.style.cssText = 'color: var(--color-error); font-style: italic; font-size: 0.85em; padding: 2px 0;';
          _notSentNote.textContent = '[Not sent — superseded by a newer message]';
          _userMsgEl.appendChild(_notSentNote);
        }
        return;
      }
      abortCtrl = new AbortController();
      abortCtrl._reason = '';
      _sendState.abortCtrl = abortCtrl;
      currentAbort = abortCtrl;

	      const _tState = Storage.loadToggleState();
	      const _isAgent = (_tState.mode || 'chat') === 'agent' || !!_tState.plan_mode || workspaceAgentIntent;

      // Timeout: 6 min for research and agent mode, 3 min otherwise
      const timeoutMs = el('research-toggle').checked || _isAgent ? RESEARCH_TIMEOUT_MS : DEFAULT_TIMEOUT_MS;
      timeoutId = setTimeout(() => {
        if (!abortCtrl.signal.aborted) {
          timedOut = true;
          abortCtrl._reason = 'timeout';
          if (_streamGenerations.get(streamSessionId) !== streamGeneration) {
            // Superseded send: the session's run id and Stop queue belong to
            // the replacement now. Just kill this hung POST.
            abortCtrl.abort();
            return;
          }
          let abortNow = true;
          try {
            abortNow = _streamRunIds.has(streamSessionId)
              ? _stopExactRun(streamSessionId)
              : _stopExactRun(streamSessionId, abortCtrl);
          } catch (_) {}
          if (abortNow) {
            abortCtrl.abort();
          } else {
            // The Stop is queued on the run-id header, but a request this
            // stalled may never send one. Hard-abort after a short grace so
            // the timeout still guarantees cancellation.
            setTimeout(() => {
              if (!abortCtrl.signal.aborted) abortCtrl.abort();
            }, RUN_ID_ABORT_GRACE_MS);
          }
        }
      }, timeoutMs);
      clearResponseTimeout = () => {
        if (responseTimeoutCleared) return;
        responseTimeoutCleared = true;
        clearTimeout(timeoutId);
      };
      
      const box = el('chat-history');
      holder = document.createElement('div');
      holder.className = 'msg msg-ai streaming';

      // Track holder globally so stop button can access it
      currentHolder = holder;
      _activeStreams.set(streamSessionId, {
        abortCtrl,
        holder,
        query: streamQuery,
        startedAt: Date.now(),
        lastActivity: Date.now(),
        // Resolve the mutable closure at call time: live-thinking helpers are
        // installed after the stream entry is registered.
        cancelViewWork: () => _cancelLiveThinkingWork(),
        finalizeView: () => _finalizeInterruptedView(),
      });
      _syncForegroundStreamGlobals();
      holder._researchQuery = msg; // Store query for notification text
      
      const modelName = _bestKnownStreamModel(selectedRouteForSend) || null;

      let loadingText = 'Initializing...';

      if (el('web-toggle').checked && !_isAgent) {
        const _searchLabel = searchModule ? searchModule.getProviderLabel() : 'web';
        loadingText = `Searching via ${_searchLabel}...<br>
                       <span style="font-size: 0.9em; opacity: 0.8;">
                       Query: "${msg.substring(0, 50)}${msg.length > 50 ? '...' : ''}"<br>
                       Fetching top results...</span>`;
      } else if (el('research-toggle').checked) {
        loadingText = 'Deep research mode active...';
      } else {
        loadingText = 'Processing request...';
      }

      var roleLabel = _modelRouteLabel(modelName, modelName);
      var _charNameInit = presetsModule.getCharacterName ? presetsModule.getCharacterName() : '';
      if (_charNameInit) roleLabel = _charNameInit;
      const roleTs = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
      holder.innerHTML = `<div class="role">${uiModule.esc(roleLabel)} <span class="role-timestamp">${roleTs}</span></div><div class="body"></div>`;
      holder._requestedModel = modelName;
      holder._actualModel = modelName;
      _applyModelColor(holder.querySelector('.role'), modelName);
      holder.style.position = 'relative';
      
      // Create spinner
      spinner = spinnerModule.create('Initializing', 'right', 'wave');
      currentSpinner = spinner;
      const bodyDiv = holder.querySelector('.body');
      bodyDiv.appendChild(spinner.createElement());
      spinner.start();
      
      // Update spinner message based on mode
      if (el('web-toggle').checked && !_isAgent) {
        spinner.updateMessage('Searching web with ' + (searchModule ? searchModule.getProviderLabel() : 'SearXNG'));
        setTimeout(() => spinner.updateMessage('Processing results'), 1500);
      } else if (el('research-toggle').checked) {
        spinner.updateMessage('Researching');
        setTimeout(() => spinner.updateMessage('Analyzing sources'), 1500);
      } else {
        spinner.updateMessage('Processing request');
        scheduleFirstTokenWaitMessages();
      }
      
      const researchBtn = el('research-toggle-btn');
      if (el('research-toggle').checked && researchBtn) {
        researchBtn.disabled = true;
        researchBtn.classList.remove('active');
      }
      box.appendChild(holder);
      uiModule.scrollHistory();

      const enableResearchBtn = () => {
        if (!researchBtn) return;
        researchBtn.disabled = false;
        researchBtn.classList.toggle('active', el('research-toggle').checked);
      };

      if (el('research-toggle').checked && researchBtn) {
        researchBtn.style.display = 'none';
        // Uncheck research toggle so follow-up messages don't trigger another research
        el('research-toggle').checked = false;
      }

      // User's current UTC offset in minutes (east of UTC). Threaded into
      // the agent so natural-language times like "today at 9pm" are
      // interpreted in YOUR timezone, not the server's.
      const _tzOffsetMin = -new Date().getTimezoneOffset();
      const _tzName = (() => {
        try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; }
        catch { return ''; }
      })();
      _sendPerf.mark('chat_stream_post_begin');
      const res = await fetch(`${API_BASE}/api/chat_stream`, {
        method: 'POST',
        body: fd,
        headers: { 'X-Tz-Offset': String(_tzOffsetMin), 'X-Tz-Name': _tzName },
        signal: abortCtrl.signal
      });
      _sendPerf.mark('chat_stream_headers');
      _sendPerf.report('headers_received');
      
      if (!res.ok) {
        clearResponseTimeout();
        if (res.status === 404) {
          // Session was deleted (e.g. by AI) — reload and go to welcome
          holder.remove();
          if (sessionModule) await sessionModule.loadSessions();
          return;
        }
        let errText = `Error ${res.status}`;
        try {
          const errBody = await res.text();
          // Parse nested JSON error if present
          const m = errBody.match(/"message"\s*:\s*"([^"]+)"/);
          if (m) errText = m[1].replace(/\\"/g, '"');
          else if (errBody.length < 200) errText = errBody;
        } catch {}
        // Auto-switch to chat mode for tool-related errors
        if (errText.includes('tool') || errText.includes('auto')) {
          errText = 'This model doesn\'t support agent tools — switched to Chat mode. Try again.';
          const _ab = document.getElementById('mode-agent-btn');
          const _cb = document.getElementById('mode-chat-btn');
          if (_ab && _cb) {
            _ab.classList.remove('active');
            _cb.classList.add('active');
            const _toggle = _ab.closest('.mode-toggle');
            if (_toggle) _toggle.classList.add('mode-chat');
          }
          if (typeof Storage !== 'undefined' && Storage.KEYS) {
            const _st = Storage.getJSON(Storage.KEYS.TOGGLES, {});
            _st.mode = 'chat';
            Storage.setJSON(Storage.KEYS.TOGGLES, _st);
          }
        }
        typewriterInto(holder.querySelector('.body'), errText);
        enableResearchBtn();
        return;
      }
      const streamRunId = res.headers.get('X-Pantheon-Run-Id') || '';
      if (streamRunId) _rememberStreamRunId(streamSessionId, streamRunId, streamGeneration);

      // Mark the chat log busy while streaming so screen readers wait for the
      // settled response instead of announcing every token. Cleared in finally.
      const _chatLog = document.getElementById('chat-history');
      if (_chatLog) _chatLog.setAttribute('aria-busy', 'true');

      // `P4-24`. Where this run's view starts. If the connection drops and the
      // run is picked up again (`_tryAutoRecover` → `resumeStream`), the replay
      // draws the whole turn from its first event and replaces this view from
      // here on, rather than drawing a second copy of it underneath.
      if (streamRunId && holder) holder.dataset.agentRun = streamRunId;

      const reader = res.body.getReader();
      _sendPerf.mark('reader_ready');
      _sendPerf.report('reader_ready');
      const decoder = new TextDecoder();
      let buffer = '';
      let metrics = null;
      let isThinking = false;
      let thinkingStartTime = null;
      // Streaming TTS: synthesize sentence-by-sentence during streaming
      streamingTTS = !!(window.aiTTSManager && window.aiTTSManager.autoPlay && window.aiTTSManager.available);
      if (streamingTTS) window.aiTTSManager.streamingStart();
      // Multi-bubble agent tracking
      let roundHolder = holder;       // Current AI text bubble (changes per round)
      let roundText = '';             // Text accumulated for current round
      let roundReplyText = null;      // Reply-only text after a thinking transition
      let currentToolBubble = null;   // Current tool execution bubble
      let lastToolThread = null;      // Visible tool timeline for tool-only turns
      let roundFinalized = false;     // Whether current round's text is finalized
      let roundFinalization = null;   // Terminal owner/result for the current round
      let lastContentRoundHolder = null; // Last non-empty round for an empty continuation Stop
      let _sourcesHtml = '';          // Sources box HTML to prepend to body
      let _sourcesExpanded = false;   // Track if user expanded sources during stream
      let _sourcesData = null;        // Raw sources data for rebuilding
      let _sourcesType = '';          // 'web' or 'research'
      let _findingsData = null;      // Raw findings data for collapsible box
      // `P4-08` / `P4-23`. This turn's prep breakdown and step / tool-call
      // meter: one node, hung under whichever spinner is on screen.
      const _meter = createAgentMeter();
      firstTokenWaitMeter = _meter;   // `B907`
      const _generatedImagesForTurn = [];
      function _rememberGeneratedImage(data) {
        const imageUrl = data?.image_url || data?.url || '';
        if (!imageUrl) return;
        const imageKey = String(data.image_id || imageUrl);
        if (_generatedImagesForTurn.some(x => String(x.image_id || x.image_url || x.url) === imageKey || x.image_url === imageUrl || x.url === imageUrl)) return;
        _generatedImagesForTurn.push({ ...data, image_url: imageUrl, url: imageUrl });
      }
      // _keepResearchOn removed — clarification state now persisted server-side via DB mode
      function _metricsTargetForTurn() {
        const visibleRound = (roundHolder && roundHolder.style.display !== 'none') ? roundHolder : null;
        const visibleText = visibleRound ? (visibleRound.querySelector('.body')?.textContent || '').trim() : '';
        // `B920`: the footer made here carries the turn's pills.
        if (lastToolThread && lastToolThread.isConnected && (!visibleRound || !visibleText || visibleText === 'Done.')) {
          return _withTurnPills(lastToolThread, holder);
        }
        return _withTurnPills(visibleRound || holder, holder);
      }
      // Insert sources box as a stable DOM node that won't be replaced during streaming.
      // Returns the content container to use for innerHTML updates.
      function _ensureStreamLayout(body) {
        if (!body) return body;
        // Sources are deferred to final render — don't insert during streaming
        // Ensure a stable content div exists for text content
        var contentDiv = body.querySelector('.stream-content');
        if (!contentDiv) {
          contentDiv = document.createElement('div');
          contentDiv.className = 'stream-content';
          body.appendChild(contentDiv);
        }
        return contentDiv;
      }
      function _ensureVisibleRoundForDelta() {
        if (!roundHolder || roundHolder.style.display !== 'none') return;
        if (!_openRoundBubble()) roundHolder.style.display = '';
      }
      // A fresh reply bubble at the bottom of the history, made the round's
      // own, with the round's text state reset. Returns its body, or `null`
      // when there is no history to put it in. `B904`: split out of
      // `_ensureVisibleRoundForDelta` so a teacher takeover can open the
      // teacher's first bubble the same way.
      function _openRoundBubble() {
        const box = document.getElementById('chat-history');
        if (!box) return null;
        // `P4-24`: the bubble builder `agent_step` and a resumed stream use.
        const newWrap = _newRoundBubble(box, holder, roundHolder, streamSessionId, modelName);
        const newBody = newWrap.querySelector('.body');
        if (lastToolThread && lastToolThread.isConnected) lastToolThread.classList.add('has-bottom');
        roundHolder = newWrap;
        roundText = '';
        roundReplyText = null;
        roundFinalized = false;
        roundFinalization = null;
        isThinking = false;
        _thinkingMode = null;
        _cancelThinkingGrace();
        _thinkingAnalysisGate.reset();
        _roundDisplayProjector.reset();
        _replyDisplayProjector.reset();
        _docFenceOpened = false;
        return newBody;
      }
      // `B904`. The thread the next tool card goes in, for `tool_start` and
      // `tool_blocked` alike: the thread at the bottom of the history, unless
      // something visible has been drawn below it since — a bubble with text, a
      // takeover banner, a note — in which case a new thread starts under that.
      // Hidden (empty) bubbles and the thinking spinner are passed over, as
      // `tool_start` always did. Two things changed when the refusal card and
      // the takeover banner started arriving live: the refusal card took
      // `lastToolThread` whatever had been drawn since, so a call refused in a
      // later step landed in an earlier step's thread, above that step's text;
      // and only a `.msg` bubble ended the search, so the teacher's first card
      // joined the student's thread, above the banner that separates them.
      function _cardThread() {
        // `P4-24`: the search lives at module scope so a resumed stream
        // follows the same rule; this is the live handler's view of it.
        const threadWrap = _threadForNextCard(document.getElementById('chat-history'),
          !!(roundText.trim() && roundHolder && roundHolder.style.display !== 'none'));
        lastToolThread = threadWrap;
        return threadWrap;
      }
      const esc = uiModule.esc;
      // Tool-aware thinking spinner
      let _lastToolName = '';
      // `P4-24`. The spinner a person waits at — the "Thinking" one between
      // tools, the 400ms pause before it, and which spinner the meter hangs
      // under — is `_createWaitSpinners`, shared with a resumed stream. The
      // names below are how the rest of this handler has always called it.
      const _wait = _createWaitSpinners({
        meter: _meter,
        roundSpinner: () => spinner,
        streaming: () => isStreaming,
        toolName: () => _lastToolName,
      });
      // Remove thinking spinner helper
      _removeThinkingSpinner = () => { _wait.remove(); };
      function _showThinkingSpinner(label) { _wait.show(label); }
      function _waitSpinner() { return _wait.host(); }
      function _replaceThinkingSpinner(label) { _wait.replace(label); }
      // Auto-show thinking spinner after text stops streaming
      function _scheduleThinkingSpinner() { _wait.schedule(); }
      _cancelThinkingTimer = () => { _wait.cancel(); };

      // Document streaming state (text-fence detection)
      let _docFenceOpened = false;
      const _thinkingAnalysisGate = createThinkingAnalysisGate({
        startsWithReasoningPrefix: markdownModule.startsWithReasoningPrefix,
      });
      const _roundDisplayProjector = createIncrementalDisplayProjector(_streamDisplayText);
      const _replyDisplayProjector = createIncrementalDisplayProjector(_streamDisplayText);
      let _thinkingMode = null;
      let _thinkingRecheckAt = 0;
      let _thinkingGraceTimer = null;
      let _liveThinkSection = null;
      let _liveThinkContent = null;
      let _liveThinkInner = null;
      let _liveThinkHeader = null;
      let _liveThinkSpinnerSlot = null;
      let _liveThinkTimerEl = null;
      let _liveThinkTokenCount = 0;
      let _liveThinkToggle = null;
      let _liveThinkDomId = null;
      let _liveThinkRenderThrottle = null;
      let _liveThinkLatestText = '';
      let _liveThinkTimerId = null;
      let _liveThinkReducedMotion = false;

      function _estimateThinkingTokens(text) {
        const clean = (text || '').trim();
        if (!clean) return 0;
        return Math.max(1, Math.ceil(clean.length / 4));
      }

      function _formatThinkStats(seconds, tokenCount) {
        const time = seconds ? seconds + 's' : '';
        const tokens = tokenCount ? tokenCount + ' tok' : '';
        return time && tokens ? time + ' · ' + tokens : (time || tokens);
      }

      function _stripThinkingWrappers(text) {
        return text
          .replace(/<\|channel>thought\s*\n?/gi, '')
          .replace(/<\|channel>response\s*\n?/gi, '')
          .replace(/<channel\|>/gi, '')
          .replace(/^\s*Thinking(?:\s+Process)?:\s*/i, '');
      }

      // While thinking is still open, every think tag in the round is noise, so
      // strip them all. Do NOT slice from the first <think> to the first </think>:
      // the false-close detection below deliberately keeps us in the thinking
      // state for `<think>The</think>` followed by real thinking left untagged,
      // and slicing would pin the live box to "The" for the rest of the stream.
      function _liveThinkingText(text) {
        const normalized = markdownModule.normalizeThinkingMarkup(_streamDisplayText(text || ''));
        return _stripThinkingWrappers(stripLiveThinkingTags(normalized));
      }

      // Once thinking has closed, the reply that follows </think> must not leak
      // into the thinking box, so go through extractThinkingBlocks — it already
      // collapses the false-close pattern and merges every block into one.
      function _closedThinkingText(text) {
        const normalized = markdownModule.normalizeThinkingMarkup(_streamDisplayText(text || ''));
        const blocks = markdownModule.extractThinkingBlocks
          ? markdownModule.extractThinkingBlocks(normalized)?.thinkingBlocks
          : null;
        if (blocks?.length) return _stripThinkingWrappers(blocks.join('\n\n'));
        return _liveThinkingText(text);
      }

      function _commitLiveThinkingText(text) {
        _liveThinkLatestText = String(text ?? '');
        _liveThinkTokenCount = _estimateThinkingTokens(_liveThinkLatestText);
        const target = _liveThinkInner;
        if (!target || !target.isConnected) return;
        const thinkBox = target.closest('.thinking-content');
        const nearBottom = !thinkBox || thinkBox.scrollHeight - thinkBox.clientHeight - thinkBox.scrollTop < 80;
        target.style.whiteSpace = 'pre-wrap';
        target.textContent = _liveThinkLatestText;
        if (thinkBox && nearBottom) thinkBox.scrollTop = thinkBox.scrollHeight;
        if (nearBottom) uiModule.scrollHistory();
      }

      function _ensureLiveThinkingThrottle() {
        if (!_liveThinkRenderThrottle) {
          _liveThinkRenderThrottle = createLiveThinkingThrottle(_commitLiveThinkingText, {
            prepare: ({ text, prepared }) => prepared ? String(text ?? '') : _liveThinkingText(text),
          });
        }
        return _liveThinkRenderThrottle;
      }

      function _stopLiveThinkTimer() {
        if (_liveThinkTimerId !== null) clearInterval(_liveThinkTimerId);
        _liveThinkTimerId = null;
      }

      function _startLiveThinkTimer() {
        if (_liveThinkTimerId !== null || !_liveThinkTimerEl) return;
        // P1-12: one place owns the query now (`static/js/motion.js`).
        _liveThinkReducedMotion = prefersReducedMotion();
        const cadence = _liveThinkReducedMotion ? 1000 : 250;
        _liveThinkTimerId = setInterval(() => {
          if (!_liveThinkTimerEl || !_liveThinkTimerEl.isConnected) {
            _stopLiveThinkTimer();
            return;
          }
          const elapsed = (Date.now() - thinkingStartTime) / 1000;
          const seconds = elapsed.toFixed(_liveThinkReducedMotion ? 0 : 1);
          _liveThinkTimerEl.textContent = _formatThinkStats(seconds, _liveThinkTokenCount);
        }, cadence);
      }

      function _queueLiveThinking(text, prepared = false) {
        _ensureLiveThinkingThrottle().update({ text, prepared });
        _startLiveThinkTimer();
      }

      _flushLiveThinking = ({ text = null, rich = false } = {}) => {
        if (text !== null) _queueLiveThinking(text, true);
        if (_liveThinkRenderThrottle) _liveThinkRenderThrottle.flush();
        if (rich && _liveThinkInner && _liveThinkInner.isConnected) {
          _liveThinkInner.style.whiteSpace = '';
          _liveThinkInner.innerHTML = markdownModule.mdToHtml(_liveThinkLatestText);
        }
        return _liveThinkLatestText;
      };

      _cancelLiveThinkingWork = () => {
        if (_liveThinkRenderThrottle) _liveThinkRenderThrottle.cancel();
        _liveThinkRenderThrottle = null;
        _stopLiveThinkTimer();
        _cancelThinkingGrace();
      };

      function _finalizeLiveThinking(text, rich = true) {
        const finalText = _flushLiveThinking({ text, rich });
        _cancelLiveThinkingWork();
        return finalText;
      }

      // Close the synthetic <think> we opened around vLLM reasoning deltas, so a
      // stream that ends mid-thinking doesn't persist an unclosed tag.
      // `currentAccumulated` is the FOREGROUND stop-state text — mirror the guard
      // the delta path uses (`if (!_isBg) currentAccumulated = accumulated`), or a
      // backgrounded stream overwrites the visible session's stop-state and
      // abortCurrentRequest/detachCurrentStream write it into the wrong bubble.
      _closeOpenThinkingMarkup = (isBackground) => {
        if (!_thinkOpen) return;
        accumulated += '</think>';
        roundText += '</think>';
        if (!isBackground) currentAccumulated = accumulated;
        _thinkOpen = false;
      };

      // Terminal finalize used by the catch path, which cannot see the
      // block-scoped helpers below.
      _endThinkingOnTerminalPath = ({ rich = true } = {}) => {
        if (isThinking) {
          isThinking = false;
          _thinkingMode = null;
          _thinkingRecheckAt = 0;
          _finalizeLiveThinking(_closedThinkingText(roundText), rich);
        } else {
          _cancelLiveThinkingWork();
        }
      };

      // Shared teardown for the terminal paths that end thinking without the
      // normal </think> transition (tool_start, agent_step, [DONE], errors).
      function _endLiveThinkingSection({ rich = true } = {}) {
        isThinking = false;
        _thinkingMode = null;
        _thinkingRecheckAt = 0;
        _finalizeLiveThinking(_closedThinkingText(roundText), rich);
        const elapsed = thinkingStartTime ? ((Date.now() - thinkingStartTime) / 1000).toFixed(1) : null;
        if (_liveThinkHeader) _liveThinkHeader.textContent = 'View thinking process';
        if (_liveThinkTimerEl) _liveThinkTimerEl.textContent = elapsed ? _formatThinkStats(elapsed, _liveThinkTokenCount) : '';
        if (_liveThinkSpinnerSlot) _liveThinkSpinnerSlot.remove();
      }

      function _cancelThinkingGrace() {
        if (_thinkingGraceTimer !== null) clearTimeout(_thinkingGraceTimer);
        _thinkingGraceTimer = null;
        _thinkingRecheckAt = 0;
      }

      function _finishLiveThinkingTransition() {
        if (!isThinking) return;
        isThinking = false;
        _thinkingMode = null;
        _cancelThinkingGrace();
        const closedText = _closedThinkingText(roundText);
        const thinkTextLen = closedText.trim().length;
        _finalizeLiveThinking(closedText, thinkTextLen >= 20);

        // Models sometimes emit a trivial marker such as <think>The</think>.
        if (thinkTextLen < 20 && _liveThinkSection) {
          _liveThinkSection.remove();
          _liveThinkSection = null;
          _liveThinkContent = null;
          _liveThinkInner = null;
          _liveThinkHeader = null;
          _liveThinkSpinnerSlot = null;
          _liveThinkTimerEl = null;
          _liveThinkTokenCount = 0;
          _liveThinkToggle = null;
          _liveThinkDomId = null;
          if (spinner && spinner.element) spinner.destroy();
          _renderStream({ knownNormal: true, displayText: _roundDisplayProjector.current() });
          _scheduleThinkingSpinner();
          return;
        }

        const elapsed = thinkingStartTime ? ((Date.now() - thinkingStartTime) / 1000).toFixed(1) : null;
        if (elapsed) {
          accumulated = accumulated.replace(/<think>/i, '<think time="' + elapsed + '">');
          roundText = roundText.replace(/<think>/i, '<think time="' + elapsed + '">');
        }
        if (_liveThinkHeader) _liveThinkHeader.textContent = 'View thinking process';
        if (_liveThinkSpinnerSlot) _liveThinkSpinnerSlot.remove();
        if (_liveThinkTimerEl && elapsed) {
          _liveThinkTimerEl.textContent = _formatThinkStats(elapsed, _liveThinkTokenCount);
          _liveThinkTimerEl.style.marginLeft = 'auto';
          _liveThinkTimerEl.style.marginRight = '5px';
          const headerRow = _liveThinkTimerEl.closest('.thinking-header');
          if (headerRow) {
            if (_liveThinkToggle && _liveThinkToggle.parentElement === headerRow) headerRow.insertBefore(_liveThinkTimerEl, _liveThinkToggle);
            else headerRow.appendChild(_liveThinkTimerEl);
          }
        }

        const thinkingId = 'think-' + Date.now();
        const liveHeader = _liveThinkSection && _liveThinkSection.querySelector('.thinking-header');
        if (liveHeader) liveHeader.dataset.thinkingId = thinkingId;
        if (_liveThinkContent) _liveThinkContent.id = thinkingId;
        if (_liveThinkToggle) _liveThinkToggle.id = thinkingId + '-toggle';

        const streamElement = _liveThinkSection ? _liveThinkSection.parentElement : roundHolder.querySelector('.stream-content');
        const replyHost = streamElement || roundHolder.querySelector('.body');
        if (replyHost && !replyHost.querySelector('.live-reply-content')) {
          const replyElement = document.createElement('div');
          replyElement.className = 'live-reply-content';
          replyHost.appendChild(replyElement);
        }
        _renderStream();
      }

      function _scheduleThinkingGrace() {
        if (_thinkingGraceTimer !== null || !_thinkingRecheckAt) return;
        const delay = Math.max(0, _thinkingRecheckAt - Date.now());
        _thinkingGraceTimer = setTimeout(() => {
          _thinkingGraceTimer = null;
          if (!isThinking || !roundHolder?.isConnected || abortCtrl?.signal?.aborted) return;
          _finishLiveThinkingTransition();
        }, delay);
      }

      // Terminal paths replace the whole round, so they should perform exactly
      // one rich markdown render instead of richly finalizing thinking, then
      // rendering the reply, then replacing both again.
      _finalizeRoundRender = () => {
        if (roundFinalized) return roundFinalization;
        const terminalHolder = roundHolder || holder;
        const dt = markdownModule.normalizeThinkingMarkup(_streamDisplayText(roundText));
        if (!dt.trim()) {
          terminalHolder.style.display = 'none';
          roundFinalized = true;
          roundFinalization = { rendered: true, holder: terminalHolder, hasContent: false };
          return roundFinalization;
        }
        const body = terminalHolder.querySelector('.body');
        const content = _ensureStreamLayout(body);
        content.style.minHeight = '';
        content.innerHTML = markdownModule.processWithThinking(markdownModule.squashOutsideCode(dt));
        if (window.hljs) terminalHolder.querySelectorAll('pre code').forEach((block) => window.hljs.highlightElement(block));
        roundFinalized = true;
        lastContentRoundHolder = terminalHolder;
        roundFinalization = { rendered: true, holder: terminalHolder, hasContent: true };
        return roundFinalization;
      };
      _finalizeInterruptedView = () => {
        _closeOpenThinkingMarkup(false);
        _endThinkingOnTerminalPath({ rich: false });
        const finalization = _finalizeRoundRender();
        return {
          rendered: !!finalization?.rendered,
          holder: finalization?.hasContent
            ? finalization.holder
            : (lastContentRoundHolder || finalization?.holder || roundHolder || holder),
          raw: accumulated,
        };
      };

      function _replyAfterClosedThinking(text) {
        text = markdownModule.normalizeThinkingMarkup(text || '');
        const closeRe = /<\/(?:think(?:ing)?|thought)>|<channel\|>/gi;
        let match = null;
        let last = null;
        while ((match = closeRe.exec(text || '')) !== null) last = match;
        if (!last) return '';
        return (text || '').slice(last.index + last[0].length).trimStart();
      }

      // Direct render helper for streaming text
      _renderStream = ({ knownNormal = false, displayText = null, replyText = null } = {}) => {
        const bodyEl = roundHolder.querySelector('.body');
        const contentEl = _ensureStreamLayout(bodyEl);

        // If thinking was already collapsed in-place, only render the reply portion
        let liveReply = contentEl.querySelector('.live-reply-content');
        if (liveReply) {
          // Extract reply text — handle native <think> tags and non-tag patterns
          let replyTrimmed = replyText === null ? '' : String(replyText);
          if (replyText === null) {
            const dt = markdownModule.normalizeThinkingMarkup(_streamDisplayText(roundText));
            const closedThinkReply = _replyAfterClosedThinking(dt);
            const { thinkingBlocks, content: extractedReply } = closedThinkReply
              ? { thinkingBlocks: [''], content: closedThinkReply }
              : markdownModule.extractThinkingBlocks(dt);
            if (thinkingBlocks.length) {
              replyTrimmed = (extractedReply || '').trim();
            } else {
            // Non-tag: check for garbled <think> (reasoning\n<think>reply)
            const _gm = dt.match(/^[\s\S]+?<(?:think(?:ing)?|thought)(?:\s+[^>]*)?>\s*([\s\S]*?)(?:<\/(?:think(?:ing)?|thought)>)?\s*$/i);
            if (_gm && _gm[1].trim()) {
              replyTrimmed = _gm[1].trim();
            } else {
              // Pure non-tag: find reply boundary
              const _rPrefixes = markdownModule.startsWithReasoningPrefix;
              const _rpStarts = ['Hey', 'Hi ', 'Hi!', 'Hello', 'Sure', 'Yes', 'No ', 'No,', 'Yo', 'OK', 'Here', 'Absolutely', 'Of course', 'Great', 'Alright', 'Thanks', 'Welcome', 'Good ', "I'm happy", "I'd be"];
              const _rt = (extractedReply || '').trimStart();
              if (_rPrefixes(_rt)) {
                const _rLines = _rt.split('\n');
                for (let _ri = 1; _ri < _rLines.length; _ri++) {
                  const _rl = _rLines[_ri].trim();
                  if (!_rl) continue;
                  if (_rpStarts.some(rp => _rl.startsWith(rp))) { replyTrimmed = _rLines.slice(_ri).join('\n'); break; }
                }
                if (!replyTrimmed) {
                  for (const rp of _rpStarts) {
                    const rx = new RegExp('[.!?]\\s*(' + rp.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')');
                    const m = rx.exec(_rt);
                    if (m && m.index > 20) { replyTrimmed = _rt.slice(m.index + 1).trim(); break; }
                  }
                }
              }
            }
            }
          }
          if (replyText === null) {
            roundReplyText = replyTrimmed;
            _replyDisplayProjector.reset();
            replyTrimmed = _replyDisplayProjector.append(replyTrimmed, roundReplyText);
          }
          if (replyTrimmed) {
            const r = liveReply._streamRenderer ||
              (liveReply._streamRenderer = createStreamRenderer(liveReply, {
                render: (t) => markdownModule.mdToHtml(markdownModule.squashOutsideCode(t)),
                hljs: window.hljs,
              }));
            r.update(replyTrimmed);
          }
          // Reply empty or not — preserve thinking bar, don't fall through to full re-render
          uiModule.scrollHistory();
          return;
        }

        // Thinking compatibility normalization and display stripping are
        // intentionally omitted from the known-normal path. The incremental
        // projector already handled the newly appended boundary, so repeating
        // the full-round regex chains per delta would restore O(N^2) work.
        let dt = displayText === null
          ? (knownNormal
              ? _roundDisplayProjector.current()
              : markdownModule.normalizeThinkingMarkup(_streamDisplayText(roundText)))
          : String(displayText);

        // If thinking is still streaming (unclosed <think>), show indicator instead of raw text
        if (!knownNormal && markdownModule.hasUnclosedThinkTag && markdownModule.hasUnclosedThinkTag(dt)) {
          const thinkStart = dt.search(/<(?:think(?:ing)?|thought)(?:\s+[^>]*)?>|<\|channel>thought/i);
          const thinkContent = dt.substring(Math.max(thinkStart, 0))
            .replace(/<(?:think(?:ing)?|thought)(?:\s+[^>]*)?>|<\|channel>thought\s*\n?/i, '')
            .replace(/<channel\|>/gi, '')
            .trim();
          const lines = thinkContent.split('\n').length;
          // Don't show beforeThink text during streaming — it'll appear in the final render
          // This prevents the "split into two" duplication
          contentEl.innerHTML =
            '<div class="thinking-section"><div class="thinking-header"><div class="thinking-header-left">Thinking' +
            (lines > 1 ? ` (${lines} lines)` : '') + '</div></div></div>';
          // The stream renderer self-heals when it next sees this overwritten
          // container (streamingRenderer.js), so no explicit reset is needed here.
          uiModule.scrollHistory();
          return;
        }

        // Incremental streaming render: freeze finalized blocks, re-render only the
        // growing tail, and highlight each code block once on completion. This is
        // what keeps code-block hover buttons from flickering and avoids the O(N^2)
        // re-parse/re-highlight of the whole message on every token.
        // See streamingRenderer.js / streamingSegmenter.js.
        if (_docFenceOpened && !dt.trim()) {
          _showDocumentWritingStatus(contentEl);
          uiModule.scrollHistory();
          return;
        }
        const renderer = contentEl._streamRenderer ||
          (contentEl._streamRenderer = createStreamRenderer(contentEl, {
            render: (t) => markdownModule.processWithThinking(markdownModule.squashOutsideCode(t)),
            hljs: window.hljs,
          }));
        renderer.update(dt);
        uiModule.scrollHistory();
      };

      let _nextIsError = false;
      let _streamSawDone = false;
      let _streamTerminalError = null;
      let _firstVisibleOutputSeen = false;
      // `B907`. The model's first output — a token, thinking included, or a
      // tool call and what only follows one — ends the wait for a first token.
      // This ran on the first `data:` line of any kind, and every stream opens
      // with `stream_steerable`, so the wait messages were called off within
      // milliseconds of being set.
      const markFirstVisibleOutput = (json) => {
        if (_firstVisibleOutputSeen || !endsFirstTokenWait(json)) return;
        _firstVisibleOutputSeen = true;
        clearFirstTokenWaitTimers();
      };

      while (true) {
        const { done, value } = await reader.read();
        _touchStreamActivity(streamSessionId);
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          // Log SSE event types (e.g. "event: error") for debugging
          if (line.startsWith('event: ')) {
            const evtType = line.slice(7).trim();
            if (evtType === 'error') _nextIsError = true;
            continue;
          }
          if (line.startsWith('data: ')) {
            const data = line.slice(6);

            // (thinking spinner removal is handled in agent_step / tool_start / content handlers)

            // Background detection: are we on a different session?
            // `P4-24`: or has a resumed view taken this chat's drawing over?
            // Coming back to a chat whose run this reader is still reading,
            // `checkBackgroundStream` has `resumeStream` draw the whole turn
            // from the run's replayed buffer, through the same drawing
            // functions as this handler. This reader missed everything that
            // happened while it was away, so from then on it keeps to its
            // background bookkeeping instead of drawing a partial second copy.
            const _bgView = _backgroundStreams.get(streamSessionId);
            const _isBg = (sessionModule.getCurrentSessionId() !== streamSessionId)
              || !!(_bgView && _bgView.resumedView && _bgView.abortCtrl === abortCtrl);

            // On first transition to background, store state in map
            if (_isBg && !_backgroundStreams.has(streamSessionId)) {
              // Leave the block in its finished shape (rich, no pre-wrap) rather
              // than frozen as plain text — the user may navigate back to it.
              _flushLiveThinking({ rich: true });
              _cancelLiveThinkingWork();
              _backgroundStreams.set(streamSessionId, {
                status: 'running',
                accumulated: accumulated,
                sourcesHtml: _sourcesHtml,
                findingsData: null,
                abortCtrl,
                query: streamQuery,
                metrics: null,
              });
              if (sessionModule && sessionModule.markStreaming) {
                sessionModule.markStreaming(streamSessionId);
              }
            }

            if (data === '[DONE]') {
              _streamSawDone = true;
              _closeOpenThinkingMarkup(_isBg);
              // Always update background map if entry exists (even if user switched back)
              var bgDone = _backgroundStreams.get(streamSessionId);
              if (bgDone && !_isBg) {
                _backgroundStreams.delete(streamSessionId);
              } else if (bgDone) {
                bgDone.status = 'completed';
                bgDone.accumulated = accumulated;
                if (_isBg) {
                  try {
                    _notifyStreamComplete(streamSessionId, streamQuery);
                    // `P4-24`: not into the chat a resumed view is showing —
                    // "Response ready in" this very chat is noise there.
                    if (sessionModule.getCurrentSessionId() !== streamSessionId) {
                      _insertStreamDoneToast(streamSessionId, streamQuery);
                    }
                  } catch (toastErr) {
                    console.warn('[bg-stream] Toast/notification error:', toastErr);
                  }
                }
                // CRITICAL: always mark stream complete for the sidebar dot
                try {
                  if (sessionModule && sessionModule.markStreamComplete) {
                    sessionModule.markStreamComplete(streamSessionId);
                  }
                } catch (dotErr) {
                  console.warn('[bg-stream] markStreamComplete error:', dotErr);
                }
                // Don't do foreground final render — the checkBackgroundStream poll
                // will detect 'completed' and reload history cleanly
                break;
              }
              // Force-close thinking if still open (model never output boundary)
              if (isThinking) {
                isThinking = false;
                // The final round render below is authoritative and will render
                // the complete thinking + reply markup once.
                _finalizeLiveThinking(_closedThinkingText(roundText), false);
                var _elapsedDone = thinkingStartTime ? ((Date.now() - thinkingStartTime) / 1000).toFixed(1) : null;
                if (_elapsedDone) {
                  accumulated = accumulated.replace(/<think>/i, '<think time="' + _elapsedDone + '">');
                  roundText = roundText.replace(/<think>/i, '<think time="' + _elapsedDone + '">');
                }
                if (_liveThinkHeader) _liveThinkHeader.textContent = 'View thinking process';
                if (_liveThinkSpinnerSlot) _liveThinkSpinnerSlot.remove();
                if (_liveThinkTimerEl && _elapsedDone) {
                  _liveThinkTimerEl.textContent = _formatThinkStats(_elapsedDone, _liveThinkTokenCount);
                  _liveThinkTimerEl.style.marginLeft = 'auto';
                  _liveThinkTimerEl.style.marginRight = '5px';
                  var _hdrDone = _liveThinkTimerEl.closest('.thinking-header');
                  // Keep the chevron furthest right with the timer to its left
                  // (match the live + final-render layout) — insert before the
                  // toggle rather than appending (which would land after it).
                  if (_hdrDone) {
                    if (_liveThinkToggle && _liveThinkToggle.parentElement === _hdrDone)
                      _hdrDone.insertBefore(_liveThinkTimerEl, _liveThinkToggle);
                    else _hdrDone.appendChild(_liveThinkTimerEl);
                  }
                }
                // Assign stable IDs
                var _thinkIdDone = 'think-' + Date.now();
                var _liveHdrDone = _liveThinkSection && _liveThinkSection.querySelector('.thinking-header');
                if (_liveHdrDone) _liveHdrDone.dataset.thinkingId = _thinkIdDone;
                if (_liveThinkContent) _liveThinkContent.id = _thinkIdDone;
                if (_liveThinkToggle) _liveThinkToggle.id = _thinkIdDone + '-toggle';
              }
              // Normal foreground completion — metrics will be displayed in the final render block below
              break;
            }
            try {
              const json = JSON.parse(data);
              // Handle SSE error events (e.g. HTTP 404 from provider)
              if (_nextIsError || json.status >= 400) {
                _nextIsError = false;
                _streamTerminalError = createTerminalStreamError(json);
                console.error('Stream error:', _streamTerminalError.message);
                if (spinner && spinner.element) spinner.destroy();
                break;
              }
              markFirstVisibleOutput(json);   // `B907`
              if (json.delta || json.type === 'agent_prep' || json.type === 'tool_approval_resolved' || json.type === 'generated_image' || json.type === 'tool_start' || json.type === 'tool_output' || json.type === 'tool_progress' || json.type === 'agent_step' || json.type === 'loop_breaker_triggered' || json.type === 'intent_nudge_exhausted' || json.type === 'doc_stream_open' || json.type === 'doc_stream_delta' || json.type === 'research_progress') {
                clearResponseTimeout();
                clearProcessingProbe();
              }
              if (json.type === 'generated_image') {
                _rememberGeneratedImage(json);
                if (!_isBg) _appendGeneratedImageBubble(json);
                continue;
              }
              if (json.type === 'agent_prep') {
                // `P4-08`. The four prep steps, live: the spinner says which is
                // running and the line under it what each finished one took.
                // This arm used to swap in a static "Preparing agent" — for the
                // one frame the loop sent, after preparing was already over.
                if (!_isBg) _cancelThinkingTimer();
                const _prepHost = _isBg ? null : _waitSpinner();
                presentMeterEvent(_meter, json, _prepHost);
                if (!_isBg && !_prepHost && _meter.spinnerLabel()) {
                  _replaceThinkingSpinner(_meter.spinnerLabel());
                }
                continue;
              }
              if (json.type === 'agent_budget') {
                // `P4-23`. The step and tool-call limits this run is held to,
                // and how much of each is spent — before either is reached.
                presentMeterEvent(_meter, json, _isBg ? null : _waitSpinner());
                continue;
              }
              if (json.type === 'rounds_exhausted' || json.type === 'budget_exceeded') {
                // `P4-23`. The stop the meter was counting toward. Recorded and
                // not consumed: the arms below still draw the note and Continue.
                presentMeterEvent(_meter, json, null);
              }
              if (json.type === 'tool_approval_resolved') {
                _cancelThinkingTimer();
                _removeThinkingSpinner();
                if (spinner && spinner.element) spinner.destroy();
                if (!_isBg && roundHolder && roundHolder !== holder) roundHolder.remove();
                if (!_isBg && holder) holder.remove();
                continue;
              }
              if (json.delta) {
                _cancelThinkingTimer();
                _removeThinkingSpinner();
                // Text arrived after tools — connect thread line to this bubble
                const _threadAbove = roundHolder?.previousElementSibling;
                if (_threadAbove && _threadAbove.classList.contains('agent-thread') && !_threadAbove.classList.contains('has-bottom')) {
                  _threadAbove.classList.add('has-bottom');
                }
                // VLLM reasoning tokens: wrap in <think> tags for the thinking UI.
                // Stateful open/close (not a whole-message substring check) so each round
                // of a multi-round agent response gets its own <think>…</think> — otherwise
                // only round 1 is wrapped and rounds 2+ reasoning leaks into the answer.
                let _delta = json.delta;
                if (json.thinking) {
                  if (!_thinkOpen) { _delta = '<think>' + _delta; _thinkOpen = true; }
                } else if (_thinkOpen) {
                  _delta = '</think>' + _delta; _thinkOpen = false;
	                }
	                const wasEmpty = !accumulated;
		                accumulated += _delta;
		                if (!_isBg) currentAccumulated = accumulated; // Foreground stop-state text
	                // First token arrived — switch stop button from processing to streaming
	                if (wasEmpty && submitBtn && !_isBg) {
	                  submitBtn.dataset.phase = 'receiving';
                }

                // Update background map if running in background
                if (_isBg) {
                  var bgEntry = _backgroundStreams.get(streamSessionId);
	                  if (bgEntry) bgEntry.accumulated = accumulated;
	                  continue; // Skip all DOM writes
	                }
	                _ensureVisibleRoundForDelta();
	                roundText += _delta;
	                _roundDisplayProjector.append(_delta, roundText);

                // Raw model text is not authorization to mutate the editor.
                // Detect document fences only for chat projection/status; the
                // server emits doc_stream_* after successful dispatch.
                if (!_docFenceOpened) {
                  _docFenceOpened = /```(?:create_document|documen(?:t)?)\s*\n/i.test(roundText);
                }

                // Detect thinking-in-progress:
                // 1. Normal: <think>...no closing tag yet
                // 2. Malformed: <think></think>\n...text but no second </think> yet
                // 3. Qwen3.5: "Thinking Process:" without <think> tags
                // Most deltas cannot change thinking state. Analyze cumulative
                // text only for a fresh tag/channel/reply boundary, an initial
                // reasoning prefix, or an expired false-close grace period.
                if (!_thinkingAnalysisGate.shouldAnalyze(roundText, {
                  isThinking,
                  nonTagThinking: _thinkingMode === 'prefix',
                  recheckAt: _thinkingRecheckAt,
                })) {
                  if (isThinking) {
                    _queueLiveThinking(roundText);
                  } else {
                    if (spinner && spinner.element) spinner.destroy();
                    if (roundReplyText !== null) {
                      roundReplyText += _delta;
                      const replyDisplayText = _replyDisplayProjector.append(_delta, roundReplyText);
                      _renderStream({ replyText: replyDisplayText });
                    } else {
                      _renderStream({ knownNormal: true, displayText: _roundDisplayProjector.current() });
                    }
                    _scheduleThinkingSpinner();
                    if (streamingTTS) window.aiTTSManager.streamingUpdate(roundText);
                  }
                  continue;
                }
                const normalizedRoundText = markdownModule.normalizeThinkingMarkup(roundText);
                let hasUnclosedThink = markdownModule.hasUnclosedThinkTag(normalizedRoundText);
                // Detect non-tag thinking patterns: "Thinking:", "Thinking Process:", Gemma-style reasoning
                // These patterns don't use <think> tags, so we simulate unclosed thinking during streaming
                const _replyPrefixes = ['Hey', 'Hi ', 'Hi!', 'Hello', 'Sure', 'Yes', 'No ', 'No,', 'Yo', 'OK', 'Here', 'Absolutely', 'Of course', 'Great', 'Alright', 'Thanks', 'Welcome', 'Good ', "I'm happy", "I'd be"];
                if (!hasUnclosedThink && !/<(?:think(?:ing)?|thought)(?:\s+[^>]*)?>|<\|channel>thought/i.test(normalizedRoundText)) {
                  const _trimmedRT = normalizedRoundText.trimStart();
                  const _isReasoning = markdownModule.startsWithReasoningPrefix(_trimmedRT);
                  if (_isReasoning) {
                    // Check if we can see a reply boundary yet (newline then reply pattern)
                    const _lines = _trimmedRT.split('\n');
                    let _replyFound = false;
                    for (let li = 1; li < _lines.length; li++) {
                      const _l = _lines[li].trim();
                      if (!_l) continue;
                      if (_replyPrefixes.some(rp => _l.startsWith(rp))) {
                        _replyFound = true;
                        break;
                      }
                    }
                    if (!_replyFound) {
                      // Also check within-line: "reasoning text.Reply text"
                      const _inlineReply = _replyPrefixes.some(rp => {
                        const rx = new RegExp('[.!?]\\s*' + rp.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
                        const m = rx.exec(_trimmedRT);
                        return m && m.index > 20;
                      });
                      if (!_inlineReply) hasUnclosedThink = true;
                    }
                  }
                }
                // Detect false close: <think>short</think> where real thinking follows untagged
                // Do NOT require a prior unclosed delta: providers can emit the
                // short open+close and leaked reasoning in one chunk.
                let _falseCloseDeadline = 0;
                if (!hasUnclosedThink) {
                  const _thinkMatch = normalizedRoundText.match(/<(?:think(?:ing)?|thought)(?:\s+[^>]*)?>([\s\S]*?)<\/(?:think(?:ing)?|thought)>/i);
                  const _thinkLen = _thinkMatch ? _thinkMatch[1].trim().length : 0;
                  if (_thinkMatch && _thinkLen < 20) {
                    const _afterClose = normalizedRoundText.replace(/<(?:think(?:ing)?|thought)(?:\s+[^>]*)?>([\s\S]*?)<\/(?:think(?:ing)?|thought)>/i, '').trim();
                    // Only keep waiting if there's trailing text that looks like thinking (not tool calls)
                    const _hasToolCall = /```(?:bash|python|web_search|read_file|write_file|create_document|edit_document|manage_|generate_image)/i.test(_afterClose);
                    const _hasOrphanClose = /<\/(?:think(?:ing)?|thought)>/i.test(_afterClose);
                    const _falseCloseStart = thinkingStartTime || Date.now();
                    if (_afterClose && !_hasToolCall && !_hasOrphanClose && (Date.now() - _falseCloseStart) < 500) {
                      hasUnclosedThink = true;
                      _falseCloseDeadline = _falseCloseStart + 500;
                      if (isThinking) {
                        _thinkingRecheckAt = _falseCloseDeadline;
                        _scheduleThinkingGrace();
                      }
                    } else if (isThinking) {
                      _cancelThinkingGrace();
                    }
                  }
                }

                if (hasUnclosedThink && !isThinking) {
                  isThinking = true;
                  _thinkingMode = /<(?:think(?:ing)?|thought)(?:\s+[^>]*)?>|<\|channel>thought/i.test(normalizedRoundText)
                    ? 'tag'
                    : 'prefix';
                  thinkingStartTime = Date.now();
                  _thinkingRecheckAt = _falseCloseDeadline || 0;
                  if (spinner && spinner.element) spinner.destroy();

                  // Create a live thinking box — starts expanded so content streams visibly
                  var thinkBody = roundHolder.querySelector('.body');
                  var thinkContent = _ensureStreamLayout(thinkBody);
                  thinkContent.style.minHeight = '';
                  _liveThinkDomId = 'live-think-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
                  thinkContent.innerHTML = `
                    <div class="thinking-section">
                      <div class="thinking-header" data-thinking-id="${_liveThinkDomId}">
                        <div class="thinking-header-left"><span class="live-think-header-text">Thinking\u2026</span></div>
                        <span class="live-think-spinner-slot" style="flex-shrink:0;margin-left:auto;"></span>
                        <span class="live-think-timer" style="font-size:11px;opacity:0.4;font-variant-numeric:tabular-nums;margin-left:6px;margin-right:5px;"></span>
                        <span class="thinking-toggle live-think-toggle expanded" id="${_liveThinkDomId}-toggle"></span>
                      </div>
                      <div class="thinking-content expanded" id="${_liveThinkDomId}">
                        <div class="thinking-content-inner live-think-inner"></div>
                      </div>
                    </div>`;
                  _liveThinkSection = thinkContent.querySelector('.thinking-section');
                  _liveThinkContent = thinkContent.querySelector('.thinking-content');
                  _liveThinkInner = thinkContent.querySelector('.live-think-inner');
                  _liveThinkHeader = thinkContent.querySelector('.live-think-header-text');
                  _liveThinkSpinnerSlot = thinkContent.querySelector('.live-think-spinner-slot');
                  _liveThinkTimerEl = thinkContent.querySelector('.live-think-timer');
                  _liveThinkToggle = thinkContent.querySelector('.live-think-toggle');
                  _liveThinkLatestText = '';
                  _cancelLiveThinkingWork();
                  _queueLiveThinking(roundText);
                  // Whirlpool spinner
                  if (_liveThinkSpinnerSlot) {
                    var _wp = spinnerModule.createWhirlpool(12);
                    _wp.element.style.margin = '0';
                    _wp.element.style.width = '12px';
                    _wp.element.style.height = '12px';
                    _wp.element.style.transform = 'translateY(-1px)'; // align the whirlpool with the header text
                    _liveThinkSpinnerSlot.appendChild(_wp.element);
                  }
                  if (_thinkingRecheckAt) _scheduleThinkingGrace();
                } else if (hasUnclosedThink && isThinking) {
                  _queueLiveThinking(roundText);
                  continue;
                } else if (!hasUnclosedThink && isThinking) {
                  _finishLiveThinkingTransition();
                } else {
                  // Normal streaming
                  if (spinner && spinner.element) spinner.destroy();
                  if (roundReplyText !== null) {
                    roundReplyText += _delta;
                    const replyDisplayText = _replyDisplayProjector.append(_delta, roundReplyText);
                    _renderStream({ replyText: replyDisplayText });
                  } else {
                    _renderStream({ knownNormal: true, displayText: _roundDisplayProjector.current() });
                  }
                  _scheduleThinkingSpinner();
                  // Feed streaming TTS with accumulated text
                  if (streamingTTS) window.aiTTSManager.streamingUpdate(roundText);
                }
              } else if (json.type === 'research_progress') {
                if (_isBg) continue; // Skip DOM updates in background
                _researchingStreamIds.add(streamSessionId);
                // Highlight research button while running
                var _rToggle = document.getElementById('research-toggle-btn');
                if (_rToggle) _rToggle.classList.add('research-running');
                // Request notification permission on first research event
                if ('Notification' in window && Notification.permission === 'default') {
                  Notification.requestPermission();
                }
                // Mark session as researching in sidebar
                var _rSid = sessionModule && sessionModule.getCurrentSessionId();
                if (_rSid && sessionModule.markResearching) sessionModule.markResearching(_rSid);
                const rp = json.data;
                // Start research timer + synapse on first progress event
                if (!_researchTimerEl && spinner && spinner.element) {
                  _researchStartTime = rp.started_at ? rp.started_at * 1000 : Date.now();
                  _researchAvgDuration = rp.avg_duration || null;
                  _researchTimerEl = document.createElement('div');
                  _researchTimerEl.className = 'research-timer';
                  // Styles in .research-timer CSS class
                  spinner.element.parentNode.insertBefore(_researchTimerEl, spinner.element.nextSibling);
                  _researchTimerInterval = setInterval(() => {
                    if (!_researchTimerEl) return;
                    var elapsed = Math.floor((Date.now() - _researchStartTime) / 1000);
                    var mm = String(Math.floor(elapsed / 60)).padStart(2, '0');
                    var ss = String(elapsed % 60).padStart(2, '0');
                    var txt = mm + ':' + ss;
                    if (_researchAvgDuration) {
                      var avgM = String(Math.floor(_researchAvgDuration / 60)).padStart(2, '0');
                      var avgS = String(Math.round(_researchAvgDuration % 60)).padStart(2, '0');
                      txt += ' / avg ' + avgM + ':' + avgS;
                    }
                    _researchTimerEl.textContent = txt;
                  }, 1000);
                  // Synapse visualization — insert right above the timer so
                  // it sits between the spinner message and the timer line.
                  try {
                    _researchSynapse = createResearchSynapse(spinner.element.parentNode, {
                      query: holder._researchQuery || rp.query || '',
                      startedAt: _researchStartTime,
                    });
                    // Move it to live between spinner and timer
                    if (_researchSynapse.element && _researchTimerEl) {
                      spinner.element.parentNode.insertBefore(_researchSynapse.element, _researchTimerEl);
                    }
                  } catch (e) { console.warn('synapse init failed', e); }
                }
                if (_researchSynapse) {
                  _researchSynapse.setPhase(rp.phase, rp);
                  if (typeof rp.round === 'number') _researchSynapse.setRound(rp.round);
                  if (typeof rp.total_sources === 'number') _researchSynapse.setSourceCount(rp.total_sources);
                  if (rp.phase === 'error') _researchSynapse.complete();
                }
                if (spinner && spinner.element) {
                  if (rp.phase === 'probing') {
                    spinner.updateMessage(`Verifying model: ${rp.model || '?'}`);
                  } else if (rp.phase === 'planning') {
                    spinner.updateMessage('Analyzing question & planning research strategy');
                  } else if (rp.phase === 'searching') {
                    const q = rp.queries ? `${rp.queries} queries` : '';
                    const s = rp.total_sources ? ` · ${rp.total_sources} sources` : '';
                    spinner.updateMessage(`Round ${rp.round || '?'}: Searching${q ? ' (' + q + ')' : ''}${s}`);
                  } else if (rp.phase === 'reading') {
                    spinner.updateMessage(rp.title ? `Reading: ${rp.title}` : `Round ${rp.round || '?'}: Reading ${rp.new_sources || ''} pages · ${rp.total_sources || 0} sources total`);
                  } else if (rp.phase === 'analyzing') {
                    spinner.updateMessage(`Round ${rp.round || '?'}: Analyzing ${rp.total_findings || 0} findings`);
                  } else if (rp.phase === 'writing') {
                    spinner.updateMessage(`Writing report · ${rp.total_sources || 0} sources`);
                  } else if (rp.phase === 'error') {
                    spinner.updateMessage(rp.message || 'Search error');
                  }
                }
              } else if (json.type === 'research_sources') {
                if (_isBg) {
                  // Store sources HTML in background map
                  if (json.data && json.data.length > 0) {
                    _sourcesHtml = _buildSourcesBox(json.data, 'research');
                    var bgE = _backgroundStreams.get(streamSessionId);
                    if (bgE) bgE.sourcesHtml = _sourcesHtml;
                  }
                  // Clear researching indicator for this background session
                  if (sessionModule && sessionModule.clearResearching) sessionModule.clearResearching(streamSessionId);
                  continue;
                }
                // Research done — clean up timer, show sources box, then spinner for LLM response
                _clearResearchTimer();
                holder._researchSources = json.data;
                var _rSid2 = sessionModule && sessionModule.getCurrentSessionId();
                if (_rSid2 && sessionModule.clearResearching) sessionModule.clearResearching(_rSid2);
                if (json.data && json.data.length > 0) {
                  _sourcesData = json.data; _sourcesType = 'research';
                  _sourcesHtml = _buildSourcesBox(json.data, 'research');
                }
                if (document.hidden) {
                  _notifyResearchComplete(_rSid2 || '', holder._researchQuery || '');
                }
              } else if (json.type === 'research_findings') {
                if (_isBg) {
                  var bgEf = _backgroundStreams.get(streamSessionId);
                  if (bgEf) bgEf.findingsData = json.data;
                  continue;
                }
                if (json.data && json.data.length > 0) {
                  _findingsData = json.data;
                }
              } else if (json.type === 'research_done') {
                // Research complete — reload session to show the persisted report
                _clearResearchTimer();
                if (sessionModule && sessionModule.clearResearching) {
                  sessionModule.clearResearching(streamSessionId);
                }
                _researchingStreamIds.delete(streamSessionId);
                // Small delay then reload session history which includes the full report
                setTimeout(async () => {
                  // Don't yank the user back to this chat if they've navigated
                  // away (e.g. started a new chat) while research finished —
                  // just refresh the sidebar so the report shows when they return.
                  if (sessionModule.getCurrentSessionId && sessionModule.getCurrentSessionId() === streamSessionId) {
                    await sessionModule.selectSession(streamSessionId);
                  } else {
                    await sessionModule.loadSessions();
                  }
                }, 500);
                continue;
              } else if (json.type === 'web_sources') {
                if (_isBg) {
                  if (json.data && json.data.length > 0) {
                    _sourcesHtml = _buildSourcesBox(json.data, 'web');
                    var bgE2 = _backgroundStreams.get(streamSessionId);
                    if (bgE2) bgE2.sourcesHtml = _sourcesHtml;
                  }
                  continue;
                }
                // Web search done — store sources for final render (don't render mid-stream)
                holder._webSources = json.data;
                if (json.data && json.data.length > 0) {
                  _sourcesData = json.data; _sourcesType = 'web';
                  _sourcesHtml = _buildSourcesBox(json.data, 'web');
                }
              } else if (json.type === 'workspace_rejected') {
                // Server refused to bind the posted workspace (deleted folder,
                // file path, sensitive dir, filesystem root). Clear the stored
                // value so the pill stops claiming a confinement that is not in
                // effect, and tell the user.
                const _wsPath = (json.data && json.data.path) || '';
                import('./workspace.js').then((m) => {
                  const ws = m.default || m;
                  if (ws && ws.setWorkspace) ws.setWorkspace('');
                });
                // `B968`: the server's sentence when it has one (a folder in the
                // workstation), the one for this machine when not.
                uiModule.showToast(
                  (json.data && json.data.message) ||
                    `Workspace ${_wsPath || '(unknown)'} is no longer usable; running without confinement`,
                  6000
                );
                continue;
              } else if (json.type === 'model_info') {
                // Update role label with model name as soon as we know it
                if (!_isBg && holder) {
                  const roleEl = holder.querySelector('.role');
                  if (roleEl) {
                    holder._requestedModel = json.requested_model || json.model || holder._requestedModel;
                    holder._actualModel = json.model || holder._actualModel || holder._requestedModel;
                    holder._requestedEndpointId = json.requested_endpoint_id || json.endpoint_id || holder._requestedEndpointId || null;
                    holder._requestedEndpointLabel = json.requested_endpoint_label || json.endpoint_label || holder._requestedEndpointLabel || 'Selected route';
                    holder._actualEndpointId = json.endpoint_id || holder._actualEndpointId || holder._requestedEndpointId;
                    holder._actualEndpointLabel = json.endpoint_label || holder._actualEndpointLabel || holder._requestedEndpointLabel;
                    if (json.suffix) holder._roleSuffix = json.suffix;
                    // Prepend character name if sent by server or set locally
                    var _charName = json.character_name || (presetsModule.getCharacterName ? presetsModule.getCharacterName() : '');
                    if (_charName) holder._characterName = _charName;
                    _setRoleModelLabel(roleEl, holder._requestedModel, holder._actualModel, {
                      suffix: holder._roleSuffix,
                      characterName: holder._characterName,
                      requestedEndpointId: holder._requestedEndpointId,
                      requestedEndpointLabel: holder._requestedEndpointLabel,
                      actualEndpointId: holder._actualEndpointId,
                      actualEndpointLabel: holder._actualEndpointLabel,
                    });
                  }
                }
              } else if (json.type === 'fallback') {
                // The selected model failed and another provider answered. Make
                // it visible so a misconfigured provider is never silently
                // masked under the selected model's name.
                if (!_isBg) {
                  // `P4-05`. The chain the toast used one field of. Kept on the
                  // holder so the footer pill can show every candidate and its
                  // status; the toast stays, because it is the signal in the
                  // moment and this is the record after it.
                  holder._fallbackChain = {
                    selected_model: json.selected_model,
                    answered_by: json.answered_by,
                    failures: json.failures || [],
                  };
                  var _selM = _shortModel(json.selected_model || '');
                  var _ansM = _shortModel(json.answered_by || '');
                  uiModule.showToast('Fallback: ' + _selM + ' failed — answered by ' + _ansM, 6000);
                  var _fallbackHolder = applyModelRouteEventState(json, holder, roundHolder, modelName);
                  if (_fallbackHolder) {
                    var _rEl = _fallbackHolder.querySelector('.role');
                    if (_rEl) {
                      var _tsS = _rEl.querySelector('.role-timestamp');
                      _rEl.textContent = _ansM + ' (fallback) ';
                      _rEl.title = (json.selected_model || '') + ' failed' +
                        (json.reason ? ': ' + json.reason : '') + ' — answered by ' + (json.answered_by || '');
                      _applyModelColor(_rEl, json.answered_by);
                      if (_tsS) _rEl.appendChild(_tsS);
                      _setRoleModelLabel(_rEl, _fallbackHolder._requestedModel, _fallbackHolder._actualModel, {
                        suffix: _fallbackHolder._roleSuffix,
                        characterName: _fallbackHolder._characterName,
                        reason: json.reason,
                        requestedEndpointId: _fallbackHolder._requestedEndpointId,
                        requestedEndpointLabel: _fallbackHolder._requestedEndpointLabel,
                        actualEndpointId: _fallbackHolder._actualEndpointId,
                        actualEndpointLabel: _fallbackHolder._actualEndpointLabel,
                      });
                    }
                  }
                }
              } else if (json.type === 'rounds_exhausted') {
                // The agent hit the per-turn step limit while still working.
                // Offer a Continue button instead of stalling silently.
                // NOTE: append to the chat-history container (bottom), NOT the
                // message body — the body innerHTML is re-rendered at stream
                // finalize, which would wipe a note placed inside it.
                const _chatBox = document.getElementById('chat-history');
                if (!_isBg && _chatBox) {
                  // `B906`. Nothing is coming after this step, so nothing is
                  // shown waiting for one. The last tool result schedules a
                  // "Thinking" spinner for the step after it; that step used
                  // to be announced (and a bubble opened for it) even when it
                  // was past the limit. The loop no longer announces it, and
                  // the pending spinner is called off here.
                  _cancelThinkingTimer();
                  _removeThinkingSpinner();
                  // `B915`. The note and its Continue are drawn by the one
                  // builder history replay and a resumed stream use, so a
                  // reload offers Continue too (the route saves the event with
                  // the reply). It drops any prior box first, so repeated
                  // cap-hits each get a fresh Continue at the bottom (multiple
                  // continues in a row), and Continue picks up from this
                  // turn's first bubble, as it always did.
                  const note = renderAgentNote(_chatBox, json, { reply: holder });
                  if (note) {
                    try { note.scrollIntoView({ block: 'end', behavior: 'smooth' }); } catch (_) { uiModule.scrollHistory && uiModule.scrollHistory(); }
                  }
                }
              } else if (json.type === 'model_actual') {
                if (!_isBg) {
                  var _modelHolder = applyModelRouteEventState(json, holder, roundHolder, modelName);
                  if (_modelHolder) _setRoleModelLabel(_modelHolder.querySelector('.role'), _modelHolder._requestedModel, _modelHolder._actualModel, {
                    suffix: _modelHolder._roleSuffix,
                    characterName: _modelHolder._characterName,
                    requestedEndpointId: _modelHolder._requestedEndpointId,
                    requestedEndpointLabel: _modelHolder._requestedEndpointLabel,
                    actualEndpointId: _modelHolder._actualEndpointId,
                    actualEndpointLabel: _modelHolder._actualEndpointLabel,
                  });
                }
              } else if (json.type === 'attachments') {
                if (_isBg) continue;
                // Update user bubble — replace file chips with image previews
                const _ub = document.querySelector('#chat-history .msg-user:last-of-type');
                if (_ub) {
                  const _aw = _ub.querySelector('.attach-cards');
                  if (_aw) {
                    for (const _att of json.data) {
                      const _isImg = (_att.mime || '').startsWith('image/') || /\.(png|jpg|jpeg|gif|webp|svg|bmp)$/i.test(_att.name || '');
                      if (_isImg && _att.id) {
                        // Skip if we already have a preview for this file id —
                        // on a regenerate the original user bubble keeps its
                        // photo and the backend re-emits the attachment event
                        // for the same id; without this guard we'd append a
                        // duplicate (which visually pushes the real photo off).
                        const _existingPreview = _aw.querySelector('[data-file-id="' + _att.id + '"]');
                        if (_existingPreview) {
                          if (_att.vision_model && !_existingPreview.querySelector('.attach-vision-model')) {
                            const _vl = document.createElement('div');
                            _vl.className = 'attach-vision-model';
                            _vl.textContent = 'Vision: ' + String(_att.vision_model).split('/').pop();
                            const _name = _existingPreview.querySelector('.attach-image-name');
                            if (_name) _existingPreview.insertBefore(_vl, _name);
                            else _existingPreview.appendChild(_vl);
                          }
                          continue;
                        }
                        const _card = _aw.querySelector('.attach-card[data-name="' + (_att.name || '').replace(/"/g, '\\"') + '"]');
                        const _iw = document.createElement('div');
                        _iw.className = 'attach-image-preview';
                        _iw.dataset.fileId = _att.id;
                        _iw.style.cursor = 'pointer';
                        _iw.onclick = () => window.open(API_BASE + '/api/upload/' + _att.id, '_blank');
                        const _im = document.createElement('img');
                        _im.src = API_BASE + '/api/upload/' + _att.id;
                        _im.alt = _att.name || 'Image';
                        _im.style.cssText = 'max-width:300px;max-height:200px;border-radius:6px;display:block;';
                        _iw.appendChild(_im);
                        if (_att.vision_model) {
                          const _vl = document.createElement('div');
                          _vl.className = 'attach-vision-model';
                          _vl.textContent = 'Vision: ' + String(_att.vision_model).split('/').pop();
                          _iw.appendChild(_vl);
                        }
                        if (_att.name) {
                          const _nm = document.createElement('div');
                          _nm.className = 'attach-image-name';
                          _nm.textContent = _att.name;
                          _iw.appendChild(_nm);
                        }
                        if (_card) _card.replaceWith(_iw); else _aw.appendChild(_iw);
                      } else {
                        const _card = _aw.querySelector('.attach-card[data-name="' + (_att.name || '').replace(/"/g, '\\"') + '"]');
                        if (_card && _att.id) {
                          _card.dataset.fileId = _att.id;
                          _card.style.cursor = 'pointer';
                          _card.onclick = () => window.open(API_BASE + '/api/upload/' + _att.id, '_blank');
                        }
                      }
                    }
                  }
                  // Caption / OCR text is no longer rendered as an inline
                  // collapsible on the user bubble — the user can view/edit
                  // it via the "Caption" button on the photo thumbnail.
                }
              } else if (json.type === 'rag_sources') {
                if (_isBg) continue;
                holder._ragSources = json.data;
              } else if (json.type === 'memories_used') {
                if (_isBg) continue;
                holder._memoriesUsed = json.data;
              } else if (json.type === 'skills_injected') {
                // `P4-16`. Up to a dozen procedures enter a request and until
                // now nothing said which. Same footer, same shape as the
                // memories pill beside it.
                if (_isBg) continue;
                holder._skillsInjected = json.data;
              } else if (json.type === 'tool_blocked') {
                // `P4-20`. The call the policy refused. Its own node, because
                // `currentToolBubble` points at whatever card is open and a
                // refusal that borrows it silently rewrites a call that
                // actually happened.
                _closeOpenThinkingMarkup(_isBg);
                if (_isBg) continue;
                // `B904`. First drawn live by this row — the route dropped the
                // event before — and a refused call is still the model's
                // action, so the step is closed the way `tool_start` closes it:
                // the reply's own spinner kept saying "Waiting for the model"
                // above the refusal, with a second "Thinking" spinner below it.
                // The card goes where `tool_start` would put a card.
                _cancelThinkingTimer();
                _removeThinkingSpinner();
                if (isThinking) _endLiveThinkingSection({ rich: false });
                if (spinner && spinner.element) spinner.destroy();
                _finalizeRoundRender();
                const bThread = _cardThread();
                const bNode = document.createElement('div');
                applyAgentThreadNode(bNode, blockedCardOptions(json));
                bThread.appendChild(bNode);
                // Not the open card: a refusal is finished the moment it is
                // drawn, and leaving the pointer on it would hand the next
                // `tool_output` somebody else's node all over again.
                currentToolBubble = null;
                uiModule.scrollHistory();
              } else if (json.type === 'auto_escalated') {
                // `P4-18`. Silent in both directions until now: the promotion
                // itself, and the tools the promotion took away.
                if (_isBg) continue;
                holder._autoEscalated = json;
              } else if (json.type === 'verifier') {
                // `P4-17`. A second model with no shared history judged whether
                // the work actually matches the request. Its findings went into
                // the prompt and nowhere else, so the reader saw "Double-checked
                // the work and found something to fix" and never saw what.
                //
                // The card lands in the round's own thread, because that is
                // where the work it is judging is. There is always one: the
                // verifier only runs after effectful tool calls. The fallback
                // is a bare container rather than a copy of the thread-creation
                // logic above — the has-top / has-bottom connectors describe a
                // thread that continues into text, and a lone verdict does not.
                if (_isBg) continue;
                // `P4-24`: that rule is `_threadOrBare`, shared with a resumed stream.
                const vThread = _threadOrBare(lastToolThread, document.getElementById('chat-history'));
                lastToolThread = vThread;
                const vNode = document.createElement('div');
                applyAgentThreadNode(vNode, verifierCardOptions(json));
                vThread.appendChild(vNode);
                uiModule.scrollHistory();
              } else if (json.type === 'compacted') {
                if (!_isBg) {
                  // `P4-13`. The figures `_compacted_event` (`routes/chat_routes.py`)
                  // now carries, read out of `json.data` exactly as the
                  // `context_trimmed` branch directly below reads its own — one
                  // shape, one reader, because the two events describe the two
                  // halves of the same step and a renderer reading one nested
                  // and one flat is how two reports of one thing drift.
                  //
                  // Compaction is the irreversible half and it was the half with
                  // no numbers: the toast said older messages were summarized
                  // and there was no way to ask how many.
                  //
                  // The figures are absent when nothing measured them — the flag
                  // is set independently of them on purpose — so the sentence
                  // degrades to the one it has always shown rather than printing
                  // a `0/0` that would read as a measurement.
                  //
                  // `B921`: the sentence is `compactionNoticeText`'s, because an
                  // agent turn's compaction is saved with the reply now and the
                  // reload draws it as a line (`renderAgentNote`) in these words.
                  // The agent loop's own notice carries the figures too.
                  uiModule.showToast(compactionNoticeText(json));
                }
              } else if (json.type === 'context_trimmed') {
                if (!_isBg) {
                  const d = json.data || {};
                  const before = Number(d.messages_before || 0);
                  const after = Number(d.messages_after || 0);
                  const detail = before && after && before > after ? ` (${after}/${before} messages sent)` : '';
                  uiModule.showToast(`Context trimmed for this model${detail}`);
                }
              } else if (json.type === 'agent_terminal' || json.type === 'chat_terminal') {
                // The backend persisted canonical partial output, sanitized
                // failure metadata, and actual-route provenance before this
                // event. The terminal catch below reloads that exact record.
                _canonicalTerminalSaved = true;
                _terminalSavedStreams.add(streamSessionId);
                const priorMetrics = metrics;
                metrics = json.data || metrics;
                if (metrics && streamRunId) {
                  metrics._costRecordId = _metricsCostRecordId(streamRunId, json);
                }
                // Direct Chat may have emitted provider usage before its
                // terminal event. Carry that already-recorded state onto the
                // canonical terminal metadata instead of billing it twice.
                if (priorMetrics && priorMetrics._costRecorded && metrics) {
                  metrics._costRecorded = true;
                }
                if (_isBg) {
                  var bgTerminal = _backgroundStreams.get(streamSessionId);
                  if (bgTerminal) {
                    if (
                      bgTerminal.metrics
                      && bgTerminal.metrics._costRecorded
                      && metrics
                    ) {
                      metrics._costRecorded = true;
                    }
                    bgTerminal.metrics = metrics;
                    bgTerminal.status = 'completed';
                    if (metrics) {
                      chatRenderer.recordSessionMetricsCost(metrics, streamSessionId);
                    }
                  }
                  continue;
                }
                if (holder && metrics) {
                  applyModelMetricsState(metrics, holder, roundHolder, modelName);
                  const terminalMetricsTarget = _metricsTargetForTurn();
                  if (terminalMetricsTarget) displayMetrics(terminalMetricsTarget, metrics);
                }
              } else if (json.type === 'metrics') {
                metrics = json.data;
                if (metrics && streamRunId) {
                  metrics._costRecordId = _metricsCostRecordId(streamRunId, json);
                }
                if (!_isBg && holder && metrics) {
                  applyModelMetricsState(metrics, holder, roundHolder, modelName);
                }
                if (_isBg) {
                  var bgM = _backgroundStreams.get(streamSessionId);
                  if (bgM) {
                    bgM.metrics = json.data;
                    chatRenderer.recordSessionMetricsCost(bgM.metrics, streamSessionId);
                  }
                  continue;
                }
                if (metrics) {
                  const metricsTarget = _metricsTargetForTurn();
                  if (metricsTarget) displayMetrics(metricsTarget, metrics);
                  refreshChatContextHeader('metrics');
                }

              } else if (json.type === 'message_saved') {
                // Wire the persisted DB id onto the just-streamed bubble so it
                // can be edited/deleted immediately, without reloading the chat.
                if (_isBg) continue;
                if (holder && json.id) holder.dataset.dbId = json.id;
                // `B892`. The reply is stored now, and with it what its
                // request was spent on — the wheel reads that back.
                refreshChatContextHeader('saved');

              } else if (json.type === 'tool_start') {
                _closeOpenThinkingMarkup(_isBg);
                if (_isBg) continue;
                _cancelThinkingTimer();
                _removeThinkingSpinner();
                // Force-close thinking if still open — tools are real content, not thinking
                if (isThinking) {
                  _endLiveThinkingSection({ rich: false });
                }
                // --- Finalize current text bubble (only once per round) ---
                if (spinner && spinner.element) spinner.destroy();
                _finalizeRoundRender();

                // Track tool name for contextual spinner labels
                _lastToolName = json.tool || '';

                // Bind the tool to the plan step the agent is on (P6-11/P6-13).
                // No-op unless an approved plan has an unticked step and plan
                // mode is off — i.e. we are executing, not drafting.
                // `effect_label`/`effect_band` are the plan window's fifth
                // per-step field (P6-11), resolved server-side by P7-06. They
                // are forwarded rather than derived: the severity ordering and
                // the wording live in `src/tool_capabilities.py` and nowhere
                // else, so a value added to the taxonomy cannot render one way
                // here and another way on the approval card.
                planWindow.noteToolStart({
                  tool: json.tool,
                  command: json.command,
                  effect_label: json.effect_label,
                  effect_band: json.effect_band,
                });

                // --- Thread timeline: group tools in a thread container ---
                const threadWrap = _cardThread();   // `B904`: shared with `tool_blocked`
                // `P4-24`: the running card is drawn by the function a resumed
                // stream calls for the same event.
                currentToolBubble = _startToolCard(threadWrap, json);

              } else if (json.type === 'tool_progress') {
                // Long-running subprocess (bash, python) is still in
                // flight — refresh the running tool card with the
                // elapsed-time + tail of its stdout/stderr so the
                // user doesn't stare at a blind "Running…" spinner.
                if (_isBg) continue;
                if (!currentToolBubble) continue;
                _drawToolProgress(currentToolBubble, json);   // `P4-24`: shared with a resumed stream

              } else if (json.type === 'tool_output') {
                if (_isBg) continue;
                // Record the bound tool's verdict + first output line as the
                // active plan step's result (P6-11). Same no-op guard as
                // `noteToolStart`.
                planWindow.noteToolEnd({
                  tool: json.tool,
                  command: json.command,
                  exit_code: json.exit_code,
                  output: json.output,
                  effect_label: json.effect_label,
                  effect_band: json.effect_band,
                });
                // --- Update the current thread node ---
                if (currentToolBubble) {
                  // `P4-24`: the result, diff, todo list and screenshot are
                  // drawn by the function a resumed stream calls too.
                  _finishToolCard(currentToolBubble, json);
                  // Reset so thinking spinner between tools says "Thinking" not the old tool's label
                  _lastToolName = '';
                }
                // --- Render generated images inline ---
                if (json.image_url) {
                  _rememberGeneratedImage(json);
                  _appendGeneratedImageBubble(json);
                }
                // --- Reload sessions after manage_session tool (delete, rename, etc.) ---
                // Debounce so bulk deletes don't fire loadSessions per call
                if (json.tool === 'manage_session' && sessionModule) {
                  if (window._manageSessionTimer) clearTimeout(window._manageSessionTimer);
                  window._manageSessionTimer = setTimeout(() => sessionModule.loadSessions(), 1000);
                }
                // --- Live-refresh the calendar after manage_calendar (add/edit/delete) ---
                // so a new event shows without the user hard-refreshing. Debounced
                // so a batch of event creates only triggers one refetch.
                if (json.tool === 'manage_calendar') {
                  if (window._manageCalTimer) clearTimeout(window._manageCalTimer);
                  window._manageCalTimer = setTimeout(
                    () => window.dispatchEvent(new CustomEvent('calendar-refresh')), 600);
                }
                // --- Live-refresh Memories after manage_memory changes ---
                if (json.tool === 'manage_memory') {
                  if (window._manageMemoryTimer) clearTimeout(window._manageMemoryTimer);
                  window._manageMemoryTimer = setTimeout(
                    () => window.dispatchEvent(new CustomEvent('memory-refresh')), 600);
                }
                // --- Apply UI control actions embedded in tool_output ---
                if (json.ui_event) {
                  chatStream.handleUIControl(json);
                }
                // Native document tool calls can arrive as a completed
                // tool_output without the text-fence streaming path. Open the
                // document editor from the real doc metadata carried on the
                // tool result so "create a document" never leaves only a chat
                // link behind if the later doc_update event is missed.
                if (
                  documentModule
                  && json.doc_id
                  && ['create_document', 'update_document', 'edit_document'].includes(json.tool)
                ) {
                  documentModule.handleDocUpdate({
                    type: 'doc_update',
                    doc_id: json.doc_id,
                    title: json.document_title || '',
                    language: json.document_language || '',
                    version: json.document_version || 1,
                    content: json.document_content || '',
                  });
                }

                // `P4-20`. The card this result belongs to is finished, so the
                // pointer is released. It used to survive to the end of the
                // round, and any later event that had no card of its own —
                // a policy refusal, an approval request, both of which skip
                // `tool_start` — rewrote this one instead. `compare/stream.js`
                // has always cleared it here; the main path had not.
                currentToolBubble = null;
                // Schedule a thinking spinner between tool rounds (short delay so
                // agent_step in the same SSE chunk can cancel it before it shows)
                _scheduleThinkingSpinner();
                uiModule.scrollHistory();

              } else if (json.type === 'doc_stream_open') {
                if (_isBg) {
                  // Store for replay when user returns to this session
                  var bgDocOpen = _backgroundStreams.get(streamSessionId);
                  if (bgDocOpen) {
                    bgDocOpen._docTitle = json.title || '';
                    bgDocOpen._docLang = json.language || '';
                    bgDocOpen._docContent = '';
                  }
                  continue;
                }
                if (documentModule) {
                  documentModule.streamDocOpen(json.title || '', json.language || '');
                }

              } else if (json.type === 'doc_stream_delta') {
                if (_isBg) {
                  var bgDocDelta = _backgroundStreams.get(streamSessionId);
                  if (bgDocDelta) bgDocDelta._docContent = json.content || '';
                  continue;
                }
                if (documentModule) {
                  documentModule.streamDocDelta(json.content || '');
                }

              } else if (json.type === 'doc_update') {
                // doc_update means the server already saved the doc to DB.
                if (_isBg) continue;
                if (documentModule) {
                  documentModule.handleDocUpdate(json);
                }

              } else if (json.type === 'doc_suggestions') {
                if (_isBg) continue;
                if (documentModule && documentModule.handleDocSuggestions) {
                  documentModule.handleDocSuggestions(json);
                }

              } else if (json.type === 'ui_control') {
                if (_isBg) continue;
                chatStream.handleUIControl(json.data || {});

              } else if (json.type === 'stream_steerable') {
                // B14. This run's own answer to whether a steer can reach it,
                // first event on the stream. Same `_isBg` rule as
                // `steer_applied` below and for the same reason: the bar
                // belongs to the foreground composer, and a background run's
                // verdict would take down a bar that belongs to a different
                // run. `steerable` is at the top level, like `round` is.
                if (_isBg) continue;
                chatStream.handleStreamSteerable(json);

              } else if (json.type === 'steer_applied') {
                // P6-18. The steer bar lives in the foreground composer, so a
                // background session's confirmation has no bar to upgrade —
                // and routing it would set the "confirmations work here" flag
                // from a run the user is not watching. `stream_agent_loop`
                // emits `round`/`count`/`steers` at the top level, not under
                // `data`, so the event goes through whole.
                if (_isBg) continue;
                chatStream.handleSteerApplied(json);

              } else if (json.type === 'ask_user') {
                if (_isBg) continue;
                // The agent posed a multiple-choice question; the turn has ended.
                // Use the shared history renderer so the live and restored
                // versions have identical behavior.
                _cancelThinkingTimer();
                _removeThinkingSpinner();
                chatRenderer.renderAskUserCard(json.data || {});

              } else if (json.type === 'plan_update') {
                if (_isBg) continue;
                // Agent wrote back to the plan (ticked a step / revised). Storing
                // the plan repaints the docked window — `_setStoredPlan` delegates
                // to planWindow.js, which owns both. This comment used to claim a
                // live refresh that had never been built (P6-11).
                const _pu = (json.data && json.data.plan) ? json.data.plan : '';
                if (_pu) _setStoredPlan(_pu, _streamSessionId);

              } else if (json.type === 'agent_step') {
                _closeOpenThinkingMarkup(_isBg);
                if (_isBg) continue;
                _cancelThinkingTimer();
                _removeThinkingSpinner();
                if (isThinking) {
                  _endLiveThinkingSection({ rich: false });
                } else {
                  _cancelLiveThinkingWork();
                }
                _finalizeRoundRender();
                // Mark thread as connected to bubble below — the one directly
                // above it (`B919`), by the rule a resumed stream follows too.
                _threadIntoNextStep(document.getElementById('chat-history'));
                // --- New round: create fresh AI bubble with spinner ---
                currentToolBubble = null;
                roundFinalized = false;
                roundFinalization = null;
                isThinking = false;
                roundReplyText = null;
                _thinkingMode = null;
                _thinkingRecheckAt = 0;
                _thinkingAnalysisGate.reset();
                _roundDisplayProjector.reset();
                _replyDisplayProjector.reset();
                _docFenceOpened = false;
                const box = document.getElementById('chat-history');
                // `P4-24`: the bubble and its spinner are drawn by the
                // functions a resumed stream calls for the same event.
                const newWrap = _newRoundBubble(box, holder, roundHolder, streamSessionId, modelName);
                const newBody = newWrap.querySelector('.body');
                roundHolder = newWrap;
                roundText = '';
                // Destroy any previous spinner before creating new one
                if (spinner && spinner.element) spinner.destroy();
                // Show spinner while waiting for text (skip for research — has its own progress)
                if (!_researchingStreamIds.has(streamSessionId)) {
                  spinner = _openRoundSpinner(newBody, _meter);   // `P4-23`: it carries the meter
                }
                if (streamingTTS) window.aiTTSManager._streamSentencesSent = 0;
                uiModule.scrollHistory();
              } else if (json.type === 'budget_exceeded') {
                if (_isBg) continue;
                _cancelThinkingTimer();
                _removeThinkingSpinner();
                // `B915`: drawn by the builder a reload and a resumed stream use.
                renderAgentNote(document.getElementById('chat-history'), json);

              } else if (json.type === 'loop_breaker_triggered' || json.type === 'intent_nudge_exhausted') {
                if (_isBg) continue;
                _cancelThinkingTimer();
                _removeThinkingSpinner();
                // `P4-10`. Which tool, how many times, with what — or the
                // sentence it kept saying without acting — and what to do next.
                // The line goes into the chat history, never into the round's
                // bubble: the next `agent_step` hides a round that wrote
                // nothing (a loop-breaker round writes nothing, by definition)
                // along with whatever was inside it, and the end-of-stream
                // render replaces the body's markup — the same reason
                // `rounds_exhausted` above appends to the history. The old
                // bracketed line lived in the bubble, flashed, and was gone.
                if (renderAgentStop(document.getElementById('chat-history'), json)) {
                  uiModule.scrollHistory();
                }

              } else if (json.type === 'teacher_takeover') {
                _closeOpenThinkingMarkup(_isBg);
                if (_isBg) continue;
                _cancelThinkingTimer();
                _removeThinkingSpinner();
                // Finalize any in-flight bubble so the takeover banner
                // separates student attempt from teacher attempt.
                //
                // `B904`. This arm had never run: the route dropped the event,
                // so the teacher's run was drawn as more of the student's. It
                // used to end by setting `roundHolder = null`, which nothing
                // after it expects — the teacher's first token threw in
                // `_renderStream`, and its first tool call finalized the
                // *first* bubble with an empty round text and hid the student's
                // answer. The student's last step is finished where it is now,
                // and the teacher's run opens a bubble of its own below the
                // banner (end of this arm).
                if (isThinking) _endLiveThinkingSection({ rich: false });
                else _cancelLiveThinkingWork();
                _finalizeRoundRender();
                if (spinner && spinner.element) { try { spinner.destroy(); } catch(_){} spinner = null; }
                // `B915` / `B917`: the banner is drawn by the builder a reload
                // and a resumed stream use, as text — the student's failure
                // can quote a tool's output.
                renderAgentNote(document.getElementById('chat-history'), json);
                // The teacher's first text starts a new bubble, below the
                // banner, with a spinner of its own for the teacher's
                // preparation and meter to hang under. Its cards start a new
                // thread, not the student's (`_cardThread` stops at the banner).
                currentToolBubble = null;
                lastToolThread = null;
                const _teacherBody = _openRoundBubble();
                if (_teacherBody) {
                  // `B922`: headed with the teacher's model, not the student's.
                  _headWithTeacher(roundHolder, json);
                  // `B917`: the spinner a resumed takeover opens too — a
                  // step's, without the meter until the teacher's first frame.
                  spinner = _openRoundSpinner(_teacherBody, null);
                }
                uiModule.scrollHistory();

              } else if (json.type === 'skill_saved') {
                if (_isBg) continue;
                // `B915`: one builder for the live stream, a resumed one and a reload.
                renderAgentNote(document.getElementById('chat-history'), json);
                uiModule.scrollHistory();

              } else if (json.type === 'escalation_failed' || json.type === 'skill_save_failed') {
                if (_isBg) continue;
                renderAgentNote(document.getElementById('chat-history'), json);   // `B915`
                uiModule.scrollHistory();

              } else if (json.error) {
                // --- Backend error (timeout, connection issue, etc.) ---
                console.error('Stream error from backend:', json.error);
                if (_isBg) continue;
                if (spinner && spinner.element) spinner.destroy();
                const errDiv = document.createElement('div');
                errDiv.style.cssText = 'color: var(--color-error); font-style: italic; padding: 4px 0;';
                errDiv.textContent = `[Error: ${json.error}]`;
                roundHolder.querySelector('.body').appendChild(errDiv);
                uiModule.scrollHistory();
              }
            } catch (e) {
              console.error('Error parsing SSE data:', e);
            }
          }
        }
      }

      if (_streamTerminalError) {
        throw _streamTerminalError;
      }
      if (!_streamSawDone) {
        if (!_canonicalTerminalSaved) {
          throw new Error('Stream closed before completion');
        }
        // The backend persisted a canonical terminal record (partial output +
        // failure metadata) before the connection died. Route through the
        // terminal-error path so that record is reloaded; falling through to
        // the success renderer would present the partial output as a clean
        // completion.
        throw createTerminalStreamError({
          text: 'Stream closed after canonical terminal event',
        });
      }

      // The final foreground render below is authoritative. Cancel any delayed
      // live-view work instead of parsing and rendering the full round once
      // here and then immediately replacing it.
      _cancelLiveThinkingWork();
      if (spinner && spinner.element) { try { spinner.destroy(); } catch (_) {} spinner = null; }
      _cancelThinkingTimer();
      _removeThinkingSpinner();
      // Stop any thread pulse animations
      document.querySelectorAll('.agent-thread.streaming').forEach(t => t.classList.remove('streaming'));
      // --- Final render (skip if stream was ever backgrounded or currently in background) ---
      // Remove streaming class from all round bubbles
      holder.classList.remove('streaming');
      if (roundHolder && roundHolder !== holder) roundHolder.classList.remove('streaming');

      const _isBgFinal = (sessionModule.getCurrentSessionId() !== streamSessionId) || _backgroundStreams.has(streamSessionId);
      if (!_isBgFinal) {
        finalMeta = sessionModule.getSessions().find(s => s.id === sessionModule.getCurrentSessionId());
        const _finalModelHolder = applyModelMetricsState(
          metrics,
          holder,
          roundHolder,
          finalMeta?.model || modelName,
        ) || holder;
        const _finalActualModel = _finalModelHolder._actualModel || finalMeta?.model;
        const _finalRequestedModel = _finalModelHolder._requestedModel || finalMeta?.model || _finalActualModel;
        // Prepend character name if set
        var _charNameFinal = presetsModule.getCharacterName ? presetsModule.getCharacterName() : '';
        const roleEl = _finalModelHolder.querySelector('.role');
        if (roleEl) {
          _setRoleModelLabel(roleEl, _finalRequestedModel, _finalActualModel, {
            suffix: _finalModelHolder._roleSuffix,
            characterName: _charNameFinal || _finalModelHolder._characterName,
            requestedEndpointId: _finalModelHolder._requestedEndpointId,
            requestedEndpointLabel: _finalModelHolder._requestedEndpointLabel,
            actualEndpointId: _finalModelHolder._actualEndpointId,
            actualEndpointLabel: _finalModelHolder._actualEndpointLabel,
          });
        }
        holder.dataset.raw = accumulated;

        // Anti-stall: a turn that ran tools but ended with essentially no
        // final prose usually means the model stopped mid-task (the case
        // where you had to type "did you finish?"). Offer a one-click
        // Continue that resumes exactly where it left off — reuses the same
        // resume mechanism as the user-stop "[Message interrupted]" button.
        try {
          const _usedTools = holder.querySelector('.agent-thread-node');
          const _proseLen = (accumulated || '').replace(/<[^>]*>/g, '').trim().length;
          if (_usedTools && _proseLen < 24 && !holder.querySelector('.agent-continue-btn')) {
            const _stall = document.createElement('div');
            _stall.className = 'stopped-indicator';
            const _lbl = document.createElement('span');
            _lbl.style.cssText = 'font-style:italic;opacity:0.7;';
            _lbl.textContent = 'Paused mid-task';
            _stall.appendChild(_lbl);
            const _cont = document.createElement('button');
            _cont.className = 'continue-btn agent-continue-btn';
            _cont.title = 'Continue — pick up where it left off';
            _cont.textContent = '▸';
            _cont.addEventListener('click', () => {
              _stall.remove();
              const mi = uiModule.el('message');
              if (mi) {
                mi.value = 'Continue — you stopped before finishing. Pick up exactly where you left off and complete the task.';
                const sb = document.querySelector('.send-btn');
                if (sb) sb.click();
              }
            });
            _stall.appendChild(_cont);
            (holder.querySelector('.body') || holder).appendChild(_stall);
          }
        } catch (_) {}

        // Clear streaming minHeight lock
        const _streamContent = roundHolder.querySelector('.stream-content');
        if (_streamContent) _streamContent.style.minHeight = '';
        if (_docFenceOpened) {
          _finishDocumentWritingStatus(roundHolder, true);
          roundHolder.style.display = '';
        }

        // Finalize the last round's bubble — flatten stream-content wrapper for clean DOM
        const finalDisplay = _streamDisplayText(roundText, { final: _docFenceOpened });
        if (finalDisplay.trim()) {
          var _body4 = roundHolder.querySelector('.body');
          // Preserve sources expanded state before final render
          var _wasExpanded = _sourcesExpanded || !!(_body4 && _body4.querySelector('.sources-content.expanded'));

          // If thinking was collapsed in-place during streaming, preserve it
          var _liveReplyEl = _body4 && _body4.querySelector('.live-reply-content');
          var _extracted = _liveReplyEl ? markdownModule.extractThinkingBlocks(finalDisplay) : null;
          var _finalReply = '';
          if (_liveReplyEl) {
            // Try standard extraction first (for native <think> tags)
            if (_extracted?.thinkingBlocks?.length) {
              _finalReply = (_extracted.content || '').trim();
            } else {
              // Non-tag thinking: extract reply from raw text
              // Handle garbled thinking tag: "Thinking: reasoning\n<think>reply"
              const _garbledMatch = finalDisplay.match(/^[\s\S]+?<(?:think(?:ing)?|thought)(?:\s+[^>]*)?>\s*([\s\S]*?)(?:<\/(?:think(?:ing)?|thought)>)?\s*$/i);
              if (_garbledMatch && _garbledMatch[1].trim()) {
                _finalReply = _garbledMatch[1].trim();
              } else {
                // Pure non-tag: find reply boundary by prefix patterns
                const _rs2 = ['Hey', 'Hi ', 'Hi!', 'Hello', 'Sure', 'Yes', 'No ', 'No,', 'Yo', 'OK', 'Here', 'Absolutely', 'Of course', 'Great', 'Alright', 'Thanks', 'Welcome', 'Good ', "I'm happy", "I'd be"];
                const _fr = (finalDisplay || '').trimStart();
                if (markdownModule.startsWithReasoningPrefix(_fr)) {
                  const _fLines = _fr.split('\n');
                  for (let _fi = 1; _fi < _fLines.length; _fi++) {
                    const _fl = _fLines[_fi].trim();
                    if (!_fl) continue;
                    if (_rs2.some(rp => _fl.startsWith(rp))) { _finalReply = _fLines.slice(_fi).join('\n'); break; }
                  }
                  // Within-line check
                  if (!_finalReply) {
                    for (const rp of _rs2) {
                      const rx = new RegExp('[.!?]\\s*(' + rp.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')');
                      const m = rx.exec(_fr);
                      if (m && m.index > 20) { _finalReply = _fr.slice(m.index + 1).trim(); break; }
                    }
                  }
                }
              }
            }
          }
          if (_liveReplyEl && _finalReply) {
            // Render reply into the live-reply container (thinking bar already showing)
            var _replyHtml = markdownModule.mdToHtml(markdownModule.squashOutsideCode(_finalReply));
            _liveReplyEl.innerHTML = _replyHtml;
            _liveReplyEl.classList.remove('live-reply-content');
            if (_sourcesData) {
              var _srcEl = document.createElement('div');
              _srcEl.innerHTML = _buildSourcesBox(_sourcesData, _sourcesType, _wasExpanded);
              _body4.insertBefore(_srcEl.firstChild || _srcEl, _body4.firstChild);
            }
            if (_findingsData) _body4.insertAdjacentHTML('beforeend', chatRenderer.buildFindingsBox(_findingsData));
          } else {
            // Full re-render (reply empty or no live-reply container)
            _body4.innerHTML = (_sourcesData ? _buildSourcesBox(_sourcesData, _sourcesType, _wasExpanded) : '')
              + markdownModule.processWithThinking(markdownModule.squashOutsideCode(finalDisplay))
              + (_findingsData ? chatRenderer.buildFindingsBox(_findingsData) : '');
          }
        } else if (_sourcesHtml) {
          var _body4b = roundHolder.querySelector('.body');
          var _wasExpanded2 = _sourcesExpanded || !!(_body4b && _body4b.querySelector('.sources-content.expanded'));
          _body4b.innerHTML = _sourcesData ? _buildSourcesBox(_sourcesData, _sourcesType, _wasExpanded2) : _sourcesHtml;
        } else if (roundHolder !== holder) {
          // Check if there's thinking content worth showing
          const _thinkingOnly = markdownModule.extractThinkingBlocks(_streamDisplayText(roundText));
          if (_thinkingOnly.thinkingBlocks?.length && !_thinkingOnly.content) {
            // Show thinking in a collapsed section even if no visible reply text
            const _body4c = roundHolder.querySelector('.body');
            if (_body4c) _body4c.innerHTML = markdownModule.processWithThinking(_streamDisplayText(roundText));
          } else {
            roundHolder.style.display = 'none';
            // Thread above expected a bubble below — remove has-bottom since bubble is hidden
            const _lastThread = roundHolder.previousElementSibling;
            if (_lastThread && _lastThread.classList.contains('agent-thread')) {
              _lastThread.classList.remove('has-bottom');
            }
          }
        }


        if (window.hljs) {
          roundHolder.querySelectorAll('pre code').forEach((block) => {
            window.hljs.highlightElement(block);
          });
        }
        if (markdownModule.renderMermaid) markdownModule.renderMermaid(roundHolder);

        uiModule.scrollHistory();
        // Render RAG sources if present
        if (holder._ragSources && holder._ragSources.length) {
          const details = document.createElement('details');
          details.className = 'rag-sources';
          const summary = document.createElement('summary');
          summary.textContent = `Sources (${holder._ragSources.length} documents)`;
          details.appendChild(summary);
          holder._ragSources.forEach(src => {
            const item = document.createElement('div');
            item.className = 'rag-source-item';
            const _esc = uiModule.esc;
            item.innerHTML = `<strong>${_esc(src.filename)}</strong> <span class="rag-similarity">${(src.similarity * 100).toFixed(1)}%</span><div class="rag-snippet">${_esc(src.snippet)}</div>`;
            details.appendChild(item);
          });
          holder.querySelector('.body').appendChild(details);
        }

        // Hide first bubble if it has no visible text content (e.g. agent went straight to tools)
        if (holder !== roundHolder && holder.style.display !== 'none') {
          const _hBody = holder.querySelector('.body');
          const _hText = _hBody ? _hBody.textContent.trim() : '';
          if (!_hText) holder.style.display = 'none';
        }

        // Attach footer to the last visible bubble (roundHolder for multi-round agent, holder for single),
        // with the turn's pills handed to it (`B920`).
        const footerTarget = _withTurnPills(
          (roundHolder && roundHolder !== holder && roundHolder.style.display !== 'none') ? roundHolder : holder,
          holder);
        if (!footerTarget.querySelector('.msg-footer')) {
          footerTarget.appendChild(createMsgFooter(footerTarget));
        }
        if (_generatedImagesForTurn.length && !_isBg) {
          _generatedImagesForTurn.forEach(imgData => _appendGeneratedImageBubble(imgData));
        }
        // Add "View Report" link for completed research
        if (_researchingStreamIds.has(streamSessionId)) {
          _appendViewReportLink(footerTarget, streamSessionId);
        }
        // Also store raw on the footer target so copy/TTS work
	        if (footerTarget !== holder) footerTarget.dataset.raw = accumulated;
		        try {
		          const _endToggles = Storage.loadToggleState();
		          if (_endToggles.plan_mode && accumulated) {
		            _setStoredPlan(accumulated, streamSessionId);
		            _attachPlanActions(footerTarget, accumulated);
		          }
		        } catch (_) {}
	        if (addAITTSButton && accumulated && window.aiTTSManager?._provider !== 'disabled' && window.aiTTSManager?.available) {
	          addAITTSButton(footerTarget, accumulated);
	        }
        // TTS auto-play: streaming mode flushes remaining text, non-streaming enqueues full message
        if (accumulated && window.aiTTSManager && window.aiTTSManager.autoPlay) {
          const ttsBtn = holder.querySelector('.ai-tts-button');
          if (ttsBtn) {
            var ICON_PLAY_TTS = playIcon({ size: 14 });
            var ICON_STOP_TTS = stopIcon({ size: 14 });
            const resetFn = () => {
              ttsBtn.innerHTML = ICON_PLAY_TTS;
              ttsBtn.classList.remove('playing', 'loading');
              ttsBtn.style.color = '#6b7280';
              ttsBtn.title = 'Read aloud';
            };
            if (streamingTTS) {
              // Flush remaining partial sentence and attach the real button
              window.aiTTSManager.streamingEnd(accumulated);
              window.aiTTSManager.streamingAttachButton(ttsBtn, resetFn);
              // If still playing sentences from the stream, show stop icon
              if (window.aiTTSManager.isPlaying || window.aiTTSManager._processing) {
                ttsBtn.innerHTML = ICON_STOP_TTS;
                ttsBtn.classList.add('playing');
                ttsBtn.style.color = '#ccc';
                ttsBtn.title = 'Stop';
              }
            } else {
              // Non-streaming fallback (autoPlay toggled mid-stream, etc.)
              window.aiTTSManager.enqueue(accumulated, ttsBtn, resetFn);
            }
          }
        }
        if (metrics) {
          displayMetrics(_metricsTargetForTurn() || footerTarget, metrics);
        }
        // Attach variant navigation if this was a regeneration
        _attachVariantNav(footerTarget);

        // Merge with previous stopped message if this was a continue
        if (_pendingContinue && _pendingContinueSteps) {
          // `B941`. Continue ▸ after the step limit: the run's steps go on
          // where they are drawn, as one reply with the steps above them.
          const prevEl = _pendingContinue;
          _pendingContinue = null;
          _pendingContinueSteps = false;
          _joinContinuedSteps(prevEl, holder);
          const sid = sessionModule.getCurrentSessionId();
          if (sid) {
            fetch(`${API_BASE}/api/session/${sid}/merge-last-assistant`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ separator: '\n\n' })
            }).catch(e => console.warn('merge-last-assistant failed:', e));
          }
        } else if (_pendingContinue) {
          const prevEl = _pendingContinue;
          _pendingContinue = null;
          const prevBody = prevEl.querySelector('.body');
          const newBody = footerTarget.querySelector('.body');
          if (prevBody && newBody && prevEl.parentNode) {
            // Merge: combine raw text with *(continued)* marker
            const oldRaw = prevEl.dataset.raw || '';
            const newRaw = footerTarget.dataset.raw || '';
            const mergedRaw = oldRaw + '\n\n*(continued)*\n\n' + newRaw;
            prevEl.dataset.raw = mergedRaw;
            // Re-render merged content
            prevBody.innerHTML = markdownModule.processWithThinking(
              markdownModule.squashOutsideCode(mergedRaw)
            );
            // Remove the new bubble and re-add footer to the merged one
            footerTarget.remove();
            const oldFooter = prevEl.querySelector('.msg-footer');
            if (oldFooter) oldFooter.remove();
            prevEl.appendChild(createMsgFooter(prevEl));
            if (window.hljs) {
              prevEl.querySelectorAll('pre code').forEach(block => window.hljs.highlightElement(block));
            }

            // Persist merge to server
            const sid = sessionModule.getCurrentSessionId();
            if (sid) {
              fetch(`${API_BASE}/api/session/${sid}/merge-last-assistant`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ separator: '\n\n*(continued)*\n\n' })
              }).catch(e => console.warn('merge-last-assistant failed:', e));
            }
          }
        }
      } // end if (!_isBgFinal)

    } catch (err) {
      // If a Stop or timeout was waiting for an identity header and the POST
      // failed before producing one, keep this on the cancellation path. There
      // is no safe headerless server cancel to send, but it must not be turned
      // into an automatic recovery attempt either. Only this send's own
      // queued Stop counts; a replacement's queued Stop is not ours to spend.
      const _pendingCatchKey = streamSessionId + ':' + streamGeneration;
      if (
        _pendingRunStops.has(_pendingCatchKey)
        && abortCtrl
        && !abortCtrl.signal.aborted
      ) {
        _pendingRunStops.delete(_pendingCatchKey);
        abortCtrl._reason = 'user-stop';
        abortCtrl.abort();
      }
      // Check if this stream was running in background — needed before any
      // stop-state write, so an errored background stream can't clobber the
      // foreground session's text.
      const _isBgCatch = (sessionModule.getCurrentSessionId() !== streamSessionId) || _backgroundStreams.has(streamSessionId);
      let _catchTerminalView = null;
      _closeOpenThinkingMarkup(_isBgCatch);
      if (_isBgCatch) {
        _cancelLiveThinkingWork();

        // A canonical terminal event may have been persisted immediately
        // before the stream moved into the background. Preserve that terminal
        // state instead of allowing the catch path to turn it back into a
        // running/error stream.
        const bgTerminal = _backgroundStreams.get(streamSessionId);
        if (bgTerminal && _terminalSavedStreams.has(streamSessionId)) {
          bgTerminal.status = 'completed';
          if (sessionModule && sessionModule.clearStreaming) {
            sessionModule.clearStreaming(streamSessionId);
          }
        }
      } else if (accumulated) {
        _catchTerminalView = _finalizeInterruptedView();
      } else {
        // Empty terminal views are owned by _renderCancelledBubble; do not run
        // the rich round renderer first because it hides an empty holder.
        _endThinkingOnTerminalPath({ rich: false });
      }
      const _catchViewHolder = _catchTerminalView?.holder || holder;
      // Clean up any active spinner (e.g. "Generating response" during tool calls)
      if (spinner && spinner.element) spinner.destroy();
      _cancelThinkingTimer();
      _removeThinkingSpinner();
      document.querySelectorAll('.agent-thread.streaming').forEach(t => t.classList.remove('streaming'));

      if (_isBgCatch) {
        // Error happened while backgrounded — update map, don't touch DOM
        console.error('Background stream error:', err);
        var bgErr = _backgroundStreams.get(streamSessionId);
        if (bgErr && (
          bgErr.status === 'completed' || _terminalSavedStreams.has(streamSessionId)
        )) {
          bgErr.status = 'completed';
          // [DONE] was already processed — this error is benign (e.g. reader.read() after close)
          // Don't override the completed status; just ensure the completed dot stays
          if (sessionModule && sessionModule.clearStreaming) {
            sessionModule.clearStreaming(streamSessionId);
          }
        } else if (bgErr) {
          bgErr.status = 'error';
          if (sessionModule && sessionModule.clearStreaming) {
            sessionModule.clearStreaming(streamSessionId);
          }
        }
      } else {
        // Stop streaming TTS on any error/abort
        if (streamingTTS && window.aiTTSManager) window.aiTTSManager.stop();

        if (abortCtrl && abortCtrl.signal.aborted) {
          const abortReason = abortCtrl._reason || '';
          // Timeout-triggered aborts should remain visible instead of disappearing.
          if (timedOut || abortReason === 'timeout') {
            const timeoutMsg = _isAgent
              ? 'Agent response timed out. Try again, switch to a faster model, or reduce tool usage.'
              : 'Response timed out. Try again.';

            if (holder && !accumulated) {
              holder.querySelector('.body').innerHTML =
                `<div style="color: var(--color-error); font-style: italic; padding: 4px 0;">[${timeoutMsg}]</div>`;
            } else if (_catchViewHolder && accumulated) {
              const timeoutNote = document.createElement('div');
              timeoutNote.className = 'stopped-indicator';
              timeoutNote.innerHTML =
                `<span style="color: var(--color-error);">[${timeoutMsg}]</span>`;
              _catchViewHolder.querySelector('.body').appendChild(timeoutNote);
            }
            if (currentAbort === abortCtrl) currentAbort = null;
            return;
          }

          if (abortReason === 'offline') {
            const offlineMsg = 'Endpoint offline — switch model or try again.';
            if (holder && !accumulated) {
              holder.querySelector('.body').innerHTML =
                `<div style="color: var(--color-error); font-style: italic; padding: 4px 0;">[${offlineMsg}]</div>`;
            } else if (_catchViewHolder && accumulated) {
              const offlineNote = document.createElement('div');
              offlineNote.className = 'stopped-indicator';
              offlineNote.innerHTML =
                `<span style="color: var(--color-error);">[${offlineMsg}]</span>`;
              _catchViewHolder.querySelector('.body').appendChild(offlineNote);
            }
            if (currentAbort === abortCtrl) currentAbort = null;
            return;
          }

          if (abortReason === 'recovery') {
            const recoveryMsg = 'Streaming was interrupted after the tab went inactive. Partial output was preserved.';
            if (holder && !accumulated) {
              holder.querySelector('.body').innerHTML =
                `<div style="color: var(--color-error); font-style: italic; padding: 4px 0;">[${recoveryMsg}]</div>`;
            } else if (_catchViewHolder && accumulated) {
              const recoveryNote = document.createElement('div');
              recoveryNote.className = 'stopped-indicator';
              recoveryNote.innerHTML =
                `<span style="color: var(--color-error);">[${recoveryMsg}]</span>`;
              _catchViewHolder.querySelector('.body').appendChild(recoveryNote);
            }
            if (currentAbort === abortCtrl) currentAbort = null;
            return;
          }

          if (abortReason === 'stale-local') {
            const staleMsg = 'Stream connection ended. Composer unlocked; send again if needed.';
            if (holder && !accumulated) {
              holder.querySelector('.body').innerHTML =
                `<div style="opacity:0.7;font-style:italic;padding:4px 0;">[${staleMsg}]</div>`;
            } else if (_catchViewHolder && accumulated) {
              const staleNote = document.createElement('div');
              staleNote.className = 'stopped-indicator';
              staleNote.innerHTML = `<span style="opacity:0.7;">[${staleMsg}]</span>`;
              _catchViewHolder.querySelector('.body').appendChild(staleNote);
            }
            if (currentAbort === abortCtrl) currentAbort = null;
            return;
          }

          // User-initiated stop (or browser navigation abort).
          // Stopped before any text arrived — keep the bubble as a
          // "Cancelled by user" record (so it survives a refresh).
          if (holder && !accumulated) {
            _renderCancelledBubble(holder);
          }

          // Navigation and non-button aborts do not pass through the synchronous
          // Stop renderer. The catch render above owns markdown; add only the
          // interruption controls here so each terminal path renders once.
          if (_catchViewHolder && accumulated && currentHolder) {
            _catchViewHolder.dataset.raw = accumulated;
            const stoppedIndicator = document.createElement('div');
            stoppedIndicator.className = 'stopped-indicator';
            const stoppedLabel = document.createElement('span');
            stoppedLabel.textContent = '[Message interrupted]';
            stoppedIndicator.appendChild(stoppedLabel);
            const continueBtn = document.createElement('button');
            continueBtn.className = 'continue-btn';
            continueBtn.title = 'Continue';
            continueBtn.textContent = '\u25B8';
            continueBtn.addEventListener('click', () => {
              stoppedIndicator.remove();
              _hideUserBubble = true;
              _pendingContinue = _catchViewHolder;
              _pendingContinueSteps = false;   // `B941`: a stopped reply's text
              const cutoff = accumulated;
              const msgInput = uiModule.el('message');
              if (msgInput) {
                msgInput.value = 'Your previous response was interrupted. It ended with:\n\n' + cutoff.slice(-500) + '\n\nDo NOT repeat what you already said. Continue exactly from where you were cut off.';
                const sb = document.querySelector('.send-btn');
                if (sb) sb.click();
              }
            });
            stoppedIndicator.appendChild(continueBtn);
            _catchViewHolder.querySelector('.body').appendChild(stoppedIndicator);

            // Tell server to mark this message as stopped
            const _sid2 = sessionModule.getCurrentSessionId();
            if (_sid2) fetch(`${API_BASE}/api/session/${_sid2}/mark-stopped`, { method: 'POST' }).catch(e => console.warn('mark-stopped failed:', e));

            if (!_catchViewHolder.querySelector('.msg-footer')) {
              // `B920`: as at the end of a stream, the pills go where the footer does.
              _catchViewHolder.appendChild(createMsgFooter(_withTurnPills(_catchViewHolder, holder)));
            }

            uiModule.scrollHistory();
          }

          // Now clear the abort controller
          if (currentAbort === abortCtrl) currentAbort = null;
        } else {
          console.error(err);
          // Stream died with a tool node still spinning. Its per-node tickers
          // (_elapsedTicker 50ms / _waveInterval 100ms) are normally cleared in
          // `tool_output`, which will never arrive now — without this sweep they
          // fire forever on the orphaned node (and auto-recover compounds it per
          // nudge). Safe here: auto-recover's new send is deferred 200ms, so no
          // fresh running nodes exist yet.
          document.querySelectorAll('.agent-thread-node.running').forEach(node => {
            if (node._waveInterval) { clearInterval(node._waveInterval); node._waveInterval = null; }
            if (node._elapsedTicker) { clearInterval(node._elapsedTicker); node._elapsedTicker = null; }
            node.classList.remove('running');
          });
          // Stream died unexpectedly — the "silently died" case. Re-engage the
          // model immediately (no wait) with a completion handshake, up to the
          // cap. Only auto-recover from connection-class failures; deterministic
          // errors (unsupported tools, 4xx/5xx, parse failures) surface right away
          // instead of burning the nudge budget on a guaranteed-to-fail retry.
          if (!(isRecoverableStreamError(err) && _tryAutoRecover(_catchViewHolder, accumulated, streamSessionId))) {
            if (err.terminalStreamError) {
              if (_canonicalTerminalSaved || accumulated.trim()) {
                // Let this stream's finally block clear foreground state before
                // reselecting; otherwise selectSession would detach the already
                // terminal reader and leave a stale background-stream marker.
                setTimeout(async () => {
                  if (sessionModule.getCurrentSessionId() === streamSessionId) {
                    await sessionModule.selectSession(streamSessionId, { showLoading: false });
                  } else {
                    await sessionModule.loadSessions();
                  }
                }, 0);
              } else {
                const terminalBody =
                  _catchViewHolder?.querySelector('.body')
                  || roundHolder?.querySelector('.body')
                  || document.querySelector('.msg-ai:last-of-type .body');
                if (terminalBody) {
                  const terminalNote = document.createElement('div');
                  terminalNote.style.cssText = 'color: var(--color-error); font-style: italic; padding: 4px 0;';
                  terminalNote.textContent = `[Error: ${err.message}]`;
                  terminalBody.appendChild(terminalNote);
                }
              }
              return;
            }
            const errorHolder =
              _catchViewHolder?.querySelector('.body')
              || document.querySelector('.msg-ai:last-of-type .body');
            if (errorHolder) {
              let errMsg = `Error: ${err.message}`;
              // Add hint for tool-call errors
              if (err.message && (err.message.includes('tool') || err.message.includes('auto'))) {
                errMsg += '\n\nThis model may not support tools — try switching to Chat mode.';
              }
              typewriterInto(errorHolder, errMsg);
            }
          }
        }
      }
    } finally {
      _cancelLiveThinkingWork();
      clearResponseTimeout();
      clearProcessingProbe();
      clearFirstTokenWaitTimers();
      // A replacement send bumps the session's generation the moment it
      // starts, before it registers or reaches the server, so cleanup rights
      // are decided by generation: a superseded send may remove only what it
      // itself owns (its stream registration by controller identity, its own
      // generation's queued Stop) and must leave session-level state — the
      // reader session id, research marker, UI — to the replacement.
      const _ownsStreamState =
        _streamGenerations.get(streamSessionId) === streamGeneration;
      const _finallyRegistered = _activeStreams.get(streamSessionId);
      if (!_finallyRegistered || _finallyRegistered.abortCtrl === abortCtrl) {
        _activeStreams.delete(streamSessionId);
      }
      _pendingRunStops.delete(streamSessionId + ':' + streamGeneration);
      if (_ownsStreamState) {
        if (_streamSessionId === streamSessionId) _streamSessionId = null;
        if (_sendStates.get(streamSessionId) === _sendState) {
          _sendStates.delete(streamSessionId);
        }
        // Superseded sends must not resync: with the replacement not yet
        // registered, a stale sync would set isStreaming false and drop
        // currentAbort while _sendInFlight is already false, reopening the
        // send gate mid-preflight. The replacement syncs when it registers
        // or finishes.
        _syncForegroundStreamGlobals();
      }
      // Streaming done — let screen readers announce the settled response.
      if (_ownsStreamState) {
        const _chatLogDone = document.getElementById('chat-history');
        if (_chatLogDone) _chatLogDone.setAttribute('aria-busy', 'false');
      }
      // Research markers gate /api/research/cancel in the Stop handler, so a
      // superseded send must not strip a replacement research run's marker.
      if (_ownsStreamState) _researchingStreamIds.delete(streamSessionId);
      if (_researchingStreamIds.size === 0) {
        var _rToggleCleanup = document.getElementById('research-toggle-btn');
        if (_rToggleCleanup) _rToggleCleanup.classList.remove('research-running');
      }

      // Only reset UI state if still on the stream's session, never
      // backgrounded, and no replacement stream owns the session now — the
      // replacement disabled the composer for its own send, so re-enabling
      // it here would hand input back mid-stream.
      const _isBgFinally = (sessionModule.getCurrentSessionId() !== streamSessionId) || _backgroundStreams.has(streamSessionId);
      if (_ownsStreamState) _terminalSavedStreams.delete(streamSessionId);

      if (!_isBgFinally && _ownsStreamState) {
        // Reset button to idle state
        updateSubmitButton('idle', submitBtn);

        // Re-enable message input; on mobile blur to dismiss keyboard
        if (messageInput) {
          messageInput.disabled = false;
          if (window.innerWidth <= 768) {
            messageInput.blur();
          } else {
            messageInput.focus();
          }
        }

        // Clear tracking variables
        currentAccumulated = '';
        currentHolder = null;
        currentSpinner = null;
        _researchingStreamIds.delete(streamSessionId);
        // Clear research-running highlight if no more active research
        if (_researchingStreamIds.size === 0) {
          var _rToggle2 = document.getElementById('research-toggle-btn');
          if (_rToggle2) _rToggle2.classList.remove('research-running');
        }
        _clearResearchTimer();

        // Re-enable research button and auto-untoggle after use
        // (skip if clarification round — keep toggle on for follow-up)
        const _el = uiModule.el;
        const _researchBtn = _el('research-toggle-btn');
        const _researchToggle = _el('research-toggle');
        if (_researchToggle && _researchToggle.checked) {
          _researchToggle.checked = false;
          Storage.setToggle('research', false);
        }
        if (_researchBtn) {
          _researchBtn.disabled = false;
          _researchBtn.classList.remove('active');
          _researchBtn.style.display = 'none';
        }
        // Also sync overflow and tool sidebar buttons
        const _overflowRes = _el('overflow-research-btn');
        if (_overflowRes) _overflowRes.classList.remove('active');
        const _toolRes = _el('tool-research-btn');
        if (_toolRes) _toolRes.classList.remove('active');

      }

      // Research clarification timeout — if user doesn't reply within 5 min, show timeout
      if (holder && holder._roleSuffix === 'Research' && !_researchingStreamIds.has(streamSessionId)) {
        var _timeoutSessionId = streamSessionId;
        var _timeoutTimer = setTimeout(async function() {
          // Check if research_pending is still active (user hasn't replied)
          try {
            var _box = document.getElementById('chat-history');
            if (_box && sessionModule.getCurrentSessionId() === _timeoutSessionId) {
              var _timeoutMsg = document.createElement('div');
              _timeoutMsg.className = 'msg msg-ai';
              _timeoutMsg.innerHTML = '<div class="role">Pantheon</div><div class="body" style="opacity:0.6;font-style:italic;">Research clarification timed out. Toggle research again to start over.</div>';
              _box.appendChild(_timeoutMsg);
              uiModule.scrollHistory();
            }
          } catch(_te) {}
        }, 5 * 60 * 1000);
        // Cancel timeout if user sends a message
        var _origSubmit = window._researchTimeoutTimer;
        if (_origSubmit) clearTimeout(_origSubmit);
        window._researchTimeoutTimer = _timeoutTimer;
      }

      // Release Web Lock
      if (_webLockRelease) {
        _webLockRelease();
        _webLockRelease = null;
      }

      // Refresh session list after a delay (picks up auto-generated names)
      setTimeout(() => {
        if (sessionModule && sessionModule.loadSessions) {
          sessionModule.loadSessions();
        }
      }, 3000);
      // Name the session whose stream just ended: the drain fires only items
      // queued from it, never whichever chat happens to be open now (P6-01).
      _drainQueuedAgentRequests(streamSessionId);
    }
  }

  /**
   * Abort current chat request
   */
  // stopServer=true ONLY for an explicit user Stop. The run is now DETACHED
  // (survives tab close / navigation), so the generic abort used by cleanup
  // paths (session switch, delete, reader teardown on tab close) must NOT stop
  // the server run — otherwise closing the tab would kill the background task,
  // defeating the whole point. Only the Stop button cancels the server run.
  export function abortCurrentRequest(stopServer = false) {
    const _sid = (sessionModule && sessionModule.getCurrentSessionId && sessionModule.getCurrentSessionId())
      || _streamSessionId
      || (window.sessionModule && window.sessionModule.getCurrentSessionId && window.sessionModule.getCurrentSessionId());
    // The CURRENT send's controller comes from its send state, installed at
    // send commit — never borrowed from the stream registry, which during the
    // replacement's preflight still holds the superseded send's entry.
    // Aborting that older controller here would sever the only identity
    // channel able to name the old run. A send committed but pre-POST has a
    // null controller: the Stop queues and there is nothing to abort yet.
    const _sendStateNow = _sid ? _sendStates.get(_sid) : null;
    const active = _getForegroundStreamState();
    const abortCtrl = _sendStateNow
      ? _sendStateNow.abortCtrl
      : (active ? active.abortCtrl : currentAbort);
    let abortNow = true;
    if (stopServer) {
      try {
        if (_sid) {
          // Before response headers arrive there is no safe server-side stop
          // identity yet. Keep the POST alive just long enough to receive that
          // opaque id, then _rememberStreamRunId sends the exact Stop and aborts
          // this reader. Never fall back to a headerless session-wide cancel.
          abortNow = _stopExactRun(_sid, abortCtrl);
        }
      } catch (_) {}
    }
    if (abortCtrl && abortNow) {
      abortCtrl.abort();
      // Don't set to null here - let catch block handle it
    }
  }

  // ── Stall watchdog ──────────────────────────────────────────────
  // Auto-recover a turn whose browser stream died by reconnecting to the exact
  // detached server run. Returns false at the cap so the caller can surface
  // the failure instead of retrying forever.
  // Only auto-recover from connection-class failures (the genuine "silently
  // died" case). Deterministic errors — unsupported tools, HTTP 4xx/5xx, JSON
  // parse failures — will fail identically on retry, so surfacing them
  // immediately is both more honest and avoids wasting the nudge budget.
  function _tryAutoRecover(holder, accumulated, sessionId) {
    if (_autoNudges >= _AUTO_NUDGE_CAP) return false;
    _autoNudges++;
    if (holder && accumulated) {
      holder.dataset.raw = accumulated;
    }
    // The server run is detached and keeps its exact pinned model/tool state.
    // Reconnect to that run instead of submitting a new user turn, which would
    // cancel it, retry the selected model, and risk duplicating side effects.
    setTimeout(async () => {
      // The stream that died may not be the chat the user is now looking at —
      // never attach the recovery reader to the wrong conversation.
      if (sessionId && sessionModule.getCurrentSessionId() !== sessionId) return;
      const resumed = await resumeStream(sessionId, holder || null);
      if (!resumed && holder && holder.isConnected) {
        const body = holder.querySelector('.body');
        if (body) typewriterInto(body, 'Connection lost. The existing run could not be resumed.');
      }
    }, 200);
    return true;
  }

  function _removeStallBanner() {
    const b = document.getElementById('stall-banner');
    if (b) b.remove();
    _stallBannerShown = false;
  }
  function _showStallBanner(secs) {
    if (document.getElementById('stall-banner')) return;
    _stallBannerShown = true;
    const box = document.getElementById('chat-history');
    if (!box) return;
    const bar = document.createElement('div');
    bar.id = 'stall-banner';
    bar.className = 'stall-banner';
    const mins = Math.floor(secs / 60);
    const label = mins >= 1 ? `${mins}m` : `${secs}s`;
    bar.innerHTML = `<span class="stall-banner-txt">Quiet for ${label} — still working?</span>`;
    const cont = document.createElement('button');
    cont.className = 'stall-banner-btn';
    cont.textContent = 'Nudge it';
    cont.title = 'Stop the stalled stream and ask it to continue';
    cont.addEventListener('click', () => {
      _removeStallBanner();
      const mi = uiModule.el('message');
      if (mi) {
        mi.value = 'Are you still working? If you stopped, continue exactly where you left off and finish the task.';
        const sb = document.querySelector('.send-btn');
        if (sb) sb.click();
      }
    });
    const stop = document.createElement('button');
    stop.className = 'stall-banner-btn stall-banner-stop';
    stop.textContent = 'Stop';
    stop.addEventListener('click', () => { _removeStallBanner(); abortCurrentRequest(true); });
    bar.appendChild(cont);
    bar.appendChild(stop);
    box.appendChild(bar);
    if (uiModule.scrollHistory) uiModule.scrollHistory();
  }
  async function _probeStaleLocalStream() {
    const active = _getForegroundStreamState();
    if (!active || _staleStreamProbeInFlight) return;
    if (Date.now() - (active.lastActivity || _lastReaderActivity) < STALE_LOCAL_STREAM_MS) return;
    const sid = sessionModule.getCurrentSessionId && sessionModule.getCurrentSessionId();
    if (!sid) return;
    if (_backgroundStreams.has(sid) || (sessionModule.getCurrentSessionId && sessionModule.getCurrentSessionId() !== sid)) return;
    _staleStreamProbeInFlight = true;
    try {
      const res = await fetch(`${API_BASE}/api/chat/stream_status/${encodeURIComponent(sid)}`, {
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (!_getForegroundStreamState() || _backgroundStreams.has(sid)) return;
      if (res.status !== 404) return;

      console.warn('[stream-watchdog] Local stream was stale and server has no active stream. Unlocking composer.');
      if (active.abortCtrl && !active.abortCtrl.signal.aborted) {
        active.abortCtrl._reason = 'stale-local';
        active.abortCtrl.abort();
      }
      _activeStreams.delete(sid);
      _syncForegroundStreamGlobals();
      _sendInFlight = false;
      if (_webLockRelease) {
        _webLockRelease();
        _webLockRelease = null;
      }
      const submitBtn = document.querySelector('.send-btn');
      if (submitBtn) updateSubmitButton('idle', submitBtn);
      const messageInput = uiModule.el('message');
      if (messageInput) messageInput.disabled = false;
      _drainQueuedAgentRequests(sid);
    } catch (err) {
      console.warn('[stream-watchdog] Stream status probe failed:', err);
    } finally {
      _staleStreamProbeInFlight = false;
    }
  }

  function _startStallWatchdog() {
    // Keep the old noisy stall banner disabled. This watchdog only unlocks
    // a dead local stream after the backend confirms no active stream exists.
    if (_stallWatchdog) { clearInterval(_stallWatchdog); _stallWatchdog = null; }
    _removeStallBanner();
    _stallWatchdog = setInterval(_probeStaleLocalStream, 5000);
  }
  function _stopStallWatchdog() {
    if (_stallWatchdog) { clearInterval(_stallWatchdog); _stallWatchdog = null; }
    _removeStallBanner();
  }

  /** Show a "Cancelled by user" record in `holder` and persist an empty
   *  assistant placeholder server-side so the turn survives a refresh.
   *  Called from both abort paths when no tokens had streamed yet. */
  function _renderCancelledBubble(holder) {
    if (!holder) return;
    if (holder.dataset.cancelledRendered === '1') return;
    holder.dataset.cancelledRendered = '1';
    holder.dataset.raw = '';
    holder.style.display = '';
    const body = holder.querySelector('.body');
    if (body) {
      body.innerHTML = '';
      const indicator = document.createElement('div');
      indicator.className = 'stopped-indicator';
      const label = document.createElement('span');
      label.style.fontStyle = 'italic';
      label.style.opacity = '0.7';
      label.textContent = '[Cancelled by user]';
      indicator.appendChild(label);
      body.appendChild(indicator);
    }
    if (typeof createMsgFooter === 'function' && !holder.querySelector('.msg-footer')) {
      holder.appendChild(createMsgFooter(holder));
    }
    // Persist as an assistant message with stopped+cancelled metadata so the
    // chat-history loader renders the same indicator after a refresh.
    // Include the model name so the bubble header still shows which model
    // was running when the user hit Stop.
    const sid = sessionModule.getCurrentSessionId();
    if (sid) {
      let modelName = '';
      try { modelName = sessionModule.getCurrentModel?.() || ''; } catch {}
      // Fallback: pull from the holder's existing meta (the streaming
      // placeholder usually has the model set in the header already).
      if (!modelName) {
        modelName = holder.dataset.model
          || holder.querySelector('.msg-header .msg-model')?.textContent
          || '';
      }
      fetch(`${API_BASE}/api/session/${sid}/inject_messages`, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: [{
            role: 'assistant',
            content: '',
            metadata: { stopped: true, cancelled: true, model: modelName },
          }],
        }),
      }).catch(() => {});
    }
  }

  /**
   * Detach current stream to run in background instead of aborting.
   * Called when user switches sessions mid-stream.
   */
  export function detachCurrentStream(sessionId) {
    const active = sessionId ? _activeStreams.get(sessionId) : _getForegroundStreamState();
    if (!active || !active.abortCtrl) {
      // Not streaming — fall through to abort
      abortCurrentRequest();
      return;
    }
    // Detachment deliberately keeps the network stream alive, but the outgoing
    // view must stop all delayed rendering immediately. The reader loop may not
    // receive another SSE line for an arbitrary amount of time.
    if (active.cancelViewWork) active.cancelViewWork();

    const terminalSaved = _terminalSavedStreams.has(sessionId);
    // `P4-24`. Once a resumed view has taken this reader's drawing over, it
    // keeps it: the reader missed what happened while it was away, and
    // re-selecting the chat (the resumed view's own reload does) must not hand
    // the drawing back to it for the instant before `checkBackgroundStream`.
    const priorBg = _backgroundStreams.get(sessionId);
    const resumedView = !!(priorBg && priorBg.resumedView && priorBg.abortCtrl === active.abortCtrl);
    // Store background stream state. A canonical terminal event can precede
    // its SSE error event; preserve completion if the user switches sessions
    // during that gap instead of creating a fresh running/error marker.
    _backgroundStreams.set(sessionId, {
      status: terminalSaved ? 'completed' : 'running',
      accumulated: currentAccumulated,
      sourcesHtml: '',
      findingsData: null,
      abortCtrl: active.abortCtrl,
      query: active.query || (active.holder ? (active.holder._researchQuery || '') : ''),
      metrics: null,
      resumedView,
    });
    // Mark session with pulsing dot in sidebar
    if (!terminalSaved && sessionModule && sessionModule.markStreaming) {
      sessionModule.markStreaming(sessionId);
    } else if (terminalSaved && sessionModule && sessionModule.clearStreaming) {
      sessionModule.clearStreaming(sessionId);
    }
    // Clear local state WITHOUT aborting the fetch
    if (currentAbort === active.abortCtrl) currentAbort = null;
    if (currentHolder === active.holder) currentHolder = null;
    if (_streamSessionId === sessionId) _streamSessionId = null;
    currentAccumulated = '';
    _syncForegroundStreamGlobals();
    // Reset submit button so the new chat is ready to send
    const submitBtn = document.querySelector('.send-btn');
    if (submitBtn) updateSubmitButton('idle', submitBtn);
  }

  // _notifyStreamComplete and _insertStreamDoneToast now in chatStream.js
  var _notifyStreamComplete = chatStream.notifyStreamComplete;
  var _insertStreamDoneToast = chatStream.insertStreamDoneToast;

  // `B920`. The footer's pills — the memories recalled, the skills shown, the
  // promotion to agent mode, the fallback chain — are drawn by `createMsgFooter`
  // from properties of the element it is handed. The live stream keeps them on
  // the turn's first bubble (`holder`), where they arrive before the reply, and
  // makes the footer on its last: the last visible step's bubble, or the last
  // thread on a turn that only ran tools. Those are one element only when the
  // reply is one bubble, so an agent turn that went round a tool drew none of
  // its pills until a reload, where the history renderer puts the saved ones on
  // the last bubble. The element a footer is made on is handed them first.
  const _TURN_PILL_KEYS = ['_memoriesUsed', '_skillsInjected', '_autoEscalated', '_fallbackChain'];
  function _withTurnPills(target, turnHolder) {
    if (!target || !turnHolder || target === turnHolder) return target;
    for (const key of _TURN_PILL_KEYS) {
      if (turnHolder[key] != null) target[key] = turnHolder[key];
    }
    return target;
  }

  // ── `P4-24` · What an agent turn draws besides its text ────────────────────
  //
  // A turn draws more than its reply: a thread of tool cards, the "Thinking"
  // spinner between them with the meter (`P4-23`) under it, the prep line
  // (`P4-08`) under the first spinner, a bubble per step, and the stop line
  // (`P4-10`) when a guard ends it. The live stream (`handleChatSubmit`) drew all of
  // that inline. A stream picked up after navigating away (`resumeStream`) drew
  // none of it: a second, much poorer dispatch chain turned every one of those
  // events into `rich = true`, so for as long as the resumed stream ran, a
  // person watched a rich run through a one-bit window.
  //
  // What follows is the drawing both streams now share. Each function takes
  // what it needs and returns what it made. The state — which card is running,
  // which thread is current, which bubble a step writes into — stays with the
  // stream that owns it. A resumed stream draws what the live one draws because
  // it calls the same code, not because a copy was kept in step (`Law 14`).

  /**
   * The spinner a person waits at, for one stream: the "Thinking" spinner
   * between tools (`.agent-thinking-dots`), which comes back 400ms after output
   * pauses, and the answer every meter event needs — which spinner is on screen
   * for the meter to hang under.
   *
   *   meter         this stream's `createAgentMeter()`
   *   roundSpinner  () => the step's own spinner, or null
   *   streaming     () => whether the stream is still being read
   *   toolName      () => the last tool started, for the spinner's words
   */
  function _createWaitSpinners({ meter = null, roundSpinner = () => null,
                                 streaming = () => true, toolName = () => '' } = {}) {
    let pauseTimer = null;
    const wait = {
      // `P4-01`: the running form of the last tool's label, from the map the
      // card beside it reads, so the spinner and the card cannot drift apart.
      label() {
        const name = String(toolName() || '');
        if (!name) return 'Thinking';
        // Check exact match first, then prefix match
        const lower = name.toLowerCase();
        if (TOOL_LABELS[lower]) return TOOL_LABELS[lower].running;
        for (const [key, forms] of Object.entries(TOOL_LABELS)) {
          if (lower.includes(key) || key.includes(lower)) return forms.running;
        }
        return 'Thinking';
      },
      show(label) {
        if (document.querySelector('.agent-thinking-dots')) return;
        const _thinkMsg = document.createElement('div');
        _thinkMsg.className = 'msg msg-ai agent-thinking-dots';
        const _thinkBody = document.createElement('div');
        _thinkBody.className = 'body';
        const _ts = spinnerModule.create(label || 'Thinking', 'right', 'wave');
        _thinkBody.appendChild(_ts.createElement());
        if (meter) meter.attachTo(_ts);   // `P4-23`: the meter rides the wait between steps
        _ts.start(120);
        _thinkMsg._spinner = _ts;
        _thinkMsg.appendChild(_thinkBody);
        document.getElementById('chat-history').appendChild(_thinkMsg);
        uiModule.scrollHistory();
      },
      remove() {
        const el = document.querySelector('.agent-thinking-dots');
        if (el) {
          if (el._spinner) el._spinner.destroy();
          el.remove();
        }
      },
      replace(label) {
        wait.remove();
        wait.show(label);
      },
      // Auto-show the spinner once output stops.
      schedule() {
        if (pauseTimer) clearTimeout(pauseTimer);
        pauseTimer = setTimeout(() => {
          if (!document.querySelector('.agent-thinking-dots') && streaming()) {
            wait.show(wait.label());
          }
        }, 400);
      },
      cancel() {
        if (pauseTimer) { clearTimeout(pauseTimer); pauseTimer = null; }
      },
      // `P4-08` / `P4-23`. The spinner on screen right now, for the meter to
      // hang under: the "Thinking" one between tools if it is up, otherwise
      // the step's own. `null` while a tool card or text owns the bottom of
      // the turn — the meter waits for the next spinner then.
      host() {
        const dots = document.querySelector('.agent-thinking-dots');
        if (dots && dots._spinner && dots._spinner.element) return dots._spinner;
        const own = roundSpinner();
        return (own && own.element) ? own : null;
      },
    };
    return wait;
  }

  // `B916`. `_openRoundSpinner` — the spinner a new step opens with, carrying
  // the meter — lives in `agentTurn.js` (imported at the top under this name),
  // so a compare pane opens its steps with it too.

  /**
   * A new step's bubble at the bottom of `box`, labelled with the model the step
   * runs on — the route state it inherits from the turn's first bubble and the
   * step before it. Returns the bubble, whose `.body` is empty.
   */
  function _newRoundBubble(box, prevHolder, roundHolder, sessionId, fallbackModel) {
    const newWrap = document.createElement('div');
    newWrap.className = 'msg msg-ai msg-continuation streaming';
    // Add model name label
    const newRole = document.createElement('div');
    newRole.className = 'role';
    const metaS = sessionModule.getSessions().find(s => s.id === sessionId);
    inheritModelRouteState(prevHolder, roundHolder, newWrap, metaS?.model || fallbackModel);
    const requested = newWrap._requestedModel;
    const actual = newWrap._actualModel;
    newRole.textContent = _modelRouteLabel(
      requested,
      actual,
      newWrap._requestedEndpointLabel,
      newWrap._actualEndpointLabel,
      newWrap._requestedEndpointId,
      newWrap._actualEndpointId,
    ) || '';
    _applyModelColor(newRole, actual);
    newWrap.appendChild(newRole);
    const newBody = document.createElement('div');
    newBody.className = 'body';
    newWrap.appendChild(newBody);
    box.appendChild(newWrap);
    return newWrap;
  }

  /**
   * The thread the next tool card goes in: the one at the bottom of `box` when
   * only hidden bubbles and the wait spinner sit below it, else a new one.
   * `textAbove` says whether the step's own bubble has text, which the new
   * thread's line reaches up to. Marks the thread as the one being written.
   */
  function _threadForNextCard(box, textAbove) {
    // Find existing thread to append to — check last few children
    // (agent_step may insert an empty msg-ai between tool rounds)
    let threadWrap = null;
    for (let ci = box.children.length - 1; ci >= Math.max(0, box.children.length - 5); ci--) {
      const child = box.children[ci];
      if (child.classList.contains('agent-thread')) {
        threadWrap = child;
        break;
      }
      // Skip hidden (empty) bubbles and thinking spinners
      if (child.style.display === 'none' || child.classList.contains('agent-thinking-dots')) continue;
      // `B904`: anything else that is visible — a bubble with text, a takeover
      // banner, a note — sits between that thread and this card.
      break;
    }
    if (threadWrap) {
      // Continuing an existing thread — remove has-bottom (agent_step may have set it
      // expecting text, but we got more tools instead)
      threadWrap.classList.remove('has-bottom');
    } else {
      threadWrap = document.createElement('div');
      threadWrap.className = 'agent-thread';
      // Extend line up to connect to chat bubble above (if there is one)
      const _prevSib = box.lastElementChild;
      const _hasBubbleAbove = _prevSib && (_prevSib.classList.contains('msg') && _prevSib.style.display !== 'none');
      const _hasThreadAbove = _prevSib && _prevSib.classList.contains('agent-thread');
      if (_hasBubbleAbove || _hasThreadAbove || textAbove) {
        threadWrap.classList.add('has-top');
      }
      box.appendChild(threadWrap);
    }
    threadWrap.classList.add('streaming');
    return threadWrap;
  }

  /**
   * `B922`. The teacher's first bubble names the teacher's model. A step's
   * bubble copies the route of the bubble above it (`inheritModelRouteState`),
   * so the one opened below a takeover banner was headed with the student's
   * model, and every teacher step after it inherited that. Nothing in the
   * teacher's run put it right: `model_actual` is sent only when a provider
   * resolves a different model from the one requested, and the teacher's
   * `metrics` relabel only its last bubble, at the end. The takeover now names
   * the model the teacher's run requests (`model`; the setting it was resolved
   * from is `teacher_model`, which the banner prints). The bubble never keeps
   * the student's endpoint, which the teacher's `metrics` would later set
   * against the teacher's own as a change of route. `B940`: the teacher's run
   * is started on its own route now, and the event names that route's endpoint
   * when it is a configured one (`endpoint_id`, `endpoint_label`) — the one its
   * record names — so the bubble is on it; otherwise it claims none. Later
   * steps inherit all of it from here.
   */
  function _headWithTeacher(bubble, event) {
    const model = String((event && (event.model || event.teacher_model)) || '').trim();
    if (!bubble || !model) return bubble;
    bubble._requestedModel = model;
    bubble._actualModel = model;
    for (const key of ['_requestedEndpointId', '_requestedEndpointLabel',
                       '_actualEndpointId', '_actualEndpointLabel']) {
      delete bubble[key];
    }
    if (event.endpoint_id && event.endpoint_label) {
      bubble._requestedEndpointId = bubble._actualEndpointId = String(event.endpoint_id);
      bubble._requestedEndpointLabel = bubble._actualEndpointLabel = String(event.endpoint_label);
    }
    const role = bubble.querySelector('.role');
    if (role) {
      role.textContent = _modelRouteLabel(model, model) || '';
      _applyModelColor(role, model);
    }
    return bubble;
  }

  /**
   * `B941`. Continue ▸ after the step limit carries the same reply on: the
   * server joins the two replies into one (`merge-last-assistant`), the
   * continuation's steps numbered after the first run's, and a reload draws
   * them as one — the continuation's first step a step of that reply. Live, the
   * continuation was merged into the turn's first bubble, as a stopped reply's
   * text is: in an agent turn that bubble is usually hidden (it wrote nothing
   * before its first tool), so the old and new text were rendered into a hidden
   * bubble, the continuation's own last bubble was removed, and the continued
   * answer left the screen until a reload. Now the continuation stays where it
   * was drawn, below the steps it carries on, and its first bubble becomes a
   * step of the reply: a continuation (no time of its own, as in the reload)
   * that edits and deletes the reply it was joined to. `firstBubble` is the
   * reply's first bubble, the one Continue ▸ handed over.
   */
  function _joinContinuedSteps(firstBubble, continuation) {
    if (!continuation || !continuation.classList) return continuation;
    continuation.classList.add('msg-continuation');
    const stamp = continuation.querySelector('.role-timestamp');
    if (stamp) stamp.remove();
    const id = firstBubble && firstBubble.dataset ? firstBubble.dataset.dbId : '';
    if (id) continuation.dataset.dbId = id;
    else delete continuation.dataset.dbId;
    return continuation;
  }

  /**
   * `B919`. At a new step, the thread directly above its bubble runs its line
   * on down into it (`has-bottom`). Both streams gave that connector to the
   * first `.agent-thread.streaming` on the page — and every thread a turn draws
   * keeps `streaming` until the turn ends, so in a turn of two threads the
   * first got it and the one directly above the new step got none (measured in
   * `test_refusals_and_text_after_a_tool_draw_the_same_in_both_streams`: after
   * `agent_step`, the second thread had `bottom: false`). After a takeover it
   * was worse: the student's thread, above the banner, took a line that ran
   * down through it. The thread is the one at the bottom of `box`, past bubbles
   * hidden for writing nothing and the wait spinner — the walk
   * `_threadForNextCard` makes — and there is none when anything else visible
   * sits between: the step's own text, a stop line, a note, a banner. A thread
   * of an earlier turn is not `streaming`, and is not this step's. Returns it.
   */
  function _threadIntoNextStep(box) {
    if (!box) return null;
    const kids = box.children;
    for (let ci = kids.length - 1; ci >= 0; ci--) {
      const child = kids[ci];
      if (child.style.display === 'none' || child.classList.contains('agent-thinking-dots')) continue;
      if (child.classList.contains('agent-thread') && child.classList.contains('streaming')) {
        child.classList.add('has-bottom');
        return child;
      }
      return null;
    }
    return null;
  }

  /**
   * The thread a card about the step's work goes in — the refused call
   * (`P4-20`) and the verifier's verdict (`P4-17`): the thread the step's cards
   * went into, or a bare one if that is gone. A bare one, not a copy of
   * `_threadForNextCard`: its connectors describe a thread that continues into
   * text, and a lone card like these does not.
   */
  function _threadOrBare(thread, box) {
    if (thread && thread.isConnected) return thread;
    const bare = document.createElement('div');
    bare.className = 'agent-thread';
    if (box) box.appendChild(bare);
    return bare;
  }

  // `B918`. The running card, its progress and the finished card —
  // `_startToolCard`, `_drawToolProgress`, `_finishToolCard` and
  // `_stopCardTickers` — live in `agentTurn.js` (imported at the top under
  // these names), so a compare pane draws a card the way both streams here do.

  /** Take `node` and everything drawn after it off the history, stopping the
   *  clocks of any cards among them. */
  function _removeViewFrom(node) {
    const parent = node && node.parentNode;
    if (!parent) return;
    const kids = Array.from(parent.children);
    const at = kids.indexOf(node);
    if (at < 0) return;
    for (const gone of kids.slice(at)) {
      if (gone.querySelectorAll) gone.querySelectorAll('.agent-thread-node').forEach(_stopCardTickers);
      gone.remove();
    }
  }

  /**
   * Live-resume a chat run still streaming detached on the server (#2539).
   *
   * On session re-entry, GET /api/chat/resume/{id} replays the run's buffer then
   * streams live; reply tokens render as they arrive. On completion a plain text
   * reply is finalized in place (canonical bubble via chatRenderer.addMessage, no
   * reload); a "rich" reply (tool calls, sources, doc streaming, multi-round) is
   * reloaded from the DB so its full render stays faithful. Returns true if it
   * attached, false to let the caller fall back to spinner+poll.
   *
   * `P4-24`. While it streams it draws what the live stream draws, through the
   * same functions (the section above): a bubble per step, the thread of tool
   * cards as they run, report progress, finish, are refused or are checked,
   * the "Thinking" spinner between them, the prep line and the step / tool-call
   * meter under whichever spinner is showing, the stop line, and generated
   * images. What it still leaves to the reload is `_RESUME_RELOAD_TYPES`.
   *
   * The run's buffer is replayed from its first event, so the turn is drawn
   * from its start. Meter frames are whole state, so the replayed meter lands
   * where the live one was. A view of the same run already on the page — the
   * live one a dropped connection left behind — is replaced, not doubled
   * (`dataset.agentRun` marks where it starts). The stop line drawn here is not
   * doubled by the reload's own copy from `metadata.agent_stops` either: the
   * reload clears the history before it draws.
   *
   * `opts.besideBackgroundReader`: this tab is still reading the run through
   * the POST that started it, moved to the background when the person left the
   * chat (`checkBackgroundStream`). That reader stops drawing once this view is
   * up (`_isBg` in `handleChatSubmit`).
   */
  export async function resumeStream(sessionId, replaceHolder = null, opts = {}) {
    if (!sessionId) return false;
    if (_resumingStreams.has(sessionId)) return false;
    if (!(opts && opts.besideBackgroundReader) && hasActiveStream(sessionId)) return false;

    let res;
    try {
      res = await fetch(`${API_BASE}/api/chat/resume/${sessionId}`);
    } catch (e) {
      return false;
    }
    if (!res.ok || !res.body) return false;
    const resumeRunId = res.headers.get('X-Pantheon-Run-Id') || '';
    if (resumeRunId) _streamRunIds.set(sessionId, resumeRunId);

    const box = document.getElementById('chat-history');
    if (!box) return false;
    // `P4-24`. The replay draws this run from its first event, so a view of it
    // already on the page is replaced from where it starts: the bubble the live
    // stream marked with the run's id, or the one `_tryAutoRecover` hands over.
    const priorView = resumeRunId
      ? Array.from(box.children).find((n) => n.dataset && n.dataset.agentRun === resumeRunId)
      : null;
    _removeViewFrom(priorView);
    if (replaceHolder && replaceHolder.parentNode) _removeViewFrom(replaceHolder);

    // Block duplicate re-attach attempts while this reader is live. A dedicated
    // set (not _backgroundStreams) so checkBackgroundStream doesn't mistake this
    // for a same-tab POST stream and spawn its own spinner+poll on re-entry.
    _resumingStreams.add(sessionId);

    const holder = document.createElement('div');
    holder.className = 'msg msg-ai';
    if (resumeRunId) holder.dataset.agentRun = resumeRunId;
    const meta = sessionModule.getSessions().find(s => s.id === sessionId);
    const roleLabel = _shortModel(meta && meta.model);
    const roleTs = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    holder.innerHTML = '<div class="role">' + uiModule.esc(roleLabel) +
      ' <span class="role-timestamp">' + roleTs + '</span></div>' +
      '<div class="body"><div class="stream-content"></div></div>';
    holder._requestedModel = meta && meta.model;
    holder._actualModel = holder._requestedModel;
    _applyModelColor(holder.querySelector('.role'), meta && meta.model);
    let contentDiv = holder.querySelector('.stream-content');
    box.appendChild(holder);

    let spinner = spinnerModule.create('Generating response...', 'right');
    holder.querySelector('.body').appendChild(spinner.createElement());
    spinner.start();
    uiModule.scrollHistory();

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let roundText = '';
    let leftSession = false;
    let metricsData = null;
    let replayError = null;
    let canonicalTerminalSeen = false;
    // "Rich" responses (tool calls, sources, doc streaming, multi-round) need the
    // full canonical render, which is rebuilt from the saved DB record on reload.
    // Plain text replies can be finalized in place without a reload.
    let rich = false;

    // `P4-24`. This stream's turn: the pieces the live stream keeps, drawn by
    // the same functions — the meter, the spinner a person waits at, the bubble
    // each step writes into, and the card that is running and its thread.
    const meter = createAgentMeter();
    let reading = true;
    let roundHolder = holder;
    let roundClosed = false;
    let thinkOpen = false;       // inside a run of reasoning tokens
    let docRound = null;         // the step whose text opened a document fence
    let toolNode = null;         // the running card (`currentToolBubble` live)
    let toolThread = null;       // the thread the last card went into (`lastToolThread`)
    let toolName = '';           // the last tool started, for the wait spinner's words
    const cards = [];
    const wait = _createWaitSpinners({
      meter,
      roundSpinner: () => spinner,
      streaming: () => reading,
      toolName: () => toolName,
    });

    const cleanup = () => {
      reading = false;
      wait.cancel();
      wait.remove();
      try { spinner.destroy(); } catch (_) {}
      // A card still running when the stream ends never gets its result. Its
      // clock stops, and it stops saying it is running — as the live stream's
      // catch path leaves an orphaned card. Matters where the view stays on
      // screen: a replay that ends on an error.
      cards.forEach((card) => {
        _stopCardTickers(card);
        card.classList.remove('running');
      });
      meter.dispose();
      _resumingStreams.delete(sessionId);
    };

    const renderDelta = () => {
      // The live stream wraps each run of reasoning tokens in <think>…</think>.
      // An open run is closed here for drawing only, so a step that is still
      // reasoning shows the thinking block rather than printing it as the reply.
      const text = thinkOpen ? roundText + '</think>' : roundText;
      const dt = markdownModule.normalizeThinkingMarkup(_streamDisplayText(text));
      if (docRound === roundHolder && !dt.trim()) {
        _showDocumentWritingStatus(contentDiv);
      } else {
        contentDiv.innerHTML = markdownModule.processWithThinking(markdownModule.squashOutsideCode(dt));
      }
      uiModule.scrollHistory();
    };

    // What the live stream does before a card or a new step: the spinners go,
    // and the step's text is drawn final — a step that wrote nothing is hidden,
    // as `_finalizeRoundRender` hides it.
    const closeRound = () => {
      wait.cancel();
      wait.remove();
      if (spinner && spinner.element) spinner.destroy();
      if (thinkOpen) { roundText += '</think>'; thinkOpen = false; }
      if (roundClosed) return;
      roundClosed = true;
      const dt = markdownModule.normalizeThinkingMarkup(_streamDisplayText(roundText));
      if (!dt.trim()) {
        roundHolder.style.display = 'none';
        return;
      }
      contentDiv.innerHTML = markdownModule.processWithThinking(markdownModule.squashOutsideCode(dt));
      if (window.hljs) roundHolder.querySelectorAll('pre code').forEach((block) => window.hljs.highlightElement(block));
    };

    // A new step's bubble, opened as `agent_step` opens it live — with its
    // spinner and the meter under it — or, without a spinner, when text arrives
    // for a step whose bubble was hidden (`_ensureVisibleRoundForDelta`). A
    // teacher's first bubble (`B917`) has a spinner and, until the teacher's
    // own first frame, no meter, as live.
    const openRound = (withSpinner, spinnerMeter = meter) => {
      roundHolder = _newRoundBubble(box, holder, roundHolder, sessionId, meta && meta.model);
      const body = roundHolder.querySelector('.body');
      if (withSpinner) spinner = _openRoundSpinner(body, spinnerMeter);
      contentDiv = document.createElement('div');
      contentDiv.className = 'stream-content';
      body.appendChild(contentDiv);
      roundText = '';
      roundClosed = false;
      uiModule.scrollHistory();
    };

    try {
      readLoop:
      while (true) {
        // User left this session: stop rendering, the run continues server-side.
        if (sessionModule.getCurrentSessionId &&
            sessionModule.getCurrentSessionId() !== sessionId) {
          leftSession = true;
          try { await reader.cancel(); } catch (_) {}
          break;
        }
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop();
        for (const part of parts) {
          // `P4-24`. This view draws into the history, so it stops the moment
          // the person moves on — not one read later, when a card would already
          // have landed in the chat they moved to.
          if (sessionModule.getCurrentSessionId &&
              sessionModule.getCurrentSessionId() !== sessionId) {
            leftSession = true;
            try { await reader.cancel(); } catch (_) {}
            break readLoop;
          }
          const eventIsError = part.split('\n').some(l => l.trim() === 'event: error');
          if (eventIsError) rich = true;
          const line = part.split('\n').find(l => l.startsWith('data: '));
          if (!line) continue;
          const payload = line.slice(6);
          if (payload === '[DONE]') {
            try { await reader.cancel(); } catch (_) {}
            break readLoop;
          }
          let json;
          try { json = JSON.parse(payload); } catch (_) { continue; }
          if (eventIsError) {
            replayError = createTerminalStreamError(json);
          } else if (json.delta) {
            // Reasoning tokens arrive flagged `thinking`; each run of them is
            // wrapped in <think>…</think>, as the live stream wraps it.
            let delta = json.delta;
            if (json.thinking) {
              if (!thinkOpen) { delta = '<think>' + delta; thinkOpen = true; }
            } else if (thinkOpen) {
              delta = '</think>' + delta;
              thinkOpen = false;
            }
            if (roundHolder.style.display === 'none') {
              // Text after the tools: the thread's line reaches down to it.
              if (toolThread && toolThread.isConnected) toolThread.classList.add('has-bottom');
              openRound(false);
            }
            roundText += delta;
            roundClosed = false;
            if (!docRound && /```(?:create_document|documen(?:t)?)\s*\n/i.test(roundText)) {
              docRound = roundHolder;
              rich = true;
            }
            wait.cancel();
            wait.remove();
            if (spinner && spinner.element) spinner.destroy();
            renderDelta();
            wait.schedule();
          } else if (METER_EVENT_TYPES.has(json.type)) {
            // `P4-08` / `P4-23`, through the call the live stream makes. Every
            // frame is whole state, so replaying the run from its first event
            // lands the meter exactly where the live one was.
            switch (json.type) {
              case 'agent_prep': {
                wait.cancel();
                const host = wait.host();
                presentMeterEvent(meter, json, host);
                if (!host && meter.spinnerLabel()) wait.replace(meter.spinnerLabel());
                break;
              }
              case 'agent_budget':
                presentMeterEvent(meter, json, wait.host());
                break;
              default:
                // The stop the meter was counting toward, recorded — and
                // (`B917`) the Continue offer or the tool-budget note beside
                // it, drawn as the live stream draws them. They are saved with
                // the reply now (`B915`), so the reload this stream ends in
                // draws them again rather than taking them away.
                presentMeterEvent(meter, json, null);
                wait.cancel();
                wait.remove();
                renderAgentNote(box, json, { reply: holder });
                rich = true;
            }
          } else if (json.type === 'tool_start') {
            rich = true;
            closeRound();
            toolName = json.tool || '';
            toolThread = _threadForNextCard(box, !!(roundText.trim() && roundHolder.style.display !== 'none'));
            toolNode = _startToolCard(toolThread, json);
            cards.push(toolNode);
          } else if (json.type === 'tool_progress') {
            rich = true;
            if (toolNode) _drawToolProgress(toolNode, json);
          } else if (json.type === 'tool_output') {
            rich = true;
            if (toolNode) {
              _finishToolCard(toolNode, json);
              toolName = '';
            }
            if (json.image_url) _appendGeneratedImageBubble(json);
            // The card is finished; a later event with no card of its own
            // must not be handed this one (`P4-20`).
            toolNode = null;
            wait.schedule();
          } else if (json.type === 'tool_blocked' || json.type === 'verifier') {
            // `P4-20`'s refusal card and `P4-17`'s verdict. A refused call is
            // the model's action, so it closes the step and takes the thread
            // `tool_start` would — the live arm's rule since `B904`. The
            // verdict stays with the thread of the step's own work
            // (`_threadOrBare`).
            rich = true;
            const node = document.createElement('div');
            applyAgentThreadNode(node, json.type === 'verifier' ? verifierCardOptions(json) : blockedCardOptions(json));
            if (json.type === 'tool_blocked') {
              closeRound();
              toolThread = _threadForNextCard(box, !!(roundText.trim() && roundHolder && roundHolder.style.display !== 'none'));
            } else {
              toolThread = _threadOrBare(toolThread, box);
            }
            toolThread.appendChild(node);
            if (json.type === 'tool_blocked') toolNode = null;
            uiModule.scrollHistory();
          } else if (json.type === 'loop_breaker_triggered' || json.type === 'intent_nudge_exhausted') {
            // `P4-10`'s line, by its one drawer. The reload draws it again from
            // `metadata.agent_stops` into a history it has just cleared, so it
            // is replaced there, not doubled.
            rich = true;
            wait.cancel();
            wait.remove();
            if (renderAgentStop(box, json)) uiModule.scrollHistory();
          } else if (json.type === 'teacher_takeover') {
            // `B917`. The takeover, as the live arm draws it: the student's
            // step is closed where it stands, the banner goes below it, and
            // the teacher's run opens a bubble of its own below that, with the
            // spinner its preparation and meter hang under. Its cards start a
            // thread of their own (the banner ends the search for one).
            rich = true;
            closeRound();
            renderAgentNote(box, json);
            toolNode = null;
            toolThread = null;
            openRound(true, null);
            _headWithTeacher(roundHolder, json);   // `B922`
          } else if (json.type === 'skill_saved' || json.type === 'escalation_failed'
                     || json.type === 'skill_save_failed') {
            // `B917`: the skill notes, by the live stream's builder.
            rich = true;
            if (renderAgentNote(box, json)) uiModule.scrollHistory();
          } else if (json.type === 'agent_step') {
            rich = true;
            closeRound();
            // Mark thread as connected to bubble below (`B919`: the one
            // directly above it, as the live arm marks it).
            _threadIntoNextStep(box);
            toolNode = null;
            openRound(true);
          } else if (json.type === 'generated_image') {
            rich = true;
            _appendGeneratedImageBubble(json);
          } else if (json.type === 'doc_stream_open') {
            rich = true;
            if (documentModule) documentModule.streamDocOpen(json.title || '', json.lang || '');
          } else if (json.type === 'doc_stream_delta') {
            rich = true;
            if (documentModule) documentModule.streamDocDelta(json.content || json.delta || '');
          } else if (json.type === 'metrics') {
            metricsData = json.data || metricsData;
            if (metricsData && resumeRunId) {
              metricsData._costRecordId = _metricsCostRecordId(resumeRunId, json);
            }
            if (metricsData) {
              chatRenderer.recordSessionMetricsCost(metricsData, sessionId);
            }
          } else if (json.type === 'fallback') {
            // Replay can attach after the selected route has already failed.
            // Reflect the fallback immediately, then reload the canonical
            // multi-round record when the detached run completes.
            rich = true;
            const fallbackHolder = applyModelRouteEventState(json, holder, roundHolder, meta && meta.model);
            if (fallbackHolder) {
              _setRoleModelLabel(
                fallbackHolder.querySelector('.role'),
                fallbackHolder._requestedModel,
                fallbackHolder._actualModel,
                {
                  reason: json.reason,
                  requestedEndpointId: fallbackHolder._requestedEndpointId,
                  requestedEndpointLabel: fallbackHolder._requestedEndpointLabel,
                  actualEndpointId: fallbackHolder._actualEndpointId,
                  actualEndpointLabel: fallbackHolder._actualEndpointLabel,
                },
              );
            }
            uiModule.showToast(
              'Fallback: ' + _shortModel(json.selected_model || '') + ' failed — answered by ' +
              _shortModel(json.answered_by || ''),
              6000,
            );
          } else if (json.type === 'model_actual') {
            rich = true;
            const modelHolder = applyModelRouteEventState(json, holder, roundHolder, meta && meta.model);
            if (modelHolder) {
              _setRoleModelLabel(
                modelHolder.querySelector('.role'),
                modelHolder._requestedModel,
                modelHolder._actualModel,
                {
                  requestedEndpointId: modelHolder._requestedEndpointId,
                  requestedEndpointLabel: modelHolder._requestedEndpointLabel,
                  actualEndpointId: modelHolder._actualEndpointId,
                  actualEndpointLabel: modelHolder._actualEndpointLabel,
                },
              );
            }
          } else if (json.type === 'agent_terminal' || json.type === 'chat_terminal') {
            // The server has already persisted canonical partial content plus
            // a sanitized failure note and actual route provenance.  Do not
            // finalize replayed deltas as a successful local-only answer.
            rich = true;
            canonicalTerminalSeen = true;
            metricsData = json.data || metricsData;
            if (metricsData && resumeRunId) {
              metricsData._costRecordId = _metricsCostRecordId(resumeRunId, json);
            }
            if (metricsData) displayMetrics(holder, metricsData);
          } else if (_RESUME_RELOAD_TYPES.has(json.type)) {
            rich = true;
          }
        }
      }
    } catch (e) {
      // Network drop or parse failure: fall through to the canonical reload.
      rich = true;
    }

    if (thinkOpen) { roundText += '</think>'; thinkOpen = false; }
    cleanup();
    if (docRound) _finishDocumentWritingStatus(docRound, true);
    if (leftSession) { _removeViewFrom(holder); return true; }

    const onThisSession = sessionModule.getCurrentSessionId &&
                          sessionModule.getCurrentSessionId() === sessionId;

    // A failure before substantive output has no persisted assistant record to
    // recover through a canonical reload. Keep its sanitized provider/request
    // error visible in the replay holder instead of deleting the only evidence.
    if (onThisSession && replayError && !canonicalTerminalSeen) {
      const errorDiv = document.createElement('div');
      errorDiv.style.cssText = 'color: var(--color-error); font-style: italic; padding: 4px 0;';
      errorDiv.textContent = `[Error: ${replayError.message}]`;
      roundHolder.style.display = '';
      contentDiv.appendChild(errorDiv);
      uiModule.scrollHistory();
      return true;
    }

    // Plain text reply: finalize in place. Replace the live bubble with a
    // canonical single message (markdown + footer actions + metrics) using the
    // same renderer history does. No history refetch, no end-of-stream flicker.
    if (onThisSession && !rich && roundText.trim()) {
      if (holder.parentNode) holder.remove();
      const model = meta && meta.model;
      const meta_ = metricsData ? Object.assign({ model }, metricsData) : { model };
      chatRenderer.addMessage('assistant', roundText, model, meta_);
      uiModule.scrollHistory();
      return true;
    }

    // Rich response (tools, sources, docs, multi-round) or user moved on:
    // reload from the DB for the full canonical render.
    if (holder._docWritingThread && holder._docWritingThread.parentNode) holder._docWritingThread.remove();
    // `P4-24`: the whole turn this view drew, not only its first bubble.
    _removeViewFrom(holder);
    if (metricsData) {
      chatRenderer.recordSessionMetricsCost(metricsData, sessionId);
    }
    if (onThisSession) sessionModule.selectSession(sessionId);
    else sessionModule.loadSessions();
    return true;
  }

  // `P4-24`. What a resumed stream leaves to the reload it ends in. Each is
  // drawn live by the main stream; here each only marks the reply "rich", so
  // the reload draws its saved form (or, for the few with none, nothing):
  //   web_sources, rag_sources, memories_used, skills_injected, auto_escalated
  //       — the footer pills, from the saved reply;
  //   research_* — research keeps its own progress view, and a resumed stream
  //       is never attached to a research run (`_checkServerStream`);
  //   ask_user — the question or approval card, from the saved tool event;
  //   plan_update, doc_update, doc_suggestions, ui_control — these act on the
  //       plan, the document editor and the page. A replay from the run's
  //       first event would act again on something already done.
  // `B917`: `teacher_takeover`, `skill_saved`, `escalation_failed` and
  // `skill_save_failed` left this list. They are saved with the reply now
  // (`B915`), and the resumed view draws them as the live one does.
  //   compacted — (`B921`) live, a toast; saved with the reply as one of its
  //       notes, which the reload draws as a line where it happened. A reply
  //       finalized in place would lose it.
  const _RESUME_RELOAD_TYPES = new Set([
    'web_sources', 'rag_sources', 'memories_used', 'skills_injected', 'auto_escalated',
    'research_progress', 'research_sources', 'research_findings', 'research_done',
    'ask_user',
    'plan_update', 'doc_update', 'doc_suggestions', 'ui_control',
    'compacted',
  ]);

  /**
   * Check for background streams when switching to a session.
   * Called after history loads on session switch.
   */
  export function checkBackgroundStream(sessionId) {
    if (!sessionId || !_backgroundStreams.has(sessionId)) return;
    var entry = _backgroundStreams.get(sessionId);

    if (entry.status === 'completed') {
      // Response is already saved to DB and will appear in history — just clean up
      _backgroundStreams.delete(sessionId);
      return;
    }

    if (entry.status === 'error') {
      _backgroundStreams.delete(sessionId);
      // `P4-24`: this tab's reader lost its connection, but a resumed view was
      // showing the run over its own, and that view's reload is the record.
      if (entry.resumedView) return;
      var box = document.getElementById('chat-history');
      if (box) {
        var errHolder = document.createElement('div');
        errHolder.className = 'msg msg-ai';
        errHolder.innerHTML = '<div class="body"><i style="color: var(--color-error);">[Background stream encountered an error]</i></div>';
        box.appendChild(errHolder);
      }
      return;
    }

    if (entry.status === 'running') {
      // `P4-24`. A run this tab went on reading in the background is drawn the
      // way a run picked up after a reload is: replayed from the server's buffer,
      // from its first event, through the same drawing as the live stream. It
      // used to be one spinner saying "Response streaming in background", with
      // this tab's reader drawing whatever arrived after the return underneath
      // it, into state the history reload had already thrown away. Research
      // keeps its own progress view, so it keeps the spinner; so does a return
      // the replay cannot attach to (the run ended a moment ago, or the request
      // failed).
      if (_researchingStreamIds.has(sessionId)) {
        _showBackgroundStreamSpinner(sessionId);
        return;
      }
      entry.resumedView = true;
      resumeStream(sessionId, null, { besideBackgroundReader: true }).then((attached) => {
        if (!attached && !_resumingStreams.has(sessionId)) _showBackgroundStreamSpinner(sessionId);
      }, () => _showBackgroundStreamSpinner(sessionId));
    }
  }

  // Stream is still active — show a clean spinner, poll until done, then
  // reload history to show the final saved response. `P4-24`: the fallback for
  // a background run `resumeStream` could not replay.
  function _showBackgroundStreamSpinner(sessionId) {
    var entry = _backgroundStreams.get(sessionId);
    if (!entry) return;
    if (sessionModule.getCurrentSessionId && sessionModule.getCurrentSessionId() !== sessionId) return;
    var box = document.getElementById('chat-history');
    if (!box) return;

    // Replay any doc content that was streamed in the background
    if (entry._docTitle != null && documentModule) {
      documentModule.streamDocOpen(entry._docTitle, entry._docLang || '');
      if (entry._docContent) {
        documentModule.streamDocDelta(entry._docContent);
      }
    }

    var holder = document.createElement('div');
    holder.className = 'msg msg-ai';
    var meta = sessionModule.getSessions().find(function(s) { return s.id === sessionId; });
    var roleLabel = _shortModel(meta && meta.model);
    var roleTs = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
    holder.innerHTML = '<div class="role">' + uiModule.esc(roleLabel) + ' <span class="role-timestamp">' + roleTs + '</span></div><div class="body"></div>';
    _applyModelColor(holder.querySelector('.role'), meta && meta.model);

    var bodyDiv = holder.querySelector('.body');
    var spinner = spinnerModule.create('Response streaming in background', 'right');
    bodyDiv.appendChild(spinner.createElement());
    spinner.start();

    box.appendChild(holder);
    uiModule.scrollHistory();

    // Poll map until stream finishes, then reload history
    var pollId = setInterval(function() {
      if (sessionModule.getCurrentSessionId() !== sessionId) {
        clearInterval(pollId);
        spinner.destroy();
        if (holder.parentNode) holder.remove();
        return;
      }
      // Update doc content while polling
      var curPoll = _backgroundStreams.get(sessionId);
      if (curPoll && curPoll._docContent && documentModule) {
        documentModule.streamDocDelta(curPoll._docContent);
      }
      if (!curPoll || curPoll.status !== 'running') {
        clearInterval(pollId);
        spinner.destroy();
        if (holder.parentNode) holder.remove(); // Remove entire holder, not just spinner
        _backgroundStreams.delete(sessionId);
        // Reload session to show the completed response — but only if the user
        // is still on it; don't yank them back from a new chat they opened.
        if (sessionModule.getCurrentSessionId && sessionModule.getCurrentSessionId() === sessionId) {
          sessionModule.selectSession(sessionId);
        } else {
          sessionModule.loadSessions();
        }
      }
    }, 500);
  }

  // Tag short single-line code blocks with .pre-compact so the CSS can
  // render the Run/Edit/Copy buttons as a slim row that doesn't make a
  // 1-line bash block taller than its own contents.
  function _markCompactPre(pre) {
    const code = pre.querySelector('code');
    if (!code) return;
    const txt = code.textContent || '';
    // Count visible lines — ignore trailing newline (common with fenced
    // blocks) and treat any empty extra line as not a real second line.
    const lines = txt.replace(/\n+$/, '').split('\n');
    const compact = lines.length <= 1 && txt.length < 200;
    pre.classList.toggle('pre-compact', compact);
  }
  function _scanCompactPres(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll('pre').forEach(_markCompactPre);
  }
  // Global observer so any <pre> added anywhere in the app (chat stream,
  // chat re-renders, document library chat previews, slash commands,
  // research previews, etc.) gets tagged without each call site needing
  // to remember.
  (function _initCompactPreObserver() {
    if (window._cmpPreObserverWired) return;
    window._cmpPreObserverWired = true;
    _scanCompactPres(document.body);
    const obs = new MutationObserver((muts) => {
      for (const m of muts) {
        for (const n of m.addedNodes) {
          if (n.nodeType !== 1) continue;
          if (n.tagName === 'PRE') _markCompactPre(n);
          if (n.querySelectorAll) _scanCompactPres(n);
        }
      }
    });
    obs.observe(document.body, { childList: true, subtree: true });
  })();

  /**
   * Initialize event listeners
   */
  export function initListeners() {
    // Global event delegation for copy-code buttons
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('.copy-code');
      if (!btn) return;
      e.stopPropagation();
      const code = btn.getAttribute('data-code');
      if (code && uiModule) {
        uiModule.copyToClipboard(code);
        // Visual feedback: swap the icon to a checkmark (regular size)
        // and add .copied which the CSS uses to flash green + pulse.
        // For slim/.pre-compact buttons the label text comes from a
        // CSS ::before — swap it via data-state so we don't break the
        // text-button layout.
        const origHTML = btn.innerHTML;
        const isCompact = !!btn.closest('pre.pre-compact');
        if (!isCompact) {
          btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
        }
        btn.classList.add('copied');
        btn.dataset.state = 'copied';
        setTimeout(() => {
          if (!isCompact) btn.innerHTML = origHTML;
          btn.classList.remove('copied');
          delete btn.dataset.state;
        }, 1500);
      }
    });

    // Run code button delegation
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('.run-code');
      if (!btn) return;
      e.stopPropagation();
      if (codeRunnerModule) codeRunnerModule.run(btn);
    });

    // Edit code button delegation — toggle contentEditable on the code element
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('.edit-code');
      if (!btn) return;
      e.stopPropagation();
      const pre = btn.closest('pre');
      if (!pre) return;
      const codeEl = pre.querySelector('code');
      if (!codeEl) return;
      const isEditing = codeEl.contentEditable !== 'false' && codeEl.contentEditable !== 'inherit';
      if (isEditing) {
        // Save: exit edit mode, update data-code on copy/run buttons
        codeEl.contentEditable = 'false';
        codeEl.classList.remove('editing');
        pre.classList.remove('editing');
        const newCode = codeEl.textContent;
        const copyBtn = pre.querySelector('.copy-code');
        if (copyBtn) copyBtn.setAttribute('data-code', newCode);
        const runBtn = pre.querySelector('.run-code');
        if (runBtn) runBtn.setAttribute('data-code', newCode);
        // Swap icon back to pencil
        btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>';
        btn.title = 'Edit';
        btn.classList.remove('active');
      } else {
        // Enter edit mode. Firefox (especially on mobile) historically lacks
        // contentEditable="plaintext-only" — setting it there leaves the block
        // non-editable, so the tap "just gets a checkmark" with no way to type.
        // Fall back to "true" when plaintext-only didn't take.
        try { codeEl.contentEditable = 'plaintext-only'; } catch (_) { /* unsupported value */ }
        if (codeEl.contentEditable !== 'plaintext-only') codeEl.contentEditable = 'true';
        codeEl.classList.add('editing');
        pre.classList.add('editing');
        // preventScroll keeps the page from jumping to the codeblock when
        // focusing the editable on mobile — the browser would otherwise
        // scroll it into view above the keyboard, which reads as "auto-
        // scroll triggered by clicking Edit".
        try { codeEl.focus({ preventScroll: true }); } catch (_) { codeEl.focus(); }
        // Swap icon to checkmark
        btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
        btn.title = 'Done editing';
        btn.classList.add('active');
      }
    });

    // `P5-06`. Two workarounds used to live here, and both existed for one
    // reason: copy/edit/run were absolutely positioned over the first line of
    // the code block.
    //
    //   * a click on the code body toggled `.buttons-hidden`, so a reader on a
    //     phone could get the buttons off the text. It also meant tapping a
    //     code block made its controls disappear for no reason a first-time
    //     reader could see (`Law 15`);
    //   * a `mouseenter` handler measured the block against the viewport and
    //     flipped the buttons to the bottom when it sat high on screen. Its own
    //     comment records that this had to be disabled on mobile because the
    //     buttons moved out from under the finger reaching for them.
    //
    // The buttons are in `.code-block-header` now. They cover nothing, they do
    // not move, and neither workaround has anything left to do.

    // Tab suspension recovery: when user tabs back in, check if stream froze
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState !== 'visible') return;
      const active = _getForegroundStreamState();
      if (!active) return;

      // Stream claims to be running — check if reader is actually alive
      const staleSince = Date.now() - (active.lastActivity || _lastReaderActivity);
      if (staleSince < 20000) return; // Active recently, probably fine

      // Reader hasn't produced data in 5+ seconds after tab resume.
      // Give it a short grace period then recover.
      console.warn('[tab-recovery] Stream appears frozen (no activity for ' + Math.round(staleSince/1000) + 's). Recovering...');

      setTimeout(() => {
        // Re-check — maybe the reader woke up during the grace period
        const stillActive = _getForegroundStreamState();
        if (!stillActive) return;
        const stillStale = Date.now() - (stillActive.lastActivity || _lastReaderActivity);
        if (stillStale < 5000) return; // Came back to life

        console.warn('[tab-recovery] Stream confirmed dead. Aborting and reloading session.');

        // Abort the frozen stream, but preserve the visible bubble.
        if (stillActive.abortCtrl) {
          stillActive.abortCtrl._reason = 'recovery';
          stillActive.abortCtrl.abort();
        }
        try {
          const sid = sessionModule && sessionModule.getCurrentSessionId && sessionModule.getCurrentSessionId();
          if (sid) _activeStreams.delete(sid);
        } catch (_) {}
        _syncForegroundStreamGlobals();

        // Release Web Lock
        if (_webLockRelease) {
          _webLockRelease();
          _webLockRelease = null;
        }

        // Reset UI state
        var _submitBtn = document.querySelector('.send-btn');
        updateSubmitButton('idle', _submitBtn);
        var _msgInput = document.getElementById('message');
        if (_msgInput) _msgInput.disabled = false;
      }, 2000); // 2 second grace period
    });

    // On mobile, fade out welcome text when keyboard opens to prevent overlap
    if (window.innerWidth <= 768) {
      const msgInput = document.getElementById('message');
      if (msgInput) {
        msgInput.addEventListener('focus', () => {
          const ws = document.getElementById('welcome-screen');
          if (ws && !ws.classList.contains('hidden')) {
            ws.classList.add('kb-hidden');
          }
        });
        msgInput.addEventListener('blur', () => {
          const ws = document.getElementById('welcome-screen');
          if (ws && !ws.classList.contains('hidden')) {
            // Delay re-show so tapping within chatbox doesn't flash
            setTimeout(() => {
              if (document.activeElement !== msgInput) {
                ws.classList.remove('kb-hidden');
              }
            }, 200);
          }
        });
      }
      // Smooth viewport resize when keyboard opens/closes
      if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', () => {
          document.documentElement.style.setProperty('--vh', window.visualViewport.height + 'px');
        });
        document.documentElement.style.setProperty('--vh', window.visualViewport.height + 'px');
      }
    }

    // If the browser discarded and restored this tab, reload the current session
    // so the user sees the server-saved partial response instead of a blank page
    if (document.wasDiscarded) {
      console.warn('[tab-recovery] Tab was discarded by browser — reloading session');
      setTimeout(() => {
        var _sid = sessionModule && sessionModule.getCurrentSessionId();
        if (_sid) sessionModule.selectSession(_sid);
      }, 500);
    }
  }

  /**
   * Regenerate response: truncate history to the user message before this AI message,
   * then re-submit that user message.
   */
  /**
   * Edit a user message: show an input, truncate to before it, resubmit the edited text.
   */
  export async function editUserMessage(userMsgElement) {
    const box = document.getElementById('chat-history');
    const allMsgs = Array.from(box.querySelectorAll('.msg'));
    const msgIndex = allMsgs.indexOf(userMsgElement);
    if (msgIndex < 0) return;

    const bodyEl = userMsgElement.querySelector('.body');
    let currentText = (userMsgElement.dataset.raw || (bodyEl ? bodyEl.textContent : '') || '').trim();
    currentText = currentText.replace(/\s*\[\d+ attachment\(s\)\]$/, '');

    // Replace body with an editable textarea
    const editor = document.createElement('textarea');
    editor.className = 'edit-textarea';
    editor.value = currentText;
    editor.rows = Math.max(2, currentText.split('\n').length);

    const btnRow = document.createElement('div');
    btnRow.style.cssText = 'display:flex; gap:6px; margin-top:4px;';

    const saveBtn = document.createElement('button');
    saveBtn.className = 'edit-save-btn';
    saveBtn.textContent = 'Send';
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'edit-cancel-btn';
    cancelBtn.textContent = 'Cancel';
    btnRow.appendChild(saveBtn);
    btnRow.appendChild(cancelBtn);

    const originalHTML = bodyEl.innerHTML;
    bodyEl.innerHTML = '';
    bodyEl.appendChild(editor);
    bodyEl.appendChild(btnRow);
    editor.focus();

    cancelBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      bodyEl.innerHTML = originalHTML;
    });

    saveBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const newText = editor.value.trim();
      if (!newText) return;

      const sessionId = sessionModule.getCurrentSessionId();
      if (!sessionId) return;

      const keepCount = msgIndex;
      try {
        await fetch(`${API_BASE}/api/session/${sessionId}/truncate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ keep_count: keepCount })
        });

        // Remove DOM elements from msgIndex onward
        for (let i = allMsgs.length - 1; i >= msgIndex; i--) {
          allMsgs[i].remove();
        }

        // Submit the edited text
        const messageInput = uiModule.el('message');
        messageInput.value = newText;
        const submitBtn = document.querySelector('.send-btn');
        if (submitBtn) submitBtn.click();
      } catch (err) {
        console.error('Edit failed:', err);
        if (uiModule) uiModule.showError('Edit failed: ' + err.message);
        bodyEl.innerHTML = originalHTML;
      }
    });

    // Also submit on Enter (without shift)
    editor.addEventListener('keydown', (e) => {
      const isMobile = window.innerWidth <= 768

      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && !isMobile) {
        e.preventDefault();
        saveBtn.click();
      }
    });
  }

  /**
   * Resend a user message. Normal resend appends a fresh copy at the end of
   * the current thread; regenerate flows can opt into replacing from here.
   */
  export async function resendUserMessage(userMsgElement, opts = {}) {
    const replaceFromHere = Boolean(opts && opts.replaceFromHere);
    const box = document.getElementById('chat-history');
    const allMsgs = Array.from(box.querySelectorAll('.msg'));
    const msgIndex = allMsgs.indexOf(userMsgElement);
    if (msgIndex < 0) return;

    // Prefer dataset.raw (stripped original user text) over .body.textContent
    // — the latter slurps the rendered "View image description" collapsible
    // content too, which would then be sent back as the user's question and
    // the AI would reply to that gibberish instead of the actual prompt.
    const bodyEl = userMsgElement.querySelector('.body');
    let text = (userMsgElement.dataset.raw || (bodyEl ? bodyEl.textContent : '') || '').trim();
    text = text.replace(/\s*\[\d+ attachment\(s\)\]$/, '');

    // Collect file_ids attached to this user message so the resend re-carries
    // the photos / docs (and the chat handler picks up the user-edited OCR
    // text cached server-side under those file ids).
    const _attachEls = userMsgElement.querySelectorAll('[data-file-id]');
    let _ids = Array.from(_attachEls).map(el => el.dataset.fileId).filter(Boolean);
    if (!_ids.length) {
      const _imgs = userMsgElement.querySelectorAll('.attach-image-preview img, .attach-card img');
      for (const _im of _imgs) {
        const _m = (_im.getAttribute('src') || '').match(/\/api\/upload\/([A-Za-z0-9_\-]+)/);
        if (_m && _m[1] && !_ids.includes(_m[1])) _ids.push(_m[1]);
      }
    }

    // Rescue: legacy bubbles may have stored the filename as the message
    // content (artifact of earlier broken resends). Don't re-send that as
    // the user prompt if we still have the file attached. Loosen the regex
    // to cover real-world camera/screenshot names with spaces, parens,
    // multi-dots: "Screen Shot 2026-05-28 at 4.05.32 PM.png", "IMG (1).JPG".
    if (text && _ids.length && /^[^\n\r]{1,200}\.(png|jpe?g|gif|webp|svg|bmp|heic|heif)$/i.test(text)) {
      text = '';
    }
    // Empty text + no attachments → tell the user instead of silently bailing.
    // The common case is a regen during a pre-upload race where the bubble
    // never had an `[data-file-id]` to scrape.
    if (!text && !_ids.length) {
      if (uiModule?.showError) uiModule.showError('Nothing to resend — message has no text and no attachments yet (try again after the upload finishes).');
      return;
    }

    const sessionId = sessionModule.getCurrentSessionId();
    if (!sessionId) return;

    try {
      if (replaceFromHere) {
        // Regenerate flows intentionally trim history to this point before
        // resubmitting. The plain "Resend message" action must not do this.
        const keepCount = msgIndex;
        await fetch(`${API_BASE}/api/session/${sessionId}/truncate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ keep_count: keepCount })
        });

        // Drop the AI replies after the user message but KEEP the user bubble
        // itself (so its photo stays visible). Then suppress the new user
        // bubble that send would otherwise add — same pattern as regenerate.
        let sibling = userMsgElement.nextSibling;
        while (sibling) {
          const next = sibling.nextSibling;
          sibling.remove();
          sibling = next;
        }
        _hideUserBubble = true;
      }
      _pendingRegenAttachments = _ids;

      // Resubmit
      const messageInput = uiModule.el('message');
      messageInput.value = text;
      const submitBtn = document.querySelector('.send-btn');
      if (submitBtn) submitBtn.click();
    } catch (err) {
      console.error('Resend failed:', err);
      if (uiModule) uiModule.showError('Resend failed: ' + err.message);
    }
  }

  export async function regenerateFrom(aiMsgElement) {
    const box = document.getElementById('chat-history');
    const allMsgs = Array.from(box.querySelectorAll('.msg'));
    const aiIndex = allMsgs.indexOf(aiMsgElement);
    if (aiIndex < 0) return;

    // Find the preceding user message
    let userIndex = -1;
    let userText = '';
    let userMsgEl = null;
    for (let i = aiIndex - 1; i >= 0; i--) {
      if (allMsgs[i].classList.contains('msg-user')) {
        userIndex = i;
        userMsgEl = allMsgs[i];
        // Prefer dataset.raw (set by addMessage with the stripped, original
        // user text) over the rendered body's textContent — the latter
        // pulls in the "View image description" collapsible content too,
        // duplicating the OCR text on regen.
        const bodyEl = userMsgEl.querySelector('.body');
        userText = (userMsgEl.dataset.raw || (bodyEl ? bodyEl.textContent : '') || '').trim();
        userText = userText.replace(/\s*\[\d+ attachment\(s\)\]$/, '');
        break;
      }
    }

    if (userIndex < 0) {
      if (uiModule) uiModule.showError('Could not find the user message to regenerate');
      return;
    }

    // Collect any file_ids attached to the original user message so the
    // regenerated send re-uses them. Without this the AI is regenerated on
    // text alone — photos (and the user-edited OCR text cached server-side
    // under that file_id) would be silently dropped.
    const _attachEls = userMsgEl ? userMsgEl.querySelectorAll('[data-file-id]') : [];
    let _regenIds = Array.from(_attachEls).map(el => el.dataset.fileId).filter(Boolean);
    // Fallback for bubbles rendered before the data-file-id stamp landed:
    // sniff the file id straight out of any `.attach-image-preview img`
    // src URLs (matches /api/upload/<id>). Otherwise an older bubble would
    // regen with zero attachments and the photo would be lost from the
    // resulting message even though the file still exists on disk.
    if (!_regenIds.length && userMsgEl) {
      const _imgs = userMsgEl.querySelectorAll('.attach-image-preview img, .attach-card img');
      for (const _im of _imgs) {
        const _m = (_im.getAttribute('src') || '').match(/\/api\/upload\/([A-Za-z0-9_\-]+)/);
        if (_m && _m[1] && !_regenIds.includes(_m[1])) _regenIds.push(_m[1]);
      }
    }
    _pendingRegenAttachments = _regenIds;

    // Rescue: earlier-version regens (before the dataset.raw fix) stored the
    // photo's filename as the user-message content. On a follow-up regen,
    // that filename would be sent back as the literal user prompt, so the
    // AI thinks the question is "blue_night_preview.jpg" and replies "that's
    // an image file". If userText is just a bare image filename and we have
    // attachments, drop it so the OCR text (or the image bytes for vision
    // models) is what the model actually sees.
    if (userText && _pendingRegenAttachments.length &&
        /^[^\n\r]{1,200}\.(png|jpe?g|gif|webp|svg|bmp|heic|heif)$/i.test(userText.trim())) {
      userText = '';
    }

    // A photo-only message has empty user text — regen must still proceed,
    // because the attachments themselves are the message. Bail only if there
    // is no text AND no attachments to send.
    if (!userText && !_pendingRegenAttachments.length) {
      if (uiModule) uiModule.showError('Nothing to regenerate — the user message has no text and no attachments');
      return;
    }

    const sessionId = sessionModule.getCurrentSessionId();
    if (!sessionId) return;

    // Save current response as a variant
    const oldRaw = aiMsgElement.dataset.raw || aiMsgElement.querySelector('.body')?.textContent || '';
    const oldHtml = aiMsgElement.querySelector('.body')?.innerHTML || '';
    let variants = [];
    try { variants = JSON.parse(aiMsgElement.dataset.variants || '[]'); } catch(_) {}
    if (variants.length === 0) {
      // First regen — save the original as variant 0
      variants.push({ raw: oldRaw, html: oldHtml, label: 'original' });
    }

    const keepCount = userIndex;

    try {
      await fetch(`${API_BASE}/api/session/${sessionId}/truncate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keep_count: keepCount })
      });

      for (let i = allMsgs.length - 1; i > aiIndex; i--) {
        allMsgs[i].remove();
      }

      // Remove the AI message from DOM — it will be replaced by the new streaming response
      // But first, stash the variants data so we can transfer it to the new element
      _pendingVariants = variants;
      _pendingVariantLabel = 'regen';
      aiMsgElement.remove();

      _hideUserBubble = true;
      const messageInput = uiModule.el('message');
      messageInput.value = userText;
      const submitBtn = document.querySelector('.send-btn');
      if (submitBtn) submitBtn.click();

    } catch (err) {
      console.error('Regenerate failed:', err);
      if (uiModule) uiModule.showError('Regenerate failed: ' + err.message);
    }
  }

  // Pending variants from a regeneration — transferred to new streaming element
  let _pendingVariants = null;
  let _pendingVariantLabel = null;
  // File-ids carried over from the original user message during a regen, so
  // photos / OCR overrides survive into the new send. Consumed once.
  let _pendingRegenAttachments = null;

  /**
   * Called after streaming completes to attach variant navigation if this was a regen.
   */
  function _attachVariantNav(msgElement) {
    if (!_pendingVariants) return;
    const variants = _pendingVariants;
    _pendingVariants = null;

    // Add the new response as the latest variant
    const newRaw = msgElement.dataset.raw || msgElement.querySelector('.body')?.textContent || '';
    const newHtml = msgElement.querySelector('.body')?.innerHTML || '';
    const varLabel = _pendingVariantLabel || 'regen';
    _pendingVariantLabel = null;
    variants.push({ raw: newRaw, html: newHtml, label: varLabel });

    msgElement.dataset.variants = JSON.stringify(variants);
    msgElement.dataset.variantIndex = String(variants.length - 1);

    _renderVariantNav(msgElement, variants, variants.length - 1);

    // Persist variants to server
    const sid = sessionModule.getCurrentSessionId();
    if (sid) {
      fetch(`${API_BASE}/api/session/${sid}/update-last-meta`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ metadata: { variants: variants, variantIndex: variants.length - 1 } })
      }).catch(e => console.warn('update-last-meta (variants) failed:', e));
    }
  }

  const _VARIANT_ICONS = { regen: '\u21BB', shorter: '\u2702', simpler: '?', original: '\u25CB' };
  function _variantTagText(label) {
    return _VARIANT_ICONS[label] || _VARIANT_ICONS['original'];
  }

  function _renderVariantNav(msgElement, variants, currentIdx) {
    // Remove existing nav if any
    const old = msgElement.querySelector('.variant-nav');
    if (old) old.remove();

    if (variants.length < 2) return;

    const nav = document.createElement('span');
    nav.className = 'variant-nav';
    nav.addEventListener('click', (e) => e.stopPropagation());

    // Label showing what this variant is
    // Divider
    const divider = document.createElement('span');
    divider.className = 'variant-divider';
    divider.textContent = '|';
    nav.appendChild(divider);

    // Label
    const curVariant = variants[currentIdx];
    const tagLabel = document.createElement('span');
    tagLabel.className = 'variant-tag' + (curVariant?.label === 'shorter' ? ' variant-tag-scissors' : '');
    tagLabel.textContent = _variantTagText(curVariant?.label);
    nav.appendChild(tagLabel);

    // < button
    const prevBtn = document.createElement('button');
    prevBtn.className = 'variant-btn';
    prevBtn.textContent = '<';
    prevBtn.disabled = currentIdx === 0;
    prevBtn.addEventListener('click', (e) => { e.stopPropagation(); _switchVariant(msgElement, variants, currentIdx - 1); });
    nav.appendChild(prevBtn);

    // Clickable number for current index (click left number = go left, right = go right)
    const numLeft = document.createElement('button');
    numLeft.className = 'variant-num';
    numLeft.textContent = String(currentIdx + 1);
    numLeft.disabled = currentIdx === 0;
    numLeft.addEventListener('click', (e) => { e.stopPropagation(); _switchVariant(msgElement, variants, currentIdx - 1); });
    nav.appendChild(numLeft);

    const slash = document.createElement('span');
    slash.className = 'variant-slash';
    slash.textContent = '/';
    nav.appendChild(slash);

    const numRight = document.createElement('button');
    numRight.className = 'variant-num';
    numRight.textContent = String(variants.length);
    numRight.disabled = currentIdx === variants.length - 1;
    numRight.addEventListener('click', (e) => { e.stopPropagation(); _switchVariant(msgElement, variants, currentIdx + 1); });
    nav.appendChild(numRight);

    // > button
    const nextBtn = document.createElement('button');
    nextBtn.className = 'variant-btn';
    nextBtn.textContent = '>';
    nextBtn.disabled = currentIdx === variants.length - 1;
    nextBtn.addEventListener('click', (e) => { e.stopPropagation(); _switchVariant(msgElement, variants, currentIdx + 1); });
    nav.appendChild(nextBtn);

    // Insert into the .role header
    const roleEl = msgElement.querySelector('.role');
    if (roleEl) {
      roleEl.appendChild(nav);
    } else {
      msgElement.appendChild(nav);
    }
  }

  function _switchVariant(msgElement, variants, newIdx) {
    if (newIdx < 0 || newIdx >= variants.length) return;
    const v = variants[newIdx];
    const body = msgElement.querySelector('.body');
    if (body) body.innerHTML = v.html;
    msgElement.dataset.raw = v.raw;
    msgElement.dataset.variantIndex = String(newIdx);
    if (window.hljs) {
      msgElement.querySelectorAll('pre code').forEach(block => window.hljs.highlightElement(block));
    }
    _renderVariantNav(msgElement, variants, newIdx);

    // Persist selected variant to server
    const sid = sessionModule.getCurrentSessionId();
    if (sid) {
      fetch(`${API_BASE}/api/session/${sid}/update-last-meta`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ metadata: { variantIndex: newIdx } })
      }).catch(e => console.warn('update-last-meta (variantIndex) failed:', e));
    }
  }

  export async function forkFrom(aiMsgElement) {
    const box = document.getElementById('chat-history');
    const allMsgs = Array.from(box.querySelectorAll('.msg'));
    const aiIndex = allMsgs.indexOf(aiMsgElement);
    if (aiIndex < 0) return;

    const sessionId = sessionModule.getCurrentSessionId();
    if (!sessionId) return;

    const keepCount = aiIndex + 1;

    try {
      const res = await fetch(`${API_BASE}/api/session/${sessionId}/fork`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keep_count: keepCount }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      await sessionModule.loadSessions();
      await sessionModule.selectSession(data.id);
      if (uiModule) uiModule.showToast(`Forked → ${data.name}`);
    } catch (err) {
      console.error('Fork failed:', err);
      if (uiModule) uiModule.showError('Fork failed: ' + err.message);
    }
  }

  /**
   * Check for pending/completed research after page refresh or session switch.
   * If research is still running, show a spinner and poll until done.
   * If research is done, fetch result and render it.
   */
  export async function checkPendingResearch(sessionId) {
    if (!sessionId) return;
    try {
      const res = await fetch(`${API_BASE}/api/research/status/${sessionId}`);
      if (!res.ok) {
        if (sessionModule && sessionModule.clearResearching) sessionModule.clearResearching(sessionId);
        return; // 404 = no research for this session
      }
      const data = await res.json();

      if (data.status === 'done') {
        // Fetch and render the completed result
        _notifyResearchComplete(sessionId, data.query || '');
        if (sessionModule && sessionModule.clearResearching) sessionModule.clearResearching(sessionId);
        const resultRes = await fetch(`${API_BASE}/api/research/result/${sessionId}`, { method: 'POST' });
        if (resultRes.ok) {
          const resultData = await resultRes.json();
          if (resultData.result) {
            // Skip if history already has a research message for this session
            if (document.querySelector(`#chat-history .msg-ai[data-research-session="${sessionId}"]`)) return;

            var srcBox = '';
            if (resultData.sources && resultData.sources.length > 0) {
              srcBox = _buildSourcesBox(resultData.sources, 'research');
            }
            var findingsBox = chatRenderer.buildFindingsBox(resultData.raw_findings);
            var cleanResult = resultData.result;
            // Build DOM directly to avoid double-processing through addMessage
            chatRenderer.hideWelcomeScreen();
            var _box = document.getElementById('chat-history');
            if (_box) {
              var _wrap = document.createElement('div');
              _wrap.className = 'msg msg-ai';
              _wrap.dataset.researchSession = sessionId;
              var _role = document.createElement('div');
              _role.className = 'role';
              var _meta = sessionModule.getSessions().find(function(s) { return s.id === sessionId; });
              _role.textContent = _shortModel(_meta?.model);
              _applyModelColor(_role, _meta?.model);
              _role.appendChild(chatRenderer.roleTimestamp());
              var _body = document.createElement('div');
              _body.className = 'body';
              _body.innerHTML = srcBox + markdownModule.processWithThinking(
                markdownModule.squashOutsideCode(cleanResult)
              ) + findingsBox;
              _wrap.dataset.raw = cleanResult;
              _wrap.appendChild(_role);
              _wrap.appendChild(_body);
              _wrap.appendChild(chatRenderer.createMsgFooter(_wrap));
              _appendViewReportLink(_wrap, sessionId);
              _box.appendChild(_wrap);
              if (window.hljs) _wrap.querySelectorAll('pre code').forEach(function(b) { window.hljs.highlightElement(b); });
              uiModule.scrollHistory();
            }
          }
        }
        return;
      }

      if (data.status !== 'running') return;

      // Don't show reconnect UI if we've already switched away
      if (sessionModule.getCurrentSessionId() !== sessionId) return;

      // Research is still running — show reconnect UI with spinner
      const box = document.getElementById('chat-history');
      if (!box) return;

      const holder = document.createElement('div');
      holder.className = 'msg msg-ai research-reconnect';
      holder.dataset.researchSession = sessionId;
      const roleTs = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
      const agentMeta = sessionModule.getSessions().find(s => s.id === sessionModule.getCurrentSessionId());
      const agentModelLabel = _shortModel(agentMeta?.model);
      holder.innerHTML = `<div class="role">${uiModule.esc(agentModelLabel)} <span class="role-timestamp">${roleTs}</span></div><div class="body"></div>`;
      _applyModelColor(holder.querySelector('.role'), agentMeta?.model);
      box.appendChild(holder);

      const bodyDiv = holder.querySelector('.body');
      const spinner = spinnerModule.create('Reconnecting to research...', 'right');
      bodyDiv.appendChild(spinner.createElement());
      spinner.start();

      // Update spinner with current progress if available
      function updateSpinnerFromProgress(progress) {
        if (!progress || !progress.phase) return;
        const rp = progress;
        if (rp.phase === 'probing') {
          spinner.updateMessage(`Verifying model: ${rp.model || '?'}`);
        } else if (rp.phase === 'planning') {
          spinner.updateMessage('Analyzing question & planning research strategy');
        } else if (rp.phase === 'searching') {
          const q = rp.queries ? `${rp.queries} queries` : '';
          const s = rp.total_sources ? ` · ${rp.total_sources} sources` : '';
          spinner.updateMessage(`Round ${rp.round || '?'}: Searching${q ? ' (' + q + ')' : ''}${s}`);
        } else if (rp.phase === 'reading') {
          spinner.updateMessage(rp.title ? `Reading: ${rp.title}` : `Round ${rp.round || '?'}: Reading ${rp.new_sources || ''} pages · ${rp.total_sources || 0} sources total`);
        } else if (rp.phase === 'analyzing') {
          spinner.updateMessage(`Round ${rp.round || '?'}: Analyzing ${rp.total_findings || 0} findings`);
        } else if (rp.phase === 'writing') {
          spinner.updateMessage(`Writing report · ${rp.total_sources || 0} sources`);
        }
      }

      updateSpinnerFromProgress(data.progress);
      _researchingStreamIds.add(sessionId);
      if (sessionModule && sessionModule.markResearching) sessionModule.markResearching(sessionId);

      // Restore research timer from started_at
      if (data.started_at && spinner && spinner.element) {
        _researchStartTime = data.started_at * 1000;
        _researchAvgDuration = data.avg_duration || null;
        _researchTimerEl = document.createElement('div');
        _researchTimerEl.className = 'research-timer';
        _researchTimerEl.style.cssText = 'font-size:0.8em; opacity:0.6; margin-top:4px; font-family:monospace;';
        spinner.element.parentNode.insertBefore(_researchTimerEl, spinner.element.nextSibling);
        _researchTimerInterval = setInterval(() => {
          if (!_researchTimerEl) return;
          var elapsed = Math.floor((Date.now() - _researchStartTime) / 1000);
          var mm = String(Math.floor(elapsed / 60)).padStart(2, '0');
          var ss = String(elapsed % 60).padStart(2, '0');
          var txt = mm + ':' + ss;
          if (_researchAvgDuration) {
            var avgM = String(Math.floor(_researchAvgDuration / 60)).padStart(2, '0');
            var avgS = String(Math.round(_researchAvgDuration % 60)).padStart(2, '0');
            txt += ' / avg ' + avgM + ':' + avgS;
          }
          _researchTimerEl.textContent = txt;
        }, 1000);
        // Reconnect synapse — seed it with whatever progress is already known
        try {
          _researchSynapse = createResearchSynapse(spinner.element.parentNode, {
            query: data.query || '',
            startedAt: _researchStartTime,
          });
          if (_researchSynapse.element && _researchTimerEl) {
            spinner.element.parentNode.insertBefore(_researchSynapse.element, _researchTimerEl);
          }
          if (data.progress) {
            _researchSynapse.setPhase(data.progress.phase, data.progress);
            if (typeof data.progress.round === 'number') _researchSynapse.setRound(data.progress.round);
            if (typeof data.progress.total_sources === 'number') _researchSynapse.setSourceCount(data.progress.total_sources);
          }
        } catch (e) { console.warn('synapse reconnect failed', e); }
      }

      // Poll for completion
      const pollInterval = setInterval(async () => {
        // Stop polling if user switched to a different session
        if (sessionModule.getCurrentSessionId() !== sessionId) {
          clearInterval(pollInterval);
          spinner.destroy();
          _clearResearchTimer();
          if (holder.parentNode) holder.remove();
          _researchingStreamIds.delete(sessionId);
          if (_researchingStreamIds.size === 0) {
            var _rToggleP = document.getElementById('research-toggle-btn');
            if (_rToggleP) _rToggleP.classList.remove('research-running');
          }
          return;
        }
        try {
          const pollRes = await fetch(`${API_BASE}/api/research/status/${sessionId}`);
          if (!pollRes.ok) {
            clearInterval(pollInterval);
            spinner.destroy();
            _clearResearchTimer();
            _researchingStreamIds.delete(sessionId);
            if (sessionModule && sessionModule.clearResearching) sessionModule.clearResearching(sessionId);
            return;
          }
          const pollData = await pollRes.json();
          updateSpinnerFromProgress(pollData.progress);
          if (_researchSynapse && pollData.progress) {
            _researchSynapse.setPhase(pollData.progress.phase, pollData.progress);
            if (typeof pollData.progress.round === 'number') _researchSynapse.setRound(pollData.progress.round);
            if (typeof pollData.progress.total_sources === 'number') _researchSynapse.setSourceCount(pollData.progress.total_sources);
          }

          if (pollData.status !== 'running') {
            clearInterval(pollInterval);
            spinner.destroy();
            _clearResearchTimer();
            _researchingStreamIds.delete(sessionId);
            if (sessionModule && sessionModule.clearResearching) sessionModule.clearResearching(sessionId);

            if (pollData.status === 'done') {
              _notifyResearchComplete(sessionId, data.query || '');
              const rRes = await fetch(`${API_BASE}/api/research/result/${sessionId}`, { method: 'POST' });
              if (rRes.ok) {
                const rData = await rRes.json();
                if (rData.result) {
                  var srcHtml = '';
                  if (rData.sources && rData.sources.length > 0) {
                    srcHtml = _buildSourcesBox(rData.sources, 'research');
                  }
                  var findingsHtml = chatRenderer.buildFindingsBox(rData.raw_findings);
                  bodyDiv.innerHTML = srcHtml + markdownModule.processWithThinking(
                    markdownModule.squashOutsideCode(rData.result)
                  ) + findingsHtml;
                  holder.dataset.raw = rData.result;
                  _appendViewReportLink(holder, sessionId);
                  if (window.hljs) {
                    holder.querySelectorAll('pre code').forEach(b => window.hljs.highlightElement(b));
                  }
                }
              }
            } else {
              bodyDiv.innerHTML = '<i style="color: var(--color-error);">[Research ' + pollData.status + ']</i>';
            }
          }
        } catch (e) {
          console.error('Research poll error:', e);
        }
      }, 2000);
    } catch (e) {
      // No research pending, that's fine
    }
  }

  /** Set a display override for the next user message bubble */
  export function setDisplayOverride(text) {
    _displayOverride = text;
  }

  /** Hide the user bubble for the next submit (e.g. continue after stop) */
  export function setHideUserBubble() {
    _hideUserBubble = true;
  }

  /** Set the AI element to merge with the next streamed response (continue after stop).
   *  `B941`: `{ steps: true }` when the next response carries on an agent run's
   *  steps (Continue ▸ after the step limit) — see `_joinContinuedSteps`. */
  export function setPendingContinue(el, opts = {}) {
    _pendingContinue = el;
    _pendingContinueSteps = !!(opts && opts.steps);
  }

  /**
   * Delete an AI message and its preceding user message from the conversation.
   */
  export async function deleteMessage(msgElement) {
    if (uiModule && uiModule.styledConfirm) {
      const ok = await uiModule.styledConfirm('Delete this message?', {
        confirmText: 'Delete',
        cancelText: 'Cancel',
        danger: true,
      });
      if (!ok) return;
    }

    const box = document.getElementById('chat-history');
    const allMsgs = Array.from(box.querySelectorAll('.msg'));
    const clickedIndex = allMsgs.indexOf(msgElement);
    if (clickedIndex < 0) return;

    // No early-out on a missing session: an output shown before any model was
    // selected (issue #1428) has no session/persisted rows, but its "x" must
    // still remove it. We only need the session id for the server-side delete
    // below; without one we fall back to removing the DOM.
    const sessionId = sessionModule.getCurrentSessionId();

    const clickedIsUser = msgElement.classList.contains('msg-user');

    // Find the user+AI pair
    let userIndex = -1;
    let aiIndex = -1;
    if (clickedIsUser) {
      userIndex = clickedIndex;
      // Find the following AI message
      for (let i = clickedIndex + 1; i < allMsgs.length; i++) {
        if (allMsgs[i].classList.contains('msg-ai') && !allMsgs[i].classList.contains('msg-continuation')) {
          aiIndex = i;
          break;
        }
        if (allMsgs[i].classList.contains('msg-user')) break; // next user msg, no AI response
      }
    } else {
      // If clicked on a continuation, walk back to the main AI message
      let mainAiIndex = clickedIndex;
      if (allMsgs[mainAiIndex].classList.contains('msg-continuation')) {
        for (let i = mainAiIndex - 1; i >= 0; i--) {
          if (allMsgs[i].classList.contains('msg-ai') && !allMsgs[i].classList.contains('msg-continuation')) {
            mainAiIndex = i;
            break;
          }
        }
      }
      aiIndex = mainAiIndex;
      // Find the preceding user message
      for (let i = aiIndex - 1; i >= 0; i--) {
        if (allMsgs[i].classList.contains('msg-user')) {
          userIndex = i;
          break;
        }
      }
    }

    // Collect DB message IDs and DOM elements to remove
    const msgIds = [];
    const domToRemove = [];

    // Add the user message if found
    if (userIndex >= 0) {
      domToRemove.push(allMsgs[userIndex]);
      const uid = allMsgs[userIndex].dataset.dbId;
      if (uid) msgIds.push(uid);
    }

    // Add the AI message if found
    if (aiIndex >= 0) {
      domToRemove.push(allMsgs[aiIndex]);
      const aid = allMsgs[aiIndex].dataset.dbId;
      if (aid) msgIds.push(aid);

      const aiEl = allMsgs[aiIndex];
      // Also remove agent-thread elements BETWEEN user and AI
      if (userIndex >= 0) {
        let between = allMsgs[userIndex].nextElementSibling;
        while (between && between !== aiEl) {
          domToRemove.push(between);
          between = between.nextElementSibling;
        }
      }
      // Walk forward from the AI element to remove continuations and tool bubbles
      let sibling = aiEl.nextElementSibling;
      while (sibling) {
        if (sibling.classList.contains('msg-user') ||
            (sibling.classList.contains('msg-ai') && !sibling.classList.contains('msg-continuation'))) {
          break;
        }
        domToRemove.push(sibling);
        sibling = sibling.nextElementSibling;
      }
    }

    if (!msgIds.length || !sessionId) {
      // No persisted rows to delete (no DB IDs, or no session at all — e.g. an
      // error output shown before a model was selected, #1428). Just remove the
      // DOM so the "x" works regardless.
      domToRemove.forEach(el => el.remove());
      if (uiModule) uiModule.showToast('Message deleted');
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/api/session/${sessionId}/delete-messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ msg_ids: msgIds })
      });
      if (!res.ok) throw new Error('Server error ' + res.status);
      domToRemove.forEach(el => el.remove());
      if (uiModule) uiModule.showToast('Message deleted');
    } catch (err) {
      console.error('Delete failed:', err);
      if (uiModule) uiModule.showError('Delete failed: ' + err.message);
    }
  }

  /**
   * Edit an AI message inline. Makes the body contentEditable, saves to DB on confirm.
   */
  export async function editAIMessage(msgElement) {
    const body = msgElement.querySelector('.body');
    if (!body) return;

    const isEditing = body.contentEditable === 'true' || body.contentEditable === 'plaintext-only';
    if (isEditing) return; // already editing

    const originalRaw = msgElement.dataset.raw || body.textContent || '';

    // Create editable textarea overlay
    const textarea = document.createElement('textarea');
    textarea.className = 'msg-edit-textarea';
    textarea.value = originalRaw;
    textarea.style.width = '100%';
    textarea.style.minHeight = Math.max(100, body.offsetHeight) + 'px';
    body.style.display = 'none';
    body.parentNode.insertBefore(textarea, body.nextSibling);
    textarea.focus();

    // Add save/cancel bar
    const bar = document.createElement('div');
    bar.className = 'msg-edit-bar';
    const saveBtn = document.createElement('button');
    saveBtn.className = 'msg-edit-save';
    saveBtn.textContent = 'Save';
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'msg-edit-cancel';
    cancelBtn.textContent = 'Cancel';
    bar.appendChild(saveBtn);
    bar.appendChild(cancelBtn);
    textarea.parentNode.insertBefore(bar, textarea.nextSibling);

    function cleanup() {
      textarea.remove();
      bar.remove();
      body.style.display = '';
    }

    cancelBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      cleanup();
    });

    saveBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const newContent = textarea.value;
      if (newContent === originalRaw) { cleanup(); return; }

      const msgId = msgElement.dataset.dbId;
      if (!msgId) { if (uiModule) uiModule.showError('Cannot edit: message ID not found'); cleanup(); return; }

      const sessionId = sessionModule.getCurrentSessionId();
      if (!sessionId) { cleanup(); return; }

      try {
        const res = await fetch(`${API_BASE}/api/session/${sessionId}/edit-message`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ msg_id: msgId, content: newContent }),
        });
        if (!res.ok) throw new Error('Server error ' + res.status);

        // Re-render body with markdown
        body.innerHTML = markdownModule.processWithThinking(markdownModule.squashOutsideCode(newContent));
        msgElement.dataset.raw = newContent;

        // Add edited indicator if not already present
        if (!msgElement.querySelector('.edited-indicator')) {
          const indicator = document.createElement('div');
          indicator.className = 'edited-indicator';
          indicator.textContent = '[Message edited]';
          body.parentNode.insertBefore(indicator, body.nextSibling);
        }

        cleanup();
        if (uiModule) uiModule.showToast('Message edited');
      } catch (err) {
        console.error('Edit failed:', err);
        if (uiModule) uiModule.showError('Edit failed: ' + err.message);
      }
    });
  }

  /**
   * Rewrite the AI's last response with a specific instruction.
   * Uses the lightweight /api/rewrite endpoint — no tools, no agent loop.
   * Just rewrites the text of the last AI bubble.
   */
  export async function rewriteWith(aiMsgElement, instruction) {
    const sessionId = sessionModule.getCurrentSessionId();
    if (!sessionId) return;

    // Get the original text from the AI bubble
    const oldRaw = aiMsgElement.dataset.raw || aiMsgElement.querySelector('.body')?.textContent || '';
    const oldHtml = aiMsgElement.querySelector('.body')?.innerHTML || '';

    if (!oldRaw.trim()) {
      if (uiModule) uiModule.showError('No text to rewrite');
      return;
    }

    // Save current response as a variant
    let variants = [];
    try { variants = JSON.parse(aiMsgElement.dataset.variants || '[]'); } catch(_) {}
    if (variants.length === 0) {
      variants.push({ raw: oldRaw, html: oldHtml, label: 'original' });
    }

    // Determine label from instruction
    let varLabel = 'rewrite';
    if (instruction.includes('shorter')) varLabel = 'shorter';
    else if (instruction.includes('simpler')) varLabel = 'simpler';

    // Clear the bubble and show a whirlpool spinner while we wait for the
    // rewrite (replaces the old "Rewriting..." text).
    const bodyEl = aiMsgElement.querySelector('.body');
    let _rwSpin = null;
    if (bodyEl) {
      bodyEl.innerHTML = '';
      _rwSpin = spinnerModule.createWhirlpool(18);
      _rwSpin.element.style.margin = '4px 0';
      bodyEl.appendChild(_rwSpin.element);
    }
    // Stop + detach the spinner (called once real content starts rendering, and
    // on the failure path so it never spins forever).
    const _killRwSpin = () => { if (_rwSpin) { try { _rwSpin.destroy(); } catch (_) {} _rwSpin = null; } };

    try {
      const res = await fetch(`${API_BASE}/api/rewrite`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          original_text: oldRaw,
          instruction: instruction,
        }),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let newText = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const payload = line.slice(6).trim();
          if (payload === '[DONE]') continue;
          try {
            const data = JSON.parse(payload);
            // The endpoint streams `event: error\ndata: {error,status}` on
            // failure — surface it instead of silently hanging on "Rewriting…".
            if (data.error) {
              throw new Error(data.error || ('HTTP ' + (data.status || 500)));
            }
            // Reasoning tokens (vLLM --reasoning-parser: Qwen3 / DeepSeek-R1)
            // arrive as separate {delta, thinking:true} chunks. They are NOT
            // the rewrite — fold them away so they don't pollute the result.
            if (data.thinking) continue;
            if (data.delta) {
              newText += data.delta;
              _killRwSpin();
              if (bodyEl) {
                bodyEl.innerHTML = markdownModule.processWithThinking(
                  markdownModule.squashOutsideCode(newText)
                );
              }
            }
          } catch (e) {
            if (e instanceof Error && e.message) throw e;  // re-throw real errors
            /* ignore JSON parse noise */
          }
        }
      }

      // Strip any thinking markup from the answer. A reasoning model may emit
      // an inline <think>…</think> block, a bare </think> (no opener), or — when
      // its reasoning came via reasoning_content — a stray leading <think> that
      // never closes (so it would otherwise hide the whole answer). Peel all of
      // those off so what's left is just the rewritten text.
      const _stripThink = (t) => {
        t = markdownModule.normalizeThinkingMarkup(t || '');
        t = t.replace(/<(?:think(?:ing)?|thought)(?:\s+[^>]*)?>[\s\S]*?<\/(?:think(?:ing)?|thought)>/gi, '');   // complete blocks
        if (/<\/(?:think(?:ing)?|thought)>/i.test(t)) t = t.replace(/^[\s\S]*?<\/(?:think(?:ing)?|thought)>/i, '');  // reasoning w/o opener
        return t.replace(/<\/?(?:think(?:ing)?|thought)(?:\s+[^>]*)?>/gi, '').trim();        // any orphan tag
      };
      newText = _stripThink(newText);

      // Nothing left after stripping (or an empty stream) → real failure, not a
      // blank bubble.
      if (!newText.trim()) {
        throw new Error('model returned no rewritten text');
      }

      // Update the element's raw text
      if (newText) {
        aiMsgElement.dataset.raw = newText;
        // Final render with proper markdown
        if (bodyEl) {
          bodyEl.innerHTML = markdownModule.processWithThinking(
            markdownModule.squashOutsideCode(newText)
          );
        }

        // Save the new response as a variant
        variants.push({ raw: newText, html: bodyEl ? bodyEl.innerHTML : '', label: varLabel });
        aiMsgElement.dataset.variants = JSON.stringify(variants);
        aiMsgElement.dataset.variantIndex = String(variants.length - 1);

        // Persist variant metadata to server
        try {
          await fetch(`${API_BASE}/api/session/${sessionId}/update-last-meta`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ metadata: { variants: variants, variantIndex: variants.length - 1 } }),
          });
        } catch (_) {}

        // Re-render variant navigation
        _renderVariantNav(aiMsgElement, variants, variants.length - 1);
      }

      if (uiModule) uiModule.scrollHistory();

    } catch (err) {
      console.error('Rewrite failed:', err);
      _killRwSpin();
      // Restore original content on failure
      if (bodyEl) bodyEl.innerHTML = oldHtml;
      if (uiModule) uiModule.showError('Rewrite failed: ' + err.message);
    }
  }

  /**
   * Continue the AI's response from where it left off.
   */
  export async function continueFrom(aiMsgElement) {
    const sessionId = sessionModule.getCurrentSessionId();
    if (!sessionId) return;

    const messageInput = uiModule.el('message');
    if (messageInput) {
      messageInput.value = 'Continue from where you left off.';
      const submitBtn = document.querySelector('.send-btn');
      if (submitBtn) submitBtn.click();
    }
  }

  // Open a chat attachment in the right place: images → Gallery editor; PDFs &
  // text/code/markdown → Documents viewer; anything else → raw file. A given
  // upload's imported document is reused (cached by upload id) so clicking it
  // again re-opens the same doc instead of making duplicates.
  const _attachDocCache = new Map();  // upload id -> doc id

  /**
   * `B232`/`B233`. POST one container file and get back the Document the
   * server extracted from it.
   *
   * One helper, two callers — the composer's import banner and
   * `openAttachment` below — because they were about to grow two copies of the
   * same three lines, and a container that imports one way from the banner and
   * another way from the chip is the `Law 13` this row is (`B233` measured
   * exactly that: a `.doc` emailed to you produced prose and the same `.doc`
   * dragged into the library produced its OLE2 bytes).
   *
   * Two routes because there are two extractors, not because there are two
   * policies: `.pdf` goes to `import-pdf`, which also does AcroForm detection
   * and picks the form-backed or the page-image document kind, and everything
   * in `OFFICE_EXTS` goes to `import-office`, which runs
   * `markitdown_runtime.convert_to_markdown`. The server refuses with a reason
   * (415 for a format nothing reads, 422 for a container with no text in it),
   * and the reason is what reaches the caller's error.
   */
  async function _importFileAsDocument(file, name, sessionId) {
    const isPdf = /\.pdf$/i.test(name || '');
    const route = isPdf ? 'import-pdf' : 'import-office';
    const fd = new FormData();
    fd.append('file', file, name || (isPdf ? 'document.pdf' : 'document'));
    if (sessionId) fd.append('session_id', sessionId);
    const res = await fetch(`${API_BASE}/api/documents/${route}`, {
      method: 'POST', body: fd, credentials: 'same-origin',
    });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try { const j = await res.json(); detail = j.detail || j.error || detail; } catch (_) {}
      throw new Error(detail);
    }
    return res.json();
  }

  /**
   * `B232`. What the server says this upload is, asked rather than guessed.
   *
   * A `HEAD` — the route registers GET and Starlette adds HEAD to it, and
   * `FileResponse` sends the headers without the body — so asking costs one
   * round trip and zero bytes, where the two regexes this replaces cost a
   * wrong answer for `.kt`, `.toml`, `.markdown`, `.rst`, `.swift` and every
   * other text file no register happens to name.
   *
   * Falls back to `ingestKindFromName`, which is the same derivation minus the
   * half only the bytes can answer, whenever the header is missing — a cached
   * response, an older server, a network that refused the HEAD. That fallback
   * is strictly wider than the regex it replaces and never narrower, so the
   * degraded path is still an improvement on the tree this row found.
   */
  async function _uploadKind(url, name, mime) {
    try {
      const res = await fetch(url, { method: 'HEAD', credentials: 'same-origin' });
      const kind = res.ok && res.headers.get('X-Upload-Kind');
      if (kind) return kind;
    } catch (_) { /* fall through to the name-only derivation */ }
    return ingestKindFromName(name, mime);
  }
  // `B161`. A FOURTH extension→language map lived here — 29 entries, in the
  // path that opens an attachment as a document — and the row that found the
  // other three did not count it. Measured before it went: it was the only one
  // that knew `.markdown` and `.cs`, and the only one that did NOT know
  // `.toml`, `.ini`, `.log` or `.tsv`, so the same file could get four
  // different languages depending on which button opened it. One call now.
  async function openAttachment(att, isImage) {
    if (!att || !att.id) return;
    const id = att.id, name = att.name || '', mime = att.mime || '';
    const url = `${API_BASE}/api/upload/${id}`;

    // Images → Gallery editor.
    if (isImage) {
      try {
        const gx = await loadPanel('editor');
        if (gx.openEditor) { gx.openEditor(url, id, null, name); return; }
      } catch (e) { console.warn('gallery open failed', e); }
      window.open(url, '_blank');
      return;
    }

    // `B232`. A 36-entry extension regex used to decide this — a second copy
    // of the composer's 38-entry one, disagreeing with it about `.markdown`,
    // `.cs`, `.tsv` and `.bash` — and both of them sat in front of a server
    // that derives the answer from the bytes. The server publishes its verdict
    // on the file itself now; this asks for it.
    //
    // `document` is the widening: `.doc`, `.docx`, `.odt`, `.pptx`, `.xls`,
    // `.xlsx` and `.epub` opened as a RAW DOWNLOAD before this row, because
    // neither regex named them, while the server has had a bundled extractor
    // for every one of them since `B102`.
    const kind = await _uploadKind(url, name, mime);
    const isPdf = mime === 'application/pdf' || /\.pdf$/i.test(name);
    const isContainer = kind === INGEST_KIND_DOCUMENT || isExtractedExtension(name);
    const isTextDoc = kind === INGEST_KIND_TEXT;
    if (!isPdf && !isContainer && !isTextDoc) { window.open(url, '_blank'); return; }  // binary/unknown → raw

    // Reuse the doc we already imported for this upload, if it still loads.
    const cached = _attachDocCache.get(id);
    if (cached) {
      try {
        documentModule.openPanel && documentModule.openPanel();
        await documentModule.loadDocument(cached);
        return;
      } catch (_) { _attachDocCache.delete(id); }
    }

    // Need a session to attach the doc to (bare-session fallback, same as compose).
    let sid = '';
    try { sid = sessionModule.getCurrentSessionId() || ''; } catch (_) {}
    if (!sid) {
      try {
        const _fd = new FormData();
        _fd.append('name', name || 'Attachment');
        _fd.append('skip_validation', 'true');
        const r = await fetch(`${API_BASE}/api/session`, { method: 'POST', body: _fd, credentials: 'same-origin' });
        if (r.ok) { const d = await r.json(); if (d && d.id) { sid = d.id; if (sessionModule.loadSessions) await sessionModule.loadSessions(); } }
      } catch (_) {}
    }

    try {
      let doc;
      if (isPdf || isContainer) {
        // The import routes want a fresh file upload — re-fetch the stored blob
        // and post it. `B233`: the office half is new and is the same call the
        // mailbox already makes, not a second extractor in the browser.
        const blob = await (await fetch(url)).blob();
        doc = await _importFileAsDocument(blob, name || 'document', sid);
      } else {
        const text = await (await fetch(url)).text();
        const res = await fetch(`${API_BASE}/api/document`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          // `P21-03`: the attachment's own name; the server titles the
          // document from it and keeps it as the source.
          body: JSON.stringify({ session_id: sid || null, ...(name ? { source_name: name } : { title: 'Document' }), content: text, language: documentLanguage(name) }),
        });
        if (!res.ok) throw new Error('document ' + res.status);
        doc = await res.json();
      }
      if (doc && doc.id) {
        _attachDocCache.set(id, doc.id);
        documentModule.openPanel && documentModule.openPanel();
        if (documentModule.injectFreshDoc) documentModule.injectFreshDoc(doc);
        else await documentModule.loadDocument(doc.id);
      }
    } catch (e) {
      console.error('open attachment as document failed', e);
      import('./ui.js').then(m => m.showError && m.showError('Could not open attachment')).catch(() => {});
      window.open(url, '_blank');  // fallback so the file is still reachable
    }
  }

  // Public API
  const chatModule = {
    init,
    initListeners,
    openAttachment,
    addMessage: chatRenderer.addMessage,
    displayMetrics: chatRenderer.displayMetrics,
    handleChatSubmit,
    // app.js calls this at three composer-Enter sites through the default
    // export. It was only ever a named export, so all three guards
    // (`chatModule.queueStreamingComposerRequest && ...`) silently resolved to
    // undefined and fell through — Law 13, a handler with no reachable caller.
    queueStreamingComposerRequest,
    abortCurrentRequest,
    detachCurrentStream,
    checkBackgroundStream,
    resumeStream,
    hideWelcomeScreen: chatRenderer.hideWelcomeScreen,
    showWelcomeScreen: chatRenderer.showWelcomeScreen,
    checkPendingResearch,
    getImageCost: chatRenderer.getImageCost,
    setDisplayOverride,
    setHideUserBubble,
    setPendingContinue,
    regenerateFrom,
    forkFrom,
    editUserMessage,
    editAIMessage,
    resendUserMessage,
    deleteMessage,
    rewriteWith,
    continueFrom,
    _appendViewReportLink,
    hasActiveStream,
    // P6-07. The queue, in the shape `tasks.js` `_runToActivityEntry` emits, so
    // the Tasks activity view can render queue rows by folding these into
    // `_activityEntries` instead of growing a second queue UI. The queue panel
    // is the caller today; `tasks.js` is the second one and is owed.
    getQueueActivityEntries,
  };

  // ── Docked plan window (P6-11) ────────────────────────────────────────────
  // chat.js owns the send path, so it owns Execute; the window is an entry
  // point into `_executeStoredPlan`, not a second copy of it. Module scripts
  // run after parsing, so the markup is there — the readyState guard only
  // covers a stray non-deferred load.
  planWindow.onExecute(_executeStoredPlan);
  planWindow.onSessionId(_currentSessionIdSafe);

  // ── Docked queue panel (P6-04 / P6-06 / P6-07) ────────────────────────────
  // Same dock, same init shape as the plan window. chat.js keeps the queue and
  // the send path; the panel gets a driver, never the array.
  //
  // The Tasks activity view gets the SAME rows through `tasks.js`'s activity
  // source registry, so the queue appears in both places from one mapper.
  // Deliberately a guarded dynamic import rather than a static named one:
  // `tasks.js` belongs to another change landing in parallel, and a static
  // import of a name that moves would fail the whole chat module at load. This
  // degrades to "queue rows do not appear under Tasks ▸ Activity" instead.
  // `app.js:32` already imports `tasks.js` at boot, so this resolves from cache.
  let _activitySourceHandle = null;
  function _registerQueueActivitySource() {
    import('./tasks.js?v=20261002workbenchef').then((mod) => {
      if (!mod || typeof mod.registerActivitySource !== 'function') return;
      mod.registerActivitySource('chat-queue', () => getQueueActivityEntries('all'));
      _activitySourceHandle = mod;
    }).catch(() => { /* the docked panel still shows the queue */ });
  }
  /** Nudge the Activity tab when the queue changes under it. No-op when shut. */
  function _refreshQueueActivityView() {
    const mod = _activitySourceHandle;
    if (!mod || typeof mod.refreshActivityView !== 'function') return;
    try { mod.refreshActivityView(); } catch (_) {}
  }
  window.__pantheonRefreshQueueActivity = _refreshQueueActivityView;

  const _initDockedPanels = () => {
    planWindow.init();
    queuePanel.init(_queuePanelDriver);
    // `H01`. Started unconditionally and with no button in front of it: the
    // failure this closes is that email was held somewhere nobody looked, and a
    // surface that has to be found is the same bug with a shorter path. It
    // hides itself when there is nothing staged.
    try { agentDrafts.start(); } catch (_) {}
    _registerQueueActivitySource();
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _initDockedPanels, { once: true });
  } else {
    _initDockedPanels();
  }

  // Single delegated handler for tool-call fold/expand. One listener on
  // document.body covers every .agent-thread-node — running, completed,
  // streaming, history-rendered, compare-mode, all of them. Re-attaching
  // per-node listeners on every innerHTML rewrite was the source of the
  // "needs many clicks" bug.
  if (!window.__pantheon_thread_click_bound) {
    document.body.addEventListener('click', (e) => {
      const header = e.target.closest('.agent-thread-header');
      if (!header) return;
      const node = header.closest('.agent-thread-node');
      if (!node) return;
      const opened = node.classList.toggle('open');
      // `P5-08`: the thread's own control says "Expand all" or "Collapse all",
      // and opening the last shut card by hand is exactly when it goes stale.
      syncThreadToggleAll(node.closest('.agent-thread'));
      if (opened) {
        // Expanding the final tool trace can push a pending ask_user card below
        // the viewport.  Keep that immediately-adjacent prompt visible.
        const thread = node.closest('.agent-thread');
        const pendingCard = thread?.nextElementSibling;
        if (pendingCard?.classList.contains('ask-user-card')) {
          requestAnimationFrame(() => pendingCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
        }
      }
    });
    window.__pantheon_thread_click_bound = true;
  }

  // `P5-08`. Expand all / Collapse all, and the copy button on a tool output.
  //
  // Both are delegated on `document.body`, for the same reason the fold above
  // is: these cards are rebuilt by `innerHTML` on every result event, and a
  // per-node listener re-attached on each rewrite is `B56` — two listeners,
  // one click, the card toggles twice and nothing appears to happen.
  if (!window.__pantheon_thread_expandall_bound) {
    document.body.addEventListener('click', (e) => {
      const btn = e.target.closest('.agent-thread-expand-all');
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();
      toggleThreadAll(btn.closest('.agent-thread'));
    });
    document.body.addEventListener('click', (e) => {
      const btn = e.target.closest('.agent-tool-output-copy');
      if (!btn) return;
      // `preventDefault` is load-bearing: this button lives inside a
      // `<summary>`, and without it the copy also folds the pane shut.
      e.preventDefault();
      e.stopPropagation();
      const pane = btn.closest('.agent-tool-output');
      const text = pane?.querySelector('pre')?.textContent || '';
      if (!text) return;
      uiModule.copyToClipboard(text);
      btn.classList.add('copied');
      clearTimeout(btn._copiedTimer);
      btn._copiedTimer = setTimeout(() => btn.classList.remove('copied'), 1500);
    });
    window.__pantheon_thread_expandall_bound = true;
  }

  // One observer draws the control on every thread, wherever it was built —
  // the live stream, history replay and compare mode each create their own
  // `.agent-thread`, and putting the call in all three is how this file ended
  // up with six copies of a tool card (`P4-01`). Same shape as the compact-`pre`
  // observer above, deliberately (`Law 14`).
  if (!window.__pantheon_thread_toolbar_observer) {
    window.__pantheon_thread_toolbar_observer = true;
    const _sweepThreads = (root) => {
      if (!root || !root.querySelectorAll) return;
      if (root.matches && root.matches('.agent-thread')) ensureThreadToggleAll(root);
      root.querySelectorAll('.agent-thread').forEach(ensureThreadToggleAll);
    };
    const _startThreadToolbars = () => {
      if (!document.body) return;
      _sweepThreads(document.body);
      new MutationObserver((muts) => {
        for (const m of muts) {
          // `B923`. The control's own writes are not news about the thread.
          // Skipping them is the second guard: `syncThreadToggleAll` already
          // writes only what changed, and this keeps a future write there
          // from turning the observer back into a loop that never yields.
          if (m.target && m.target.closest && m.target.closest('.agent-thread-toolbar')) continue;
          if (m.target && m.target.closest) {
            const t = m.target.closest('.agent-thread');
            if (t) ensureThreadToggleAll(t);
          }
          for (const n of m.addedNodes) {
            if (n.nodeType === 1) _sweepThreads(n);
          }
        }
      }).observe(document.body, { childList: true, subtree: true });
    };
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', _startThreadToolbars, { once: true });
    } else {
      _startThreadToolbars();
    }
  }

  // `P5-07`. Copy the executed command. One delegated listener for the same
  // reason the fold above has one — `B56` is what a per-node listener on these
  // cards costs, and the card is rebuilt on every rewrite.
  //
  // It copies the **whole** command, not the line on screen. That is the point
  // of the row: for a document tool the visible line is the first 80 characters
  // and on the approval replay it is the first 240, so copying what is shown
  // would hand the user a truncated command that looks complete. `P4-09` put
  // the full text on the card, behind a `<details>`, and this reads it from
  // there when it is present. Reading `textContent` rather than a `data-`
  // attribute means what lands on the clipboard is exactly what the card shows,
  // decoded once by the browser instead of escaped and unescaped by hand.
  if (!window.__pantheon_thread_copy_bound) {
    document.body.addEventListener('click', (e) => {
      const btn = e.target.closest('.agent-thread-cmd-copy');
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();
      const node = btn.closest('.agent-thread-node');
      const full = node?.querySelector('.agent-thread-cmd-full .agent-thread-cmd');
      const shown = btn.closest('.agent-thread-cmd-block')?.querySelector('.agent-thread-cmd');
      const text = (full || shown)?.textContent || '';
      if (!text) return;
      uiModule.copyToClipboard(text);
      btn.classList.add('copied');
      clearTimeout(btn._copiedTimer);
      btn._copiedTimer = setTimeout(() => btn.classList.remove('copied'), 1500);
    });
    window.__pantheon_thread_copy_bound = true;
  }

  export default chatModule;
  window.chatModule = chatModule;
