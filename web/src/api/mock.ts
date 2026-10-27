// API giả trong bộ nhớ để làm web khi backend chưa xong. Hành vi bám docs/api-contract.md.
// Token thử: /s/demo (bình thường), /s/demo-f2 (tầng 2), /s/sent (đã gửi email), /s/expired (410).
import { ApiError, type Api, type Claim, type Slot } from "./types";

const SLOT_IDS = ["F1", "F2"].flatMap((f) => ["A", "B", "C"].flatMap((r) => [1, 2, 3].map((c) => `${f}-${r}${c}`)));

export function routeSteps(slotId: string): string[] {
  const [, floor, row, col] = slotId.match(/^F(\d)-([A-C])(\d)$/) ?? [];
  return [floor === "1" ? "Tầng 1" : `Lên ram tầng ${floor}`, `Đi đến hàng ${row}`, `Ô số ${col}`];
}

const now = () => new Date().toISOString();
const inMinutes = (m: number) => new Date(Date.now() + m * 60_000).toISOString();

const slots: Slot[] = SLOT_IDS.map((slot_id, i) => ({
  slot_id,
  source: slot_id === "F1-A1" ? "SENSOR" : "BUTTON",
  status: i === 0 ? "RESERVED" : i % 4 === 1 ? "OCCUPIED" : "AVAILABLE",
  updated_at: now(),
}));

const claims: Record<string, Claim> = {
  demo: { session_ref: "A7K2", slot_id: "F1-A1", route_steps: routeSteps("F1-A1"), claim_expires_at: inMinutes(15), email_submitted: false },
  "demo-f2": { session_ref: "B3Q9", slot_id: "F2-C3", route_steps: routeSteps("F2-C3"), claim_expires_at: inMinutes(15), email_submitted: false },
  sent: { session_ref: "C5M1", slot_id: "F1-B2", route_steps: routeSteps("F1-B2"), claim_expires_at: inMinutes(10), email_submitted: true },
};

const usedKeys = new Set<string>();
const delay = <T>(value: T) => new Promise<T>((r) => setTimeout(() => r(value), 300));

function findClaim(token: string): Claim {
  if (token === "expired") throw new ApiError(410, "TOKEN_EXPIRED", "Mã QR đã hết hạn");
  const claim = claims[token];
  if (!claim) throw new ApiError(404, "NOT_FOUND", "Không tìm thấy phiên");
  return claim;
}

export const mockApi: Api = {
  getLayout: () => delay({ slots: structuredClone(slots) }),

  getClaim: async (token) => delay(structuredClone(findClaim(token))),

  submitClaimEmail: async (token, email, consent, idempotencyKey) => {
    await delay(null);
    const claim = findClaim(token);
    if (usedKeys.has(idempotencyKey)) return { email_status: "QUEUED" };
    if (!consent || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      throw new ApiError(400, "INVALID_INPUT", "Email hoặc xác nhận đồng ý không hợp lệ");
    }
    if (claim.email_submitted) throw new ApiError(409, "EMAIL_ALREADY_SENT", "Phiên này đã gửi email");
    usedKeys.add(idempotencyKey);
    claim.email_submitted = true;
    return { email_status: "QUEUED" };
  },

  getActiveClaims: () =>
    delay(
      Object.entries(claims).map(([token, c]) => ({
        session_ref: c.session_ref,
        slot_id: c.slot_id,
        claim_url: `${location.origin}/s/${token}`,
        claim_expires_at: c.claim_expires_at,
      })),
    ),

  getDashboard: () =>
    delay({
      available: slots.filter((s) => s.status === "AVAILABLE").length,
      reserved: slots.filter((s) => s.status === "RESERVED").length,
      occupied: slots.filter((s) => s.status === "OCCUPIED").length,
      unknown: slots.filter((s) => s.status === "UNKNOWN").length,
      offline_devices: [],
      alerts: [],
    }),
};
