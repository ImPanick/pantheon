/**
 * AI model dropdown loader — fetches available model endpoints from
 * the backend and populates the editor's model-select surfaces:
 *
 *   #ge-ai-inpaint   — inpaint picker
 *   select.ge-tool-model[data-ge-tool-model="…"]
 *                    — per-tool pickers (harmonize / upscale / style /
 *                      sharpen / etc.)
 *
 * (The editor-wide "Gen" picker #ge-ai-model was removed from the
 * topbar; each tool carries its own model select now.)
 *
 * Each model is filtered through a small capability classifier so the
 * inpaint dropdown only sees image+mask edit models and the per-tool
 * dropdowns get everything img2img-capable.
 *
 * Every picker ends with a "+ Serve a model in Cookbook…" sentinel —
 * choosing it opens Cookbook → Serve filtered to image models, then
 * reverts the picker to its prior value (so it's an action, not a
 * selectable model).
 *
 * @param {{
 *   container:              HTMLElement,
 *   apiBase:                string,
 *   openCookbookForImg2img: () => void,
 * }} deps
 */
import { state } from './state.js';
import { sortModelIds } from '../modelSort.js';

// Heuristic classifier on a model id + endpoint name. A model can be:
//   - gen: text-to-image generation
//   - inpaint: image+mask edit (inpaint / img2img)
// Some models do only one (e.g. dall-e-3 = gen-only, no edits API).
function modelCaps(modelId, endpointName, endpointType) {
  const id = (modelId || '').toLowerCase();
  const name = (endpointName || '').toLowerCase();
  const type = (endpointType || '').toLowerCase();
  // Reject anything obviously text-only.
  const textOnly = /(?:^|[/\-_:])(gpt-?[345]|gpt-oss|claude|llama|qwen[^-]*chat|chat$|instruct$|coder)/i;
  if (textOnly.test(id) && !/image/i.test(id)) return { gen: false, inpaint: false };
  // OpenAI image family.
  if (/dall-e-3/.test(id))    return { gen: true,  inpaint: false };
  if (/dall-e-2/.test(id))    return { gen: true,  inpaint: true  };
  if (/gpt-image/.test(id))   return { gen: true,  inpaint: true  };
  // Diffusion families — most generic SD/SDXL/Flux base models
  // support both via diffusers.
  if (/(?:^|[/\-_])(?:sd-?xl|sdxl|sd3|sd-|stable[\s-]*diffusion|flux|playground|pixart|kandinsky)/i.test(id)) {
    const isInpaintModel = /inpaint|edit|fill/i.test(id) || /inpaint|edit|fill/i.test(name);
    return { gen: !isInpaintModel || /base/i.test(id), inpaint: true };
  }
  // Self-hosted diffusion server: model id often matches the repo
  // name; trust the endpoint name hint.
  if (type === 'image') {
    if (/inpaint|edit|fill/i.test(name)) return { gen: false, inpaint: true };
    return { gen: true, inpaint: true };
  }
  if (/inpaint|edit|fill/i.test(name)) return { gen: false, inpaint: true };
  if (/diffus|flux|sd|image/i.test(name)) return { gen: true, inpaint: true };
  // Editor image tools should be conservative. Unknown LLM/chat models
  // do not belong in image generation or inpaint pickers.
  return { gen: false, inpaint: false };
}

