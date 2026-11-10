"""USB acceptance must not masquerade as delivery or eject on contention."""
import asyncio
import base64
import json
from types import SimpleNamespace

import pytest

from src import phone_usb as U, phone_runtime as R
from src.workstation_client import WorkstationError


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    from src import tool_execution as T, workstation_access as W
    monkeypatch.setattr(T, 'projects_base', lambda: str(tmp_path))
    monkeypatch.setattr(T, 'projects_root', lambda owner, **kw: str(tmp_path / owner))
    monkeypatch.setattr(W, 'may_use', lambda *a, **kw: True)
    class Remote:
        native_android = True
        def __init__(self):
            self.files = {}; self.failure = None; self.state = 'on'; self.person = False
        async def phone(self, account, action, holder='person', **kw):
            if self.failure: raise self.failure
            if action == 'status':
                return dict(state=self.state, device='pixel_9', edition='standard', mode='android')
            if holder == 'agent' and self.person: raise WorkstationError('busy', 'Person has control')
            op = kw['operation']; name = kw.get('name')
            if op == 'list': return {'files': {n: {'sha256': U.digest(d), 'bytes': len(d)} for n,d in self.files.items()}}
            if op == 'read': return {'data_b64': base64.b64encode(self.files[name]).decode()}
            if op == 'write':
                current = self.files.get(name)
                assert (U.digest(current) if current is not None else None) == kw['expected']
                self.files[name] = base64.b64decode(kw['data_b64']); return {}
            if op == 'eject': return {'connected': False}
            if op == 'connect': return {'connection': 'lease'}
            raise AssertionError(op)
    remote = Remote()
    item = U.Connection('owner', remote, 'account', {'device':'pixel_9','edition':'standard'}, 'lease')
    monkeypatch.setitem(U._connections, 'owner', item)
    return item, remote


def test_upload_is_queued_until_android_acknowledges_and_recovers_after_busy(bridge):
    item, remote = bridge
    async def run():
        data = b'PNG test bytes'
        accepted = await U.upload('owner', 'screenshot.png', data)
        assert accepted['ok'] and accepted['queued'] and remote.files == {}
        assert item.public()['files'][0]['synced'] is False
        remote.failure = WorkstationError('busy', 'Device busy')
        with pytest.raises(WorkstationError): await item.round()
        assert not item.stopping.is_set()
        remote.failure = None
        await item.round()
        assert remote.files['screenshot.png'] == data
        assert item.public()['files'][0]['synced'] is True
    asyncio.run(run())


def test_transient_unavailable_does_not_revoke_the_connection(bridge):
    item, remote = bridge
    async def run():
        remote.failure = WorkstationError('unavailable', 'Transfer timed out')
        with pytest.raises(WorkstationError): await item.call('list')
        assert not item.stopping.is_set()
        remote.failure = None; remote.state = 'unavailable'
        with pytest.raises(RuntimeError): await item.round()
        assert not item.stopping.is_set()
        remote.state = 'on'; await item.round()
        remote.state = 'off'
        with pytest.raises(RuntimeError, match='stopped'): await item.round()
        assert item.stopping.is_set()
    asyncio.run(run())


def test_busy_status_keeps_its_identity_in_phone_client(monkeypatch):
    class Worker:
        async def phone_choice(self, *a, **kw): return {}
        async def phone(self, *a, **kw): raise WorkstationError('busy', 'Temporary lock contention')
    client = R.PhoneClient('owner', Worker())
    monkeypatch.setattr(client, '_read', lambda: dict(device='pixel_9', edition='standard', producer='android'))
    with pytest.raises(WorkstationError) as error:
        asyncio.run(client.phone('account', 'status', holder='person'))
    assert error.value.code == 'busy'


def test_agent_eject_cannot_bypass_person_control_or_drop_queued_bytes(bridge):
    item, remote = bridge
    async def run():
        await U.upload('owner','queued.txt',b'keep me')
        remote.person = True
        with pytest.raises(WorkstationError): await U.eject('owner',holder='agent')
        assert not item.stopping.is_set() and not item.closing
        with item.folder() as folder: assert folder.read('queued.txt') == b'keep me'
        remote.person = False
        result = await U.eject('owner',holder='agent')
        assert not result['connected']
        with item.folder() as folder: assert folder.read('queued.txt') == b'keep me'
    asyncio.run(run())


