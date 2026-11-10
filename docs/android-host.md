# Independent Android host

Android can use its own host worker while the desktop remains stopped or uses a
different backend. The phone window, agent controls, file transfer and live viewer
all use this worker. Each person gets a private SDK home, control key and VM;
device/image combinations keep separate persistent data. Choosing another image
stops the previous VM. It never wipes or imports personal SDK data.

The worker runs where the Android Emulator can use the host hypervisor, outside
Docker Desktop's Linux VM. It probes `emulator -accel-check`; the adapters use
Hypervisor.Framework on macOS, WHPX on Windows, and KVM on Linux. Package/ABI and
actual accelerator availability decide readiness. Apple Silicon is tested here;
Windows and Linux adapters still require real-host acceptance. This does not
promise that Google publishes an emulator for every CPU, or that unsupported
hardware acquires acceleration through Docker.

## Install and pair

Use Python3.11+ and Docker running Linux containers. On Windows, use patched
Python3.11.10+, 3.12.4+, or 3.13+: these versions apply private Windows ACLs when
the worker creates a directory with mode0700. Use a private state parent owned
by the worker; an existing directory's ACL is not repaired by `mkdir`.
Install the host dependencies:

```sh
python -m pip install -r workstation/native_android/host-dependencies.txt
```

Install Google's Emulator37.2.13, platform-tools37.0.1 and the selected API35
system image into a **dedicated SDK directory**, after accepting Google's
[SDK agreement](https://developer.android.com/studio/terms) and applicable image
terms. Use Google's [SDK tools](https://developer.android.com/tools/sdkmanager).
The ARM image uses Google's `android-sdk-arm-dbt-license`. These files are not
redistributed by Pantheon.

The radio needs the Linux x86_64 `netsimd` from the **same Emulator37.2.13** SDK
archive, even on Mac/Windows: Docker runs this helper privately. Retain its SDK
licence/notice beside the binary. Docker must support `linux/amd64` containers.
The universal Android control server is
[scrcpy-server3.3.4](https://github.com/Genymobile/scrcpy/releases/tag/v3.3.4),
SHA256 `8588238c9a5a00aa542906b6ec7e6d5541d9ffb9b5d0f6e1bc0e365e2303079e`.
Pantheon verifies it before use. No host scrcpy GUI or shared ADB server is used.

Build the private packet-network helper from this checkout:

```sh
docker build --platform linux/amd64 -t pantheon-android-radio:37.2.13 -f workstation/native_android/Dockerfile.radio .
```

Run the pairing command as the host operator, with absolute paths. The acceptance
flags record that person's decision; selecting an image in the app never accepts
the operator's SDK agreements.

```sh
python -m workstation.native_android.configure --state /path/android-host --sdk /path/private-sdk --radio-binary /path/netsimd --scrcpy-server /path/scrcpy-server --internet --accept-sdk-license --accept-arm-license
python -m workstation.native_android.server --config /path/android-host/host-config.json
```

Use the app's `PUID` equal to the host worker's UID on Unix so its mode600 pairing
file is readable. Add the printed pairing folder and URL to `.env`, and include
`docker/android-host.yml` in `COMPOSE_FILE`. Only the app mounts the pairing file;
neither desktop nor Android guests receive it. Recreate the app with Compose.
On native Linux, use an address on the Docker host bridge reachable from the app
and set `bind` in the host config accordingly; loopback alone is not reachable
through an ordinary Linux bridge. Mac/Windows Docker Desktop can reach the host
through `host.docker.internal`.

### Windows worker profile

Run the worker under a dedicated Windows account. The SDK resolves its console
token through the actual Windows profile API; changing `HOME` or `USERPROFILE`
does not redirect it. Per-owner Android ADB keys and VM data still live in each
private SDK home. The console token belongs to the trusted worker account and
is never sent to the app or either guest.

Run `docker info` under that same worker account before pairing; it must reach
the Linux-container daemon that holds `pantheon-android-radio:37.2.13`. A Docker
Desktop session working under another account does not establish worker access.
Use Docker Desktop under the same dedicated identity, or explicitly grant its
identity read access to only the app pairing export. Verify the app container
can read that mounted token without printing its value. Do not make the SDK,
owner keys or Android userdata public to fix a pairing bind-mount failure.

Prepare a console token in that dedicated account once. From this checkout,
under that account, this command creates a random token only if none exists:

```powershell
python -c "import secrets; from workstation.native_android.platform_support import windows_profile; p=windows_profile()/'.emulator_console_auth_token'; f=p.open('x',encoding='ascii'); f.write(secrets.token_hex(32)); f.close()"
```

If the SDK already created a nonempty token, retain it. Add
`--windows-console-token "$env:USERPROFILE\.emulator_console_auth_token"` to
the pairing command above (with Windows absolute paths and no ARM licence flag
for an x86-64 image). The worker validates the actual profile location and reads
the token without replacing it. Missing, empty or mismatched configuration stops
Android startup with an explanation. It never silently imports personal keys or
turns off console authentication.

### Portable Docker storage

For a **fresh deployment**, include `docker/portable-storage.yml` along with
`docker/android-host.yml`. For example, use explicit `-f` arguments on every OS:

```sh
docker compose -f docker-compose.yml -f docker/portable-storage.yml -f docker/android-host.yml up -d --build
```

This keeps app state and the shared projects folder in Docker-managed Linux
volumes. Every workstation profile mounts the same projects volume. This matters
on Windows: NTFS bind mounts cannot preserve the Unix ownership and private
directory mode required by USB sharing. A POSIX filesystem within WSL is another
option; a Windows drive mounted under `/mnt/c` is still NTFS.

Do not add this overlay to an existing deployment without migrating its data:
the fresh volumes do not contain existing bind-mounted projects or settings.
Existing Mac/Linux POSIX deployments can keep their current storage. The worker
pairing directory remains a separate read-only mount in the app.

For a remote/private host, configure `bind`, `tls_cert` and `tls_key` on the worker,
then set `PANTHEON_ANDROID_URL` and its own `PANTHEON_ANDROID_TLS_PIN`. Its pin never
inherits the desktop's certificate. The client refuses public plain HTTP.

## Runtime behaviour

The app stores desired device/image separately from the active VM. Offline
person selections persist; an agent cannot queue changes past a person's
takeover. Phone takeover is independent of desktop takeover. A changed display
ends its old stream, releases held input, and reconnects at the new geometry.

The image installer checks the catalogue size/checksum and records SHA256 and
licence identity. A cached restore uses that exact archive revision. The managed
cache may evict immutable images while no Android VM runs; AVD userdata, keys and
restore records remain. Unmanaged SDK images are never evicted. New devices request
2GiB data partitions by default; `data_size_gib` controls the request for newly
created slots. The SDK may enlarge this to the image minimum (API35 grew to
6GiB during testing), and requires additional free host space to start. Existing
disk sizes are preserved. `max_running` defaults to one for a small host.

With `internet` enabled, Wi-Fi packets go to that VM's private Docker network
service. The existing Internet-only kernel rules protect private addresses for
TCP and UDP. Netsim drops its Linux capabilities before serving guest packets;
no raw radio port is published. The SDK's fallback network stays restricted.
Without `internet`, the VM has no application egress. An unavailable packet
service does not authorize direct SDK networking.

Graceful worker shutdown stops guests and private helpers and preserves storage.
It also cancels an active image installation and waits for staging cleanup;
an operation still blocked after the shutdown wait reports an unfinished stop.
The installer thread remains owned until it exits, and an already-started atomic
image promotion finishes its cache record before stopping. Cancellation preserves
AVD userdata and suppresses the installer's automatic device start.
Do not delete a locked AVD or remove user data to resolve a failed boot. Windows
process cleanup, two-live-guest isolation and crash recovery need host-specific
acceptance; they are not established by a Mac cold-boot test.


## Host portability and clamshell QA

The app and Android worker are independently deployable. Stock SDK local workers
support Linux x86-64, Windows x86-64, and macOS x86-64/ARM64; other app hosts can
pair with a compatible remote worker over pinned TLS. Detection checks the native
CPU even when Python is translated and reports the SDK's actual accelerator.
`configure --gpu software` is the portable graphics default; `--gpu host` opts into
hardware rendering. On Linux Docker bridges, set `--bind` to a private host bridge
address and `--app-url` to the URL reachable from the app. Loopback alone is not
reachable through Docker's host-gateway mapping. Remote listeners need the
existing TLS certificate/key and app certificate pin configuration. The private
radio helper requires Docker Linux/AMD64 execution; build the documented helper
for both online and offline use. SDK images can reside on a separate drive from
runtime state; staging and atomic installation happen on the SDK volume.
On SELinux Linux hosts, the radio copies its executable to the private runtime
folder and labels only that expendable copy for the container (`ro,z`). It does
not relabel the SDK or home directory, or disable SELinux. The radio state path
must not contain a colon on Linux because Docker's volume syntax reserves it.

### Acceptance status

The Mac acceptance covers a real accelerated Android boot, image changes,
viewer input and Android/workstation/project-folder transfers. The portable
storage test executes the real USB folder code in Linux containers as separate
app and workstation UIDs, verifies files in both directions and rejects symlinks.
That proves Linux container filesystem behavior, not a native Linux emulator.

Windows-specific Python/console paths and Linux radio mount selection have
regression coverage, including Windows launch variables, failed-start cleanup,
installer cancellation and control-coordinate mapping for partial Android UI
trees. Code-level tests do not certify platform drivers or every SDK subprocess
lifecycle. Native Windows and Linux worker acceptance is still open:
it needs the current worker to cold-boot on WHPX and KVM respectively, authenticate
with the owner key, reject another owner's key, exercise viewer input and USB in
both directions, change images without losing data, and shut down cleanly. WSL
without a usable `/dev/kvm` cannot provide the native Linux Android acceptance;
Windows can instead run the Android worker natively alongside the WSL/Docker app.

Clamshell profiles use generic Android firmware with horizontal hinges and
open/90-degree/closed postures. Panel dimensions come from
[Samsung's Z Flip6 specification](https://www.samsung.com/uk/business/smartphones/galaxy-z/galaxy-z-flip6-blue-256gb-sm-f741blbgeub/)
and [Motorola's Razr 50 Ultra specification](https://en-us.support.motorola.com/app/answers/detail/a_id/183647/~/technischen-daten--motorola-razr-50-ultra-).
The authenticated posture bridge changes Android’s WindowManager size, verifies its actual logical viewport, and normalizes the captured physical region to the same coordinates used by touch. These generic cover viewports exercise Android configuration changes; they do not reproduce
Samsung/Motorola firmware, camera masking, proprietary cover launchers or retail
multi-display policies. Jetpack WindowLayoutInfo/FoldingFeature delivery is not
validated by these generic profiles. Real-device acceptance is still needed for those.

## USB shared folders

Connect USB in the phone pane to synchronize `Download/PantheonUSB` with the
owner's `Android USB/<device>-<edition>` folder in Pantheon projects. The workstation
uses that same existing projects export. The pane lists/downloads these user files;
its file/document upload controls add to the connected folder. Sync continues
while the app is running and USB is connected, even if the pane closes. Restarting
the app leaves USB disconnected. Eject drains in-flight operations and flushes the
guest; files remain on both sides. Changing/stopping the device ejects it.

This is a software USB folder bridge, not raw host USB passthrough or a full disk
mount. It supports 64 flat files, 20,000,000 bytes per file and 128 MiB total, with
portable ASCII filenames. Subfolders, links and case aliases are refused visibly.
Conflicting versions retain a deterministic Android copy; deletions do not
propagate. Only this explicitly exported folder crosses the VM boundary. The
shared workstation backend retains its existing shared-root projects limitation;
use the per-user workstation VM export when isolation from other workstation-root
users is required. Worker pairing keys and private Android userdata never enter
this export.
