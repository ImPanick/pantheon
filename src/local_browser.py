# SPDX-License-Identifier: AGPL-3.0-or-later
"""The agent browser without a workstation — each person's own Firefox,
headless, run by Pantheon itself.

The owner (2026-10-31): *"the browser should be able to run without needing a
workstation/VM entirely — and be linkable to the LLM itself as well."* Until
this the agent browser (`P25-05`) was only ever the Firefox inside a person's
workstation, so an install without one had no browser to watch, take over or
hand the agent; the built-in Playwright server (`builtin_browser`) is headless
and nobody can see it.

**The same browser, a different host.** `workstation/browser.py` drives
Firefox over WebDriver BiDi and is standard library only; the workstation's
daemon is one host for it and this module is another. Every action, frame,
note, pointing and sign-in is that file's, so the window
(`static/js/browserWindow.js`) and the `agent_browser` tool cannot tell the two
apart: `LocalBrowserClient` answers the four calls they make (`browser`,
`control`, `ensure`, `names`) with the shapes the protocol gives them.

**Which one a person gets** is `browser_for`: their workstation's when the
workstation would answer them (`workstation_access.workstation_for`), so a
person with a machine keeps one browser on one screen; this one otherwise,
when Pantheon has a Firefox and the person may use the browser
(`can_use_browser`, on by default). The image installs Debian's `firefox-esr`;
a desktop install finds the person's own (`browser.find_firefox`).

**Where it may go.** This browser runs inside Pantheon, beside its database,
its search engine and its vector store, so it is given a proxy of Pantheon's
own and every connection it makes goes through it (the profile turns off
direct connections, DNS of its own, WebRTC and QUIC). The proxy resolves each
name once, refuses loopback, link-local (cloud metadata), private and LAN
addresses (`outbound_fetch._is_private_address` with no LAN grant), and
connects to the address it checked, so a name cannot answer one address to the
check and another to the connection. The LAN, `localhost` and a project's dev
server are the workstation's: a machine of the person's own, whose network an
admin chooses (`P20-06`).

**One holder**, as on the workstation (`P20-05`): while the person has taken
the browser over, the agent's actions are `busy`.

A browser nobody has used for `IDLE_STOP_S` is stopped (its profile kept),
like an idle workstation machine (`B979`): a headless Firefox is a few hundred
megabytes.
"""
from __future__ import annotations

import asyncio
import atexit
import ipaddress
import logging
import os
import select
import socket
import socketserver
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.workstation_client import WorkstationError
from workstation import protocol as P

logger = logging.getLogger(__name__)

PRIVILEGE = "can_use_browser"
PROFILE_ROOT_NAME = "browser"
IDLE_STOP_S = 20 * 60.0
RUNS_IN_PANTHEON = "pantheon"
RUNS_IN_WORKSTATION = "workstation"

NO_FIREFOX_SENTENCE = ("Pantheon has no Firefox, so it has no browser of its own. The Docker image "
                       "has one; on a desktop install, install Firefox — or turn on the "
                       "workstation in Settings → Workstation.")
NOT_PERMITTED_SENTENCE = "Your account may not use the browser. An admin can allow it in Settings → Users."
TOKEN_SENTENCE = "An API token cannot drive the browser."
BUSY_SENTENCE = ("A person has taken over this browser. Wait for them to hand it back, or ask "
                 "them what they need.")
REFUSED_PAGE = (b"<!doctype html><title>Not opened</title><body style='font:15px system-ui;"
                b"margin:3em;max-width:36em'><h1 style='font-size:18px'>Not opened</h1><p>Pantheon's "
                b"browser opens public web addresses only. This machine, its private network and "
                b"the LAN are reached from a workstation.</p></body>")


# ── the proxy every connection goes through ──────────────────────────────────

def _allowed_address(host: str, port: int) -> Tuple[Optional[str], str]:
    """`(address, "")` to connect to, or `(None, why)`. Resolved once here, and
    the caller connects to the address that was checked."""
    from src.outbound_fetch import _is_private_address
    host = host.strip("[]")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return None, f"{host} does not resolve"
    addrs: List[str] = []
    for info in infos:
        a = info[4][0]
        try:
            ip = ipaddress.ip_address(a.split("%", 1)[0])
        except ValueError:
            return None, f"{host} resolved to something that is not an address"
        if _is_private_address(ip, allow_lan=False):
            return None, f"{host} is on this machine or a private network"
        addrs.append(a)
    if not addrs:
        return None, f"{host} does not resolve"
    return addrs[0], ""


