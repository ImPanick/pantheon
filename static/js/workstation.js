// SPDX-License-Identifier: AGPL-3.0-or-later
//
// `P20-02`. The Workstation panel (`D-2026-09-30-03`).
//
// Two cards, two audiences. The first is for anyone signed in and says what the
// server says: is it on, may I use it, does it answer right now and what it
// said, my account and whether my home was there — and, for a person who may
// use it, *Reset my workstation*, behind a confirmation. The second is the
// admin's settings, and it is drawn only from a status answer that carries
// `settings`; the server decides who gets one (`routes/workstation_routes.py`).
//
// **Every rule lives in Python.** Which state the workstation is in, the
// sentence for it, which layer the address and the token came from, and what a
// valid address looks like are all answered by `src/workstation_access.py`; this
// file puts them on the screen. The choices in the two selects come from the
// protocol through the same answer (`settings.backends`, `settings.network_modes`)
// so a mode the protocol adds is offered without an edit here — only its words
// are written below, and a value with no words is shown as itself.
//
// **The token is never read back.** The status answer does not carry it — only
// `token_present` and `token_source` — and the field it can be pasted into is
// cleared after every save, which is `netagent`'s rule in `networks.js` for the
// same reason: re-populating a secret field from a GET is how a masked value is
// written back over the real one.

import uiModule from './ui.js';
import { invalidateSettings } from './appConfig.js';

const $ = (id) => document.getElementById(id);

// Words for the protocol's values. Keyed by value; the values themselves come
// from the server.
const BACKEND_WORDS = {
  container: {
    label: 'Container beside Pantheon',
    says: 'An Ubuntu container beside Pantheon, started by the workstation overlay. '
      + 'People are kept apart by Unix accounts inside it.',
  },
  vm: {
    label: 'Virtual machine',
    says: 'An Ubuntu virtual machine — a stronger wall between people than accounts in one container.',
  },
  remote: {
    label: 'Another machine',
    says: 'Another machine running the workstation daemon, at the address above.',
  },
};

// `B981`. What `sudo` reaches depends on the kind of machine. In the container
// people are Unix accounts in one machine, so root in it reads every home — the
// sentence the page ships with beside the switch (`index.html`, `#ws-sudo-why`),
// said there once and kept for any kind without words of its own. On the VM
// backend each person has a machine of their own, and root in one found no trace
// of another's home (measured in `P20-07`). Another machine is wherever the
// daemon runs, and root there is root there. Keyed by `machineKind`.
const SUDO_WORDS = {
  vm: 'With sudo on, an agent can install software in its own person’s machine. Other '
    + 'people’s machines are separate: it cannot reach their homes.',
  remote: 'With sudo on, an agent can install software on that machine — and can read other '
    + 'people’s workstation homes and anything else on it.',
};

const NETWORK_WORDS = {
  full: {
    label: 'Internet and local network',
    says: 'The internet and your local network. Something an agent reads could steer it '
      + 'to devices on your LAN.',
  },
  internet: {
    label: 'Internet only',
    says: 'The internet, but not your local network.',
  },
  none: {
    label: 'No network',
    says: 'No network at all. Installing software from the internet will fail.',
  },
};

// `P20-06`. Said beside the network mode: whether the choice is in force, who
// holds it, and whether an agent using sudo can lift it — one sentence per state
// the server works out (`workstation_access.network_view`), never a claim the
// system does not keep. `{held}` is the mode actually in force.
const NETWORK_STATE_WORDS = {
  unrestricted: '',
  enforced: 'Enforced outside the workstation, so it holds even for an agent using sudo.',
  enforced_sudo_off: 'Enforced for workstation accounts. It holds while sudo is off.',
  liftable: 'Enforced only while sudo is off — and sudo is on, so an agent can lift it.',
  needs_recreate: 'Not enforced: this workstation was started without its network gate. '
    + 'Recreate it with the current workstation overlay (docker compose up -d) to enforce it.',
  not_enforced: 'Not enforced: this workstation cannot hold a network mode, so it has '
    + 'whatever network its machine gives it.',
  pending: 'Not in force yet: the workstation is still held at “{held}”.',
  unknown: 'Whether it is in force is checked when the workstation answers.',
};

/** The sentence for one `network_view` answer, or '' when there is nothing to
 *  add to the mode's own words. */
function networkStateSentence(view) {
  if (!view || !view.state) return NETWORK_STATE_WORDS.unknown;
  const words = NETWORK_STATE_WORDS[view.state];
  if (words === undefined) return '';
  const held = NETWORK_WORDS[view.in_force] ? NETWORK_WORDS[view.in_force].label : view.in_force;
  return words.replace('{held}', held || '');
}

