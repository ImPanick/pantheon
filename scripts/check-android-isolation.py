# SPDX-License-Identifier: AGPL-3.0-or-later
"""Disposable two-kernel security acceptance harness; no Android image or SDK.

Run in the VM host image with --network none, the checkout read-only,
and a fresh --output directory. Only fresh qcow2 overlays and cloud-init seeds
are used. The shipping Fleet, VmStation, qemu_argv and agentd are exercised.
Android's three listeners are explicitly fixtures, not Android proof.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from urllib.parse import urlsplit

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1],
                    help="read-only checkout containing workstation/")
parser.add_argument("--base-image", type=Path,
                    default=Path("/opt/pantheon-workstation/vm/ubuntu-cloud.img"),
                    help="verified Ubuntu cloud qcow2 from the VM host build")
parser.add_argument("--output", type=Path, required=True,
                    help="fresh empty result directory, never an existing service volume")
parser.add_argument("--timeout-seconds", type=int, default=650)
args = parser.parse_args()
SOURCE = args.source.resolve(strict=True)
if not (SOURCE / "workstation" / "vm.py").is_file():
    parser.error("--source must contain this checkout's workstation package")
if not 60 <= args.timeout_seconds <= 900:
    parser.error("--timeout-seconds must be between 60 and 900")
RESULTS = args.output.absolute()
if RESULTS.is_symlink() or (RESULTS.exists() and any(RESULTS.iterdir())):
    parser.error("--output must be a fresh empty directory without symlinks")
RESULTS.mkdir(parents=True, exist_ok=True)
BASE = args.base_image.resolve(strict=True)
sys.path.insert(0, str(SOURCE))
from workstation import protocol as P, vm
from workstation.agentd import make_server

START = time.monotonic()
ANN, BOB = P.account_name("isolation-alice"), P.account_name("isolation-bob")
PORTS = (5586, 5587, 21001)
HOST_TOKEN = P.TOKEN_PREFIX + secrets.token_urlsafe(32)
report = {"evidence_level": "two actual QEMU/TCG Linux guests; Android sockets are fixtures",
          "android_boot_verified": False, "kvm_verified": False,
          "google_sign_in_verified": False, "checks": [], "events": []}


def event(message):
    line = {"seconds": round(time.monotonic() - START, 2), "message": message}
    report["events"].append(line)
    print(json.dumps(line), flush=True)
    save()


def save():
    (RESULTS / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


def check(name, verdict, detail=None):
    report["checks"].append({"name": name, "passed": bool(verdict), "detail": detail})
    save()
    assert verdict, name


def request(url, path, token, body=None, timeout=720):
    p = urlsplit(url)
    conn = http.client.HTTPConnection(p.hostname, p.port, timeout=timeout)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        conn.request("POST" if body is not None else "GET", path,
                     json.dumps(body).encode() if body is not None else None, headers)
        response = conn.getresponse()
        return response.status, json.loads(response.read())
    finally:
        conn.close()


def call(url, token, name, account=None, body=None):
    _, path = P.route_path(name, account)
    status, answer = request(url, path, token, body)
    assert status == 200, (name, status, answer)
    return answer


GUEST = '''import os,socket,threading,subprocess
from pathlib import Path
from workstation.agentd import SingleUserSystem,make_server
ACCOUNT={account!r}
TOKEN={token!r}
system=SingleUserSystem(Path('/home'),backend='vm')
system.ensure(ACCOUNT)
project=Path('/projects')/{projects_folder!r}
project.mkdir(parents=True)
subprocess.run(['mount','-t','9p','-o','trans=virtio,version=9p2000.L,msize=262144',
                'pantheon-projects',str(project)],check=True)
for rel in ('.android/avd/private.txt','.pantheon/account-session-fixture.txt',
            'Documents/private.txt','.pantheon/phone-transfers/private.txt'):
    p=system.home(ACCOUNT)/rel;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text('fixture-only:'+ACCOUNT+':'+rel)
Path('/root/own-daemon-token').write_text(TOKEN)
os.chmod('/root/own-daemon-token',0o600)
def listener(port):
    s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    s.bind(('127.0.0.1',port));s.listen()
    while True:
        c,_=s.accept()
        with c:c.sendall(('fixture-only:'+ACCOUNT+':'+str(port)).encode())
for port in (5586,5587,21001):threading.Thread(target=listener,args=(port,),daemon=True).start()
make_server(system,TOKEN,bind='0.0.0.0',port=7040).serve_forever()
'''


class CloudMachine(vm.Machine):
    """Actual QEMU guests, minimal cloud seed instead of desktop provisioning."""

    def __init__(self, fleet, account):
        self.fleet, self.account = fleet, account
        self.dir = fleet.state / "machines" / account
        self.proc = None
        self.port = None
        self.token = ""

    def exists(self):
        return (self.dir / "disk.qcow2").exists()

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self.running():
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        self.token = vm.mint_machine_token(self.dir / "token")
        if not self.exists():
            subprocess.run(["qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b",
                            str(BASE), str(self.dir / "disk.qcow2"), "12G"], check=True,
                           stdout=subprocess.DEVNULL)
        seed = self.dir / "seed"
        seed.mkdir()
        files = []
        for source in sorted((SOURCE / "workstation").glob("*.py")):
            files.append({"path": "/opt/isolation/workstation/" + source.name,
                          "permissions": "0444", "encoding": "b64",
                          "content": base64.b64encode(source.read_bytes()).decode()})
        files += [{"path": "/opt/isolation/guest.py", "permissions": "0400",
                   "content": GUEST.format(account=self.account, token=self.token,
                                           projects_folder=P.project_folder_of(self.account))},
                  {"path": "/etc/systemd/system/pantheon-isolation.service",
                   "permissions": "0644", "content": "[Unit]\nAfter=network.target\n"
                   "[Service]\nWorkingDirectory=/opt/isolation\n"
                   "ExecStart=/usr/bin/python3 /opt/isolation/guest.py\n"
                   "[Install]\nWantedBy=multi-user.target\n"}]
        userdata = {"hostname": self.account, "manage_etc_hosts": False,
                    "ssh_pwauth": False, "package_update": False, "package_upgrade": False,
                    "write_files": files,
                    "runcmd": [["systemctl", "daemon-reload"],
                               ["systemctl", "start", "pantheon-isolation.service"]]}
        (seed / "user-data").write_text("#cloud-config\n" + json.dumps(userdata))
        (seed / "meta-data").write_text(json.dumps({"instance-id": self.account,
                                                   "local-hostname": self.account}))
        # No cloud datasource network probe and no package or license operation.
        (seed / "network-config").write_text("version: 2\nethernets:\n  id0:\n"
                                             "    match: {name: 'en*'}\n    dhcp4: true\n")
        vm.make_iso(self.dir / "app.iso", "cidata", seed, keep_modes=False)
        self.port = vm.free_port()
        self.argv = self.fleet.machine_argv(self)
        with open(self.dir / "qemu.log", "wb") as log:
            self.proc = subprocess.Popen(self.argv, stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=log)
        event("Started fresh TCG guest " + self.account)

    def why_not(self):
        return vm.tail(self.dir / "qemu.log", 6) or vm.tail(self.dir / "console.log", 6)

    def stop(self, *, graceful=True):
        if self.running():
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)


def main():
    report["source_sha256"] = {n: hashlib.sha256((SOURCE / "workstation" / n).read_bytes()).hexdigest()
                               for n in ("vm.py", "phone.py", "agentd.py", "protocol.py")}
    if sys.platform != "linux" or {name for _, name in socket.if_nameindex()} != {"lo"}:
        parser.error("run in a fresh Linux container with --network none; only loopback may be present")
    pin = re.search(r"^ARG CLOUD_IMAGE_SHA256=([0-9a-f]{64})$",
                    (SOURCE / "workstation" / "vm.Dockerfile").read_text(), re.MULTILINE)
    digest = hashlib.sha256()
    with BASE.open("rb") as image:
        while chunk := image.read(1024 * 1024):
            digest.update(chunk)
    if pin is None or digest.hexdigest() != pin[1]:
        parser.error("base image does not match this checkout's pinned cloud-image SHA-256; "
                     "build its VM host image rather than attaching any existing user disk")
    report["base_image_sha256"] = digest.hexdigest()
    scratch = tempfile.TemporaryDirectory(prefix="pantheon-tcg-isolation-")
    state = Path(scratch.name)
    projects = state / "projects"
    projects.mkdir()
    os.environ[P.PROJECTS_DIR_ENV] = str(projects)
    host_private = state / "host-private.txt"
    host_private.write_text("host-only-fixture")
    for account in (ANN, BOB):
        folder = projects / P.project_folder_of(account)
        folder.mkdir()
        (folder / "project-private.txt").write_text("project-fixture:" + account)
        (folder / "host-absolute-link").symlink_to(host_private)
        (folder / "host-relative-link").symlink_to("../../host-private.txt")
    fleet = vm.Fleet(state, accel="tcg", need_image=False, machine_factory=CloudMachine,
                     memory_mib=768, cpus=2, start_timeout=args.timeout_seconds,
                     idle_stop_s=0, max_running=2)
    host = make_server(fleet, HOST_TOKEN, bind="127.0.0.1", port=0,
                       station=vm.VmStation(fleet, HOST_TOKEN))
    threading.Thread(target=host.serve_forever, kwargs={"poll_interval": .05}, daemon=True).start()
    url = f"http://127.0.0.1:{host.server_address[1]}"
    try:
        event("Starting two minimal cloud guests; no Android SDK, desktop packages or existing disks")
        failures = []
        def ensure(account):
            try:
                call(url, HOST_TOKEN, "ensure", account, {})
                event("Real guest daemon ready " + account)
            except Exception as e:
                failures.append((account, str(e)))
        threads = [threading.Thread(target=ensure, args=(a,)) for a in (ANN, BOB)]
        for t in threads: t.start()
        deadline = time.monotonic() + args.timeout_seconds + 30
        while any(t.is_alive() for t in threads) and time.monotonic() < deadline:
            time.sleep(10)
            event("Waiting for cloud-init: " + ", ".join(
                a + ": " + vm.tail(fleet.machine_for(a).dir / "console.log", 1)[-150:]
                for a in (ANN, BOB)))
        assert not any(t.is_alive() for t in threads), "cloud guests did not boot within the requested deadline"
        assert not failures, failures
        ann, bob = fleet.machine_for(ANN), fleet.machine_for(BOB)
        def execute(account, command):
            answer = call(url, HOST_TOKEN, "exec", account,
                          {"command": command, "shell": "python", "timeout_s": 90})
            assert answer["exit_code"] == 0, answer
            return json.loads(answer["stdout"])
        facts = {}
        for account in (ANN, BOB):
            facts[account] = execute(account,
                "import os,json;from pathlib import Path;print(json.dumps({"
                "'uid':os.geteuid(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),"
                "'homes':[p.name for p in Path('/home').iterdir()],"
                "'has_kvm_node':Path('/dev/kvm').exists(),"
                "'project_mounts':[ln for ln in Path('/proc/mounts').read_text().splitlines() if ' 9p ' in ln]}))")
        report["guest_facts"] = facts
        check("two actual kernels", facts[ANN]["boot_id"] != facts[BOB]["boot_id"])
        check("adversary is guest root", facts[ANN]["uid"] == facts[BOB]["uid"] == 0)
        check("root Alice cannot see Bob home", BOB not in facts[ANN]["homes"])
        check("root Bob cannot see Alice home", ANN not in facts[BOB]["homes"])
        check("each guest mounted one fixture project export", all(
            len(facts[a]["project_mounts"]) == 1 for a in (ANN, BOB)))
        for account in (ANN, BOB):
            machine = fleet.machine_for(account)
            netdev = machine.argv[machine.argv.index("-netdev") + 1]
            check("only daemon hostfwd for " + account,
                  netdev == f"user,id=net0,hostfwd=tcp:127.0.0.1:{machine.port}-:7040")
        probe = '''import http.client,json,socket
from pathlib import Path
own=Path('/root/own-daemon-token').read_text()
out={{'local_listener_owners':[],'host_listener_exposure':[],'bad_auth':[],
      'foreign_files':[],'project_reads':[]}}
for port in {ports!r}:
    with socket.create_connection(('127.0.0.1',port),timeout=3) as s:
        out['local_listener_owners'].append(s.recv(200).decode())
    try:
        with socket.create_connection(('10.0.2.2',port),timeout=3) as s:
            out['host_listener_exposure'].append(s.recv(200).decode())
    except OSError:out['host_listener_exposure'].append(None)
for token in (own,None):
    c=http.client.HTTPConnection('10.0.2.2',{bob_port!r},timeout=5)
    headers={{'Content-Type':'application/json'}}
    if token:headers['Authorization']='Bearer '+token
    c.request('POST',{bob_path!r},json.dumps({{'action':'status'}}),headers)
    r=c.getresponse();out['bad_auth'].append([r.status,json.loads(r.read()).get('error')]);c.close()
for rel in ('.android/avd/private.txt','.pantheon/account-session-fixture.txt',
            'Documents/private.txt','.pantheon/phone-transfers/private.txt'):
    out['foreign_files'].append(Path('/home/{bob}/'+rel).exists())
project=Path('/projects')/{ann_folder!r}
(project/'guest-made-host-link').symlink_to({host_private!r})
for path in (Path('/projects')/{bob_folder!r}/'project-private.txt',
             project/'..'/{bob_folder!r}/'project-private.txt',
             project/'host-absolute-link',project/'host-relative-link',
             project/'guest-made-host-link'):
    try:out['project_reads'].append(path.read_text())
    except OSError:out['project_reads'].append(None)
out['own_project']=(project/'project-private.txt').read_text()
c=http.client.HTTPConnection('10.0.2.2',{host_port!r},timeout=5)
c.request('POST',{bob_path!r},json.dumps({{'action':'status'}}),
          {{'Authorization':'Bearer '+own,'Content-Type':'application/json'}})
r=c.getresponse();out['host_auth_status']=r.status;r.read();c.close()
print(json.dumps(out))
'''.format(ports=PORTS,bob_port=bob.port,
           bob_path=P.route_path("phone",BOB)[1],bob=BOB,host_port=host.server_address[1],
           ann_folder=P.project_folder_of(ANN),bob_folder=P.project_folder_of(BOB),
           host_private=str(host_private))
        attacks = execute(ANN, probe)
        report["root_alice_probe"] = attacks
        check("own simulated Android listeners are live",
              all(ANN in owner for owner in attacks["local_listener_owners"]))
        check("foreign console/emulator/ADB-server ports absent on VM host",
              attacks["host_listener_exposure"] == [None] * 3)
        check("Bob rejects Alice/no token", attacks["bad_auth"] == [[401,"unauthorized"]] * 2)
        # The host pairing token never enters a guest, even in a test script.
        status, answer = request(f"http://127.0.0.1:{bob.port}",
                                  P.route_path("phone",BOB)[1], HOST_TOKEN, {"action":"status"})
        check("Bob rejects the host daemon token", (status,answer.get("error")) == (401,"unauthorized"))
        check("VM host rejects Alice guest token", attacks["host_auth_status"] == 401)
        check("Bob device/account/document/transfer markers absent from Alice kernel",
              attacks["foreign_files"] == [False] * 4)
        check("Alice reads only her own project marker", attacks["own_project"] == "project-fixture:" + ANN)
        check("9p sibling and absolute/relative symlink probes disclose no foreign file",
              attacks["project_reads"] == [None] * 5)
        check("host fixture survives project probes", host_private.read_text() == "host-only-fixture")
        check("Bob project fixture survives probes", (projects / P.project_folder_of(BOB) /
              "project-private.txt").read_text() == "project-fixture:" + BOB)
        for account in (ANN, BOB):
            markers = execute(account, "import json;from pathlib import Path;"
                "print(json.dumps([p.read_text() for p in Path.home().rglob('private.txt')]))")
            check("own device/document/transfer markers survive " + account,
                  len(markers) == 3 and all(account in v for v in markers))
        report["verdict"] = "passed"
        event("Actual two-kernel/root/network/token isolation checks passed; Android remains untested")
    except Exception:
        report["verdict"] = "failed_or_blocked"
        report["error"] = traceback.format_exc()
        event("Acceptance did not complete; see exact error and guest console logs")
        raise
    finally:
        for account, machine in fleet._machines.items():
            machine.stop()
            for filename in ("console.log", "qemu.log"):
                src = machine.dir / filename
                if src.exists():
                    (RESULTS / f"{account}-{filename}").write_bytes(src.read_bytes())
        host.shutdown();host.server_close()
        report["elapsed_s"] = round(time.monotonic() - START, 2)
        save()
        scratch.cleanup()


if __name__ == "__main__":
    main()