def _split_hostport(text: str, default_port: int) -> Tuple[str, int]:
    text = text.strip()
    if text.startswith("["):
        host, _, rest = text[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else ""
    else:
        host, _, port = text.rpartition(":") if text.count(":") == 1 else (text, "", "")
    try:
        return host, int(port) if port else default_port
    except ValueError:
        return host, -1


def _pipe(a: socket.socket, b: socket.socket) -> None:
    socks = [a, b]
    try:
        while True:
            ready, _, _ = select.select(socks, [], [], 300)
            if not ready:
                return
            for s in ready:
                data = s.recv(65536)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except OSError:
        return


class _ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:  # noqa: D401 — socketserver's hook
        conn: socket.socket = self.request
        conn.settimeout(30)
        head = b""
        try:
            while b"\r\n\r\n" not in head and len(head) < 65536:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                head += chunk
        except OSError:
            return
        raw_head, _, rest = head.partition(b"\r\n\r\n")
        lines = raw_head.decode("latin-1").split("\r\n")
        try:
            method, target, version = lines[0].split(" ", 2)
        except ValueError:
            return
        if method.upper() == "CONNECT":
            host, port = _split_hostport(target, 443)
        else:
            from urllib.parse import urlsplit
            parts = urlsplit(target)
            if parts.scheme != "http" or not parts.hostname:
                return self._refuse(conn, "only http and https")
            host, port = parts.hostname, parts.port or 80
        if not host or not 1 <= port <= 65535:
            return self._refuse(conn, "no such address")
        addr, why = _allowed_address(host, port)
        if addr is None:
            logger.info("pantheon browser: refused %s:%s (%s)", host, port, why)
            return self._refuse(conn, why)
        try:
            upstream = socket.create_connection((addr, port), timeout=20)
        except OSError:
            return self._fail(conn)
        upstream.settimeout(None)
        conn.settimeout(None)
        try:
            if method.upper() == "CONNECT":
                conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                if rest:
                    upstream.sendall(rest)
            else:
                from urllib.parse import urlsplit
                parts = urlsplit(target)
                path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
                kept = [h for h in lines[1:] if h and not h.lower().startswith(("proxy-", "connection:"))]
                out = [f"{method} {path} {version}", *kept, "Connection: close", "", ""]
                upstream.sendall("\r\n".join(out).encode("latin-1") + rest)
            _pipe(conn, upstream)
        finally:
            upstream.close()

    @staticmethod
    def _refuse(conn: socket.socket, why: str) -> None:
        body = REFUSED_PAGE
        try:
            conn.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/html; charset=utf-8\r\n"
                         + f"Content-Length: {len(body)}\r\nX-Pantheon-Refused: {why[:120]}\r\n"
                           "Connection: close\r\n\r\n".encode("latin-1", "replace") + body)
        except OSError:
            pass

    @staticmethod
    def _fail(conn: socket.socket) -> None:
        try:
            conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        except OSError:
            pass


