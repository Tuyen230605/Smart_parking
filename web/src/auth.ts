// Người 4: nối Cognito (Hosted UI hoặc Amplify Auth) ở đây. Trang kiosk/admin gọi API qua
// getAccessToken(); trả null khi chưa đăng nhập để API trả 401.
export async function getAccessToken(): Promise<string | null> {
  return null;
}
