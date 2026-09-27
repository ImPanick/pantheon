// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/settings/mcpPresets.js — the MCP preset catalogue, and the picker
// that offers it inside Settings → Integrations → + → MCP Tool Server.
//
// `P8-45`, decided 2026-09-27 as "inside the MCP form" (`D-2026-09-27-01`).
//
// **What was there.** Fifteen presets — fourteen with a setup walkthrough —
// sat in `static/js/admin.js` (`MCP_PRESETS`, 1854-1920 when re-measured by a
// balanced-bracket parse), feeding an admin MCP form whose two entry points,
// `initMcpForm` and `loadMcpServers`, return on DOM ids (`adm-mcpCommand`,
// `adm-mcpList`) that no template in this tree renders. So the one place a
// person could start from "I want GitHub" instead of "I need a command line"
// had not been reachable, and the form everybody uses — the one `P8-46`
// rebuilt — asked for a Command and Arguments a person must already know.
//
// **What this is.** The catalogue's one home (`Law 7`): `admin.js` imports it
// from here rather than keeping a copy, and the picker below fills the EXISTING
// add-server form — Command, Arguments, Environment — and shows the preset's
// setup steps in place. It adds no route to save through and no second form
// (`Law 14`): the person reviews what was filled in and presses the same Save.
//
// Three rules the catalogue itself keeps:
//
//   * **A value only the person has is left empty and marked, never faked.**
//     An environment variable whose preset value is `""` — a token, a password,
//     a client secret — reaches the form as an empty box marked as needed, and
//     Save refuses while it is still empty. `postgresql://user:pass@localhost/db`
//     used to ship as an argument that looked filled in; it is an empty,
//     marked argument now.
//   * **Nothing is fetched to show a preset** (`Law 16`). The catalogue is data
//     in this file. What reaches out is what the person later runs — `npx`
//     downloads a package from the npm registry the first time it starts, and
//     the picker says so before they save.
//   * **Whether this install will run it is asked, not guessed.** Choosing a
//     preset asks `POST /api/mcp/check`, which runs the one rule
//     (`_validate_mcp_command`, the rule `P8-47`'s `refusal_on_the_agent_path`
//     already asks) and looks for the launcher on this machine. No copy of the
//     rule lives here.

/**
 * The catalogue. Moved verbatim from `static/js/admin.js` except where the
 * header above says otherwise: the Postgres argument that faked a connection
 * string is now an empty, marked argument, and the walkthroughs name the boxes
 * and the button of the form they are shown in (`Save`, the variable names)
 * rather than the unreachable admin form's (`Add Server`, "Github Personal
 * Access Token").
 *
 * Shape: `{name, command, args, env, help?, needs?, oauthFile?, oauth?,
 * providerDropdown?}`. `env` values of `""` are values the person supplies.
 * `needs.args` maps an argument's index to what goes in it, for the one kind
 * of value that cannot be spotted by being empty in `env`.
 */
