#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regenerate every screenshot and GIF in `docs/media/` with one command.

    python3 scripts/showcase/capture.py                    # everything
    python3 scripts/showcase/capture.py --workstation      # … and the workstation desktop
    python3 scripts/showcase/capture.py --only chat,workbench --no-gifs
    python3 scripts/showcase/capture.py --list             # what each scene shows

What it does, in order — and nothing here is a mock of the product:

  1. starts this checkout's `app.py` on a throwaway data directory, on a free
     loopback port, with authentication on;
  2. with `--workstation`, starts a `pantheon-workstation` container on a
     loopback port with this checkout's `workstation/` mounted over the image's
     copy (so the daemon speaks the tree's protocol), pairs it from Settings and
     signs the demo person in to their desktop;
  3. seeds a fictional world through the real API (`seed.py`): documents in
     nested folders, a chain of automations with a failure branch and a dry
     run, a workflow (two steps, one start), skills with an imported package
     and a group, notes, a week of
     calendar, memories — and chats with a real agent trace, played by a
     scripted stand-in model on loopback (`demo_model.py`) while Pantheon runs
     the tools for real;
  4. drives Chromium through each scene (`scenes.py`) in a dark and a light
     palette at 1440×900, three at phone width, and records the GIFs;
  5. writes optimised PNGs and two-pass palette GIFs into `docs/media/`
     (`media.py` holds the size budgets the test enforces), and prints what
     each file came to;
  6. stops everything it started and deletes the data directory.

**Nothing phones home (`Law 16`).** Chromium runs behind a proxy address that
answers nothing, with loopback the only bypass, and every page request to any
other host is refused and recorded; a run that recorded one fails. The seeded
names are fictional and the account password is generated per run.

**Needs:** Python with Playwright (`pip install playwright`; `playwright install
chromium`), Pillow and httpx; `ffmpeg` on PATH; and an interpreter with
Pantheon's requirements for the server — this one if it has them, else pass
`--server-python`. Docker only for `--workstation`. Not run in CI: it drives a
real browser for several minutes. `tests/test_the_showcase_pipeline.py` runs the
seeding against the real API and checks what the README shows.

**Churn.** A regenerated picture that differs from the committed one by less
than `media.CHURN_PIXELS` of its pixels (a clock, a relative time) is left as it
was; `--force` rewrites everything.
"""
from __future__ import annotations

import argparse
import contextlib
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import demo_model  # noqa: E402
import media  # noqa: E402
import seed  # noqa: E402

DEFAULT_OUT = ROOT / "docs" / "media"


def _free_port() -> int:
    with contextlib.closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _say(msg: str) -> None:
    print(f"[showcase] {msg}", flush=True)


def _server_python(explicit: Optional[str]) -> str:
    """An interpreter that can import Pantheon's server stack."""
    candidates = [explicit] if explicit else [
        sys.executable, str(ROOT / ".venv" / "bin" / "python"), str(ROOT / "venv" / "bin" / "python")]
    for exe in candidates:
        if exe and Path(exe).exists() and subprocess.run(
                [exe, "-c", "import fastapi, uvicorn, sqlalchemy"],
                capture_output=True).returncode == 0:
            return exe
    raise SystemExit("No interpreter with Pantheon's requirements found; pass --server-python "
                     "(the one you run app.py with).")


def theme_colours() -> Dict[str, Dict[str, str]]:
    """The built-in palettes, read from `static/js/theme.js` — the one place
    they are defined — so a capture sets exactly what the Theme window would."""
    text = (ROOT / "static" / "js" / "theme.js").read_text(encoding="utf-8")
    block = text[text.index("export const THEMES"):]
    block = block[:block.index("};")]
    out = {}
    for m in re.finditer(r"^\s*(\w+):\s*\{\s*bg:'(#\w+)',\s*fg:'(#\w+)',\s*panel:'(#\w+)',"
                         r"\s*border:'(#\w+)',\s*red:'(#\w+)'", block, re.M):
        name, bg, fg, panel, border, red = m.groups()
        out[name] = {"bg": bg, "fg": fg, "panel": panel, "border": border, "red": red}
    return out


# What the throwaway server may inherit from the shell that runs the capture.
# Everything else is left behind, and every address, key and token the product
# reads is blanked — derived from `.env.example`, the one list of them — because
# `app.py` also loads this checkout's `.env`, and a developer's `.env` names
# their real database, models, keys and workstation. A capture that inherited
# them would write the demo world into the real database and photograph the
# real model list. Measured: under pytest, an inherited `DATABASE_URL` of
# `sqlite:///:memory:` gave the server a database with no tables.
_INHERIT = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "TZ", "TMPDIR", "SHELL",
            "PYTHONPATH", "VIRTUAL_ENV", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
_POINTER = re.compile(r"(_URL|_HOST|_HOSTS|_KEY|_TOKEN|_SECRET|_PASSWORD|_INSTANCE|_ENDPOINT|"
                      r"_PAIRING|_CERT_SHA256|_CX|_CLIENT_ID|_USERNAME|_TENANT)$")


def pointer_keys() -> List[str]:
    """Every setting in `.env.example` that points somewhere or proves who you are."""
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    keys = {m.group(1) for m in re.finditer(r"^#?\s*([A-Z][A-Z0-9_]*)=", text, re.M)}
    return sorted(k for k in keys if _POINTER.search(k))


class Server:
    """This checkout's `app.py` on a throwaway data directory."""

    def __init__(self, python: str, data_dir: Path, port: int, extra_env=None):
        self.python, self.data_dir, self.port = python, data_dir, port
        self.base = f"http://127.0.0.1:{port}"
        self.log_path = data_dir.parent / "server.log"
        self.proc = None
        self.extra_env = dict(extra_env or {})

    def environment(self) -> Dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k in _INHERIT or k.startswith("LC_")}
        env.update({k: "" for k in pointer_keys()})
        env.update({
            "PANTHEON_DATA_DIR": str(self.data_dir),
            "DATABASE_URL": "sqlite:///" + (self.data_dir / "app.db").as_posix(),
            # A port nothing listens on: the in-process vector index, never a real ChromaDB.
            "CHROMADB_HOST": "127.0.0.1", "CHROMADB_PORT": str(_free_port()),
            "AUTH_ENABLED": "true", "LOCALHOST_BYPASS": "false",
            "APP_BIND": "127.0.0.1", "APP_PORT": str(self.port),
        })
        env.update(self.extra_env)
        return env

    def start(self, timeout: float = 180) -> None:
        import httpx

        env = self.environment()
        self._log = open(self.log_path, "wb")
        self.proc = subprocess.Popen([self.python, "app.py"], cwd=ROOT, env=env,
                                     stdout=self._log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"app.py exited ({self.proc.returncode}); see {self.log_path}")
            try:
                if httpx.get(self.base + "/api/auth/status", timeout=2).status_code == 200:
                    return
            except httpx.HTTPError:
                pass  # not listening yet; the deadline below is what reports a failure
            time.sleep(1)
        raise RuntimeError(f"app.py did not answer within {timeout:.0f}s; see {self.log_path}")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait(timeout=10)
        if getattr(self, "_log", None):
            self._log.close()


