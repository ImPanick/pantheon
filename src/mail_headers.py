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

`B1822`, `B1823`. A message's body is read here too, for the same reason: the
routes and the MCP server each had their own `_extract_text`, with the same
faults. `extract_text` and `extract_html` are the one definition now.

`B1980`. And what a UID is (`one_uid`), so a set such as `1:*` reaches no
command from either process.

`B1964`. And a To/Cc/Bcc field as the SMTP envelope reads it
(`envelope_recipients`, with `normalize_address_field`), so a quoted
`"Smith, John"` is one recipient on every send.
"""
from __future__ import annotations

import email.header
import html
import re


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


# ── A message's body, as text (`B1822`, `B1823`) ───────────────────────────
#
# The reader's and the MCP server's `_extract_text` were copies with the same
# faults: a charset with no codec raised `LookupError` (`errors="replace"`
# covers bad bytes, not a missing codec), an HTML-first `multipart/alternative`
# came back twice, and a single-part `text/html` message came back as raw
# markup. From upstream Odysseus 682662d3 and 84aa9a91, but not its
# `text_parts or html_parts`: on an HTML post with a plain mailing-list footer
# that keeps only the footer.

def decode_text_part(part) -> str:
    """A text part's payload as text, whatever charset it names (`B1822`):
    `unknown-8bit` is named the way a header's is (`P23-08`), and a charset
    with no codec is read as UTF-8, as `decode_header` does (`B1232`)."""
    payload = part.get_payload(decode=True)
    if not payload:
        return ""
    payload, charset = raw_8bit_charset(payload, part.get_content_charset() or "utf-8")
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, ValueError):
        return payload.decode("utf-8", errors="replace")


# `B1823`. Each pattern and loop below is linear in the text, which is the
# sender's: a lazy `<a ...>(.*?)</a>` or `<style.*?</style>`, `<[^>]+>` or
# `[ \t]+\n` restarts at every `<` or space and scans to the end — 52 KB of
# unclosed `<a href="...">` kept a lazy anchor pattern busy for nine seconds.
_HIDDEN_OPEN = re.compile(r"<(script|style|head)\b", re.I)
_HIDDEN_CLOSE = {name: re.compile(rf"</{name}\s*>", re.I) for name in ("script", "style", "head")}
_ANCHOR_OPEN = re.compile(r"<a\b([^<>]*)>", re.I)
_ANCHOR_CLOSE = re.compile(r"</a\s*>", re.I)
_HREF = re.compile(r"""(?:^|[\s/])href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'<>`]+))""", re.I)
_SHOWN_TARGET = re.compile(r"(?:https?|mailto):", re.I)
_LINE_BREAK = re.compile(r"<br\s*/?>", re.I)
_BLOCK_END = re.compile(r"</(?:p|div|li|tr|h[1-6])\s*>", re.I)
_TAG = re.compile(r"<[^>]+>")
_BLANK_LINES = re.compile(r"\n{3,}")


def _strip_tags(text: str) -> str:
    """`<[^>]+>` removed, matched only up to the last `>`: a `<` after it opens
    no tag, and leaving that tail out is what keeps the pattern linear."""
    cut = text.rfind(">") + 1
    return _TAG.sub("", text[:cut]) + text[cut:]


def _drop_hidden(text: str) -> str:
    """Each `<script>`, `<style>` and `<head>` block removed, to its first
    close tag; an unclosed one stays (and is looked for once, not per tag)."""
    out, kept_to, at, unclosed = [], 0, 0, set()
    while True:
        opened = _HIDDEN_OPEN.search(text, at)
        if opened is None:
            break
        name = opened.group(1).lower()
        closed = None if name in unclosed else _HIDDEN_CLOSE[name].search(text, opened.end())
        if closed is None:
            unclosed.add(name)
            at = opened.end()
            continue
        out.append(text[kept_to:opened.start()])
        kept_to = at = closed.end()
    out.append(text[kept_to:])
    return "".join(out)


def _keep_link_targets(text: str) -> str:
    """Each `<a href=...>label</a>` as `label <target>` when the target is
    http(s) or mailto and the label does not already show it; any other target
    (`javascript:`, `data:`, a relative path) leaves the label alone."""
    out, kept_to, at = [], 0, 0
    while True:
        opened = _ANCHOR_OPEN.search(text, at)
        if opened is None:
            break
        href = _HREF.search(opened.group(1))
        if href is None:
            at = opened.end()
            continue
        closed = _ANCHOR_CLOSE.search(text, opened.end())
        if closed is None:
            break  # no `</a>` after this one, so none after any later one
        label = text[opened.end():closed.start()]
        target = html.unescape(next(g for g in href.groups() if g is not None)).strip()
        shown = html.unescape(_strip_tags(label))
        out.append(text[kept_to:opened.start()])
        out.append(label)
        if (_SHOWN_TARGET.match(target) and target not in shown
                and target.split(":", 1)[1] not in shown):
            # Escaped, so the tag strip below keeps it and the unescape restores it.
            out.append(" &lt;" + html.escape(target, quote=False) + "&gt;")
        kept_to = at = closed.end()
    out.append(text[kept_to:])
    return "".join(out)