export const MCP_PRESETS = [
  { name: "Gmail",           command: "npx", args: ["-y", "@gongrzhe/server-gmail-autoauth-mcp"],      env: { GOOGLE_CLIENT_ID: "", GOOGLE_CLIENT_SECRET: "" },
    oauthFile: { dir: "gmail", filename: "gcp-oauth.keys.json" },
    oauth: {
      provider: "google",
      keys_file: "gmail/gcp-oauth.keys.json",
      token_file: "gmail/credentials.json",
      scopes: ["https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/gmail.settings.basic"],
    },
    help: `Setup:
1. Go to console.cloud.google.com > create or select a project
2. APIs & Services > Library > search "Gmail API" > Enable
3. APIs & Services > OAuth consent screen > set up (External is fine)
4. Under Audience, add your Gmail address as a test user
5. APIs & Services > Credentials > + Create Credentials > OAuth Client ID
6. Application type: Desktop App > Create
7. Put the Client ID in GOOGLE_CLIENT_ID and the Client Secret in GOOGLE_CLIENT_SECRET below
8. Press Save, then press Authorize on the server's page
9. Sign in with Google; if the page it sends you back to fails to load, copy that page's address and paste it back` },
  { name: "Email (IMAP/SMTP)", command: "npx", args: ["-y", "@codefuturist/email-mcp", "stdio"],        env: { MCP_EMAIL_ADDRESS: "", MCP_EMAIL_PASSWORD: "", MCP_EMAIL_IMAP_HOST: "", MCP_EMAIL_SMTP_HOST: "" },
    providerDropdown: {
      label: "Provider",
      targets: { MCP_EMAIL_IMAP_HOST: "imap", MCP_EMAIL_SMTP_HOST: "smtp" },
      options: [
        { name: "Migadu",        imap: "imap.migadu.com",     smtp: "smtp.migadu.com" },
        { name: "Fastmail",      imap: "imap.fastmail.com",   smtp: "smtp.fastmail.com" },
        { name: "Proton Bridge", imap: "127.0.0.1",           smtp: "127.0.0.1" },
        { name: "Outlook/Hotmail", imap: "outlook.office365.com", smtp: "smtp.office365.com" },
        { name: "Yahoo",         imap: "imap.mail.yahoo.com", smtp: "smtp.mail.yahoo.com" },
        { name: "iCloud",        imap: "imap.mail.me.com",    smtp: "smtp.mail.me.com" },
        { name: "Zoho",          imap: "imap.zoho.com",       smtp: "smtp.zoho.com" },
        { name: "Custom",        imap: "",                    smtp: "" },
      ],
    },
    help: "Works with any IMAP/SMTP email provider.\n1. Pick your provider above (or Custom, and fill in both hosts yourself)\n2. Put your address in MCP_EMAIL_ADDRESS and your password (or app password) in MCP_EMAIL_PASSWORD\n3. Press Save" },
  { name: "CalDAV (Radicale/Nextcloud)", command: "npx", args: ["-y", "caldav-mcp"],                     env: { CALDAV_BASE_URL: "http://localhost:5232", CALDAV_USERNAME: "", CALDAV_PASSWORD: "" },
    help: "Works with any CalDAV server (Radicale, Nextcloud, etc.).\n1. Set CALDAV_BASE_URL to your CalDAV server (Radicale's own default is http://localhost:5232)\n2. Put your username and password in CALDAV_USERNAME and CALDAV_PASSWORD\n3. Press Save" },
  { name: "Google Calendar", command: "npx", args: ["-y", "@cocal/google-calendar-mcp"],                 env: { GOOGLE_OAUTH_CREDENTIALS: "" },
    help: `Setup:
1. Go to console.cloud.google.com > create/select a project
2. APIs & Services > Library > enable Google Calendar API
3. APIs & Services > Credentials > + Create Credentials > OAuth Client ID
4. Application type: Desktop App > Create
5. Click "Download JSON" on the credential you just created
6. Set GOOGLE_OAUTH_CREDENTIALS to the full path of that JSON file on the machine Pantheon runs on` },
  { name: "Google Drive",    command: "npx", args: ["-y", "@modelcontextprotocol/server-gdrive"],        env: {},
    help: "Google Drive signs in through the browser the first time it runs. Nothing to fill in here — press Save, then authorize when you are asked to." },
  { name: "GitHub",          command: "npx", args: ["-y", "@modelcontextprotocol/server-github"],        env: { GITHUB_PERSONAL_ACCESS_TOKEN: "" },
    help: "1. Go to github.com > Settings > Developer Settings > Personal Access Tokens > Fine-grained tokens\n2. Generate a new token with the repo permissions you need\n3. Paste it as the value of GITHUB_PERSONAL_ACCESS_TOKEN below" },
  { name: "Slack",           command: "npx", args: ["-y", "@modelcontextprotocol/server-slack"],         env: { SLACK_BOT_TOKEN: "", SLACK_TEAM_ID: "" },
    help: "1. Go to api.slack.com/apps > Create New App > From Scratch\n2. Add Bot Token Scopes (channels:read, chat:write, etc.)\n3. Install to workspace, copy the Bot User OAuth Token (xoxb-...) into SLACK_BOT_TOKEN\n4. Put your Team ID in SLACK_TEAM_ID — it is in your workspace URL or Slack admin settings" },
  { name: "Notion",          command: "npx", args: ["-y", "@notionhq/notion-mcp-server"],               env: { OPENAPI_MCP_HEADERS: "" },
    help: "1. Go to notion.so/my-integrations\n2. Create a new integration\n3. Copy the Internal Integration Secret\n4. Share the Notion pages/databases you want accessible with the integration\n5. Set OPENAPI_MCP_HEADERS to:\n   {\"Authorization\": \"Bearer YOUR_SECRET\", \"Notion-Version\": \"2022-06-28\"}" },
  { name: "Linear",          command: "npx", args: ["-y", "mcp-linear"],                                env: { LINEAR_API_KEY: "" },
    help: "1. Go to linear.app > Settings > API\n2. Create a Personal API Key\n3. Paste it as the value of LINEAR_API_KEY below" },
  { name: "Brave Search",    command: "npx", args: ["-y", "@modelcontextprotocol/server-brave-search"], env: { BRAVE_API_KEY: "" },
    help: "1. Go to brave.com/search/api\n2. Sign up for a free plan (2000 queries/month)\n3. Paste your API key as the value of BRAVE_API_KEY below" },
  { name: "Browser (Playwright)", command: "npx", args: ["-y", "@playwright/mcp@latest", "--headless"],  env: {},
    help: "Browser automation via Playwright. The AI can navigate pages, click, fill forms, and read content.\nRuns headless by default. Remove the --headless argument to see the browser window.\nFirst run installs Chromium automatically." },
  { name: "Filesystem",      command: "npx", args: ["-y", "@modelcontextprotocol/server-filesystem", "/home"], env: {},
    help: "The last argument is the folder the server may read and write. Change it to the one you mean." },
  { name: "Memory",          command: "npx", args: ["-y", "@modelcontextprotocol/server-memory"],        env: {} },
  { name: "Postgres",        command: "npx", args: ["-y", "@modelcontextprotocol/server-postgres", ""], env: {},
    needs: { args: { 2: "postgresql://USER:PASSWORD@HOST:5432/DATABASE" } },
    help: "Put your database's connection URL in the empty argument box, e.g. postgresql://USER:PASSWORD@HOST:5432/DATABASE.\nThis package takes it as an argument, so it shows in the machine's process list." },
  { name: "Todoist",         command: "npx", args: ["-y", "todoist-mcp-server"],                         env: { TODOIST_API_TOKEN: "" },
    help: "1. Go to todoist.com > Settings > Integrations > Developer\n2. Copy your API token into TODOIST_API_TOKEN below" },
];