def test_computer_usb_actions_reach_the_coordinator_as_agent(monkeypatch):
    from src.agent_tools.computer_tools import ComputerTool, parse_args
    async def state(*a, **kw):return dict(state='on',device='pixel_9',edition='standard')
    client = SimpleNamespace(native_android=True,phone=state)
    monkeypatch.setattr(R,'phone_for',lambda owner:(client,'account'))
    calls=[]
    async def connect(owner, worker, account, *, holder):
        calls.append(('connect',owner,worker,account,holder));return {'connected':True}
    async def eject(owner, *, holder):
        calls.append(('eject',owner,holder));return {'connected':False}
    monkeypatch.setattr(U,'connect',connect);monkeypatch.setattr(U,'eject',eject)
    monkeypatch.setattr(U,'status',lambda owner, profile=None: {'connected':False,'owner_check':owner})
    async def run():
        for action in ('usb_status','usb_connect','usb_eject'):
            args, problem = parse_args({'action':action})
            assert not problem and args['screen']=='phone'
            result=await ComputerTool().execute(json.dumps(args),{'owner':'alice'})
            assert result['exit_code']==0 and 'usb' in result and 'images' not in result
    asyncio.run(run())
    assert calls==[('connect','alice',client,'account','agent'),('eject','alice','agent')]


def test_mobile_skills_are_discoverable_with_their_actual_tools(tmp_path):
    from services.memory.skills import SkillsManager
    sm=SkillsManager(str(tmp_path))
    rows={s['name']:s for s in sm.injectable_skills(owner='alice',active_toolsets=['computer'])}
    assert {'workstation-phone','android-mobile-qa'} <= rows.keys()
    assert 'android-usb-files' not in rows
    rows={s['name']:s for s in sm.injectable_skills(owner='alice',active_toolsets=['computer','bash'])}
    assert rows['android-usb-files']['status']=='published'


def test_revoked_lease_ejects_but_a_timeout_does_not(bridge):
    item, remote = bridge
    async def run():
        remote.failure=WorkstationError('usb_ejected','Reconnect USB')
        with pytest.raises(WorkstationError):await item.call('list')
        assert item.stopping.is_set()
    asyncio.run(run())


def test_usb_status_is_observation_but_connection_mutations_keep_the_gate():
    from src.tool_capabilities import capabilities_for_action, ToolEffect
    look=capabilities_for_action('computer',json.dumps({'action':'usb_status'}))
    assert look.effects == frozenset({ToolEffect.READ_WORKSPACE})
    for action in ('usb_connect','usb_eject'):
        cap=capabilities_for_action('computer',json.dumps({'action':action}))
        assert ToolEffect.EXECUTE_CODE in cap.effects


def test_media_scan_quotes_one_filename_and_is_best_effort():
    from workstation.phone_usb import scan_media
    from workstation.phone import PhoneError
    import shlex
    calls=[]
    def call(args,**kw):calls.append((args,kw));raise PhoneError('unavailable','Indexer unavailable')
    path='/sdcard/Download/PantheonUSB/screenshot 12.png'
    scan_media(call,path)
    args,kw=calls[0]
    assert shlex.split(args[1])==['content','call','--uri','content://media','--method','scan_file','--arg',path]
    assert kw['timeout']==5 and kw['quiet']


def test_connect_does_not_reuse_previous_profile_before_background_poll(bridge, monkeypatch):
    item, remote = bridge
    from src import workstation_access as W
    monkeypatch.setattr(W,'workstation_for',lambda *a,**kw: (_ for _ in ()).throw(RuntimeError('Desktop not configured')))
    item.profile=('galaxy_z_flip6','standard')
    async def run():
        answer=await U.connect('owner',remote,'account',holder='agent')
        assert item.stopping.is_set()
        assert answer['device']=='pixel_9' and answer['folder'].endswith('pixel_9-standard')
        current=U._connections['owner'];current.stopping.set()
        await current.task
    asyncio.run(run())
