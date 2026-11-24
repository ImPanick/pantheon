# Deploying Pantheon

This is the guide for putting Pantheon on a server and keeping it there: what runs, where it can
run, what each target needs from the host, and what's shipped versus what's still on the roadmap.
The [setup guide](setup.md) covers first-run configuration, providers, GPUs, voice and HTTPS in
detail; this page is the layer above it. What Pantheon does once it's up is in the
[capabilities reference](capabilities.md).

> **Pantheon will stay free and open source, forever.** It doesn't matter if you're one person
> running inference on a single GPU or a multi-billion-dollar firm. If it's useful, use it. That's
> why I created it. *Panick*
>
> The licence is [AGPL-3.0-or-later](../LICENSE); [what that asks of you](#the-licence-in-a-deployment)
> is short.

**Status key used on this page.** **Shipped** means it's in `dev` and the files named are in the
repository. **In progress** means a branch is building it now. **Roadmap** means nothing is built
yet and the section describes what it will take, so you aren't surprised later. Nothing on this
page that's marked Roadmap has a file behind it.

---

## The shape of it

Pantheon is a set of services, not one process. Three layers, and the rule that ties them
together is that **virtual machines are never nested inside each other by Pantheon**:

| Layer | What lives there |
|---|---|
| **0, the host** | Bare metal, or a VM on ESXi, Proxmox or Hyper-V. Supplies the CPU's virtualization extensions (`/dev/kvm` on Linux). |
| **1, Pantheon's services** | The app and its helpers (`pantheon`, `chromadb`, `searxng`, `ntfy`), and one service per VM family: `workstation-vm` for Linux desktops, `android-vm` for phones, a future one for iOS (nothing built). Each family is its own container, so they're siblings. |
| **The VMs** | One per person per family. Alice's desktop and Alice's phone are two VMs side by side, each in its family's service, never one inside the other. Bob gets his own pair. An admin can instead put people on one shared desktop VM, an account each (see [Own desktop VM or a shared one](#own-desktop-vm-or-a-shared-one)); phones stay one per person. |

A container isn't a virtualization layer, so on a bare-metal Linux host each person's desktop and
phone run one hardware-virtualization layer deep: as fast as they're going to get. Every hypervisor
underneath (a Pantheon host that's itself a VM, or Docker Desktop's WSL2 VM) adds one level of
nesting, and nested virtualization costs real speed. Phones feel it most.

Splitting the families into separate services is deliberate:

- **Host allocation per family.** An admin sizes the desktop pool and the phone pool separately
  (CPUs, memory, how many run at once) instead of one container juggling everything.
- **Restart one piece without stopping the rest.** Rebuild the app, or the phone service, and
  everyone's Linux desktops keep running. Only restarting `workstation-vm` itself touches desktops.
- **Another family slots in.** The VM lifecycle interface is kept backend-agnostic, so iOS, or a
  driver that asks a hypervisor for sibling VMs directly, is a new service, not a rewrite.

### The services

| Service | What it is | Image | State it keeps | Privileges |
|---|---|---|---|---|
| `pantheon` | The app: web UI, API, agent loop, scheduler, mail pollers | `ghcr.io/impanick/pantheon` (published from `main`) or built from `Dockerfile` | `./data`, `./logs` (bind mounts by default) | None added. Drops to `PUID`/`PGID`. |
| `chromadb` | Vector store for memory and document search | `chromadb/chroma:1.5.9`, pinned | `chromadb-data` volume | None added |
| `searxng` | Self-hosted web search | `searxng/searxng`, pinned | `searxng-data` volume | `CHOWN`, `SETGID`, `SETUID`, `DAC_OVERRIDE` only, everything else dropped |
| `ntfy` | Push for lock-screen approvals | `binwiederhier/ntfy:v2.38.2`, pinned | `ntfy-cache` volume | None added |
| `workstation-net` | Owns the network namespace the container workstation runs in, and the only thing allowed to write its firewall rules | built from `workstation/` | pairing volume | `NET_ADMIN`, `CHOWN`; all else dropped |
| `workstation` | Container backend for the desktop: one Ubuntu container, a Unix account and desktop per person. For hosts without KVM. | built from `workstation/` | `workstation-homes`, Android SDK volume | No added capability, `NET_RAW` dropped, one device-cgroup rule for `/dev/kvm` |
| `workstation-debian` / `-fedora` / `-rocky` | The same desktop on another distro, for people who pick it. Off unless its profile is on. | built from `workstation/` | own homes and pairing volumes | as `workstation` |
| `workstation-vm` | VM backend for the desktop: a QEMU/KVM machine per person | built from `workstation/vm.Dockerfile` | `workstation-vm` volume (each person's disk) | No added capability, no Docker socket, one device-cgroup rule for `/dev/kvm` (`c 10:232 rwm`) |
| `android-vm` | Phones: an Android VM per person, beside the desktops, on the host's KVM | built from `workstation/android-vm.Dockerfile` | `android-vm` volume (each person's phone, SDK and keys), `android-vm-pairing` | Starts with `NET_ADMIN` only to write its own kernel rules, then every process runs as uid 500 with no capability. No Docker socket, one device-cgroup rule for `/dev/kvm` (`c 10:232 rwm`) |

None of the workstation services mounts the Docker socket, runs privileged or publishes a port.
The pairing token each one shares with the app lives on a named volume the app reads read-only.

Only the `pantheon` image is published to a registry today. Every workstation image builds on the
machine that runs it, which matters as soon as you leave single-host Compose (below).

---

## Picking a target

| Target | Status | Use it when |
|---|---|---|
| [Docker Compose, one host](#docker-compose) | **Shipped**, the supported path | Almost always. A single big box runs everything, including every person's VMs. |
| [Compose plus a remote workstation](#a-workstation-on-another-machine) | **Shipped** | The desktops should live on a different machine (a Proxmox or libvirt VM, a spare box) from the app. |
| [Pantheon on a hypervisor host](#hypervisor-hosts) | **Shipped** (it's Compose, inside a VM) | Your estate is ESXi, vSphere, Proxmox or Hyper-V and Pantheon gets a VM like everything else. |
| [Windows with Docker Desktop](#windows-and-docker-desktop) | **Shipped**, for development | A workstation or laptop. Fine for building and testing, not where you want people's phones. |
| [Docker Swarm](#docker-swarm) | **Roadmap** | You already run Swarm and want Pantheon's stateless pieces scheduled there. |
| [Kubernetes and k3s](#kubernetes-and-k3s) | **Roadmap** | You run k3s or Kubernetes. Needs a chart and a KVM story per node. |
| [Direct hypervisor backend](#direct-hypervisor-backend) | **Roadmap** | You want each person's desktop and phone created as real VMs on vSphere, Proxmox or KubeVirt, with HA and migration. |

### One replica of the app

Whatever the target, run **exactly one** `pantheon` container. It's not a stateless web tier:

- The database is SQLite in `./data/app.db` by default, opened in WAL mode by one process.
  `DATABASE_URL` takes a PostgreSQL URL and the schema carries PostgreSQL DDL, but SQLite is what
  CI and the deployment host run. Treat PostgreSQL as unproven.
- The mail pollers (`PANTHEON_INPROCESS_POLLERS`) and the scheduled-task runner
  (`PANTHEON_INPROCESS_TASKS`) run inside the app. Two replicas would fire every task twice.
- Approvals, live agent runs and the workstation sessions they drive are held by that process.

Scale up, not out: more cores and memory on the host, more VMs per family. If you need the app to
survive a host failure today, that's a cold standby restored from a backup, not a second replica.

---

## Host requirements

**CPU virtualization.** VT-x or AMD-V, enabled in firmware, with the `kvm_intel` or `kvm_amd`
module loaded. Without it the desktop falls back to QEMU's TCG emulator (it works, about ten times
slower, and the Settings panel says so) and there are no phones.

```bash
grep -cE 'vmx|svm' /proc/cpuinfo   # > 0: the CPU has it
ls -l /dev/kvm                     # exists: the kernel exposes it
lsmod | grep kvm                   # kvm_intel or kvm_amd is loaded
```

`workstation-vm` doesn't need `/dev/kvm` passed in as a device. If the node isn't in the container,
it makes it (`mknod` is a default Docker capability) and opens it; the compose file's device-cgroup
rule is what lets that open succeed. On a host without KVM the open fails and the VM runs on TCG,
said out loud, instead of the container refusing to start. `PANTHEON_WORKSTATION_VM_ACCEL` forces
`kvm` or `tcg` if you'd rather it fail than fall back.

**Memory.** Budget it per running VM, plus the app. The defaults you'll be sizing against:

| Knob | Default | Who sets it |
|---|---|---|
| Desktop VM memory | Sized from the host, or what an admin chooses in Settings → Workstation (1 GiB to 256 GiB), else `PANTHEON_WORKSTATION_VM_MEMORY_MIB` | Admin |
| Desktop VM processors | The admin sets the pool (`workstation_vm_cpus_max`, 1 to 64, empty for all of the host's); each person picks their own count within it, applied on their machine's next start. `PANTHEON_WORKSTATION_VM_CPUS` (2) is the default for someone who hasn't picked. | Admin sets the ceiling, each person picks under it |
| Own VM or shared VM | `workstation_vm_placement` (`own` or `shared`) for people with no desktop yet, and `workstation_vm_placement_people` for each person by name. Settings → Workstation. | Admin |
| Desktop VM disk | `PANTHEON_WORKSTATION_VM_DISK_GIB=20` per machine (the shared machine is one disk for everyone on it) | Operator |
| Desktops running at once | `PANTHEON_WORKSTATION_VM_MAX_RUNNING=auto` | Operator |
| Idle desktop powered off after | `PANTHEON_WORKSTATION_VM_IDLE_MIN=30` minutes | Operator |
| Phone memory | `PANTHEON_ANDROID_VM_PHONE_MEMORY_MIB` each, sized from the host when empty | Operator |
| Phone processors | `PANTHEON_ANDROID_VM_PHONE_CPUS=4` each | Operator |
| Phones running at once | `PANTHEON_ANDROID_VM_MAX_RUNNING=auto` (sized from the host's memory) | Operator |
| Whole phone service | `PANTHEON_ANDROID_VM_SERVICE_CPUS`, `PANTHEON_ANDROID_VM_SERVICE_MEMORY` (0: no limit beyond the host's) | Operator |

A VM holds on the host only what its guest is actually using and gives freed pages back, so the
memory setting is a ceiling, not a reservation. Plan for the ceiling anyway on a shared box. If the
model server (vLLM, llama.cpp, Ollama) runs on the same host, its weights and KV cache come out of
the same pool. Measure the app and helpers on your own host with `docker stats` after a day of use;
a number written here would be wrong for your workload.

### Own desktop VM or a shared one

On the `vm` backend each person's desktop is either a VM of their own or an account on one VM
several people share. A dedicated server can give everyone their own machine; a small box can keep
most people on the shared one and give a machine of their own only to whoever needs the power.

- **The default** (`workstation_vm_placement`, Settings → Workstation → New people's machine) is
  for people who don't have a desktop yet. It ships as `own`. Changing it moves nobody who already
  has one.
- **Each person** (`workstation_vm_placement_people`, Settings → Workstation → Each person's
  machine) overrides the default by username. Moving someone to the shared machine powers their own
  VM off cleanly and keeps its disk, so moving them back finds their files where they left them.
- **The shared machine** is one VM named `shared` on the `workstation-vm` volume, sized like any
  other: the admin's memory, every processor in the pool. Sudo is off there whatever the sudo
  switch says, `/proc` hides other people's processes, and each person's home and projects folder
  are closed to everyone else by Unix permissions alone. Restart and reset act on that person's
  desktop and home, not the whole machine. Saving a starting point and choosing processors need a
  machine of one's own.
- **Phones** are unchanged: one Android VM per person in `android-vm`, wherever their desktop is.

Only the VM host takes a placement. The container backend is already one shared machine, and a
remote workstation is whatever the operator runs there. Spreading desktops over several
workstation hosts is planned, not built.

**Disk.** Each person's desktop is a copy-on-write disk on the `workstation-vm` volume, up to
`PANTHEON_WORKSTATION_VM_DISK_GIB`. The Ubuntu base image is made once, on first use. The Android
SDK and system images are several gigabytes and are downloaded once, after the operator accepts
Google's SDK licence. Put Docker's data root on fast local storage, not a network share.

**GPU** is optional and only for model serving, image generation and the Chatterbox voice:
`docker/gpu.nvidia.yml` or `docker/gpu.amd.yml`, covered in the [setup guide](setup.md).

---

## Docker Compose

### First run

Linux or macOS:

```bash
git clone https://github.com/ImPanick/pantheon.git
cd pantheon
cp .env.example .env
docker compose up -d --build
```

Windows (PowerShell):

```powershell
git clone https://github.com/ImPanick/pantheon.git
Set-Location pantheon
Copy-Item .env.example .env
docker compose up -d --build
```

Open `http://localhost:7000` once `docker compose ps` shows `pantheon` as `healthy`. That takes 35
to 60 seconds on a cold host: the app binds its port only after it's loaded embeddings, the vector
store and the MCP layer. The healthcheck asks `/api/ready` for a real answer, so `healthy` means
the database answers and the data directory takes a write, not just that a process exists.

Set `PANTHEON_ADMIN_PASSWORD` in `.env` before the first start to have the admin account made for
you; otherwise the first visit asks for it.

### Rebuild one service at a time

This is the payoff of splitting the stack. Build the service, then recreate only it:

```bash
docker compose build pantheon
docker compose up -d --no-deps pantheon
```

The same two lines work in PowerShell. `docker compose up -d --build <service>` also works, but
without `--no-deps` Compose will start (and, if their config changed, recreate) the services it
depends on. `--no-deps` makes it touch exactly the one you named.

What a restart of each service interrupts:

| Service | Restarting it interrupts | Doesn't interrupt |
|---|---|---|
| `pantheon` | Agent turns in flight, open browser tabs reconnect | Every desktop and phone, and what's running in them |
| `workstation-vm` | Every person's desktop VM. Each is shut down cleanly (`stop_grace_period: 2m`), because its disk is someone's work. | The app, the phones |
| `android-vm` | Every person's phone, each shut down cleanly (`stop_grace_period: 2m`) | The app, the desktops |
| `workstation` | The container-backend desktops | The VM backend |
| `workstation-net` | Recreate `workstation` right after (`docker compose up -d workstation`): a new namespace leaves the old one with loopback only, which fails closed | |
| `chromadb`, `searxng`, `ntfy` | Memory search, web search, push, for the seconds they're down | |

The workstation images build locally, so after pulling a new version run
`docker compose build --pull` before the per-service `up`, or the old image keeps running.

### Updating the app with a verified deploy

```bash
git pull
./scripts/pantheon-deploy run
```

`pantheon-deploy` builds, recreates the app, waits for `healthy` rather than sleeping a guessed
number of seconds, then verifies the routes, that every built-in MCP server imports in a fresh
interpreter, that the boot log has no traceback, and that the bytes in the image are the bytes in
git. It tags the image it replaces, and `./scripts/pantheon-deploy rollback` puts it back. It
won't roll back on its own, because schema migrations are forward-only and rolling back data is a
decision for you, not a script. Details in the [setup guide](setup.md#deploying-an-update).

### Profiles and overlays

Optional services sit behind profiles, set in `.env`:

```bash
COMPOSE_PROFILES=debian,fedora,rocky   # extra desktop distros people can pick
COMPOSE_PROFILES=chatterbox            # the GPU voice, with the NVIDIA overlay
```

Optional behaviour comes from overlays in `docker/`, listed in `COMPOSE_FILE`:

| Overlay | Adds |
|---|---|
| `docker/gpu.nvidia.yml`, `docker/gpu.amd.yml` | GPU passthrough for model serving and image work |
| `docker/android-host.yml` | Points the app at the native Android host worker (added for you by the bootstrap below) |
| `docker/workstation-remote.yml` | Uses a workstation on another machine and starts none locally |
| `docker/portable-storage.yml` | Named volumes instead of bind mounts, for Docker Desktop on Windows and macOS. Fresh installs only. |
| `docker/host-docker.yml` | Mounts the host's Docker socket into the app. High trust, off unless you mean it. |

**The separator differs by OS.** Compose splits `COMPOSE_FILE` on `:` on Linux and macOS and on
`;` on Windows:

```bash
COMPOSE_FILE=docker-compose.yml:docker/gpu.nvidia.yml        # Linux, macOS
```

```powershell
COMPOSE_FILE=docker-compose.yml;docker/gpu.nvidia.yml        # Windows
```

### Phones

**Shipped:** `android-vm`, a Compose service of its own beside `workstation-vm`, running one
Android VM per person on the host's KVM, with its own pool of processors, memory and running
phones that an admin sets independently of the desktops'. It comes up with the rest of the stack.
Nothing of Google's is in its image: an admin accepts Google's Android SDK licence once, at a
terminal on the host, and until then it downloads nothing and every phone shows the command:

```bash
docker compose up -d --build
docker compose run --rm android-vm accept-license
```

A phone never runs inside a desktop VM, whatever the desktop's backend. Without KVM in Docker
(a Mac), the phone runs on a small native host worker beside Docker instead, which uses WHPX on
Windows and Hypervisor.Framework on macOS; `docker/android-host.yml` points the app at it and keeps
`android-vm` from starting:

```bash
python3 -m workstation.native_android.bootstrap up --app docker --compose -- up -d --build
python3 -m workstation.native_android.bootstrap down --compose -- down
```

```powershell
py -3 -m workstation.native_android.bootstrap up --app docker --compose -- up -d --build
py -3 -m workstation.native_android.bootstrap down --compose -- down
```

The contract every VM service follows is in [VM services](vm-services.md); the host worker's
walkthrough is the [Android host guide](android-host.md).

### A workstation on another machine

**Shipped.** The desktops don't have to live on the Pantheon host. On the other machine (a Proxmox
or libvirt VM, a spare box with KVM):

```bash
sudo python3 workstation/install.py
```

It installs the workstation daemon and prints the lines to add to Pantheon's `.env`: the overlay,
the URL, a token and the certificate's SHA-256 fingerprint. Pantheon pins that certificate and
refuses to send the token over plain HTTP to a public address. Then `docker compose up -d` and
Settings → Workstation → On. With this overlay, no local workstation service starts.

### Exposing it

The app binds to `127.0.0.1:7000` by default. For anything beyond one machine, put it behind a
TLS-terminating reverse proxy and set:

```bash
APP_BIND=127.0.0.1                         # loopback, with the proxy on the same host
ALLOWED_ORIGINS=https://pantheon.example.com
SECURE_COOKIES=true
OAUTH_REDIRECT_BASE_URL=https://pantheon.example.com   # only for remote MCP OAuth
```

The live desktop and phone streams are WebSockets, so the proxy has to pass `Upgrade` and
`Connection` headers. Path prefixes, HTTP/2 and LAN or tailnet HTTPS are in the
[setup guide](setup.md#private-or-proxied-deployments).

Never publish `chromadb`, `searxng`, `ntfy` or a model server's port to the internet. They bind to
loopback for a reason.

### Operating it

- **Backups:** `./scripts/pantheon-backup snapshot` takes a consistent snapshot through SQLite's
  own backup API, safe while the app runs. Schedule it and ship the tarball off the box. See
  [backup and restore](backup-restore.md). Desktop disks live on the `workstation-vm` volume and
  are backed up with your Docker volume tooling, not this script.
- **Health:** `GET /api/ready` answers without a sign-in, `{"ready": true}` with 200 or 503.
  Docker doesn't restart an unhealthy container (`restart: unless-stopped` acts on exit), so alert
  on it.
- **Metrics:** `PANTHEON_METRICS_ENABLED=1` and `GET /metrics` in Prometheus format, scraped with
  an API token scoped `metrics:read`. Or push with `PANTHEON_OTLP_ENDPOINT`. See
  [metrics](setup.md#metrics--pointing-prometheus-and-grafana-at-pantheon).
- **As a systemd unit:** `pantheon-ui.service` for a native install, which waits for `/api/ready`
  before calling itself started.

---

## Windows and Docker Desktop

This is a development setup, and a good one for that. Know what's underneath it:

- **Docker Desktop's containers run inside WSL2, which is a Hyper-V VM.** Every Pantheon VM is
  therefore nested once. Desktops are usable. A phone running inside a desktop VM (the fallback
  above) is nested twice, and that's where boots crawl. Use the native Android host worker on
  Windows (WHPX), which runs the phone directly on Windows's hypervisor, and `android-vm` will
  keep phones out of the desktops once it lands.
- **KVM inside WSL2 needs nested virtualization.** On Windows 11 it's on by default; to be explicit,
  put this in `%UserProfile%\.wslconfig` and run `wsl --shutdown`:

  ```ini
  [wsl2]
  nestedVirtualization=true
  memory=48GB      # what WSL2, and so every container and VM, may use in total
  processors=12
  ```

  `memory` caps everything Docker runs, VMs included, so size it for the desktops and phones you
  want running at once.
- **The native phone host uses the Windows Hypervisor Platform.** Turn it on once, from an elevated
  PowerShell, and reboot:

  ```powershell
  Enable-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform -All
  ```

- **`COMPOSE_FILE` uses `;`** between files, as above.
- **Bind mounts from NTFS can't hold SQLite's write-ahead log** reliably; Pantheon detects that and
  falls back to `delete` journal mode, and says so once in the log. `docker/portable-storage.yml`
  keeps data on named volumes inside WSL2 instead, for fresh installs.

---

## Hypervisor hosts

Running Pantheon itself in a VM is ordinary Compose inside that VM. The one thing the hypervisor
has to do is pass the CPU's virtualization extensions through, or every desktop drops to TCG and
there are no phones. Each Pantheon VM is then one level of nesting.

**VMware ESXi / vSphere.** Edit the VM, CPU, and tick *Expose hardware assisted virtualization to
the guest OS*, with the VM powered off. That's `vhv.enable = "TRUE"` in the `.vmx`. Give the VM
enough vCPUs and memory for the desktops and phones you want running at once, on top of the app.

**Proxmox VE.** Set the VM's CPU type to `host`, so the guest sees VT-x or AMD-V, and make sure the
Proxmox node has nested KVM on:

```bash
qm set <vmid> --cpu host

cat /sys/module/kvm_intel/parameters/nested   # Intel: Y or 1 means on
cat /sys/module/kvm_amd/parameters/nested     # AMD

# if it's off (stop the VMs on that node first):
echo "options kvm_intel nested=1" > /etc/modprobe.d/kvm-nested.conf   # or kvm_amd
modprobe -r kvm_intel && modprobe kvm_intel                            # or kvm_amd
```

**Hyper-V (Windows Server).** With the VM off, from an elevated PowerShell:

```powershell
Set-VMProcessor -VMName pantheon -ExposeVirtualizationExtensions $true
```

**Bare-metal Linux is the best host for phones.** No nesting at all: each person's desktop and
phone run on the host's KVM directly. If your estate is all hypervisors, the next best option is
to keep the app in a VM and give the desktops their own machine with the
[remote workstation](#a-workstation-on-another-machine).

### Direct hypervisor backend

**Roadmap.** Today Pantheon makes each person's VMs itself, with QEMU, inside its VM-family
services. The design keeps that VM lifecycle (create, start, stop, reset, health) behind an
interface that doesn't assume QEMU, so a later driver can ask a hypervisor's API to create each
person's desktop and phone as sibling VMs on a cluster: Proxmox, vSphere/vCenter, or KubeVirt on
Kubernetes. That's what gets you HA, live migration and the cluster's own resource pools, with the
VMs at layer 1 on the cluster instead of nested inside Pantheon's host. None of those drivers is
built.

---

## Docker Swarm

**Roadmap.** There's no stack file in the repository, so `docker stack deploy` won't work against
`docker-compose.yml` as it stands. Swarm uses `docker stack deploy`, not Helm. What it will take:

- **Images from a registry.** `docker stack deploy` ignores `build:`. The app image is published;
  the workstation images aren't, so they'd be built and pushed to your registry first
  (`docker compose build`, then tag and push each).
- **The VM services don't fit Swarm as written.** Swarm services can't take a device-cgroup rule or
  a device, so `workstation-vm` would get no KVM and fall back to TCG. `network_mode:
  "service:workstation-net"`, which the container workstation depends on to share the gate's
  network namespace, isn't supported in a stack either, and `depends_on` is ignored.
- **The likely split:** run the app and its helpers (`pantheon` with `replicas: 1`, placed on the
  node that holds its volume; `chromadb`; `searxng`; `ntfy`) as a stack, and run the VM-family
  services with plain Compose on the KVM nodes, or use the remote workstation. A stack file that
  does exactly that is the planned deliverable.

---

## Kubernetes and k3s

**Roadmap.** There's no Helm chart yet. This section is the design the chart will follow, and the
annotation for anyone trying it by hand before then.

### The KVM annotation

**Pods that run VMs (`workstation-vm`, and `android-vm` when it lands) need `/dev/kvm`.** A
container can't open it unless the node's device cgroup allows it, and Kubernetes doesn't let a
pod spec add a device-cgroup rule the way Compose does. Without one of the three options below the
desktops run on TCG and there are no phones. Pick one:

1. **A device plugin (recommended).** It advertises `/dev/kvm` as an extended resource the
   scheduler counts and passes the device in. KubeVirt's `devices.kubevirt.io/kvm` resource is the
   common one; a generic device plugin configured for `/dev/kvm` works too. The pod asks for it:

   ```yaml
   resources:
     limits:
       devices.kubevirt.io/kvm: "1"
   ```

2. **A privileged pod with `/dev/kvm` mounted by `hostPath`.** It works, and it hands the pod the
   whole node. Only on dedicated nodes, tainted so nothing else lands there.

3. **Hand the VMs to KubeVirt.** Each person's desktop and phone becomes a KubeVirt
   `VirtualMachine` instead of a QEMU process in a pod. That needs the
   [direct hypervisor backend](#direct-hypervisor-backend), so it's the long-term option, not one
   that works today.

Only nodes with VT-x or AMD-V should take those pods. Label them yourself, or run Node Feature
Discovery and select on its CPU feature labels, and put a `nodeSelector` on the VM pods. If the
nodes are themselves VMs, the [hypervisor host](#hypervisor-hosts) rules apply to each node.

### How the Compose services map

| Compose | Kubernetes |
|---|---|
| `pantheon` | A `StatefulSet` (or `Deployment` with `strategy: Recreate`), **one replica**, a `ReadWriteOnce` volume for `/app/data`. Never `RollingUpdate`: two pods would open the same SQLite file. Probe `/api/ready` for readiness. |
| `chromadb`, `searxng`, `ntfy` | One `Deployment` each with a volume, `ClusterIP` services only |
| `workstation-net` + `workstation` | **One pod, two containers.** They share a network namespace in Compose (`network_mode: service:`), which is exactly what containers in a pod do. `NET_ADMIN` on the gate container only. |
| `workstation-vm`, `android-vm` | A `StatefulSet` per family on KVM nodes, with the KVM option above, a volume for the VM disks, and `terminationGracePeriodSeconds: 120` so machines shut down cleanly |
| `shm_size` | An `emptyDir` with `medium: Memory` mounted at `/dev/shm` (`sizeLimit: 1Gi` for the app, `2Gi` for the container workstation), or Firefox tabs crash |
| Pairing volumes | A shared volume or a `Secret` per service; the app mounts each read-only |
| `ports` bound to `127.0.0.1` | Nothing published but the app, through your ingress |

### k3s specifically

k3s is a fine single-node or small-cluster target. It ships containerd, Traefik as the ingress
(which passes the WebSocket upgrade the live desktop needs), and the `local-path` provisioner,
whose volumes are `ReadWriteOnce` and tied to one node. That's what the app's single replica wants
anyway; pin it to that node. On a single bare-metal k3s node the VMs are one layer deep, same as
Compose.

The planned chart's values: image registry, storage class, the KVM mode (`devicePlugin`,
`privileged` or `kubevirt`), and the per-family pools (CPUs, memory, how many run at once) that
admins otherwise set in Compose and Settings.

---

## The licence in a deployment

Pantheon is AGPL-3.0-or-later. Using it costs nothing and needs no permission, at any size. Three
things follow from the licence:

- **Run it unmodified, anywhere, for anyone:** nothing more to do. Every page already links to the
  source.
- **Change the code and let anyone but yourself use it over a network:** AGPL §13 asks you to offer
  those users your modified source. Publish your fork and set `PANTHEON_SOURCE_URL` to it, and the
  Source link on every page points there. See [the Source link](setup.md#the-source-link--and-what-a-modified-copy-owes-its-users).
- **Redistribute it:** keep `LICENSE`, `NOTICE` and `CREDITS.md` with it. Pantheon is a modified
  version of [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus), whose authors keep
  copyright over their parts, and the vendored third-party pieces keep their own licences.
