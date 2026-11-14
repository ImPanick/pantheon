# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bounded, typed access to one Android shared-storage directory."""
import base64
import hashlib
import re
import secrets
import shlex
import tempfile
import time
from pathlib import Path

from workstation import protocol as P
LIMIT = P.MAX_FILE_BYTES
TOTAL = 128 << 20
COUNT = 64
DIRECTORY = '/sdcard/Download/PantheonUSB'


def filename(value):
    # A portable flat folder: no path separators, device names or case aliases.
    if (not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._()-]{0,139}',value)
            or value.endswith((' ','.')) or value.split('.')[0].upper() in
            {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(10)],*[f'LPT{i}' for i in range(10)]}):
        raise ValueError('USB filenames need 1–140 ASCII letters, numbers, spaces, dots, parentheses, underscores or dashes; no reserved device names.')
    return value


def digest(data):return hashlib.sha256(data).hexdigest()


def scan_media(call,path):
    """Notify MediaStore after a verified write; indexing is best effort.

    Android's MediaStore.scanFile uses this provider method (Android 35).
    Failure must not delete a file whose bytes were already confirmed.
    """
    from workstation.phone import PhoneError
    try:
        call(['shell','content call --uri content://media --method scan_file --arg '+shlex.quote(path)],timeout=5,quiet=True)
    except (PhoneError,OSError):pass  # the file is delivered; Android indexes it on its next media scan anyway


def operation(phone, op, connection=None, name=None, data_b64=None, expected=None, *, _deadline=None):
    from workstation.phone import PhoneError
    deadline = _deadline if _deadline is not None else time.monotonic() + 30
    def call(args, **kwargs):
        remaining = deadline - time.monotonic()
        if remaining <= 0:raise PhoneError('unavailable','USB operation timed out; device data was kept.')
        kwargs['timeout'] = min(remaining, kwargs.get('timeout', 20))
        return phone.adb(args, **kwargs)
    with phone.lock:
        phone._on()
        if phone.mode() != 'android':raise PhoneError('unavailable','USB storage needs Android.')
        identity=(phone.device,phone.edition,phone.emulator.pid)
        if op == 'connect':
            call(['shell','mkdir','-p',DIRECTORY])
            phone._usb_connection=(secrets.token_urlsafe(32),identity)
            return {'connection':phone._usb_connection[0], 'directory':DIRECTORY}
        active=getattr(phone,'_usb_connection',None)
        if not active or active!=(connection,identity):raise PhoneError('usb_ejected','USB was ejected or the Android device changed. Reconnect USB.')
        if op == 'eject':
            call(['shell','sync'],timeout=20)
            phone._usb_connection=None;return {'connected':False}
        if op not in ('list','read','write'):raise PhoneError('bad_request','Unknown USB operation.')
        def shell(command):return call(['shell',command],timeout=20)
        def current(path):
            q=shlex.quote(path)
            answer=shell(f'if [ -L {q} ]; then exit 1; elif [ -f {q} ]; then sha256sum {q}; elif [ -e {q} ]; then exit 1; else echo missing; fi').strip()
            if answer == 'missing':return None
            value=answer.split()[0]
            if not re.fullmatch('[a-f0-9]{64}',value):raise PhoneError('unavailable','Android returned an invalid USB checksum.')
            return value
        if op == 'list':
            raw=call(['exec-out',f'find {DIRECTORY} -mindepth 1 -maxdepth 1 -print0 | head -c 32769'],binary=True)
            if len(raw)>32768:raise PhoneError('unavailable','USB directory listing is too large.')
            result={};total=0;aliases=set()
            for path in raw.split(b'\0'):
                if not path:continue
                text=path.decode('utf-8',errors='strict')
                if not text.startswith(DIRECTORY+'/'):raise PhoneError('unavailable','Invalid USB listing.')
                item=text[len(DIRECTORY)+1:]
                if item.startswith('.usb-'):continue
                try:filename(item)
                except ValueError as e:raise PhoneError('bad_request',str(e)) from e
                if item.casefold() in aliases:raise PhoneError('bad_request','USB contains filenames differing only in case.')
                aliases.add(item.casefold())
                if len(result)>=COUNT:raise PhoneError('bad_request','USB supports at most 64 files in this folder.')
                q=shlex.quote(text)
                size=int(shell(f'test ! -L {q} && test -f {q} && stat -c %s {q}').strip())
                total+=size
                if not 0<=size<=LIMIT or total>TOTAL:raise PhoneError('bad_request','USB supports 20 MiB per file and 128 MiB total.')
                result[item]={'sha256':current(text),'bytes':size}
            return {'files':result}
        try:filename(name)
        except ValueError as e:raise PhoneError('bad_request',str(e)) from e
        path=DIRECTORY+'/'+name;q=shlex.quote(path)
        if op == 'read':
            shell(f'test ! -L {q} && test -f {q}')
            data=call(['exec-out',f'head -c {LIMIT+1} {q}'],binary=True)
            if len(data)>LIMIT:raise PhoneError('bad_request','USB file exceeds 20 MiB.')
            return {'data_b64':base64.b64encode(data).decode(), 'sha256':digest(data),'bytes':len(data)}
        if expected is not None and not (isinstance(expected,str) and re.fullmatch('[a-f0-9]{64}',expected)):
            raise PhoneError('bad_request','Invalid expected USB checksum.')
        if not isinstance(data_b64,str) or len(data_b64)>(LIMIT+2)//3*4:raise PhoneError('bad_request','USB file exceeds 20 MiB.')
        try:data=base64.b64decode(data_b64,validate=True)
        except ValueError:raise PhoneError('bad_request','Invalid USB bytes.') from None
        if len(data)>LIMIT:raise PhoneError('bad_request','USB file exceeds 20 MiB.')
        listing=operation(phone,'list',connection,_deadline=deadline)['files']
        aliases={n.casefold():n for n in listing}
        if name.casefold() in aliases and aliases[name.casefold()]!=name:
            raise PhoneError('bad_request','USB filenames must be unique without case differences.')
        if (name not in listing and len(listing)>=COUNT) or sum(v['bytes'] for v in listing.values())-listing.get(name,{}).get('bytes',0)+len(data)>TOTAL:
            raise PhoneError('bad_request','USB folder is full; no files were overwritten.')
        if current(path)!=expected:raise PhoneError('busy','USB file changed during synchronization; retrying without overwriting it.')
        stage=DIRECTORY+'/.usb-'+secrets.token_hex(12)
        committed=False
        try:
            with tempfile.TemporaryDirectory(prefix='usb-',dir=phone.home()) as tmp:
                source=Path(tmp)/'file';source.write_bytes(data)
                call(['push',str(source),stage],timeout=45)
            if current(stage)!=digest(data):raise PhoneError('unavailable','Android did not confirm USB file bytes.')
            if current(path)!=expected:raise PhoneError('busy','USB file changed during synchronization.')
            shell('mv -fT '+shlex.quote(stage)+' '+q)
            committed=True
            if current(path)!=digest(data):raise PhoneError('unavailable','Android did not confirm the committed USB file.')
            # ADB writes bypass MediaStore. Tell Android about the committed
            # file so Photos and system file pickers can discover it.
            scan_media(call,path)
            return {'sha256':digest(data),'bytes':len(data)}
        finally:
            if not committed:call(['shell','rm','-f',shlex.quote(stage)],quiet=True)
