// Kiểu dữ liệu theo docs/api-contract.md. Sửa hợp đồng thì sửa ở đây trước.

export type SlotStatus = "AVAILABLE" | "RESERVED" | "OCCUPIED" | "UNKNOWN" | "OUT_OF_SERVICE";

export interface Slot {
  slot_id: string; // F1-A1 … F2-C3
  source: "SENSOR" | "BUTTON";
  status: SlotStatus;
  updated_at: string;
}

export interface PublicLayout {
  slots: Slot[];
}

export interface Claim {
  session_ref: string;
  slot_id: string;
  route_steps: string[];
  claim_expires_at: string;
  email_submitted: boolean;
}

export interface EmailAccepted {
  email_status: "QUEUED";
}

export interface ActiveClaim {
  session_ref: string;
  slot_id: string;
  claim_url: string;
  claim_expires_at: string;
  // Backend trả thêm để kiosk hiện lộ trình và chọn phiên mới nhất (đề xuất hợp đồng v1.1).
  route_steps?: string[];
  created_at?: string;
}

export interface AdminDashboard {
  available: number;
  reserved: number;
  occupied: number;
  unknown: number;
  offline_devices: string[];
  alerts: string[];
}

// ---------- Quản trị (backend/README.md, mục "Endpoint quản trị") ----------

export type SessionState =
  | "RESERVED"
  | "ENTRY_GATE_OPEN"
  | "PARKED"
  | "EXIT_REQUESTED"
  | "PAYMENT_PENDING"
  | "EXIT_GATE_OPEN"
  | "CLOSED"
  | "EXPIRED"
  | "MANUAL_REVIEW"
  | "RESOLVED"
  | "DISMISSED";

export type PaymentStatus = "PENDING" | "NO_CHARGE" | "PAID_CASH" | "WAIVED";

export interface SessionSummary {
  session_id: string;
  session_ref: string;
  state: SessionState;
  lane_id: "ENTRY" | "EXIT" | null;
  slot_id: string | null;
  review_reason: string | null;
  created_at: string;
  checkin_at: string | null;
  parked_at: string | null;
  charge_end_at: string | null;
  exit_confirmed_at: string | null;
  fee_vnd: number | null;
  payment_status: PaymentStatus | null;
  email_status: "QUEUED" | "ACCEPTED_BY_SES" | "FAILED" | null;
  plate_confidence: number | null;
  plate_normalized: string | null; // null khi quá hạn lưu 10 ngày
}

export interface AuditEntry {
  action: string;
  at: string;
  actor_id: string;
  actor: string;
  reason?: string;
  detail?: string;
}

export interface SessionDetail extends SessionSummary {
  card_color: "GREEN" | "RED" | null;
  related_session_id: string | null;
  resolution: "ENTRY" | "EXIT" | "DISMISS" | null;
  resolved_session_id: string | null;
  resolved_from_session_id: string | null;
  claim_expires_at: string | null;
  entry_command_id: string | null;
  exit_command_id: string | null;
  entry_gate_opened_at: string | null;
  exit_gate_opened_at: string | null;
  gate_error: string | null;
  paid_amount_vnd: number | null;
  payment_note: string | null;
  paid_at: string | null;
  closed_at: string | null;
  updated_at: string | null;
  plate_text: string | null;
  email: string | null;
  audit: AuditEntry[] | null;
}

export interface SessionPage {
  sessions: SessionSummary[];
  next_cursor: string | null;
}

export interface ResolvePlateInput {
  action: "ENTRY" | "EXIT" | "DISMISS";
  plate_text?: string;
  reason: string;
}

export interface Resolution {
  review: SessionDetail;
  session: SessionDetail | null;
  commands_sent?: boolean;
}

export interface PaymentInput {
  payment_status: "PAID_CASH" | "WAIVED";
  amount_vnd?: number;
  note?: string;
}

export interface OpenExitResult {
  command_id: string;
  session: SessionDetail;
}

export interface GateView {
  state: "OPENING" | "OPEN" | "CLOSING" | "CLOSED" | "ERROR" | null;
  error_code: string | null;
  updated_at: string | null;
}

export interface DeviceView {
  device_id: "pi-01" | "gate-01" | "slots-01";
  online: boolean;
  state: "ONLINE" | "DEGRADED" | "OFFLINE" | null;
  last_seen_at: string | null;
  firmware_version: string | null;
  gates?: Record<"ENTRY" | "EXIT", GateView>;
  display?: { state: "SHOWN" | "ERROR" | null; updated_at: string | null };
  last_snapshot_at?: string | null;
  snapshot_fresh?: boolean;
}

export interface PricingRules {
  free_minutes: number;
  first_block_minutes: number;
  first_block_vnd: number;
  extra_hour_vnd: number;
}

export interface Pricing extends PricingRules {
  version: number;
  updated_at: string | null;
  updated_by: string | null;
}

export type ErrorCode =
  | "INVALID_INPUT"
  | "UNAUTHENTICATED"
  | "FORBIDDEN"
  | "NOT_FOUND"
  | "SLOT_CONFLICT"
  | "INVALID_STATE"
  | "EMAIL_ALREADY_SENT"
  | "TOKEN_EXPIRED"
  | "RATE_LIMITED"
  | "DEVICE_OFFLINE"
  | "INTERNAL_ERROR"
  | "NETWORK_ERROR";

export class ApiError extends Error {
  constructor(public status: number, public code: ErrorCode, message: string) {
    super(message);
  }
}

/** Mọi trang gọi backend qua interface này; `http.ts` và `mock.ts` cùng cài đặt. */
export interface Api {
  getLayout(): Promise<PublicLayout>;
  getClaim(token: string): Promise<Claim>;
  submitClaimEmail(token: string, email: string, consent: boolean, idempotencyKey: string): Promise<EmailAccepted>;
  getActiveClaims(): Promise<ActiveClaim[]>;
  getDashboard(): Promise<AdminDashboard>;
  // Quản trị. Thao tác thay đổi nhận Idempotency-Key: giữ nguyên key khi thử lại sau lỗi mạng/5xx.
  listSessions(query: { status?: SessionState; limit?: number; cursor?: string }): Promise<SessionPage>;
  getSession(sessionId: string): Promise<SessionDetail>;
  resolvePlate(sessionId: string, input: ResolvePlateInput, idempotencyKey: string): Promise<Resolution>;
  renewClaim(sessionId: string, reason: string | undefined, idempotencyKey: string): Promise<ActiveClaim>;
  recordPayment(sessionId: string, input: PaymentInput, idempotencyKey: string): Promise<SessionDetail>;
  openExit(sessionId: string, reason: string | undefined, idempotencyKey: string): Promise<OpenExitResult>;
  confirmPassage(sessionId: string, reason: string | undefined, idempotencyKey: string): Promise<SessionDetail>;
  getDevices(): Promise<{ devices: DeviceView[] }>;
  getPricing(): Promise<Pricing>;
  updatePricing(rules: PricingRules & { reason?: string }, idempotencyKey: string): Promise<Pricing>;
}
