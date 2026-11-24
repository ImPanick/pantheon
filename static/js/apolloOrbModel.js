// SPDX-License-Identifier: AGPL-3.0-or-later
// Apollo's orb, the parts with no DOM (phase 6): which mood the signals add up
// to, how each mood looks, where the orb sits, and where a marked line range
// is. `apolloOrb.js` draws it; the cases in
// `tests/test_apollos_orb_shows_its_mood_and_points_js.py` read these.

/** Moods, most pressing first. Listening beats speaking: when the person
 *  talks, the orb is theirs. Needs you is the colour of the resting orb. */
export const MOODS = ['listening', 'speaking', 'thinking', 'needs', 'idle'];

export const MOOD_WORDS = {
  listening: 'listening',
  speaking: 'speaking',
  thinking: 'thinking',
  needs: 'something needs you',
  idle: 'idle',
};

/** One mood from what the page has said. `s` holds booleans:
 *  listening (dictation on), speaking (a reply being read aloud), thinking
 *  (Apollo's chat is busy), needs (a task waits on the person). */
export function mood(s) {
  const x = s || {};
  for (const m of MOODS) if (m !== 'idle' && x[m]) return m;
  return 'idle';
}

// The sun: a warm core, a corona, and how each mood moves it. Periods are in
// seconds; amp is how far the glow swells. Kept here so a test can hold the
// moods apart and the canvas only reads numbers.
const LOOK = {
  idle:      { core: '#ffd27a', rim: '#f29e38', halo: 'rgba(255,190,90,', period: 4.2, amp: 0.06, swirl: 0,    ring: 0 },
  listening: { core: '#fff3d1', rim: '#ffc45c', halo: 'rgba(255,230,170,', period: 1.1, amp: 0.10, swirl: 0,    ring: 1 },
  thinking:  { core: '#ffe08a', rim: '#f5a524', halo: 'rgba(255,200,90,', period: 2.0, amp: 0.08, swirl: 1.6,  ring: 0 },
  speaking:  { core: '#ffe9a8', rim: '#f7b13d', halo: 'rgba(255,214,120,', period: 0.9, amp: 0.12, swirl: 0.4,  ring: 2 },
  needs:     { core: '#ffc04d', rim: '#e8700c', halo: 'rgba(255,150,40,', period: 1.6, amp: 0.12, swirl: 0,    ring: 0 },
};

export function look(m) { return LOOK[m] || LOOK.idle; }

/** How big the glow is at time `t` (seconds). `level` (0..1) is the voice's
 *  loudness while speaking; with no level the swell is the mood's own beat.
 *  `still` holds it at rest, for reduced motion. */
export function glow(m, t, level = null, still = false) {
  const L = look(m);
  if (still) return 1;
  if (m === 'speaking' && typeof level === 'number' && level >= 0) {
    return 1 + Math.min(1, level) * L.amp * 2.2;
  }
  return 1 + Math.sin((t / L.period) * Math.PI * 2) * L.amp;
}

/** Keep a square of `size` inside the viewport with `margin` round it. */
export function clamp(pos, size, vw, vh, margin = 8) {
  const maxX = Math.max(margin, vw - size - margin);
  const maxY = Math.max(margin, vh - size - margin);
  const x = Math.round(Math.min(maxX, Math.max(margin, Number(pos && pos.x) || 0)));
  const y = Math.round(Math.min(maxY, Math.max(margin, Number(pos && pos.y) || 0)));
  return { x, y };
}

/** Where the orb rests until the person moves it: bottom right, clear of the
 *  composer's send button. */
export function home(size, vw, vh) {
  return clamp({ x: vw - size - 28, y: vh - size - 132 }, size, vw, vh);
}

/** Where the orb goes to point at `r` (a rect: left, top, width, height):
 *  beside it on the left when there's room, else on the right, else above,
 *  else below, centred on it. `side` says which, for the beam. */
export function besideRect(r, size, vw, vh, gap = 14) {
  const cy = r.top + r.height / 2 - size / 2;
  const cx = r.left + r.width / 2 - size / 2;
  const tries = [
    ['left', { x: r.left - size - gap, y: cy }, r.left - size - gap >= 8],
    ['right', { x: r.left + r.width + gap, y: cy }, r.left + r.width + gap + size <= vw - 8],
    ['above', { x: cx, y: r.top - size - gap }, r.top - size - gap >= 8],
    ['below', { x: cx, y: r.top + r.height + gap }, r.top + r.height + gap + size <= vh - 8],
  ];
  const pick = tries.find((t) => t[2]) || tries[0];
  return { ...clamp(pick[1], size, vw, vh), side: pick[0] };
}

/** One rect round several (a line range that wraps onto many boxes). */
export function union(rects) {
  const list = (rects || []).filter((r) => r && (r.width > 0 || r.height > 0));
  if (!list.length) return null;
  const left = Math.min(...list.map((r) => r.left));
  const top = Math.min(...list.map((r) => r.top));
  const right = Math.max(...list.map((r) => r.left + r.width));
  const bottom = Math.max(...list.map((r) => r.top + r.height));
  return { left, top, width: right - left, height: bottom - top };
}

/** Character offsets of lines `from`..`to` (1-based, inclusive) in `text`:
 *  [start, end), end at the last line's newline. Null when the range starts
 *  past the end; a range running past the end stops at the last line. */
export function lineSpan(text, from, to) {
  const s = String(text || '');
  const a = Math.max(1, Math.floor(Number(from) || 1));
  const b = Math.max(a, Math.floor(Number(to) || a));
  let start = 0;
  let line = 1;
  while (line < a) {
    const nl = s.indexOf('\n', start);
    if (nl < 0) return null;
    start = nl + 1;
    line += 1;
  }
  if (start >= s.length && a > 1) return null;
  let end = start;
  while (line <= b) {
    const nl = s.indexOf('\n', end);
    if (nl < 0) { end = s.length; break; }
    end = nl;
    if (line === b) break;
    end = nl + 1;
    line += 1;
  }
  return [start, end];
}

/** The words the orb says beside itself for a show, or '' for none. */
export function showWords(detail) {
  const d = detail || {};
  const label = typeof d.label === 'string' ? d.label.trim().slice(0, 140) : '';
  if (label) return label;
  if (Array.isArray(d.lines) && d.lines.length === 2) {
    return d.lines[0] === d.lines[1] ? `Line ${d.lines[0]}` : `Lines ${d.lines[0]} to ${d.lines[1]}`;
  }
  return '';
}

/** Read a show event: the place and its target, or null for one the orb
 *  can't follow. Mirrors `src/apollo/orb.py:PLACES`. */
export const PLACES = ['home', 'pane', 'needs_you', 'activity', 'task', 'chat_input', 'code', 'view', 'selector'];

export function readShow(d) {
  if (!d || typeof d.place !== 'string' || !PLACES.includes(d.place)) return null;
  const out = { place: d.place };
  if (d.target !== undefined && d.target !== null && d.target !== '') out.target = d.target;
  if ((d.place === 'task' || d.place === 'view') && out.target === undefined) return null;
  if (d.place === 'selector') {
    if (typeof d.selector !== 'string' || !d.selector.trim()) return null;
    out.selector = d.selector;
    out.glideOnly = !!d.glideOnly;
  }
  if (Array.isArray(d.lines) && d.lines.length === 2 && d.lines.every((n) => Number.isInteger(n) && n > 0)) {
    out.lines = [Math.min(d.lines[0], d.lines[1]), Math.max(d.lines[0], d.lines[1])];
  }
  out.words = showWords({ label: d.label, lines: out.lines });
  return out;
}
