# VM services

Pantheon gives each person machines of their own: a Linux desktop and an
Android phone today, and possibly an iOS device later. Each family of machines
runs in a **service of its own**, side by side. No VM ever runs inside another
VM.

```
layer 0   the host (bare metal, or the VM your hypervisor gives Pantheon)
layer 1   Pantheon and its services, in parallel:
            pantheon          the app
            workstation-vm    each person's Linux desktop VM
            android-vm        each person's Android VM
            (ios-vm)          a future family slots in here
```

Before 2026-11-16 the phone ran inside the person's desktop VM. Under Docker
Desktop that put Android three hypervisors deep, where it stalled before its
display, and it tied the phone to whatever system the desktop runs (Ubuntu,
Debian, Fedora, Rocky, or a person's own image). Now the desktop is never an
Android endpoint, whatever its backend (`src/workstation_client.py`,
`tests/test_a_phone_never_runs_inside_a_desktop.py`).

## What every VM service does

A new family (iOS, say) is another service built the same way. It needs no
change to the others.

1. **Its own compose service, image and volume.** Restarting or rebuilding one
   family never interrupts the others' VMs. No `depends_on` between them, and
   none from `pantheon` to them: Pantheon runs without any of them.
2. **One VM per person.** Each person's VM, data and keys sit in a folder
   named for their account, and no account can reach another's.
3. **The workstation protocol over HTTP with a bearer token**
   (`workstation/protocol.py`). `GET /v1/health` answers `agent`,
   `protocol`, `backend` and `why`. Per-account routes live under
   `/v1/users/{account}/…`. The token is made by the service in its own pairing
   volume, `root:<PGID> 0640`, and Pantheon mounts that volume read-only.
4. **One sentence when it can't run.** No KVM, a licence not yet accepted, an
   install in progress: health answers 200 with `why`, and every per-account
   route answers `unavailable` with that same sentence. The panel shows it.
5. **An admin's pool, set on the service.** How many VMs may run at once
   (`auto` sizes it to the host), each VM's memory and CPUs, and Docker limits
   for the whole service. These bound what a person can ask for in Settings.
6. **Least privilege.** Not privileged, no Docker socket, no published port.
   It gets only the device-cgroup rule for `/dev/kvm`, plus whatever it needs
   once at start-up.
7. **Pantheon routes by family, never by fallback.** Each family has its own
   URL and token file (`PANTHEON_WORKSTATION_VM_URL`, `PANTHEON_ANDROID_URL`),
   and Pantheon never sends one family's work to another family's service.

| Family  | Service          | Port | State volume     | Pairing volume           | Pantheon reads                    |
|---------|------------------|------|------------------|--------------------------|-----------------------------------|
| Linux   | `workstation-vm` | 7040 | `workstation-vm` | `workstation-vm-pairing` | `PANTHEON_WORKSTATION_VM_URL`     |
| Android | `android-vm`     | 7993 | `android-vm`     | `android-vm-pairing`     | `PANTHEON_ANDROID_URL`            |

## The Android VM service

`android-vm` runs the native Android host (`workstation/native_android/`) in a
Linux container on KVM. Each person gets one Android Emulator VM, with a
private SDK home, adb key and data of their own.

- **Licence.** Nothing of Google's is in the image. An admin accepts Google's
  Android SDK License once, at a terminal on the Pantheon host:
  `docker compose run --rm android-vm accept-license`. Until then the service
  downloads nothing, and every phone shows the command. No environment
  variable accepts it.
- **Network.** At start-up, kernel rules cover every process the service runs
  (uid 500). They allow Google's repository and, when phones have internet,
  the public internet. Pantheon, the other services and your LAN are blocked.
  Then the service drops every capability for good.
- **Radio.** Each phone's Netsim (Wi-Fi and Bluetooth) is a process of its own
  on a loopback port of its own. The emulator reaches it only through an
  authenticated proxy with a fresh secret per phone.
- **Pool.** `PANTHEON_ANDROID_VM_MAX_RUNNING` sets how many phones run at once,
  `PANTHEON_ANDROID_VM_PHONE_MEMORY_MIB` and `PANTHEON_ANDROID_VM_PHONE_CPUS`
  set each phone's share, and `PANTHEON_ANDROID_VM_SERVICE_CPUS` and
  `PANTHEON_ANDROID_VM_SERVICE_MEMORY` cap the whole service.

On a Mac, Docker has no KVM. There the phone runs on a worker on the host
instead (`docker/android-host.yml`, `docs/android-host.md`), and that overlay
keeps `android-vm` from starting.

## Design note: hypervisor drivers (not built)

If Pantheon itself runs as a VM on ESXi, vSphere or Proxmox, that hypervisor
becomes layer 0. Every VM these services run is then nested one level down.
That works, with these settings:

- **ESXi or vSphere:** turn on *Expose hardware assisted virtualization to the
  guest OS* (`vhv.enable`) on the Pantheon VM.
- **Proxmox:** set the Pantheon VM's CPU type to `host` and turn on nested
  `kvm_intel`/`kvm_amd` on the node.

Either way, the Android emulator takes a real performance hit, worse on AMD
than on Intel.

The clean answer for a cluster is a different backend behind the same
lifecycle API. Pantheon would ask the hypervisor (the Proxmox API,
vSphere/vCenter) to create each person's desktop and phone as sibling VMs on
the cluster. That is layer 1 everywhere, with the hypervisor's HA, vMotion and
resource pools.

The contract above is the seam for that backend: a service is whatever
answers the protocol for one family, with one VM per account. A hypervisor
driver would answer the same routes and create the VM through the hypervisor
instead of KVM in a container. To keep that door open:

- Nothing in Pantheon assumes a VM runs in the service's own container. The
  app only knows a URL, a token and the protocol.
- Per-account state lives with the service, keyed by account, never in
  Pantheon's data.
- The pool (how many, how big) is the service's to enforce, which a
  hypervisor's resource pool would do natively.

No hypervisor backend is built yet.
