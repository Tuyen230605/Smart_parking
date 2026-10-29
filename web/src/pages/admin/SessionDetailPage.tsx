import type { ReactNode } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { api, type SessionDetail } from "../../api";
import { EMAIL_LABELS, formatDuration, formatTime, formatVnd, PAYMENT_LABELS, REVIEW_REASONS } from "./format";
import { SessionActions } from "./SessionActions";
import { ErrorCard, StateBadge, useAdminLoad } from "./shared";

const CLAIM_STATES = ["RESERVED", "ENTRY_GATE_OPEN", "PARKED"];
const AUDIT_LABELS: Record<string, string> = {
  "resolve-plate": "Xử lý OCR",
  "renew-claim": "Cấp lại QR",
  payment: "Thu tiền",
  "open-exit": "Mở cần ra",
  "confirm-passage": "Xác nhận xe qua",
  "expire-reservation": "Hết hạn giữ ô",
  "purge-identity": "Xóa dữ liệu định danh",
};

export function SessionDetailPage() {
  const { sessionId = "" } = useParams();
  const notice = (useLocation().state as { notice?: string } | null)?.notice;
  // Làm mới 5 giây/lần để thấy ACK cần chắn và cảm biến ô cập nhật trạng thái.
  const { data: s, error, reload } = useAdminLoad(() => api.getSession(sessionId), [sessionId], 5_000);

  return (
    <>
      <p><Link to="/admin/sessions">← Danh sách phiên</Link></p>
      {notice && <div className="card success">{notice}</div>}
      <ErrorCard error={error} />
      {s && (
        <>
          <div className="admin-head">
            <h2 style={{ margin: 0 }}>Phiên {s.session_ref} <StateBadge state={s.state} /></h2>
            <span className="muted">{s.session_id}</span>
          </div>
          <div className="detail-grid">
            <section className="card">
              <h2>Thông tin</h2>
              <Facts s={s} />
            </section>
            <SessionActions session={s} onChanged={reload} />
          </div>
          <section className="card">
            <h2>Nhật ký thao tác</h2>
            {s.audit?.length ? (
              <ol className="audit">
                {s.audit.map((a, i) => (
                  <li key={i}>
                    {formatTime(a.at)} · <b>{AUDIT_LABELS[a.action] ?? a.action}</b>
                    {a.detail && ` (${a.detail})`} · {a.actor || a.actor_id}
                    {a.reason && <> · <i>{a.reason}</i></>}
                  </li>
                ))}
              </ol>
            ) : (
              <p className="muted">Chưa có thao tác quản trị.</p>
            )}
          </section>
        </>
      )}
    </>
  );
}

function Facts({ s }: { s: SessionDetail }) {
  const rows: [string, ReactNode][] = [
    ["Làn / thẻ", [s.lane_id === "EXIT" ? "Ra" : s.lane_id === "ENTRY" ? "Vào" : "—", s.card_color].filter(Boolean).join(" · ")],
    ["Biển số", s.plate_normalized ?? (s.plate_text ? `OCR đọc: ${s.plate_text}` : "đã xóa hoặc không đọc được")],
    ["Độ tin cậy OCR", s.plate_confidence != null ? s.plate_confidence.toFixed(2) : "—"],
    ["Ô", s.slot_id ?? "—"],
    ["Tạo lúc", formatTime(s.created_at)],
    ["Vào bãi", formatTime(s.checkin_at)],
    ["Đỗ vào ô", formatTime(s.parked_at)],
    ["Thời gian gửi", s.checkin_at ? formatDuration(s.checkin_at, s.charge_end_at) : "—"],
    ["Chốt phí lúc", formatTime(s.charge_end_at)],
    ["Phí", formatVnd(s.fee_vnd)],
    ["Thanh toán", s.payment_status ? PAYMENT_LABELS[s.payment_status] : "—"],
    ["Ghi chú thu tiền", s.payment_note ?? "—"],
    ["Email", s.email_status ? `${EMAIL_LABELS[s.email_status] ?? s.email_status}${s.email ? ` · ${s.email}` : ""}` : "Không nhập"],
    ["Mở cần ra", formatTime(s.exit_gate_opened_at)],
    ["Xe qua cổng", formatTime(s.exit_confirmed_at)],
  ];
  if (s.review_reason) rows.unshift(["Lý do chờ xử lý", REVIEW_REASONS[s.review_reason] ?? s.review_reason]);
  if (CLAIM_STATES.includes(s.state)) rows.push(["QR hết hạn", formatTime(s.claim_expires_at)]);
  if (s.gate_error) rows.push(["Lỗi cần chắn", <span className="badge badge-bad">{s.gate_error}</span>]);
  const links: [string, string | null][] = [
    ["Phiên liên quan", s.related_session_id],
    ["Đã xử lý thành phiên", s.resolved_session_id],
    ["Tạo từ lượt chờ xử lý", s.resolved_from_session_id],
  ];
  for (const [label, id] of links) {
    if (id) rows.push([label, <Link to={`/admin/sessions/${id}`}>{id}</Link>]);
  }
  return (
    <dl className="facts">
      {rows.map(([label, value]) => (
        <div key={label} style={{ display: "contents" }}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