const URL_SOURCE_WORDS = {
  setting: 'set here',
  environment: 'set by the workstation overlay (PANTHEON_WORKSTATION_URL)',
};

const TOKEN_SOURCE_WORDS = {
  setting: 'Present — set here.',
  environment: 'Present — from PANTHEON_WORKSTATION_TOKEN.',
  pairing: 'Present — read from the pairing volume the workstation shares with Pantheon.',
  // `COPY-U-43` (P23-03): one line each, the same facts.
  none: 'None yet. Read from the pairing volume when the workstation starts. For a remote '
    + 'one, set PANTHEON_WORKSTATION_TOKEN on both sides or paste it.',
};

// `B980`. Where the pinned certificate came from, said beside its fingerprint.
const PIN_SOURCE_WORDS = {
  setting: 'set here',
  environment: 'from PANTHEON_WORKSTATION_CERT_SHA256',
};
const PIN_NONE_WORDS = 'None: an https:// address is checked against the system\'s trusted '
  + 'certificates. For one workstation/install.py set up, paste the fingerprint it printed.';

const HOME_WORDS = {
  kept: 'kept from before',
  made_now: 'made just now',
};

// `B959` (`P20-07`): the status looks without making, so a person who has never
// used the workstation has no home yet — and is told when one appears.
const HOME_NONE_WORDS = 'no home yet — it is made the first time you or your agent work there';

// `P20-07`: what the machine under a workstation is, from the daemon's own
// look (`health.machine`). Said only where it changes what a person expects.
const ACCEL_WORDS = {
  kvm: 'hardware-accelerated (KVM)',
  tcg: 'emulated without KVM — slow',
};
const IMAGE_WORDS = {
  preparing: 'preparing the machine image (first start)',
  failed: 'the machine image could not be prepared',
};

// `B979`: on the VM backend, a machine nobody has used for a while is powered
// off (its disk kept) and the host caps how many run. Said beside the daemon's
// facts, and to a person whose own machine is off.
const YOUR_MACHINE_WORDS = {
  stopped: 'your machine is off — it starts when you or your agent next work there',
};

function minutes(seconds) {
  const n = Math.max(1, Math.round(seconds / 60));
  return n === 1 ? '1 minute' : `${n} minutes`;
}

/** `health.machines` as words: how many run, of how many, and when one stops. */
function describeMachines(machines) {
  if (!machines || typeof machines.running !== 'number') return [];
  const parts = [];
  const what = machines.running === 1 && typeof machines.max_running !== 'number'
    ? 'machine' : 'machines';
  parts.push(typeof machines.max_running === 'number'
    ? `${machines.running} of ${machines.max_running} ${what} running`
    : `${machines.running} ${what} running`);
  if (typeof machines.idle_stop_s === 'number') {
    parts.push(`a machine stops after ${minutes(machines.idle_stop_s)} unused`);
  }
  return parts;
}

let _status = null;
let _wired = false;

function show(node, on) {
  if (node) node.hidden = !on;
}

function say(id, text, ok) {
  const out = $(id);
  if (!out) return;
  out.textContent = text || '';
  out.classList.toggle('networks-probe-hit', !!ok);
  out.hidden = !text;
}

/** The daemon's own answer as one line: what it is and how it is set. */
function describeDaemon(daemon) {
  if (!daemon) return '';
  const parts = [];
  if (daemon.backend) {
    const words = BACKEND_WORDS[daemon.backend];
    parts.push(words ? words.label : daemon.backend);
  }
  if (daemon.protocol !== undefined) parts.push(`protocol ${daemon.protocol}`);
  if (daemon.version) parts.push(`daemon ${daemon.version}`);
  if (typeof daemon.sudo === 'boolean') parts.push(daemon.sudo ? 'sudo on' : 'sudo off');
  if (daemon.network) {
    const words = NETWORK_WORDS[daemon.network];
    parts.push(`network: ${words ? words.label.toLowerCase() : daemon.network}`);
  }
  if (Array.isArray(daemon.screen) && daemon.screen.length === 2) {
    parts.push(`screen ${daemon.screen[0]}×${daemon.screen[1]}`);
  }
  if (typeof daemon.accounts === 'number') {
    parts.push(daemon.accounts === 1 ? '1 account' : `${daemon.accounts} accounts`);
  }
  const machine = daemon.machine;
  if (machine && typeof machine === 'object') {
    if (ACCEL_WORDS[machine.accel]) parts.push(ACCEL_WORDS[machine.accel]);
    if (IMAGE_WORDS[machine.image]) parts.push(IMAGE_WORDS[machine.image]);
  }
  parts.push(...describeMachines(daemon.machines));  // `B979`
  return parts.join(' · ');
}

