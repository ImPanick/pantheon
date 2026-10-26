// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/admin.js — Admin panel module (ES6)
// Admin-only: users, endpoints, RAG, embeddings, webhooks, features. MCP servers and API tokens live in Settings → MCP & Integrations (`B902`, `B1524`).

import uiModule from './ui.js';
import settingsModule from './settings.js?v=20261009census';
import { providerLogo, providerLogoFromUrl } from './providers.js';
import { sortModelObjects } from './modelSort.js';
import { PROVIDER_DEVICE_FLOWS, formatDeviceFlowError, runProviderDeviceFlow } from './providerDeviceFlow.js';
import { getSettings, getTools, invalidateSettings, invalidateTools } from './appConfig.js';
import { chevronIcon } from './icons.js';
// C-ERR: a refused response is read once, by the one reader.
import { readRefusal } from './workbench/refusal.js';
import { bindMenuDismiss } from './escMenuStack.js';
import { topPortalZ } from './toolWindowZOrder.js';
// `P23-03`: the one table — each switch below names the Tools entry it hides.
// Same specifier as `app.js` (no query): one instance of the table's state.
import { hidesLine, viewerMayAdminister } from './ui_visibility.js';

import { scrollBehavior } from './motion.js';
let initialized = false;
let modalEl = null;
// When the user adds an endpoint, store its id so the next render of
// the endpoints list can flash a glow on that row. Cleared once the
// animation fires.
let _recentlyAddedEpId = null;
let _authPolicy = { password_min_length: 8, reserved_usernames: [] };

function el(id) { return document.getElementById(id); }
function esc(s) { return uiModule.esc(s); }

/** `B732`. A panel that could not draw its list says which of four things
 *  happened, through `P9-07`'s one shape (`ui.renderEmptyState`) — not one grey
 *  `.admin-empty` sentence for all of them. *Signed out* and *not an
 *  administrator* are told apart and each says what to do; a failure carries
 *  the server's own words and *Try again*; an empty list says what to add.
 *  `.admin-empty` rides along so the panel's spacing is unchanged (`Law 2`). */
function _goSignIn() {
  try { window.location.assign('/login'); } catch (_) { /* no window */ }
}
function _refusedState(host, status, reason, onRetry) {
  if (status === 401) {
    return uiModule.renderEmptyState(host, {
      kind: 'error', className: 'admin-empty', title: 'You are signed out',
      message: 'Your sign-in has ended. Sign in again to manage this.',
      action: { label: 'Sign in', onClick: _goSignIn },
    });
  }
  if (status === 403) {
    return uiModule.renderEmptyState(host, {
      kind: 'error', className: 'admin-empty',
      title: 'You are not signed in as an administrator',
      message: 'Only an administrator can see and change this. Sign in with an administrator\'s account.',
      action: { label: 'Sign in as someone else', onClick: _goSignIn },
    });
  }
  return uiModule.renderEmptyState(host, {
    kind: 'error', className: 'admin-empty', title: 'Could not load this',
    reason: reason || (status ? `The server answered ${status}.` : ''), onRetry,
  });
}

/* ═══════════════════════════════════════════
   USERS TAB
   ═══════════════════════════════════════════ */
const PRIV_LABELS = {
  can_use_agent: 'Agent mode',
  can_use_browser: 'Browser automation',
  can_use_bash: 'Shell / Python / Files',
  // `P20-02`. The workstation (`D-2026-09-30-03`). Off for everyone but admins
  // until granted here; the label names what it hands out, because "workstation"
  // alone does not say that a shell comes with it.
  can_use_workstation: 'Workstation (Ubuntu shell, files, screen)',
  can_use_documents: 'Document editor',
  can_use_research: 'Deep research',
  can_generate_images: 'Image generation',
  can_manage_memory: 'Brain (memories & skills)',
  // `D-2026-10-09-01` §2. The label names what it hands out, not the mode's
  // name: granting this lets the person switch a chat to Auto, where a step
  // that would raise an approval card runs instead.
  can_auto_approve: 'Auto-approve (run tool steps in a chat without asking)',
  // `B1191` (`D-2026-10-26-01` §5). One per Tools entry that had no switch for
  // a person. Off hides it, refuses its routes and holds its background work
  // with a sentence; nothing is deleted.
  can_use_assistant: 'Assistant',
  can_use_calendar: 'Calendar',
  can_use_compare: 'Compare',
  can_use_email: 'Email',
  can_use_notes: 'Notes',
  can_use_tasks: 'Tasks',
  can_use_theme: 'Theme',
  can_use_workbench: 'Workbench',
};

// `B1195`, the owner's call (`D-2026-10-26-01` §6). What a switch takes that
// is not a Tools entry, said where the table has nothing to say.
const PRIV_TAKES = {
  can_generate_images: 'Off takes the AI image tools (upscale, inpaint, style transfer and the rest). Their own images stay in their Gallery.',
  // `B1191`: what their background work does while off — held, never deleted.
  can_use_assistant: 'Off also holds the Assistant\'s check-ins.',
  can_use_email: 'Off also holds their inbox check, mail scheduled to send, and their email actions.',
  can_use_notes: 'Off also holds their note reminders.',
  can_use_tasks: 'Off also holds their scheduled tasks; each says why, and runs again once it is back on.',
  can_use_workbench: 'Off also holds their workflows.',
};

// `B966`, the owner's call (`D-2026-10-01-01`). A privilege this panel no
// longer offers, and what it says in the switch's place. `can_use_bash` granted
// a non-admin nothing: `NON_ADMIN_BLOCKED_TOOLS` refuses the shell, Python and
// the file tools to every non-admin whatever it says, and admins — the only
// people it could mean anything for — have no privilege panel. The stored key
// and the server's refusal are unchanged; `can_use_workstation` is the grant
// that gives a person a shell.
const NON_ADMIN_RETIRED_PRIVS = {
  can_use_bash: "Pantheon's own shell is for admins only — turn on Workstation below to give this person a shell in the workstation.",
};

/**
 * One privilege switch (or the daily limit) for one person.
 *
 * `SET-M-10` (P23-03). No word when it worked, and a refused PUT left the
 * switch where it was flipped to. Now: *Saved* and when it takes effect, or the
 * switch goes back and the server's sentence is shown.
 */
async function _savePrivilege(input) {
  const username = input.dataset.user;
  const key = input.dataset.priv;
  let value;
  if (input.type === 'checkbox') value = input.checked;
  else if (input.type === 'number') value = parseInt(input.value) || 0;
  else value = input.value;
  const revert = () => {
    if (input.type === 'checkbox') input.checked = !input.checked;
  };
  try {
    const res = await fetch(`/api/auth/users/${encodeURIComponent(username)}/privileges`, {
      method: 'PUT', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [key]: value }),
    });
    if (!res.ok) {
      revert();
      uiModule.showError((await readRefusal(res, 'Not saved.')).sentence);
      return false;
    }
    uiModule.showToast(`Saved. ${username} sees it after their next reload.`);
    return true;
  } catch (e) {
    revert();
    uiModule.showError('Not saved: Pantheon did not answer.');
    return false;
  }
}

async function loadUsers() {
  const list = el('adm-userList');
  try {
    const res = await fetch('/api/auth/users', { credentials: 'same-origin' });
    if (!res.ok) {
      const refused = res.status === 401 || res.status === 403
        ? '' : (await readRefusal(res, `The server answered ${res.status}.`)).sentence;
      _refusedState(list, res.status, refused, loadUsers);
      return;
    }
    const data = await res.json();
    if (!data.users || data.users.length === 0) {
      uiModule.renderEmptyState(list, {
        kind: 'empty', className: 'admin-empty', title: 'No accounts yet',
        message: 'Add one with the form below.',
      });
      return;
    }
    list.innerHTML = '';
    // `SET-M-11` (P23-03). *Revoke admin* was offered on the only admin, and
    // pressing it confirmed and then answered "Cannot demote the last admin".
    const adminCount = data.users.filter(x => x.is_admin).length;
    data.users.forEach(u => {
      const row = document.createElement('div');
      row.className = 'admin-user-row';

      // Header: name + badges + delete
      const header = document.createElement('div');
      header.style.cssText = 'display:flex;align-items:center;justify-content:space-between;cursor:pointer;padding:4px 0;';
      const initial = u.username.charAt(0).toUpperCase();
      header.innerHTML = `
        <div class="admin-user-info">
          <div style="width:28px;height:28px;border-radius:50%;background:color-mix(in srgb, var(--accent) 20%, var(--panel));display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;flex-shrink:0;color:var(--accent);">${esc(initial)}</div>
          <div>
            <span class="admin-user-name">${esc(u.username)}</span>
            ${u.is_admin ? '<span class="admin-badge" style="margin-left:6px;">ADMIN</span>' : ''}
          </div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end;">
          ${u.is_admin ? '' : `<button type="button" class="admin-btn-sm" data-adm-privs="${esc(u.username)}" aria-expanded="false" style="font-size:11px;">Privileges</button>`}
          ${u.is_admin && adminCount <= 1 ? '' : `<button type="button" class="admin-btn-sm" data-adm-toggle-admin="${esc(u.username)}" data-make-admin="${u.is_admin ? '0' : '1'}" style="font-size:11px;">${u.is_admin ? 'Revoke admin' : 'Make admin'}</button>`}
          <span class="admin-user-more" style="position:relative;display:inline-block;">
            <button type="button" class="admin-btn-sm" data-adm-user-more="${esc(u.username)}" aria-haspopup="menu" aria-expanded="false" aria-label="More for ${esc(u.username)}" title="More" style="font-size:11px;padding:4px 8px;line-height:1;"><svg width="14" height="4" viewBox="0 0 14 4" fill="currentColor" aria-hidden="true"><circle cx="2" cy="2" r="1.4"/><circle cx="7" cy="2" r="1.4"/><circle cx="12" cy="2" r="1.4"/></svg></button>
            <div class="admin-user-more-menu" role="menu" style="display:none;position:absolute;top:calc(100% + 4px);right:0;min-width:130px;padding:4px;background:var(--panel,var(--bg));border:1px solid var(--border);border-radius:8px;box-shadow:0 6px 20px rgba(0,0,0,0.22);flex-direction:column;gap:1px;">
              <button type="button" role="menuitem" class="admin-btn-sm adm-more-item" data-adm-rename-user="${esc(u.username)}" style="background:none;border:0;border-radius:5px;padding:7px 9px;width:100%;text-align:left;font-size:12px;font-weight:normal;color:var(--fg);cursor:pointer;">Rename</button>
              ${u.is_admin ? '' : `<button type="button" role="menuitem" class="admin-btn-sm adm-more-item" data-adm-del-user="${esc(u.username)}" style="background:none;border:0;border-radius:5px;padding:7px 9px;width:100%;text-align:left;font-size:12px;font-weight:normal;color:var(--color-error);cursor:pointer;">Remove</button>`}
            </div>
          </span>
          ${u.is_admin ? '' : chevronIcon({ size: 12, className: 'admin-user-chevron', style: 'opacity:0.3;transition:transform 0.2s,opacity 0.2s;' })}
        </div>
      `;
      row.appendChild(header);

      // Privileges panel (hidden by default, not for admins)
      if (!u.is_admin) {
        const privPanel = document.createElement('div');
        privPanel.className = 'admin-priv-panel hidden';
        privPanel.style.cssText = 'padding:8px 0 4px;border-top:1px solid var(--border);margin-top:8px;';

        // Boolean toggles. `P23-03` (SET-U-1): the heading was *Features*, the
        // same word as the instance switches in Agent Tools, and no row said
        // which entry under Tools it took away. *Can use* is this person's
        // column of the one table; each row names what it hides.
        let html = '<div style="font-size:10px;text-transform:uppercase;letter-spacing:0.5px;opacity:0.35;font-weight:600;margin-bottom:4px;">Can use</div>';
        for (const [key, label] of Object.entries(PRIV_LABELS)) {
          if (NON_ADMIN_RETIRED_PRIVS[key]) {
            html += `<div class="admin-toggle-sub" style="padding:4px 0;">${esc(NON_ADMIN_RETIRED_PRIVS[key])}</div>`;
            continue;
          }
          const checked = u.privileges && u.privileges[key] ? 'checked' : '';
          const hides = [_hidesLine({ privilege: key }), PRIV_TAKES[key]].filter(Boolean).join(' ');
          html += `<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0;">
            <span style="font-size:12px;">${label}${hides ? `<span class="admin-toggle-sub" style="display:block;font-size:10px;opacity:0.55;">${esc(hides)}</span>` : ''}</span>
            <label class="admin-switch" style="transform:scale(0.85);"><input type="checkbox" data-priv="${key}" data-user="${esc(u.username)}" ${checked} aria-label="${esc(label)}"><span class="admin-slider"></span></label>
          </div>`;
        }
        // Rate limit
        html += '<div style="font-size:10px;text-transform:uppercase;letter-spacing:0.5px;opacity:0.35;font-weight:600;margin:10px 0 4px;">Limits</div>';
        const maxMsg = (u.privileges && u.privileges.max_messages_per_day) || 0;
        html += `<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0;">
          <div>
            <span style="font-size:12px;">Daily message limit</span>
            <div style="font-size:10px;opacity:0.4;">0 = no limit</div>
          </div>
          <input type="number" min="0" value="${maxMsg}" data-priv="max_messages_per_day" data-user="${esc(u.username)}" style="width:70px;padding:4px 6px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--fg);font-size:12px;text-align:center;">
        </div>`;
        // Allowed models — checkbox list
        const allowedModels = Array.isArray(u.privileges && u.privileges.allowed_models)
          ? u.privileges.allowed_models
          : [];
        const allowedSet = new Set(allowedModels);
        const modelsRestricted = !!(u.privileges && u.privileges.allowed_models_restricted);
        const blockAllModels = !!(u.privileges && u.privileges.block_all_models);
        html += `<div style="padding:4px 0;">
          <div style="display:flex;align-items:center;justify-content:space-between;">
            <span style="font-size:12px;">Allowed models</span>
            <div style="display:flex;gap:8px;">
              <a href="#" class="priv-models-all" data-user="${esc(u.username)}" style="font-size:10px;opacity:0.5;">All</a>
              <a href="#" class="priv-models-none" data-user="${esc(u.username)}" style="font-size:10px;opacity:0.5;">None</a>
            </div>
          </div>
          <div style="font-size:10px;opacity:0.4;margin-bottom:4px;">${blockAllModels ? 'No models allowed' : (!modelsRestricted ? 'All models allowed (no restrictions)' : (allowedSet.size === 0 ? 'No models allowed' : allowedSet.size + ' model(s) allowed'))}</div>
          <div class="priv-models-list" data-user="${esc(u.username)}">
            <span style="opacity:0.4;font-size:11px;">Loading models...</span>
          </div>
        </div>`;
        privPanel.innerHTML = html;
        row.appendChild(privPanel);

        // Toggle panel visibility + rotate chevron + load models
        let _modelsLoaded = false;
        header.addEventListener('click', (e) => {
          if (e.target.closest('.admin-btn-delete, [data-adm-rename-user], [data-adm-toggle-admin], .admin-user-more')) return;
          privPanel.classList.toggle('hidden');
          const isOpen = !privPanel.classList.contains('hidden');
          const chevron = header.querySelector('.admin-user-chevron');
          if (chevron) {
            chevron.style.transform = isOpen ? 'rotate(180deg)' : '';
            chevron.style.opacity = isOpen ? '0.7' : '0.3';
          }
          // `SET-U-7` (P23-03): the row's hint said "Click to manage
          // privileges" open or shut; the button says what pressing it does.
          const privBtn = header.querySelector('[data-adm-privs]');
          if (privBtn) {
            privBtn.textContent = isOpen ? 'Hide privileges' : 'Privileges';
            privBtn.setAttribute('aria-expanded', String(isOpen));
          }
          // Load models list on first expand
          if (!_modelsLoaded && !privPanel.classList.contains('hidden')) {
            _modelsLoaded = true;
            _loadModelsForUser(u.username, allowedSet, modelsRestricted, blockAllModels, privPanel);
          }
        });

        // Wire privilege changes (boolean + number inputs, not model checkboxes)
        privPanel.querySelectorAll('[data-priv]').forEach(input => {
          input.addEventListener('change', () => _savePrivilege(input));
        });
      }

      // `B1198` (`SET-U-7`'s other half). Rename and Remove sat beside
      // Privileges at one size; they live behind the row's ⋯ now — the
      // pattern the endpoint cards already use (`#adm-epLocalMoreMenu`) — and
      // Privileges stays on the row. The two items keep their handlers below.
      const moreBtn = row.querySelector('[data-adm-user-more]');
      const moreMenu = row.querySelector('.admin-user-more-menu');
      if (moreBtn && moreMenu) {
        let dismiss = null;
        const shut = () => {
          moreMenu.style.display = 'none';
          moreBtn.setAttribute('aria-expanded', 'false');
          dismiss = null;
        };
        const closeMore = () => { const d = dismiss; if (d) d(); shut(); };
        moreBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          if (moreMenu.style.display !== 'none') { closeMore(); return; }
          // Above the rows below it, from the one stack (`check-zindex.py`).
          moreMenu.style.zIndex = String(topPortalZ());
          moreMenu.style.display = 'flex';
          moreBtn.setAttribute('aria-expanded', 'true');
          dismiss = bindMenuDismiss(moreMenu, shut,
            (ev) => !moreMenu.contains(ev.target) && !moreBtn.contains(ev.target));
        });
        // Capture: the items stop their own clicks from bubbling.
        moreMenu.addEventListener('click', (e) => {
          if (e.target.closest('.adm-more-item')) closeMore();
        }, true);
      }

      // Rename button
      const renameBtn = row.querySelector('[data-adm-rename-user]');
      if (renameBtn) {
        renameBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const oldUsername = renameBtn.dataset.admRenameUser;
          const next = await uiModule.styledPrompt(`Rename "${oldUsername}"`, {
            defaultValue: oldUsername,
            placeholder: 'New username',
            confirmText: 'Rename',
          });
          const username = (next || '').trim();
          if (!username || username === oldUsername) return;
          try {
            const res = await fetch(`/api/auth/users/${encodeURIComponent(oldUsername)}/rename`, {
              method: 'PUT',
              credentials: 'same-origin',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ username }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
              uiModule.showError(data.detail || 'Failed to rename user');
              return;
            }
            if (data.renamed_self) {
              window.location.reload();
              return;
            }
            loadUsers();
          } catch (err) {
            uiModule.showError('Failed to rename user');
          }
        });
      }

      // Delete button
      const delBtn = row.querySelector('[data-adm-del-user]');
      if (delBtn) {
        delBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const username = delBtn.dataset.admDelUser;
          if (!await uiModule.styledConfirm(`Remove user "${username}"?`, { confirmText: 'Remove', danger: true })) return;
          const res = await fetch('/api/auth/users', { method: 'DELETE', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username }) });
          if (res.ok) loadUsers();
          else uiModule.showError('Failed to delete user');
        });
      }

      // Promote / demote (admin toggle) — present on every row
      const adminToggleBtn = row.querySelector('[data-adm-toggle-admin]');
      if (adminToggleBtn) {
        adminToggleBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const username = adminToggleBtn.dataset.admToggleAdmin;
          const makeAdmin = adminToggleBtn.dataset.makeAdmin === '1';
          const confirmMsg = makeAdmin
            ? `Make ${username} an admin? They can change every setting and every user, including you.`
            : `Take admin away from ${username}? They keep their account and lose the Admin settings.`;
          if (!await uiModule.styledConfirm(confirmMsg, { confirmText: makeAdmin ? 'Make admin' : 'Revoke admin', danger: !makeAdmin })) return;
          adminToggleBtn.disabled = true;
          try {
            const res = await fetch(`/api/auth/users/${encodeURIComponent(username)}/admin`, {
              method: 'PUT',
              credentials: 'same-origin',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ is_admin: makeAdmin }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
              uiModule.showError(data.detail || 'Failed to change admin status');
              adminToggleBtn.disabled = false;
              return;
            }
            // Demoting yourself drops your own admin access — reload into the
            // normal-user view (mirrors the rename-self reload above).
            if (data.self) { window.location.reload(); return; }
            loadUsers();
          } catch (err) {
            uiModule.showError('Failed to change admin status');
            adminToggleBtn.disabled = false;
          }
        });
      }

      list.appendChild(row);
    });
  } catch (e) { _refusedState(list, 0, `Could not reach the server: ${e.message}`, loadUsers); }
}

