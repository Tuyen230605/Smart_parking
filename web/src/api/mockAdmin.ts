// Phần quản trị của API giả. Bám quy tắc của backend (backend/src/parking/admin.py) ở mức đủ để làm giao diện:
// kiểm trạng thái, cùng Idempotency-Key thì trả kết quả cũ, mỗi thao tác thêm một mục audit.
import {
  ApiError,
  type Api,
  type AuditEntry,
  type DeviceView,
  type Pricing,
  type SessionDetail,
  type SessionState,
  type Slot,
} from "./types";

type AdminApi = Pick<
  Api,
  | "listSessions"
  | "getSession"
  | "resolvePlate"
  | "renewClaim"
  | "recordPayment"
  | "openExit"
  | "confirmPassage"
  | "getDevices"
  | "getPricing"
  | "updatePricing"
>;

const PAID = ["NO_CHARGE", "PAID_CASH", "WAIVED"];
const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

function session(id: string, ref: string, state: SessionState, minutesAgo: number, extra: Partial<SessionDetail>): SessionDetail {
  return {
    session_id: id,
    session_ref: ref,
    state,
    lane_id: "ENTRY",
    slot_id: null,
    review_reason: null,
    created_at: ago(minutesAgo),
    checkin_at: ago(minutesAgo),
    parked_at: null,
    charge_end_at: null,
    exit_confirmed_at: null,
    fee_vnd: null,
    payment_status: null,
    email_status: null,
    plate_confidence: 0.93,
    plate_normalized: null,
    card_color: "GREEN",
    related_session_id: null,
    resolution: null,
    resolved_session_id: null,
    resolved_from_session_id: null,
    claim_expires_at: null,
    entry_command_id: null,
    exit_command_id: null,
    entry_gate_opened_at: null,
    exit_gate_opened_at: null,
    gate_error: null,
    paid_amount_vnd: null,
    payment_note: null,
    paid_at: null,
    closed_at: null,
    updated_at: ago(minutesAgo),
    plate_text: null,
    email: null,
    audit: [],
    ...extra,
  };
}

