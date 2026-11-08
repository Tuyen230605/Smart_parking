#!/usr/bin/env bash
# Build web app với cấu hình từ deploy.sh rồi đưa lên S3 + làm mới CloudFront.
source "$(dirname "$0")/common.sh"
cd "$REPO_ROOT/web"
[ -f .env.production.local ] || { echo "Chưa có web/.env.production.local — chạy ./deploy.sh trước"; exit 1; }
npm ci
npm run build
BUCKET="$(stack_output WebBucketName)"
# File có hash trong tên cache lâu; index.html luôn lấy bản mới.
aws s3 sync dist/ "s3://$BUCKET/" --delete --exclude index.html --cache-control "public,max-age=31536000,immutable"
aws s3 cp dist/index.html "s3://$BUCKET/index.html" --cache-control "no-cache"
aws cloudfront create-invalidation --distribution-id "$(stack_output DistributionId)" --paths "/*" >/dev/null
echo "✅ Web: $(stack_output WebUrl)   (CloudFront cần ~1–2 phút để cập nhật)"
