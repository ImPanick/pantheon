# Pantheon Setup Guide

This page keeps the detailed install, deployment, troubleshooting, and configuration notes out of the front README.

## Quick Start

> **Branch note:** `main` is the only branch — cloning gives you it, and there is nothing to switch to. *(Corrected 2026-08-30: this line described upstream Odysseus's two-branch model and told people to check out a branch this repository does not have.)*

Defaults work out of the box: clone, run, then configure models/search/email
inside **Settings**. Only edit `.env` for deployment-level overrides like
`APP_BIND`, `APP_PORT`, `AUTH_ENABLED`, `DATABASE_URL`, or a pre-seeded admin password.

On first setup, Pantheon creates an admin account (`admin` unless
`PANTHEON_ADMIN_USER` is set) and prints a temporary password in the terminal.
For Docker installs, the same line is in `docker compose logs pantheon`.
Use that for the first login, then change it in **Settings**.

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

Open `http://localhost:7000` when the containers are healthy. Docker Compose
binds the web UI to `127.0.0.1` by default. If the port is taken, set
`APP_PORT=7001` in `.env` and recreate the container. Set `APP_BIND=0.0.0.0`
only when you intentionally want LAN/reverse-proxy access.

> **On Apple Silicon (M-series) Macs:** Docker can't reach the Metal GPU, so
> Cookbook serves local models on CPU only. For GPU-accelerated model serving,
> run natively instead — see [Apple Silicon](#apple-silicon) below.

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
Requirements: Python 3.11+. Cookbook also needs `tmux` for background model
downloads and serves. The app itself is lightweight; local model serving is the
heavy part and depends on the model, runtime, GPU, and VRAM, so small hosts can
connect to API or remote model servers instead. Use `--host 0.0.0.0` only when you intentionally want LAN/reverse-proxy access.

### Apple Silicon
Docker on macOS cannot use the Metal GPU. For GPU-accelerated Cookbook on an
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

Keep `AUTH_ENABLED=true` (the default) before binding outside loopback. Do not
expose this port directly to the public internet. To build a clickable app wrapper:

```bash
./build-macos-app.sh
```

<details>
<summary>Cookbook, GPU, Ollama, and troubleshooting notes</summary>

**Docker bundled services.** Compose starts Pantheon, ChromaDB, SearXNG, and
ntfy. Pantheon and the bundled service ports bind to `127.0.0.1` by default, so
they are reachable from the host but not exposed to your LAN/public internet
unless you opt in.

**Cookbook storage in Docker.** Downloads live in `./data/huggingface`
(`~/.cache/huggingface` in the container). Cookbook-installed Python CLIs and
serve engines live in `./data/local` (`~/.local` in the container), so they
survive container recreation.

**Remote servers.** In **Cookbook -> Settings -> Servers**, generate the
Pantheon SSH key and add the public key to the remote server's
`~/.ssh/authorized_keys`. From the host you can also run:

```bash
ssh-copy-id -i data/ssh/id_ed25519.pub user@server
```

**Host Docker access (explicit opt-in).** Default Docker Compose intentionally
does not mount `/var/run/docker.sock`. You can still connect Pantheon to
existing Ollama, vLLM, and other OpenAI-compatible endpoints without Docker
socket access.

Cookbook/local Docker-daemon management requires the opt-in overlay below. Raw
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

**Docker GPU overlays.** CPU-only users can skip this section. Cookbook can
only detect GPUs that Docker exposes to the container — if the host runtime or
device passthrough is not configured, Cookbook sees the iGPU, another card, or
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
> the CUDA Toolkit at runtime. If Cookbook logs show `Unable to find cudart
> library`, `Could NOT find CUDAToolkit`, `CUDA Toolkit not found`, or
> tensors/layers assigned to CPU, that is a Cookbook/llama.cpp build issue —
> not a Docker passthrough failure. Reinstall the serve engine via
> **Cookbook → Dependencies** to get a CUDA-enabled build.
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
container. Cookbook **Serve** is a separate workflow for serving downloaded
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
outside loopback only for a trusted LAN/VPN such as Tailscale: keep
`AUTH_ENABLED=true` and do not expose the port directly to the public internet.

**Requirements:** Python 3.11+. The core app (chat, agent, memory, documents,
email, calendar, deep research) runs fully native. For full **Cookbook** background
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

### Common self-host traps (30-second fixes)
A grab-bag of small gotchas that otherwise turn into long debugging sessions.

- **`AUTH_ENABLED=false` is ignored / you're still forced to log in (Windows).** If you edited `.env` in Notepad it may have saved a UTF-8 **BOM**, turning the first key into `﻿AUTH_ENABLED` so it is never matched. Pantheon loads `.env` with `encoding="utf-8-sig"` to tolerate a leading BOM, but the safe fix is to re-save `.env` as **UTF-8 without BOM** (VS Code: *Save with Encoding → UTF-8*).
- **macOS: the app isn't at `http://localhost:7000`.** macOS AirPlay Receiver usually holds port `7000`, so the macOS start script serves on **`7860`** instead — open `http://localhost:7860`. To use `7000`, free it (System Settings → General → AirDrop & Handoff → turn off *AirPlay Receiver*) and set `APP_PORT=7000`.
- **Copy buttons do nothing over a plain-HTTP Tailscale/LAN URL.** Browsers only expose the clipboard API (`navigator.clipboard`) on **secure origins** — HTTPS, or `localhost`. Over `http://100.x.y.z:7860` it is blocked. Serve over HTTPS (see *HTTPS + LAN/Tailscale exposure* above); `localhost` is exempt, so copy still works on the host itself.
- **Self-hosted ntfy reminders don't reach your phone.** Two things: (1) the bundled ntfy binds to loopback by default — to reach it from your phone set `NTFY_BIND` to your host/Tailscale IP and `NTFY_BASE_URL` to the same server URL in `.env`, then recreate the ntfy container (see the `NTFY_*` block in `.env.example`); (2) in the ntfy **Android** app, subscribe to the topic with **Instant delivery** enabled — non-`ntfy.sh` servers don't get instant push otherwise.
- **Local mail (Dovecot) login fails: "Plaintext authentication disallowed on non-encrypted connections."** Your IMAP/SMTP server is refusing cleartext auth over an unencrypted link. Prefer enabling TLS on the mail server; on a trusted LAN only, you can allow cleartext (Dovecot: `disable_plaintext_auth = no`).
- **Calendar/contacts (Radicale) won't sync.** Point Pantheon at the **full collection URL** with its trailing slash — e.g. `http://host:5232/<user>/<collection-id>/` — not just the server root. Radicale shows this address for each calendar/address book in its web UI.

### Optional Dependencies
`requirements-optional.txt` contains packages that unlock extra features. It is not installed by default.

| Package | Feature unlocked |
|---------|-----------------|
| `faster-whisper` | Local speech-to-text (microphone -> text) via the "local" STT provider. |
| `kokoro`, `soundfile` | Local Kokoro-82M text-to-speech on a CUDA GPU. The pinned Kokoro release supports Pantheon installs on Python 3.11-3.12; these packages are intentionally skipped on Python 3.13+ (including the Python 3.14 container image). |
| `ddgs` | DuckDuckGo as a search provider option. |
| `PyMuPDF` | PDF page rendering in the side viewer panel and form-filling. (Note: AGPL-3.0) |
| `markitdown` | Office/EPUB document text extraction (converts .docx/.xlsx/.pptx/.xls/.epub to Markdown). |

Install the optional set only when you need these features:

```bash
pip install -r requirements-optional.txt
```

The default Docker image currently uses Python 3.14, while Kokoro 0.9.4 declares Python `>=3.10,<3.13`. Pantheon itself continues to support Python 3.11+, but this pinned optional local-TTS feature requires a native Python 3.11 or 3.12 environment. Kokoro declares `torch`, but the local provider only activates when that torch build has CUDA and a GPU is visible; install the CUDA build appropriate for your host. Browser and configured endpoint TTS remain available on Python 3.13+ and in the container image.

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
Pantheon email accounts currently use IMAP/SMTP username-password auth. Outlook
and Microsoft 365 generally require OAuth instead, so normal Microsoft mailbox
passwords will fail. See [docs/email-outlook.md](docs/email-outlook.md) for the
current limitation and the planned integration direction.

## Security Notes
Pantheon is a self-hosted workspace with powerful local tools: shell access, file uploads, model downloads, web research, email/calendar integrations, and API tokens. Treat it like an admin console.

- Keep `AUTH_ENABLED=true` for any network-accessible deployment.
- Keep `LOCALHOST_BYPASS=false` outside local development.
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

Cloudflare Access, Tailscale, Caddy, nginx, and Traefik can all fit this pattern; none are required by Pantheon. If your access layer reaches Pantheon on the same host, proxy to `http://127.0.0.1:7000` and keep `AUTH_ENABLED=true` and `LOCALHOST_BYPASS=false`. Any proxy that forwards `X-Forwarded-Proto: https` gets `Secure` session cookies without configuration, so `SECURE_COOKIES` only needs setting when you want to override that — force it on for a proxy that forwards no scheme at all, or off while you still serve plain HTTP.
`ALLOWED_ORIGINS` lists exact permitted origins for cross-origin browser/API clients; ordinary same-origin reverse-proxy access usually does not need a special CORS entry.

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
- Pantheon sends `Strict-Transport-Security` once it sees `X-Forwarded-Proto:
  https`. HSTS applies to the whole hostname and ignores the port, so any other
  plain-HTTP service on that same hostname becomes unreachable in browsers that
  have visited Pantheon. Give Pantheon its own hostname, or strip the header at
  the proxy (`header_down -Strict-Transport-Security` in Caddy).

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
| `8080` | SearXNG |
| `8091` | ntfy |
| `8100` | ChromaDB host port for manual/compose access |
| `11434` | Ollama |
| `8000-8020` | Common local model/provider APIs |

## Configuration
Most setup is done inside the app with `/setup` or **Settings**. Use `.env`
for deployment-level defaults and secrets you want present before first boot.
Key settings:

| Variable | Default | Description |
|---|---|---|
| `LLM_HOST` | `localhost` | Your LLM server (e.g. `llm-host.local:8000`) |
| `LLM_HOSTS` | -- | Comma-separated list for model discovery |
| `OPENAI_API_KEY` | -- | Optional OpenAI key. Prefer adding providers in the app unless pre-seeding. |
| `SEARXNG_INSTANCE` | `http://localhost:8080` | SearXNG URL. Docker overrides this to `http://searxng:8080`. |
| `SEARXNG_SECRET` | generated on first Docker boot | Optional SearXNG cookie/CSRF secret. Leave blank unless you need to pin it. |
| `SEARXNG_GENERAL_ENGINES` | `bing,mojeek,presearch` | Which engines general queries are sent to. See **What self-hosted search does and does not mean** below. |
| `SEARXNG_WIDEN_ENGINES` | `0` | Allow a failed search to retry with the instance's *default* engines. Off — see below. |
| `APP_BIND` | `127.0.0.1` | Docker Compose host bind address for the web UI. Use `0.0.0.0` only for intentional LAN/reverse-proxy access. |
| `APP_PORT` | `7000` | Docker Compose host port for the web UI. |
| `APP_DATA_DIR` | `./data` | Docker Compose host directory for application data volumes. |
| `APP_LOGS_DIR` | `./logs` | Docker Compose host directory for application logs. |
| `AUTH_ENABLED` | `true` | Enable/disable login |
| `LOCALHOST_BYPASS` | `false` | Development-only auth bypass for loopback requests. Keep false for shared/network deployments. |
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

All upload-limit vars are validated (must be a positive integer) and optional; an invalid value fails fast at startup.

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
   "trust": "limited", "notes": "GPU box + bench machines"},
  {"name": "prod", "cidrs": ["10.20.0.0/16"], "hosts": ["prod-llm.internal"],
   "trust": "trusted"}
]
```

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

**Scoping a run.** Inside a scope, a host in another segment is refused before a
socket opens — on model endpoint selection, discovery, URL fetches and every
paced outbound call. **A host in no declared network is refused too:** if you
named two segments and asked for one, you did not mean "and also anything I
forgot to describe".

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
      credentials: ody_your_token_here
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
services/  docs, memory, search, hwfit (Cookbook) …
static/    index.html + app.js + style.css + js/ (modular front-end)
docs/      landing page (index.html) + preview clips
```

## Data
All user data lives in `data/` (gitignored): `app.db` (sessions, messages, documents),
`memory.json`, `presets.json`, `uploads/`, `personal_docs/`, `chroma/`, `settings.json`.

To back up or restore everything in `data/`, see the
[Backup & Restore guide](backup-restore.md).
