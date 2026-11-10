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

Use Python3.11+ and Docker. Install the host dependencies:

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
Do not delete a locked AVD or remove user data to resolve a failed boot. Windows
process cleanup, two-live-guest isolation and crash recovery need host-specific
acceptance; they are not established by a Mac cold-boot test.
