// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `B2215`. Runs the REAL vendored Pyodide (`static/lib/pyodide/`) the way
// `static/js/pythonSandbox.js` runs a person's block: the same options to
// `loadPyodide`, the same Python wrapper, both lifted out of that file rather
// than copied (`Law 13`), and reports what each block printed.
//
// Node, not a browser: `pyodide.js` is the page's own file, but under Node it
// takes Node's branch to load `pyodide.asm.mjs` and the wasm, and Node 22 has no JS Promise
// Integration unless asked, which is the "stack switching off" case
// `enableRunUntilComplete` is about. The browser's own loading path (a classic
// Worker importing `pyodide.asm.mjs` from an opaque-origin frame) is not
// reachable from here.
//
//     node tests/harness/python_sandbox_pyodide.mjs
//
// Prints one line of JSON.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const LIB = path.join(ROOT, 'static', 'lib', 'pyodide');
const SANDBOX = fs.readFileSync(path.join(ROOT, 'static', 'js', 'pythonSandbox.js'), 'utf8');

function bail(why) {
  console.log(JSON.stringify({ ok: false, error: 'ANCHOR-MISSING: ' + why }));
  process.exit(2);
}

// The wrapper: the array of Python lines `.join('\n')`-ed in the sandbox.
const wrapperSrc = SANDBOX.match(/var WRAPPER = (\[[\s\S]*?\])\.join\('\\n'\);/);
if (!wrapperSrc) bail('var WRAPPER = [...].join(\'\\n\') in pythonSandbox.js');
const WRAPPER = Function('"use strict"; return ' + wrapperSrc[1])().join('\n');

// The options object handed to `loadPyodide`, with `INDEX` bound to the
// vendored directory instead of the page's URL.
const optsSrc = SANDBOX.match(/loadPyodide\((\{[^}]*\})\)/);
if (!optsSrc) bail('loadPyodide({ ... }) in pythonSandbox.js');
const INDEX = LIB + path.sep;
const options = Function('INDEX', '"use strict"; return (' + optsSrc[1] + ');')(INDEX);
const requested = { ...options, indexURL: undefined };  // loadPyodide adds to it

// The page's own file, `pyodide.js`, evaluated as a classic script so its
// top-level `var loadPyodide` lands on the global object as it does there.
vm.runInThisContext(fs.readFileSync(path.join(LIB, 'pyodide.js'), 'utf8'),
  { filename: path.join(LIB, 'pyodide.js'),
    importModuleDynamically: vm.constants.USE_MAIN_CONTEXT_DEFAULT_LOADER });
if (typeof globalThis.loadPyodide !== 'function') bail('pyodide.js publishes no loadPyodide');
const py = await globalThis.loadPyodide(options);

const CASES = {
  hello: 'print("hi", 1 + 1)',
  version: 'import sys; print(sys.version.split()[0])',
  error: 'raise ValueError("boom")',
  runUntilComplete: [
    'import asyncio',
    'async def f():',
    '    return 8',
    'print(asyncio.get_event_loop().run_until_complete(f()))',
  ].join('\n'),
};

const runs = {};
for (const [name, code] of Object.entries(CASES)) {
  try {
    py.globals.set('_pantheon_code', code);
    const out = await py.runPythonAsync(WRAPPER);
    const pair = out.toJs();
    if (out.destroy) out.destroy();
    runs[name] = { stdout: String(pair[0] || ''), stderr: String(pair[1] || '') };
  } catch (err) {
    runs[name] = { threw: String((err && err.message) || err) };
  }
}
console.log(JSON.stringify({ ok: true, options: requested, runs }));
