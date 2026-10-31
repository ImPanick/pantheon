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
#              It also installs KasmVNC's X server (`D-2026-10-31-01`), the
#              display every person's desktop is: the package below, pinned by
#              version and by checksum per architecture, refused on a mismatch.
#   client DIR (Pantheon's image, not a workstation) KasmVNC's web client,
#              unpacked from that same pinned package into DIR — Pantheon
#              serves it itself (`src/desktop_client.py`), so the browser only
#              ever runs the copy this file names. Nothing in the package runs.
#   files      Firefox's no-phone-home policy (--policies DIR, default
#              /etc/firefox/policies, where Firefox reads it), the skeleton
#              new homes start from (--skel DIR, default
#              /opt/pantheon-workstation/skel), and the desktop's look
#              (`D-2026-10-31-02`): Pantheon's window frames (--themes DIR,
#              default /usr/share/themes) and the wallpaper and the menu's mark
#              (--share DIR, default /usr/share/pantheon-workstation, where the
#              skeleton's settings name them); with --code DIR also the
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
xvfb jwm xterm xdotool scrot fonts-dejavu-core dbus-daemon dbus-bin \
nftables \
xfwm4 xfce4-panel xfdesktop4 xfce4-session xfce4-settings xfconf xfce4-terminal thunar \
xfce4-whiskermenu-plugin papirus-icon-theme adwaita-icon-theme fonts-inter \
fonts-jetbrains-mono librsvg2-common"
# `nftables` (`P20-06`): the network gate, which runs from the same image, writes the
# admin's mode with `nft`. In the workstation itself it does nothing: the overlay gives
# the workstation no `CAP_NET_ADMIN`.
# `xvfb` stays beside KasmVNC: it is the display where KasmVNC has no package (an
# architecture other than these two), and the agent's screenshots work on it as before.
# `D-2026-10-31-02`. The desktop is XFCE, themed to the cockpit (`files` below puts
# the theme in place; the settings are the skeleton's `.config`): its window manager
# with a compositor, the panel and its menu, the wallpaper, the session that starts
# them, the terminal and the file manager, Papirus's icons over Adwaita's, Inter and
# JetBrains Mono, and the SVG loader the wallpaper and the menu's mark need. About
# 300 MB with the icons (apt's own figure on Ubuntu 24.04, 2026-10-31); the admin
# chose the look over the size. `jwm` and `xterm` stay: they are the desktop a
# machine without XFCE still gets (`ubuntu.py`).

# `D-2026-10-31-01`. The live desktop: KasmVNC's X server for Ubuntu 24.04, from
# Kasm Technologies' own release (GPL-2.0-or-later; https://github.com/kasmtech/KasmVNC).
# The checksums were read from the two packages themselves when this was pinned
# (2026-10-31); a package that does not match is refused, never installed. Moving the
# version means downloading both, reading both sums, and changing all three lines.
KASMVNC_VERSION=1.5.2
KASMVNC_SHA256_AMD64=89a5d1fbe9e032b122202be158a2b25f15c97e0a5b8dcf92a5e6835c7b7b2acd
KASMVNC_SHA256_ARM64=4d680f3d1eb77fb155ae67af7f9fa25d7fbd38a7f69ae146784c7f738e2eed1a
KASMVNC_URL=https://github.com/kasmtech/KasmVNC/releases/download

say() { printf 'provision: %s\n' "$*"; }

