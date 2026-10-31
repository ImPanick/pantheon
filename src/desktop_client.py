# SPDX-License-Identifier: AGPL-3.0-or-later
"""The live desktop's web client — `D-2026-10-31-01`.

The Workstation window shows a person's desktop as it moves, and lets them take
it over, through KasmVNC: its X server is each person's display in the
workstation (`workstation/ubuntu.py`), and its web client draws that display in
the window. This module is where the web client comes from, and the answer is
**Pantheon, never the workstation.**

**WHY PANTHEON SERVES IT.** The workstation is the one place in the install
built to run what an agent is told to run, and with `sudo` on (the default)
the agent is root there. A client served from the workstation — through
Pantheon's origin, as a proxy would — would be script that root in the
workstation could rewrite, running in a person's browser with their session.
So the workstation is asked for the desktop's *stream* only
(`protocol.ROUTES["desktop"]`, relayed by `routes/workstation_routes.py`), and
the script that reads it is a copy Pantheon's image unpacked when it was built,
from the same pinned, checksummed KasmVNC package the workstation installs
(`workstation/provision.sh client`, the `desktop-client` stage in
`Dockerfile`). Nothing a workstation says changes a byte of it.

**WHERE.** `PREFIX`, under `/api/`, so `AuthMiddleware` gates it like every
other API path: a caller with no session is refused, and the service worker
(which leaves `/api/` alone) never caches it. Only GET and HEAD, only files
under the unpacked folder (Starlette's `StaticFiles` resolves every path and
refuses one that leaves it). `core/middleware.py` gives these responses their
own policy: framed by Pantheon's own pages only, its scripts and the hashes of
the page's own inline block, WebAssembly for the client's decoder, and every
connection back to this origin.

**WITHOUT IT** — a checkout run outside the image, where nothing unpacked the
client — `available()` is False, the window says so and shows the screen as
pictures, as it did before the desktop streamed.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlencode

from starlette.responses import PlainTextResponse, Response
from starlette.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

#: Where the client is served. Under `/api/`: gated, and never cached by the worker.
PREFIX = "/api/workstation/desktop/client"
#: Where the image unpacked it (`Dockerfile`, stage `desktop-client`).
DIR_ENV = "PANTHEON_DESKTOP_CLIENT_DIR"
DEFAULT_DIR = "/opt/pantheon/kasmvnc/www"
#: The client's page.
PAGE = "vnc.html"
#: The stream the client connects to, relative to the origin's root (the
#: client builds `ws(s)://<this host>/<path>`).
STREAM_PATH = "api/workstation/desktop/websockify"

UNAVAILABLE_SENTENCE = ("This install has no live-desktop client — it comes with Pantheon's "
                        "Docker image — so the screen is shown as pictures.")


def client_dir() -> Path:
    return Path(os.environ.get(DIR_ENV) or DEFAULT_DIR)


def available() -> bool:
    """Whether the client is here to serve."""
    return (client_dir() / PAGE).is_file()


def page_url(*, watch_person: Optional[str] = None) -> str:
    """The client's page for the window's frame, told everything it needs in
    its own query (KasmVNC's client reads its settings there first): connect
    at once to Pantheon's stream — the caller's own desktop, or for an admin
    watching (`B1424`) that person's — scale the fixed-size screen to the frame,
    reconnect when the stream drops (a display restart, a reset), never
    disconnect for being idle, and hand the clipboard to the window both ways
    (`static/js/workstationScreen.js` bridges it to the person's own). A watcher
    is view-only here as well as at the workstation, which never lets a
    `watch` login drive, and is handed no clipboard: what another person copied
    is theirs, not something watching their screen shows."""
    path = STREAM_PATH
    if watch_person:
        path += "?" + urlencode({"person": watch_person})
    query = {
        "autoconnect": "true",
        "path": path,
        "resize": "scale",
        "reconnect": "true",
        "reconnect_delay": "1500",
        # Minutes. 0 is read as the client's default (20), so a large number is
        # "never": a person watching an agent work for an hour has not left.
        "idle_disconnect": "1440",
        "view_only": "true" if watch_person else "false",
        "clipboard_up": "false" if watch_person else "true",
        "clipboard_down": "false" if watch_person else "true",
        "clipboard_seamless": "false",
        "show_dot": "false",
        "enable_webrtc": "false",
    }
    return f"{PREFIX}/{PAGE}?" + urlencode(query, quote_via=quote)


class DesktopClientFiles(StaticFiles):
    """The unpacked client, served under `PREFIX` (module docstring)."""

    def __init__(self) -> None:
        super().__init__(directory=str(client_dir()), check_dir=False)

    async def check_config(self) -> None:
        # A checkout with no client is not a misconfiguration: it answers
        # every request with the sentence below rather than failing.
        if available():
            await super().check_config()

    async def get_response(self, path: str, scope) -> Response:
        if not available():
            return PlainTextResponse(UNAVAILABLE_SENTENCE, status_code=404,
                                     headers={"Cache-Control": "no-store"})
        response = await super().get_response(path, scope)
        # The page names its assets by content (`ui-DKMQOe2K.js`), so they may
        # be kept; the page itself is asked again each time, like the app's.
        if path.endswith(".html") or path in ("", "."):
            response.headers["Cache-Control"] = "no-cache"
        elif response.status_code == 200:
            response.headers["Cache-Control"] = "private, max-age=86400"
        return response

    def file_response(self, full_path, stat_result, scope, status_code=200):
        """The page's inline block is authorised by its hash, derived from the
        bytes on disk — the `/static` mount's rule (`B211`), the same function."""
        page = os.fspath(full_path)
        if page.endswith(".html"):
            try:
                from src.app_helpers import inline_script_hashes_for_file
                hashes = inline_script_hashes_for_file(page)
            except Exception:  # noqa: BLE001 — a page that cannot be hashed runs no inline script
                logger.exception("Failed to hash inline scripts in %s", page)
            else:
                if hashes:
                    scope.setdefault("state", {})["csp_script_hashes"] = hashes
        return super().file_response(full_path, stat_result, scope, status_code)


__all__ = ["DEFAULT_DIR", "DIR_ENV", "DesktopClientFiles", "PAGE", "PREFIX", "STREAM_PATH",
           "UNAVAILABLE_SENTENCE", "available", "client_dir", "page_url"]
