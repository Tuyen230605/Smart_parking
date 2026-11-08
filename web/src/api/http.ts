import { getAccessToken, handleUnauthorized } from "../auth";
import { ApiError, type Api, type ErrorCode } from "./types";

async function request<T>(base: string, path: string, init: RequestInit = {}, auth = false): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (auth) {
    const token = await getAccessToken();
    if (!token) throw new ApiError(401, "UNAUTHENTICATED", "Cần đăng nhập");
    headers.set("Authorization", `Bearer ${token}`);
  }
  let res: Response;
  try {
    res = await fetch(`${base}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "Không kết nối được máy chủ");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (auth && res.status === 401) handleUnauthorized();
    // API Gateway trả {"message":"Unauthorized"} khi JWT hỏng, không có `code`.
    const code = (body.code as ErrorCode) ?? (res.status === 401 ? "UNAUTHENTICATED" : res.status === 403 ? "FORBIDDEN" : "INVALID_INPUT");
    throw new ApiError(res.status, code, body.message ?? res.statusText);
  }
  return body as T;
}

const post = (body: unknown = {}): RequestInit => ({
  method: "POST",
  headers: { "Idempotency-Key": crypto.randomUUID() },
  body: JSON.stringify(body),
});

export function createHttpApi(base: string): Api {
  const admin = <T>(path: string, init?: RequestInit) => request<T>(base, `/admin${path}`, init, true);
  const sessionAction = <T>(id: string, action: string, body: unknown = {}) =>
    admin<T>(`/sessions/${encodeURIComponent(id)}/${action}`, post(body));

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
    getDashboard: () => admin("/dashboard"),
    listSessions: (status) => admin(`/sessions?limit=100${status ? `&status=${encodeURIComponent(status)}` : ""}`),
    resolvePlate: (id, action, plate_text, reason) => sessionAction(id, "resolve-plate", { action, plate_text, reason }),
    renewClaim: (id) => sessionAction(id, "renew-claim"),
    recordPayment: (id, payment_status, amount_vnd, note) => sessionAction(id, "payment", { payment_status, amount_vnd, note }),
    openExit: (id) => sessionAction(id, "open-exit"),
    confirmPassage: (id) => sessionAction(id, "confirm-passage"),
    getDevices: () => admin("/devices"),
    getPricing: () => admin("/pricing"),
    putPricing: (p) => admin("/pricing", { method: "PUT", body: JSON.stringify(p) }),
    gateCommand: (gate, action) => admin(`/gates/${gate}/command`, post({ action })),
    ackAlert: async (id) => {
      await admin(`/alerts/${encodeURIComponent(id)}/ack`, post());
    },
  };
}
