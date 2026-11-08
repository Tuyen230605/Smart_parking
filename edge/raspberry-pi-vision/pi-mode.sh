#!/usr/bin/env bash
# Pi 5 chỉ có MỘT camera và libcamera chỉ cho MỘT tiến trình giữ nó.
# Script này chuyển camera giữa dự án Smart Parking (pi-vision) và Smart Lighting (container vision).
#   ./pi-mode.sh parking    # dừng vision Lighting, bật pi-vision (giữ nguyên qua reboot)
#   ./pi-mode.sh lighting   # tắt pi-vision, bật lại vision Lighting
#   ./pi-mode.sh status
# Các container khác của Lighting (broker, ui, state, policy…) vẫn chạy, không đụng tới.
set -euo pipefail
MODE="${1:-status}"
# Container vision của docker compose (project "oi" → oi-vision-1). Ghi đè bằng biến nếu khác tên.
LIGHTING_CONTAINERS="${LIGHTING_CONTAINERS:-$(docker ps -a --filter label=com.docker.compose.service=vision --format '{{.Names}}' 2>/dev/null || true)}"
# systemd unit khác (ngoài pi-vision) có giữ camera, ví dụ LIGHTING_UNITS="oi-vision.service"
LIGHTING_UNITS="${LIGHTING_UNITS:-$(systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -i vision | grep -v '^pi-vision' || true)}"

show() {
  echo "pi-vision (parking): $(systemctl is-active pi-vision 2>/dev/null || true) / $(systemctl is-enabled pi-vision 2>/dev/null || true)"
  for c in $LIGHTING_CONTAINERS; do echo "container $c (lighting): $(docker inspect -f '{{.State.Status}}' "$c")"; done
  for u in $LIGHTING_UNITS; do echo "unit $u (lighting): $(systemctl is-active "$u" || true)"; done
  echo "Tiến trình đang mở camera:"; (sudo fuser -v /dev/media* /dev/video* 2>&1 | grep -v "^ *USER" || echo "  (không có)")
}

case "$MODE" in
  parking)
    for c in $LIGHTING_CONTAINERS; do echo "→ docker stop $c"; docker stop "$c" >/dev/null; done  # unless-stopped: không tự bật lại khi reboot
    for u in $LIGHTING_UNITS; do echo "→ disable $u"; sudo systemctl disable --now "$u"; done
    sleep 2
    sudo systemctl enable --now pi-vision
    echo "✅ Camera thuộc Smart Parking. Log: journalctl -u pi-vision -f"
    ;;
  lighting)
    sudo systemctl disable --now pi-vision || true
    sleep 2
    for u in $LIGHTING_UNITS; do echo "→ enable $u"; sudo systemctl enable --now "$u"; done
    for c in $LIGHTING_CONTAINERS; do echo "→ docker start $c"; docker start "$c" >/dev/null; done
    echo "✅ Camera trả lại Smart Lighting"
    ;;
  status) ;;
  *) echo "Cách dùng: $0 parking|lighting|status"; exit 1 ;;
esac
show
