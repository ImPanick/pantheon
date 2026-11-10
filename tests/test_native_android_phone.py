# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone routing, persisted intent, private takeover and pinned viewer protocol."""
import asyncio
import io
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from src import phone_runtime as R
from src.workstation_client import WorkstationError
from workstation.native_android import rfb


class Worker:
    def __init__(self):
        self.device='pixel_9';self.edition='standard';self.holder='agent';self.offline=False
        self.calls=[]
    async def phone(self,account,action,*,holder='agent',**fields):
        self.calls.append((account,action,fields))
        if self.offline:raise WorkstationError('unavailable','Host offline')
        if action!='status' and holder=='agent' and self.holder=='person':raise WorkstationError('busy','Taken over')
        if action=='device':self.device=fields['device']
        if action=='edition':self.edition=fields['edition']
        if action in ('install','start') and fields.get('device'):self.device=fields['device']
        return dict(device=self.device,edition=self.edition,state='off',isolation='per_user_vm')
    async def phone_choice(self,account,device,edition,*,holder,changing=False):
        if self.offline:raise WorkstationError('unavailable','Host offline')
        if holder=='agent' and self.holder=='person' and (changing or device!=self.device or edition!=self.edition):raise WorkstationError('busy','Taken over')
        self.device,self.edition=device,edition
        return dict(device=device,edition=edition,state='off',isolation='per_user_vm')
    async def phone_screen(self,account):return {'kind':None,'holder':self.holder}


@pytest.fixture
def client(monkeypatch):
    worker=Worker();client=R.PhoneClient('ada',worker)
    saved={'device':'pixel_9','edition':'standard','producer':'android'}
    monkeypatch.setattr(client,'_read',lambda:dict(saved))
    monkeypatch.setattr(client,'_save',lambda choice:saved.update(choice))
    monkeypatch.setattr(client,'_legacy',lambda:(_ for _ in ()).throw(WorkstationError('off','Desktop off')))
    return client,worker,saved


def test_person_image_choice_survives_worker_outage_and_new_handle(client,monkeypatch):
    phone,worker,saved=client
    async def check():
        worker.offline=True
        state=await phone.phone('owned','edition',holder='person',edition='google_play')
        assert state['edition']=='google_play' and saved['edition']=='google_play'
        worker.offline=False
        state=await phone.phone('owned','status',holder='person')
        assert state['edition']=='google_play' and worker.edition=='google_play'
        assert all(action not in ('start','install') for _,action,_ in worker.calls)
    asyncio.run(check())


def test_agent_cannot_queue_choice_while_person_holds_phone(client):
    phone,worker,saved=client;worker.holder='person'
    async def check():
        with pytest.raises(WorkstationError,match='Taken over'):
            await phone.phone('owned','edition',edition='google_play')
        assert saved['edition']=='standard'
        await phone.phone('owned','status',holder='person')
        assert worker.edition=='standard'
        worker.offline=True
        with pytest.raises(WorkstationError):await phone.phone('owned','install',device='pixel_9_pro')
        assert saved['device']=='pixel_9'
    asyncio.run(check())


def test_agent_use_device_persists_the_device_it_actually_booted(client):
    phone,worker,saved=client
    async def check():
        state=await phone.phone('owned','install',device='pixel_9_pro')
        assert state['device']==saved['device']==worker.device=='pixel_9_pro'
        assert sum(action=='install' for _,action,_ in worker.calls)==1
        await phone.phone('owned','status',holder='person')
        assert worker.device=='pixel_9_pro'
    asyncio.run(check())


def test_native_phone_does_not_inherit_desktop_computer_use_approval(monkeypatch):
    from src.tool_execution import _inside_workstation_now
    monkeypatch.setenv(R.URL_ENV,'http://127.0.0.1:7993')
    assert R.computer_in_workstation({'action':'click','screen':'desktop','x':0,'y':0})
    for content in ({'action':'click','screen':'phone','x':0,'y':0},{'action':'use_device','device':'pixel_9'},'not a valid action'):
        assert not R.computer_in_workstation(content)
        assert not _inside_workstation_now('computer','ada',False,content)
    monkeypatch.delenv(R.URL_ENV)
    assert R.computer_in_workstation({'action':'click','screen':'phone','x':0,'y':0})


