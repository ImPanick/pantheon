# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bring the Android host up with Pantheon, on a machine that has nothing yet.

`docs/android-host.md` lists seven manual steps between a fresh machine and a
phone that boots: Google's emulator and platform-tools in a private SDK, Linux
`netsimd` from the same emulator release, the pinned scrcpy server, the radio
helper's Docker image, pairing, a running worker, and the app told where it is.
Nothing did them, so Android worked only where someone had run them by hand.
This module does all of them, each only when it is missing, then starts the
worker under a small supervisor and stops it again with Pantheon:

    python -m workstation.native_android.bootstrap up --app native --print-env sh
    python -m workstation.native_android.bootstrap up --app docker --compose -- up -d --build
    python -m workstation.native_android.bootstrap down [--compose -- down]
    python -m workstation.native_android.bootstrap status

`start-macos.sh` and `launch-windows.ps1` call `up --app native` before the
server and `down` when it exits; a Docker install runs the second line instead
of `docker compose up`.

What it will not do:

* Accept a licence for anyone. Google's SDK agreement (and on Apple silicon the
  ARM image agreement) is shown once, on the first run at a terminal, and the
  operator types yes; a run with no terminal stops with the sentence that says
  how (`--accept-sdk-license`). The acceptance is kept in the host's
  `license-consent.json`, as `configure` keeps it.
* Download from anywhere but Google's SDK repository (dl.google.com, checked
  against the size and SHA-1 in Google's own catalogue, and the SHA-256 in
  `sdk-pins.json` or the one recorded on first install), the scrcpy GitHub
  release (pinned SHA-256), and PyPI (`host-requirements.lock`, every hash).
* Touch an SDK it did not install. A package folder it finds without its own
  marker is used when its revision is the pinned one, and refused otherwise.
* Start a worker on a host whose hypervisor the emulator cannot use. That stops
  here, with what to change on this OS, instead of in a phone that never boots.

Standard library only: it runs before the worker's own venv exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath

from .images import extract, sha
from .platform_support import (ARM_LICENSE, SDK_LICENSE, accelerator_name, accepted, check_python, native_abi,
                               record_consent, required_licenses, write_private)

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PINS = HERE / 'sdk-pins.json'
LOCK = HERE / 'host-requirements.lock'
REPOSITORY = 'https://dl.google.com/android/repository/'
CATALOGUE = REPOSITORY + 'repository2-3.xml'
IMAGE_CATALOGUES = {
    'x86_64': REPOSITORY + 'sys-img/google_apis/sys-img2-3.xml',
    'arm64-v8a': REPOSITORY + 'sys-img/google_apis/sys-img2-3.xml',
}
LICENSE_URL = 'https://developer.android.com/studio/terms'
ARM_LICENSE_URL = REPOSITORY + 'sys-img/google_apis/sys-img2-3.xml'
RADIO_IMAGE = 'pantheon-android-radio:37.2.13'
RADIO_LABEL = 'pantheon.radio-source'
RADIO_SOURCES = ('workstation/native_android/Dockerfile.radio',
                 'workstation/native_android/radio_init.py', 'workstation/netrules.py')
DEFAULT_PORT = 7993
FREE_BYTES = 8 << 30
HEALTH_WAIT_S = 90.0
STOP_WAIT_S = 180.0
ACCEPT_ENV = 'PANTHEON_ANDROID_ACCEPT_LICENSES'
STATE_ENV = 'PANTHEON_ANDROID_HOST_DIR'
SDK_ENV = 'PANTHEON_ANDROID_SDK'
MARKER = '.pantheon-package.json'
PACKAGE_DIRS = {'emulator': 'emulator', 'platform-tools': 'platform-tools'}
PACKAGE_BINARIES = {'emulator': 'emulator', 'platform-tools': 'adb'}

EXIT_FAILED, EXIT_CONSENT, EXIT_ACCEL, EXIT_DOCKER = 1, 3, 4, 5

NEEDS_CONSENT = (
    "Android needs Google's Android SDK License ({url}){arm} accepted once on this machine before "
    "Pantheon downloads the emulator. Run this at a terminal to read and accept it, or pass "
    "--accept-sdk-license{arm_flag} (or set {env}={ids}) if you, the operator, accept it.")


class BootstrapError(Exception):
    def __init__(self, message: str, code: int = EXIT_FAILED):
        super().__init__(message)
        self.message = message
        self.code = code


def say(text: str) -> None:
    print('▶ Android: ' + text, file=sys.stderr, flush=True)


# ── where things are ──────────────────────────────────────────────────────────

def host_key() -> tuple[str, str]:
    """This machine as Google's catalogue names hosts: `(host-os, host-arch)`."""
    os_name = {'Linux': 'linux', 'Darwin': 'macosx', 'Windows': 'windows'}.get(platform.system())
    try:
        abi = native_abi()
    except RuntimeError as error:
        raise BootstrapError(str(error)) from None
    if os_name is None:
        raise BootstrapError('The stock SDK has no local emulator for this OS. Connect Pantheon to a compatible Android worker.')
    return os_name, ('aarch64' if abi == 'arm64-v8a' else 'x64')


def default_state() -> Path:
    if os.environ.get(STATE_ENV):
        return Path(os.environ[STATE_ENV]).expanduser()
    return Path.home() / '.pantheon' / 'android-host'


def exe(name: str) -> str:
    return name + ('.exe' if os.name == 'nt' else '')


