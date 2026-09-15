// SPDX-License-Identifier: AGPL-3.0-or-later
// static/sw.js — Pantheon PWA Service Worker
// Strategy:
//   - HTML (navigation): stale-while-revalidate. Instant open from cache,
//     background refresh so the next open has latest HTML.
//   - JS/CSS (/static/*.js|.css): network-first, cache fallback for offline.
//     (So code/style edits show up on a normal reload, no manual cache clear.)
//   - Other static assets (images/fonts/libs): cache-first with bg refresh.
//   - API / non-GET: never cached.
// Bump CACHE_NAME whenever the precache list or SW logic changes.
const CACHE_NAME = 'pantheon-v416-b57-shell-closure';

// KaTeX resolves these from its own stylesheet, so caching the CSS without them
// gives offline math fallback glyphs instead of proper typesetting.
const KATEX_FONTS = [
  'AMS-Regular', 'Caligraphic-Bold', 'Caligraphic-Regular',
  'Fraktur-Bold', 'Fraktur-Regular',
  'Main-Bold', 'Main-BoldItalic', 'Main-Italic', 'Main-Regular',
  'Math-BoldItalic', 'Math-Italic',
  'SansSerif-Bold', 'SansSerif-Italic', 'SansSerif-Regular',
  'Script-Regular',
  'Size1-Regular', 'Size2-Regular', 'Size3-Regular', 'Size4-Regular',
  'Typewriter-Regular',
].map(name => `/static/lib/katex/fonts/KaTeX_${name}.woff2`);


