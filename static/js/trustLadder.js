// static/js/trustLadder.js
//
// P7-03 / P7-04, user-facing half — and `P7-05`'s correction, which was re-filed
// as an acceptance criterion on both rows: *"Auto-Pilot as the existing default
// with the ladder added below it, never above."*
//
// Three surfaces, one module, because they are one vocabulary. The ladder in
// Settings chooses how often the gate asks; the scope chooser on the approval
// card turns one approval into a standing rule the `allow_listed` rung will
// honour; and the list under the ladder shows every rule that exists and takes
// one back. A second copy of any of those words would drift, and then the same
// choice would read as two different promises in three places.
//
// CORRECTED 2026-08-29. This said "two surfaces", and there were two — which is
// the defect refutation called the worst thing in the change. A rule could be
// created and then neither seen nor revoked from anywhere in the product: the
// widest grant on offer, "anything bash does", was one click on an approval
// card, after which no screen showed it existed. `GET` and
// `DELETE /api/tool-allow-rules` had existed, been owner-scoped and been tested
// since the store landed, and nothing drew either, so recovering meant knowing
// the route was there and issuing HTTP by hand against your own install. The
// third surface below is that list, on the endpoints that were already there.
//
// ── WHAT IS NOT ON THE LADDER, AND WHY ──────────────────────────────────────
//
// `.pantheon/design/pantheon-v10.html:1719-1727` draws five rungs. Three of them
// are gate settings and exist in `TrustRung` (`src/tool_capabilities.py`); two
// are not, and this file must not invent them as options:
//
//   "plan only"  — a *mode you enter*, not a gate setting: a read-only tool
//                  allowlist plus a directive, reached from the composer's Plan
//                  button (`P6-12`). A fourth radio here would be a control
//                  lying about what it does — moving it would not put the run
//                  into plan mode.
//   "auto-pilot" — what `gate_on_untrusted` already *feels like* in a clean
//                  chat. The design says so in its own correction note at
//                  :1727. A separate option would be a second name for one
//                  state, and picking "the other one" would change nothing.
//
// Both are *mentioned* in the copy below — a person orienting themselves needs
// to know where plan mode went and that auto-pilot is what they already have.
// Mentioning is not offering. `LADDER_INTRO` and `LADDER_NOTE` are prose;
// `TRUST_RUNGS` is the set of things you can pick, and it has exactly three
// entries whose values are exactly the three enum members.
//
// ── WHY THE COPY READS LIKE THIS ────────────────────────────────────────────
//
// `Law 15`. The owner's words about a competitor's more advanced product: *"I'm
// genuinely confused how to work it. There's no tutorials and the learning curve
// is too steep for the little amount of time I have."* The option *names* are
// unavoidably jargon — they are the design's names and the enum's names, and
// renaming them here would give the product two vocabularies for one setting —
// so every name is followed by a sentence that says what will happen to the
// person reading it, in their words, naming the consequence and never the
// mechanism. `P7-06`'s refuter set the standard one row ago: *"the honest answer
// is yes — from the sentence, not from the design."*
//
// And the strict rungs say what they cost, up front, in the same size type as
// the promise. Someone who switches to one without being told what it will feel
// like switches back angrily, and trusts the next control less.
//
// CORRECTED 2026-08-29. The paragraph above used to finish *"'Ask every time'
// means a confirmation before everything that writes, runs, sends or deletes"*,
// and both strict rungs' sentences promised the same four verbs. That was
// false, and measurably so. Both rungs gate on `POST_EXTERNAL_BLOCKED_EFFECTS`
// (`src/tool_capabilities.py`), which carries `read_private` alongside the four
// write-ish ones: 72 of the 81 known tools are gated, and the nine that are not
// are `ask_user`, `get_workspace`, `glob`, `grep`, `ls`, `read_file`,
// `search_hf_models`, `update_plan` and `web_search`. Reading your mail, your
// calendar, your notes and the agent's own memory of earlier chats all stop and
// ask. That may well be the right set — but a person choosing this rung on the
// old sentence would meet a confirmation for reading a note and conclude the
// product was broken, which is the same wound `Law 15` exists to close. The
// sentences and the cost lines below name the reads.

import { getSettings, invalidateSettings } from './appConfig.js';
import uiModule from './ui.js';

/** The settings key `src/agent_loop.py:resolve_trust_rung()` reads. */
export const TRUST_RUNG_KEY = 'trust_rung';

/** `DEFAULT_TRUST_RUNG` in `src/tool_capabilities.py` — today's behaviour. */
export const DEFAULT_TRUST_RUNG = 'gate_on_untrusted';

/**
 * The ladder, ordered as it is drawn: the default first, the two stricter rungs
 * below it.
 *
 * That order IS the `P7-05` acceptance criterion, not a layout preference. The
 * correction it records is that nothing looser than current behaviour exists to
 * add, so nothing may appear above the default — a reader who scrolled up from
 * the default and found another rung would conclude the product had been holding
 * something back, which is the belief the correction exists to prevent.
 *
 * `cost` is empty on the default and only on the default: changing nothing costs
 * nothing. On both others it is a required field — see `TRUST_RUNGS` assertions
 * in `tests/test_trust_ladder_js.py`.
 */