class Layout:
    """Every path the host keeps, from its state folder and SDK."""

    def __init__(self, state: Path, sdk: Path | None = None):
        self.state = Path(state).expanduser().resolve()
        config = self.config_file
        recorded = None
        if config.exists():
            try:
                recorded = json.loads(config.read_text()).get('sdk')
            except (OSError, ValueError):
                recorded = None
        chosen = sdk or (Path(os.environ[SDK_ENV]) if os.environ.get(SDK_ENV) else None) or \
            (Path(recorded) if recorded else None) or self.state / 'sdk'
        self.sdk = Path(chosen).expanduser().resolve()

    config_file = property(lambda self: self.state / 'host-config.json')
    venv = property(lambda self: self.state / 'venv')
    radio = property(lambda self: self.state / 'radio')
    netsimd = property(lambda self: self.state / 'radio' / 'netsimd')
    scrcpy = property(lambda self: self.state / ('scrcpy-server-v' + load_pins()['scrcpy-server']['version']))
    pins = property(lambda self: self.state / 'sdk-pins.json')
    worker = property(lambda self: self.state / 'worker.json')
    stop_file = property(lambda self: self.state / 'worker.stop')
    log = property(lambda self: self.state / 'worker.log')
    token = property(lambda self: self.state / 'pairing' / 'token')
    emulator = property(lambda self: self.sdk / 'emulator' / exe('emulator'))

    def python(self) -> Path:
        return self.venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def load_pins() -> dict:
    return json.loads(PINS.read_text())


# ── downloads ─────────────────────────────────────────────────────────────────

def _official(url: str) -> None:
    allowed = (REPOSITORY, load_pins()['scrcpy-server']['url'])
    if not any(url == a or (a.endswith('/') and url.startswith(a)) for a in allowed):
        raise BootstrapError(f'Refusing to download {url}: it is not an official source Pantheon pins.')


def fetch(url: str, limit: int = 16 << 20) -> bytes:
    _official(url)
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read(limit + 1)
    except (urllib.error.URLError, OSError) as error:
        raise BootstrapError(f'Could not reach {url} ({error}). Android needs to download from Google once; '
                             'check this machine can reach dl.google.com.') from None
    if len(data) > limit:
        raise BootstrapError(f'{url} is larger than any catalogue should be.')
    return data


def download(url: str, folder: Path, *, size: int | None, sha1: str | None, sha256: str | None,
             label: str) -> tuple[Path, str]:
    """`url` into `folder`, checked against everything known about it. Returns
    the file and its SHA-256."""
    _official(url)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / PurePosixPath(url).name
    for attempt in range(3):
        digest1, digest256, done, shown = hashlib.sha1(), hashlib.sha256(), 0, -1
        try:
            with urllib.request.urlopen(url, timeout=60) as response, target.open('wb') as out:
                while True:
                    block = response.read(1 << 20)
                    if not block:
                        break
                    done += len(block)
                    if size and done > size:
                        raise BootstrapError(f'{label} is larger than Google\'s catalogue says; refusing it.')
                    out.write(block)
                    digest1.update(block)
                    digest256.update(block)
                    if size:
                        tenth = done * 10 // size
                        if tenth != shown:
                            shown = tenth
                            say(f'downloading {label}: {tenth * 10}%')
            break
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            target.unlink(missing_ok=True)
            if attempt == 2:
                raise BootstrapError(f'Could not download {label} from {url} ({error}).') from None
            time.sleep(2 ** attempt)
    if size is not None and done != size:
        target.unlink(missing_ok=True)
        raise BootstrapError(f'{label} is {done} bytes; Google\'s catalogue says {size}. Refusing it.')
    if sha1 and digest1.hexdigest() != sha1.lower():
        target.unlink(missing_ok=True)
        raise BootstrapError(f'{label} does not match the SHA-1 in Google\'s catalogue. Refusing it.')
    if sha256 and digest256.hexdigest() != sha256.lower():
        target.unlink(missing_ok=True)
        raise BootstrapError(f'{label} does not match its pinned SHA-256. Refusing it.')
    return target, digest256.hexdigest()


# ── Google's catalogue ────────────────────────────────────────────────────────

def revision_of(element) -> str:
    rev = element.find('revision')
    if rev is None:
        return ''
    parts = [rev.findtext(k) for k in ('major', 'minor', 'micro')]
    return '.'.join(p for p in parts if p is not None)


def catalogue_archive(tree, path: str, revision: str, host: tuple[str, str]) -> tuple[dict | None, list[str]]:
    """The archive of `path` at `revision` for `host` in a catalogue, and every
    revision the catalogue offers (for the sentence when the pin is gone)."""
    offered = []
    for entry in tree.iter('remotePackage'):
        if entry.get('path') != path:
            continue
        found = revision_of(entry)
        offered.append(found)
        if found != revision:
            continue
        licence = entry.find('uses-license')
        for archive in entry.iter('archive'):
            os_name = archive.findtext('host-os')
            arch = archive.findtext('host-arch')
            if os_name not in (None, host[0]) or arch not in (None, host[1]):
                continue
            complete = archive.find('complete')
            url = complete.findtext('url')
            if not url or PurePosixPath(url).name != url:
                raise BootstrapError(f'Google\'s catalogue names an unexpected archive for {path}.')
            return ({'revision': revision, 'url': REPOSITORY + url, 'size': int(complete.findtext('size')),
                     'sha1': (complete.findtext('checksum') or '').lower(),
                     'license': licence.get('ref') if licence is not None else SDK_LICENSE}, offered)
    return None, offered


def licence_texts(*trees) -> dict[str, str]:
    out: dict[str, str] = {}
    for tree in trees:
        for item in tree.iter('license'):
            if item.get('id') and item.get('id') not in out:
                out[item.get('id')] = ''.join(item.itertext())
    return out


class Catalogue:
    """Google's catalogues, fetched once a run and only when something needs them."""

    def __init__(self, abi: str):
        self.abi = abi
        self._main = self._images = None

    def main(self):
        if self._main is None:
            self._main = ET.fromstring(fetch(CATALOGUE))
        return self._main

    def images(self):
        if self._images is None:
            self._images = ET.fromstring(fetch(IMAGE_CATALOGUES[self.abi]))
        return self._images

    def licences(self) -> dict[str, str]:
        return licence_texts(self.main(), self.images())


# ── licences ──────────────────────────────────────────────────────────────────

