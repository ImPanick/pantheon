# SPDX-License-Identifier: AGPL-3.0-or-later
"""Choose the phone's host independently of the desktop's backend.

A configured Android host never silently falls back to a shared workstation.
Desired device/image are app preferences; worker state describes the active VM.
The explicit web preview continues to use the original workstation producer.
"""
from __future__ import annotations
import asyncio
import os
import threading
from pathlib import Path
from workstation import protocol as P
from src.workstation_client import WorkstationClient,WorkstationError

URL_ENV='PANTHEON_ANDROID_URL'
TOKEN_ENV='PANTHEON_ANDROID_TOKEN_FILE'
PIN_ENV='PANTHEON_ANDROID_TLS_PIN'
PREF='android_phone'
_locks={}
_preferences_lock=threading.RLock()


def configured():return bool(os.environ.get(URL_ENV,'').strip())


def phone_for(owner,*,auth_manager=None):
    from src import workstation_access as wa
    if not configured():return wa.workstation_for(owner,auth_manager=auth_manager)
    if not wa.may_use(owner,auth_manager=auth_manager):raise WorkstationError('not_permitted',wa.NOT_PERMITTED_SENTENCE)
    account=wa.account_of(owner)
    try:token=Path(os.environ[TOKEN_ENV]).read_text().strip()
    except (KeyError,OSError):raise WorkstationError('unconfigured','The Android host pairing file is missing. Run its installer and mount the pairing file into Pantheon.') from None
    client=WorkstationClient(os.environ[URL_ENV],token,android_vm_endpoint=True,
                             tls_pin_override=os.environ.get(PIN_ENV,''))
    return PhoneClient(owner,client,auth_manager=auth_manager),account


