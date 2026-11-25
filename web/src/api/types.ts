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

// slot_id: ô trống gần cổng nhất LÚC HỎI — chỉ là gợi ý, phiên không được gán ô. null nếu không còn/không rõ.
export interface Claim {
  session_ref: string;
  slot_id: string | null;
  route_steps: string[];
  free_count?: number | null;
  claim_expires_at: string;
  email_submitted: boolean;
  email_auto?: boolean; // email chỉ dẫn đã tự gửi vì biển số đã liên kết email
  linked_email?: string | null; // email (che bớt) đang liên kết với biển số của lượt này
}

export interface EmailAccepted {
  email_status: "QUEUED";
}

export interface ActiveClaim {
  session_ref: string;
  slot_id: string | null;
  free_count?: number | null;
  claim_url: string;
  claim_expires_at: string;
  route_steps?: string[];
  checkin_at?: string;
}

export interface Alert {
  alert_id: string;
  kind: string;
  level: "INFO" | "WARN" | "ERROR";
  message: string;
  created_at: string;
  session_id?: string;
}

export interface LotCar {
  plate: string | null;
  session_id: string;
  session_ref?: string;
  state: SessionState;
  checkin_at?: string;
}

export interface AdminDashboard {
  lot?: { in_lot: LotCar[]; pending_entry: LotCar[]; pending_exit: LotCar[] };
  available: number;
  reserved: number;
  occupied: number;
  unknown: number;
  out_of_service?: number;
  offline_devices: string[];
  alerts: Alert[];
}

export type SessionState =
  | "ENTRY_PENDING"
  | "MANUAL_REVIEW"
  | "RESERVED"
  | "PARKED"
  | "EXIT_REQUESTED"
  | "EXIT_OPENED"
  | "CLOSED"
  | "EXPIRED"
  | "REJECTED"
  | "RESOLVED";

export type PaymentStatus = "PENDING" | "NO_CHARGE" | "PAID_CASH" | "WAIVED";

export interface HistoryEntry {
  at: string;
  actor: string;
  action: string;
  reason?: string;
}

export interface AdminSession {
  session_id: string;
  session_ref: string;
  state: SessionState;
  slot_id?: string;
  plate_text: string | null;
  plate_confidence?: number;
  email: string | null;
  email_status?: string;
  review_lane?: "ENTRY" | "EXIT";
  review_reason?: string;
  created_at: string;
  checkin_at?: string;
  parked_at?: string;
  exit_requested_at?: string;
  exit_opened_at?: string;
  exit_confirmed_at?: string;
  fee_vnd?: number;
  fee_preview_vnd?: number;
  payment_status?: PaymentStatus;
  payment_note?: string;
  claim_url?: string;
  claim_expires_at?: string;
  history?: HistoryEntry[];
}

export interface SessionList {
  items: AdminSession[];
  total: number;
}

export interface GateInfo {
  state: string;
  command_id?: string | null;
  error_code?: string | null;
  at?: string;
}

export interface DeviceInfo {
  device_id: string;
  state: "ONLINE" | "DEGRADED" | "OFFLINE";
  last_seen_at?: string;
  firmware_version?: string;
  gates?: Partial<Record<"ENTRY" | "EXIT", GateInfo>>;
  display?: { state?: string; screen?: string; at?: string };
  pending_commands?: number;
}

export interface Pricing {
  version: number;
  free_minutes: number;
  first_hour_vnd: number;
  next_hour_vnd: number;
  updated_at?: string;
}

export type ResolveAction = "ENTRY" | "EXIT" | "REJECT";

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
  | "INTERNAL"
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
  submitClaimEmail(token: string, email: string, consent: boolean, idempotencyKey: string, slotId?: string | null, remember?: boolean): Promise<EmailAccepted>;
  forgetClaimEmail(token: string): Promise<{ linked_email: null }>;
  unsubscribe(token: string): Promise<{ ok: boolean }>;
  getActiveClaims(): Promise<ActiveClaim[]>;
  getDashboard(): Promise<AdminDashboard>;
  listSessions(status?: string): Promise<SessionList>;
  resolvePlate(id: string, action: ResolveAction, plateText: string, reason: string): Promise<AdminSession>;
  renewClaim(id: string): Promise<AdminSession>;
  recordPayment(id: string, status: "PAID_CASH" | "WAIVED", amount: number | null, note: string): Promise<AdminSession>;
  openExit(id: string): Promise<AdminSession>;
  confirmPassage(id: string): Promise<AdminSession>;
  getDevices(): Promise<DeviceInfo[]>;
  getPricing(): Promise<Pricing>;
  putPricing(p: Pick<Pricing, "free_minutes" | "first_hour_vnd" | "next_hour_vnd">): Promise<Pricing>;
  gateCommand(gate: "ENTRY" | "EXIT", action: "OPEN" | "CLOSE"): Promise<{ command_id: string }>;
  ackAlert(id: string): Promise<void>;
}