export const TRUST_RUNGS = [
  {
    value: 'gate_on_untrusted',
    name: 'Gate on untrusted',
    current: true,
    badge: 'What you have now',
    band: 'none',
    sentence:
      'This is auto-pilot, and it is what your install already does. Pantheon '
      + 'gets on with the job and does not interrupt you; it stops to ask only '
      + 'after something from outside the conversation — a web page, an email, '
      + 'a file it fetched — has been pulled in. Leave this alone if you are '
      + 'not sure.',
    cost: '',
  },
  {
    value: 'allow_listed',
    name: 'Allow-listed',
    current: false,
    badge: '',
    band: 'some',
    sentence:
      'Pantheon stops and waits for your yes before nearly everything it does '
      + '— saving a file, running code, sending anything, deleting anything, '
      + 'and looking at things of yours such as your mail, your calendar, your '
      + 'notes and what it remembers from earlier chats — except the things '
      + 'you have already said yes to, which it goes ahead and does.',
    cost:
      'What this costs you: a run of questions to begin with. They thin out as '
      + 'you approve the things you do often, but anything new still stops and '
      + 'waits, so a job left running on its own sits unfinished until you come '
      + 'back to it. And once something from outside the conversation has been '
      + 'pulled in — a web page, an email, a file it fetched — Pantheon asks '
      + 'about everything again, including the things you said yes to.',
  },
  {
    value: 'ask_every_time',
    name: 'Ask every time',
    current: false,
    badge: '',
    band: 'high',
    sentence:
      'Pantheon stops and waits for your yes before nearly everything it does '
      + '— saving a file, running code, sending anything, deleting anything, '
      + 'and looking at things of yours such as your mail, your calendar, your '
      + 'notes and what it remembers from earlier chats — every single time, '
      + 'even when nothing has gone wrong and nothing came in from outside.',
    cost:
      'What this costs you: a great many interruptions, some of which will '
      + 'feel absurd. A job that touches twenty files asks you twenty times, '
      + 'and Pantheon stops to ask before it so much as looks up your calendar '
      + 'or reads back a note it wrote in an earlier chat. Nothing happens at '
      + 'all while you are away from the screen.',
  },
];

export const LADDER_TITLE = 'How often Pantheon checks with you';

export const LADDER_INTRO =
  'Auto-pilot is what you have today: in a fresh chat Pantheon gets on with '
  + 'the job and only stops if something from outside gets pulled in. It is the '
  + 'first choice below and it stays chosen unless you move it. The other two '
  + 'only ever make Pantheon ask more often — there is nothing here that makes '
  + 'it ask less.';

export const LADDER_NOTE =
  'Plan mode is not on this list. It is the Plan button beside the message '
  + 'box, and it applies to one conversation at a time rather than to every '
  + 'chat.';

const _RUNG_VALUES = TRUST_RUNGS.map((rung) => rung.value);

/** Fail *safe*, not strict — the same argument `coerce_trust_rung` makes. */
function _coerceRung(value) {
  const normalized = String(value == null ? '' : value).trim().toLowerCase();
  return _RUNG_VALUES.includes(normalized) ? normalized : DEFAULT_TRUST_RUNG;
}

// ── Is this setting real on this server? ────────────────────────────────────
//
// The same question `probeSteerSupport()` (`static/js/chatStream.js`) asks about
// the steer route, answered from a payload the page already fetches instead of
// from a request of its own. `trust_rung` reaches the browser only if it is in
// `DEFAULT_SETTINGS` (`src/settings.py`) — `GET /api/auth/settings` returns
// defaults merged with the saved file, and `POST` iterates `DEFAULT_SETTINGS`
// and silently drops every key that is not in it. So the key's presence answers
// both halves at once: the server will report this setting, and it will accept a
// write of it. Its absence means an older build, and the ladder is not drawn —
// three radio buttons whose value is discarded on save is precisely the
// half-wiring `Law 13` names and `P3-13` shipped.

let _statePromise = null;
let _rung = null;

function _loadTrustState() {
  if (_statePromise) return _statePromise;
  _statePromise = Promise.resolve()
    .then(() => getSettings())
    .then((settings) => {
      const supported = !!settings
        && typeof settings === 'object'
        && Object.prototype.hasOwnProperty.call(settings, TRUST_RUNG_KEY);
      _rung = supported ? _coerceRung(settings[TRUST_RUNG_KEY]) : null;
      // Only this rung reads standing rules, so only this rung asks whether the
      // store exists. An install that never touches the ladder never makes the
      // request, and the approval card never grows an affordance it would have
      // had to hide again.
      if (_rung !== 'allow_listed') return { supported, rung: _rung, rules: false };
      return _probeAllowRules().then((rules) => ({ supported, rung: _rung, rules }));
    })
    .catch(() => {
      _rung = null;
      return { supported: false, rung: null, rules: false };
    });
  return _statePromise;
}

/** Resolves once the server has been asked. Exported so tests need no timers. */
export function trustSettingsReady() {
  return _loadTrustState();
}

// ── Job 1: the ladder ───────────────────────────────────────────────────────

function _el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null && text !== '') node.textContent = text;
  return node;
}

