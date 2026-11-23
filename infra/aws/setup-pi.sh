#!/usr/bin/env bash
# Đưa Smart Parking lên Pi bằng một lệnh, chạy từ LAPTOP:
#   ./setup-pi.sh <user>@<ip-pi>
# 1. Kiểm tra Pi có internet   2. git clone/pull repo về ~/Cloud-Course
# 3. Chép cert pi-01 + config.local.toml   4. Cài venv + systemd (install-pi.sh)   5. In trạng thái camera
# KHÔNG tự chuyển camera: xem kết quả rồi chạy ./pi-mode.sh parking trên Pi.
# Chạy lại an toàn (cập nhật code mới nhất từ GitHub).
set -euo pipefail
TARGET="${1:?Cách dùng: ./setup-pi.sh <user>@<ip-pi>}"
REPO_URL="${REPO_URL:-https://github.com/Tuyen230605/Smart_parking.git}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
[ -f "$REPO_ROOT/secrets/certs/pi-01/cert.pem" ] || { echo "Chưa có cert pi-01 — chạy ./provision-devices.sh trước"; exit 1; }

echo "→ [1/5] Pi có internet?"
ssh "$TARGET" 'curl -sS -o /dev/null --max-time 8 https://aws.amazon.com && echo "  ✓ có internet" || { echo "  ✗ Pi chưa ra được internet (xem docs/setup-guide.md mục 7.1)"; exit 1; }'

echo "→ [2/5] Lấy code"
ssh "$TARGET" "command -v git >/dev/null || sudo apt-get install -y git; \
  if [ -d ~/Cloud-Course/.git ]; then git -C ~/Cloud-Course pull --ff-only; \
  else git clone $REPO_URL ~/Cloud-Course; fi"

echo "→ [3/5] Chép cert pi-01"
"$HERE/copy-pi-certs.sh" "$TARGET"

echo "→ [4/5] Cài pi-vision (cần mật khẩu sudo của Pi)"
ssh -t "$TARGET" "cd ~/Cloud-Course/edge/raspberry-pi-vision && ./install-pi.sh"

echo "→ [5/5] Ai đang giữ camera"
ssh -t "$TARGET" "cd ~/Cloud-Course/edge/raspberry-pi-vision && ./pi-mode.sh status"

cat <<MSG

✅ Pi đã có code + cert. Chuyển camera sang bãi xe (trên Pi):
   ssh $TARGET
   cd ~/Cloud-Course/edge/raspberry-pi-vision && ./pi-mode.sh parking
   journalctl -u pi-vision -f        # phải thấy "Đã kết nối MQTT"
Hiệu chỉnh: mở http://<ip-pi>:8000 trên laptop.
MSG
