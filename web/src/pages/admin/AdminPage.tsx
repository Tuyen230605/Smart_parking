// Trang quản trị: tổng quan + cảnh báo, thiết bị + điều khiển cần, phiên đỗ + thao tác, bảng giá.
import { useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api, ApiError, type AdminDashboard, type AdminSession, type DeviceInfo, type LotCar, type Pricing, type ResolveAction } from "../../api";
import { RequireAuth } from "../../components/RequireAuth";
import { useLoad } from "../../components/useLoad";

export function AdminPage() {
  return (
    <RequireAuth groups={["ADMIN"]}>
      <main className="page">
        <nav className="tabs">
          <NavLink to="/admin" end>Tổng quan</NavLink>
          <NavLink to="/admin/sessions">Phiên đỗ</NavLink>
          <NavLink to="/admin/pricing">Bảng giá</NavLink>
        </nav>
        <Routes>
          <Route index element={<Overview />} />
          <Route path="sessions" element={<Sessions />} />
          <Route path="pricing" element={<PricingEditor />} />
        </Routes>
      </main>
    </RequireAuth>
  );
}

const vnd = (n?: number) => (n === undefined ? "—" : `${n.toLocaleString("vi-VN")} ₫`);
const time = (s?: string) => (s ? new Date(s).toLocaleTimeString("vi-VN") : "—");
const ago = (s?: string) => {
  if (!s) return "chưa từng";
  const sec = Math.round((Date.now() - Date.parse(s)) / 1000);
  return sec < 60 ? `${sec}s trước` : `${Math.round(sec / 60)} phút trước`;
};
const errMsg = (e: unknown) => (e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));

/** Gọi một thao tác, hiện lỗi bằng alert, rồi tải lại dữ liệu. */
function useAction(reload: () => void) {
  const [busy, setBusy] = useState(false);
  return {
    busy,
    run: async (fn: () => Promise<unknown>) => {
      setBusy(true);
      try {
        await fn();
      } catch (e) {
        window.alert(errMsg(e));
      } finally {
        setBusy(false);
        reload();
      }
    },
  };
}

// ── tổng quan ───────────────────────────────────────────────────────────────

function Overview() {
  const dash = useLoad(() => api.getDashboard(), [], 3_000);
  const devices = useLoad(() => api.getDevices(), [], 3_000);
  const { run } = useAction(dash.reload);
  const d = dash.data;
  return (
    <>
      {dash.error && <div className="card error">{errMsg(dash.error)}</div>}
      {d && (
        <div className="stats">
          <div className="card stat-available"><b>{d.available}</b> trống</div>
          <div className="card stat-reserved"><b>{d.lot?.in_lot.length ?? 0}</b> xe trong bãi</div>
          <div className="card stat-occupied"><b>{d.occupied}</b> có xe</div>
          <div className="card stat-unknown"><b>{d.unknown}</b> không rõ</div>
        </div>
      )}
      {d?.lot && <LotList lot={d.lot} />}
      <section className="card">
        <h2>Cảnh báo {d && d.alerts.length > 0 && <span className="badge">{d.alerts.length}</span>}</h2>
        {d?.alerts.length === 0 && <p className="muted">Không có cảnh báo mới.</p>}
        <ul className="alerts">
          {d?.alerts.map((a) => (
            <li key={a.alert_id} className={`alert-${a.level.toLowerCase()}`}>
              <span className="muted">{time(a.created_at)}</span> <b>{a.kind}</b> {a.message}
              <button className="link" onClick={() => run(() => api.ackAlert(a.alert_id))}>Đã xem</button>
            </li>
          ))}
        </ul>
      </section>
      <section className="card">
        <h2>Thiết bị</h2>
        {devices.error && <p className="error-text">{errMsg(devices.error)}</p>}
        <div className="devices">
          {devices.data?.map((dev) => <Device key={dev.device_id} dev={dev} reload={devices.reload} />)}
        </div>
      </section>
    </>
  );
}

/** Danh sách xe trong bãi lấy từ phiên đỗ (cùng nguồn với trang camera trên Pi). */
function LotList({ lot }: { lot: NonNullable<AdminDashboard["lot"]> }) {
  const plates = (cars: LotCar[]) => cars.map((c) => c.plate ?? c.session_ref).join(", ") || "—";
  return (
    <section className="card">
      <h2>Xe trong bãi <span className="badge">{lot.in_lot.length}</span></h2>
      <p className="lot-plates">{plates(lot.in_lot)}</p>
      {lot.pending_entry.length > 0 && (
        <p>Chờ cho vào: <b>{plates(lot.pending_entry)}</b> → <NavLink to="/admin/sessions">Phiên đỗ</NavLink></p>
      )}
      {lot.pending_exit.length > 0 && (
        <p>Chờ cho ra: <b>{plates(lot.pending_exit)}</b> → <NavLink to="/admin/sessions">Phiên đỗ</NavLink></p>
      )}
    </section>
  );
}

