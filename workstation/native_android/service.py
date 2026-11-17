# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pantheon's Android VM service: `android-vm` in docker-compose.yml.

The owner's design (2026-11-16): the host is layer 0, Pantheon and its services
are layer 1, and each family of VMs has a container of its own, side by side,
never one inside another. `workstation-vm` runs each person's Linux desktop;
this service runs each person's Android phone. Nesting the phone inside the
desktop VM put it three hypervisors deep under Docker Desktop, where it never
reached its display, and tied it to whatever system the desktop runs. As its
own service it is one VM per person beside that person's desktop, restartable
and sized on its own (`docs/vm-services.md`).

It is the native Android host worker (`server.py`, `host.py`) run in a Linux
container on KVM, with three things a worker on someone's own machine does not
need:

* **Kernel rules for the whole service.** Before anything else runs, every
  socket of the service's account is kept off private and LAN addresses
  (`netrules`, mode *internet*): Google's SDK repository and, when phones have
  internet, the public internet answer; Pantheon, the other services and the
  LAN do not. Pantheon's requests *to* this service still get their answers.
* **Netsim as a process of its own per phone** (`radio.ProcessRadio`), since
  there is no Docker socket in here and there must not be one.
* **The licence as a step an admin takes.** Nothing of Google's is in the
  image. Until an admin has read and accepted Google's Android SDK License at a
  terminal, the service answers every phone with the one sentence that says
  how (`docker compose run --rm android-vm accept-license`), and downloads
  nothing. An environment variable does not accept it here.

    python3 -m workstation.native_android.service serve           # the container's default
    python3 -m workstation.native_android.service accept-license  # an admin, at a terminal
    python3 -m workstation.native_android.service health          # Docker's healthcheck
