// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/checklist.js

/**
 * `B11`/`B12`. What the two checklist surfaces ARE, and the three small facts
 * their rows were each spelling for themselves.
 *
 * ── What was measured ───────────────────────────────────────────────────────
 * `tests/harness/checklist_surfaces.js` runs both renderers — `planWindow.js`'s
 * `renderStep` and `chatRenderer.js`'s `buildTodoCard` — over the same three
 * steps and compares what they emit. Two of the three states come out
 * **structurally identical**, class-for-class and element-for-element:
 *
 *     <li class="plan-step task-item task-done">
 *       <span class="task-check" role="img" aria-label="done"></span>
 *       <span class="plan-step-main"><span class="task-text">…</span></span></li>
 *
 * That is not a defect. One row system, joined by selector in `style.css`
 * (`P6-17`), is `Law 14` working: a step and a todo item ARE the same object,
 * and forking them would be the mistake. The defect is one level up. The two
 * cards those rows sit in mean opposite things — an **approved plan** is a
 * commitment the user signed off and the agent is executing; an **agent task
 * list** is the model's own scratch list, which it rewrites whenever it likes
 * and which nobody approved — and the heads read:
 *
 *     Active plan · 1 of 2 done · Executing
 *     Task list · 1 of 2 done
 *
 * Those two are as alike as their rows, and the count reads identically in
 * both. Worse, the todo card's own `aria-label` already says **"Agent task
 * list"** while its visible title says only "Task list": the screen reader was
 * being told which list it is and the eye was not. A surface where the eye gets
 * less than the accessible name is `Law 15` failing in the one direction nobody
 * checks.
 *
 * ── What carries the distinction, and why it is here ────────────────────────
 * The container, in words — because that is where the difference actually lives
 * and because a new badge or tint would be a symbol a stranger has to be taught
 * (`Law 15`). Both surfaces now say, in a line under their head, what the list
 * is and whose it is. **The two sentences live side by side in this table on
 * purpose**: written together they cannot drift into saying the same thing,
 * which is exactly how the two heads converged in the first place.
 *
 * The rows stay one system. Nothing below styles a step differently on one
 * surface, and `.plan-step-chip` is spelled here once rather than in two
 * renderers, so they cannot fall out of step again.
 */

/**
 * The two checklist surfaces. `title` is what a person reads; `ariaLabel` is
 * what a screen reader reads, and they are the same string by construction
 * rather than by good intentions — that they had diverged is this row.
 */
export const CHECKLIST_SURFACES = {
  plan: {
    kind: 'plan',
    title: 'Active plan',
    ariaLabel: 'Active plan',
    blurb: 'Steps you approved. The agent works down this list.',
  },
  agentTodo: {
    kind: 'agent-todo',
    // "Agent" is not a new word: it is the word this card's own aria-label has
    // carried since it shipped. The eye is being told what the screen reader
    // already was.
    title: 'Agent task list',
    ariaLabel: 'Agent task list',
    blurb: 'The agent’s own working list. It rewrites this as it goes.',
  },
};

/**
 * The progress line both heads show. It was `${done} of ${total} done` in
 * `planWindow.js` and `done + ' of ' + total + ' done'` in `chatRenderer.js` —
 * the same sentence, twice, in two spellings.
 */
export function checklistProgress(done, total) {
  return `${done} of ${total} done`;
}

/**
 * The class list for a step's chip. `planWindow.js` builds chips as DOM and
 * `chatRenderer.js` builds them as a string; the *technique* is each renderer's
 * business — one escapes with `textContent`, the other through `esc()`, and
 * forcing either to change would be a rewrite, not an elevation. What they must
 * not each decide is the class, so only that is shared.
 */
export const STEP_CHIP_CLASS = 'plan-step-chip';
export function stepChipClass(modifier) {
  return modifier ? `${STEP_CHIP_CLASS} ${modifier}` : STEP_CHIP_CLASS;
}

/**
 * The play triangle on the Execute-plan control.
 *
 * `.plan-inline-execute` is ONE control with two builders — the docked window
 * (`planWindow.js`) and the inline actions on a plan-mode bubble
 * (`chat.js:_attachPlanActions`) — and each drew its own polygon. `B12` shared
 * them here on the majority of the seven sites it could see.
 *
 * `B83` re-measured the whole surface: **eighteen** play triangles in **four**
 * geometries, and `6 4 20 12 6 20 6 4` is the minority of those. The glyph's
 * home is `icons.js` now — a triangle five unrelated modules want does not
 * belong in the checklist module — and this is a re-export, not a second copy,
 * so the two builders that import it from here keep working (`Law 1`).
 */
export { PLAY_POINTS } from './icons.js';