async function _loadModelsForUser(username, allowedSet, modelsRestricted, blockAllModels, privPanel) {
  const listEl = privPanel.querySelector(`.priv-models-list[data-user="${username}"]`);
  if (!listEl) return;
  try {
    // Use /api/model-endpoints rather than /api/models — the latter is
    // backed by `cached_models`, so endpoints that haven't been probed yet
    // (e.g. a freshly-added cloud API like DeepSeek) simply don't show up
    // until some other endpoint happens to trigger a cache refresh. The
    // endpoints listing always reflects every configured endpoint.
    const res = await fetch('/api/model-endpoints', { credentials: 'same-origin' });
    const data = await res.json();
    const allModels = [];
    (Array.isArray(data) ? data : []).forEach(ep => {
      if (!ep.online) return;
      (ep.models || []).forEach(mid => {
        allModels.push({ mid, epName: ep.name || '', display: mid.split('/').pop() });
      });
    });
    if (!allModels.length) {
      listEl.innerHTML = '<span style="opacity:0.4;font-size:11px;">No models available</span>';
      return;
    }
    let restricted = modelsRestricted;
    let blockAll = blockAllModels;
    listEl.innerHTML = sortModelObjects(allModels).map(m => {
      const checked = !blockAll && (!restricted || allowedSet.has(m.mid)) ? 'checked' : '';
      return `<label>
        <input type="checkbox" class="priv-model-cb" data-mid="${esc(m.mid)}" ${checked}>
        <span>${esc(m.display)}</span>
        <span style="opacity:0.3;font-size:10px;margin-left:auto;">${esc(m.epName)}</span>
      </label>`;
    }).join('');

    // Save on change
    function _saveModels() {
      const checked = [];
      listEl.querySelectorAll('.priv-model-cb').forEach(cb => {
        if (cb.checked) checked.push(cb.dataset.mid);
      });
      // Three distinct states the backend must be able to tell apart:
      //  - all checked   -> no restriction (allowed_models: [], block_all_models: false)
      //  - none checked  -> block everything (allowed_models: [], block_all_models: true)
      //  - some checked  -> allowlist (allowed_models: checked, block_all_models: false)
      let value, hintText;
      if (checked.length === allModels.length) {
        restricted = false;
        blockAll = false;
        value = [];
        hintText = 'All models allowed (no restrictions)';
      } else if (checked.length === 0) {
        restricted = true;
        blockAll = true;
        value = [];
        hintText = 'No models allowed';
      } else {
        restricted = true;
        blockAll = false;
        value = checked;
        hintText = value.length + ' model(s) allowed';
      }
      const hint = privPanel.querySelector('.priv-models-list[data-user]')?.previousElementSibling?.querySelector('div[style*="opacity"]');
      if (hint) hint.textContent = hintText;
      fetch(`/api/auth/users/${encodeURIComponent(username)}/privileges`, {
        method: 'PUT', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ allowed_models: value, allowed_models_restricted: restricted, block_all_models: blockAll }),
      }).catch(() => {});
    }
    listEl.querySelectorAll('.priv-model-cb').forEach(cb => cb.addEventListener('change', _saveModels));

    // All / None buttons
    privPanel.querySelector(`.priv-models-all[data-user="${username}"]`)?.addEventListener('click', (e) => {
      e.preventDefault();
      listEl.querySelectorAll('.priv-model-cb').forEach(cb => cb.checked = true);
      _saveModels();
    });
    privPanel.querySelector(`.priv-models-none[data-user="${username}"]`)?.addEventListener('click', (e) => {
      e.preventDefault();
      listEl.querySelectorAll('.priv-model-cb').forEach(cb => cb.checked = false);
      _saveModels();
    });
  } catch (e) {
    listEl.innerHTML = '<span style="opacity:0.4;font-size:11px;">Failed to load models</span>';
  }
}

function initSignupToggle() {
  const toggle = el('adm-signupToggle');
  fetch('/api/auth/status', { credentials: 'same-origin' })
    .then(r => r.json())
    .then(d => { toggle.checked = !!d.signup_enabled; })
    .catch(e => console.warn('Auth status fetch failed:', e));
  toggle.addEventListener('change', async () => {
    // `H17`. This used to POST `/api/auth/signup-toggle`, whose own docstring
    // has always said *"DEPRECATED: this endpoint uses toggle semantics which
    // can lead to unsafe state changes. Use PUT /open-signup instead."* — and
    // the safe idempotent replacement had no caller anywhere in the tree.
    //
    // Toggle semantics on a security control are the defect: two admins
    // clicking, or one double-submit, flips it twice and leaves open
    // registration ON while both switches read OFF. The state to send is the
    // one the switch is now showing, so send exactly that.
    const desired = toggle.checked;
    try {
      const res = await fetch('/api/auth/open-signup', {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: desired }),
      });
      const data = await res.json();
      // Trust the server's answer over the optimistic switch — a refused
      // request must not leave the UI claiming a change that did not happen.
      toggle.checked = typeof data.signup_enabled === 'boolean'
        ? data.signup_enabled
        : desired;
      if (!res.ok) toggle.checked = !desired;
    } catch (e) { toggle.checked = !desired; }
  });
}

function initAddUser() {
  fetch('/api/auth/policy', { credentials: 'same-origin' })
    .then(r => r.ok ? r.json() : null)
    .then(policy => {
      if (!policy) return;
      _authPolicy = policy;
      const admPw = el('adm-newPassword');
      if (admPw) admPw.placeholder = `Password (min ${policy.password_min_length})`;
    })
    .catch(() => {});
  el('adm-addBtn').addEventListener('click', async () => {
    const msg = el('adm-addMsg');
    msg.textContent = ''; msg.className = '';
    const username = el('adm-newUsername').value.trim();
    const password = el('adm-newPassword').value;
    const is_admin = el('adm-newIsAdmin').checked;
    if (!username) { msg.textContent = 'Username required'; msg.className = 'admin-error'; return; }
    if (password.length < _authPolicy.password_min_length) { msg.textContent = `Password must be at least ${_authPolicy.password_min_length} characters`; msg.className = 'admin-error'; return; }
    if (_authPolicy.reserved_usernames.includes(username.toLowerCase())) { msg.textContent = 'This username is reserved'; msg.className = 'admin-error'; return; }
    el('adm-addBtn').disabled = true;
    try {
      const res = await fetch('/api/auth/users', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password, is_admin }) });
      const data = await res.json();
      if (res.ok) { msg.textContent = 'User created'; msg.className = 'admin-success'; el('adm-newUsername').value = ''; el('adm-newPassword').value = ''; el('adm-newIsAdmin').checked = false; loadUsers(); }
      else { msg.textContent = data.detail || 'Failed'; msg.className = 'admin-error'; }
    } catch (e) { msg.textContent = 'Request failed'; msg.className = 'admin-error'; }
    el('adm-addBtn').disabled = false;
  });
}

/* ═══════════════════════════════════════════
   SERVICES TAB — Endpoints
   ═══════════════════════════════════════════ */
function _isLocalEndpoint(url) {
  if (!url) return false;
  try {
    const u = new URL(url);
    const h = u.hostname.toLowerCase();
    if (h === 'localhost' || h === '127.0.0.1' || h === '0.0.0.0') return true;
    if (h.endsWith('.local')) return true;
    if (/^10\./.test(h)) return true;
    if (/^192\.168\./.test(h)) return true;
    if (/^172\.(1[6-9]|2[0-9]|3[01])\./.test(h)) return true;
    // Tailscale CGNAT range (100.64.0.0/10 → 100.64.x–100.127.x). Servers
    // found via "Scan for Servers" come back as tailnet IPs, which are still
    // your own machines, so group them under Local rather than API.
    if (/^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./.test(h)) return true;
    // Single-label hostnames are LAN by convention.
    if (!h.includes('.')) return true;
    return false;
  } catch { return false; }
}

async function _refreshAfterEndpointChange(deletedEndpointId) {
  try {
    const sm = window.sessionModule;
    const pending = sm && sm.getPendingChat ? sm.getPendingChat() : null;
    if (deletedEndpointId && pending && String(pending.endpointId || '') === String(deletedEndpointId)) {
      if (sm.setPendingChat) sm.setPendingChat(null);
    }
  } catch (_) {}
  try {
    if (window.modelsModule && window.modelsModule.refreshModels) {
      await window.modelsModule.refreshModels(true);
    }
  } catch (_) {}
  try {
    window.dispatchEvent(new CustomEvent('ge:model-endpoints-updated', {
      detail: { deletedEndpointId: deletedEndpointId || null }
    }));
  } catch (_) {}
  try {
    if (window.sessionModule && window.sessionModule.updateModelPicker) {
      window.sessionModule.updateModelPicker();
    }
  } catch (_) {}
}

async function _selectAddedModelInChat(endpoint) {
  const modelId = endpoint && Array.isArray(endpoint.models) ? endpoint.models[0] : '';
  if (!modelId) return;
  try {
    if (window.modelsModule && window.modelsModule.refreshModels) {
      await window.modelsModule.refreshModels(true);
    }
  } catch (_) {}
  try {
    document.dispatchEvent(new CustomEvent('pantheon:auto-select-model', {
      detail: {
        endpointId: endpoint.id || '',
        endpointName: endpoint.name || '',
        modelId,
        url: endpoint.base_url || '',
      }
    }));
  } catch (_) {}
}

async function loadEndpoints() {
  const listLocal = el('adm-epList-local');
  const listApi = el('adm-epList-api');
  // Render endpoint rows first. Do not make Added Models wait on /api/models or
  // endpoint probes; explicit Refresh/Probe actions do that work.
  const refreshDependentModelUi = (force = false) => {
    setTimeout(() => {
      if (window.modelsModule && window.modelsModule.refreshModels) {
        window.modelsModule.refreshModels(!!force, force ? {} : { cacheOnly: true }).then(() => {
          if (window.sessionModule && window.sessionModule.updateModelPicker) {
            window.sessionModule.updateModelPicker();
          }
        }).catch(() => {});
      }
      if (settingsModule && typeof settingsModule.refreshAiModelEndpoints === 'function') {
        settingsModule.refreshAiModelEndpoints();
      }
    }, 0);
  };
  try {
    const res = await fetch('/api/model-endpoints', { credentials: 'same-origin' });
    // Treat a non-OK response (e.g. 401/403 for non-admins, or backend
    // returning an error envelope) the same as "no endpoints yet": show the
    // empty state, not "Failed to load". The user just installed the app —
    // there's literally nothing to load, so the error read as broken UI.
    let data = [];
    if (res.ok) {
      try { data = await res.json(); } catch { data = []; }
    }
    if (!Array.isArray(data) || data.length === 0) {
      const empty = '<div class="admin-empty">None</div>';
      if (listLocal) listLocal.innerHTML = empty;
      if (listApi) listApi.innerHTML = '<div class="admin-empty">None</div>';
      refreshDependentModelUi();
      return;
    }
    const rowHtml = data.map(ep => {
      const epModels = Array.isArray(ep.models) ? ep.models : [];
      const pinnedModels = Array.isArray(ep.pinned_models) ? ep.pinned_models : [];
      const visibleCount = ep.picker_requires_pinning ? pinnedModels.length : epModels.length;
      const totalCount = Number.isFinite(Number(ep.model_count))
        ? Number(ep.model_count)
        : visibleCount + (ep.hidden_count || 0);
      // `ep.models` is the *visible* set — when every model is hidden it's
      // empty, but we still need to render the expand panel so the user can
      // un-hide them. Gate on the total instead.
      const hasModels = ep.online && totalCount > 0;
      // `D-2026-10-07-02` §1: "down" — enabled, its listing failed, so it
      // offers nothing until it answers (the picker shows its one line).
      const statusBadge = ep.status === 'down'
        ? `<span class="admin-badge admin-badge-off" title="${esc(ep.down_line || '')}">not answering</span>`
        : ep.status === 'empty'
        ? '<span class="admin-badge">no models</span>'
        : ep.online
          ? `<span class="admin-badge">${visibleCount}/${totalCount} models enabled</span>`
          : '<span class="admin-badge admin-badge-off">offline</span>';
      const justAddedClass = (_recentlyAddedEpId && String(ep.id) === _recentlyAddedEpId) ? ' adm-ep-just-added' : '';
      const category = ep.category || (_isLocalEndpoint(ep.base_url) ? 'local' : 'api');
      const kindLabel = ep.endpoint_kind && ep.endpoint_kind !== 'auto' ? ep.endpoint_kind.toUpperCase() : '';
      const keyLabel = ep.has_key
        ? (ep.api_key_fingerprint ? ` (key ${esc(ep.api_key_fingerprint)})` : ' (key set)')
        : '';
      // `P3-22`. `supports_tools` decides whether this endpoint is sent tool
      // schemas at all, and until now an admin who knew the answer had nowhere
      // to say it. Three states, not a checkbox: unset means "work it out",
      // and a checkbox would collapse that to `false` for every endpoint
      // anybody ever edits. The hint says what Pantheon believes *right now*,
      // because "Auto" on its own is not an answer to the question the admin
      // came here with — and the server computes it with the same function the
      // agent runs, not a second description of the rules.
      const tt = ep.tool_transport || {};
      const declared = tt.declared === true ? 'true' : (tt.declared === false ? 'false' : '');
      const usesNative = tt.resolved === 'native';
      // `B1301`. `offer` says whether the request carries tool schemas at all,
      // and for an endpoint nobody has declared the answer is now "both" — the
      // schemas go and the fenced prompt stays, because nothing has told
      // Pantheon which channel this server answers on. Saying only "the fenced
      // prompt" there would describe the prompt and contradict the request.
      const doing = tt.offer === 'both'
        ? 'both — native schemas and the fenced prompt'
        : (tt.resolved
          ? (usesNative ? 'native tool calling' : 'the fenced prompt')
          : 'an answer it could not work out');
      const forModel = (tt.model_dependent && tt.sample_model && tt.offer !== 'both')
        ? ` for ${esc(tt.sample_model)}` : '';
      const toolsHint = declared
        ? `Using ${doing} — you told it so.`
        : `Working it out: ${doing}${forModel}.`;
      return `
        <div class="admin-user-row${ep.is_enabled ? '' : ' admin-ep-disabled'}${justAddedClass}" data-adm-ep-id="${ep.id}">
          <div style="display:flex;align-items:center;justify-content:space-between;${hasModels ? 'cursor:pointer;' : ''}padding:4px 0;" data-adm-ep-header="${ep.id}">
            <div class="admin-user-info" style="flex:1;flex-wrap:wrap;gap:0.3rem;align-items:center;">
              <span class="adm-ep-row-logo" style="display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;flex-shrink:0;opacity:0.9;">${providerLogoFromUrl(ep.base_url) || ''}</span>
              <span class="admin-user-name">${esc(ep.name)}</span>
              ${ep.model_type === 'image' ? '<span class="admin-badge" style="background:color-mix(in srgb, var(--accent) 20%, transparent);color:var(--accent);">Image</span>' : ''}
              ${kindLabel ? `<span class="admin-badge">${esc(kindLabel)}</span>` : ''}
              ${statusBadge}
              ${ep.is_enabled ? '' : '<span class="admin-badge admin-badge-off">disabled</span>'}
              ${hasModels ? `<span style="font-size:10px;opacity:0.4;${category === 'api' ? 'flex-basis:100%;' : ''}">Click to manage models</span>` : ''}
            </div>
            <div style="display:flex;gap:4px;align-items:center;">
              <button class="admin-btn-sm" data-adm-toggle-ep="${ep.id}">${ep.is_enabled ? 'Disable' : 'Enable'}</button>
              <button class="admin-btn-delete" data-adm-del-ep="${ep.id}" data-adm-ep-online="${ep.online ? '1' : '0'}">Delete</button>
              ${hasModels ? chevronIcon({ size: 12, className: 'admin-user-chevron', style: 'opacity:0.3;transition:transform 0.2s,opacity 0.2s;' }) : ''}
            </div>
          </div>
          <div class="admin-ep-detail adm-ep-tools-row">
            <label for="adm-ep-tools-${ep.id}" style="opacity:0.7;">Tool calling</label>
            <select id="adm-ep-tools-${ep.id}" class="adm-ep-tools-select" data-adm-ep-tools="${ep.id}" title="Whether this endpoint is sent native tool schemas">
              <option value=""${declared === '' ? ' selected' : ''}>Auto</option>
              <option value="true"${declared === 'true' ? ' selected' : ''}>Native</option>
              <option value="false"${declared === 'false' ? ' selected' : ''}>Fenced</option>
            </select>
            <span class="adm-ep-tools-hint">${toolsHint}</span>
          </div>
          <div class="admin-ep-detail">${esc(ep.base_url)}${category === 'local' ? `<button type="button" class="admin-ep-copy-btn" data-adm-copy-url="${esc(ep.base_url)}" title="Copy URL" aria-label="Copy URL" style="background:none;border:none;padding:0 2px;margin-left:6px;cursor:pointer;color:inherit;opacity:0.45;vertical-align:-2px;line-height:1;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>` : ''}${keyLabel}</div>
          ${hasModels ? `<div class="mcp-tools-panel hidden" data-adm-ep-models-panel="${ep.id}"></div>` : ''}
        </div>`;
    });
    // Partition rows into Local vs API for the split sections.
    // Subsections without any rows are hidden entirely (heading + all)
    // so empty groups don't take up vertical real estate.
    const _renderInto = (container, indices) => {
      if (!container) return;
      const section = container.closest('.adm-ep-section');
      if (!indices.length) {
        if (section) section.style.display = 'none';
        container.innerHTML = '';
        return;
      }
      if (section) section.style.display = '';
      container.innerHTML = indices.map(i => rowHtml[i]).join('');
    };
    const localIdx = [], apiIdx = [];
    data.forEach((ep, i) => ((ep.category || (_isLocalEndpoint(ep.base_url) ? 'local' : 'api')) === 'local' ? localIdx : apiIdx).push(i));
    // Sort each section: enabled endpoints first, disabled at the bottom.
    // Preserve original order within each group via stable sort.
    const _sortByEnabled = (a, b) => Number(!!data[b].is_enabled) - Number(!!data[a].is_enabled);
    localIdx.sort(_sortByEnabled);
    apiIdx.sort(_sortByEnabled);
    _renderInto(listLocal, localIdx);
    _renderInto(listApi, apiIdx);
    // Iterate matching nodes across both containers.
    const queryAll = (sel) => {
      const out = [];
      [listLocal, listApi].forEach(c => {
        if (c) c.querySelectorAll(sel).forEach(n => out.push(n));
      });
      return out;
    };
    queryAll('[data-adm-toggle-ep]').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await fetch(`/api/model-endpoints/${btn.dataset.admToggleEp}`, { method: 'PATCH' });
        await _refreshAfterEndpointChange();
        loadEndpoints();
      });
    });
    queryAll('[data-adm-ep-tools]').forEach(sel => {
      // The row header opens the model panel on click; a select inside it must
      // not do that on its way to being used.
      sel.addEventListener('click', (e) => e.stopPropagation());
      sel.addEventListener('change', async (e) => {
        e.stopPropagation();
        const v = sel.value;
        // `null`, not an omitted key: the PATCH route reads `"supports_tools"
        // in body`, so leaving it out would mean "don't change it" and Auto
        // could never be chosen again once an admin had picked something.
        const supports_tools = v === '' ? null : (v === 'true');
        try {
          const res = await fetch(`/api/model-endpoints/${sel.dataset.admEpTools}`, {
            method: 'PATCH',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ supports_tools }),
          });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
        } catch (err) {
          if (uiModule && uiModule.showError) uiModule.showError('Could not save the tool-calling setting.');
          loadEndpoints();
          return;
        }
        await _refreshAfterEndpointChange();
        loadEndpoints();
      });
    });
    queryAll('[data-adm-copy-url]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const url = btn.dataset.admCopyUrl || '';
        if (!url) return;
        uiModule.copyToClipboard(url).then(() => {
          // Brief icon swap to a checkmark so the user gets feedback that
          // the copy actually happened. Reverts after ~1.4s.
          const prev = btn.innerHTML;
          btn.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
          btn.style.opacity = '1';
          setTimeout(() => { btn.innerHTML = prev; btn.style.opacity = ''; }, 1400);
        }).catch(() => {});
      });
    });
    queryAll('[data-adm-del-ep]').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        var epId = btn.dataset.admDelEp;
        var isOffline = btn.dataset.admEpOnline === '0';
        // Offline endpoints are already broken — skip the confirm dialog
        // entirely and delete immediately. The optimistic UI removal makes
        // the action feel instant.
        if (!isOffline) {
          var deps = [];
          try {
            var depRes = await fetch('/api/model-endpoints/' + epId + '/dependents', { credentials: 'same-origin' });
            var depData = await depRes.json();
            deps = depData.dependents || [];
          } catch (e) { /* proceed without warning */ }
          var msg = 'Delete this endpoint?';
          if (deps.length) {
            msg += '\n\nThe following settings use this endpoint and will be reset:\n— ' + deps.join('\n— ');
          }
          if (!await uiModule.styledConfirm(msg, { confirmText: 'Delete', danger: true })) return;
        }
        // Optimistic: remove from UI immediately
        const row = btn.closest('[data-adm-ep-id]');
        if (row) row.remove();
        fetch('/api/model-endpoints/' + epId, { method: 'DELETE' })
          .then(() => _refreshAfterEndpointChange(epId))
          .then(() => loadEndpoints())
          .catch(() => loadEndpoints());
      });
    });
    // Clear the just-added marker now that the row has been rendered
    // with the animation class — keeps the glow from re-firing on every
    // subsequent loadEndpoints() call (e.g. when toggling a model).
    if (_recentlyAddedEpId) _recentlyAddedEpId = null;
    // Models expand/collapse (click anywhere on card)
    queryAll('[data-adm-ep-id]').forEach(row => {
      const header = row.querySelector('[data-adm-ep-header]');
      if (!header) return;
      let _modelsLoaded = false;
      row.style.cursor = 'pointer';
      row.addEventListener('click', async (e) => {
        // Don't let interactions inside the expanded panel re-fire the
        // expand/collapse handler — the search box was getting closed
        // because clicking it bubbled up to here.
        if (e.target.closest('.admin-btn-sm, .admin-btn-delete, .mcp-tools-list, .mcp-tools-header, .mcp-tools-search, input, label')) return;
        const epId = header.dataset.admEpHeader;
        const panel = row.querySelector(`[data-adm-ep-models-panel="${epId}"]`);
        if (!panel) return;
        panel.classList.toggle('hidden');
        const chevron = row.querySelector('.admin-user-chevron');
        const isOpen = !panel.classList.contains('hidden');
        if (chevron) {
          chevron.style.transform = isOpen ? 'rotate(180deg)' : '';
          chevron.style.opacity = isOpen ? '0.7' : '0.3';
        }
        if (!_modelsLoaded && isOpen) {
          _modelsLoaded = true;
          // Our shared whirlpool spinner (consistent with the rest of the app).
          panel.innerHTML = '';
          let _modelsSpin = null;
          const _ld = document.createElement('span');
          _ld.style.cssText = 'opacity:0.55;font-size:11px;display:inline-flex;align-items:center;gap:8px;';
          _ld.appendChild(document.createTextNode('Loading models…'));
          try {
            const _sp = (await import('./spinner.js')).default;
            _modelsSpin = _sp.createWhirlpool(14);
            _modelsSpin.element.style.cssText = 'width:14px;height:14px;margin:0;display:inline-block;';
            _ld.appendChild(_modelsSpin.element);
          } catch (_) {}
          panel.appendChild(_ld);
          const _stopSpin = () => { try { _modelsSpin && _modelsSpin.stop(); } catch (_) {} };
          const _loadingHtml = (label) => `<span style="opacity:0.55;font-size:11px;display:inline-flex;align-items:center;gap:8px;">${esc(label)}</span>`;
          const renderModels = (models, warning = '') => {
            const sortedModels = sortModelObjects(models);
            const usesPinnedPicker = sortedModels.some(m => !!m.picker_requires_pinning);
            panel.dataset.pickerMode = usesPinnedPicker ? 'pinned' : 'hidden';
            const warningHtml = warning ? `<div class="admin-error" style="font-size:11px;margin:6px 0;">${esc(warning)}</div>` : '';
            const attachRefresh = () => {
              panel.querySelector(`[data-ep-refresh-models="${epId}"]`)?.addEventListener('click', async (e) => {
                e.preventDefault();
                panel.innerHTML = _loadingHtml('Refreshing models...');
                try {
                  const res = await fetch(`/api/model-endpoints/${epId}/models?refresh=true&refresh_timeout=60`, { credentials: 'same-origin' });
                  const refreshWarning = res.headers.get('X-Model-Refresh-Warning') || '';
                  if (!res.ok) throw new Error(`HTTP ${res.status}`);
                  const refreshedModels = await res.json();
                  renderModels(refreshedModels, refreshWarning);
                  _refreshAfterEndpointChange();
                  if (refreshWarning && uiModule?.showToast) uiModule.showToast(refreshWarning, 6000);
                } catch (_) {
                  // `D-2026-10-07-02` §1: the request itself failed, so
                  // nothing was learned about the endpoint.
                  renderModels(sortedModels, 'Could not ask it. Try again.');
                }
              });
            };
            if (!sortedModels.length) {
              panel.innerHTML = `<div class="mcp-tools-header">
                <span>Models</span>
                <span style="display:flex;gap:8px;align-items:center;">
                  <a href="#" data-ep-refresh-models="${epId}">Refresh</a>
                </span>
              </div>${warningHtml}<span style="opacity:0.5;font-size:11px;">No models</span>`;
              attachRefresh();
              return;
            }
            const enabledCount = usesPinnedPicker
              ? sortedModels.filter(m => m.is_pinned).length
              : sortedModels.filter(m => !m.is_hidden).length;
            const showSearch = sortedModels.length >= 8;
            panel.innerHTML = `<div class="mcp-tools-header">
              <span>Models</span>
              <span style="display:flex;gap:8px;align-items:center;">
                <a href="#" data-ep-refresh-models="${epId}">Refresh</a>
                <a href="#" data-ep-select-all="${epId}">All</a>
                <a href="#" data-ep-select-none="${epId}">None</a>
              </span>
            </div>${warningHtml}${showSearch ? `<input type="search" class="mcp-tools-search" placeholder="Search ${sortedModels.length} models..." data-ep-search="${epId}">` : ''}<div class="mcp-tools-list">` + sortedModels.map(m =>
              `<label title="${esc(m.id)}" data-ep-model-row data-search="${esc((m.display + ' ' + m.id).toLowerCase())}" class="adm-model-row">
                <input type="checkbox" class="adm-cb-hidden" data-ep-model-id="${esc(m.id)}" ${(usesPinnedPicker ? m.is_pinned : !m.is_hidden) ? 'checked' : ''}>
                <span class="adm-check-dot" aria-hidden="true"></span>
                <span>${esc(m.display)}</span>${m.is_listed === false ? '<span class="adm-model-unlisted">not listed</span>' : ''}
              </label>`
            ).join('') + '</div>';
            const filterRows = (q) => {
              const needle = q.trim().toLowerCase();
              panel.querySelectorAll('[data-ep-model-row]').forEach(row => {
                row.style.display = (!needle || row.dataset.search.includes(needle)) ? '' : 'none';
              });
            };
            attachRefresh();
            panel.querySelector(`[data-ep-search="${epId}"]`)?.addEventListener('input', (e) => filterRows(e.target.value));
            panel.querySelector(`[data-ep-select-all="${epId}"]`)?.addEventListener('click', (e) => {
              e.preventDefault();
              panel.querySelectorAll('[data-ep-model-row]').forEach(row => {
                if (row.style.display !== 'none') row.querySelector('input[type=checkbox]').checked = true;
              });
              _saveEpModelState(epId, panel);
            });
            panel.querySelector(`[data-ep-select-none="${epId}"]`)?.addEventListener('click', (e) => {
              e.preventDefault();
              panel.querySelectorAll('[data-ep-model-row]').forEach(row => {
                if (row.style.display !== 'none') row.querySelector('input[type=checkbox]').checked = false;
              });
              _saveEpModelState(epId, panel);
            });
            panel.querySelectorAll('input[type=checkbox]').forEach(cb => {
              cb.addEventListener('change', () => _saveEpModelState(epId, panel));
            });
          };
          try {
            const res = await fetch(`/api/model-endpoints/${epId}/models`, { credentials: 'same-origin' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const models = await res.json();
            _stopSpin();
            renderModels(models);
          } catch (e) { _stopSpin(); panel.innerHTML = '<span class="admin-error" style="font-size:11px;">Failed to load models</span>'; }
        }
      });
    });
    refreshDependentModelUi();
  } catch (e) {
    const err = '<div class="admin-error">Failed to load</div>';
    [listLocal, listApi].forEach(c => { if (c) c.innerHTML = err; });
  }
}

