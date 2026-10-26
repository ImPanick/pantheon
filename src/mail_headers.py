# SPDX-License-Identifier: AGPL-3.0-or-later
"""Decoding a mail header for a person or a model to read — one definition.

`B1232`. The reader, the inbox list, the pollers and the agent's mail tools
(`mcp_servers/email_server.py`) all turn a raw `Subject`/`From`/`To` into text.
There were two copies of that function: `routes/email_helpers._decode_header`,
which `P23-08` taught to name the charset of a bare 8-bit header, and the MCP
server's own, which it did not reach — so a Subject sent with a bare UTF-8 "—"
read "Spring menu site — quote accepted" in the browser and "Spring menu site
��� quote accepted" to the agent summarising it. The MCP server runs in its own
process and cannot import a request-handler module, which is why it kept a
copy; it can import `src/`, which is where `src/mail_auth.py` already lives for
the same reason (`P18-02`). So the one definition is here and both import it
(`Law 7`).
"""
from __future__ import annotations

import email.header


def raw_8bit_charset(data, charset):
    """`P23-08` (DOCS-M-10). Name the charset of a header's raw 8-bit bytes.

    A Subject sent with a bare UTF-8 "—" (not RFC 2047 — non-compliant but
    common) reaches here as a `Header` whose bytes are `unknown-8bit`, which
    `make_header` renders as "���". Measured on `9560d50` in the list, the
    reader and the reply. UTF-8 when the bytes are UTF-8, else Windows-1252,
    the 8-bit charset such mail is usually in (every byte decodes).
    """
    if isinstance(data, bytes) and (charset or "").lower() == "unknown-8bit":
        try:
            data.decode("utf-8")
            return data, "utf-8"
        except UnicodeDecodeError:
            return data, "windows-1252"
    return data, charset


def decode_header(raw) -> str:
    """A MIME header as text: RFC 2047 words decoded, raw 8-bit bytes named."""
    if not raw:
        return ""
    if isinstance(raw, str) and any("\udc80" <= ch <= "\udcff" for ch in raw):
        # The same bytes on a str path: surrogate-escaped (`P23-08`).
        raw = raw.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    try:
        # make_header concatenates per RFC 2047: no spurious space between an
        # encoded-word and adjacent plain text (plain runs keep their own
        # whitespace), and the whitespace between two adjacent encoded-words is
        # dropped. The old " ".join produced "Re:  Jose"-style double spaces on
        # every non-ASCII subject or sender.
        parts = [raw_8bit_charset(d, c) for d, c in email.header.decode_header(raw)]
        return str(email.header.make_header(parts))
    except Exception:
        # Malformed header or unknown/invalid MIME charset (e.g. a spam header
        # like =?x-unknown-charset?B?...?=) makes make_header raise LookupError;
        # fall back to a lossy per-part decode. errors="replace" only covers
        # byte-decode errors, not codec lookup, hence the explicit utf-8 retry.
        decoded = []
        for data, charset in email.header.decode_header(raw):
            if isinstance(data, bytes):
                try:
                    decoded.append(data.decode(charset or "utf-8", errors="replace"))
                except (LookupError, ValueError):
                    decoded.append(data.decode("utf-8", errors="replace"))
            else:
                decoded.append(data)
        return "".join(decoded)


# ── A reminder Pantheon mailed, under either of its names (`B1161`) ─────────
#
# A reminder is marked twice: an `X-…-Kind: reminder` header, and a subject
# prefix for the mail paths that drop custom headers. The rename to Pantheon
# changed both marks (`X-Odysseus-Kind` → `X-Pantheon-Kind`, "Reminder
# (Odysseus):" → "Reminder (Pantheon):") and carried nothing across, so every
# reminder sent before the upgrade stopped being one: the mailbox's Reminders
# filter, its Clear button and the urgent-mail scanner's self-filter each
# looked only for the new marks. These are the one list of both, newest first;
# the `ody_` token prefix (`core/api_tokens.py`) is the precedent for reading
# the old name beside the new. Pantheon writes only the first of each pair.
REMINDER_KIND_HEADERS = ("X-Pantheon-Kind", "X-Odysseus-Kind")
REMINDER_SUBJECT_PREFIXES = ("Reminder (Pantheon):", "Reminder (Odysseus):")
# The origin a Pantheon-sent message carries (`X-Pantheon-Origin`), under both
# names, for the same reason.
OWN_ORIGIN_HEADERS = (("X-Pantheon-Origin", "pantheon-ui"), ("X-Odysseus-Origin", "odysseus-ui"))


def imap_quote(value: str) -> str:
    """An IMAP SEARCH string: quoted, with `\\` and `"` escaped."""
    return '"' + str(value or "").replace("\\", "\\\\").replace('"', '\\"') + '"'


def imap_any(keys) -> str:
    """One IMAP SEARCH key matching any of `keys`: `OR` is binary and prefix,
    so n keys take n-1 of them in front (`OR OR a b c` is `(a or b) or c`)."""
    keys = list(keys)
    return "OR " * (len(keys) - 1) + " ".join(keys)


def reminder_search_keys() -> list:
    """The IMAP SEARCH keys that each find a reminder: every kind header, then
    every subject prefix."""
    return ([f"HEADER {h} {imap_quote('reminder')}" for h in REMINDER_KIND_HEADERS]
            + [f"SUBJECT {imap_quote(p)}" for p in REMINDER_SUBJECT_PREFIXES])


def is_reminder(msg) -> bool:
    """A parsed message carries a reminder's kind header or subject prefix."""
    for h in REMINDER_KIND_HEADERS:
        if str(msg.get(h) or "").strip().lower() == "reminder":
            return True
    subject = str(msg.get("Subject") or "").strip().lower()
    return any(subject.startswith(p.lower()) for p in REMINDER_SUBJECT_PREFIXES)


def is_own_origin(msg) -> bool:
    """A parsed message carries Pantheon's (or, before the rename, Odysseus's)
    origin header."""
    return any(str(msg.get(h) or "").strip().lower() == v for h, v in OWN_ORIGIN_HEADERS)