class Stream:
    def __init__(self,data):self.data=io.BytesIO(data);self.output=bytearray()
    def read(self,size):
        data=self.data.read(size)
        if len(data)!=size:raise rfb.StreamEnded()
        return data
    def write(self,data):self.output.extend(data)


def hello(messages):
    return b'RFB 003.008\n\1\1'+b'\2\0\0\2'+struct.pack('>ii',7,-224)+messages


def test_pinned_kasm_first_and_later_jpeg_frames_have_completion_and_correct_pixels():
    request=b'\3'+struct.pack('>BHHHH',0,0,0,8,6)
    stream=Stream(hello(request*2));released=[]
    with pytest.raises(rfb.StreamEnded):
        rfb.serve(stream,lambda:(Image.new('RGB',(8,6),(221,31,54)),'generation-one'),lambda _:None,lambda:released.append(True),frame_interval=0)
    output=bytes(stream.output)
    # The two complete JPEGs are decoded as the pinned viewer's Tight path does.
    assert output.count(struct.pack('>HHHHi',0,0,0,0,-224))==2
    offset=0
    for _ in range(2):
        offset=output.index(b'\xff\xd8',offset)
        end=output.index(b'\xff\xd9',offset)+2
        image=Image.open(io.BytesIO(output[offset:end]));image.load()
        assert image.size==(8,6)
        assert all(abs(a-b)<5 for a,b in zip(image.getpixel((0,0)),(221,31,54)))
        offset=end
    assert released==[True]


def test_bundled_kasm_optional_relays_are_refused_without_interrupting_frames():
    request=b'\3'+struct.pack('>BHHHH',0,0,0,8,6)
    subscriptions=b'\xb6\x07printer\xb6\x09smartcard'
    stream=Stream(hello(request+subscriptions+request));events=[]
    with pytest.raises(rfb.StreamEnded):
        rfb.serve(stream,lambda:(Image.new('RGB',(8,6)),'one'),events.append,lambda:None,frame_interval=0)
    output=bytes(stream.output)
    assert output.count(struct.pack('>HHHHi',0,0,0,0,-224))==2
    reason=b'Android has no relays.'
    assert output.count(b'\xb6\0'+bytes([len(reason)])+reason)==2
    assert events==[]


def test_kasm_plaintext_clipboard_and_same_size_image_switch():
    text='café Ω 測試'.encode();paste=b'\xb4\1\x0atext/plain'+struct.pack('>I',len(text))+text
    request=b'\3'+struct.pack('>BHHHH',0,0,0,8,6)
    stream=Stream(hello(paste+request));events=[];released=[];counter=iter(('a','b'))
    with pytest.raises(rfb.StreamEnded):
        rfb.serve(stream,lambda:(Image.new('RGB',(8,6)),next(counter)),events.append,lambda:released.append(True),frame_interval=0)
    assert events==[dict(kind='text',text=text.decode(),geometry='a')]
    assert b'\xff\xd8' not in stream.output
    assert released==[True]


def test_worker_exposes_no_host_file_or_shell_routes(tmp_path,monkeypatch):
    import json,threading,urllib.request,urllib.error
    from workstation.native_android import server
    class Host:
        accel=None;why='Not installed'
        def __init__(self,config):pass
    monkeypatch.setattr(server,'Host',Host)
    worker=server.make_server(dict(state=str(tmp_path),sdk=str(tmp_path),token_file=str(tmp_path/'token'),port=0))
    thread=threading.Thread(target=worker.serve_forever,daemon=True);thread.start()
    token=(tmp_path/'token').read_text()
    try:
        for action in ('exec','read','write','ensure','reset','config'):
            url=f'http://127.0.0.1:{worker.server_port}/v1/users/pw-ada-12345678/'+action
            req=urllib.request.Request(url,data=b'{}',headers={'Authorization':'Bearer '+token})
            with pytest.raises(urllib.error.HTTPError) as error:urllib.request.urlopen(req)
            assert error.value.code==404
        req=urllib.request.Request(url,data=b'{}')
        with pytest.raises(urllib.error.HTTPError) as error:urllib.request.urlopen(req)
        assert error.value.code==401
    finally:worker.shutdown();worker.server_close();thread.join()


