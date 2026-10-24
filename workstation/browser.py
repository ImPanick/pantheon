# SPDX-License-Identifier: AGPL-3.0-or-later
"""The agent browser: each person's own Firefox, driven over WebDriver BiDi.
`P25-05`.

The owner (2026-10-24): *"this means we need an agent browser that's in
app."* The browser is the Firefox already in every workstation (`P20-01`:
Mozilla's build, phoning nowhere), started for the account **as the account**
— so the admin's network mode holds for it exactly as for the account's shell
(`P20-06`) — on the account's own display when it has one, so the desktop and
the in-app window show the same browser, and headless when it has none.

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
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from workstation import protocol as P
from workstation.bidi import BidiError, Session

logger = logging.getLogger(__name__)

PROFILE_DIR = ".pantheon/browser"
START_TIMEOUT_S = 30.0
NAV_TIMEOUT_S = 45.0
READ_MAX_CHARS = 12_000
ELEMENTS_MAX = 150
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

# The page as the agent reads it: its text, and the elements a person could
# click or type into, numbered in document order and marked so the number
# finds the element again. Visible ones only; hidden inputs are not offered.
READ_FN = r"""(maxChars, maxEls) => {
  const seen = new Set();
  const sel = 'a[href], button, input:not([type=hidden]), select, textarea, summary, ' +
              '[role=button], [role=link], [role=tab], [role=menuitem], [role=checkbox], ' +
              '[contenteditable=""], [contenteditable=true], [onclick]';
  document.querySelectorAll('[data-pantheon-ref]').forEach((e) => e.removeAttribute('data-pantheon-ref'));
  const out = [];
  let n = 0;
  for (const el of document.querySelectorAll(sel)) {
    if (out.length >= maxEls) break;
    if (seen.has(el)) continue;
    seen.add(el);
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    if (r.width < 2 || r.height < 2 || st.visibility === 'hidden' || st.display === 'none') continue;
    n += 1;
    el.setAttribute('data-pantheon-ref', String(n));
    const tag = el.tagName.toLowerCase();
    const label = (el.getAttribute('aria-label') || el.innerText || el.value || el.placeholder ||
                   el.title || el.alt || el.name || '').replace(/\s+/g, ' ').trim().slice(0, 80);
    const item = { ref: n, tag, label };
    if (tag === 'input') item.type = el.type || 'text';
    if (tag === 'a') item.href = el.href.slice(0, 200);
    if (el.disabled) item.disabled = true;
    out.push(item);
  }
  const text = (document.body ? document.body.innerText : '').replace(/\n{3,}/g, '\n\n');
  return JSON.stringify({ title: document.title, url: location.href,
                          text: text.slice(0, maxChars), cut: text.length > maxChars, elements: out });
}"""

# Where an element is, in the viewport's pixels, after bringing it into view.
WHERE_FN = r"""(ref) => {
  const el = document.querySelector('[data-pantheon-ref="' + ref + '"]');
  if (!el) return '';
  el.scrollIntoView({ block: 'center', inline: 'center' });
  const r = el.getBoundingClientRect();
  return JSON.stringify({ x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2),
                          editable: !!(el.isContentEditable || /^(input|textarea|select)$/i.test(el.tagName)) });
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