async function _saveEpModelState(epId, panel) {
  const hidden = [];
  const pinned = [];
  const usesPinnedPicker = panel && panel.dataset && panel.dataset.pickerMode === 'pinned';
  panel.querySelectorAll('input[type=checkbox]').forEach(cb => {
    if (cb.checked) pinned.push(cb.dataset.epModelId);
    else hidden.push(cb.dataset.epModelId);
  });
  const total = panel.querySelectorAll('input[type=checkbox]').length;
  const enabled = usesPinnedPicker ? pinned.length : total - hidden.length;
  try {
    await fetch(`/api/model-endpoints/${epId}/models`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(usesPinnedPicker ? { pinned_models: pinned } : { hidden }),
    });
    const row = panel.closest('[data-adm-ep-id]');
    if (row) {
      const badge = row.querySelector('.admin-badge');
      if (badge && !badge.classList.contains('admin-badge-off')) {
        const match = String(badge.textContent || '').match(/\/(\d+)/);
        const canonicalTotal = match ? Number(match[1]) : total;
        badge.textContent = `${enabled}/${canonicalTotal} models enabled`;
      }
    }
    if (settingsModule && typeof settingsModule.refreshAiModelEndpoints === 'function') {
      settingsModule.refreshAiModelEndpoints();
    }
    _refreshAfterEndpointChange();
  } catch (e) { /* silent */ }
}

