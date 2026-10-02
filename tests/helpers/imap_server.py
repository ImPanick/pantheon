# SPDX-License-Identifier: AGPL-3.0-or-later
"""A small IMAP4rev1 server on a loopback socket, for tests that drive
Pantheon's real mail code (`B1137`, `B1139`).

Nothing of Pantheon's is stood in: `_imap_connect` dials this server with
`imaplib`, logs in, selects INBOX, searches and fetches exactly as it would a
person's provider. What is fake is only the far end — one mailbox, held in
memory, which a test fills with `deliver` and empties with `expunge`.

It answers what Pantheon's client sends — CAPABILITY, LOGIN, LIST, SELECT /
EXAMINE, STATUS, UID SEARCH, UID FETCH (UID FLAGS RFC822.HEADER RFC822.SIZE,
BODY.PEEK[…]), NOOP, CLOSE, LOGOUT — and nothing more. `refuse_logins` makes
LOGIN answer NO, the way a provider answers a stale password; `log` keeps every
command line, so a test can count logins.
"""

from __future__ import annotations

import re
import socketserver
import threading
import time
from email.utils import formatdate


class Mailbox:
    def __init__(self):
        self.lock = threading.Lock()
        self.messages = []        # [{uid, raw, flags}]
        self.next_uid = 1
        self.log = []
        self.refuse_logins = False

    def deliver(self, raw: bytes) -> int:
        with self.lock:
            uid = self.next_uid
            self.next_uid += 1
            self.messages.append({"uid": uid, "raw": raw, "flags": set()})
            return uid

    def expunge(self, uid: int) -> None:
        """The person deleted (or archived) it in their own mail client."""
        with self.lock:
            self.messages = [m for m in self.messages if m["uid"] != uid]

    def logins(self) -> int:
        return sum(1 for line in list(self.log) if " LOGIN " in f" {line.upper()} ")


def message(*, frm: str, subject: str, mid: str, to: str = "rowan@example.test",
            body: str = "Hello.") -> bytes:
    return (f"From: {frm}\r\nTo: {to}\r\nSubject: {subject}\r\n"
            f"Date: {formatdate(localtime=False)}\r\nMessage-ID: <{mid}>\r\n"
            f"MIME-Version: 1.0\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{body}\r\n").encode()


def _header(raw: bytes) -> bytes:
    i = raw.find(b"\r\n\r\n")
    return raw if i < 0 else raw[:i + 4]


