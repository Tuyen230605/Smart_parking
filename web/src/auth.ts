// Đăng nhập Cognito bằng USER_PASSWORD_AUTH gọi thẳng REST của Cognito (không cần Amplify).
// Token lưu localStorage; tự làm mới bằng refresh token trước khi hết hạn.
// Khi chạy API giả (không có VITE_COGNITO_CLIENT_ID) thì coi như đã đăng nhập ADMIN.
import { useSyncExternalStore } from "react";

const REGION = import.meta.env.VITE_COGNITO_REGION as string | undefined;
const CLIENT_ID = import.meta.env.VITE_COGNITO_CLIENT_ID as string | undefined;
const KEY = "smart-parking.auth";

export const authEnabled = Boolean(REGION && CLIENT_ID);

export interface Session {
  username: string;
  groups: string[];
  accessToken: string;
  refreshToken: string;
  expiresAt: number; // ms epoch
}

const MOCK_SESSION: Session = { username: "mock-admin", groups: ["ADMIN", "KIOSK"], accessToken: "", refreshToken: "", expiresAt: Infinity };

let current: Session | null = authEnabled ? load() : MOCK_SESSION;
const listeners = new Set<() => void>();

function load(): Session | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

function save(s: Session | null) {
  current = s;
  try {
    if (s) localStorage.setItem(KEY, JSON.stringify(s));
    else localStorage.removeItem(KEY);
  } catch {
    /* trình duyệt chặn storage: vẫn dùng trong bộ nhớ */
  }
  listeners.forEach((l) => l());
}

function decode(jwt: string): Record<string, unknown> {
  const part = jwt.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
  return JSON.parse(decodeURIComponent(escape(atob(part))));
}

async function cognito(target: string, body: unknown) {
  const res = await fetch(`https://cognito-idp.${REGION}.amazonaws.com/`, {
    method: "POST",
    headers: { "Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": `AWSCognitoIdentityProviderService.${target}` },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const type = String(data.__type ?? "");
    if (type.includes("NotAuthorized") || type.includes("UserNotFound")) throw new Error("Sai tên đăng nhập hoặc mật khẩu");
    throw new Error(data.message ?? "Không đăng nhập được");
  }
  return data;
}

function fromResult(r: { AccessToken: string; RefreshToken?: string; ExpiresIn: number }, refreshToken?: string): Session {
  const claims = decode(r.AccessToken);
  return {
    username: String(claims.username ?? ""),
    groups: (claims["cognito:groups"] as string[] | undefined) ?? [],
    accessToken: r.AccessToken,
    refreshToken: r.RefreshToken ?? refreshToken ?? "",
    expiresAt: Date.now() + r.ExpiresIn * 1000,
  };
}

export async function login(username: string, password: string): Promise<Session> {
  const data = await cognito("InitiateAuth", {
    AuthFlow: "USER_PASSWORD_AUTH",
    ClientId: CLIENT_ID,
    AuthParameters: { USERNAME: username.trim(), PASSWORD: password },
  });
  if (!data.AuthenticationResult) {
    throw new Error(`Tài khoản cần bước bổ sung (${data.ChallengeName}); chạy lại infra/aws/create-users.sh`);
  }
  const s = fromResult(data.AuthenticationResult);
  save(s);
  return s;
}

export function logout() {
  if (authEnabled) save(null);
}

let refreshing: Promise<void> | null = null;

/** Token gửi kèm API kiosk/admin; null khi chưa đăng nhập hoặc chạy mock. */
export async function getAccessToken(): Promise<string | null> {
  if (!authEnabled || !current) return null;
  if (current.expiresAt - Date.now() < 60_000) {
    refreshing ??= cognito("InitiateAuth", {
      AuthFlow: "REFRESH_TOKEN_AUTH",
      ClientId: CLIENT_ID,
      AuthParameters: { REFRESH_TOKEN: current.refreshToken },
    })
      .then((d) => save(fromResult(d.AuthenticationResult, current?.refreshToken)))
      .catch(() => save(null))
      .finally(() => (refreshing = null));
    await refreshing;
  }
  return current?.accessToken ?? null;
}

/** API trả 401 → token hỏng/hết hạn: đăng xuất để hiện lại form. */
export function handleUnauthorized() {
  logout();
}

export function useAuth(): Session | null {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => current,
  );
}