def test_stop_during_image_install_cancels_late_automatic_boot(tmp_path,monkeypatch):
    import json
    from contextlib import nullcontext
    from workstation.native_android.host import NativePhone
    class Installer:
        callback=None
        def running(self):return False
        def info(self):return {'state':'running'}
        def start(self,package,*,accept,then):self.callback=then
    home=tmp_path/'owner';home.mkdir()
    consent=tmp_path/'consent.json';consent.write_text(json.dumps({'license_ids':['android-sdk-license','android-sdk-arm-dbt-license']}))
    system=SimpleNamespace(config={'consent':str(consent)},sdk=tmp_path/'sdk',abi='arm64-v8a',why=None,accel='hvf',
                           home=lambda _:home,files_as=lambda _:nullcontext())
    installer=Installer();phone=NativePhone(system,'owned',None,installer=installer)
    phone.screen=SimpleNamespace(release_all=lambda:None,size=None,lock=__import__('threading').RLock())
    monkeypatch.setattr(phone,'installed',lambda device=None:False)
    starts=[];monkeypatch.setattr(phone,'start',lambda *a,**k:starts.append(True))
    assert phone.install()['state']=='installing'
    phone.stop();installer.callback(True)
    assert phone.state=='off' and starts==[]


def test_native_boot_stops_immediately_if_adbd_omits_auth(tmp_path,monkeypatch):
    import json
    from workstation.native_android.host import NativePhone
    from workstation.native_android.adb import AdbAuthenticationError
    home=tmp_path/'owner';home.mkdir()
    system=SimpleNamespace(config={},sdk=tmp_path/'sdk',abi='arm64-v8a',why=None,home=lambda _:home)
    phone=NativePhone(system,'owned',None)
    process=SimpleNamespace(poll=lambda:None);phone.emulator=process
    def insecure(*a,**k):raise AdbAuthenticationError('missing_auth_challenge','Insecure guest')
    phone.direct=SimpleNamespace(shell=insecure)
    stopped=[]
    monkeypatch.setattr(phone,'_stop_locked',lambda:stopped.append(True))
    phone._boot(process)
    assert stopped==[True] and phone.state=='unavailable'
    assert 'missing_auth_challenge' in phone.why


def test_nft_106_mode_comment_is_read_from_kernel_text_when_json_omits_it():
    from workstation import netrules as N
    def run(args,stdin):
        if '-j' in args:return 0,'{"nftables":[{"table":{"family":"inet","name":"pantheon_workstation"}}]}',''
        return 0,'table inet pantheon_workstation {\n\tcomment "pantheon-workstation network=internet"\n}\n',''
    assert N.in_force(N.GATE_TABLE,run=run,nft='/usr/sbin/nft')=='internet'


