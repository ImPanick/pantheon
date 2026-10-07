# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scenes the showcase captures, and the browser that captures them.

Each scene is what a person does to get there — click the sidebar, press
Ctrl+K, drag a port — never a DOM edit. The browser state a capture sets is the
state a person's own choices leave: the palette they picked (`pantheon-theme`),
first-run tours switched off (Settings → Appearance), the snap tip seen.

**Two things only a capture adds, both to the picture and neither to the
product:** in a GIF, a drawn pointer that follows the real mouse events
(headless Chromium draws none), and a fixed 1440×900 or 390×844 window.

**Motion.** Captures run with `prefers-reduced-motion: no-preference`. With
`reduce`, opening the Workbench or the Forge window freezes the tab — `ui.js`'s
`_promote` re-raises a window's z-index forever while the reduced-motion guard
turns the change into a 0.01 ms transition it reads mid-flight (filed with the
showcase's handoff as a defect, not worked around here).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import media

DESKTOP = (1440, 900)
PHONE = (390, 844)
THEMES = ("dark", "light")
LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}

# A pointer for the GIFs, drawn over the page and moved by the page's own
# mouse and drag events. Built with DOM calls (the page's CSP allows no inline
# script, and a capture adds none).
_CURSOR_JS = r"""
(() => {
  if (window.__showcaseCursor) return;
  const svgNS = 'http://www.w3.org/2000/svg';
  const box = document.createElement('div');
  Object.assign(box.style, {position: 'fixed', left: '0px', top: '0px', width: '24px',
    height: '24px', zIndex: '2147483647', pointerEvents: 'none',
    transform: 'translate(-200px,-200px)', transition: 'none'});
  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('width', '24'); svg.setAttribute('height', '24'); svg.setAttribute('viewBox', '0 0 24 24');
  const path = document.createElementNS(svgNS, 'path');
  path.setAttribute('d', 'M3 2 L3 19 L7.5 14.8 L10.6 21.5 L13.4 20.2 L10.4 13.6 L16.6 13.6 Z');
  path.setAttribute('fill', '#ffffff'); path.setAttribute('stroke', '#111111');
  path.setAttribute('stroke-width', '1.4'); path.setAttribute('stroke-linejoin', 'round');
  svg.appendChild(path); box.appendChild(svg);
  const ring = document.createElement('div');
  Object.assign(ring.style, {position: 'absolute', left: '-9px', top: '-10px', width: '22px',
    height: '22px', borderRadius: '50%', border: '2px solid rgba(255,255,255,0.85)',
    boxShadow: '0 0 0 2px rgba(0,0,0,0.35)', opacity: '0'});
  box.insertBefore(ring, svg);
  document.documentElement.appendChild(box);
  const at = (e) => { if (e.clientX || e.clientY) box.style.transform = `translate(${e.clientX}px,${e.clientY}px)`; };
  for (const t of ['mousemove', 'pointermove', 'dragover', 'drag']) window.addEventListener(t, at, true);
  window.addEventListener('mousedown', () => { ring.style.opacity = '1'; }, true);
  window.addEventListener('mouseup', () => { ring.style.opacity = '0'; }, true);
  window.addEventListener('dragend', () => { ring.style.opacity = '0'; }, true);
  window.addEventListener('drop', () => { ring.style.opacity = '0'; }, true);
  window.__showcaseCursor = box;
})();
"""


@dataclass
class Scene:
    name: str
    kind: str          # "png" (dark + light), "phone" (one PNG), "gif"
    what: str          # the caption-sized sentence `--list` prints
    run: Callable
    needs: str = ""    # "workstation" — skipped without it


