#!/usr/bin/env bash
# Build web/ với URL API và Cognito lấy từ output stack, rồi đưa lên S3 + CloudFront.
#
#   infra/aws/scripts/deploy-web.sh           # chỉ in lệnh sẽ chạy
#   infra/aws/scripts/deploy-web.sh --apply   # chạy thật (cần AWS_PROFILE đã đăng nhập)
#
# File có hash trong tên (assets/) cache lâu; index.html không cache để bản mới có hiệu lực ngay.
set -euo pipefail

STACK="${STACK:-smart-parking-dev}"
REGION="${AWS_REGION:-ap-southeast-2}"
APPLY=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    *) echo "Tham số không hợp lệ: $arg" >&2; exit 2 ;;
  esac
done

ROOT="$(git rev-parse --show-toplevel)"

run() {
  if ((APPLY)); then
    "$@"
  else
    printf '+'
    printf ' %q' "$@"
    printf '\n'
  fi
}

output() {
  if ((APPLY)); then
    aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
      --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
  else
    echo "<$1>"
  fi
}

((APPLY)) || echo "# Chế độ xem trước: thêm --apply để chạy thật. Stack $STACK, region $REGION."

api_url="$(output ApiUrl)"
bucket="$(output WebBucketName)"
distribution="$(output WebDistributionId)"

run npm --prefix "$ROOT/web" ci
run env VITE_API_BASE_URL="$api_url" \
  VITE_COGNITO_USER_POOL_ID="$(output UserPoolId)" \
  VITE_COGNITO_CLIENT_ID="$(output UserPoolClientId)" \
  npm --prefix "$ROOT/web" run build
run aws s3 sync "$ROOT/web/dist" "s3://$bucket" --delete --region "$REGION" \
  --exclude index.html --cache-control "public,max-age=31536000,immutable"
run aws s3 cp "$ROOT/web/dist/index.html" "s3://$bucket/index.html" --region "$REGION" \
  --cache-control "no-cache"
run aws cloudfront create-invalidation --distribution-id "$distribution" --paths /index.html

((APPLY)) && echo "Xong: $(output WebUrl)"
exit 0
