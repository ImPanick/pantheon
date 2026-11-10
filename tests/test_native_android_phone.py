# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phone routing, persisted intent, private takeover and pinned viewer protocol."""
import asyncio
import io
import struct
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
    phone.screen=SimpleNamespace(release_all=lambda:None,size=None)
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