function describeYou(you) {
  if (!you || !you.account) return '';
  let line = `Your account: ${you.account}`;
  if (you.home_state === 'none') return `${line} · ${HOME_NONE_WORDS}`;
  if (you.home) {
    const when = HOME_WORDS[you.home_state];
    line += ` · home ${you.home}${when ? ` (${when})` : ''}`;
  }
  if (YOUR_MACHINE_WORDS[you.machine]) line += ` · ${YOUR_MACHINE_WORDS[you.machine]}`;  // `B979`
  return line;
}

/** The first card, from one status answer. */
function render(status) {
  _status = status;
  const box = $('ws-status');
  if (box) box.dataset.state = status.state || 'unknown';
  const text = $('ws-status-text');
  if (text) text.textContent = status.sentence || '';

  // What the daemon said, when it answered. When a probe failed and the
  // headline is not already that failure (an admin's check of a workstation
  // that is switched off), the failure goes here instead, in its own words.
  const facts = $('ws-facts');
  if (facts) {
    let line = describeDaemon(status.daemon);
    if (!line && status.error && status.state !== 'down') line = status.error.message || '';
    facts.textContent = line;
    show(facts, !!line);
  }

  const you = $('ws-you');
  if (you) {
    const line = describeYou(status.you);
    you.textContent = line;
    show(you, !!line);
  }

  show($('ws-check'), !!status.is_admin);
  // Only for a person who may use it and only while it answers: a reset of a
  // workstation that is down would fail, and a button that cannot work is a
  // control left dangling (`Law 15`).
  show($('ws-reset'), !!status.may_use && status.state === 'up');
  // `P20-05`. The window onto the screen, on the same terms. It is a
  // `[data-open-workstation-screen]` door, answered by `workstationScreen.js`.
  show($('ws-open-screen'), !!status.may_use && status.state === 'up');

  show($('ws-admin'), !!status.settings);
}

/** One status answer, everywhere it goes: the first card, and for an admin
 *  the controls and the sentences under them. */
function apply(status) {
  render(status);
  if (status.settings) {
    fillSettings(status.settings);
    renderEffects(status.settings, status.daemon, status.network);
  }
  return status;
}

function fillSelect(select, values, words, current) {
  if (!select) return;
  select.textContent = '';
  for (const value of values || []) {
    const opt = document.createElement('option');
    opt.value = value;
    opt.textContent = words[value] ? words[value].label : value;
    if (value === current) opt.selected = true;
    select.appendChild(opt);
  }
  select.value = current;
}

/** The admin's controls, set to what is stored. The token field is never set. */
function fillSettings(settings) {
  if (!settings) return;
  if ($('ws-enabled')) $('ws-enabled').checked = !!settings.enabled;
  if ($('ws-sudo')) $('ws-sudo').checked = !!settings.sudo;
  if ($('ws-route-tools')) $('ws-route-tools').checked = !!settings.route_tools;
  if ($('ws-url')) $('ws-url').value = settings.url_setting || '';
  // `B980`: shown, unlike the token — a certificate's fingerprint is no secret.
  if ($('ws-tls-pin')) $('ws-tls-pin').value = settings.tls_pin_setting || '';
  fillSelect($('ws-backend'), settings.backends, BACKEND_WORDS, settings.backend);
  fillSelect($('ws-network'), settings.network_modes, NETWORK_WORDS, settings.network);
}