# kasmvnc_deb ARCH OUT: the pinned KasmVNC package for ARCH (amd64 or arm64),
# downloaded to OUT and checked against its sum; anything else stops the script.
kasmvnc_deb() {
    arch=$1
    out=$2
    case "$arch" in
        amd64) sum=$KASMVNC_SHA256_AMD64 ;;
        arm64) sum=$KASMVNC_SHA256_ARM64 ;;
        *) say "KasmVNC builds no package for $arch"; exit 1 ;;
    esac
    url="$KASMVNC_URL/v$KASMVNC_VERSION/kasmvncserver_ubuntu_noble_${KASMVNC_VERSION}_$arch.deb"
    cacert=
    ca=${PROVISION_CA:-/run/secrets/build-ca}
    if [ -s "$ca" ]; then
        # The builder's CA beside the system's, never instead of it: a proxy that
        # inspects TLS re-signs GitHub too, and one that does not leaves it alone.
        cat /etc/ssl/certs/ca-certificates.crt "$ca" > /tmp/provision-ca.pem
        cacert=/tmp/provision-ca.pem
    fi
    say "fetching KasmVNC $KASMVNC_VERSION ($arch)"
    curl --fail --silent --show-error --location --retry 3 ${cacert:+--cacert "$cacert"} \
        --output "$out" "$url"
    rm -f /tmp/provision-ca.pem
    if ! printf '%s  %s\n' "$sum" "$out" | sha256sum -c - >/dev/null 2>&1; then
        rm -f "$out"
        say "the KasmVNC package did not match its pinned checksum; refusing it"
        exit 1
    fi
}

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
    # The live desktop (`D-2026-10-31-01`): KasmVNC's X server, installed from the
    # pinned package with apt so its libraries come from Ubuntu.
    arch=$(dpkg --print-architecture)
    case "$arch" in
        amd64|arm64)
            kasmvnc_deb "$arch" /tmp/kasmvncserver.deb
            apt-get install -y --no-install-recommends /tmp/kasmvncserver.deb
            rm -f /tmp/kasmvncserver.deb ;;
        *) say "KasmVNC builds no package for $arch; the desktop is shown as pictures (Xvfb)" ;;
    esac
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
    themes=/usr/share/themes
    share=/usr/share/pantheon-workstation
    while [ $# -gt 0 ]; do
        case "$1" in
            --skel) skel=$2; shift ;;
            --code) code=$2; shift ;;
            --policies) policies=$2; shift ;;
            --themes) themes=$2; shift ;;
            --share) share=$2; shift ;;
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
        # Replace even read-only files on a re-run. cp -a alone tries to open
        # the old file for writing; --remove-destination unlinks it first and
        # still preserves the source file's mode and contents.
        cp -a --remove-destination /etc/skel/. "$skel/"
    fi
    cp -a "$HERE/skel/." "$skel/"
    # `D-2026-10-31-02`: what the skeleton's XFCE settings name — the window
    # frames (made by scripts/make-workstation-theme.py, never edited by hand),
    # the wallpaper and the menu button's mark. Replaced whole, so a part the
    # theme no longer has does not linger.
    rm -rf "$themes/Pantheon"
    install -d -m 0755 "$themes/Pantheon/xfwm4" "$share"
    install -m 0644 "$HERE"/desktop/themes/Pantheon/xfwm4/* "$themes/Pantheon/xfwm4/"
    install -m 0644 "$HERE/desktop/pantheon-desktop.svg" "$HERE/desktop/pantheon-mark.svg" "$share/"
    if [ -n "$code" ]; then
        install -d -m 0755 "$code/workstation"
        install -m 0644 "$HERE"/*.py "$code/workstation/"
    fi
    say "files in place (skeleton $skel, theme $themes/Pantheon${code:+, daemon $code/workstation})"
}

client() {
    [ $# -eq 1 ] || { say "client takes one folder"; exit 2; }
    # The web client is the same in both architectures' packages, so the amd64 one
    # is read whatever this runs on. `dpkg-deb -x` unpacks files and runs nothing.
    deb=/tmp/kasmvncserver.deb
    kasmvnc_deb amd64 "$deb"
    rm -rf /tmp/kasmvnc-unpacked
    dpkg-deb -x "$deb" /tmp/kasmvnc-unpacked
    install -d -m 0755 "$1"
    cp -a /tmp/kasmvnc-unpacked/usr/share/kasmvnc/www "$1/www"
    install -d -m 0755 "$1/LICENSES"
    install -m 0644 /tmp/kasmvnc-unpacked/usr/share/doc/kasmvncserver/copyright "$1/LICENSES/kasmvncserver-copyright"
    rm -rf /tmp/kasmvnc-unpacked "$deb"
    chmod -R a+rX "$1"
    say "KasmVNC $KASMVNC_VERSION web client in $1/www"
}

case "$STEP" in
    packages) packages "$@" ;;
    files) files "$@" ;;
    client) client "$@" ;;
    *) echo "usage: provision.sh packages [--image] | files [--skel DIR] [--code DIR] [--policies DIR] [--themes DIR] [--share DIR] | client DIR" >&2; exit 2 ;;
esac