function Device({ dev, reload }: { dev: DeviceInfo; reload: () => void }) {
  const { busy, run } = useAction(reload);
  return (
    <div className={`device device-${dev.state.toLowerCase()}`}>
      <b>{dev.device_id}</b> <span className="pill">{dev.state}</span>
      <div className="muted">gặp lần cuối {ago(dev.last_seen_at)} · fw {dev.firmware_version ?? "?"}</div>
      {dev.device_id === "gate-01" && (
        <div className="gates">
          {(["ENTRY", "EXIT"] as const).map((g) => (
            <div key={g}>
              Cần {g === "ENTRY" ? "vào" : "ra"}: <b>{dev.gates?.[g]?.state ?? "?"}</b>
              {dev.gates?.[g]?.error_code && <span className="error-text"> {dev.gates[g]!.error_code}</span>}
              <div className="row">
                <button className="secondary" disabled={busy} onClick={() => run(() => api.gateCommand(g, "OPEN"))}>Mở tay</button>
                <button className="secondary" disabled={busy} onClick={() => run(() => api.gateCommand(g, "CLOSE"))}>Đóng</button>
              </div>
            </div>
          ))}
          {dev.display?.screen && <div className="muted">OLED: {dev.display.screen} ({ago(dev.display.at)})</div>}
          {!!dev.pending_commands && <div className="error-text">{dev.pending_commands} lệnh chưa ACK</div>}
        </div>
      )}
    </div>
  );
}

// ── phiên đỗ ────────────────────────────────────────────────────────────────

const STATE_LABEL: Record<string, string> = {
  ENTRY_PENDING: "Chờ cho vào", MANUAL_REVIEW: "Chờ duyệt", RESERVED: "Trong bãi", PARKED: "Trong bãi", EXIT_REQUESTED: "Chờ cho ra",
  EXIT_OPENED: "Đã mở cần ra", CLOSED: "Đã đóng", EXPIRED: "Hết hạn giữ ô", REJECTED: "Từ chối", RESOLVED: "Đã gộp",
};

function Sessions() {
  const [filter, setFilter] = useState("OPEN");
  const list = useLoad(() => api.listSessions(filter || undefined), [filter], 3_000);
  return (
    <>
      <div className="row">
        <label className="inline">
          Lọc
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="OPEN">Đang mở</option>
            <option value="ENTRY_PENDING">Chờ cho vào</option>
            <option value="EXIT_REQUESTED">Chờ cho ra</option>
            <option value="CLOSED">Đã đóng</option>
            <option value="">Tất cả</option>
          </select>
        </label>
        <span className="muted">{list.data?.items.length ?? 0} phiên</span>
      </div>
      {list.error && <div className="card error">{errMsg(list.error)}</div>}
      {list.data?.items.map((s) => <SessionCard key={s.session_id} s={s} reload={list.reload} />)}
    </>
  );
}