async function _saveRung(value, status) {
  const say = (text) => { if (status) status.textContent = text; };
  say('Saving…');
  let data = null;
  try {
    const res = await fetch('/api/auth/settings', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [TRUST_RUNG_KEY]: value }),
    });
    if (!res.ok) {
      say(res.status === 403
        ? 'Only an administrator can change this. Nothing was saved.'
        : 'That could not be saved. Nothing has changed.');
      return false;
    }
    // Before the round-trip check below, not after it, and not only on the
    // happy path: `set_settings` rewrites the whole settings file on any
    // accepted request, so the shared snapshot in `appConfig.js` is stale from
    // this moment even when the key we sent was one of the ones it discarded.
    invalidateSettings();
    data = await res.json();
  } catch (_) {
    say('That could not be saved. Nothing has changed.');
    return false;
  }
  // Read the setting back out of the server's own reply rather than trusting a
  // 200. `POST /api/auth/settings` answers 200 and drops any key it does not
  // recognise, so "it saved" and "it was thrown away" are the same response —
  // which is exactly how a control ends up half-wired without anyone noticing.
  const saved = data && typeof data === 'object' ? data[TRUST_RUNG_KEY] : undefined;
  if (saved !== value) {
    say('This server did not accept the change. Nothing has changed.');
    return false;
  }
  _rung = value;
  const chosen = TRUST_RUNGS.find((rung) => rung.value === value);
  say(chosen && chosen.current
    ? 'Saved. Pantheon is back to not interrupting you.'
    : 'Saved. New chats will use this from now on.');
  // Moving *onto* the rung that reads rules asks the store the question the
  // page load did not — it had no reason to, because the rung was something
  // else then.
  //
  // Refutation reproduced the omission against the real module: from the
  // default rung, move the ladder to "Allow-listed", render an approval card,
  // and the scope chooser is `null` because `_ruleKinds` is still empty. The
  // store had never been asked. That is the direction a first-time user takes
  // — you switch a setting on and then use it — and it stayed broken until a
  // reload, while the mirror case (moving *off* the rung) was tested. Awaited
  // rather than kicked and forgotten so that the caller's promise means "the
  // ladder has finished settling", which is what the card renderer's own
  // ordering depends on.
  if (value === 'allow_listed') await _probeAllowRules();
  return true;
}

/**
 * Draw the ladder into `host`. Returns the ladder element, or `null`.
 *
 * Split from `initTrustLadder` so a test can drive the drawing without owning
 * the fetch, and so the "server does not have this setting" branch is a
 * decision made in one place rather than in the renderer.
 */
export function renderTrustLadder(host, rung) {
  if (!host) return null;
  const selected = _coerceRung(rung);
  host.textContent = '';

  const box = _el('div', 'trust-ladder');
  box.setAttribute('role', 'radiogroup');
  box.setAttribute('aria-label', LADDER_TITLE);

  box.appendChild(_el('div', 'trust-ladder-title', LADDER_TITLE));
  box.appendChild(_el('p', 'trust-ladder-intro', LADDER_INTRO));

  const list = _el('div', 'trust-ladder-options');
  const status = _el('div', 'trust-ladder-status', '');
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');

  const inputs = [];
  // What the ladder currently believes is saved. A write that the server did
  // not take must put the dot back — leaving it on the option the person
  // clicked, beside a line saying nothing changed, shows two answers at once
  // and the wrong one is the more visible.
  let settled = selected;
  const showSettled = () => {
    inputs.forEach((input) => { input.checked = input.value === settled; });
  };
  TRUST_RUNGS.forEach((rungDef) => {
    const row = _el('label', 'trust-rung');
    row.dataset.rungValue = rungDef.value;
    row.dataset.rungCost = rungDef.band;
    if (rungDef.current) row.dataset.rungCurrent = 'true';

    const input = document.createElement('input');
    input.type = 'radio';
    input.className = 'trust-rung-input';
    input.name = 'trust-rung';
    input.value = rungDef.value;
    input.checked = rungDef.value === selected;
    inputs.push(input);
    row.appendChild(input);

    const body = _el('span', 'trust-rung-body');

    const head = _el('span', 'trust-rung-head');
    const mark = _el('span', 'trust-rung-mark');
    mark.setAttribute('aria-hidden', 'true');
    head.appendChild(mark);
    head.appendChild(_el('span', 'trust-rung-name', rungDef.name));
    if (rungDef.badge) head.appendChild(_el('span', 'trust-rung-badge', rungDef.badge));
    body.appendChild(head);

    body.appendChild(_el('span', 'trust-rung-sentence', rungDef.sentence));
    if (rungDef.cost) body.appendChild(_el('span', 'trust-rung-cost', rungDef.cost));

    row.appendChild(body);

    input.addEventListener('change', () => {
      if (!input.checked) return;
      inputs.forEach((other) => { other.checked = other === input; });
      _saveRung(rungDef.value, status).then((saved) => {
        if (saved) settled = rungDef.value;
        else showSettled();
        paintRules();
      });
    });
    list.appendChild(row);
  });

  box.appendChild(list);
  box.appendChild(status);
  box.appendChild(_el('p', 'trust-ladder-note', LADDER_NOTE));

  // The standing rules, under the ladder, on the rung that is the only one to
  // read them. Repainted after every settled write, so switching on the rung
  // shows the list without a reload and switching off takes it away.
  const rules = _el('div', 'allow-rule-list');
  box.appendChild(rules);
  // Draws from what the module already knows and asks the store nothing. A cold
  // page that starts on another rung has never asked it — but the only way to
  // reach this rung from there is through `_saveRung`, which asks on the way and
  // does not resolve until it has an answer. A second probe here would be a
  // renderer with a side effect, and two places to fix when one of them is
  // wrong.
  const paintRules = () => { renderAllowRuleList(rules, settled); };
  paintRules();

  host.appendChild(box);
  return box;
}

