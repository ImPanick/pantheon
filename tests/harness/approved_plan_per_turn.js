// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B06`. Runs the real send-site block out of `chat.js` **twice against the
// same closure** and reports what each turn put in the form.
//
// The property the row asks for cannot be read out of the file, and the row's
// own `Verify` line asks for the wrong thing. "Round" in this codebase means a
// tool iteration inside one HTTP request (`agent_loop.py`'s
// `for round_num in range(1, max_rounds + 1)`), and the verifier instruction is
// built once per request above that loop — so *"the checklist is in the
// verifier's instruction on all four rounds"* was already true and would have
// ticked the row on a passing observation. The defect is about TURNS: the
// second HTTP request, after `Continue ▸` or any follow-up the user types.
//
// Two turns, one closure, and look at what the second one sent.
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'static', 'js', 'chat.js');
const START = '      const toggleState = Storage.loadToggleState();';
const END = "	      if (el('web-toggle').checked) {";

const source = fs.readFileSync(SRC, 'utf8');
const from = source.indexOf(START);
const to = source.indexOf(END, from);
if (from < 0 || to < 0 || to <= from) {
  console.error('ANCHOR-MISSING: could not extract the send block from chat.js');
  process.exit(2);
}
const block = source.slice(from, to);

// `executing` is what `planWindow.isExecuting()` answers. Turn 1 and turn 2 are
// the same run, so it is true both times — that is the whole question.
const mode = process.argv[2] || 'executing';
const PLAN = '- [ ] step one\n- [ ] step two';

function turn() {
  const appended = {};
  const fd = { append: (k, v) => { appended[k] = v; }, set: (k, v) => { appended[k] = v; } };
  const Storage = { loadToggleState: () => ({ plan_mode: false, mode: 'chat' }) };
  const el = () => ({ checked: false });
  const planWindow = {
    isExecuting: () => mode === 'executing',
    getPlan: () => PLAN,
  };
  const _getStoredPlan = () => planWindow.getPlan();
  const msg = 'You hit the step limit before finishing — continue from exactly where you left off.';

  const run = new Function(
    'fd', 'Storage', 'el', 'planWindow', '_getStoredPlan', 'msg',
    'isIncognitoForSend', 'documentModule', 'activeDocIdForSend',
    block,
  );
  run(fd, Storage, el, planWindow, _getStoredPlan, msg, false, null, null);
  return appended;
}

const one = turn();
const two = turn();
console.log(JSON.stringify({
  turn1_has_plan: Object.prototype.hasOwnProperty.call(one, 'approved_plan'),
  turn2_has_plan: Object.prototype.hasOwnProperty.call(two, 'approved_plan'),
  turn1_mode: one.mode,
  turn2_mode: two.mode,
}));