export function wireAIModelSelectors({ container, apiBase, openCookbookForImg2img }) {
  // Delegated handler for the "+ Serve a model in Cookbook…" sentinel
  // option — catches clicks regardless of whether loadAIModels has
  // rewired the individual select yet and survives any innerHTML
  // reset later.
  container.addEventListener('change', (e) => {
    const sel = e.target.closest('select');
    if (!sel) return;
    if (sel.value !== '__serve_cookbook__') return;
    // Revert to the previous selection so the sentinel isn't "stuck".
    const prev = sel._prevServeValue ?? '';
    sel.value = prev;
    openCookbookForImg2img();
  });
  // Track prior value so we can restore it after the sentinel fires.
  container.addEventListener('focus', (e) => {
    const sel = e.target.closest('select');
    if (sel && sel.value !== '__serve_cookbook__') sel._prevServeValue = sel.value;
  }, true);

  const aiInpaintSelect = document.getElementById('ge-ai-inpaint');
  // The global Gen model dropdown was removed from the editor topbar, so
  // there is nothing left to populate unless the inpaint select or a
  // per-tool select is present.
  if (!aiInpaintSelect && !document.querySelector('select.ge-tool-model')) return;

  async function loadAIModels(opts = {}) {
    try {
      const selectBaseUrl = opts.selectBaseUrl || '';
      const prevInpaintValue = aiInpaintSelect?.value || '';
      const res = await fetch(`${apiBase}/api/model-endpoints`);
      const endpoints = await res.json();
      if (aiInpaintSelect) aiInpaintSelect.innerHTML = '<option value="">Auto</option>';
      const perToolSelects = Array.from(document.querySelectorAll('select.ge-tool-model'));
      for (const ts of perToolSelects) ts.innerHTML = '<option value="">Auto</option>';
      let firstInpaint = null;
      let selectedInpaint = null;
      for (const ep of endpoints) {
        if (!ep.is_enabled) continue;
        const hasListedModels = Array.isArray(ep.models) && ep.models.length;
        const models = hasListedModels ? sortModelIds(ep.models) : [''];
        const isImageEndpoint = (ep.model_type || '').toLowerCase() === 'image';
        // Image/inpaint endpoints can be called by URL even when their
        // /models cache is still empty, so don't strand a freshly served
        // Cookbook model as "(offline)" in the editor picker.
        const epUsable = !!ep.online || isImageEndpoint;
        for (const modelId of models) {
          const caps = modelCaps(modelId || ep.name, ep.name, ep.model_type);
          if (!caps.gen && !caps.inpaint) continue;
          // Encode "<base_url>::<model_id>" so the value carries both pieces.
          const value = `${ep.base_url}::${modelId}`;
          const shortModel = modelId ? String(modelId).split('/').pop() : (ep.name || ep.base_url);
          const epHint = modelId && ep.name && ep.name !== modelId ? ` · ${ep.name}` : '';
          const label = `${shortModel}${epHint}${epUsable ? '' : ' (offline)'}`;
          if (caps.inpaint && aiInpaintSelect) {
            const opt = document.createElement('option');
            opt.value = value;
            opt.textContent = label;
            opt.disabled = !epUsable;
            aiInpaintSelect.appendChild(opt);
            if (epUsable && selectBaseUrl && ep.base_url === selectBaseUrl && !selectedInpaint) selectedInpaint = value;
            // Prefer dedicated inpaint/edit models for default selection.
            if (epUsable && !firstInpaint && (!modelId || /inpaint|edit|fill|gpt-image/i.test(modelId) || /inpaint|edit|fill/i.test(ep.name || ''))) {
              firstInpaint = value;
            }
          }
          // Per-tool selectors get every img2img-capable entry. Both
          // caps.inpaint AND caps.gen models work for harmonize /
          // style / upscale (anything that can do img2img).
          if (caps.inpaint || caps.gen) {
            for (const ts of perToolSelects) {
              const opt = document.createElement('option');
              opt.value = value;
              opt.textContent = label;
              opt.disabled = !epUsable;
              ts.appendChild(opt);
            }
          }
        }
      }
      const hasValue = (sel, value) => !!value && [...sel.options].some(o => o.value === value);
      if (aiInpaintSelect) {
        if (selectedInpaint) aiInpaintSelect.value = selectedInpaint;
        else if (hasValue(aiInpaintSelect, prevInpaintValue)) aiInpaintSelect.value = prevInpaintValue;
        else if (firstInpaint) aiInpaintSelect.value = firstInpaint;
      }
      // Append the "Serve a model in Cookbook…" sentinel at the
      // bottom of every model dropdown.
      const appendServeSentinel = (sel) => {
        const sep = document.createElement('option');
        sep.disabled = true;
        sep.textContent = '──────────';
        sel.appendChild(sep);
        const serveOpt = document.createElement('option');
        serveOpt.value = '__serve_cookbook__';
        serveOpt.textContent = '+ Serve a model in Cookbook…';
        sel.appendChild(serveOpt);
      };
      for (const ts of perToolSelects) appendServeSentinel(ts);
      if (aiInpaintSelect) appendServeSentinel(aiInpaintSelect);
      // Wire the sentinel on the Inpaint select too.
      const wireServeSentinel = (sel) => {
        if (!sel) return;
        let prev = sel.value;
        sel.addEventListener('change', () => {
          if (sel.value === '__serve_cookbook__') {
            sel.value = prev;
            openCookbookForImg2img();
            return;
          }
          prev = sel.value;
        });
      };
      wireServeSentinel(aiInpaintSelect);
      // Restore each per-tool selection from localStorage.
      for (const ts of perToolSelects) {
        const key = 'ge-tool-model-' + ts.dataset.geToolModel;
        try {
          const saved = localStorage.getItem(key);
          if (saved && [...ts.options].some(o => o.value === saved)) {
            ts.value = saved;
          }
        } catch {}
        let prevValue = ts.value;
        ts.addEventListener('change', () => {
          if (ts.value === '__serve_cookbook__') {
            ts.value = prevValue;
            openCookbookForImg2img();
            return;
          }
          prevValue = ts.value;
          try { localStorage.setItem(key, ts.value); } catch {}
        });
      }
    } catch (e) {
      // Fetch failed — still give the user the affordance to set up
      // a model. Otherwise the dropdown shows only "Auto" with no
      // hint about what to do next.
      const fallback = '<option value="">Auto</option><option value="" disabled>──────────</option><option value="__serve_cookbook__">+ Serve a model in Cookbook…</option>';
      if (aiInpaintSelect) aiInpaintSelect.innerHTML = fallback;
      document.querySelectorAll('select.ge-tool-model').forEach(ts => { ts.innerHTML = fallback; });
      const wireServe = (sel) => {
        if (!sel) return;
        let prev = sel.value;
        sel.addEventListener('change', () => {
          if (sel.value === '__serve_cookbook__') {
            sel.value = prev;
            openCookbookForImg2img();
            return;
          }
          prev = sel.value;
        });
      };
      wireServe(aiInpaintSelect);
      document.querySelectorAll('select.ge-tool-model').forEach(wireServe);
    }
  }
  loadAIModels();
  const onModelEndpointsUpdated = (e) => {
    if (!container.isConnected) {
      window.removeEventListener('ge:model-endpoints-updated', onModelEndpointsUpdated);
      return;
    }
    loadAIModels({ selectBaseUrl: e.detail?.baseUrl || '' });
  };
  window.addEventListener('ge:model-endpoints-updated', onModelEndpointsUpdated);
  // Re-fetch the model list when the user opens the inpaint dropdown,
  // so a model served via Cookbook mid-edit shows up without having to
  // close and reopen the editor. Debounced to one refresh per 3s so
  // rapid open/close doesn't hammer the endpoint. Preserves the
  // current selection across the reload.
  let _lastModelRefresh = 0;
  const refreshOnOpen = (e) => {
    const sel = e.target.closest('#ge-ai-inpaint, select.ge-tool-model');
    if (!sel) return;
    const now = Date.now();
    if (now - _lastModelRefresh < 3000) return;
    _lastModelRefresh = now;
    const keep = sel.value;
    loadAIModels().then(() => {
      // Restore the prior selection if it still exists.
      if ([...sel.options].some(o => o.value === keep)) sel.value = keep;
    });
  };
  container.addEventListener('mousedown', refreshOnOpen, true);
}
