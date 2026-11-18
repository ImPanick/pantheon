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
import logging
import os
import platform
import re
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
from .radio import PrivateRadio, ProcessRadio
from .platform_support import accelerator_name, check_python, console_path, native_abi, write_private  # noqa: F401 — re-exported

logger = logging.getLogger(__name__)
PROC_NET = Path('/proc/net')  # this container's own network namespace


def _listening_uids(port):
    """Users of the TCP sockets listening on this port, from the kernel's table.
    Readable without access to the listening process."""
    uids=set()
    for name in ('tcp','tcp6'):
        try:lines=(PROC_NET/name).read_text().splitlines()[1:]
        except OSError:continue
        for line in lines:
            fields=line.split()
            if len(fields)<10 or fields[3]!='0A':continue  # 0A: LISTEN
            try:
                if int(fields[1].rsplit(':',1)[1],16)==port:uids.add(int(fields[7]))
            except ValueError:continue
    return uids


def _console_reply(connection):
    data=bytearray()
    while not data.endswith((b'OK\r\n',b'KO\r\n')):
        block=connection.recv(1024)
        if not block or len(data)>8192: raise AdbError('Invalid Android console response.')
        data.extend(block)
        if b'\r\nKO:' in data or data.startswith(b'KO:'): raise AdbError('Android refused its console operation.')
    return data


