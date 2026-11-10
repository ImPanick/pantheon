# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pair an installed private Android SDK host with Pantheon.

Run this as the host operator, outside the app container. SDK packages remain
Google's licensed downloads. No account's personal AVDs or keys are imported.
"""
import argparse
from datetime import datetime,timezone
import json
import os
import platform
import secrets
from pathlib import Path
from .boot_policy import build
from .host import write_private,native_abi
from .control import SERVER_SHA256
from .images import sha
from .platform_support import check_python, console_path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('state','sdk','radio-binary','scrcpy-server'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--accept-sdk-license',action='store_true',help='The person running this accepts https://developer.android.com/studio/terms')
    parser.add_argument('--accept-arm-license',action='store_true',help='Accept the ARM image terms in https://dl.google.com/android/repository/sys-img/google_apis/sys-img2-3.xml')
    parser.add_argument('--internet',action='store_true',help='Enable the private packet network with Internet-only kernel rules.')
    parser.add_argument('--port',type=int,default=7993)
    parser.add_argument('--bind',default='127.0.0.1',help='Worker listen address. Linux Docker: use a private host bridge address reachable from the app.')
    parser.add_argument('--app-url',help='Worker URL reachable from the app, including scheme and port; remote connections require TLS.')
    parser.add_argument('--gpu',choices=('auto','host','software','swiftshader'),default='software')
    parser.add_argument('--windows-console-token',type=Path,help='Existing console token in the dedicated Windows worker profile; used read-only.')
    args=parser.parse_args();os.umask(0o077)
    host_options={}
    if args.windows_console_token:host_options['windows_console_token']=str(args.windows_console_token.resolve())
    try:
        check_python()
        console_path(host_options,args.state)
    except RuntimeError as error:parser.error(str(error))
    root=args.state.resolve();root.mkdir(parents=True,exist_ok=True,mode=0o700)
    sdk=args.sdk.resolve()
    try:abi=native_abi()
    except RuntimeError as error:parser.error(str(error))
    consent=root/'license-consent.json'
    if not consent.exists():
        if not args.accept_sdk_license or (abi=='arm64-v8a' and not args.accept_arm_license):
            parser.error('The host operator must explicitly accept the SDK and applicable ARM-image agreements.')
        ids=['android-sdk-license']+(['android-sdk-arm-dbt-license'] if abi=='arm64-v8a' else [])
        write_private(consent,json.dumps({'accepted_at':datetime.now(timezone.utc).isoformat(),'license_ids':ids,
                      'scope':'Installed SDK and selected development images on this private Android host','source':'Host operator CLI acceptance'},indent=2))
    if sha(args.scrcpy_server)!=SERVER_SHA256:parser.error('The scrcpy server must be the pinned version3.3.4 (see docs/android-host.md).')
    if not args.radio_binary.is_file():parser.error('The verified Linux Netsim executable is missing.')
    config_file=root/'host-config.json'
    if config_file.exists():parser.error('A host configuration already exists. Edit it explicitly; device data and pairing were preserved.')
    policies={}
    for tag in ('google_apis','default'):
        package='system-images;android-35;'+tag+';'+abi
        ramdisk=sdk/'system-images/android-35'/tag/abi/'ramdisk.img'
        if ramdisk.is_file():policies[package]=build(ramdisk,root/'boot-policies'/tag)
    pairing=root/'pairing/token'
    if not pairing.exists():write_private(pairing,secrets.token_urlsafe(48))
    config={'state':str(root),'sdk':str(sdk),'abi':abi,'consent':str(consent),'token_file':str(pairing),
            'radio_binary':str(args.radio_binary.resolve()),'scrcpy_server':str(args.scrcpy_server.resolve()),
            'boot_policies':policies,'internet':args.internet,'port':args.port,'bind':args.bind,'gpu':args.gpu,'max_running':1,'memory_mib':4096,'data_size_gib':2}
    config.update(host_options)
    write_private(config_file,json.dumps(config,indent=2)+'\n')
    print('Android host config: '+str(config_file))
    print('PANTHEON_ANDROID_PAIRING_DIR='+str(pairing.parent))
    address = args.app_url or ('http://' + ('host.docker.internal' if platform.system() in ('Darwin','Windows') else args.bind) + ':' + str(args.port))
    print('PANTHEON_ANDROID_URL='+address)
    if platform.system() == 'Linux' and args.bind == '127.0.0.1':
        print('Linux Docker bridge apps cannot reach this loopback listener. Set --bind to a private host bridge IP and --app-url to its reachable URL, or run the app in the host network.')
    print('Start: python -m workstation.native_android.server --config '+str(config_file))


if __name__=='__main__':main()
