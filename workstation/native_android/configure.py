# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pair an installed private Android SDK host with Pantheon.

Run this as the host operator, outside the app container. SDK packages remain
Google's licensed downloads. No account's personal AVDs or keys are imported.

Re-runnable: an existing `host-config.json` is merged, never replaced. Paths and
options given now update it; device data, the pairing token, recorded profiles
and boot policies already built are kept. `bootstrap.py` calls `prepare` on
every launch; this CLI is the same step for an operator who installs by hand.
"""
import argparse
import json
import os
import platform
import secrets
from pathlib import Path
from .boot_policy import build
from .host import write_private,native_abi
from .control import SERVER_SHA256
from .images import sha
from .platform_support import check_python, console_path, required_licenses, record_consent, accepted  # noqa: F401

def prepare(*,state,sdk,radio_binary,scrcpy_server,internet=None,port=None,bind=None,app_url=None,
            gpu=None,windows_console_token=None):
    """Write or merge `host-config.json` and return `(config_file, config)`.
    The operator's licence acceptance must already be recorded."""
    root=Path(state).resolve();root.mkdir(parents=True,exist_ok=True,mode=0o700)
    sdk=Path(sdk).resolve()
    abi=native_abi()
    if not accepted(root,abi):
        raise RuntimeError('The host operator must explicitly accept the SDK and applicable ARM-image agreements.')
    if sha(scrcpy_server)!=SERVER_SHA256:raise RuntimeError('The scrcpy server must be the pinned version3.3.4 (see docs/android-host.md).')
    if not Path(radio_binary).is_file():raise RuntimeError('The verified Linux Netsim executable is missing.')
    config_file=root/'host-config.json'
    config=json.loads(config_file.read_text()) if config_file.exists() else {
        'internet':False,'port':7993,'bind':'127.0.0.1','gpu':'software','max_running':1,'memory_mib':4096,'data_size_gib':2}
    if windows_console_token:config['windows_console_token']=str(Path(windows_console_token).resolve())
    console_path(config,root)  # Windows: the token must already be the worker profile's own.
    policies=dict(config.get('boot_policies',{}))
    for tag in ('google_apis','default'):
        package='system-images;android-35;'+tag+';'+abi
        ramdisk=sdk/'system-images/android-35'/tag/abi/'ramdisk.img'
        if package not in policies and ramdisk.is_file():policies[package]=build(ramdisk,root/'boot-policies'/tag)
    pairing=root/'pairing/token'
    if not pairing.exists():write_private(pairing,secrets.token_urlsafe(48))
    config.update({'state':str(root),'sdk':str(sdk),'abi':abi,'consent':str(root/'license-consent.json'),'token_file':str(pairing),
                   'radio_binary':str(Path(radio_binary).resolve()),'scrcpy_server':str(Path(scrcpy_server).resolve()),
                   'boot_policies':policies})
    for key,value in (('internet',internet),('port',port),('bind',bind),('app_url',app_url),('gpu',gpu)):
        if value is not None:config[key]=value
    write_private(config_file,json.dumps(config,indent=2)+'\n')
    return config_file,config


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('state','sdk','radio-binary','scrcpy-server'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--accept-sdk-license',action='store_true',help='The person running this accepts https://developer.android.com/studio/terms')
    parser.add_argument('--accept-arm-license',action='store_true',help='Accept the ARM image terms in https://dl.google.com/android/repository/sys-img/google_apis/sys-img2-3.xml')
    parser.add_argument('--internet',action='store_true',default=None,help='Enable the private packet network with Internet-only kernel rules.')
    parser.add_argument('--no-internet',dest='internet',action='store_false',help='Turn the private packet network off.')
    parser.add_argument('--port',type=int)
    parser.add_argument('--bind',help='Worker listen address. Linux Docker: use a private host bridge address reachable from the app.')
    parser.add_argument('--app-url',help='Worker URL reachable from the app, including scheme and port; remote connections require TLS.')
    parser.add_argument('--gpu',choices=('auto','host','software','swiftshader'))
    parser.add_argument('--windows-console-token',type=Path,help='Existing console token in the dedicated Windows worker profile; used read-only.')
    args=parser.parse_args();os.umask(0o077)
    host_options={}
    if args.windows_console_token:host_options['windows_console_token']=str(args.windows_console_token.resolve())
    try:
        check_python()
        console_path(host_options,args.state)
        abi=native_abi()
    except RuntimeError as error:parser.error(str(error))
    root=args.state.resolve();root.mkdir(parents=True,exist_ok=True,mode=0o700)
    if not accepted(root,abi):
        if not args.accept_sdk_license or (abi=='arm64-v8a' and not args.accept_arm_license):
            parser.error('The host operator must explicitly accept the SDK and applicable ARM-image agreements.')
        record_consent(root,required_licenses(abi),source='Host operator CLI acceptance')
    try:
        config_file,config=prepare(state=root,sdk=args.sdk,radio_binary=args.radio_binary,scrcpy_server=args.scrcpy_server,
                                   internet=args.internet,port=args.port,bind=args.bind,app_url=args.app_url,gpu=args.gpu,
                                   windows_console_token=args.windows_console_token)
    except RuntimeError as error:parser.error(str(error))
    print('Android host config: '+str(config_file))
    print('PANTHEON_ANDROID_PAIRING_DIR='+str(Path(config['token_file']).parent))
    address = config.get('app_url') or ('http://' + ('host.docker.internal' if platform.system() in ('Darwin','Windows') else config['bind']) + ':' + str(config['port']))
    print('PANTHEON_ANDROID_URL='+address)
    if platform.system() == 'Linux' and config['bind'] == '127.0.0.1':
        print('Linux Docker bridge apps cannot reach this loopback listener. Set --bind to a private host bridge IP and --app-url to its reachable URL, or run the app in the host network.')
    print('Start: python -m workstation.native_android.server --config '+str(config_file))


if __name__=='__main__':main()
