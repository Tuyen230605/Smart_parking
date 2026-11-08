// API giả trong bộ nhớ để làm web khi backend chưa xong. Hành vi bám docs/api-contract.md.
// Token thử: /s/demo (bình thường), /s/demo-f2 (tầng 2), /s/sent (đã gửi email), /s/expired (410).
import { ApiError, type AdminSession, type Api, type Claim, type DeviceInfo, type Pricing, type Slot } from "./types";

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
      alerts: alerts.filter((a) => !ackedAlerts.has(a.alert_id)),
    }),

  listSessions: (status) =>
    delay({
      items: structuredClone(sessions.filter((s) => !status || (status === "OPEN" ? OPEN.includes(s.state) : s.state === status))),
      total: sessions.length,
    }),

  resolvePlate: async (id, action, plateText) => {
    const s = findSession(id);
    if (s.state !== "MANUAL_REVIEW") throw new ApiError(409, "INVALID_STATE", "Phiên không chờ duyệt");
    if (action === "REJECT") return update(s, { state: "REJECTED" });
    const slot = slots.find((x) => x.status === "AVAILABLE");
    if (!slot) throw new ApiError(409, "SLOT_CONFLICT", "Không còn ô trống");
    slot.status = "RESERVED";
    return update(s, { state: action === "ENTRY" ? "RESERVED" : "RESOLVED", plate_text: plateText, slot_id: slot.slot_id, checkin_at: now() });
  },

  renewClaim: async (id) => update(findSession(id), { claim_expires_at: inMinutes(15) }),

  recordPayment: async (id, status, _amount, note) => {
    const s = findSession(id);
    if (s.payment_status !== "PENDING") throw new ApiError(409, "INVALID_STATE", "Không chờ thu tiền");
    return update(s, { payment_status: status, payment_note: note, state: "EXIT_OPENED", exit_opened_at: now() });
  },

  openExit: async (id) => update(findSession(id), { state: "EXIT_OPENED", exit_opened_at: now() }),

  confirmPassage: async (id) => {
    const s = findSession(id);
    if (s.state !== "EXIT_OPENED") throw new ApiError(409, "INVALID_STATE", "Cổng ra chưa mở");
    return update(s, { state: "CLOSED", exit_confirmed_at: now() });
  },

  getDevices: () => delay(structuredClone(devices)),

  getPricing: () => delay({ ...pricing }),

  putPricing: async (p) => {
    pricing = { ...pricing, ...p, version: pricing.version + 1, updated_at: now() };
    return delay({ ...pricing });
  },

  gateCommand: async (gate, action) => {
    const g = devices[1].gates![gate]!;
    g.state = action === "OPEN" ? "OPEN" : "CLOSED";
    g.at = now();
    return delay({ command_id: crypto.randomUUID() });
  },

  ackAlert: async (id) => {
    ackedAlerts.add(id);
    await delay(null);
  },
};

// ── dữ liệu giả cho trang quản trị ──────────────────────────────────────────
const OPEN = ["MANUAL_REVIEW", "RESERVED", "PARKED", "EXIT_REQUESTED", "EXIT_OPENED"];
const ago = (m: number) => new Date(Date.now() - m * 60_000).toISOString();

const sessions: AdminSession[] = [
  { session_id: "01MOCKREVIEW", session_ref: "R8T1", state: "MANUAL_REVIEW", plate_text: "51A-1Z345", plate_confidence: 0.42, email: null, review_lane: "ENTRY", review_reason: "LOW_CONFIDENCE", created_at: ago(1) },
  { session_id: "01MOCKRESERVED", session_ref: "A7K2", state: "RESERVED", slot_id: "F1-A1", plate_text: "51A-12345", email: null, created_at: ago(2), checkin_at: ago(2), fee_preview_vnd: 0, claim_url: `${location.origin}/s/demo`, claim_expires_at: inMinutes(13) },
  { session_id: "01MOCKPAY", session_ref: "P4Z9", state: "EXIT_REQUESTED", slot_id: "F1-B2", plate_text: "30F-67890", email: "khach@example.com", email_status: "ACCEPTED_BY_SES", created_at: ago(75), checkin_at: ago(75), exit_requested_at: ago(0), fee_vnd: 15000, payment_status: "PENDING" },
  { session_id: "01MOCKOPENED", session_ref: "Q2W3", state: "EXIT_OPENED", slot_id: "F2-A1", plate_text: "29H-55555", email: null, created_at: ago(9), checkin_at: ago(9), fee_vnd: 0, payment_status: "NO_CHARGE", exit_opened_at: ago(0) },
];

const alerts = [
  { alert_id: "a1", kind: "MANUAL_REVIEW", level: "WARN" as const, message: "Lượt R8T1 ở làn ENTRY cần duyệt: LOW_CONFIDENCE", created_at: ago(1), session_id: "01MOCKREVIEW" },
  { alert_id: "a2", kind: "PAYMENT_PENDING", level: "INFO" as const, message: "Lượt P4Z9 chờ thu 15.000 ₫", created_at: ago(0), session_id: "01MOCKPAY" },
];
const ackedAlerts = new Set<string>();

const devices: DeviceInfo[] = [
  { device_id: "pi-01", state: "ONLINE", last_seen_at: now(), firmware_version: "0.1.0" },
  { device_id: "gate-01", state: "ONLINE", last_seen_at: now(), firmware_version: "mock", gates: { ENTRY: { state: "CLOSED" }, EXIT: { state: "CLOSED" } } },
  { device_id: "slots-01", state: "ONLINE", last_seen_at: now(), firmware_version: "mock" },
];

let pricing: Pricing = { version: 1, free_minutes: 15, first_hour_vnd: 10000, next_hour_vnd: 5000 };

function findSession(id: string) {
  const s = sessions.find((x) => x.session_id === id);
  if (!s) throw new ApiError(404, "NOT_FOUND", "Không tìm thấy phiên");
  return s;
}

function update(s: AdminSession, patch: Partial<AdminSession>) {
  Object.assign(s, patch);
  return delay(structuredClone(s));
}
