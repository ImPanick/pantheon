// SPDX-License-Identifier: AGPL-3.0-or-later
// static/js/emailLibrary/replyRecipients.js
//
// Pure helpers for building reply-all recipient lists. No DOM, no fetch,
// no shared state — safe to import anywhere and to unit-test under node.

// Extract the bare email from "Name <email@x>" or a plain "email@x".
export function extractEmail(addr) {
  const m = (addr || '').match(/<([^>]+)>/);
  return (m ? m[1] : (addr || '')).trim().toLowerCase();
}

// Split a To/Cc header into its recipients at the commas between them, not
// at one inside a quoted name or an <address> (`B1964`): Exchange's
// '"Smith, John" <john@corp.com>' is one recipient. A non-string (a JSON
// message blob's To is not always one) is no recipients. From upstream
// Odysseus #6910.
export function splitRecipientList(raw) {
  const s = typeof raw === 'string' ? raw : '';
  const out = [];
  let cur = '';
  let quote = false;
  let angle = false;
  let escaped = false;
  for (const ch of s) {
    if (escaped) {
      escaped = false;
    } else if (ch === '\\' && quote) {
      escaped = true;
    } else if (ch === '"') {
      quote = !quote;
    } else if (ch === '<' && !quote) {
      angle = true;
    } else if (ch === '>' && !quote) {
      angle = false;
    }

    if (ch === ',' && !quote && !angle) {
      const part = cur.trim();
      if (part) out.push(part);
      cur = '';
    } else {
      cur += ch;
    }
  }
  const tail = cur.trim();
  if (tail) out.push(tail);
  return out;
}

// Reply-all CC = everyone on the original To + Cc, minus ourselves, with the
// original "Name <email>" form preserved.
//
// `mine` is a single address or a list of the user's own addresses (a
// multi-account user has more than one). Empty/unknown ⇒ no exclusion.
// Comparing by exact extracted email (not a substring `includes`) is what
// fixes issue #360: an empty self address made `"...".includes("")` true for
// every recipient, so reply-all dropped the entire Cc list.
export function buildReplyAllCc(data, mine) {
  const list = Array.isArray(mine) ? mine : [mine];
  const me = new Set(list.map((a) => (a || '').toLowerCase()).filter(Boolean));
  return [...splitRecipientList(data && data.to), ...splitRecipientList(data && data.cc)]
    .filter((addr) => !me.has(extractEmail(addr)))
    .join(', ');
}
