// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/settings/mcpBuild.js
//
// `P22-22` — build an MCP server in the browser, without a terminal.
//
// Three things, each drawn into a host it is handed and nothing else (no
// document-wide lookups), because the host moves: `settings.js:showMcpForm`
// draws into `#unified-intg-form`, which `P22-21` moves with its id from
// Settings → Integrations into the Workbench's MCP & Integrations room
// (`#workbench-room-integrations`). Found by its id, it is the same element in
// either place, so this module works in both.
//
//   mountToolTry(host, { tool, call })   *Try a tool*: a form built from the
//       tool's `input_schema` (`workbench/argsForm.js`, the one schema form),
//       one call, and what came back as text — stdout, stderr, the exit, how
//       long, whether it ran out of time, whether the agent has it switched
//       off. Shared by a connected server's tool rows (`/api/mcp/servers/{id}/call`)
//       and a server being built (`/api/mcp/scaffold/{name}/try`).
//   mountMcpBuildDoor(host, { onOpen })  *Build an MCP server*, greyed with the
//       workstation's own sentence when it is off, has no address, or is not
//       this person's to use — the Code step's rule (`D-2026-10-01-05` §3).
//   mountMcpBuild(host, { isAdmin, onRegister, onClose })  the panel: make one
//       in your workstation, check it, try its tools, edit its code, and hand
//       it to an admin. *Register* opens the existing *Add MCP Server* form
//       filled in (`onRegister`) — `POST /api/mcp/servers`, `require_admin`,
//       stays the only way a server is registered (`D-2026-09-27-01`). A
//       non-admin is shown the fields to send instead.
//
// The routes, spelled here as their callers (`B596`):
//   GET  /api/mcp/scaffold                 POST /api/mcp/scaffold
//   GET  /api/mcp/scaffold/${name}          PUT  /api/mcp/scaffold/${name}
//   POST /api/mcp/scaffold/${name}/check    POST /api/mcp/scaffold/${name}/try
//
// Nothing here checks arguments against a schema before sending them
// (`D-2026-09-27-02`): the server enforces its own, and *Try* shows what it said.

import { mountArgsForm } from '../workbench/argsForm.js';
import { describeServerRefusal } from './mcpFields.js';

let _seq = 0;
const _id = (stem) => `mcp-build-${stem}-${++_seq}`;

function _el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function _button(text, cls) {
  const b = _el('button', cls || 'admin-btn-sm', text);
  b.type = 'button';
  return b;
}

const _PRE = 'white-space:pre-wrap;word-break:break-word;font-family:monospace;font-size:11px;'
  + 'margin:3px 0 0;padding:6px 8px;border:1px solid var(--border);border-radius:5px;'
  + 'background:color-mix(in srgb, var(--fg) 4%, transparent);max-height:220px;overflow:auto;';
const _NOTE = 'font-size:11px;line-height:1.45;margin:4px 0;';

async function _json(response) {
  try { return await response.json(); } catch (_) { return {}; }
}

/** `fetch` for the scaffold routes: the answer, or an Error carrying the
 *  server's own sentence (`describeServerRefusal`). */
async function _ask(url, init) {
  const r = await fetch(url, { credentials: 'same-origin', ...(init || {}) });
  const data = await _json(r);
  if (!r.ok) throw new Error(describeServerRefusal(r.status, data).text);
  return data;
}

