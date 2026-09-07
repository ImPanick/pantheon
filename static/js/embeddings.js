// static/js/embeddings.js — Settings → Embeddings (H04)
//
// `routes/embedding_routes.py` has been a complete, admin-gated embedding-model
// manager since before the fork, with **no markup anywhere**: the fastembed
// catalogue with downloaded / downloading / active / recommended / size, a
// download that runs off the event loop, a progress poll, a delete that refuses
// to remove the model in use, and custom endpoint configuration. Finished,
// self-consistent code that never got a single pixel.
//
// The most important state this panel has is the one where nothing is
// installed. `fastembed` and `chromadb` are both OPTIONAL dependencies, so a
// default install has neither — and then memory and document search fall back
// to keyword matching. `B40` is what that fallback was actually doing. So the
// panel leads with what is in use rather than with a catalogue, and an absent
// dependency is explained rather than reported as an error.
import uiModule from './ui.js';

const el = (id) => document.getElementById(id);

let _loaded = false;
let _pollTimers = new Map();

function _text(tag, text, css) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (css) node.style.cssText = css;
  return node;
}

/** A line of the status card: a label, a value, and an optional note. */
function _statusLine(label, value, note) {
  const row = document.createElement('div');
  row.style.cssText = 'display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;';
  row.appendChild(_text('span', label, 'opacity:0.6;min-width:150px;'));
  row.appendChild(_text('span', value, 'font-weight:600;'));
  if (note) row.appendChild(_text('span', note, 'opacity:0.55;font-size:11px;flex-basis:100%;'));
  return row;
}

async function _getJSON(url) {
  const res = await fetch(url, { credentials: 'same-origin' });
  if (!res.ok) {
    const err = new Error(`HTTP ${res.status}`);
    err.status = res.status;
    try { err.detail = (await res.json())?.detail; } catch (_) { /* not JSON */ }
    throw err;
  }
  return res.json();
}

// ── the status card ──

async function _renderStatus() {
  const host = el('emb-status');
  if (!host) return;
  host.textContent = '';

  let endpoint = null;
  let models = null;
  let modelsError = null;
  let chroma = null;

  try { endpoint = await _getJSON('/api/embeddings/endpoint'); } catch (_) { /* shown below */ }
  try { models = await _getJSON('/api/embeddings/models'); } catch (e) { modelsError = e; }
  try {
    const health = await _getJSON('/api/diagnostics/services');
    chroma = (health?.services || []).find((s) => s && s.name === 'chromadb') || null;
  } catch (_) { /* best effort — the two lines above still render */ }

  if (endpoint && endpoint.active && endpoint.url) {
    host.appendChild(_statusLine('Embedding with', endpoint.url,
      endpoint.model ? `Model: ${endpoint.model}` : 'No model name set — the server picks.'));
  } else if (Array.isArray(models)) {
    const active = models.find((m) => m.active);
    host.appendChild(_statusLine(
      'Embedding with',
      active ? active.model : 'a local model',
      active && !active.downloaded
        ? 'Configured but not downloaded yet — download it below, or search stays on keywords.'
        : 'Running on this machine.'));
  } else if (modelsError && modelsError.status === 503) {
    // The state that matters most, and the reason this panel leads with it.
    host.appendChild(_statusLine('Embedding with', 'nothing',
      'fastembed is not installed and no remote endpoint is set, so memory and '
      + 'document search fall back to keyword matching — they only find things '
      + 'that share a word with what you typed.'));
    host.appendChild(_text('div',
      'To use a model on this machine: pip install fastembed — then reopen this page. '
      + 'Or point Pantheon at a remote endpoint below.',
      'opacity:0.55;font-size:11px;margin-top:2px;'));
  } else {
    host.appendChild(_statusLine('Embedding with', 'unknown',
      'Could not read the embedding configuration.'));
  }

  if (chroma) {
    const readable = {
      ok: 'Working.',
      degraded: 'One of the two vector stores is down.',
      down: 'Installed but not working.',
      disabled: 'Not installed. Without it, memory search cannot use vectors at '
                + 'all, whatever model is configured above.',
    }[chroma.status] || chroma.detail || '';
    host.appendChild(_statusLine('Vector storage', chroma.status, readable));
  }
}

// ── the remote endpoint ──

async function _loadEndpoint() {
  const urlIn = el('emb-ep-url');
  const modelIn = el('emb-ep-model');
  const clearBtn = el('emb-ep-clear');
  if (!urlIn) return;
  try {
    const cfg = await _getJSON('/api/embeddings/endpoint');
    urlIn.value = cfg.url || '';
    if (modelIn) modelIn.value = cfg.model || '';
    if (clearBtn) clearBtn.hidden = !cfg.active;
  } catch (_) { /* the form still works; saving will report its own errors */ }
}