/**
 * Draw the ladder if — and only if — this server carries the setting.
 *
 * The card around it stays `hidden` until there is something in it. An empty
 * bordered box in a settings panel reads as a feature that failed to load, which
 * is a worse answer than the honest one: on a build without the setting, there
 * is simply no such control here.
 */
export function initTrustLadder(root) {
  const host = root || (typeof document !== 'undefined'
    ? document.getElementById('trust-ladder')
    : null);
  if (!host) return Promise.resolve(null);
  return _loadTrustState().then((state) => {
    if (!state.supported) return null;
    const ladder = renderTrustLadder(host, state.rung);
    const card = typeof document !== 'undefined'
      ? document.getElementById('trust-ladder-card')
      : null;
    if (card && ladder) card.hidden = false;
    return ladder;
  });
}

// ── Job 2: "always allow this", on the approval card ────────────────────────
//
// `P7-04`'s rule store landed from the parallel batch while this was being
// written, so the endpoint below is real and not a guess:
//
//   GET    /api/tool-allow-rules       -> { rules: [...], match_kinds: [...] }
//   POST   /api/tool-allow-rules       <- { tool_name, match_kind, pattern }
//   DELETE /api/tool-allow-rules/{id}  -> { status: "revoked", id }, or 404
//
// Each `rules` entry carries `id`, `owner`, `tool_name`, `match_kind`,
// `pattern`, `last_used_at` and `created_at`, newest first
// (`list_tool_allow_rules`, routes/chat_routes.py). One `GET` therefore answers
// both questions this file asks — what kinds may be offered, and what already
// exists to be taken back — which is why there is no second request for the
// list under the ladder.
//
// `match_kinds` is sent by the server for exactly this purpose — its own comment
// in `routes/chat_routes.py` says a chooser should be built from the store's
// kinds rather than from a hardcoded client copy, because a kind added to one
// and not the other renders as a blank option or an unsubmittable form. So the
// list below is filtered by what the server named, never assumed.
//
// PROBED, the way `probeSteerSupport()` (`static/js/chatStream.js`) probes the
// steer route — and the affordance is simply not drawn when the answer is no.
// `Law 13` is the law this programme breaks most often and `P3-13` is the row
// where a gate against half-wiring was itself half wired, so the conditions are
// stated here and tested:
//
//   * 404 / 405 / 501 — this build has no such route. Never drawn.
//   * 401 / 403 — this caller may not create rules: a bearer API token, or no
//     signed-in owner (`_allow_rule_owner`). An affordance certain to be refused
//     is not an affordance, so it is never drawn either.
//   * the rung is not `allow_listed`. This one is not cosmetic:
//     `ToolRunSecurityContext.decision_for` consults the store *only* at
//     `ALLOW_LISTED`, and `_resolve_allow_rule_lookup` only builds a lookup
//     there. A rule saved on any other rung is written, listed, and never read —
//     which is a button wired to nothing wearing a receipt.
//
// The probe runs on that rung and nowhere else, so an install that never
// touches the ladder never makes the request.
//
// CORRECTED 2026-08-29. This used to say "one request per page load", and it
// meant it: the probe ran only from `_loadTrustState`, which skipped it unless
// the rung was already `allow_listed` when the page loaded. Switching *onto*
// the rung therefore left the store unasked and the chooser `null` until a
// reload — the direction a first-time user takes. `_saveRung` now asks on the
// way onto the rung as well. Still at most one request either way: the probe
// caches its own promise.
//
// NO REGEX, NO PATTERN AUTHORING. There is no text field anywhere on this card.
// A person picks one of the store's kinds; the pattern is derived from the
// action already on screen and shown verbatim beside the choice, so the rule is
// read rather than composed.

const ALLOW_RULE_API = '/api/tool-allow-rules';

// There is no client-side list of match kinds here, and there must not be one.
//
// CORRECTED 2026-08-29. This was `ALLOW_RULE_MATCH_KINDS`, exported, and
// described as "the store's kinds" — a claim `src/tool_allow_rules.py` then
// contradicted by saying `GET` returns `MATCH_KINDS` "so nothing keeps a second
// copy of the three strings". It was that second copy. It was only ever used to
// narrow what the server named, so it could not widen a grant, but a kind the
// store gained would have been dropped on the floor with nothing said.
//
// It is gone, and so is the narrowing it did on the way in from the wire —
// `_ruleKinds` is now exactly what the server named. The judgement it was
// duplicating lives in one place, `allowRuleScopes`, which offers a kind only
// when `allowRuleWording` has a sentence for it: a blank button that posts a
// rule nobody can read back is worse than an absent one. The store stays
// authoritative for which kinds exist; this file is only authoritative for
// which of them it can describe, and a kind it cannot describe is not offered
// until somebody writes the words.
//
// The revoke list deliberately does *not* apply that judgement: a grant this
// screen cannot phrase is still a grant, and hiding it would be the defect the
// list exists to fix.

