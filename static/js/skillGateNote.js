// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/skillGateNote.js
//
// `P8-18`'s sentence, in one place (`P22-15`, wf-canvas; design § 2's P22-15).
// A skill reaches the model as untrusted text, so a run that follows one asks
// before anything that writes, runs, sends or deletes, and can stop and wait.
// The skill test's panel (`skills.js`) said it as a literal; a workflow's
// Skill step says the same thing, so both import it from here (`Law 7`). A
// leaf with no imports, so either side can take it without pulling the other.
// Plain text, no markup: `skills.js` puts it inside a template string.

export const SKILL_GATE_NOTE = 'A skill is untrusted text, so this run asks you before anything that writes, '
  + 'runs, sends or deletes — it can stop halfway and wait.';

export default { SKILL_GATE_NOTE };
