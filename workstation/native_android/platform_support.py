# SPDX-License-Identifier: AGPL-3.0-or-later
"""Native SDK profile conventions that environment overrides cannot change."""
from pathlib import Path
import platform
import re
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
