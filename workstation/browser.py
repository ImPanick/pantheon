# SPDX-License-Identifier: AGPL-3.0-or-later
"""The agent browser: each person's own Firefox, driven over WebDriver BiDi.
`P25-05`.

The owner (2026-10-24): *"this means we need an agent browser that's in
app."* The browser is the Firefox already in every workstation (`P20-01`:
Mozilla's build, phoning nowhere), started for the account **as the account**
— so the admin's network mode holds for it exactly as for the account's shell
(`P20-06`) — on the account's own display when it has one, so the desktop and
the in-app window show the same browser, and headless when it has none.

`D-2026-11-01-01`: **on a screen of its own** where the system has one
(`System.browser_display`: KasmVNC with nothing else on it, apart from the
desktop), streamed live to the in-app window as the desktop is, so a person
sees Firefox itself — its tabs, its address bar, the page as it moves — and
uses it while they hold it. The agent drives it here exactly as before; what
changes for it is that a page's size is the window's content on that screen
(`_page_size`), a frame says where the page sits on it (`_view`), and its tab is
the one the screen shows. Headless where the screen will not start.

**Why nobody else can drive it.** Firefox's remote agent listens on this
machine's loopback, which every account here can reach. WebDriver BiDi allows
**one** session per browser (measured: a second `session.new` answers *session
not created: Maximum number of active sessions*), the daemon opens it the
moment the browser says it is listening and holds it for the browser's whole
life, and the session's id — needed to attach to it — never leaves the daemon.
Its profile turns every other remote protocol off (`remote.active-protocols`
= BiDi only). A browser whose session the daemon could not open is stopped.

**One holder.** The browser is on the person's screen, so `P20-05`'s rule is
its rule: while a person holds the screen, the agent's browser actions are
refused (`busy`) and the person's — from the in-app window — go through.

**What a page is to the agent.** `read` answers the page's text and its
interactive elements numbered `[1]`, `[2]`…, each marked in the page itself
(`data-pantheon-ref`) so `click` and `type` name an element by its number and
land in its middle with real pointer and key input — what a person's hand
does, not a script's `el.click()` a page can tell apart.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from workstation import protocol as P
from workstation.bidi import BidiError, Session

logger = logging.getLogger(__name__)

PROFILE_DIR = ".pantheon/browser"
START_TIMEOUT_S = 30.0
# `B1721`. A browser that has been started this many times inside this window
# is not started again until the oldest of those starts leaves it. It is on the
# person's desktop, so every start is a Firefox window opening, and whatever
# asked for it — the in-app window asks for a frame about once a second — would
# otherwise open it again as often as it closes. A browser that runs is started
# once.
RESTARTS_MAX = 3
RESTART_WINDOW_S = 120.0
NAV_TIMEOUT_S = 45.0
READ_MAX_CHARS = 12_000
ELEMENTS_MAX = 150
# `P25-07`. How many of the browser's own actions are kept for the window, how
# recently a frame must have been asked for to count as someone watching, and
# how long the agent's hand waits, while watched, before it acts.
ACTIVITY_KEPT = 40
WATCHED_S = 3.0
PACE_POINTER_S = 0.8
PACE_OTHER_S = 0.35
PACE_INSPECT_S = 1.2       # `P25-11`: long enough to see what was looked at
WHY_MAX = 200
INSPECT_ELEMENTS_MAX = 2500
_LISTENING_RE = re.compile(r"WebDriver BiDi listening on ws://([0-9.]+):(\d+)")

USER_JS = """// Written by the Pantheon workstation (`workstation/browser.py`).
user_pref("remote.active-protocols", 1);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.aboutwelcome.enabled", false);
user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);
user_pref("browser.tabs.warnOnClose", false);
user_pref("browser.sessionstore.resume_from_crash", false);
"""

# `D-2026-11-01-01`. Written after the shipped preferences for a browser on a
# screen of its own, where a person watches and uses it as their browser: its
# tabs at the top of a screen that has no window manager and so no title bar
# (Firefox draws none in its tab strip), a page's new window opened as a tab of
# this one rather than a second window over it, closing the last tab keeping the
# window (closing it would stop the browser under the agent), and no bookmarks
# bar taking the page's room.
SCREEN_JS = """// The browser's own screen (`D-2026-11-01-01`).
user_pref("browser.tabs.inTitlebar", 0);
user_pref("browser.link.open_newwindow", 3);
user_pref("browser.link.open_newwindow.restriction", 0);
user_pref("browser.tabs.closeWindowWithLastTab", false);
user_pref("browser.toolbars.bookmarks.visibility", "never");
"""
# Where Firefox keeps its window's place and size: written before each start
# on a screen of its own, so the window covers the screen exactly — there is no
# window manager to maximize it — and kept the rest of the file as it was.
XULSTORE = "xulstore.json"
_MAIN_WINDOW = ("chrome://browser/content/browser.xhtml", "main-window")
# How long `_ctx` waits for a tab to say whether it is the one on the screen.
_VISIBLE_ASK_S = 2.0

# Where the page sits on the browser's screen (`P.BROWSER_ACTIONS`' "view"):
# `mozInnerScreenX/Y` is Firefox's own word for the viewport's corner in screen
# pixels; the fallback is the window's place plus its chrome.
VIEW_FN = r"""() => JSON.stringify({
  x: Math.round(typeof mozInnerScreenX === 'number' ? mozInnerScreenX : screenX + (outerWidth - innerWidth) / 2),
  y: Math.round(typeof mozInnerScreenY === 'number' ? mozInnerScreenY : screenY + (outerHeight - innerHeight)),
  w: innerWidth, h: innerHeight })"""

# The page as the agent reads it: its text, and the elements a person could
# click or type into, numbered in document order and marked so the number
# finds the element again. Visible ones only; hidden inputs are not offered.
READ_FN = r"""(maxChars, maxEls) => {
  const seen = new Set();
  const sel = 'a[href], button, input:not([type=hidden]), select, textarea, summary, ' +
              '[role=button], [role=link], [role=tab], [role=menuitem], [role=checkbox], ' +
              '[contenteditable=""], [contenteditable=true], [onclick]';
  document.querySelectorAll('[data-pantheon-ref]').forEach((e) => e.removeAttribute('data-pantheon-ref'));
  // `G1` (`D-2026-11-01-04`): what is in view is always numbered — a long
  // page's first elements no longer crowd out the ones on the screen — and
  // the rest fill up to the limit in document order. Numbers stay in
  // document order either way.
  const shown = [];
  for (const el of document.querySelectorAll(sel)) {
    if (shown.length >= 4000) break;
    if (seen.has(el)) continue;
    seen.add(el);
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    if (r.width < 2 || r.height < 2 || st.visibility === 'hidden' || st.display === 'none') continue;
    const inView = r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth;
    shown.push({ el, r, inView });
  }
  const inViewCount = shown.filter((s) => s.inView).length;
  let room = Math.max(0, maxEls - inViewCount);
  const picked = shown.filter((s) => s.inView || (room-- > 0));
  const out = [];
  let n = 0;
  for (const { el, r, inView } of picked) {
    if (out.length >= maxEls) break;
    n += 1;
    el.setAttribute('data-pantheon-ref', String(n));
    const tag = el.tagName.toLowerCase();
    const value = el.type === 'password' ? '' : el.value;   // a filled password is never read out
    const label = (el.getAttribute('aria-label') || el.innerText || value || el.placeholder ||
                   el.title || el.alt || el.name || '').replace(/\s+/g, ' ').trim().slice(0, 80);
    const item = { ref: n, tag, label };
    if (inView) {
      // `G1`: where it is in the viewport — the page's screenshot's pixels.
      const x = Math.max(0, r.left), y = Math.max(0, r.top);
      item.box = [Math.round(x), Math.round(y), Math.round(Math.min(r.right, innerWidth) - x),
                  Math.round(Math.min(r.bottom, innerHeight) - y)];
    }
    if (tag === 'input') item.type = el.type || 'text';
    if (tag === 'a') item.href = el.href.slice(0, 200);
    if (el.disabled) item.disabled = true;
    out.push(item);
  }
  const text = (document.body ? document.body.innerText : '').replace(/\n{3,}/g, '\n\n');
  return JSON.stringify({ title: document.title, url: location.href, viewport: [innerWidth, innerHeight],
                          text: text.slice(0, maxChars), cut: text.length > maxChars, elements: out });
}"""

# Where an element is, in the viewport's pixels, after bringing it into view.
WHERE_FN = r"""(ref) => {
  const el = document.querySelector('[data-pantheon-ref="' + ref + '"]');
  if (!el) return '';
  el.scrollIntoView({ block: 'center', inline: 'center' });
  const r = el.getBoundingClientRect();
  const value = el.type === 'password' ? '' : el.value;
  const label = (el.getAttribute('aria-label') || el.innerText || value || el.placeholder ||
                 el.title || el.alt || el.name || el.tagName.toLowerCase()).replace(/\s+/g, ' ').trim().slice(0, 60);
  return JSON.stringify({ x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2),
                          editable: !!(el.isContentEditable || /^(input|textarea|select)$/i.test(el.tagName)),
                          label });
}"""

# `P27-06`. The sign-in form's fields on the open page, for `login`: the
# visible password field, the user-name field before it in the same form (or
# alone, on a page that asks for the name first), and a one-time-code field.
# Each is marked so `_fill` finds it again; nothing here reads a value.
FIELDS_FN = r"""() => {
  const shown = (el) => {
    const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
    return r.width >= 2 && r.height >= 2 && st.visibility !== 'hidden' && st.display !== 'none' && !el.disabled;
  };
  document.querySelectorAll('[data-pantheon-fill]').forEach((e) => e.removeAttribute('data-pantheon-fill'));
  const inputs = [...document.querySelectorAll('input')].filter(shown);
  const isOtp = (el) => /one-time-code/i.test(el.autocomplete || '') ||
    /otp|totp|2fa|mfa|one.?time|verification|auth.?code/i.test((el.name || '') + ' ' + (el.id || '') + ' ' +
                                                             (el.placeholder || '') + ' ' + (el.getAttribute('aria-label') || ''));
  const pass = inputs.find((el) => el.type === 'password' && !/new-password/i.test(el.autocomplete || ''));
  const textual = (el) => /^(text|email|tel|)$/i.test(el.getAttribute('type') || '') && !isOtp(el);
  let user = null;
  if (pass) {
    const scope = pass.form ? [...pass.form.querySelectorAll('input')].filter(shown) : inputs;
    const before = scope.slice(0, scope.indexOf(pass)).filter(textual);
    user = before.find((el) => /username|email/i.test(el.autocomplete || '')) || before[before.length - 1] || null;
  } else {
    user = inputs.find((el) => textual(el) && /username|email/i.test(el.autocomplete || '')) ||
           inputs.find((el) => textual(el) && /user|login|email|account|name/i.test((el.name || '') + ' ' + (el.id || '') + ' ' + (el.placeholder || ''))) ||
           null;
  }
  const otp = pass ? null : inputs.find(isOtp) || null;
  if (user) user.setAttribute('data-pantheon-fill', 'user');
  if (pass) pass.setAttribute('data-pantheon-fill', 'pass');
  if (otp) otp.setAttribute('data-pantheon-fill', 'otp');
  return JSON.stringify({ user: !!user, pass: !!pass, otp: !!otp });
}"""

# Where a marked field is, after bringing it into view.
FIELD_AT_FN = r"""(which) => {
  const el = document.querySelector('[data-pantheon-fill="' + which + '"]');
  if (!el) return '';
  el.scrollIntoView({ block: 'center', inline: 'center' });
  el.focus();
  const r = el.getBoundingClientRect();
  return JSON.stringify({ x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) });
}"""

# `P26-01`. What is under a point, as something that finds it again: a
# selector (an id when the page has a unique one, else a path of tags and
# positions), its tag, role and a little of its text — a password field's
# value never, only its placeholder.
ANCHOR_FN = r"""(x, y) => {
  const el = document.elementFromPoint(x, y);
  if (!el || el === document.documentElement || el === document.body) return '';
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  const path = (e) => {
    if (e.id && document.querySelectorAll('#' + esc(e.id)).length === 1) return '#' + esc(e.id);
    const parts = [];
    while (e && e.nodeType === 1 && e !== document.documentElement) {
      let p = e.tagName.toLowerCase();
      if (e.id && document.querySelectorAll('#' + esc(e.id)).length === 1) { parts.unshift('#' + esc(e.id)); break; }
      const same = e.parentElement ? [...e.parentElement.children].filter((c) => c.tagName === e.tagName) : [];
      if (same.length > 1) p += ':nth-of-type(' + (same.indexOf(e) + 1) + ')';
      parts.unshift(p);
      e = e.parentElement;
    }
    return parts.join(' > ');
  };
  const r = el.getBoundingClientRect();
  const text = (el.getAttribute('aria-label') || el.innerText || el.alt || el.placeholder || el.title || '')
    .replace(/\s+/g, ' ').trim().slice(0, 80);
  return JSON.stringify({ selector: path(el), tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || '',
                          text, box: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)] });
}"""

# `P26-01`. Where each anchored element is now, in the viewport's pixels, or
# null when it is gone. A selector that now finds an element whose text is not
# the note's is not that element: the text is asked of its tag instead.
LOCATE_FN = r"""(anchors) => {
  const same = (el, a) => !a.text || (el.getAttribute('aria-label') || el.innerText || el.alt || el.placeholder || el.title || '')
    .replace(/\s+/g, ' ').trim().slice(0, 80).startsWith(a.text.slice(0, 30));
  return JSON.stringify(JSON.parse(anchors).map((a) => {
    let el = null;
    try { el = document.querySelector(a.selector); } catch (_) { el = null; }
    if (el && !same(el, a)) el = null;
    if (!el && a.text && a.tag) {
      el = [...document.getElementsByTagName(a.tag)].find((e) => same(e, a)) || null;
    }
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (r.width < 1 && r.height < 1) return null;
    const where = r.bottom < 0 ? 'above' : (r.top > window.innerHeight ? 'below' : 'here');
    return { box: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)], where };
  }));
}"""

# `P25-11`. What a page is made of, as a designer or an editor reads it — for
# one element (a `read` number, a person's `point`, a selector, or a point) or
# the whole page. Colours come back as hex; a password field's value never.
# Looking only: nothing on the page is changed but the element scrolled into
# view, which the person watching sees.
INSPECT_FN = r"""(raw, maxEls) => {
  const target = raw ? JSON.parse(raw) : null;
  const hex = (c) => {
    const m = String(c || '').match(/rgba?\(([^)]+)\)/);
    if (!m) return String(c || '');
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    const a = p.length > 3 ? p[3] : 1;
    if (a === 0) return 'transparent';
    const h = '#' + p.slice(0, 3).map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
    return a < 1 ? h + Math.round(a * 255).toString(16).padStart(2, '0') : h;
  };
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  const path = (e) => {
    const parts = [];
    while (e && e.nodeType === 1 && e !== document.documentElement) {
      if (e.id && document.querySelectorAll('#' + esc(e.id)).length === 1) { parts.unshift('#' + esc(e.id)); break; }
      let p = e.tagName.toLowerCase();
      const same = e.parentElement ? [...e.parentElement.children].filter((c) => c.tagName === e.tagName) : [];
      if (same.length > 1) p += ':nth-of-type(' + (same.indexOf(e) + 1) + ')';
      parts.unshift(p);
      e = e.parentElement;
    }
    return parts.join(' > ');
  };
  const words = (el) => (el.getAttribute('aria-label') || el.innerText || el.alt || el.placeholder || el.title || '')
    .replace(/\s+/g, ' ').trim();
  const shown = (el) => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
    return r.width >= 1 && r.height >= 1 && st.visibility !== 'hidden' && st.display !== 'none'; };
  const PROPS = ['font-family', 'font-size', 'font-weight', 'line-height', 'letter-spacing', 'text-transform',
    'text-align', 'color', 'background-color', 'background-image', 'border', 'border-radius', 'box-shadow',
    'padding', 'margin', 'gap', 'display', 'flex-direction', 'justify-content', 'align-items',
    'grid-template-columns', 'width', 'height', 'max-width', 'opacity', 'position'];
  const DULL = { 'background-image': 'none', 'box-shadow': 'none', 'text-transform': 'none', 'opacity': '1',
    'position': 'static', 'letter-spacing': 'normal', 'gap': 'normal', 'grid-template-columns': 'none',
    'max-width': 'none', 'border-radius': '0px', 'margin': '0px', 'padding': '0px', 'flex-direction': 'row',
    'justify-content': 'normal', 'align-items': 'normal' };
  const element = (el) => {
    el.scrollIntoView({ block: 'center', inline: 'nearest' });
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    const styles = {};
    PROPS.forEach((k) => {
      let v = cs.getPropertyValue(k).trim();
      if (!v || DULL[k] === v) return;
      if (k === 'border' && /^0px/.test(v)) return;
      if (/color$/.test(k)) v = hex(v);
      if (k === 'background-color' && v === 'transparent') return;
      if (k === 'border' || k === 'box-shadow') v = v.replace(/rgba?\([^)]+\)/g, hex);
      if (k === 'background-image') v = v.replace(/url\([^)]{60,}\)/g, 'url(…)').slice(0, 200);
      styles[k] = v.slice(0, 200);
    });
    const tag = el.tagName.toLowerCase();
    const out = { tag, selector: path(el), role: el.getAttribute('role') || '', text: words(el).slice(0, 400),
      box: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)], styles,
      children: el.children.length };
    if (tag === 'a') out.href = (el.href || '').slice(0, 300);
    if (tag === 'img') { out.src = (el.currentSrc || el.src || '').slice(0, 300); out.alt = el.alt || '';
      out.natural = [el.naturalWidth, el.naturalHeight]; }
    if (el.type === 'password') out.text = el.placeholder || '';
    let b = el, bg = 'transparent';
    while (b && b.nodeType === 1) { const c = hex(getComputedStyle(b).backgroundColor); if (c !== 'transparent') { bg = c; break; } b = b.parentElement; }
    out.on_background = bg;
    return out;
  };
  let el = null;
  if (target && target.ref != null) {
    el = document.querySelector('[data-pantheon-ref="' + target.ref + '"]');
    if (!el) return JSON.stringify({ missing: 'There is no element ' + target.ref + ' on this reading; read the page again.' });
  } else if (target && target.selector) {
    try { el = document.querySelector(target.selector); } catch (_) { el = null; }
    const same = (e) => !target.text || words(e).slice(0, 80).startsWith(String(target.text).slice(0, 30));
    if (el && !same(el)) el = null;
    if (!el && target.tag) el = [...document.getElementsByTagName(target.tag)].find(same) || null;
    if (!el) return JSON.stringify({ missing: 'That element is no longer on the page.' });
  } else if (target && target.x != null) {
    el = document.elementFromPoint(target.x, target.y);
    if (!el || el === document.documentElement || el === document.body) el = null;
    if (!el) return JSON.stringify({ missing: 'There is nothing on the page there.' });
  }
  if (el) return JSON.stringify({ title: document.title, url: location.href, element: element(el) });
  // The whole page: what it is made of, counted.
  const count = (m, k, w) => { if (k) m.set(k, (m.get(k) || 0) + (w || 1)); };
  const top = (m, n) => [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, n).map(([v, c]) => ({ value: v, count: Math.round(c) }));
  const text = new Map(), back = new Map(), fonts = new Map(), sizes = new Map(), space = new Map(),
    radii = new Map(), shadows = new Map(), widths = new Map();
  let seen = 0;
  // The page's own ground: the body's background, or the root's behind it.
  [document.documentElement, document.body].forEach((e) => {
    const bg = e ? hex(getComputedStyle(e).backgroundColor) : 'transparent';
    if (bg !== 'transparent') count(back, bg, innerWidth * innerHeight / 1000);
  });
  for (const e of document.body ? document.body.querySelectorAll('*') : []) {
    if (seen >= maxEls) break;
    if (!shown(e)) continue;
    seen += 1;
    const cs = getComputedStyle(e);
    const r = e.getBoundingClientRect();
    const own = [...e.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join('').trim().length;
    if (own) {
      count(text, hex(cs.color), own);
      count(fonts, cs.fontFamily.split(',')[0].replace(/["']/g, '').trim(), own);
      count(sizes, cs.fontSize, own);
    }
    const bg = hex(cs.backgroundColor);
    if (bg !== 'transparent') count(back, bg, r.width * r.height / 1000);
    ['padding-top', 'padding-left', 'margin-top', 'margin-bottom', 'row-gap', 'column-gap'].forEach((k) => {
      const v = cs.getPropertyValue(k); if (/^[1-9][0-9.]*px$/.test(v)) count(space, v); });
    if (/^[1-9]/.test(cs.borderTopLeftRadius)) count(radii, cs.borderTopLeftRadius);
    if (cs.boxShadow && cs.boxShadow !== 'none') count(shadows, cs.boxShadow.replace(/rgba?\([^)]+\)/g, hex).slice(0, 120));
    if (cs.maxWidth && cs.maxWidth !== 'none' && /px$/.test(cs.maxWidth)) count(widths, cs.maxWidth);
  }
  const vars = {};
  try {
    const rs = getComputedStyle(document.documentElement);
    for (const sheet of document.styleSheets) {
      let rules; try { rules = sheet.cssRules; } catch (_) { continue; }
      for (const rule of rules || []) {
        if (!rule.style || !/(^|,)\s*(:root|html)\s*(,|$)/.test(rule.selectorText || '')) continue;
        for (const k of rule.style) if (k.startsWith('--') && Object.keys(vars).length < 60) vars[k] = rs.getPropertyValue(k).trim().slice(0, 80);
      }
    }
  } catch (_) { /* a sheet that will not be read says nothing */ }
  const media = new Set();
  try {
    for (const sheet of document.styleSheets) {
      let rules; try { rules = sheet.cssRules; } catch (_) { continue; }
      for (const rule of rules || []) if (rule.media && rule.conditionText && media.size < 12) media.add(rule.conditionText.slice(0, 80));
    }
  } catch (_) { /* as above */ }
  const heads = [...document.querySelectorAll('h1, h2, h3')].filter(shown).slice(0, 24)
    .map((h) => ({ tag: h.tagName.toLowerCase(), text: words(h).slice(0, 100) }));
  const imgs = [...document.images];
  const meta = (n) => { const m = document.querySelector('meta[name="' + n + '"]'); return m ? (m.content || '').slice(0, 300) : ''; };
  return JSON.stringify({ title: document.title, url: location.href, page: {
    size: [document.documentElement.scrollWidth, document.documentElement.scrollHeight],
    viewport: [innerWidth, innerHeight], scrolled: Math.round(scrollY), description: meta('description'),
    theme_color: meta('theme-color'), lang: document.documentElement.lang || '',
    text_colours: top(text, 8), backgrounds: top(back, 8), fonts: top(fonts, 6), sizes: top(sizes, 10),
    spacing: top(space, 10), radii: top(radii, 6), shadows: top(shadows, 4), max_widths: top(widths, 4),
    variables: vars, media: [...media], headings: heads,
    landmarks: ['header', 'nav', 'main', 'aside', 'footer'].filter((t) => document.querySelector(t)),
    images: imgs.length, images_without_alt: imgs.filter((i) => !i.hasAttribute('alt')).length,
    links: document.links.length, elements_counted: seen } });
}"""


# WebDriver's key codes for the keys a person names (`press`).
KEYS = {
    "enter": "", "return": "", "tab": "", "escape": "", "esc": "",
    "backspace": "", "delete": "", "space": " ", "up": "", "down": "",
    "left": "", "right": "", "pageup": "", "pagedown": "", "home": "",
    "end": "", "ctrl": "", "control": "", "shift": "", "alt": "",
    "meta": "", "cmd": "",
}


def _key_actions(combo: str) -> List[Dict[str, str]]:
    """`"ctrl+a"` → down ctrl, down a, up a, up ctrl."""
    parts = [p for p in combo.lower().split("+") if p]
    if not parts:
        raise BrowserError("bad_request", "Name a key, like Enter or ctrl+a.")
    codes = []
    for p in parts:
        if p in KEYS:
            codes.append(KEYS[p])
        elif len(p) == 1:
            codes.append(p)
        else:
            raise BrowserError("bad_request", f"“{p}” is not a key this browser knows.")
    return ([{"type": "keyDown", "value": c} for c in codes] +
            [{"type": "keyUp", "value": c} for c in reversed(codes)])


class BrowserError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def check_url(raw: Any) -> str:
    """An address the browser may open: http(s), or about:blank. A bare name
    (`example.org`) is read as https."""
    url = str(raw or "").strip()
    if not url:
        raise BrowserError("bad_request", "Give an address to open, like https://example.org.")
    if url == "about:blank":
        return url
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url):
        url = "https://" + url
    if not re.match(r"^https?://[^\s/]", url, re.I) or len(url) > 4000:
        raise BrowserError("bad_request", "The browser opens web addresses: http:// or https://.")
    return url


# Where a Firefox may be, beyond `PATH`'s `firefox`. Debian's package (the one
# Pantheon's own image installs for the browser without a workstation,
# `src/local_browser.py`) is `firefox-esr`; a desktop install of Pantheon finds
# the person's own Firefox where its installer puts it. `FIREFOX_ENV` wins.
FIREFOX_ENV = "PANTHEON_BROWSER_FIREFOX"
FIREFOX_NAMES = ("firefox", "firefox-esr")
FIREFOX_PATHS = (
    "/Applications/Firefox.app/Contents/MacOS/firefox",
    r"C:\Program Files\Mozilla Firefox\firefox.exe",
    r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
)


def find_firefox() -> Optional[str]:
    """The Firefox this machine has, or None."""
    chosen = (os.environ.get(FIREFOX_ENV) or "").strip()
    if chosen:
        return chosen if os.path.isfile(chosen) and os.access(chosen, os.X_OK) else None
    for name in FIREFOX_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for path in FIREFOX_PATHS:
        if os.path.isfile(path):
            return path
    return None


class AccountBrowser:
    """One person's browser: the process, its session, its tabs."""

    #: Preferences written after the shipped ones — the browser without a
    #: workstation sets its proxy here (`src/local_browser.py`).
    extra_prefs = ""

    def __init__(self, launch_prefix: List[str], env: Dict[str, str], profile: Path,
                 headless: bool, own=None, screen=None):
        self.launch_prefix = launch_prefix
        self.env = env
        self.profile = profile
        self.headless = headless
        self.own = own
        # `D-2026-11-01-01`. The browser's own screen (`System.browser_display`):
        # started with the browser, which runs on it when it starts and
        # headless when it will not. `on_screen` says which the running one is.
        self.screen = screen
        self.on_screen = False
        self.proc: Optional[subprocess.Popen] = None
        self.session: Optional[Session] = None
        self.current: Optional[str] = None
        self.lock = threading.RLock()
        # `P25-07`. What the browser did, newest last, for the window to show
        # as it happens: `{id, seq, at, who, action, label, x?, y?, phase}`.
        # `seq` rises whenever an entry is added or moves on, so a window that
        # has seen up to N asks only for what came after.
        self.activity: List[Dict[str, Any]] = []
        self.seq = 0
        self._ids = 0
        self.watched_at = 0.0
        self.pointed: Optional[Dict] = None   # `P25-10`: what the person last pointed at
        self._act_lock = threading.Lock()
        self._starts: List[float] = []        # `B1721`: when it was last started

    # -- life -------------------------------------------------------------------

    def running(self) -> bool:
        return (self.proc is not None and self.proc.poll() is None
                and self.session is not None and not self.session.closed)

    def ensure_running(self) -> None:
        """Started if it is not running (`D-2026-11-01-01`: a window that
        streams the browser's screen wants Firefox on it)."""
        with self.lock:
            if not self.running():
                self.stop()
                self.start()

    def _on_screen_env(self) -> Optional[Dict[str, str]]:
        """The environment for Firefox on its own screen, starting the screen;
        None where there is no screen or it will not start (said in the log,
        and the browser runs headless)."""
        if self.screen is None:
            return None
        try:
            display = self.screen.start()
        except Exception as e:  # noqa: BLE001 — a screen that will not start: headless
            logger.info("browser: no screen of its own (%s); it runs headless",
                        getattr(e, "message", None) or e)
            return None
        return {**self.env, "DISPLAY": display, "XAUTHORITY": str(self.screen.auth_path())}

    def _write_profile_file(self, name: str, text: str) -> Path:
        """One file of the profile, written whole and never through a link at
        its own name (the profile is in the account's home)."""
        path = self.profile / name
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def _xulstore_text(self) -> str:
        """`XULSTORE` with the main window over the whole screen, everything
        else in it as Firefox left it."""
        try:
            fd = os.open(self.profile / XULSTORE, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "r", encoding="utf-8") as f:
                store = json.load(f)
        except (OSError, ValueError):
            store = {}
        if not isinstance(store, dict):
            store = {}
        doc, win = _MAIN_WINDOW
        page = store.get(doc) if isinstance(store.get(doc), dict) else {}
        page[win] = {"screenX": "0", "screenY": "0", "width": str(P.SCREEN_WIDTH),
                     "height": str(P.SCREEN_HEIGHT), "sizemode": "normal"}
        store[doc] = page
        return json.dumps(store)

    def _fit_window(self, env: Dict[str, str]) -> None:
        """Firefox's window moved to the corner and sized to the screen, once
        it is on it — the window manager's job, and there is none. Best
        effort: `XULSTORE` already asked Firefox for this size."""
        if not shutil.which("xdotool"):
            return
        argv = self.launch_prefix + [
            "xdotool", "search", "--sync", "--onlyvisible", "--class", "firefox",
            "windowmove", "%@", "0", "0", "windowsize", "%@", str(P.SCREEN_WIDTH), str(P.SCREEN_HEIGHT)]
        try:
            subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10)
        except (OSError, subprocess.SubprocessError) as e:
            logger.info("browser: its window could not be fitted to its screen: %s", e)

    def start(self) -> None:
        firefox = find_firefox()
        if not firefox:
            raise BrowserError("unavailable", "This workstation has no Firefox, so it has no browser.")
        now = time.monotonic()
        self._starts = [t for t in self._starts if now - t < RESTART_WINDOW_S]
        if len(self._starts) >= RESTARTS_MAX:
            wait = int(RESTART_WINDOW_S - (now - self._starts[0])) + 1
            raise BrowserError("unavailable", (
                f"The browser stopped {len(self._starts)} times in the last "
                f"{int(RESTART_WINDOW_S)} seconds, so it is not started again for {wait} s. "
                "If the desktop's display restarted, it will settle; if Firefox keeps "
                "failing, the workstation's log says why."))
        self._starts.append(now)
        self.profile.mkdir(parents=True, exist_ok=True)
        env = self._on_screen_env()
        self.on_screen = env is not None
        headless = self.headless if self.screen is None else not self.on_screen
        names = self.names() if callable(getattr(self, "names", None)) else None
        written = [self._write_profile_file(
            "user.js", USER_JS + (SCREEN_JS if self.on_screen else "")
            + (names.browser_prefs() if names else "") + self.extra_prefs)]
        if self.on_screen:
            written.append(self._write_profile_file(XULSTORE, self._xulstore_text()))
        if self.own:
            self.own([self.profile.parent, self.profile, *written])
        if names:
            # `P27-04`. The pinned certificates, each trusted as its own
            # server's only; what could not be done is logged, not fatal.
            for problem in names.import_pins(self.profile):
                logger.warning("browser: %s", problem)
        argv = self.launch_prefix + [firefox, "--remote-debugging-port=0", "--no-remote",
                                     "--profile", str(self.profile)]
        if headless:
            argv.append("--headless")
        argv.append("about:blank")
        self.proc = subprocess.Popen(argv, env=env or self.env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     start_new_session=True)
        port = self._listening_port()
        try:
            self.session = Session("127.0.0.1", port)
            self.session.start()
        except BidiError as e:
            self.stop()
            raise BrowserError("unavailable", f"The browser started but could not be driven: {e.message}")
        threading.Thread(target=self._drain, daemon=True).start()
        ctx = self._contexts()[0]["context"]
        self.current = ctx
        if env is not None:
            self._fit_window(env)
        self._viewport(ctx)

    def _listening_port(self) -> int:
        end = time.monotonic() + START_TIMEOUT_S
        assert self.proc is not None and self.proc.stdout is not None
        seen: List[str] = []
        while time.monotonic() < end:
            line = self.proc.stdout.readline()
            if not line:
                if self.proc.poll() is not None:
                    break
                continue
            text = line.decode("utf-8", "replace")
            seen.append(text.strip())
            m = _LISTENING_RE.search(text)
            if m:
                return int(m.group(2))
        self.stop()
        raise BrowserError("unavailable", "The browser did not start: "
                           + ((" ".join(seen[-2:]))[:200] or "it said nothing."))

    def _drain(self) -> None:
        try:
            while self.proc and self.proc.stdout and self.proc.stdout.readline():
                pass
        except (OSError, ValueError):
            pass  # the drain only keeps Firefox's pipe from filling; it ends when Firefox does

    def stop(self) -> None:
        with self.lock:
            if self.session is not None:
                try:
                    self.session.close()
                except Exception:  # noqa: BLE001
                    pass
            self.session = None
            if self.proc is not None and self.proc.poll() is None and not hasattr(os, "killpg"):
                self.proc.kill()   # Windows: no process groups; Firefox's children follow it
            if self.proc is not None and self.proc.poll() is None:
                try:
                    os.killpg(self.proc.pid, 15)
                    self.proc.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(self.proc.pid, 9)
                    except OSError:
                        pass  # already gone between the check and the kill
            self.proc = None
            self.current = None

    # -- BiDi -------------------------------------------------------------------

    def _call(self, method: str, params: Dict, timeout: float = 30.0) -> Dict:
        try:
            return self.session.call(method, params, timeout=timeout)
        except BidiError as e:
            if e.code == "timeout":
                raise BrowserError("timeout", e.message)
            if e.code == "unavailable":
                raise BrowserError("unavailable", e.message)
            raise BrowserError("refused", f"The browser refused that: {e.message or e.code}.")

    def _contexts(self) -> List[Dict]:
        return self._call("browsingContext.getTree", {"maxDepth": 0}).get("contexts") or []

    def _viewport(self, ctx: str) -> None:
        if self.on_screen:
            # `D-2026-11-01-01`: on its own screen the page is the window's
            # content, which a person sees; a viewport set larger would be
            # drawn past the screen's edge.
            return
        try:
            self._call("browsingContext.setViewport",
                       {"context": ctx, "viewport": {"width": P.BROWSER_WIDTH, "height": P.BROWSER_HEIGHT}})
        except BrowserError:
            pass  # a viewport Firefox will not set leaves the window's own size; frames still come

    def _ctx(self) -> str:
        ids = [c["context"] for c in self._contexts()]
        if not ids:
            got = self._call("browsingContext.create", {"type": "tab"})
            ids = [got["context"]]
        if self.on_screen and len(ids) > 1:
            # `D-2026-11-01-01`: on its own screen a person can pick a tab in
            # Firefox itself, so the agent's tab is the one on the screen.
            shown = self._shown_tab(ids)
            if shown:
                self.current = shown
        if self.current not in ids:
            self.current = ids[0]
        return self.current

    def _shown_tab(self, ids: List[str]) -> Optional[str]:
        """The tab the screen shows, the current one asked first; None when
        none says so in time."""
        order = ([self.current] if self.current in ids else []) + [i for i in ids if i != self.current]
        for ctx in order:
            try:
                if self._eval(ctx, "() => document.visibilityState", timeout=_VISIBLE_ASK_S) == "visible":
                    return ctx
            except BrowserError:
                continue  # a tab between pages says nothing yet; the next is asked
        return None

    def _page_size(self, ctx: str) -> Tuple[int, int]:
        """The page's size in CSS pixels: the protocol's for a headless
        browser, whose viewport is set to it; the window's content on a screen
        of its own (`D-2026-11-01-01`)."""
        if not self.on_screen:
            return P.BROWSER_WIDTH, P.BROWSER_HEIGHT
        try:
            w, h = json.loads(self._eval(ctx, "() => JSON.stringify([innerWidth, innerHeight])",
                                         timeout=5.0) or "[]")
        except (BrowserError, ValueError, TypeError):
            return P.BROWSER_WIDTH, P.BROWSER_HEIGHT
        if not all(isinstance(v, int) and not isinstance(v, bool) and 0 < v <= 10_000 for v in (w, h)):
            return P.BROWSER_WIDTH, P.BROWSER_HEIGHT
        return w, h

    def _view(self, ctx: str) -> Optional[Dict[str, int]]:
        """Where the page sits on the browser's screen, in its pixels; None
        for a headless browser, whose picture is the page (`P.BROWSER_ACTIONS`)."""
        if not self.on_screen:
            return None
        try:
            got = json.loads(self._eval(ctx, VIEW_FN, timeout=5.0) or "{}")
        except (BrowserError, ValueError, TypeError):
            return None
        if not isinstance(got, dict):
            return None
        try:
            x, y = int(got.get("x")), int(got.get("y"))
            w, h = int(got.get("w")), int(got.get("h"))
        except (TypeError, ValueError):
            return None
        x = max(0, min(x, P.SCREEN_WIDTH - 1))
        y = max(0, min(y, P.SCREEN_HEIGHT - 1))
        w = max(1, min(w, P.SCREEN_WIDTH - x))
        h = max(1, min(h, P.SCREEN_HEIGHT - y))
        return {"x": x, "y": y, "w": w, "h": h}

    def _eval(self, ctx: str, fn: str, *args: Any, timeout: float = 30.0) -> Any:
        got = self._call("script.callFunction", {
            "functionDeclaration": fn, "awaitPromise": False, "target": {"context": ctx},
            "arguments": [_arg(a) for a in args]}, timeout=timeout)
        if got.get("type") == "exception":
            raise BrowserError("refused", "The page would not answer that.")
        res = got.get("result") or {}
        return res.get("value")

    def _where(self, ctx: str, ref: Any) -> Dict:
        if not isinstance(ref, int) or isinstance(ref, bool) or ref < 1:
            raise BrowserError("bad_request", "“ref” is an element's number from `read`.")
        raw = self._eval(ctx, WHERE_FN, ref)
        if not raw:
            raise BrowserError("gone", f"Element [{ref}] is not on the page any more: read the page "
                                       "again, then use its new numbers.")
        return json.loads(raw)

    def _point(self, ctx: str, x: int, y: int, *, button: int = 0, clicks: int = 1) -> None:
        acts: List[Dict] = [{"type": "pointerMove", "x": int(x), "y": int(y)}]
        for _ in range(clicks):
            acts += [{"type": "pointerDown", "button": button}, {"type": "pointerUp", "button": button}]
        self._call("input.performActions", {"context": ctx, "actions": [
            {"type": "pointer", "id": "mouse", "parameters": {"pointerType": "mouse"}, "actions": acts}]})
        self._call("input.releaseActions", {"context": ctx})

    def _keys(self, ctx: str, keys: List[Dict[str, str]]) -> None:
        self._call("input.performActions", {"context": ctx, "actions": [
            {"type": "key", "id": "keyboard", "actions": keys}]})
        self._call("input.releaseActions", {"context": ctx})

    def state(self, ctx: Optional[str] = None) -> Dict:
        ctx = ctx or self._ctx()
        tabs = []
        for c in self._contexts():
            tabs.append({"tab": c["context"], "url": c.get("url") or "", "current": c["context"] == ctx})
        title = ""
        try:
            title = str(self._eval(ctx, "() => document.title") or "")[:200]
        except BrowserError:
            pass  # a page that will not say its title has none to show; its address still does
        url = next((t["url"] for t in tabs if t["tab"] == ctx), "")
        return {"url": url, "title": title, "tabs": tabs}

    # -- what the person watches (`P25-07`) -------------------------------------

    def _log(self, who: str, action: str, label: str, x=None, y=None, phase: str = "doing",
             why: Any = None, box: Any = None) -> Dict:
        with self._act_lock:
            self._ids += 1
            self.seq += 1
            entry = {"id": self._ids, "seq": self.seq, "at": time.time(), "who": who,
                     "action": action, "label": label[:160], "phase": phase}
            if x is not None and y is not None:
                entry["x"], entry["y"] = int(x), int(y)
            # `P25-12`. The agent's own sentence for why — what the person
            # watching reads under the hand. A person's acts need none.
            if who == "agent" and isinstance(why, str) and why.strip():
                entry["why"] = " ".join(why.split())[:WHY_MAX]
            # `P25-11`. What an inspection looked at, outlined on the page.
            if isinstance(box, (list, tuple)) and len(box) == 4:
                entry["box"] = [int(v) for v in box]
            self.activity.append(entry)
            del self.activity[:-ACTIVITY_KEPT]
            return entry

    def _moved_on(self, entry: Dict, phase: str, label: Optional[str] = None) -> None:
        with self._act_lock:
            self.seq += 1
            entry["seq"] = self.seq
            entry["phase"] = phase
            if label:
                entry["label"] = label[:160]

    def activity_since(self, since: int) -> List[Dict[str, Any]]:
        with self._act_lock:
            return [dict(e) for e in self.activity if e["seq"] > since]

    def watched(self) -> bool:
        return time.monotonic() - self.watched_at < WATCHED_S

    def _pace(self, who: str, seconds: float) -> None:
        """An agent's hand moves at a pace a watching person can follow — only
        while someone watches, and outside the lock, so the window's frames
        keep coming while it waits."""
        if who == "agent" and self.watched():
            time.sleep(seconds)

    def act(self, action: str, body: Dict, who: str = "agent") -> Dict:
        """One action, said in the activity before it is done and marked done
        (or failed) after, so the window shows the hand arriving first."""
        with self.lock:
            if not self.running():
                self.stop()
                self.start()
        if action == "inspect":
            return self._inspect(body, who)
        if action == "point":
            return self._point_at(body, who)
        try:
            label, x, y = self._intent(action, body)
        except BrowserError as e:
            # Said too: a hand that reached for something no longer there.
            what = f"element {body.get('ref')}" if body.get("ref") is not None else "the page"
            self._log(who, action, f"{action.capitalize()} on {what} — {e.message}", phase="failed")
            raise
        entry = self._log(who, action, label, x, y, why=body.get("why"))
        self._pace(who, PACE_POINTER_S if x is not None else PACE_OTHER_S)
        try:
            out = self._act(action, body, at=(x, y) if x is not None else None)
        except BrowserError as e:
            self._moved_on(entry, "failed", f"{label} — {e.message}")
            raise
        self._moved_on(entry, "done")
        return out

    def _intent(self, action: str, body: Dict):
        """What the hand is about to do, in words, and where: `(label, x, y)`."""
        x = y = None
        if action in ("click", "type") and body.get("ref") is not None:
            with self.lock:
                at = self._where(self._ctx(), body.get("ref"))
            x, y = at["x"], at["y"]
            what = at.get("label") or f"element {body.get('ref')}"
        elif action == "click":
            with self.lock:
                x, y = _xy(body, self._page_size(self._ctx()))
            what = "the page"
        if action == "click":
            return f"Clicking “{what}”", x, y
        if action == "type":
            text = str(body.get("text") or "")
            shown = text if len(text) <= 40 else text[:39] + "…"
            into = f" into “{what}”" if x is not None else ""
            return f"Typing “{shown}”{into}{' and pressing Enter' if body.get('submit') else ''}", x, y
        if action == "login":
            return f"Signing in with “{str(body.get('label') or 'a saved login')[:80]}”", None, None
        if action == "open":
            return f"Opening {str(body.get('url') or '')[:120]}", None, None
        if action == "read":
            return "Reading the page", None, None
        if action == "press":
            return f"Pressing {body.get('keys')}", None, None
        if action == "scroll":
            dy = body.get("dy", 5) or 0
            return f"Scrolling {'down' if dy >= 0 else 'up'}", None, None
        return {"back": "Going back", "forward": "Going forward", "reload": "Reloading the page",
                "tabs": "Looking at the tabs", "tab_new": "Opening a new tab",
                "tab_switch": "Switching tabs", "tab_close": "Closing a tab"}.get(action, action), None, None

    # -- actions ----------------------------------------------------------------

    def _act(self, action: str, body: Dict, at=None) -> Dict:
        with self.lock:
            if not self.running():
                self.stop()
                self.start()
            ctx = self._ctx()
            out: Dict[str, Any] = {"ok": True, "action": action}
            if action == "open":
                self._call("browsingContext.navigate", {"context": ctx, "url": check_url(body.get("url")),
                                                        "wait": "complete"}, timeout=NAV_TIMEOUT_S)
            elif action == "login":
                out.update(self._login(ctx, body))
            elif action == "read":
                raw = self._eval(ctx, READ_FN, READ_MAX_CHARS, ELEMENTS_MAX)
                out.update(json.loads(raw or "{}"))
                return out
            elif action == "click":
                if at is not None:
                    x, y = at
                elif body.get("ref") is not None:
                    where = self._where(ctx, body.get("ref"))
                    x, y = where["x"], where["y"]
                else:
                    x, y = _xy(body, self._page_size(ctx))
                self._point(ctx, x, y, clicks=2 if body.get("double") else 1)
                time.sleep(0.4)
            elif action == "type":
                text = body.get("text")
                if not isinstance(text, str) or len(text) > P.MAX_TYPE_CHARS:
                    raise BrowserError("bad_request", f"“text” is at most {P.MAX_TYPE_CHARS} characters.")
                if body.get("ref") is not None:
                    where = self._where(ctx, body.get("ref"))
                    self._point(ctx, where["x"], where["y"])
                    if where.get("editable"):
                        self._keys(ctx, _key_actions("ctrl+a") + [{"type": "keyDown", "value": ""},
                                                                  {"type": "keyUp", "value": ""}])
                keys: List[Dict[str, str]] = []
                for ch in text:
                    keys += [{"type": "keyDown", "value": ch}, {"type": "keyUp", "value": ch}]
                if body.get("submit"):
                    keys += [{"type": "keyDown", "value": KEYS["enter"]}, {"type": "keyUp", "value": KEYS["enter"]}]
                if keys:
                    self._keys(ctx, keys)
                time.sleep(0.4 if body.get("submit") else 0.1)
            elif action == "press":
                for combo in str(body.get("keys") or "").split():
                    self._keys(ctx, _key_actions(combo))
                time.sleep(0.3)
            elif action == "scroll":
                dy = _bounded(body.get("dy", 5), "dy", P.MAX_SCROLL_CLICKS)
                dx = _bounded(body.get("dx", 0), "dx", P.MAX_SCROLL_CLICKS)
                self._eval(ctx, "(dx, dy) => { window.scrollBy(dx * 100, dy * 100); return ''; }", dx, dy)
            elif action in ("back", "forward"):
                try:
                    self._call("browsingContext.traverseHistory",
                               {"context": ctx, "delta": -1 if action == "back" else 1}, timeout=NAV_TIMEOUT_S)
                except BrowserError as e:
                    if e.code != "refused":
                        raise
                    raise BrowserError("refused", f"There is nothing to go {action} to.")
                time.sleep(0.4)
            elif action == "reload":
                self._call("browsingContext.reload", {"context": ctx, "wait": "complete"}, timeout=NAV_TIMEOUT_S)
            elif action == "tabs":
                pass
            elif action == "tab_new":
                got = self._call("browsingContext.create", {"type": "tab"})
                self.current = ctx = got["context"]
                self._viewport(ctx)
                if body.get("url"):
                    self._call("browsingContext.navigate", {"context": ctx, "url": check_url(body.get("url")),
                                                            "wait": "complete"}, timeout=NAV_TIMEOUT_S)
            elif action == "tab_switch":
                ctx = self._tab(body)
                self.current = ctx
                try:
                    self._call("browsingContext.activate", {"context": ctx})
                except BrowserError:
                    pass  # activating only raises the tab on a desktop; `current` already points at it
            elif action == "tab_close":
                ctx_close = self._tab(body)
                if len(self._contexts()) <= 1:
                    raise BrowserError("refused", "That is the only tab; open another first.")
                self._call("browsingContext.close", {"context": ctx_close})
                if self.current == ctx_close:
                    self.current = None
                ctx = self._ctx()
            else:
                raise BrowserError("bad_request", f"“{action}” is not a browser action.")
            out.update(self.state(ctx))
            return out

    # -- `P25-10` / `P25-11`: what the person points at, and what is looked at ---

    def _facts(self, ctx: str, target: Optional[Dict]) -> Dict:
        raw = self._eval(ctx, INSPECT_FN, json.dumps(target) if target else "", INSPECT_ELEMENTS_MAX)
        got = json.loads(raw or "{}")
        if got.get("missing"):
            raise BrowserError("refused", got["missing"])
        return got

    def _inspect(self, body: Dict, who: str) -> Dict:
        """`P25-11`. One element, or the whole page, as it is made: logged with
        what was looked at outlined, held long enough to be seen."""
        target: Optional[Dict] = None
        elsewhere = None
        with self.lock:
            ctx = self._ctx()
            url = self.state(ctx).get("url") or ""
            if body.get("pointed"):
                p = self.pointed
                if not p:
                    raise BrowserError("refused", "The person has not pointed at anything in the browser yet.")
                if p["page"] != url.split("#", 1)[0]:
                    elsewhere = p
                elif p.get("anchor"):
                    target = dict(p["anchor"])
            elif body.get("ref") is not None:
                target = {"ref": body.get("ref")}
            elif body.get("selector"):
                sel = str(body.get("selector"))
                if len(sel) > 300:
                    raise BrowserError("bad_request", "“selector” is at most 300 characters.")
                target = {"selector": sel}
            elif body.get("x") is not None or body.get("y") is not None:
                x, y = _xy(body, self._page_size(ctx))
                target = {"x": x, "y": y}
        if elsewhere is not None:
            # The person pointed on another page: what was kept then, said so.
            entry = self._log(who, "inspect", f"Recalling what you pointed at on {elsewhere['title'] or elsewhere['page']}",
                              why=body.get("why"))
            self._moved_on(entry, "done")
            return {"ok": True, "action": "inspect", "url": url, "title": "", "pointed": elsewhere,
                    "elsewhere": True, **({"element": elsewhere["facts"]} if elsewhere.get("facts") else
                                          {"page": elsewhere.get("page_facts") or {}})}
        entry = self._log(who, "inspect", "Inspecting the page" if target is None else "Inspecting an element",
                          why=body.get("why"))
        try:
            with self.lock:
                got = self._facts(self._ctx(), target)
        except BrowserError as e:
            self._moved_on(entry, "failed", f"{entry['label']} — {e.message}")
            raise
        el = got.get("element")
        if el:
            st = el.get("styles") or {}
            font = (st.get("font-family") or "").split(",")[0].strip("\"' ")
            bits = [b for b in (font, st.get("font-size"), st.get("color")) if b]
            label = f"Inspecting <{el['tag']}>{(' “' + el['text'][:40] + '”') if el.get('text') else ''}" \
                    f"{(' — ' + ' '.join(bits)) if bits else ''}"
            bx = el.get("box") or [0, 0, 0, 0]
            with self._act_lock:
                self.seq += 1
                entry.update(seq=self.seq, label=label[:160], box=[int(v) for v in bx],
                             x=int(bx[0] + bx[2] / 2), y=int(bx[1] + bx[3] / 2))
        else:
            with self._act_lock:
                self.seq += 1
                entry.update(seq=self.seq, label="Inspecting the page — colours, type, spacing, structure")
        self._pace(who, PACE_INSPECT_S)
        self._moved_on(entry, "done")
        got.update(ok=True, action="inspect")
        if body.get("pointed"):
            got["pointed"] = self.pointed
        return got

    def _point_at(self, body: Dict, who: str) -> Dict:
        """`P25-10`. The person says *this*: an element under a point, or the
        page. Kept until they point again, so the agent can look at it after
        they have browsed on — what it was then travels with it."""
        if who != "person":
            raise BrowserError("refused", "Pointing is the person's: it is how they say which page they mean.")
        with self.lock:
            ctx = self._ctx()
            st = self.state(ctx)
            url = st.get("url") or ""
            if body.get("page"):
                facts = self._facts(ctx, None)
                self.pointed = {"page": url.split("#", 1)[0], "url": url, "title": st.get("title") or "",
                                "anchor": None, "facts": None, "page_facts": facts.get("page"), "at": time.time()}
                label = f"Pointed at the page {st.get('title') or url}"
                box = None
            else:
                x, y = _xy(body, self._page_size(ctx))
                raw = self._eval(ctx, ANCHOR_FN, x, y)
                if not raw:
                    raise BrowserError("refused", "There is nothing on the page there to point at.")
                anchor = json.loads(raw)
                anchor.pop("box", None)
                facts = self._facts(ctx, {"x": x, "y": y})
                el = facts.get("element") or {}
                anchor = {"selector": el.get("selector") or anchor["selector"], "tag": anchor["tag"],
                          "text": anchor["text"]}
                self.pointed = {"page": url.split("#", 1)[0], "url": url, "title": st.get("title") or "",
                                "anchor": anchor, "facts": el, "page_facts": None, "at": time.time()}
                label = f"Pointed at <{anchor['tag']}>{(' “' + anchor['text'][:40] + '”') if anchor['text'] else ''}"
                box = el.get("box")
        entry = self._log(who, "point", label, box=box)
        self._moved_on(entry, "done")
        return {"ok": True, "action": "point", "pointed": self.pointed, **st}

    # -- `P26-01` … `P26-03`: notes pinned to the page ---------------------------

    def notebook(self):
        from workstation.page_notes import NoteBook
        if getattr(self, "_notebook", None) is None:
            self._notebook = NoteBook(self.profile)
        return self._notebook

    def note(self, action: str, body: Dict, who: str = "person") -> Dict:
        """One of `P.NOTE_ACTIONS`. Not in the activity feed: a note is the
        person's words about the page, not something done to it. Answers the
        notes for the open page (or every page's, `all`), each where its
        element is now, or `lost`."""
        from workstation.page_notes import NoteRefused
        try:
            with self.lock:
                if not self.running():
                    self.stop()
                    self.start()
                ctx = self._ctx()
                url = self.state(ctx).get("url") or ""
                book = self.notebook()
                if action == "note_add":
                    if who != "person":
                        raise BrowserError("refused", "Notes are the person's to make.")
                    x, y = _xy(body, self._page_size(ctx))
                    raw = self._eval(ctx, ANCHOR_FN, x, y)
                    if not raw:
                        raise BrowserError("refused", "There is nothing on the page there to pin a note to.")
                    anchor = json.loads(raw)
                    box = anchor.pop("box")
                    book.add(url, anchor, str(body.get("text") or ""), [x - box[0], y - box[1]])
                elif action == "note_edit":
                    if who != "person":
                        raise BrowserError("refused", "Notes are the person's to change.")
                    book.edit(body.get("note"), text=body.get("text"), shapes=body.get("shapes"),
                              width=P.BROWSER_WIDTH, height=P.BROWSER_HEIGHT)
                elif action == "note_remove":
                    if who != "person":
                        raise BrowserError("refused", "Notes are the person's to remove.")
                    book.remove(body.get("note"))
                elif action in ("note_done", "notes_sent"):
                    ids = body.get("notes") if isinstance(body.get("notes"), list) else [body.get("note")]
                    if action == "notes_sent":
                        status = "sent"
                    elif who == "person" and body.get("status") in ("open", "done", "declined"):
                        status = body["status"]
                    else:
                        status = "declined" if body.get("declined") else "done"
                    book.mark(ids, status, str(body.get("said") or ""))
                notes = book.for_page(None if body.get("all") else url)
                here = [n for n in notes if n["page"] == url.split("#", 1)[0]]
                if here:
                    raw = self._eval(ctx, LOCATE_FN, json.dumps([n["anchor"] for n in here]))
                    for n, at in zip(here, json.loads(raw or "[]")):
                        n["lost"] = at is None
                        if at:
                            n["box"], n["where"] = at["box"], at["where"]
                return {"ok": True, "action": action, "url": url, "notes": notes}
        except NoteRefused as e:
            raise BrowserError("bad_request", e.message) from None

    # -- `P27-06`: signing in by reference --------------------------------------

    def _fill(self, ctx: str, which: str, value: str) -> None:
        raw = self._eval(ctx, FIELD_AT_FN, which)
        if not raw:
            raise BrowserError("gone", "The sign-in form changed while it was being filled. Nothing was sent.")
        at = json.loads(raw)
        self._point(ctx, at["x"], at["y"])
        self._keys(ctx, _key_actions("ctrl+a") + [{"type": "keyDown", "value": KEYS["backspace"]},
                                                  {"type": "keyUp", "value": KEYS["backspace"]}])
        keys: List[Dict[str, str]] = []
        for ch in value:
            keys += [{"type": "keyDown", "value": ch}, {"type": "keyUp", "value": ch}]
        if keys:
            self._keys(ctx, keys)

    def _login(self, ctx: str, body: Dict) -> Dict:
        """Fill the open page's sign-in form from a saved login and send it.
        The values arrive from Pantheon's server for this one call and go
        only into the page's fields: never into the activity, an answer or an
        error. Refused on any page whose origin is not one of the login's —
        a look-alike page is not the service."""
        origins = body.get("origins")
        if (not isinstance(origins, list) or not origins or len(origins) > 8
                or not all(isinstance(o, str) for o in origins)):
            raise BrowserError("bad_request", "“origins” is the login's addresses.")
        label = str(body.get("label") or "the login")[:80]
        values = {"user": body.get("username") or "", "pass": body.get("secret") or "",
                  "otp": body.get("otp") or ""}
        if not all(isinstance(v, str) and len(v) <= 4096 for v in values.values()):
            raise BrowserError("bad_request", "A saved value is too long to type.")
        here = _origin(self.state(ctx).get("url") or "")
        if here not in origins:
            raise BrowserError("refused", f"This page is {here or 'not a web page'}, and “{label}” is for "
                                          f"{', '.join(origins)}. Nothing was filled: open the service's own "
                                          "sign-in page first.")
        names = {"user": "user name", "pass": "password", "otp": "one-time code"}
        filled: List[str] = []
        for _ in range(3):
            found = json.loads(self._eval(ctx, FIELDS_FN) or "{}")
            did = [w for w in ("user", "pass", "otp")
                   if found.get(w) and values[w] and names[w] not in filled]
            if not did:
                break
            for w in did:
                self._fill(ctx, w, values[w])
                filled.append(names[w])
            self._keys(ctx, [{"type": "keyDown", "value": KEYS["enter"]}, {"type": "keyUp", "value": KEYS["enter"]}])
            time.sleep(1.5)
            if _origin(self.state(ctx).get("url") or "") not in origins:
                break   # signed in and sent on elsewhere: nothing more to fill here
        if not filled:
            raise BrowserError("refused", "No sign-in form was found on this page. Open the page with "
                                          "the user name or password field, then sign in again.")
        try:
            after = json.loads(self._eval(ctx, FIELDS_FN) or "{}")
        except BrowserError:
            after = {}   # a page mid-navigation cannot be asked; the next read says where it went
        return {"filled": filled, "still_asking": bool(after.get("pass") and "password" in filled)}

    def _tab(self, body: Dict) -> str:
        want = body.get("tab")
        tabs = [c["context"] for c in self._contexts()]
        if isinstance(want, int) and not isinstance(want, bool) and 1 <= want <= len(tabs):
            return tabs[want - 1]
        if isinstance(want, str) and want in tabs:
            return want
        raise BrowserError("bad_request", f"“tab” is a tab's number, 1 to {len(tabs)}.")

    def frame(self, if_none_match: str = "", since: int = 0) -> Optional[Dict]:
        """The page as it is, and what the browser did after `since`. None (a
        `304`) only when both are what the caller already has."""
        self.watched_at = time.monotonic()
        with self.lock:
            if not self.running():
                self.stop()
                self.start()
            ctx = self._ctx()
            shot = self._call("browsingContext.captureScreenshot", {"context": ctx})
            data = base64.b64decode(shot.get("data") or "")
            digest = hashlib.sha256(data).hexdigest()[:16]
            activity = self.activity_since(since)
            if if_none_match and digest == if_none_match and not activity:
                return None
            # `D-2026-11-01-01`: the picture's own size — the page on a screen
            # of its own is the window's content, not the protocol's size.
            width, height = png_size(data) or (P.BROWSER_WIDTH, P.BROWSER_HEIGHT)
            out = {"mime": "image/png", "data_b64": shot.get("data") or "", "digest": digest,
                   "width": width, "height": height, "view": self._view(ctx),
                   "activity": activity, "seq": self.seq}
            out.update(self.state(ctx))
            return out

    def live(self, since: int = 0) -> Dict:
        """`activity` (`D-2026-11-01-01`): what `frame` answers, without the
        picture, for a window that shows the browser's screen live. Asking is
        watching, as for a frame."""
        self.watched_at = time.monotonic()
        with self.lock:
            if not self.running():
                self.stop()
                self.start()
            ctx = self._ctx()
            out: Dict[str, Any] = {"ok": True, "action": "activity",
                                   "activity": self.activity_since(since), "seq": self.seq,
                                   "view": self._view(ctx)}
            out.update(self.state(ctx))
            return out


def _origin(url: str) -> str:
    """`scheme://host[:port]`, default ports dropped — `src/vault.origin_of`'s
    shape, so the two compare as equal strings."""
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(str(url or ""))
        port = parts.port
    except ValueError:
        return ""
    scheme, host = (parts.scheme or "").lower(), (parts.hostname or "").lower()
    if scheme not in ("http", "https") or not host:
        return ""
    if ":" in host:
        host = f"[{host}]"
    if port is None or (scheme, port) in (("http", 80), ("https", 443)):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def _arg(a: Any) -> Dict:
    if isinstance(a, bool):
        return {"type": "boolean", "value": a}
    if isinstance(a, (int, float)):
        return {"type": "number", "value": a}
    return {"type": "string", "value": str(a)}


def _xy(body: Dict, size: Optional[Tuple[int, int]] = None):
    """A point on the page, checked against the page's size — the protocol's
    for a headless browser, the window's content on a screen of its own
    (`D-2026-11-01-01`)."""
    width, height = size or (P.BROWSER_WIDTH, P.BROWSER_HEIGHT)
    x, y = body.get("x"), body.get("y")
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (x, y)):
        raise BrowserError("bad_request", "A click names an element (“ref”) or a point (“x”, “y”).")
    if not (0 <= x < width and 0 <= y < height):
        raise BrowserError("bad_request", f"The page is {width}×{height}; that point is off it.")
    return x, y


