// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Runs the REAL `static/sw.js` install handler (`B57`), so the tests measure
// the shipped walk rather than a transcription of it. Reads one JSON command on
// stdin and writes one JSON result on stdout.
//
//   {"op":"install"}                     install against the real tree; the
//                                        result also reports what each cached
//                                        module imports and what each cached
//                                        document references, read back with
//                                        the worker's own `importsOf` and
//                                        `assetsOf`, plus the `cache` mode each
//                                        fetch asked for (`B85`)
//   {"op":"install","fail":[url,...]}    ... with those URLs answering 404
//   {"op":"walk","files":{url:src},"seeds":[url,...]}
//                                        drive the walk over a synthetic tree
//   {"op":"imports","url":...,"source":...}   call importsOf directly
//   {"op":"assets","url":...,"source":...}    call assetsOf directly (`B86`)
//
// A Response here refuses to be read twice, because `cache.put` consumes the
// body: a walk that stores before it clones would pass a forgiving stub and
// cache nothing in a browser.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const REPO = process.cwd();
const ORIGIN = 'http://localhost';

function readCommand() {
  return JSON.parse(fs.readFileSync(0, 'utf8') || '{}');
}

function diskBody(url) {
  const rel = url.split('?')[0].replace(/^\//, '');
  const full = path.join(REPO, rel === '' ? 'static/index.html' : rel);
  if (!full.startsWith(REPO) || !fs.existsSync(full) || !fs.statSync(full).isFile()) return null;
  return fs.readFileSync(full, 'utf8');
}

// A 404 still has a body — so a walk that stopped checking `res.ok` would cache
// the error page here, exactly as it would in a browser.
function makeResponse(body, ok = true) {
  return {
    ok,
    status: ok ? 200 : 404,
    _used: false,
    clone() {
      if (this._used) throw new TypeError('Response body is already used');
      return makeResponse(body, ok);
    },
    async text() {
      if (this._used) throw new TypeError('Response body is already used');
      this._used = true;
      return body;
    },
  };
}

function run(cmd) {
  const fail = new Set(cmd.fail || []);
  const files = cmd.files || null;
  const fetched = [];
  // `B85`. The install's REQUEST is half of what this row is about, so the stub
  // records the `cache` mode it was asked for. `undefined` is recorded as the
  // string '(none)' so "the option was dropped" and "the option says default"
  // stay distinguishable — they are different bugs with the same symptom.
  const modes = new Map();
  const stored = new Map();

  const cache = {
    async put(url, res) { stored.set(String(url), await res.text()); },
    async match(url) {
      const hit = stored.get(String(url));
      return hit === undefined ? undefined : makeResponse(hit);
    },
  };

  const context = {
    console,
    URL,
    setTimeout,
    caches: {
      async open() { return cache; },
      async keys() { return []; },
      async delete() { return true; },
      async match() { return undefined; },
    },
    async fetch(url, options) {
      const key = String(url);
      fetched.push(key);
      modes.set(key, (options && options.cache) || '(none)');
      if (fail.has(key)) return makeResponse('<!doctype html>not found', false);
      const body = files ? (key in files ? files[key] : null) : diskBody(key);
      return body === null
        ? makeResponse('<!doctype html>not found', false)
        : makeResponse(body);
    },
  };
  const listeners = {};
  context.self = context;
  context.globalThis = context;
  context.location = { origin: ORIGIN, href: `${ORIGIN}/static/sw.js` };
  context.addEventListener = (type, fn) => { (listeners[type] ||= []).push(fn); };
  context.skipWaiting = () => {};
  context.clients = { claim: async () => {} };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(REPO, 'static/sw.js'), 'utf8'), context);

  if (cmd.op === 'imports') {
    const importsOf = vm.runInContext('importsOf', context);
    return { imports: importsOf(cmd.source, cmd.url) };
  }

  if (cmd.op === 'assets') {
    const assetsOf = vm.runInContext('assetsOf', context);
    return { assets: assetsOf(cmd.source, cmd.url) };
  }

  // A synthetic tree drives the shipped walk directly, with seeds of the
  // test's choosing — the shipped lists stay as they are.
  if (cmd.op === 'walk') {
    const precacheShellGraph = vm.runInContext('precacheShellGraph', context);
    return Promise.resolve(precacheShellGraph(cache, cmd.seeds)).then(seen => ({
      cached: [...stored.keys()].sort(),
      fetched: fetched.slice().sort(),
      modes: Object.fromEntries(modes),
      seen: [...seen].sort(),
    }));
  }

  const install = (listeners.install || [])[0];
  if (!install) throw new Error('sw.js registered no install listener');
  let waited = null;
  install({ waitUntil(p) { waited = p; } });
  if (!waited) throw new Error('the install handler did not call waitUntil');
  // `imports` is read back with the worker's OWN `importsOf`, so the closure
  // assertion in the test has no second opinion about what a specifier is —
  // there is one walker and this is it. `assets` is the same arrangement for
  // the reference grammars `B86` added: `assetsOf` decides what a stylesheet,
  // a page or a manifest names, and the test asserts closure over that.
  const importsOf = vm.runInContext('importsOf', context);
  const assetsOf = vm.runInContext('assetsOf', context);
  const isWalkable = vm.runInContext('isWalkable', context);
  const docKind = vm.runInContext('docKind', context);
  return Promise.resolve(waited).then(() => {
    const imports = {};
    const assets = {};
    for (const [url, body] of stored) {
      if (isWalkable(url)) imports[url] = importsOf(body, url);
      const kind = docKind(url);
      if (kind && kind !== 'js') assets[url] = assetsOf(body, url);
    }
    return {
      cached: [...stored.keys()].sort(),
      fetched: fetched.slice().sort(),
      modes: Object.fromEntries(modes),
      cacheName: vm.runInContext('CACHE_NAME', context),
      imports,
      assets,
    };
  });
}

const cmd = readCommand();
Promise.resolve(run(cmd)).then((out) => {
  process.stdout.write(JSON.stringify(out));
}, (err) => {
  process.stderr.write(String(err && err.stack || err));
  process.exit(1);
});
