# SPDX-License-Identifier: AGPL-3.0-or-later
"""The workstation's desktop is XFCE, themed to the cockpit — `D-2026-10-31-02`.

The admin, 2026-10-31: *"Is there a way to have a - wee bit better looking VM
in use? it does kinda clash with the over all "modernize" aesthetic -- I accept
the hardware use off-sets"*, then chose "XFCE, themed to the cockpit" over a
lighter desktop. What that is, and what is held here:

* **the look is made, not hand-drawn**: `scripts/make-workstation-theme.py`
  draws the window frames, the wallpaper and the menu's mark from the default
  theme's five tokens, and what is committed is exactly what it writes — so a
  change of palette is one run, and a hand edit of a generated file is caught;
* **the frames are a theme xfwm4 can load**: every part it reads, at the sizes
  that make a 30 px title bar, opaque where it must be and shaped only at the
  corners;
* **the settings are the skeleton's files**: XML that parses, a channel per
  file, and every file and name they point at put in place by `provision.sh`
  — the theme, the wallpaper, the mark, the launchers;
* **the display starts XFCE where the machine has it and JWM where it has
  not**, waits for the panel before the first click, and gives a home made
  before the change the desktop's settings once, as the account, never over a
  file it already has and never through a link.

How it looks was checked on a live desktop built from these same files
(2026-10-31: Xvfb, the real `XDisplay.start` as an unprivileged account, on a
home made before the change): the session ready in 0.9 s, the settings added,
the panel's buttons where the skills say, and the damage watch (`B974`) still
telling a still screen from a changed one with the compositor on.
"""
from __future__ import annotations

import contextlib
import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from workstation import protocol as P
from workstation import ubuntu
from workstation import vm

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "workstation"
SKEL = PKG / "skel"
CHANNELS = SKEL / ".config" / "xfce4" / "xfconf" / "xfce-perchannel-xml"
THEME = PKG / "desktop" / "themes" / "Pantheon" / "xfwm4"
SHARE = "/usr/share/pantheon-workstation"
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