function initEndpointForm() {
  const provider = el('adm-epProvider');
  const urlInput = el('adm-epUrl');
  const kindSel = el('adm-epKind');

  // Custom provider picker — mirrors the (now hidden) <select id="adm-epProvider">
  // so the rest of this function (which reads provider.value and dispatches
  // change events) keeps working unchanged.
  const picker = el('adm-provider-picker');
  const pickerBtn = el('adm-provider-btn');
  const pickerMenu = el('adm-provider-menu');
  const pickerCurrent = picker ? picker.querySelector('.adm-provider-current') : null;
  const DEVICE_AUTH_PROVIDER_VALUES = new Set(Object.keys(PROVIDER_DEVICE_FLOWS));
  let deviceAuthPolling = false;
  let _deviceAuthAbort = null;   // `B1482`: the sign-in in flight, so Cancel can end it
  function _selectedProviderOption() {
    return provider && provider.selectedOptions ? provider.selectedOptions[0] : null;
  }
  function _selectedDeviceAuthProvider() {
    const opt = _selectedProviderOption();
    const flow = opt && opt.dataset ? opt.dataset.authFlow : '';
    if (flow && DEVICE_AUTH_PROVIDER_VALUES.has(flow)) return flow;
    return DEVICE_AUTH_PROVIDER_VALUES.has(provider.value) ? provider.value : '';
  }
  function _isDeviceAuthSelected() {
    return !!_selectedDeviceAuthProvider();
  }
  function _setApiFormForProvider() {
    const deviceAuthProvider = _selectedDeviceAuthProvider();
    const deviceAuthConfig = PROVIDER_DEVICE_FLOWS[deviceAuthProvider] || null;
    const apiKey = el('adm-epApiKey');
    const testBtn = el('adm-epApiTestBtn');
    const addBtn = el('adm-epAddBtn');
    const status = el('adm-deviceAuthStatus');
    const msg = _endpointMsg('api');
    if (deviceAuthConfig) {
      urlInput.value = '';
      urlInput.placeholder = deviceAuthProvider === 'copilot'
        ? 'GitHub Copilot uses GitHub account sign-in'
        : 'ChatGPT Subscription uses OpenAI account sign-in';
      urlInput.readOnly = true;
      if (apiKey) {
        apiKey.value = '';
        apiKey.placeholder = 'No API key needed';
        apiKey.disabled = true;
      }
      if (testBtn) {
        testBtn.disabled = true;
        testBtn.style.opacity = '0.45';
        testBtn.style.cursor = 'not-allowed';
      }
      if (addBtn) {
        addBtn.disabled = false;
        addBtn.textContent = 'Add';
        addBtn.style.width = '55px';
        addBtn.style.display = '';
      }
      if (kindSel) kindSel.value = 'api';
      if (msg) {
        msg.textContent = '';
        msg.className = '';
      }
    } else {
      urlInput.placeholder = 'Base URL or pick provider';
      urlInput.readOnly = false;
      if (apiKey) {
        apiKey.placeholder = 'API key';
        apiKey.disabled = false;
      }
      if (testBtn) {
        testBtn.disabled = false;
        testBtn.style.opacity = '';
        testBtn.style.cursor = '';
      }
      if (addBtn) {
        addBtn.disabled = false;
        addBtn.textContent = 'Add';
        addBtn.style.width = '55px';
        addBtn.style.display = '';
      }
      if (msg) {
        msg.textContent = '';
        msg.className = '';
      }
      if (!deviceAuthPolling && status) status.textContent = '';
    }
  }
  function _renderPickerMenu() {
    if (!pickerMenu) return;
    pickerMenu.innerHTML = Array.from(provider.options).map(o => {
      const logo = o.dataset.logo ? (providerLogo(o.dataset.logo) || '') : '';
      const active = o.value === provider.value ? ' active' : '';
      return `<div class="adm-provider-item${active}" role="option" data-value="${o.value.replace(/"/g, '&quot;')}">
        <span class="adm-provider-logo">${logo}</span>
        <span>${o.textContent}</span>
      </div>`;
    }).join('');
  }
  function _syncPickerCurrent() {
    if (!pickerCurrent) return;
    const opt = provider.selectedOptions[0] || provider.options[0];
    const logo = opt.dataset.logo ? (providerLogo(opt.dataset.logo) || '') : '';
    pickerCurrent.querySelector('.adm-provider-logo').innerHTML = logo;
    pickerCurrent.querySelector('.adm-provider-name').textContent = opt.textContent;
  }
  if (picker && pickerBtn && pickerMenu && pickerCurrent) {
    _renderPickerMenu();
    _syncPickerCurrent();
    if (provider.value && !urlInput.value) urlInput.value = provider.value;
    pickerBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      pickerMenu.classList.toggle('hidden');
    });
    pickerMenu.addEventListener('click', (e) => {
      const item = e.target.closest('.adm-provider-item');
      if (!item) return;
      provider.value = item.dataset.value;
      provider.dispatchEvent(new Event('change', { bubbles: true }));
      pickerMenu.classList.add('hidden');
      _renderPickerMenu();
      _syncPickerCurrent();
    });
    document.addEventListener('click', (e) => {
      if (!picker.contains(e.target)) pickerMenu.classList.add('hidden');
    });
    // Capture-phase Esc: dismiss the picker menu without bubbling to the
    // settings-modal handler that would otherwise close the whole modal.
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      if (pickerMenu.classList.contains('hidden')) return;
      e.stopPropagation();
      pickerMenu.classList.add('hidden');
    }, { capture: true });
  }

  provider.addEventListener('change', () => {
    if (_isDeviceAuthSelected()) {
      _setApiFormForProvider();
      _renderPickerMenu();
      _syncPickerCurrent();
      return;
    }
    if (provider.value) urlInput.value = provider.value;
    else urlInput.value = '';
    if (kindSel) kindSel.value = provider.value ? 'api' : 'proxy';
    _setApiFormForProvider();
  });
  urlInput.addEventListener('input', () => {
    if (provider.value && urlInput.value.trim() !== provider.value) {
      provider.value = '';
      if (kindSel) kindSel.value = 'api';
      _renderPickerMenu();
      _syncPickerCurrent();
    }
  });
  if (kindSel) kindSel.value = kindSel.value || 'api';
  function _apiEndpointKind() {
    return (kindSel && kindSel.value) ? kindSel.value : 'api';
  }
  function _modelRefreshModeForApiEndpoint(url, endpointKind) {
    if (endpointKind === 'proxy') return 'manual';
    try {
      if ((new URL(url)).hostname.toLowerCase() === 'generativelanguage.googleapis.com') return '';
    } catch (_) {}
    return 'auto';
  }
  function _normalizeBaseUrl(raw) {
    let u = raw.trim();
    // Fix common protocol typos
    u = u.replace(/^https?:\/(?!\/)/, m => m + '/');  // https:/ → https://
    u = u.replace(/^htp:/, 'http:').replace(/^htps:/, 'https:');
    u = u.replace(/^http:\/\/\//, 'http://');  // http:/// → http://
    u = u.replace(/^https:\/\/\//, 'https://');
    // Add http:// if no protocol
    if (!/^https?:\/\//.test(u)) u = 'http://' + u;
    // Strip trailing slashes
    u = u.replace(/\/+$/, '');
    // Strip trailing paths that shouldn't be in a base URL
    u = u.replace(/\/v1\/(models|chat\/completions|completions|messages)\/?$/i, '/v1');
    u = u.replace(/\/(models|chat\/completions|completions|v1\/messages)\/?$/i, '');
    u = u.replace(/\/api\/(chat|tags|generate)\/?$/i, '/api');
    // Fix double /v1/v1
    u = u.replace(/\/v1\/v1$/, '/v1');
    // Strip query params and fragments
    u = u.split('?')[0].split('#')[0];
    try {
      const parsed = new URL(u);
      if (parsed.hostname.endsWith('ollama.com')) {
        u = 'https://ollama.com/api';
      }
    } catch(e) {}
    // Ensure /v1 suffix for bare host:port URLs (not cloud providers)
    if (!u.includes('api.') && !u.includes('openrouter') && !u.includes('opencode.ai') && !u.includes('ollama.com') && !u.endsWith('/v1')) {
      try {
        const parsed = new URL(u);
        if (!parsed.pathname || parsed.pathname === '/') {
          u += '/v1';
        }
      } catch(e) {}
    }
    return u;
  }

  async function _defaultOllamaUrl() {
    try {
      const res = await fetch('/api/runtime', { credentials: 'same-origin' });
      if (res.ok) {
        const data = await res.json();
        if (data && data.ollama_base_url) return data.ollama_base_url;
      }
    } catch (_) {}
    return 'http://127.0.0.1:11434/v1';
  }

  function _renderEndpointTestResult(msg, res, d) {
    if (res.ok && d.status === 'empty') {
      msg.textContent = 'Online — no models found';
      msg.className = 'admin-success';
      return;
    }
    if (res.ok && d.online) {
      const models = d.models || [];
      const preview = models.slice(0, 3).map(m => esc(String(m).split('/').pop())).join(', ');
      msg.innerHTML = `Online — found ${models.length} model${models.length !== 1 ? 's' : ''}${preview ? `: ${preview}${models.length > 3 ? ', …' : ''}` : ''}`;
      msg.className = 'admin-success';
      return;
    }
    msg.textContent = (d && d.detail) || (d && d.ping_error ? `Offline — ${d.ping_error}` : 'Offline');
    msg.className = 'admin-error';
  }

  function _endpointMsg(kind) {
    return el(kind === 'local' ? 'adm-epLocalMsg' : 'adm-epApiMsg') || el('adm-epMsg');
  }

  let apiTestController = null;
  const apiTestBtn = el('adm-epApiTestBtn');
  const apiCancelTestBtn = el('adm-epApiCancelTestBtn');
  if (apiTestBtn) {
    apiTestBtn.addEventListener('click', async () => {
      if (_isDeviceAuthSelected()) {
        const msg = _endpointMsg('api');
        msg.textContent = '';
        msg.className = '';
        return;
      }
      const msg = _endpointMsg('api');
      msg.textContent = ''; msg.className = '';
      const rawUrl = (urlInput.value || provider.value).trim();
      const apiKey = el('adm-epApiKey').value.trim();
      if (!rawUrl) { msg.textContent = 'Select a provider or enter a base URL'; msg.className = 'admin-error'; return; }
      if (provider.value && !apiKey) { msg.textContent = 'API key is required for cloud providers'; msg.className = 'admin-error'; return; }
      const url = provider.value && rawUrl === provider.value ? rawUrl : _normalizeBaseUrl(rawUrl);
      apiTestController = new AbortController();
      apiTestBtn.disabled = true;
      apiTestBtn.textContent = 'Testing...';
      if (apiCancelTestBtn) apiCancelTestBtn.classList.remove('hidden');
      try {
        const fd = new FormData();
        fd.append('base_url', url);
        fd.append('endpoint_kind', _apiEndpointKind());
        fd.append('model_refresh_timeout', '30');
        if (apiKey) fd.append('api_key', apiKey);
        const res = await fetch('/api/model-endpoints/test', {
          method: 'POST',
          body: fd,
          credentials: 'same-origin',
          signal: apiTestController.signal,
        });
        const d = await res.json();
        _renderEndpointTestResult(msg, res, d);
      } catch (e) {
        if (e && e.name === 'AbortError') {
          msg.textContent = 'Test canceled';
          msg.className = '';
        } else {
          msg.textContent = 'Test failed: ' + (e && e.message ? e.message : 'request failed');
          msg.className = 'admin-error';
        }
      }
      apiTestController = null;
      apiTestBtn.disabled = false;
      apiTestBtn.textContent = 'Test';
      if (apiCancelTestBtn) apiCancelTestBtn.classList.add('hidden');
    });
  }
  if (apiCancelTestBtn) {
    apiCancelTestBtn.addEventListener('click', () => {
      if (apiTestController) apiTestController.abort();
    });
  }

  el('adm-epAddBtn').addEventListener('click', async () => {
    const deviceAuthProvider = _selectedDeviceAuthProvider();
    if (deviceAuthProvider) {
      await _startProviderDeviceAuth(deviceAuthProvider, el('adm-epAddBtn'));
      return;
    }
    const msg = _endpointMsg('api');
    msg.textContent = ''; msg.className = '';
    const rawUrl = (urlInput.value || provider.value).trim();
    const apiKey = el('adm-epApiKey').value.trim();
    if (!rawUrl) { msg.textContent = 'Select a provider or enter a base URL'; msg.className = 'admin-error'; return; }
    if (provider.value && !apiKey) { msg.textContent = 'API key is required for cloud providers'; msg.className = 'admin-error'; return; }
    // Normalize URL (fix typos, add /v1, strip wrong paths)
    const url = provider.value && rawUrl === provider.value ? rawUrl : _normalizeBaseUrl(rawUrl);
    const btn = el('adm-epAddBtn');
    btn.disabled = true; btn.textContent = 'Adding...';
    try {
      const fd = new FormData();
      fd.append('base_url', url);
      const endpointKind = _apiEndpointKind();
      fd.append('endpoint_kind', endpointKind);
      const refreshMode = _modelRefreshModeForApiEndpoint(url, endpointKind);
      if (refreshMode) fd.append('model_refresh_mode', refreshMode);
      fd.append('model_refresh_timeout', '30');
      if (apiKey) fd.append('api_key', apiKey);
      if (provider.value && provider.selectedOptions && provider.selectedOptions[0]) {
        fd.append('name', provider.selectedOptions[0].textContent.trim());
      }
      const epType = el('adm-epType');
      if (epType) fd.append('model_type', epType.value);
      if (provider.value && /openrouter\.ai|ollama\.com/i.test(provider.value)) fd.append('require_models', 'true');
      else fd.append('skip_probe', 'false');
      const res = await fetch('/api/model-endpoints', { method: 'POST', body: fd, credentials: 'same-origin' });
      const d = await res.json();
      if (res.ok) {
        const count = d.models ? d.models.length : 0;
        urlInput.value = ''; urlInput.style.display = '';
        el('adm-epApiKey').value = ''; provider.value = '';
        if (kindSel) kindSel.value = 'proxy';
        if (epType) epType.value = 'llm';
        if (d.id) _recentlyAddedEpId = String(d.id);
        await loadEndpoints();
        await _selectAddedModelInChat(d);
        const goLink = ' <a href="#" data-go-added-models style="margin-left:6px;text-decoration:underline;color:inherit;font-weight:600;">Added Models →</a>';
        if (!d.online) {
          msg.innerHTML = 'Added (endpoint offline — will retry on next load)' + goLink;
          msg.className = 'admin-error';
        } else if (d.status === 'empty') {
          msg.innerHTML = 'Added — endpoint reachable, no models found' + goLink;
          msg.className = 'admin-success';
        } else {
          msg.innerHTML = `Added — found ${count} model${count !== 1 ? 's' : ''}` + goLink;
          msg.className = 'admin-success';
        }
      } else { msg.textContent = d.detail || 'Failed'; msg.className = 'admin-error'; }
    } catch (e) { msg.textContent = 'Request failed'; msg.className = 'admin-error'; }
    btn.disabled = false; btn.textContent = 'Add';
  });

  async function _startProviderDeviceAuth(providerKey, triggerEl = null) {
    if (deviceAuthPolling) return;
    const config = PROVIDER_DEVICE_FLOWS[providerKey];
    if (!config) return;
    const status = el('adm-deviceAuthStatus') || _endpointMsg('api');
    if (!status) return;
    const triggerText = triggerEl ? triggerEl.textContent : '';
    // Render an error with an inline "Try again" (the top button is hidden for
    // device-auth providers, so retry lives here). Built with DOM methods, not
    // innerHTML. Call reset() first so the deviceAuthPolling guard is cleared.
    const showAuthError = (text) => {
      status.className = 'admin-error';
      status.textContent = text + ' ';
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'admin-btn-sm';
      retry.textContent = 'Try again';
      retry.addEventListener('click', () => { _startProviderDeviceAuth(providerKey, triggerEl); });
      status.appendChild(retry);
    };
    const reset = () => {
      if (triggerEl) {
        triggerEl.disabled = false;
        triggerEl.textContent = triggerText || 'Add';
      }
      deviceAuthPolling = false;
      _setApiFormForProvider();
    };
    status.textContent = '';
    status.className = 'adm-ep-inline-msg';
    if (triggerEl) {
      triggerEl.disabled = true;
      triggerEl.textContent = 'Starting...';
    }
    deviceAuthPolling = true;
    _setApiFormForProvider();
    status.textContent = `Starting ${config.label} sign-in...`;

    // `B1482`: one sign-in at a time, and a Cancel that ends it on the server.
    if (_deviceAuthAbort) _deviceAuthAbort.abort('replaced');
    const abort = new AbortController();
    _deviceAuthAbort = abort;
    try {
      const result = await runProviderDeviceFlow(providerKey, {
        openWindow: () => {},
        signal: abort.signal,
        onStart: ({ start, authUrl }) => {
          if (triggerEl) triggerEl.textContent = 'Waiting...';
          status.className = '';
          const authLabel = providerKey === 'copilot' ? 'Authorize on GitHub' : 'Authorize with OpenAI';
          const waitLabel = providerKey === 'copilot' ? 'Waiting for GitHub authorization...' : 'Waiting for ChatGPT authorization...';
          status.innerHTML =
            '<div class="adm-copilot-panel">' +
              '<div class="adm-copilot-wait"><span class="admin-spinner"></span>' +
                '<span>' + esc(waitLabel) + '</span></div>' +
              '<div class="adm-copilot-coderow">' +
                '<span class="adm-copilot-code-label">Code</span>' +
                '<code class="adm-copilot-code">' + esc(start.user_code) + '</code>' +
                '<button type="button" class="admin-btn-sm adm-device-auth-copy">Copy</button>' +
              '</div>' +
              '<a class="admin-btn-add adm-copilot-auth" href="' + encodeURI(authUrl || '') + '" target="_blank" rel="noopener">' + esc(authLabel) + ' ↗</a>' +
              '<button type="button" class="admin-btn-sm adm-device-auth-cancel">Cancel</button>' +
            '</div>';
          const cancelBtn = status.querySelector('.adm-device-auth-cancel');
          if (cancelBtn) cancelBtn.addEventListener('click', () => abort.abort());
          const copyBtn = status.querySelector('.adm-device-auth-copy');
          if (copyBtn) copyBtn.addEventListener('click', async () => {
            const code = start.user_code || '';
            // `B59`. This had the right fallback in the wrong order, and its
            // own comment named the reason the fallback exists.
            const ok = await uiModule.copyText(code);
            copyBtn.textContent = ok ? 'Copied' : 'Failed';
            setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
          });
        },
      });
      if (result.status === 'authorized') {
        const endpoint = result.endpoint || {};
        const n = ((endpoint && endpoint.models) || []).length;
        status.className = 'admin-success';
        status.textContent = 'Connected - ' + n + ' ' + config.label + ' model' + (n !== 1 ? 's' : '') + ' available.';
        if (endpoint && endpoint.id) _recentlyAddedEpId = String(endpoint.id);
        await loadEndpoints();
        await _selectAddedModelInChat(endpoint || {});
        reset();
        return;
      }
      if (result.status === 'failed') {
        reset();
        showAuthError('Authorization failed (' + (result.error || 'denied') + ').');
        return;
      }
      if (result.status === 'expired') {
        reset();
        showAuthError('Authorization expired.');
        return;
      }
      if (result.status === 'cancelled') {
        reset();
        status.className = '';
        status.textContent = abort.signal.reason === 'replaced' ? '' : 'Sign-in cancelled.';
        return;
      }
    } catch (e) {
      reset();
      showAuthError(formatDeviceFlowError(e));
    } finally {
      if (_deviceAuthAbort === abort) _deviceAuthAbort = null;
    }
  }

  // API Key reveal toggle. The key inputs are hidden by default so the Add
  // form reads as a single action row; the Key button toggles the input row
  // and flips aria-expanded for screen readers / CSS pseudo-classes.
  const _wireKeyToggle = (btnId, rowId) => {
    const btn = el(btnId);
    const row = el(rowId);
    if (!btn || !row) return;
    btn.addEventListener('click', () => {
      const showing = row.style.display !== 'none';
      row.style.display = showing ? 'none' : '';
      btn.setAttribute('aria-expanded', showing ? 'false' : 'true');
      btn.style.opacity = showing ? '0.75' : '1';
      if (!showing) {
        const inp = row.querySelector('input');
        if (inp) inp.focus();
      }
    });
  };
  _wireKeyToggle('adm-epLocalKeyBtn', 'adm-epLocalApiKey-row');

  // Delegated link handler for jumping between settings tabs.
  //   [data-go-added-models]              → quick shortcut for the Added Models tab
  //   [data-go-settings-tab="X"]          → any tab whose nav button has data-settings-tab="X"
  //   [data-go-scroll-to="#elementId"]    → after switching, scroll the element into view
  document.addEventListener('click', (e) => {
    const explicit = e.target.closest('[data-go-settings-tab]');
    if (explicit) {
      e.preventDefault();
      const tab = explicit.getAttribute('data-go-settings-tab');
      const scrollTo = explicit.getAttribute('data-go-scroll-to');
      const btn = document.querySelector(`[data-settings-tab="${tab}"]`);
      if (btn) btn.click();
      if (scrollTo) {
        // Defer to the next frame so the panel has actually become visible
        // before we try to scroll into it.
        requestAnimationFrame(() => {
          const target = document.querySelector(scrollTo);
          if (target) target.scrollIntoView({ behavior: scrollBehavior(), block: 'start' });
        });
      }
      return;
    }
    const link = e.target.closest('[data-go-added-models]');
    if (!link) return;
    e.preventDefault();
    const btn = document.querySelector('[data-settings-tab="added-models"]');
    if (btn) btn.click();
  });

  // Generic open/close helper for the kebab dropdowns in this card.
  // Both the Local and API cards use the same shape: an h2-anchored button
  // with id "<prefix>MoreBtn" toggles a sibling menu with id "<prefix>MoreMenu".
  // Global Esc handler: close any currently-open kebab menu in the admin
  // panel regardless of which _wireKebab instance owns it. Belt-and-braces
  // backup for the per-instance handler below — registered once.
  if (!document._admKebabEscWired) {
    document._admKebabEscWired = true;
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      // Any visible kebab dropdown in the admin panel — match by id pattern
      // so adding a new kebab elsewhere automatically benefits.
      const menus = document.querySelectorAll(
        '#adm-epLocalMoreMenu, #adm-epApiMoreMenu'
      );
      let closed = false;
      menus.forEach((m) => {
        if (m && m.style.display !== 'none') {
          m.style.display = 'none';
          // Sync the associated button's aria-expanded when we can find it.
          const btn = document.getElementById(m.id.replace('Menu', 'Btn'));
          if (btn) btn.setAttribute('aria-expanded', 'false');
          closed = true;
        }
      });
      if (closed) e.stopPropagation();
    }, { capture: true });
  }

  const _wireKebab = (btnId, menuId, onItem) => {
    const btn = el(btnId);
    const menu = el(menuId);
    if (!btn || !menu) return;
    const isOpen = () => menu.style.display !== 'none';
    const close = () => { menu.style.display = 'none'; btn.setAttribute('aria-expanded', 'false'); };
    const open = () => { menu.style.display = 'flex'; btn.setAttribute('aria-expanded', 'true'); };
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (isOpen()) close(); else open();
    });
    menu.addEventListener('click', (e) => {
      const item = e.target.closest('.adm-more-item');
      if (!item) return;
      if (onItem) onItem(item, e);
      close();
    });
    document.addEventListener('click', (e) => {
      if (!isOpen()) return;
      if (e.target.closest('#' + menuId + ', #' + btnId)) return;
      close();
    });
    // Use capture phase so this fires before the settings-modal Esc handler
    // (which is in bubble phase). stopPropagation prevents the modal from
    // closing when the user only meant to dismiss this menu.
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && isOpen()) {
        e.stopPropagation();
        close();
      }
    }, { capture: true });
  };

  // API card "..." menu: contains the Proxy/API connection-mode toggle.
  // Sync the visible checkmarks with the hidden #adm-epKind select so
  // downstream code (which reads kindSel.value) keeps working.
  (function wireApiKindMenu() {
    const kind = el('adm-epKind');
    if (!kind) return;
    const opts = document.querySelectorAll('#adm-epApiMoreMenu .adm-kind-opt');
    const sync = () => {
      opts.forEach((o) => {
        const check = o.querySelector('.adm-kind-check');
        if (check) check.style.visibility = (o.dataset.kind === kind.value) ? 'visible' : 'hidden';
      });
    };
    sync();
    kind.addEventListener('change', sync);
    _wireKebab('adm-epApiMoreBtn', 'adm-epApiMoreMenu', (item) => {
      const k = item.dataset.kind;
      if (!k) return;
      kind.value = k;
      kind.dispatchEvent(new Event('change'));
    });
  })();

  // Local card "..." kebab: holds Scan network / Ollama / API key reveal.
  // Item buttons keep their own click handlers; the helper just handles
  // open/close + outside-click + Esc.
  _wireKebab('adm-epLocalMoreBtn', 'adm-epLocalMoreMenu');

  // ── Added Models toolbar: Probe + Clear offline ────────────────────
  // Both buttons act over the currently-rendered endpoint list. The
  // online/offline marker is stamped on each row's [data-adm-ep-online]
  // attribute by loadEndpoints(), so both buttons just iterate the DOM
  // without re-fetching anything they don't already have.
  const _refreshOfflineCount = () => {
    const lbl = el('adm-epOfflineCount');
    if (!lbl) return;
    const n = document.querySelectorAll('[data-adm-ep-id] [data-adm-ep-online="0"]').length;
    lbl.textContent = n > 0 ? `(${n})` : '';
    // Hide the button entirely when there's nothing offline — no point
    // showing an action that has nothing to act on.
    const btn = el('adm-epClearOfflineBtn');
    if (btn) btn.style.display = n === 0 ? 'none' : '';
  };
  // Wire after every loadEndpoints() run by patching the render hook —
  // simplest path: MutationObserver on the two list containers.
  const _obsRoots = ['adm-epList-local', 'adm-epList-api']
    .map(id => el(id)).filter(Boolean);
  if (_obsRoots.length) {
    const mo = new MutationObserver(_refreshOfflineCount);
    _obsRoots.forEach(r => mo.observe(r, { childList: true, subtree: true }));
    _refreshOfflineCount();
  }

  const _fetchWithTimeout = async (url, opts = {}, timeoutMs = 25000) => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      return await fetch(url, { ...opts, signal: ctrl.signal });
    } finally {
      clearTimeout(timer);
    }
  };
  const _collectAddedEndpointIds = async () => {
    const domIds = Array.from(document.querySelectorAll('[data-adm-ep-id]'))
      .map(r => r.getAttribute('data-adm-ep-id'))
      .filter(Boolean);
    if (domIds.length) return Array.from(new Set(domIds));
    try {
      const res = await fetch('/api/model-endpoints', { credentials: 'same-origin' });
      const data = await res.json().catch(() => []);
      return (Array.isArray(data) ? data : []).map(ep => ep && ep.id).filter(Boolean);
    } catch (_) {
      return [];
    }
  };
  const _setProbeAllButtonLabel = async (btn, text, whirlpoolRef) => {
    btn.innerHTML = '';
    if (whirlpoolRef && whirlpoolRef.element) btn.appendChild(whirlpoolRef.element);
    btn.appendChild(document.createTextNode(text));
  };
  if (!window.__admEpProbeAllWired) {
    window.__admEpProbeAllWired = true;
    document.addEventListener('click', async (ev) => {
      const probeAllBtn = ev.target.closest('#adm-epProbeAllBtn');
      if (!probeAllBtn || probeAllBtn.disabled) return;
      ev.preventDefault();
      probeAllBtn.disabled = true;
      const origHTML = probeAllBtn.innerHTML;
      let _wp = null;
      try {
        try {
          const sp = window.spinnerModule || (await import('./spinner.js')).default;
          _wp = sp.createWhirlpool(11);
          _wp.element.style.cssText = 'display:inline-flex;width:11px;height:11px;margin:0 4px 0 0;';
          await _setProbeAllButtonLabel(probeAllBtn, 'Probing', _wp);
        } catch (_) {
          probeAllBtn.innerHTML = '<span style="opacity:0.7;">Probing...</span>';
        }
        await _fetchWithTimeout('/api/model-endpoints/probe-local', { credentials: 'same-origin' }, 12000).catch(() => null);
        const ids = await _collectAddedEndpointIds();
        if (!ids.length) {
          await loadEndpoints();
          if (uiModule && uiModule.showToast) uiModule.showToast('No endpoints to probe', 1800);
          return;
        }
        let done = 0;
        let failed = 0;
        const lane = async (id) => {
          try {
            const res = await _fetchWithTimeout(`/api/model-endpoints/${encodeURIComponent(id)}/models?refresh=true&refresh_timeout=20`, {
              credentials: 'same-origin'
            }, 25000);
            if (!res || !res.ok || res.headers.get('X-Model-Refresh-Status') === 'failed') failed += 1;
            else await res.json().catch(() => null);
          } catch (err) {
            failed += 1;
            console.warn('Endpoint probe failed', id, err);
          } finally {
            done += 1;
            try { await _setProbeAllButtonLabel(probeAllBtn, `Probing ${done}/${ids.length}`, _wp); } catch (_) {}
          }
        };
        const queue = [...ids];
        const workers = Array.from({ length: Math.min(4, queue.length) }, () => (async () => {
          while (queue.length) {
            const id = queue.shift();
            if (id) await lane(id);
          }
        })());
        await Promise.all(workers);
        await loadEndpoints();
        await _refreshAfterEndpointChange();
        _refreshOfflineCount();
        if (uiModule && uiModule.showToast) {
          const ok = Math.max(0, ids.length - failed);
          uiModule.showToast(failed ? `Probed ${ok}/${ids.length} endpoints; ${failed} failed` : `Probed ${ids.length} endpoints`, failed ? 4200 : 1800);
        }
      } finally {
        if (_wp) { try { _wp.destroy(); } catch (_) {} }
        probeAllBtn.innerHTML = origHTML;
        probeAllBtn.disabled = false;
      }
    });
  }

  const clearOfflineBtn = el('adm-epClearOfflineBtn');
  if (clearOfflineBtn) {
    clearOfflineBtn.addEventListener('click', async () => {
      const offlineBtns = Array.from(document.querySelectorAll('[data-adm-del-ep][data-adm-ep-online="0"]'));
      const ids = offlineBtns.map(b => b.getAttribute('data-adm-del-ep')).filter(Boolean);
      if (!ids.length) {
        if (uiModule && uiModule.showToast) {
          uiModule.showToast('No offline endpoints — nothing to clear', 1800);
        }
        return;
      }
      const confirmMsg = ids.length === 1
        ? 'Remove 1 offline endpoint?'
        : `Remove ${ids.length} offline endpoints?`;
      if (uiModule && uiModule.styledConfirm) {
        const ok = await uiModule.styledConfirm(confirmMsg, { confirmText: 'Remove', danger: true });
        if (!ok) return;
      } else if (!confirm(confirmMsg)) {
        return;
      }
      clearOfflineBtn.disabled = true;
      // Optimistic UI: pull rows immediately, then fire the DELETEs.
      offlineBtns.forEach(b => {
        const row = b.closest('[data-adm-ep-id]');
        if (row) row.remove();
      });
      await Promise.all(ids.map(id =>
        fetch('/api/model-endpoints/' + id, { method: 'DELETE', credentials: 'same-origin' }).catch(() => {})
      ));
      await _refreshAfterEndpointChange();
      try { await loadEndpoints(); } catch (_) {}
      _refreshOfflineCount();
      if (uiModule && uiModule.showToast) uiModule.showToast(`Removed ${ids.length} offline endpoint${ids.length === 1 ? '' : 's'}`, 1800);
    });
  }

  // Clear-on-focus for the API key inputs. The fields are type=password so the
  // value is masked; users can't see what's there to edit it in place, so the
  // expected gesture is "click in, type new key". Wiping on focus removes the
  // select-all-and-delete dance.
  const _wireClearOnFocus = (id) => {
    const inp = el(id);
    if (!inp) return;
    inp.addEventListener('focus', () => {
      if (inp.value) inp.value = '';
    });
  };
  _wireClearOnFocus('adm-epLocalApiKey');
  _wireClearOnFocus('adm-epApiKey');

  // Drop the Ollama provider logo into the Ollama Quickstart button. Reuses
  // the same SVG the provider picker uses, so brand parity stays free.
  try {
    const _ollamaLogoSlot = document.querySelector('#adm-epOllamaBtn .adm-ollama-logo');
    if (_ollamaLogoSlot) {
      const svg = providerLogo('ollama') || '';
      if (svg) _ollamaLogoSlot.innerHTML = svg;
    }
  } catch (_) {}

  // Local "Add" button — sibling form for self-hosted base URLs.
  const localAddBtn = el('adm-epLocalAddBtn');
  const localTestBtn = el('adm-epLocalTestBtn');
  if (localTestBtn) {
    localTestBtn.addEventListener('click', async () => {
      const testOriginalHtml = localTestBtn.innerHTML || '>Test';
      const msg = _endpointMsg('local');
      msg.textContent = ''; msg.className = 'adm-ep-inline-msg';
      const raw = (el('adm-epLocalUrl').value || '').trim();
      if (!raw) { msg.textContent = 'Enter a base URL to test'; msg.className = 'admin-error'; return; }
      const url = _normalizeBaseUrl(raw);
      const keyEl = el('adm-epLocalApiKey');
      const apiKey = keyEl ? keyEl.value.trim() : '';
      localTestBtn.disabled = true;
      localTestBtn.innerHTML = testOriginalHtml.replace(/>Test\s*$/, '>Testing...');
      try {
        const fd = new FormData();
        fd.append('base_url', url);
        if (apiKey) fd.append('api_key', apiKey);
        const res = await fetch('/api/model-endpoints/test', { method: 'POST', body: fd, credentials: 'same-origin' });
        const d = await res.json();
        _renderEndpointTestResult(msg, res, d);
      } catch (e) {
        msg.textContent = 'Test failed: ' + (e && e.message ? e.message : 'request failed');
        msg.className = 'admin-error';
      }
      localTestBtn.disabled = false;
      localTestBtn.innerHTML = testOriginalHtml;
    });
  }
  if (localAddBtn) {
    localAddBtn.addEventListener('click', async () => {
      const addOriginalHtml = localAddBtn.innerHTML || '>Add';
      const msg = _endpointMsg('local');
      msg.textContent = ''; msg.className = 'adm-ep-inline-msg';
      const raw = (el('adm-epLocalUrl').value || '').trim();
      if (!raw) { msg.textContent = 'Enter a base URL (e.g. http://localhost:8002/v1)'; msg.className = 'admin-error'; return; }
      const url = _normalizeBaseUrl(raw);
      const keyEl = el('adm-epLocalApiKey');
      const apiKey = keyEl ? keyEl.value.trim() : '';
      localAddBtn.disabled = true;
      localAddBtn.innerHTML = addOriginalHtml.replace(/>Add\s*$/, '>Adding...');
      try {
        const fd = new FormData();
        fd.append('base_url', url);
        if (apiKey) fd.append('api_key', apiKey);
        fd.append('endpoint_kind', 'local');
        fd.append('model_refresh_mode', 'auto');
        const lt = el('adm-epLocalType');
        if (lt) fd.append('model_type', lt.value);
        fd.append('skip_probe', 'false');
        const res = await fetch('/api/model-endpoints', { method: 'POST', body: fd, credentials: 'same-origin' });
        const d = await res.json();
        if (res.ok) {
          el('adm-epLocalUrl').value = '';
          if (keyEl) keyEl.value = '';
          if (lt) lt.value = 'llm';
          if (d.id) _recentlyAddedEpId = String(d.id);
          await loadEndpoints();
          await _selectAddedModelInChat(d);
          const count = (d.models || []).length;
          const baseText = d.status === 'empty'
            ? 'Added — Ollama is running, no models pulled yet'
            : d.online
            ? `Added — found ${count} model${count !== 1 ? 's' : ''}`
            : 'Added (offline — will retry on next load)';
          msg.innerHTML = `${baseText} <a href="#" data-go-added-models style="margin-left:6px;text-decoration:underline;color:inherit;font-weight:600;">Added Models →</a>`;
          msg.className = d.online ? 'admin-success' : 'admin-error';
        } else { msg.textContent = d.detail || 'Failed'; msg.className = 'admin-error'; }
      } catch (e) { msg.textContent = 'Request failed'; msg.className = 'admin-error'; }
      localAddBtn.disabled = false;
      localAddBtn.innerHTML = addOriginalHtml;
    });
  }

  const ollamaBtn = el('adm-epOllamaBtn');
  if (ollamaBtn) {
    ollamaBtn.addEventListener('click', async () => {
      const input = el('adm-epLocalUrl');
      if (input) {
        input.value = await _defaultOllamaUrl();
        input.focus();
      }
      const msg = _endpointMsg('local');
      if (msg) {
        msg.innerHTML = '<span style="font-size:11px;opacity:0.55;">Ollama ready to test.</span>';
        msg.className = '';
      }
    });
  }

  // Discover local models button
  const discoverBtn = el('adm-epDiscoverBtn');
  if (discoverBtn) {
    discoverBtn.addEventListener('click', async () => {
      const msg = _endpointMsg('local');
      discoverBtn.disabled = true;
      msg.className = 'adm-ep-inline-msg';
      msg.innerHTML = '';
      try {
        const sp = window.spinnerModule || (await import('./spinner.js')).default;
        const wp = sp.createWhirlpool(20);
        wp.element.style.cssText = 'display:inline-block;vertical-align:middle;margin:0 8px 0 0;';
        const wrap = document.createElement('div');
        wrap.style.cssText = 'display:flex;align-items:center;padding:8px 0;';
        wrap.appendChild(wp.element);
        const txt = document.createElement('span');
        txt.textContent = 'Scanning ports 8000-8020, 8080, 1234, 11434, and 11435 for model servers...';
        txt.style.cssText = 'font-size:12px;opacity:0.7;';
        wrap.appendChild(txt);
        msg.appendChild(wrap);
        discoverBtn._wp = wp;
      } catch(e) { msg.textContent = 'Scanning...'; }
      try {
        const res = await fetch('/api/discover');
        const data = await res.json();
        const items = data.items || [];
        if (!items.length) {
          msg.textContent = 'No model servers found. Make sure vLLM, llama.cpp, SGLang, or Ollama is running. Docker users may need Ollama bound to a trusted reachable interface.';
          msg.className = 'admin-error';
        } else {
          // Auto-add each discovered endpoint. Server dedupes on base_url
          // and returns `existing: true` for already-registered ones.
          // Map fingerprinted provider IDs to friendly display names.
          const _PROVIDER_DISPLAY = {
            llamacpp: 'llama.cpp', lmstudio: 'LM Studio', vllm: 'vLLM',
            ollama: 'Ollama',
          };
          let added = 0;
          let skipped = 0;
          for (const item of items) {
            const base = item.url.replace('/chat/completions', '').replace(/\/$/, '');
            const providerDisplay = _PROVIDER_DISPLAY[item.provider] || null;
            const fd = new FormData();
            fd.append('base_url', base);
            if (providerDisplay) {
              // Use "Provider (host:port)" so the endpoint is immediately
              // identifiable in the list, e.g. "llama.cpp (localhost:8080)".
              const hostPart = base.replace(/^https?:\/\//, '').split('/')[0];
              fd.append('name', `${providerDisplay} (${hostPart})`);
            }
            fd.append('endpoint_kind', 'local');
            fd.append('model_refresh_mode', 'auto');
            fd.append('skip_probe', 'false');
            const r = await fetch('/api/model-endpoints', { method: 'POST', body: fd });
            if (r.ok) {
              try {
                const dd = await r.json();
                if (dd && dd.existing) { skipped++; }
                else { added++; if (dd && dd.id) _recentlyAddedEpId = String(dd.id); }
              } catch (_) { added++; }
            }
          }
          const totalModels = items.reduce((n, i) => n + (i.models ? i.models.length : 0), 0);
          const serverNames = items.map(i =>
            (_PROVIDER_DISPLAY[i.provider] || i.url.replace(/^https?:\/\//, '').split('/')[0])
          );
          const parts = [
            `Found ${items.length} server${items.length !== 1 ? 's' : ''} (${serverNames.join(', ')}) with ${totalModels} model${totalModels !== 1 ? 's' : ''}`,
          ];
          if (added) parts.push(`added ${added} new`);
          if (skipped) parts.push(`${skipped} already added`);
          msg.innerHTML = parts.join(' — ');
          msg.className = 'admin-success';
          loadEndpoints();
        }
      } catch (e) {
        msg.textContent = 'Scan failed: ' + e.message;
        msg.className = 'admin-error';
      }
      if (discoverBtn._wp) { discoverBtn._wp.destroy(); discoverBtn._wp = null; }
      discoverBtn.disabled = false;
      discoverBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="vertical-align:-1px;margin-right:4px;"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>Scan for Servers';
    });
  }

  document.querySelectorAll('.adm-quickstart-section').forEach((sec) => {
    const head = sec.querySelector('.adm-quickstart-toggle');
    if (!head) return;
    const key = 'pantheon.addModels.' + sec.id + '.open';
    let open = false;
    try { open = localStorage.getItem(key) === '1'; } catch {}
    const apply = () => {
      sec.classList.toggle('collapsed', !open);
      head.setAttribute('aria-expanded', open ? 'true' : 'false');
    };
    apply();
    const toggle = () => {
      open = !open;
      try { localStorage.setItem(key, open ? '1' : '0'); } catch {}
      apply();
    };
    head.addEventListener('click', toggle);
    head.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
    });
  });
}