let _rulesProbe = null;
let _ruleKinds = [];
// Every rule the store has told us about, newest first, and whether it has told
// us anything at all. `false` is "not asked yet", which is not the same answer
// as the empty list and must not be drawn as one.
let _rules = [];
let _rulesKnown = false;

function _probeAllowRules() {
  if (_rulesProbe) return _rulesProbe;
  _rulesProbe = Promise.resolve()
    .then(() => fetch(ALLOW_RULE_API, { credentials: 'same-origin' }))
    .then(async (res) => {
      // Any answer that is not a 2xx means do not offer it. That is broader
      // than `probeSteerSupport`'s three-status test on purpose: the statuses
      // this route can give — 404/405/501 for a build with no such route,
      // 401/403 for a caller `_allow_rule_owner` will always refuse, 5xx for a
      // store that cannot answer — all end in the same place, and there is no
      // "the route is fine, this call was not" case here for a narrower test to
      // rescue. At most one probe per page either way; a `false` is not retried.
      if (!res || !res.ok) return false;
      let data = {};
      try { data = await res.json(); } catch (_) { return false; }
      // Exactly what the server named, normalised and not narrowed. Narrowing
      // here would be a second copy of the judgement `allowRuleScopes` already
      // makes, and the copy that is easier to forget.
      const named = Array.isArray(data && data.match_kinds) ? data.match_kinds : [];
      _ruleKinds = named
        .map((kind) => String(kind == null ? '' : kind).trim().toLowerCase())
        .filter(Boolean);
      // The same answer carries the rules themselves, so the list under the
      // ladder costs no second request. Kept even when the store named no kind
      // this build can offer: it can still show and revoke what the store
      // holds, and "there are grants you cannot see" is the state being fixed
      // here.
      _rules = Array.isArray(data && data.rules) ? data.rules.filter(Boolean) : [];
      _rulesKnown = true;
      return _ruleKinds.length > 0;
    })
    .catch(() => false);
  return _rulesProbe;
}

/** The literal prefix a "starts with" rule would store, or '' if there is none. */
export function allowRulePrefix(content) {
  return String(content == null ? '' : content).trim().split(/\s+/)[0] || '';
}

/**
 * One rule, in words — `null` for a kind this file has no sentence for.
 *
 * The single place either surface gets its wording from. The chooser on the
 * approval card asks it what a scope would mean; the list under the ladder asks
 * it what an existing rule does mean. That is not tidiness: the two screens are
 * a promise and its receipt, and a person who reads "anything bash does" when
 * they grant it has to find those same four words when they come to take it
 * back, or they will not be sure it is the same thing.
 *
 * `pattern` is the stored pattern for `exact` and `prefix` and is ignored for
 * `any`, exactly as `rule_matches` (src/tool_allow_rules.py) reads them.
 */
export function allowRuleWording(tool, match, pattern) {
  const name = String(tool == null ? '' : tool).trim();
  const kind = String(match == null ? '' : match).trim().toLowerCase();
  const literal = String(pattern == null ? '' : pattern).trim();
  if (kind === 'exact' && literal) {
    return {
      label: 'Only this exact command',
      detail: literal,
      sentence:
        'Pantheon goes ahead without asking when it wants to do exactly this '
        + 'again. Anything even slightly different still stops and asks you.',
    };
  }
  if (kind === 'prefix' && literal) {
    return {
      label: `Anything beginning with “${literal}”`,
      detail: literal,
      // Says what the rule really is. The store matches a literal prefix with
      // no word-boundary rule — deliberately, and its own comment explains why
      // — so "commands starting with git" would be a friendlier sentence that
      // was not true of `gitleaks`.
      sentence:
        `Pantheon goes ahead without asking whenever the command begins with `
        + `those exact letters — “${literal} …” — including things you have not `
        + `seen it do yet. Everything else still stops and asks you.`,
    };
  }
  if (kind === 'any' && name) {
    return {
      label: `Anything ${name} does`,
      detail: name,
      sentence:
        `Pantheon goes ahead without asking every time it uses ${name}, `
        + `whatever it passes to it. This is the widest yes you can give and it `
        + `covers uses you have not seen yet.`,
    };
  }
  return null;
}

/**
 * The offered scopes for one action, narrowest first.
 *
 * DELIBERATELY NOT the order `MATCH_KINDS` is written in: the widest scope is
 * the one a person grants by accident, and a list read top to bottom should
 * widen as it goes rather than open on the answer that gives the most away. The
 * store stays authoritative for *which* kinds exist — that is read off the wire
 * — and only the reading order is decided here.
 *
 * CORRECTED 2026-08-29. This used to cite `src/tool_allow_rules.py:48` as
 * saying the tuple is *"ordered widest-first, which is the order a chooser
 * should present them in"*, and staged a disagreement with it. That line was
 * corrected on the same day and now says the opposite — it hands presentation
 * order to the chooser and keeps only membership — so the disagreement was with
 * a sentence that no longer exists, and a reader following the citation would
 * have found the store agreeing and assumed one of the two files was stale.
 */
