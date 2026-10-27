import { getAccessToken } from "../auth";
import { ApiError, type Api, type ErrorCode } from "./types";

async function request<T>(base: string, path: string, init: RequestInit = {}, auth = false): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (auth) {
    const token = await getAccessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }
  let res: Response;
  try {
    res = await fetch(`${base}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "Không kết nối được máy chủ");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(res.status, (body.code as ErrorCode) ?? "INVALID_INPUT", body.message ?? res.statusText);
  }
  return body as T;
}

export function createHttpApi(base: string): Api {
  return {
    getLayout: () => request(base, "/public/layout"),
    getClaim: (token) => request(base, `/public/claims/${encodeURIComponent(token)}`),
    submitClaimEmail: (token, email, consent, idempotencyKey) =>
      request(base, `/public/claims/${encodeURIComponent(token)}/email`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify({ email, consent_for_this_session: consent }),
      }),
    getActiveClaims: () => request(base, "/kiosk/active-claims", {}, true),
    getDashboard: () => request(base, "/admin/dashboard", {}, true),
  };
}
