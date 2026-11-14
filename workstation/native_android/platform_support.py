# SPDX-License-Identifier: AGPL-3.0-or-later
"""Native SDK profile conventions that environment overrides cannot change."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import platform
import re
import secrets
import subprocess
import sys


def check_python():
    # These releases added Windows' user/Administrators ACL for mkdir(0700).
    version = sys.version_info[:3]
    if platform.system() == 'Windows' and not (
        version >= (3, 13, 0) or (3, 12, 4) <= version < (3, 13, 0)
        or (3, 11, 10) <= version < (3, 12, 0)
    ):
        raise RuntimeError('Windows Android hosting requires Python 3.11.10+, 3.12.4+, or 3.13+ for private state directories.')


def windows_profile():
    # Match the SDK's System::getHomeDirectory, not the overridden USERPROFILE.
    import ctypes
    from ctypes import wintypes
    function = ctypes.WinDLL('shell32', use_last_error=True).SHGetFolderPathW
    function.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.HANDLE,
                         wintypes.DWORD, wintypes.LPWSTR]
    function.restype = ctypes.c_long
    value = ctypes.create_unicode_buffer(260)
    if function(None, 0x28, None, 0, value) != 0 or not value.value:
        raise RuntimeError('Cannot locate the Windows Android worker profile.')
    return Path(value.value)


def console_path(config, owner_home):
    if platform.system() != 'Windows':
        return Path(owner_home) / '.emulator_console_auth_token'
    selected = config.get('windows_console_token')
    if not selected:
        raise RuntimeError('Windows requires an explicit --windows-console-token from the dedicated worker profile.')
    expected = windows_profile() / '.emulator_console_auth_token'
    path = Path(selected)
    if path.resolve() != expected.resolve():
        raise RuntimeError('The console token must belong to the actual Windows profile running the Android worker.')
    try:
        token = path.read_text(encoding='ascii').strip()
    except (OSError, UnicodeError) as error:
        raise RuntimeError('The Windows worker console token must already exist and be readable.') from error
    if not token:
        raise RuntimeError('The Windows worker console token is empty; emulator authentication must stay enabled.')
    if not re.fullmatch(r'[A-Za-z0-9_+/=-]{16,256}', token):
        raise RuntimeError('The Windows worker console token has an invalid format.')
    return path


def native_abi():
    """Native CPU, including translated Python; only stock SDK host targets."""
    system = platform.system()
    cpu = os.environ.get('PROCESSOR_ARCHITEW6432', platform.machine()).lower() if system == 'Windows' else platform.machine().lower()
    if system == 'Darwin':
        try:
            probe = subprocess.run(['/usr/sbin/sysctl', '-n', 'hw.optional.arm64'], capture_output=True, text=True, timeout=5)
            if probe.returncode == 0 and probe.stdout.strip() == '1': cpu = 'arm64'
        except (OSError, subprocess.TimeoutExpired): pass  # no sysctl answer: keep platform.machine(), which is right outside Rosetta
    if system == 'Darwin' and cpu in ('arm64', 'aarch64'): return 'arm64-v8a'
    if system in ('Darwin', 'Windows', 'Linux') and cpu in ('amd64', 'x86_64'): return 'x86_64'
    raise RuntimeError('The stock SDK has no local emulator for this OS/CPU. Connect Pantheon to a compatible Android worker.')


def write_private(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.new-' + secrets.token_hex(4))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


SDK_LICENSE='android-sdk-license'
ARM_LICENSE='android-sdk-arm-dbt-license'


def required_licenses(abi):
    return [SDK_LICENSE]+([ARM_LICENSE] if abi=='arm64-v8a' else [])


def record_consent(root,license_ids,*,source,texts=None):
    """The operator's acceptance, kept beside the host's state. Earlier
    acceptances are kept; `texts` maps an id to the SHA-256 of the exact
    agreement text that was shown."""
    consent=Path(root)/'license-consent.json'
    old=json.loads(consent.read_text()) if consent.exists() else {}
    ids=sorted(set(old.get('license_ids',[]))|set(license_ids))
    shown=dict(old.get('license_text_sha256',{}));shown.update(texts or {})
    record={'accepted_at':old.get('accepted_at') or datetime.now(timezone.utc).isoformat(),'license_ids':ids,
            'scope':'Installed SDK and selected development images on this private Android host','source':source}
    if shown:record['license_text_sha256']=shown
    if set(ids)!=set(old.get('license_ids',[])) and old:record['updated_at']=datetime.now(timezone.utc).isoformat()
    write_private(consent,json.dumps(record,indent=2))
    return consent


def accepted(root,abi):
    consent=Path(root)/'license-consent.json'
    try:ids=set(json.loads(consent.read_text())['license_ids'])
    except (OSError,ValueError,KeyError,TypeError):return False
    return set(required_licenses(abi))<=ids


def accelerator_name(output):
    value = output.lower()
    for needles, name in ((('hypervisor.framework', 'hvf'), 'hvf'), (('whpx',), 'whpx'),
                          (('aehd', 'gvm'), 'aehd'), (('kvm',), 'kvm'), (('haxm',), 'haxm')):
        if any(word in value for word in needles): return name
    return 'sdk'  # successful SDK probe, unknown accelerator label