// Two lists, two jobs — they are no longer the same set and must not be
// "resynced" back into one:
//
//   PRECACHE       = the app shell. Mirrors the <script type="module"> tags
//                    and <link rel="stylesheet"> in index.html — i.e. what
//                    loads before first paint.
//   PANEL_PRECACHE = modules that index.html deliberately does NOT load,
//                    because js/panels.js imports them on first use. They are
//                    off the critical path, not out of the offline manifest:
//                    without them here, a panel the user never opened while
//                    online could not open offline at all.
//
// `B57`: both are ENTRY POINTS, not the shell. Install walks the imports out of
// them (see `precacheShellGraph`), so a module reached only through another
// module does not need to appear here — and must not be added here, because the
// walk already has it and a second copy is a second thing to keep in step.
//
// Both are fetched at install time, in the background. Entries must match the
// exact URL the browser requests, query string included.
const PRECACHE = [
  '/',
  '/static/style.css?v=20260808startupshell1',
  '/static/app.js?v=20260815toolapproval4',
  '/static/js/storage.js',
  '/static/js/appConfig.js',
  '/static/js/ui.js',
  '/static/js/markdown.js',
  '/static/js/dragSort.js',
  '/static/js/sessions.js',
  '/static/js/memory.js?v=20260722memoryloading1',
  '/static/js/skills.js',
  '/static/js/tourHints.js',
  '/static/js/fileHandler.js',
  '/static/js/voiceRecorder.js',
  '/static/js/models.js?v=20260715startupcalm2',
  '/static/js/rag.js',
  '/static/js/presets.js',
  '/static/js/search.js',
  '/static/js/spinner.js',
  '/static/js/tts-ai.js',
  '/static/js/document.js?v=20260815approvalsave1',
  '/static/js/gallery.js?v=20260708match1',
  '/static/js/chatRenderer.js?v=20260829trustladder1',
  // `P4-01`: the one builder for a tool card in the agent thread. On the
  // critical path via chat.js and chatRenderer.js.
  '/static/js/agentThread.js',
  '/static/js/trustLadder.js',
  '/static/js/codeRunner.js',
  '/static/js/chatStream.js?v=20260829trustladder1',
  '/static/js/chat.js?v=20260829trustladder1',
  '/static/js/planWindow.js',
  // `B11`/`B13`. Two leaf tables on the critical path: what the plan window and
  // the todo card call themselves, and the word the six run statuses are shown
  // as. Imported by chat.js, chatRenderer.js, planWindow.js and tasks.js — so
  // they load before first paint and belong in the shell list, not behind the
  // network-first fallback that happens to cache them on a first online visit.
  '/static/js/checklist.js',
  '/static/js/runStatus.js',
  '/static/js/cookbook.js',
  '/static/js/search-chat.js',
  '/static/js/compare/index.js?v=20260829trustladder1',
  '/static/js/theme.js',
  '/static/js/censor.js',
  // `B58`. The three entries below carried no query while every importer used
  // one. `caches.match(e.request)` has no `ignoreSearch`, so a bare entry can
  // never answer a versioned request: they were fetched at install and served
  // to nothing. Third recurrence of what `P3-11` and `B54` each fixed, and the
  // first one a checker can see.
  '/static/js/settings.js?v=20260815approvalsave1',
  '/static/js/admin.js?v=20260716openrouter3',
  '/static/js/init.js?v=20260715freshroot3',
  '/static/js/slashCommands.js?v=20260815approvalsave1',
  '/static/js/emailInbox.js?v=20260815approvalsave1',
  '/static/js/emailLibrary/utils.js',
  '/static/js/emailLibrary/signatureFold.js',
  '/static/js/emailLibrary/state.js',
  '/static/js/notes.js',
  '/static/js/tasks.js?v=20260723tasksbulkfeedback1',
  '/static/js/calendar.js',
  '/static/js/calendar/utils.js',
  '/static/js/group.js',
  '/static/js/keyboard-shortcuts.js',
  '/static/js/sidebar-layout.js?v=20260715startupclean',
  // `B54`. These three load from a <script type="module"> tag in index.html and
  // were never in this list, so offline they 404 and the boot graph stops.
  '/static/js/a11y.js',
  '/static/js/assistant.js',
  '/static/js/tourAutoplay.js',
  '/static/js/section-management.js',
  // `B57`. index.html:3263 loads this one as a CLASSIC script — no
  // `type="module"` — so nothing imports it and the walk below cannot reach
  // it. It was in no list either, and the manifest test could not see it:
  // that test read `<script type="module">` only, and the type attribute
  // decides how a script is evaluated, not whether it is requested.
  '/static/js/cookbookSchedule.js',
  '/static/lib/highlight.min.js',
  // Math turns up in ordinary answers and KaTeX is small, so precaching it and
  // its fonts keeps formulas typeset offline. Mermaid is deliberately NOT
  // precached: at 3.5 MB it would re-download on every CACHE_NAME bump, a poor
  // trade for a library most sessions never touch. The cache-first rule below
  // picks it up the first time a diagram renders, which is also when it starts
  // mattering offline.
  '/static/lib/katex/katex.min.js',
  '/static/lib/katex/katex.min.css',
  ...KATEX_FONTS,
];