/** What a marked box says while it is still empty. */
export const NEEDS_YOUR_VALUE = 'Yours to fill in — see Setup above';

/**
 * Which of a preset's values only the person has.
 *
 * `{args: {index: hint}, env: {KEY: hint}}`. An environment variable is needed
 * when the preset ships it empty; an argument only when `needs.args` says so,
 * because an empty argument cannot otherwise be told from a missing one.
 */
export function presetNeeds(preset) {
  const p = preset && typeof preset === 'object' ? preset : {};
  const env = {};
  for (const [key, value] of Object.entries(p.env || {})) {
    if (value === '') env[key] = NEEDS_YOUR_VALUE;
  }
  const args = {};
  const declared = (p.needs && p.needs.args) || {};
  for (const [index, hint] of Object.entries(declared)) args[Number(index)] = String(hint);
  return { args, env };
}

/** Everything the form is filled with, as plain data. Copies, never aliases. */
export function presetFields(preset) {
  const p = preset && typeof preset === 'object' ? preset : {};
  return {
    name: String(p.name || ''),
    transport: 'stdio',
    command: String(p.command || ''),
    args: Array.isArray(p.args) ? p.args.map(String) : [],
    env: { ...(p.env || {}) },
    needs: presetNeeds(p),
  };
}

/**
 * The extra fields `POST /api/mcp/servers` takes for a preset that signs in
 * with Google: `oauth_file` (the client id and secret, which `add_server`
 * writes to a keys file under the MCP OAuth directory and then removes from the
 * stored environment) and `oauth_config` (what the Authorize flow runs from).
 * Ported from the unreachable admin form's save handler; empty for every other
 * preset, and for no preset at all.
 */