export function createMockAdmin(slots: Slot[], routeSteps: (slotId: string) => string[]): AdminApi {
  const sessions: SessionDetail[] = [
    session("01MOCK00000000000000000006", "R6QX", "MANUAL_REVIEW", 1, {
      review_reason: "LOW_CONFIDENCE", plate_text: "51A-1Z345", plate_confidence: 0.42, checkin_at: null,
    }),
    session("01MOCK00000000000000000005", "A7K2", "RESERVED", 2, {
      slot_id: "F1-A1", plate_normalized: "51A-12345", claim_expires_at: new Date(Date.now() + 13 * 60_000).toISOString(),
    }),
    session("01MOCK00000000000000000004", "P4MD", "PAYMENT_PENDING", 75, {
      slot_id: "F1-B3", plate_normalized: "30F-67890", parked_at: ago(73), charge_end_at: ago(1), fee_vnd: 15000,
      payment_status: "PENDING", email_status: "ACCEPTED_BY_SES", email: "khach@example.com",
    }),
    session("01MOCK00000000000000000003", "F9ZK", "EXIT_REQUESTED", 10, {
      slot_id: "F2-A1", plate_normalized: "29B-24680", parked_at: ago(9), charge_end_at: ago(0), fee_vnd: 0,
      payment_status: "NO_CHARGE",
    }),
    session("01MOCK00000000000000000002", "K2HT", "PARKED", 40, {
      slot_id: "F1-A2", plate_normalized: "43C-11223", parked_at: ago(38),
    }),
    session("01MOCK00000000000000000001", "C5M1", "CLOSED", 300, {
      slot_id: "F2-B2", plate_normalized: "51G-99887", parked_at: ago(298), charge_end_at: ago(200), fee_vnd: 15000,
      payment_status: "PAID_CASH", paid_amount_vnd: 15000, exit_confirmed_at: ago(198), closed_at: ago(198),
    }),
  ];
  let pricing: Pricing = {
    version: 1, free_minutes: 15, first_block_minutes: 60, first_block_vnd: 10000, extra_hour_vnd: 5000,
    updated_at: null, updated_by: null,
  };
  let pricingKey = "";
  const usedKeys = new Map<string, string>(); // `${session}:${thao tác}` → key đã dùng
  const delay = <T>(value: T) => new Promise<T>((r) => setTimeout(() => r(structuredClone(value)), 250));

  function find(id: string): SessionDetail {
    const s = sessions.find((x) => x.session_id === id);
    if (!s) throw new ApiError(404, "NOT_FOUND", "Không tìm thấy phiên");
    return s;
  }

  function conflict(message: string): never {
    throw new ApiError(409, "INVALID_STATE", message);
  }

  /** Cùng key cho cùng thao tác → trả trạng thái hiện tại mà không làm lại. */
  function mutate(id: string, action: string, key: string, reason: string | undefined, apply: (s: SessionDetail) => void) {
    const s = find(id);
    if (usedKeys.get(`${id}:${action}`) === key) return s;
    apply(s);
    usedKeys.set(`${id}:${action}`, key);
    const entry: AuditEntry = { action, at: new Date().toISOString(), actor_id: "mock-admin", actor: "mock" };
    if (reason) entry.reason = reason;
    s.audit = [...(s.audit ?? []), entry];
    s.updated_at = entry.at;
    return s;
  }

  function claimOf(s: SessionDetail) {
    return {
      session_ref: s.session_ref,
      slot_id: s.slot_id ?? "",
      route_steps: routeSteps(s.slot_id ?? "F1-A1"),
      claim_url: `${location.origin}/s/demo`,
      claim_expires_at: s.claim_expires_at ?? "",
      created_at: s.created_at,
    };
  }

  return {
    listSessions: async ({ status, limit = 20, cursor }) => {
      const all = sessions.filter((s) => !status || s.state === status).sort((a, b) => b.created_at.localeCompare(a.created_at));
      const start = Number(cursor ?? 0);
      const page = all.slice(start, start + limit);
      return delay({ sessions: page, next_cursor: start + limit < all.length ? String(start + limit) : null });
    },

    getSession: async (id) => delay(find(id)),

    resolvePlate: async (id, input, key) => {
      let created: SessionDetail | null = null;
      const review = mutate(id, "resolve-plate", key, input.reason, (s) => {
        if (s.state !== "MANUAL_REVIEW") conflict("Phiên không ở trạng thái chờ xử lý");
        if (!input.reason?.trim()) throw new ApiError(400, "INVALID_INPUT", "Thiếu reason");
        if (input.action === "ENTRY") {
          const free = slots.find((x) => x.status === "AVAILABLE");
          if (!free) throw new ApiError(409, "SLOT_CONFLICT", "Bãi đầy, không còn ô trống");
          free.status = "RESERVED";
          created = session(`01MOCK${Date.now().toString().padStart(20, "0")}`, "N3W1", "RESERVED", 0, {
            slot_id: free.slot_id, plate_normalized: input.plate_text?.toUpperCase() ?? null, resolved_from_session_id: s.session_id,
            claim_expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
          });
          sessions.push(created);
        } else if (input.action === "EXIT") {
          created = sessions.find((x) => x.plate_normalized === input.plate_text?.toUpperCase() && x.state === "PARKED") ?? null;
          if (!created) conflict("Không có phiên đang đỗ cho biển số này");
          Object.assign(created, { state: "PAYMENT_PENDING", charge_end_at: s.created_at, fee_vnd: 10000, payment_status: "PENDING" });
        }
        s.state = input.action === "DISMISS" ? "DISMISSED" : "RESOLVED";
        s.resolution = input.action;
        s.resolved_session_id = created?.session_id ?? null;
      });
      const target = review.resolved_session_id ? find(review.resolved_session_id) : null;
      return delay({ review, session: target, commands_sent: true });
    },

    renewClaim: async (id, reason, key) => {
      const s = mutate(id, "renew-claim", key, reason, (x) => {
        if (!["RESERVED", "ENTRY_GATE_OPEN", "PARKED"].includes(x.state)) conflict("Chỉ cấp lại QR cho xe còn trong bãi");
        x.claim_expires_at = new Date(Date.now() + 15 * 60_000).toISOString();
      });
      return delay(claimOf(s));
    },

    recordPayment: async (id, input, key) =>
      delay(
        mutate(id, "payment", key, input.note, (s) => {
          if (s.state !== "PAYMENT_PENDING" || s.payment_status !== "PENDING") conflict("Phiên không ở trạng thái chờ thu tiền");
          if (input.payment_status === "PAID_CASH" && input.amount_vnd !== s.fee_vnd) {
            conflict(`Số tiền phải bằng phí đã chốt ${s.fee_vnd} ₫`);
          }
          if (input.payment_status === "WAIVED" && !input.note?.trim()) throw new ApiError(400, "INVALID_INPUT", "Thiếu note");
          Object.assign(s, {
            state: "EXIT_REQUESTED", payment_status: input.payment_status, paid_amount_vnd: input.amount_vnd ?? 0,
            payment_note: input.note ?? null, paid_at: new Date().toISOString(),
          });
        }),
      ),

    openExit: async (id, reason, key) => {
      const s = mutate(id, "open-exit", key, reason, (x) => {
        if (!["EXIT_REQUESTED", "EXIT_GATE_OPEN"].includes(x.state) || !PAID.includes(x.payment_status ?? "")) {
          conflict("Phiên chưa yêu cầu ra hoặc chưa thu tiền");
        }
        // API giả coi như cần ra đã ACK OPEN ngay.
        Object.assign(x, { exit_command_id: crypto.randomUUID(), state: "EXIT_GATE_OPEN", exit_gate_opened_at: new Date().toISOString() });
      });
      return delay({ command_id: s.exit_command_id ?? "", session: s });
    },

    confirmPassage: async (id, reason, key) =>
      delay(
        mutate(id, "confirm-passage", key, reason, (s) => {
          if (!["EXIT_REQUESTED", "EXIT_GATE_OPEN"].includes(s.state) || !s.exit_command_id) conflict("Chưa mở cần ra cho phiên này");
          const now = new Date().toISOString();
          Object.assign(s, { state: "CLOSED", exit_confirmed_at: now, closed_at: now, email: null });
        }),
      ),

    getDevices: async () => {
      const now = new Date().toISOString();
      const devices: DeviceView[] = [
        { device_id: "pi-01", online: true, state: "ONLINE", last_seen_at: now, firmware_version: "0.1.0" },
        {
          device_id: "gate-01", online: true, state: "ONLINE", last_seen_at: now, firmware_version: "0.1.0",
          gates: {
            ENTRY: { state: "CLOSED", error_code: null, updated_at: ago(2) },
            EXIT: { state: "CLOSED", error_code: null, updated_at: ago(5) },
          },
          display: { state: "SHOWN", updated_at: ago(2) },
        },
        { device_id: "slots-01", online: true, state: "ONLINE", last_seen_at: now, firmware_version: "0.1.0", last_snapshot_at: now, snapshot_fresh: true },
      ];
      return delay({ devices });
    },

    getPricing: async () => delay(pricing),

    updatePricing: async (rules, key) => {
      if (key !== pricingKey) {
        const { reason: _reason, ...values } = rules;
        if (values.first_block_minutes < values.free_minutes) {
          throw new ApiError(400, "INVALID_INPUT", "first_block_minutes không được nhỏ hơn free_minutes");
        }
        pricing = { ...values, version: pricing.version + 1, updated_at: new Date().toISOString(), updated_by: "mock-admin" };
        pricingKey = key;
      }
      return delay(pricing);
    },
  };
}