export function allowRuleScopes(aq, kinds) {
  const action = (aq && aq.action) || {};
  const tool = String(action.tool || '').trim();
  const content = String(action.content || '').trim();
  const offered = new Set(Array.isArray(kinds) ? kinds : _ruleKinds);
  if (!tool) return [];

  const prefix = allowRulePrefix(content);
  const scopes = [];
  const offer = (match, pattern) => {
    const words = allowRuleWording(tool, match, pattern);
    if (words) scopes.push(Object.assign({ match, pattern }, words));
  };

  if (offered.has('exact') && content) offer('exact', content);
  // Only when there is something left over to generalise. For a one-word
  // command "begins with" and "exactly this" are the same rule under two names,
  // and offering both would make the narrower one look narrower than it is.
  if (offered.has('prefix') && prefix && prefix !== content) offer('prefix', prefix);
  if (offered.has('any')) offer('any', '');
  return scopes;
}

export const ALLOW_RULE_TITLE = 'Stop asking about this in future';

export const ALLOW_RULE_HINT =
  'Only pick one of these if you want Pantheon to stop asking. Skip it and '
  + 'nothing is remembered — this approval covers this one action and no more.';

/**
 * Send one rule to the store. Reports what happened, and never blocks the
 * approval it travelled with.
 *
 * The approval is the urgent half and the rule is the convenience: holding a
 * gated action open while a second request finishes would make the important
 * one wait on the optional one. So this runs alongside the decision, and says
 * what it did — the server's own refusals are already plain sentences ("You
 * already have 200 allow rules. Revoke one before adding another.") and are
 * shown verbatim rather than replaced with a generic failure.
 */
export async function createAllowRule(rule) {
  if (!rule || !rule.match || !rule.tool) return false;
  let res = null;
  try {
    res = await fetch(ALLOW_RULE_API, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tool_name: rule.tool,
        match_kind: rule.match,
        pattern: rule.pattern || '',
      }),
    });
  } catch (_) {
    uiModule.showError('Pantheon could not save that. It will keep asking.');
    return false;
  }
  let data = {};
  try { data = await res.json(); } catch (_) { data = {}; }
  if (!res.ok || !data || !data.id) {
    const detail = data && typeof data.detail === 'string' ? data.detail : '';
    uiModule.showError(
      detail || 'Pantheon could not save that. It will keep asking.',
    );
    return false;
  }
  // Keep the list under the ladder honest inside this page session. Settings is
  // a panel in the same page, so a rule granted here and then looked for there
  // would otherwise be missing from a list that had loaded before it existed —
  // which is the complaint this whole surface answers, arriving one tab over.
  // Newest first, matching the store's own ordering.
  const stored = {
    id: String(data.id),
    tool_name: String(data.tool_name || rule.tool || ''),
    match_kind: String(data.match_kind || rule.match || ''),
    pattern: String(data.pattern == null ? (rule.pattern || '') : data.pattern),
    last_used_at: data.last_used_at || null,
    created_at: data.created_at || null,
  };
  if (!_rules.some((existing) => existing && existing.id === stored.id)) {
    _rules = [stored].concat(_rules);
  }
  // CORRECTED 2026-08-29. This toast used to end at "…before it does this," and
  // the comment here explained that naming a place to undo it would be pointing
  // at nowhere, because nothing in the product drew `GET` or
  // `DELETE /api/tool-allow-rules`. That was true and it was the defect: the
  // widest grant in the product was one click away and could then be neither
  // seen nor taken back. Something draws them now, so the sentence says where —
  // a person who has just been surprised by their own click needs the way back
  // in the same breath, not a search through Settings.
  uiModule.showToast(rule.match === 'any'
    ? `Saved. Pantheon will stop asking before it uses ${rule.tool}. `
      + `You can take it back in Settings, under “${LADDER_TITLE}”.`
    : 'Saved. Pantheon will stop asking before it does this. '
      + `You can take it back in Settings, under “${LADDER_TITLE}”.`);
  return true;
}

/**
 * The scope chooser, or `null` when any of the conditions above fails.
 *
 * `read()` yields the chosen rule or `null`; `commit()` sends it. Nothing is
 * sent until one of the card's affirmative buttons calls `commit()` — see
 * `APPROVAL_DECISIONS_THAT_GRANT` in `static/js/chatRenderer.js`, which names
 * them rather than naming the refusal, because refusing an action must not be a
 * way to create permission for it and a list of refusals is never complete.
 */