export function presetSaveExtras(preset, env) {
  const p = preset && typeof preset === 'object' ? preset : null;
  const out = {};
  if (!p) return out;
  const values = env && typeof env === 'object' ? env : {};
  if (p.oauthFile) {
    out.oauth_file = JSON.stringify({
      dir: p.oauthFile.dir,
      filename: p.oauthFile.filename,
      client_id: values.GOOGLE_CLIENT_ID || '',
      client_secret: values.GOOGLE_CLIENT_SECRET || '',
    });
  }
  if (p.oauth) out.oauth_config = JSON.stringify(p.oauth);
  return out;
}

/**
 * The sentences for what `POST /api/mcp/check` said about one command.
 *
 * Reads two verdicts and derives neither: `launcher.verdict` (`found` or
 * `missing` — can this machine start it at all) and `assistant.verdict`
 * (`accepted` or `refused` — would `manage_mcp` register it, with the rule's
 * own `reason`). Returns `[{key, tone, text}]`, tone `ok`, `note` or `bad`.
 */
export function describeLaunchCheck(result) {
  const data = result && typeof result === 'object' ? result : {};
  const command = String(data.command || '').trim() || 'this command';
  const lines = [];
  const launcher = data.launcher && data.launcher.verdict;
  if (launcher === 'missing') {
    lines.push({
      key: 'launcher', tone: 'bad',
      text: `Pantheon can’t find ${command} on this machine, so this server won’t start here. Install it first.`,
    });
  } else if (launcher === 'found') {
    lines.push({ key: 'launcher', tone: 'ok', text: `${command} is installed on this machine.` });
  }
  const assistant = data.assistant && typeof data.assistant === 'object' ? data.assistant : null;
  if (assistant && assistant.verdict === 'refused') {
    const reason = String(assistant.reason || '').trim();
    lines.push({
      key: 'assistant', tone: 'note',
      text: 'Only an administrator can add this, from this form. Asked to, the assistant refuses'
        + (reason ? `: “${reason}”` : '.'),
    });
  } else if (assistant && assistant.verdict === 'accepted') {
    lines.push({ key: 'assistant', tone: 'ok', text: 'The assistant could add this one for you too.' });
  }
  return lines;
}

const TONES = { ok: 'var(--green)', note: 'var(--fg)', bad: 'var(--red)' };

function elem(tag, props) {
  const node = document.createElement(tag);
  Object.assign(node, props || {});
  return node;
}

function fire(node, type) {
  if (node && typeof node.dispatchEvent === 'function') {
    node.dispatchEvent(new Event(type, { bubbles: true }));
  }
}

/**
 * The "Start from" row of the add-server form.
 *
 * `options.fields` holds the form's own controls: `name`, `transport` and
 * `command` inputs, and the `args` and `env` editors `createMcpFieldEditor`
 * built. Choosing a preset fills them and says, in place, what the person has
 * to supply, how to get it, and what this install makes of the command.
 * Choosing "Nothing" stops the preset's extras and leaves every field as it
 * is — nothing typed is cleared by the picker.
 *
 * `options.checkLaunch(registration)` returns a promise of the check route's
 * answer; without it the picker draws no verdict and claims none.
 *
 * Returns `{element, active(), choose(index), saveExtras(env)}`.
 */
