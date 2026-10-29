import type { PaymentStatus, PricingRules, SessionState, SessionSummary } from "../../api";

export const STATE_LABELS: Record<SessionState, string> = {
  RESERVED: "Đã giữ ô",
  ENTRY_GATE_OPEN: "Đã mở cần vào",
  PARKED: "Đang đỗ",
  EXIT_REQUESTED: "Sẵn sàng ra",
  PAYMENT_PENDING: "Chờ thu tiền",
  EXIT_GATE_OPEN: "Đã mở cần ra",
  CLOSED: "Đã đóng",
  EXPIRED: "Hết hạn giữ ô",
  MANUAL_REVIEW: "Chờ xử lý",
  RESOLVED: "Đã xử lý",
  DISMISSED: "Đã bỏ qua",
};

export const REVIEW_REASONS: Record<string, string> = {
  WRONG_LANE: "Thẻ sai làn",
  STALE_EVENT: "Sự kiện đến trễ",
  UNREADABLE_PLATE: "Không đọc được biển số",
  LOW_CONFIDENCE: "OCR không chắc chắn",
  PLATE_ALREADY_ACTIVE: "Biển số đang có phiên mở",
  SLOTS_UNKNOWN: "Không có dữ liệu ô mới",
  NO_ACTIVE_SESSION: "Không tìm thấy phiên đang đỗ",
  SESSION_NOT_PARKED: "Phiên chưa ghi nhận đỗ",
};

export const PAYMENT_LABELS: Record<PaymentStatus, string> = {
  PENDING: "Chưa thu",
  NO_CHARGE: "Miễn phí (0 ₫)",
  PAID_CASH: "Đã thu tiền mặt",
  WAIVED: "Miễn thu",
};

export const EMAIL_LABELS: Record<string, string> = {
  QUEUED: "Đang gửi",
  ACCEPTED_BY_SES: "SES đã nhận",
  FAILED: "Gửi lỗi",
};

/** Trạng thái theo nhóm màu để nhìn nhanh trên bảng. */
export function stateTone(state: SessionState): "warn" | "ok" | "info" | "done" {
  if (state === "MANUAL_REVIEW" || state === "PAYMENT_PENDING") return "warn";
  if (state === "EXIT_REQUESTED" || state === "EXIT_GATE_OPEN") return "info";
  if (state === "CLOSED" || state === "EXPIRED" || state === "RESOLVED" || state === "DISMISSED") return "done";
  return "ok";
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "medium" });
}

export function formatVnd(amount: number | null | undefined): string {
  return amount == null ? "—" : `${amount.toLocaleString("vi-VN")} ₫`;
}

export function formatDuration(fromIso: string | null, toIso?: string | null): string {
  if (!fromIso) return "—";
  const minutes = Math.max(0, Math.floor((Date.parse(toIso ?? new Date().toISOString()) - Date.parse(fromIso)) / 60_000));
  return minutes < 60 ? `${minutes} phút` : `${Math.floor(minutes / 60)} giờ ${minutes % 60} phút`;
}

/** null khi OCR không đọc được hoặc đã quá hạn lưu; trang chi tiết nói rõ trường hợp nào. */
export function plateOf(s: SessionSummary): string {
  return s.plate_normalized ?? "—";
}

/** Cùng công thức với backend/src/parking/pricing.py để xem trước bảng giá. */
export function computeFee(rules: PricingRules, minutes: number): number {
  const seconds = minutes * 60;
  if (seconds < rules.free_minutes * 60) return 0;
  const firstBlock = rules.first_block_minutes * 60;
  if (seconds <= firstBlock) return rules.first_block_vnd;
  return rules.first_block_vnd + Math.ceil((seconds - firstBlock) / 3600) * rules.extra_hour_vnd;
}