class Recorder:
    """Frames for a GIF: a screenshot after every step, each one GIF frame long.

    **Counted, not timed.** Every screenshot is one frame at `media.GIF_FPS`,
    and a pause is a number of frames, so a scene that does the same thing
    makes the same frames and a re-run leaves the committed GIF alone
    (`media._gif_unchanged`). A screenshot takes about as long as a frame
    lasts (measured: 88 ms against 83), so what the product animates still
    plays at about its own speed; only a wait on the product — a reply
    streaming — makes a different number of frames from run to run.
    """

    FRAME = 1.0 / media.GIF_FPS

    def __init__(self, page):
        self.page = page
        self.frames: List[Tuple[float, bytes]] = []
        self.clock = 0.0
        self.pos = (DESKTOP[0] * 0.55, DESKTOP[1] * 0.6)
        page.evaluate(_CURSOR_JS)
        page.mouse.move(*self.pos)

    def snap(self) -> None:
        self.frames.append((self.clock, self.page.screenshot()))
        self.clock += self.FRAME

    def hold(self, seconds: float) -> None:
        for _ in range(max(1, round(seconds / self.FRAME))):
            self.snap()

    def move(self, x: float, y: float, seconds: float = 0.7) -> None:
        sx, sy = self.pos
        steps = max(4, int(seconds * 12))
        for i in range(1, steps + 1):
            t = i / steps
            e = t * t * (3 - 2 * t)  # ease in and out
            self.page.mouse.move(sx + (x - sx) * e, sy + (y - sy) * e)
            self.snap()
        self.pos = (x, y)

    def move_to(self, locator, seconds: float = 0.7, dx: float = 0.5, dy: float = 0.5) -> Tuple[float, float]:
        box = locator.bounding_box()
        x, y = box["x"] + box["width"] * dx, box["y"] + box["height"] * dy
        self.move(x, y, seconds)
        return x, y

    def click(self, locator, seconds: float = 0.7, settle: float = 0.6, **kw) -> None:
        self.move_to(locator, seconds, **kw)
        self.page.mouse.down()
        self.snap()
        self.page.mouse.up()
        self.hold(settle)

    def drag(self, src, dst, seconds: float = 1.4, settle: float = 0.8,
             src_at=(0.5, 0.5), dst_at=(0.5, 0.5)) -> None:
        self.move_to(src, 0.6, *src_at)
        self.page.mouse.down()
        self.snap()
        box = dst.bounding_box()
        # A first nudge starts the drag the way a hand does.
        self.move(self.pos[0] + 6, self.pos[1] + 4, 0.15)
        self.move(box["x"] + box["width"] * dst_at[0], box["y"] + box["height"] * dst_at[1], seconds)
        self.page.mouse.up()
        self.hold(settle)

    def type(self, text: str, per_char: float = 0.045) -> None:
        for i, ch in enumerate(text):
            self.page.keyboard.type(ch)
            if per_char:
                time.sleep(per_char)
            if i % 2 or i == len(text) - 1:
                self.snap()

    def wheel(self, dy: float, steps: int = 8) -> None:
        """Scroll under the pointer, a notch at a time."""
        for _ in range(steps):
            self.page.mouse.wheel(0, dy / steps)
            self.snap()

    def key(self, key: str, settle: float = 0.5) -> None:
        self.page.keyboard.press(key)
        self.hold(settle)


