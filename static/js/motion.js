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

/**
 * Run `fn(reduced)` whenever the preference changes, and return an unsubscribe.
 * Nothing needs this yet; it exists so the next thing that does has one place
 * to put the listener rather than a second copy of the query string.
 */
export function onMotionPreferenceChange(fn) {
  let mq;
  try {
    mq = window.matchMedia && window.matchMedia(QUERY);
  } catch (_) {
    return () => {};
  }
  if (!mq) return () => {};
  const handler = (e) => fn(!!e.matches);
  // Safari before 14 has no addEventListener on MediaQueryList.
  if (mq.addEventListener) {
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }
  mq.addListener(handler);
  return () => mq.removeListener(handler);
}
