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

// `D-26` (P23-02, Doc 2 § 5): the why is said once, in Skills › Settings; here
// only what the run will do.
export const SKILL_GATE_NOTE = 'The run asks before it writes, runs, sends or deletes.';

export default { SKILL_GATE_NOTE };