class Studio:
    """One Chromium, and a fresh context per picture."""

    def __init__(self, pw, base: str, username: str, password: str, colours: Dict[str, Dict[str, str]],
                 out: Path, *, force: bool = False, model=None, client=None,
                 report: Optional[dict] = None, workstation: bool = False,
                 python: Optional[str] = None):
        self.base, self.username, self.password = base, username, password
        self.colours, self.out, self.force = colours, out, force
        self.model, self.client, self.report = model, client, report or {}
        self.workstation = workstation
        # The interpreter Pantheon runs with (it has the `mcp` package): what a
        # scene's demo MCP server is started with (`gif_describe`).
        self.python = python
        self.blocked: List[str] = []
        self.results: List[Tuple[str, str]] = []
        # `Law 16`. Everything off this machine goes to a proxy address nothing
        # answers on; loopback is the only bypass. Page requests are also
        # checked one by one below, so an attempt is recorded, not just refused.
        self.browser = pw.chromium.launch(
            args=["--proxy-server=http://127.0.0.1:9", "--proxy-bypass-list=127.0.0.1;localhost;[::1]",
                  "--disable-background-networking", "--disable-component-update",
                  "--disable-sync", "--no-pings", "--disable-default-apps",
                  "--disable-features=PushMessaging,Translate,OptimizationHints,MediaRouter"])

    # ── contexts ────────────────────────────────────────────────────────────

    def open(self, theme: str = "dark", size=DESKTOP, path: str = "/", phone: bool = False):
        ctx = self.browser.new_context(
            viewport={"width": size[0], "height": size[1]}, device_scale_factor=1,
            is_mobile=phone, has_touch=phone, locale="en-US",
            service_workers="block", reduced_motion="no-preference")
        theme_pref = json.dumps({"name": theme, "colors": self.colours[theme]})
        ctx.add_init_script(
            "try{"
            f"localStorage.setItem('pantheon-theme', {json.dumps(theme_pref)});"
            "localStorage.setItem('pantheon-hint-drag-to-snap-seen','1');"
            "localStorage.setItem('pantheon-ui-visibility', JSON.stringify({'first-run-tours': false}));"
            "}catch(_){}")
        ctx.route("**/*", self._guard)
        r = ctx.request.post(self.base + "/api/auth/login",
                             data={"username": self.username, "password": self.password, "remember": True})
        if not r.ok:
            raise RuntimeError(f"sign-in failed: {r.status}")
        page = ctx.new_page()
        page.goto(self.base + path, wait_until="domcontentloaded")
        page.wait_for_selector("#tool-workbench-btn", state="attached", timeout=60000)
        page.wait_for_timeout(2500)
        self.dismiss_hints(page)
        return page

    def _guard(self, route):
        host = urlparse(route.request.url).hostname or ""
        if route.request.url.startswith(("data:", "blob:")) or host in LOOPBACK:
            return route.continue_()
        self.blocked.append(route.request.url)
        return route.abort()

    @staticmethod
    def dismiss_hints(page) -> None:
        """Answer any first-open hint the way a person does: its own button."""
        for btn in page.locator(".tour-hint .tour-hint-dismiss").all():
            try:
                if btn.is_visible():
                    btn.click(timeout=2000)
            except Exception:
                pass  # a hint that left on its own is the outcome wanted; the shot follows

    @staticmethod
    def close_page(page) -> None:
        page.context.close()

    def close(self) -> None:
        self.browser.close()

    # ── output ──────────────────────────────────────────────────────────────

    def shot(self, page, name: str, settle: int = 700) -> None:
        page.wait_for_timeout(settle)
        self.dismiss_hints(page)
        how = media.write_png(self.out / f"{name}.png", page.screenshot(), force=self.force)
        self.results.append((f"{name}.png", how))

    def gif(self, rec: Recorder, name: str, **kw) -> None:
        how = media.encode_gif(rec.frames, self.out / f"{name}.gif", force=self.force, **kw)
        self.results.append((f"{name}.gif", how))

    # ── shared moves ────────────────────────────────────────────────────────

    def chat_id(self, key: str) -> str:
        for c in self.report.get("chats", []):
            if c["key"] == key:
                return c["session_id"]
        raise KeyError(f"no seeded chat {key!r}")

    def task_id(self, key: str) -> str:
        return self.report["tasks"][key]

    def palette(self, page, query: str) -> None:
        page.keyboard.press("Control+k")
        page.wait_for_selector("#search-input", state="visible")
        page.keyboard.type(query, delay=30)
        page.wait_for_timeout(700)

    @staticmethod
    def chat_top(page) -> None:
        page.evaluate("() => { const c = document.getElementById('chat-history'); if (c) c.scrollTop = 0; }")
        page.wait_for_timeout(300)

    # ── the run ─────────────────────────────────────────────────────────────

    def run(self, only=None, gifs: bool = True) -> List[Tuple[str, str]]:
        for sc in SCENES:
            if only and sc.name not in only:
                continue
            if sc.kind == "gif" and not gifs:
                continue
            if sc.needs == "workstation" and not self.workstation:
                self.results.append((sc.name, "skipped (run with --workstation)"))
                continue
            themes = THEMES if sc.kind == "png" else ("dark",)
            for theme in themes:
                started = time.monotonic()
                sc.run(self, theme)
                print(f"[showcase] {sc.name} ({theme}) {time.monotonic() - started:.0f}s", flush=True)
        return self.results