function _wireEndpoint() {
  const saveBtn = el('emb-ep-save');
  const clearBtn = el('emb-ep-clear');
  const msg = el('emb-ep-msg');
  if (!saveBtn || !clearBtn || !msg) return;

  saveBtn.addEventListener('click', async () => {
    const url = (el('emb-ep-url')?.value || '').trim();
    if (!url) {
      msg.textContent = 'Enter a URL, or use a local model.';
      msg.style.color = 'var(--red)';
      return;
    }
    saveBtn.disabled = true;
    msg.textContent = 'Saving…';
    msg.style.color = '';
    try {
      // The route takes a form body and validates the URL itself — it rejects
      // non-HTTP(S) schemes and the cloud metadata range before any outbound
      // request. Its refusal text is worth showing verbatim rather than
      // replacing with "failed": it says which rule the URL broke.
      const body = new URLSearchParams();
      body.set('url', url);
      body.set('model', el('emb-ep-model')?.value || '');
      body.set('api_key', el('emb-ep-key')?.value || '');
      const res = await fetch('/api/embeddings/endpoint', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body,
      });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try { detail = (await res.json())?.detail || detail; } catch (_) { /* not JSON */ }
        throw new Error(detail);
      }
      msg.textContent = 'Saved.';
      msg.style.color = 'var(--green)';
      const keyIn = el('emb-ep-key');
      if (keyIn) keyIn.value = '';   // never leave a key sitting in the DOM
      await _loadEndpoint();
      await _renderStatus();
    } catch (e) {
      msg.textContent = String(e.message || e);
      msg.style.color = 'var(--red)';
    } finally {
      saveBtn.disabled = false;
    }
  });

  clearBtn.addEventListener('click', async () => {
    if (!await uiModule.styledConfirm(
        'Stop using the remote endpoint and go back to a model on this machine?',
        { confirmText: 'Use a local model' })) return;
    clearBtn.disabled = true;
    msg.textContent = 'Clearing…';
    msg.style.color = '';
    try {
      const res = await fetch('/api/embeddings/endpoint', {
        method: 'DELETE', credentials: 'same-origin',
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      msg.textContent = 'Using a local model.';
      msg.style.color = 'var(--green)';
      await _loadEndpoint();
      await _renderStatus();
      await _renderModels();
    } catch (e) {
      msg.textContent = 'Could not clear the endpoint.';
      msg.style.color = 'var(--red)';
    } finally {
      clearBtn.disabled = false;
    }
  });
}

// ── the local catalogue ──

function _sizeLabel(model) {
  if (model.downloaded && model.cached_size_mb != null) return `${model.cached_size_mb} MB on disk`;
  if (model.size_gb) return `${model.size_gb} GB download`;
  return '';
}

function _modelRow(model) {
  const row = document.createElement('div');
  row.className = 'admin-list-row';
  row.style.cssText = 'display:flex;gap:8px;align-items:center;padding:6px 0;border-bottom:1px solid var(--border);';

  const left = document.createElement('div');
  left.style.cssText = 'flex:1;min-width:0;';
  const name = _text('div', model.model, 'font-size:12px;font-weight:600;word-break:break-all;');
  left.appendChild(name);

  const badges = document.createElement('div');
  badges.style.cssText = 'display:flex;gap:5px;flex-wrap:wrap;margin-top:2px;font-size:10px;';
  // Tint, never undiluted accent text: seven of the sixteen themes fail the
  // contrast floor on accent-coloured labels.
  const badge = (label, tinted) => _text('span', label,
    'padding:0 5px;border-radius:3px;border:1px solid '
    + (tinted ? 'color-mix(in srgb, var(--accent, var(--red)) 45%, var(--border))' : 'var(--border)')
    + ';opacity:0.8;');
  if (model.active) badges.appendChild(badge('in use', true));
  if (model.recommended) badges.appendChild(badge('recommended', true));
  if (model.downloaded) badges.appendChild(badge('downloaded'));
  const size = _sizeLabel(model);
  if (size) badges.appendChild(_text('span', size, 'opacity:0.5;'));
  if (model.dim) badges.appendChild(_text('span', `${model.dim} dims`, 'opacity:0.5;'));
  left.appendChild(badges);

  if (model.description) {
    left.appendChild(_text('div', model.description,
      'opacity:0.5;font-size:11px;margin-top:2px;line-height:1.4;'));
  }
  row.appendChild(left);

  const actions = document.createElement('div');
  actions.style.cssText = 'display:flex;gap:5px;flex-shrink:0;';
  if (model.downloading) {
    actions.appendChild(_text('span', 'Downloading…', 'font-size:11px;opacity:0.7;'));
    _pollUntilDownloaded(model.model);
  } else if (!model.downloaded) {
    const dl = document.createElement('button');
    dl.className = 'admin-btn-sm';
    dl.textContent = 'Download';
    dl.addEventListener('click', () => _download(model.model, dl));
    actions.appendChild(dl);
  } else if (!model.active) {
    // The route refuses to delete the active model, so the button is not
    // offered for it either — an action that always fails is not an action.
    const del = document.createElement('button');
    del.className = 'admin-btn-sm';
    del.textContent = 'Delete';
    del.addEventListener('click', () => _deleteModel(model));
    actions.appendChild(del);
  }
  row.appendChild(actions);
  return row;
}

async function _renderModels() {
  const host = el('emb-models');
  if (!host) return;
  host.textContent = '';
  let models;
  try {
    models = await _getJSON('/api/embeddings/models');
  } catch (e) {
    // A missing optional dependency is a state, not a failure. Saying
    // "fastembed is not installed" and stopping tells an operator nothing
    // about what it costs them or what to do.
    if (e.status === 503) {
      host.appendChild(_text('div',
        'No local models are available because fastembed is not installed.',
        'font-size:12px;'));
      host.appendChild(_text('div',
        'Install it with: pip install fastembed — then reopen this page. '
        + 'Until then, either set a remote endpoint above or search falls back '
        + 'to keyword matching.',
        'opacity:0.55;font-size:11px;margin-top:3px;line-height:1.5;'));
    } else {
      host.appendChild(_text('div', 'Could not read the model catalogue.',
        'font-size:12px;color:var(--red);'));
    }
    return;
  }
  if (!Array.isArray(models) || !models.length) {
    host.appendChild(_text('div', 'The catalogue is empty.', 'font-size:12px;opacity:0.6;'));
    return;
  }
  // Already sorted active-first, then downloaded, then by size — by the route,
  // which is where that decision belongs.
  for (const model of models) host.appendChild(_modelRow(model));
}

async function _download(name, btn) {
  btn.disabled = true;
  btn.textContent = 'Starting…';
  try {
    const res = await fetch(`/api/embeddings/models/${encodeURIComponent(name)}/download`, {
      method: 'POST', credentials: 'same-origin',
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    btn.textContent = 'Downloading…';
    _pollUntilDownloaded(name);
  } catch (e) {
    btn.disabled = false;
    btn.textContent = 'Download';
    uiModule.showError('Could not start the download');
  }
}

/**
 * Poll one model's status until it stops downloading.
 *
 * Keyed by model name so two rows cannot start two pollers for the same
 * download, and cleared when the panel is re-rendered — an interval that
 * outlives its row is how a settings modal ends up making requests forever.
 */
function _pollUntilDownloaded(name) {
  if (_pollTimers.has(name)) return;
  const tick = async () => {
    let status;
    try {
      status = await _getJSON(`/api/embeddings/models/${encodeURIComponent(name)}/status`);
    } catch (_) {
      _stopPoll(name);
      return;
    }
    if (status.downloading) {
      _pollTimers.set(name, setTimeout(tick, 2500));
      return;
    }
    _stopPoll(name);
    if (status.downloaded) uiModule.showToast(`${name} is ready`);
    await _renderModels();
    await _renderStatus();
  };
  _pollTimers.set(name, setTimeout(tick, 2500));
}

function _stopPoll(name) {
  const timer = _pollTimers.get(name);
  if (timer) clearTimeout(timer);
  _pollTimers.delete(name);
}

function _stopAllPolls() {
  for (const timer of _pollTimers.values()) clearTimeout(timer);
  _pollTimers.clear();
}

async function _deleteModel(model) {
  if (!await uiModule.styledConfirm(
      `Delete ${model.model} from this machine? It can be downloaded again.`,
      { confirmText: 'Delete', danger: true })) return;
  try {
    const res = await fetch(`/api/embeddings/models/${encodeURIComponent(model.model)}`, {
      method: 'DELETE', credentials: 'same-origin',
    });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try { detail = (await res.json())?.detail || detail; } catch (_) { /* not JSON */ }
      throw new Error(detail);
    }
    uiModule.showToast(`${model.model} deleted`);
    await _renderModels();
    await _renderStatus();
  } catch (e) {
    // The route's refusal to delete the model in use is worth quoting rather
    // than flattening to "failed" — it is the whole reason the button exists.
    uiModule.showError(String(e.message || e));
  }
}

/** Called when the Embeddings panel is opened. Idempotent. */
export async function open() {
  _stopAllPolls();
  if (!_loaded) {
    _wireEndpoint();
    _loaded = true;
  }
  await _loadEndpoint();
  await Promise.all([_renderStatus(), _renderModels()]);
}

export default { open };