def html_to_text(raw_html: str) -> str:
    """The text a person reads in mail HTML (`B1823`): no script, style or
    head; link targets kept as `label <https://...>` (the agent's `read_email`
    gets only this text, and the markup it got before carried them, `Law 1`);
    a line break for `<br>` and after a paragraph, div, list item, row or
    heading; trailing spaces and runs of blank lines trimmed."""
    text = raw_html.replace("\r\n", "\n").replace("\r", "\n")
    text = _keep_link_targets(_drop_hidden(text))
    text = _BLOCK_END.sub("\n", _LINE_BREAK.sub("\n", text))
    text = html.unescape(_strip_tags(text))
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return _BLANK_LINES.sub("\n\n", text).strip()


def _is_body_part(part, content_type: str) -> bool:
    return (part.get_content_type() == content_type
            and "attachment" not in str(part.get("Content-Disposition", "")))


def html_shadowed_by_plain(msg) -> set:
    """`id()` of every `text/html` part inside a `multipart/alternative` that
    also holds a non-empty plain body: the plain one is that body (`B1822`)."""
    shadowed = set()
    for part in msg.walk():
        if part.get_content_type() != "multipart/alternative":
            continue
        inside = list(part.walk())[1:]
        if any(_is_body_part(p, "text/plain") and p.get_payload(decode=True) for p in inside):
            shadowed.update(id(p) for p in inside if p.get_content_type() == "text/html")
    return shadowed


def extract_text(msg) -> str:
    """A message's body as text: its plain parts, or the first HTML part's
    text when none came before it. An HTML alternative to a plain part is
    passed over, wherever it sits (`B1822`); a single-part HTML message is its
    text (`B1823`); a single-part plain body is returned as it is."""
    if msg.is_multipart():
        text_parts = []
        shadowed = html_shadowed_by_plain(msg)
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                text = decode_text_part(part)
                if text:
                    text_parts.append(text)
            elif (ct == "text/html" and not text_parts and "attachment" not in cd
                  and id(part) not in shadowed):
                raw_html = decode_text_part(part)
                if raw_html:
                    text_parts.append(html_to_text(raw_html))
        return "\n".join(text_parts)
    text = decode_text_part(msg)
    if text and msg.get_content_type() == "text/html":
        return html_to_text(text)
    return text


def extract_html(msg):
    """A message's first HTML body part, raw, or None (`B1822`: decoded the
    way `extract_text` decodes)."""
    if msg.is_multipart():
        for part in msg.walk():
            if _is_body_part(part, "text/html"):
                text = decode_text_part(part)
                if text:
                    return text
    elif msg.get_content_type() == "text/html":
        text = decode_text_part(msg)
        if text:
            return text
    return None


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


def one_uid(uid) -> str:
    """`uid` as text when it is one plain ASCII number, else "".

    An IMAP UID names one message, but every command that takes one also takes
    a set: `1:*` is every message in the folder, `5,7` two of them, `*` the
    last. A fullwidth or Arabic digit is no number IMAP knows. Bytes (a SEARCH
    answer) are read as ASCII and an int as its digits.

    `B2010` wrote this rule for the routes (`_one_uid`); `B1980` moved it here,
    because the agent's mail tools (`mcp_servers/email_server.py`) run in their
    own process and import `src/`, never `routes/`.
    """
    text = uid.decode("ascii", "replace") if isinstance(uid, bytes) else str(uid if uid is not None else "")
    return text if text.isascii() and text.isdigit() else ""


# ── A To/Cc/Bcc field as the SMTP envelope reads it (`B1964`) ───────────────
#
# `/send` parsed the address grammar, but the scheduled-send poller (which
# also sends every agent draft a person approves) and the agent's own send
# split each field on its commas, so Exchange's `"Smith, John" <john@corp.com>`
# went out as RCPT TO `"Smith` and `John" <john@corp.com>`. These are the one
# definition all three use. From upstream Odysseus #6910.

def normalize_address_field(field):
    """A To/Cc/Bcc field with the empty pieces a paste leaves (`a@x.com,`)
    taken out, its addresses joined by `, `. Splitting on every comma and
    rejoining puts a quoted `"Smith, John"` back together. A list or tuple is
    one field."""
    if isinstance(field, (list, tuple)):
        field = ", ".join(str(p) for p in field if p)
    if not field:
        return field
    parts = [p.strip() for p in str(field).split(",")]
    return ", ".join(p for p in parts if p)


def envelope_recipients(*fields) -> list:
    """The bare addresses of To/Cc/Bcc fields (strings or lists, None skipped),
    in order, for the SMTP envelope. Each field is normalised first: the strict
    `getaddresses` reads `a@x.com,` as no address at all."""
    import email.utils

    headers = [normalize_address_field(f) for f in fields if f]
    out = []
    for _name, addr in email.utils.getaddresses([h for h in headers if h]):
        addr = (addr or "").strip()
        if addr:
            out.append(addr)
    return out
