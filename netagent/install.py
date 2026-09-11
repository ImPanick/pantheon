#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Install the host agent and wire Pantheon to it. A script, not an agent.

`P17-12`, from the owner: *"the installer would run, install and start the MCP
servers.. It'll then generate the API keys it would need to pass into the
Pantheon ... do-no-harm no AI awareness."*

**THAT LAST PART IS THE DESIGN AND IT IS RIGHT.** The step that mints a
credential and writes it into a config file should be a file a person can read
top to bottom, not something that reasons. So this is deterministic, prints every
action before taking it, and has a `--dry-run` that prints and does nothing.

**IT DOES NOT NEED `docker exec`.** `docker-compose.yml` bind-mounts
`${APP_DATA_DIR:-./data}` to `/app/data`, so `data/settings.json` on this machine
*is* Pantheon's settings file. Writing it directly works whether the container is
up or down, survives a rebuild, and needs no running Pantheon to provision
against. One fewer moving part than the plan, and the plan was right about
everything else.

**ORDER, because it matters:**

  1. `docker compose up` — Pantheon comes up configured to reach nothing
  2. this, on the host — starts the agent, mints a token
  3. this writes the address and token into `data/settings.json`
  4. Pantheon picks it up on its next settings read (a two-second cache)

Run it with no arguments to see what it would do.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from netagent.tokens import load_or_create  # noqa: E402

IS_WINDOWS = platform.system() == "Windows"
DEFAULT_PORT = 7010


def say(message: str = "") -> None:
    print(message, flush=True)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _settings_path(repo: Path, data_dir: str = "") -> Path:
    """Where Pantheon's settings actually live on this machine.

    Honours `APP_DATA_DIR` the way compose does, because an operator who moved
    their data directory has moved it for both of us.
    """
    if data_dir:
        return Path(data_dir).expanduser() / "settings.json"
    env = os.environ.get("APP_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser() / "settings.json"
    return repo / "data" / "settings.json"


def _container_reaches_host(port: int) -> str:
    """The address Pantheon should use, and why.

    From inside a container, `host.docker.internal` is the host — and it does
    **not** arrive on the host's loopback interface. So an agent bound to
    `127.0.0.1` is invisible to Pantheon even though both are on this machine.
    That is the single most common way this setup fails, so the installer picks
    the working answer and says which it picked.
    """
    return f"http://host.docker.internal:{port}"


def _lan_address() -> str:
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.2)
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0])
    except OSError:
        return ""
    finally:
        if sock is not None:
            sock.close()


def _write_settings(path: Path, values: dict, *, dry_run: bool) -> None:
    """Merge into Pantheon's settings. Read-modify-write, never replace.

    `preserve_unreadable` in spirit: a settings file that will not parse is a
    reason to stop, not a reason to write a fresh one over it. Somebody's API
    keys are in there.
    """
    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            say(f"  ! {path} exists and could not be read: {e}")
            say("    Refusing to overwrite it — your credentials are in that file.")
            raise SystemExit(2)
        if not isinstance(existing, dict):
            say(f"  ! {path} is not a settings object. Refusing to overwrite it.")
            raise SystemExit(2)

    merged = {**existing, **values}
    if dry_run:
        say(f"  would write {path}:")
        for key, value in values.items():
            shown = "(set)" if "token" in key else json.dumps(value)
            say(f"      {key} = {shown}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.installer-tmp")
    tmp.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    tmp.replace(path)
    say(f"  wrote {path}")


