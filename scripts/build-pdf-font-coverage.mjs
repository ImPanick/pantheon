// SPDX-License-Identifier: AGPL-3.0-or-later
// `B1687`. Writes `static/js/pdfFontCoverage.js`: which characters each face
// below draws, read out of the vendored file by the vendored jsPDF.
//
// The fallback PDF (`_rasterisePdf` in `static/js/document.js`) fetches Inter
// only for a document that needs it, and has to decide that before the face is
// fetched (`_pdfFontsNeeded`). It decided by script and skipped every
// `\p{Extended_Pictographic}` character as an emoji no face draws — and Inter
// draws ™, ↔, ▶, ❤, ‼ and twenty more of them, so a Latin document's `Brand™`
// fetched nothing and lost the `™`. A list of code points kept by hand would
// be the next thing to go stale (`Law 7`); the font is the one source. So this
// asks the font the question the export asks once the face is loaded
// (`_pdfRegisterFonts`'s `draws`): jsPDF's `characterToGlyph` over the cmap
// jsPDF itself parses, for every code point jsPDF can write (one UTF-16 unit
// per glyph, so nothing past U+FFFF).
//
//     node scripts/build-pdf-font-coverage.mjs            # write the table
//     node scripts/build-pdf-font-coverage.mjs --check    # exit 1 if it is stale
//
// `--out <file>` reads or writes another path (the test's stale copy). Run it
// when a face below is bumped; the table records each face's sha256, so
// `tests/test_the_fallback_pdf_draws_the_symbols_inter_has_in_a_browser.py`
// fails until it is. Nothing at runtime runs this.
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const FONT_DIR = join(ROOT, 'static', 'lib', 'pdf-fonts');
const JSPDF = join(ROOT, 'static', 'lib', 'jspdf.umd.min.js');
const OUT = join(ROOT, 'static', 'js', 'pdfFontCoverage.js');

// The faces whose coverage is decided by the font. Inter's regular face: its
// bold has the same cmap and its italics lack only private-use code points
// (measured with this reader, 2026-10-29). The CJK face is not here — it draws
// 20,340 characters scattered through the ideographs, a table larger than the
// rest of the export, and is fetched by block (`_PDF_CJK`).
const FACES = ['Inter-Regular.ttf'];

function coverage(file) {
  const { jsPDF } = createRequire(import.meta.url)(JSPDF);
  const bytes = readFileSync(join(FONT_DIR, file));
  const pdf = new jsPDF();
  // The binary string `_pdfFontFile` hands jsPDF's virtual file system.
  pdf.addFileToVFS(file, bytes.toString('latin1'));
  pdf.addFont(file, 'coverage', 'normal');
  const cmap = pdf.getFont('coverage', 'normal').metadata;
  const ranges = [];
  for (let cp = 0; cp <= 0xffff; cp++) {
    if (cmap.characterToGlyph(cp) === 0) continue;
    const last = ranges[ranges.length - 1];
    if (last && last[1] === cp - 1) last[1] = cp;
    else ranges.push([cp, cp]);
  }
  return {
    sha256: createHash('sha256').update(bytes).digest('hex'),
    ranges: ranges.map(([a, b]) => (a === b ? a.toString(16) : `${a.toString(16)}-${b.toString(16)}`)),
  };
}

function render() {
  const lines = [
    '// SPDX-License-Identifier: AGPL-3.0-or-later',
    '// static/js/pdfFontCoverage.js',
    '//',
    '// `B1687`. Written by `node scripts/build-pdf-font-coverage.mjs`; not edited',
    '// by hand. The characters each face the fallback PDF embeds draws, read out',
    '// of the vendored file by the vendored jsPDF (`characterToGlyph` over the',
    '// cmap it parses, the question `document.js` asks once the face is loaded),',
    '// as hexadecimal code points and `first-last` ranges. `_pdfFontsNeeded`',
    '// reads it to decide, before anything is fetched, whether a document needs',
    '// the face at all.',
    '//',
  ];
  const body = [];
  for (const file of FACES) {
    const { sha256, ranges } = coverage(file);
    lines.push(`// ${file}: sha256 ${sha256}, ${ranges.length} ranges.`);
    const rows = [];
    for (let i = 0; i < ranges.length; i += 10) {
      rows.push('    ' + ranges.slice(i, i + 10).map((r) => JSON.stringify(r)).join(', '));
    }
    body.push(`  ${JSON.stringify(file)}: [\n${rows.join(',\n')}\n  ]`);
  }
  lines.push(`export const PDF_FONT_COVERAGE = {\n${body.join(',\n')}\n};`);
  return lines.join('\n') + '\n';
}

function main(argv) {
  const check = argv.includes('--check');
  const at = argv.indexOf('--out');
  const out = at >= 0 ? argv[at + 1] : OUT;
  const want = render();
  const name = relative(ROOT, out) || out;
  if (check) {
    let have = '';
    try { have = readFileSync(out, 'utf8'); } catch (_) { /* missing reads as stale */ }
    if (have === want) return 0;
    console.log(`${name} is not what ${FACES.join(', ')} draws now: `
      + 'run `node scripts/build-pdf-font-coverage.mjs` and commit what it writes.');
    return 1;
  }
  writeFileSync(out, want);
  console.log(`${name}: ${FACES.join(', ')}`);
  return 0;
}

process.exitCode = main(process.argv.slice(2));
