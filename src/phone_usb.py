# SPDX-License-Identifier: AGPL-3.0-or-later
"""An owner-bound USB shared folder using the existing projects export.

Only an explicit connection runs the two-way copier. Baselines and worker leases
stay in app memory, outside the exported filesystem. Eject waits for in-flight IO.
"""
import asyncio
import base64
import contextlib
import os
import secrets
import stat
import time
from workstation.phone_usb import filename,digest,LIMIT,TOTAL,COUNT,DIRECTORY


def plan_sync(local,remote,baseline):
    out=[]
    for name in sorted(local.keys() | remote.keys()):
        left,right=local.get(name),remote.get(name)
        if left==right:continue
        if left is None:kind='pull'
        elif right is None:kind='push'
        elif baseline.get(name)==right:kind='push'
        elif baseline.get(name)==left:kind='pull'
        else:kind='conflict'
        out.append((kind,name))
    return out


class Folder:
    """Pinned directory descriptors; never follow a workstation-created link."""
    def __init__(self,base,parts,owner_uid=None):
        self.base,self.parts=base,parts;self.fd=None
        self.owner_uids={os.geteuid(),0} | ({owner_uid} if owner_uid is not None else set())
    def private_root(self,fd):
        info=os.fstat(fd)
        return not info.st_mode & 0o007 and info.st_uid in self.owner_uids and info.st_gid == os.getegid()
    def __enter__(self):
        fd=os.open(self.base,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            for index, part in enumerate(self.parts):
                if not part or part in ('.','..') or '/' in part or '\\' in part:raise ValueError('Invalid USB folder.')
                created=False
                try:os.mkdir(part,0o700,dir_fd=fd);created=True
                except FileExistsError:pass
                child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                if index == 0 and not self.private_root(child):
                    os.close(child);raise RuntimeError('The user projects folder must be private before connecting USB.')
                if index > 0 and created:os.fchmod(child,0o777)
                os.close(fd);fd=child
            self.fd=fd;return self
        except BaseException:os.close(fd);raise
    def __exit__(self,*_):os.close(self.fd);self.fd=None
    def check(self):
        fd=os.open(self.base,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            for index, part in enumerate(self.parts):
                child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                if index == 0 and not self.private_root(child):
                    os.close(child);raise RuntimeError('The user projects folder is no longer private; eject USB.')
                os.close(fd);fd=child
            current,held=os.fstat(fd),os.fstat(self.fd)
            if (current.st_dev,current.st_ino)!=(held.st_dev,held.st_ino):
                raise RuntimeError('USB folder moved during synchronization; reconnect it.')
        finally:os.close(fd)
    def read(self,name):
        self.check()
        filename(name)
        fd=os.open(name,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW,dir_fd=self.fd)
        with os.fdopen(fd,'rb') as f:
            info=os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>LIMIT:
                raise RuntimeError('USB accepts regular, unlinked files up to 20 MiB.')
            data=f.read(LIMIT+1)
            after=os.fstat(f.fileno())
            if len(data)>LIMIT or (after.st_size,after.st_mtime_ns)!=(info.st_size,info.st_mtime_ns):
                raise RuntimeError('USB file changed while reading; retrying.')
            return data
    def manifest(self):
        self.check()
        files={};total=0;aliases=set()
        with os.scandir(self.fd) as entries:
            for entry in entries:
                if entry.name.startswith('.usb-'):continue
                filename(entry.name)
                if len(files)>=COUNT:raise RuntimeError('USB supports at most 64 files.')
                if entry.name.casefold() in aliases:raise RuntimeError('USB filenames must be unique without case differences.')
                aliases.add(entry.name.casefold());data=self.read(entry.name);total+=len(data)
                if total>TOTAL:raise RuntimeError('USB supports 128 MiB total.')
                files[entry.name]={'sha256':digest(data),'bytes':len(data)}
        return files
    def put(self,name,data,expected):
        filename(name)
        if len(data)>LIMIT:raise RuntimeError('USB file exceeds 20 MiB.')
        def current():
            try:return digest(self.read(name))
            except FileNotFoundError:return None
        if current()!=expected:raise RuntimeError('USB file changed; keeping the current version.')
        temporary='.usb-'+secrets.token_hex(12)
        fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600,dir_fd=self.fd)
        try:
            with os.fdopen(fd,'wb') as output:
                os.fchmod(output.fileno(),0o666)  # owner-root boundary admits app and desktop UID
                output.write(data);output.flush();os.fsync(output.fileno())
            if current()!=expected:raise RuntimeError('USB file changed; keeping the current version.')
            self.check()
            # Do not replace an existing name on initial copy (atomic no-clobber).
            if expected is None:
                os.link(temporary,name,src_dir_fd=self.fd,dst_dir_fd=self.fd,follow_symlinks=False)
                os.unlink(temporary,dir_fd=self.fd)
            else:os.replace(temporary,name,src_dir_fd=self.fd,dst_dir_fd=self.fd)
        finally:
            with contextlib.suppress(FileNotFoundError):os.unlink(temporary,dir_fd=self.fd)


_connections={}
_locks={}

def _lock(owner):return _locks.setdefault((id(asyncio.get_running_loop()),owner),asyncio.Lock())

def status(owner,profile=None):
    item=_connections.get(owner)
    if item and profile is not None and item.profile!=tuple(profile):return {'connected':False,'files':[]}
    return item.public() if item else {'connected':False,'files':[]}


class Connection:
    def __init__(self,owner,client,account,state,lease,owner_uid=None):
        from src.tool_execution import projects_base,projects_root
        from pathlib import Path
        self.owner,self.client,self.account=owner,client,account
        self.owner_uid=owner_uid;self.workstation_connected=False
        self.profile=(state['device'],state['edition']);self.lease=lease
        self.base=projects_base();self.parts=[Path(projects_root(owner,create=False)).name,'Android USB','-'.join(self.profile)]
        self.baseline={};self.files=[];self.error='';self.synced=None;self.stopping=asyncio.Event();self.task=None;self.io_lock=asyncio.Lock();self.closing=False
    def folder(self):return Folder(self.base,self.parts,self.owner_uid)
    def public(self):
        return {'connected':not self.stopping.is_set(),'device':self.profile[0],'edition':self.profile[1],'folder':'/'.join(self.parts[1:]),
                'android_folder':DIRECTORY,'workstation_connected':self.workstation_connected,'files':self.files,'error':self.error,'synced_at':self.synced}
    async def call(self,op,**fields):
        from src.workstation_client import WorkstationError
        try:return await self.client.phone(self.account,'usb',holder='person',operation=op,connection=self.lease,**fields)
        except WorkstationError as error:
            if error.code=='usb_ejected':self.stopping.set()
            raise
    async def remote_bytes(self,name,expected):
        answer=await self.call('read',name=name)
        raw=answer.get('data_b64','')
        if not isinstance(raw,str) or len(raw)>(LIMIT+2)//3*4:raise RuntimeError('USB response exceeds its byte limit.')
        data=base64.b64decode(raw,validate=True)
        if len(data)>LIMIT or digest(data)!=expected:raise RuntimeError('Android file changed while reading; retrying.')
        return data
    async def round(self):
        from src.workstation_access import may_use
        if not may_use(self.owner,auth_manager=getattr(self.client,'auth_manager',None)):
            self.stopping.set();raise RuntimeError('Workstation access was revoked; USB ejected.')
        state=await self.client.phone(self.account,'status',holder='person')
        if (state.get('device'),state.get('edition'))!=self.profile or state.get('state')=='off':
            self.stopping.set();raise RuntimeError('Android stopped or changed device; USB ejected.')
        if state.get('state')!='on':
            raise RuntimeError(state.get('why') or 'Waiting for Android; files remain queued for USB.')
        remote=(await self.call('list')).get('files')
        if not isinstance(remote,dict) or len(remote)>COUNT:raise RuntimeError('Invalid Android USB listing.')
        aliases=set();total=0
        for name,entry in remote.items():
            filename(name)
            if name.casefold() in aliases:raise RuntimeError('USB filenames differ only by case.')
            aliases.add(name.casefold())
            import re
            if not isinstance(entry,dict) or not re.fullmatch('[a-f0-9]{64}',str(entry.get('sha256',''))):raise RuntimeError('Invalid Android USB checksum.')
            size=entry.get('bytes')
            if type(size)!=int or not 0<=size<=LIMIT:raise RuntimeError('Invalid Android USB size.')
            total+=size
        if total>TOTAL:raise RuntimeError('Android USB exceeds 128 MiB.')
        # Each folder operation is bounded and only touches this connection's export.
        with self.folder() as folder:
            local=await asyncio.to_thread(folder.manifest)
            names=set(local)|set(remote)
            if len(names)>COUNT or len({n.casefold() for n in names})!=len(names):raise RuntimeError('USB has too many files or conflicting case names.')
            if sum(max(local.get(n,{}).get('bytes',0),remote.get(n,{}).get('bytes',0)) for n in names)>TOTAL:raise RuntimeError('Combined USB files exceed 128 MiB.')
            left={n:e['sha256'] for n,e in local.items()};right={n:e['sha256'] for n,e in remote.items()}
            for kind,name in plan_sync(left,right,self.baseline):
                if self.stopping.is_set():return
                if kind=='conflict':
                    data=await self.remote_bytes(name,right[name])
                    stem,extension=os.path.splitext(name)
                    copy=stem[:90]+' (Android '+right[name][:12]+')'+extension[:12]
                    if sum(max(local.get(n,{}).get('bytes',0),remote.get(n,{}).get('bytes',0)) for n in names)+(len(data) if copy not in names else 0)>TOTAL:raise RuntimeError('USB needs space for a conflict copy; no files were overwritten.')
                    if copy not in names and len(names)>=COUNT:raise RuntimeError('USB needs room for a conflict copy; no files were overwritten.')
                    existing=local.get(copy,{}).get('sha256')
                    if existing not in (None,right[name]):raise RuntimeError('USB conflict-copy name is already in use.')
                    if self.stopping.is_set():return
                    if existing is None:await asyncio.to_thread(folder.put,copy,data,None)
                    remote_copy=remote.get(copy,{}).get('sha256')
                    if remote_copy not in (None,right[name]):raise RuntimeError('Android conflict-copy name is already in use.')
                    if remote_copy is None:await self.call('write',name=copy,data_b64=base64.b64encode(data).decode(),expected=None)
                    names.add(copy);self.baseline[copy]=right[name]
                    local[copy]=remote[copy]={'sha256':right[name],'bytes':len(data)}
                    kind='push'
                if self.stopping.is_set():return
                if kind=='pull':
                    data=await self.remote_bytes(name,right[name])
                    if self.stopping.is_set():return
                    await asyncio.to_thread(folder.put,name,data,left.get(name))
                    self.baseline[name]=right[name]
                    local[name]={'sha256':right[name],'bytes':len(data)}
                else:
                    data=await asyncio.to_thread(folder.read,name)
                    if digest(data)!=left[name]:raise RuntimeError('Project file changed while syncing; retrying.')
                    await self.call('write',name=name,data_b64=base64.b64encode(data).decode(),expected=right.get(name))
                    self.baseline[name]=left[name]
                    remote[name]={'sha256':left[name],'bytes':len(data)}
            current=await asyncio.to_thread(folder.manifest)
            for name in left.keys() & right.keys():
                if left[name]==right[name]:self.baseline[name]=left[name]
            self.files=[{'name':n,**v,'synced':self.baseline.get(n)==v['sha256']} for n,v in sorted(current.items())];self.synced=time.time();self.error=''
    async def run(self):
        while not self.stopping.is_set():
            try:
                async with self.io_lock:
                    if not self.stopping.is_set():await self.round()
            except Exception as error:self.error=str(error)[:300]
            try:await asyncio.wait_for(self.stopping.wait(),5)
            except asyncio.TimeoutError:pass


async def connect(owner,client,account,*,holder='person'):
    async with _lock(owner):
        state=await client.phone(account,'status',holder=holder)
        if state.get('state')!='on' or state.get('mode')!='android':raise RuntimeError('Turn on Android before connecting USB.')
        old=_connections.get(owner)
        if old and not old.stopping.is_set():
            if old.profile==(state.get('device'),state.get('edition')):return old.public()
            old.stopping.set()
            if old.task:await old.task
        if not getattr(client,'native_android',False):raise RuntimeError('USB shared folders require the dedicated Android host.')
        from src import workstation_access as wa
        station=None;owner_uid=None
        try:
            station, station_account=wa.workstation_for(owner,auth_manager=getattr(client,'auth_manager',None))
            await wa.sync_config(station)
            await station.ensure(station_account)
            identity=await station.exec(station_account,'id -u',timeout_s=10)
            if identity.get('exit_code')!=0:raise RuntimeError('Cannot identify the workstation user.')
            owner_uid=int(identity.get('stdout','').strip())
        except Exception:
            station=None  # Independent phone/app USB still works without a desktop.
        lease=await client.phone(account,'usb',holder=holder,operation='connect')
        item=Connection(owner,client,account,state,lease['connection'],owner_uid)
        with item.folder() as folder:
            if station is not None:
                import shlex
                probe='USB-probe-'+secrets.token_hex(12)+'.txt';nonce=secrets.token_hex(24).encode()
                try:
                    await asyncio.to_thread(folder.put,probe,nonce,None)
                    relative='/'.join(item.parts[1:])+'/'+probe
                    result=await station.exec(station_account,'cat -- "$PANTHEON_PROJECTS"/'+shlex.quote(relative),timeout_s=10)
                    item.workstation_connected=result.get('exit_code')==0 and result.get('stdout','').encode()==nonce
                finally:
                    with contextlib.suppress(FileNotFoundError):os.unlink(probe,dir_fd=folder.fd)
        _connections[owner]=item;item.task=asyncio.create_task(item.run())
        return item.public()


async def eject(owner,*,holder='person'):
    async with _lock(owner):
        item=_connections.get(owner)
        if not item:return status(owner)
        if holder=='agent':
            # Gate the actual mutation at the worker, including takeover races.
            # Pending local files stay local after an explicit ejection.
            async with item.io_lock:
                await item.client.phone(item.account,'usb',holder='agent',operation='eject',connection=item.lease)
                item.closing=True;item.stopping.set()
            if item.task:await item.task
            return item.public()
        item.closing=True
        final_error=''
        async with item.io_lock:
            if not item.stopping.is_set():
                try:await item.round()
                except Exception as error:final_error='Final USB sync incomplete: '+str(error)[:200]
            else:final_error=item.error
            item.stopping.set()
        if item.task:await item.task
        try:await item.call('eject')
        except Exception:final_error=(final_error+' ' if final_error else '')+'USB disconnected; Android could not confirm its final disk flush.'
        item.error=final_error
        return item.public()


async def upload(owner,name,data):
    item=_connections.get(owner)
    if not item or item.stopping.is_set() or item.closing:raise RuntimeError('Connect USB before adding a file.')
    async with item.io_lock:
        if item.stopping.is_set() or item.closing:raise RuntimeError("USB was ejected.")
        with item.folder() as folder:
            listing=await asyncio.to_thread(folder.manifest)
            if len(listing)>=COUNT or sum(e['bytes'] for e in listing.values())+len(data)>TOTAL:raise RuntimeError('USB folder is full.')
            await asyncio.to_thread(folder.put,name,data,None)
            current=await asyncio.to_thread(folder.manifest)
            item.files=[{'name':n,**v,'synced':item.baseline.get(n)==v['sha256']} for n,v in sorted(current.items())]
    return {'ok':True,'queued':True,'name':name,'bytes':len(data),'sha256':digest(data),'destination':'/'.join(item.parts[1:])+'/'+name}


async def download(owner,name):
    item=_connections.get(owner)
    if not item:raise RuntimeError('No USB folder has been connected in this session.')
    with item.folder() as folder:return await asyncio.to_thread(folder.read,name)