def test_image_restore_uses_recorded_revision_and_keeps_private_userdata(tmp_path,monkeypatch):
    import hashlib,json,zipfile
    from workstation.native_android.images import ImageInstaller,BASE
    from workstation.phone import image_parts
    package='system-images;android-35;google_apis_playstore;arm64-v8a'
    other='system-images;android-35;google_apis;arm64-v8a'
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as zipped:zipped.writestr('arm64-v8a/system.img',b'image fixture')
    data=archive.getvalue();licence='Accepted SDK fixture licence'
    spec={'filename':'old-r09.zip','size':len(data),'sha1':hashlib.sha1(data).hexdigest(),
          'sha256':hashlib.sha256(data).hexdigest(),'license':'accepted-sdk','url':BASE+'google_apis_playstore/old-r09.zip'}
    state=tmp_path/'state';state.mkdir();sdk=tmp_path/'sdk';(sdk/'licenses').mkdir(parents=True)
    (sdk/'licenses/accepted-sdk').write_text(hashlib.sha1(licence.encode()).hexdigest()+'\n')
    consent=tmp_path/'consent';consent.write_text(json.dumps({'license_ids':['accepted-sdk']}))
    private=state/'owners/one/device-data';private.parent.mkdir(parents=True);private.write_bytes(b'private userdata')
    other_image=sdk/image_parts(other)['sysdir'];other_image.mkdir(parents=True);(other_image/'system.img').write_bytes(b'old immutable image')
    other_record=dict(spec,url=BASE+'google_apis/older.zip',filename='older.zip')
    host=SimpleNamespace(root=state,sdk=sdk,abi='arm64-v8a',config={'consent':str(consent),'managed_images':{package:spec,other:other_record}})
    metadata=f'<repository><license id="accepted-sdk">{licence}</license><remotePackage path="{package}"><uses-license ref="accepted-sdk"/><archives><archive><complete><url>new-r99.zip</url><size>999</size><checksum>new revision</checksum></complete></archive></archives></remotePackage></repository>'.encode()
    requests=[]
    def urlopen(url,timeout):
        requests.append(url)
        if url.endswith('.xml'):return io.BytesIO(metadata)
        assert url==spec['url']
        return io.BytesIO(data)
    monkeypatch.setattr('urllib.request.urlopen',urlopen)
    original_replace = Path.replace
    def cross_volume_replace(source, target):
        if source.is_relative_to(state) and Path(target).is_relative_to(sdk):
            raise OSError(18, 'Cross-device link')
        return original_replace(source, target)
    monkeypatch.setattr(Path, 'replace', cross_volume_replace)
    ImageInstaller(host).install_image(package)
    assert spec['url'] in requests and not any('new-r99' in url for url in requests)
    assert private.read_bytes()==b'private userdata'
    assert not other_image.exists()
    records=json.loads((state/'image-cache.json').read_text())
    assert records[package]['sha256']==spec['sha256']
    assert records[other]==other_record


def test_preview_can_switch_to_independent_android_after_desktop_is_disabled(client):
    phone,worker,saved=client;saved['producer']='preview'
    async def check():
        selected=await phone.phone('owned','edition',holder='person',edition='google_play')
        assert selected['edition']=='google_play' and saved['producer']=='android'
        saved['producer']='preview'
        state=await phone.phone('owned','start',holder='person')
        assert saved['producer']=='android' and state['edition']=='google_play'
    asyncio.run(check())


def test_unchanged_native_choice_still_allows_agent_observation_during_takeover(client):
    phone,worker,saved=client;worker.holder='person'
    async def check():
        state=await phone.phone('owned','status')
        assert state['device']=='pixel_9'
    asyncio.run(check())


def test_kasm_scroll_and_middle_button_reach_android_without_blocking_swipes():
    import threading
    from workstation.native_android.screen import Screen
    from workstation.native_android.control import ScrcpyControl
    packets=[]
    control=object.__new__(ScrcpyControl);control.send=packets.append
    phone=SimpleNamespace(lock=threading.RLock(),generation='one',control=control,_on=lambda:None,touch=lambda:None)
    screen=Screen(phone);screen.size=(100,200);screen.physical=(1000,2000)
    geometry=('one',screen.size,screen.physical)
    pointer=lambda mask,dx,dy:b'\5'+struct.pack('>HHHhh',mask,25,50,dx,dy)
    stream=Stream(hello(pointer(0,-40,80)+pointer(2,0,0)+pointer(0,0,0)))
    with pytest.raises(rfb.StreamEnded):
        rfb.serve(stream,lambda:(Image.new('RGB',screen.size),geometry),
                  lambda e:screen.rfb_event(e,'viewer',lambda:'person'),lambda:None)
    # Signed browser pixels become bounded Android wheel axes, not sleep-based swipes.
    assert packets==[struct.pack('>BiiHHhhI',3,250,500,1000,2000,-2048,-4096,0),
                     struct.pack('>BBiii',0,0,3,0,0)+struct.pack('>BBiii',0,1,3,0,0)]