# ── the scenes ──────────────────────────────────────────────────────────────

def _hero(st: Studio, theme: str, size=DESKTOP, name: Optional[str] = None, phone=False):
    page = st.open(theme, size, "/#" + st.chat_id("week"), phone=phone)
    page.wait_for_selector(".msg-ai", timeout=30000)
    if not phone:
        page.locator("#chats-section-title").click()       # show the chats in the sidebar
        page.locator("#mode-agent-btn").click()            # the composer in the mode the turn ran in
    page.mouse.move(5, size[1] - 5)
    st.chat_top(page)
    st.shot(page, name or f"chat-{theme}")
    st.close_page(page)


def scene_chat(st: Studio, theme: str):
    _hero(st, theme)


def scene_workbench(st: Studio, theme: str):
    page = st.open(theme, path="/#" + st.chat_id("week"))
    page.locator("#tool-workbench-btn").click()
    page.wait_for_selector("#workbench-modal .wb-node", timeout=30000)
    page.wait_for_timeout(800)
    _node(page, "Collect weekly metrics").locator(".wb-node-title").click()
    page.get_by_role("button", name="Show me what this would do").first.click()
    page.wait_for_function("() => /Dry run of/.test(document.querySelector('#workbench-modal')?.innerText || '')",
                           timeout=30000)
    _fit(page)
    page.mouse.move(5, 895)
    st.shot(page, f"workbench-{theme}", settle=1200)
    st.close_page(page)


def _fit(page) -> None:
    """*Fit*, once the window has finished opening: the canvas fits itself
    while the window is still growing, so its zoom differs a fraction from
    one opening to the next (measured: 2.4% of the screen's pixels moved
    between two runs), and a picture taken without it churns every run."""
    page.wait_for_timeout(600)
    page.locator("#workbench-modal").get_by_role("button", name="Fit", exact=True).click()
    page.wait_for_timeout(500)


def _node(page, title: str):
    return page.locator("#workbench-modal .wb-node",
                        has=page.locator(".wb-node-title", has_text=title)).first


def scene_tasks(st: Studio, theme: str):
    page = st.open(theme, path="/#" + st.chat_id("week"))
    page.locator("#tool-tasks-btn").click()
    page.wait_for_selector("#tasks-modal .task-card", timeout=30000)
    page.mouse.move(5, 895)
    st.shot(page, f"tasks-{theme}", settle=1200)
    st.close_page(page)


def scene_documents(st: Studio, theme: str):
    page = st.open(theme, path="/#" + st.chat_id("week"))
    page.locator("#tool-library-btn").click()
    page.wait_for_selector("#doclib-grid .doclib-card", timeout=30000)
    page.mouse.move(5, 895)
    st.shot(page, f"documents-{theme}", settle=1200)
    st.close_page(page)


def scene_skills(st: Studio, theme: str):
    page = st.open(theme, path="/#" + st.chat_id("week"))
    st.palette(page, "skills")
    page.locator("#search-results").get_by_text("Skills", exact=True).first.click()
    page.wait_for_selector("#skills-modal:not(.hidden)", timeout=30000)
    page.mouse.move(5, 895)
    st.shot(page, f"skills-{theme}", settle=1200)
    st.close_page(page)