export function buildAllowRuleChooser(aq) {
  // Both conditions. `allowRuleScopes` is empty until the probe has come back
  // with kinds this file has words for, so an unanswered probe, a refused
  // caller, a build with no such route and a store whose whole vocabulary is
  // newer than this screen are all the same "no" here.
  if (_rung !== 'allow_listed') return null;
  const scopes = allowRuleScopes(aq);
  if (!scopes.length) return null;

  const box = _el('div', 'allow-rule');
  box.appendChild(_el('div', 'allow-rule-title', ALLOW_RULE_TITLE));
  box.appendChild(_el('p', 'allow-rule-hint', ALLOW_RULE_HINT));

  const list = _el('div', 'allow-rule-scopes');
  list.setAttribute('role', 'group');
  list.setAttribute('aria-label', ALLOW_RULE_TITLE);
  const buttons = [];
  let chosen = null;

  scopes.forEach((scope) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'allow-rule-scope';
    button.dataset.scope = scope.match;
    // Starts off. A standing rule is never the default answer to a question
    // whose whole subject is whether to stop asking.
    button.setAttribute('aria-pressed', 'false');

    const mark = _el('span', 'allow-rule-scope-mark');
    mark.setAttribute('aria-hidden', 'true');
    button.appendChild(mark);
    const text = _el('span', 'allow-rule-scope-text');
    text.appendChild(_el('span', 'allow-rule-scope-label', scope.label));
    text.appendChild(_el('span', 'allow-rule-scope-detail', scope.detail));
    text.appendChild(_el('span', 'allow-rule-scope-sentence', scope.sentence));
    button.appendChild(text);

    button.addEventListener('click', () => {
      const already = button.getAttribute('aria-pressed') === 'true';
      buttons.forEach((other) => other.setAttribute('aria-pressed', 'false'));
      button.setAttribute('aria-pressed', already ? 'false' : 'true');
      chosen = already ? null : scope;
    });

    buttons.push(button);
    list.appendChild(button);
  });

  box.appendChild(list);
  const action = (aq && aq.action) || {};
  box.read = () => (chosen
    ? {
      match: chosen.match,
      pattern: chosen.pattern,
      tool: String(action.tool || ''),
      content: String(action.content || ''),
    }
    : null);
  box.commit = () => {
    const rule = box.read();
    if (!rule) return null;
    return createAllowRule(rule);
  };
  return box;
}

// ── Job 3: seeing what you have granted, and taking it back ─────────────────
//
// The half of `P7-04` that was missing. `core/database.py` says of this table:
// *"Revocation is a DELETE… this is the table where that omission is
// expensive"*; `list_tool_allow_rules` says *"Listable is half of revocable: a
// grant nobody can see is one nobody thinks to take back"*; and the store's
// five-second snapshot TTL is defended on the grounds that *"revoke means
// revoked before the user has finished reading the confirmation"*. All three
// were describing a revoke that did not exist on any screen. This is it.
//
// Deliberately NOT `P7-09`. That row is the inspector for session-scope
// approval grants — the blanket "allow for this task / this chat" a card can
// hand out, which lives in a session's history and dies with it. These are
// owner-scoped rules in a table, they outlive every chat, and they are the ones
// nothing could see. Two different things, and this builds only the second.
//
// It reuses the endpoints that already shipped and adds no vocabulary: the
// rows are `allowRuleWording`, the same sentences the approval card offered
// when the grant was made.

export const ALLOW_RULE_LIST_TITLE = 'What Pantheon no longer asks about';

// "Within a few seconds" is `SNAPSHOT_TTL_SECONDS`, which is five, and the TTL
// is five for the sake of a sentence like this one — its own comment says
// *"revoke means revoked before the user has finished reading the
// confirmation"*. "Next time you start a chat" would sound safer and be wrong in
// the direction that matters: someone revoking in a hurry needs to know the run
// in front of them is already covered.
export const ALLOW_RULE_LIST_HINT =
  'These are the things you told Pantheon to stop asking about. Revoke one and '
  + 'it goes back to asking before that action within a few seconds, even in '
  + 'the middle of a chat that is already running. None of them apply once '
  + 'something from outside the conversation has been pulled in — a web page, '
  + 'an email, a file it fetched — because then Pantheon asks about everything '
  + 'again.';

export const ALLOW_RULE_LIST_EMPTY =
  'Nothing yet. When Pantheon stops to ask before doing something, the card it '
  + 'shows you offers to stop asking about that one thing in future — whatever '
  + 'you accept there turns up on this list.';

/** The words for a stored rule, including one whose kind this build cannot phrase. */
function _storedRuleWording(rule) {
  const tool = String((rule && rule.tool_name) || '').trim();
  const words = allowRuleWording(tool, rule && rule.match_kind, rule && rule.pattern);
  if (words) return words;
  // A grant this screen has no sentence for is still a grant, and hiding it
  // would be the exact defect this list exists to end. So it is shown, said to
  // be unreadable, and revoked by the same button as the rest.
  return {
    label: `Something ${tool || 'a tool'} is allowed to do`,
    detail: String((rule && rule.pattern) || tool || ''),
    sentence:
      'This build cannot put this one into words: it is a kind of rule this '
      + 'screen does not know how to describe. It is still something Pantheon '
      + 'will go ahead and do without asking, and revoking it here still works.',
  };
}

/** Whether this rule has ever been used, as a sentence rather than a timestamp. */
function _storedRuleWhen(rule) {
  const stamp = rule && rule.last_used_at ? String(rule.last_used_at) : '';
  // Never used is the interesting case and is said out loud: it is how a person
  // finds the grant they made once by accident and have not needed since.
  if (!stamp) return 'Pantheon has not used this yet.';
  const when = new Date(stamp);
  if (Number.isNaN(when.getTime())) return 'Pantheon has used this.';
  return `Pantheon last used this on ${when.toLocaleDateString()}.`;
}

