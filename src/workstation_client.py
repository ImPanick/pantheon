# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pantheon's side of the workstation — `P20-02`, `D-2026-09-30-03`.

The workstation is a separate machine (a container beside Pantheon, a VM, or
any host running `workstation/agentd.py`), and this module is the only thing in
Pantheon that talks to it. It imports the protocol rather than restating it
(`Law 7`): a route, a field bound or an error code exists once, in
`workstation/protocol.py`, and the daemon reads the same file.

**WHERE IT IS, AND THE TOKEN, WITHOUT ANYONE TYPING EITHER.** The admin setting
wins; otherwise the environment the compose overlay sets
(`PANTHEON_WORKSTATION_URL`); otherwise nothing, and the workstation is off. The
token: the setting, then `PANTHEON_WORKSTATION_TOKEN`, then the file the daemon
wrote into the pairing volume the two services share. Switching the overlay on
is the consent; nothing ships pointing anywhere (`D-2026-08-31-01`).

**WHY THE URL IS NOT PUT THROUGH THE SSRF VALIDATORS.** They guard addresses
that arrive from content. This one is an admin's setting, and every request's
path comes from `protocol.ROUTES` — the same argument `src/netagent_client.py`
makes: there is no parameter through which a model can name where a request
goes. Calls go through `src.paced_http` / the outbound limiter like every other
(a local host is paced at zero, so it costs nothing).

**NEVER RAISES ANYTHING BUT `WorkstationError`,** whose `message` is a sentence
for a person — the tool layer puts it in the card as it stands.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Union
from urllib.parse import urlencode, urlsplit, urlunsplit

from workstation import protocol as P

logger = logging.getLogger(__name__)

URL_ENV = P.URL_ENV
_TIMEOUT = 30.0
# An exec's answer can take as long as the command; the daemon enforces the
# command's own timeout and this only has to outlast it.
_EXEC_GRACE_S = 15.0

account_for = P.account_name


class WorkstationError(Exception):
    """What went wrong, as a protocol code and a sentence for a person."""

    def __init__(self, code: str, message: str, status: int = 0):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def as_result(self) -> Dict[str, Any]:
        """The shape a tool handler returns, so a refusal reads like any other
        failed tool call."""
        return {"error": self.message, "exit_code": 1, "workstation_error": self.code}


def _setting(key: str, default: Any = "") -> Any:
    try:
        from src.settings import get_setting
        return get_setting(key, default)
    except Exception:  # noqa: BLE001 — unreadable settings are "not configured"
        return default


def parse_base(raw: str) -> Optional[str]:
    """An origin (`scheme://host[:port]`) out of a string, or None. Rebuilt from
    its parts, so a value carrying a path, a query or credentials cannot
    survive by looking like a base URL (`src/netagent_client.parse_agent_base`)."""
    raw = str(raw or "").strip()
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    if parts.username or parts.password:
        return None
    if port is not None and not 1 <= port <= 65535:
        return None
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


# Where a value came from, as the Settings panel says it (`P20-02`). One word
# per layer, in the order the layers are consulted; `none` means no layer
# answered. An enum rather than a pair of booleans (`Law 10`).
SOURCE_SETTING = "setting"
SOURCE_ENVIRONMENT = "environment"
SOURCE_PAIRING = "pairing"
SOURCE_NONE = "none"


def resolve_base() -> tuple[Optional[str], str]:
    """`(origin, source)`: the address in effect and the layer it came from.

    `P20-02`. The order lives here and only here — `configured_base` is this
    function's first half — so the panel's "where it came from" and the address
    the client actually calls cannot disagree (`Law 7`). A stored value that
    does not parse falls through to the environment rather than winning; the
    settings route refuses one at the moment it is typed, so that only happens
    to a hand-edited file."""
    stored = parse_base(str(_setting("workstation_url", "") or ""))
    if stored:
        return stored, SOURCE_SETTING
    env = parse_base(os.environ.get(URL_ENV, ""))
    if env:
        return env, SOURCE_ENVIRONMENT
    return None, SOURCE_NONE


def configured_base() -> Optional[str]:
    return resolve_base()[0]


def pairing_token_path() -> Path:
    return Path(os.environ.get(P.PAIRING_DIR_ENV) or P.DEFAULT_PAIRING_DIR) / P.TOKEN_FILENAME


def resolve_token() -> tuple[str, str]:
    """`(token, source)`. The value never leaves the server: the panel is told
    the source and whether there is one, and nothing else (`P20-02`)."""
    token = str(_setting("workstation_token", "") or "").strip()
    if token:
        return token, SOURCE_SETTING
    token = (os.environ.get(P.TOKEN_ENV) or "").strip()
    if token:
        return token, SOURCE_ENVIRONMENT
    try:
        token = pairing_token_path().read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    if token:
        return token, SOURCE_PAIRING
    return "", SOURCE_NONE


