# SPDX-License-Identifier: AGPL-3.0-or-later
"""Host adapter for the SDK's HVF, WHPX and KVM implementations.

The app chooses an account and a catalogue profile, never a host command or path.
Operator configuration and private SDK homes belong only to this host worker.
"""
from __future__ import annotations
from contextlib import nullcontext
from pathlib import Path
import hashlib
import json
import os
import platform
import secrets
import signal
import socket
import subprocess
import threading
import time

try:
    import psutil
except ImportError:
    psutil = None
from workstation import phone as PH
from .adb import AdbError, AdbAuthenticationError, DirectAdb
from .control import ScrcpyControl
from .radio import PrivateRadio


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


class Host:
    backend = 'native_android'
    def __init__(self, config):
        if psutil is None:
            raise RuntimeError('Install the Android host dependencies from workstation/native_android/host-dependencies.txt.')
        self.config = config
        self.root = Path(config['state']).resolve()
        self.sdk = Path(config['sdk']).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        from .images import ImageInstaller
        self.installer = ImageInstaller(self)
        policies=self.root/'boot-policies.json'
        if policies.exists():self.config.setdefault('boot_policies',{}).update(json.loads(policies.read_text()))
        self.phones = {}
        self.closing = False
        self.claims = {}
        self.max_running = max(1, min(16, int(config.get('max_running', 1))))
        self.abi = config.get('abi') or ('arm64-v8a' if platform.machine().lower() in ('aarch64','arm64') else 'x86_64')
        self.emulator = self.sdk / 'emulator' / ('emulator.exe' if os.name == 'nt' else 'emulator')
        self.accel = None
        self.why = None
        try:
            result = subprocess.run([str(self.emulator), '-accel-check'], capture_output=True, text=True, timeout=20)
            if result.returncode:
                self.why = 'Android acceleration is unavailable: ' + (result.stdout + result.stderr)[-400:]
            else:
                self.accel = {'Darwin':'hvf','Windows':'whpx','Linux':'kvm'}.get(platform.system(), 'sdk')
        except (OSError, subprocess.TimeoutExpired):
            self.why = 'Install the Android SDK emulator on this host, then check its acceleration support.'

    def home(self, account):
        # An operator may explicitly register an existing owned SDK profile.
        entry = self.config.get('profiles', {}).get(account, {})
        return Path(entry['home']).resolve() if 'home' in entry else self.root / 'owners' / hashlib.sha256(account.encode()).hexdigest() / 'home'

    def ensure(self, account):
        self.home(account).mkdir(parents=True, exist_ok=True, mode=0o700)
        return {'home':str(self.home(account))}

    def uid(self, account):
        return getattr(os, 'getuid', lambda: 1000)()

    def files_as(self, account):
        return nullcontext()

    def get(self, account):
        from .screen import Screen
        with self.lock:
            if self.closing:raise PH.PhoneError('unavailable','The Android host is shutting down. Try again after it restarts.')
            if account not in self.phones:
                self.ensure(account)
                phone = NativePhone(self, account, None, memory_mib=int(self.config.get('memory_mib',4096)),
                                    claim_port=self.claim, release_port=self.free, can_start=self.room,installer=self.installer)
                phone.screen = Screen(phone)
                self.phones[account] = phone
            return self.phones[account]

    def room(self, account):
        with self.lock:
            if self.closing:return 'The Android host is shutting down.'
            if self.installer.running():return 'Wait for the Android image install to finish.'
            if account not in self.claims and len(self.claims) >= self.max_running:
                return 'All Android VM slots on this host are in use. Stop another device or increase the host capacity.'
        return None

    def claim(self, account):
        with self.lock:
            if self.room(account): return None
            if account in self.claims: return self.claims[account]
            for port in range(5586, 5686, 2):
                if port in self.claims.values(): continue
                guards=[]
                try:
                    for number in (port,port+1):
                        guard=socket.socket(); guard.bind(('127.0.0.1',number)); guards.append(guard)
                    self.claims[account]=port
                    return port
                except OSError:
                    continue
                finally:
                    for guard in guards: guard.close()
        return None

    def free(self, account):
        with self.lock: self.claims.pop(account,None)

    def stop_all(self):
        with self.lock:
            self.closing=True
            phones=list(self.phones.values())
            for phone in phones:phone.retire()
        errors=[]
        for phone in phones:
            try: phone.stop()
            except Exception as error: errors.append(str(error))
        if errors: raise RuntimeError('; '.join(errors))