def _generator():
    spec = importlib.util.spec_from_file_location(
        "make_workstation_theme", ROOT / "scripts" / "make-workstation-theme.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = _generator()


def _xpm(path: Path):
    """(width, height, {symbol: colour}, rows) of an XPM, read strictly."""
    strings = re.findall(r'"([^"]*)"', path.read_text())
    w, h, n, cpp = (int(v) for v in strings[0].split())
    colours = {}
    for line in strings[1:1 + n]:
        sym, rest = line[:cpp], line[cpp:].split()
        assert rest[0] == "c", line
        colours[sym] = rest[1]
    rows = strings[1 + n:]
    assert len(rows) == h, path.name
    for row in rows:
        assert len(row) == w * cpp, path.name
    return w, h, colours, [[row[i:i + cpp] for i in range(0, len(row), cpp)] for row in rows]


def _channel(name: str) -> ET.Element:
    root = ET.parse(CHANNELS / f"{name}.xml").getroot()
    assert root.tag == "channel" and root.get("name") == name
    return root


def _prop(root: ET.Element, path: str) -> ET.Element:
    node = root
    for part in path.split("/"):
        node = next(p for p in node.findall("property") if p.get("name") == part)
    return node


# ── made, not hand-drawn ─────────────────────────────────────────────────────

def test_the_committed_look_is_exactly_what_the_generator_draws():
    done = subprocess.run(["python3", str(ROOT / "scripts" / "make-workstation-theme.py"),
                           "--check"], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_generator_draws_from_the_cockpits_default_theme():
    theme_js = (ROOT / "static" / "js" / "theme.js").read_text()
    line = next(ln for ln in theme_js.splitlines() if re.match(r"\s*dark:\s*\{", ln))
    tokens = dict(re.findall(r"(\w+):'(#[0-9a-fA-F]{6})'", line))
    assert tokens == GEN.TOKENS, "THEMES.dark moved: run scripts/make-workstation-theme.py"
    p = GEN.palette()
    assert GEN.rgb_hex(p["close"]) == tokens["red"]
    assert GEN.rgb_hex(p["text"]) == tokens["fg"]
    # the oklab mix is the cockpit's: halfway from black to white is mid grey in oklab
    assert GEN.rgb_hex(GEN.mix(GEN.BLACK, GEN.WHITE, 0.5)) == "#636363"


def test_the_wallpaper_is_the_screen_size_and_has_no_grain():
    svg = ET.parse(PKG / "desktop" / "pantheon-desktop.svg").getroot()
    assert (svg.get("width"), svg.get("height")) == (str(P.SCREEN_WIDTH), str(P.SCREEN_HEIGHT))
    text = (PKG / "desktop" / "pantheon-desktop.svg").read_text()
    assert "feTurbulence" not in text, "grain is what a streamed screen cannot compress"
    assert text.count("<radialGradient") == 5  # four lights and the vignette
    mark = ET.parse(PKG / "desktop" / "pantheon-mark.svg").getroot()
    brand = ET.parse(ROOT / "docs" / "brand" / "pantheon-mark.svg").getroot()
    ns = "{http://www.w3.org/2000/svg}"
    assert mark.find(f"{ns}path").get("d") == brand.find(f"{ns}path").get("d")


# ── a theme xfwm4 can load ───────────────────────────────────────────────────

PARTS = [f"{part}-{state}" for state in ("active", "inactive") for part in (
    "top-left", "top-right", "left", "right", "bottom", "bottom-left", "bottom-right",
    "title-1", "title-2", "title-3", "title-4", "title-5")]
BUTTONS = [f"{b}-{s}" for b in ("close", "hide", "maximize", "maximize-toggled", "menu", "shade",
                                "shade-toggled", "stick", "stick-toggled")
           for s in ("active", "inactive", "prelight", "pressed")]


def test_every_part_xfwm4_reads_is_there_and_nothing_else():
    names = {p.name for p in THEME.iterdir()}
    assert names == {"themerc"} | {f"{n}.xpm" for n in PARTS + BUTTONS}


def test_the_title_bar_is_30_pixels_and_only_the_corners_are_shaped():
    for name in PARTS + BUTTONS:
        w, h, colours, rows = _xpm(THEME / f"{name}.xpm")
        transparent = {s for s, c in colours.items() if c == "None"}
        used_transparent = any(px in transparent for row in rows for px in row)
        if name.startswith(("title-", "top-")) or name in BUTTONS:
            assert h == GEN.TITLE_H, name
        if name.startswith("top-"):
            assert w == GEN.RADIUS and used_transparent, name
            # rounded on the outside: the outer top pixel is cut, the inner one is not
            outer = rows[0][0 if "left" in name else -1]
            inner = rows[-1][-1 if "left" in name else 0]
            assert outer in transparent and inner not in transparent, name
        else:
            assert not used_transparent, f"{name} would punch a hole in the frame"
        if name in BUTTONS:
            assert w == GEN.BUTTON_W, name


def test_a_button_lights_on_hover_and_close_lights_in_the_accent():
    def colours(name):
        return set(_xpm(THEME / f"{name}.xpm")[2].values())
    accent = GEN.TOKENS["red"]
    assert accent in colours("close-prelight")
    assert accent not in colours("close-active") | colours("maximize-prelight")
    assert colours("maximize-prelight") != colours("maximize-active")
    rc = dict(line.split("=", 1) for line in (THEME / "themerc").read_text().splitlines()
              if "=" in line and not line.startswith("#"))
    assert rc["show_app_icon"] == "false" and rc["full_width_title"] == "true"
    assert re.fullmatch(r"#[0-9a-f]{6}", rc["active_text_color"])


# ── the settings are the skeleton's files ────────────────────────────────────

def test_every_setting_parses_and_names_its_own_channel():
    files = sorted(CHANNELS.glob("*.xml"))
    assert {f.stem for f in files} == {"xsettings", "xfwm4", "xfce4-panel", "xfce4-desktop",
                                       "xfce4-session", "xfce4-terminal"}
    for f in files:
        _channel(f.stem)
    ET.parse(SKEL / ".config" / "fontconfig" / "fonts.conf")


def test_the_window_manager_uses_pantheons_frames_with_its_compositor_and_no_vsync():
    wm = _channel("xfwm4")
    assert _prop(wm, "general/theme").get("value") == THEME.parent.name == "Pantheon"
    assert _prop(wm, "general/button_layout").get("value") == "|HMC"
    assert _prop(wm, "general/use_compositing").get("value") == "true"
    assert _prop(wm, "general/vblank_mode").get("value") == "off"
    assert _prop(wm, "general/workspace_count").get("value") == "1"


def test_gtk_is_dark_adwaita_with_papirus_inter_and_jetbrains_mono():
    xs = _channel("xsettings")
    assert _prop(xs, "Net/ThemeName").get("value") == "Adwaita"
    assert _prop(xs, "Net/IconThemeName").get("value") == "Papirus-Dark"
    assert _prop(xs, "Gtk/FontName").get("value").startswith("Inter ")
    assert _prop(xs, "Gtk/MonospaceFontName").get("value").startswith("JetBrains Mono ")
    assert _prop(xs, "Net/CursorBlink").get("value") == "false"
    # Ubuntu has no "Adwaita-dark" theme folder; the dark variant is asked for here.
    assert "gtk-application-prefer-dark-theme=1" in \
        (SKEL / ".config" / "gtk-3.0" / "settings.ini").read_text()


def test_the_panel_is_complete_so_it_never_asks_and_its_launchers_exist():
    panel = _channel("xfce4-panel")
    ids = [int(v.get("value")) for v in _prop(panel, "panels/panel-1/plugin-ids").findall("value")]
    plugins = {int(p.get("name").split("-")[1]): p
               for p in _prop(panel, "plugins").findall("property")}
    assert set(ids) <= set(plugins), "a plugin id with no plugin"
    kinds = [plugins[i].get("value") for i in ids]
    assert kinds[:4] == ["whiskermenu", "launcher", "launcher", "launcher"]
    assert {"tasklist", "clock"} <= set(kinds)
    for i in ids:
        if plugins[i].get("value") != "launcher":
            continue
        for item in _prop(plugins[i], "items").findall("value"):
            entry = SKEL / ".config" / "xfce4" / "panel" / f"launcher-{i}" / item.get("value")
            assert entry.is_file(), entry
            assert re.search(r"^Exec=\S+", entry.read_text(), re.M)
    assert _prop(panel, "panels/panel-1/size").get("value") == "40"
    menu = plugins[ids[0]]
    assert _prop(menu, "button-icon").get("value") == f"{SHARE}/pantheon-mark.svg"
    # nothing in the menu ends the session or locks the screen
    for command in ("logout", "logoutuser", "shutdown", "restart", "lockscreen", "switchuser"):
        assert _prop(menu, f"show-command-{command}").get("value") == "false", command


def test_the_wallpaper_is_named_for_both_screens_a_display_can_be():
    desk = _channel("xfce4-desktop")
    screen = _prop(desk, "backdrop/screen0")
    names = {p.get("name") for p in screen.findall("property")}
    assert {"monitorVNC-0", "monitorscreen"} <= names  # KasmVNC's and Xvfb's
    for monitor in screen.findall("property"):
        assert _prop(monitor, "workspace0/last-image").get("value") == \
            f"{SHARE}/pantheon-desktop.svg"
    assert _prop(desk, "desktop-icons/style").get("value") == "0"


def test_the_session_saves_nothing_asks_nothing_and_starts_no_agents_or_locks():
    session = _channel("xfce4-session")
    for path, value in (("general/SaveOnExit", "false"), ("general/PromptOnLogout", "false"),
                        ("startup/ssh-agent/enabled", "false"),
                        ("startup/gpg-agent/enabled", "false"),
                        ("shutdown/LockScreen", "false")):
        assert _prop(session, path).get("value") == value, path
    assert "Hidden=true" in (SKEL / ".config" / "autostart" / "xscreensaver.desktop").read_text()


def test_the_desktop_starts_with_nothing_open():
    """`B1721`. The owner, 2026-10-31: *"Currently the VM constantly opens and
    reopens firefox and the terminal... Let it be idle."* Every desktop
    session opened a terminal, so every restart of the display was a terminal
    opening again. Nothing starts with the session now, in XFCE or in JWM."""
    autostart = SKEL / ".config" / "autostart"
    for entry in autostart.iterdir():
        assert "Hidden=true" in entry.read_text(), f"{entry.name} starts with the desktop"
    assert "StartupCommand" not in (SKEL / ".jwmrc").read_text()


def test_the_terminal_pastes_without_asking_and_has_no_chrome():
    term = _channel("xfce4-terminal")
    values = {p.get("name"): p.get("value") for p in term.findall("property")}
    assert values["misc-show-unsafe-paste-dialog"] == "false"
    assert values["misc-menubar-default"] == "false"
    assert values["scrolling-bar"] == "TERMINAL_SCROLLBAR_NONE"
    assert values["misc-cursor-blinks"] == "false"
    assert len(values["color-palette"].split(";")) == 16


# ── provision.sh puts it all in place ────────────────────────────────────────

def test_provisioning_installs_xfce_and_keeps_jwm_as_the_fallback():
    text = (PKG / "provision.sh").read_text()
    packages = re.search(r'^PACKAGES="(.*?)"', text, re.S | re.M).group(1).replace("\\\n", " ")
    for pkg in ("xfwm4", "xfce4-panel", "xfdesktop4", "xfce4-session", "xfconf",
                "xfce4-terminal", "thunar", "xfce4-whiskermenu-plugin", "papirus-icon-theme",
                "fonts-inter", "fonts-jetbrains-mono", "librsvg2-common", "jwm", "xterm"):
        assert pkg in packages.split(), pkg


@pytest.mark.skipif(not shutil.which("sh") or not Path("/etc/skel").is_dir(),
                    reason="needs a POSIX sh and an /etc/skel")
def test_the_files_step_puts_the_theme_the_wallpaper_and_the_settings_in_place(tmp_path):
    out = tmp_path
    done = subprocess.run(
        ["sh", str(PKG / "provision.sh"), "files", "--skel", str(out / "skel"),
         "--policies", str(out / "policies"), "--themes", str(out / "themes"),
         "--share", str(out / "share")], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert sorted(p.name for p in (out / "themes" / "Pantheon" / "xfwm4").iterdir()) == \
        sorted(p.name for p in THEME.iterdir())
    assert sorted(p.name for p in (out / "share").iterdir()) == \
        ["pantheon-desktop.svg", "pantheon-mark.svg"]
    assert (out / "skel" / ".config" / "xfce4" / "xfconf" / "xfce-perchannel-xml" /
            "xfwm4.xml").read_bytes() == (CHANNELS / "xfwm4.xml").read_bytes()
    # a part the theme no longer has does not linger after the next run
    (out / "themes" / "Pantheon" / "xfwm4" / "gone.xpm").write_text("x")
    subprocess.run(["sh", str(PKG / "provision.sh"), "files", "--skel", str(out / "skel"),
                    "--policies", str(out / "policies"), "--themes", str(out / "themes"),
                    "--share", str(out / "share")], check=True, capture_output=True, timeout=60)
    assert not (out / "themes" / "Pantheon" / "xfwm4" / "gone.xpm").exists()


def test_the_vm_image_carries_the_desktop_and_a_change_to_it_makes_a_new_image(tmp_path):
    rels = vm.payload_files(PKG)
    assert "desktop/themes/Pantheon/xfwm4/themerc" in rels
    assert "desktop/pantheon-desktop.svg" in rels
    assert "skel/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml" in rels
    payload = tmp_path / "payload"
    shutil.copytree(PKG, payload, ignore=shutil.ignore_patterns("__pycache__"))
    before = vm.payload_digest(payload, "base")
    with open(payload / "desktop" / "pantheon-desktop.svg", "a") as f:
        f.write("\n")
    assert vm.payload_digest(payload, "base") != before
    for dockerfile in ("Dockerfile", "vm.Dockerfile"):
        assert re.search(r"^COPY desktop/ ", (PKG / dockerfile).read_text(), re.M), dockerfile


# ── the display starts XFCE, or JWM ──────────────────────────────────────────

def test_the_desktop_is_xfce_where_the_machine_has_it_and_jwm_where_it_has_not():
    argv, env = ubuntu.desktop_session(lambda name: "/usr/bin/" + name)
    assert argv == ["xfce4-session"]
    assert env == {"XDG_CURRENT_DESKTOP": "XFCE", "XDG_SESSION_DESKTOP": "xfce",
                   "DESKTOP_SESSION": "xfce", "XDG_MENU_PREFIX": "xfce-", **ubuntu.A11Y_ENV}
    assert ubuntu.desktop_session(lambda name: None) == (["jwm"], dict(ubuntu.A11Y_ENV))


class _Proc:
    returncode = None

    def poll(self):
        return None


class _System:
    def __init__(self, home: Path):
        self._home = home
        self.added = []
        self.retired = []

    def home(self, account):
        return self._home

    def uid(self, account):
        return os.getuid()

    def run_as(self, account, *, with_display=True):
        return ["setpriv"], {"HOME": str(self._home), **({"DISPLAY": ":8"} if with_display else {})}

    def add_desktop_settings(self, account):
        self.added.append(account)
        return 0

    def retire_shipped_files(self, account):
        self.retired.append(account)
        return 0


@pytest.mark.parametrize("xfce", [True, False])
def test_a_display_starts_the_desktop_the_machine_has(tmp_path, monkeypatch, xfce):
    system = _System(tmp_path)
    display = ubuntu.XDisplay(system, "pw-ann-12345678")
    real_which = shutil.which
    monkeypatch.setattr(ubuntu.shutil, "which", lambda name, *a, **k: (
        ("/usr/bin/xfce4-session" if xfce else None) if name == ubuntu.XFCE_SESSION
        else "/usr/bin/" + name if name == "dbus-run-session" else real_which(name, *a, **k)))
    monkeypatch.setattr(ubuntu, "fs_identity", lambda uid, gid: contextlib.nullcontext())
    monkeypatch.setattr(display, "_start_server", lambda *a: (_Proc(), 8, None))
    monkeypatch.setattr(display, "_open_watch", lambda: None)
    waits = []
    monkeypatch.setattr(display, "_wait_for_wm",
                        lambda prefix, env, **kw: waits.append(kw) or 0.0)
    started = []
    monkeypatch.setattr(ubuntu.subprocess, "Popen",
                        lambda argv, **kw: started.append((argv, kw["env"])) or _Proc())
    assert display.start() == ":8"
    (argv, env), = started
    assert argv[:3] == ["setpriv", "dbus-run-session", "--"]
    if xfce:
        assert argv[3:] == ["xfce4-session"] and env["XDG_CURRENT_DESKTOP"] == "XFCE"
        assert system.added == ["pw-ann-12345678"] and waits == [{"panel": True}]
        assert system.retired == ["pw-ann-12345678"]
    else:
        assert argv[3:] == ["jwm"] and "XDG_CURRENT_DESKTOP" not in env
        assert system.added == [] and waits == [{"panel": False}]
    assert env["DISPLAY"] == ":8"


def test_the_first_click_waits_for_the_panel_not_only_the_window_manager(tmp_path, monkeypatch):
    display = ubuntu.XDisplay(_System(tmp_path), "pw-ann-12345678")
    asked = []
    panel_up = iter([1, 1, 0])  # the panel maps on the third look

    def run(argv, **kw):
        asked.append(argv[1:])
        code = next(panel_up) if argv[1:3] == ["xdotool", "search"] else 0
        return subprocess.CompletedProcess(argv, code)

    monkeypatch.setattr(ubuntu.subprocess, "run", run)
    monkeypatch.setattr(ubuntu.time, "sleep", lambda s: None)
    display._wait_for_wm(["setpriv"], {}, panel=True)
    assert asked.count(["xdotool", "get_num_desktops"]) == 3
    assert asked.count(["xdotool", "search", "--onlyvisible", "--class", "xfce4-panel"]) == 3
    asked.clear()
    display._wait_for_wm(["setpriv"], {})  # JWM: the desktop count alone
    assert asked == [["xdotool", "get_num_desktops"]]


# ── a home made before the change ────────────────────────────────────────────

def _skeleton(tmp_path) -> Path:
    skel = tmp_path / "skel"
    shutil.copytree(SKEL, skel)
    return skel


def test_missing_settings_are_added_and_nothing_there_is_ever_replaced(tmp_path):
    src = _skeleton(tmp_path) / ".config"
    dest = tmp_path / "home" / ".config"
    (dest / "gtk-3.0").mkdir(parents=True)
    (dest / "gtk-3.0" / "gtk.css").write_text("/* mine */")
    added = ubuntu.copy_missing(src, dest)
    every = [p for p in src.rglob("*") if p.is_file()]
    assert added == len(every) - 1
    assert (dest / "gtk-3.0" / "gtk.css").read_text() == "/* mine */"
    assert (dest / "xfce4" / "xfconf" / "xfce-perchannel-xml" / "xfce4-panel.xml").read_bytes() \
        == (src / "xfce4" / "xfconf" / "xfce-perchannel-xml" / "xfce4-panel.xml").read_bytes()
    assert ubuntu.copy_missing(src, dest) == 0  # a second run adds nothing


def test_nothing_is_written_through_a_link(tmp_path):
    src = _skeleton(tmp_path) / ".config"
    dest = tmp_path / "home" / ".config"
    dest.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (dest / "xfce4").symlink_to(elsewhere)               # a folder that is a link
    target = tmp_path / "victim"
    target.write_text("untouched")
    (dest / "gtk-3.0").mkdir()
    (dest / "gtk-3.0" / "gtk.css").symlink_to(target)    # a file that is a link
    ubuntu.copy_missing(src, dest)
    assert list(elsewhere.iterdir()) == []
    assert target.read_text() == "untouched"
    assert (dest / "gtk-3.0" / "settings.ini").is_file()  # the rest still arrives


@pytest.fixture
def open_dir():
    """A directory another uid can traverse — pytest's own tmp root is 0700."""
    path = Path(tempfile.mkdtemp(prefix="pantheon-desktop-"))
    os.chmod(path, 0o755)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _system(tmp_path, monkeypatch):
    monkeypatch.setattr(ubuntu, "_visudo_ok", lambda p: True)
    if not IS_ROOT:
        monkeypatch.setattr(ubuntu, "fs_identity", lambda uid, gid: contextlib.nullcontext())
    system = ubuntu.UbuntuSystem(tmp_path / "homes", skeleton=_skeleton(tmp_path),
                                 sudoers_path=tmp_path / "sudoers", runtime_root=tmp_path / "run",
                                 prepare=False)
    account = "pw-ann-12345678"
    uid = system.registry.uid_for(account)
    home = system.home(account)
    home.mkdir(parents=True)
    (home / ".jwmrc").write_text("<JWM/>")  # what a home made before the change has
    if IS_ROOT:
        os.chown(home, uid, uid)
    return system, account, home, uid


def test_an_older_home_is_given_the_desktops_settings_once(open_dir, monkeypatch):
    system, account, home, uid = _system(open_dir, monkeypatch)
    added = system.add_desktop_settings(account)
    assert added == len([p for p in (SKEL / ".config").rglob("*") if p.is_file()])
    panel = home / ".config" / "xfce4" / "xfconf" / "xfce-perchannel-xml" / "xfce4-panel.xml"
    assert panel.is_file()
    if IS_ROOT:
        assert panel.stat().st_uid == uid and (home / ".config").stat().st_uid == uid
    # The person then removes a setting on purpose: it stays removed.
    (home / ".config" / "gtk-3.0" / "gtk.css").unlink()
    assert system.add_desktop_settings(account) == 0
    assert not (home / ".config" / "gtk-3.0" / "gtk.css").exists()


def test_a_home_whose_config_is_a_link_is_left_alone(open_dir, monkeypatch):
    system, account, home, _ = _system(open_dir, monkeypatch)
    elsewhere = open_dir / "elsewhere"
    elsewhere.mkdir()
    (home / ".config").symlink_to(elsewhere)
    assert system.add_desktop_settings(account) == 0
    assert list(elsewhere.iterdir()) == []


# ── `B1721`: the terminal a home was given at start is taken back, unless it was changed ──

# What `e22fd4a` put in every home made while it shipped, byte for byte.
SHIPPED_TERMINAL = """# SPDX-License-Identifier: AGPL-3.0-or-later
# One terminal open when the desktop starts, so the first screenshot already
# shows somewhere to type (D-2026-10-31-02). This file is in the account's
# home; "Reset to clean" puts it back.
[Desktop Entry]
Version=1.0
Type=Application
Name=Terminal
Exec=xfce4-terminal
Icon=org.xfce.terminal
OnlyShowIn=XFCE;
X-XFCE-Autostart-Override=true
Terminal=false
"""
TERMINAL_REL = ".config/autostart/pantheon-terminal.desktop"


def test_the_retired_files_digest_is_the_shipped_files():
    import hashlib
    assert ubuntu.RETIRED_HOME_FILES[TERMINAL_REL] == hashlib.sha256(
        SHIPPED_TERMINAL.encode()).hexdigest()


def _with_terminal(home, text, uid):
    path = home / TERMINAL_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if IS_ROOT:
        for p in (home / ".config", path.parent, path):
            os.chown(p, uid, uid)
    return path


def test_a_home_still_holding_the_shipped_terminal_loses_it(open_dir, monkeypatch):
    system, account, home, uid = _system(open_dir, monkeypatch)
    path = _with_terminal(home, SHIPPED_TERMINAL, uid)
    (path.parent / "mine.desktop").write_text("[Desktop Entry]\nExec=true\n")
    assert system.retire_shipped_files(account) == 1
    assert not path.exists()
    assert (path.parent / "mine.desktop").exists(), "only the shipped file goes"
    assert system.retire_shipped_files(account) == 0


def test_a_terminal_entry_the_person_changed_is_theirs(open_dir, monkeypatch):
    system, account, home, uid = _system(open_dir, monkeypatch)
    path = _with_terminal(home, SHIPPED_TERMINAL.replace("Exec=xfce4-terminal",
                                                         "Exec=xfce4-terminal --maximize"), uid)
    assert system.retire_shipped_files(account) == 0
    assert path.exists()


def test_nothing_is_removed_through_a_link(open_dir, monkeypatch):
    system, account, home, uid = _system(open_dir, monkeypatch)
    elsewhere = open_dir / "elsewhere"
    (elsewhere / "autostart").mkdir(parents=True)
    target = elsewhere / "autostart" / "pantheon-terminal.desktop"
    target.write_text(SHIPPED_TERMINAL)
    (home / ".config").symlink_to(elsewhere)
    assert system.retire_shipped_files(account) == 0
    assert target.exists()
    (home / ".config").unlink()
    (home / ".config" / "autostart").mkdir(parents=True)
    (home / TERMINAL_REL).symlink_to(target)
    assert system.retire_shipped_files(account) == 0
    assert target.exists() and (home / TERMINAL_REL).is_symlink()
