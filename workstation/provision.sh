#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Make an Ubuntu 24.04 machine the workstation's userland — `P20-07`.
#
# ONE list of what a workstation has, for every backend (`Law 14`). Before this
# file the list lived inline in `Dockerfile`; a VM provisioned by cloud-init or a
# host set up by `install.py` would have needed a second copy, and a second copy
# is the one that goes stale. So:
#
#   Dockerfile (the container image)   sh provision.sh packages --image
#                                      sh provision.sh files --skel /etc/skel
#   vm.py (the VM's base image)        the same two, inside the VM, from cloud-init
#   install.py (another machine)       sh provision.sh packages
#                                      sh provision.sh files --code /opt/pantheon-workstation
#
#   packages   apt: the desktop, the tools and Mozilla's Firefox (below).
#              --image: this is an image being built, not somebody's machine —
#              also drop apt's lists and the base image's `ubuntu` user (uid
#              1000, Pantheon's default PGID: the pairing group). Never on a host
#              an operator owns: that user may be them.
#   files      Firefox's no-phone-home policy (--policies DIR, default
#              /etc/firefox/policies, where Firefox reads it), and the skeleton
#              new homes start from (--skel DIR, default
#              /opt/pantheon-workstation/skel); with --code DIR also the
#              daemon's package (DIR/workstation/*.py).
#
# Optional, for a builder that cannot reach Ubuntu's mirrors directly — none of
# it is left behind, and nothing about any one network goes into the result:
#   APT_MIRROR      an Ubuntu mirror to use instead (e.g. https://archive.ubuntu.com/ubuntu)
#   APT_PROXY       an HTTP(S) proxy for apt (e.g. an apt-cacher, or a corporate proxy)
#   PROVISION_CA    a CA file apt trusts for HTTPS while provisioning; the
#                   Dockerfile's BuildKit secret `build-ca` is used when present.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
STEP=${1:-}
[ $# -gt 0 ] && shift

# The workstation's own packages. Changing this list changes every backend.
PACKAGES="ca-certificates curl git sudo tini procps less nano unzip xz-utils \
python3 python3-venv python3-pip build-essential \
xvfb jwm xterm xdotool scrot fonts-dejavu-core dbus-daemon dbus-bin"

say() { printf 'provision: %s\n' "$*"; }

packages() {
    image=no
    while [ $# -gt 0 ]; do
        case "$1" in
            --image) image=yes ;;
            *) say "unknown option $1"; exit 2 ;;
        esac
        shift
    done
    export DEBIAN_FRONTEND=noninteractive
    if [ -n "${APT_MIRROR:-}" ]; then
        say "using the mirror $APT_MIRROR"
        sed -i -E "s#^URIs: .*#URIs: ${APT_MIRROR}#" /etc/apt/sources.list.d/ubuntu.sources
    fi
    ca=${PROVISION_CA:-/run/secrets/build-ca}
    if [ -s "$ca" ]; then
        echo "Acquire::https::CAInfo \"$ca\";" > /etc/apt/apt.conf.d/99-provision-ca
    fi
    if [ -n "${APT_PROXY:-}" ]; then
        printf 'Acquire::http::Proxy "%s";\nAcquire::https::Proxy "%s";\n' "$APT_PROXY" "$APT_PROXY" \
            > /etc/apt/apt.conf.d/99-provision-proxy
    fi
    apt-get update
    # shellcheck disable=SC2086 # the list is words on purpose
    apt-get install -y --no-install-recommends $PACKAGES
    # Firefox from Mozilla's own repository: Ubuntu's `firefox` is a snap
    # wrapper, and snapd does not run in a container. The pin keeps apt from
    # ever preferring the wrapper. Mozilla's key is committed, not fetched
    # (`firefox/packages.mozilla.org.asc`, fingerprint 35BAA0B3…15A3).
    install -d -m 0755 /etc/apt/keyrings
    install -m 0644 "$HERE/firefox/packages.mozilla.org.asc" /etc/apt/keyrings/packages.mozilla.org.asc
    printf 'Types: deb\nURIs: https://packages.mozilla.org/apt\nSuites: mozilla\nComponents: main\nSigned-By: /etc/apt/keyrings/packages.mozilla.org.asc\n' \
        > /etc/apt/sources.list.d/mozilla.sources
    printf 'Package: *\nPin: origin packages.mozilla.org\nPin-Priority: 1000\n' \
        > /etc/apt/preferences.d/mozilla
    apt-get update
    apt-get install -y --no-install-recommends firefox
    rm -f /etc/apt/apt.conf.d/99-provision-ca /etc/apt/apt.conf.d/99-provision-proxy
    if [ "$image" = yes ]; then
        rm -rf /var/lib/apt/lists/*
        userdel -r ubuntu 2>/dev/null || true
    fi
    say "packages installed"
}

files() {
    skel=/opt/pantheon-workstation/skel
    code=
    policies=/etc/firefox/policies
    while [ $# -gt 0 ]; do
        case "$1" in
            --skel) skel=$2; shift ;;
            --code) code=$2; shift ;;
            --policies) policies=$2; shift ;;
            *) say "unknown option $1"; exit 2 ;;
        esac
        shift
    done
    # `Law 16`: what Firefox may not do on its own (the list is in the file;
    # measured 2026-09-30 in `P20-01`: 135 lookups of 15 outside hosts without
    # it, none with it).
    install -d -m 0755 "$policies"
    install -m 0644 "$HERE/firefox/policies.json" "$policies/policies.json"
    install -d -m 0755 "$skel"
    if [ "$skel" != /etc/skel ]; then
        # A skeleton of the workstation's own on a machine whose /etc/skel is
        # not ours to change: the system's files first (.bashrc, .profile), so
        # a home made from it is the home the container image makes.
        cp -a /etc/skel/. "$skel/"
    fi
    cp -a "$HERE/skel/." "$skel/"
    if [ -n "$code" ]; then
        install -d -m 0755 "$code/workstation"
        install -m 0644 "$HERE"/*.py "$code/workstation/"
    fi
    say "files in place (skeleton $skel${code:+, daemon $code/workstation})"
}

case "$STEP" in
    packages) packages "$@" ;;
    files) files "$@" ;;
    *) echo "usage: provision.sh packages [--image] | files [--skel DIR] [--code DIR] [--policies DIR]" >&2; exit 2 ;;
esac
