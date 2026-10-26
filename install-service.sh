#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="$SCRIPT_DIR/pantheon-ui.service"

if [ ! -f "$SERVICE_FILE" ]; then
  echo "Error: pantheon-ui.service not found in $SCRIPT_DIR"
  exit 1
fi

echo "Installing Pantheon UI service..."
echo "Make sure you've edited pantheon-ui.service with your username and paths first!"
echo ""

sudo cp "$SERVICE_FILE" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pantheon-ui
# B444: the unit's ExecStartPost waits for /api/ready, so `start` returns only
# once the app is serving, or fails when it never does. This used to print
# `systemctl status` straight after `start`, which read `active (running)` while
# port 7000 still refused connections.
echo "Starting — this waits until Pantheon answers on port 7000 (up to 3 minutes)..."
if sudo systemctl start pantheon-ui; then
  echo "Pantheon UI is serving: http://127.0.0.1:7000"
  sudo systemctl status pantheon-ui --no-pager || true
else
  echo "Pantheon UI did not come up, so the service is not running."
  echo "Its log says why: sudo journalctl -u pantheon-ui -n 80 --no-pager"
  sudo systemctl status pantheon-ui --no-pager || true
  exit 1
fi