def scene_settings(st: Studio, theme: str):
    page = st.open(theme, path="/#" + st.chat_id("week"))
    st.palette(page, "workstation")
    page.locator("#search-results").get_by_text("Administration").first.click()
    page.wait_for_selector("[data-settings-panel='workstation']:not(.hidden)", timeout=30000)
    page.mouse.move(5, 895)
    st.shot(page, f"settings-{theme}", settle=1500)
    st.close_page(page)


def scene_palette(st: Studio, theme: str):
    page = st.open(theme, path="/#" + st.chat_id("week"))
    st.palette(page, "work")
    st.shot(page, f"palette-{theme}", settle=600)
    st.close_page(page)


def scene_themes(st: Studio, theme: str):
    page = st.open(theme, path="/#" + st.chat_id("week"))
    page.locator("#tool-theme-btn").click()
    page.wait_for_selector("#theme-modal .theme-swatch", timeout=30000)
    page.mouse.move(5, 895)
    st.shot(page, f"themes-{theme}", settle=900)
    st.close_page(page)


def scene_brain(st: Studio, theme: str):
    import seed

    page = st.open(theme, path="/#" + st.chat_id("week"))
    page.locator("#tool-memory-btn").click()
    # The window asks for its list when it opens and says "Loading memories..."
    # until it arrives (`B1070`; it used to say "No memories yet" for 7.4 s on
    # the seeded demo). Measured since: the list is drawn ~300 ms after the
    # click. The wait is for the first memory's words, whatever that takes.
    first = seed.MEMORIES[0][0][:24]
    page.wait_for_function("(t) => document.body.innerText.includes(t)", arg=first, timeout=60000)
    # Oldest first: the order they were told, which reads as a story.
    page.locator("#memory-sort-btn").click()
    page.get_by_role("option", name="Oldest").click()
    page.mouse.move(5, 895)
    st.shot(page, f"brain-{theme}", settle=900)
    st.close_page(page)


def scene_workstation(st: Studio, theme: str):
    """The chat where the agent worked in the workstation, and its screen beside it."""
    page = st.open(theme, path="/#" + st.chat_id("workstation"))
    page.wait_for_selector(".msg-ai", timeout=30000)
    page.keyboard.press("Control+b")                       # the sidebar folds to its rail
    page.wait_for_timeout(600)
    st.palette(page, "workstation screen")
    page.locator("#search-results").get_by_text("Workstation screen").first.click()
    page.wait_for_function(
        "() => [...document.querySelectorAll('#workstation-screen-modal img')]"
        ".some(i => i.src.startsWith('data:image/') && i.naturalWidth >= 1000)", timeout=90000)
    # Dock it to the right edge by its title bar, then widen it by the dock's
    # own edge — the two drags a person makes.
    head = page.locator("#workstation-screen-modal .modal-header").first.bounding_box()
    _drag(page, (head["x"] + 200, head["y"] + head["height"] / 2), (DESKTOP[0] - 1, DESKTOP[1] / 2))
    page.wait_for_timeout(1000)
    edge = page.locator(".edge-dock-resize-handle-right").first.bounding_box()
    if edge and edge["width"]:
        x = edge["x"] + edge["width"] / 2
        _drag(page, (x, DESKTOP[1] / 2), (600, DESKTOP[1] / 2))
    page.mouse.move(5, 895)
    st.shot(page, f"workstation-{theme}", settle=2500)
    st.close_page(page)


def _drag(page, start, end, steps: int = 16) -> None:
    page.mouse.move(*start)
    page.mouse.down()
    for i in range(1, steps + 1):
        page.mouse.move(start[0] + (end[0] - start[0]) * i / steps,
                        start[1] + (end[1] - start[1]) * i / steps)
        page.wait_for_timeout(25)
    page.mouse.up()


def scene_phone_chat(st: Studio, theme: str):
    _hero(st, theme, PHONE, "phone-chat", phone=True)


