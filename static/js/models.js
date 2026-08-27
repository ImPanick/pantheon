// static/js/models.js

/**
 * Model list fetching.
 *
 * The cached `/api/models` items this module keeps are the source the model
 * picker (modelPicker.js), the group builder, the Forge and the admin panel
 * all read through `getCachedItems()`.
 */

// Side-effect import, not a value import: dragSort.js sets `window.dragSortModule`
// at module scope, and sessions.js reads that global to enable session drag-sort
// (sessions.js:2505). models.js is the only module statically imported at boot
// that pulls dragSort.js in — galleryEditor.js, the other importer, is loaded
// lazily by panels.js. Removing this line silently disables session reordering.
import './dragSort.js';

let API_BASE = '';
let _cachedItems = []; // cached /api/models items for model-switch dropdown
let _lastFetchTime = 0;
let _fetchInflight = null;
let _fetchSeq = 0;
const _FETCH_CACHE_TTL = 30000; // 30s client-side cache for /api/models

export function init(apiBase) {
  API_BASE = apiBase;
}

export async function refreshModels(force = false, opts = {}) {
  const cacheOnly = !!(opts && opts.cacheOnly);
  const hasCache = _cachedItems.length > 0;

  // Skip network fetch if cache is fresh and not forced.
  // Cache-only is used for cheap picker/settings opens, but it must not turn a
  // cold page load into an empty model list. If nothing has been fetched in this
  // tab yet, do one normal load.
  const now = Date.now();
  const needsFetch = !(cacheOnly && hasCache) && (force || _cachedItems.length === 0 || (now - _lastFetchTime) >= _FETCH_CACHE_TTL);
  if (!needsFetch) return;

  try {
    if (force) _fetchInflight = null;
    if (!_fetchInflight) {
      // Pass ?refresh=true on forced refreshes so the BACKEND's 30s
      // per-user cache also gets bypassed. Without this, `force=true`
      // only clears the frontend cache and the same stale list comes
      // back — newly-served endpoints don't appear until the cache
      // ages out. (Bug repro: serve a model, picker is empty for ~30s
      // even though the endpoint is in the DB and online.)
      const _seq = ++_fetchSeq;
      const _url = `${API_BASE}/api/models` + (force ? '?refresh=true' : '?background=false');
      _fetchInflight = fetch(_url, { credentials: 'same-origin' })
        .then(async (res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const data = await res.json();
          return { data, seq: _seq };
        })
        .finally(() => { _fetchInflight = null; });
    }
    const { data, seq } = await _fetchInflight;
    if (seq < _fetchSeq) return;
    _lastFetchTime = Date.now();
    _cachedItems = data.items || [];
  } catch (e) {
    console.error(e);
  }
}

export function getCachedItems() { return _cachedItems; }

const modelsModule = {
  init,
  refreshModels,
  getCachedItems,
};

export default modelsModule;
window.modelsModule = modelsModule;
