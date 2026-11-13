# Pantheon Setup Guide

This page keeps the detailed install, deployment, troubleshooting, and configuration notes out of the front README.

## Quick Start

> **Branch note:** `main` is the only branch — cloning gives you it, and there is nothing to switch to. *(Corrected 2026-08-30: this line described upstream Odysseus's two-branch model and told people to check out a branch this repository does not have.)*

Defaults work out of the box: clone, run, then configure models/search/email
inside **Settings**. Only edit `.env` for deployment-level overrides like
`APP_BIND`, `APP_PORT`, `DATABASE_URL`, or a pre-seeded admin password. (Sign-in is always on;
there is no `.env` switch for it since 0.2.0.)

On first setup, open Pantheon in a browser: with no account yet, the sign-in page
asks you to make the admin (and whether people may create their own accounts).
Running `setup.py` in a terminal asks for it there instead. To have it made ahead
of time, set `PANTHEON_ADMIN_PASSWORD` (and `PANTHEON_ADMIN_USER`, `admin` if
unset) in `.env`. An update never asks again: the setup appears only while the
account store is empty.

Contributing? See [CONTRIBUTING.md](../CONTRIBUTING.md) for setup, testing, and
pull request guidelines.

### Docker (recommended)
```bash
git clone https://github.com/ImPanick/pantheon.git
cd pantheon
cp .env.example .env       # optional, but recommended for explicit defaults
docker compose up -d --build
```
To include optional extras in the image (PDF viewer, Office extraction; includes AGPL PyMuPDF), build with `docker compose build --build-arg INSTALL_OPTIONAL=true` before `up`.

The image carries the default local embedding model (about 90 MB), fetched while it is built and copied into `./data/fastembed_cache` on first start, so memory and document search work by meaning without anything being downloaded at run time. `--build-arg BAKE_MODELS=false` builds without it.

The image also carries speech for voice chat and dictation (about half a gigabyte): faster-whisper with the Whisper `base` model, and Piper with the `en_US-ljspeech-medium` voice, both running on the CPU. Turn them on in **Settings → Voice**: *Speech to text* → *Local Whisper, on this server*, and the voice chat's voice → *Piper, on this server*; each has a test button. `--build-arg INSTALL_VOICE=false` builds without speech; `BAKE_MODELS=false` leaves out its models too, and they are then fetched on first use only with *Download models from the internet* on (Settings → System). `WHISPER_SEED_MODEL` and `PIPER_SEED_VOICE` choose which model and voice are baked. After an update, hard-refresh the browser once so it loads the new page.

It carries a realistic voice as well: Kokoro (Kokoro-82M exported to ONNX, Apache-2.0, about 350 MB), which speaks on the CPU about three times faster than it talks, in 41 voices across American and British English, Spanish, French, Hindi, Italian and Brazilian Portuguese. The server's voice is *Automatic* out of the box (**Settings → Voice**): Chatterbox while it runs on an NVIDIA GPU (below), else Kokoro, else Piper. Each person turns on **Conversation** for themselves, the speech-bubble switch in the composer or **Settings → Conversation**, and the agent then says every reply out loud while it writes it; there they choose their own voice and speed, with *Hear it* to listen first, and that voice also answers them in a voice chat and reads aloud for them. Nobody else's Pantheon changes. An install that never chose a voice speaks with *Automatic* after this update; one that chose a voice, or chose *None*, keeps its choice. `INSTALL_VOICE=false` or `BAKE_MODELS=false` leaves Kokoro out too; it is then fetched on first use from the `kokoro-onnx` release on GitHub, only with *Download models from the internet* on, or you put `kokoro-v1.0.onnx` and `voices-v1.0.bin` in `data/models/kokoro/` yourself.

**Chatterbox on an NVIDIA GPU (optional).** Chatterbox Turbo (Resemble AI, MIT) is a more natural voice for a server with an NVIDIA GPU, and it runs beside Pantheon in a container of its own, because it needs PyTorch on CUDA. With the NVIDIA overlay in use (`docker/gpu.nvidia.yml`, or `docker-compose.gpu-nvidia.yml`), add `COMPOSE_PROFILES=chatterbox` to `.env` and run `docker compose up -d --build`. The build fetches its weights from Hugging Face once (a few gigabytes), and the container then runs offline and needs about 3 GB of GPU memory. While it answers, *Automatic* speaks with it, and people can choose it in **Settings → Conversation**. To give it more voices, put a recording of one person speaking (WAV or FLAC, longer than five seconds) in `data/chatterbox-voices/`, named for the voice (`Grandad.wav` becomes "Grandad"); it speaks in the voice it hears, so use only a voice you have the right to use. Everything it says carries Resemble AI's inaudible Perth watermark.

Open `http://localhost:7000` when the containers are healthy. Docker Compose
binds the web UI to `127.0.0.1` by default. If the port is taken, set
`APP_PORT=7001` in `.env` and recreate the container. Set `APP_BIND=0.0.0.0`
only when you intentionally want LAN/reverse-proxy access.

> **On Apple Silicon (M-series) Macs:** Docker can't reach the Metal GPU, so
> Forge serves local models on CPU only. For GPU-accelerated model serving,
> run natively instead — see [Apple Silicon](#apple-silicon) below.

### Deploying an update

```bash
git pull
./scripts/pantheon-deploy run          # or: pantheon deploy run
```

This is the whole deploy. It builds, brings the service up, **waits for the
container to report healthy**, verifies it, prints a report and exits non-zero
if anything failed.

**Why waiting matters.** `docker compose up -d` prints `Container
pantheon-1 Started` and returns as soon as the container starts, but Pantheon
binds port 7000 only after it has finished importing itself — 35–60 seconds on
a typical host, because it loads embeddings, the vector store and the MCP
layer first. Anything that probes the app before then gets `Connection
refused` on every route and looks exactly like a failed deploy. The `pantheon`
service carries a healthcheck that asks `127.0.0.1:7000/api/ready` for a real
answer — 200 only when the database answers and the data directory takes a
write, 503 otherwise — so `docker ps` distinguishes *running* from *serving*,
and this script waits for it instead of sleeping a guessed number of seconds.
`/api/ready` answers without a sign-in, because a probe cannot sign in, and a
caller with no session is told `{"ready": true|false}` and nothing else.

Note that Docker does **not** restart a container it marks unhealthy —
`restart: unless-stopped` acts on process exit. The healthcheck makes a wedged
container visible; clearing it is still `docker compose restart pantheon`.

What `run` verifies, after the container is healthy:

| Check | What it catches |
|---|---|
| every route in the probe's table answers what it answered when measured | a route that 404s or sits behind the login wall after a change |
| every `mcp_servers/*_server.py` imports in a **fresh interpreter** | the import cycle that silently killed the Email and RAG MCP servers for a week |
| no traceback in this container's boot log | anything the app caught, logged and carried on from |
| the bytes in the image match the committed blobs | an image built from a working tree that has drifted from the repository |

Useful variants:

```bash
./scripts/pantheon-deploy run --no-build      # restart and verify, no rebuild
./scripts/pantheon-deploy verify              # verify what is running now
./scripts/pantheon-deploy run --timeout 600   # a slow or cold host
./scripts/pantheon-deploy run --json          # machine-readable report
```

**Rolling back.** `run` tags the image it is about to replace as
`pantheon-deploy:previous` before it builds, and prints the rollback command if
the deploy fails. It does **not** roll back on its own:

```bash
./scripts/pantheon-deploy rollback
```

That is deliberate. Rolling the *image* back is reliable; rolling the *data*
back is not. Pantheon runs schema migrations on every startup and they are
forward-only — most are additive and an older image reads straight through
them, but at least one rewrites existing rows into a form the older image
cannot read. An automatic rollback would sometimes turn a failed deploy into a
worse one, silently, so the decision stays with you. If `docker image prune`
has removed the previous image, `docker images` will show what else is on the
host.

### Native Linux / macOS
```bash
git clone https://github.com/ImPanick/pantheon.git
cd pantheon
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python setup.py
python -m uvicorn app:app --host 127.0.0.1 --port 7000
```
Requirements: Python 3.11+. Forge also needs `tmux` for background model
downloads and serves. The app itself is lightweight; local model serving is the
heavy part and depends on the model, runtime, GPU, and VRAM, so small hosts can
connect to API or remote model servers instead. Use `--host 0.0.0.0` only when you intentionally want LAN/reverse-proxy access.

### Apple Silicon
Docker on macOS cannot use the Metal GPU. For GPU-accelerated Forge on an
M-series Mac, run Pantheon natively:

```bash
git clone https://github.com/ImPanick/pantheon.git
cd pantheon
./start-macos.sh
```

It launches at `http://127.0.0.1:7860`. To expose it to your phone over a trusted LAN/VPN such as Tailscale, bind all interfaces:

```bash
PANTHEON_HOST=0.0.0.0 ./start-macos.sh
# then open http://<tailscale-ip>:7860
```

The script also reads `.env` at startup, so `APP_BIND=0.0.0.0` and `APP_PORT`
set there are picked up automatically without a command-line override each run.

Make the admin account before binding outside loopback — until it exists, whoever
reaches the sign-in page first creates it. Do not expose this port directly to the
public internet. To build a clickable app wrapper:

```bash
./build-macos-app.sh
```

<details>
<summary>Forge, GPU, Ollama, and troubleshooting notes</summary>

**Docker bundled services.** Compose starts Pantheon, ChromaDB, SearXNG, and
ntfy. Pantheon and the bundled service ports bind to `127.0.0.1` by default, so
they are reachable from the host but not exposed to your LAN/public internet
unless you opt in.

**Forge storage in Docker.** Downloads live in `./data/huggingface`
(`~/.cache/huggingface` in the container). Forge-installed Python CLIs and
serve engines live in `./data/local` (`~/.local` in the container), so they
survive container recreation.

**Remote servers.** In **Forge -> Settings -> Servers**, generate the
Pantheon SSH key and add the public key to the remote server's
`~/.ssh/authorized_keys`. From the host you can also run:

```bash
ssh-copy-id -i data/ssh/id_ed25519.pub user@server
```

**Host Docker access (explicit opt-in).** Default Docker Compose intentionally
does not mount `/var/run/docker.sock`. You can still connect Pantheon to
existing Ollama, vLLM, and other OpenAI-compatible endpoints without Docker
socket access.

Forge/local Docker-daemon management requires the opt-in overlay below. Raw
Docker socket access is high-trust because it can effectively grant broad
control over the host Docker daemon. Remote server Docker workflows over SSH
remain preferred.

Place these values in `.env`, or export them in the shell before running
`docker compose`:

```bash
COMPOSE_FILE=docker-compose.yml:docker/host-docker.yml
DOCKER_GID=<host docker group gid>
```

Combine host Docker access with a GPU overlay when both are intentionally
required:

```bash
COMPOSE_FILE=docker-compose.yml:docker/gpu.nvidia.yml:docker/host-docker.yml
# or
COMPOSE_FILE=docker-compose.yml:docker/gpu.amd.yml:docker/host-docker.yml
```

**A workstation for the agents (`P20`).** An Ubuntu desktop the agents work
in: a private account, home and desktop per person, kept between chats, with
*Reset to clean*. When it is on, the agent's shell, Python and file tools run
there instead of inside Pantheon, a `computer` tool can see and work its
screen, and the person can watch that screen and take over at any time. It is
part of the default stack and on from the first start: the agent can use it
as soon as the admin account exists. **Settings → Workstation → On** switches
it off or back on, and a stack without a workstation leaves it off. Nothing to
paste: Pantheon finds it and reads its keys from volumes only it and the
workstation's containers share. Upgrading an install whose Settings were saved
before this change keeps the answer it had; if the switch reads off, turn it on.

The stack ships both local kinds, and *Backend* in the same panel chooses
between them. *Automatic* (the default) picks the VM where Docker can use KVM
and the container where it cannot:

| | What it is |
|---|---|
| **Virtual machines** (`workstation-vm`) | An Ubuntu VM for each person: a hypervisor between people, and *Reset to clean* is a fresh machine. Needs KVM to be quick (Linux with `/dev/kvm`). The machine image is made when the workstation is first used on this backend (minutes with KVM); each person's machine then starts on their first use and takes up to 2 GB of RAM while it runs (`PANTHEON_WORKSTATION_VM_MEMORY_MIB`); one nobody has used for 30 minutes is powered off and starts again on the next use (`PANTHEON_WORKSTATION_VM_IDLE_MIN`), and no more run at once than the host's memory holds (`PANTHEON_WORKSTATION_VM_MAX_RUNNING`). Without KVM (Docker Desktop on Windows or macOS) the machines are emulated: the image takes an hour or more and everything runs several times slower, which is why *Automatic* uses the container there. |
| **Container** (`workstation`) | An Ubuntu container beside Pantheon. Each person is a Unix account in it. Starts in seconds on any Docker. |
| **Another machine** | Any Ubuntu 24.04 machine — a Proxmox or libvirt VM, a spare box. Copy the repository's `workstation/` folder to it and run `sudo python3 workstation/install.py`; it prints the four lines to put in Pantheon's `.env` (`COMPOSE_FILE=docker-compose.yml:docker/workstation-remote.yml`, the address, the token and the certificate's fingerprint). HTTPS with that one certificate pinned by default; `--no-tls` for a LAN or a VPN. Pantheon never sends the workstation's token over plain http to a public address. |

**A real VM on Windows.** Docker Desktop runs inside WSL 2's own virtual
machine, so a VM per person needs WSL 2 to pass virtualization through to it
(nested virtualization). That is Windows 11 only. Put these lines in
`%UserProfile%\.wslconfig`, run `wsl --shutdown`, start Docker Desktop again,
then `docker compose up -d --force-recreate workstation-vm`:

```ini
[wsl2]
nestedVirtualization=true
```

Settings → Workstation then says *KVM* instead of *emulated*, and *Automatic*
moves to the VM. On Windows 10 and on macOS, Docker has no KVM to give, so the
container is the fast workstation there.

**A real VM per person on Proxmox.** Run Pantheon in a Proxmox VM (not an
LXC container) and let that VM use KVM itself (nested virtualization). Docker
in it then has `/dev/kvm`, and each person's machine runs at close to native
speed:

1. On the Proxmox host, `cat /sys/module/kvm_intel/parameters/nested`
   (`kvm_amd` on AMD) prints `Y` or `1`. It usually does on a current Proxmox;
   if not, put `options kvm_intel nested=Y` (or `options kvm_amd nested=1`) in
   a file under `/etc/modprobe.d/` and reboot the host.
2. Pantheon's VM: Hardware → Processors → Type `host` (`qm set <vmid> --cpu
   host`), then stop and start it from Proxmox; a reboot from inside does not
   pick up the change. A `host` CPU cannot live-migrate to a node with a
   different CPU.
3. Inside it, `ls /dev/kvm` shows the device; then `docker compose up -d
   --force-recreate workstation-vm`.

Size the VM for the people who work at once: each running machine takes up to
`PANTHEON_WORKSTATION_VM_MEMORY_MIB` (2 GB) and `PANTHEON_WORKSTATION_VM_CPUS`
(2), on top of Pantheon itself.

### Mobile Emulator

Android runs **inside each user's own VM**, through the existing VM workstation
backend. The shared container backend is refused for Android: Unix accounts,
different ADB ports and turning sudo off do not isolate device ports; sudo would
also expose other users' files. Select **VM** in Settings → Workstation. Nothing
copies or wipes an existing container AVD when you switch backend. Preserve its
home volume; moving old device data requires a separate, deliberate migration.
Android eligibility is bound to the operator's configured VM endpoint, as well
as the daemon's isolation metadata. A custom workstation URL needs an explicit
**VM** backend choice; choosing VM without a configured VM host does not turn a
container endpoint into one. The host operator and Pantheon configuration are
trusted; root in a user's guest cannot change that configuration or read the VM
host's token.

The emulator runs generic Android 15 (Google APIs by default), as one of the
device profiles: Google's Pixel 9, 9 Pro, 9 Pro XL,
8 and 8a, Pixel Fold and 9 Pro Fold, and Pixel Tablet; Samsung's Galaxy S25,
S25 Ultra and A55, Z Fold6, and Galaxy Tab S9 and Tab S10 Ultra; the OnePlus 12
and OnePlus Pad 2; and the Nothing Phone (2). Each is drawn as it looks: its
colour, its corners and bezel, its camera, a foldable's crease, and its keys on
the edges they are on. The Workbench's **Devices** room lists them:
pick one and Pantheon downloads, installs and sets up what that device needs
(the first time, after you accept the
[Android SDK License](https://developer.android.com/studio/terms) there, about
4 GB), then turns it on beside the list. The + menu's *Mobile Emulator* opens the same
phone in a window of its own. Either way it is drawn as the device, with its
side keys working; the mouse is a finger (click to tap, drag to swipe, scroll
to fling, right click for Back). The agent uses it exactly as you do: the same
screen, taps, keys, rotate and fold, and the same device list (`computer` with
`screen: phone`, `press`, `rotate`, `fold`, `open_url`, `use_device`), plus
`adb` from its shell. The SDK, apps and account state are on that user's VM disk.
They survive a VM power cycle. **Reset to clean** still replaces the whole VM,
including its phone; do not use reset to troubleshoot a missing KVM device.

Android needs hardware acceleration **inside that VM**, not merely on the host.
The VM host must actually use KVM and the guest must open `/dev/kvm`; without
both Android is refused. A guest device node under software emulation is not
evidence of real acceleration. Allocate at least the
Android memory budget plus 1536 MiB to each VM; 10240 MiB, 4 vCPUs and adequate
disk space are recommended for a desktop plus Android (`PANTHEON_WORKSTATION_VM_MEMORY_MIB`,
`PANTHEON_WORKSTATION_VM_CPUS`, `PANTHEON_WORKSTATION_VM_DISK_GIB`). Stop/start an
existing VM to apply its host resource settings; its disk is kept.

**Nested virtualization is experimental here.** Google's
[acceleration documentation](https://developer.android.com/studio/run/emulator-acceleration)
does not support a VM-accelerated emulator inside another VM. Do not infer support
from a BIOS/Windows toggle or from host KVM. Before installing an SDK image, verify
`/dev/kvm` actually opens in the user's VM; after an authorized SDK install, run
`/opt/android-sdk/emulator/emulator -accel-check` there and perform a real cold-boot,
stream, touch and file-transfer acceptance run. This host path has not passed that
Android acceptance. The controlled development probe on 2026-11-08 found running
Docker Desktop/WSL and a Windows hypervisor, but no usable Linux KVM device.

**Historical native Windows probes (2026-11-09).** The current independent worker
and its Windows setup are documented in [Android host](android-host.md); its
native Windows/Linux acceptance remains open. The following records the earlier
standalone SDK investigation, not verification of today's integration. On Cybertooth,
the initial read-only 2026-11-09 probe of `WHvGetCapability` returned success with
`HypervisorPresent=true`. The SDK was absent in the checked locations at that
stage. The subsequently authorized official SDK test below has now booted real
Android on WHPX; Pantheon had no native Windows device-host adapter at that point.
An additional read-only Windows feature inventory reported `HypervisorPlatform`
**disabled** (`Win32_OptionalFeature.InstallState=2`), with Hyper-V and Virtual
Machine Platform enabled (`1`). A hypervisor-present capability response does not
establish the optional feature's state. The installed emulator's actual
`-accel-check` and real guest boot succeeded without enabling it. Any future
feature or security-policy change and any restart need separate authorization.
No feature, firewall, security exclusion, service or driver was changed.
Google's supported Windows path is native
[WHPX](https://developer.android.com/studio/run/emulator-acceleration#vm-windows);
keep Hyper-V enabled.
[Cuttlefish](https://source.android.com/docs/devices/cuttlefish/get-started)
still requires Linux KVM, so moving it into the same WSL/Docker environment does
not solve this host's current blocker. An authorized separate Linux/KVM worker is
the other viable direction to validate.

An open-source QEMU/WHPX host with a PC-targeted AOSP image is another
investigation, not a working provider. No clean, current drop-in image has been
verified here. A "FOSS" download name does not establish component rights; for
example, [Bliss's licensing page](https://blissos.org/licensing.html) identifies
proprietary components in some variants. Cuttlefish's Linux host integration also
needs porting before its images can be treated as native Windows targets. A full
modern [AOSP source build](https://source.android.com/docs/setup/start/requirements)
requires at least 400 GB free storage and 64 GB RAM; the current authorized C:
workspace does not have that free storage. No alternate drive/build host is
selected or modified. A local SDK development test needs the operator's explicit
SDK licence consent; it does not establish consumer deployment or redistribution
rights.

**Authorized local SDK preparation (2026-11-09).** The owner subsequently
authorized the three pinned official archives for an isolated native test:
emulator 37.2.13, platform-tools 37.0.1 and API 35 Google Play x86_64 image
revision 9. They were checksum-verified and extracted under the task's
`validation/native-android-test`; the exact package `android-sdk-license`
agreement dated January 16, 2019 was disclosed, compared with the public 2026
agreement and accepted under that authorization. Component notices were retained.
No SDK binaries or images are vendored in this repository.

The actual native `emulator -accel-check` returned success and reported
`WHPX(10.0.26200) is installed and usable`, despite the feature inventory above.
No feature change or restart was needed for that check. A fresh manual AVD is
recognized by `-list-avds`. Actual native boot and control results are below;
none of these SDK checks establish tenant isolation.

Boot preflight found an exception to workspace-only credential storage: the
native Windows console implementation uses the Windows profile's
`.emulator_console_auth_token`, and ADB loads or generates `.android/adbkey`
and `adbkey.pub` there. Android SDK environment variables do not reliably relocate
those native Windows lookups. The owner subsequently authorized creation of the
console token and read-only use of the existing ADB keys. The token was created
with access restricted to that Windows user and SYSTEM; the keys were held
read-only without write sharing during the tests. Existing key files were left
unchanged, no private key was copied into the test directories, and the assistant
did not enable persistent debugging trust. The profile token
remains at the approved location. A deployed worker needs its own host identity
and credentials rather than this personal-profile test arrangement.
The [console source](https://android.googlesource.com/platform/external/qemu/+/emu-master-dev/android/emu/telnet/auth/src/android/console_auth.cpp)
and [ADB key source](https://android.googlesource.com/platform/packages/modules/adb/+/refs/heads/main/client/auth.cpp)
explain these defaults. A future worker still needs independent per-user
stream/control/storage isolation and actual adversarial acceptance.

**Native acceptance results (2026-11-09; validation only).** These are actual
official SDK guests using WHPX on Cybertooth, not browser streams, mocked Android
or Linux/KVM. The phone and fold-profile guests also ran concurrently with
separate AVD directories. Both owned process trees were stopped afterwards; a
separate inventory found no processes remaining under this test SDK path.

| Check | Observed result |
|---|---|
| Generic Android 15 / API 35 | Cold boot, Android properties, real home/Settings pixels and UI hierarchy passed. Play Store and Play services packages are present; no Google account was used. |
| Touch and navigation | Explicit touchscreen input opened Network & internet; Back, Home and Recents passed on the final scoped pass. Earlier automation attempts had intermittent touch failures and an overview tutorial; this is not a long-duration reliability result. |
| Device keys and rotation | Power reported Asleep then Awake; volume changed 4 to 5 to 4, requiring two Up presses and one Down, with restoration checked. A 1080 by 2400 frame became 2400 by 1080; rotation preferences were restored. Playback was enabled for these checks, with microphone and cameras disabled. Audio streaming into Pantheon was not tested. |
| Selected generated file | A new destination and new payload passed checked ADB push, byte/hash readback and sync. The previous unique 67-byte transfer was verified before any push after the next cold boot. This is the SDK transfer primitive, not Pantheon's native document/upload integration. |
| Data and shutdown | Earlier short/forced-shutdown attempts left a zero-byte marker. Subsequent explicit guest sync and a longer wait after console kill preserved both the original marker and the later unique transfer. Kill acknowledgement/exit code was not independently recorded. The cause was not isolated, and power-loss durability is not established. Final owned emulator/ADB process counts were measured as zero. |
| Fold profile | A separate generic-Android Pixel Fold geometry accepted fold/unfold and reported hinge angle 180 then 0. SDK rotation swapped capture dimensions. The capture still returned the full framebuffer after folding, with distorted/partial layouts; cover viewport, scaling and touch mapping remain unverified. This is partial support, not retail Pixel Fold fidelity. |
| Guest-to-host isolation | **Failed.** Android shell reached a disposable loopback marker and the test's unauthenticated ADB smart server through `10.0.2.2`, despite `restrict=on` options. A harmless generated-marker command on that same test guest was executed through the host ADB server. No other user's device was targeted. Separate ports and Windows Jobs do not close this boundary. |
| Pantheon native integration | Not implemented. Live embedded streaming, owner-bound native device operations, takeover, cross-owner access denial and actual two-user isolation remain acceptance gates. No user APK install/QA flow or personal Google sign-in was tested. |

The exact probe sources, configurations, JSON results and hash-checked screenshots
are retained locally under `validation/native-android-test/logs/proof-phone-20261109T070410Z`
and `proof-fold-20261109T070409Z` in the task workspace, outside this checkout.
No SDK payloads, device disks, credentials or raw emulator logs are committed.
The owner requested review of these results **before** starting Pantheon
implementation. The intended scope remains usable generic Android phones and
tablets across feasible profiles, including agent-driven application QA; Pixel
is a starting test profile. Vendor-specific compatibility and iOS remain separate
future work. See `.pantheon/DECISIONS.md`, `D-2026-11-09-03`.

**Guest-to-host ADB follow-up (2026-11-09; validation only).** The controlled
exposure above was reproduced again, then two separate mitigations were tested
on the same owned Android AVD. These are scratch prototypes outside Pantheon;
they are not a native provider or proof of complete per-user isolation.

| Experiment | Verified scope |
|---|---|
| Restricted network path | The installed SDK enables `WiFiPacketStream`, described in its `lib/advancedFeatures.ini` as Netsim-provided Wi-Fi. With that default, the guest still reached the owned host marker and ADB smart server despite both network restriction options. The matching-source comparison added `-feature -WiFiPacketStream` to select the other Wi-Fi path, with `restrict=on,ipv6=off` on both network options and explicit marker-only `guestfwd` mappings. The tested raw host marker, ADB and unforwarded virtual ADB paths were then denied. Working allowlisted marker connections and healthy host endpoints ruled out a disconnected guest or dead server as the explanation. |
| Direct authenticated device control | A separate prototype used `-no-direct-adb`, `-no-sim` and a bounded direct ADB wire client, without relying on an SDK smart server. Before launching the emulator, non-listening exclusive wildcard IPv4 and IPv6 sockets reserved its configured smart-server port. All eight competing bind/listen variants were denied, including loopback/wildcard addresses with and without reuse. An earlier loopback-only reservation failed that check and was rejected. This reservation changes no Windows firewall or port-policy settings and exposes no listening service. |

The restricted run covered initial Wi-Fi, Wi-Fi disabled with cellular
enabled, Wi-Fi reenabled, and an Android reboot with a changed boot ID. Each phase
had a working allowlisted network control. A separate full emulator restart also
verified the previous unique transferred file before a new push; fresh checked
bytes survived the later Android reboot. Guest network preferences were restored.
This proves the selected IPv4 TCP paths under that configuration, not general
Internet/Play connectivity, all IPv6 or UDP paths, or resistance to guest root.

The direct-control test checked that the raw device listener belonged to the
captured emulator process tree before signing its challenge with the approved
existing ADB key. It never sent a public-key enrollment request. Keyless,
wrong-key and concurrent wrong-key clients obtained no authorized stream during
their bounded three-second observation windows; the authorized connection stayed
usable. A disposable local Docker bridge client, UID 0 with all capabilities
dropped and no host mounts, reached the marker and received the device's real
authentication challenge, but obtained no shell stream. Its parser recorded no
partial response frame. This is a calibrated Linux-container network-origin
check, not a second user, hostile workstation VM or Android-root acceptance.

The final direct-control repeat recorded 226 process-owned TCP listener snapshots
at a nominal 250 ms interval, with no observer errors or identified `adb.exe`
listeners. Sampling cannot exclude transient listeners or endpoints outside that
process tree. Other SDK TCP listeners remained; console, gRPC and Netsim surfaces
still need authentication and cross-owner attack tests. The direct
experiment did not use the restricted Wi-Fi configuration; their combination has
not been validated. The approved shared fixture key is not a per-device identity
or a production credential model.

Fresh selected-byte writes passed in earlier direct-control runs, and the final
security-only repeat verified the prior unique file after a cold boot. However,
another preserved direct-shell Downloads write failed with `Operation not
permitted`; its cause and readiness/reliability remain unresolved. That write
method differs from the earlier successful checked SDK `adb push`. The final
security repeat explicitly skipped fresh writes and does not resolve that failure.

Evidence is retained outside this checkout under
`validation/native-android-test/logs`: the matching-source network comparison is
`isolation-baseline-20261109T084247Z-b19594eb` against
`isolation-restricted-20261109T083039Z-69370750`; the strict direct/Linux-origin
repeat is `direct-adb-20261109T083550Z-27bef584`. Sources and screenshots were
hash-checked, and independent adversarial review checked the negative-test
deadlines, positive controls and limited claims. Failed attempts remain alongside
the successful runs. These completed runs recorded console-kill acknowledgements,
emulator exit code zero and empty captured process jobs. A final independent
inventory, `logs/final-mitigation-process-inventory.json`, found no remaining
processes under the isolated SDK path; the disposable containers were removed.

No Windows feature, firewall, route, service, security policy or restart action
was taken. PowerShell policy blocked an early observer script; a read-only Windows
API observer replaced it without changing or bypassing that policy. No new SDK
package or licence acceptance was involved. The diagnostic direct-ADB clients
sent no public-key enrollment requests; no persistent-trust UI action or personal
account sign-in was performed. A complete before/after authorization-state audit
remains open. At that stage Pantheon integration remained paused for review,
and the existing Linux VM/KVM guards remain intact. The proposed boundary and its
remaining acceptance gates are recorded in `.pantheon/DECISIONS.md`,
`D-2026-11-09-04`.

**Native runtime continuation (2026-11-09).** The owner subsequently authorized
continuing through implementation of the usable Android experience, superseding
the earlier pause. The Windows provider was unimplemented at that point; the following
results concern real disposable Android/WHPX guests and SDK endpoints, not an
embedded Pantheon stream. The Linux VM/KVM gates remain intact.

| Check | Result and limit |
|---|---|
| File-create comparison | The first ordered comparison recorded 37 fresh-file attempts: two initial shell creates in the existing Downloads folder returned explicit exit status 1 / `Operation not permitted`; the nearby exec and sync operations passed. Later shell attempts passed. The counterordered run recorded 46 successful fresh creates, including a binary sync case. All 35 successful files from the first comparison matched before new writes after a distinct cold boot. An intervening immediate cold-read failure lacked a useful diagnostic; later reads recovered the original bytes. Timing, caller/service and shared-storage create policy remain possible factors. Reliability is not declared fixed. |
| Transfer service | All 20 sync attempts across those two comparisons returned structured `OKAY` and exact readback bytes, including the binary cases. This supports using Android's sync service instead of shell redirection; it is not a general durability or app-integration guarantee. Shell ran as UID 2000 in the shell SELinux domain with enforcement enabled; no permission override was applied. The hardcoded AOSP MediaProvider query returned no version on this Play image, so provider identity/readiness is unknown. |
| Console | `avd name` is intentionally public metadata. The privileged read-only `power display` was refused before authentication and returned battery state after approved console authentication. A bogus console token was rejected. |
| Emulator gRPC | On an explicitly JWT-protected owned endpoint, `getBattery` rejected missing bearer, malformed bearer and an otherwise formed token signed by an unregistered in-memory key with `UNAUTHENTICATED`. No valid gRPC credential or JWK was enrolled. This does not verify authorized streaming or every method/listener. |
| Netsim services | A fresh standalone daemon served credential-free `CellService/List` in both default and no-CLI modes. `FrontendService/GetVersion` returned `UNIMPLEMENTED` in both. The CLI flag cannot be claimed as isolation, and source/version differences prevent inferring all registered services. |
| Trial without a Netsim daemon | Android booted and returned real launcher pixels with `WiFiPacketStream` and `Uwb` disabled and the custom packet-stream endpoint held by exclusive non-listening sockets. The harness launched no Netsim daemon, and none appeared in its post-boot process snapshot. Lifetime absence was not measured. Bluetooth/UWB behavior remains unverified. Several other QEMU TCP listeners remain unclassified. |
| Restricted connectivity | With the trial above, a fixed forwarded relay returned its fixture while the same controlled raw-host fixture did not. Five exact abuse requests were refused: CONNECT, an absolute loopback URL, a foreign Host, an Authorization header and POST. The relay made one fixed credential-free HTTPS GET to Google's connectivity-check endpoint and observed HTTP 204. A prior successful configuration with a captured Netsim daemon also made one such request. Host urllib performed TLS; this is not Android application, Play Store or Google-account networking acceptance, and the relay is not a general proxy. |

Successful evidence is outside this checkout under
`validation/native-android-test/logs`: `storage-20261109T092028Z-0f28de67`,
`storage-20261109T092937Z-5b7c175e`,
`netsim-readonly-20261109T094801Z-0556ecef`,
`endpoints-20261109T094251Z-ec5fa3f7` and
`endpoints-20261109T094906Z-42e24939`. Archived sources and the captured frame
hashes were checked. Failed harness/startup/readback attempts are retained too;
disconnected-route failures were never counted as successful isolation. Guest
Wi-Fi preferences were restored. Completed emulator checks recorded console
acknowledgement, exit code zero and empty captured Jobs. SDK `adb.exe` helpers
did run and fail to bind the reserved smart-server port; no sampled listening
ADB server is a narrower claim than no ADB process. The disabled Netsim branch's
assigned final zero is not an independent process measurement.
The later independent `logs/final-continuation-process-inventory.json` found no
remaining processes whose executable was under this isolated SDK directory.

Per-device ADB trust is the next approval gate. The published emulator source
supports preseeded matching key files in each child's private
`ANDROID_EMULATOR_HOME`, before fallback to personal-profile keys. Booting a
fresh image this way installs persistent guest debugging trust, so the earlier
approval to read existing keys does not authorize it. A concrete config-only plan
is prepared at `validation/native-android-test/logs/per-user-key-proof-plan.json`,
with source/config hashes, fresh-tree checks and a guarded runner. It requests
two new key pairs, proof-directory ACLs restricted to the current Windows user
and SYSTEM, and two fresh AVDs under `validation/native-android-test/per-user-proof`.
No new key or guest trust has been created; approval is pending, not denied.
This would test separate device keys/data under one Windows identity, not two
Windows owners or the complete broker boundary. Existing AVDs will not be
rekeyed, reset or migrated. See `D-2026-11-09-05`.

The phone toolbar now also exposes volume down/up and a separate sleep/wake key
beside Back, Home and Recents, using the same existing phone actions as the side
keys. These hardware controls are hidden in web-only preview. Process Turn off,
rotation and applicable folding retain their separate controls. This interface
change does not enable the proposed native provider.
The existing actual-app Chromium case passed with explicit stream/transfer
fixtures and recorded clicks for all three added keys. A legacy crop assertion
initially raced layout; it now waits for the same required geometry. Desktop and
narrow-preview screenshots were retained and visually checked. This is browser
verification, separate from the real SDK runtime checks above.

The proposed native worker would reuse the narrow phone operations in
`workstation/protocol.py`: lifecycle/status, streamed display, input, device controls
and selected-byte transfer, all bound to the authenticated owner. A trusted Windows
broker, outside agent-controlled guests, would own the emulator and ADB processes,
per-user AVD directories/ACLs, and host-enforced restrictions on **every** raw ADB,
console and gRPC entry point. Different ports or Windows usernames alone are not
that boundary. It would need an explicit operator-configured worker role; it must
not impersonate the existing Linux VM backend to bypass its checks. Capture, input
and transfers must operate the same device through that broker.

Agent interaction does not require a custom Android build or an MCP server inside
the guest. The existing Linux phone protocol already mediates screenshots, UI
marks, touch/key input, device controls and selected-file transfer, with the same
person/agent holder boundary. The proposed Windows adapter must preserve those
owner checks and user takeover, record authorized actions without logging secrets
or file contents, and keep raw ADB, console and unrestricted shell private. Apps
can initially be opened through their UI; a dedicated app-launch operation would
need explicit validation and authorization. No native adapter or guest MCP is
implemented here.

The owner supports an **optional internal companion APK**, delivered directly to
their emulated device, with no Play Store listing. It remains future work after
real boot, per-user isolation and selected-transfer acceptance. Pair each install
to one authenticated owner/device with revocable credentials; request only needed
permissions with explicit consent. Use an operator-configured reachable broker
address and authenticated encrypted transport. Android guest loopback is the
guest itself, not Pantheon's host loopback, and emulator networking is not a tenant
boundary. Constrain the connection to that broker and preserve Android permission
checks. Installs/updates need a trusted signing identity, verified artifact hashes
and an authorized update path; credentials must not enter screenshots or logs. A
custom AOSP service would need a demonstrated gap and separate review of its
permissions, privacy and applicable SDK/GMS/licensing terms. No companion APK is
built, installed or connected by this change.

Installed emulator metadata supports the host-manager/Android-guest/separate-disk
architecture; it does not reveal proprietary stream internals. LDPlayer documents
[instance management and ADB commands](https://www.ldplayer.net/support/introduction-to-ldplayer-command-line-interface.html),
which is evidence of a management interface, not integration or redistribution
rights. No vendor implementation or image is copied into Pantheon. Google SDK/GMS
terms remain separate from AOSP's component licences.

Before enabling a native provider: close the demonstrated guest-to-host control
exposure, wire the actual stream/touch and selected-file checksum path, then
attack it from a second Windows identity and guest-root
in Android/Linux, including access through WSL/Docker. Check ports, device files,
account sessions and the broker's credentials. The local native SDK boot passed;
this two-user acceptance and the native Pantheon integration remain open. No
personal-account readiness is claimed.

The Android start action **never substitutes Firefox**. A separate *Open browser
preview (web only)* action runs Firefox with the selected profile, mobile user
agent and touch events. It persistently says **Browser preview · Web only**.
Apps, Play Store, sign-in to Android and Android file transfer are unavailable in
that preview. Every device profile
runs **generic Android** when Android is available. Profiles approximate the
selected device's size, density, body and fold; they do not provide retail
device identity, OEM firmware or certified hardware behavior. The folded display
uses a region of the inner display, rather than a second OEM cover panel.
Preview port discovery has a real deadline even for silent or newline-free Firefox
output. Stop cancels its owned process without waiting for the phone's status lock.
Display startup and teardown run on a separate lifecycle worker; a replacement
waits for the old display to be released. A failed or cancelled old worker cannot
publish itself or close the replacement's screen. These fixes were exercised with
controlled processes and a fresh real Firefox/KasmVNC preview, not a captured live
stack trace or an Android boot.
iPhones cannot be emulated by this Android backend. Each running
phone takes about `PANTHEON_PHONE_MEMORY_MIB` (8 GB); at most
`PANTHEON_PHONE_MAX_RUNNING` (2) run at once, and one nobody has used or
watched for `PANTHEON_PHONE_IDLE_MIN` (30) minutes is saved and stopped. Each user's
ADB server, emulator console and ADB device port remain inside their VM; only that
VM's authenticated workstation daemon is forwarded, never those Android ports.

The cockpit's **Workspace** offers **Documents**, **Workstation**, **Browser**
and **Mobile Emulator**. The emulator docks, floats and fills the workspace like
the other surfaces, and the Workbench's Devices room still opens the same device.
Turn on starts a cold Android boot with its own boot animation enabled; installed
apps and settings remain on the device's persistent disk. The side Power key
starts an off device and sleeps or wakes a running Android device. *Turn off*
stops the emulator. Back, Home, Recent apps and the side volume keys operate
Android. Fold/Unfold and Rotate animate the body only after the device command
succeeds, with reduced motion respected. They resize the shared screen used by
people and agents; the animation is presentation, not a model of physical hinge
mechanics. Live capture is attempted once Android's display service is running;
the earliest boot frames depend on when that image accepts scrcpy. Before that,
the screen shows that it is waiting for Android. Cold boots can take minutes on
first use.
Agents can take screenshots of that same live boot display; touch and numbered
UI marks wait for Android to finish booting.

Update the workstation image along with the Pantheon UI to receive the new boot
and active-display behavior. Rebuild the VM host too; guest daemon code and the
current Android installer are loaded read-only on its next VM start, including
for an existing VM disk. Older daemon Android answers without per-user isolation
metadata are refused by both the UI and agent client, including their stream;
Stop remains available. Animated physical rotation and the early boot stream
need the updated daemon. Provisioning installs a checksum-pinned scrcpy client
and server together in the SDK volume; Ubuntu 24.04's older scrcpy cannot capture
the default Android 15 image. Existing SDK installations are reused while the
display bridge is upgraded. The pin and checksum come from
[scrcpy's tagged Linux release instructions](https://github.com/Genymobile/scrcpy/blob/v3.3.4/doc/linux.md).

To install an APK, put it in the workstation and use its per-account
`adb install -r /path/to/app.apk`, or ask the agent to do so. Use Home to launch
apps and *Open a web address* for the optional URL tool. No APK or app store is
downloaded merely by opening this workspace surface.

The **Android image** selector offers the existing Android 15 **Google APIs**
image (Play services, no Play Store) and **Google Play (developer image)**
(`system-images;android-35;google_apis_playstore;x86_64`, present in Google's
[image manifest](https://dl.google.com/android/repository/sys-img/google_apis_playstore/sys-img2-3.xml)).
Choosing Play is explicit and asks for agreement even if the SDK was installed
for another image. Different image packages have **separate AVD storage**;
switching back restores that image's own apps and data. A matching legacy AVD is
reused; an incompatible or ambiguous saved image is never rewritten into another
OS. No image is silently upgraded or wiped. The SDK's package terms are accepted
only for the packages being installed, not every agreement in its catalogue.

Play images are release-signed and do not offer `adb root`. Sign in directly on
Android, using its own screens; Pantheon has no Google password form. Your own
agents can operate this same device and see its account sessions; host admins
remain trusted. Emulator/profile identity does not guarantee Play Integrity,
banking/DRM support, app availability, CTS certification or a retail device. See Google's
[AVD documentation](https://developer.android.com/studio/run/managing-avds).
SDK tools and images are separately licensed downloads, not relicensed as open
source by this repository. The operator must accept and comply with the
[Android SDK License](https://developer.android.com/studio/terms), including its
use and redistribution restrictions. Do not redistribute built SDK images on
the assumption that Pantheon's source license covers them. OEM-specific systems
are a future possibility only if a compatible image can be legally obtained,
used for the intended purpose, and legally redistributed under its actual terms;
no OEM software is included or promised by this uplift.

Android's open-source core (AOSP) and Google's SDK/Play software have different
licences. Offering this integration in open-source code does not confer rights
to redistribute Google images or operate a general-purpose hosted Play service.
The SDK agreement limits its granted use to Android application development.
No Google SDK image or Play package is committed to this repository or downloaded
without an explicit installation choice. This change is a development integration,
not a claim of distribution rights for a consumer Android service.

For the independent host worker and Docker pairing, see [Independent Android host](android-host.md).

**Apple Silicon runtime proof (2026-11-09; outside the product).** With the
owner's SDK and ARM-image licence acceptance, Emulator 37.2.13, platform-tools
37.0.1 and API 35 Google Play ARM revision 9 were installed from Google's
catalogue with archive size and checksum verification. A fresh private AVD
uses Hypervisor.Framework directly, independently of Docker's desktop and
without personal SDK keys or Google sign-in. Direct authenticated ADB reached
Android 15, resumed Settings and sent a fresh 32 KiB payload whose guest-side
SHA-256 matched. An independent untrusted key was refused; that is one-device
authentication evidence, not a two-owner isolation result.

The first stop exposed a late SDK ADB smart-server start and a Netsim helper.
The scoped harness now supplies a non-executing custom ADB path, reserves the
smart-server ports and inventories private SDK executable identities and
listeners before and after shutdown. Later runs observed no smart server or
leftover SDK process; these snapshots are not lifetime listener attestation.
Earlier low-memory/software-rendering trials exposed UI stalls. With 4 GiB RAM,
four vCPUs and `host` rendering plus `GuestAngle`, a stricter run verified an
actual Settings touch transition, a prior selected file surviving a cold boot,
another exact transfer with sync, and natural guest poweroff. Hidden stale
WindowManager error records are distinguished from visible dialogs.

Disabling Bluetooth's host backend caused Android HAL crashes. A separate
network-none, read-only Docker Netsim instance with an authenticated fixed-target
host relay let the real Android guest reach Bluetooth ON. Two independently
keyed radio instances passed workstation-root cross-owner transport negatives;
their trusted connections worked before and after. This is not two-real-VM or
Android-root acceptance. The native worker and renderer now have app routes and a shared phone UI; live product acceptance remains in progress.

The standard Google APIs ARM image was then installed under byte-identical
accepted ARM terms. Its default ADB listener returned CNXN without an AUTH
challenge, so the private client refused it before signing or executing a
command. SDK boot-property switches did not fix that refusal. A separate
derived boot-policy ramdisk is under test; it is not an accepted runtime.
To fit the owner's disk budget, immutable image archives are removed after
verified extraction and only one system-image cache is retained at a time;
private userdata and the pinned restore package records are kept separately.
Ordinary application networking, lifetime listener isolation, rooted/two-owner
tests, real image switching and product integration remain open. See
`D-2026-11-09-07`; these proofs do not change the shipping VM/KVM guards.

**USB tether · send files to Android** transfers one chosen upload or one owned
Pantheon document's **current text** (Markdown stays `.md`, other text uses `.txt`).
Use *Upload a file* for binary originals such as PDFs, images or APK files.
Nothing is installed or executed by a transfer. Each transfer is bounded to
20 MB and goes into a unique folder under `Download/Pantheon` on the caller's
running Android device. Android's returned SHA-256 must match the bytes sent.
There is no blanket host mount, arbitrary host path, user selector or network
tether; browser preview cannot receive Android files. Temporary staging files
are private to that user, with cleanup attempted after success or failure.

**Transfer hardening (2026-11-09).** The existing Linux VM path retains the
official SDK `adb push` sync service. Before staging private bytes, it requires
an allocated device serial, a current authorized transport and completed boot.
An explicit false system-user CE property asks the person to unlock Android;
missing/unknown values remain compatible with configured images and are not
proof of general user readiness. The copy and its checksum still decide success.

Admission uses the existing lifecycle lock with a bounded wait. Admission,
readiness and ADB commands share one transfer budget; an expired queued request
does not receive a fresh budget or proceed into staging. Local filesystem calls
are synchronous and are not a hard wall-clock guarantee. No push retry is added.
Verification requires one standard SHA-256 record naming the exact generated
destination, preserving spaces in filenames. A changed serial refuses subsequent
verification and cleanup instead of addressing a default or replacement device.

Failures retain the protocol's existing code/message shape with actionable
readiness, staging, preparation, send and verification messages. Unconfirmed
Android cleanup is reported without replacing the primary failure; a cleanup
timeout cannot relabel that failure. Private staging cleanup failures are logged
without file contents or remote diagnostics. If Android verified the file but
private cleanup was not confirmed, the response says so instead of reporting
complete success.

The final offline Linux regression slice passed 230 cases across transfer,
device and lifecycle coverage, using real private filesystem staging,
application/daemon HTTP and explicit ADB fixtures. It covers queued requests,
deadline expiry, stale/locked devices, selected SDK arguments, malformed checksum
records, cleanup failures and ownership/holder gates. These are hermetic checks,
not new Android/KVM runtime acceptance or a resolution of the prototype EPERM
finding above. Evidence is in the task workspace's
`validation/transfer-linux-20261109-5/transfer-tests.xml`. Native transport/proof
files and their pending key-approval plan were not changed; no Android credentials,
trust, host security settings or live deployment were changed by these tests.

For local testing from `dev`, build from that checkout: the repository's Docker
publish workflow currently runs on `main` only, so pulling a `:dev` registry tag
does not establish that this source is running. Rebuild Pantheon and the VM host
in your own test stack; no SDK download is part of an ordinary source build.

For an opt-in isolation check, build a **separate test image** with
`docker build -f workstation/vm.Dockerfile -t pantheon-isolation-check workstation`,
then run the harness in a fresh container with no network or existing volumes:

```bash
mkdir android-isolation-results
docker run --rm --network none --workdir /work \
  --mount "type=bind,source=$PWD,target=/work,readonly" \
  --mount "type=bind,source=$PWD/android-isolation-results,target=/results" \
  --entrypoint python3 pantheon-isolation-check \
  -u scripts/check-android-isolation.py --output /results
```

Use a new empty results directory each time. The script verifies the pinned
Ubuntu cloud-image hash, uses fresh disposable qcow2 disks, and runs two real
TCG Linux kernels with the shipped daemon and VM routing. Guest-root probes
check cross-user files and session **markers**, authenticated daemon ports,
fixture listeners standing in for ADB/console, and each user's separate fixture
9p project export, including sibling and symlink reads. JSON results and serial
logs are retained; the test disks and tokens are removed. This verifies those
specific isolation checks, **not Android, real ADB, Google sign-in, KVM, or all
possible hypervisor/9p exploits**. Android acceptance still requires a suitable
KVM host and an explicitly authorized SDK install.

An unset *sudo* choice is on in each user's own VM and off in the shared
container; an admin can choose explicitly. In the shared container, enabling
sudo lets one person's agent read another's workstation home, and the panel
says so beside the switch. In a person's own VM, root reaches only their
machine. The network is full by default too — an admin narrows it to
*internet only* or *none* in the same panel, held by the small
`workstation-net` container beside the container backend, so an agent using
*sudo* cannot lift it (`P20-06`). Neither backend has access to Docker or to
Pantheon's data, except the projects folder (`data/projects`, shared
read-write so a project is the same folder on both sides, `B1417`; on the VM
backend each person's machine is given their own folder and no other, `B1427`).

**The browser does not need a workstation.** Pantheon's image has a headless
Firefox of its own. The agents' `agent_browser` tool and the browser window use
the workstation's Firefox when the workstation answers, and Pantheon's whenever
it does not (switched off, still starting, or not allowed for that person). The
person watches and takes control of either from the same window. Pantheon's
browser reaches public addresses only, plus the local network when an admin has
turned on *agent LAN reach* and the person may use the workstation; never
Pantheon's own services.

**The screen is live** (`D-2026-10-31-01`). Each person's desktop is
KasmVNC's X server, and the Workstation window shows it as it moves, with the
mouse and keyboard yours while you hold it (*Take over*, *Hand back*). Text the
workstation copies lands on your clipboard (or behind a *Copy* button where the
browser wants a press first); *Paste* sends yours to the workstation. The
stream reaches only the person whose desktop it is, from Pantheon's own pages,
and an admin watching someone else's sees it view-only. After updating, run
`docker compose up -d --build` once: the workstation's image gains KasmVNC, and
the VM backend makes its machine image again on first use (minutes with KVM).
Where there is no stream — a workstation not yet rebuilt, a native install
without the client (`PANTHEON_DESKTOP_CLIENT_DIR`) — the window shows the
screen as pictures, a few a second, and says why under it.

**The browser is live too, on a screen of its own** (`D-2026-11-01-01`). The
agent's Firefox runs alone on a second KasmVNC screen, apart from the desktop,
and the Browser window shows it as it moves: Firefox's own tabs and address
bar, yours to use while you hold it, with the same *Paste* and *Copy*. The
agent drives and sees it as before. This holds for the workstation's browser
and for Pantheon's own (Pantheon's image carries KasmVNC's server as well, and
runs it as Pantheon's own user), so rebuild both images:
`docker compose up -d --build`. A native install without KasmVNC, or a
workstation not yet rebuilt, keeps showing the browser as pictures and says why.

**Computer Use** (`D-2026-11-01-02`). In Settings → Workstation, or with the
*Computer Use* button on the screen window, a person lets the agent act inside
their own workstation without an approval card — clicking, typing, running
commands, installing software — after accepting a warning: what the agent reads
there can steer it, and the workstation reaches the internet. A command that
deletes or overwrites files still asks (the projects folder is shared with
Pantheon), and nothing outside the workstation is lifted. It is held to people
with both *Auto-approve* and the workstation under Settings → Users; an admin
sees who has it on, and can turn it off, under Auto-approve there.

**A starting point of your own.** *Save starting point…* (in the panel and on the
screen window) makes the workstation as it is now what *Reset* puts back;
*Forget starting point* returns Reset to the image's clean start. On the
container backend it is the person's home — what was installed system-wide with
`sudo` stays until `docker compose up -d --force-recreate workstation`; on the
VM backend it is the machine's whole disk, saved with the machine powered off
and started again after. Starting points are kept by the workstation, beside
the homes (`/home/.pantheon-workstation/starting-points` in the container,
`starting-points/` in the VM host's state), out of every person's reach.

**The desktop is XFCE, in the cockpit's look** (`D-2026-10-31-02`): Pantheon's
window frames and wallpaper, and a panel along the bottom with the Pantheon
menu (it searches every program), Terminal, Firefox, Files, the open windows
and a clock. Every setting is a file in the person's home (`~/.config`), so
*Reset to clean* brings the look back with the rest; a home from before the
change is given those files on its next start, and keeps any of its own. The
look is drawn by `scripts/make-workstation-theme.py` from the default theme's
colours: change the colours there, run it, and rebuild. A workstation without
XFCE installed starts the older JWM desktop instead.

**Starting and stopping the backends from Pantheon** (`B1478`, opt-in). Without
the host's Docker both backends run (an idle VM host runs no machine) and
*Backend* chooses which one answers. Add `docker/host-docker.yml` to
`COMPOSE_FILE` and choosing one also starts that backend and stops the other,
and the panel lists the workstation's containers with Start, Stop, Restart and
Logs. That overlay gives Pantheon the host's Docker socket — broad control of
the host, the same opt-in the Forge uses — and Pantheon uses it here only on its
own compose project's workstation services: it lists, starts, stops, restarts
and reads logs, and never creates, pulls or removes anything.

`docker/workstation.yml`, `docker/workstation-vm.yml` and
`docker/workstation-both.yml` used to add the workstation; they still load and
add nothing. An install that used them should run
`docker compose up -d --build --remove-orphans` once.

**Docker GPU overlays.** CPU-only users can skip this section. Forge can
only detect GPUs that Docker exposes to the container — if the host runtime or
device passthrough is not configured, Forge sees the iGPU, another card, or
CPU instead of your intended GPU.

For NVIDIA, `scripts/check-docker-gpu.sh` diagnoses GPU passthrough and can
optionally install the host runtime or update `.env`.

```bash
# Read-only diagnostic (default — installs nothing, never edits .env):
scripts/check-docker-gpu.sh

# Print OS-specific install commands without running them:
scripts/check-docker-gpu.sh --print-install-commands

# Install NVIDIA Container Toolkit on Ubuntu/Debian (requires sudo):
scripts/check-docker-gpu.sh --install-nvidia-toolkit

# Write COMPOSE_FILE to .env (only when GPU passthrough is confirmed working):
scripts/check-docker-gpu.sh --enable-nvidia-overlay

# Full assisted setup — install toolkit, then enable overlay if passthrough works:
scripts/check-docker-gpu.sh --install-nvidia-toolkit --enable-nvidia-overlay
```
#### Arch Linux NVIDIA Docker notes

On Arch Linux, verify the host NVIDIA driver and Docker GPU passthrough before enabling the Pantheon NVIDIA overlay.

Install the required packages:

```bash
sudo pacman -Syu
sudo pacman -S docker docker-compose nvidia-container-toolkit nvidia-utils
sudo systemctl enable --now docker
```

Configure Docker to use the NVIDIA container runtime:

```bash
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Verify the host GPU:

```bash
nvidia-smi
```

Verify Docker GPU passthrough:

```bash
docker run --rm --gpus all nvidia/cuda:12.9.0-base-ubuntu22.04 nvidia-smi
```

Then enable the Pantheon NVIDIA compose overlay:

```env
COMPOSE_FILE=docker-compose.yml:docker/gpu.nvidia.yml
```

Rebuild and verify the GPU inside the Pantheon container:

```bash
docker compose up -d --build
docker compose exec pantheon nvidia-smi -L
```

For first-time local model testing on 8 GB laptop GPUs, start with GGUF/Q4 models on llama.cpp before trying GPTQ/AWQ models on vLLM or SGLang. This keeps the first run simpler while confirming GPU passthrough works.

**WSL2 + snap Docker.** If the NVIDIA check fails with this error, Docker may be
installed via snap:

```text
failed to fulfil mount request: open /usr/lib/wsl/lib/libdxcore.so: no such file or directory
```

Check with `snap list docker` or:

```bash
docker info --format '{{.DockerRootDir}}'
```

A Docker root under `/var/snap/docker/` means snap confinement can prevent
Docker from seeing WSL2's `/usr/lib/wsl/lib` GPU libraries even when the files
exist on the host. Reinstalling or reconfiguring `nvidia-container-toolkit` will
not fix that. Remove snap Docker, install the official apt-based Docker Engine
([Docker docs](https://docs.docker.com/engine/install/ubuntu/)), then configure
the NVIDIA runtime again:

```bash
sudo snap remove docker
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Then re-run `scripts/check-docker-gpu.sh`.

Safety notes:
- The app never installs host GPU runtime automatically.
- The app never edits `.env` automatically.
- `.env` is only modified when `--enable-nvidia-overlay` is explicitly passed,
  and only after GPU passthrough succeeds. `--yes` skips prompts but does not
  bypass the passthrough gate.
- `.env.bak.*` backups created by `--enable-nvidia-overlay` are ignored by
  Git and the Docker build context.

To enable manually without the script, add this to `.env`:

```bash
COMPOSE_FILE=docker-compose.yml:docker/gpu.nvidia.yml
```

**AMD / ROCm.** AMD setup is read-only diagnostic plus manual `.env` edit. Run:

```bash
scripts/check-docker-amd-gpu.sh
```

Then add the reported values to `.env`, replacing `RENDER_GID` with your host's
numeric render group id:

```bash
COMPOSE_FILE=docker-compose.yml:docker/gpu.amd.yml
RENDER_GID=989
```

For NVIDIA/AMD GPU support, also read the comments in the selected overlay file: docker/gpu.nvidia.yml or docker/gpu.amd.yml.

**Stack-management UIs (Portainer, Coolify, Dockhand, etc.).** These tools
often accept only a single Compose file and do not reliably honor `COMPOSE_FILE`
or multiple `-f` overlays. CLI users should keep using the `COMPOSE_FILE`
overlay workflow above. For stack UIs, point the stack at one of the standalone
files instead, which bundle the base stack plus the GPU settings:

- `docker-compose.gpu-nvidia.yml` — still requires the NVIDIA Container Toolkit
  on the host.
- `docker-compose.gpu-amd.yml` — still requires host ROCm/kfd/DRI setup, the
  `video`/`render` group membership, and `RENDER_GID` when needed.

The base `docker-compose.yml` plus the `docker/gpu.*.yml` overlays remain the
source of truth; the standalone files mirror them for single-file deployments.

Verify after enabling either overlay:

```bash
docker compose exec pantheon nvidia-smi -L   # NVIDIA
docker compose exec pantheon sh -lc 'test -e /dev/kfd && test -d /dev/dri && ls -l /dev/kfd /dev/dri/renderD*'  # AMD
```

> **GPU passthrough ≠ llama.cpp CUDA.** `nvidia-smi` passing inside the
> container confirms Docker GPU access, but llama.cpp also needs `cudart` and
> the CUDA Toolkit at runtime. If Forge logs show `Unable to find cudart
> library`, `Could NOT find CUDAToolkit`, `CUDA Toolkit not found`, or
> tensors/layers assigned to CPU, that is a Forge/llama.cpp build issue —
> not a Docker passthrough failure. Reinstall the serve engine via
> **Forge → Dependencies** to get a CUDA-enabled build.
>
> The same split applies to AMD/ROCm: seeing `/dev/kfd` and `/dev/dri` inside
> the container confirms device passthrough, not ROCm userspace or a
> ROCm-enabled vLLM/llama.cpp build. `rocm-smi` and `rocminfo` are not expected
> inside the slim Pantheon image.

**Ollama with Docker.** If Ollama runs on the host, add this endpoint in
Settings:

```text
http://host.docker.internal:11434/v1
```

Ollama must listen outside its own loopback interface:

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

This connects Pantheon in Docker to an Ollama server that is already running on
your host machine; it does not start Ollama inside the container.
`host.docker.internal` is Docker's hostname for the host machine from inside the
container. Forge **Serve** is a separate workflow for serving downloaded
models through Pantheon/llama.cpp, so Windows users with an existing Ollama
install usually only need to add the endpoint in Settings.

**Tool calls not firing on a manually-added Ollama `/v1` endpoint.** By
design, a local Ollama `/v1` endpoint defaults to the conservative
text-based (fenced-block) tool-calling path rather than native structured
tool calls, since some locally-served models mishandle native schemas (see
#1567). This is correct for most local setups, but if you know your specific
model reliably supports native tool calling (check `ollama show <model>` for
`tools` under Capabilities), you can opt that endpoint in explicitly. There
is currently no UI control for this on manually-added endpoints (see #5192);
the flag can still be set directly against the existing API, from a browser
console on an authenticated admin session:

```js
fetch('/api/model-endpoints/<endpoint-id>', {
  method: 'PATCH',
  credentials: 'same-origin',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({supports_tools: true})
}).then(r => r.json()).then(console.log)
```

Find `<endpoint-id>` by inspecting the `/api/model-endpoints` response (or
your browser's network tab while Settings loads the endpoint list). Send
`supports_tools: false` to disable native structured tool calls and force the
conservative fenced/text path, or `supports_tools: null` to return the endpoint
to the Auto heuristic.

**Useful checks.**

```bash
docker compose ps
docker compose logs --tail=120 pantheon
docker compose logs pantheon | grep -E 'ChromaDB|MemoryVectorStore|DEGRADED'
```

**macOS details.** `start-macos.sh` installs Homebrew deps, creates the venv,
runs setup, and starts uvicorn on port `7860` because AirPlay often holds
`7000`. It uses llama.cpp/Ollama for Metal. vLLM/SGLang are CUDA/ROCm-only and
do not run on macOS. MLX-only models are not served by Pantheon.

</details>

### Native Windows

**One-command launcher** (creates the venv, installs deps, runs setup, starts the
server; safe to re-run):

```powershell
git clone https://github.com/ImPanick/pantheon.git
cd pantheon
powershell -ExecutionPolicy Bypass -File .\launch-windows.ps1
```

Or do it by hand:

```powershell
git clone https://github.com/ImPanick/pantheon.git
cd pantheon
py -3.11 -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
python setup.py
python -m uvicorn app:app --host 127.0.0.1 --port 7000
```

If `python` points at an older interpreter, use `py -3.12` (or another installed
3.11+ version) for the venv step.

**Exposing on a LAN/Tailscale (Windows):** the launcher binds to `127.0.0.1` and
does **not** read `APP_BIND` / `PANTHEON_HOST` from `.env`, so editing `.env`
alone leaves the native Windows server on loopback. Pass the launcher's
`-BindHost` flag instead:

```powershell
powershell -ExecutionPolicy Bypass -File .\launch-windows.ps1 -BindHost 0.0.0.0
```

The manual `uvicorn` command takes the same address as `--host 0.0.0.0`. Bind
outside loopback only for a trusted LAN/VPN such as Tailscale, once the admin account
exists, and do not expose the port directly to the public internet.

**Requirements:** Python 3.11+. The core app (chat, agent, memory, documents,
email, calendar, deep research) runs fully native. For full **Forge** background
model downloads and the agent shell tool, also install
[Git for Windows](https://git-scm.com/download/win) (provides `bash.exe`).
Local GPU *serving* of vLLM/SGLang needs Linux/WSL2; for a local model on Windows,
[Ollama](https://ollama.com/download) is the easiest path — point Pantheon at
`http://localhost:11434/v1` in Settings.

Open `http://localhost:7000`, log in with the generated admin password,
and configure everything else inside **Settings**.

## Troubleshooting & Advanced Setup

### `chromadb-client` conflicts with embedded ChromaDB
If `chromadb-client` (the lightweight HTTP-only package) is installed alongside the full `chromadb` package, Pantheon starts but ChromaDB silently falls back to HTTP-only mode and fails.

**Fix:** uninstall `chromadb-client` and force-reinstall the full package:
```bash
./venv/bin/pip uninstall chromadb-client -y
./venv/bin/pip install --force-reinstall chromadb
```

### HTTPS + LAN/Tailscale exposure
To expose Pantheon on a local network or Tailscale with HTTPS:
1. Change the bind address to `0.0.0.0` in `.env` (`APP_BIND=0.0.0.0` or `PANTHEON_HOST=0.0.0.0`).
2. Generate a locally-trusted cert for your LAN/Tailscale IPs using [mkcert](https://github.com/FiloSottile/mkcert):
   ```bash
   mkcert -install
   mkcert -cert-file cert.pem -key-file key.pem 192.168.1.100 tailscale-ip
   ```
3. Run `uvicorn` with the generated certs:
   ```bash
   python -m uvicorn app:app --host 0.0.0.0 --port 7000 --ssl-certfile=cert.pem --ssl-keyfile=key.pem
   ```
4. Install the `mkcert` CA on any other device you want to access Pantheon from (e.g., for iOS, email the `rootCA.pem` to yourself, install the profile, and trust it in Certificate Trust Settings).

### Reach Pantheon from your phone (push and lock-screen approvals)
Settings → Reminders → **Push to your devices** turns on notifications that arrive with Pantheon closed. When the agent asks before it acts, the question lands on the phone with **Approve** and **Deny** on it; the answer goes through the same approval check as the card in the chat, signed in as you on that phone.

Browsers only allow push on a secure page: `https://`, or `localhost` on the machine itself. A phone opening `http://192.168.x.x:7000` cannot turn it on, and the card says so. The least work is [Tailscale](https://tailscale.com/) on the Pantheon machine and the phone:

1. In the Tailscale admin console, turn on MagicDNS and HTTPS certificates.
2. On the Pantheon machine: `tailscale serve --bg 7000` (Pantheon keeps listening on `127.0.0.1`; Tailscale carries it). It prints an address like `https://pantheon.your-tailnet.ts.net`.
3. On the phone, with Tailscale connected, open that address, sign in, then Settings → Reminders → *Turn on for this device*, and *Send a test*.

Your own reverse proxy with a real certificate (Caddy, nginx) works the same way, and so does the `mkcert` route above once the phone trusts its CA. A companion pairing token is not enough for approvals: only a signed-in person may answer one, so sign in in the phone's browser.

- **Android:** Chrome, Edge, Firefox and Samsung Internet show Approve and Deny on the notification. On the lock screen the phone may ask you to unlock first; that is the phone's setting.
- **iPhone / iPad (iOS 16.4 or later):** add Pantheon to the Home Screen (Share → Add to Home Screen) and turn push on from that icon. iOS shows the notification without the two buttons; tapping it opens the chat at the card.
- **Desktop:** works in any current browser; Windows and macOS show the buttons in their notification centre.

What leaves the machine: each push goes to the push service of the browser you turned it on in (Google for Chrome/Android, Mozilla, Apple, Microsoft), encrypted so that service cannot read it. Nothing is sent before you turn push on. Pantheon keeps its signing key and your devices in the data folder (`push_vapid.json`, `push_subscriptions.json`); deleting the key turns push off on every device until each is turned on again. `PANTHEON_PUSH_HOSTS` adds a push service you run yourself; `PANTHEON_PUSH_CONTACT` sets the `mailto:` or `https:` contact push services see.

### Common self-host traps (30-second fixes)
A grab-bag of small gotchas that otherwise turn into long debugging sessions.

- **You're asked to sign in although `.env` says `AUTH_ENABLED=false`.** That is the product since 0.2.0: there is always a sign-in, and the variable is ignored (the log says so once at start). The first run asks for the admin account. Whether other people may make their own accounts is Settings → Users → *People can sign themselves up*, off by default.
- **You've lost the admin password.** Stop Pantheon, set a new one where its data lives, start it again (`B1272`) — every other account is untouched, and the person is signed out everywhere:
  ```bash
  docker compose stop pantheon
  docker compose run --rm pantheon python scripts/reset_password.py admin
  docker compose start pantheon
  ```
  (Native installs: `python scripts/reset_password.py admin` with the server stopped.) It asks for the password twice and never takes it from the command line; `--disable-2fa` also turns two-factor sign-in off, for a lost authenticator.
- **The first setting in `.env` is ignored (Windows).** If you edited `.env` in Notepad it may have saved a UTF-8 **BOM**, turning the first key into `﻿APP_BIND` (say) so it is never matched. Pantheon loads `.env` with `encoding="utf-8-sig"` to tolerate a leading BOM, but the safe fix is to re-save `.env` as **UTF-8 without BOM** (VS Code: *Save with Encoding → UTF-8*).
- **macOS: the app isn't at `http://localhost:7000`.** macOS AirPlay Receiver usually holds port `7000`, so the macOS start script serves on **`7860`** instead — open `http://localhost:7860`. To use `7000`, free it (System Settings → General → AirDrop & Handoff → turn off *AirPlay Receiver*) and set `APP_PORT=7000`.
- **Copy buttons do nothing over a plain-HTTP Tailscale/LAN URL.** Browsers only expose the clipboard API (`navigator.clipboard`) on **secure origins** — HTTPS, or `localhost`. Over `http://100.x.y.z:7860` it is blocked. Serve over HTTPS (see *HTTPS + LAN/Tailscale exposure* above); `localhost` is exempt, so copy still works on the host itself.
- **Self-hosted ntfy reminders don't reach your phone.** Two things: (1) the bundled ntfy binds to loopback by default — to reach it from your phone set `NTFY_BIND` to your host/Tailscale IP and `NTFY_BASE_URL` to the same server URL in `.env`, then recreate the ntfy container (see the `NTFY_*` block in `.env.example`); (2) in the ntfy **Android** app, subscribe to the topic with **Instant delivery** enabled — non-`ntfy.sh` servers don't get instant push otherwise.
- **Local mail (Dovecot) login fails: "Plaintext authentication disallowed on non-encrypted connections."** Your IMAP/SMTP server is refusing cleartext auth over an unencrypted link. Prefer enabling TLS on the mail server; on a trusted LAN only, you can allow cleartext (Dovecot: `disable_plaintext_auth = no`).
- **A mail account stops with "showed a different certificate from the one this account trusts" or "showed a certificate no trusted authority signed".** Pantheon checks the mail server's certificate before it sends a password or a sign-in token. A public host such as `imap.example.com` has to show a certificate an authority signed for its name, as every mail provider's does. A host on your own network has its first certificate remembered, and a different one later is refused. That covers a private or Tailscale address, a name with no dot such as `dovecot`, and a name ending `.lan`, `.local`, `.internal` or `.home.arpa`. If you replaced the server's certificate, or your own server answers on a public name with a self-signed one, open the account in Settings → Email and press **Test**. Check the fingerprint it shows against your server's, then press **Trust this certificate**. A mail provider's own hosts (Gmail's, Outlook's) are never trusted by hand. The remembered certificates are kept per member in `data/mail_tls_pins.json`.
- **A mail account's Test, inbox or send says "Pantheon will not connect this mail account to that server."** A member's mail account reaches public mail servers on mail ports (IMAP 143 and 993, SMTP 25, 465 and 587). A server on the Pantheon machine itself, on your private network (a `192.168.x.x`, `10.x.x.x` or Tailscale address, or a name that resolves to one), or on another port is reached only for an admin, or a member an admin allowed it: Settings → Users → **Mail servers on this network**. Without that, the account form could be used to find out which ports on your network are open. Link-local and cloud metadata addresses (`169.254.169.254` and the like) are refused to everyone.
- **Calendar/contacts (Radicale) won't sync.** Point Pantheon at the **full collection URL** with its trailing slash — e.g. `http://host:5232/<user>/<collection-id>/` — not just the server root. Radicale shows this address for each calendar/address book in its web UI.

### Speech on a native install
The Docker image installs `requirements-voice.txt` for you. On a native install, install it to use local Whisper and the Piper voice:

```bash
pip install -r requirements-voice.txt
```

Both install from wheels on Python 3.11–3.14, x86-64 and ARM64. With nothing baked, the Whisper model and the Piper voice are fetched from Hugging Face on first use, and only once *Download models from the internet* is on; or put a voice's `.onnx` and `.onnx.json` in `data/models/piper/` yourself. Piper is GPL-3.0-or-later (see `CREDITS.md`). The browser's own speech recognition and voice, and any OpenAI-compatible speech endpoint you add, need none of this.

The same packages speak with Kokoro on the CPU: its phonemes come from the espeak-ng Piper carries and it runs on Piper's ONNX Runtime. Its model is fetched on first use from the `kokoro-onnx` release on GitHub, only once *Download models from the internet* is on, and checked against the hashes Pantheon holds; or put `kokoro-v1.0.onnx` and `voices-v1.0.bin` in `data/models/kokoro/` yourself. Chatterbox needs Docker and an NVIDIA GPU (see *Chatterbox on an NVIDIA GPU* above).

### Optional Dependencies
`requirements-optional.txt` contains packages that unlock extra features. It is not installed by default.

| Package | Feature unlocked |
|---------|-----------------|
| `faster-whisper` | Local speech-to-text (microphone -> text) via the "local" STT provider. |
| `kokoro`, `soundfile` | Local Kokoro-82M text-to-speech on a CUDA GPU (the voice *Kokoro through PyTorch*). The pinned Kokoro release supports Pantheon installs on Python 3.11-3.12; these packages are intentionally skipped on Python 3.13+ (including the Python 3.14 container image). Kokoro on the CPU needs none of them: it comes with `requirements-voice.txt`. |
| `ddgs` | DuckDuckGo as a search provider option. |
| `PyMuPDF` | PDF page rendering in the side viewer panel and form-filling. (Note: AGPL-3.0) |
| `markitdown` | Office/EPUB document text extraction (converts .docx/.xlsx/.pptx/.xls/.epub to Markdown). |

Install the optional set only when you need these features:

```bash
pip install -r requirements-optional.txt
```

The default Docker image currently uses Python 3.14, while Kokoro 0.9.4 declares Python `>=3.10,<3.13`. Pantheon itself continues to support Python 3.11+, but this pinned optional local-TTS feature requires a native Python 3.11 or 3.12 environment. Kokoro declares `torch`, but the local provider only activates when that torch build has CUDA and a GPU is visible; install the CUDA build appropriate for your host. Browser and configured endpoint TTS remain available on Python 3.13+ and in the container image, and so does Piper, which speaks on the CPU (`requirements-voice.txt`, in the image by default).

### Faster, reproducible installs with uv (optional)
[uv](https://docs.astral.sh/uv/) works as a drop-in replacement for the
venv + pip steps in the native install guides, no project changes are needed but this change results in faster installs along with a lockfile for reproducible environments. After [installing `uv`](https://docs.astral.sh/uv/getting-started/installation/), use:

```bash
uv venv venv --python 3.13
uv pip install -r requirements.txt
# then continue as usual: python setup.py, uvicorn, ...
```

`requirements.txt` is intentionally unpinned, so two installs at different times can produce different package versions. If you want a reproducible environment (e.g. across your own machines, or to roll back after a bad upgrade), snapshot and restore exact versions with:

```bash
uv pip compile requirements.txt -o requirements.lock   # snapshot current resolution
uv pip sync requirements.lock                          # reproduce it exactly later
```

`requirements.lock` is gitignored and platform-specific (compile it on the OS you deploy to). Regenerate it deliberately when you want to take upgrades. The plain `uv pip install -r requirements.txt` keeps following the unpinned requirements like pip does.

### Outlook / Office 365 email
Outlook and Microsoft 365 mailboxes connect with **Sign in with Microsoft**
(OAuth) — a normal Microsoft mailbox password will fail over plain IMAP/SMTP.
[email-outlook.md](email-outlook.md) has the app registration and settings it needs.

## Security Notes
Pantheon is a self-hosted workspace with powerful local tools: shell access, file uploads, model downloads, web research, email/calendar integrations, and API tokens. Treat it like an admin console.

- Sign-in is always on (`D-2026-10-07-02` §2); `AUTH_ENABLED` and `LOCALHOST_BYPASS` are ignored. Make the admin account before the instance is reachable from anywhere but this machine, and leave registration (Settings → Users) off unless you want strangers to make accounts.
- Leave `SECURE_COOKIES` unset unless you need to override it: session cookies are marked `Secure` whenever the request arrives over HTTPS. Use `SECURE_COOKIES=true` to force it on for a proxy whose scheme Pantheon cannot see, or `SECURE_COOKIES=false` to force it off while you still serve plain HTTP alongside HTTPS.
- Do not expose it directly to the public internet without HTTPS and a trusted reverse proxy or private access layer.
- Keep `.env`, `data/`, `logs/`, databases, uploads, generated media, backups, auth/session files, API keys, and model/provider tokens out of Git and private shares. They are ignored by default.
- Review `data/auth.json` after first boot: disable open signup unless you intentionally want it, make only your own account admin, and keep demo/test accounts non-admin.
- Non-admin users do not get shell/Python/file read/write by default, and admin-only routes/tools such as MCP management, API tokens, webhooks, model/cookbook serving, backup/vault, and app settings are admin-gated. Other features are controlled by per-user privileges, so review each user's privileges before exposing a deployment.
- Rotate any API keys or tokens that were ever pasted into a shared chat, demo, screenshot, or log.
- If you enable API tokens or webhooks, create separate tokens per integration and delete unused ones.
- Prefer binding manual development runs to `127.0.0.1`; bind to `0.0.0.0` only when you intentionally want LAN/reverse-proxy access.
- Keep ChromaDB, SearXNG, ntfy, Ollama, vLLM, llama.cpp, databases, and raw model/provider APIs internal-only. Expose only the authenticated Pantheon web/API entrypoint through your trusted proxy or private access layer.
- Before publishing a fork, run `git status --short` and confirm no private files from `.env`, `data/`, `logs/`, uploads, backups, or local databases are staged.
- If you run a modified copy for other people, set `PANTHEON_SOURCE_URL` to your own published source — see [The Source link](#the-source-link--and-what-a-modified-copy-owes-its-users).

> **Upgrading an existing install:** `SECURE_COOKIES` used to default to
> `false`, so an install set up before scheme derivation may still carry
> `SECURE_COOKIES=false` in its own `.env`. That explicit value stays
> authoritative, so HTTPS logins keep getting a non-`Secure` session cookie.
> Pulling this change updates the tracked Compose files, but nothing rewrites
> your `.env` — drop the line from it unless you deliberately serve plain HTTP
> alongside HTTPS and want the escape hatch.

### Private or proxied deployments
Pantheon serves plain HTTP on its app port. Docker Compose binds Pantheon and the bundled services to `127.0.0.1` by default, so a typical production/private setup is:

1. Keep Pantheon on localhost, for example `127.0.0.1:7000`.
2. Terminate HTTPS at a trusted reverse proxy or private access gateway.
3. Put the authenticated Pantheon web/API entrypoint behind that layer.
4. Keep raw service and model ports internal-only.

Cloudflare Access, Tailscale, Caddy, nginx, and Traefik can all fit this pattern; none are required by Pantheon. If your access layer reaches Pantheon on the same host, proxy to `http://127.0.0.1:7000`; a request the proxy forwards from loopback signs in like any other. Any proxy that forwards `X-Forwarded-Proto: https` gets `Secure` session cookies without configuration, so `SECURE_COOKIES` only needs setting when you want to override that — force it on for a proxy that forwards no scheme at all, or off while you still serve plain HTTP.
`ALLOWED_ORIGINS` lists exact permitted origins for cross-origin browser/API clients; ordinary same-origin reverse-proxy access usually does not need a special CORS entry.

#### Serving under a path prefix

To serve Pantheon at `https://host/pantheon/` rather than at the root, have the
proxy strip the prefix and start uvicorn with the same prefix as its root path:

```bash
python -m uvicorn app:app --host 127.0.0.1 --port 7000 --root-path /pantheon
```

`--root-path` is the supported way to put Pantheon behind a prefix: every
redirect it builds (the sign-in redirect, the `/static` page redirects) and the
login page's own URLs carry the prefix. **Mounting Pantheon inside another
Python ASGI app** (`Mount("/pantheon", app=pantheon_app)` in a Starlette or
FastAPI app of your own) **is not supported**: inside a mount Starlette records
the outer app's prefix as empty for the mounted one, so Pantheon's redirects —
the sign-in redirect among them — drop `/pantheon` and send the browser to the
outer app's root (`B371`). Put a proxy in front instead.

#### Faster over the network: HTTP/2

The frontend is raw ES modules with no bundler, so a page load is a few hundred
small same-origin requests. Over HTTP/1.1 browsers typically allow only a small
number of concurrent connections per host (commonly around six), so many of
those requests are serialized across multiple round trips. On localhost that
costs almost nothing. Over a LAN, VPN, or remote link it can become a major
part of load time, especially as latency increases.

HTTP/2 multiplexes them onto one connection and the serialisation disappears.
Pantheon needs no changes for this — uvicorn keeps speaking HTTP/1.1 on
loopback and the proxy speaks HTTP/2 to the browser. Mainstream browsers
negotiate HTTP/2 for normal web pages over TLS; they do not use the cleartext
h2c mode here, so browser-facing HTTP/2 requires a certificate. The
`--ssl-certfile` route in *HTTPS + LAN/Tailscale exposure* above gives you
HTTPS but not HTTP/2 — uvicorn does not speak it.

**1. Install Caddy.** See the [install docs](https://caddyserver.com/docs/install)
for your platform; on macOS, `brew install caddy`.

**2. Write a `Caddyfile`.** Pick the block that matches how you reach the
machine. Replace `7000` if Pantheon listens elsewhere — the macOS start script
uses `7860`.

Public domain, Caddy obtains and renews the certificate itself:

```
pantheon.example.com {
	reverse_proxy 127.0.0.1:7000
}
```

Tailscale, no public DNS needed — `tailscale cert` issues a browser-trusted
certificate for a tailnet name and writes `<domain>.crt` and `<domain>.key`:

```bash
tailscale cert myhost.tailnet-name.ts.net
```

```
myhost.tailnet-name.ts.net {
	tls /path/to/myhost.tailnet-name.ts.net.crt /path/to/myhost.tailnet-name.ts.net.key
	reverse_proxy 127.0.0.1:7000
}
```

LAN with your own certificate — same shape, your own files:

```
pantheon.lan {
	tls /path/to/cert.pem /path/to/key.pem
	reverse_proxy 127.0.0.1:7000
}
```

Give `tls` absolute paths: a service starts in a working directory you did not
choose. If port 443 is already taken, append a port to the site address
(`pantheon.example.com:8443`) and use it in the URL. That alone does not free
port 80 — Caddy still binds it for the HTTP-to-HTTPS redirect, and fails to
start with `listen tcp :80: bind: address already in use` if something else
holds it. Turn the redirect off with a global block at the top of the file:

```
{
	auto_https disable_redirects
}
```

**3. Run it in the foreground first:**

```bash
caddy run --config ./Caddyfile
```

Once that works, run it as a service:

```bash
brew services start caddy          # macOS — reads $(brew --prefix)/etc/Caddyfile, not ./Caddyfile
sudo systemctl enable --now caddy  # Linux, if your package installed the unit
```

Pantheon's own service is unchanged; the proxy runs alongside it. Under Docker,
run the proxy as another container, or on the host pointing at the published
port.

**4. Point Pantheon at the new origin** in `.env`, then restart it.

A proxy that exposes the HTTPS request scheme to Pantheon needs no `SECURE_COOKIES` setting. Only force it on when the proxy cannot expose that scheme:

```bash
# only if the proxy cannot expose the external HTTPS scheme to Pantheon:
SECURE_COOKIES=true
# only if you use remote MCP servers with OAuth:
OAUTH_REDIRECT_BASE_URL=https://pantheon.example.com
```

Gmail OAuth needs nothing here when the proxy runs on the same host: the
redirect URI is built from the incoming request, and uvicorn rewrites the
scheme from `X-Forwarded-Proto` for proxies it trusts — by default only
`127.0.0.1`. A proxy in a separate container or on another machine is not
trusted, so pin the URI there:

```bash
GOOGLE_OAUTH_REDIRECT_URI=https://pantheon.example.com/api/email/oauth/google/callback
```

(uvicorn's own `FORWARDED_ALLOW_IPS` widens that trust, but it has to be in the
environment uvicorn starts with — `.env` is read by the app afterwards, too
late for it to take effect.)

**5. Confirm HTTP/2 is really on:**

```bash
curl -s -o /dev/null -w '%{http_version}\n' https://pantheon.example.com/
# 2
```

The status code is not the thing to check here — a logged-out request redirects
to the login page, so `curl -I` shows `HTTP/2 302`, and the `HTTP/2` prefix is
the part that matters. The browser reports the same in the Network panel's
Protocol column (`h2`); in Chrome and Firefox that column is hidden until you
enable it by right-clicking the column headers.

Three things bite when moving an existing install behind TLS:

- Leave `SECURE_COOKIES` unset when Pantheon can see the external HTTPS scheme;
  the cookie then follows the request automatically. If your proxy cannot expose
  that scheme, set `SECURE_COOKIES=true` **at the same time** you stop serving
  plain HTTP, not before. An explicit `true` applies to every login, so while an
  HTTP entrypoint is still reachable the browser will reject the `Secure` cookie
  there and login will appear to loop.
- `OAUTH_REDIRECT_BASE_URL` defaults to `http://localhost:7000`. Unlike the
  Gmail redirect URI it cannot be derived from a request — it is registered
  with each MCP authorization server up front — so set it to the external
  origin if you use remote MCP servers over OAuth.
- Pantheon sends `Strict-Transport-Security` (with `includeSubDomains`) once it
  sees `X-Forwarded-Proto: https`. HSTS applies to the whole hostname and every
  subdomain under it, and ignores the port, so any other plain-HTTP service on
  that hostname or below it becomes unreachable in browsers that have visited
  Pantheon. Give Pantheon its own hostname with nothing plain-HTTP beneath it,
  or strip the header at the proxy (`header_down -Strict-Transport-Security` in
  Caddy).

Server-sent events are not buffered by this configuration, so chat streaming
arrives token by token; add `flush_interval -1` inside the `reverse_proxy`
block if you want that pinned explicitly. nginx needs `proxy_buffering off;`
for the same reason.

Changing the external origin also affects state scoped to it. Service workers
and their caches are origin-scoped, so moving to a different origin starts with
a cold load. Cookies follow their own domain/path/security rules rather than
being port-scoped: changing the hostname normally requires a new login, while
changing only the scheme or port does not by itself guarantee that existing
cookies disappear.

Common internal-only ports from the default docs/compose setup:

| Port | Service |
|---|---|
| `7000` | Pantheon raw app port |
| `8080` | SearXNG (moved with `SEARXNG_HOST_PORT`) |
| `8091` | ntfy |
| `8100` | ChromaDB host port for manual/compose access |
| `11434` | Ollama |
| `8000-8020` | Common local model/provider APIs |

## Configuration
Most setup is done inside the app with `/setup` or **Settings**. Use `.env`
for deployment-level defaults and secrets you want present before first boot.

**Switches: what counts as on.** Every on/off variable below reads the same words:

| | accepted |
|---|---|
| **on** | `1` `true` `yes` `on` |
| **off** | `0` `false` `no` `off` |

Case does not matter and surrounding spaces are ignored. Anything else — an empty value, or a
word not in those lists — means *not set*, and the switch keeps its documented default: a
variable you never set and a variable you set to nothing are the same thing.

Six switches keep their own older rule because changing them would flip a running deployment.
They are listed at the top of `.env.example`. `AUTH_ENABLED`, `LOCALHOST_BYPASS` and
`PANTHEON_SINGLE_USER` are not switches any more: there is always a sign-in, and each is ignored
(named once in the log if set).

Key settings:

| Variable | Default | Description |
|---|---|---|
| `LLM_HOST` | `localhost` | Your LLM server (e.g. `llm-host.local:8000`) |
| `LLM_HOSTS` | -- | Comma-separated list for model discovery |
| `OPENAI_API_KEY` | -- | Optional OpenAI key. Prefer adding providers in the app unless pre-seeding. |
| `SEARXNG_INSTANCE` | `http://localhost:8080` | SearXNG URL. Docker overrides this to `http://searxng:8080`. |
| `SEARXNG_HOST_PORT` | `8080` | Docker Compose host port for the bundled SearXNG, on loopback. Change it when 8080 is taken, for example by llama-server's default, and recreate the stack. The app keeps reaching SearXNG at `http://searxng:8080` inside the compose network; a native install using this SearXNG sets `SEARXNG_INSTANCE` to the new port. |
| `SEARXNG_SECRET` | generated on first Docker boot | Optional SearXNG cookie/CSRF secret. Leave blank unless you need to pin it. |
| `SEARXNG_GENERAL_ENGINES` | `bing,mojeek,presearch` | Which engines general queries are sent to. See **What self-hosted search does and does not mean** below. |
| `SEARXNG_WIDEN_ENGINES` | `0` | Allow a failed search to retry with the instance's *default* engines. Off — see below. |
| `APP_BIND` | `127.0.0.1` | Docker Compose host bind address for the web UI. Use `0.0.0.0` only for intentional LAN/reverse-proxy access. |
| `APP_PORT` | `7000` | Docker Compose host port for the web UI. |
| `APP_DATA_DIR` | `./data` | Docker Compose host directory for application data volumes. |
| `APP_LOGS_DIR` | `./logs` | Docker Compose host directory for application logs. |
| `AUTH_ENABLED` | — | Ignored since 0.2.0: sign-in is always on. Named once in the log if set. |
| `LOCALHOST_BYPASS` | — | Ignored since 0.2.0: a request from this machine signs in like any other. Named once in the log if set. |
| `ALLOWED_ORIGINS` | `http://localhost,http://127.0.0.1` | Comma-separated exact permitted origins for cross-origin browser/API clients. |
| `SECURE_COOKIES` | derived from the request scheme | Marks session cookies `Secure` on HTTPS requests. Set true to force it on, false to force it off. |
| `DATABASE_URL` | `sqlite:///./data/app.db` | Database connection string |
| `CHROMADB_HOST` | `localhost` | ChromaDB host for vector memory. Docker overrides this to `chromadb`. |
| `CHROMADB_PORT` | `8100` | ChromaDB port for manual host runs. Docker overrides this to `8000`. |
| `EMBEDDING_URL` | -- | OpenAI-compatible embeddings endpoint |
| `PANTHEON_CHAT_UPLOAD_MAX_BYTES` | `10485760` | Chat/agent attachment cap in bytes. Raise for larger local PDFs or text documents. |
| `PANTHEON_GALLERY_UPLOAD_MAX_BYTES` | `104857600` | Gallery image upload cap in bytes (100 MB). |
| `PANTHEON_GALLERY_TRANSFORM_UPLOAD_MAX_BYTES` | `26214400` | Gallery transform input cap in bytes (25 MB). |
| `PANTHEON_MEMORY_IMPORT_MAX_BYTES` | `10485760` | Memory import file cap in bytes (10 MB). |
| `PANTHEON_PERSONAL_UPLOAD_MAX_BYTES` | `26214400` | Personal document upload cap in bytes (25 MB). |
| `PANTHEON_EMAIL_COMPOSE_UPLOAD_MAX_BYTES` | `26214400` | Email compose attachment cap in bytes (25 MB). |
| `PANTHEON_STT_MAX_AUDIO_BYTES` | `26214400` | Speech-to-text audio cap in bytes (25 MB). |
| `PANTHEON_ICS_MAX_BYTES` | `10485760` | Calendar `.ics` import cap in bytes (10 MB). |
| `PANTHEON_FONT_UPLOAD_MAX_BYTES` | `26214400` | Custom font upload cap in bytes (25 MB), for the theme panel's **Add a font**. |
| `PANTHEON_SOURCE_URL` | `https://github.com/ImPanick/pantheon` | Where the **Source** link on every page points. **A modified copy must point it at its own source** — see below. |

All upload-limit vars are validated (must be a positive integer) and optional; an invalid value fails fast at startup.

### The Source link — and what a modified copy owes its users

Every page Pantheon serves, the login page included, has a small **Source** link in its
bottom-right corner. It is the offer AGPL-3.0 §13 asks for: anyone who uses a modified
version of this program over a network must be able to get its source. Out of the box it
points at `https://github.com/ImPanick/pantheon`, which is the source an unmodified install
is running.

**If you change Pantheon's code and let anyone but yourself use it, point the link at your
own published source** — your fork, with your changes in it:

```bash
# .env
PANTHEON_SOURCE_URL=https://github.com/your-name/your-fork
```

The stored `source_url` setting (`POST /api/auth/settings` as an admin, or `data/settings.json`)
wins over the variable, and the variable over the default. Only `http://` and `https://`
addresses are accepted — anything else is refused on save and draws no link. Nothing is
fetched from that address: it is a link a person clicks, so it makes no request until they do.
The setting is checked on every page load, so a change needs no restart.

### Built-in MCP servers (optional setup)

Pantheon auto-registers a few built-in MCP servers at startup. The npx-based ones (currently the browser server, `@playwright/mcp`) only start when their npm package is already in the local npx cache. If a package isn't cached, that server is skipped with a startup log message explaining what to do, so a fresh install does not block on a multi-minute npm download or hang if Playwright system deps are missing.

To enable the browser MCP (page navigation, screenshots, vision), run once:

```bash
npx -y @playwright/mcp@latest --version
```

That installs `@playwright/mcp` plus Playwright (~300MB total). Restart Pantheon and the server will register at startup.


### Parallel networks — declaring segments and scoping a run to one

Pantheon ships declaring **nothing**, and with nothing declared it behaves
exactly as it always has: one flat set of hosts, no scoping, no change.

Declare segments in the `networks` setting when you have more than one and they
are not equally trusted — a printer VLAN, a lab subnet behind a jump host, a
second tailnet, the production network:

```json
[
  {"name": "lab",  "cidrs": ["10.9.0.0/24"],  "hosts": ["lab-gpu.lan"],
   "trust": "trusted", "notes": "GPU box + bench machines"},
  {"name": "guest", "cidrs": ["192.168.9.0/24"], "trust": "untrusted"}
]
```

**Trust is two levels.** `trusted`: the agent's own connections — a page fetch,
a `network reach` check — may go there. `untrusted`: the network is listed, so
the agent knows it exists, but Pantheon opens no connection there on its behalf.
(An older third level, `limited`, never behaved differently from `trusted`; a
saved one reads as `trusted` — the settings form shows it that way and saves it
as `trusted` — and writing `limited` through the API is refused with a sentence.) Like scoping, this governs Pantheon's own connections, not a shell
command — see below.

**`cidrs` classify; `hosts` are scanned.** A `/16` is 65,536 addresses, and
expanding a declaration into a sweep is how "discover my networks" becomes a
port scan your own IDS reports. Model discovery probes the hosts you list and
uses the CIDRs only to say which segment something belongs to.

**A bare hostname matches only by exact listing.** Resolving it would make
membership depend on whichever network answered the lookup, which is precisely
the ambiguity this exists to remove.

**Order decides an overlap.** First match wins, so put narrow segments before
broad ones. That is stated rather than sorted for you — "most specific wins"
quietly reorders what you wrote, and the surprise arrives later.

**Scoping a run.** A task's *Networks* (in the task form) holds its runs to the
networks picked (`B1475`). Inside a scope, what the agent reaches — a page
fetch, an integration, a `network reach` check, discovery — is refused any host
outside them before a socket opens. **A host in no declared network is refused
too:** if you named two segments and asked for one, you did not mean "and also
anything I forgot to describe". Pick *internet* as well to allow everything no
network claims. Pantheon's own calls for the run — its model, its workstation —
are refused only a host in *another* declared network, so a run scoped to the
lab keeps its own model and shell, and does not use a model in production.

**Each person's own networks** (`B1475`). With *Each person may declare their
own networks* on (Settings → Networks; off by default), Settings → My networks
lets each person declare networks of their own, in the same shape, and link a
login from their own vault to one. Theirs are read only in their own runs —
beside yours, after them, so a name of yours wins — and nobody else's runs see
them; the agent's `network list` names a linked login to an agent allowed to
use it, which signs in with it by name and never sees it. They grant no reach:
whether an agent may reach the LAN at all is still *Agents may reach the local
network* and the person's workstation privilege. You see every person's
networks under the switch, and of a linked login only that one is linked.

**What this is for, and what it is not.** Scoping is how you *direct* the agent:
work on the lab, and the lab is what gets discovered, offered and acted on. It
prevents the mistakes — a model list that mixes the lab GPU with the production
one, a sweep that wanders onto the printer VLAN, an agent that helpfully fixes
the wrong box — and it prevents them completely.

It is not a sandbox. A shell tool running `curl 10.20.7.3` reaches that address,
because the process has a route to it and no Python function can remove a route.
That is stated so you can plan around it, not as an apology: Pantheon is an
orchestration harness on machines you own, and traffic between them is normal.
If you do want a hard boundary — most likely because several people share one
install — that is a network namespace or a firewall rule at the OS level, and it
belongs outside the app.

---

### Turning a feature off actually turns it off

Settings → Features has eight switches. Each one now applies in three places:
the button disappears, the routes behind it refuse with a `403`, and — the part
that matters — **the agent loses the tool**. A model cannot call Deep Research or
the image tools for a feature you have switched off, whether or not it knows the
URL.

Before this, only the button disappeared. An admin who turned off Deep Research
got a success response, the toggle stayed off, and the feature answered every
request; three of the eight flags (`web_fetch`, `memory`, `rag`) did nothing
anywhere at all.

Two behaviours worth knowing:

- **A disabled feature answers `403`, not `404`.** It exists and your
  administrator switched it off; the message says so, and says who can turn it
  back on. Pretending it was never built would be a lie you could disprove by
  asking a colleague.
- **If the flags file cannot be read, everything stays ON.** A corrupt
  `data/features.json` must not silently take half the product away — and that
  failure would look exactly like somebody having disabled everything on
  purpose.

`sensitive_filter` is the one switch that gates no capability: it redacts what is
displayed and removes nothing the agent can do.

Your own Appearance preferences no longer overrule an administrator's switch. A
"show in sidebar" toggle brings back things you chose to hide, not things
somebody else turned off.

---

### Email the agent wrote is held until you say so

When Pantheon composes an email on your behalf it does **not** send it. The
message is staged and a panel appears above the composer showing every draft
waiting on you, with the recipients — including any `Bcc` — the full body, and
how long it has been waiting.

**If you have been running Pantheon or Odysseus for a while, expect a backlog on
first launch.** This confirmation behaviour has been the default since before
this fork, and until now there was nowhere to see the drafts it produced: the
mail was staged, the agent told you it was awaiting your approval, and no such
screen existed. Everything the agent has ever composed is still there and will
appear the first time you open the app after this update. Nothing was sent, and
nothing was lost.

- **Approve & send** delivers that one message now.
- **Discard** marks it cancelled. It is not deleted — the row stays in
  `data/scheduled_emails.db` if you ever want it back.
- **Discard all** is offered when there is more than one, and asks first.

There is deliberately no *Approve all*. A single button that sends hundreds of
year-old, model-composed emails to real people is the exact hole this
confirmation step exists to close.

To turn the confirmation off entirely and have the agent send immediately, set
`agent_email_confirm` to false in Settings. Drain the backlog first — turning it
off stops new drafts accumulating but does not send the ones already staged.

---

### Your own machines are never throttled

Pantheon paces the calls it makes out, so a provider does not see a burst where a
steady rate would do. That pacing does **not** apply to your own machines: a
model server on `localhost`, a box on your LAN, anything on a `.lan` or `.local`
name, a private-range address, or a tailnet peer is called as fast as the work
needs.

The reason is that pacing exists to stay under somebody else's abuse detection.
Your own hardware runs none, so a floor between requests there buys nothing and
costs real time — indexing five thousand documents would have spent over two
minutes asleep. If your own server *does* answer `429`, that is a real signal
from a real server and Pantheon backs off exactly as it would for anyone else.

If you deliberately want a LAN host paced — an old machine that falls over under
load, say — give it an explicit policy and that wins over the local shortcut.

### Behind an outbound proxy: exempt IPv6 destinations

Pantheon's HTTP client reads `HTTPS_PROXY`/`HTTP_PROXY` and `NO_PROXY` from the
environment. One limitation, measured 2026-10-26 with the pinned httpx 0.28.1 and
httpcore 1.0.9: a request to an **IPv6 address** through an HTTP proxy is sent as
`CONNECT fd00::5:7040 HTTP/1.1` — without the brackets RFC 9110 asks for
(`[fd00::5]:7040`). A strict proxy refuses it; a lenient one may split the address
at the wrong colon. So list an IPv6 model server or workstation in `NO_PROXY` by
its single address (`fd00::5` — every client honours that; a range such as
`fd00::/8` is honoured only by the clients Pantheon builds itself), or reach it by a
hostname. IPv4 addresses and names are unaffected. This is httpcore's to fix;
`tests/test_an_ipv6_connect_through_a_proxy_is_said.py` records the line it sends
and fails once it is bracketed, so this paragraph goes when it does.

---

### Nothing recurring fires on an exact boundary

Every background job in Pantheon — the email pollers, the nightly skill audit,
the scheduled housekeeping tasks, the browser's unread badge — runs a few percent
late, on purpose, by a random amount that is re-rolled each time.

**This is not about your install.** Inside one Pantheon the outbound limiter
already paces whatever these jobs send. The problem is that every Pantheon on
earth reaches the top of the hour at the same instant, so a provider you share
with everybody else — a mail host, a model API — sees one spike per hour instead
of a flat rate, and spikes are what abuse detection scores on. The sharper case
is an outage: a provider goes down, every client fails together, and without
jitter every client comes back at the same synchronised moment.

Your schedules still mean what they say. A job asked to run hourly runs hourly;
it just does not run at `:00:00`. Nothing ever fires *early* — that would make a
cron-driven task run twice in one period. The spread is capped at five minutes,
so a daily job stays daily rather than wandering.

Two things deliberately keep their exact timing:

- **A manual "Run now".** You are watching; a spread-out start reads as a button
  that did not work.
- **The scheduler's own tick.** It wakes near the next due-time boundary on
  purpose, so a `* * * * *` task is not up to a minute late. The jitter lives on
  the individual task instead.

`python3 .pantheon/check-jitter.py` is in CI and fails the build on a recurring
job with a fixed interval. It exists because the original audit found that not a
single recurring job in the product had jitter — nobody ever chose an exact sixty
seconds, it is just what you write.

---

### Outbound cooldowns survive a restart

When a provider tells Pantheon to stop — a `429`, a GitHub secondary-rate-limit
`403`, a mail server rejecting a login — the limiter holds that host or account in
a cooldown that escalates if the answer keeps coming back. Since `P15-09` those
cooldowns are written to `data/outbound_state.json` and restored on start.

**Why that is worth a section.** Before, every cooldown lived in memory. Restart
while GitHub had you in a forty-minute penalty and Pantheon started asking again
immediately — and a crash-loop plus a rate limit is precisely the pair that turns
a soft ban into a permanent one. The same applied to per-mailbox IMAP penalties,
where repeated failing logins are what providers lock accounts for.

**Deadlines are stored as wall-clock time, not as the process's own clock.** The
in-memory value is a monotonic reading, whose origin resets at boot; persisting
that number would restore a meaningless deadline after exactly the reboot a
crash-loop causes, while appearing to work perfectly on a machine that only
restarted the app.

The file holds nothing but a key, a deadline, a failure count and the provider's
own message. Pacing intervals and request counters stay in memory, because they
are re-earned in one request and because a counter that says *this process*
should not quietly start meaning something else.

**To clear a cooldown**: stop Pantheon, delete `data/outbound_state.json`, start
it. A penalty that expired while the process was down is dropped on load rather
than restored, so the file empties itself; a corrupt or unreadable one is ignored
and the limiter starts clean rather than refusing to make outbound calls. A
restored deadline is capped at 24 hours as a bound on what a moved system clock
can do — the in-process limiter still honours a longer `Retry-After` while it is
running.

`pantheon_outbound_cooldown_seconds{host}` on the metrics endpoint is how you see
this from outside, and it is usually the answer to "why does this feature look
broken when nothing is broken".

---

### Metrics — pointing Prometheus and Grafana at Pantheon

Off by default. Turn it on with `PANTHEON_METRICS_ENABLED=1` (or the setting),
and `GET /metrics` serves the Prometheus text exposition format.

**Nothing is ever sent anywhere.** A scrape is *your* Prometheus asking Pantheon
a question — there is no collector address in this codebase and no place to put
one, and CI fails the build if one appears. That is `Law 16` clause 4 satisfied
by shape rather than by promise.

**Authenticate the scrape.** Create an API token with the `metrics:read` scope
(Settings → API tokens, profile *metrics*), then:

```yaml
scrape_configs:
  - job_name: pantheon
    authorization:
      credentials: pan_your_token_here
    static_configs:
      - targets: ['pantheon.lan:7000']
```

An admin browser session also works, so you can just open the URL and look.
`metrics:read` grants the aggregate scrape body and nothing else — no message
content, no settings, no per-session detail.

**Everything is a gauge, deliberately.** A Prometheus counter must be monotonic,
and `events_retention_days` prunes at 90 days — so a `_total` sourced from that
table would *decline gradually* as old rows age out, which Prometheus reads as
neither a counter reset nor a real rate. `rate()` over it would be wrong in a way
nobody notices on a dashboard. The windowed numbers carry their window in the
name instead (`pantheon_llm_rounds_1h`), and mean what they say.

| Metric | What it tells you |
|---|---|
| `pantheon_llm_rounds_1h{model,outcome}` | Throughput, and how much of it failed |
| `pantheon_llm_tokens_1h{model,direction}` | What each model is actually costing you |
| `pantheon_turn_duration_ms_1h{stat}` | Turn latency — mean, max, sample count |
| `pantheon_tool_calls_1h{tool,outcome}` | `outcome="error"` is a tool that *returned* a failure; `"exception"` is one that raised |
| `pantheon_retrieval_1h{store,outcome}` | `"unavailable"` is the store being down; `"empty"` is a genuine miss |
| `pantheon_approvals_1h{outcome}` | `"expired"` is a question nobody answered |
| `pantheon_self_check{check}` | 0=ok 1=attention 2=unknown 3=stuck. Alert on `> 0` |
| `pantheon_self_check_age_seconds` | How stale the row above is. The self-checks probe real subsystems, so they are cached for 60s rather than re-run on every scrape |
| `pantheon_outbound_cooldown_seconds{host}` | Why a feature looks broken when nothing is broken |
| `pantheon_queue_depth{queue}` | `agent_mail` is the staged-drafts queue that once sat invisible for a year |
| `pantheon_events_rows` | Table size, bounded by your retention setting |
| `pantheon_scrape_collector_failed{collector}` | A collector that raised. The scrape still returns everything else |

**`pantheon_turn_duration_ms` measures the turn, not the model.** It runs from
the chat request arriving to the totals being written, so it includes tool calls
and retries. That is usually the number you want; it is named this way so you are
never guessing which one it is.

**The self-checks are cached for 60 seconds, and that is a correctness
measure rather than a speed one.** One of them asks the embedding server whether
it is answering — a real HTTP call. Re-running it on a 15-second scrape would
send 240 requests an hour to your embedding server as a side effect of being
monitored. `pantheon_self_check_age_seconds` tells you how old the reading is,
because a cached number that does not say it is cached gets read as live.

**Liveness probing is not on this endpoint.** Checking whether every configured
provider answers means real network calls to other people's machines; at a
15-second scrape interval that is thousands of requests an hour. It stays on the
diagnostics panel, where a person asks for it.

---

### Metrics, pushed — when your collector cannot reach in

The section above is *pull*: your Prometheus asks, Pantheon answers. That covers
most installs. It does not cover a Pantheon behind NAT, or on one of the
[parallel networks](#parallel-networks--declaring-segments-and-scoping-a-run-to-one) your collector has no route into. For
those, Pantheon can push the same readings to an OpenTelemetry collector you run.

**One address, and it ships empty.**

```
PANTHEON_OTLP_ENDPOINT=http://otel.lan:4318
```

Either the base URL or the full `http://otel.lan:4318/v1/metrics`; the signal
path is appended only when it is not already there, because both spellings are
common and guessing wrong costs a `404` you would have no way to see.

**The address is the switch.** There is no separate on/off setting. No address,
no push — and the shipped value is empty, enforced by CI rather than intended:
`.pantheon/check-destinations.py` fails the build if a destination-shaped default
is non-empty. This is the first legitimate outbound address in the product, so it
is also the first place a well-meant default could hide. `Law 16` clause 4 says
telemetry is fine and *phoning home* is not; the difference is entirely who owns
the address, and this way the answer can only be you.

| Setting | Default | What it does |
|---|---|---|
| `otlp_endpoint` | *(empty)* | Your collector. Also `PANTHEON_OTLP_ENDPOINT` |
| `otlp_interval_seconds` | `60` | Floored at 10, plus up to 10% jitter |
| `otlp_headers` | `{}` | Whatever your collector wants for auth. Never logged |
| `otlp_resource_attributes` | `{}` | Merged over `service.name` and `service.version` — put `service.instance.id` here if several Pantheons share a collector |

**It is the same numbers, under the same names.** The push does not have its own
collectors; it serialises what the scrape would have served. Two exporters with
two sets of collectors is how a dashboard ends up disagreeing with itself, and
renaming `pantheon_scrape_duration_seconds` for the push path would silently
halve the series for anyone running both.

**OTLP/HTTP with a JSON body, over `httpx` — no OpenTelemetry SDK.** The payload
is a handful of nested keys. The SDK brings a dependency tree, its own background
processor, and a constructor whose default endpoint is a real address, which is
three things to audit in exchange for serialising a dict.

**Watch the exporter on the scrape endpoint, not in the pushed data.** When the
push is failing, the pushed copy of its health metric is exactly the one that
does not arrive.

| Metric | What it tells you |
|---|---|
| `pantheon_otlp_configured` | `0` is the shipped state, not a fault |
| `pantheon_otlp_consecutive_failures` | Alert on this. Resets to 0 on any success |
| `pantheon_otlp_points_last_push` | Size of the last accepted batch |
| `pantheon_otlp_points_rejected` | Points your collector answered `200` for and then discarded — OTLP reports a partly-rejected batch as a success with a `partialSuccess` body, so a status check alone would call that delivered |
| `pantheon_otlp_last_success_age_seconds` | **Absent** until a push succeeds. Not `0`, which would read as *just now* |

**The push goes through the same outbound limiter as everything else**, so it
inherits `P16-16` network scoping and backs off when your collector rate-limits
it. A metrics push on a timer is the one request in the product guaranteed to
keep firing whether or not anybody is watching, which is exactly the shape the
limiter exists for.

---

### What self-hosted search does and does not mean

Worth being plain about, because the phrase promises more than it delivers.

**SearXNG is a metasearch engine.** Self-hosting it means *the aggregator* runs
on your hardware — it does not mean the searching happens there. SearXNG has no
index of its own; it forwards your query to other people's engines and merges
what comes back. What you gain is real: no account, no profile, no cookies, no
search history held by a company, and your browser never talks to those engines
directly. What you do not gain is queries that stay on your network. They
cannot; there would be nothing to search.

**Which engines see your queries is a choice, and it is yours.**
`SEARXNG_GENERAL_ENGINES` pins the list. It ships as `bing,mojeek,presearch`
because on a fresh instance the usual defaults are rate-limited or
CAPTCHA-blocked and return nothing — not because those three are more private.
Set it to whatever you are comfortable with; Mojeek and Presearch have their
own indexes, and an instance pinned to those two queries no large ad network at
all, at the cost of thinner results.

**A failed search will not quietly widen that list.** Until 2026-09-01 it did:
when a pinned search returned nothing, the third retry dropped the pin, and
SearXNG's `use_default_settings: true` handed the query to its full default set
— Google, DuckDuckGo, Brave, Startpage. Engines you had excluded, on the third
attempt, logged at INFO as a detail. That is off now (`P16-10`). Set
`SEARXNG_WIDEN_ENGINES=1` if you would rather have the results; the log says
which engines were tried either way.

**If you want the guarantee at the source rather than from the client**, restrict
the engine set in `config/searxng/settings.yml` with
`use_default_settings: {engines: {keep_only: [...]}}`. Pantheon does not ship
that, deliberately: the news category does not pin engines, so a `keep_only`
list tuned for general search silently breaks news queries, and a default that
breaks a working feature is a worse default than the one it replaces. It is the
right change to make by hand once you know which engines your instance actually
answers on.


## Architecture
```
app.py                   # FastAPI entry point
core/      auth, database, middleware, constants
src/       llm_core, agent_loop, agent_tools, chat_processor, search/
routes/    chat, session, document, memory, model … endpoints
services/  docs, memory, search, hwfit (Forge) …
static/    index.html + app.js + style.css + js/ (modular front-end)
docs/      landing page (index.html) + preview clips
```

## Data
All user data lives in `data/` (gitignored): `app.db` (sessions, messages, documents),
`memory.json`, `presets.json`, `uploads/`, `personal_docs/`, `chroma/`, `settings.json`.

To back up or restore everything in `data/`, see the
[Backup & Restore guide](backup-restore.md).
