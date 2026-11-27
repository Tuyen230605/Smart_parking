#!/usr/bin/env bash
# Cài pi-vision lên Raspberry Pi 5: thư viện, venv, systemd unit theo user hiện tại.
#   cd ~/Cloud-Course/edge/raspberry-pi-vision && ./install-pi.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="${VENV:-$HOME/venv-parking}"

echo "→ apt: picamera2, opencv"
sudo apt-get update -qq
sudo apt-get install -y python3-picamera2 python3-opencv python3-venv >/dev/null

echo "→ venv $VENV"
[ -d "$VENV" ] || python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/pip" install -q -r "$HERE/requirements.txt"
(cd "$HERE" && "$VENV/bin/python" -m unittest -q test_presence)

[ -f "$HERE/config.local.toml" ] || echo "⚠ Chưa có config.local.toml — chạy infra/aws/copy-pi-certs.sh từ laptop"
[ -f /etc/parking/certs/pi-01.private.key ] || echo "⚠ Chưa có cert trong /etc/parking/certs"

echo "→ systemd unit pi-vision (User=$USER)"
sudo tee /etc/systemd/system/pi-vision.service >/dev/null <<UNIT
[Unit]
Description=Smart parking vision pi-01
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$HERE
ExecStart=$VENV/bin/python main.py --config config.toml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now pi-vision
echo "✅ Cài xong, pi-vision đã chạy và tự bật khi khởi động. Xem log: journalctl -u pi-vision -f"