class AccountBrowser:
    """One person's browser: the process, its session, its tabs."""

    def __init__(self, launch_prefix: List[str], env: Dict[str, str], profile: Path,
                 headless: bool, own=None):
        self.launch_prefix = launch_prefix
        self.env = env
        self.profile = profile
        self.headless = headless
        self.own = own
        self.proc: Optional[subprocess.Popen] = None
        self.session: Optional[Session] = None
        self.current: Optional[str] = None
        self.lock = threading.RLock()

    # -- life -------------------------------------------------------------------

    def running(self) -> bool:
        return (self.proc is not None and self.proc.poll() is None
                and self.session is not None and not self.session.closed)

    def start(self) -> None:
        firefox = shutil.which("firefox")
        if not firefox:
            raise BrowserError("unavailable", "This workstation has no Firefox, so it has no browser.")
        self.profile.mkdir(parents=True, exist_ok=True)
        (self.profile / "user.js").write_text(USER_JS, encoding="utf-8")
        if self.own:
            self.own([self.profile.parent, self.profile, self.profile / "user.js"])
        argv = self.launch_prefix + [firefox, "--remote-debugging-port=0", "--no-remote",
                                     "--profile", str(self.profile)]
        if self.headless:
            argv.append("--headless")
        argv.append("about:blank")
        self.proc = subprocess.Popen(argv, env=self.env, stdout=subprocess.PIPE,
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
            pass

    def stop(self) -> None:
        with self.lock:
            if self.session is not None:
                try:
                    self.session.close()
                except Exception:  # noqa: BLE001
                    pass
            self.session = None
            if self.proc is not None and self.proc.poll() is None:
                try:
                    os.killpg(self.proc.pid, 15)
                    self.proc.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(self.proc.pid, 9)
                    except OSError:
                        pass
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
        try:
            self._call("browsingContext.setViewport",
                       {"context": ctx, "viewport": {"width": P.BROWSER_WIDTH, "height": P.BROWSER_HEIGHT}})
        except BrowserError:
            pass

    def _ctx(self) -> str:
        ids = [c["context"] for c in self._contexts()]
        if not ids:
            got = self._call("browsingContext.create", {"type": "tab"})
            ids = [got["context"]]
        if self.current not in ids:
            self.current = ids[0]
        return self.current

    def _eval(self, ctx: str, fn: str, *args: Any) -> Any:
        got = self._call("script.callFunction", {
            "functionDeclaration": fn, "awaitPromise": False, "target": {"context": ctx},
            "arguments": [_arg(a) for a in args]})
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
            pass
        url = next((t["url"] for t in tabs if t["tab"] == ctx), "")
        return {"url": url, "title": title, "tabs": tabs}

    # -- actions ----------------------------------------------------------------

    def act(self, action: str, body: Dict) -> Dict:
        with self.lock:
            if not self.running():
                self.stop()
                self.start()
            ctx = self._ctx()
            out: Dict[str, Any] = {"ok": True, "action": action}
            if action == "open":
                self._call("browsingContext.navigate", {"context": ctx, "url": check_url(body.get("url")),
                                                        "wait": "complete"}, timeout=NAV_TIMEOUT_S)
            elif action == "read":
                raw = self._eval(ctx, READ_FN, READ_MAX_CHARS, ELEMENTS_MAX)
                out.update(json.loads(raw or "{}"))
                return out
            elif action == "click":
                if body.get("ref") is not None:
                    at = self._where(ctx, body.get("ref"))
                    x, y = at["x"], at["y"]
                else:
                    x, y = _xy(body)
                self._point(ctx, x, y, clicks=2 if body.get("double") else 1)
                time.sleep(0.4)
            elif action == "type":
                text = body.get("text")
                if not isinstance(text, str) or len(text) > P.MAX_TYPE_CHARS:
                    raise BrowserError("bad_request", f"“text” is at most {P.MAX_TYPE_CHARS} characters.")
                if body.get("ref") is not None:
                    at = self._where(ctx, body.get("ref"))
                    self._point(ctx, at["x"], at["y"])
                    if at.get("editable"):
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
                    pass
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

    def _tab(self, body: Dict) -> str:
        want = body.get("tab")
        tabs = [c["context"] for c in self._contexts()]
        if isinstance(want, int) and not isinstance(want, bool) and 1 <= want <= len(tabs):
            return tabs[want - 1]
        if isinstance(want, str) and want in tabs:
            return want
        raise BrowserError("bad_request", f"“tab” is a tab's number, 1 to {len(tabs)}.")

    def frame(self, if_none_match: str = "") -> Optional[Dict]:
        with self.lock:
            if not self.running():
                self.stop()
                self.start()
            ctx = self._ctx()
            shot = self._call("browsingContext.captureScreenshot", {"context": ctx})
            data = base64.b64decode(shot.get("data") or "")
            digest = hashlib.sha256(data).hexdigest()[:16]
            if if_none_match and digest == if_none_match:
                return None
            out = {"mime": "image/png", "data_b64": shot.get("data") or "", "digest": digest,
                   "width": P.BROWSER_WIDTH, "height": P.BROWSER_HEIGHT}
            out.update(self.state(ctx))
            return out


def _arg(a: Any) -> Dict:
    if isinstance(a, bool):
        return {"type": "boolean", "value": a}
    if isinstance(a, (int, float)):
        return {"type": "number", "value": a}
    return {"type": "string", "value": str(a)}


def _xy(body: Dict):
    x, y = body.get("x"), body.get("y")
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (x, y)):
        raise BrowserError("bad_request", "A click names an element (“ref”) or a point (“x”, “y”).")
    if not (0 <= x < P.BROWSER_WIDTH and 0 <= y < P.BROWSER_HEIGHT):
        raise BrowserError("bad_request", f"The page is {P.BROWSER_WIDTH}×{P.BROWSER_HEIGHT}; that point is off it.")
    return x, y


def _bounded(v: Any, name: str, limit: int) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or abs(v) > limit:
        raise BrowserError("bad_request", f"“{name}” is a whole number from -{limit} to {limit}.")
    return v


class Browsers:
    """Every account's browser, made on first use."""

    def __init__(self, system) -> None:
        self.system = system
        self._by_account: Dict[str, AccountBrowser] = {}
        self._lock = threading.Lock()

    def get(self, account: str) -> AccountBrowser:
        with self._lock:
            b = self._by_account.get(account)
            if b is None:
                self.system.ensure(account)
                display = None
                try:
                    display = self.system.wake(account)
                except Exception:  # noqa: BLE001 — a desktop that will not start: headless
                    display = None
                prefix, env = self.system.run_as(account)
                env = dict(env)
                headless = not (display or env.get("DISPLAY"))
                if display and not env.get("DISPLAY"):
                    env["DISPLAY"] = display
                env.setdefault("HOME", str(self.system.home(account)))
                env["MOZ_CRASHREPORTER_DISABLE"] = "1"
                profile = Path(self.system.home(account)) / PROFILE_DIR
                b = AccountBrowser(prefix, env, profile, headless,
                                   own=lambda paths, a=account: self.system.own(a, paths))
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