"""
from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import secrets
import shutil
import signal
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from workstation import agentd, netrules, protocol as P

logger = logging.getLogger(__name__)

#: The account everything after start-up runs as: the worker, every emulator
#: and every Netsim. Not root, no capabilities, and the only account the
#: kernel rules name.
SERVICE_UID = SERVICE_GID = 500
TABLE = 'pantheon_android'
PORT = 7993
STATE_ENV = 'PANTHEON_ANDROID_VM_STATE'
PAIRING_ENV = 'PANTHEON_ANDROID_VM_PAIRING'
PAIRING_GID_ENV = 'PANTHEON_ANDROID_PAIRING_GID'
DEFAULT_STATE = '/var/lib/pantheon-android'
DEFAULT_PAIRING = '/android-pairing'
#: What an admin sets on the service (`.env.example`): the pool this service
#: may use, and each phone's share of it.
ENV = {
    'max_running': 'PANTHEON_ANDROID_VM_MAX_RUNNING',
    'memory_mib': 'PANTHEON_ANDROID_VM_PHONE_MEMORY_MIB',
    'cores': 'PANTHEON_ANDROID_VM_PHONE_CPUS',
    'internet': 'PANTHEON_ANDROID_VM_INTERNET',
    'gpu': 'PANTHEON_ANDROID_VM_GPU',
}
MAX_PHONES = 16
#: Room kept beside each phone for the emulator's own process, scrcpy and Netsim.
PHONE_OVERHEAD_MIB = 2048
ACCEPT_COMMAND = 'docker compose run --rm android-vm accept-license'
NEEDS_LICENCE = ("Android needs Google's Android SDK License accepted once before Pantheon downloads the "
                 "emulator. An admin reads and accepts it at a terminal on the Pantheon host: "
                 + ACCEPT_COMMAND + ". Your device data is kept.")
INSTALLING = ("Android is being installed on Pantheon's Android VM service. The first start downloads "
              "Google's emulator and tools; your phone starts once that finishes.")


class SettingsError(ValueError):
    """A value an admin set that this service cannot use; the sentence says which."""


def _int(environ, name, default, low, high):
    raw = (environ.get(name) or '').strip()
    if not raw:
        return default
    if not raw.isdigit() or not low <= int(raw) <= high:
        raise SettingsError(f'{name} is a whole number from {low} to {high}, not {raw!r}.')
    return int(raw)


def settings(environ, *, total_mib):
    """The admin's choices from the environment, checked: how many phones may
    run at once (`auto` sizes it to this machine), each phone's memory and
    CPUs, whether phones reach the internet, and the renderer."""
    from workstation import phone as PH
    memory = _int(environ, ENV['memory_mib'], 0, 2048, 65536)
    sized = memory or PH.default_memory_mib(total_mib)
    raw = (environ.get(ENV['max_running']) or 'auto').strip().lower()
    if raw == 'auto':
        max_running = max(1, min(MAX_PHONES, total_mib // (sized + PHONE_OVERHEAD_MIB)))
    else:
        max_running = _int(environ, ENV['max_running'], 1, 1, MAX_PHONES)
    internet = (environ.get(ENV['internet']) or 'on').strip().lower()
    # flag-spelling: the workstation package is standard library only and imports nothing of Pantheon's; on and off as the compose file writes them.
    if internet not in ('on', 'off'):
        raise SettingsError(f"{ENV['internet']} is on or off, not {internet!r}.")
    gpu = (environ.get(ENV['gpu']) or 'software').strip().lower()
    if gpu not in ('auto', 'host', 'software', 'swiftshader'):
        raise SettingsError(f"{ENV['gpu']} is auto, host, software or swiftshader, not {gpu!r}.")
    out = {'max_running': max_running, 'cores': _int(environ, ENV['cores'], 4, 1, 16),
           'internet': internet == 'on', 'gpu': gpu}
    if memory:
        out['memory_mib'] = memory
    return out


# ── start-up, as root, once ───────────────────────────────────────────────────

def harden():
    """KVM opened to the service's account, then the kernel rules written and
    read back from the kernel. Returns why KVM is unusable, or None."""
    from workstation import phone as PH
    ok, why = PH.kvm_for_accounts()
    netrules.apply(netrules.ruleset('internet', table=TABLE, uids=(SERVICE_UID, SERVICE_UID),
                                    resolvers=netrules.lan_resolvers()))
    if netrules.in_force(TABLE) != 'internet':
        raise RuntimeError("The Android VM service's network rules were not installed.")
    if ok:
        return None
    return ('The Android VM service has no KVM here: ' + why.split('. ')[0].rstrip('.') + '. Android VMs need '
            'hardware virtualisation: KVM on Linux, or Docker Desktop on WSL 2 on Windows.')


def pair(pairing: Path, state: Path, gid):
    """The token Pantheon reads (root:<PGID> 0640 in the pairing volume, as the
    Linux VM service keeps its own) and the service's private copy of it."""
    from workstation.__main__ import secure_pairing
    pairing.mkdir(parents=True, exist_ok=True)
    token = agentd.load_or_create_token(pairing, env=None)
    secure_pairing(pairing, gid)
    copy = state / 'pairing' / 'token'
    from .platform_support import write_private
    write_private(copy, token + '\n')
    for path in (state, copy.parent, copy):
        os.chown(path, SERVICE_UID, SERVICE_GID)
    return copy


def drop_privileges():
    """From root to the service's account for good: no groups, no capability
    in any set or the bounding set, and no way back (no-new-privileges)."""
    libc = ctypes.CDLL(None, use_errno=True)
    for bit in range(64):
        if libc.prctl(24, bit, 0, 0, 0) != 0 and ctypes.get_errno() != 22:  # PR_CAPBSET_DROP; EINVAL past the last
            raise OSError('Could not drop the Android VM service\'s capability bound.')
    os.setgroups([])
    os.setgid(SERVICE_GID)
    os.setuid(SERVICE_UID)
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise OSError('Could not set no-new-privileges.')
    for name in ('CapEff', 'CapPrm', 'CapAmb'):
        if netrules.capabilities(name):
            raise RuntimeError('The Android VM service kept a capability.')


# ── while Android is not ready: one sentence for every phone ──────────────────