def test_kasm_receives_actual_screen_geometry_before_scaling_input():
    # Kasm's current renderer otherwise assumes its viewport is the server
    # resolution, scaling pixels but leaving pointer coordinates unscaled.
    request=b'\3'+struct.pack('>BHHHH',0,0,0,490,1100)
    encodings=b'\2\0\0\3'+struct.pack('>iii',7,-224,-308)
    resize=b'\xfb'+struct.pack('>BHHBB',0,800,600,1,0)+struct.pack('>IHHHHI',0,0,0,800,600,0)
    stream=Stream(b'RFB 003.008\n\1\1'+encodings+request+b'\xfc'+struct.pack('>HH',1280,1280)+resize+request)
    with pytest.raises(rfb.StreamEnded):
        rfb.serve(stream,lambda:(Image.new('RGB',(490,1100)),'one'),lambda _:None,lambda:None,frame_interval=0)
    geometry=struct.pack('>HHHHi',0,0,490,1100,-308)+b'\1\0\0\0'+struct.pack('>IHHHHI',0,0,0,490,1100,0)
    assert bytes(stream.output).count(geometry)==1
    assert stream.output.index(geometry)<stream.output.index(b'\xff\xd8')
    assert struct.pack('>HHHHi',1,3,490,1100,-308) in stream.output
    assert bytes(stream.output).count(b'\xff\xd8')==2


def test_native_host_capabilities_follow_host_cpu_and_sdk_output(monkeypatch):
    from workstation.native_android import host as H
    monkeypatch.setattr(H.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(H.platform, 'machine', lambda: 'x86_64')
    monkeypatch.setattr(H.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout='1\n'))
    assert H.native_abi() == 'arm64-v8a'
    monkeypatch.setattr(H.platform, 'system', lambda: 'Windows')
    monkeypatch.setenv('PROCESSOR_ARCHITEW6432', 'ARM64')
    with pytest.raises(RuntimeError, match='compatible Android worker'):
        H.native_abi()
    assert H.accelerator_name('AEHD (version 2.2) is installed and usable.') == 'aehd'
    assert H.accelerator_name('Hypervisor.Framework OS X is usable') == 'hvf'


def test_usb_merge_keeps_both_initial_versions_and_uses_content_baselines():
    from src.phone_usb import plan_sync
    assert plan_sync({'a.txt':'A'}, {'a.txt':'B'}, {}) == [('conflict','a.txt')]
    assert plan_sync({'a.txt':'A2'}, {'a.txt':'A'}, {'a.txt':'A'}) == [('push','a.txt')]
    assert plan_sync({'a.txt':'A'}, {'a.txt':'A2'}, {'a.txt':'A'}) == [('pull','a.txt')]
    assert plan_sync({}, {'a.txt':'A'}, {'a.txt':'A'}) == [('pull','a.txt')]
    assert plan_sync({'a.txt':'A'}, {'a.txt':'A'}, {}) == []


def test_usb_project_folder_refuses_symlink_and_hardlink_exports(tmp_path):
    from src.phone_usb import Folder
    outside=tmp_path/'private';outside.mkdir();(outside/'secret').write_text('secret')
    root=tmp_path/'projects';root.mkdir();(root/'owner').symlink_to(outside,target_is_directory=True)
    with pytest.raises(OSError):
        with Folder(root, ['owner','Android USB','pixel-standard']):pass
    (root/'owner').unlink();(root/'owner').mkdir(mode=0o700)
    with Folder(root,['owner','Android USB','pixel-standard']) as folder:
        folder.put('hello.txt', b'hello', expected=None)
        assert folder.read('hello.txt') == b'hello'
        with pytest.raises(RuntimeError):folder.put('hello.txt',b'overwrite',expected=None)
        import os
        os.link(outside/'secret', root/'owner/Android USB/pixel-standard/leak.txt')
        with pytest.raises(RuntimeError):folder.manifest()


