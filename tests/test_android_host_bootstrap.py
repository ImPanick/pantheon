# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Android host bootstrap: what it installs, from where, and what it refuses.

Google's repository is replaced by a fake catalogue and fake archives served
through `urlopen`, so every check here runs offline.
"""
import hashlib
import io
import json
import os
import stat
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from workstation.native_android import bootstrap as B

LICENCE = 'Terms and Conditions\nThis is the Android Software Development Kit License Agreement.\n'
ARM_TEXT = 'ARM image terms.\n'
EMULATOR, PLATFORM_TOOLS = '37.2.13', '37.0.1'


def zip_of(files: dict[str, bytes], executable=()) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as package:
        for name, data in files.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = ((0o100755 if name in executable else 0o100644) << 16)
            package.writestr(info, data)
    return out.getvalue()


def emulator_zip(accel_ok=True, marker=b'') -> bytes:
    script = (b'#!/bin/sh\nif [ "$1" = "-accel-check" ]; then echo "accel:\n0\nKVM (version 12) is installed and usable."; exit 0; fi\n'
              if accel_ok else b'#!/bin/sh\necho "accel:\n9\n/dev/kvm is not found: VT disabled in BIOS or KVM kernel module not loaded"; exit 1\n')
    return zip_of({'emulator/emulator': script + marker, 'emulator/netsimd': b'NETSIM' + marker,
                   'emulator/source.properties': f'Pkg.Revision={EMULATOR}\n'.encode(),
                   'emulator/NOTICE.txt': b'notice', 'emulator/lib64/libx.so': b'lib'},
                  executable={'emulator/emulator', 'emulator/netsimd'})


def tools_zip() -> bytes:
    return zip_of({'platform-tools/adb': b'#!/bin/sh\n', 'platform-tools/source.properties':
                   f'Pkg.Revision={PLATFORM_TOOLS}\n'.encode()}, executable={'platform-tools/adb'})


class Repo:
    """A fake dl.google.com: the catalogue, the image catalogue and archives."""

    def __init__(self, archives=None, bad_sha1=()):
        self.files: dict[str, bytes] = {}
        self.calls: list[str] = []
        archives = archives or {
            ('emulator', EMULATOR): {('linux', 'x64'): emulator_zip(), ('macosx', 'aarch64'): emulator_zip(),
                                     ('windows', 'x64'): emulator_zip()},
            ('platform-tools', PLATFORM_TOOLS): {('linux', None): tools_zip(), ('macosx', None): tools_zip(),
                                                 ('windows', None): tools_zip()},
            ('emulator', '36.1.9'): {('linux', 'x64'): emulator_zip()},
        }
        packages = []
        for (path, revision), hosts in archives.items():
            parts = revision.split('.')
            items = []
            for (os_name, arch), data in hosts.items():
                name = f'{path}-{os_name}-{arch or "any"}-{revision}.zip'
                self.files[B.REPOSITORY + name] = data
                sha1 = '0' * 40 if name in bad_sha1 else hashlib.sha1(data).hexdigest()
                items.append(f'<archive><complete><size>{len(data)}</size><checksum type="sha1">{sha1}</checksum>'
                             f'<url>{name}</url></complete><host-os>{os_name}</host-os>'
                             + (f'<host-arch>{arch}</host-arch>' if arch else '') + '</archive>')
            packages.append(f'<remotePackage path="{path}"><revision><major>{parts[0]}</major><minor>{parts[1]}</minor>'
                            f'<micro>{parts[2]}</micro></revision><uses-license ref="android-sdk-license"/>'
                            f'<archives>{"".join(items)}</archives></remotePackage>')
        self.files[B.CATALOGUE] = (
            '<sdk:sdk-repository xmlns:sdk="http://schemas.android.com/sdk/android/repo/repository2/03">'
            f'<license id="android-sdk-license" type="text">{LICENCE}</license>{"".join(packages)}'
            '</sdk:sdk-repository>').encode()
        self.files[B.IMAGE_CATALOGUES['x86_64']] = (
            '<sys-img:sdk-sys-img xmlns:sys-img="http://schemas.android.com/sdk/android/repo/sys-img2/03">'
            f'<license id="android-sdk-arm-dbt-license" type="text">{ARM_TEXT}</license></sys-img:sdk-sys-img>').encode()
        pin = B.load_pins()['scrcpy-server']
        self.scrcpy = b'scrcpy'
        self.files[pin['url']] = self.scrcpy

    def urlopen(self, url, timeout=None):
        url = url if isinstance(url, str) else url.full_url
        self.calls.append(url)
        if url not in self.files:
            raise B.urllib.error.URLError('not found')
        return _Response(self.files[url])

    def downloads(self):
        return [c for c in self.calls if c.endswith('.zip')]


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


@pytest.fixture
def repo(monkeypatch):
    fake = Repo()
    monkeypatch.setattr(B.urllib.request, 'urlopen', fake.urlopen)
    monkeypatch.setattr(B, 'say', lambda text: None)
    return fake


@pytest.fixture
def layout(tmp_path):
    return B.Layout(tmp_path / 'state', tmp_path / 'sdk')


def accept(layout, abi='x86_64', catalogue=None):
    B.ensure_consent(layout, abi, catalogue or B.Catalogue(abi), accept=set(B.required_licenses(abi)), interactive=False)


# ── the catalogue ─────────────────────────────────────────────────────────────

def test_catalogue_picks_the_pinned_revision_for_this_host(repo):
    tree = B.ET.fromstring(repo.files[B.CATALOGUE])
    spec, _ = B.catalogue_archive(tree, 'emulator', EMULATOR, ('macosx', 'aarch64'))
    assert spec['url'].endswith('emulator-macosx-aarch64-37.2.13.zip') and spec['license'] == 'android-sdk-license'
    any_arch, _ = B.catalogue_archive(tree, 'platform-tools', PLATFORM_TOOLS, ('windows', 'x64'))
    assert any_arch['url'].endswith('platform-tools-windows-any-37.0.1.zip')
    missing, offered = B.catalogue_archive(tree, 'emulator', EMULATOR, ('macosx', 'x64'))
    assert missing is None and EMULATOR in offered


def test_a_pinned_revision_google_no_longer_offers_is_named(repo, layout, monkeypatch):
    monkeypatch.setattr(B, 'load_pins', lambda: {**json.loads(B.PINS.read_text()),
                                                 'emulator': {'revision': '99.0.0', 'archives': {}}})
    with pytest.raises(B.BootstrapError, match='does not offer emulator 99.0.0 for linux-x64'):
        B.resolve_archive(layout, 'emulator', ('linux', 'x64'), B.Catalogue('x86_64'))


def test_downloads_only_from_official_sources(repo, tmp_path):
    with pytest.raises(B.BootstrapError, match='not an official source'):
        B.download('https://example.com/emulator.zip', tmp_path, size=1, sha1=None, sha256=None, label='x')
    with pytest.raises(B.BootstrapError, match='not an official source'):
        B.fetch('https://dl.google.com.evil.example/android/repository/x.xml')


# ── consent ───────────────────────────────────────────────────────────────────

def test_without_a_terminal_or_a_flag_nothing_is_accepted_or_fetched(repo, layout):
    with pytest.raises(B.BootstrapError) as error:
        B.ensure_consent(layout, 'x86_64', B.Catalogue('x86_64'), accept=set(), interactive=False)
    assert error.value.code == B.EXIT_CONSENT and '--accept-sdk-license' in error.value.message
    assert repo.calls == [] and not (layout.state / 'license-consent.json').exists()


def test_apple_silicon_needs_the_arm_image_agreement_too(repo, layout):
    with pytest.raises(B.BootstrapError, match='--accept-arm-license'):
        B.ensure_consent(layout, 'arm64-v8a', B.Catalogue('arm64-v8a'), accept={B.SDK_LICENSE}, interactive=False)
    accept(layout, 'arm64-v8a')
    assert json.loads((layout.state / 'license-consent.json').read_text())['license_ids'] == sorted(
        [B.SDK_LICENSE, B.ARM_LICENSE])
    assert (layout.sdk / 'licenses' / B.ARM_LICENSE).read_text().split() == [hashlib.sha1(ARM_TEXT.encode()).hexdigest()]


def test_the_operator_reads_the_text_and_types_yes(repo, layout):
    shown = []
    B.ensure_consent(layout, 'x86_64', B.Catalogue('x86_64'), accept=set(), interactive=True,
                     ask=lambda prompt: 'yes\n', show=shown.append)
    assert any('Android Software Development Kit License Agreement' in s for s in shown)
    record = json.loads((layout.state / 'license-consent.json').read_text())
    assert record['source'] == 'Operator prompt at the Pantheon launcher'
    assert record['license_text_sha256'][B.SDK_LICENSE] == hashlib.sha256(LICENCE.encode()).hexdigest()
    # The same file `sdkmanager --licenses` writes, which images.py checks.
    assert (layout.sdk / 'licenses' / B.SDK_LICENSE).read_text().split() == [hashlib.sha1(LICENCE.encode()).hexdigest()]


@pytest.mark.parametrize('answer', ['', 'no\n', 'sure\n'])
def test_anything_but_yes_is_a_no(repo, layout, answer):
    with pytest.raises(B.BootstrapError) as error:
        B.ensure_consent(layout, 'x86_64', B.Catalogue('x86_64'), accept=set(), interactive=True,
                         ask=lambda prompt: answer, show=lambda text: None)
    assert error.value.code == B.EXIT_CONSENT and not (layout.state / 'license-consent.json').exists()


def test_an_earlier_acceptance_is_not_asked_again(repo, layout):
    accept(layout)
    repo.calls.clear()
    B.ensure_consent(layout, 'x86_64', B.Catalogue('x86_64'), accept=set(), interactive=False)
    assert repo.calls == []


# ── SDK packages ──────────────────────────────────────────────────────────────

def test_installs_checks_and_records_then_does_nothing_the_second_time(repo, layout):
    catalogue = B.Catalogue('x86_64')
    host = ('linux', 'x64')
    assert B.ensure_package(layout, 'emulator', host, catalogue)
    assert B.ensure_package(layout, 'platform-tools', host, catalogue)
    emulator = layout.sdk / 'emulator' / 'emulator'
    assert emulator.stat().st_mode & stat.S_IXUSR and (layout.sdk / 'platform-tools' / 'adb').is_file()
    recorded = json.loads(layout.pins.read_text())['emulator']['linux-x64']
    assert recorded['sha256'] == hashlib.sha256(repo.files[recorded['url']]).hexdigest()
    assert not [p for p in layout.sdk.iterdir() if p.name.startswith('.install-')]
    repo.calls.clear()
    assert not B.ensure_package(layout, 'emulator', host, catalogue)
    assert not B.ensure_package(layout, 'platform-tools', host, catalogue)
    assert repo.calls == []


def test_an_archive_that_does_not_match_googles_catalogue_is_refused(monkeypatch, layout):
    fake = Repo(bad_sha1={'emulator-linux-x64-37.2.13.zip'})
    monkeypatch.setattr(B.urllib.request, 'urlopen', fake.urlopen)
    monkeypatch.setattr(B, 'say', lambda text: None)
    with pytest.raises(B.BootstrapError, match='SHA-1'):
        B.ensure_package(layout, 'emulator', ('linux', 'x64'), B.Catalogue('x86_64'))
    assert not (layout.sdk / 'emulator').exists()


def test_a_reinstall_must_match_the_sha256_recorded_the_first_time(repo, layout):
    host = ('linux', 'x64')
    B.ensure_package(layout, 'emulator', host, B.Catalogue('x86_64'))
    url = json.loads(layout.pins.read_text())['emulator']['linux-x64']['url']
    repo.files[url] = repo.files[url]  # same bytes: fine
    B.shutil.rmtree(layout.sdk / 'emulator')
    B.ensure_package(layout, 'emulator', host, B.Catalogue('x86_64'))
    # Google now serves different bytes under the same name and catalogue entry.
    swapped = emulator_zip(marker=b'#changed')
    repo.files[url] = swapped
    records = json.loads(layout.pins.read_text())
    records['emulator']['linux-x64'].update(size=len(swapped), sha1=hashlib.sha1(swapped).hexdigest())
    layout.pins.write_text(json.dumps(records))
    B.shutil.rmtree(layout.sdk / 'emulator')
    with pytest.raises(B.BootstrapError, match='pinned SHA-256'):
        B.ensure_package(layout, 'emulator', host, B.Catalogue('x86_64'))


def test_a_repository_pin_wins_and_must_agree_with_the_host_record(repo, layout, monkeypatch):
    pins = json.loads(B.PINS.read_text())
    url = B.REPOSITORY + 'emulator-linux-x64-37.2.13.zip'
    data = repo.files[url]
    pins['emulator']['archives']['linux-x64'] = {'url': url, 'size': len(data), 'sha1': hashlib.sha1(data).hexdigest(),
                                                 'sha256': hashlib.sha256(data).hexdigest()}
    monkeypatch.setattr(B, 'load_pins', lambda: pins)
    B.ensure_package(layout, 'emulator', ('linux', 'x64'), B.Catalogue('x86_64'))
    assert B.CATALOGUE not in repo.calls  # pinned: the catalogue was not needed
    pins['emulator']['archives']['linux-x64']['sha256'] = '0' * 64
    with pytest.raises(B.BootstrapError, match='does not match the SHA-256 pinned in the repository'):
        B.resolve_archive(layout, 'emulator', ('linux', 'x64'), B.Catalogue('x86_64'))


def test_an_sdk_pantheon_did_not_install_is_used_only_at_the_pinned_revision(repo, layout):
    folder = layout.sdk / 'emulator'
    folder.mkdir(parents=True)
    (folder / 'source.properties').write_text(f'Pkg.Revision={EMULATOR}\n')
    assert not B.ensure_package(layout, 'emulator', ('linux', 'x64'), B.Catalogue('x86_64'))
    (folder / 'source.properties').write_text('Pkg.Revision=35.1.4\n')
    with pytest.raises(B.BootstrapError, match='Pantheon did not install .*revision 35.1.4'):
        B.ensure_package(layout, 'emulator', ('linux', 'x64'), B.Catalogue('x86_64'))
    assert (folder / 'source.properties').exists()  # left alone


def test_a_mac_gets_linux_netsimd_from_the_linux_emulator_archive(repo, layout):
    assert B.ensure_netsimd(layout, ('macosx', 'aarch64'), B.Catalogue('arm64-v8a'))
    assert layout.netsimd.read_bytes() == b'NETSIM' and layout.netsimd.stat().st_mode & stat.S_IXUSR
    assert sorted(p.name for p in layout.radio.iterdir()) == sorted([B.MARKER, 'NOTICE.txt', 'netsimd'])
    assert repo.downloads() == [B.REPOSITORY + 'emulator-linux-x64-37.2.13.zip']
    repo.calls.clear()
    assert not B.ensure_netsimd(layout, ('macosx', 'aarch64'), B.Catalogue('arm64-v8a'))
    assert repo.calls == []


def test_linux_copies_netsimd_from_its_own_emulator(repo, layout):
    B.ensure_package(layout, 'emulator', ('linux', 'x64'), B.Catalogue('x86_64'))
    repo.calls.clear()
    assert B.ensure_netsimd(layout, ('linux', 'x64'), B.Catalogue('x86_64'))
    assert layout.netsimd.read_bytes() == b'NETSIM' and repo.calls == []


def test_scrcpy_server_must_match_its_pinned_sha256(repo, layout, monkeypatch):
    layout.state.mkdir(parents=True)
    pins = json.loads(B.PINS.read_text())
    pins['scrcpy-server']['sha256'] = hashlib.sha256(repo.scrcpy).hexdigest()
    monkeypatch.setattr(B, 'load_pins', lambda: pins)
    assert B.ensure_scrcpy(layout) and not B.ensure_scrcpy(layout)
    pins['scrcpy-server']['sha256'] = '1' * 64
    layout.scrcpy.unlink()
    with pytest.raises(B.BootstrapError, match='pinned SHA-256'):
        B.ensure_scrcpy(layout)
    assert not layout.scrcpy.exists()


# ── acceleration ──────────────────────────────────────────────────────────────

def test_no_acceleration_stops_before_the_worker_with_what_to_change(repo, layout, monkeypatch):
    monkeypatch.setattr(B.platform, 'system', lambda: 'Windows')
    run = lambda *a, **k: SimpleNamespace(returncode=1, stdout='WHPX is not installed', stderr='')
    with pytest.raises(B.BootstrapError) as error:
        B.check_acceleration(layout, run=run)
    assert error.value.code == B.EXIT_ACCEL and 'Windows Hypervisor Platform' in error.value.message
    ok = lambda *a, **k: SimpleNamespace(returncode=0, stdout='Hypervisor.Framework OS X Version 15.1', stderr='')
    assert B.check_acceleration(layout, run=ok) == 'hvf'


def test_linux_advice_names_the_kvm_group_or_missing_device(monkeypatch):
    monkeypatch.setattr(B.os.path, 'exists', lambda path: path != '/dev/kvm')
    assert 'no /dev/kvm' in B.acceleration_advice('Linux', '')
    monkeypatch.setattr(B.os.path, 'exists', lambda path: True)
    monkeypatch.setattr(B.os, 'access', lambda path, mode: False)
    assert 'usermod -aG kvm' in B.acceleration_advice('Linux', '')


# ── Docker ────────────────────────────────────────────────────────────────────

class Docker:
    def __init__(self, ostype='linux', label=None):
        self.ostype, self.label, self.commands = ostype, label, []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        verb = command[1]
        if verb == 'info':
            return SimpleNamespace(returncode=0 if self.ostype else 1, stdout=(self.ostype or '') + '\n', stderr='')
        if verb == 'image':
            return SimpleNamespace(returncode=0 if self.label else 1, stdout=(self.label or '') + '\n', stderr='')
        if verb == 'build':
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if verb == 'network':
            return SimpleNamespace(returncode=0, stdout='172.17.0.1 ', stderr='')
        raise AssertionError(command)


def test_the_radio_image_is_built_once_per_source_change():
    fresh = Docker()
    assert B.ensure_radio_image(run=fresh)
    build = fresh.commands[-1]
    assert build[:4] == ['docker', 'build', '--platform', 'linux/amd64'] and B.RADIO_IMAGE in build
    assert f'{B.RADIO_LABEL}={B.radio_source_hash()}' in build
    current = Docker(label=B.radio_source_hash())
    assert not B.ensure_radio_image(run=current) and not any(c[1] == 'build' for c in current.commands)
    stale = Docker(label='old')
    assert B.ensure_radio_image(run=stale)


@pytest.mark.parametrize('ostype', [None, 'windows'])
def test_no_linux_docker_is_a_clear_stop(ostype):
    with pytest.raises(B.BootstrapError) as error:
        B.ensure_radio_image(run=Docker(ostype=ostype))
    assert error.value.code == B.EXIT_DOCKER


def test_no_docker_command_is_a_clear_stop():
    def missing(*a, **k):
        raise FileNotFoundError('docker')
    with pytest.raises(B.BootstrapError, match='no `docker` command') as error:
        B.ensure_radio_image(run=missing)
    assert error.value.code == B.EXIT_DOCKER


# ── wiring the app ────────────────────────────────────────────────────────────

@pytest.mark.parametrize('system,app,bind,url', [
    ('Darwin', 'native', '127.0.0.1', 'http://127.0.0.1:7993'),
    ('Darwin', 'docker', '127.0.0.1', 'http://host.docker.internal:7993'),
    ('Windows', 'docker', '127.0.0.1', 'http://host.docker.internal:7993'),
    ('Linux', 'native', '127.0.0.1', 'http://127.0.0.1:7993'),
    ('Linux', 'docker', '172.17.0.1', 'http://host.docker.internal:7993'),
])
def test_where_the_worker_listens_and_the_app_reaches_it(monkeypatch, system, app, bind, url):
    monkeypatch.setattr(B.platform, 'system', lambda: system)
    assert B.endpoint(app, 7993, gateway=lambda: '172.17.0.1') == (bind, url)


def test_the_bridge_gateway_comes_from_docker():
    assert B.docker_bridge_gateway(run=Docker()) == '172.17.0.1'


def test_app_environment_for_each_mode_and_shell():
    config = {'app_url': 'http://127.0.0.1:7993', 'token_file': "/home/o'neil/.pantheon/android-host/pairing/token"}
    native = B.app_env('native', config)
    assert native == {'PANTHEON_ANDROID_URL': 'http://127.0.0.1:7993',
                      'PANTHEON_ANDROID_TOKEN_FILE': config['token_file']}
    assert B.app_env('docker', config)['PANTHEON_ANDROID_PAIRING_DIR'] == "/home/o'neil/.pantheon/android-host/pairing"
    assert "export PANTHEON_ANDROID_TOKEN_FILE='/home/o'\"'\"'neil" in B.render_env(native, 'sh')
    assert "$env:PANTHEON_ANDROID_TOKEN_FILE = '/home/o''neil" in B.render_env(native, 'powershell')


def test_compose_gets_the_android_overlay_once(monkeypatch, tmp_path):
    monkeypatch.setattr(B, 'REPO', tmp_path)
    env = B.compose_env({'PANTHEON_ANDROID_URL': 'u'}, base={})
    assert env['COMPOSE_FILE'].split(os.pathsep) == ['docker-compose.yml', 'docker/android-host.yml']
    again = B.compose_env({}, base={'COMPOSE_FILE': 'docker-compose.yml:docker/gpu.yml:docker/android-host.yml',
                                   'COMPOSE_PATH_SEPARATOR': ':'})
    assert again['COMPOSE_FILE'] == 'docker-compose.yml:docker/gpu.yml:docker/android-host.yml'
    (tmp_path / '.env').write_text('COMPOSE_FILE=docker-compose.yml;docker/gpu.yml\nCOMPOSE_PATH_SEPARATOR=;\n')
    from_file = B.compose_env({}, base={})
    assert from_file['COMPOSE_FILE'] == 'docker-compose.yml;docker/gpu.yml;docker/android-host.yml'


@pytest.mark.skipif(not hasattr(os, 'getuid'), reason='POSIX uid')
def test_linux_app_must_run_as_the_workers_uid(monkeypatch, tmp_path):
    monkeypatch.setattr(B, 'REPO', tmp_path)
    monkeypatch.setattr(B.platform, 'system', lambda: 'Linux')
    B.check_puid(environ={'PUID': str(os.getuid())})
    with pytest.raises(B.BootstrapError, match=f'Set PUID={os.getuid()}'):
        B.check_puid(environ={'PUID': str(os.getuid() + 1)})


# ── the command line ──────────────────────────────────────────────────────────

def test_up_without_consent_exits_3_and_says_how(repo, tmp_path, capsys, monkeypatch):
    monkeypatch.delenv(B.ACCEPT_ENV, raising=False)
    monkeypatch.setattr(B, 'host_key', lambda: ('linux', 'x64'))
    monkeypatch.setattr(B, 'native_abi', lambda: 'x86_64')
    monkeypatch.setattr(B.sys, 'stdin', io.StringIO())
    code = B.main(['--state', str(tmp_path / 's'), 'up', '--app', 'native'])
    assert code == B.EXIT_CONSENT
    assert 'https://developer.android.com/studio/terms' in capsys.readouterr().err
    assert repo.calls == []


def test_compose_arguments_after_the_separator(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(B, 'down', lambda args: seen.setdefault('compose', args.compose) and 0)
    B.main(['--state', str(tmp_path), 'down', '--compose', '--', 'down', '--remove-orphans'])
    assert seen['compose'] == ['down', '--remove-orphans']


def test_pins_prints_what_this_host_recorded_in_the_repository_shape(repo, layout, capsys):
    B.ensure_package(layout, 'emulator', ('linux', 'x64'), B.Catalogue('x86_64'))
    B.main(['--state', str(layout.state), '--sdk', str(layout.sdk), 'pins'])
    printed = json.loads(capsys.readouterr().out)
    entry = printed['emulator']['archives']['linux-x64']
    assert entry['url'].startswith(B.REPOSITORY) and len(entry['sha256']) == 64 and 'revision' not in entry


def test_bootstrap_imports_nothing_outside_the_standard_library():
    import subprocess
    import sys
    root = Path(__file__).resolve().parent.parent
    code = ('import sys; sys.path.insert(0, %r); import workstation.native_android.bootstrap; '
            'bad=[m for m in sys.modules if m.split(".")[0] in ("psutil","PIL","cryptography","lz4","src")]; '
            'print(bad); sys.exit(1 if bad else 0)') % str(root)
    assert subprocess.run([sys.executable, '-I', '-c', code]).returncode == 0