def write_sdk_licences(sdk: Path, texts: dict[str, str], ids) -> None:
    """What `sdkmanager --licenses` writes: the SHA-1 of each accepted text,
    one per line under `licenses/`. `images.py` reads the same files."""
    folder = sdk / 'licenses'
    folder.mkdir(parents=True, exist_ok=True)
    for licence in ids:
        text = texts.get(licence)
        if text is None:
            continue
        digest = hashlib.sha1(text.encode()).hexdigest()
        path = folder / licence
        lines = path.read_text().split() if path.exists() else []
        if digest not in lines:
            path.write_text('\n'.join(lines + [digest]) + '\n')


def ask_operator(prompt: str) -> str:
    """`input()` on stderr: stdout may be the app's environment (`--print-env`)
    that a launcher captures, where a question would never be seen."""
    sys.stderr.write(prompt)
    sys.stderr.flush()
    return sys.stdin.readline()


def ensure_consent(layout: Layout, abi: str, catalogue: Catalogue, *, accept: set[str],
                   interactive: bool, ask=ask_operator, show=print) -> None:
    ids = required_licenses(abi)
    if accepted(layout.state, abi):
        if not all((layout.sdk / 'licenses' / i).exists() for i in ids):
            write_sdk_licences(layout.sdk, catalogue.licences(), ids)
        return
    by_flag = set(ids) <= accept
    if not by_flag and not interactive:
        arm = abi == 'arm64-v8a'
        raise BootstrapError(NEEDS_CONSENT.format(
            url=LICENSE_URL, arm=f' and the ARM image agreement ({ARM_LICENSE_URL})' if arm else '',
            arm_flag=' --accept-arm-license' if arm else '', env=ACCEPT_ENV, ids=','.join(ids)), EXIT_CONSENT)
    texts = catalogue.licences()
    missing = [i for i in ids if i not in texts]
    if missing:
        raise BootstrapError(f'Google\'s catalogue no longer carries the {", ".join(missing)} text; '
                             'Pantheon cannot show what would be accepted.')
    if by_flag:
        source = 'Operator flag or environment at the Pantheon launcher'
    else:
        for licence in ids:
            show(f'\n──── {licence} ────\n{texts[licence].strip()}\n')
        show(f'Pantheon will download Google\'s Android Emulator, platform-tools and Android system images '
             f'into {layout.sdk}. They are Google\'s, under the agreement{"s" if len(ids) > 1 else ""} above '
             f'({", ".join(ids)}); Pantheon does not redistribute them.')
        answer = ask(f'Do you accept {" and ".join(ids)}? Type yes to accept: ').strip().lower()
        if answer not in ('y', 'yes'):
            raise BootstrapError('Not accepted, so Android was not installed. Pantheon runs without it.',
                                 EXIT_CONSENT)
        source = 'Operator prompt at the Pantheon launcher'
    record_consent(layout.state, ids, source=source,
                   texts={i: hashlib.sha256(texts[i].encode()).hexdigest() for i in ids})
    write_sdk_licences(layout.sdk, texts, ids)
    say('licence accepted and recorded in ' + str(layout.state / 'license-consent.json'))


# ── the worker's own Python ───────────────────────────────────────────────────

def ensure_venv(layout: Layout, *, run=subprocess.run) -> bool:
    want = sha(LOCK)
    marker = layout.venv / '.pantheon-lock-sha256'
    if layout.python().exists() and marker.exists() and marker.read_text().strip() == want:
        return False
    say('installing the worker\'s Python packages (pinned, hash-checked)')
    if not layout.python().exists():
        result = run([sys.executable, '-m', 'venv', str(layout.venv)], capture_output=True, text=True)
        if result.returncode:
            raise BootstrapError('Could not create the Android worker\'s Python environment: '
                                 + (result.stderr or result.stdout)[-400:])
    result = run([str(layout.python()), '-m', 'pip', 'install', '--disable-pip-version-check', '--quiet',
                  '--require-hashes', '--prefer-binary', '-r', str(LOCK)], capture_output=True, text=True)
    if result.returncode:
        raise BootstrapError('Could not install the Android worker\'s Python packages: '
                             + (result.stderr or result.stdout)[-600:])
    marker.write_text(want + '\n')
    return True


# ── SDK packages ──────────────────────────────────────────────────────────────

def source_revision(folder: Path) -> str | None:
    props = folder / 'source.properties'
    try:
        for line in props.read_text(errors='replace').splitlines():
            if line.split('=', 1)[0].strip() == 'Pkg.Revision':
                return line.split('=', 1)[1].strip()
    except OSError:
        return None
    return None


def installed_revision(sdk: Path, name: str) -> tuple[str | None, bool]:
    """`(revision, managed)` of a package folder in the SDK."""
    folder = sdk / PACKAGE_DIRS[name]
    marker = folder / MARKER
    if marker.exists():
        try:
            return json.loads(marker.read_text()).get('revision'), True
        except (OSError, ValueError):
            return None, True
    if folder.exists():
        return source_revision(folder), False
    return None, False


def resolve_archive(layout: Layout, name: str, host: tuple[str, str], catalogue: Catalogue) -> dict:
    pins = load_pins()[name]
    key = f'{host[0]}-{host[1]}'
    pinned = dict(pins.get('archives', {}).get(key) or {})
    recorded = {}
    if layout.pins.exists():
        recorded = json.loads(layout.pins.read_text()).get(name, {}).get(key) or {}
    if pinned.get('url'):
        spec = {**pinned, 'revision': pins['revision'], 'license': pins.get('license', SDK_LICENSE)}
    elif recorded.get('revision') == pins['revision'] and recorded.get('url'):
        spec = dict(recorded)
    else:
        spec, offered = catalogue_archive(catalogue.main(), name, pins['revision'], host)
        if spec is None:
            raise BootstrapError(
                f'Google\'s catalogue does not offer {name} {pins["revision"]} for {key} '
                f'(it offers {", ".join(sorted(set(offered))) or "nothing"}). Pantheon pins that revision; '
                f'add its archive to workstation/native_android/sdk-pins.json to install it.')
    if pinned.get('sha256'):
        if recorded.get('sha256') and recorded['sha256'] != pinned['sha256']:
            raise BootstrapError(f'{name} recorded on this host does not match the SHA-256 pinned in the repository.')
        spec['sha256'] = pinned['sha256']
    elif recorded.get('sha256') and recorded.get('url') == spec.get('url'):
        spec['sha256'] = recorded['sha256']
    return spec