class WaitingStation:
    """Answers the Android host's routes while there is no Android to run: the
    health check says why, and every phone route is `unavailable` with that
    sentence. Starts nothing and downloads nothing."""
    authorised = agentd.Workstation.authorised
    check_account = staticmethod(agentd.Workstation.check_account)

    def __init__(self, token, why):
        self.token = token
        self.run = secrets.token_hex(16)
        self.system = SimpleNamespace(accel=None, why=why, reprobe=lambda: None)
        self.phones = SimpleNamespace(get=self._refuse)

    def set_why(self, why):
        self.system.why = why

    def _refuse(self, *_args, **_kwargs):
        raise agentd.WorkstationError('unavailable', self.system.why)

    phone = control = choice = phone_screen = _refuse


def waiting_server(station, bind, port):
    from .server import Handler

    class Bound(Handler):
        pass
    Bound.station = station

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        block_on_close = False
        allow_reuse_address = True
    return Server((bind, port), Bound)


# ── Android itself, as the service's account ──────────────────────────────────

def install(layout, wanted, *, token_file, bind, port):
    """What `bootstrap.py up` installs, minus what this image already has (the
    worker's Python) and what it must not have (Docker): Google's emulator and
    platform-tools from Google's repository at the pinned revisions, Netsim
    from that emulator, the pinned scrcpy server. Then the host configuration
    this service runs, written as `configure.py` writes it."""
    from . import bootstrap as B
    from .configure import prepare
    from .platform_support import native_abi, write_private
    abi = native_abi()
    host = B.host_key()
    catalogue = B.Catalogue(abi)
    if not B.accepted(layout.state, abi):
        raise B.BootstrapError(NEEDS_LICENCE, B.EXIT_CONSENT)
    # Licence files the SDK checks, written from the texts the admin accepted.
    B.ensure_consent(layout, abi, catalogue, accept=set(), interactive=False)
    needs = [n for n in ('emulator', 'platform-tools')
             if B.installed_revision(layout.sdk, n)[0] != B.load_pins()[n]['revision']]
    if needs or not layout.netsimd.exists():
        probe = layout.sdk if layout.sdk.exists() else layout.sdk.parent
        probe.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(probe).free < B.FREE_BYTES:
            raise B.BootstrapError(f'Android needs about {B.FREE_BYTES >> 30} GiB free in the android-vm '
                                   f'volume; there are {shutil.disk_usage(probe).free >> 30} GiB.')
    for name in ('emulator', 'platform-tools'):
        B.ensure_package(layout, name, host, catalogue)
    B.check_acceleration(layout)
    B.ensure_netsimd(layout, host, catalogue)
    B.ensure_scrcpy(layout)
    config_file, config = prepare(state=layout.state, sdk=layout.sdk, radio_binary=layout.netsimd,
                                  scrcpy_server=layout.scrcpy, internet=wanted['internet'], port=port, bind=bind,
                                  app_url=f'http://android-vm:{port}', gpu=wanted['gpu'])
    config.update({key: value for key, value in wanted.items() if key != 'memory_mib'})
    if 'memory_mib' in wanted:
        config['memory_mib'] = wanted['memory_mib']
    else:
        config.pop('memory_mib', None)  # sized to this machine by the host
    config.update({'radio_transport': 'process', 'token_file': str(token_file), 'service': 'android-vm'})
    write_private(config_file, json.dumps(config, indent=2) + '\n')
    return config


