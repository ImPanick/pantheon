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

# Mozilla's signing key, committed rather than fetched so the build trusts a key
# somebody checked, not whatever the network answered. Fingerprint
# 35BAA0B33E9EB396F59CA838C0BA5CE6DC6315A3 (Mozilla's published value, checked
# 2026-09-30 with `gpg --show-keys`).
COPY firefox/packages.mozilla.org.asc /etc/apt/keyrings/packages.mozilla.org.asc

RUN --mount=type=secret,id=build-ca,required=false,mode=0444 \
    set -eu; \
    if [ -n "$APT_MIRROR" ]; then \
        sed -i -E "s#^URIs: .*#URIs: ${APT_MIRROR}#" /etc/apt/sources.list.d/ubuntu.sources; \
    fi; \
    if [ -s /run/secrets/build-ca ]; then \
        echo 'Acquire::https::CAInfo "/run/secrets/build-ca";' > /etc/apt/apt.conf.d/99-build-ca; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates curl git sudo tini procps less nano unzip xz-utils \
        python3 python3-venv python3-pip build-essential \
        xvfb jwm xterm xdotool scrot fonts-dejavu-core dbus-daemon dbus-bin; \
    # Firefox from Mozilla's own repository: Ubuntu's `firefox` is a snap
    # wrapper, and snapd does not run in a container. The pin keeps apt from
    # ever preferring the wrapper.
    printf 'Types: deb\nURIs: https://packages.mozilla.org/apt\nSuites: mozilla\nComponents: main\nSigned-By: /etc/apt/keyrings/packages.mozilla.org.asc\n' \
        > /etc/apt/sources.list.d/mozilla.sources; \
    printf 'Package: *\nPin: origin packages.mozilla.org\nPin-Priority: 1000\n' \
        > /etc/apt/preferences.d/mozilla; \
    apt-get update; \
    apt-get install -y --no-install-recommends firefox; \
    rm -f /etc/apt/apt.conf.d/99-build-ca; \
    rm -rf /var/lib/apt/lists/*; \
    # The base image's `ubuntu` user (uid 1000) is nobody here. Removing it
    # keeps 1000 free, which is Pantheon's default PGID — the group the pairing
    # token is readable by (`docker/workstation.yml`).
    userdel -r ubuntu 2>/dev/null || true

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
COPY firefox/policies.json /etc/firefox/policies/policies.json
# The skeleton every home starts from and "Reset to clean" returns to.
COPY skel/ /etc/skel/
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