def configured_token() -> str:
    return resolve_token()[0]


def enabled() -> bool:
    """The admin's switch. Off by default: a workstation nobody turned on does
    nothing, even if the overlay is running."""
    return _setting("workstation_enabled", False) is True


def from_settings() -> Optional["WorkstationClient"]:
    """The configured client, or None when the workstation is off or has no
    address. A missing token is not None — it is a client whose calls say
    what is missing, because "off" and "misconfigured" are different answers."""
    if not enabled():
        return None
    base = configured_base()
    if not base:
        return None
    return WorkstationClient(base, configured_token())


ProgressCb = Callable[[str, str], Union[None, Awaitable[None]]]


class WorkstationClient:
    """One workstation, one token. Every method is one route in `ROUTES`."""

    def __init__(self, base: str, token: str, *, timeout: float = _TIMEOUT):
        parsed = parse_base(base)
        if not parsed:
            raise WorkstationError("bad_request", f"{base!r} is not a workstation address.")
        self.base = parsed
        self.token = token or ""
        self.timeout = timeout

    # -- plumbing ---------------------------------------------------------------

    def _url(self, name: str, account: Optional[str] = None, query: Optional[Dict] = None):
        method, path = P.route_path(name, account)
        url = f"{self.base}{path}"
        if query:
            url += "?" + urlencode({k: v for k, v in query.items() if v is not None})
        return method, url

    def _headers(self) -> Dict[str, str]:
        if not self.token:
            raise WorkstationError(
                "unauthorized",
                "Pantheon has no token for the workstation. It is read from the pairing volume the "
                "workstation shares with Pantheon, or set in Settings → Workstation.")
        return {"Authorization": f"Bearer {self.token}"}

    @staticmethod
    def _error_from(response) -> WorkstationError:
        status = getattr(response, "status_code", 0)
        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            body = {}
        code = body.get("error") if isinstance(body, dict) else None
        message = body.get("message") if isinstance(body, dict) else None
        if status == 401:
            return WorkstationError(
                "unauthorized",
                "The workstation refused Pantheon's token. If it was set by hand, it must match "
                "the workstation's PANTHEON_WORKSTATION_TOKEN.", status)
        if code in P.ERRORS and message:
            return WorkstationError(code, str(message), status)
        return WorkstationError("internal", f"The workstation answered {status}.", status)

    async def _call(self, name: str, account: Optional[str] = None, body: Optional[Dict] = None,
                    *, query: Optional[Dict] = None, timeout: Optional[float] = None,
                    allow_304: bool = False) -> Optional[Dict]:
        method, url = self._url(name, account, query)
        headers = self._headers() if name != "health" else (
            {"Authorization": f"Bearer {self.token}"} if self.token else {})
        try:
            from src import paced_http
            kwargs: Dict[str, Any] = {"headers": headers, "timeout": timeout or self.timeout,
                                      "authenticated": True}
            if method == "POST":
                kwargs["json"] = body or {}
            response = await paced_http.request(method, url, **kwargs)
        except WorkstationError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.info("workstation unreachable at %s: %s", self.base, type(e).__name__)
            raise WorkstationError(
                "unavailable",
                f"The workstation at {self.base} did not answer ({type(e).__name__}). "
                "Is it running?") from e
        if allow_304 and response.status_code == 304:
            return None
        if response.status_code != 200:
            raise self._error_from(response)
        try:
            payload = response.json()
        except Exception as e:  # noqa: BLE001
            raise WorkstationError("internal", "The workstation answered with something that is "
                                               "not JSON.") from e
        if not isinstance(payload, dict):
            raise WorkstationError("internal", "The workstation's answer was not an object.")
        return payload

    # -- the routes -------------------------------------------------------------

    async def health(self) -> Dict:
        payload = await self._call("health")
        if payload.get("agent") != P.AGENT_NAME:
            # Something answered on that port, and it is not a workstation.
            raise WorkstationError(
                "unavailable", f"Something answered at {self.base}, but it is not a Pantheon "
                               "workstation.")
        if payload.get("protocol") != P.PROTOCOL_VERSION:
            raise WorkstationError(
                "unavailable", f"The workstation speaks protocol {payload.get('protocol')}; this "
                               f"Pantheon speaks {P.PROTOCOL_VERSION}. Update the older one.")
        return payload

    async def config(self, **settings: Any) -> Dict:
        return await self._call("config", body=settings)

    async def ensure(self, account: str) -> Dict:
        return await self._call("ensure", account)

    async def reset(self, account: str) -> Dict:
        return await self._call("reset", account, timeout=120.0)

    async def control(self, account: str, holder: str) -> Dict:
        return await self._call("control", account, {"holder": holder})

    async def exec(self, account: str, command: str, *, shell: str = "bash",
                   cwd: Optional[str] = None, timeout_s: float = P.DEFAULT_EXEC_TIMEOUT_S,
                   env: Optional[Dict[str, str]] = None, stdin: Optional[str] = None,
                   on_output: Optional[ProgressCb] = None) -> Dict:
        """Run a command as `account`. With `on_output`, the output is streamed
        to it as `(kind, text)` while the command runs; the return value is the
        same either way."""
        body: Dict[str, Any] = {"command": command, "shell": shell, "timeout_s": timeout_s}
        if cwd:
            body["cwd"] = cwd
        if env:
            body["env"] = env
        if stdin is not None:
            body["stdin"] = stdin
        wait = min(float(timeout_s), P.MAX_EXEC_TIMEOUT_S) + _EXEC_GRACE_S
        if on_output is None:
            return await self._call("exec", account, body, timeout=wait)
        return await self._stream_exec(account, dict(body, stream=True), on_output, wait)

    async def _stream_exec(self, account: str, body: Dict, on_output: ProgressCb,
                           wait: float) -> Dict:
        import inspect

        import httpx

        from src.paced_http import _host, _observe
        from src.rate_limiter import outbound

        method, url = self._url("exec", account)
        host = _host(url)
        await outbound.acquire_async(host, authenticated=True)
        result: Optional[Dict] = None
        try:
            async with httpx.AsyncClient(timeout=wait) as client:
                async with client.stream(method, url, json=body, headers=self._headers()) as r:
                    _observe(host, r)
                    if r.status_code != 200:
                        await r.aread()
                        raise self._error_from(r)
                    async for line in r.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if event.get("type") == "exit":
                            result = {k: v for k, v in event.items() if k != "type"}
                            continue
                        out = on_output(str(event.get("type")), str(event.get("data") or ""))
                        if inspect.isawaitable(out):
                            await out
        except WorkstationError:
            raise
        except Exception as e:  # noqa: BLE001
            outbound.note_failure(host)
            raise WorkstationError(
                "unavailable", f"The workstation at {self.base} stopped answering while the "
                               f"command ran ({type(e).__name__}).") from e
        if result is None:
            raise WorkstationError("internal", "The workstation ended the command without a result.")
        if result.get("error") in P.ERRORS and "stdout" not in result:
            raise WorkstationError(result["error"], str(result.get("message") or ""))
        return result

    async def read(self, account: str, path: str, *, offset: int = 0,
                   max_bytes: Optional[int] = None) -> Dict:
        """`{"path", "size", "data": bytes, "truncated"}`."""
        body: Dict[str, Any] = {"path": path, "offset": offset}
        if max_bytes is not None:
            body["max_bytes"] = max_bytes
        payload = await self._call("read", account, body, timeout=120.0)
        payload["data"] = base64.b64decode(payload.pop("data_b64", "") or "")
        return payload

    async def write(self, account: str, path: str, data: Union[bytes, str], *,
                    append: bool = False, make_dirs: bool = True) -> Dict:
        raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        if len(raw) > P.MAX_FILE_BYTES:
            raise WorkstationError("too_large", f"A file is at most {P.MAX_FILE_BYTES:,} bytes.")
        return await self._call("write", account, {
            "path": path, "data_b64": base64.b64encode(raw).decode(),
            "append": bool(append), "make_dirs": bool(make_dirs)}, timeout=120.0)

    async def list(self, account: str, path: Optional[str] = None, *, recursive: bool = False,
                   max_entries: Optional[int] = None) -> Dict:
        body: Dict[str, Any] = {"recursive": bool(recursive)}
        if path:
            body["path"] = path
        if max_entries is not None:
            body["max_entries"] = max_entries
        return await self._call("list", account, body)

    async def screenshot(self, account: str, *, fmt: str = "png",
                         if_none_match: Optional[str] = None) -> Optional[Dict]:
        """The screen, or None when `if_none_match` names the frame already held."""
        return await self._call("screenshot", account,
                                query={"format": fmt, "if_none_match": if_none_match},
                                allow_304=True)

    async def input(self, account: str, action: str, *, holder: str = "agent",
                    screenshot_after: bool = False, **fields: Any) -> Dict:
        if action not in P.INPUT_ACTIONS:
            raise WorkstationError("bad_request",
                                   f"“{action}” is not one of {', '.join(P.INPUT_ACTIONS)}.")
        body = {"action": action, "holder": holder, "screenshot_after": bool(screenshot_after),
                **{k: v for k, v in fields.items() if v is not None}}
        return await self._call("input", account, body, timeout=P.MAX_WAIT_MS / 1000 + _TIMEOUT)


__all__ = ["SOURCE_ENVIRONMENT", "SOURCE_NONE", "SOURCE_PAIRING", "SOURCE_SETTING", "URL_ENV",
           "WorkstationClient", "WorkstationError", "account_for", "configured_base",
           "configured_token", "enabled", "from_settings", "pairing_token_path", "parse_base",
           "resolve_base", "resolve_token"]
