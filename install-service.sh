#!/bin/bash
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
sudo systemctl start pantheon-ui
sudo systemctl status pantheon-ui
