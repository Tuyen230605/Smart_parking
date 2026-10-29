import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, type SessionSummary } from "../../api";
import { formatVnd, plateOf, REVIEW_REASONS } from "./format";
import { ErrorCard, StateBadge, useAdminLoad } from "./shared";

export function Dashboard() {
  const board = useAdminLoad(() => api.getDashboard(), [], 5_000);
  const queues = useAdminLoad(async () => {
    const [review, payment, ready, opened] = await Promise.all([
      api.listSessions({ status: "MANUAL_REVIEW", limit: 20 }),
      api.listSessions({ status: "PAYMENT_PENDING", limit: 20 }),
      api.listSessions({ status: "EXIT_REQUESTED", limit: 20 }),
      api.listSessions({ status: "EXIT_GATE_OPEN", limit: 20 }),
    ]);
    return { review: review.sessions, payment: payment.sessions, exit: [...opened.sessions, ...ready.sessions] };
  }, [], 5_000);

  return (
    <>
      <ErrorCard error={board.error ?? queues.error} />
      {board.data && (
        <>
          <div className="stats">
            <div className="card"><b>{board.data.available}</b> ô trống</div>
            <div className="card"><b>{board.data.reserved}</b> đang giữ</div>
            <div className="card"><b>{board.data.occupied}</b> có xe</div>
            <div className="card"><b>{board.data.unknown}</b> không rõ</div>
          </div>
          <section className="card">
            <h2>Cảnh báo</h2>
            {board.data.alerts.length ? (
              <ul className="alerts">{board.data.alerts.map((a) => <li key={a}>{a}</li>)}</ul>
            ) : (
              <p className="muted">Không có cảnh báo.</p>
            )}
          </section>
        </>
      )}
      {queues.data && (
        <div className="queues">
          <Queue title="Chờ xử lý" empty="Không có lượt nào cần xử lý." sessions={queues.data.review}
            detail={(s) => REVIEW_REASONS[s.review_reason ?? ""] ?? s.review_reason ?? ""} />
          <Queue title="Chờ thu tiền" empty="Không có xe chờ thanh toán." sessions={queues.data.payment}
            detail={(s) => formatVnd(s.fee_vnd)} />
          <Queue title="Cổng ra" empty="Không có xe chờ ra." sessions={queues.data.exit}
            detail={(s) => <StateBadge state={s.state} />} />
        </div>
      )}
    </>
  );
}

function Queue({ title, empty, sessions, detail }: {
  title: string;
  empty: string;
  sessions: SessionSummary[];
  detail: (s: SessionSummary) => ReactNode;
}) {
  return (
    <section className="card">
      <h2>{title} ({sessions.length})</h2>
      {sessions.length === 0 && <p className="muted">{empty}</p>}
      {sessions.map((s) => (
        <Link key={s.session_id} className="queue-item" to={`/admin/sessions/${s.session_id}`}>
          <span><b>{s.session_ref}</b> · {plateOf(s)}{s.slot_id ? ` · ${s.slot_id}` : ""}</span>
          <span>{detail(s)}</span>
        </Link>
      ))}
    </section>
  );
}