def test_usb_typed_storage_round_trip_conflict_bounds_and_eject(tmp_path,monkeypatch):
    import base64,subprocess,threading,os
    from workstation import phone_usb as U
    from workstation.phone import PhoneError
    guest=tmp_path/'guest';guest.mkdir();monkeypatch.setattr(U,'DIRECTORY',str(guest))
    monkeypatch.setattr(U,'COUNT',2)
    class Phone:
        lock=threading.RLock();device='pixel_9';edition='standard';emulator=SimpleNamespace(pid=123)
        def _on(self):pass
        def mode(self):return 'android'
        def home(self):return tmp_path
        def adb(self,args,**kwargs):
            if args[0]=='push':
                import shutil
                shutil.copyfile(args[1],args[2]);return ''
            result=subprocess.run(' '.join(args[1:]),shell=True,capture_output=True,timeout=10)
            if result.returncode and not kwargs.get('quiet'):raise RuntimeError('guest command failed')
            return result.stdout if kwargs.get('binary') else result.stdout.decode()
    phone=Phone();key=U.operation(phone,'connect')['connection']
    data=b'hello Android';encoded=base64.b64encode(data).decode()
    got=U.operation(phone,'write',key,'a.txt',encoded)
    assert got['sha256']==U.digest(data)
    assert base64.b64decode(U.operation(phone,'read',key,'a.txt')['data_b64'])==data
    with pytest.raises(PhoneError):U.operation(phone,'write',key,'a.txt',encoded)
    U.operation(phone,'write',key,'b.txt',encoded)
    with pytest.raises(PhoneError,match='full'):U.operation(phone,'write',key,'c.txt',encoded)
    assert set(U.operation(phone,'list',key)['files'])=={'a.txt','b.txt'}
    U.operation(phone,'eject',key)
    with pytest.raises(PhoneError,match='ejected'):U.operation(phone,'list',key)
    assert (guest/'a.txt').read_bytes()==data
    key=U.operation(phone,'connect')['connection'];phone.device='galaxy_z_flip6'
    with pytest.raises(PhoneError,match='changed'):U.operation(phone,'list',key)


def test_usb_live_folder_replacement_is_refused(tmp_path):
    from src.phone_usb import Folder
    root=tmp_path/'projects';root.mkdir()
    with Folder(root,['owner','USB']) as folder:
        folder.put('a.txt',b'a',None)
        (root/'owner/USB').rename(root/'owner/moved')
        (root/'owner/USB').mkdir()
        with pytest.raises(RuntimeError,match='moved'):folder.put('b.txt',b'b',None)
    assert not (root/'owner/moved/b.txt').exists()


def test_usb_export_allows_the_desktop_uid_but_keeps_the_owner_root_private(tmp_path):
    import os,stat
    from src.phone_usb import Folder
    base=tmp_path/'projects';base.mkdir()
    with Folder(base,['owner','Android USB','pixel-standard']) as folder:
        folder.put('test.txt',b'hello',None)
        assert stat.S_IMODE((base/'owner').stat().st_mode)==0o700
        assert stat.S_IMODE((base/'owner/Android USB').stat().st_mode)==0o777
        assert stat.S_IMODE((base/'owner/Android USB/pixel-standard/test.txt').stat().st_mode)==0o666
        (base/'owner').chmod(0o755)
        with pytest.raises(RuntimeError,match='private'):folder.read('test.txt')


