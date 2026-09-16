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
//   {"op":"navigate","urls":[url,...]}   install, then take the network away
//                                        and dispatch a real FetchEvent at
//                                        each URL through the shipped fetch
//                                        handler (`B120`). `mode` defaults to
//                                        'navigate'; the result says, per URL,
//                                        whether the handler answered at all
//                                        and the sha256 of what it answered
//                                        with, against `hashes` — the sha256
//                                        of every entry install stored.
//
// A Response here refuses to be read twice, because `cache.put` consumes the
// body: a walk that stores before it clones would pass a forgiving stub and
// cache nothing in a browser.
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const REPO = process.cwd();
const ORIGIN = 'http://localhost';

function readCommand() {
  return JSON.parse(fs.readFileSync(0, 'utf8') || '{}');
}

// Bodies here are up to 283 KB and there are 214 of them; the tests only ever
// ask "is this the same document", so they compare digests.
function sha(body) {
  return crypto.createHash('sha256').update(String(body)).digest('hex').slice(0, 16);
}

// `B122`. A URL with no file extension is a ROUTE, and this app has two that
// serve a document: `/` reads `static/index.html` and `/login` reads
// `static/login.html` (`app.py:916`, `app.py:969`). The rule here is the shape
// of that — `/<name>` is `static/<name>.html` — rather than a table of routes,
// which would be a copy of `app.py` living in a harness. A route with no file
// behind it answers 404, exactly as a missing module does.
function diskBody(url) {
  let rel = url.split('?')[0].replace(/^\//, '');
  if (rel === '') rel = 'static/index.html';
  else if (!/\.[A-Za-z0-9]+$/.test(rel)) rel = `static/${rel}.html`;
  const full = path.join(REPO, rel);
  if (!full.startsWith(REPO) || !fs.existsSync(full) || !fs.statSync(full).isFile()) return null;
  return fs.readFileSync(full, 'utf8');
}

// A 404 still has a body — so a walk that stopped checking `res.ok` would cache
// the error page here, exactly as it would in a browser.
function makeResponse(body, ok = true, redirected = false) {
  return {
    ok,
    status: ok ? 200 : 404,
    // `B122`. `fetch` follows redirects by default and reports the hop here.
    // A worker that stores such a response under the URL it asked for caches
    // somebody else's document under this key, so the flag has to exist on
    // the stub or the guard cannot be tested.
    redirected,
    _used: false,
    clone() {
      if (this._used) throw new TypeError('Response body is already used');
      return makeResponse(body, ok, redirected);
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
  // URLs whose response reports that it came from somewhere else (`B122`).
  const redirects = new Set(cmd.redirects || []);
  const files = cmd.files || null;
  const fetched = [];
  // `B85`. The install's REQUEST is half of what this row is about, so the stub
  // records the `cache` mode it was asked for. `undefined` is recorded as the
  // string '(none)' so "the option was dropped" and "the option says default"
  // stay distinguishable — they are different bugs with the same symptom.
  const modes = new Map();
  const stored = new Map();
  // Offline is a property of this context, not of a call: the `navigate` op
  // takes the network away after install and leaves it away.
  let offline = false;

  // `B120`. A real Cache is keyed on the resolved URL, so `cache.put('/')` and
  // `cache.match(request)` for `http://localhost/` are the same entry. The
  // install path only ever passes path strings, so this changed nothing there
  // — it is what lets a FetchEvent, which carries an absolute URL, find what
  // install stored.
  const keyOf = (u) => String((u && u.url) || u).replace(`${ORIGIN}`, '') || '/';
  const cache = {
    async put(url, res) { stored.set(keyOf(url), await res.text()); },
    async match(url) {
      const hit = stored.get(keyOf(url));
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
      // Delegates rather than answering `undefined`, because the JS/CSS branch
      // of the fetch handler falls back through `caches.match(e.request)` and
      // a stub that always missed would make an offline module look uncached.
      async match(url) { return cache.match(url); },
    },
    async fetch(url, options) {
      const key = keyOf(url);
      fetched.push(key);
      modes.set(key, (options && options.cache) || '(none)');
      // What a browser does with no network: the promise rejects. It does not
      // resolve with a 404, and a handler that only checked `res.ok` would
      // pass a stub that faked one.
      if (offline) throw new TypeError('Failed to fetch');
      if (fail.has(key)) return makeResponse('<!doctype html>not found', false);
      const body = files ? (key in files ? files[key] : null) : diskBody(key);
      if (body === null) return makeResponse('<!doctype html>not found', false);
      return makeResponse(body, true, redirects.has(key));
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

  // `B120`. Install for real, then take the network away and put a real
  // FetchEvent through the shipped handler — the only way to find out what a
  // navigation is answered with is to ask the handler, and the defect this op
  // exists for is a navigation the handler never claims at all.
  if (cmd.op === 'navigate') {
    const installer = (listeners.install || [])[0];
    if (!installer) throw new Error('sw.js registered no install listener');
    let installed = null;
    installer({ waitUntil(p) { installed = p; } });
    return Promise.resolve(installed).then(async () => {
      const hashes = {};
      for (const [url, body] of stored) hashes[url] = sha(body);
      offline = true;
      const onFetch = (listeners.fetch || [])[0];
      if (!onFetch) throw new Error('sw.js registered no fetch listener');
      const answered = {};
      for (const url of cmd.urls || []) {
        const request = {
          url: ORIGIN + url,
          method: cmd.method || 'GET',
          mode: cmd.mode || 'navigate',
        };
        let promised;
        onFetch({ request, respondWith(p) { promised = p; } });
        if (promised === undefined) { answered[url] = { handled: false }; continue; }
        let res;
        try {
          res = await promised;
        } catch (err) {
          answered[url] = { handled: true, threw: String(err && err.message || err) };
          continue;
        }
        if (!res) { answered[url] = { handled: true, empty: true }; continue; }
        answered[url] = { handled: true, status: res.status, sha: sha(await res.text()) };
      }
      return { answered, hashes, cached: [...stored.keys()].sort() };
    });
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
