# SPDX-License-Identifier: AGPL-3.0-or-later
"""Managed immutable SDK image cache; private userdata is never evicted."""
from pathlib import Path,PurePosixPath
import hashlib
import json
import os
import shutil
import stat
import tempfile
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from workstation import phone as PH
from .boot_policy import build

BASE='https://dl.google.com/android/repository/sys-img/'


def sha(path,algorithm='sha256'):
    digest=hashlib.new(algorithm)
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1<<20),b''):digest.update(block)
    return digest.hexdigest()


def extract(archive,destination):
    root=Path(destination).resolve()
    with zipfile.ZipFile(archive) as package:
        if len(package.infolist())>20000:raise RuntimeError('The SDK archive contains too many files.')
        for item in package.infolist():
            name=PurePosixPath(item.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in item.filename:
                raise RuntimeError('The SDK archive contains an unsafe path.')
            path=root.joinpath(*name.parts)
            if not path.resolve().is_relative_to(root):raise RuntimeError('The SDK archive leaves its directory.')
            if item.is_dir():path.mkdir(parents=True,exist_ok=True);continue
            path.parent.mkdir(parents=True,exist_ok=True)
            mode=item.external_attr>>16
            if stat.S_ISLNK(mode):
                target=package.read(item).decode()
                if Path(target).is_absolute() or not (path.parent/target).resolve().is_relative_to(root):raise RuntimeError('Unsafe SDK archive link.')
                path.symlink_to(target);continue
            with package.open(item) as source,path.open('wb') as output:
                for block in iter(lambda:source.read(1<<20),b''):
                    if block.strip(b'\0'):
                        if shutil.disk_usage(root).free<1<<30:raise RuntimeError('Android install stopped to preserve 1 GiB free. Device data was kept.')
                        output.write(block)
                    else:output.seek(len(block),1)
                output.truncate(item.file_size)
            path.chmod(mode&0o777 or 0o644)


class ImageInstaller(PH.Installer):
    def __init__(self,host):
        super().__init__();self.host=host

    def start(self,package,*,accept,then=None):
        with self.host.lock,self.lock:
            if self.state.get('state')=='running':raise PH.PhoneError('busy','Another Android image is being installed.')
            if self.host.claims:raise PH.PhoneError('busy','Stop running Android VMs before changing the image cache.')
            self.state=dict(state='running',package=package,step='image',percent=0,started=time.time())
            self._thread=threading.Thread(target=self._work,args=(package,then),daemon=True);self._thread.start()
            return dict(self.state)

    def _work(self,package,then):
        ok=False
        try:
            self.install_image(package)
            ok=True
        except Exception as error:
            with self.lock:self.state.update(state='failed',why=str(error)[:500],finished=time.time())
        else:
            with self.lock:self.state.update(state='done',percent=100,finished=time.time())
        if then:then(ok)

    def install_image(self,package):
        from .host import write_private
        parts=PH.image_parts(package);tag=parts['tag'];abi=parts['abi']
        if tag not in ('google_apis','google_apis_playstore','default') or abi!=self.host.abi:
            raise RuntimeError('This image is not offered by this host adapter.')
        directory={'google_apis':'google_apis','google_apis_playstore':'google_apis_playstore','default':'android'}[tag]
        base=BASE+directory+'/'
        with urllib.request.urlopen(base+'sys-img2-3.xml',timeout=30) as response:metadata=response.read(8<<20)
        tree=ET.fromstring(metadata)
        record_file=self.host.root/'image-cache.json'
        records=json.loads(record_file.read_text()) if record_file.exists() else dict(self.host.config.get('managed_images',{}))
        spec=dict(records[package]) if package in records else None
        for entry in tree.iter('remotePackage'):
            channel=entry.find('channelRef')
            if entry.get('path')!=package or (channel is not None and channel.get('ref')!='channel-0'):continue
            complete=entry.find('./archives/archive/complete')
            current=dict(filename=complete.findtext('url'),size=int(complete.findtext('size')),
                      sha1=complete.findtext('checksum'),license=entry.find('uses-license').get('ref'))
            if spec is None:spec=current
            break
        if spec is None:raise RuntimeError('Google does not publish this image for the selected architecture.')
        if Path(spec['filename']).name!=spec['filename'] or not 0<spec['size']<8<<30:raise RuntimeError('Invalid SDK package metadata.')
        consent=json.loads(Path(self.host.config['consent']).read_text())
        if spec['license'] not in consent['license_ids']:raise RuntimeError('The host operator must accept this SDK image licence before installation.')
        licence=next((''.join(item.itertext()) for item in tree.iter('license') if item.get('id')==spec['license']),None)
        if licence is None:raise RuntimeError('The image catalogue has no matching SDK licence.')
        accepted_file=self.host.sdk/'licenses'/spec['license']
        accepted_hashes=accepted_file.read_text().splitlines() if accepted_file.exists() else []
        if hashlib.sha1(licence.encode()).hexdigest() not in accepted_hashes:
            raise RuntimeError('The SDK image terms changed. The host operator must accept the current agreement.')
        text_hash=hashlib.sha256(licence.encode()).hexdigest()
        if spec.get('license_text_sha256',text_hash)!=text_hash:raise RuntimeError('The pinned image licence does not match the accepted catalogue.')
        spec['license_text_sha256']=text_hash
        url=spec.get('url',base+spec['filename'])
        if url!=base+spec['filename']:raise RuntimeError('The recorded image is not from its official SDK catalogue path.')
        # Delete only explicitly managed immutable images, while no SDK guest is
        # running. AVDs, saved keys, files and snapshots are outside this tree.
        for old in list(records):
            if old==package:continue
            target=self.host.sdk/PH.image_parts(old)['sysdir']
            if target.is_dir():shutil.rmtree(target)
        target=self.host.sdk/parts['sysdir']
        if target.exists():raise RuntimeError('The image directory already exists; refusing to overwrite an unmanaged image.')
        with tempfile.TemporaryDirectory(prefix='image-',dir=self.host.root) as temporary:
            root=Path(temporary);archive=root/'package.zip';done=0
            with urllib.request.urlopen(url,timeout=60) as response,archive.open('wb') as output:
                for block in iter(lambda:response.read(1<<20),b''):
                    done+=len(block)
                    if done>spec['size'] or shutil.disk_usage(root).free<1<<30:raise RuntimeError('Android image download exceeded its size or available storage.')
                    output.write(block)
                    with self.lock:self.state.update(percent=int(done/spec['size']*75))
            if done!=spec['size'] or sha(archive,'sha1')!=spec['sha1']:raise RuntimeError('The Android image checksum did not match Google’s catalogue.')
            archive_hash=sha(archive)
            if spec.get('sha256',archive_hash)!=archive_hash:raise RuntimeError('The pinned Android archive SHA-256 did not match.')
            spec.update(sha256=archive_hash,url=url)
            unpack=root/'unpack';unpack.mkdir();extract(archive,unpack)
            source=unpack/abi
            if not (source/'system.img').is_file():raise RuntimeError('The SDK archive has no Android system image.')
            if tag!='google_apis_playstore':
                policy=build(source/'ramdisk.img',self.host.root/'boot-policies'/hashlib.sha256(package.encode()).hexdigest()[:16])
                self.host.config.setdefault('boot_policies',{})[package]=policy
                write_private(self.host.root/'boot-policies.json',json.dumps(self.host.config['boot_policies']))
            target.parent.mkdir(parents=True,exist_ok=True);source.replace(target)
            records[package]=spec;write_private(record_file,json.dumps(records,indent=2))
