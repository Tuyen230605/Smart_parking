#!/usr/bin/env bash
# Dựng/cập nhật toàn bộ backend AWS bằng CloudFormation (chỉ cần AWS CLI v2).
#   ./deploy.sh                        # lần đầu sẽ hỏi email
#   AWS_REGION=ap-southeast-1 ./deploy.sh
# Chạy lại bao nhiêu lần cũng được: chỉ cập nhật phần thay đổi.
source "$(dirname "$0")/common.sh"
cd "$(dirname "$0")"

if [ -z "${SENDER_EMAIL:-}" ]; then
  read -rp "Email gửi chỉ dẫn cho khách (SES sẽ gửi thư xác minh): " SENDER_EMAIL
  save_config SENDER_EMAIL "$SENDER_EMAIL"
fi
if [ -z "${BUDGET_EMAIL+x}" ]; then
  read -rp "Email nhận cảnh báo chi phí [$SENDER_EMAIL]: " BUDGET_EMAIL
  BUDGET_EMAIL="${BUDGET_EMAIL:-$SENDER_EMAIL}"
  save_config BUDGET_EMAIL "$BUDGET_EMAIL"
fi
if [ -z "${CLAIM_HMAC_SECRET:-}" ]; then
  CLAIM_HMAC_SECRET="$(head -c 48 /dev/urandom | base64 | tr -d '/+=\n' | head -c 48)"
  save_config CLAIM_HMAC_SECRET "$CLAIM_HMAC_SECRET"
fi
save_config AWS_REGION "$AWS_REGION"
[ -n "${ENABLE_CDN:-}" ] && save_config ENABLE_CDN "$ENABLE_CDN"
[ -n "${WEB_BASE_URL_OVERRIDE+x}" ] && save_config WEB_BASE_URL_OVERRIDE "$WEB_BASE_URL_OVERRIDE"

ARTIFACT_BUCKET="smart-parking-artifacts-$ACCOUNT_ID-$AWS_REGION"
if ! aws s3api head-bucket --bucket "$ARTIFACT_BUCKET" 2>/dev/null; then
  echo "→ Tạo bucket chứa code Lambda: $ARTIFACT_BUCKET"
  if [ "$AWS_REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$ARTIFACT_BUCKET" >/dev/null
  else
    aws s3api create-bucket --bucket "$ARTIFACT_BUCKET" \
      --create-bucket-configuration LocationConstraint="$AWS_REGION" >/dev/null
  fi
  aws s3api put-public-access-block --bucket "$ARTIFACT_BUCKET" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
fi

IOT_ENDPOINT="$(iot_endpoint)"
echo "→ IoT endpoint: $IOT_ENDPOINT"

echo "→ Đóng gói Lambda"
aws cloudformation package --template-file template.yaml --s3-bucket "$ARTIFACT_BUCKET" \
  --s3-prefix "$STACK_NAME" --output-template-file "$SECRETS_DIR/packaged.yaml" >/dev/null

echo "→ Deploy stack $STACK_NAME tại $AWS_REGION (lần đầu ~5–10 phút vì CloudFront)"
aws cloudformation deploy --stack-name "$STACK_NAME" --template-file "$SECRETS_DIR/packaged.yaml" \
  --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND --no-fail-on-empty-changeset \
  --parameter-overrides \
    Stage="$STAGE" IotEndpoint="$IOT_ENDPOINT" ClaimHmacSecret="$CLAIM_HMAC_SECRET" \
    SenderEmail="$SENDER_EMAIL" BudgetEmail="${BUDGET_EMAIL:-}" \
    WebBaseUrlOverride="${WEB_BASE_URL_OVERRIDE:-}" EnableCdn="${ENABLE_CDN:-true}"

echo "→ Seed 18 ô + bảng giá"
aws lambda invoke --function-name "$(stack_output JobsFunctionName)" \
  --cli-binary-format raw-in-base64-out --payload '{"job":"seed"}' "$SECRETS_DIR/seed-out.json" >/dev/null
cat "$SECRETS_DIR/seed-out.json"; echo

API_URL="$(stack_output ApiUrl)"
WEB_URL="$(stack_output WebUrl)"
cat > "$REPO_ROOT/web/.env.production.local" <<ENV
VITE_API_BASE_URL=$API_URL
VITE_COGNITO_REGION=$AWS_REGION
VITE_COGNITO_CLIENT_ID=$(stack_output UserPoolClientId)
ENV
cp "$REPO_ROOT/web/.env.production.local" "$REPO_ROOT/web/.env.development.local"

cat <<MSG

✅ Backend đã deploy
   API : $API_URL
   Web : $WEB_URL   (chạy ./deploy-web.sh để đưa web lên)
   Đã ghi web/.env.production.local và web/.env.development.local

Việc tiếp theo:
   1. Mở hộp thư $SENDER_EMAIL và bấm link xác minh của Amazon SES.
   2. ./create-users.sh          # tài khoản admin + kiosk
   3. ./provision-devices.sh     # cert cho pi-01, gate-01, slots-01 (chạy 1 lần)
   4. ./deploy-web.sh
MSG
