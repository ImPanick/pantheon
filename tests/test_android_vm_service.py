# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Android VM service: each person's phone as its own VM, beside the desktop.

The owner (2026-11-16): the host is layer 0, Pantheon and its services are
layer 1, and each family of VMs is a container of its own: "Another
independent docker service - because we can control host allocation per
machine a little easier than just having one bundled VM container running tons
of VM's, and this also allows for further control, being able to restart single
components of pantheon without interrupting workflows in Linux VM's."

These pin what that means: `android-vm` is its own compose service, Pantheon
reaches phones there and nowhere else, the service keeps its own pool, its
radio needs no Docker socket, and Google's licence is accepted by an admin at
a terminal before anything of Google's is downloaded.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import sys
import textwrap
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from workstation import protocol as P
from workstation.native_android import radio as R
from workstation.native_android import service as S

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = 'pw-panick-ce7e0193'


def compose(*files):
    merged = {}
    for name in files or ('docker-compose.yml',):
        data = yaml.safe_load((ROOT / name).read_text())
        for service, body in (data.get('services') or {}).items():
            merged.setdefault(service, {}).update(body)
    return merged


def env_of(service):
    out = {}
    for item in service.get('environment') or []:
        key, _, value = item.partition('=')
        out[key] = value
    return out


# ── its own service, beside the Linux VMs ─────────────────────────────────────

def test_android_runs_in_its_own_service_beside_the_linux_vms():
    services = compose()
    android, linux = services['android-vm'], services['workstation-vm']
    assert android['build']['dockerfile'] == 'android-vm.Dockerfile'
    assert android['build']['dockerfile'] != linux['build']['dockerfile']
    volumes = set(android['volumes'])
    assert 'android-vm:/var/lib/pantheon-android' in volumes
    assert not volumes & set(linux['volumes']), 'the two VM services share no volume'
    # Restarting one never takes the other with it.
    assert 'android-vm' not in (linux.get('depends_on') or {})
    assert 'workstation-vm' not in (android.get('depends_on') or {})
    assert 'android-vm' not in (services['pantheon'].get('depends_on') or {})


def test_the_android_service_is_not_privileged_and_has_no_docker_socket():
    android = compose()['android-vm']
    assert not android.get('privileged')
    assert android.get('cap_add') == ['NET_ADMIN']
    assert android['device_cgroup_rules'] == ['c 10:232 rwm']
    assert not any('docker.sock' in str(v) for v in android['volumes'])
    assert 'ports' not in android


def test_pantheon_reaches_phones_on_the_android_service():
    pantheon = compose()['pantheon']
    env = env_of(pantheon)
    assert env['PANTHEON_ANDROID_URL'] == '${PANTHEON_ANDROID_URL:-http://android-vm:7993}'
    assert env['PANTHEON_ANDROID_TOKEN_FILE'] == '/android-pairing/token'
    assert 'android-vm-pairing:/android-pairing:ro' in pantheon['volumes']


def test_the_host_worker_overlay_keeps_the_service_from_starting_too():
    overlay = yaml.safe_load((ROOT / 'docker/android-host.yml').read_text())['services']
    assert overlay['android-vm']['profiles'], 'one Android host answers for people, never two'


def test_the_service_has_its_own_pool_an_admin_sets():
    android = compose()['android-vm']
    env = env_of(android)
    for name in S.ENV.values():
        assert name in env
    assert str(android['cpus']).startswith('${PANTHEON_ANDROID_VM_SERVICE_CPUS')
    assert str(android['mem_limit']).startswith('${PANTHEON_ANDROID_VM_SERVICE_MEMORY')


def test_the_image_carries_nothing_of_googles():
    text = (ROOT / 'workstation/android-vm.Dockerfile').read_text()
    vm = (ROOT / 'workstation/vm.Dockerfile').read_text()
    base = next(line for line in text.splitlines() if line.startswith('FROM '))
    assert base in vm.splitlines(), 'the same pinned base as the Linux VM service'
    assert 'dl.google.com' not in text and 'sdkmanager' not in text
    assert '--require-hashes' in text
    assert 'workstation.native_android.service' in text