/** The sentences under the admin's controls — what each choice means now. */
function renderEffects(settings, daemon, network) {
  const url = $('ws-url-effect');
  if (url) {
    const where = URL_SOURCE_WORDS[settings.url_source];
    url.textContent = settings.url
      ? `In effect: ${settings.url} — ${where || settings.url_source}.`
      : 'No address yet. Filled in by the workstation overlay, or type one.';
  }
  const token = $('ws-token-effect');
  if (token) {
    token.textContent = TOKEN_SOURCE_WORDS[settings.token_present ? settings.token_source : 'none']
      || TOKEN_SOURCE_WORDS.none;
  }
  show($('ws-forget-token'), settings.token_source === 'setting');
  const pin = $('ws-tls-pin-effect');
  if (pin) {
    const where = PIN_SOURCE_WORDS[settings.tls_pin_source];
    pin.textContent = settings.tls_pin
      ? `Pinned: ${settings.tls_pin} — ${where || settings.tls_pin_source}.`
      : PIN_NONE_WORDS;
  }

  const backend = $('ws-backend-effect');
  if (backend) {
    const chosen = $('ws-backend') ? $('ws-backend').value || settings.backend : settings.backend;
    let line = BACKEND_WORDS[chosen] ? BACKEND_WORDS[chosen].says : '';
    // The daemon says what it is; when that is not what the setting says, the
    // admin is told rather than left to wonder which one is true.
    if (daemon && daemon.backend && daemon.backend !== chosen) {
      const theirs = BACKEND_WORDS[daemon.backend] ? BACKEND_WORDS[daemon.backend].label : daemon.backend;
      line += `${line ? ' ' : ''}The workstation that answered says it is: ${theirs.toLowerCase()}.`;
    }
    backend.textContent = line;
  }

  renderSudo(settings, daemon);
  renderRecreate(settings, daemon);

  const networkEffect = $('ws-network-effect');
  if (networkEffect) {
    const chosen = $('ws-network') ? $('ws-network').value || settings.network : settings.network;
    const words = NETWORK_WORDS[chosen];
    // The state is about the mode the server last pushed; a choice not yet
    // saved has no state of its own to report.
    const view = network && network.chosen === chosen ? network : null;
    // Full restricts nothing, so there is nothing to be in force until a
    // workstation says otherwise.
    const quiet = chosen === 'full' && (!view || view.state === 'unknown');
    const state = quiet ? '' : networkStateSentence(view);
    networkEffect.textContent = `${words ? words.says : chosen}${state ? ` ${state}` : ''}`;
  }
}

/**
 * `B956`. Beside `sudo`: turning it off applies from now on, and what gives a
 * clean system back. For the container, that is recreating it — every home
 * kept — with the command to copy, because Pantheon holds no Docker socket and
 * cannot run it. The command is the server's (`RECREATE_COMMAND`); the kind of
 * machine is what the daemon says it is, or the setting while it has not said.
 */
/** The kind of machine the workstation is: what the daemon that answered says
 *  it is (`health.backend`), else what the admin set while none has. One
 *  answer for every sentence that depends on it (`B956`, `B981`). */
function machineKind(settings, daemon) {
  return (daemon && daemon.backend) || (settings && settings.backend) || '';
}

/** `B981`. The sentence beside the `sudo` switch, for this kind of machine. The
 *  container's — and any kind's without words of its own, the cautious answer —
 *  is the one the page shipped with, kept the first time this runs. */
function renderSudo(settings, daemon) {
  const why = $('ws-sudo-why');
  if (!why) return;
  if (why.dataset.shipped === undefined) why.dataset.shipped = why.textContent;
  why.textContent = SUDO_WORDS[machineKind(settings, daemon)] || why.dataset.shipped;
}

function renderRecreate(settings, daemon) {
  const box = $('ws-recreate');
  if (!box) return;
  const kind = machineKind(settings, daemon);
  const command = typeof settings.recreate_command === 'string' ? settings.recreate_command : '';
  const container = kind === 'container' && !!command;
  const why = $('ws-recreate-why');
  if (why) {
    why.textContent = container
      ? 'Recreate the workstation for a clean system — every home and account is kept. '
        + 'Pantheon cannot do this itself; run this where you start Pantheon:'
      : 'For a clean system, rebuild that machine: Pantheon cannot reach past the workstation '
        + 'daemon to do it.';
  }
  const cmd = $('ws-recreate-cmd');
  if (cmd) cmd.textContent = container ? command : '';
  show($('ws-recreate-row'), container);
  show(box, true);
}

async function readError(res) {
  let detail = `Failed (${res.status})`;
  try {
    const body = await res.json();
    if (body && body.detail) detail = String(body.detail);
  } catch (_) { /* a non-JSON error body is still an error; keep the status */ }
  return detail;
}