/**
 * Revoke one rule. Resolves `'revoked'`, `'gone'` or `'failed'`.
 *
 * `'gone'` is a 404, which for the caller's own list means the rule is not
 * there any more — another tab, another device, or a revoke that landed twice.
 * It is reported separately rather than as a failure because the person's
 * intent has been served, and drawn the same way as a success for the same
 * reason: leaving a row on screen for a grant the server says does not exist
 * would be this surface telling the lie it was built to stop telling.
 */
export async function revokeAllowRule(id) {
  const key = String(id == null ? '' : id).trim();
  if (!key) return 'failed';
  let res = null;
  try {
    res = await fetch(`${ALLOW_RULE_API}/${encodeURIComponent(key)}`, {
      method: 'DELETE',
      credentials: 'same-origin',
    });
  } catch (_) {
    return 'failed';
  }
  if (res && res.ok) {
    _rules = _rules.filter((rule) => !(rule && String(rule.id) === key));
    return 'revoked';
  }
  if (res && res.status === 404) {
    _rules = _rules.filter((rule) => !(rule && String(rule.id) === key));
    return 'gone';
  }
  return 'failed';
}

/**
 * Draw the list into `host`, or empty and hide it when there is nothing to say.
 *
 * Two conditions, the same two the chooser answers to. Off the rung that reads
 * rules, a saved rule still exists and is simply not consulted, and a list of
 * grants shown beside a setting that ignores them would read as a promise the
 * run will not keep. And before the store has answered — a build with no such
 * route, a caller `_allow_rule_owner` refuses, a store that 500s — there is no
 * list to draw and "Nothing yet" would be a claim about a store nobody managed
 * to ask.
 *
 * Hidden rather than removed: the rules survive in `_rules`, so moving back
 * onto the rung redraws them without another request.
 */
export function renderAllowRuleList(host, rung) {
  if (!host) return null;
  host.textContent = '';
  const on = _coerceRung(rung) === 'allow_listed' && _rulesKnown;
  host.hidden = !on;
  if (!on) return null;

  host.appendChild(_el('div', 'allow-rule-list-title', ALLOW_RULE_LIST_TITLE));
  host.appendChild(_el('p', 'allow-rule-list-hint', ALLOW_RULE_LIST_HINT));

  const status = _el('div', 'allow-rule-list-status', '');
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  host.appendChild(status);

  if (!_rules.length) {
    host.appendChild(_el('p', 'allow-rule-list-empty', ALLOW_RULE_LIST_EMPTY));
    return host;
  }

  const rows = _el('div', 'allow-rule-list-rows');
  host.appendChild(rows);

  _rules.forEach((rule) => {
    const words = _storedRuleWording(rule);
    const row = _el('div', 'allow-rule-row');
    row.dataset.ruleId = String((rule && rule.id) || '');
    row.dataset.ruleMatch = String((rule && rule.match_kind) || '');

    const text = _el('span', 'allow-rule-row-text');
    text.appendChild(_el('span', 'allow-rule-row-label', words.label));
    if (words.detail) text.appendChild(_el('span', 'allow-rule-row-detail', words.detail));
    text.appendChild(_el('span', 'allow-rule-row-sentence', words.sentence));
    text.appendChild(_el('span', 'allow-rule-row-when', _storedRuleWhen(rule)));
    row.appendChild(text);

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'allow-rule-revoke';
    button.textContent = 'Revoke';
    // Twenty buttons all reading "Revoke" name nothing to anyone who cannot see
    // the row they sit in.
    button.setAttribute('aria-label', `Revoke: ${words.label}`);
    button.addEventListener('click', () => {
      if (button.disabled) return;
      button.disabled = true;
      status.textContent = 'Revoking…';
      revokeAllowRule(row.dataset.ruleId).then((outcome) => {
        if (outcome === 'failed') {
          // `Law 13`. The row stays, the button comes back, and the sentence
          // says the thing that is actually true and unwelcome: the grant is
          // still standing. A silent failure here leaves someone believing they
          // took a permission back when they did not.
          button.disabled = false;
          status.textContent =
            'That could not be taken back, so Pantheon can still do it without '
            + 'asking. Try again in a moment.';
          return;
        }
        row.remove();
        if (!rows.children.length) {
          rows.remove();
          host.appendChild(_el('p', 'allow-rule-list-empty', ALLOW_RULE_LIST_EMPTY));
        }
        status.textContent = outcome === 'gone'
          ? 'That one had already gone. Pantheon will ask before it does that again.'
          : 'Taken back. Pantheon will ask before it does that again.';
      });
    });
    row.appendChild(button);
    rows.appendChild(row);
  });
  return host;
}

// Self-init. `initTrustLadder` is a no-op without `#trust-ladder` in the page,
// so importing this module anywhere is safe; the settings read it starts is the
// same cached one every other module shares (`appConfig.js`).
if (typeof document !== 'undefined') {
  initTrustLadder().catch(() => {});
}
