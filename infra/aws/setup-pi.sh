#!/usr/bin/env bash
# Đưa Smart Parking lên Pi bằng một lệnh, chạy từ LAPTOP:
#   ./setup-pi.sh <user>@<ip-pi>
# 1. Kiểm tra Pi có internet   2. git clone/pull repo về ~/Cloud-Course
# 3. Chép cert pi-01 + config.local.toml   4. Cài venv + systemd và bật pi-vision (install-pi.sh)
# Chạy lại an toàn (cập nhật code mới nhất từ GitHub).
set -euo pipefail
TARGET="${1:?Cách dùng: ./setup-pi.sh <user>@<ip-pi>}"
REPO_URL="${REPO_URL:-https://github.com/Tuyen230605/Smart_parking.git}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
[ -f "$REPO_ROOT/secrets/certs/pi-01/cert.pem" ] || { echo "Chưa có cert pi-01 — chạy ./provision-devices.sh trước"; exit 1; }

echo "→ [1/4] Pi có internet?"
ssh "$TARGET" 'curl -sS -o /dev/null --max-time 8 https://aws.amazon.com && echo "  ✓ có internet" || { echo "  ✗ Pi chưa ra được internet (xem docs/setup-guide.md mục 5)"; exit 1; }'

echo "→ [2/4] Lấy code"
ssh "$TARGET" "command -v git >/dev/null || sudo apt-get install -y git; \
  if [ -d ~/Cloud-Course/.git ]; then git -C ~/Cloud-Course pull --ff-only; \
  else git clone $REPO_URL ~/Cloud-Course; fi"

echo "→ [3/4] Chép cert pi-01"
"$HERE/copy-pi-certs.sh" "$TARGET"

echo "→ [4/4] Cài và bật pi-vision (cần mật khẩu sudo của Pi)"
ssh -t "$TARGET" "cd ~/Cloud-Course/edge/raspberry-pi-vision && ./install-pi.sh"

cat <<MSG

✅ Pi đã chạy pi-vision. Kiểm tra:
   ssh $TARGET 'journalctl -u pi-vision -n 20'   # phải thấy "Đã kết nối MQTT"
Trang camera: http://<ip-pi>:8000
MSG
