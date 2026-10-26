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