# ── the admin's pool ──────────────────────────────────────────────────────────

def test_settings_default_to_a_pool_sized_to_the_host():
    chosen = S.settings({}, total_mib=64 * 1024)
    assert chosen['cores'] == 4 and chosen['internet'] is True and chosen['gpu'] == 'software'
    assert 'memory_mib' not in chosen
    assert 1 <= chosen['max_running'] <= S.MAX_PHONES
    assert S.settings({}, total_mib=64 * 1024)['max_running'] > S.settings({}, total_mib=16 * 1024)['max_running']


def test_settings_take_the_admins_numbers():
    chosen = S.settings({S.ENV['max_running']: '3', S.ENV['memory_mib']: '6144', S.ENV['cores']: '2',
                         S.ENV['internet']: 'off'}, total_mib=8 * 1024)
    assert chosen == {'max_running': 3, 'memory_mib': 6144, 'cores': 2, 'internet': False, 'gpu': 'software'}


def test_auto_counts_each_phones_memory_and_its_overhead():
    chosen = S.settings({S.ENV['memory_mib']: '4096'}, total_mib=(4096 + S.PHONE_OVERHEAD_MIB) * 3)
    assert chosen['max_running'] == 3


@pytest.mark.parametrize('name,value', [('max_running', '0'), ('max_running', '99'), ('cores', 'many'),
                                        ('memory_mib', '512'), ('internet', 'maybe'), ('gpu', 'rtx')])
def test_settings_refuse_a_value_with_a_sentence(name, value):
    with pytest.raises(S.SettingsError) as caught:
        S.settings({S.ENV[name]: value}, total_mib=32 * 1024)
    assert S.ENV[name] in str(caught.value)


# ── start-up: KVM, then the kernel rules, for the service's account alone ─────

def test_the_kernel_rules_cover_the_service_account_and_are_read_back(monkeypatch):
    from workstation import phone as PH
    written = []
    monkeypatch.setattr(PH, 'kvm_for_accounts', lambda: (True, 'kvm'))
    monkeypatch.setattr(S.netrules, 'apply', written.append)
    monkeypatch.setattr(S.netrules, 'lan_resolvers', lambda: [])
    monkeypatch.setattr(S.netrules, 'in_force', lambda table: 'internet' if table == S.TABLE else None)
    assert S.harden() is None
    rules = written[0]
    assert f'meta skuid {S.SERVICE_UID}-{S.SERVICE_UID}' in rules
    assert 'network=internet' in rules and '@excluded4' in rules


def test_the_service_refuses_to_run_without_its_kernel_rules(monkeypatch):
    from workstation import phone as PH
    monkeypatch.setattr(PH, 'kvm_for_accounts', lambda: (True, 'kvm'))
    monkeypatch.setattr(S.netrules, 'apply', lambda text: None)
    monkeypatch.setattr(S.netrules, 'lan_resolvers', lambda: [])
    monkeypatch.setattr(S.netrules, 'in_force', lambda table: None)
    with pytest.raises(RuntimeError):
        S.harden()


def test_no_kvm_is_said_in_one_sentence(monkeypatch):
    from workstation import phone as PH
    monkeypatch.setattr(PH, 'kvm_for_accounts', lambda: (False, 'the host has no KVM'))
    monkeypatch.setattr(S.netrules, 'apply', lambda text: None)
    monkeypatch.setattr(S.netrules, 'lan_resolvers', lambda: [])
    monkeypatch.setattr(S.netrules, 'in_force', lambda table: 'internet')
    why = S.harden()
    assert 'no KVM' in why and 'WSL 2' in why


# ── before Android is installed: one sentence for every phone ─────────────────

