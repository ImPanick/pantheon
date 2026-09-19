// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `P15-11`. Runs the email library's sync-status line over the payloads the
// server actually sends, and prints the sentence a person reads.
//
// Reading the file answers a different question. `_renderEmailSyncStatus` is
// four lines of `parts.push`, and what makes the row true is which of them run
// for `{"source": "unavailable", "retry_in": 240}` — the response
// `routes/email_routes.py` has been sending since `P15-12` and which both
// clients dropped. Only running it shows that the line used to read
// "Last updated: 2d ago" and nothing else, which is the sentence that makes a
// person sit and wait for mail that is not coming.
//
// The vocabulary is the REAL `runStatus.js`, evaluated as written, not a stub:
// the row's whole point is that the renderer does not get to invent the words,
// so a harness that retyped them would prove the renderer agrees with the
// harness.
//
// The clock is fake and settable, because the countdown is the half of the
// row's `Verify` that a single render cannot see: a notice that prints "in 15
// min" once and then says it for ever is a countdown in appearance only.
//
// Usage:
//   node email_sync_throttle.js line '<json>'      # one payload -> the line
//   node email_sync_throttle.js poll '<json>'      # via noteMailboxSync
//   node email_sync_throttle.js seq  '<json>'      # steps -> the line after each
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const JS = path.join(__dirname, '..', '..', 'static', 'js');
const librarySrc = fs.readFileSync(path.join(JS, 'emailLibrary.js'), 'utf8');
const wordsSrc = fs.readFileSync(path.join(JS, 'runStatus.js'), 'utf8')
  .replace(/^export\s+/gm, '');

/** A top-level `function name(...) { ... }`, ending at the first `}` in column 0. */
function fn(src, name) {
  const start = src.indexOf(`\nfunction ${name}(`);
  const exported = src.indexOf(`\nexport function ${name}(`);
  const at = start >= 0 ? start : exported;
  if (at < 0) throw new Error(`${name} not found`);
  const from = src.indexOf('function', at);
  const end = src.indexOf('\n}\n', from);
  if (end < 0) throw new Error(`${name} has no end`);
  return src.slice(from, end + 3);
}

/** The `let _libSyncStatus = { ... };` declaration, as written. */
function decl(src, name) {
  const at = src.indexOf(`let ${name} = {`);
  if (at < 0) throw new Error(`${name} not found`);
  const end = src.indexOf('\n};', at);
  return src.slice(at, end + 3);
}

const el = { textContent: '', title: '', style: { visibility: '' } };
const CHIP = [];
let CLOCK = Date.parse('2026-09-18T12:00:00Z');
class FakeDate extends Date {
  constructor(...args) {
    if (args.length === 0) super(CLOCK); else super(...args);
  }
  static now() { return CLOCK; }
  static parse(v) { return Date.parse(v); }
}
const sandbox = {
  console,
  Date: FakeDate,
  Number,
  Math,
  Object,
  String,
  document: { getElementById: (id) => (id === 'email-lib-sync-status' ? el : null) },
  state: { _libEmails: [{ uid: 1 }], _libOpen: true },
  // `P9-11`. The poll now also puts the throttle on the minimized dock, because
  // the window this line lives in is usually closed when a mailbox goes quiet.
  // Recorded rather than stubbed away: `chip` is read by the `poll` mode below,
  // so the same harness answers both "what does the line say" and "what does
  // the dock say" from one run of the real code.
  Modals: { setBackgroundWork: (id, work) => { CHIP.push({ id, work }); return true; } },
  openEmailLibrary: () => { CHIP.push({ opened: true }); },
};
vm.createContext(sandbox);
vm.runInContext(
  wordsSrc + '\n'
  + decl(librarySrc, '_libSyncStatus') + '\n'
  + fn(librarySrc, '_libSyncDateFrom') + '\n'
  + fn(librarySrc, '_libRelativeTime') + '\n'
  + fn(librarySrc, '_libThrottleRemaining') + '\n'
  + fn(librarySrc, '_renderEmailSyncStatus') + '\n'
  + fn(librarySrc, '_setEmailSyncStatus') + '\n'
  + fn(librarySrc, '_syncMailboxWorkChip') + '\n'
  + fn(librarySrc, 'noteMailboxSync') + '\n',
  sandbox);

const mode = process.argv[2];
const payload = JSON.parse(process.argv[3] || '{}');

function read() {
  return { line: el.textContent, title: el.title, visibility: el.style.visibility };
}

if (mode === 'line') {
  // What a list response does: a timestamp, a source, and (when the server is
  // telling us to stay away) a countdown.
  sandbox._setEmailSyncStatus({
    updatedAt: payload.updated_at || '',
    source: payload.source || '',
    retryIn: payload.retry_in || 0,
    throttleDetail: payload.detail || '',
    loading: false,
  });
  console.log(JSON.stringify(read()));
} else if (mode === 'poll') {
  // What the 60-second unread poll does, through the door `emailInbox.js` calls.
  sandbox._setEmailSyncStatus({ updatedAt: payload.updated_at || '', loading: false });
  for (const sync of payload.polls || []) sandbox.noteMailboxSync(sync);
  console.log(JSON.stringify({ ...read(), chip: CHIP[CHIP.length - 1] || null }));
} else if (mode === 'seq') {
  const lines = [];
  for (const step of payload.steps || []) {
    if (step.advance) { CLOCK += step.advance * 1000; }
    else if (step.poll) { sandbox.noteMailboxSync(step.poll); }
    else if (step.sync) {
      sandbox._setEmailSyncStatus({
        updatedAt: step.sync.updated_at || '',
        source: step.sync.source || '',
        retryIn: step.sync.retry_in || 0,
        throttleDetail: step.sync.detail || '',
        loading: false,
      });
    }
    sandbox._renderEmailSyncStatus();
    lines.push(el.textContent);
  }
  console.log(JSON.stringify({ lines }));
} else {
  throw new Error(`unknown mode ${mode}`);
}
