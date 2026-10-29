import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, type SessionState, type SessionSummary } from "../../api";
import { formatTime, formatVnd, PAYMENT_LABELS, plateOf, STATE_LABELS } from "./format";
import { ErrorCard, StateBadge } from "./shared";
import { handleAuthError } from "./useAction";

const PAGE_SIZE = 25;

export function SessionsPage() {
  const [params, setParams] = useSearchParams();
  const status = (params.get("status") || undefined) as SessionState | undefined;
  const navigate = useNavigate();
  const [rows, setRows] = useState<SessionSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>();

  const load = useCallback(
    async (from: string | null, append: boolean) => {
      setLoading(true);
      setError(undefined);
      try {
        const page = await api.listSessions({ status, limit: PAGE_SIZE, cursor: from ?? undefined });
        setRows((prev) => (append ? [...prev, ...page.sessions] : page.sessions));
        setCursor(page.next_cursor);
      } catch (e) {
        handleAuthError(e);
        setError(e);
      } finally {
        setLoading(false);
      }
    },
    [status],
  );

  useEffect(() => {
    load(null, false);
  }, [load]);

  return (
    <>
      <div className="actions-row" style={{ marginBottom: 12 }}>
        <label>
          Trạng thái{" "}
          <select value={status ?? ""} onChange={(e) => setParams(e.target.value ? { status: e.target.value } : {})}>
            <option value="">Tất cả</option>
            {Object.entries(STATE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <button type="button" className="secondary" onClick={() => load(null, false)} disabled={loading}>Làm mới</button>
      </div>
      <ErrorCard error={error} />
      <div className="card table-wrap">
        <table>
          <thead>
            <tr><th>Mã</th><th>Trạng thái</th><th>Biển số</th><th>Ô</th><th>Tạo lúc</th><th>Phí</th><th>Thanh toán</th></tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.session_id} className="clickable" onClick={() => navigate(`/admin/sessions/${s.session_id}`)}>
                <td><b>{s.session_ref}</b></td>
                <td><StateBadge state={s.state} /></td>
                <td>{plateOf(s)}</td>
                <td>{s.slot_id ?? "—"}</td>
                <td>{formatTime(s.created_at)}</td>
                <td>{formatVnd(s.fee_vnd)}</td>
                <td>{s.payment_status ? PAYMENT_LABELS[s.payment_status] : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && rows.length === 0 && <p className="muted">Không có phiên nào.</p>}
        {cursor && (
          <p><button type="button" className="secondary" disabled={loading} onClick={() => load(cursor, true)}>Tải thêm</button></p>
        )}
        {loading && <p className="muted">Đang tải…</p>}
      </div>
    </>
  );
}