async function fetchStatus(method) {
  const url = method === 'POST' ? '/api/workstation/check' : '/api/workstation/status';
  const res = await fetch(url, { method, credentials: 'same-origin' });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

function renderUnreachable(e) {
  render({
    state: 'unknown',
    sentence: `Pantheon could not say how the workstation is: ${String((e && e.message) || e)}`,
    may_use: false,
    is_admin: !!(_status && _status.is_admin),
  });
}

/** Ask again, as whoever is looking. */
export async function load() {
  try {
    return apply(await fetchStatus('GET'));
  } catch (e) {
    renderUnreachable(e);
    return null;
  }
}

/** The admin's *Check now*: asks even while it is switched off. */
async function check() {
  say('ws-result', '', false);
  try {
    return apply(await fetchStatus('POST'));
  } catch (e) {
    renderUnreachable(e);
    return null;
  }
}

/** One settings write. A refusal is shown in the server's words and the
 *  controls are put back to what is stored, so the page never shows a value
 *  the server refused. */
async function save(body) {
  const res = await fetch('/api/auth/settings', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    say('ws-admin-result', await readError(res), false);
    await load();
    return false;
  }
  // The shared settings snapshot is now a lie; anything reading it next would
  // get the pre-save value.
  invalidateSettings();
  say('ws-admin-result', 'Saved.', true);
  // A check rather than a status read: it is what pushes a changed `sudo` to
  // the daemon, and it answers for a workstation that was just switched off.
  await check();
  return true;
}

async function saveAddress() {
  const body = { workstation_url: ($('ws-url')?.value || '').trim() };
  // An empty token box means "leave it alone", not "clear it" — the same rule
  // as the network agent's. Forgetting a token is its own button.
  const token = ($('ws-token')?.value || '').trim();
  if (token) body.workstation_token = token;
  // `B980`: the pin only when it was changed, so saving an address never
  // rewrites one by accident; emptied, it goes back to the environment's.
  const pin = ($('ws-tls-pin')?.value || '').trim();
  if ($('ws-tls-pin') && pin !== ((_status && _status.settings && _status.settings.tls_pin_setting) || '')) {
    body.workstation_tls_pin = pin;
  }
  const ok = await save(body);
  if ($('ws-token')) $('ws-token').value = '';
  return ok;
}

/**
 * The confirmation and the reset, shared by this panel and the workstation
 * screen window (`P20-05`) — one sentence for what is erased, one request.
 * Resolves `null` when the person said no, else `{ ok, message }` with the
 * server's sentence either way.
 */
export async function confirmAndResetMine() {
  const message = 'Everything in your workstation home is erased — files, settings, anything '
    + 'installed into it — and it starts clean. Nobody else\'s home is touched.';
  let ok = false;
  try {
    ok = uiModule && uiModule.styledConfirm
      ? await uiModule.styledConfirm(message, {
        title: 'Reset your workstation?', confirmText: 'Reset', danger: true,
      })
      : window.confirm(`Reset your workstation?\n\n${message}`);
  } catch (_) { ok = false; }
  if (!ok) return null;
  const res = await fetch('/api/workstation/reset', { method: 'POST', credentials: 'same-origin' });
  if (!res.ok) return { ok: false, message: await readError(res) };
  const body = await res.json().catch(() => ({}));
  return { ok: true, message: body.sentence || 'Your workstation home is back to a clean start.' };
}

async function resetMine() {
  const answer = await confirmAndResetMine();
  if (!answer) return false;
  say('ws-result', answer.message, answer.ok);
  if (!answer.ok) return false;
  await load();
  return true;
}

function wire() {
  if (_wired) return;
  _wired = true;
  $('ws-check')?.addEventListener('click', () => { check(); });
  $('ws-reset')?.addEventListener('click', () => { resetMine(); });
  // Each switch and select saves the moment it changes, like the email
  // approval switch does; the two text fields wait for their button, because a
  // half-typed address is not a choice.
  const onChange = (id, key, read) => {
    const node = $(id);
    node?.addEventListener('change', () => { save({ [key]: read(node) }); });
  };
  onChange('ws-enabled', 'workstation_enabled', (n) => !!n.checked);
  onChange('ws-sudo', 'workstation_sudo', (n) => !!n.checked);
  onChange('ws-route-tools', 'workstation_route_tools', (n) => !!n.checked);
  onChange('ws-backend', 'workstation_backend', (n) => n.value);
  onChange('ws-network', 'workstation_network', (n) => n.value);
  $('ws-save-address')?.addEventListener('click', () => { saveAddress(); });
  $('ws-recreate-copy')?.addEventListener('click', () => {
    const text = $('ws-recreate-cmd')?.textContent || '';
    if (text && uiModule && uiModule.copyToClipboard) uiModule.copyToClipboard(text);
  });
  $('ws-forget-token')?.addEventListener('click', () => { save({ workstation_token: '' }); });
}

export async function open() {
  wire();
  return load();
}

export const _test = {
  describeMachines,  // `B979`
  describeDaemon, describeYou, render, apply, fillSettings, renderEffects, networkStateSentence,
  renderRecreate, renderSudo, machineKind,
};
