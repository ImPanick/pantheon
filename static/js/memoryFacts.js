// SPDX-License-Identifier: AGPL-3.0-or-later
// `P13-01` / `B643`. What a memory's numbers mean, as data.
//
// This module imports **nothing**, deliberately, and that is why it exists.
// `chatRenderer.js` needs these helpers for the memory pill and `memory.js`
// needs them for the Brain list, and `chatRenderer` cannot import `memory.js`:
// `memory.js` → `sessions.js` → `chatRenderer.js` is a cycle, which is also
// why `sessions.js` reaches the Brain through `window.memoryModule` and says
// so at its own call site. `P13-02` hit the same bind in Python and answered
// it the same way — `src/memory_edges.py` is the vocabulary and imports
// nothing from the project — so this is that precedent on the browser side.

/** Python's `normalise_confidence` (`src/memory.py`), in a browser.
 *
 *  Two copies because one is Python and one is a browser, the arrangement
 *  `MEMORY_ENGINE_LABELS` already uses a few lines away in `chatRenderer.js`,
 *  and a test drives both over one table rather than trusting that whoever
 *  changes the rule remembers both. That arrangement earned its keep twice in
 *  one day on `B1404`, where the two sides disagreed on a rounding tie.
 *
 *  The cases that matter are the ones that change what a reader sees, not the
 *  third decimal place:
 *
 *   * `null`/absent is **not recorded**, and stays not recorded. Every memory
 *     written before `P13-01` reads this, and so does one a person typed in:
 *     they are not a 1.0, they are a producer nobody asked. A number invented
 *     for a record nobody assessed makes an old memory look freshly checked,
 *     which is the `PandAtlas` failure this phase's preamble cites.
 *   * a **boolean** is not a number. `Number(true)` is 1 in JavaScript, so
 *     without this guard `confidence: true` would render as `100%` — the most
 *     confident thing on the page, from a field nobody set.
 *   * `NaN` parses and then poisons every comparison, so it is rejected
 *     rather than clamped.
 *   * out of range is **clamped, not rejected**: a model asked for 0..1 will
 *     occasionally answer 1.5, and the useful reading of that is "very sure"
 *     rather than "unparseable". Python's comment says exactly this.
 *
 *  Returns `fallback` (default `null`) when there is no usable number.
 */
export function normaliseConfidence(value, fallback = null) {
  if (value === null || value === undefined || typeof value === 'boolean') return fallback;
  // `Number('')` and `Number('   ')` are **0** in JavaScript, where Python's
  // `float('')` raises and the field reads as not recorded. Without this an
  // empty confidence renders `0%` — *somebody looked and was sure it was
  // wrong* — which is the opposite of *nobody looked*. Found by driving the
  // two implementations over one table rather than by reading either.
  if (typeof value === 'string' && value.trim() === '') return fallback;
  const number = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(number)) return fallback;
  const clamped = Math.min(Math.max(number, 0), 1);
  return _round3(clamped);
}

/** Python's `round(x, 3)`, including its tie rule.
 *
 *  `toFixed` rounds a tie **away from zero** and Python rounds it **to even**,
 *  so `0.0625` is `0.063` here and `0.062` there. That is `B1404`'s defect for
 *  the second time in one day — there `Math.round` and Python's `round`
 *  disagreed on a channel that landed on `.5` — and it is caught the same way,
 *  by a test that drives both sides instead of reading one.
 *
 *  A tie at three decimals needs `x * 2000` to be an odd integer, which only
 *  a dyadic value such as `0.0625` or `0.1875` can manage; everything else is
 *  decided by `toFixed` on the true binary value, exactly as Python decides
 *  it. Scaling by 1000 first does NOT work: `0.6665 * 1000` is
 *  `666.5000000000001`, so a scaled compare reads a tie where Python sees a
 *  value just under one and rounds down.
 */
function _round3(x) {
  const doubled = x * 2000;
  if (Number.isInteger(doubled) && Math.abs(doubled) % 2 === 1) {
    const floor = Math.floor(x * 1000);
    return (floor % 2 === 0 ? floor : floor + 1) / 1000;
  }
  return Number(x.toFixed(3));
}

/** The integer percent a confidence is shown as, or `null` for not recorded.
 *
 *  Half-up, stated rather than inherited: `Math.round` is half-up and Python's
 *  `round` is half-to-even, so the one number that reaches a reader is
 *  computed here by a rule written down in one place and checked against the
 *  server's over a table of adversarial values.
 */
export function confidencePercent(value) {
  const confidence = normaliseConfidence(value);
  if (confidence === null) return null;
  return Math.floor(confidence * 100 + 0.5);
}

/** The confidence pill for one memory, or `null` when there is nothing to say.
 *
 *  `null` rather than an empty pill, because "nobody assessed this" and
 *  "assessed at 0%" are different claims and an empty box says neither. A
 *  recorded **zero** does render, as `0%`: somebody looked and was not sure,
 *  and that is a fact about the memory rather than an absence of one.
 */
export function memoryConfidencePill(memory) {
  const percent = confidencePercent(memory && memory.confidence);
  if (percent === null) return null;
  return {
    className: 'memory-confidence',
    text: `${percent}%`,
    // Says which number it is. `confidence` is the extractor's self-report at
    // the moment of extraction and never moves on its own; corroboration is
    // `mentions`/`mention_sessions` and moves every time you bring something
    // up. `PandAtlas` ships them merged and it reads `CONFIDENCE 66%` beside
    // `1 mentions` — two-thirds certainty from a single unconfirmed
    // statement, which looks like evidence and is not.
    title: `How sure the extractor was, when it wrote this down, that you`
      + ` actually said it — ${percent}%. It does not change on its own;`
      + ` how often you have brought this up is counted separately.`,
  };
}

// `P13-15`. The two count pills, as data.
//
// `uses` counts how often the SYSTEM reached for this memory and put it in a
// prompt. `mention_sessions` counts how many separate conversations the PERSON
// raised it in. A memory the assistant keeps injecting and a memory you keep
// bringing up are different kinds of important, and one number cannot mean
// both — so they are two pills, built from two fields, and each title says
// which is which. A bare "11×" beside a bare "said in 3" is a riddle.
//
// Exported as data rather than built inline so a test can run it instead of
// reading it (`Law 20`). `B61` is why: a mutation that computed a value
// correctly and never put it on screen survived every test of the helper.
//
// Moved here from `memory.js` by `P13-01`, with its test: the confidence pill
// is the same kind of thing about the same records, and one of the two living
// in a window module while its sibling lived in a shared one is the split
// `Law 7` is about.
export function memoryCountPills(memory) {
  const uses = Number((memory && memory.uses) || 0);
  const sessions = Number((memory && memory.mention_sessions) || 0);
  const pills = [];
  if (uses > 0) {
    pills.push({
      className: 'memory-item-uses',
      text: `${uses}×`,
      title: `Injected into chat context ${uses} time${uses === 1 ? '' : 's'}`,
    });
  }
  // Two or more: one conversation is not a pattern, and "said in 1" beside a
  // memory that was created by being said once is noise.
  if (sessions > 1) {
    pills.push({
      className: 'memory-item-mentions',
      text: `said in ${sessions}`,
      title: `You have brought this up in ${sessions} separate chats`
        + ` — which is why it ranks a little higher. Different from the ${uses}× above,`
        + ` which counts how often it was injected into a chat.`,
    });
  }
  return pills;
}