/* ═══════════════════════════════════════════
   TOOLS TAB — MCP
   ═══════════════════════════════════════════ */

// `B902`. The admin MCP form that stood here (`initMcpForm`, `loadMcpServers`,
// `_saveMcpToolState`, and the `_GOOGLE_OAUTH_HELP` text nothing read) returned
// on ids no template renders, and everything it did is the Settings MCP form's
// (`static/js/settings.js`, its presets in `settings/mcpPresets.js`) — one place
// to add a server, not two (`D-2026-09-27-01`). Deleted, as `B1445` deleted the
// dead lookups in `app.js`.
// ── Built-in tools management ──
const TOOL_META = {
  bash:              { name: 'Shell',            desc: 'Execute bash commands',           cat: 'Code',       ctx: '~200' },
  python:            { name: 'Python',           desc: 'Run Python scripts',              cat: 'Code',       ctx: '~200' },
  read_file:         { name: 'Read File',        desc: 'Read files from disk',            cat: 'Code',       ctx: '~150' },
  write_file:        { name: 'Write File',       desc: 'Write/create files',              cat: 'Code',       ctx: '~150' },
  web_search:        { name: 'Web Search',       desc: 'Search the web via SearXNG',      cat: 'Search',     ctx: '~300' },
  search_chats:      { name: 'Search Chats',     desc: 'Search chat history',           cat: 'Search',     ctx: '~150' },
  create_document:   { name: 'Create Document',  desc: 'Create new documents',            cat: 'Documents',  ctx: '~200' },
  update_document:   { name: 'Update Document',  desc: 'Modify existing documents',       cat: 'Documents',  ctx: '~200' },
  edit_document:     { name: 'Edit Document',    desc: 'Find & replace in documents',     cat: 'Documents',  ctx: '~200' },
  suggest_document:  { name: 'Suggest Changes',  desc: 'Propose document edits',          cat: 'Documents',  ctx: '~200' },
  manage_documents:  { name: 'Manage Documents', desc: 'List, delete, organize docs',     cat: 'Documents',  ctx: '~150' },
  generate_image:    { name: 'Generate Image',   desc: 'Create images via AI',            cat: 'Media',      ctx: '~150' },
  manage_memory:     { name: 'Memory',           desc: 'Save and recall memories',        cat: 'Knowledge',  ctx: '~200' },
  manage_skills:     { name: 'Skills',           desc: 'Learn and use procedures',        cat: 'Knowledge',  ctx: '~200' },
  manage_rag:        { name: 'RAG / Docs',       desc: 'Query indexed documents',         cat: 'Knowledge',  ctx: '~150' },
  chat_with_model:   { name: 'Chat with Model',  desc: 'Talk to another AI model',        cat: 'Multi-Agent', ctx: '~200' },
  pipeline:          { name: 'Pipeline',         desc: 'Multi-step AI workflows',         cat: 'Multi-Agent', ctx: '~200' },
  ask_teacher:       { name: 'Ask Teacher',      desc: 'Query a more capable model',      cat: 'Multi-Agent', ctx: '~150' },
  send_to_session:   { name: 'Send to Chat',     desc: 'Send message to another chat',    cat: 'Chats',      ctx: '~100' },
  create_session:    { name: 'Create Chat',      desc: 'Start a new chat',                cat: 'Chats',      ctx: '~100' },
  list_sessions:     { name: 'List Chats',       desc: 'Browse existing chats',           cat: 'Chats',      ctx: '~100' },
  manage_session:    { name: 'Manage Chat',      desc: 'Rename, archive, configure',      cat: 'Chats',      ctx: '~100' },
  list_models:       { name: 'List Models',      desc: 'Show available models',           cat: 'System',     ctx: '~100' },
  ui_control:        { name: 'UI Control',       desc: 'Change theme, layout, settings',  cat: 'System',     ctx: '~150' },
  manage_tasks:      { name: 'Tasks',            desc: 'Schedule automated tasks',        cat: 'System',     ctx: '~150' },
  api_call:          { name: 'API Call',         desc: 'Make HTTP requests',              cat: 'System',     ctx: '~200' },
  manage_endpoints:  { name: 'Endpoints',        desc: 'Add/remove model endpoints',      cat: 'System',     ctx: '~100' },
  manage_mcp:        { name: 'MCP Servers',      desc: 'Manage MCP connections',          cat: 'System',     ctx: '~100' },
  manage_webhooks:   { name: 'Webhooks',         desc: 'Configure webhook events',        cat: 'System',     ctx: '~100' },
  manage_tokens:     { name: 'API Tokens',       desc: 'Manage API access tokens',        cat: 'System',     ctx: '~100' },
  manage_settings:   { name: 'Settings',         desc: 'Change app settings',             cat: 'System',     ctx: '~100' },
};