def record_pin(layout: Layout, name: str, host: tuple[str, str], spec: dict) -> None:
    records = json.loads(layout.pins.read_text()) if layout.pins.exists() else {}
    records.setdefault(name, {})[f'{host[0]}-{host[1]}'] = {k: spec[k] for k in
                                                           ('revision', 'url', 'size', 'sha1', 'sha256', 'license') if k in spec}
    write_private(layout.pins, json.dumps(records, indent=2, sort_keys=True) + '\n')


def ensure_package(layout: Layout, name: str, host: tuple[str, str], catalogue: Catalogue) -> bool:
    revision = load_pins()[name]['revision']
    have, managed = installed_revision(layout.sdk, name)
    folder = layout.sdk / PACKAGE_DIRS[name]
    if have == revision:
        return False
    if folder.exists() and not managed:
        raise BootstrapError(
            f'{folder} holds an Android {name} Pantheon did not install (revision {have or "unknown"}); '
            f'Pantheon pins {revision}. Set {SDK_ENV} to an empty folder, or remove that one.')
    spec = resolve_archive(layout, name, host, catalogue)
    layout.sdk.mkdir(parents=True, exist_ok=True)
    say(f'installing {name} {revision} from Google ({spec["size"] >> 20} MiB)')
    with tempfile.TemporaryDirectory(prefix='.install-', dir=layout.sdk) as temporary:
        stage = Path(temporary)
        archive, digest = download(spec['url'], stage, size=spec.get('size'), sha1=spec.get('sha1'),
                                   sha256=spec.get('sha256'), label=f'{name} {revision}')
        spec['sha256'] = digest
        unpack = stage / 'unpack'
        unpack.mkdir()
        try:
            extract(archive, unpack)
        except (RuntimeError, zipfile.BadZipFile) as error:
            raise BootstrapError(f'{name} {revision} could not be unpacked: {error}') from None
        archive.unlink()
        source = unpack / PACKAGE_DIRS[name]
        if not (source / exe(PACKAGE_BINARIES[name])).is_file():
            raise BootstrapError(f'{name} {revision} from Google has no {exe(PACKAGE_BINARIES[name])}.')
        (source / MARKER).write_text(json.dumps({k: spec[k] for k in ('revision', 'url', 'sha256')}) + '\n')
        if folder.exists():
            folder.replace(stage / 'previous')
        source.replace(folder)
    record_pin(layout, name, host, spec)
    return True


NETSIM_MEMBERS = ('emulator/netsimd',)


def ensure_netsimd(layout: Layout, host: tuple[str, str], catalogue: Catalogue) -> bool:
    """Linux x86-64 `netsimd` from the pinned emulator release, on every OS: the
    radio helper runs it in a linux/amd64 container (`radio.py`)."""
    revision = load_pins()['emulator']['revision']
    marker = layout.radio / MARKER
    if layout.netsimd.is_file() and marker.exists() and json.loads(marker.read_text()).get('revision') == revision:
        return False
    layout.radio.mkdir(parents=True, exist_ok=True, mode=0o700)
    linux = ('linux', 'x64')
    if host == linux:
        source = layout.sdk / 'emulator' / 'netsimd'
        if not source.is_file():
            raise BootstrapError(f'The emulator {revision} in {layout.sdk} has no netsimd.')
        shutil.copyfile(source, layout.netsimd)
        for notice in (layout.sdk / 'emulator').glob('NOTICE*'):
            shutil.copyfile(notice, layout.radio / notice.name)
        spec = {'revision': revision, 'source': str(source)}
    else:
        spec = resolve_archive(layout, 'emulator', linux, catalogue)
        say(f'fetching Linux netsimd from the emulator {revision} archive ({spec["size"] >> 20} MiB, '
            'the radio helper runs it in a Linux container)')
        with tempfile.TemporaryDirectory(prefix='.netsim-', dir=layout.radio) as temporary:
            archive, digest = download(spec['url'], Path(temporary), size=spec.get('size'), sha1=spec.get('sha1'),
                                       sha256=spec.get('sha256'), label=f'emulator {revision} (Linux)')
            spec['sha256'] = digest
            with zipfile.ZipFile(archive) as package:
                names = package.namelist()
                member = next((n for n in NETSIM_MEMBERS if n in names), None)
                if member is None:
                    raise BootstrapError(f'The Linux emulator {revision} archive has no netsimd.')
                staged = Path(temporary) / 'netsimd'
                with package.open(member) as src, staged.open('wb') as out:
                    shutil.copyfileobj(src, out)
                staged.replace(layout.netsimd)
                for name in names:
                    path = PurePosixPath(name)
                    if len(path.parts) == 2 and path.parts[0] == 'emulator' and \
                            path.name.upper().startswith(('NOTICE', 'LICENSE')):
                        with package.open(name) as src, (layout.radio / path.name).open('wb') as out:
                            shutil.copyfileobj(src, out)
        record_pin(layout, 'emulator', linux, spec)
    layout.netsimd.chmod(0o755)
    marker.write_text(json.dumps({'revision': revision, 'sha256': sha(layout.netsimd)}) + '\n')
    return True


def ensure_scrcpy(layout: Layout) -> bool:
    pin = load_pins()['scrcpy-server']
    if layout.scrcpy.is_file() and sha(layout.scrcpy) == pin['sha256']:
        return False
    say(f'fetching scrcpy-server {pin["version"]} (pinned SHA-256)')
    with tempfile.TemporaryDirectory(prefix='.scrcpy-', dir=layout.state) as temporary:
        file, _ = download(pin['url'], Path(temporary), size=None, sha1=None, sha256=pin['sha256'],
                           label=f'scrcpy-server {pin["version"]}')
        file.replace(layout.scrcpy)
    return True


