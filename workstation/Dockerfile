# SPDX-License-Identifier: AGPL-3.0-or-later
# The Pantheon workstation — `P20-01`, `D-2026-09-30-03`.
#
# An Ubuntu 24.04 userland the agents work in: one Unix account and one X
# display per person, a light desktop (JWM, a terminal, Firefox), the tools a
# task usually needs, and `agentd` answering `workstation/protocol.py` on 7040.
# The build context is this directory and nothing else:
#
#     docker build -t pantheon-workstation workstation/
#
# It is started by `docker/workstation.yml`; nothing here reaches Pantheon's
# data, and Pantheon's image does not depend on this one.
FROM ubuntu:24.04

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
# skeleton every home starts from and "Reset to clean" returns to in /etc/skel.
COPY firefox/policies.json /opt/pantheon-workstation/provision/firefox/policies.json
COPY skel/ /opt/pantheon-workstation/provision/skel/
RUN sh /opt/pantheon-workstation/provision/provision.sh files --skel /etc/skel
COPY *.py /opt/pantheon-workstation/workstation/

ENV LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /opt/pantheon-workstation
EXPOSE 7040
# tini is PID 1 so the orphans an agent leaves behind (`nohup … &` and exit)
# are reaped rather than piling up as zombies under the daemon.
ENTRYPOINT ["/usr/bin/tini", "--", "python3", "-m", "workstation"]
CMD ["--system", "ubuntu", "--bind", "0.0.0.0"]
