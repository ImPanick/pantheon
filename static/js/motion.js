// SPDX-License-Identifier: AGPL-3.0-or-later
// One answer to "does this person want motion?", for the code that CSS cannot
// reach.
//
// P1-12. The global guard in style.css handles every CSS animation and
// transition in the product — including the ones injected into document.head at
// runtime, because an `!important` author declaration beats a normal one
// wherever the stylesheet came from. What it cannot touch is motion a script
// produces frame by frame: seven full-screen canvas background animators, and
// smooth scrolling, which `scrollIntoView({behavior:'smooth'})` performs in
// spite of `scroll-behavior: auto`.
//
// Read live, not cached at load. Someone turning the OS preference on should
// not have to reload the page to be believed, and this is one `matchMedia` call
// — cheaper than the frame it is deciding about.

const QUERY = '(prefers-reduced-motion: reduce)';

/** True when the operating system says to reduce motion. */
export function prefersReducedMotion() {
  try {
    return !!(window.matchMedia && window.matchMedia(QUERY).matches);
  } catch (_) {
    // matchMedia throws in a few embedded webviews. Erring towards motion
    // matches what the browser does with no preference set at all.
    return false;
  }
}

/** `'auto'` or `'smooth'`, for a ScrollToOptions / ScrollIntoViewOptions. */
export function scrollBehavior() {
  return prefersReducedMotion() ? 'auto' : 'smooth';
}


/** `B1567`. Run `finish` once, when `content`'s own closing animation ends or
 *  after `ms`, whichever comes first — and take the other one back.
 *
 *  Every window that animates shut did this as two independent callbacks: an
 *  `animationend` listener (`{ once: true }`) and a 250 ms fallback timer. When
 *  the timer won — a starved frame, a busy machine — it hid the window and the
 *  listener stayed attached, because display:none cut the animation it was
 *  waiting for. The next time the window opened, its OPENING animation's end
 *  fired that stale listener and the window shut itself about 300 ms after it
 *  appeared (measured on the Brain, its third open in a row). One answer, run
 *  once, with the listener removed whichever path finishes: the shape
 *  `cookbook.js` `_doClose` reached with a generation counter. A descendant's
 *  animation ending is not the window's, so it is ignored. */
export function whenShut(content, finish, ms = 250) {
  let done = false;
  let timer = null;
  const onEnd = (e) => { if (!e || e.target === content) run(); };
  function run() {
    if (done) return;
    done = true;
    content.removeEventListener('animationend', onEnd);
    clearTimeout(timer);
    finish();
  }
  content.addEventListener('animationend', onEnd);
  timer = setTimeout(run, ms);
  return run;
}