class Workstation:
    """A `pantheon-workstation` container on a loopback port, for `--workstation`."""

    def __init__(self, image: Optional[str]):
        self.image = image or self._newest_image()
        self.name = "pantheon-showcase-ws-" + secrets.token_hex(4)
        self.port = _free_port()
        self.token = secrets.token_hex(24)
        self.url = f"http://127.0.0.1:{self.port}"
        self.started = False

    @staticmethod
    def _newest_image() -> str:
        out = subprocess.run(["docker", "images", "pantheon-workstation",
                              "--format", "{{.CreatedAt}}\t{{.Repository}}:{{.Tag}}"],
                             capture_output=True, text=True, check=True).stdout.split("\n")
        rows = sorted(r for r in out if r.strip())
        if not rows:
            raise RuntimeError("no pantheon-workstation image; build one with "
                               "`docker compose -f docker-compose.yml -f docker/workstation.yml build workstation`")
        return rows[-1].split("\t")[1]

    def start(self, timeout: float = 120) -> None:
        import httpx

        subprocess.run([
            "docker", "run", "-d", "--rm", "--name", self.name,
            "-p", f"127.0.0.1:{self.port}:7040", "--shm-size", "2g", "--cap-drop", "NET_RAW",
            "-e", f"PANTHEON_WORKSTATION_TOKEN={self.token}",
            # The tree's daemon over the image's copy: the image brings Ubuntu,
            # the desktop and Firefox; the protocol must be this checkout's.
            "-v", f"{ROOT / 'workstation'}:/opt/pantheon-workstation/workstation:ro",
            self.image, "--system", "ubuntu", "--bind", "0.0.0.0", "--port", "7040",
        ], check=True, capture_output=True)
        self.started = True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if httpx.get(self.url + "/v1/health", timeout=2).json().get("agent") == "pantheon-workstation":
                    return
            except (httpx.HTTPError, ValueError):
                pass  # still booting; the deadline below is what reports a failure
            time.sleep(1)
        raise RuntimeError("the workstation container did not answer")

    def pair(self, client) -> None:
        """Settings → Workstation: the address, the token, and On — the admin's
        own three fields — then the first frame, which makes the person's
        account and desktop."""
        seed._ok(client.post("/api/auth/settings", json={
            "workstation_url": self.url, "workstation_token": self.token,
            "workstation_enabled": True}), "workstation settings")
        state = seed._ok(client.post("/api/workstation/check"), "workstation check")
        if state.get("state") != "up":
            raise RuntimeError(f"workstation not up: {state.get('sentence')}")
        seed._ok(client.get("/api/workstation/screen", timeout=120), "first workstation frame")

    def stop(self) -> None:
        if self.started:
            subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)