class _ThreadingProxy(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class GuardProxy:
    """The proxy, on this machine's loopback, started on first use."""

    def __init__(self) -> None:
        self._server: Optional[_ThreadingProxy] = None
        self._lock = threading.Lock()

    def port(self) -> int:
        with self._lock:
            if self._server is None:
                self._server = _ThreadingProxy(("127.0.0.1", 0), _ProxyHandler)
                threading.Thread(target=self._server.serve_forever, name="browser-proxy",
                                 daemon=True).start()
            return int(self._server.server_address[1])

    def stop(self) -> None:
        with self._lock:
            if self._server is not None:
                self._server.shutdown()
                self._server.server_close()
                self._server = None


def proxy_prefs(port: int) -> str:
    """The profile's network, every connection through the proxy."""
    prefs = {
        "network.proxy.type": 1,
        "network.proxy.http": "127.0.0.1", "network.proxy.http_port": port,
        "network.proxy.ssl": "127.0.0.1", "network.proxy.ssl_port": port,
        "network.proxy.share_proxy_settings": True,
        "network.proxy.no_proxies_on": "",
        "network.proxy.allow_hijacking_localhost": True,
        "network.proxy.failover_direct": False,
        "network.proxy.socks_remote_dns": True,
        "network.trr.mode": 5,
        "network.dns.disablePrefetch": True,
        "network.prefetch-next": False,
        "network.http.speculative-parallel-limit": 0,
        "network.http.http3.enable": False,
        "media.peerconnection.enabled": False,
        "app.update.enabled": False,
        "toolkit.telemetry.enabled": False,
        "datareporting.healthreport.uploadEnabled": False,
        "browser.safebrowsing.malware.enabled": False,
        "browser.safebrowsing.phishing.enabled": False,
        "extensions.update.enabled": False,
    }
    out = ["// Written by Pantheon (`src/local_browser.py`): every connection through its proxy."]
    for k, v in prefs.items():
        val = ("true" if v else "false") if isinstance(v, bool) else (
            str(v) if isinstance(v, int) else '"' + str(v) + '"')
        out.append(f'user_pref("{k}", {val});')
    return "\n".join(out) + "\n"


# ── the host: every person's browser, in this process ────────────────────────

class _LocalSystem:
    """What `workstation.browser.Browsers` asks of a host, answered for this
    process: no accounts to make, no desktop (headless), Pantheon's own user."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def ensure(self, account: str) -> Dict:
        home = self.home(account)
        home.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(home, 0o700)
        except OSError:
            pass  # a filesystem without modes (Windows): the data folder is the boundary
        return {"home": str(home)}

    def wake(self, account: str) -> None:
        return None

    def run_as(self, account: str) -> Tuple[List[str], Dict[str, str]]:
        keep = ("PATH", "LANG", "LC_ALL", "TZ", "TMPDIR", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
                "LOCALAPPDATA", "APPDATA", "USERPROFILE", "FONTCONFIG_PATH", "FONTCONFIG_FILE",
                "XDG_RUNTIME_DIR")
        env = {k: os.environ[k] for k in keep if k in os.environ}
        env["HOME"] = str(self.home(account))
        env["MOZ_CRASHREPORTER_DISABLE"] = "1"
        env.pop("DISPLAY", None)
        return [], env

    def home(self, account: str) -> Path:
        return self.root / account

    def own(self, account: str, paths) -> None:
        return None


class LocalBrowsers:
    """Every person's browser in this process, and who holds each."""

    def __init__(self, root: Optional[Path] = None) -> None:
        from workstation.browser import Browsers
        if root is None:
            from src.constants import DATA_DIR
            root = Path(DATA_DIR) / PROFILE_ROOT_NAME
        self.root = Path(root)
        self.proxy = GuardProxy()
        self.browsers = Browsers(_LocalSystem(self.root))
        self._holders: Dict[str, Dict[str, Any]] = {}
        self._used: Dict[str, float] = {}
        self._lock = threading.Lock()

    def _browser(self, account: str):
        b = self.browsers.get(account)
        b.extra_prefs = proxy_prefs(self.proxy.port())
        return b

    def holder(self, account: str) -> Dict[str, Any]:
        with self._lock:
            return dict(self._holders.get(account) or {"holder": "agent", "since": None})

    def control(self, account: str, holder: str) -> Dict[str, Any]:
        if holder not in P.HOLDERS:
            raise WorkstationError("bad_request", "“holder” is “agent” or “person”.")
        rec = {"holder": holder, "since": time.time()}
        with self._lock:
            self._holders[account] = rec
        return dict(rec)

    def _sweep(self, keep: str) -> None:
        """`IDLE_STOP_S`: stop the browsers nobody has used for that long."""
        now = time.monotonic()
        with self._lock:
            self._used[keep] = now
            idle = [a for a, at in self._used.items() if a != keep and now - at > IDLE_STOP_S]
            for a in idle:
                self._used.pop(a, None)
        for a in idle:
            logger.info("pantheon browser of %s stopped after %d minutes unused", a, IDLE_STOP_S // 60)
            self.browsers.stop(a)

    def act(self, account: str, body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """`agentd.Workstation.browser`'s rules, here."""
        from workstation.browser import BrowserError
        action = body.get("action")
        if action not in P.BROWSER_ACTIONS:
            raise WorkstationError("bad_request", f"“action” is one of {', '.join(P.BROWSER_ACTIONS)}.")
        who = body.get("holder") or "agent"
        if who not in P.HOLDERS:
            raise WorkstationError("bad_request", "“holder” is “agent” or “person”.")
        if (who == "agent" and action != "frame" and action not in P.NOTE_ACTIONS
                and self.holder(account)["holder"] == "person"):
            raise WorkstationError("busy", BUSY_SENTENCE)
        self._sweep(account)
        try:
            b = self._browser(account)
            if action in P.NOTE_ACTIONS:
                return b.note(action, body, who=who)
            if action == "frame":
                since = body.get("since", 0)
                since = since if isinstance(since, int) and not isinstance(since, bool) and since >= 0 else 0
                return b.frame(str(body.get("if_none_match") or ""), since)
            return b.act(action, body, who=who)
        except BrowserError as e:
            code = e.code if e.code in P.ERRORS else (
                "bad_request" if e.code in ("gone", "refused") else "unavailable")
            if code == "unavailable" and "no Firefox" in e.message:
                raise WorkstationError(code, NO_FIREFOX_SENTENCE)
            raise WorkstationError(code, e.message)

    def stop_all(self) -> None:
        self.browsers.stop_all()
        self.proxy.stop()


_host: Optional[LocalBrowsers] = None
_host_lock = threading.Lock()


def host() -> LocalBrowsers:
    global _host
    with _host_lock:
        if _host is None:
            _host = LocalBrowsers()
            atexit.register(_host.stop_all)
        return _host


class LocalBrowserClient:
    """The calls the window and the tool make of a workstation's browser,
    answered by `host()`. Async like `WorkstationClient`; the browser itself
    is synchronous, so each call runs in a thread."""

    runs_in = RUNS_IN_PANTHEON

    def __init__(self, browsers: Optional[LocalBrowsers] = None) -> None:
        self._browsers = browsers

    @property
    def browsers(self) -> LocalBrowsers:
        return self._browsers or host()

    async def browser(self, account: str, action: str, *, holder: str = "agent",
                      **fields: Any) -> Optional[Dict[str, Any]]:
        body = {k: v for k, v in fields.items() if v is not None}
        body.update(action=action, holder=holder)
        return await asyncio.to_thread(self.browsers.act, account, body)

    async def control(self, account: str, holder: str) -> Dict[str, Any]:
        return self.browsers.control(account, holder)

    async def ensure(self, account: str) -> Dict[str, Any]:
        return {"account": account, "holder": self.browsers.holder(account)["holder"]}

    async def names(self, account: str, names: Dict[str, str], pins: List[Dict[str, str]]) -> Dict:
        # A mapped name is a LAN name, and this browser does not reach the LAN.
        return {}


def firefox_here() -> bool:
    from workstation.browser import find_firefox
    return find_firefox() is not None


def may_use(owner: Optional[str], *, auth_manager: Any = None) -> bool:
    """`can_use_browser`, resolved the way every privilege is."""
    try:
        from src.owner_identity import normalize_owner
        name = normalize_owner(owner)
        if not name:
            return False
        if auth_manager is None:
            from src.auth_manager_access import shared_auth_manager
            auth_manager = shared_auth_manager()
        if not getattr(auth_manager, "is_configured", False):
            return False
        from src.auth_helpers import resolve_privilege
        privs = auth_manager.get_privileges(name) or {}
        return resolve_privilege(privs if isinstance(privs, dict) else {}, PRIVILEGE) is True
    except Exception as e:  # noqa: BLE001 — an unanswerable question is a no
        logger.warning("could not resolve %s for %r: %s", PRIVILEGE, owner, e)
        return False


def browser_for(owner: Optional[str], *, auth_manager: Any = None):
    """`(client, account)` for this person's browser: their workstation's when
    it would answer them, else Pantheon's own — or a `WorkstationError`
    saying why there is neither."""
    from src import workstation_access as wa
    try:
        return wa.workstation_for(owner, auth_manager=auth_manager)
    except WorkstationError as ws_refusal:
        if not may_use(owner, auth_manager=auth_manager):
            raise WorkstationError("not_permitted", NOT_PERMITTED_SENTENCE) from None
        if not firefox_here():
            if ws_refusal.code in ("off", "unconfigured"):
                raise WorkstationError("unavailable", NO_FIREFOX_SENTENCE) from None
            raise
        return LocalBrowserClient(), wa.account_of(owner)


async def ready_browser(owner: Optional[str], *, auth_manager: Any = None):
    """`browser_for`, with the workstation made ready when it is the one
    (`workstation_access.ensure_ready`: the account, and the admin's settings
    pushed)."""
    client, account = browser_for(owner, auth_manager=auth_manager)
    if isinstance(client, LocalBrowserClient):
        return client, account
    from src.workstation_access import ensure_ready
    ready = await ensure_ready(owner, auth_manager=auth_manager)
    return ready.client, ready.account


def unavailable_reason(owner: Optional[str], *, delegated_credential: bool = False) -> Optional[str]:
    """Why this turn is not offered `agent_browser`, or None when it is."""
    if delegated_credential:
        return TOKEN_SENTENCE
    try:
        browser_for(owner)
    except WorkstationError as e:
        return e.message
    except Exception as e:  # noqa: BLE001 — an unanswerable question is a no
        logger.warning("could not decide whether %r may use the browser: %s", owner, e)
        return "Pantheon could not read the browser's settings."
    return None


def runs_in(client: Any) -> Optional[str]:
    """`ran_in` for a tool result: `workstation`, or None for Pantheon's own."""
    return None if isinstance(client, LocalBrowserClient) else RUNS_IN_WORKSTATION


__all__ = ["BUSY_SENTENCE", "GuardProxy", "IDLE_STOP_S", "LocalBrowserClient", "LocalBrowsers",
           "NOT_PERMITTED_SENTENCE", "NO_FIREFOX_SENTENCE", "PRIVILEGE", "RUNS_IN_PANTHEON",
           "RUNS_IN_WORKSTATION", "browser_for", "firefox_here", "host", "may_use", "proxy_prefs",
           "ready_browser", "runs_in", "unavailable_reason"]
