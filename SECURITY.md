# Security Policy

Pantheon is a self-hosted AI workspace with privileged local capabilities. Please do not run it as a public, unauthenticated service.

## Reporting a Vulnerability

**Report privately. Do not open an issue.**

Use **[GitHub private vulnerability reporting](https://github.com/ImPanick/pantheon/security/advisories/new)** — the repository's **Security** tab, then **Report a vulnerability**. That opens a draft advisory only the maintainer can read: it does not notify watchers, it does not appear in the issue list, and it is where a fix and a CVE would be coordinated from if one is warranted.

If that page 404s, private reporting has not been turned on for this repository yet. Then open a public issue containing **only** the sentence *"I have a security report — please enable private vulnerability reporting"*: no component, no version, no reproduction. You will be contacted there.

*Until 2026-09-16 this section said to report "by opening a minimal issue that does not disclose exploit details". That was written when the repository was private and it does not survive going public. This project ships shell execution, file read/write, mail send and read, and MCP process launch — for most bugs in that surface, naming the component **is** the exploit, and a reporter following that instruction would have published it. The advice is withdrawn.*

### What to include

The more of this you have, the faster it moves. Send what you have; do not wait until the list is complete.

- **The revision.** From the repository root: `git show -s --abbrev=12 --format='%h (%cs)' HEAD`.
- **Install method** — Docker, manual Python, Windows native, macOS app.
- **The configuration that matters.** At minimum `AUTH_ENABLED`, `LOCALHOST_BYPASS`, whether the instance is reachable beyond localhost, and what sits in front of it.
- **Reproduction steps**, and what an attacker gets at the end of them.
- **The starting privilege.** Anonymous, an authenticated non-admin, a chat-scoped API token, or an admin session — these are four different findings and [`THREAT_MODEL.md`](THREAT_MODEL.md) treats them differently.
- **Which boundary it crosses**, if you can name one from [`THREAT_MODEL.md`](THREAT_MODEL.md). If it crosses none, say so anyway; the threat model may be the thing that is wrong.

### What happens next

This is one maintainer working in the open. There is no security team, no paid triage rotation and no bug bounty, so the commitment here is deliberately small enough to keep:

| | |
|---|---|
| Acknowledgement | within **5 days** of the advisory being filed |
| First assessment — confirmed, not reproduced, or out of scope, with reasoning | within **14 days** |
| No reply by then | comment on the advisory thread. Do not escalate to a public issue |

Once a report is confirmed: the fix lands on `main`, the advisory is published with the fix rather than before it, and you are credited by the name or handle you ask for — or not credited, if you prefer. If a report is declined, you get the reasoning, and you are free to disclose publicly after that; there is no embargo you did not agree to.

### Out of scope

These are not vulnerabilities in this project, and saying so up front saves you the work:

- **What an authenticated admin can do by design.** Shell, Python execution, file read/write, mail, MCP and model serving are admin capabilities on purpose — [`THREAT_MODEL.md`](THREAT_MODEL.md) states that boundary and does not try to defend it. An admin session running a shell command is the product working.
- **A deployment this file told you not to build.** `AUTH_ENABLED=false` on a network-exposed instance, `LOCALHOST_BYPASS=true` behind a proxy, ChromaDB or Ollama published to the internet — see *Deployment Guidance* below.
- **The Known Gaps already listed in [`THREAT_MODEL.md`](THREAT_MODEL.md).** They are on the record. A *new* way to reach one of them, or a consequence worse than the one written down, is in scope and worth reporting.
- **Third-party dependency advisories**, which belong upstream — with one exception worth sending: if this repository's use of a dependency makes a flaw reachable when it otherwise would not be, that is ours. See *Dependencies* below.

## Supported Versions

**There are no tagged releases yet.** No `v1.0`, no release branches, no long-term-support line — and no release notes to subscribe to, so Watch → Custom → Releases will stay silent.

| Version | Supported |
|---|---|
| `main` (default branch) | Yes — the only supported version |
| Anything older than current `main` | No |
| Tagged releases | None exist yet |

If you self-host this, that means: track `main`, pull and redeploy to pick up a security fix, and pin to a commit rather than to a tag if you need a fixed target — the bug report form already asks for `git show -s --abbrev=12 --format='%h (%cs)' HEAD`, which is the only version identifier this project has. A fix does not get backported to the commit you happen to be sitting on; there is nowhere to backport it to. Watch the repository for pushes, or read [`CHANGELOG.md`](CHANGELOG.md), which has one `[Unreleased]` section and nothing else, for the same reason.

## Dependencies

Four automated things run without anyone starting them. [`docs/security-ci.md`](docs/security-ci.md) explains each one, what it blocks, and the one-time repository settings that make the blocking real:

- **Dependabot** (`.github/dependabot.yml`) opens grouped weekly pull requests for Python packages, npm packages, the Docker base image, and the pinned Action SHAs in every workflow.
- **Dependency review** compares the dependencies before and after a pull request and blocks the merge if the change introduces a package with a known moderate-or-worse advisory. This is the gate.
- **pip-audit** scans every pinned Python dependency against the advisory database, on pull requests and on pushes to `main`, and **blocks** — a finding with no entry in [`.pantheon/dependency-advisories.toml`](.pantheon/dependency-advisories.toml) fails the job, and so does an entry whose finding is no longer reported. What it reads is `requirements.txt`, `requirements-optional.txt`, `requirements-image.txt` **and** the three Real-ESRGAN wheel pins, which live in a shell variable in `docker/build-realesrgan-wheels.sh` and are read out of it by `.pantheon/audit-dependencies.py` rather than copied into a second list. That last part is deliberate: those three packages go into every image and appear in no requirements file, which is how the `basicsr` advisory below came to be visible only to someone who thought to run `pip-audit` inside a running container by hand.
- **Trivy** scans the built container image — everything installed into it, including anything a `pip install` at runtime dragged in that no requirements file names. Advisory, and findings land in the repository's Security tab.

### One accepted risk: `basicsr` 1.4.2 (CVE-2024-27763)

Stated here rather than left for you to find in a scan.

**What ships.** `docker/build-realesrgan-wheels.sh` builds patched wheels for `basicsr==1.4.2`, `gfpgan==1.3.8` and `facexlib==0.3.0`, and the `Dockerfile` installs them with `--no-deps`. So `basicsr` 1.4.2 is present in the default Docker image whether or not you ever use Real-ESRGAN. It is in no requirements file, which for a while meant no scanner in CI named it except Trivy — advisory, and reporting into a tab. That is fixed: `.pantheon/audit-dependencies.py` reads the pins out of `docker/build-realesrgan-wheels.sh` and audits them alongside the requirements files, so the blocking `pip-audit` job reports this advisory on every run, together with the reasoning below, which it prints from the register rather than making you open a file to find. Trivy reports it against the image as well.

**Why it cannot be fixed by upgrading.** `basicsr` 1.4.2 is the newest release and was published on 2022-08-30; upstream has released nothing since. The advisory (GHSA-86w8-vhw6-q9qq, CVE-2024-27763, PYSEC-2026-1215) records `1.4.2` as last-affected with no fixed version. `realesrgan` 0.3.0 — itself the newest release, from 2022-09-20 — declares `basicsr>=1.4.2`, so there is no version of that constraint that resolves to something unflagged. Removing the pin does not help; it resolves to the same wheel.

**What the bug actually is.** Command injection in `basicsr/utils/dist_util.py`, in the SLURM branch of distributed-training setup: it interpolates `$SLURM_NODELIST` into a `scontrol show hostname` shell command. Reaching it needs two things at once — `SLURM_NODELIST` set in the process environment, *and* a call into the distributed-training entry point, which inference never makes. Pantheon calls Real-ESRGAN for image upscaling only. The CVSS vector is `AV:L/AC:L/PR:L` — local, already-authenticated — and it is consistent with that: anyone who can set environment variables on the Pantheon process already has local code execution and does not need this.

**The decision.** Accepted, not mitigated, because there is nothing to upgrade to and vendoring a fork of a dormant 2022 package to patch a code path we never call would be a larger risk than the one it removes. Revisit if upstream releases again, if Real-ESRGAN gains a maintained replacement, or if anything in this tree ever calls `basicsr`'s distributed entry point — that last one changes the answer.

**And the acceptance expires.** The register entry carries a `review_by` date and `.pantheon/check-pins.py` fails once it is past, so nobody renews this by not looking at it. The same checker fails if `docker/build-realesrgan-wheels.sh` stops pinning `basicsr==1.4.2` — a suppression that has outlived the dependency it excuses is exactly as misleading as one that never had a reason — so a future bump of that pin is noticed by the gate rather than by someone remembering this paragraph exists.

## Deployment Guidance

- Keep `AUTH_ENABLED=true` for any network-accessible deployment.
- Keep `LOCALHOST_BYPASS=false` outside local development.
- Leave `SECURE_COOKIES` unset unless you need to override it: session cookies are marked `Secure` whenever the request arrives over HTTPS. Set `SECURE_COOKIES=true` to force it on (for a proxy Pantheon cannot see the scheme of), or `SECURE_COOKIES=false` to force it off while you still serve plain HTTP alongside HTTPS.
- Use HTTPS when exposing the app beyond localhost.
- Put the authenticated Pantheon web/API entrypoint behind a trusted reverse proxy or private access layer such as Cloudflare Access, Tailscale, or a VPN.
- Keep ChromaDB, SearXNG, ntfy, Ollama, vLLM, llama.cpp, databases, and raw model/provider APIs internal-only.
- Protect `.env`, `data/`, `logs/`, uploads, generated media, backups, auth/session files, database files, API keys, and model/provider tokens.
- Disable open signup unless you intentionally want new accounts.
- Keep demo/test users non-admin, and remove them entirely on serious deployments.
- Give admin accounts strong passwords and enable 2FA where possible.
- Leave high-risk agent tools restricted to admins: shell, Python, file read/write, email send/read, MCP, app API, task/skill/memory management, settings, tokens, and model serving.
- Rotate API keys, webhook secrets, and Pantheon API tokens if they appear in logs, screenshots, demos, or shared chats.
- Treat shell, model-serving, MCP, email, calendar, and vault features as privileged admin functionality.
- Common internal-only ports are Pantheon `7000`, SearXNG `8080`, ntfy `8091`, ChromaDB `8100`, Ollama `11434`, and local model/provider APIs such as `8000-8020`.

## Publishing A Fork

Before pushing a public fork, run:

```bash
git status --short
git check-ignore -v .env data/auth.json data/app.db logs/compound.log pantheon.db
git grep -n -I -E "(sk-[A-Za-z0-9_-]{20,}|xox[baprs]-|AIza[0-9A-Za-z_-]{20,}|Bearer [A-Za-z0-9._~+/-]{20,})" -- . ':!static/lib/**' ':!package-lock.json'
```

Only `.env.example`, docs, source, tests, and static assets should be committed. Never commit live `.env` values, `data/` contents, local databases, uploaded files, generated media, logs, backups, auth/session files, API keys, model/provider tokens, password hashes, or personal documents.
