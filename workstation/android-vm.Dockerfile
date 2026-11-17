# SPDX-License-Identifier: AGPL-3.0-or-later
# Pantheon's Android VM service — `android-vm` in docker-compose.yml.
#
# One Android VM per person, beside (never inside) that person's Linux desktop
# VM, which `vm.Dockerfile`'s service runs. What it runs and why is in
# `native_android/service.py`; the pattern the VM services share is in
# `docs/vm-services.md`. Same build context as `vm.Dockerfile`:
#
#     docker build -f workstation/android-vm.Dockerfile -t pantheon-android-vm workstation/
#
# Nothing of Google's is in this image. The emulator, platform-tools and Android
# system images are downloaded into the service's volume only after an admin
# has accepted Google's Android SDK License at a terminal
# (`docker compose run --rm android-vm accept-license`).
#
# `B1677`. The same base as `Dockerfile` and `vm.Dockerfile`, by the same
# content address, and why is written in `Dockerfile`.
FROM ubuntu:noble-20261024.1@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852

ARG DEBIAN_FRONTEND=noninteractive
# The same optional knob as `vm.Dockerfile`, for a builder that cannot reach
# Ubuntu's mirrors directly; not left in a layer.
ARG APT_MIRROR=

# Ubuntu's own packages: Python for the worker, nftables for the service's
# kernel rules, tini as PID 1, and the libraries Google's Linux emulator links
# (the list `provision.sh` installs for it, less the JDK and USB, which a
# headless emulator here does not use).
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
        ca-certificates python3 python3-venv nftables tini \
        libpulse0 libnss3 libxcomposite1 libxcursor1 libxi6 libxtst6 libasound2t64 libgl1 libegl1 \
        libgbm1 libdrm2 libxkbcommon0 libxkbfile1 libxdamage1 libxrandr2 libxshmfence1 \
        libdbus-glib-1-2 libbsd0; \
    rm -f /etc/apt/apt.conf.d/99-build-ca; \
    rm -rf /var/lib/apt/lists/*

# The worker's Python packages from PyPI, every file checked against the
# SHA-256 in the lock (the lock `bootstrap.py` installs on a host).
COPY native_android/host-requirements.lock /opt/pantheon/host-requirements.lock
RUN --mount=type=secret,id=build-ca,required=false,mode=0444 \
    set -eu; \
    if [ -s /run/secrets/build-ca ]; then export PIP_CERT=/run/secrets/build-ca; fi; \
    python3 -m venv /opt/pantheon/venv; \
    /opt/pantheon/venv/bin/pip install --no-cache-dir --only-binary=:all: --require-hashes \
        -r /opt/pantheon/host-requirements.lock

# The worker's code: the workstation package (protocol, kernel rules, the
# phone) and the native Android host.
COPY *.py /opt/pantheon/workstation/
COPY native_android/ /opt/pantheon/workstation/native_android/

ENV LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/pantheon \
    PATH=/opt/pantheon/venv/bin:/usr/sbin:/usr/bin:/sbin:/bin
WORKDIR /opt/pantheon
EXPOSE 7993
# Starts as root only to open KVM to the service's account and write its kernel
# rules; `service.py` then drops to that account (uid 500) for good.
ENTRYPOINT ["/usr/bin/tini", "--", "python3", "-m", "workstation.native_android.service"]
CMD ["serve"]