def _phone_tool(page, button: str) -> None:
    """At phone width the sidebar is behind the menu button: tap it, then the tool."""
    page.locator("#hamburger-btn").tap()
    page.wait_for_timeout(500)
    page.locator(button).scroll_into_view_if_needed()
    page.locator(button).tap()


def scene_phone_documents(st: Studio, theme: str):
    page = st.open(theme, PHONE, "/#" + st.chat_id("week"), phone=True)
    _phone_tool(page, "#tool-library-btn")
    page.wait_for_selector("#doclib-grid .doclib-card", timeout=30000)
    st.shot(page, "phone-documents", settle=1200)
    st.close_page(page)


def scene_phone_tasks(st: Studio, theme: str):
    page = st.open(theme, PHONE, "/#" + st.chat_id("week"), phone=True)
    _phone_tool(page, "#tool-tasks-btn")
    page.wait_for_selector("#tasks-modal .task-card", timeout=30000)
    st.shot(page, "phone-tasks", settle=1500)
    st.close_page(page)


# ── GIFs ────────────────────────────────────────────────────────────────────

def gif_workflow(st: Studio, theme: str):
    """Wire *if it fails* by dragging, then ask what the chain would do."""
    head, alert = st.task_id("metrics"), st.task_id("alert")
    st.client.put(f"/api/tasks/{head}", json={"else_task_id": ""}).raise_for_status()
    try:
        page = st.open(theme, path="/#" + st.chat_id("week"))
        page.locator("#tool-workbench-btn").click()
        page.wait_for_selector("#workbench-modal .wb-node", timeout=30000)
        _fit(page)
        rec = Recorder(page)
        rec.hold(0.8)
        src = _node(page, "Collect weekly metrics").locator(".wb-port[data-when='error']")
        rec.drag(src, _node(page, "Tell me the metrics run failed"), seconds=1.5, settle=1.6)
        rec.click(_node(page, "Collect weekly metrics").locator(".wb-node-title"), settle=1.0)
        rec.click(page.get_by_role("button", name="Show me what this would do").first, settle=0.4)
        page.wait_for_function("() => /Dry run of/.test(document.querySelector('#workbench-modal')?.innerText || '')",
                               timeout=30000)
        rec.move(DESKTOP[0] - 80, DESKTOP[1] - 60, 0.8)
        rec.hold(3.0)
        st.gif(rec, "workflow")
        st.close_page(page)
    finally:
        # Whatever happened, the seeded chain is put back as it was.
        st.client.put(f"/api/tasks/{head}", json={"else_task_id": alert})


def gif_filing(st: Studio, theme: str):
    """Drag two loose documents into folders."""
    page = st.open(theme, path="/#" + st.chat_id("week"))
    page.locator("#tool-library-btn").click()
    page.wait_for_selector("#doclib-grid .doclib-card", timeout=30000)
    page.wait_for_timeout(1000)
    rec = Recorder(page)
    rec.hold(0.8)
    for title, folder in (("invoice-0143.csv", "Finance"), ("packing-list.txt", "Personal")):
        card = page.locator("#doclib-grid .doclib-card", has=page.locator(".memory-item-title", has_text=title)).first
        chip = page.locator(f"#doclib-modal .doclib-folder-chip[data-folder-target='{folder}']").first
        rec.drag(card, chip, seconds=1.3, settle=1.4, src_at=(0.3, 0.35))
    rec.move(DESKTOP[0] - 80, DESKTOP[1] - 60, 0.6)
    rec.hold(1.5)
    st.gif(rec, "filing")
    st.close_page(page)
    # Put them back where the seed left them, for the next scene.
    docs = st.report["documents"]
    st.client.post("/api/document-folders/file",
                   json={"document_ids": [docs["invoice-0143.csv"], docs["packing-list.txt"]], "to": None})


