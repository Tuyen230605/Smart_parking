#!/usr/bin/env bash
# Chép cert pi-01 + config.local.toml sang Pi qua SSH.   ./copy-pi-certs.sh oi@192.168.1.50
set -euo pipefail
TARGET="${1:?Cách dùng: ./copy-pi-certs.sh <user>@<ip-pi> [thư-mục-repo-trên-pi]}"
REMOTE_REPO="${2:-~/Cloud-Course}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
C="$REPO_ROOT/secrets/certs"
TMP="/tmp/parking-certs-$$"
ssh "$TARGET" "mkdir -p $TMP"
scp "$C/AmazonRootCA1.pem" "$TARGET:$TMP/AmazonRootCA1.pem"
scp "$C/pi-01/cert.pem" "$TARGET:$TMP/pi-01.cert.pem"
scp "$C/pi-01/private.key" "$TARGET:$TMP/pi-01.private.key"
scp "$REPO_ROOT/edge/raspberry-pi-vision/config.local.toml" "$TARGET:$REMOTE_REPO/edge/raspberry-pi-vision/config.local.toml"
ssh -t "$TARGET" "sudo mkdir -p /etc/parking/certs && sudo mv $TMP/* /etc/parking/certs/ && rmdir $TMP && \
  sudo chown -R \$(id -u):\$(id -g) /etc/parking/certs && chmod 600 /etc/parking/certs/pi-01.private.key && \
  ls -l /etc/parking/certs"
echo "✅ Đã chép cert sang $TARGET:/etc/parking/certs"
