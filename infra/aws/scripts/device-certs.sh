#!/usr/bin/env bash
# Tạo certificate cho pi-01, gate-01, slots-01 và gắn IoT policy/Thing do stack SAM tạo.
#
#   infra/aws/scripts/device-certs.sh                 # chỉ in lệnh sẽ chạy
#   infra/aws/scripts/device-certs.sh --apply         # tạo thật (cần AWS_PROFILE đã đăng nhập)
#   infra/aws/scripts/device-certs.sh --apply gate-01 # chỉ một thiết bị
#
# File ra ở secrets/devices/<thiết bị>/ (git bỏ qua). Gửi riêng cho từng người, không qua git/chat nhóm.
# Thiết bị đã có private key thì bỏ qua để không tạo certificate thừa.
set -euo pipefail

STAGE="${STAGE:-dev}"
REGION="${AWS_REGION:-ap-southeast-2}"
APPLY=0
DEVICES=()
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    pi-01 | gate-01 | slots-01) DEVICES+=("$arg") ;;
    *) echo "Tham số không hợp lệ: $arg" >&2; exit 2 ;;
  esac
done
[[ ${#DEVICES[@]} -gt 0 ]] || DEVICES=(pi-01 gate-01 slots-01)

OUT="$(git rev-parse --show-toplevel)/secrets/devices"

run() {
  if ((APPLY)); then
    "$@"
  else
    printf '+'
    printf ' %q' "$@"
    printf '\n'
  fi
}

((APPLY)) || echo "# Chế độ xem trước: thêm --apply để chạy thật. Region $REGION, stage $STAGE."

for device in "${DEVICES[@]}"; do
  dir="$OUT/$device"
  if [[ -e "$dir/$device.private.key" ]]; then
    echo "# Bỏ qua $device: đã có $dir/$device.private.key"
    continue
  fi
  run mkdir -p "$dir"
  run chmod 700 "$dir"
  if ((APPLY)); then
    arn="$(aws iot create-keys-and-certificate --set-as-active --region "$REGION" \
      --certificate-pem-outfile "$dir/$device.cert.pem" \
      --private-key-outfile "$dir/$device.private.key" \
      --query certificateArn --output text)"
    chmod 600 "$dir/$device.private.key"
  else
    run aws iot create-keys-and-certificate --set-as-active --region "$REGION" \
      --certificate-pem-outfile "$dir/$device.cert.pem" --private-key-outfile "$dir/$device.private.key" \
      --query certificateArn --output text
    arn="<certificateArn>"
  fi
  run aws iot attach-policy --region "$REGION" --policy-name "smart-parking-$STAGE-$device" --target "$arn"
  run aws iot attach-thing-principal --region "$REGION" --thing-name "$device" --principal "$arn"
done

run curl -fsSL -o "$OUT/AmazonRootCA1.pem" https://www.amazontrust.com/repository/AmazonRootCA1.pem
if ((APPLY)); then
  aws iot describe-endpoint --endpoint-type iot:Data-ATS --region "$REGION" \
    --query endpointAddress --output text >"$OUT/endpoint.txt"
  echo "Xong. Endpoint ATS: $(cat "$OUT/endpoint.txt"); file ở $OUT"
else
  run aws iot describe-endpoint --endpoint-type iot:Data-ATS --region "$REGION" --query endpointAddress --output text
fi
