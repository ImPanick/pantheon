// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B83`. The shared icon table, and the modules that draw its glyphs.
//
// Two questions, and only the first can be answered by reading a file.
//
//   1. How many play triangles and stop squares does the tree spell out?
//      That is a claim about SOURCE and it is made in the pytest beside this
//      file, with comments blanked (`B87`) — a comment of mine explaining why
//      there is only one triangle would otherwise count as a second one.
//
//   2. What does a module actually EMIT? `queuePanel.js` and the Activity row
//      draw play and stop side by side, and the defect `B83` names is that the
//      two were a pixel apart in a 24-unit box. Reading the source after the
//      change tells you both call `playIcon`; it does not tell you they get the
//      same polygon out, because `playIcon` takes options and an option could
//      change the geometry. So the real modules are loaded and asked.
//
// Usage:
//   node icon_table.js glyphs
//   node icon_table.js panel      — what queuePanel.js's two constants emit
const fs = require('fs');
const path = require('path');

const JSDIR = path.join(__dirname, '..', '..', 'static', 'js');
const read = (rel) => fs.readFileSync(path.join(JSDIR, rel), 'utf8');
// The real table, inlined rather than stubbed: it is a leaf module with no
// imports, which is what makes evaluating the shipped file cheap.
const icons = read('icons.js').replace(/^export\s+/gm, '');

function slice(source, startMark, endMark, label) {
  const from = source.indexOf(startMark);
  if (from < 0) {
    console.error(`ANCHOR-MISSING: ${label} start (${startMark})`);
    process.exit(2);
  }
  const to = source.indexOf(endMark, from);
  if (to < 0 || to <= from) {
    console.error(`ANCHOR-MISSING: ${label} end (${endMark})`);
    process.exit(2);
  }
  return source.slice(from, to);
}

const mode = process.argv[2] || 'glyphs';

if (mode === 'glyphs') {
  const api = new Function(`
    ${icons}
    return { PLAY_POINTS, PLAY_GLYPH, STOP_GLYPH, iconSvg, playIcon, stopIcon };
  `)();
  console.log(JSON.stringify({
    points: api.PLAY_POINTS,
    playGlyph: api.PLAY_GLYPH,
    stopGlyph: api.STOP_GLYPH,
    // Every form a call site asks for, so "one triangle" can be checked against
    // what comes out rather than against what goes in.
    filled: api.playIcon({ size: 9 }),
    outline: api.playIcon({ size: 14, outline: true }),
    styled: api.playIcon({ size: 11, style: 'vertical-align:-1px;' }),
    stop: api.stopIcon({ size: 9 }),
    // The polygon each of those carries. One distinct value is the whole row.
    polygons: [
      api.playIcon({ size: 8 }), api.playIcon({ size: 14, outline: true }),
      api.playIcon({ size: 13, style: 'x' }), api.PLAY_GLYPH,
    ].map((s) => (s.match(/points="([^"]*)"/) || [])[1]),
    rects: [api.stopIcon({ size: 9 }), api.stopIcon({ size: 14 }), api.STOP_GLYPH]
      .map((s) => (s.match(/<rect[^>]*>/) || [])[0]),
    // `Themes are protected`: an icon table that named a colour would be a
    // seventeenth theme. Every paint attribute the table can emit, collected.
    paints: [api.playIcon({}), api.playIcon({ outline: true }), api.stopIcon({})]
      .flatMap((s) => (s.match(/(?:fill|stroke)="[^"]*"/g) || [])),
  }));
} else if (mode === 'panel') {
  // The docked queue panel's two icon constants, evaluated out of the shipped
  // module. These are the two controls `Law 15` is about: they sit on one row.
  const src = read('queuePanel.js');
  const consts = slice(src, 'const ICON_PLAY =', 'const ICON_GRIP =', 'queuePanel icons');
  const out = new Function(`
    ${icons}
    ${consts}
    return { play: ICON_PLAY, stop: ICON_STOP };
  `)();
  console.log(JSON.stringify(out));
} else {
  console.error(`unknown mode: ${mode}`);
  process.exit(2);
}
