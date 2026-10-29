// Người 4: đăng nhập Cognito cho trang quản trị và kiosk, không cần thư viện. Gọi thẳng API công khai của
// Cognito (InitiateAuth USER_PASSWORD_AUTH qua HTTPS) với app client không có secret (infra/aws/template.yaml).
// Bỏ trống VITE_COGNITO_* khi chạy API giả hoặc backend local: đăng nhập tắt, getAccessToken() trả null.
//
// Access token chỉ giữ trong bộ nhớ; refresh token lưu localStorage để kiosk mở lại trang không phải đăng nhập.
// Nhóm trong token chỉ để ẩn/hiện giao diện; backend mới là nơi kiểm quyền.

const POOL_ID = import.meta.env.VITE_COGNITO_USER_POOL_ID as string | undefined;
const CLIENT_ID = import.meta.env.VITE_COGNITO_CLIENT_ID as string | undefined;
export const authEnabled = Boolean(POOL_ID && CLIENT_ID);
const ENDPOINT = `https://cognito-idp.${POOL_ID?.split("_")[0]}.amazonaws.com/`;
const REFRESH_KEY = "smart-parking.refresh-token";
const REFRESH_MARGIN_MS = 60_000;

export interface AuthUser {
  username: string;
  groups: string[];
}

export type SignInResult = { status: "SIGNED_IN" } | { status: "NEW_PASSWORD_REQUIRED"; session: string };

export class AuthError extends Error {
  constructor(public code: string, message: string) {
    super(message);
  }
}

const MESSAGES: Record<string, string> = {
  NotAuthorizedException: "Sai email hoặc mật khẩu.",
  UserNotFoundException: "Sai email hoặc mật khẩu.",
  PasswordResetRequiredException: "Tài khoản cần đặt lại mật khẩu, liên hệ quản trị nhóm.",
  InvalidPasswordException: "Mật khẩu mới chưa đạt: ít nhất 12 ký tự, có chữ thường và chữ số.",
  TooManyRequestsException: "Thử quá nhiều lần, đợi một lúc rồi thử lại.",
  LimitExceededException: "Thử quá nhiều lần, đợi một lúc rồi thử lại.",
  NETWORK_ERROR: "Không kết nối được Cognito. Kiểm tra mạng rồi thử lại.",
};

let accessToken: { value: string; expiresAt: number } | null = null;
let user: AuthUser | null = null;
let refreshing: Promise<boolean> | null = null;
const listeners = new Set<() => void>();

function storage(action: (s: Storage) => string | null | void): string | null {
  try {
    return action(localStorage) ?? null;
  } catch {
    return null; // trình duyệt chặn localStorage: vẫn đăng nhập được, chỉ không nhớ qua lần tải lại
  }
}

async function cognito<T>(target: string, body: object): Promise<T> {
  let res: Response;
  try {
    res = await fetch(ENDPOINT, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": `AWSCognitoIdentityProviderService.${target}`,
      },
      body: JSON.stringify({ ClientId: CLIENT_ID, ...body }),
    });
  } catch {
    throw new AuthError("NETWORK_ERROR", MESSAGES.NETWORK_ERROR);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const code = String(data.__type ?? "UNKNOWN").split("#").pop() ?? "UNKNOWN";
    throw new AuthError(code, MESSAGES[code] ?? data.message ?? "Đăng nhập thất bại.");
  }
  return data as T;
}

interface AuthResult {
  AccessToken: string;
  ExpiresIn: number;
  RefreshToken?: string;
}

interface InitiateAuthResponse {
  AuthenticationResult?: AuthResult;
  ChallengeName?: string;
  Session?: string;
}

function decodeClaims(token: string): Record<string, unknown> {
  const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
  const json = decodeURIComponent(
    Array.from(atob(part.padEnd(part.length + ((4 - (part.length % 4)) % 4), "=")))
      .map((c) => `%${c.charCodeAt(0).toString(16).padStart(2, "0")}`)
      .join(""),
  );
  return JSON.parse(json);
}