async function loadBuiltinTools() {
  const list = el('adm-builtin-tools-list');
  if (!list) return;
  try {
    // This panel is an editor, and its save posts the whole disabled list
    // rebuilt from the checkboxes below. So it has to render authoritative
    // state: a snapshot that went stale out of band (the manage_settings tool,
    // another tab) would be re-posted wholesale on the next unrelated toggle
    // and would silently undo the newer state. refreshAll() calls this on every
    // panel open, so drop the shared entry and refill it. The startup read that
    // chatRenderer.js shares is unaffected; this panel just never edits a cache,
    // which is the same rule the settings panel follows by reading directly.
    invalidateTools();
    const data = await getTools();
    const tools = data.tools || [];
    if (!tools.length) {
      uiModule.renderEmptyState(list, {
        kind: 'empty', className: 'admin-empty', title: 'No tools are registered',
        message: 'The server reported no built-in tools. Its log says what it loaded at start.',
      });
      return;
    }

    // Group by category
    const groups = {};
    for (const t of tools) {
      const meta = TOOL_META[t.id] || { name: t.id, desc: '', cat: 'Other', ctx: '?' };
      const cat = meta.cat;
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push({ ...t, ...meta });
    }

    // Category order
    const catOrder = ['Code', 'Search', 'Documents', 'Media', 'Knowledge', 'Multi-Agent', 'Chats', 'System', 'Other'];
    let html = '';
    for (const cat of catOrder) {
      const items = groups[cat];
      if (!items) continue;
      const enabledCount = items.filter(i => i.enabled).length;
      const totalCount = items.length;
      const catId = 'tool-cat-' + cat.replace(/[^a-zA-Z]/g, '');
      const allEnabled = enabledCount === totalCount;
      html += `<div class="admin-tool-category">
        <div class="admin-tool-cat-header" data-tool-cat="${catId}" style="cursor:pointer;display:flex;align-items:center;justify-content:space-between;">
          <span>${esc(cat)}</span>
          <span style="display:flex;align-items:center;gap:6px;" class="admin-tool-cat-right">
            <span class="admin-tool-cat-count" style="font-size:10px;opacity:0.5;">${enabledCount}/${totalCount}</span>
            <label class="admin-switch" style="flex-shrink:0;">
              <input type="checkbox" data-tool-cat-toggle="${catId}" ${allEnabled ? 'checked' : ''}>
              <span class="admin-slider"></span>
            </label>
            ${chevronIcon({ size: 12, className: 'admin-tool-cat-chevron', style: 'opacity:0.3;transition:transform 0.2s,opacity 0.2s;' })}
          </span>
        </div>
        <div class="admin-tool-cat-body hidden" id="${catId}">`;
      for (const t of items) {
        html += `
        <div class="admin-tool-row">
          <div class="admin-tool-info">
            <span class="admin-tool-name">${esc(t.name)}</span>
            <span class="admin-tool-desc">${esc(t.desc)}</span>
          </div>
          <span class="admin-tool-ctx" title="Approximate context tokens used">${esc(t.ctx)}</span>
          <label class="admin-switch" style="flex-shrink:0;">
            <input type="checkbox" data-tool-id="${esc(t.id)}" ${t.enabled ? 'checked' : ''}>
            <span class="admin-slider"></span>
          </label>
        </div>`;
      }
      html += '</div></div>';
    }
    list.innerHTML = html;

    // Prevent toggle clicks from expanding/collapsing
    list.querySelectorAll('.admin-tool-cat-right').forEach(span => {
      span.addEventListener('click', e => e.stopPropagation());
    });

    // Wire category expand/collapse
    list.querySelectorAll('[data-tool-cat]').forEach(header => {
      header.addEventListener('click', () => {
        const body = el(header.dataset.toolCat);
        if (!body) return;
        body.classList.toggle('hidden');
        const chevron = header.querySelector('.admin-tool-cat-chevron');
        const isOpen = !body.classList.contains('hidden');
        if (chevron) {
          chevron.style.transform = isOpen ? 'rotate(180deg)' : '';
          chevron.style.opacity = isOpen ? '0.7' : '0.3';
        }
      });
    });

    // Merge only the user's intended changes onto authoritative server state.
    // /api/tools replaces the full disabled list, so rebuilding it from this
    // panel's DOM can undo a change made by another tab or manage_settings
    // after the panel was opened.
    async function _saveToolState(changes) {
      invalidateTools();
      const latest = await getTools();
      const state = new Map(
        (latest.tools || []).map(t => [t.id, !!t.enabled])
      );
      const before = new Map(state);

      for (const change of changes) {
        if (state.has(change.id)) {
          state.set(change.id, !!change.enabled);
        }
      }

      const disabled = Array.from(state.entries())
        .filter(([, enabled]) => !enabled)
        .map(([id]) => id);

      try {
        const res = await fetch('/api/tools', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ disabled }),
          credentials: 'same-origin',
        });
        // `SET-M-10` (P23-03). A refusal threw into a change handler nobody
        // caught: the switch stayed flipped and nothing was said. Now a
        // refused save puts every switch back where the server has it and
        // says the server's sentence; a save says so.
        const refused = res.ok ? null : (await readRefusal(res, 'Not saved.')).sentence;
        const shown = refused ? before : state;

        // Bring the still-open editor forward to the same merged snapshot so an
        // out-of-band change is visible instead of leaving stale checkboxes.
        list.querySelectorAll('input[data-tool-id]').forEach(c => {
          if (shown.has(c.dataset.toolId)) {
            c.checked = shown.get(c.dataset.toolId);
          }
        });
        list.querySelectorAll('.admin-tool-category').forEach(_updateCatCounter);
        if (refused) uiModule.showError(refused);
        else uiModule.showToast(changes.length === 1
          ? `Saved. The agent ${changes[0].enabled ? 'may' : 'may not'} call ${(TOOL_META[changes[0].id] || {}).name || changes[0].id}.`
          : 'Saved.');
      } catch (e) {
        list.querySelectorAll('input[data-tool-id]').forEach(c => {
          if (before.has(c.dataset.toolId)) c.checked = before.get(c.dataset.toolId);
        });
        list.querySelectorAll('.admin-tool-category').forEach(_updateCatCounter);
        uiModule.showError('Not saved: Pantheon did not answer.');
      } finally {
        // This route persists disabled_tools into the settings store
        // (routes/model_routes.py), so both snapshots are now stale.
        invalidateTools();
        invalidateSettings();
      }
    }
    function _updateCatCounter(catEl) {
      if (!catEl) return;
      const catChecks = catEl.querySelectorAll('input[data-tool-id]');
      const catEnabled = Array.from(catChecks).filter(c => c.checked).length;
      const counter = catEl.querySelector('.admin-tool-cat-count');
      if (counter) counter.textContent = catEnabled + '/' + catChecks.length;
      const catToggle = catEl.querySelector('input[data-tool-cat-toggle]');
      if (catToggle) catToggle.checked = (catEnabled === catChecks.length);
    }

    // Wire individual tool toggles
    list.querySelectorAll('input[data-tool-id]').forEach(chk => {
      chk.addEventListener('change', async () => {
        await _saveToolState([
          { id: chk.dataset.toolId, enabled: chk.checked },
        ]);
        _updateCatCounter(chk.closest('.admin-tool-category'));
      });
    });

    // Wire category-level toggle (enable/disable all in category)
    list.querySelectorAll('input[data-tool-cat-toggle]').forEach(chk => {
      chk.addEventListener('change', async () => {
        const catEl = chk.closest('.admin-tool-category');
        if (!catEl) return;
        const checked = chk.checked;
        const changes = Array.from(catEl.querySelectorAll('input[data-tool-id]'))
          .map(c => ({ id: c.dataset.toolId, enabled: checked }));
        catEl.querySelectorAll('input[data-tool-id]').forEach(c => { c.checked = checked; });
        await _saveToolState(changes);
        _updateCatCounter(catEl);
      });
    });
  } catch (e) {
    console.error('Failed to load tools:', e);
    // `B732`: the reason, and a way to ask again — not the "nothing here" grey.
    _refusedState(list, 0, `The tool list did not load: ${e.message}`, loadBuiltinTools);
  }
}

/* ── Embedding model ──
   No settings UI: the embedding model (RAG, semantic memory, tool selection)
   is fixed infrastructure that ships with the app, and swapping it would
   invalidate every existing vector. Configure via the FASTEMBED_MODEL /
   EMBEDDING_URL env vars if you really need to override it. */

/* ── RAG ── */
async function loadRag() {
  loadRagStats();   // `B1453`: the count moves with every add, remove and reload
  try {
    const res = await fetch('/api/personal');
    if (!res.ok) {
      // `B732`: a refusal is not an empty index.
      const refused = res.status === 401 || res.status === 403
        ? '' : (await readRefusal(res, `The server answered ${res.status}.`)).sentence;
      _refusedState(el('adm-ragDirList'), res.status, refused, loadRag);
      el('adm-ragFileList').innerHTML = '';
      return;
    }
    const data = await res.json();
    // `B1187`. Whether the index behind these lists is up, and the sentence
    // saying why not — `P23-02` gave the route both and only the Brain's RAG
    // tab drew them; this card listed directories over a dead index.
    const health = el('adm-ragHealth');
    if (health) {
      const down = data && data.healthy === false;
      health.hidden = !down;
      health.textContent = down ? String(data.reason || 'The knowledge index is off.') : '';
    }
    const dirList = el('adm-ragDirList');
    const dirs = data.directories || [];
    if (dirs.length === 0) {
      uiModule.renderEmptyState(dirList, {
        kind: 'empty', className: 'admin-empty', title: 'No directories indexed',
        message: 'Type a directory on this machine below and press Add Directory.',
      });
    }
    else {
      dirList.innerHTML = dirs.map(d => `<div class="admin-rag-item"><span class="admin-rag-item-name" title="${esc(d)}">${esc(d)}</span><button class="admin-btn-delete" data-adm-rag-dir="${esc(d)}">Remove</button></div>`).join('');
      dirList.querySelectorAll('[data-adm-rag-dir]').forEach(btn => {
        btn.addEventListener('click', async () => {
          if (!await uiModule.styledConfirm(`Remove directory "${btn.dataset.admRagDir}" from RAG?`, { confirmText: 'Remove', danger: true })) return;
          btn.disabled = true; btn.textContent = '...';
          try {
            const res = await fetch('/api/personal/remove_directory?directory=' + encodeURIComponent(btn.dataset.admRagDir), { method: 'DELETE' });
            if (res.ok) { ragMsg('Directory removed'); loadRag(); }
            else { const e = await res.json(); ragMsg(e.detail || 'Failed', true); }
          } catch (e) { ragMsg('Error: ' + e.message, true); }
        });
      });
    }
    const fileList = el('adm-ragFileList');
    const files = data.files || [];
    if (files.length === 0) {
      uiModule.renderEmptyState(fileList, {
        kind: 'empty', className: 'admin-empty', title: 'No files indexed',
        message: 'Drop files on the box above, or add a directory.',
      });
    }
    else {
      fileList.innerHTML = files.map(f => {
        const size = f.size ? (f.size > 1024 ? (f.size / 1024).toFixed(1) + ' KB' : f.size + ' B') : '';
        return `<div class="admin-rag-item"><span class="admin-rag-item-name" title="${esc(f.path || f.name)}">${esc(f.name)}</span><span class="admin-rag-item-meta">${size}</span><button class="admin-btn-delete" data-adm-rag-file="${esc(f.path || f.name)}">Delete</button></div>`;
      }).join('');
      fileList.querySelectorAll('[data-adm-rag-file]').forEach(btn => {
        btn.addEventListener('click', async () => {
          if (!await uiModule.styledConfirm(`Delete "${btn.dataset.admRagFile}" from RAG?`, { confirmText: 'Delete', danger: true })) return;
          btn.disabled = true; btn.textContent = '...';
          try {
            const res = await fetch('/api/personal/file?filepath=' + encodeURIComponent(btn.dataset.admRagFile), { method: 'DELETE' });
            if (res.ok) { ragMsg('File removed'); loadRag(); }
            else { const e = await res.json(); ragMsg(e.detail || 'Failed', true); }
          } catch (e) { ragMsg('Error: ' + e.message, true); }
        });
      });
    }
  } catch (e) {
    _refusedState(el('adm-ragDirList'), 0, `The index did not answer: ${e.message}`, loadRag);
    el('adm-ragFileList').innerHTML = '';
  }
}

/** `B1453`. The index's own account of itself: how many chunks, which model
 *  embeds them — `GET /api/rag/stats`, which nothing called. */
async function loadRagStats() {
  const out = el('adm-ragStats');
  if (!out) return;
  try {
    const res = await fetch('/api/rag/stats', { credentials: 'same-origin' });
    const s = res.ok ? await res.json() : null;
    if (!s || s.error) { out.textContent = s && s.error ? `Index: ${s.error}` : ''; return; }
    const n = Number(s.document_count) || 0;
    out.textContent = `Index: ${n.toLocaleString()} chunk${n === 1 ? '' : 's'}`
      + (s.embedding_model && s.embedding_model !== 'N/A' ? ` · embedded with ${s.embedding_model}` : '');
  } catch (_) {
    out.textContent = '';
  }
}

/** `B1453`. Uploaded files: how many, how much, and the reference-safe
 *  cleanup of expired ones — `GET /api/upload/stats` and `POST
 *  /api/upload/cleanup`, which nothing called and nothing ran. */
async function loadUploads() {
  const out = el('adm-uploadsStats');
  if (!out) return;
  try {
    const res = await fetch('/api/upload/stats', { credentials: 'same-origin' });
    const s = res.ok ? await res.json() : null;
    if (!s || s.error) { out.textContent = 'Could not read the upload index.'; return; }
    const n = Number(s.total_files) || 0;
    out.textContent = `${n.toLocaleString()} file${n === 1 ? '' : 's'}, ${s.total_size_mb} MB. `
      + `"Remove expired uploads" deletes files older than ${s.cleanup_days} days that no chat, `
      + 'document or gallery item still uses.';
  } catch (_) {
    out.textContent = 'Could not read the upload index.';
  }
}

function initUploads() {
  const btn = el('adm-uploadsCleanBtn');
  const msg = el('adm-uploadsMsg');
  if (!btn || !msg) return;
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    msg.textContent = 'Checking every chat, document and gallery item first…';
    msg.style.color = '';
    try {
      const res = await fetch('/api/upload/cleanup', { method: 'POST', credentials: 'same-origin' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      const n = Number(data.files_cleaned) || 0;
      msg.textContent = n ? `Removed ${n} expired upload${n === 1 ? '' : 's'}.` : 'Nothing had expired.';
      loadUploads();
    } catch (e) {
      msg.textContent = String(e.message || e);
      msg.style.color = 'var(--red)';
    } finally {
      btn.disabled = false;
    }
  });
}

let _ragMsgTimer = null;
function ragMsg(text, isError, persist) {
  const s = el('adm-ragStatus');
  s.textContent = text; s.style.color = isError ? 'var(--red)' : 'var(--fg)';
  if (_ragMsgTimer) { clearTimeout(_ragMsgTimer); _ragMsgTimer = null; }
  if (text && !persist) _ragMsgTimer = setTimeout(() => { s.textContent = ''; }, 5000);
}

async function ragUpload(files) {
  if (!files || files.length === 0) return;
  ragMsg('Uploading ' + files.length + ' file(s)...', false, true);
  const fd = new FormData();
  for (const f of files) fd.append('files', f);
  try {
    const res = await fetch('/api/personal/upload', { method: 'POST', body: fd });
    const data = await res.json();
    if (data.success) { ragMsg(`Uploaded ${data.uploaded.length} file(s), ${data.indexed_count} chunks indexed`); loadRag(); }
    else ragMsg(data.detail || 'Upload failed', true);
  } catch (e) { ragMsg('Upload error: ' + e.message, true); }
}

function initRag() {
  const dropZone = el('adm-ragDropZone');
  const fileInput = el('adm-ragFileInput');
  dropZone.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => ragUpload(fileInput.files));
  dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
  dropZone.addEventListener('drop', e => { e.preventDefault(); dropZone.classList.remove('dragover'); ragUpload(e.dataTransfer.files); });
  el('adm-ragAddDirBtn').addEventListener('click', async () => {
    const dir = el('adm-ragDirInput').value.trim();
    if (!dir) return;
    const btn = el('adm-ragAddDirBtn');
    btn.disabled = true; btn.textContent = 'Indexing...';
    try {
      const res = await fetch('/api/personal/add_directory', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ directory: dir }) });
      const data = await res.json();
      if (data.success) { ragMsg(`Indexed ${data.indexed_count} chunks from directory`); el('adm-ragDirInput').value = ''; loadRag(); }
      else ragMsg(data.detail || data.message || 'Failed', true);
    } catch (e) { ragMsg('Error: ' + e.message, true); }
    btn.disabled = false; btn.textContent = 'Add Directory';
  });
  el('adm-ragReloadBtn').addEventListener('click', async () => {
    const btn = el('adm-ragReloadBtn');
    btn.disabled = true; btn.textContent = 'Reloading...';
    try {
      const res = await fetch('/api/personal/reload', { method: 'POST' });
      const data = await res.json();
      // `B1187`: a reload over an index that is off says so, and why.
      if (!res.ok) ragMsg(data.detail || `Reload failed (${res.status})`, true);
      else if (data.ok === false) ragMsg(`Re-read ${data.count} files, but ${data.reason || 'the knowledge index is off.'}`, true, true);
      else ragMsg(`Index reloaded: ${data.count} documents`);
      loadRag();
    } catch (e) { ragMsg('Reload failed: ' + e.message, true); }
    btn.disabled = false; btn.textContent = 'Reload Index';
  });
}

/* `B1524`. The admin API-token form (`initTokenForm`, `loadTokens`,
   `_TOKEN_SCOPES`) stood here and returned on `adm-token*` ids no template
   renders. A token is made, listed and revoked in Settings → MCP &
   Integrations (`settings.js` `showTokenForm`, `B1193`), which reads what a
   token may do from the server's own list (`GET /api/tokens/profiles`)
   rather than a copy of it. Deleted, as `B902` deleted the admin MCP form. */

/* ── Webhooks ── */
async function loadWebhooks() {
  const list = el('adm-whList');
  try {
    const res = await fetch('/api/webhooks', { credentials: 'same-origin' });
    const hooks = await res.json();
    if (!hooks.length) { list.innerHTML = '<div class="admin-empty">No webhooks configured</div>'; return; }
    list.innerHTML = hooks.map(w => {
      const events = (w.events || []).map(e => `<span class="admin-badge">${esc(e)}</span>`).join(' ');
      const statusBadge = w.last_status_code
        ? `<span class="admin-badge" style="background:${w.last_status_code < 400 ? 'color-mix(in srgb, var(--fg) 20%, transparent)' : 'color-mix(in srgb, var(--red) 20%, transparent)'};color:${w.last_status_code < 400 ? 'var(--fg)' : 'var(--red)'};">${w.last_status_code}</span>`
        : '';
      const lastTriggered = w.last_triggered_at ? new Date(w.last_triggered_at).toLocaleString() : 'Never';
      const errorText = w.last_error ? `<div style="font-size:0.75rem;color:var(--red);margin-top:0.2rem;">Error: ${esc(w.last_error.substring(0, 80))}</div>` : '';
      return `
        <div class="admin-ep-item" style="flex-wrap:wrap;">
          <div class="admin-ep-info" style="flex:1;min-width:200px;">
            <div class="admin-ep-name">${esc(w.name)} ${w.is_active ? '' : '<span class="admin-badge admin-badge-off">disabled</span>'} ${w.has_secret ? '<span class="admin-badge">signed</span>' : ''}</div>
            <div class="admin-ep-detail">${esc(w.url)}</div>
            <div style="margin-top:0.3rem;">${events}</div>
            <div class="admin-ep-detail">Last: ${lastTriggered} ${statusBadge}</div>
            ${errorText}
          </div>
          <div class="admin-ep-actions">
            <button class="admin-btn-sm" data-adm-wh-test="${w.id}">Test</button>
            <button class="admin-btn-sm" data-adm-wh-toggle="${w.id}">${w.is_active ? 'Disable' : 'Enable'}</button>
            <button class="admin-btn-delete" data-adm-wh-delete="${w.id}">Delete</button>
          </div>
        </div>`;
    }).join('');
    list.querySelectorAll('[data-adm-wh-test]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const msg = el('adm-whMsg'); msg.textContent = 'Sending test...'; msg.className = '';
        try {
          const res = await fetch(`/api/webhooks/${btn.dataset.admWhTest}/test`, { method: 'POST', credentials: 'same-origin' });
          msg.textContent = res.ok ? 'Test sent!' : 'Test failed'; msg.className = res.ok ? 'admin-success' : 'admin-error';
          setTimeout(() => loadWebhooks(), 1000);
        } catch (e) { msg.textContent = 'Failed: ' + e.message; msg.className = 'admin-error'; }
      });
    });
    list.querySelectorAll('[data-adm-wh-toggle]').forEach(btn => {
      btn.addEventListener('click', async () => { await fetch(`/api/webhooks/${btn.dataset.admWhToggle}`, { method: 'PATCH', credentials: 'same-origin' }); loadWebhooks(); });
    });
    list.querySelectorAll('[data-adm-wh-delete]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!await uiModule.styledConfirm('Delete this webhook?', { confirmText: 'Delete', danger: true })) return;
        await fetch(`/api/webhooks/${btn.dataset.admWhDelete}`, { method: 'DELETE', credentials: 'same-origin' }); loadWebhooks();
      });
    });
  } catch (e) { list.innerHTML = '<div class="admin-error">Failed to load webhooks</div>'; }
}

function initWebhookForm() {
  el('adm-whAddBtn').addEventListener('click', async () => {
    const msg = el('adm-whMsg');
    msg.textContent = ''; msg.className = '';
    const name = el('adm-whName').value.trim();
    const url = el('adm-whUrl').value.trim();
    const secret = el('adm-whSecret').value.trim();
    const events = Array.from(modalEl.querySelectorAll('.adm-wh-event:checked')).map(e => e.value).join(',');
    if (!name) { msg.textContent = 'Name is required'; msg.className = 'admin-error'; return; }
    if (!url) { msg.textContent = 'URL is required'; msg.className = 'admin-error'; return; }
    if (!events) { msg.textContent = 'Select at least one event'; msg.className = 'admin-error'; return; }
    const fd = new FormData();
    fd.append('name', name); fd.append('url', url); fd.append('secret', secret); fd.append('events', events);
    try {
      const res = await fetch('/api/webhooks', { method: 'POST', body: fd, credentials: 'same-origin' });
      if (res.ok) { msg.textContent = 'Webhook added'; msg.className = 'admin-success'; el('adm-whName').value = ''; el('adm-whUrl').value = ''; el('adm-whSecret').value = ''; loadWebhooks(); }
      else { const d = await res.json(); msg.textContent = d.detail || 'Failed'; msg.className = 'admin-error'; }
    } catch (e) { msg.textContent = 'Failed: ' + e.message; msg.className = 'admin-error'; }
  });
}

