# Biến dùng chung cho các script trong infra/aws. `source` file này, không chạy trực tiếp.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SECRETS_DIR="$REPO_ROOT/secrets"          # đã có trong .gitignore — KHÔNG commit
CONFIG_FILE="$SECRETS_DIR/deploy.env"
mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"

# Giá trị lưu từ lần chạy trước (region, email, khóa HMAC...)
# shellcheck disable=SC1090
[ -f "$CONFIG_FILE" ] && source "$CONFIG_FILE"

export AWS_REGION="${AWS_REGION:-ap-southeast-1}"
export AWS_DEFAULT_REGION="$AWS_REGION"
STAGE="${STAGE:-dev}"
STACK_NAME="smart-parking-$STAGE"

command -v aws >/dev/null || { echo "Chưa cài AWS CLI v2: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"; exit 1; }
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)" || {
  echo "AWS CLI chưa đăng nhập. Chạy: aws configure   (hoặc aws configure sso)"; exit 1; }

save_config() {  # save_config KEY VALUE — ghi/ghi đè một dòng trong secrets/deploy.env
  local key="$1" value="$2"
  touch "$CONFIG_FILE" && chmod 600 "$CONFIG_FILE"
  grep -v "^$key=" "$CONFIG_FILE" > "$CONFIG_FILE.tmp" || true
  printf '%s=%q\n' "$key" "$value" >> "$CONFIG_FILE.tmp"
  mv "$CONFIG_FILE.tmp" "$CONFIG_FILE"
}

stack_output() {  # stack_output OutputKey
  aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

iot_endpoint() {
  aws iot describe-endpoint --endpoint-type iot:Data-ATS --query endpointAddress --output text
}