# ── acceleration ──────────────────────────────────────────────────────────────

def acceleration_advice(system: str, output: str) -> str:
    said = ' '.join(output.split())[-300:]
    if system == 'Linux':
        if not os.path.exists('/dev/kvm'):
            fix = ('This machine has no /dev/kvm. Turn on virtualization (Intel VT-x or AMD-V) in the '
                   'firmware and load the kvm_intel or kvm_amd module; inside a VM, the hypervisor must '
                   'pass nested virtualization through.')
        elif not os.access('/dev/kvm', os.R_OK | os.W_OK):
            fix = ('/dev/kvm is there but this user cannot open it. Add yourself to its group '
                   '(sudo usermod -aG kvm "$USER"), then log out and back in.')
        else:
            fix = 'KVM is present, but the emulator could not use it.'
    elif system == 'Darwin':
        fix = ('macOS provides Hypervisor.framework on the host itself, not inside a virtual machine; '
               'run Pantheon on the Mac, not in a VM, or connect a remote Android worker.')
    elif system == 'Windows':
        fix = ('Turn on "Windows Hypervisor Platform" (Control Panel > Programs > Turn Windows features on '
               'or off), restart, and make sure virtualization is on in the firmware.')
    else:
        fix = 'This host has no accelerator the Android Emulator supports.'
    return f'Android cannot start here: the emulator found no usable hardware acceleration. {fix} (emulator said: {said})'


