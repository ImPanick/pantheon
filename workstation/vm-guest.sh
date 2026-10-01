#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Inside the VM backend's base image, once, while it is being made — `P20-07`.
#
# `workstation/vm.py` boots Ubuntu's cloud image with a cloud-init seed that
# writes this directory to /opt/pantheon-workstation/provision and runs
# `vm-guest.sh bake`. It makes the image every person's machine starts from:
#
#   1. the workstation itself: `provision.sh`, the same list the container
#      image is built from (`Law 14`);
#   2. the daemon as a service, from the app disk each machine is given at
#      every start (its code and that machine's own token), so a new Pantheon
#      reaches every machine on its next start without a new image;
#   3. the cloud image made quiet (`Law 16`, below);
#   4. no cloud-init next time, and no machine-id, so each machine made from
#      the image gets its own on its first boot.
#
# It ends by writing one line to the serial console — the launcher reads that
# line, not a guess, to decide whether the image is ready.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
OK=PANTHEON-WORKSTATION-IMAGE-READY
FAILED=PANTHEON-WORKSTATION-IMAGE-FAILED
APP=/opt/pantheon-workstation/app

say() { printf 'vm-guest: %s\n' "$*"; printf 'vm-guest: %s\n' "$*" > /dev/ttyS0 2>/dev/null || true; }

bake() {
    trap 'say "$FAILED"' EXIT
    # Build-time knobs (a mirror, a proxy, a CA) arrive here and nowhere else,
    # and are removed before the image is closed.
    if [ -f "$HERE/provision.env" ]; then
        set -a; . "$HERE/provision.env"; set +a
    fi
    sh "$HERE/provision.sh" packages --image
    sh "$HERE/provision.sh" files --skel /etc/skel

    # The app disk: label PWSAPP, read-only, mounted where the unit runs from.
    # Five minutes for it to appear, because under TCG a busy host's udev is
    # that slow; it is always attached, so the wait ends when it does.
    install -d -m 0755 "$APP"
    grep -q 'LABEL=PWSAPP' /etc/fstab || \
        echo "LABEL=PWSAPP $APP iso9660 ro,nofail,x-systemd.device-timeout=5min 0 0" >> /etc/fstab
    install -m 0644 "$HERE/pantheon-workstation.service" /etc/systemd/system/pantheon-workstation.service
    # Offline (`--root=/`): the image is powered off next, so nothing needs
    # the running manager — and under TCG on a busy host its D-Bus answers
    # time out (measured `P20-07`: "Failed to list unit files: Connection
    # timed out" from a package's own script).
    systemctl --root=/ enable pantheon-workstation.service

    quiet

    rm -f "$HERE/provision.env" "$HERE/provision-ca.crt"
    touch /etc/cloud/cloud-init.disabled
    truncate -s 0 /etc/machine-id
    rm -f /var/lib/dbus/machine-id
    trap - EXIT
    say "$OK"
}

# `Law 16` — nothing in the machine talks to anyone nobody chose. Ubuntu's
# cloud image is a server meant for a cloud, and out of the box it reaches
# Canonical, Ubuntu's mirrors and the snap store on timers of its own. Each
# line is one of those, switched off; what replaces it (if anything) is said.
# Measured `P20-07`: see the row for the idle capture before and after.
quiet() {
    export DEBIAN_FRONTEND=noninteractive
    # The snap store: snapd refreshes from api.snapcraft.io. Nothing here is a
    # snap (Firefox is Mozilla's .deb, `provision.sh`). No `--auto-remove`
    # here or below: a metapackage that goes with it must not take the
    # packages it pulled in along.
    apt-get purge -y snapd 2>/dev/null || true
    rm -rf /snap /var/snap /var/lib/snapd
    # Entropy from entropy.ubuntu.com on first boot; the machine has virtio-rng.
    apt-get purge -y pollinate 2>/dev/null || true
    # Automatic updates and the daily apt runs: the image is re-made instead,
    # like the container image is rebuilt.
    apt-get purge -y unattended-upgrades 2>/dev/null || true
    for unit in apt-daily.timer apt-daily-upgrade.timer motd-news.timer ua-timer.timer \
                apt-news.service esm-cache.service fwupd-refresh.timer \
                update-notifier-download.timer update-notifier-motd.timer \
                systemd-timesyncd.service ssh.service ssh.socket; do
        systemctl --root=/ disable "$unit" 2>/dev/null || true
        systemctl --root=/ mask "$unit" 2>/dev/null || true
    done
    # MOTD news and Ubuntu Pro's apt news (motd.ubuntu.com, Canonical).
    [ -f /etc/default/motd-news ] && sed -i 's/^ENABLED=.*/ENABLED=0/' /etc/default/motd-news
    command -v pro >/dev/null 2>&1 && pro config set apt_news=false >/dev/null 2>&1 || true
    # The release-upgrade check (changelogs.ubuntu.com).
    [ -f /etc/update-manager/release-upgrades ] && \
        sed -i 's/^Prompt=.*/Prompt=never/' /etc/update-manager/release-upgrades
    # Time: ntp.ubuntu.com is not ours to call. The clock comes from the host,
    # through the virtual RTC at boot and kvm-clock under KVM.
    apt-get clean
    say "quietened"
}

case "${1:-}" in
    bake) bake ;;
    *) echo "usage: vm-guest.sh bake" >&2; exit 2 ;;
esac