def serve(args, environ=os.environ):
    import psutil  # noqa: PLC0415 — the image's, from host-requirements.lock
    from . import bootstrap as B
    from .platform_support import native_abi
    state = Path(environ.get(STATE_ENV) or DEFAULT_STATE)
    pairing = Path(environ.get(PAIRING_ENV) or DEFAULT_PAIRING)
    total_mib = psutil.virtual_memory().total // (1024 * 1024)
    try:
        wanted = settings(environ, total_mib=total_mib)
    except SettingsError as error:
        logger.error('%s', error)
        return 2
    state.mkdir(parents=True, exist_ok=True)
    os.chown(state, SERVICE_UID, SERVICE_GID)
    from workstation.__main__ import _gid
    no_kvm = harden()
    token_file = pair(pairing, state, _gid(environ.get(PAIRING_GID_ENV, '')))
    drop_privileges()
    token = token_file.read_text().strip()
    layout = B.Layout(state)
    abi = native_abi()
    stop = threading.Event()
    station = WaitingStation(token, no_kvm or INSTALLING)
    waiting = waiting_server(station, args.bind, args.port)
    threading.Thread(target=waiting.serve_forever, daemon=True).start()

    def on_signal(*_):
        stop.set()
        threading.Thread(target=waiting.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    logger.info('Android VM service on %s:%s; %d phone(s) at once, %s CPUs each, internet %s',
                args.bind, args.port, wanted['max_running'], wanted['cores'], 'on' if wanted['internet'] else 'off')
    if no_kvm:
        logger.error('%s', no_kvm)
        stop.wait()
        waiting.server_close()
        return 0
    config = None
    while not stop.is_set():
        if not B.accepted(layout.state, abi):
            station.set_why(NEEDS_LICENCE)
            logger.warning('%s', NEEDS_LICENCE)
            while not stop.wait(5) and not B.accepted(layout.state, abi):
                pass
            continue
        station.set_why(INSTALLING)
        try:
            config = install(layout, wanted, token_file=token_file, bind=args.bind, port=args.port)
            break
        except (B.BootstrapError, RuntimeError, OSError) as error:
            why = getattr(error, 'message', None) or str(error)
            station.set_why('The Android VM service could not install Android: ' + why)
            logger.error('could not install Android (trying again in five minutes): %s', why)
            stop.wait(300)
    waiting.shutdown()
    waiting.server_close()
    if stop.is_set() or config is None:
        return 0
    from .server import make_server
    server = make_server(config)

    def finish(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, finish)
    signal.signal(signal.SIGINT, finish)
    logger.info('Android ready: %s acceleration', server.host.accel or 'no')
    try:
        server.serve_forever()
    finally:
        try:
            server.host.stop_all()
        finally:
            server.server_close()
    return 0


def accept_license(args, environ=os.environ):
    """Google's agreement shown in full and accepted only by a typed yes, at a
    terminal. What `bootstrap.py` asks an operator on their own machine."""
    from . import bootstrap as B
    from .platform_support import native_abi
    state = Path(environ.get(STATE_ENV) or DEFAULT_STATE)
    if not (sys.stdin is not None and sys.stdin.isatty()):
        print('✗ Android: the licence is accepted at a terminal. Run: ' + ACCEPT_COMMAND, file=sys.stderr)
        return B.EXIT_CONSENT
    if os.geteuid() == 0:
        state.mkdir(parents=True, exist_ok=True)
        os.chown(state, SERVICE_UID, SERVICE_GID)
        harden()
        drop_privileges()
    layout = B.Layout(state)
    abi = native_abi()
    try:
        B.ensure_consent(layout, abi, B.Catalogue(abi), accept=set(), interactive=True,
                         show=lambda text: print(text, file=sys.stderr))
    except B.BootstrapError as error:
        print('✗ Android: ' + error.message, file=sys.stderr)
        return error.code
    print('✓ Android: accepted. The Android VM service installs Android now; nothing to restart.', file=sys.stderr)
    return 0


def health(args, environ=os.environ):
    """Docker's healthcheck: the service answers its own authenticated health route."""
    import urllib.request
    state = Path(environ.get(STATE_ENV) or DEFAULT_STATE)
    try:
        token = (state / 'pairing' / 'token').read_text().strip()
        request = urllib.request.Request(f'http://127.0.0.1:{args.port}/v1/health',
                                         headers={'Authorization': 'Bearer ' + token})
        answer = json.load(urllib.request.urlopen(request, timeout=5))
    except (OSError, ValueError):
        return 1
    return 0 if answer.get('agent') == P.AGENT_NAME and answer.get('backend') == 'native_android' else 1


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python3 -m workstation.native_android.service',
                                     description=__doc__.split('\n\n')[0])
    parser.add_argument('command', nargs='?', default='serve', choices=('serve', 'accept-license', 'health'))
    parser.add_argument('--bind', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=PORT)
    args = parser.parse_args(argv)
    logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    os.umask(0o077)
    return {'serve': serve, 'accept-license': accept_license, 'health': health}[args.command](args)


if __name__ == '__main__':
    sys.exit(main())