class PhoneClient:
    native_android=True
    def __init__(self,owner,client,*,auth_manager=None):
        self.owner,self.client,self.auth_manager=owner,client,auth_manager

    def _read(self):
        from routes.prefs_routes import _load_for_user
        choice=_load_for_user(self.owner).get(PREF)
        if not isinstance(choice,dict):return None
        return {'device':choice.get('device') if isinstance(choice.get('device'),str) and choice.get('device') in P.PHONE_DEVICES else P.PHONE_DEFAULT_DEVICE,
                'edition':choice.get('edition') if choice.get('edition') in P.PHONE_EDITIONS else 'standard',
                'producer':'preview' if choice.get('producer')=='preview' else 'android'}

    def _save(self,choice):
        from routes.prefs_routes import _load_for_user,_save_for_user
        with _preferences_lock:
            prefs=_load_for_user(self.owner);prefs[PREF]=dict(choice);_save_for_user(self.owner,prefs)

    def _legacy(self):
        from src.workstation_access import workstation_for
        return workstation_for(self.owner,auth_manager=self.auth_manager)[0]

    async def _stop_preview(self,account,holder):
        try:
            await self._legacy().phone(account,'stop',holder=holder)
        except WorkstationError as error:
            if error.code not in ('off','unconfigured','unavailable'):
                raise

    async def _choice(self,account):
        choice=self._read()
        if choice is None:
            # Adopt the person's existing preference, never their VM or data.
            # A fresh native deployment can work without any desktop configured.
            try:state=await self._legacy().phone(account,'status',holder='person')
            except WorkstationError:state={}
            choice={'device':state.get('device') if isinstance(state.get('device'),str) and state.get('device') in P.PHONE_DEVICES else P.PHONE_DEFAULT_DEVICE,
                    'edition':state.get('edition') if state.get('edition') in P.PHONE_EDITIONS else 'standard',
                    'producer':'android'}
            self._save(choice)
        return choice

    async def _sync(self,account,choice,holder,*,changing=False):
        return await self.client.phone_choice(account,choice['device'],choice['edition'],holder=holder,changing=changing)

    def _lock(self):
        key=(id(asyncio.get_running_loop()),self.owner)
        return _locks.setdefault(key,asyncio.Lock())

    async def phone(self,account,action,*,holder='agent',**fields):
        async with self._lock():
            choice=await self._choice(account)
            previous_producer=choice['producer']
            changing=action in ('device','edition','start','install','preview')
            if holder=='agent' and changing:
                # Apply the authoritative holder gate BEFORE a desired choice
                # can be persisted and later executed by a person's poll.
                wanted=dict(choice)
                if action in ('device','edition'):wanted[action]=fields.get(action)
                if action in ('start','install') and fields.get('device') is not None:wanted['device']=fields['device']
                await self._sync(account,wanted,holder,changing=True)
            if action in ('start','install') and fields.get('device') is not None:
                if not isinstance(fields['device'],str) or fields['device'] not in P.PHONE_DEVICES:
                    raise WorkstationError('bad_request','Choose a device from the catalogue.')
                choice['device']=fields['device'];self._save(choice)
            if action in ('device','edition'):
                value=fields.get(action)
                allowed=P.PHONE_DEVICES if action=='device' else P.PHONE_EDITIONS
                if not isinstance(value,str) or value not in allowed:raise WorkstationError('bad_request','Choose a device or image from the catalogue.')
                choice[action]=value
                if action=='edition':
                    if previous_producer=='preview':await self._stop_preview(account,holder)
                    choice['producer']='android'
                self._save(choice)
            if action=='preview':
                if isinstance(fields.get('device'),str) and fields.get('device') in P.PHONE_DEVICES:choice['device']=fields['device']
                # Stop the independent VM before changing the explicit producer.
                await self.client.phone(account,'stop',holder=holder)
                legacy=self._legacy()
                from src.workstation_access import sync_config
                await sync_config(legacy)
                answer=await legacy.phone(account,'preview',holder=holder,device=choice['device'])
                choice['producer']='preview';self._save(choice)
                return dict(answer,edition=choice['edition'])
            if action in ('start','install'):
                if choice['producer']=='preview':await self._stop_preview(account,holder)
                choice['producer']='android';self._save(choice)
            elif choice['producer']=='preview':
                answer=await self._legacy().phone(account,action,holder=holder,**fields)
                return dict(answer,edition=choice['edition'])
            try:
                await self._sync(account,choice,holder)
                answer=await self.client.phone(account,action,holder=holder,**fields)
                return dict(answer,device=choice['device'],edition=choice['edition'],preview_available=True)
            except WorkstationError as error:
                if action not in ('status','device','edition'):raise
                return {'available':False,'state':'unavailable','mode':None,'isolation':'per_user_vm',
                        'device':choice['device'],'edition':choice['edition'],'why':error.message,
                        'preview_available':True,'stream_ready':False}

    async def control(self,account,holder):
        async with self._lock():
            choice=await self._choice(account)
            client=self._legacy() if choice['producer']=='preview' else self.client
            return await client.control(account,holder)

    async def phone_screen(self,account):
        async with self._lock():
            choice=await self._choice(account)
            if choice['producer']=='preview':return await self._legacy().phone_screen(account)
            await self._sync(account,choice,'person')
            return await self.client.phone_screen(account)

    def phone_screen_stream(self,account,viewer):
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def stream():
            async with self._lock():
                choice=await self._choice(account)
                client=self._legacy() if choice['producer']=='preview' else self.client
                if client is self.client:await self._sync(account,choice,viewer)
                context=client.phone_screen_stream(account,viewer)
                upstream=await context.__aenter__()
            try:yield upstream
            finally:await context.__aexit__(None,None,None)
        return stream()


def computer_in_workstation(content):
    """Side-effect-free routing classifier shared by the gate and dispatcher."""
    from src.agent_tools.computer_tools import parse_args
    args,problem=parse_args(content)
    if problem:return False
    return not (args.get('screen')=='phone' and configured())
