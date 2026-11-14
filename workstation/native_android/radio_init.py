# SPDX-License-Identifier: AGPL-3.0-or-later
"""Install the existing Internet-only rules before starting unprivileged Netsim."""
import ctypes
import os
import sys
from workstation import netrules

MODE='internet' if '--internet' in sys.argv else 'none'
# Slirp's signal pipe needs its own loopback. This namespace contains only
# this owner's disposable radio, with no private SDK keys or host control.
netrules.apply(netrules.ruleset(MODE,uids=(501,501),resolvers=[netrules.DOCKER_DNS]))
if netrules.in_force(netrules.GATE_TABLE)!=MODE:raise RuntimeError('Android network rules were not installed.')
libc=ctypes.CDLL(None,use_errno=True)
for bit in range(64):
    if libc.prctl(24,bit,0,0,0)!=0 and ctypes.get_errno()!=22:raise OSError('Could not drop the Android radio capability bound.')
if libc.prctl(38,1,0,0,0)!=0:raise OSError('Could not set no-new-privileges.')
os.setgroups([]);os.setgid(501);os.setuid(501)
for name in ('CapEff','CapPrm','CapAmb'):
    if netrules.capabilities(name):raise RuntimeError('Android radio retained capabilities.')
netrules.self_test()
os.execv('/opt/netsimd',['/opt/netsimd','--grpc-port','7443','--hci-port','0','--no-web-ui','--no-cli-ui',
                         '--no-shutdown','--logtostderr','--host-dns','127.0.0.11'])
