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
const CACHE_NAME = 'pantheon-v429-tidy-preview';

// KaTeX resolves these from its own stylesheet, so caching the CSS without them
// gives offline math fallback glyphs instead of proper typesetting.
//
// `B86`: this list is now DERIVED — the walk reads katex.min.css and follows
// its `url()`s, which produces exactly these 20 and nothing else. It stays for
// the reason `PANEL_PRECACHE` stays: it is the sentence explaining why a
// library's fonts belong in an offline manifest, and it is the floor if the
// stylesheet ever stops naming them. It is also the check on the new walk —
// reproducing a 20-entry hand-list that has been right for 416 cache
// generations is how the `url()` derivation was shown to work.
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
// `B86`: the same is now true of anything a document REFERENCES rather than
// imports — a font in a stylesheet, a PWA manifest or an icon on a <link>, an
// icon named by the manifest. Those are derived too (see `assetsOf`) and must
// not be listed here either.
//
// Both are fetched at install time, in the background. Entries must match the
// exact URL the browser requests, query string included.
const PRECACHE = [
  '/',
  // `B122`. The second document this app serves, and the only other one that
  // exists: `app.py:973` reads `static/login.html` through the same nonce
  // helper `/` goes through. It was in neither list while `theme.js` was a
  // seed *because* this page imports it, so the page's dependency was
  // guaranteed offline and the page was not.
  //
  // The call this row asks for is made, and it is made on a path that needs no
  // server at all: the Log out button in settings does
  // `await fetch('/api/auth/logout')` inside a `try {} catch (_) {}`, wipes
  // localStorage and sessionStorage, and then sets `location.href = '/login'`
  // unconditionally. Offline the fetch rejects, the catch swallows it, the
  // wipe still happens and the navigation still happens — so an offline user
  // who logs out lands on a page that does not exist for them, having just
  // lost their local state. That is reachable with the network down; the
  // server-issued 302 the row imagined is not, because a server that can
  // redirect can also serve the page.
  //
  // An offline login still cannot check a credential, and that is not what
  // this buys. The submit handler catches the rejection and shows it in the
  // error line, so the page degrades to a visible message instead of a
  // browser error page with no way back, and the same form works the moment
  // the network returns.
  '/login',
  '/static/style.css?v=20260919tidypreview1',
  '/static/app.js?v=20260919tidypreview1',
  '/static/js/storage.js',
  '/static/js/appConfig.js',
  '/static/js/ui.js',
  '/static/js/markdown.js',
  // `P5-06`: the code block's language glyph. `markdown.js` imports it now, so
  // the offline shell cannot render a fenced block without it. It reached the
  // tree with `document.js` and was never precached, which was invisible while
  // only the document surfaces used it.
  '/static/js/langIcons.js',
  '/static/js/dragSort.js',
  '/static/js/sessions.js',
  '/static/js/memory.js?v=20260919tidypreview1',
  '/static/js/skills.js',
  '/static/js/tourHints.js',
  '/static/js/fileHandler.js?v=20260919chipramp1',
  '/static/js/voiceRecorder.js',
  '/static/js/models.js?v=20260715startupcalm2',
  '/static/js/rag.js',
  '/static/js/presets.js',
  '/static/js/search.js',
  '/static/js/spinner.js',
  '/static/js/tts-ai.js',
  '/static/js/document.js?v=20260815approvalsave1',
  '/static/js/gallery.js?v=20260708match1',
  '/static/js/chatRenderer.js?v=20260919chipramp1',
  // `P4-01`: the one builder for a tool card in the agent thread. On the
  // critical path via chat.js and chatRenderer.js.
  '/static/js/agentThread.js',
  '/static/js/trustLadder.js',
  '/static/js/codeRunner.js',
  '/static/js/chatStream.js?v=20260919chipramp1',
  '/static/js/chat.js?v=20260919chipramp1',
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
  '/static/js/compare/index.js?v=20260919chipramp1',
  '/static/js/theme.js',
  '/static/js/censor.js',
  // `B58`. The three entries below carried no query while every importer used
  // one. `caches.match(e.request)` has no `ignoreSearch`, so a bare entry can
  // never answer a versioned request: they were fetched at install and served
  // to nothing. Third recurrence of what `P3-11` and `B54` each fixed, and the
  // first one a checker can see.
  '/static/js/settings.js?v=20260918emptystates1',
  '/static/js/admin.js?v=20260918p2admin1',
  '/static/js/init.js?v=20260918a11yfocus1',
  '/static/js/slashCommands.js?v=20260815approvalsave1',
  '/static/js/emailInbox.js?v=20260815approvalsave1',
  '/static/js/emailLibrary/utils.js',
  '/static/js/emailLibrary/signatureFold.js',
  '/static/js/emailLibrary/state.js',
  '/static/js/notes.js',
  '/static/js/tasks.js?v=20260919workflowdiagram1',
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
// derive: the HTML shell, and the libs nothing imports — plus any module
// reached through a computed specifier, of which login.html's
// `import(f('/static/js/theme.js'))` is the one in this tree. `B122` added the
// second document for the same reason: nothing on the shell links the login
// page, so no walk from `/` can reach it.
//
// `B86` shrank that list of exceptions. "The stylesheet and the fonts nothing
// imports" used to be in it; the stylesheet is on a `<link>` in the shell and
// the fonts are in `url()`s inside it, so both are derivable and now are.
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
//
// One resolver for every reference grammar (`B86` added two more), so the
// origin check exists once. Dropping it would turn a reference that merely
// LOOKS local — `https://cdn.example/static/js/x.js` — into a request to our
// own /static/ for a file that lives on somebody else's host. Returns '' for
// anything unresolvable or off-origin; each caller adds its own predicate.
function resolveRef(spec, base) {
  let resolved;
  try {
    resolved = new URL(spec, base);
  } catch (err) {
    return '';
  }
  if (resolved.origin !== base.origin) return '';
  return resolved.pathname + resolved.search;
}

// `B231`. A *sentence about* a reference is not a reference, and this walk read
// raw source until it was measured. `static/js/runStatus.js:33` is a JSDoc line
// explaining why the Tasks view is reached as `import('./tasks.js?v=…')`, with a
// literal ellipsis — and install fetched `/static/js/tasks.js?v=%E2%80%A6`, got
// a 200 (the static handler ignores the query), and stored a second 178 KB copy
// of `tasks.js` under a URL no importer spells and `caches.match` can never
// serve. Paid on every cold install and every `CACHE_NAME` bump; there have
// been 418 of those.
//
// This is `B87` one layer down: `.pantheon/check-specifiers.py` was taught to
// blank comments for **that same docstring** and `sw.js` never was, which is
// `Law 20` in the worker — reading the file instead of the code. The walk is the
// place to fix it (`Law 13`): deleting the sentence would fix this module and
// leave the next comment that mentions an import to be found by hand.
//
// Characters become spaces rather than vanishing, so nothing downstream shifts.
// Three grammars, because they disagree about what a comment is and getting that
// wrong is worse than not stripping at all:
//
//   js    `//` to end of line and `/* … */`, tracking string and template
//         literals — `'https://x'` contains `//`, and blanking from there would
//         silently swallow the rest of the line.
//   css   `/* … */` ONLY. `//` is not a CSS comment, and these stylesheets are
//         minified onto one line: treating one as a comment would blank the
//         whole file and take all 20 KaTeX fonts out of the install with it.
//   html  `<!-- … -->` only.
//
// A manifest is JSON, which has no comments, and is returned untouched.
function withoutComments(source, kind) {
  if (kind !== 'js' && kind !== 'css' && kind !== 'html') return source;
  const out = source.split('');
  const n = source.length;
  const blank = (from, to) => {
    for (let k = from; k < to; k += 1) if (out[k] !== '\n') out[k] = ' ';
  };
  let i = 0;
  let quote = '';
  while (i < n) {
    const ch = source[i];
    if (quote) {
      if (ch === '\\' && quote !== '`') { i += 2; continue; }
      if (ch === quote) quote = '';
      i += 1;
      continue;
    }
    if (kind === 'js' && (ch === '"' || ch === "'" || ch === '`')) {
      quote = ch;
      i += 1;
      continue;
    }
    if (kind === 'js' && source.startsWith('//', i)) {
      const end = source.indexOf('\n', i);
      blank(i, end < 0 ? n : end);
      i = end < 0 ? n : end;
      continue;
    }
    if ((kind === 'js' || kind === 'css') && source.startsWith('/*', i)) {
      const end = source.indexOf('*/', i + 2);
      const stop = end < 0 ? n : end + 2;
      blank(i, stop);
      i = stop;
      continue;
    }
    if (kind === 'html' && source.startsWith('<!--', i)) {
      const end = source.indexOf('-->', i + 4);
      const stop = end < 0 ? n : end + 3;
      blank(i, stop);
      i = stop;
      continue;
    }
    i += 1;
  }
  return out.join('');
}

function importsOf(source, url) {
  const base = new URL(url, self.location.origin);
  const found = [];
  // `matchAll` scans against its own copy of the regex, so the shared
  // module-scope `lastIndex` never leaks from one module's scan into the next —
  // a hazard `exec` in a loop carries and that no test can see, because a scan
  // that runs to its end resets it anyway.
  for (const m of withoutComments(source, 'js').matchAll(MODULE_SPECIFIER)) {
    const request = resolveRef(m[1], base);
    if (request && isWalkable(request)) found.push(request);
  }
  return found;
}


// `B86`. The walk above follows `import` out of the JS it fetches. The shell
// has a second reference grammar that nothing followed, and the gap had the
// same shape: five `@font-face` woff2 in style.css and three more in
// index.html's inline <style> — 978 KB, the app font, the code font and the
// accessibility font — were in no list, while KaTeX's 20 were, on the argument
// the KATEX_FONTS comment makes. Nothing could catch it either:
// `test_offline_shell_manifest.py` compares `<script src>` and
// `<link rel=stylesheet>` against the lists, and a font named INSIDE a
// stylesheet is neither.
//
// Listing them is the half that rots, and this tree shows why by how much. The
// hand-list the row asked for was seven URLs. The derivation finds twelve: the
// three Inter faces are declared in an inline <style> block, which is not a
// stylesheet the page links, and icons/icon-512.png and
// icons/icon-maskable-512.png are named only by manifest.json, which nothing
// but the manifest reads. Five of twelve missed by the list that was supposed
// to fix the problem (`Law 13`).
//
// So references are derived from the documents install already has in hand:
//
//   *.css          `url()` targets
//   / and *.html   <link> hrefs, plus the same `url()` scan — an inline
//                  <style> block carries the identical grammar, and that is
//                  what reaches the three Inter faces
//   *.json         a PWA manifest's icons[].src, resolved against the manifest
//
// Only the format a browser will actually request is followed. `@font-face`
// takes the first `format()` the browser supports and every browser with a
// service worker supports woff2, so the legacy entries are never fetched:
// katex.min.css names 60 url()s — 20 woff2 and 40 .woff/.ttf this repo did not
// even vendor. Following all of them would be 40 requests per install that
// 404, and a closure no test could assert. Following woff2 reproduces
// KATEX_FONTS exactly.
const CSS_URL = /url\(\s*(['"]?)([^'")]+)\1\s*\)/g;
const LINK_TAG = /<link\b[^>]*>/gi;

// The <link> rels that name something the shell needs offline. This list
// decides WHICH references are followed, and nothing more: it is not what
// keeps the module graph out. A <link> names a script through `modulepreload`
// or `preload as=script`, and both are stopped by `isNotAScript` below —
// adding `modulepreload` here is a mutation that changes no output, which is
// how this comment came to say so instead of implying a guard that is not
// here.
const ASSET_RELS = new Set(['stylesheet', 'manifest', 'icon', 'apple-touch-icon', 'preload']);

// What a `url()` may pull in — fonts and images, the things a stylesheet
// actually fetches.
const STYLE_ASSET = /\.(?:woff2|png|svg|webp|gif|jpe?g|ico)(?:\?|$)/i;

// The one thing this walk must never reach is a script. `/static/lib/` holds
// mermaid's 3.5 MB and `isWalkable` is what keeps it out of the JS walk; a
// <link> can name a script too (`rel=preload as=script`), so the exclusion is
// stated once here rather than left to the rel list to imply.
function isNotAScript(url) {
  return !/\.js(?:\?|$)/i.test(url);
}

// Which reference grammar this document is written in — and, for a module,
// whether the walk is allowed to read it at all. A `.json` is only ever
// reached through a `<link rel="manifest">`, so reading one as a PWA manifest
// is not a guess about its content.
function docKind(url) {
  const path = url.split('?')[0];
  if (/\.js$/.test(path)) return isWalkable(url) ? 'js' : '';
  if (/\.css$/.test(path)) return 'css';
  if (/\.(?:json|webmanifest)$/.test(path)) return 'manifest';
  // A route, not a file. `/` used to be spelled out on its own here; `B122`
  // added a second one and the rule that covers both is "no extension on the
  // last segment", which is what a server route looks like and what a font or
  // an icon never looks like. The three extension tests above run first, so
  // nothing with a known type can reach this line.
  if (/\.html$/.test(path) || !/\.[A-Za-z0-9]+$/.test(path)) return 'html';
  return '';
}

function assetsOf(rawSource, url) {
  const base = new URL(url, self.location.origin);
  const kind = docKind(url);
  // `B231`. The same rule as the import walk, stated at the other reader rather
  // than at one of them: a commented-out `<link>` or a `url()` inside `/* … */`
  // is a sentence, not a request. Nothing measured has been costing anything
  // here — the twelve fonts and three icons are identical either way, and a test
  // pins that — but a walk that reads comments in one grammar and not the other
  // is the shape `Law 13` is about.
  const source = withoutComments(rawSource, kind);
  const found = [];
  const add = (spec, accept) => {
    const request = resolveRef(spec, base);
    if (request && request.startsWith('/static/') && accept(request)) found.push(request);
  };

  if (kind === 'html') {
    for (const tag of source.match(LINK_TAG) || []) {
      const rel = (tag.match(/\brel\s*=\s*"([^"]*)"/i) || ['', ''])[1].trim().toLowerCase();
      if (!ASSET_RELS.has(rel)) continue;
      add((tag.match(/\bhref\s*=\s*"([^"]*)"/i) || ['', ''])[1], isNotAScript);
    }
  }
  if (kind === 'html' || kind === 'css') {
    for (const m of source.matchAll(CSS_URL)) add(m[2], u => STYLE_ASSET.test(u));
  }
  if (kind === 'manifest') {
    let icons = [];
    try {
      const parsed = JSON.parse(source);
      if (parsed && Array.isArray(parsed.icons)) icons = parsed.icons;
    } catch (err) {
      icons = [];
    }
    for (const icon of icons) {
      if (icon && typeof icon.src === 'string') add(icon.src, u => STYLE_ASSET.test(u));
    }
  }
  return found;
}

// Fetch one URL, store it, and report what it references. addAll is atomic — if
// any item fails, none are cached — so this puts one at a time and swallows its
// own failures: a single 404 must not block the whole install, and must not
// stop the walk reaching the rest of the graph either.
//
// `B85`. This fetched with `{ cache: 'reload' }`, which bypasses the HTTP cache
// and forces a full 200 for every entry. Install is paid on a cold install AND
// on every CACHE_NAME bump — 416 of those, 13 in the week `B57` was measured,
// because the policy at the top of this file is to bump whenever the list or
// the worker logic changes. So roughly twice a day every installed client
// re-downloaded the whole shell at full size while holding a byte-identical
// copy the server would have confirmed for free.
//
// `reload` was there for a reason that has to survive: install must never fill
// the OFFLINE cache from a stale HTTP-cache copy. `{ cache: 'default' }` does
// not preserve it. Measured 2026-09-15, one request per class through the real
// ASGI app:
//
//   /static/*.js|.css          Cache-Control: no-cache   ETag   Last-Modified
//   /static/*.woff2|.png|.json      (no Cache-Control)   ETag   Last-Modified
//   /                    (no Cache-Control, no ETag, no Last-Modified)
//
// `_RevalidatingStatic` (app.py:510) stamps `no-cache` on `.js`, `.css` and
// `.html` and nothing else, so the fonts, icons and PWA manifest carry
// validators but no freshness directive. Under `default` that means heuristic
// freshness (RFC 9111 §4.2.2) — served from disk for days without asking the
// server, which is exactly the stale install `reload` existed to prevent. The
// row that filed this concluded those URLs must keep `reload`; that is the
// wrong menu. `{ cache: 'no-cache' }` is the mode that means what install
// needs: ALWAYS revalidate, never serve a stored response the server has not
// just confirmed. It is the `reload` guarantee for all 213 entries — including
// the ones the response header does not cover — and it takes the 304 instead
// of the body. Measured: every class above answers a conditional request with
// `304` and a zero-byte body.
//
// `/` is the one that cannot revalidate, under any mode: `serve_html_with_nonce`
// (src/app_helpers.py:31) builds a fresh HTMLResponse per request with no ETag
// and no Last-Modified, so it is a full 283 KB every install. `B121`.
async function precacheOne(cache, url) {
  let res;
  try {
    res = await fetch(url, { cache: 'no-cache' });
  } catch (err) {
    return [];
  }
  if (!res || !res.ok) return [];
  // `B122`. A response that arrived from somewhere else is not this URL's
  // body, and storing it here would answer this URL with the wrong document
  // for the life of the cache. `/login` is the first entry that can redirect:
  // `app.py:972` sends it to `/` with a 302 when `AUTH_ENABLED` is false, and
  // without this guard an auth-disabled deployment would store a second
  // 283 KB copy of the app shell under `/login` and serve it to a navigation
  // there. Nothing else in either list redirects today, so this costs nothing
  // and covers the next one.
  if (res.redirected) return [];
  // Read the copy, store the original: cache.put consumes the body. Only a
  // document that CAN name something is read — a woff2 or a png is stored
  // without ever being turned into a string.
  const kind = docKind(url);
  let source = '';
  if (kind) {
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
  if (!source) return [];
  return kind === 'js' ? importsOf(source, url) : assetsOf(source, url);
}

// Breadth-first from the seeds. `seen` is what makes this terminate: the graph
// has cycles and the set is the entire argument. The round ceiling is a guard
// against a pathological tree, not the termination proof — this tree settles in
// three rounds (frontiers of 133, 74 and 6 after `B86`; the third is the icons
// reached through manifest.json, which is itself reached through the shell).
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

// `B120`. Nine server routes answer with the same app shell — `app.py:916-962`
// routes eight of them straight to `serve_index`, the identical document, and
// the SPA picks the view off `window.location.pathname`. The handler below
// answered a navigation only when the path was exactly `/`, so the other eight
// matched no branch at all, got no `respondWith`, and went to the network:
// offline they failed while a complete, correct copy of what they render sat
// in the cache. The sharp edge is the installed PWA — index.html builds a
// per-route manifest with `start_url: path`, so "Add to Home Screen" from
// `/tasks` installs an app whose launch URL was the one that could not open.
//
// The narrowing was deliberate and it stays. Matching *every* navigation
// served the app index in place of a deep-linked page, so this is a route set
// and not a relaxed predicate: `/backgrounds` and the `/static/*.html`
// prototype pages are their own documents and must still reach the network,
// and an unknown path must still get the server's 404 rather than a shell.
//
// **This list is derived, not transcribed** (`Law 13`). The source of truth is
// `app.py`, and `test_the_shell_route_set_is_what_the_server_actually_serves`
// drives the real app, asks every GET route with no path parameters for its
// body, and fails if the set that answers byte-identically to `/` is not
// exactly this. A tenth route added to `app.py` fails that test on the commit
// that adds it, which is the only thing that stops this list from being the
// next one to go stale.
const SHELL_ROUTES = new Set([
  '/',
  '/calendar',
  '/cookbook',
  '/email',
  '/gallery',
  '/library',
  '/memory',
  '/notes',
  '/tasks',
]);

// `B122`. Documents this worker holds that are NOT the shell — they answer a
// navigation with themselves, not with `/`. Derived from `PRECACHE` rather
// than written out again: a seed that is not under `/static/` is a page this
// app serves at that path, which is what makes it navigable, and a second list
// would be a second thing to keep in step.
const CACHED_PAGES = new Set(
  PRECACHE.filter(url => url !== '/' && !url.startsWith('/static/'))
);

// Which cache entry answers a navigation, or '' for "not ours — let it go to
// the network and the branches below".
function navigationKey(pathname) {
  if (SHELL_ROUTES.has(pathname)) return '/';
  if (CACHED_PAGES.has(pathname)) return pathname;
  return '';
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

  // HTML navigation: stale-while-revalidate the document this route serves —
  // and ONLY for a route this worker has a document for. Other navigations
  // (e.g. a deep-linked /static/*.html page, or a path that does not exist)
  // must go to the network/static handlers below; otherwise every navigation
  // was served the app index, replacing the page the user actually asked for.
  //
  // `navigationKey` is what makes that distinction a route set instead of the
  // single path this used to test (`B120`, `B122`).
  if (e.request.mode === 'navigate') {
    const key = navigationKey(url.pathname);
    if (key) {
      e.respondWith(
        caches.open(CACHE_NAME).then(async cache => {
          const cached = await cache.match(key);
          const network = fetch(e.request).then(res => {
            // The nine shell routes return the same bytes, so a fresh copy
            // from any of them refreshes the one entry all nine are served
            // from — the premise the route set is derived on, checked against
            // the real server by the test named above. `redirected` is the
            // same guard `precacheOne` carries, for the same reason.
            if (res && res.ok && !res.redirected) cache.put(key, res.clone());
            return res;
          }).catch(() => cached);
          return cached || network;
        })
      );
      return;
    }
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