class Host:
    backend = 'native_android'
    def __init__(self, config):
        check_python()
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
        self.abi = config.get('abi') or native_abi()
        self.emulator = self.sdk / 'emulator' / ('emulator.exe' if os.name == 'nt' else 'emulator')
        self.accel = None
        self.why = None
        self._probed = 0.0
        self.probe()

    REPROBE_S = 30.0

    def probe(self):
        """Ask the SDK again what accelerates it here. A host whose hypervisor
        was off when the worker started (KVM group not yet applied, Windows
        Hypervisor Platform turned on later) becomes usable without a worker
        restart; a usable one is not asked again."""
        accel, why = None, None
        try:
            result = subprocess.run([str(self.emulator), '-accel-check'], capture_output=True, text=True, timeout=20)
            if result.returncode:
                why = 'Android acceleration is unavailable: ' + (result.stdout + result.stderr)[-400:]
            else:
                accel = accelerator_name(result.stdout + result.stderr)
        except (OSError, subprocess.TimeoutExpired):
            why = 'Install the Android SDK emulator on this host, then check its acceleration support.'
        try:
            console_path(self.config, self.root)
        except RuntimeError as error:
            why = str(error)
        self.accel, self.why, self._probed = accel, why, time.monotonic()

    def reprobe(self):
        if self.why is not None and time.monotonic() - self._probed >= self.REPROBE_S:
            self.probe()
        return self.why

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
                phone = NativePhone(self, account, None, memory_mib=self.phone_memory_mib(),
                                    claim_port=self.claim, release_port=self.free, can_start=self.room,installer=self.installer)
                phone.screen = Screen(phone)
                self.phones[account] = phone
            return self.phones[account]

    def phone_memory_mib(self):
        """The operator's `memory_mib` when set, otherwise sized to this
        machine (`PH.default_memory_mib`: 8 to 12 GiB) on macOS, Windows and Linux alike."""
        chosen = self.config.get('memory_mib')
        if chosen:
            return int(chosen)
        return PH.default_memory_mib(psutil.virtual_memory().total // (1024 * 1024))

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
        try:self.installer.stop()
        except Exception as error:errors.append(str(error))
        for phone in phones:
            try: phone.stop()
            except Exception as error: errors.append(str(error))
        if errors: raise RuntimeError('; '.join(errors))


class NativePhone(PH.AccountPhone):
    native_android_usb = True
    unowned = None  # why the control listener is not provably this VM's, when it is not
    _proved = False  # it was, at least once since this launch
    _leaving = False  # a stop is under way: a listener that goes now is not a loss
    _said_lost = None  # the reason last logged for a lost listener, until it is back
    def __init__(self,*args,**kwargs):
        self.control = self.direct = self.radio = None
        # Android's own display is up (SurfaceFlinger runs) while it still
        # boots: its boot animation streams before control attaches.
        self.boot_display = False
        self.generation = secrets.token_hex(16)
        self.process_identity = None  # this launch: an attestation is kept only for it
        self._processes = {}  # pid: the psutil handle kept from when that process was first seen
        self._attested = None  # which emulator last proved itself by console token
        super().__init__(*args,**kwargs)

    def package(self, device=None):
        return super().package(device).rsplit(';',1)[0] + ';' + self.system.abi

    def _availability(self):
        reprobe = getattr(self.system, 'reprobe', None)
        return reprobe() if callable(reprobe) else self.system.why

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
                        except PH.PhoneError as error:
                            self.state,self.why='unavailable',error.message
                            logger.warning('Android phone for %s did not start after its image was installed: %s',self.account,error.message)
                        except Exception:
                            # The sentence sends the person to this log, so the fault has to be in it.
                            logger.exception('Android phone for %s could not start after its image was installed',self.account)
                            self.state,self.why='unavailable','Android could not start after installation. Check the host log, then try Turn on again.'
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
        console=console_path(self.system.config,self.home())
        if platform.system() != 'Windows' and not console.exists():
            write_private(console,secrets.token_hex(32))
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

    def _process_family(self):
        """The emulator and its descendants that still run. Kept after the
        launcher exits; a process that reuses one of their pids is never
        among them.

        Each is known by the psutil handle kept from when it was first seen,
        and found again by comparing a handle made now with that one. Never by
        a remembered create_time(): psutil derives that from the wall clock
        (on Linux, the kernel's start tick plus the boot time as the clock
        reads now), so once a host steps its clock every later reading
        differs, for a process that never changed. Found in the owner's log
        (2026-11-18, Windows, Docker Desktop): the Linux VM's clock went back
        about 1.5 s every 30 s, so within 30 s of every launch the emulator
        stopped counting as this VM's own. A phone then never finished
        booting, or it showed and took no input. Two psutil handles compare by
        pid and the kernel's own start time, which no later clock change
        moves."""
        if self.emulator is not None and self.emulator.poll() is None:
            try:
                # A handle made now, like those returned below: a kept one
                # answers from what it read first (its executable, and the
                # create_time its children are compared with).
                launcher=psutil.Process(self.emulator.pid)
                if launcher==self._processes.get(launcher.pid):
                    for process in launcher.children(recursive=True):
                        if self._processes.get(process.pid)!=process:self._processes[process.pid]=process
            except psutil.Error:pass  # the emulator exited while being listed; the loop below drops what is gone
        family=[]
        for pid,kept in list(self._processes.items()):
            try:
                process=psutil.Process(pid)
                if process==kept:family.append(process);continue
            except psutil.Error:pass  # exited or its pid was reused: no longer ours, forgotten just below
            self._processes.pop(pid,None)
        return family

    def _owned(self):
        """Whether this phone's ADB port is held by this VM's own emulator.
        When it is not, `unowned` says why: the refusal carries it, and a
        phone that had proved itself says it in the log, once per reason."""
        why=self._not_owned()
        if why is None:
            if self._said_lost is not None:
                logger.info("Android phone for %s: its control listener is this VM's own again.",self.account)
                self._said_lost=None
            self._proved=True
        elif self._proved and not self._leaving and why!=self._said_lost:
            # Before Android first answers, a port not yet open is the normal
            # wait, and the boot names one that outlasts a minute. After it,
            # this is the phone losing its controls: never left unsaid.
            logger.warning("Android phone for %s: its control listener is no longer provably this VM's: %s. "
                           'Taps, keys and the picture stop until it is.',self.account,why)
            self._said_lost=why
        self.unowned=why
        return why is None

    def _not_owned(self):
        """None when this VM's own emulator listens on the phone's ADB port; else why not."""
        try:
            family=self._process_family()
            if not family:
                running=self.emulator is not None and self.emulator.poll() is None
                return (f'its emulator (pid {self.emulator.pid}) is not among the processes this VM started' if running
                        else 'its emulator process has exited')
            hidden=[];emulators=0;unread=None
            for process in family:
                try:
                    if not Path(process.exe()).resolve().is_relative_to(self.system.sdk/'emulator'):continue
                    emulators+=1
                    try:connections=process.net_connections(kind='tcp')
                    except psutil.AccessDenied:hidden.append(process);continue
                    if any(conn.status==psutil.CONN_LISTEN and conn.laddr.port==self.port+1
                           for conn in connections):return None
                except (psutil.Error,OSError) as error:
                    unread=type(error).__name__;continue  # An unrelated SDK helper may exit during enumeration.
            if hidden:return self._not_owned_without_sockets(hidden)
            if not emulators:
                return (f'its processes could not be read ({unread})' if unread
                        else "none of its processes runs this host's SDK emulator")
            return f'its emulator is not listening on port {self.port+1}'
        except (psutil.Error,OSError) as error:return f'its processes could not be read ({type(error).__name__})'

    def _not_owned_without_sockets(self,emulators):
        """The same proof when the host hides the emulator's open sockets.

        Seen from a shell on the owner's Windows host (2026-11-18, `docker
        exec -u 500`: the service's user but group 0): the emulator's
        executable was readable, its open sockets were not. That was the
        shell's limit, not the service's, which read them (its phone attested
        before this existed; what failed there was `_process_family`). It
        stays for a host that does hide them from the service.
        Then the kernel's own listener table must show both of this phone's
        ports held by the emulator's user and nobody else, and the console on
        this phone's port must accept this account's private token and name
        this account's AVD. Another account's emulator has another token, so
        it never passes. A pass is kept for this emulator until it changes.
        Returns None for a pass, else why not."""
        try:owners={process.uids().real for process in emulators}
        except (psutil.Error,OSError) as error:return f"its emulator's user could not be read ({type(error).__name__})"
        for port in (self.port,self.port+1):
            holders=_listening_uids(port)
            if not holders:return f'nothing listens on port {port} (its sockets are hidden from this service)'
            if not holders<=owners:return f"port {port} is held by a user other than its emulator's"
        identity=(self.port,self.process_identity,frozenset((p.pid,self._processes.get(p.pid)) for p in emulators))
        if self._attested==identity:return None
        try:
            with socket.create_connection(('127.0.0.1',self.port),timeout=3) as connection:
                connection.settimeout(3)
                _console_reply(connection)
                token=console_path(self.system.config,self.home()).read_text().strip()
                connection.sendall(('auth '+token+'\n').encode());_console_reply(connection)
                connection.sendall(b'avd name\n')
                named=_console_reply(connection).decode('utf-8',errors='replace').splitlines()
        except AdbError:return f"the emulator console on port {self.port} refused this account's token"
        except OSError as error:return f'the emulator console on port {self.port} did not answer ({type(error).__name__})'
        if self.avd not in (line.strip() for line in named):return f'the emulator console on port {self.port} names another device'
        self._attested=identity
        return None

    def _launch_android(self):
        self.port=self._claim_port(self.account)
        if self.port is None: raise PH.PhoneError('unavailable','No Android VM slot is free.')
        self._write_avd()
        cfg=self.system.config
        radio=ProcessRadio if cfg.get('radio_transport')=='process' else PrivateRadio
        self.radio=radio(self.home()/'.android/radio',cfg['radio_binary'],internet=cfg.get('internet',False))
        self.radio.__enter__()
        android=self.home()/'.android'
        # Python normalizes Windows environment keys to uppercase. Preserve
        # SYSTEMROOT for the Windows loader while retaining a narrow allowlist.
        env={key:value for key,value in os.environ.items() if key.upper() in ('PATH','SYSTEMROOT','WINDIR','TEMP','TMP','LANG','LC_ALL','USER','LOGNAME')}
        env.update(HOME=str(self.home()),USERPROFILE=str(self.home()),ANDROID_HOME=str(self.system.sdk),
                   ANDROID_SDK_ROOT=str(self.system.sdk),ANDROID_USER_HOME=str(android),ANDROID_EMULATOR_HOME=str(android),
                   ANDROID_AVD_HOME=str(android/'avd'),ANDROID_SDK_HOME=str(self.home()),ADB_VENDOR_KEYS=str(android/'adbkey'),
                   ANDROID_ADB_SERVER_PORT='20586',ADB_SERVER_PORT='20586',ADB_SERVER_SOCKET='tcp:127.0.0.1:20586',**self.radio.env)
        args=[str(self.system.emulator),'-avd',self.avd,'-port',str(self.port),'-no-window','-no-audio',
              '-no-snapshot','-no-metrics','-crash-report-mode','disabled','-no-direct-adb','-no-sim',
              '-adb-path',str(Path(__file__).with_name('no_adb.py')),'-memory',str(self.memory_mib),'-cores',str(max(1,min(16,int(cfg.get('cores',4))))),
              '-accel','on','-gpu',cfg.get('gpu','software'),'-feature',
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
        # Popen's child cannot have been reaped yet, so this handle is the launcher's own.
        self._processes={self.emulator.pid:psutil.Process(self.emulator.pid)}
        self.process_identity=secrets.token_hex(8)
        self.unowned=self._said_lost=None;self._proved=self._leaving=False
        self._process_family()
        self.direct=DirectAdb(self.port+1,android/'adbkey',self._owned,lambda:self.unowned)
        self.generation=secrets.token_hex(16)
        self.state,self.why,self.boot_phase='starting','','emulator'
        self.boot_display=False
        self.posture='open' if PH.P.PHONE_DEVICES[self.device]['kind']=='foldable' else None
        self.rotation=0
        logger.info('Android phone for %s: emulator started (pid %s, console port %s, ADB port %s, %s).',
                    self.account,self.emulator.pid,self.port,self.port+1,self.package())
        self._booting=threading.Thread(target=self._boot,args=(self.emulator,),daemon=True)
        self._booting.start()
        return self.info('start')

    def _boot(self,proc):
        started=time.monotonic()
        deadline=started+600
        bootstrap_deadline=started+120
        error=None
        complete=False
        said=None  # what Android last answered after it booted, for the owner
        unanswered,unanswered_since,unanswered_logged=None,0.0,False  # the same, before it booted
        while time.monotonic()<deadline:
            if self.emulator is not proc:return
            if proc.poll() is not None:
                error='Android stopped during startup'+self._last_words();break
            try:
                if not self.boot_display and self.direct.shell(
                        ['getprop','init.svc.surfaceflinger'],timeout=5).strip()=='running':
                    # The owner (2026-11-15): show Android actually starting.
                    # Its display streams from here, boot animation and all,
                    # once Android says its ADB is private.
                    if self.direct.shell(['getprop','ro.adb.secure'],timeout=5).strip()!='1':
                        error='Android did not enforce private ADB authentication.';break
                    with self.lock:
                        if self.emulator is not proc:return
                        self.boot_display=True;self.boot_phase='android'
                    logger.info('Android phone for %s: Android answered after %.0f s; its display is streaming.',
                                self.account,time.monotonic()-started)
                complete=self.direct.shell(['getprop','sys.boot_completed'],timeout=5).strip()=='1'
                if complete:
                    if self.direct.shell(['getprop','ro.adb.secure'],timeout=5).strip()!='1':
                        error='Android did not enforce private ADB authentication.';break
                    # wm overrides persist in userdata; every cold boot starts open.
                    self._tidy(['wm','size','reset'])
                    self._tidy(['wm','scaling','auto'])
                    # The emulator's own post-boot setup goes through adb, which
                    # this host withholds from it, so the screen would sleep at
                    # Android's default timeout. Keep it on here instead.
                    self._tidy(['settings','put','system','screen_off_timeout','2147483647'])
                    self._tidy(['svc','power','stayon','true'])
                    if self.system.config.get('internet') and not self._join_wifi(proc):return
                    with self.lock:
                        if self.emulator is not proc:return
                        self._show();self.state='on';self.boot_phase='ready'
                    logger.info('Android phone for %s is on after %.0f s, with its controls attached.',
                                self.account,time.monotonic()-started)
                    return
            except AdbAuthenticationError as auth:
                if auth.reason!='key_rejected' or time.monotonic()>bootstrap_deadline:
                    error='Android private-device authentication failed: '+auth.reason;break
            except OSError as failure:
                error='Android startup failed: '+str(failure)[:300];break
            except (AdbError,PH.PhoneError) as waiting:
                # Still booting: retried until the deadline, which reports it.
                # Once Android has booted, a step that keeps failing is logged
                # once and named in the failure, never swallowed for 10 minutes.
                now=getattr(waiting,'message',None) or str(waiting)
                if complete and now!=said:
                    logger.warning('Android phone for %s booted, then a startup step failed (retrying): %s',self.account,now)
                    said=now
                elif not complete:
                    # Before boot, failures are normal for a while. One that
                    # outlasts a minute is logged once, and named at the end.
                    if now!=unanswered:unanswered,unanswered_since,unanswered_logged=now,time.monotonic(),False
                    elif not unanswered_logged and time.monotonic()-unanswered_since>60:
                        logger.warning('Android phone for %s: Pantheon cannot reach Android yet (still trying): %s',self.account,now)
                        unanswered_logged=True
            time.sleep(2 if self.boot_display else .5)  # quickly to the first frame
        with self.lock:
            if self.emulator is proc:
                # What the emulator itself said, read before it is stopped: it
                # learns that Android booted from the guest, not through ADB,
                # so it tells a guest that never came up from one this host
                # could not reach.
                booted,last=self._emulator_said()
                self._stop_locked()
                self.state,self.why='unavailable',error or (
                    f'Android booted, but Pantheon could not finish setting it up: {said.rstrip(".")}. Start it again to retry.' if said
                    else (f'Android finished booting (its emulator says so), but Pantheon never reached Android: {unanswered.rstrip(".")}. '
                          'Start it again to retry.') if unanswered and booted
                    else f'Pantheon never reached Android: {unanswered.rstrip(".")}{last}. Start it again to retry.' if unanswered
                    else f'Android did not finish booting{last}. Start it again to retry.')
                logger.warning('Android phone for %s did not start: %s',self.account,self.why)

    def _tidy(self,args):
        """A finishing touch on a booted phone. A user build (Google Play) may
        refuse one to its shell; the phone still turns on, and the log says so."""
        try:self.direct.shell(args,timeout=10)
        except AdbError as refused:
            if isinstance(refused,AdbAuthenticationError):raise
            logger.warning('Android refused %s on the phone for %s: %s',' '.join(args[:2]),self.account,refused)

    def _join_wifi(self,proc):
        """Join the emulator's private Wi-Fi; False when the emulator changed.

        Google Play images are user builds. Their shell may not run
        `cmd wifi connect-network` (only root may), so Android's own join is
        waited for first, a refused connect is not retried, and a phone whose
        Wi-Fi never gets an address still turns on, without internet, rather
        than failing after ten minutes of silent retries."""
        def status():
            try:return self.direct.shell(['cmd','wifi','status'],timeout=5)
            except AdbError:return ''
        def wait(said,seconds,step):
            until=time.monotonic()+seconds
            while self.emulator is proc:
                if said in status():return True
                if time.monotonic()>until:return False
                time.sleep(step)
            return None
        try:self.direct.shell(['svc','wifi','enable'],timeout=10)
        except AdbAuthenticationError:raise
        except AdbError as refused:logger.warning('Android refused to turn on its Wi-Fi: %s',refused)
        joined=wait('Wifi is enabled',30,.5) and wait('/10.0.2.',10,1)
        if joined is None:return False
        if not joined:
            try:self.direct.shell(['cmd','wifi','connect-network','AndroidWifi','open'],timeout=15)
            except AdbError as refused:
                logger.info('Android would not join AndroidWifi from its shell (%s); waiting for it to join by itself.',refused)
            joined=wait('/10.0.2.',45,1)
            if joined is None:return False
        if not joined:
            logger.warning('Android phone for %s did not get a Wi-Fi address; it starts without internet.',self.account)
        return True

    def _show(self):
        if self.control is None:
            try: self.control=ScrcpyControl(self.direct,self.system.config['scrcpy_server']).start()
            except AdbError as error: raise PH.PhoneError('unavailable',str(error)) from error
        self.screen.refresh()

    def ensure_shown(self):
        with self.lock:
            if self.state=='on' and not self.running():
                # An emulator that died under a phone that was on: said here, with its last line.
                logger.warning('Android phone for %s: its emulator exited (status %s) while Android was on%s.',
                               self.account,self.emulator.poll() if self.emulator is not None else None,self._emulator_said()[1])
                self._stop_locked();self.state,self.why='unavailable','Android stopped. Turn it on again to retry.'

    def stream_ready(self):
        if self.state not in ('starting','on') or not self.running(): return False
        return self.control is not None or (self.state=='starting' and self.boot_display)

    def screen_size(self):
        if self.screen is not None and self.screen.size is not None: return self.screen.size
        return super().screen_size()

    def _marks_source_size(self):
        self.screen.refresh()
        return self.screen.physical

    def _on(self):
        self._active()
        if not self.running() or self.state!='on': raise PH.PhoneError('unavailable','Wait for Android to finish booting, or turn it on first.')
        self.touch()

    def _emulator_said(self):
        """(whether the emulator's log says Android finished booting, its last
        line as ` (its emulator last said: ...)` or ``). The log holds what
        the guest made the emulator print: read without following a link,
        bounded, and never trusted beyond naming a failed start."""
        if not hasattr(os,'O_NOFOLLOW'):return False,''
        try:
            fd=os.open(self.home()/PH.LOG_FILE,os.O_RDONLY|os.O_NOFOLLOW)
            with os.fdopen(fd,'rb') as log:
                log.seek(0,os.SEEK_END);log.seek(max(0,log.tell()-(1<<20)))
                text=log.read().decode('utf-8','replace')
        except OSError:return False,''
        lines=[' '.join(''.join(c if c.isprintable() else ' ' for c in line).split()) for line in text.splitlines()]
        lines=[line for line in lines if line]
        return 'boot completed' in text.lower(),f' (its emulator last said: {lines[-1][:200]})' if lines else ''

    def _last_words(self):
        # The inherited reader protects a guest-writable Linux log with
        # O_NOFOLLOW. Windows has no such flag: do not follow a reparse point
        # merely to decorate an error, or leave the boot thread in 'starting'.
        if not hasattr(os,'O_NOFOLLOW'):
            return ' (see .android/pantheon-emulator.log in the Android host profile)'
        return super()._last_words()

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

    def set_posture(self,posture):
        # A console or shell that fails here is this phone's error, said to
        # whoever asked. An OSError used to end the request with no answer and
        # nothing in the log; an AdbError answered "the host failed".
        try:return self._set_posture(posture)
        except AdbError as error:raise PH.PhoneError('unavailable',str(error)) from error
        except OSError as error:
            raise PH.PhoneError('unavailable',f"Android's emulator console did not answer ({type(error).__name__}).") from error

    def _set_posture(self,posture):
        with self.lock:
            if posture not in PH.P.PHONE_POSTURES:raise PH.PhoneError('bad_request','Choose open, half_open or closed.')
            self._on()
            device=PH.P.PHONE_DEVICES[self.device]
            if device['kind']!='foldable':raise PH.PhoneError('bad_request','This device does not fold.')
            self.screen.release_all()
            command=['sensor','set','hinge-angle0','90'] if posture=='half_open' else ['fold' if posture=='closed' else 'unfold']
            self.console(command,20)
            reported=self.console(['sensor','get','hinge-angle0'],5)
            match=re.search(r'hinge-angle0\s*=\s*([0-9.]+)',reported)
            lo,hi={'closed':(0,30),'half_open':(89,91),'open':(150,180)}[posture]
            if not match or not lo<=float(match[1])<=hi:raise PH.PhoneError('unavailable','Android did not confirm its hinge angle.')
            size=f"{device['cover_width']}x{device.get('cover_height',device['height'])}" if posture=='closed' else 'reset'
            self.direct.shell(['wm','size',size],timeout=10)
            self.direct.shell(['wm','scaling','auto'],timeout=10)
            self.posture=posture;self.screen.viewport_key=None
            deadline=time.monotonic()+5
            while True:
                try:
                    report=self.direct.shell(['dumpsys','input'],timeout=5)
                    line=next((line for line in report.splitlines() if 'Viewport INTERNAL: displayId=0,' in line and 'isActive=[1]' in line),'')
                    dimensions=re.search(r'logicalFrame=\[0, 0, (\d+), (\d+)\]',line)
                    expected=(device['cover_width'],device.get('cover_height',device['height'])) if posture=='closed' else (device['width'],device['height'])
                    if not dimensions or tuple(map(int,dimensions.groups())) not in (expected,expected[::-1]):
                        raise PH.PhoneError('unavailable','Android is still changing its display viewport.')
                    self.screen.refresh();break
                except PH.PhoneError:
                    if time.monotonic()>deadline:raise
                    time.sleep(.1)
            return self.info('posture')

    def console(self,args,timeout):
        if args not in (['rotate'],['fold'],['unfold'],['sensor','set','hinge-angle0','90'],['sensor','get','hinge-angle0']): raise AdbError('Unsupported Android console operation.')
        if not self._owned(): raise AdbError(f'The Android console no longer belongs to this VM: {self.unowned}.')
        with socket.create_connection(('127.0.0.1',self.port),timeout=timeout) as connection:
            connection.settimeout(timeout)
            def response():return _console_reply(connection)
            response()
            token=console_path(self.system.config,self.home()).read_text().strip()
            connection.sendall(('auth '+token+'\n').encode());response()
            if not self._owned(): raise AdbError('The Android console changed before input.')
            self.screen.release_all();self.generation=secrets.token_hex(16)
            connection.sendall((' '.join(args)+'\n').encode());answer=response()
        return answer.decode('utf-8',errors='replace')

    def _stop_locked(self):
        self.boot_display=False  # no more frames from here
        self._leaving=True  # its listener goes with it, and that is the stop, not a loss
        self._usb_connection = None
        self.generation=secrets.token_hex(16)
        if self.screen is not None: self.screen.release_all()
        if self.control is not None: self.control.close();self.control=None
        proc=self.emulator
        self._process_family()
        if proc is not None and proc.poll() is None:
            if self.direct is not None:
                try:self.direct.shell(['sync'],timeout=10);self.direct.shell(['svc','power','shutdown'],timeout=5)
                except AdbError:pass  # no clean in-guest shutdown: the terminate below still stops it
                try:proc.wait(timeout=30)
                except subprocess.TimeoutExpired:pass  # still running: terminated just below
            # Popen still owns its child even if startup failed before psutil
            # recorded its identity or the authenticated ADB client existed.
            if proc.poll() is None:proc.terminate()
        family=self._process_family()
        for process in reversed(family):
            try:process.terminate()
            except psutil.NoSuchProcess:pass  # already gone, which is the goal
        alive=psutil.wait_procs(family,timeout=10)[1] if family else []
        for process in alive:
            try:
                # Only a process kept for this phone, and only while its pid is still that process.
                if self._processes.get(process.pid)==process and process.is_running():process.kill()
            except psutil.NoSuchProcess:pass  # already gone; anything still alive is reported below
        if alive and psutil.wait_procs(alive,timeout=5)[1]:
            raise PH.PhoneError('unavailable','Android did not stop; its VM slot stays reserved.')
        if proc is not None and proc.poll() is None:
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    raise PH.PhoneError('unavailable','Android did not stop; its VM slot stays reserved.')
        self._processes={}
        if self.screen is not None:
            with self.screen.lock:
                self.screen.size=self.screen.physical=self.screen.cache=None
                self.screen.viewport_key=self.screen.viewport_signature=None
                self.screen.cached_at=0
        self.emulator=self.direct=None
        if self.radio is not None: self.radio.__exit__(None,None,None);self.radio=None
        self._release();self.boot_phase='off';self.state='off'
        if proc is not None:logger.info('Android phone for %s: emulator stopped.',self.account)
        if self._android_lifecycle:
            self._android_lifecycle=False;self._mobile_lifecycle.release()