// Lazily-imported panel modules (js/panels.js). Not in index.html by design;
// precached so the panel still opens with no network.
const PANEL_PRECACHE = [
  // Image editor — galleryEditor.js and its js/editor/ graph.
  '/static/js/galleryEditor.js',
  '/static/js/editor/ai-inpaint.js?v=20260708match1',
  '/static/js/editor/ai-models.js',
  '/static/js/editor/ai-rembg.js',
  '/static/js/editor/ai-tool-runner.js',
  '/static/js/editor/ai-tools-misc.js',
  '/static/js/editor/build/controls.js?v=20260708match1',
  '/static/js/editor/build/popups.js',
  '/static/js/editor/build/right-panel.js',
  '/static/js/editor/build/toolbar.js?v=20260708sam3',
  '/static/js/editor/build/topbar.js',
  '/static/js/editor/build/transform-popup.js',
  '/static/js/editor/canvas-coords.js',
  '/static/js/editor/canvas-events.js',
  '/static/js/editor/canvas-transforms.js',
  '/static/js/editor/checkerboard.js',
  '/static/js/editor/clipboard-and-drop.js',
  '/static/js/editor/composite-helpers.js',
  '/static/js/editor/filters/blur.js',
  '/static/js/editor/filters/edge-feather.js',
  '/static/js/editor/fx/adj-popup.js',
  '/static/js/editor/fx/filter-string.js',
  '/static/js/editor/fx/histogram.js',
  '/static/js/editor/fx/pixel-pass.js',
  '/static/js/editor/harmonize-masks.js',
  '/static/js/editor/history-panel.js',
  '/static/js/editor/keyboard-shortcuts.js',
  '/static/js/editor/layer-helpers.js',
  '/static/js/editor/layer-panel.js',
  '/static/js/editor/mask-utils.js',
  '/static/js/editor/shortcuts-popover.js',
  '/static/js/editor/slider-ux.js',
  '/static/js/editor/snap.js',
  '/static/js/editor/state.js',
  '/static/js/editor/stroke-pipeline.js',
  '/static/js/editor/stroke-tool-sliders.js',
  '/static/js/editor/tools/clone.js',
  '/static/js/editor/tools/crop.js',
  '/static/js/editor/tools/flood-fill.js',
  '/static/js/editor/tools/lasso-mask.js',
  '/static/js/editor/tools/lasso.js',
  '/static/js/editor/tools/move.js',
  '/static/js/editor/tools/stroke.js',
  '/static/js/editor/tools/transform-drag.js',
  '/static/js/editor/tools/transform-handles.js',
  '/static/js/editor/tools/transform-session.js',
  '/static/js/editor/tools/wand.js',
  '/static/js/editor/wire-import.js',
  '/static/js/editor/wire-inpaint-controls.js?v=20260708match1',
  '/static/js/editor/wire-merge-buttons.js',
  '/static/js/editor/wire-selection-controls.js',
  '/static/js/editor/wire-topbar-menus.js',
  '/static/js/editor/wire-topbar-overflow.js',
  '/static/js/editor/wire-topbar.js',
];