def gif_palette(st: Studio, theme: str):
    """Ctrl+K: one box for every window, setting, command and chat."""
    page = st.open(theme, path="/#" + st.chat_id("week"))
    rec = Recorder(page)
    rec.hold(0.8)
    rec.key("Control+k", settle=0.4)
    rec.type("work", per_char=0.09)
    rec.hold(1.4)
    for _ in "work":
        rec.key("Backspace", settle=0.05)
    rec.type("skills", per_char=0.09)
    rec.hold(0.8)
    rec.key("Enter", settle=0.2)
    page.wait_for_selector("#skills-modal:not(.hidden)", timeout=30000)
    rec.hold(2.0)
    st.gif(rec, "palette")
    st.close_page(page)


def gif_describe(st: Studio, theme: str):
    """`P22-19`, the Workbench's headline flow: the first example sentence under
    *Describe it* → *Draft it* → the draft arrives switched off, every step
    marked "Drafted — check me", and where it sends things → *Check them now*
    → *All look right* → *Switch on*.

    The demo world has no chat server, so this scene registers one
    (`demo_chat.py`) through the admin route for its own length and removes it
    after, with the workflow it drafted — the scenes before it never see
    either. Last in `SCENES` for that reason."""
    import shutil
    import tempfile

    if not st.python:
        raise RuntimeError("gif_describe starts a demo MCP server: Studio needs `python`")
    posts = Path(tempfile.mkdtemp(prefix="pantheon-showcase-chat-")) / "posts.jsonl"
    made = st.client.post("/api/mcp/servers", data={
        "name": "Chat", "transport": "stdio", "command": st.python,
        "args": json.dumps([str(Path(__file__).resolve().parent / "demo_chat.py"), str(posts)])})
    made.raise_for_status()
    server_id = made.json()["id"]
    try:
        page = st.open(theme, path="/#" + st.chat_id("week"))
        page.locator("#tool-workbench-btn").click()
        page.wait_for_selector("#workbench-modal .wf-shelf-new", timeout=30000)
        page.wait_for_timeout(800)
        rec = Recorder(page)
        rec.hold(0.6)
        rec.click(page.locator("#workbench-modal .wf-shelf-new").first, settle=0.9)
        rec.click(page.locator("#workbench-modal .wf-new-example").first, settle=0.8)
        rec.click(page.locator("#workbench-modal .wf-new-draft").first, settle=0.2)
        page.wait_for_selector("#workbench-modal .wf-arrived", timeout=60000)
        rec.hold(0.4)
        _fit(page)
        rec.hold(3.0)
        rec.click(page.locator("#workbench-modal .wf-arrived button", has_text="Check them now").first, settle=0.2)
        page.wait_for_selector("#workbench-modal .wf-check .wf-check-plan li:not(.wf-check-wait)", timeout=30000)
        rec.hold(2.4)
        rec.click(page.locator("#workbench-modal .wf-check-all").first, settle=0.2)
        page.wait_for_selector("#workbench-modal .wf-check-switch", timeout=30000)
        rec.hold(1.2)
        rec.click(page.locator("#workbench-modal .wf-check-switch").first, settle=0.2)
        page.wait_for_function("() => (document.querySelector('#workbench-modal .wf-switch') || {}).textContent"
                               " === 'On'", timeout=30000)
        rec.move(DESKTOP[0] - 80, DESKTOP[1] - 60, 0.6)
        rec.hold(2.6)
        st.gif(rec, "describe")
        st.close_page(page)
    finally:
        for wf in (st.client.get("/api/workflows").json() or {}).get("workflows", []):
            if wf.get("name") == "Bank mail to chat":
                st.client.delete(f"/api/workflows/{wf['id']}")
        st.client.delete(f"/api/mcp/servers/{server_id}")
        shutil.rmtree(posts.parent, ignore_errors=True)