/* ── Features — *Switched on for everyone* ── */
const featureLabels = {
  web_search: 'Web Search', deep_research: 'Deep Research',
  memory: 'Brain (memories)', document_editor: 'Document Editor', rag: 'RAG Knowledge Base', sensitive_filter: 'Sensitive Info Filter',
  gallery: 'Gallery',
  // `B1488`, the owner's ruling: the eight Tools entries `B1191` gave a
  // person's switch have one for everyone too (`src/tool_privileges.py`).
  assistant: 'Assistant', calendar: 'Calendar', compare: 'Compare', email: 'Email',
  notes: 'Notes', tasks: 'Tasks', theme: 'Theme', workbench: 'Workbench',
};

// `B1488`. What a switch for everyone holds besides its door — the everyone
// column of `PRIV_TAKES` above: held, never deleted, and running again once
// it is back on (`tool_privileges.paused_sentence`).
const FEATURE_TAKES = {
  assistant: 'Off also holds the Assistant\'s check-ins.',
  calendar: 'Off also holds the calendar work in scheduled tasks.',
  email: 'Off also holds every inbox check, mail scheduled to send, and email actions.',
  notes: 'Off also holds note reminders.',
  tasks: 'Off also holds every scheduled task; each says why, and runs again once it is back on.',
  workbench: 'Off also holds every workflow.',
};

/** `P23-03` (SET-U-1). "Off hides Brain." — the Tools entries (and composer
 *  buttons) a switch takes away, read from the one table, so a row cannot
 *  claim something the applier does not do. Empty when it hides nothing.
 *  `B1194`: the sentence moved into the table's module (`hidesLine`), so
 *  Settings → Appearance says the Library's in the same words — and it says
 *  what a switch leaves standing: *Document editor* hides documents, never
 *  the chat archive. */
function _hidesLine(which) {
  return hidesLine(which);
}

/**
 * One *Switched on for everyone* switch.
 *
 * `SET-M-10` / `SET-M-12` (P23-03). It posted and said nothing, kept a refused
 * switch flipped, and changed nothing on the admin's own page until a reload.
 * Now the page applies the answer at once (`window.applyFeatureFlags`, the
 * load path's applier) and says so, and a refusal puts the switch back.
 */
async function _saveFeature(toggle) {
  const key = toggle.dataset.admFeature;
  const body = {}; body[key] = toggle.checked;
  try {
    const r = await fetch('/api/auth/features', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) {
      toggle.checked = !toggle.checked;
      uiModule.showError((await readRefusal(r, 'Not saved.')).sentence);
      return false;
    }
    const now = await r.json().catch(() => null);
    if (typeof window.applyFeatureFlags === 'function') window.applyFeatureFlags(now || { [key]: toggle.checked });
    uiModule.showToast(`${featureLabels[key] || key} ${toggle.checked ? 'on' : 'off'} for everyone. Others see it after their next reload.`);
    return true;
  } catch (e) {
    toggle.checked = !toggle.checked;
    uiModule.showError('Not saved: Pantheon did not answer.');
    return false;
  }
}

async function loadFeatures() {
  const container = el('adm-featureToggles');
  if (!container) return;
  try {
    const res = await fetch('/api/auth/features', { credentials: 'same-origin' });
    const features = await res.json();
    container.innerHTML = Object.entries(featureLabels).map(([key, label]) => {
      const hides = [_hidesLine({ feature: key }), FEATURE_TAKES[key]].filter(Boolean).join(' ');
      return `
      <div class="admin-toggle-row" style="padding:0.4rem 0;border-bottom:1px solid var(--border);">
        <div class="admin-toggle-label">${label}${hides ? `<div class="admin-toggle-sub" style="font-size:11px;opacity:0.6;">${esc(hides)}</div>` : ''}</div>
        <label class="admin-switch"><input type="checkbox" data-adm-feature="${key}" ${features[key] ? 'checked' : ''} aria-label="${esc(label)}"><span class="admin-slider"></span></label>
      </div>`;
    }).join('');
    container.querySelectorAll('input[data-adm-feature]').forEach(toggle => {
      toggle.addEventListener('change', () => _saveFeature(toggle));
    });
  } catch (e) { container.innerHTML = '<div class="admin-error">Failed to load features</div>'; }
}

/* ── CalDAV Config ── */
function initCalDAV() {
  const urlIn = el('caldav-url');
  const userIn = el('caldav-user');
  const passIn = el('caldav-pass');
  const saveBtn = el('caldav-save-btn');
  const testBtn = el('caldav-test-btn');
  const status = el('caldav-status');
  if (!urlIn || !saveBtn) return;

  // Load current config
  fetch(`${API_BASE}/api/calendar/config`, { credentials: 'same-origin' })
    .then(r => r.json()).then(d => {
      urlIn.value = d.caldav_url || '';
      userIn.value = d.caldav_username || '';
      passIn.value = d.caldav_password || '';
    }).catch(() => {});

  saveBtn.addEventListener('click', async () => {
    status.textContent = 'Saving...';
    try {
      const res = await fetch(`${API_BASE}/api/calendar/config`, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ caldav_url: urlIn.value, caldav_username: userIn.value, caldav_password: passIn.value }),
      });
      const d = await res.json();
      status.textContent = d.ok ? 'Saved' : 'Error';
      status.style.color = d.ok ? 'var(--green)' : 'var(--red)';
    } catch (e) { status.textContent = 'Error'; status.style.color = 'var(--red)'; }
    setTimeout(() => { status.textContent = ''; status.style.color = ''; }, 3000);
  });

  testBtn.addEventListener('click', async () => {
    status.textContent = 'Testing...';
    try {
      // Save first
      await fetch(`${API_BASE}/api/calendar/config`, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ caldav_url: urlIn.value, caldav_username: userIn.value, caldav_password: passIn.value }),
      });
      const res = await fetch(`${API_BASE}/api/calendar/test`, { method: 'POST', credentials: 'same-origin' });
      const d = await res.json();
      status.textContent = d.ok ? `Connected (${d.calendars} calendars)` : `Failed: ${d.error}`;
      status.style.color = d.ok ? 'var(--green)' : 'var(--red)';
    } catch (e) { status.textContent = 'Error'; status.style.color = 'var(--red)'; }
    setTimeout(() => { status.textContent = ''; status.style.color = ''; }, 5000);
  });
}

/* ── Storage cleanup (H10) ──

   `GET /api/cleanup/preview` and `POST /api/cleanup` have existed, owner-scoped
   and with a real dry run, with no caller in `static/` at all. The dry run is
   the whole reason this is worth wiring rather than leaving to the Danger Zone:
   it returns the sessions it would archive, the ones it would delete, AND the
   ones it is sparing WITH THE REASON — "part of last 10 sessions", "has 20+
   messages", "contains keyword: important". A person deciding whether to free
   340 MB wants to see what survives at least as much as what goes.

   Rendered with createElement and textContent throughout. Session names are
   user-supplied and go straight into this list; `innerHTML` here would be an
   XSS hole with a chat title as the payload. */
let _cleanupPreview = null;

function _cleanupRow(session, extra) {
  const row = document.createElement('div');
  row.style.cssText = 'display:flex;gap:8px;align-items:baseline;padding:2px 0;';
  const name = document.createElement('span');
  name.style.cssText = 'flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
  name.textContent = session.name || '(untitled)';
  const meta = document.createElement('span');
  meta.style.cssText = 'opacity:0.55;font-size:11px;flex-shrink:0;';
  meta.textContent = extra;
  row.append(name, meta);
  return row;
}

function _cleanupGroup(title, sessions, describe) {
  const box = document.createElement('div');
  box.style.cssText = 'margin-top:10px;';
  const head = document.createElement('div');
  head.style.cssText = 'font-size:12px;font-weight:600;margin-bottom:2px;';
  head.textContent = `${title} (${sessions.length})`;
  box.appendChild(head);
  if (!sessions.length) {
    const none = document.createElement('div');
    none.style.cssText = 'opacity:0.5;font-size:11px;';
    none.textContent = 'none';
    box.appendChild(none);
    return box;
  }
  const list = document.createElement('div');
  list.style.cssText = 'max-height:180px;overflow-y:auto;font-size:12px;';
  for (const session of sessions) list.appendChild(_cleanupRow(session, describe(session)));
  box.appendChild(list);
  return box;
}

function _renderCleanupPreview(data) {
  const host = el('adm-cleanupPreview');
  if (!host) return;
  host.textContent = '';

  const archive = data.sessions_to_archive || [];
  const remove = data.sessions_to_delete || [];
  const kept = data.preserved_sessions || [];

  const summary = document.createElement('div');
  summary.style.cssText = 'font-size:12px;margin-bottom:2px;';
  summary.textContent = remove.length
    ? `Would free about ${data.estimated_space_freed_mb} MB by deleting ${remove.length} `
      + `chat${remove.length === 1 ? '' : 's'}, and archive ${archive.length}.`
    : `Nothing to delete. ${archive.length} chat${archive.length === 1 ? '' : 's'} would be archived.`;
  host.appendChild(summary);

  const plural = (n) => `${n} message${n === 1 ? '' : 's'}`;
  host.appendChild(_cleanupGroup('To archive', archive, (x) => plural(x.message_count)));
  host.appendChild(_cleanupGroup('To delete', remove,
    (x) => `${plural(x.message_count)} · ${x.estimated_size_kb} KB`));
  // The reason is the point of this group, so it is what gets shown.
  host.appendChild(_cleanupGroup('Kept', kept, (x) => x.reason || 'kept'));

  host.hidden = false;
}