// `B57`. The two lists name entry points. They are not the shell, and the
// difference is the whole of this row: an ES module graph loads whole or not at
// all, so a root whose imports are absent from the cache does not partially
// work — it does not run.
//
// Measured on this tree the day this landed: the 32 <script type="module"> tags
// in index.html reach 172 modules, and the two lists together named 105 of
// them. The 67 named by no entry under any URL included toolWindowZOrder.js
// (27 importers), escMenuStack.js (18), windowDrag.js (12) and modalManager.js
// (11) — which put 21 of the 32 roots, app.js and chat.js among them, out of
// reach of the cache. Offline from a fresh install the shell painted and
// nothing ran.
//
// Nothing noticed because the fetch handler below caches every OK JS response,
// so any online visit fills the graph in. **That is a freshness path, not a
// completeness path**, and two ordinary events empty it back to this list:
//
//   * `activate` deletes every cache but the current one, so a CACHE_NAME bump
//     discards everything the fetch handler wrote. There have been 415 of them,
//     13 in the week this was found.
//   * a first visit registers this worker from the bottom of index.html, after
//     the page has already fetched its module graph uncontrolled — none of it
//     passes through the fetch handler, so a cold install caches the list and
//     nothing else.
//
// So the closure is DERIVED here rather than written down (`Law 13`): install
// reads each module it fetches and follows its import specifiers. Adding an
// import is all it takes to have the target precached — there is no list to
// update, and no build step in this repo to update it from.
//
// The seeds stay hand-written because they are exactly what a walk cannot
// derive: the HTML shell, the stylesheet, and the fonts and libs nothing
// imports — plus any module reached through a computed specifier, of which
// login.html's `import(f('/static/js/theme.js'))` is the one in this tree.
const MODULE_SPECIFIER =
  /(?:^|[^\w.])(?:import\s*\(?\s*|from\s+)['"]([^'"]+\.js(?:\?[^'"]*)?)['"]/g;

// What the walk will read and follow. `/static/lib/` is deliberately outside
// it: mermaid is 3.5 MB and is deliberately not precached (see above), and
// following imports into the vendored libs would drag it in by the back door.
function isWalkable(url) {
  return url.startsWith('/static/')
    && !url.startsWith('/static/lib/')
    && /\.js(\?|$)/.test(url);
}

// Cache identity is the resolved URL, query included — the defect `P3-11`,
// `B54` and `B58` each found a fresh batch of. `new URL(spec, base)` resolves
// to exactly what the browser will request: the specifier's own query, never
// the importer's.
function importsOf(source, url) {
  const base = new URL(url, self.location.origin);
  const found = [];
  // `matchAll` scans against its own copy of the regex, so the shared
  // module-scope `lastIndex` never leaks from one module's scan into the next —
  // a hazard `exec` in a loop carries and that no test can see, because a scan
  // that runs to its end resets it anyway.
  for (const m of source.matchAll(MODULE_SPECIFIER)) {
    let resolved;
    try {
      resolved = new URL(m[1], base);
    } catch (err) {
      continue;
    }
    if (resolved.origin !== base.origin) continue;
    const request = resolved.pathname + resolved.search;
    if (isWalkable(request)) found.push(request);
  }
  return found;
}

// Fetch one URL, store it, and report what it imports. addAll is atomic — if
// any item fails, none are cached — so this puts one at a time and swallows its
// own failures: a single 404 must not block the whole install, and must not
// stop the walk reaching the rest of the graph either.
async function precacheOne(cache, url) {
  let res;
  try {
    res = await fetch(url, { cache: 'reload' });
  } catch (err) {
    return [];
  }
  if (!res || !res.ok) return [];
  // Read the copy, store the original: cache.put consumes the body.
  let source = '';
  if (isWalkable(url)) {
    try {
      source = await res.clone().text();
    } catch (err) {
      source = '';
    }
  }
  try {
    await cache.put(url, res);
  } catch (err) {
    /* storage quota, or a response that cannot be stored — the walk carries on */
  }
  return source ? importsOf(source, url) : [];
}

// Breadth-first from the seeds. `seen` is what makes this terminate: the graph
// has cycles and the set is the entire argument. The round ceiling is a guard
// against a pathological tree, not the termination proof — this tree settles in
// three rounds.
async function precacheShellGraph(cache, seeds) {
  const seen = new Set(seeds);
  let frontier = [...seen];
  for (let round = 0; round < 32 && frontier.length; round += 1) {
    const discovered = await Promise.all(frontier.map(url => precacheOne(cache, url)));
    frontier = [];
    for (const list of discovered) {
      for (const url of list) {
        if (seen.has(url)) continue;
        seen.add(url);
        frontier.push(url);
      }
    }
  }
  return seen;
}

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(cache =>
      precacheShellGraph(cache, [...PRECACHE, ...PANEL_PRECACHE])
    )
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // Never touch API calls or non-GET.
  if (url.pathname.startsWith('/api/') || e.request.method !== 'GET') return;

  // HTML navigation: stale-while-revalidate the app shell — but ONLY for the
  // SPA root. Other navigations (e.g. a deep-linked /static/*.html page) must
  // go to the network/static handlers below; otherwise every navigation was
  // served the app index, replacing the page the user actually asked for.
  if (e.request.mode === 'navigate' && url.pathname === '/') {
    e.respondWith(
      caches.open(CACHE_NAME).then(async cache => {
        const cached = await cache.match('/');
        const network = fetch(e.request).then(res => {
          if (res && res.ok) cache.put('/', res.clone());
          return res;
        }).catch(() => cached);
        return cached || network;
      })
    );
    return;
  }

  // JS/CSS: network-first — always try the network so code/style edits show up
  // on a normal reload; fall back to cache only when offline.
  if (url.pathname.startsWith('/static/') && /\.(js|css)(\?|$)/.test(url.pathname + url.search)) {
    e.respondWith(
      fetch(e.request).then(res => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(e.request, copy));
        }
        return res;
      }).catch(() => caches.match(e.request))
    );
    return;
  }

  // Other static assets (images, fonts, libs): cache-first with background refresh.
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(
      caches.open(CACHE_NAME).then(async cache => {
        const cached = await cache.match(e.request);
        const fetching = fetch(e.request).then(res => {
          if (res && res.ok) cache.put(e.request, res.clone());
          return res;
        }).catch(() => cached);
        return cached || fetching;
      })
    );
    return;
  }
});