export function createMcpPresetPicker(options) {
  const opts = options && typeof options === 'object' ? options : {};
  const fields = opts.fields && typeof opts.fields === 'object' ? opts.fields : {};
  const checkLaunch = typeof opts.checkLaunch === 'function' ? opts.checkLaunch : null;
  const catalogue = Array.isArray(opts.presets) ? opts.presets : MCP_PRESETS;

  const element = elem('div', { className: 'mcp-preset' });
  element.setAttribute('data-mcp-preset', '');

  const row = elem('div', { className: 'settings-row' });
  const label = elem('label', { className: 'settings-label', textContent: 'Start from' });
  label.setAttribute('for', 'uf-mcp-preset');
  const select = elem('select', { className: 'settings-input' });
  select.id = 'uf-mcp-preset';
  select.setAttribute('data-mcp-preset-select', '');
  select.appendChild(elem('option', { value: '', textContent: 'Nothing — fill in the fields yourself' }));
  catalogue.forEach((preset, index) => {
    select.appendChild(elem('option', { value: String(index), textContent: preset.name }));
  });
  row.appendChild(label);
  row.appendChild(select);
  element.appendChild(row);

  const info = elem('div', { className: 'mcp-preset-info' });
  info.setAttribute('data-mcp-preset-info', '');
  info.style.cssText = 'font-size:11px;line-height:1.5;margin:4px 0 2px;padding:6px 8px;'
    + 'border:1px solid var(--border);border-radius:6px;';
  info.style.display = 'none';
  element.appendChild(info);

  let active = null;        // the chosen preset, or null
  let checkedCommand = null; // the command the verdict on screen is about
  let lastName = null;       // the name the picker last wrote, so a typed one survives
  let generation = 0;        // a slow answer for an earlier choice is dropped

  const verdict = elem('div', { className: 'mcp-preset-verdict' });
  verdict.setAttribute('data-mcp-preset-verdict', '');
  verdict.setAttribute('role', 'status');

  function line(text, extra) {
    const node = elem('div', { textContent: text });
    if (extra) node.style.cssText = extra;
    return node;
  }

  function paintVerdict(lines) {
    verdict.replaceChildren();
    for (const entry of lines) {
      const node = line(entry.text, `color:${TONES[entry.tone] || TONES.note};margin-top:3px;`
        + (entry.tone === 'bad' ? 'font-weight:600;' : ''));
      node.setAttribute('data-mcp-check', entry.key);
      node.setAttribute('data-mcp-check-tone', entry.tone);
      verdict.appendChild(node);
    }
  }

  function currentEnv() {
    const env = fields.env;
    if (!env || typeof env.peek !== 'function') return {};
    const value = env.peek();
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  }

  function renderInfo(preset, filled) {
    info.replaceChildren();
    info.appendChild(line('Filled in below. Nothing is added until you press Save.', 'opacity:0.75;'));

    if (preset.providerDropdown) {
      const pd = preset.providerDropdown;
      const providerRow = elem('div');
      providerRow.style.cssText = 'display:flex;gap:6px;align-items:center;margin-top:5px;';
      const providerLabel = elem('label', { textContent: pd.label || 'Provider' });
      providerLabel.setAttribute('for', 'uf-mcp-preset-provider');
      const provider = elem('select', { className: 'settings-input' });
      provider.id = 'uf-mcp-preset-provider';
      provider.setAttribute('data-mcp-preset-provider', '');
      // No provider is chosen for the person: a host filled in before they
      // said which one is the placeholder-that-looks-filled-in this module
      // exists to stop shipping.
      provider.appendChild(elem('option', { value: '', textContent: 'Choose yours…' }));
      pd.options.forEach((option, index) => {
        provider.appendChild(elem('option', { value: String(index), textContent: option.name }));
      });
      provider.addEventListener('change', () => {
        const option = pd.options[Number(provider.value)];
        if (!option || !fields.env || typeof fields.env.setValue !== 'function') return;
        // What the person already typed — the address, the password — stays.
        const next = { ...currentEnv() };
        for (const [envKey, field] of Object.entries(pd.targets)) next[envKey] = option[field] || '';
        fields.env.setValue(next, { needs: filled.needs.env });
      });
      providerRow.appendChild(providerLabel);
      providerRow.appendChild(provider);
      info.appendChild(providerRow);
    }

    const needed = Object.keys(filled.needs.env)
      .concat(Object.keys(filled.needs.args).map((i) => `argument ${Number(i) + 1}`));
    info.appendChild(line(needed.length
      ? `You fill in: ${needed.join(', ')}.`
      : 'Nothing to fill in.', 'margin-top:4px;font-weight:600;'));

    if (preset.help) {
      info.appendChild(line('Setup', 'margin-top:6px;font-weight:600;'));
      const steps = line(preset.help, 'white-space:pre-wrap;opacity:0.85;');
      steps.className = 'mcp-preset-steps';
      info.appendChild(steps);
    }

    if (filled.command === 'npx') {
      info.appendChild(line('The first time it starts, npx downloads this package from the npm registry.',
        'margin-top:6px;opacity:0.75;'));
    }

    verdict.replaceChildren();
    info.appendChild(verdict);
    info.style.display = 'block';
  }

  function runCheck(filled) {
    checkedCommand = filled.command;
    if (!checkLaunch) return;
    const mine = ++generation;
    paintVerdict([{ key: 'pending', tone: 'note', text: 'Checking this install…' }]);
    let outcome;
    try {
      outcome = checkLaunch({ command: filled.command, args: filled.args, env: filled.env });
    } catch (err) {
      outcome = Promise.reject(err);
    }
    Promise.resolve(outcome).then((answer) => {
      if (mine !== generation) return;
      paintVerdict(describeLaunchCheck({ command: filled.command, ...(answer || {}) }));
    }).catch((err) => {
      if (mine !== generation) return;
      // Never a silent gap where a verdict should be.
      paintVerdict([{ key: 'error', tone: 'bad',
        text: `Couldn’t check this install (${String((err && err.message) || err || 'no answer')}). You can still save.` }]);
    });
  }

  function choose(index) {
    const preset = catalogue[Number(index)];
    generation += 1;
    if (!preset || index === '' || index == null) {
      active = null;
      checkedCommand = null;
      info.replaceChildren();
      info.style.display = 'none';
      return null;
    }
    active = preset;
    const filled = presetFields(preset);
    if (fields.name && (!String(fields.name.value || '').trim() || fields.name.value === lastName)) {
      fields.name.value = filled.name;
      lastName = filled.name;
    }
    if (fields.transport) {
      fields.transport.value = filled.transport;
      fire(fields.transport, 'change');
    }
    if (fields.args && typeof fields.args.setValue === 'function') {
      fields.args.setValue(filled.args, { needs: filled.needs.args });
    }
    if (fields.env && typeof fields.env.setValue === 'function') {
      fields.env.setValue(filled.env, { needs: filled.needs.env });
    }
    renderInfo(preset, filled);
    if (fields.command) {
      fields.command.value = filled.command;
      fire(fields.command, 'input');
    }
    runCheck(filled);
    return preset;
  }

  select.addEventListener('change', () => { choose(select.value); });

  // Every preset is a stdio server. Switched to SSE or HTTP, the form no
  // longer sends the fields the preset filled, so the preset — its steps, its
  // verdict, its Google sign-in extras — stops too, rather than describing a
  // server the form is no longer going to add.
  if (fields.transport && typeof fields.transport.addEventListener === 'function') {
    fields.transport.addEventListener('change', () => {
      if (active && fields.transport.value !== 'stdio') {
        select.value = '';
        choose('');
      }
    });
  }

  // A verdict about `npx` must not stay on screen under a command that is no
  // longer `npx`: the moment the Command box stops matching, the verdict goes.
  if (fields.command && typeof fields.command.addEventListener === 'function') {
    fields.command.addEventListener('input', () => {
      if (checkedCommand == null) return;
      if (String(fields.command.value || '').trim() !== checkedCommand) {
        generation += 1;
        checkedCommand = null;
        verdict.replaceChildren();
      }
    });
  }

  return {
    element,
    active: () => active,
    choose: (index) => { select.value = index === '' || index == null ? '' : String(index); return choose(select.value); },
    saveExtras: (env) => presetSaveExtras(active, env),
  };
}

export default {
  MCP_PRESETS, NEEDS_YOUR_VALUE, presetNeeds, presetFields, presetSaveExtras,
  describeLaunchCheck, createMcpPresetPicker,
};
