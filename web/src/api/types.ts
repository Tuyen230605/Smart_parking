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
}

export interface AdminDashboard {
  available: number;
  reserved: number;
  occupied: number;
  unknown: number;
  offline_devices: string[];
  alerts: string[];
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
}