class _Handler(socketserver.StreamRequestHandler):
    box: Mailbox = None

    def _send(self, data: bytes) -> None:
        self.wfile.write(data)
        self.wfile.flush()

    def handle(self):
        self._send(b"* OK [CAPABILITY IMAP4rev1 AUTH=PLAIN LOGIN] test IMAP ready\r\n")
        while True:
            line = self.rfile.readline()
            if not line:
                return
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            # A literal argument ({n}) — read it and continue the line.
            while re.search(r"\{(\d+)\}$", text):
                n = int(re.search(r"\{(\d+)\}$", text).group(1))
                self._send(b"+ go on\r\n")
                data = self.rfile.read(n).decode("utf-8", "replace")
                rest = self.rfile.readline().decode("utf-8", "replace").rstrip("\r\n")
                text = re.sub(r"\{\d+\}$", '"' + data + '"', text) + rest
            self.box.log.append(text)
            tag, _, rest = text.partition(" ")
            cmd, _, arg = rest.partition(" ")
            cmd = cmd.upper()
            if cmd == "CAPABILITY":
                self._send(b"* CAPABILITY IMAP4rev1 AUTH=PLAIN LOGIN UIDPLUS\r\n")
                self._send(f"{tag} OK CAPABILITY done\r\n".encode())
            elif cmd == "LOGIN":
                if self.box.refuse_logins:
                    self._send(f"{tag} NO [AUTHENTICATIONFAILED] Invalid credentials\r\n".encode())
                else:
                    self._send(f"{tag} OK LOGIN done\r\n".encode())
            elif cmd in ("NOOP", "CHECK", "ENABLE", "ID"):
                self._send(f"{tag} OK {cmd} done\r\n".encode())
            elif cmd in ("LIST", "LSUB"):
                self._send(b'* LIST (\\HasNoChildren) "/" "INBOX"\r\n')
                self._send(f"{tag} OK {cmd} done\r\n".encode())
            elif cmd in ("SELECT", "EXAMINE"):
                with self.box.lock:
                    n, nxt = len(self.box.messages), self.box.next_uid
                self._send(f"* {n} EXISTS\r\n* 0 RECENT\r\n".encode())
                self._send(b"* FLAGS (\\Seen \\Answered \\Flagged \\Deleted \\Draft)\r\n")
                self._send(f"* OK [UIDVALIDITY 1] UIDs valid\r\n* OK [UIDNEXT {nxt}] next\r\n".encode())
                mode = "READ-ONLY" if cmd == "EXAMINE" else "READ-WRITE"
                self._send(f"{tag} OK [{mode}] {cmd} done\r\n".encode())
            elif cmd == "STATUS":
                with self.box.lock:
                    n, nxt = len(self.box.messages), self.box.next_uid
                    unseen = sum(1 for m in self.box.messages if "\\Seen" not in m["flags"])
                self._send(f'* STATUS "INBOX" (MESSAGES {n} UNSEEN {unseen} UIDNEXT {nxt} '
                           f'UIDVALIDITY 1)\r\n'.encode())
                self._send(f"{tag} OK STATUS done\r\n".encode())
            elif cmd == "UID":
                sub, _, more = arg.partition(" ")
                sub = sub.upper()
                if sub == "SEARCH":
                    with self.box.lock:
                        found = list(self.box.messages)
                    crit = more.upper()
                    if "UNSEEN" in crit:
                        found = [m for m in found if "\\Seen" not in m["flags"]]
                    if "UNANSWERED" in crit:
                        found = [m for m in found if "\\Answered" not in m["flags"]]
                    if "FLAGGED" in crit:
                        found = [m for m in found if "\\Flagged" in m["flags"]]
                    self._send(("* SEARCH " + " ".join(str(m["uid"]) for m in found)).rstrip().encode()
                               + b"\r\n")
                    self._send(f"{tag} OK SEARCH done\r\n".encode())
                elif sub == "FETCH":
                    uidset, _, items = more.partition(" ")
                    self._fetch(uidset, items.upper())
                    self._send(f"{tag} OK FETCH done\r\n".encode())
                else:
                    self._send(f"{tag} OK {sub} done\r\n".encode())
            elif cmd == "LOGOUT":
                self._send(b"* BYE test IMAP\r\n")
                self._send(f"{tag} OK LOGOUT done\r\n".encode())
                return
            else:
                self._send(f"{tag} OK {cmd or 'nothing'} ignored\r\n".encode())

    def _uids(self, uidset: str):
        with self.box.lock:
            known = {m["uid"]: m for m in self.box.messages}
        top = max(known) if known else 0
        wanted = []
        for part in uidset.split(","):
            if ":" in part:
                a, b = part.split(":")
                a = top if a == "*" else int(a)
                b = top if b == "*" else int(b)
                wanted += [u for u in range(min(a, b), max(a, b) + 1) if u in known]
            elif part.strip().isdigit() and int(part) in known:
                wanted.append(int(part))
        return [known[u] for u in wanted]

    def _fetch(self, uidset: str, items: str) -> None:
        for seq, m in enumerate(self._uids(uidset), start=1):
            raw = m["raw"]
            head = [f"UID {m['uid']}", "FLAGS (" + " ".join(sorted(m["flags"])) + ")",
                    f"RFC822.SIZE {len(raw)}",
                    'INTERNALDATE "' + formatdate(time.time(), localtime=False) + '"']
            literal = None
            if "HEADER" in items:
                key = "RFC822.HEADER" if "RFC822.HEADER" in items else "BODY[HEADER]"
                literal = (key, _header(raw))
            elif "BODY[]" in items or "BODY.PEEK[]" in items or re.search(r"\bRFC822\b(?![.])", items):
                literal = ("BODY[]", raw)
            line = f"* {seq} FETCH (" + " ".join(head)
            if literal:
                self._send((line + f" {literal[0]} {{{len(literal[1])}}}\r\n").encode())
                self._send(literal[1] + b")\r\n")
            else:
                self._send((line + ")\r\n").encode())


class _Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


class ImapServer:
    """`with ImapServer() as srv:` — `srv.port`, `srv.box`."""

    def __init__(self):
        self.box = Mailbox()
        handler = type("Handler", (_Handler,), {"box": self.box})
        self._srv = _Server(("127.0.0.1", 0), handler)
        self.port = self._srv.server_address[1]
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._srv.shutdown()
        self._srv.server_close()