class NativePhone(PH.AccountPhone):
    def __init__(self,*args,**kwargs):
        self.control = self.direct = self.radio = None
        self.generation = secrets.token_hex(16)
        self.process_identity = None
        super().__init__(*args,**kwargs)

    def package(self, device=None):
        return super().package(device).rsplit(';',1)[0] + ';' + self.system.abi

    def _availability(self):
        return self.system.why

    def _edition_accepted(self):
        try:
            consent=json.loads(Path(self.system.config['consent']).read_text())
            ids=set(consent['license_ids'])
            return ('android-sdk-license' in ids and (self.system.abi != 'arm64-v8a' or 'android-sdk-arm-dbt-license' in ids)
                    and (self.edition!='google_play' or 'google_play' in self._accepted_editions))
        except (OSError,ValueError,KeyError,TypeError): return False

    def installed(self, device=None):
        return (self.system.sdk / PH.image_parts(self.package(device))['sysdir'] / 'system.img').is_file()

    def mobile_why(self):
        return 'Browser preview is provided by the workstation, separately from this Android VM.'

    def _save_device(self):
        write_private(self.home()/PH.PREFS_FILE,json.dumps({'device':self.device,'edition':self.edition,
                      'accepted_editions':sorted(self._accepted_editions)}))

    def info(self,action='status'):
        out=super().info(action)
        out.update(isolation='per_user_vm',runtime='native_android',accel=self.system.accel,
                   installed=self.installed(),can_install=True,
                   preview_available=False,license={'accepted':self._edition_accepted(),'url':PH.LICENSE_URL})
        for device in out['devices']: device['installed']=self.installed(device['id'])
        return out

    def install(self,device=None,*,accept=False,then_start=True):
        if device is not None:
            if not isinstance(device,str) or device not in PH.P.PHONE_DEVICES: raise PH.PhoneError('bad_request','Choose a device from the catalogue.')
            with self.lock:
                if device!=self.device:
                    if self.running(): self._stop_locked()
                    self.device=device;self._save_device()
        if accept:
            self._accepted_editions.add(self.edition);self._save_device()
        if not self._edition_accepted():raise PH.PhoneError('license',PH.NEEDS_LICENSE.format(url=PH.LICENSE_URL))
        if self.installed(): return self.start() if then_start else self.info('install')
        with self.lock:
            self._stop_locked()
            wanted,edition=self.device,self.edition
            install_generation=self.generation
            self.state,self.why='installing',''
            def then(ok):
                with self.lock:
                    if self._retired.is_set() or self.generation!=install_generation or self.state!='installing':return
                    self.state='off'
                    self.why='' if ok else self.installer.info().get('why','The Android image could not be installed.')
                    if ok and then_start and self.device==wanted and self.edition==edition:
                        try:self.start()
                        except PH.PhoneError as error:self.state,self.why='unavailable',error.message
                        except Exception:self.state,self.why='unavailable','Android could not start after installation. Check the host log, then try Turn on again.'
            try:self.installer.start(self.package(),accept=accept,then=then)
            except Exception:self.state='off';raise
            return self.info('install')

    def _write_avd(self):
        self.system.ensure(self.account)
        android=self.home()/'.android';avd_home=android/'avd'
        avd_home.mkdir(parents=True,exist_ok=True,mode=0o700)
        key=android/'adbkey'
        if not key.exists():
            # keygen writes files only; it never starts the shared SDK server.
            adb=self.system.sdk/'platform-tools'/('adb.exe' if os.name=='nt' else 'adb')
            subprocess.run([str(adb),'keygen',str(key)],check=True,capture_output=True,timeout=15,
                           env={**os.environ,'HOME':str(self.home()),'ANDROID_USER_HOME':str(android)})
            key.chmod(0o600)
        console=self.home()/'.emulator_console_auth_token'
        if not console.exists(): write_private(console,secrets.token_hex(32))
        registered=self.system.config.get('profiles',{}).get(self.account,{})
        selected=registered.get('slots',{}).get(self.package(),{})
        if selected and selected.get('device')==self.device:
            self.avd=selected['avd']
        else:
            self.avd=self._avd_slot(self.package())
        folder=avd_home/(self.avd+'.avd')
        folder.mkdir(exist_ok=True,mode=0o700)
        previous=folder/'config.ini'
        data_size=next((line.split('=',1)[1].strip() for line in previous.read_text().splitlines()
                        if '=' in line and line.split('=',1)[0].strip()=='disk.dataPartition.size'),None) if previous.exists() else None
        if data_size is None:
            data_size='6G' if (folder/'userdata-qemu.img').exists() else str(max(2,min(64,int(self.system.config.get('data_size_gib',2)))))+'G'
        config=PH.avd_config(self.device,self.package(),memory_mib=self.memory_mib,name=self.avd)
        config=config.replace('disk.dataPartition.size=6G','disk.dataPartition.size='+data_size)
        policy=self.system.config.get('boot_policies',{}).get(self.package())
        if PH.image_kind(self.package())!='google_play' and not policy:
            raise PH.PhoneError('unavailable','This developer image needs an authenticated ADB boot policy. Run the Android host installer for this image.')
        if policy:
            source=self.system.sdk/PH.image_parts(self.package())['sysdir']/'ramdisk.img'
            if hashlib.sha256(source.read_bytes()).hexdigest()!=policy['source_sha256']:
                raise PH.PhoneError('unavailable','The Android image changed; rebuild its authenticated boot policy before starting it.')
            config+='kernel.parameters=androidboot.verifiedbootstate=orange\n'
        write_private(folder/'config.ini',config)
        write_private(avd_home/(self.avd+'.ini'),PH.avd_ini(self.device,avd_home,self.package(),name=self.avd))
        write_private(android/'emu-update-last-check.ini','Android.Emulator.LastCheck=4102444800000\n')

    def _owned(self):
        if self.emulator is None or self.emulator.poll() is not None or self.process_identity is None: return False
        try:
            process=psutil.Process(self.emulator.pid)
            if process.create_time()!=self.process_identity: return False
            family=[process,*process.children(recursive=True)]
            listeners=[p for p in family for conn in p.net_connections(kind='tcp')
                       if conn.status==psutil.CONN_LISTEN and conn.laddr.port==self.port+1]
            # The SDK launcher may exec the guest; every listener must descend
            # from this captured launch and execute inside this private SDK.
            if not listeners: return False
            return all(Path(p.exe()).resolve().is_relative_to(self.system.sdk/'emulator') for p in listeners)
        except (psutil.Error,OSError): return False

    def _launch_android(self):
        self.port=self._claim_port(self.account)
        if self.port is None: raise PH.PhoneError('unavailable','No Android VM slot is free.')
        self._write_avd()
        cfg=self.system.config
        self.radio=PrivateRadio(self.home()/'.android/radio',cfg['radio_binary'],internet=cfg.get('internet',False))
        self.radio.__enter__()
        android=self.home()/'.android'
        env={key:value for key,value in os.environ.items() if key in ('PATH','SystemRoot','WINDIR','TEMP','TMP','LANG','LC_ALL','USER','LOGNAME')}
        env.update(HOME=str(self.home()),USERPROFILE=str(self.home()),ANDROID_HOME=str(self.system.sdk),
                   ANDROID_SDK_ROOT=str(self.system.sdk),ANDROID_USER_HOME=str(android),ANDROID_EMULATOR_HOME=str(android),
                   ANDROID_AVD_HOME=str(android/'avd'),ANDROID_SDK_HOME=str(self.home()),ADB_VENDOR_KEYS=str(android/'adbkey'),
                   ANDROID_ADB_SERVER_PORT='20586',ADB_SERVER_PORT='20586',ADB_SERVER_SOCKET='tcp:127.0.0.1:20586',**self.radio.env)
        args=[str(self.system.emulator),'-avd',self.avd,'-port',str(self.port),'-no-window','-no-audio',
              '-no-snapshot','-no-metrics','-crash-report-mode','disabled','-no-direct-adb','-no-sim',
              '-adb-path',str(Path(__file__).with_name('no_adb.py')),'-memory',str(self.memory_mib),'-cores','4',
              '-accel','on','-gpu',cfg.get('gpu','host'),'-feature',
              '-WiFiPacketStream,-Uwb,BluetoothEmulation,-ModemSimulator,-GnssGrpcV1,GuestAngle',
              '-wifi-user-mode-options','restrict=on,ipv6=off','-network-user-mode-options','restrict=on,ipv6=off',
              '-packet-streamer-endpoint','dns:///'+self.radio.TARGET]
        if cfg.get('internet'):args[args.index('-feature')+1]=args[args.index('-feature')+1].replace('-WiFiPacketStream','WiFiPacketStream')
        policy=cfg.get('boot_policies',{}).get(self.package())
        if policy:
            ramdisk=Path(policy['path'])
            if hashlib.sha256(ramdisk.read_bytes()).hexdigest()!=policy['derived_sha256']:
                raise PH.PhoneError('unavailable','The authenticated Android boot policy changed.')
            args+=['-ramdisk',str(ramdisk)]
        options={'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=='nt' else {'start_new_session':True}
        with open(self.home()/PH.LOG_FILE,'wb') as log:
            self.emulator=subprocess.Popen(args,cwd=self.home(),env=env,stdin=subprocess.DEVNULL,
                                           stdout=log,stderr=subprocess.STDOUT,**options)
        self.process_identity=psutil.Process(self.emulator.pid).create_time()
        self.direct=DirectAdb(self.port+1,android/'adbkey',self._owned)
        self.generation=secrets.token_hex(16)
        self.state,self.why,self.boot_phase='starting','','emulator'
        self.posture='open' if PH.P.PHONE_DEVICES[self.device]['kind']=='foldable' else None
        self.rotation=0
        self._booting=threading.Thread(target=self._boot,args=(self.emulator,),daemon=True)
        self._booting.start()
        return self.info('start')

    def _boot(self,proc):
        deadline=time.monotonic()+600
        bootstrap_deadline=time.monotonic()+120
        error=None
        while time.monotonic()<deadline:
            if self.emulator is not proc:return
            if proc.poll() is not None:
                error='Android stopped during startup'+self._last_words();break
            try:
                complete=self.direct.shell(['getprop','sys.boot_completed'],timeout=5).strip()=='1'
                if complete:
                    if self.direct.shell(['getprop','ro.adb.secure'],timeout=5).strip()!='1':
                        error='Android did not enforce private ADB authentication.';break
                    if self.system.config.get('internet'):
                        self.boot_phase='android'
                        self.direct.shell(['svc','wifi','enable'],timeout=10)
                        wifi_deadline=time.monotonic()+30
                        while 'Wifi is enabled' not in self.direct.shell(['cmd','wifi','status'],timeout=5):
                            if self.emulator is not proc:return
                            if time.monotonic()>wifi_deadline:raise PH.PhoneError('unavailable','Android Wi-Fi did not enable.')
                            time.sleep(.5)
                        self.direct.shell(['cmd','wifi','connect-network','AndroidWifi','open'],timeout=15)
                        wifi_deadline=time.monotonic()+45
                        while '/10.0.2.' not in self.direct.shell(['cmd','wifi','status'],timeout=5):
                            if self.emulator is not proc:return
                            if time.monotonic()>wifi_deadline:raise PH.PhoneError('unavailable','The private Android network did not assign an address.')
                            time.sleep(1)
                    with self.lock:
                        if self.emulator is not proc:return
                        self._show();self.state='on';self.boot_phase='ready'
                    return
            except AdbAuthenticationError as auth:
                if auth.reason!='key_rejected' or time.monotonic()>bootstrap_deadline:
                    error='Android private-device authentication failed: '+auth.reason;break
            except (AdbError,PH.PhoneError):pass
            time.sleep(2)
        with self.lock:
            if self.emulator is proc:
                self._stop_locked()
                self.state,self.why='unavailable',error or 'Android did not finish booting. Start it again to retry.'

    def _show(self):
        if self.control is None:
            try: self.control=ScrcpyControl(self.direct,self.system.config['scrcpy_server']).start()
            except AdbError as error: raise PH.PhoneError('unavailable',str(error)) from error
        self.screen.refresh()

    def ensure_shown(self):
        with self.lock:
            if self.state=='on' and not self.running():
                self._stop_locked();self.state,self.why='unavailable','Android stopped. Turn it on again to retry.'

    def stream_ready(self):
        return self.state in ('starting','on') and self.running() and self.control is not None

    def screen_size(self):
        if self.screen is not None and self.screen.size is not None: return self.screen.size
        return super().screen_size()

    def _on(self):
        self._active()
        if not self.running() or self.state!='on': raise PH.PhoneError('unavailable','Wait for Android to finish booting, or turn it on first.')
        self.touch()

    def adb(self,args,*,timeout=20,quiet=False,data=None,binary=False):
        try:
            if self.direct is None: raise AdbError('The Android VM is not connected.')
            if args[0]=='get-state': value=self.direct.shell(['getprop','sys.boot_completed'],timeout);return 'device\n' if value.strip()=='1' else ''
            if args[0]=='push': self.direct.push(Path(args[1]),args[2],timeout);return ''
            if args[0]=='emu': return self.console(args[1:],timeout)
            if args[0] in ('shell','exec-out'):
                # AccountPhone's existing SDK call sites quote shell operands
                # themselves. Preserve SDK joining semantics exactly once.
                command=' '.join(args[1:])
                if args[0]=='shell': return self.direct.shell(['sh','-c',command],timeout)
                value=self.direct.execute_bytes(['sh','-c',command],timeout)
                return value if binary else value.decode('utf-8','replace')
            raise AdbError('Unsupported internal Android operation.')
        except (AdbError,OSError) as error:
            if quiet: return b'' if binary else ''
            raise PH.PhoneError('unavailable',str(error)) from error

    def console(self,args,timeout):
        if args not in (['rotate'],['fold'],['unfold']): raise AdbError('Unsupported Android console operation.')
        if not self._owned(): raise AdbError('The Android console no longer belongs to this VM.')
        with socket.create_connection(('127.0.0.1',self.port),timeout=timeout) as connection:
            connection.settimeout(timeout)
            def response():
                data=bytearray()
                while not data.endswith((b'OK\r\n',b'KO\r\n')):
                    block=connection.recv(1024)
                    if not block or len(data)>8192: raise AdbError('Invalid Android console response.')
                    data.extend(block)
                    if b'\r\nKO:' in data or data.startswith(b'KO:'): raise AdbError('Android refused its console operation.')
                return data
            response()
            token=(self.home()/'.emulator_console_auth_token').read_text().strip()
            connection.sendall(('auth '+token+'\n').encode());response()
            if not self._owned(): raise AdbError('The Android console changed before input.')
            self.screen.release_all();self.generation=secrets.token_hex(16)
            connection.sendall((' '.join(args)+'\n').encode());response()
        return ''

    def _stop_locked(self):
        self.generation=secrets.token_hex(16)
        if self.screen is not None: self.screen.release_all()
        if self.control is not None: self.control.close();self.control=None
        proc=self.emulator
        if proc is not None and proc.poll() is None:
            try: self.direct.shell(['sync'],timeout=10);self.direct.shell(['svc','power','shutdown'],timeout=5)
            except AdbError: pass
            try: proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                parent=psutil.Process(proc.pid)
                if parent.create_time()!=self.process_identity: raise PH.PhoneError('unavailable','Android process identity changed; refusing to stop an unrelated process.')
                children=parent.children(recursive=True)
                for process in reversed(children):
                    try: process.terminate()
                    except psutil.NoSuchProcess: pass
                parent.terminate()
                alive=psutil.wait_procs([parent,*children],timeout=10)[1]
                for process in alive:
                    try: process.kill()
                    except psutil.NoSuchProcess: pass
                if psutil.wait_procs(alive,timeout=5)[1]: raise PH.PhoneError('unavailable','Android did not stop; its VM slot stays reserved.')
        self.emulator=self.direct=None
        if self.radio is not None: self.radio.__exit__(None,None,None);self.radio=None
        self._release();self.boot_phase='off';self.state='off'
        if self._android_lifecycle:
            self._android_lifecycle=False;self._mobile_lifecycle.release()