function _post(url, body) {
  return _ask(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
}

// ── what a call answered, in words ───────────────────────────────────────────

/**
 * The words *Try* draws for one answer of `/call` or `/try` — the same
 * envelope from both. `headline` is one sentence; `meta` the exit, the time
 * and whether it ran out of time; `sections` the texts that came back, each
 * with what it is. Pure, so a test reads exactly what a person would.
 */
export function describeTryResult(result) {
  const r = result && typeof result === 'object' ? result : {};
  const ms = Number.isFinite(r.duration_ms) ? `${r.duration_ms} ms` : null;
  let headline;
  let tone;
  if (r.ok) {
    headline = ms ? `It answered in ${ms}.` : 'It answered.';
    tone = 'ok';
  } else if (r.timed_out) {
    headline = 'It did not answer in time, and was stopped.';
    tone = 'bad';
  } else if (r.error) {
    headline = String(r.error);
    tone = 'bad';
  } else {
    headline = 'It answered that it failed.';
    tone = 'bad';
  }
  const meta = [];
  if (r.exit_code !== undefined && r.exit_code !== null) meta.push(`exit code ${r.exit_code}`);
  if (ms) meta.push(ms);
  meta.push(r.timed_out ? 'ran out of time' : 'finished in time');
  const sections = [
    ['What it answered', r.stdout],
    ['What it said went wrong', r.stderr],
    ['What it printed while it ran', r.printed],
  ].filter(([, text]) => typeof text === 'string' && text !== '');
  if (r.ok && !sections.length) sections.push(['What it answered', '(nothing)']);
  const notes = [];
  if (r.tool_is_disabled) {
    notes.push('The assistant has this tool switched off. This test call ran anyway; '
      + 'the assistant still cannot call it.');
  }
  if (r.truncated) notes.push('The answer was longer than this shows; the end was cut.');
  return { headline, tone, meta: meta.join(' · '), sections, notes };
}

function _drawResult(box, result) {
  const said = describeTryResult(result);
  box.replaceChildren();
  const head = _el('p', 'mcp-try-headline', said.headline);
  head.setAttribute('data-tone', said.tone);
  head.style.cssText = _NOTE + `font-weight:600;color:${said.tone === 'ok' ? 'var(--green, #50fa7b)' : 'var(--red)'};`;
  box.appendChild(head);
  const meta = _el('p', 'mcp-try-meta', said.meta);
  meta.style.cssText = _NOTE + 'opacity:0.65;';
  box.appendChild(meta);
  for (const [label, text] of said.sections) {
    const part = _el('div', 'mcp-try-section');
    part.setAttribute('data-mcp-try-section', label);
    const cap = _el('div', null, label);
    cap.style.cssText = 'font-size:11px;opacity:0.7;margin-top:4px;';
    part.appendChild(cap);
    const pre = _el('pre', null, text);
    pre.style.cssText = _PRE;
    part.appendChild(pre);
    box.appendChild(part);
  }
  for (const line of said.notes) {
    const n = _el('p', 'mcp-try-note', line);
    n.style.cssText = _NOTE + 'opacity:0.75;';
    box.appendChild(n);
  }
}

// ── Try a tool ────────────────────────────────────────────────────────────────

/**
 * *Try a tool* into `host`. `tool` is `{name, description, input_schema, …}`;
 * `call(args)` resolves to the `/call`/`/try` envelope or rejects with a
 * sentence. Returns `{ element, run() → Promise, destroy() }`.
 */
export function mountToolTry(host, { tool, call } = {}) {
  const t = tool && typeof tool === 'object' ? tool : {};
  const name = String(t.name || '');
  const box = _el('div', 'mcp-try');
  box.setAttribute('data-mcp-try-panel', name);
  box.style.cssText = 'margin:4px 0 6px;padding:8px 10px;border:1px solid var(--border);border-radius:6px;';
  const lead = _el('p', 'mcp-try-lead', `Call ${name} once with what you type. It runs for real.`);
  lead.style.cssText = _NOTE + 'opacity:0.75;margin-top:0;';
  box.appendChild(lead);
  if (t.description) {
    const desc = _el('p', 'mcp-try-desc', String(t.description));
    desc.style.cssText = _NOTE + 'opacity:0.6;';
    box.appendChild(desc);
  }
  const formHost = _el('div', 'mcp-try-form');
  box.appendChild(formHost);
  const form = mountArgsForm(formHost, {
    tool: { ...t, name, input_schema: t.input_schema || t.inputSchema || {} },
    pickField: null,
    lenient: true,
  });
  const row = _el('div', 'mcp-try-actions');
  row.style.cssText = 'display:flex;gap:8px;align-items:center;margin-top:6px;';
  const go = _button(`Run ${name}`, 'admin-btn-sm mcp-try-run');
  go.setAttribute('data-mcp-try-run', name);
  row.appendChild(go);
  box.appendChild(row);
  const result = _el('div', 'mcp-try-result');
  result.setAttribute('role', 'status');
  result.setAttribute('aria-live', 'polite');
  box.appendChild(result);
  host.appendChild(box);

  async function run() {
    const read = form.read();
    const args = (read && read.args) || {};
    go.disabled = true;
    result.replaceChildren(_el('p', 'mcp-try-busy', 'Running…'));
    try {
      _drawResult(result, await call(args));
    } catch (err) {
      const p = _el('p', 'mcp-try-refused', String((err && err.message) || err || 'It could not be called.'));
      p.setAttribute('data-tone', 'bad');
      p.style.cssText = _NOTE + 'color:var(--red);';
      result.replaceChildren(p);
    } finally {
      go.disabled = false;
    }
  }
  go.addEventListener('click', (event) => {
    if (event && event.preventDefault) event.preventDefault();
    run();
  });
  return { element: box, run, destroy() { form.destroy(); box.remove(); } };
}

// ── the door ──────────────────────────────────────────────────────────────────

/**
 * *Build an MCP server*, live when this person may build one in their
 * workstation and greyed — with the workstation's own sentence, visible and
 * tied to the button — when not. Resolves to `{ available, why }`.
 */
export async function mountMcpBuildDoor(host, { onOpen } = {}) {
  const wrap = _el('div', 'mcp-build-door');
  wrap.style.cssText = 'display:flex;flex-direction:column;gap:3px;margin:2px 0 8px;';
  const line = _el('div');
  line.style.cssText = 'display:flex;gap:8px;align-items:center;flex-wrap:wrap;';
  const lead = _el('span', null, 'Or write your own, in your workstation:');
  lead.style.cssText = 'font-size:11px;opacity:0.7;';
  const open = _button('Build an MCP server', 'admin-btn-sm mcp-build-open');
  open.setAttribute('data-mcp-build-open', '');
  line.appendChild(lead);
  line.appendChild(open);
  wrap.appendChild(line);
  const why = _el('p', 'mcp-build-door-why');
  why.id = _id('why');
  why.style.cssText = _NOTE + 'opacity:0.7;display:none;';
  wrap.appendChild(why);
  host.replaceChildren(wrap);

  let state = { available: false, why: 'Asking the workstation…' };
  open.disabled = true;
  try {
    const listed = await _ask('/api/mcp/scaffold');
    state = (listed && listed.workstation) || state;
  } catch (err) {
    state = { available: false, why: String((err && err.message) || err) };
  }
  open.disabled = !state.available;
  if (!state.available) {
    open.setAttribute('aria-disabled', 'true');
    open.setAttribute('aria-describedby', why.id);
    open.title = String(state.why || '');
    why.textContent = String(state.why || '');
    why.style.display = 'block';
  }
  open.addEventListener('click', (event) => {
    if (event && event.preventDefault) event.preventDefault();
    if (state.available && typeof onOpen === 'function') onOpen();
  });
  return state;
}

// ── the panel ─────────────────────────────────────────────────────────────────

const CHECKED_WORDS = {
  works: 'It started when it was last checked.',
  broken: 'It did not start when it was last checked.',
  changed: 'Edited since it was last checked.',
  never: 'Not checked since Pantheon started.',
};

/** One sentence for a check's answer (`{started, tools, error}`). */
export function describeCheck(check) {
  const c = check && typeof check === 'object' ? check : {};
  if (c.started) {
    const tools = Array.isArray(c.tools) ? c.tools : [];
    return tools.length ? `It started and offers: ${tools.join(', ')}`
      : 'It started, and offers no tools yet.';
  }
  return `It did not start: ${c.error || 'no reason was given.'}`;
}

/** The fields an admin types, as plain lines a person can send. */
export function registrationText(reg) {
  const r = reg && typeof reg === 'object' ? reg : {};
  const args = Array.isArray(r.args) ? r.args : [];
  return [
    `Name: ${r.name || ''}`,
    `Transport: ${r.transport || 'stdio'}`,
    `Command: ${r.command || ''}`,
    'Arguments (one box each):',
    ...args.map((a) => `  ${a}`),
    'Environment: leave empty',
  ].join('\n');
}

const RUNS_AS_AUTHOR = 'Once it is registered, every assistant on this Pantheon can call it, '
  + 'and each call runs in your workstation account, with your files.';

/**
 * The Build panel into `host`. `isAdmin` decides what *Register* does:
 * `onRegister(registration)` for an admin, the fields as text otherwise.
 * Resolves once the list is drawn; returns `{ element, refresh(), build() }`.
 */
export async function mountMcpBuild(host, { isAdmin = false, onRegister, onClose } = {}) {
  const panel = _el('div', 'admin-card mcp-build');
  panel.style.cssText = 'margin-top:8px;';
  const title = _el('h2', null, 'Build an MCP server');
  title.style.cssText = 'font-size:13px;';
  panel.appendChild(title);
  const lead = _el('p', 'mcp-build-lead',
    'It is made in your own workstation and runs there — no terminal needed. '
    + 'Check it, try its tools, and hand it to an administrator when it works.');
  lead.style.cssText = _NOTE + 'opacity:0.75;';
  panel.appendChild(lead);
  const why = _el('p', 'mcp-build-why');
  why.setAttribute('role', 'status');
  why.style.cssText = _NOTE + 'display:none;';
  panel.appendChild(why);

  // New server
  const fresh = _el('div', 'mcp-build-new settings-col');
  const h3 = _el('h3', null, 'A new server');
  h3.style.cssText = 'font-size:12px;margin:8px 0 4px;';
  fresh.appendChild(h3);
  const field = (label, placeholder, cls) => {
    const row = _el('div', 'settings-row');
    const id = _id(cls);
    const l = _el('label', 'settings-label', label);
    l.setAttribute('for', id);
    const input = _el('input', `settings-input ${cls}`);
    input.id = id;
    input.placeholder = placeholder;
    input.autocomplete = 'off';
    input.spellcheck = false;
    row.appendChild(l);
    row.appendChild(input);
    fresh.appendChild(row);
    return input;
  };
  const nameIn = field('Name', 'weather', 'mcp-build-name');
  const toolIn = field('Tool', 'get_forecast', 'mcp-build-tool');
  const descIn = field('What it is for', 'Weather forecasts (optional)', 'mcp-build-description');
  const hint = _el('p', null, 'Lowercase letters, digits and dashes for the name; letters, digits '
    + 'and single underscores for the tool. More tools can be added in its code later.');
  hint.style.cssText = _NOTE + 'opacity:0.6;';
  fresh.appendChild(hint);
  const freshRow = _el('div', 'settings-row');
  freshRow.style.cssText = 'justify-content:flex-end;gap:8px;align-items:center;';
  const freshMsg = _el('span', 'mcp-build-new-msg');
  freshMsg.setAttribute('role', 'status');
  freshMsg.style.cssText = 'font-size:11px;flex:1;';
  const make = _button('Build it', 'admin-btn-add mcp-build-make');
  const close = _button('Close', 'admin-btn-add mcp-build-close');
  freshRow.appendChild(freshMsg);
  freshRow.appendChild(make);
  freshRow.appendChild(close);
  fresh.appendChild(freshRow);
  panel.appendChild(fresh);

  // Yours
  const listHead = _el('h3', null, 'Yours');
  listHead.style.cssText = 'font-size:12px;margin:12px 0 4px;';
  panel.appendChild(listHead);
  const list = _el('div', 'mcp-build-list');
  panel.appendChild(list);
  host.replaceChildren(panel);

  const cards = new Map();

  function setAvailable(ws) {
    const ok = !!(ws && ws.available);
    why.textContent = ok ? '' : String((ws && ws.why) || '');
    why.style.display = ok ? 'none' : 'block';
    for (const input of [nameIn, toolIn, descIn, make]) input.disabled = !ok;
  }

  function card(entry) {
    const name = String(entry.name);
    const box = _el('div', 'mcp-build-server');
    box.setAttribute('data-mcp-build-server', name);
    box.style.cssText = 'border:1px solid var(--border);border-radius:8px;padding:8px 10px;margin-bottom:6px;';
    const head = _el('div');
    head.style.cssText = 'display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;';
    head.appendChild(_el('strong', null, name));
    const state = _el('span', 'mcp-build-checked');
    state.style.cssText = 'font-size:11px;opacity:0.7;';
    head.appendChild(state);
    box.appendChild(head);
    const said = _el('p', 'mcp-build-check');
    said.setAttribute('role', 'status');
    said.style.cssText = _NOTE;
    box.appendChild(said);
    const printed = _el('pre', 'mcp-build-printed');
    printed.style.cssText = _PRE;
    printed.style.display = 'none';
    box.appendChild(printed);
    const actions = _el('div');
    actions.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;margin:4px 0;';
    const checkBtn = _button('Check', 'admin-btn-sm mcp-build-check-run');
    const editBtn = _button('Edit the code', 'admin-btn-sm mcp-build-edit');
    const regBtn = _button('Register', 'admin-btn-sm mcp-build-register');
    actions.appendChild(checkBtn);
    actions.appendChild(editBtn);
    actions.appendChild(regBtn);
    box.appendChild(actions);
    const tools = _el('div', 'mcp-build-tools');
    box.appendChild(tools);
    const source = _el('div', 'mcp-build-source');
    box.appendChild(source);
    const register = _el('div', 'mcp-build-registration');
    box.appendChild(register);

    const c = { name, box, state, said, printed, tools, source, register };

    c.paintState = (word) => { state.textContent = CHECKED_WORDS[word] || ''; };
    c.paintCheck = (check) => {
      said.textContent = describeCheck(check);
      said.setAttribute('data-tone', check && check.started ? 'ok' : 'bad');
      said.style.color = check && check.started ? 'var(--green, #50fa7b)' : 'var(--red)';
      const err = check && typeof check.stderr === 'string' ? check.stderr.trim() : '';
      printed.textContent = err;
      printed.style.display = err ? 'block' : 'none';
      tools.replaceChildren();
      for (const offer of (check && check.started && Array.isArray(check.offers)) ? check.offers : []) {
        const row = _el('div', 'mcp-build-tool');
        row.setAttribute('data-mcp-build-tool', String(offer.name));
        const line = _el('div');
        line.style.cssText = 'display:flex;gap:8px;align-items:center;';
        line.appendChild(_el('code', null, String(offer.name)));
        const tryBtn = _button('Try', 'admin-btn-sm mcp-build-try');
        tryBtn.setAttribute('aria-expanded', 'false');
        line.appendChild(tryBtn);
        row.appendChild(line);
        const place = _el('div');
        place.style.display = 'none';
        row.appendChild(place);
        let mounted = null;
        tryBtn.addEventListener('click', (event) => {
          if (event && event.preventDefault) event.preventDefault();
          const shown = place.style.display !== 'none';
          if (!shown && !mounted) {
            mounted = mountToolTry(place, {
              tool: offer,
              call: (args) => _post(`/api/mcp/scaffold/${encodeURIComponent(name)}/try`,
                { tool: offer.name, arguments: args }),
            });
          }
          place.style.display = shown ? 'none' : 'block';
          tryBtn.setAttribute('aria-expanded', shown ? 'false' : 'true');
        });
        tools.appendChild(row);
      }
    };

    c.check = async () => {
      checkBtn.disabled = true;
      said.textContent = 'Starting it in your workstation…';
      said.style.color = '';
      try {
        const check = await _post(`/api/mcp/scaffold/${encodeURIComponent(name)}/check`);
        c.paintCheck(check);
        c.paintState(check.started ? 'works' : 'broken');
        return check;
      } catch (err) {
        said.textContent = String((err && err.message) || err);
        said.style.color = 'var(--red)';
        return null;
      } finally {
        checkBtn.disabled = false;
      }
    };

    c.edit = async () => {
      source.replaceChildren(_el('p', null, 'Opening…'));
      let got;
      try {
        got = await _ask(`/api/mcp/scaffold/${encodeURIComponent(name)}`);
      } catch (err) {
        source.replaceChildren(_el('p', null, String((err && err.message) || err)));
        return;
      }
      const id = _id('source');
      const label = _el('label', null, `${name}/server.py — section 2 is where your code goes`);
      label.setAttribute('for', id);
      label.style.cssText = 'font-size:11px;opacity:0.75;display:block;margin-top:6px;';
      const area = _el('textarea', 'settings-input mcp-build-code');
      area.id = id;
      area.spellcheck = false;
      area.rows = 18;
      area.value = String(got.source || '');
      area.style.cssText = 'width:100%;box-sizing:border-box;font-family:monospace;font-size:11px;'
        + 'resize:vertical;margin-top:3px;';
      const row = _el('div');
      row.style.cssText = 'display:flex;gap:8px;align-items:center;margin-top:4px;';
      const save = _button('Save and check', 'admin-btn-sm mcp-build-save');
      const cancel = _button('Close the code', 'admin-btn-sm mcp-build-code-close');
      const msg = _el('span', 'mcp-build-save-msg');
      msg.setAttribute('role', 'status');
      msg.style.cssText = 'font-size:11px;';
      row.appendChild(save);
      row.appendChild(cancel);
      row.appendChild(msg);
      source.replaceChildren(label, area, row);
      save.addEventListener('click', async (event) => {
        if (event && event.preventDefault) event.preventDefault();
        save.disabled = true;
        msg.textContent = 'Saving…';
        try {
          await _ask(`/api/mcp/scaffold/${encodeURIComponent(name)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source: area.value }),
          });
          msg.textContent = 'Saved.';
          await c.check();
        } catch (err) {
          msg.textContent = `Not saved — ${String((err && err.message) || err)}`;
        } finally {
          save.disabled = false;
        }
      });
      cancel.addEventListener('click', (event) => {
        if (event && event.preventDefault) event.preventDefault();
        source.replaceChildren();
      });
      area.focus && area.focus();
    };

    c.register = async () => {
      register.replaceChildren(_el('p', null, 'Getting the fields…'));
      let got;
      try {
        got = await _ask(`/api/mcp/scaffold/${encodeURIComponent(name)}`);
      } catch (err) {
        register.replaceChildren(_el('p', null, String((err && err.message) || err)));
        return;
      }
      const note = _el('p', 'mcp-build-runs-as', RUNS_AS_AUTHOR);
      note.style.cssText = _NOTE + 'opacity:0.8;';
      if (isAdmin && typeof onRegister === 'function') {
        register.replaceChildren(note);
        onRegister(got.registration);
        return;
      }
      const lead = _el('p', 'mcp-build-admin-only', 'Only an admin registers a server. Send them these fields:');
      lead.style.cssText = _NOTE + 'font-weight:600;';
      const pre = _el('pre', 'mcp-build-fields', registrationText(got.registration));
      pre.style.cssText = _PRE;
      register.replaceChildren(lead, pre, note);
    };

    checkBtn.addEventListener('click', (e) => { if (e && e.preventDefault) e.preventDefault(); c.check(); });
    editBtn.addEventListener('click', (e) => { if (e && e.preventDefault) e.preventDefault(); c.edit(); });
    regBtn.addEventListener('click', (e) => { if (e && e.preventDefault) e.preventDefault(); c.register(); });
    c.paintState(entry.checked);
    if (Array.isArray(entry.tools) && entry.tools.length && entry.checked !== 'broken') {
      said.textContent = `Last check: offers ${entry.tools.join(', ')}. Check again to try them.`;
    }
    cards.set(name, c);
    return c;
  }

  async function refresh() {
    let listed;
    try {
      listed = await _ask('/api/mcp/scaffold');
    } catch (err) {
      listed = { servers: [], workstation: { available: false, why: String((err && err.message) || err) } };
    }
    setAvailable(listed.workstation);
    cards.clear();
    list.replaceChildren();
    const servers = Array.isArray(listed.servers) ? listed.servers : [];
    if (!servers.length) {
      const none = _el('p', 'mcp-build-none', 'None yet.');
      none.style.cssText = _NOTE + 'opacity:0.6;';
      list.appendChild(none);
    }
    for (const entry of servers) list.appendChild(card(entry).box);
    return listed;
  }

  async function build() {
    const name = String(nameIn.value || '').trim();
    const tool = String(toolIn.value || '').trim();
    make.disabled = true;
    freshMsg.textContent = 'Making it in your workstation…';
    freshMsg.style.color = '';
    try {
      const made = await _post('/api/mcp/scaffold', {
        name, tools: tool ? [tool] : [], description: String(descIn.value || '').trim(),
      });
      await refresh();
      const c = cards.get(made.name);
      if (c) {
        c.paintCheck(made.check);
        c.paintState(made.check && made.check.started ? 'works' : 'broken');
      }
      freshMsg.textContent = describeCheck(made.check);
      freshMsg.style.color = made.check && made.check.started ? 'var(--green, #50fa7b)' : 'var(--red)';
      nameIn.value = '';
      toolIn.value = '';
      descIn.value = '';
      return made;
    } catch (err) {
      freshMsg.textContent = String((err && err.message) || err);
      freshMsg.style.color = 'var(--red)';
      return null;
    } finally {
      make.disabled = !!why.textContent;
    }
  }

  make.addEventListener('click', (e) => { if (e && e.preventDefault) e.preventDefault(); build(); });
  close.addEventListener('click', (e) => {
    if (e && e.preventDefault) e.preventDefault();
    if (typeof onClose === 'function') onClose();
  });
  await refresh();
  return { element: panel, refresh, build, cards };
}

export default { mountToolTry, mountMcpBuildDoor, mountMcpBuild, describeTryResult, describeCheck, registrationText };
