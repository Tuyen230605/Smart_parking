import { getAccessToken } from "../auth";
import { ApiError, type Api, type ErrorCode } from "./types";

// API Gateway tự trả lỗi không có `code` (401 hết hạn token, 429 throttle, 5xx). Không gán chúng thành
// INVALID_INPUT, nếu không trang sẽ báo sai và tạo Idempotency-Key mới khi đáng ra phải thử lại cùng key.
function fallbackCode(status: number): ErrorCode {
  if (status === 401) return "UNAUTHENTICATED";
  if (status === 403) return "FORBIDDEN";
  if (status === 404) return "NOT_FOUND";
  if (status === 429) return "RATE_LIMITED";
  if (status >= 500) return "INTERNAL_ERROR";
  return "INVALID_INPUT";
}

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
    throw new ApiError(res.status, (body.code as ErrorCode) ?? fallbackCode(res.status), body.message ?? res.statusText);
  }
  return body as T;
}

function mutation(method: string, idempotencyKey: string, body?: unknown): RequestInit {
  return {
    method,
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(body ?? {}),
  };
}

export function createHttpApi(base: string): Api {
  const session = (id: string) => `/admin/sessions/${encodeURIComponent(id)}`;
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
    listSessions: ({ status, limit, cursor }) => {
      const query = new URLSearchParams();
      if (status) query.set("status", status);
      if (limit) query.set("limit", String(limit));
      if (cursor) query.set("cursor", cursor);
      return request(base, `/admin/sessions?${query}`, {}, true);
    },
    getSession: (id) => request(base, session(id), {}, true),
    resolvePlate: (id, input, key) => request(base, `${session(id)}/resolve-plate`, mutation("POST", key, input), true),
    renewClaim: (id, reason, key) => request(base, `${session(id)}/renew-claim`, mutation("POST", key, { reason }), true),
    recordPayment: (id, input, key) => request(base, `${session(id)}/payment`, mutation("POST", key, input), true),
    openExit: (id, reason, key) => request(base, `${session(id)}/open-exit`, mutation("POST", key, { reason }), true),
    confirmPassage: (id, reason, key) =>
      request(base, `${session(id)}/confirm-passage`, mutation("POST", key, { reason }), true),
    getDevices: () => request(base, "/admin/devices", {}, true),
    getPricing: () => request(base, "/admin/pricing", {}, true),
    updatePricing: (rules, key) => request(base, "/admin/pricing", mutation("PUT", key, rules), true),
  };
}