function SessionCard({ s, reload }: { s: AdminSession; reload: () => void }) {
  const { busy, run } = useAction(reload);
  const [plate, setPlate] = useState(s.plate_text ?? "");
  const [note, setNote] = useState("");
  const resolve = (action: ResolveAction) => run(() => api.resolvePlate(s.session_id, action, plate, note || "Quản trị xác nhận"));

  return (
    <section className={`card session state-${s.state.toLowerCase()}`}>
      <div className="session-head">
        <b>{s.session_ref}</b>
        <span className="pill">{STATE_LABEL[s.state] ?? s.state}</span>
        {s.slot_id && <span>ô <b>{s.slot_id}</b></span>}
        <span>biển số <b>{s.plate_text ?? "—"}</b>{s.plate_confidence !== undefined && <small className="muted"> ({Math.round(s.plate_confidence * 100)}%)</small>}</span>
        <span className="muted">vào {time(s.checkin_at ?? s.created_at)}</span>
        {s.email_status && <span className="muted">email: {s.email_status}</span>}
      </div>

      {s.state === "ENTRY_PENDING" && (
        <div className="actions entry-pending">
          <p>Camera thấy xe <b className="fee">{s.plate_text ?? "—"}</b> ở làn VÀO</p>
          <div className="row">
            <button disabled={busy || !s.plate_text} onClick={() => resolve("ENTRY")}>Cho vào (mở cần vào)</button>
            <button className="secondary" disabled={busy} onClick={() => resolve("REJECT")}>Không cho vào</button>
          </div>
        </div>
      )}

      {s.state === "MANUAL_REVIEW" && (
        <div className="actions">
          <p>Làn <b>{s.review_lane}</b> · lý do <code>{s.review_reason}</code></p>
          <input value={plate} onChange={(e) => setPlate(e.target.value)} placeholder="Biển số đúng, ví dụ 51A-12345" />
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Ghi chú (lưu vết)" />
          <div className="row">
            <button disabled={busy || !plate} onClick={() => resolve("ENTRY")}>Cho VÀO (mở cần vào)</button>
            <button disabled={busy || !plate} onClick={() => resolve("EXIT")}>Xử lý RA theo biển số</button>
            <button className="secondary" disabled={busy} onClick={() => resolve("REJECT")}>Bỏ qua</button>
          </div>
        </div>
      )}

      {(s.state === "RESERVED" || s.state === "PARKED") && (
        <div className="actions row">
          <span>Phí tạm tính: <b>{vnd(s.fee_preview_vnd)}</b></span>
          {s.claim_url ? <a href={s.claim_url} target="_blank" rel="noreferrer">Link QR</a> : <span className="muted">QR đã hết hạn</span>}
          <button className="secondary" disabled={busy} onClick={() => run(() => api.renewClaim(s.session_id))}>Cấp lại QR</button>
        </div>
      )}

      {s.state === "EXIT_REQUESTED" && (
        <div className="actions exit-pending">
          <p>Xe đang chờ ở làn RA · Phí: <b className="fee">{vnd(s.fee_vnd)}</b>
            {s.payment_status === "NO_CHARGE" && <span className="muted"> (miễn phí, dưới thời gian miễn phí)</span>}</p>
          {s.payment_status === "PENDING" ? (
            <div className="row">
              <button disabled={busy} onClick={() => run(() => api.recordPayment(s.session_id, "PAID_CASH", s.fee_vnd ?? 0, "Đã thu tại cổng"))}>
                Đã thu {vnd(s.fee_vnd)} → cho ra (mở cần)
              </button>
              <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Lý do miễn phí" />
              <button className="secondary" disabled={busy || !note} onClick={() => run(() => api.recordPayment(s.session_id, "WAIVED", null, note))}>Miễn phí</button>
            </div>
          ) : (
            <button disabled={busy} onClick={() => run(() => api.openExit(s.session_id))}>Cho ra (mở cần)</button>
          )}
        </div>
      )}

      {s.state === "EXIT_OPENED" && (
        <div className="actions row">
          <span>Phí {vnd(s.fee_vnd)} · {s.payment_status} · cần ra mở lúc {time(s.exit_opened_at)}</span>
          <button disabled={busy} onClick={() => run(() => api.confirmPassage(s.session_id))}>Xác nhận xe đã ra</button>
          <button className="secondary" disabled={busy} onClick={() => run(() => api.openExit(s.session_id))}>Mở lại cần</button>
        </div>
      )}

      {s.state === "CLOSED" && <p className="muted">Ra lúc {time(s.exit_confirmed_at)} · {vnd(s.fee_vnd)} · {s.payment_status}</p>}

      {s.history && s.history.length > 0 && (
        <details>
          <summary className="muted">Lịch sử ({s.history.length})</summary>
          <ul className="history">
            {s.history.map((h, i) => <li key={i}>{time(h.at)} · {h.actor} · {h.action}{h.reason ? ` · ${h.reason}` : ""}</li>)}
          </ul>
        </details>
      )}
    </section>
  );
}

// ── bảng giá ────────────────────────────────────────────────────────────────

function PricingEditor() {
  const { data, error, reload } = useLoad(() => api.getPricing(), []);
  return data ? <PricingForm key={data.version} p={data} reload={reload} /> : error ? <div className="card error">{errMsg(error)}</div> : null;
}

function PricingForm({ p, reload }: { p: Pricing; reload: () => void }) {
  const [form, setForm] = useState({ free_minutes: p.free_minutes, first_hour_vnd: p.first_hour_vnd, next_hour_vnd: p.next_hour_vnd });
  const { busy, run } = useAction(reload);
  const field = (key: keyof typeof form, label: string) => (
    <label>
      {label}
      <input type="number" min={0} value={form[key]} onChange={(e) => setForm({ ...form, [key]: Number(e.target.value) })} />
    </label>
  );
  return (
    <section className="card narrow-card">
      <h2>Bảng giá demo (phiên bản {p.version})</h2>
      {field("free_minutes", "Miễn phí dưới (phút)")}
      {field("first_hour_vnd", "Đến hết 60 phút (₫)")}
      {field("next_hour_vnd", "Mỗi giờ tiếp theo bắt đầu (₫)")}
      <p className="muted">Phiên đang đỗ giữ bảng giá lúc vào; giá mới áp dụng cho xe vào sau khi lưu.</p>
      <button disabled={busy} onClick={() => run(() => api.putPricing(form))}>Lưu bảng giá</button>
    </section>
  );
}