function accept(result: AuthResult) {
  const claims = decodeClaims(result.AccessToken);
  accessToken = { value: result.AccessToken, expiresAt: Date.now() + result.ExpiresIn * 1000 };
  user = {
    username: String(claims.username ?? claims["cognito:username"] ?? ""),
    groups: Array.isArray(claims["cognito:groups"]) ? (claims["cognito:groups"] as string[]) : [],
  };
  if (result.RefreshToken) storage((s) => s.setItem(REFRESH_KEY, result.RefreshToken!));
  listeners.forEach((fn) => fn());
}

export async function signIn(username: string, password: string): Promise<SignInResult> {
  const data = await cognito<InitiateAuthResponse>("InitiateAuth", {
    AuthFlow: "USER_PASSWORD_AUTH",
    AuthParameters: { USERNAME: username, PASSWORD: password },
  });
  // Tài khoản do quản trị tạo bằng admin-create-user phải đổi mật khẩu tạm ở lần đầu.
  if (data.ChallengeName === "NEW_PASSWORD_REQUIRED" && data.Session) {
    return { status: "NEW_PASSWORD_REQUIRED", session: data.Session };
  }
  if (!data.AuthenticationResult) {
    throw new AuthError(data.ChallengeName ?? "UNKNOWN", `Cognito yêu cầu bước ${data.ChallengeName} chưa được hỗ trợ.`);
  }
  accept(data.AuthenticationResult);
  return { status: "SIGNED_IN" };
}

export async function completeNewPassword(username: string, newPassword: string, session: string): Promise<void> {
  const data = await cognito<InitiateAuthResponse>("RespondToAuthChallenge", {
    ChallengeName: "NEW_PASSWORD_REQUIRED",
    Session: session,
    ChallengeResponses: { USERNAME: username, NEW_PASSWORD: newPassword },
  });
  if (!data.AuthenticationResult) throw new AuthError("UNKNOWN", "Không đổi được mật khẩu, thử đăng nhập lại.");
  accept(data.AuthenticationResult);
}

/** Lấy access token mới bằng refresh token. Chỉ đăng xuất khi Cognito từ chối token, không đăng xuất vì mất mạng. */
function refresh(): Promise<boolean> {
  const token = storage((s) => s.getItem(REFRESH_KEY));
  if (!authEnabled || !token) return Promise.resolve(false);
  refreshing ??= cognito<InitiateAuthResponse>("InitiateAuth", {
    AuthFlow: "REFRESH_TOKEN_AUTH",
    AuthParameters: { REFRESH_TOKEN: token },
  })
    .then((data) => {
      if (!data.AuthenticationResult) return false;
      accept(data.AuthenticationResult);
      return true;
    })
    .catch((e) => {
      if (e instanceof AuthError && e.code === "NotAuthorizedException") signOut();
      return false;
    })
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export async function getAccessToken(): Promise<string | null> {
  if (!authEnabled) return null;
  if (accessToken && accessToken.expiresAt - Date.now() > REFRESH_MARGIN_MS) return accessToken.value;
  return (await refresh()) && accessToken ? accessToken.value : null;
}

/** Gọi khi tải trang: dùng refresh token còn lưu để không phải đăng nhập lại. */
export async function restoreSession(): Promise<boolean> {
  return user !== null || refresh();
}

export function signOut() {
  const token = storage((s) => s.getItem(REFRESH_KEY));
  storage((s) => s.removeItem(REFRESH_KEY));
  accessToken = null;
  user = null;
  listeners.forEach((fn) => fn());
  // Thu hồi refresh token phía Cognito; lỗi mạng thì bỏ qua vì token đã xóa khỏi máy này.
  if (authEnabled && token) cognito("RevokeToken", { Token: token }).catch(() => undefined);
}

export function currentUser(): AuthUser | null {
  return user;
}

export function onAuthChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