function initCleanup() {
  const previewBtn = el('adm-cleanupPreviewBtn');
  const runBtn = el('adm-cleanupRunBtn');
  const msg = el('adm-cleanupMsg');
  if (!previewBtn || !runBtn || !msg) return;

  previewBtn.addEventListener('click', async () => {
    previewBtn.disabled = true;
    msg.textContent = 'Checking…';
    msg.style.color = '';
    try {
      const res = await fetch('/api/cleanup/preview', { credentials: 'same-origin' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      _cleanupPreview = await res.json();
      _renderCleanupPreview(_cleanupPreview);
      const total = (_cleanupPreview.sessions_to_archive || []).length
                  + (_cleanupPreview.sessions_to_delete || []).length;
      msg.textContent = total ? '' : 'Nothing to clean up.';
      // Nothing to do is not a state that should offer to do it.
      runBtn.hidden = total === 0;
    } catch (e) {
      msg.textContent = 'Could not read the cleanup preview.';
      msg.style.color = 'var(--red)';
    } finally {
      previewBtn.disabled = false;
    }
  });

  runBtn.addEventListener('click', async () => {
    if (!_cleanupPreview) return;
    const remove = (_cleanupPreview.sessions_to_delete || []).length;
    const archive = (_cleanupPreview.sessions_to_archive || []).length;
    // Deletion is the irreversible half, so it leads the sentence and the
    // dialog is `danger` only when something is actually going to be deleted.
    const detail = remove
      ? `Delete ${remove} chat${remove === 1 ? '' : 's'} and archive ${archive}? `
        + 'Deleted chats cannot be recovered.'
      : `Archive ${archive} chat${archive === 1 ? '' : 's'}? Nothing will be deleted.`;
    const ok = await uiModule.styledConfirm(detail, {
      title: 'Run cleanup',
      confirmText: remove ? 'Delete and archive' : 'Archive',
      danger: Boolean(remove),
    });
    if (!ok) return;

    runBtn.disabled = true;
    msg.textContent = 'Cleaning up…';
    msg.style.color = '';
    try {
      const res = await fetch('/api/cleanup', { method: 'POST', credentials: 'same-origin' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const d = await res.json();
      msg.textContent = `Archived ${d.archived_count}, deleted ${d.deleted_count}, `
        + `freed ${d.space_freed_mb} MB.`;
      msg.style.color = 'var(--green)';
      // The preview now describes a world that no longer exists.
      _cleanupPreview = null;
      el('adm-cleanupPreview').hidden = true;
      runBtn.hidden = true;
      try { window.sessionModule?.loadSessions?.(); } catch (_) { /* the list will catch up on its own */ }
    } catch (e) {
      msg.textContent = 'Cleanup failed.';
      msg.style.color = 'var(--red)';
    } finally {
      runBtn.disabled = false;
    }
  });
}

/* ── Data Backup (export/import) ── */
function initBackup() {
  el('adm-exportDataBtn').addEventListener('click', async () => {
    const btn = el('adm-exportDataBtn');
    const msg = el('adm-backupMsg');
    btn.disabled = true; btn.textContent = 'Exporting...'; msg.textContent = '';
    try {
      const res = await fetch('/api/export', { credentials: 'same-origin' });
      if (!res.ok) throw new Error('Export failed');
      const blob = await res.blob();
      const disposition = res.headers.get('Content-Disposition') || '';
      const match = disposition.match(/filename=(.+)/);
      const filename = match ? match[1] : 'pantheon_backup.json';
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      a.click();
      URL.revokeObjectURL(a.href);
      msg.textContent = 'Export downloaded.'; msg.className = 'admin-success';
    } catch (e) { msg.textContent = 'Export failed: ' + e.message; msg.className = 'admin-error'; }
    btn.disabled = false; btn.textContent = 'Export Data';
  });

  const fileInput = el('adm-importFile');
  el('adm-importDataBtn').addEventListener('click', () => { fileInput.value = ''; fileInput.click(); });
  fileInput.addEventListener('change', async () => {
    const file = fileInput.files[0];
    if (!file) return;
    const msg = el('adm-backupMsg');
    const btn = el('adm-importDataBtn');
    btn.disabled = true; btn.textContent = 'Importing...'; msg.textContent = '';
    try {
      const text = (await file.text()).replace(/^\uFEFF/, '').trim();
      let data;
      try {
        data = JSON.parse(text);
      } catch (e) {
        throw new Error('Invalid backup file: ' + e.message);
      }
      const res = await fetch('/api/import', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      const result = await res.json().catch(() => null);
      if (!result) {
        throw new Error(`Import failed: server returned ${res.status}`);
      }
      if (res.ok && result.ok) {
        msg.textContent = result.message || 'Import successful.'; msg.className = 'admin-success';
      } else {
        msg.textContent = result.message || result.detail || 'Import failed'; msg.className = 'admin-error';
      }
    } catch (e) { msg.textContent = 'Import failed: ' + e.message; msg.className = 'admin-error'; }
    btn.disabled = false; btn.textContent = 'Import Data';
  });
}

/* ── Danger Zone ── */
function initDangerZone() {
  // Per-category Danger Zone wipes. Each button declares its target
  // via data-wipe-kind; one delegated handler handles double-confirm,
  // POSTs to /api/admin/wipe/{kind}, and writes the result.
  const _LABELS = {
    chats: 'chats', memory: 'memory entries', skills: 'skills',
    notes: 'notes', tasks: 'tasks', documents: 'documents',
    gallery: 'gallery images', calendar: 'calendar items',
  };
  const _wipeMsg = el('adm-wipeMsg');
  modalEl.querySelectorAll('[data-wipe-kind]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const kind = btn.dataset.wipeKind;
      const isAll = kind === '__all__';
      const label = isAll ? 'data across every category' : (_LABELS[kind] || kind);
      if (!await uiModule.styledConfirm(`Delete ALL ${label}? This cannot be undone.`, { confirmText: 'Delete', danger: true })) return;
      if (!await uiModule.styledConfirm(`Really delete every one of your ${label}?`, { confirmText: isAll ? 'Yes, delete everything' : 'Yes, delete everything', danger: true })) return;
      btn.disabled = true;
      const prevHtml = btn.innerHTML;
      btn.innerHTML = isAll ? 'Deleting all…' : 'Deleting…';
      if (_wipeMsg) { _wipeMsg.textContent = ''; _wipeMsg.className = ''; }
      try {
        if (isAll) {
          // Iterate every known category. Failures in one shouldn't stop
          // the rest — record per-category counts and surface a summary.
          const kinds = Object.keys(_LABELS);
          const results = [];
          for (const k of kinds) {
            try {
              const r = await fetch(`/api/admin/wipe/${k}`, { method: 'DELETE', credentials: 'same-origin' });
              const d = await r.json().catch(() => ({}));
              results.push({ k, ok: r.ok, count: d.count ?? 0, error: r.ok ? null : (d.detail || 'failed') });
            } catch (e) {
              results.push({ k, ok: false, count: 0, error: e.message });
            }
          }
          const okCount = results.filter(r => r.ok).length;
          const total = results.reduce((n, r) => n + (r.ok ? r.count : 0), 0);
          const fails = results.filter(r => !r.ok).map(r => r.k);
          if (_wipeMsg) {
            if (!fails.length) {
              _wipeMsg.textContent = `Deleted ${total} items across all ${okCount} categories.`;
              _wipeMsg.className = 'admin-success';
            } else {
              _wipeMsg.textContent = `Deleted ${total} items; failed: ${fails.join(', ')}.`;
              _wipeMsg.className = 'admin-error';
            }
          }
        } else {
          const res = await fetch(`/api/admin/wipe/${kind}`, { method: 'DELETE', credentials: 'same-origin' });
          const data = await res.json().catch(() => ({}));
          if (res.ok) {
            if (_wipeMsg) { _wipeMsg.textContent = `Deleted ${data.count ?? 0} ${label}.`; _wipeMsg.className = 'admin-success'; }
          } else {
            if (_wipeMsg) { _wipeMsg.textContent = data.detail || 'Failed'; _wipeMsg.className = 'admin-error'; }
          }
        }
      } catch (e) {
        if (_wipeMsg) { _wipeMsg.textContent = 'Request failed: ' + e.message; _wipeMsg.className = 'admin-error'; }
      }
      btn.disabled = false; btn.innerHTML = prevHtml;
    });
  });
}

/* ═══════════════════════════════════════════
   TERMINAL LOGS VIEWER
   ═══════════════════════════════════════════ */
let logsPollInterval = null;
let isLogsPolling = false;
let cachedLogs = [];
let logsAbortController = null;

function renderLogs(isAutoPoll = false) {
  const consoleContainer = el('log-console-container');
  const levelSelect = el('log-level-select');
  const searchInput = el('log-search-input');

  if (!consoleContainer) return;

  const levelFilter = levelSelect ? levelSelect.value : 'ALL';
  const searchQuery = searchInput ? searchInput.value.trim().toLowerCase() : '';

  let logs = cachedLogs;

  // Filter by level locally
  if (levelFilter !== 'ALL') {
    logs = logs.filter(line => line.includes(` - ${levelFilter} - `));
  }

  // Filter by search query locally
  if (searchQuery) {
    logs = logs.filter(line => line.toLowerCase().includes(searchQuery));
  }

  if (logs.length === 0) {
    consoleContainer.innerHTML = '<div class="settings-system-logs-placeholder">No logs found matching current filters.</div>';
    return;
  }

  // Preserve scroll position if user is reading previous logs
  const atBottom = consoleContainer.scrollHeight - consoleContainer.scrollTop - consoleContainer.clientHeight < 40;

  consoleContainer.innerHTML = logs.map(line => {
    let levelClass = 'log-line-default';

    if (line.includes(' - INFO - ')) {
      levelClass = 'log-line-info';
    } else if (line.includes(' - WARNING - ')) {
      levelClass = 'log-line-warning';
    } else if (line.includes(' - ERROR - ') || line.includes(' - CRITICAL - ')) {
      levelClass = 'log-line-error';
    } else if (line.includes(' - DEBUG - ')) {
      levelClass = 'log-line-debug';
    }

    // XSS safe escape
    const escaped = line
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');

    return `<div class="log-line ${levelClass}">${escaped}</div>`;
  }).join('');

  if (!isAutoPoll || atBottom) {
    consoleContainer.scrollTop = consoleContainer.scrollHeight;
  }
}

// ---------------------------------------------------------------------------
// Self-checks — what is quietly wrong (P16-15)
// ---------------------------------------------------------------------------
//
// Rendered ABOVE the log console on purpose. The whole lesson of H01 is that
// nobody reads a log to discover a problem they do not know they have: a year
// of agent-written email sat staged and invisible while the mail server was
// reachable the entire time. A count in front of a person is the fix.
//
// Built with DOM calls rather than innerHTML: every string here comes from
// server-side state, some of it derived from mail and host names, and this
// panel exists to report trouble — the one surface where an injected string is
// most likely to arrive.
async function loadSelfChecks() {
  const panel = el('self-check-panel');
  if (!panel) return;

  let data;
  try {
    const res = await fetch('/api/diagnostics/self-check', { credentials: 'same-origin' });
    if (!res.ok) { panel.hidden = true; return; }
    data = await res.json();
  } catch (_e) {
    panel.hidden = true;   // never let a diagnostic break the page it sits on
    return;
  }

  // Liveness, from the report that already existed and had no caller (P16-17).
  // Fetched alongside rather than instead: the two answer different questions,
  // and H01 is the proof that you need both — the mail server was reachable the
  // entire time a year of email sat staged and invisible.
  let services = [];
  try {
    const sres = await fetch('/api/diagnostics/services', { credentials: 'same-origin' });
    if (sres.ok) {
      const sdata = await sres.json();
      services = (sdata && Array.isArray(sdata.services) ? sdata.services : [])
        .filter((s) => s && s.status && s.status !== 'ok');
    }
  } catch (_e) { /* liveness is best-effort; the state checks above still render */ }

  panel.textContent = '';
  const rows = (data && Array.isArray(data.needs_attention)) ? data.needs_attention : [];

  if (!rows.length && !services.length) {
    const ok = document.createElement('div');
    ok.className = 'self-check-allclear';
    const n = (data && Array.isArray(data.checks)) ? data.checks.length : 0;
    ok.textContent = `${n} self-check${n === 1 ? '' : 's'} passed — nothing accumulating, nothing given up, every service answering.`;
    panel.appendChild(ok);
    panel.hidden = false;
    return;
  }

  for (const c of rows) {
    const row = document.createElement('div');
    row.className = 'self-check-row is-' + String(c.status || 'unknown');

    const body = document.createElement('div');
    const title = document.createElement('div');
    title.className = 'self-check-title';
    title.textContent = String(c.title || c.name || 'Check');
    body.appendChild(title);

    const summary = document.createElement('p');
    summary.className = 'self-check-summary';
    summary.textContent = String(c.summary || '');
    body.appendChild(summary);

    if (c.action) {
      const action = document.createElement('p');
      action.className = 'self-check-action';
      action.textContent = String(c.action);
      body.appendChild(action);
    }
    row.appendChild(body);

    if (c.count) {
      const count = document.createElement('div');
      count.className = 'self-check-count';
      count.textContent = String(c.count);
      row.appendChild(count);
    }
    panel.appendChild(row);
  }

  // Reachability, after state. That order is the point: something can be
  // perfectly reachable and still quietly broken, and the reverse is obvious
  // the moment you try to use it.
  for (const svc of services) {
    const row = document.createElement('div');
    row.className = 'self-check-row is-' + (svc.status === 'down' ? 'stuck' : 'attention');

    const body = document.createElement('div');
    const title = document.createElement('div');
    title.className = 'self-check-title';
    // `COPY-U-44` (P23-03): "chromadb — not answering" named a library.
    title.textContent = `${_SERVICE_NAMES[svc.name] || String(svc.name)} — ${svc.status === 'down' ? 'down' : 'degraded'}`;
    body.appendChild(title);

    const summary = document.createElement('p');
    summary.className = 'self-check-summary';
    summary.textContent = String(svc.detail || '');
    body.appendChild(summary);
    row.appendChild(body);
    panel.appendChild(row);
  }
  panel.hidden = false;
}

/** The services `src/service_health.py` reports, by what a person knows them as. */
const _SERVICE_NAMES = { chromadb: 'Vector store', searxng: 'SearXNG' };

// ---------------------------------------------------------------------------
// Usage over time (P14-05)
// ---------------------------------------------------------------------------
//
// The question that started P14: not "what has this session cost" — the session
// row always knew that — but "what did last Tuesday cost, and is this model
// cheaper than that one". Until P14-01 the timestamp was discarded at write, so
// there was nothing to draw.
//
// Bars are inline SVG built with DOM calls. No charting library: this is one
// series of daily totals, and vendoring a library to draw rectangles would be a
// third-party dependency for something the browser already does. Every string
// here is server-derived — model names, owner names — so textContent, never
// innerHTML.

function usageBars(buckets, host) {
  const max = Math.max(1, ...buckets.map(b => b.input_tokens + b.output_tokens));
  const w = 100 / Math.max(1, buckets.length);
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 100 30');
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.setAttribute('class', 'usage-chart');
  svg.setAttribute('role', 'img');

  const total = buckets.reduce((n, b) => n + b.rounds, 0);
  const label = document.createElementNS('http://www.w3.org/2000/svg', 'title');
  // The accessible name carries the numbers, because a chart nobody can read
  // aloud is a chart that excludes people from the only place this data lives.
  label.textContent = `${total} rounds over ${buckets.length} days, `
    + `${buckets[0] ? buckets[0].day : ''} to `
    + `${buckets.length ? buckets[buckets.length - 1].day : ''}`;
  svg.appendChild(label);

  buckets.forEach((b, i) => {
    const value = b.input_tokens + b.output_tokens;
    const h = value ? Math.max(0.6, (value / max) * 28) : 0;
    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    rect.setAttribute('x', (i * w + w * 0.12).toFixed(3));
    rect.setAttribute('y', (29 - h).toFixed(3));
    rect.setAttribute('width', (w * 0.76).toFixed(3));
    rect.setAttribute('height', h.toFixed(3));
    rect.setAttribute('class', value ? 'usage-bar' : 'usage-bar is-empty');
    const tip = document.createElementNS('http://www.w3.org/2000/svg', 'title');
    tip.textContent = `${b.day}: ${b.rounds} round${b.rounds === 1 ? '' : 's'}, `
      + `${value.toLocaleString()} tokens`;
    rect.appendChild(tip);
    svg.appendChild(rect);
  });
  host.appendChild(svg);
}

function usageTable(rows, columns, host) {
  const table = document.createElement('table');
  table.className = 'usage-table';
  const thead = document.createElement('thead');
  const hr = document.createElement('tr');
  columns.forEach(c => {
    const th = document.createElement('th');
    th.textContent = c.label;
    if (c.numeric) th.className = 'is-num';
    hr.appendChild(th);
  });
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = document.createElement('tbody');
  rows.forEach(row => {
    const tr = document.createElement('tr');
    columns.forEach(c => {
      const td = document.createElement('td');
      const value = row[c.key];
      td.textContent = c.numeric && typeof value === 'number'
        ? value.toLocaleString() : String(value ?? '');
      if (c.numeric) td.className = 'is-num';
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  host.appendChild(table);
}

async function loadUsage() {
  const body = el('usage-body');
  if (!body) return;
  const range = el('usage-range');
  const days = range ? range.value : 30;

  body.textContent = 'Loading…';
  let data;
  try {
    const res = await fetch(`/api/diagnostics/usage?days=${encodeURIComponent(days)}`,
                            { credentials: 'same-origin' });
    if (!res.ok) { body.textContent = `Could not load usage (HTTP ${res.status}).`; return; }
    data = await res.json();
  } catch (_e) {
    body.textContent = 'Could not reach this Pantheon.';
    return;
  }

  const series = (data && data.over_time) || {};
  const buckets = Array.isArray(series.buckets) ? series.buckets : [];
  body.textContent = '';

  if (!buckets.some(b => b.rounds)) {
    // Not an error, and it should not look like one. A fresh install has no
    // history, and saying "nothing yet" beats an empty chart that reads as
    // broken.
    const empty = document.createElement('p');
    empty.className = 'usage-empty';
    empty.textContent = 'No model rounds recorded in this window yet. '
      + 'Usage is recorded from the first message after this build.';
    body.appendChild(empty);
    return;
  }

  const head = document.createElement('p');
  head.className = 'usage-headline';
  head.textContent = `${(data.rounds || 0).toLocaleString()} rounds · `
    + `${(data.input_tokens || 0).toLocaleString()} in · `
    + `${(data.output_tokens || 0).toLocaleString()} out`
    + (data.errors ? ` · ${data.errors} failed` : '');
  body.appendChild(head);

  usageBars(buckets, body);

  const axis = document.createElement('p');
  axis.className = 'usage-axis';
  axis.textContent = `${buckets[0].day} → ${buckets[buckets.length - 1].day} (UTC days)`;
  body.appendChild(axis);

  if (Array.isArray(series.models) && series.models.length) {
    const h = document.createElement('h4');
    h.className = 'usage-subhead';
    h.textContent = 'By model';
    body.appendChild(h);
    usageTable(series.models, [
      { key: 'model', label: 'Model' },
      { key: 'rounds', label: 'Rounds', numeric: true },
      { key: 'input_tokens', label: 'In', numeric: true },
      { key: 'output_tokens', label: 'Out', numeric: true },
      { key: 'avg_ms', label: 'Avg ms', numeric: true },
    ], body);
  }

  // Only when there is more than one, because a single-user install does not
  // need a table to tell it who the user is.
  if (Array.isArray(series.owners) && series.owners.length > 1) {
    const h = document.createElement('h4');
    h.className = 'usage-subhead';
    h.textContent = 'By owner';
    body.appendChild(h);
    usageTable(series.owners, [
      { key: 'owner', label: 'Owner' },
      { key: 'rounds', label: 'Rounds', numeric: true },
      { key: 'input_tokens', label: 'In', numeric: true },
      { key: 'output_tokens', label: 'Out', numeric: true },
    ], body);
  }
}

// `B490` / `B684`. Two more panels of the usage panel's shape — a query each,
// so loaded on open and not before — whose code lives in its own module, which
// is imported the first time either is opened.
const _LAZY_PANELS = [
  ['evals-panel', () => import('./evalsPanel.js')],
  ['auth-audit-panel', () => import('./authAudit.js')],
];

function setupLazyPanels() {
  for (const [id, load] of _LAZY_PANELS) {
    const panel = el(id);
    if (!panel) continue;
    panel.addEventListener('toggle', () => {
      if (!panel.open) return;
      load().then((m) => m.open()).catch((e) => {
        console.error(`${id} did not load:`, e);
        uiModule.showError('That panel did not load. Reload the page and try again.');
      });
    });
  }
}

function setupUsagePanel() {
  const panel = el('usage-panel');
  if (!panel) return;
  const range = el('usage-range');
  // Load on first open, not on page load: it is a query over the events table
  // and nobody opening Settings for a theme should pay for it.
  panel.addEventListener('toggle', () => { if (panel.open) loadUsage(); });
  if (range) range.addEventListener('change', () => { if (panel.open) loadUsage(); });
}

// ---------------------------------------------------------------------------
// Report a bug (P16-14)
// ---------------------------------------------------------------------------
//
// The obstacle to bug reports is not a missing pipe. It is that people do not
// know what to include, and are afraid of leaking their own data — and here
// that fear is correct: a trace from this product carries the username in every
// file path, the LAN in every endpoint, and often a slice of the message that
// caused it.
//
// So the report is assembled, redacted, and shown IN FULL in an editable box
// before anything happens to it. Nothing in this file sends it anywhere. The
// "open issue tracker" control is an <a> the person clicks — a navigation, not
// a fetch — and it carries no report with it; they paste what they chose to
// keep. That is Law 16 satisfied by design rather than by volume.

// Built with textContent and DOM calls: every string below is server-derived,
// and this panel's entire job is displaying trouble.
const PROJECT_ISSUES_URL = 'https://github.com/ImPanick/pantheon/issues';

function setupBugReport() {
  const root = el('bug-report');
  if (!root) return;
  const buildBtn = el('bug-report-build');
  const copyBtn = el('bug-report-copy');
  const issueLink = el('bug-report-issue');
  const noteBox = el('bug-report-note');
  const output = el('bug-report-output');
  const status = el('bug-report-status');
  if (!buildBtn || !output || !status) return;

  function say(message, isError) {
    status.textContent = message || '';
    status.classList.toggle('is-error', Boolean(isError));
  }

  buildBtn.addEventListener('click', async () => {
    buildBtn.disabled = true;
    say('Assembling and redacting…');
    try {
      const note = noteBox ? noteBox.value : '';
      const res = await fetch(
        '/api/diagnostics/bundle?note=' + encodeURIComponent(note),
        { credentials: 'same-origin' }
      );
      if (!res.ok) { say(`Could not assemble the report (HTTP ${res.status}).`, true); return; }
      const data = await res.json();
      if (!data || typeof data.markdown !== 'string') {
        say('The report came back in a shape this page does not understand.', true);
        return;
      }
      output.value = data.markdown;
      output.hidden = false;
      if (copyBtn) copyBtn.hidden = false;
      if (issueLink) {
        // A configured tracker wins; otherwise this project's own. Either way
        // it is a link, and it carries no report — the person pastes what they
        // decided to keep, which is the only version that ever leaves.
        issueLink.href = (data.issue_url || PROJECT_ISSUES_URL);
        issueLink.hidden = false;
      }
      say('Ready. Read it, edit anything you would rather not share, then copy.');
    } catch (_e) {
      say('Could not reach this Pantheon to assemble the report.', true);
    } finally {
      buildBtn.disabled = false;
    }
  });

  if (copyBtn) {
    copyBtn.addEventListener('click', async () => {
      // Deliberately copies output.value, not the fetched markdown: the edits
      // the person made are the point of showing it to them.
      // `B59`. The graceful degradation below is kept — selecting the text and
      // telling the person to press Ctrl+C is a better answer than a toast —
      // and only the mechanism moves to the shared helper.
      if (await uiModule.copyText(output.value)) {
        say('Copied. Paste it into an issue.');
      } else {
        output.focus();
        output.select();
        say('Clipboard unavailable — the report is selected, press Ctrl/Cmd+C.', true);
      }
    });
  }
}

async function loadLogs(isAutoPoll = false) {
  const consoleContainer = el('log-console-container');
  const limitSelect = el('log-limit-select');

  if (!consoleContainer) return;

  const limit = limitSelect ? limitSelect.value : 200;

  if (logsAbortController) {
    logsAbortController.abort();
  }
  logsAbortController = new AbortController();
  const { signal } = logsAbortController;

  try {
    const res = await fetch(`/api/diagnostics/logs?limit=${limit}`, {
      credentials: 'same-origin',
      signal
    });

    if (!res.ok) {
      if (!isAutoPoll) {
        consoleContainer.innerHTML = '';
        const errDiv = document.createElement('div');
        errDiv.style.color = 'var(--red)';
        errDiv.style.fontWeight = '600';
        errDiv.textContent = `Failed to load logs: HTTP ${res.status}`;
        consoleContainer.appendChild(errDiv);
      }
      return;
    }

    const data = await res.json();
    if (data.status !== 'success' || !data.logs) {
      if (!isAutoPoll) {
        consoleContainer.innerHTML = '';
        const errDiv = document.createElement('div');
        errDiv.style.color = 'var(--red)';
        errDiv.style.fontWeight = '600';
        errDiv.textContent = 'Failed to parse logs data';
        consoleContainer.appendChild(errDiv);
      }
      return;
    }

    cachedLogs = data.logs;
    renderLogs(isAutoPoll);
  } catch (err) {
    if (err.name === 'AbortError') {
      return; // Silently ignore deliberate abort
    }
    if (!isAutoPoll) {
      consoleContainer.innerHTML = '';
      const errDiv = document.createElement('div');
      errDiv.style.color = 'var(--red)';
      errDiv.style.fontWeight = '600';
      errDiv.textContent = `Error retrieving logs: ${err.message}`;
      consoleContainer.appendChild(errDiv);
    }
  } finally {
    if (logsAbortController?.signal === signal) {
      logsAbortController = null;
    }
  }
}

function startLogsPolling() {
  if (isLogsPolling) return;
  isLogsPolling = true;
  const toggle = el('log-auto-refresh-toggle');
  if (toggle) toggle.checked = true;

  logsPollInterval = setInterval(() => {
    const modal = el('settings-modal');
    const systemPanel = el('settings-modal')?.querySelector('[data-settings-panel="system"]');

    // Safe self-cleanup if modal or panel is hidden/closed
    if (!modal || modal.classList.contains('hidden') || !systemPanel || systemPanel.classList.contains('hidden')) {
      stopLogsPolling();
      return;
    }

    loadLogs(true);
  }, 3000);
}

function stopLogsPolling() {
  if (!isLogsPolling) return;
  isLogsPolling = false;
  if (logsPollInterval) {
    clearInterval(logsPollInterval);
    logsPollInterval = null;
  }
  const toggle = el('log-auto-refresh-toggle');
  if (toggle) toggle.checked = false;
}

function initLogsView() {
  const refreshBtn = el('log-refresh-btn');
  const levelSelect = el('log-level-select');
  const limitSelect = el('log-limit-select');
  const searchInput = el('log-search-input');
  const autoRefreshToggle = el('log-auto-refresh-toggle');

  loadSelfChecks();
  setupBugReport();   // wires listeners only; assembles nothing until asked
  setupUsagePanel();  // queries only when the panel is opened
  setupLazyPanels();  // `B490` evals, `B684` sign-ins: the same, in their own modules
  if (refreshBtn) refreshBtn.addEventListener('click', () => { loadLogs(false); loadSelfChecks(); });
  if (levelSelect) levelSelect.addEventListener('change', () => renderLogs(false));
  if (limitSelect) limitSelect.addEventListener('change', () => loadLogs(false));
  if (searchInput) searchInput.addEventListener('input', () => renderLogs(false));

  if (autoRefreshToggle) {
    autoRefreshToggle.addEventListener('change', (e) => {
      if (e.target.checked) {
        startLogsPolling();
      } else {
        stopLogsPolling();
      }
    });
  }

  // Initial fetch on view loading
  loadLogs(false);
}

/* ═══════════════════════════════════════════
   INIT & REFRESH
   ═══════════════════════════════════════════ */
function initAll() {
  modalEl = el('settings-modal');
  // `P2-19` / `P2-20` added `initWebhookForm` and `initRag`. Both were written
  // with the panels they serve and left out of this array, so neither had run
  // since the fork — the markup being absent was the second half of that, not
  // the cause. Anything added here needs a line in `refreshAll` too, or the
  // panel binds its controls and then renders nothing to use them on.
  const inits = [
    initSignupToggle, initAddUser, initEndpointForm,
    initCalDAV, initBackup, initCleanup, initDangerZone, initLogsView,
    initWebhookForm, initRag, initUploads,
    () => settingsModule.initIntegrations()
  ];
  for (const fn of inits) {
    try { fn(); } catch (e) { console.error('Admin init error in', fn.name || 'anonymous', e); }
  }
  initialized = true;
  refreshAll();
}

function refreshAll() {
  loadUsers();
  loadEndpoints();
  loadBuiltinTools();
  loadWebhooks();
  loadRag();
  loadUploads();
  loadFeatures();
  loadLogs(false);
}

/* ═══════════════════════════════════════════
   PUBLIC API
   ═══════════════════════════════════════════ */
let _initAsking = null;

export function _initData() {
  // `SET-M-8` (P23-03). Everything this module loads is admin-only on the
  // server; for anyone else it was fifteen 403s per Settings open and panels
  // drawn over refusals.
  //
  // `B1525`. The check read the table's state as it stood, and before
  // `/api/auth/status` has answered `isAdmin` is `null` — so Settings opened
  // in that window ran every loader, `/api/personal` (`B1192`'s tenth) among
  // them, for a guest too. Now it asks `viewerMayAdminister`, which waits for
  // the status the page has asked for (at most its four seconds) and answers
  // no only for a viewer the server called a non-admin. Asked again while it
  // waits, it is the same wait, not a second set of loaders.
  if (_initAsking) return _initAsking;
  _initAsking = viewerMayAdminister().then((may) => {
    if (!may) return;
    if (!initialized) initAll();
    else refreshAll();
  }).finally(() => { _initAsking = null; });
  return _initAsking;
}

export function open(tab) {
  _initData();
  settingsModule.open(tab || 'services');
}

export function close() {
  stopLogsPolling();
  settingsModule.close();
}

const adminModule = { open, close, _initData, get _initialized() { return initialized; } };
export default adminModule;