def main(argv: Optional[List[str]] = None) -> int:
    import scenes

    ap = argparse.ArgumentParser(description="Regenerate docs/media from a seeded Pantheon.")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="where to write (default docs/media)")
    ap.add_argument("--server-python", help="interpreter with Pantheon's requirements")
    ap.add_argument("--only", help="comma-separated scene names (see --list)")
    ap.add_argument("--no-gifs", action="store_true", help="screenshots only")
    ap.add_argument("--workstation", action="store_true",
                    help="also start a workstation container and capture its desktop (needs Docker)")
    ap.add_argument("--workstation-image", help="image to use (default: the newest pantheon-workstation:*)")
    ap.add_argument("--force", action="store_true", help="rewrite files even when unchanged")
    ap.add_argument("--keep-data", action="store_true", help="keep the throwaway data directory")
    ap.add_argument("--list", action="store_true", help="list the scenes and exit")
    args = ap.parse_args(argv)

    if args.list:
        for sc in scenes.SCENES:
            print(f"{sc.name:<14} {sc.kind:<6} {sc.what}")
        return 0
    try:
        import playwright  # noqa: F401
    except ImportError:
        raise SystemExit("Playwright is not installed: pip install playwright && playwright install chromium")
    media._ffmpeg()
    only = set(filter(None, (args.only or "").split(","))) or None
    unknown = (only or set()) - {s.name for s in scenes.SCENES}
    if unknown:
        raise SystemExit(f"unknown scene(s): {', '.join(sorted(unknown))} (see --list)")

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    python = _server_python(args.server_python)
    work = Path(tempfile.mkdtemp(prefix="pantheon-showcase-"))
    data = work / "data"
    data.mkdir()
    server = ws = None
    started = time.monotonic()
    try:
        if args.workstation:
            ws = Workstation(args.workstation_image)
            _say(f"workstation: {ws.image} on {ws.url}")
            ws.start()
        _say("installing the demo skill package (offline)")
        subprocess.run([python, str(HERE / "offline_package.py"), "--data-dir", str(data),
                        "--owner", seed.PERSON["username"]], check=True, cwd=ROOT,
                       stdout=subprocess.DEVNULL)
        server = Server(python, data, _free_port())
        _say(f"starting Pantheon on {server.base} (data in {data})")
        server.start()

        import httpx
        password = secrets.token_urlsafe(18)
        client = httpx.Client(base_url=server.base, timeout=300)
        seed.setup_admin(client, password)
        have = []
        if ws:
            _say("pairing the workstation and making the desktop")
            ws.pair(client)
            have.append("workstation")
        with demo_model.DemoModel() as model:
            _say("seeding the demo world through the API")
            report = seed.seed_all(client, model_base_url=model.base_url, have=have)
            _say("seeded: " + ", ".join(f"{k} {n}" for k, n in seed.counts(report).items()))
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                studio = scenes.Studio(pw, server.base, seed.PERSON["username"], password,
                                       theme_colours(), out, force=args.force, model=model,
                                       client=client, report=report, workstation=bool(ws),
                                       python=python)
                try:
                    results = studio.run(only=only, gifs=not args.no_gifs)
                finally:
                    studio.close()
            if studio.blocked:
                for url in studio.blocked:
                    _say(f"BLOCKED a request off this machine: {url}")
                raise SystemExit("a captured page tried to reach another host (Law 16); "
                                 "nothing was written for it — fix the page, then re-run")
        for name, how in results:
            _say(f"{name:<28} {how}")
        total = sum(size for _, size in media.sizes(out))
        _say(f"docs/media is {total / 1024 / 1024:.2f} MB "
             f"(budget {media.TOTAL_BUDGET / 1024 / 1024:.0f} MB); "
             f"took {(time.monotonic() - started) / 60:.1f} min")
        return 0 if total <= media.TOTAL_BUDGET else 1
    finally:
        if server:
            server.stop()
        if ws:
            ws.stop()
        if args.keep_data:
            _say(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
