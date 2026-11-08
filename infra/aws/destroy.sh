#!/usr/bin/env bash
# Xóa toàn bộ tài nguyên AWS của dự án sau khi bảo vệ xong (tránh phát sinh chi phí).
source "$(dirname "$0")/common.sh"
read -rp "Xóa stack $STACK_NAME, 3 IoT Thing/cert và bucket web tại $AWS_REGION? Gõ 'xoa' để xác nhận: " ok
[ "$ok" = "xoa" ] || { echo "Đã hủy"; exit 1; }
BUCKET="$(stack_output WebBucketName 2>/dev/null || true)"
[ -n "$BUCKET" ] && [ "$BUCKET" != "None" ] && aws s3 rm "s3://$BUCKET" --recursive
aws cloudformation delete-stack --stack-name "$STACK_NAME"
echo "→ Đang xóa stack (CloudFront có thể mất ~10 phút)…"
aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"
for DEV in pi-01 gate-01 slots-01; do
  for CERT_ARN in $(aws iot list-thing-principals --thing-name "$DEV" --query principals --output text 2>/dev/null); do
    CERT_ID="${CERT_ARN##*/}"
    aws iot detach-thing-principal --thing-name "$DEV" --principal "$CERT_ARN"
    aws iot detach-policy --policy-name "smart-parking-$DEV" --target "$CERT_ARN" || true
    aws iot update-certificate --certificate-id "$CERT_ID" --new-status INACTIVE
    aws iot delete-certificate --certificate-id "$CERT_ID"
  done
  aws iot delete-thing --thing-name "$DEV" || true
  for v in $(aws iot list-policy-versions --policy-name "smart-parking-$DEV" \
               --query 'policyVersions[?isDefaultVersion==`false`].versionId' --output text 2>/dev/null); do
    aws iot delete-policy-version --policy-name "smart-parking-$DEV" --policy-version-id "$v"
  done
  aws iot delete-policy --policy-name "smart-parking-$DEV" || true
done
rm -rf "$SECRETS_DIR/certs"
echo "✅ Đã xóa. Bucket artifacts smart-parking-artifacts-$ACCOUNT_ID-$AWS_REGION giữ lại (xóa tay nếu muốn)."
