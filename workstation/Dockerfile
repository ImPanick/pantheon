# SPDX-License-Identifier: AGPL-3.0-or-later
# The Pantheon workstation — `P20-01`, `D-2026-09-30-03`.
#
# An Ubuntu 24.04 userland (or Debian 13, Fedora 45 or Rocky Linux 9: `WORKSTATION_OS`, `B1747`) the agents work in: one Unix account and one X
# display per person, a desktop (XFCE themed to the cockpit, `D-2026-10-31-02`:
# a terminal, Firefox, a file manager), the tools a
# task usually needs, and `agentd` answering `workstation/protocol.py` on 7040.
# The build context is this directory and nothing else:
#
#     docker build -t pantheon-workstation workstation/
#
# It is started by `docker/workstation.yml`; nothing here reaches Pantheon's
# data, and Pantheon's image does not depend on this one.
#
# `B1677`. The base is a content address, not `ubuntu:24.04`: Canonical
# rebuilds that tag in place, so a rebuild could change the userland with
# nothing in the tree saying so. Ubuntu publishes no three-part tag; the dated
# one names the build for a reader, and the digest (Docker Hub's record of the
# multi-platform index, read 2026-10-29: the same index `24.04` and `noble`
# pointed at that day) is what the builder pulls. `vm.Dockerfile` builds from the
# same one; `.github/dependabot.yml`'s `/workstation` entry is what moves both.
#
# `B1747`. One Dockerfile, four systems: `WORKSTATION_OS` picks the base, and
# everything after it — `provision.sh`, the desktop, the daemon — is the same
# file for all of them (`Law 14`). BuildKit pulls and builds only the stage the
# chosen system needs. Ubuntu is the workstation every install has; the other
# three are opt-in compose profiles (`docker-compose.yml`). Each is pinned the
# way Ubuntu is: a tag for a reader, a digest for the builder (each read
# 2026-11-02 from Docker Hub's record of the multi-platform index).
#   debian  Debian 13 (trixie), Debian's own official image, a dated build.
#   fedora  Fedora 45, Fedora's official image (Fedora publishes no dated
#           tag, so the digest alone says which build).
#   rocky   Rocky Linux 9 (the RHEL 9 family), the Rocky project's own image,
#           a dated build.
# `B2214`, 2026-11-24: all four moved to the newest build Docker Hub listed that
# day (Ubuntu noble-20261110.1, Debian trixie-20261123, Fedora 45 — what
# `fedora:latest` pointed at — and Rocky 9.9.20261112.0), each digest the
# multi-platform index's. Rocky stays on 9: Rocky 10 is out (10.3), but
# KasmVNC, the live desktop, publishes no EL10 build (its `builder/` has
# `oracle_8` and `oracle_9` only, read at its newest tag v1.5.2 and on master),
# and `provision.sh` refuses a Rocky build whose desktop does not install. Rocky
# 10 also needs an x86-64-v3 CPU, which Rocky 9 does not.
ARG WORKSTATION_OS=ubuntu
FROM ubuntu:noble-20261110.1@sha256:562111b88caa79c71391c0c4d3c2114a7d5c35915c20561fd893cb1e07929e6b AS base-ubuntu
FROM debian:trixie-20261123@sha256:3cda3ca472ce45507a5109c6a3907093e24d9ae67d55954c9a07a45665dafba2 AS base-debian
FROM fedora:45@sha256:a7d72ba2745b100a3351087472e5ee7b2450af7cf331e7673007e3817612839c AS base-fedora
FROM rockylinux/rockylinux:9.9.20261112.0@sha256:bb5755f96bec05ff26165e779ec843d7167544be9e50770508f307019a6d05c4 AS base-rocky

FROM base-${WORKSTATION_OS}
ARG WORKSTATION_OS

ARG DEBIAN_FRONTEND=noninteractive
# Optional, and empty by default, so a plain build uses Ubuntu's own sources
# untouched. For a builder that cannot reach them directly — a local mirror, or
# a TLS-inspecting proxy that only tunnels HTTPS: `--build-arg
# APT_MIRROR=https://archive.ubuntu.com/ubuntu` plus the proxy's CA as the
# BuildKit secret `build-ca` (`--secret id=build-ca,src=ca.crt`). The secret is
# mounted for the one RUN that needs it and is not in any layer; it is
# world-readable inside that RUN because apt downloads as `_apt`, not root.
ARG APT_MIRROR=