def test_usb_connection_syncs_both_ways_preserves_conflicts_and_stops_on_profile_change(tmp_path,monkeypatch):
    import base64
    from src import phone_usb as U,tool_execution as T,workstation_access as W
    monkeypatch.setattr(T,'projects_base',lambda:str(tmp_path))
    monkeypatch.setattr(T,'projects_root',lambda owner,**kw:str(tmp_path/owner))
    monkeypatch.setattr(W,'may_use',lambda *a,**kw:True)
    class Remote:
        def __init__(self):self.files={'shared.txt':b'Android version'};self.device='pixel_9'
        async def phone(self,account,action,**kw):
            assert account=='owner-account'
            if action=='status':return dict(state='on',device=self.device,edition='standard')
            assert kw['connection']=='private-lease'
            op=kw['operation'];name=kw.get('name')
            if op=='eject':return {'connected':False}
            if op=='list':return {'files':{n:{'sha256':U.digest(d),'bytes':len(d)} for n,d in self.files.items()}}
            if op=='read':return {'data_b64':base64.b64encode(self.files[name]).decode()}
            if op=='write':
                current=self.files.get(name)
                assert (U.digest(current) if current is not None else None)==kw.get('expected')
                self.files[name]=base64.b64decode(kw['data_b64']);return {}
            raise AssertionError(op)
    async def check():
        remote=Remote();item=U.Connection('owner',remote,'owner-account',{'device':'pixel_9','edition':'standard'},'private-lease')
        with item.folder() as folder:folder.put('shared.txt',b'Workstation version',None)
        await item.round()
        assert remote.files['shared.txt']==b'Workstation version'
        copy=next(n for n in remote.files if '(Android ' in n)
        assert remote.files[copy]==b'Android version'
        await item.round();assert len(remote.files)==2
        remote.files['from-phone.txt']=b'phone file'
        await item.round()
        with item.folder() as folder:
            assert folder.read('from-phone.txt')==b'phone file'
            folder.put('shared.txt',b'edited on desktop',U.digest(b'Workstation version'))
        await item.round();assert remote.files['shared.txt']==b'edited on desktop'
        remote.device='galaxy_z_flip6'
        with pytest.raises(RuntimeError,match='changed'):await item.round()
        assert item.stopping.is_set()
        remote.device='pixel_9'
        fresh=U.Connection('owner',remote,'owner-account',{'device':'pixel_9','edition':'standard'},'private-lease')
        U._connections['owner']=fresh
        try:
            await U.upload('owner','just-before-eject.txt',b'must reach Android')
            result=await U.eject('owner')
            assert result['connected'] is False and not result['error']
            assert remote.files['just-before-eject.txt']==b'must reach Android'
        finally:U._connections.pop('owner',None)
    asyncio.run(check())


def test_phone_stream_supplies_a_visible_crosshair_once_per_connection():
    request=b'\3'+struct.pack('>BHHHH',0,0,0,8,6)
    greeting=b'RFB 003.008\n\1\1'+b'\2\0\0\3'+struct.pack('>iii',7,-224,-239)
    stream=Stream(greeting+request*2)
    with pytest.raises(rfb.StreamEnded):
        rfb.serve(stream,lambda:(Image.new('RGB',(8,6)),'one'),lambda _:None,lambda:None,frame_interval=0)
    rect=struct.pack('>HHHHi',10,10,21,21,-239)
    assert bytes(stream.output).count(rect)==1
    offset=bytes(stream.output).index(rect)+len(rect)
    pixels=bytes(stream.output)[offset:offset+21*21*4]
    mask=bytes(stream.output)[offset+21*21*4:offset+21*21*4+21*3]
    assert pixels[(10*21+10)*4:(10*21+10)*4+3]==b'\xff\xff\xff'
    assert mask[10*3+1] & (0x80 >> (10%8))


def test_native_cleanup_retains_owned_children_after_launcher_exit_without_pid_reuse(monkeypatch):
    from workstation.native_android import host as H
    class Process:
        def __init__(self,pid,born):self.pid=pid;self.born=born
        def create_time(self):return self.born
        def is_running(self):return True
        def children(self,recursive=True):return [child]
    parent,child=Process(1,100),Process(2,200)
    processes={1:parent,2:child}
    monkeypatch.setattr(H,'psutil',SimpleNamespace(Process=lambda pid:processes[pid],Error=Exception))
    phone=object.__new__(H.NativePhone);phone.process_identity=100;phone._processes={}
    phone.emulator=SimpleNamespace(pid=1,poll=lambda:None)
    assert {p.pid for p in phone._process_family()}=={1,2}
    phone.emulator=SimpleNamespace(pid=1,poll=lambda:0)
    parent.born=999
    assert {p.pid for p in phone._process_family()}=={2}