def gif_themes(st: Studio, theme: str):
    """Sixteen palettes; a few of them, one click each."""
    page = st.open(theme, path="/#" + st.chat_id("week"))
    page.locator("#tool-theme-btn").click()
    page.wait_for_selector("#theme-modal .theme-swatch", timeout=30000)
    page.wait_for_timeout(600)
    rec = Recorder(page)
    rec.hold(0.6)
    for name in ("light", "paper", "copper", "cyberpunk", "lavender", "claude", "dark"):
        rec.click(page.locator(f"#theme-modal .theme-swatch[data-theme='{name}']").first,
                  seconds=0.45, settle=0.9)
    rec.hold(0.6)
    st.gif(rec, "themes", colors=224)
    st.close_page(page)


def gif_agent(st: Studio, theme: str):
    """A turn, live: the question, the trace as it runs, the approval, the answer."""
    import re
    from demo_model import CONVERSATIONS

    turn = next(c for c in CONVERSATIONS if c["key"] == "survey")["turns"][0]
    # The reply's last words, as the page will show them (markdown removed).
    tail = " ".join(re.sub(r"[*_`|#]", "", turn["steps"][-1]["say"]).split()[-4:])
    page = st.open(theme, path="/")
    page.locator("#mode-agent-btn").click()
    st.model.set_pace(0.03)
    try:
        rec = Recorder(page)
        rec.hold(0.6)
        rec.click(page.locator("#message").first, seconds=0.5, settle=0.2)  # .first: `ui.autoResize` clones it, id and all
        rec.type(turn["user"], per_char=0.015)
        rec.key("Enter", settle=0.3)
        allow = page.get_by_role("button", name="Allow for this task")
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline and not allow.count():
            rec.snap()
        if allow.count():
            rec.hold(0.8)
            rec.click(allow.first, seconds=0.6, settle=0.2)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline and tail not in page.locator(".msg-ai").last.inner_text():
            rec.snap()
        # Clicking the card stops the chat following the stream, as it does for
        # anyone; scroll down to the answer the way they would.
        rec.move(DESKTOP[0] * 0.55, DESKTOP[1] * 0.55, 0.4)
        rec.wheel(2400, steps=10)
        rec.move(DESKTOP[0] - 80, DESKTOP[1] - 60, 0.5)
        rec.hold(2.5)
        st.gif(rec, "agent")
    finally:
        st.model.set_pace(0.0)
    st.close_page(page)


SCENES: List[Scene] = [
    Scene("chat", "png", "the agent's trace and its answer, in the launch-week chat", scene_chat),
    Scene("workstation", "png", "the Workstation window: the agent's Ubuntu desktop, Firefox open on the page it wrote",
          scene_workstation, needs="workstation"),
    Scene("workbench", "png", "the Workbench canvas after Show me what this would do", scene_workbench),
    Scene("tasks", "png", "the Tasks window", scene_tasks),
    Scene("documents", "png", "the Library's documents, in folders", scene_documents),
    Scene("skills", "png", "the Skills window: yours, an imported package, a group", scene_skills),
    Scene("settings", "png", "Settings → Workstation", scene_settings),
    Scene("palette", "png", "the command palette (Ctrl+K)", scene_palette),
    Scene("themes", "png", "the twenty-three palettes", scene_themes),
    Scene("brain", "png", "the Brain's memories", scene_brain),
    Scene("phone-chat", "phone", "the chat at phone width", scene_phone_chat),
    Scene("phone-documents", "phone", "the Library at phone width", scene_phone_documents),
    Scene("phone-tasks", "phone", "the Tasks window at phone width", scene_phone_tasks),
    Scene("workflow", "gif", "wire *if it fails* by dragging, then dry-run the chain", gif_workflow),
    Scene("agent", "gif", "an agent turn live: trace, approval, answer", gif_agent),
    Scene("filing", "gif", "drag documents into folders", gif_filing),
    Scene("palette-gif", "gif", "Ctrl+K: what matches work, then skills, Enter", gif_palette),
    Scene("themes-gif", "gif", "switching palettes", gif_themes),
    # Last: it registers a demo chat server for its own length (see its doc).
    Scene("describe", "gif", "describe it: a drafted workflow, its steps checked, switched on", gif_describe),
]