# What a workstation has is one list in `provision.sh`, which the VM backend and
# `install.py` run too (`P20-07`, `Law 14`): Ubuntu's desktop, tools and
# Mozilla's Firefox — from Mozilla's repository, pinned so apt never picks
# Ubuntu's snap wrapper (snapd does not run in a container), signed by a key
# committed rather than fetched (`firefox/packages.mozilla.org.asc`, fingerprint
# 35BAA0B33E9EB396F59CA838C0BA5CE6DC6315A3, Mozilla's published value, checked
# 2026-09-30 with `gpg --show-keys`). `--image` also drops apt's lists and the
# base image's `ubuntu` user (uid 1000), which keeps 1000 free: it is Pantheon's
# default PGID, the group the pairing token is readable by
# (`docker/workstation.yml`). Only the script and the key are copied first, so
# editing anything else does not re-run apt.
COPY provision.sh /opt/pantheon-workstation/provision/provision.sh
COPY firefox/packages.mozilla.org.asc /opt/pantheon-workstation/provision/firefox/packages.mozilla.org.asc

RUN --mount=type=secret,id=build-ca,required=false,mode=0444 \
    sh /opt/pantheon-workstation/provision/provision.sh packages --image

# `Law 16` — nothing phones home. `firefox/policies.json` is the list: telemetry,
# studies, updates (app, add-ons, system add-ons, OpenH264 and Widevine, both
# Mozilla's and Google's updater), Pocket, the default-browser check, the
# Terms-of-Use and onboarding screens, captive-portal and connectivity checks,
# region lookup, sponsored tiles and suggestions, push, Safe Browsing,
# DNS-over-HTTPS and every prefetch. Remote Settings and Normandy are pinned to
# loopback instead of switched off: pointing their server anywhere else also
# stops Firefox loading the dumps its search configuration comes from.
# Measured 2026-09-30 on a fresh profile left idle for 120 s: without the file,
# 135 lookups of 15 outside hosts; with it, none.
# `provision.sh files` puts it at /etc/firefox/policies/policies.json, and the
# skeleton every home starts from and "Reset to clean" returns to in /etc/skel,
# and the desktop's window frames, wallpaper and menu mark (`D-2026-10-31-02`).
# `B1751`. The phone — Google's Android Emulator with one real Android system
# image, adb and scrcpy (`provision.sh phone`, `workstation/phone.py`) — only
# when asked for: about 4 GB, x86_64 only, and building it accepts the Android
# SDK License. `docker-compose.yml` passes WORKSTATION_PHONE through; set it to
# `on` in `.env` and rebuild. The image name is kept in the environment, where
# the daemon reads which system image this build has.
ARG WORKSTATION_PHONE=off
ARG WORKSTATION_PHONE_IMAGE="system-images;android-35;google_apis;x86_64"
ARG ANDROID_CMDLINE_TOOLS_SHA256=
RUN --mount=type=secret,id=build-ca,required=false,mode=0444 \
    if [ "$WORKSTATION_PHONE" = "on" ]; then \
        PHONE_IMAGE="$WORKSTATION_PHONE_IMAGE" \
        ANDROID_CMDLINE_TOOLS_SHA256="$ANDROID_CMDLINE_TOOLS_SHA256" \
        sh /opt/pantheon-workstation/provision/provision.sh phone /opt/android-sdk; \
    fi
ENV ANDROID_SDK_ROOT=/opt/android-sdk \
    PANTHEON_PHONE_IMAGE=${WORKSTATION_PHONE_IMAGE}

COPY firefox/policies.json /opt/pantheon-workstation/provision/firefox/policies.json
COPY skel/ /opt/pantheon-workstation/provision/skel/
COPY desktop/ /opt/pantheon-workstation/provision/desktop/
RUN sh /opt/pantheon-workstation/provision/provision.sh files --skel /etc/skel
COPY *.py /opt/pantheon-workstation/workstation/
# `B976`. The overlay runs this container without CAP_NET_RAW (`P20-06`), and the
# kernel refuses to start a program whose file capability names one the machine
# never grants — Ubuntu's `ping` among them (measured 2026-10-01: `sudo apt-get
# install iputils-ping`, then `ping` → *Operation not permitted* at exec). After
# every dpkg run apt takes out of each program on PATH what this machine cannot
# grant, so `ping` starts and uses an unprivileged ICMP socket
# (`workstation/netraw.py`). Here and not in `provision.sh`: the container is the
# only backend that drops a capability.
COPY apt-net-raw.conf /etc/apt/apt.conf.d/80pantheon-net-raw

ENV LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /opt/pantheon-workstation
EXPOSE 7040
# tini is PID 1 so the orphans an agent leaves behind (`nohup … &` and exit)
# are reaped rather than piling up as zombies under the daemon.
ENTRYPOINT ["/usr/bin/tini", "--", "python3", "-m", "workstation"]
CMD ["--system", "ubuntu", "--bind", "0.0.0.0"]
