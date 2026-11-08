#!/usr/bin/env bash
# Tạo/đặt lại mật khẩu cho tài khoản quản trị và kiosk trong Cognito.
#   ./create-users.sh                      # hỏi mật khẩu
#   ./create-users.sh admin2 ADMIN         # thêm một người dùng khác
source "$(dirname "$0")/common.sh"
POOL="$(stack_output UserPoolId)"

create() {  # create USERNAME GROUP
  local user="$1" group="$2" pass
  read -rsp "Mật khẩu cho '$user' (≥8 ký tự, có số): " pass; echo
  aws cognito-idp admin-create-user --user-pool-id "$POOL" --username "$user" \
    --message-action SUPPRESS >/dev/null 2>&1 || echo "  ($user đã tồn tại — đặt lại mật khẩu)"
  aws cognito-idp admin-set-user-password --user-pool-id "$POOL" --username "$user" \
    --password "$pass" --permanent
  aws cognito-idp admin-add-user-to-group --user-pool-id "$POOL" --username "$user" --group-name "$group"
  echo "  ✓ $user ∈ $group"
}

if [ $# -ge 2 ]; then
  create "$1" "$2"
else
  create admin ADMIN
  create kiosk KIOSK
fi