def test_fold_cover_frame_uses_androids_actual_viewport_for_pixels_and_touch():
    from workstation.native_android.screen import normalize_viewport
    image=Image.new('RGB',(1080,2640),(0,0,0))
    for y in range(759,1881):image.paste((20,80,140),(0,y,1080,y+1))
    line='Viewport INTERNAL: displayId=0, orientation=0, logicalFrame=[0, 0, 720, 748], physicalFrame=[0, 759, 1080, 1881], deviceSize=[1080, 2640], isActive=[1]'
    cover=normalize_viewport(image,line)
    assert cover.size==(720,748)
    assert cover.getpixel((0,0))==(20,80,140)
    assert cover.getpixel((719,747))==(20,80,140)
    with pytest.raises(ValueError):normalize_viewport(image,line.replace('1881','99999'))


def test_fold_capture_can_already_be_the_logical_display():
    from workstation.native_android.screen import normalize_viewport
    image=Image.new('RGB',(720,748),(20,80,140))
    line='Viewport INTERNAL: displayId=0, orientation=0, logicalFrame=[0, 0, 720, 748], physicalFrame=[0, 759, 1080, 1881], deviceSize=[1080, 2640], isActive=[1]'
    assert normalize_viewport(image,line).size==(720,748)


def test_listener_attestation_ignores_an_exited_sibling(monkeypatch,tmp_path):
    from workstation.native_android import host as H
    class Gone(Exception):pass
    class Process:
        def __init__(self,gone=False):self.gone=gone
        def exe(self):return str(tmp_path/'emulator/qemu')
        def net_connections(self,kind):
            if self.gone:raise Gone()
            return [SimpleNamespace(status='LISTEN',laddr=SimpleNamespace(port=5587))]
    monkeypatch.setattr(H,'psutil',SimpleNamespace(Error=Gone,CONN_LISTEN='LISTEN'))
    phone=object.__new__(H.NativePhone);phone.port=5586;phone.system=SimpleNamespace(sdk=tmp_path)
    monkeypatch.setattr(phone,'_process_family',lambda:[Process(True),Process()])
    assert phone._owned()
    monkeypatch.setattr(phone,'_process_family',lambda:[Process(True)])
    assert not phone._owned()


def test_capture_and_grab_acquire_phone_before_screen_lock(monkeypatch):
    from workstation.native_android.screen import Screen
    held=[]
    class Lock:
        def __init__(self,name):self.name=name
        def __enter__(self):
            if self.name=='screen':assert 'phone' in held, 'screen lock must follow phone lock'
            held.append(self.name)
        def __exit__(self,*_):held.pop()
    phone=SimpleNamespace(lock=Lock('phone'),_active=lambda:None,stream_ready=lambda:True,touch=lambda:None,generation='one')
    screen=Screen(phone);screen.lock=Lock('screen');screen.size=screen.physical=(4,4)
    monkeypatch.setattr(screen,'refresh',lambda:Image.new('RGB',(4,4)))
    assert screen.frame()[0].size==(4,4)
    assert screen.grab('png')[1]=='image/png'


@pytest.mark.parametrize('rotation',[1,3])
def test_physical_fold_capture_uses_already_rotated_viewport_bounds(rotation):
    from workstation.native_android.screen import normalize_viewport
    image=Image.new('RGB',(2640,1080))
    image.paste((20,80,140),(730,10,1852,1070))
    line=f'Viewport INTERNAL: displayId=0, orientation={rotation}, logicalFrame=[0, 0, 748, 720], physicalFrame=[730, 10, 1852, 1070], deviceSize=[2640, 1080], isActive=[1]'
    cover=normalize_viewport(image,line)
    assert cover.size==(748,720)
    assert cover.getpixel((0,0))==cover.getpixel((747,719))==(20,80,140)
