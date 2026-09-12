#!/usr/bin/env bash
# One-command install on a fresh Ubuntu 22.04/24.04 VPS.
#
#   sudo REPO=https://github.com/jbergie03-gif/Trage-Gate.git bash install.sh
#
# Installs the scanner under /opt/nfl-scanner and runs it as a systemd service
# that restarts on failure and starts on boot. Read-only: it never trades.

set -euo pipefail

REPO="${REPO:-https://github.com/jbergie03-gif/Trage-Gate.git}"
SUBDIR="${SUBDIR:-nfl_scanner}"
CHECKOUT="${CHECKOUT:-/opt/nfl-scanner-src}"
DEST="${DEST:-/opt/nfl-scanner}"
SERVICE="nfl-scanner"
RUN_USER="${RUN_USER:-scanner}"

if [[ $EUID -ne 0 ]]; then
  echo "run with sudo" >&2
  exit 1
fi

apt-get update -qq
apt-get install -y -qq python3 python3-venv git sqlite3

id -u "$RUN_USER" &>/dev/null || useradd --system --create-home --shell /usr/sbin/nologin "$RUN_USER"

if [[ -d "$CHECKOUT/.git" ]]; then
  git -C "$CHECKOUT" pull --ff-only
else
  git clone --depth 1 "$REPO" "$CHECKOUT"
fi

mkdir -p "$DEST"
cp "$CHECKOUT/$SUBDIR"/*.py "$DEST/"
mkdir -p "$DEST/data"
chown -R "$RUN_USER:$RUN_USER" "$DEST"

cat >"/etc/systemd/system/$SERVICE.service" <<EOF
[Unit]
Description=Cross-venue NFL prediction market scanner
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$DEST
ExecStart=/usr/bin/python3 $DEST/scan.py
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=$DEST/data

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "$SERVICE"
sleep 3
systemctl --no-pager --lines=15 status "$SERVICE" || true

cat <<EOF

Installed. Useful commands:
  systemctl status $SERVICE          # is it alive
  journalctl -u $SERVICE -f          # live log, ALERT lines are the ones that matter
  cd $DEST && python3 report.py      # what it has found so far

To update after a code change, re-run this script.
The SQLite database in $DEST/data survives re-runs.
EOF