@pytest.fixture
def waiting():
    station = S.WaitingStation('pws_' + 'a' * 40, S.NEEDS_LICENCE)
    server = S.waiting_server(station, '127.0.0.1', 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield station, 'http://127.0.0.1:%d' % server.server_address[1]
    server.shutdown()
    server.server_close()


def call(url, path, token, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url + path, data=data, method='POST' if data else 'GET',
                                     headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=5) as answer:
            return answer.status, json.load(answer)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def test_health_answers_and_says_why_there_is_no_android_yet(waiting):
    station, url = waiting
    status, answer = call(url, '/v1/health', station.token)
    assert status == 200 and answer['agent'] == P.AGENT_NAME and answer['backend'] == 'native_android'
    assert answer['why'] == S.NEEDS_LICENCE
    assert 'docker compose run --rm android-vm accept-license' in answer['why']


def test_every_phone_route_says_the_same_sentence_and_starts_nothing(waiting):
    station, url = waiting
    for path, body in ((f'/v1/users/{ACCOUNT}/phone', {'action': 'start', 'holder': 'person'}),
                       (f'/v1/users/{ACCOUNT}/control', {'holder': 'person'}),
                       (f'/v1/users/{ACCOUNT}/phone/choice', {'holder': 'person'})):
        status, answer = call(url, path, station.token, body)
        assert status >= 400
        assert answer['error'] == 'unavailable' and answer['message'] == S.NEEDS_LICENCE
    station.set_why(S.INSTALLING)
    status, answer = call(url, f'/v1/users/{ACCOUNT}/phone', station.token, {'action': 'status'})
    assert answer['message'] == S.INSTALLING


def test_the_waiting_service_still_wants_the_token(waiting):
    _, url = waiting
    status, answer = call(url, '/v1/health', 'pws_wrong')
    assert status == 401 and answer['error'] == 'unauthorized'


# ── the licence: accepted by an admin at a terminal, before any download ─────

def test_install_downloads_nothing_until_the_licence_is_accepted(tmp_path, monkeypatch):
    from workstation.native_android import bootstrap as B
    monkeypatch.setattr(B, 'fetch', lambda *a, **k: pytest.fail('fetched before the licence was accepted'))
    monkeypatch.setattr(B, 'download', lambda *a, **k: pytest.fail('downloaded before the licence was accepted'))
    monkeypatch.setenv(B.ACCEPT_ENV, 'android-sdk-license')
    with pytest.raises(B.BootstrapError) as caught:
        S.install(B.Layout(tmp_path), S.settings({}, total_mib=32 * 1024), token_file=tmp_path / 't',
                  bind='0.0.0.0', port=S.PORT)
    assert caught.value.message == S.NEEDS_LICENCE
    assert not (tmp_path / 'license-consent.json').exists()


def test_accepting_needs_a_terminal_and_records_nothing_without_one(tmp_path, monkeypatch, capsys):
    from workstation.native_android import bootstrap as B
    monkeypatch.setenv(S.STATE_ENV, str(tmp_path))
    monkeypatch.setattr(sys, 'stdin', open(os.devnull))
    assert S.accept_license(None) == B.EXIT_CONSENT
    assert 'docker compose run --rm android-vm accept-license' in capsys.readouterr().err
    assert not (tmp_path / 'license-consent.json').exists()


def test_the_service_reads_no_licence_from_its_environment():
    text = (ROOT / 'workstation/native_android/service.py').read_text()
    assert 'ACCEPT_ENV' not in text and 'PANTHEON_ANDROID_ACCEPT_LICENSES' not in text
    assert 'accept=set()' in text


# ── the radio, with no Docker socket ──────────────────────────────────────────

FAKE_NETSIM = textwrap.dedent('''\
    #!{python}
    import socket, sys, threading
    port = int(sys.argv[sys.argv.index('--grpc-port') + 1])
    server = socket.socket(); server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', port)); server.listen()
    def serve(conn):
        with conn:
            while True:
                block = conn.recv(65536)
                if not block:
                    return
                conn.sendall(b'netsim:' + block)
    while True:
        conn, _ = server.accept()
        threading.Thread(target=serve, args=(conn,), daemon=True).start()
    ''')


@pytest.fixture
def netsim(tmp_path):
    binary = tmp_path / 'netsimd'
    binary.write_text(FAKE_NETSIM.format(python=sys.executable))
    binary.chmod(0o755)
    return binary


def connect(radio, credential, target=R.TARGET):
    conn = socket.create_connection(('127.0.0.1', radio.port), 5)
    conn.sendall(f'CONNECT {target} HTTP/1.1\r\nProxy-Authorization: '.encode() + credential + b'\r\n\r\n')
    return conn


def test_each_phone_gets_its_own_netsim_process_behind_the_authenticated_proxy(tmp_path, netsim, monkeypatch):
    monkeypatch.setattr(R.PrivateRadio, 'docker', lambda *a, **k: pytest.fail('the service has no Docker'))
    radio = R.ProcessRadio(tmp_path / 'owner/radio', netsim)
    with radio:
        assert radio.report['transport'] == 'authenticated_private_process'
        assert radio.env['grpc_proxy'].endswith('@127.0.0.1:%d' % radio.port)
        conn = connect(radio, radio.credential)
        assert conn.recv(100).startswith(b'HTTP/1.1 200')
        conn.sendall(R.PREFACE)
        assert conn.recv(100) == b'netsim:' + R.PREFACE
        conn.close()
        assert radio.report['authorized_connections'] == 1
        process = radio.process
    assert radio.process is None and radio.report['owned_process_stopped'] is True
    assert process.poll() is not None, 'the phone stopping stops its Netsim'


@pytest.mark.parametrize('target,good_credential', [(R.TARGET, False), ('example.com:443', True)])
def test_the_proxy_refuses_a_stranger_or_another_target(tmp_path, netsim, target, good_credential):
    radio = R.ProcessRadio(tmp_path / 'owner/radio', netsim)
    with radio:
        credential = radio.credential if good_credential else b'Basic ' + base64.b64encode(b'radio:guess')
        conn = connect(radio, credential, target)
        assert conn.recv(100).startswith(b'HTTP/1.1 407')
        conn.close()
        assert radio.report['authorized_connections'] == 0


def test_two_phones_get_two_netsims_on_two_ports(tmp_path, netsim):
    with R.ProcessRadio(tmp_path / 'a/radio', netsim) as one, R.ProcessRadio(tmp_path / 'b/radio', netsim) as two:
        assert one.netsim_port != two.netsim_port and one.process.pid != two.process.pid
        assert one.secret != two.secret


def test_a_host_in_the_service_launches_phones_with_the_process_radio(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from workstation.native_android import host as H
    home = tmp_path / 'owner'
    (home / '.android').mkdir(parents=True)
    chosen = []

    class Launched(Exception):
        pass

    def radio(name):
        def made(*args, **kwargs):
            chosen.append(name)
            return SimpleNamespace(env={}, TARGET=R.TARGET, __enter__=lambda: None)
        return made
    monkeypatch.setattr(H, 'PrivateRadio', radio('docker'))
    monkeypatch.setattr(H, 'ProcessRadio', radio('process'))
    monkeypatch.setattr(H.subprocess, 'Popen', lambda args, **kwargs: (chosen.append(args), (_ for _ in ()).throw(Launched()))[1])
    for transport, cores in ((None, '4'), ('process', '2')):
        config = {'radio_binary': 'radio', 'scrcpy_server': 'control'}
        if transport:
            config.update(radio_transport=transport, cores=2)
        system = SimpleNamespace(config=config, sdk=tmp_path / 'sdk', emulator=tmp_path / 'sdk/emulator/emulator',
                                 abi='x86_64', why=None, home=lambda _: home)
        phone = H.NativePhone(system, ACCOUNT, None, claim_port=lambda _: 5586)
        phone.avd = 'owned-avd'
        monkeypatch.setattr(phone, '_write_avd', lambda: None)
        with pytest.raises(Launched):
            phone._launch_android()
        args = chosen[-1]
        assert args[args.index('-cores') + 1] == cores
    assert [c for c in chosen if isinstance(c, str)] == ['docker', 'process']
