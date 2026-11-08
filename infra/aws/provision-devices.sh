#!/usr/bin/env bash
# Tạo 3 IoT Thing + certificate + policy riêng (pi-01, gate-01, slots-01) và sinh file cấu hình:
#   secrets/certs/<device>/{cert.pem,private.key}, secrets/certs/AmazonRootCA1.pem, secrets/iot.json
#   edge/raspberry-pi-vision/config.local.toml           (Pi dùng)
#   firmware/esp32-*/include/secrets.h                   (nạp ESP32 ngày mai)
# Chạy lại an toàn: thiết bị đã có cert thì giữ nguyên, chỉ cập nhật policy và file cấu hình.
#   WIFI_SSID=... WIFI_PASS=... ./provision-devices.sh   # điền sẵn Wi-Fi cho ESP32
source "$(dirname "$0")/common.sh"
CERTS="$SECRETS_DIR/certs"
mkdir -p "$CERTS"
ARN="arn:aws:iot:$AWS_REGION:$ACCOUNT_ID"
T="parking/v1/site-01"
ENDPOINT="$(iot_endpoint)"

[ -f "$CERTS/AmazonRootCA1.pem" ] || curl -fsSL -o "$CERTS/AmazonRootCA1.pem" https://www.amazontrust.com/repository/AmazonRootCA1.pem

policy_doc() {  # quyền tối thiểu theo docs/mqtt-contract.md
  case "$1" in
    pi-01) cat <<JSON
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":"iot:Connect","Resource":"$ARN:client/pi-01"},
 {"Effect":"Allow","Action":"iot:Publish","Resource":["$ARN:topic/$T/vision/pi-01/events","$ARN:topic/$T/devices/pi-01/status"]}]}
JSON
    ;;
    gate-01) cat <<JSON
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":"iot:Connect","Resource":"$ARN:client/gate-01"},
 {"Effect":"Allow","Action":"iot:Subscribe","Resource":["$ARN:topicfilter/$T/gates/gate-01/commands","$ARN:topicfilter/$T/displays/gate-01/commands"]},
 {"Effect":"Allow","Action":"iot:Receive","Resource":["$ARN:topic/$T/gates/gate-01/commands","$ARN:topic/$T/displays/gate-01/commands"]},
 {"Effect":"Allow","Action":"iot:Publish","Resource":["$ARN:topic/$T/gates/gate-01/telemetry","$ARN:topic/$T/displays/gate-01/telemetry","$ARN:topic/$T/devices/gate-01/status"]}]}
JSON
    ;;
    slots-01) cat <<JSON
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":"iot:Connect","Resource":"$ARN:client/slots-01"},
 {"Effect":"Allow","Action":"iot:Publish","Resource":["$ARN:topic/$T/slots/slots-01/state","$ARN:topic/$T/devices/slots-01/status"]}]}
JSON
    ;;
  esac
}

for DEV in pi-01 gate-01 slots-01; do
  echo "→ $DEV"
  DIR="$CERTS/$DEV"; mkdir -p "$DIR"
  aws iot describe-thing --thing-name "$DEV" >/dev/null 2>&1 || aws iot create-thing --thing-name "$DEV" >/dev/null

  POLICY="smart-parking-$DEV"
  DOC="$(policy_doc "$DEV")"
  if aws iot get-policy --policy-name "$POLICY" >/dev/null 2>&1; then
    # Giữ tối đa 5 phiên bản: xóa bản cũ không phải mặc định trước khi thêm bản mới.
    for v in $(aws iot list-policy-versions --policy-name "$POLICY" \
                 --query 'policyVersions[?isDefaultVersion==`false`].versionId' --output text); do
      aws iot delete-policy-version --policy-name "$POLICY" --policy-version-id "$v"
    done
    aws iot create-policy-version --policy-name "$POLICY" --policy-document "$DOC" --set-as-default >/dev/null
  else
    aws iot create-policy --policy-name "$POLICY" --policy-document "$DOC" >/dev/null
  fi

  if [ ! -f "$DIR/cert.pem" ]; then
    CERT_ARN="$(aws iot create-keys-and-certificate --set-as-active \
      --certificate-pem-outfile "$DIR/cert.pem" --private-key-outfile "$DIR/private.key" \
      --query certificateArn --output text)"
    echo "$CERT_ARN" > "$DIR/cert.arn"
    aws iot attach-policy --policy-name "$POLICY" --target "$CERT_ARN"
    aws iot attach-thing-principal --thing-name "$DEV" --principal "$CERT_ARN"
    chmod 600 "$DIR/private.key"
    echo "  ✓ tạo certificate mới"
  else
    echo "  ✓ giữ certificate cũ"
  fi
done

cat > "$SECRETS_DIR/iot.json" <<JSON
{"endpoint": "$ENDPOINT", "region": "$AWS_REGION", "certs_dir": "$CERTS"}
JSON

# ── Pi: ghi đè [mqtt] của config.toml; cert chép vào /etc/parking/certs trên Pi ──
cat > "$REPO_ROOT/edge/raspberry-pi-vision/config.local.toml" <<TOML
# Sinh bởi infra/aws/provision-devices.sh — không commit. Ghi đè config.toml.
[mqtt]
enabled = true
host = "$ENDPOINT"
port = ${IOT_PORT:-8883}   # 443 nếu mạng chặn 8883
tls = true
ca_cert = "/etc/parking/certs/AmazonRootCA1.pem"
cert = "/etc/parking/certs/pi-01.cert.pem"
key = "/etc/parking/certs/pi-01.private.key"
TOML

# ── ESP32: include/secrets.h ──
write_secrets_h() {  # write_secrets_h DEVICE PROJECT_DIR
  local dev="$1" out="$REPO_ROOT/firmware/$2/include/secrets.h"
  mkdir -p "$(dirname "$out")"
  cat > "$out" <<H
// Sinh bởi infra/aws/provision-devices.sh — KHÔNG commit (đã có trong .gitignore).
#pragma once

#define WIFI_SSID "${WIFI_SSID:-DIEN_TEN_WIFI}"
#define WIFI_PASS "${WIFI_PASS:-DIEN_MAT_KHAU_WIFI}"

#define AWS_IOT_ENDPOINT "$ENDPOINT"
#define AWS_IOT_PORT ${IOT_PORT:-8883}   // 443 nếu mạng chặn 8883
#define DEVICE_ID "$dev"

static const char AWS_ROOT_CA[] PROGMEM = R"PEM(
$(cat "$CERTS/AmazonRootCA1.pem")
)PEM";

static const char DEVICE_CERT[] PROGMEM = R"PEM(
$(cat "$CERTS/$dev/cert.pem")
)PEM";

static const char DEVICE_KEY[] PROGMEM = R"PEM(
$(cat "$CERTS/$dev/private.key")
)PEM";
H
  chmod 600 "$out"
}
write_secrets_h gate-01 esp32-gates
write_secrets_h slots-01 esp32-slot-sensors

cat <<MSG

✅ Đã cấp 3 thiết bị. Endpoint: $ENDPOINT
   Cert:            $CERTS/<device>/
   Pi config:       edge/raspberry-pi-vision/config.local.toml
   ESP32 secrets.h: firmware/esp32-gates/include, firmware/esp32-slot-sensors/include
   (sửa WIFI_SSID/WIFI_PASS trong secrets.h trước khi nạp, hoặc chạy lại với biến WIFI_SSID/WIFI_PASS)

Chép cert sang Pi:
   ./copy-pi-certs.sh <user>@<ip-pi>
MSG