def png_size(data: bytes) -> Optional[Tuple[int, int]]:
    """A PNG's width and height, from its header; None for anything else."""
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height)
    return None


def _bounded(v: Any, name: str, limit: int) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or abs(v) > limit:
        raise BrowserError("bad_request", f"“{name}” is a whole number from -{limit} to {limit}.")
    return v


class Browsers:
    """Every account's browser, made on first use."""

    def __init__(self, system) -> None:
        self.system = system
        self.names_of = lambda account: None   # `P27-04`: set by the daemon
        self._by_account: Dict[str, AccountBrowser] = {}
        self._lock = threading.Lock()

    def get(self, account: str) -> AccountBrowser:
        with self._lock:
            b = self._by_account.get(account)
            if b is None:
                self.system.ensure(account)
                # `D-2026-11-01-01`: a screen of the browser's own where the
                # system has one — apart from the desktop, streamed like it —
                # and the desktop's display only where it has none.
                screen = None
                display_of = getattr(self.system, "browser_display", None)
                if callable(display_of):
                    try:
                        screen = display_of(account)
                    except Exception:  # noqa: BLE001 — no screen of its own: as before
                        screen = None
                display = None
                if screen is None:
                    try:
                        display = self.system.wake(account)
                    except Exception:  # noqa: BLE001 — a desktop that will not start: headless
                        display = None
                prefix, env = self.system.run_as(account)
                env = dict(env)
                if screen is not None:
                    # Never the desktop's: the browser's screen is its own.
                    env.pop("DISPLAY", None)
                    env.pop("XAUTHORITY", None)
                headless = not (display or env.get("DISPLAY"))
                if display and not env.get("DISPLAY"):
                    env["DISPLAY"] = display
                env.setdefault("HOME", str(self.system.home(account)))
                env["MOZ_CRASHREPORTER_DISABLE"] = "1"
                profile = Path(self.system.home(account)) / PROFILE_DIR
                b = AccountBrowser(prefix, env, profile, headless,
                                   own=lambda paths, a=account: self.system.own(a, paths),
                                   screen=screen)
                b.names = lambda a=account: self.names_of(a)   # `P27-04`
                self._by_account[account] = b
            return b

    def stop(self, account: str) -> None:
        with self._lock:
            b = self._by_account.pop(account, None)
        if b is not None:
            b.stop()

    def stop_all(self) -> None:
        with self._lock:
            items = list(self._by_account.items())
            self._by_account.clear()
        for _, b in items:
            b.stop()
