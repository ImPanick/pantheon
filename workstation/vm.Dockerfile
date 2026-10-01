# SPDX-License-Identifier: AGPL-3.0-or-later
# The workstation's VM backend — `P20-07`, `D-2026-09-30-03`.
#
# Not the workstation itself: the host that runs one Ubuntu VM per person under
# QEMU and answers `workstation/protocol.py` for all of them on 7040
# (`workstation/vm.py`). Each machine is made from Ubuntu's cloud image,
# provisioned on the first start by cloud-init with the same `provision.sh` the
# container image is built from. Same build context as `Dockerfile`:
#
#     docker build -f workstation/vm.Dockerfile -t pantheon-workstation-vm workstation/
#
# Started by `docker/workstation-vm.yml`.
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
# The same two optional knobs as `Dockerfile`, for a builder that cannot reach
# Ubuntu's mirrors directly; neither is left in a layer.
ARG APT_MIRROR=
# Where Ubuntu publishes the cloud image the machines are made from. The
# `release` directory is the newest 24.04 build; its checksum list is signed by
# Ubuntu's cloud-image key, which comes from Ubuntu's own archive
# (`ubuntu-cloudimage-keyring`, apt-verified) rather than from the network.
# Pin a dated build (`…/noble/release-20260926`) for a reproducible image.
ARG CLOUD_IMAGE_URL=https://cloud-images.ubuntu.com/releases/noble/release
ARG CLOUD_IMAGE_FILE=ubuntu-24.04-server-cloudimg-amd64.img

RUN --mount=type=secret,id=build-ca,required=false,mode=0444 \
    set -eu; \
    if [ -n "$APT_MIRROR" ]; then \
        sed -i -E "s#^URIs: .*#URIs: ${APT_MIRROR}#" /etc/apt/sources.list.d/ubuntu.sources; \
    fi; \
    if [ -s /run/secrets/build-ca ]; then \
        echo 'Acquire::https::CAInfo "/run/secrets/build-ca";' > /etc/apt/apt.conf.d/99-build-ca; \
        export CURL_CA_BUNDLE=/run/secrets/build-ca; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates curl gpgv ubuntu-cloudimage-keyring \
        qemu-system-x86 qemu-utils genisoimage python3 tini; \
    mkdir -p /opt/pantheon-workstation/vm; \
    cd /opt/pantheon-workstation/vm; \
    curl -fsSL -o SHA256SUMS "$CLOUD_IMAGE_URL/SHA256SUMS"; \
    curl -fsSL -o SHA256SUMS.gpg "$CLOUD_IMAGE_URL/SHA256SUMS.gpg"; \
    gpgv --keyring /usr/share/keyrings/ubuntu-cloudimage-keyring.gpg SHA256SUMS.gpg SHA256SUMS; \
    curl -fsSL -o "$CLOUD_IMAGE_FILE" "$CLOUD_IMAGE_URL/$CLOUD_IMAGE_FILE"; \
    grep " \*$CLOUD_IMAGE_FILE\$" SHA256SUMS | sha256sum -c -; \
    mv "$CLOUD_IMAGE_FILE" ubuntu-cloud.img; \
    rm -f SHA256SUMS.gpg /etc/apt/apt.conf.d/99-build-ca; \
    apt-get purge -y curl; \
    rm -rf /var/lib/apt/lists/*

# What each machine is provisioned with, the same files `Dockerfile` uses.
COPY provision.sh vm-guest.sh /opt/pantheon-workstation/payload/
COPY firefox/ /opt/pantheon-workstation/payload/firefox/
COPY skel/ /opt/pantheon-workstation/payload/skel/
# The daemon's code: this host runs `vm.py`, and every machine is given the
# same files on its app disk at each start.
COPY *.py /opt/pantheon-workstation/workstation/

ENV LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /opt/pantheon-workstation
EXPOSE 7040
ENTRYPOINT ["/usr/bin/tini", "--", "python3", "-m", "workstation.vm"]