def check_acceleration(layout: Layout, *, run=subprocess.run) -> str:
    try:
        result = run([str(layout.emulator), '-accel-check'], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BootstrapError(acceleration_advice(platform.system(), str(error)), EXIT_ACCEL) from None
    if result.returncode:
        raise BootstrapError(acceleration_advice(platform.system(), result.stdout + result.stderr), EXIT_ACCEL)
    return accelerator_name(result.stdout + result.stderr)


# ── Docker: the private radio helper ──────────────────────────────────────────

def docker(*args, run=subprocess.run, timeout=60, **kwargs):
    try:
        return run(['docker', *args], capture_output=True, text=True, timeout=timeout, **kwargs)
    except FileNotFoundError:
        raise BootstrapError('Android\'s private network helper runs in Docker, and this machine has no '
                             '`docker` command. Install Docker (Docker Desktop on Mac or Windows) and start it.',
                             EXIT_DOCKER) from None
    except subprocess.TimeoutExpired:
        raise BootstrapError('Docker did not answer. Start Docker and try again.', EXIT_DOCKER) from None


def radio_source_hash() -> str:
    digest = hashlib.sha256()
    for name in RADIO_SOURCES:
        digest.update(name.encode() + b'\0' + (REPO / name).read_bytes() + b'\0')
    return digest.hexdigest()


def ensure_radio_image(*, run=subprocess.run) -> bool:
    info = docker('info', '--format', '{{.OSType}}', run=run)
    if info.returncode or info.stdout.strip() != 'linux':
        raise BootstrapError('Docker is not running Linux containers here. Start Docker (Linux containers) '
                             'and try again; Android\'s private network helper needs it.', EXIT_DOCKER)
    want = radio_source_hash()
    have = docker('image', 'inspect', RADIO_IMAGE, '--format', '{{index .Config.Labels "' + RADIO_LABEL + '"}}', run=run)
    if have.returncode == 0 and have.stdout.strip() == want:
        return False
    say('building the private network helper image ' + RADIO_IMAGE)
    built = docker('build', '--platform', 'linux/amd64', '--label', f'{RADIO_LABEL}={want}', '-t', RADIO_IMAGE,
                   '-f', 'workstation/native_android/Dockerfile.radio', '.', run=run, timeout=1800, cwd=str(REPO))
    if built.returncode:
        hint = (' On Apple silicon, Docker must run linux/amd64 images: turn on "Use Rosetta for x86_64/amd64 '
                'emulation" in Docker Desktop.' if platform.machine().lower() in ('arm64', 'aarch64') else '')
        raise BootstrapError('Could not build the Android network helper image.' + hint + ' Docker said: '
                             + (built.stderr or built.stdout)[-600:], EXIT_DOCKER)
    return True


def docker_bridge_gateway(*, run=subprocess.run) -> str:
    """The host's address on Docker's default bridge: what `host-gateway` (and
    so `host.docker.internal` in docker-compose.yml) resolves to on Linux."""
    out = docker('network', 'inspect', 'bridge', '--format', '{{range .IPAM.Config}}{{.Gateway}} {{end}}', run=run)
    for address in out.stdout.split():
        if address.count('.') == 3:
            return address
    raise BootstrapError('Could not find Docker\'s bridge address, which the app reaches the Android worker on. '
                         'Is Docker running?', EXIT_DOCKER)


# ── Windows: the console token ────────────────────────────────────────────────

def ensure_windows_console_token() -> Path | None:
    if platform.system() != 'Windows':
        return None
    from .platform_support import windows_profile  # noqa: PLC0415
    import secrets  # noqa: PLC0415
    path = windows_profile() / '.emulator_console_auth_token'
    if not path.exists() or not path.read_text(encoding='ascii', errors='replace').strip():
        with path.open('w' if path.exists() else 'x', encoding='ascii') as out:
            out.write(secrets.token_hex(32))
        say(f'created the emulator console token in {path} (docs/android-host.md recommends running the '
            'worker under a dedicated Windows account)')
    return path


# ── pairing ───────────────────────────────────────────────────────────────────

def endpoint(app: str, port: int, *, gateway=docker_bridge_gateway) -> tuple[str, str]:
    """`(bind, app_url)`: where the worker listens and where the app reaches it."""
    if app == 'native':
        return '127.0.0.1', f'http://127.0.0.1:{port}'
    if platform.system() == 'Linux':
        return gateway(), f'http://host.docker.internal:{port}'
    return '127.0.0.1', f'http://host.docker.internal:{port}'


def configure(layout: Layout, *, bind: str, app_url: str, port: int, internet: bool | None,
              console_token: Path | None, run=subprocess.run) -> dict:
    command = [str(layout.python()), '-m', 'workstation.native_android.configure', '--state', str(layout.state),
               '--sdk', str(layout.sdk), '--radio-binary', str(layout.netsimd), '--scrcpy-server', str(layout.scrcpy),
               '--bind', bind, '--app-url', app_url, '--port', str(port)]
    if internet is not None:
        command.append('--internet' if internet else '--no-internet')
    if console_token is not None:
        command += ['--windows-console-token', str(console_token)]
    result = run(command, cwd=str(REPO), capture_output=True, text=True)
    if result.returncode:
        raise BootstrapError('Pairing the Android host failed: ' + (result.stderr or result.stdout)[-600:])
    return json.loads(layout.config_file.read_text())


# ── the worker and its supervisor ─────────────────────────────────────────────

def health(config: dict, token: str, *, timeout: float = 3.0) -> dict | None:
    host = config.get('bind', '127.0.0.1')
    host = '127.0.0.1' if host in ('0.0.0.0', '') else host
    url = f'http://{host}:{config.get("port", DEFAULT_PORT)}/v1/health'
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            answer = json.loads(response.read(65536))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return answer if answer.get('ok') and answer.get('backend') == 'native_android' else None


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == 'nt':
        import ctypes  # noqa: PLC0415
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def ours(pid: int) -> bool:
    """Whether `pid` is still this host's supervisor or worker, before it is
    signalled: a recorded pid can be reused after a crash."""
    if os.name == 'nt':
        return alive(pid)
    try:
        if Path('/proc').is_dir():
            line = Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
        else:
            line = subprocess.run(['ps', '-o', 'command=', '-p', str(pid)], capture_output=True, text=True,
                                  timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return 'workstation.native_android' in line


def read_worker(layout: Layout) -> dict:
    try:
        return json.loads(layout.worker.read_text())
    except (OSError, ValueError):
        return {}


def config_digest(layout: Layout) -> str:
    return sha(layout.config_file) if layout.config_file.exists() else ''


def start_worker(layout: Layout) -> int:
    layout.stop_file.unlink(missing_ok=True)
    command = [str(layout.python()), '-m', 'workstation.native_android.bootstrap', '--state', str(layout.state),
               '--sdk', str(layout.sdk), 'supervise']
    log = layout.log.open('ab')
    try:
        if os.name == 'nt':
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            proc = subprocess.Popen(command, cwd=str(REPO), stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=subprocess.STDOUT, creationflags=flags)
        else:
            proc = subprocess.Popen(command, cwd=str(REPO), stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=subprocess.STDOUT, start_new_session=True)
    finally:
        log.close()
    return proc.pid


def wait_healthy(layout: Layout, config: dict, token: str, supervisor: int, *, wait=HEALTH_WAIT_S) -> dict:
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        answer = health(config, token)
        if answer:
            return answer
        if not alive(supervisor):
            break
        time.sleep(0.5)
    tail = ''
    try:
        tail = layout.log.read_text(errors='replace')[-1200:]
    except OSError as error:
        tail = f'(the log could not be read: {error})'
    raise BootstrapError(f'The Android worker did not come up. Its log is {layout.log}:\n{tail}')


def stop_worker(layout: Layout, *, wait=STOP_WAIT_S) -> bool:
    """Ask the supervisor to stop its worker (which stops every Android VM and
    keeps their data), then wait for it. Returns whether one was running."""
    record = read_worker(layout)
    supervisor, worker = record.get('supervisor'), record.get('worker')
    if not (alive(supervisor) or alive(worker)):
        layout.worker.unlink(missing_ok=True)
        return False
    say('stopping the Android worker (its VMs shut down; their data is kept)')
    layout.stop_file.write_text(str(time.time()))
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline and (alive(supervisor) or alive(worker)):
        time.sleep(0.5)
    for pid in (worker, supervisor):
        if alive(pid) and ours(pid):
            say(f'process {pid} did not stop in {int(wait)} s; ending it')
            try:
                os.kill(int(pid), signal.SIGKILL if hasattr(signal, 'SIGKILL') else signal.SIGTERM)
            except ProcessLookupError:
                pass  # it exited between the check and the kill, which is what was wanted
            except OSError as error:
                say(f'could not end process {pid}: {error}; end it yourself before the next start')
    layout.stop_file.unlink(missing_ok=True)
    layout.worker.unlink(missing_ok=True)
    return True


def supervise(layout: Layout, *, restarts: int = 5, window: float = 600.0) -> int:
    """Run the worker and keep it running until `down` asks it to stop. A
    worker that keeps dying is left stopped, with its log saying why."""
    command = [sys.executable, '-m', 'workstation.native_android.server', '--config', str(layout.config_file)]
    stopping = {'now': False}

    def stop(*_):
        stopping['now'] = True

    for name in ('SIGTERM', 'SIGINT', 'SIGBREAK'):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stop)
    crashes: list[float] = []
    while True:
        options = ({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt'
                   else {'start_new_session': False})
        child = subprocess.Popen(command, cwd=str(REPO), stdin=subprocess.DEVNULL, **options)
        write_private(layout.worker, json.dumps({'supervisor': os.getpid(), 'worker': child.pid,
                                                 'started': time.time(), 'config_sha256': config_digest(layout)}))
        while child.poll() is None:
            if stopping['now'] or layout.stop_file.exists():
                stopping['now'] = True
                try:
                    child.send_signal(signal.CTRL_BREAK_EVENT if os.name == 'nt' else signal.SIGTERM)
                except OSError:
                    pass  # it already exited: the wait below returns at once and nothing is left to stop
                try:
                    child.wait(STOP_WAIT_S - 10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                break
            time.sleep(0.5)
        if stopping['now']:
            print('android worker: stopped', flush=True)
            layout.worker.unlink(missing_ok=True)
            return 0
        now = time.monotonic()
        crashes = [t for t in crashes if now - t < window] + [now]
        if len(crashes) > restarts:
            print(f'android worker: exited {child.returncode}; {len(crashes)} times in {int(window)} s, '
                  'so it is left stopped. Fix what the log above says, then run Pantheon again.', flush=True)
            layout.worker.unlink(missing_ok=True)
            return 1
        delay = min(60, 2 ** len(crashes))
        print(f'android worker: exited {child.returncode}; starting it again in {delay} s', flush=True)
        for _ in range(delay * 2):
            if stopping['now'] or layout.stop_file.exists():
                layout.worker.unlink(missing_ok=True)
                return 0
            time.sleep(0.5)


# ── the app's side ────────────────────────────────────────────────────────────

def app_env(app: str, config: dict) -> dict[str, str]:
    token = Path(config['token_file'])
    env = {'PANTHEON_ANDROID_URL': config['app_url']}
    if app == 'native':
        env['PANTHEON_ANDROID_TOKEN_FILE'] = str(token)
    else:
        env['PANTHEON_ANDROID_PAIRING_DIR'] = str(token.parent)
    return env


def render_env(env: dict[str, str], style: str) -> str:
    if style == 'sh':
        return ''.join(f'export {k}={shlex.quote(v)}\n' for k, v in env.items())
    if style == 'powershell':
        return ''.join(f"$env:{k} = '{v.replace(chr(39), chr(39) * 2)}'\n" for k, v in env.items())
    return ''.join(f'{k}={v}\n' for k, v in env.items())


def dotenv(path: Path) -> dict[str, str]:
    out = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            out[key.strip()] = value.split(' #', 1)[0].strip().strip('"').strip("'")
    except OSError:
        pass  # no readable .env: Compose itself then uses its defaults, so this does too
    return out


def compose_env(env: dict[str, str], *, base: dict[str, str] | None = None) -> dict[str, str]:
    """The environment `docker compose` runs with: the app wired to the worker,
    and `docker/android-host.yml` added to whatever COMPOSE_FILE already says."""
    base = dict(os.environ if base is None else base)
    file_env = dotenv(REPO / '.env')
    separator = base.get('COMPOSE_PATH_SEPARATOR') or file_env.get('COMPOSE_PATH_SEPARATOR') or os.pathsep
    files = (base.get('COMPOSE_FILE') or file_env.get('COMPOSE_FILE') or 'docker-compose.yml').split(separator)
    overlay = 'docker/android-host.yml'
    if not any(Path(f).as_posix().endswith(overlay) for f in files):
        files.append(overlay)
    return {**base, **env, 'COMPOSE_FILE': separator.join(files), 'COMPOSE_PATH_SEPARATOR': separator}


def check_puid(*, environ=None) -> None:
    """Linux: the app reads the mode-600 pairing token as PUID, so PUID must be
    the worker's own uid. Docker Desktop's file sharing does not map owners."""
    if platform.system() != 'Linux' or not hasattr(os, 'getuid'):
        return
    environ = os.environ if environ is None else environ
    puid = environ.get('PUID') or dotenv(REPO / '.env').get('PUID') or '1000'
    if puid.strip() != str(os.getuid()):
        raise BootstrapError(f'The app runs as PUID {puid}, and the Android worker as uid {os.getuid()}; the app '
                             f'could not read the pairing token. Set PUID={os.getuid()} in .env (and PGID to your '
                             'group), then run this again.')


# ── commands ──────────────────────────────────────────────────────────────────

def up(args) -> int:
    check_python()
    layout = Layout(args.state, args.sdk)
    host = host_key()
    abi = native_abi()
    layout.state.mkdir(parents=True, exist_ok=True, mode=0o700)
    accept = {i.strip() for i in os.environ.get(ACCEPT_ENV, '').split(',') if i.strip()}
    if args.accept_sdk_license:
        accept.add(SDK_LICENSE)
    if args.accept_arm_license:
        accept.add(ARM_LICENSE)
    catalogue = Catalogue(abi)
    interactive = sys.stdin is not None and sys.stdin.isatty() and not args.no_prompt
    ensure_consent(layout, abi, catalogue, accept=accept, interactive=interactive,
                   show=lambda text: print(text, file=sys.stderr))
    changed = False
    needs_sdk = [n for n in ('emulator', 'platform-tools') if installed_revision(layout.sdk, n)[0] != load_pins()[n]['revision']]
    if needs_sdk or not layout.netsimd.exists():
        probe = layout.sdk if layout.sdk.exists() else layout.sdk.parent
        probe.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(probe).free < FREE_BYTES:
            raise BootstrapError(f'Android needs about {FREE_BYTES >> 30} GiB free at {probe} for the emulator and '
                                 f'one Android image; there are {shutil.disk_usage(probe).free >> 30} GiB.')
        if needs_sdk and read_worker(layout):
            stop_worker(layout)
    changed |= ensure_venv(layout)
    for name in ('emulator', 'platform-tools'):
        changed |= ensure_package(layout, name, host, catalogue)
    accel = check_acceleration(layout)
    say(f'hardware acceleration: {accel}')
    changed |= ensure_netsimd(layout, host, catalogue)
    changed |= ensure_scrcpy(layout)
    changed |= ensure_radio_image()
    console = ensure_windows_console_token()
    port = args.port
    if not port and layout.config_file.exists():
        port = json.loads(layout.config_file.read_text()).get('port')
    port = port or DEFAULT_PORT
    bind, app_url = endpoint(args.app, port)
    first = not layout.config_file.exists()
    before = config_digest(layout)
    config = configure(layout, bind=bind, app_url=app_url, port=port,
                       internet=(not args.no_internet) if (first or args.no_internet) else None,
                       console_token=console)
    if args.app == 'docker':
        check_puid()
    token = layout.token.read_text().strip()
    record = read_worker(layout)
    running = alive(record.get('supervisor'))
    current = running and health(config, token)
    if current and record.get('config_sha256') == config_digest(layout) and config_digest(layout) == before:
        say(f'worker already running at {config["bind"]}:{config["port"]}')
        answer = current
    else:
        if running or record:
            stop_worker(layout)
        say(f'starting the Android worker on {config["bind"]}:{config["port"]} (log: {layout.log})')
        supervisor = start_worker(layout)
        answer = wait_healthy(layout, config, token, supervisor)
    if answer.get('why'):
        raise BootstrapError('The Android worker is up but cannot run Android: ' + answer['why'], EXIT_ACCEL)
    env = app_env(args.app, config)
    write_private(layout.state / f'app-{args.app}.env', render_env(env, 'dotenv'))
    say(f'ready: {answer.get("accel") or accel} acceleration; the app reaches it at {config["app_url"]}'
        + (' (first launch installed what was missing)' if changed else ''))
    if args.print_env:
        sys.stdout.write(render_env(env, args.print_env))
        sys.stdout.flush()
    if args.compose is not None:
        result = subprocess.run(['docker', 'compose', *args.compose], cwd=str(REPO), env=compose_env(env))
        return result.returncode
    return 0


def down(args) -> int:
    layout = Layout(args.state, args.sdk)
    code = 0
    if args.compose is not None:
        config = json.loads(layout.config_file.read_text()) if layout.config_file.exists() else None
        env = app_env('docker', config) if config else {}
        if config is None:
            env['PANTHEON_ANDROID_PAIRING_DIR'] = str(layout.token.parent)
        code = subprocess.run(['docker', 'compose', *args.compose], cwd=str(REPO), env=compose_env(env)).returncode
    if not stop_worker(layout):
        say('no Android worker was running')
    return code


def status(args) -> int:
    layout = Layout(args.state, args.sdk)
    record = read_worker(layout)
    config = json.loads(layout.config_file.read_text()) if layout.config_file.exists() else None
    answer = health(config, layout.token.read_text().strip()) if config and layout.token.exists() else None
    print(json.dumps({'state': str(layout.state), 'sdk': str(layout.sdk), 'configured': config is not None,
                      'supervisor': record.get('supervisor') if alive(record.get('supervisor')) else None,
                      'healthy': bool(answer), 'accel': (answer or {}).get('accel'), 'why': (answer or {}).get('why'),
                      'packages': {n: installed_revision(layout.sdk, n)[0] for n in PACKAGE_DIRS}}, indent=2))
    return 0 if answer else 1


def pins(args) -> int:
    layout = Layout(args.state, args.sdk)
    recorded = json.loads(layout.pins.read_text()) if layout.pins.exists() else {}
    out = load_pins()
    for name, archives in recorded.items():
        for key, spec in archives.items():
            if spec.get('revision') == out[name]['revision']:
                out[name]['archives'][key] = {k: spec[k] for k in ('url', 'size', 'sha1', 'sha256') if k in spec}
    print(json.dumps(out, indent=2))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='python -m workstation.native_android.bootstrap',
                                     description=__doc__.split('\n\n')[0])
    parser.add_argument('--state', type=Path, default=None, help=f'Host state folder (default ~/.pantheon/android-host, or ${STATE_ENV}).')
    parser.add_argument('--sdk', type=Path, default=None, help=f'Private SDK folder (default <state>/sdk, or ${SDK_ENV}).')
    sub = parser.add_subparsers(dest='command', required=True)
    p_up = sub.add_parser('up', help='Install what is missing, pair, and start the worker.')
    p_up.add_argument('--app', choices=('native', 'docker'), default='docker',
                      help='Where the Pantheon app runs: on this host (native) or in Docker.')
    p_up.add_argument('--port', type=int)
    p_up.add_argument('--accept-sdk-license', action='store_true', help=f'I, the operator, accept {LICENSE_URL}.')
    p_up.add_argument('--accept-arm-license', action='store_true', help=f'I accept the ARM image terms in {ARM_LICENSE_URL}.')
    p_up.add_argument('--no-prompt', action='store_true', help='Never ask at the terminal.')
    p_up.add_argument('--no-internet', action='store_true', help='Give Android no application network.')
    p_up.add_argument('--print-env', choices=('sh', 'powershell', 'dotenv'), help='Print the app\'s environment to stdout.')
    p_up.add_argument('--compose', action='store_const', const=[], help='Then run docker compose with the arguments after it (last option).')
    p_down = sub.add_parser('down', help='Stop the worker (and its VMs).')
    p_down.add_argument('--compose', action='store_const', const=[], help='First run docker compose with the arguments after it (last option).')
    sub.add_parser('status', help='Say whether the worker is up.')
    sub.add_parser('pins', help='Print sdk-pins.json with the archives this host recorded.')
    sub.add_parser('supervise', help=argparse.SUPPRESS)
    argv = list(sys.argv[1:] if argv is None else argv)
    compose = None
    if '--compose' in argv:  # everything after it is docker compose's, `--` or not
        at = argv.index('--compose')
        argv, compose = argv[:at], argv[at + 1:]
        if compose[:1] == ['--']:
            compose = compose[1:]
    args = parser.parse_args(argv)
    if compose is not None:
        if args.command not in ('up', 'down'):
            parser.error('--compose goes with up or down')
        args.compose = compose
    args.state = args.state or default_state()
    os.umask(0o077)
    try:
        if args.command == 'supervise':
            return supervise(Layout(args.state, args.sdk))
        return {'up': up, 'down': down, 'status': status, 'pins': pins}[args.command](args)
    except BootstrapError as error:
        print('✗ Android: ' + error.message, file=sys.stderr, flush=True)
        return error.code
    except RuntimeError as error:  # check_python and native_abi say what to do themselves
        print('✗ Android: ' + str(error), file=sys.stderr, flush=True)
        return EXIT_FAILED


if __name__ == '__main__':
    sys.exit(main())