def _launch_hint(repo: Path, port: int, bind: str, allow: str,
                 allow_exec: bool, elevated: list) -> str:
    parts = [sys.executable or "python", "-m", "netagent.server",
             "--bind", bind, "--port", str(port)]
    if allow:
        parts += ["--allow", allow]
    if allow_exec:
        parts += ["--allow-exec"]
    for cmd in elevated:
        parts += ["--allow-elevated", cmd]
    return " ".join(parts)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="netagent-install",
        description="Install the Pantheon host agent and wire Pantheon to it.")
    ap.add_argument("--dry-run", action="store_true",
                    help="print every action and take none of them")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--bind", default="0.0.0.0",
                    help="0.0.0.0 so the container can reach it. Use 127.0.0.1 "
                         "if Pantheon is NOT in Docker on this machine.")
    ap.add_argument("--allow", default="",
                    help="a network the agent may answer about, e.g. 192.168.1.0/24")
    ap.add_argument("--allow-exec", action="store_true",
                    help="let Pantheon run commands on this machine")
    ap.add_argument("--allow-elevated", action="append", default=[], metavar="CMD")
    ap.add_argument("--data-dir", default="",
                    help="Pantheon's data directory (default: ./data beside the repo)")
    ap.add_argument("--start", action="store_true",
                    help="also start the agent now, in the background")
    args = ap.parse_args(argv)

    repo = _repo_root()
    settings = _settings_path(repo, args.data_dir)
    state = Path.home() / ".pantheon-netagent"
    url = _container_reaches_host(args.port)

    say("Pantheon host agent — installer")
    say("=" * 62)
    say(f"  repo          {repo}")
    say(f"  settings      {settings}")
    say(f"  agent state   {state}")
    say(f"  listening on  {args.bind}:{args.port}")
    say(f"  Pantheon uses {url}")
    if args.bind == "0.0.0.0":
        lan = _lan_address()
        say("")
        say("  NOTE: 0.0.0.0 puts the agent on your LAN. It is authenticated and")
        say("  refuses an unknown token, but it is a listener and you should know")
        say(f"  it is open{f' on {lan}' if lan else ''}. Use --bind 127.0.0.1 if")
        say("  Pantheon is not running in Docker on this machine.")
    say("")
    if args.allow_exec:
        say("  HOST EXECUTION IS BEING TURNED ON.")
        say("  Pantheon will be able to run commands on this machine as you.")
        say("  The agent refuses a permanent list of destructive commands that")
        say("  cannot be changed from Pantheon, by a setting, or by a flag.")
        if args.allow_elevated:
            say(f"  These may request elevation (UAC/sudo asks you): "
                f"{', '.join(args.allow_elevated)}")
        say("")
    if not args.allow:
        say("  No --allow given: the agent will describe this machine but refuse")
        say("  every target. Add --allow <cidr> to let it answer about a network.")
        say("")

    token_hash, raw = load_or_create(state) if not args.dry_run else ("", None)
    if args.dry_run:
        say("  would mint a token (or reuse the existing one)")
    elif raw:
        say("  minted a new token")
    else:
        say("  reusing the token already in the state directory")
        say("  (delete token.json and re-run to rotate it)")
    _ = token_hash

    values = {"netagent_url": url}
    if raw:
        values["netagent_token"] = raw
    elif not args.dry_run:
        say("")
        say("  ! The token already existed, so its raw value is not recoverable —")
        say("    only its hash is stored, which is the point. Pantheon's existing")
        say("    setting is left alone. To re-pair: delete")
        say(f"    {state / 'token.json'} and run this again.")
    _write_settings(settings, values, dry_run=args.dry_run)

    command = _launch_hint(repo, args.port, args.bind, args.allow,
                           args.allow_exec, args.allow_elevated)
    say("")
    say("  Start the agent with:")
    say(f"      {command}")
    say("")
    say("  To keep it running after you log out, use your platform's own")
    say("  scheduler — Task Scheduler on Windows, a user launchd/systemd unit")
    say("  elsewhere. Deliberately not a service installer: a background service")
    say("  is easy to install and hard to remember you installed, and this one")
    say("  has the network.")

    if args.start and not args.dry_run:
        say("")
        say("  starting it now…")
        creation = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
        popen_kwargs = {"cwd": str(repo), "stdout": subprocess.DEVNULL,
                        "stderr": subprocess.DEVNULL}
        if IS_WINDOWS:
            popen_kwargs["creationflags"] = creation | getattr(
                subprocess, "DETACHED_PROCESS", 0)
        else:
            popen_kwargs["start_new_session"] = True
        subprocess.Popen(command.split(), **popen_kwargs)  # noqa: S603
        say("  started. Check Settings → Networks → Network agent.")
    say("=" * 62)
    if args.dry_run:
        say("  DRY RUN — nothing was written, nothing was started.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
