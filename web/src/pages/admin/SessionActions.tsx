// Thao tác theo trạng thái phiên. Mỗi thao tác dùng useAction (Idempotency-Key + audit phía backend).
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, type ActiveClaim, type SessionDetail } from "../../api";
import { formatTime, formatVnd } from "./format";
import { ConfirmButton } from "./shared";
import { useAction } from "./useAction";

const CLAIM_STATES = ["RESERVED", "ENTRY_GATE_OPEN", "PARKED"];
const EXIT_STATES = ["EXIT_REQUESTED", "EXIT_GATE_OPEN"];
const PAID = ["NO_CHARGE", "PAID_CASH", "WAIVED"];

export function SessionActions({ session: s, onChanged }: { session: SessionDetail; onChanged: () => void }) {
  const blocks = [];
  if (s.state === "MANUAL_REVIEW") blocks.push(<ResolveForm key="resolve" s={s} onChanged={onChanged} />);
  if (s.state === "PAYMENT_PENDING" && s.payment_status === "PENDING") {
    blocks.push(<PaymentForm key="payment" s={s} onChanged={onChanged} />);
  }
  if (EXIT_STATES.includes(s.state) && PAID.includes(s.payment_status ?? "")) {
    blocks.push(<ExitControls key="exit" s={s} onChanged={onChanged} />);
  }
  if (CLAIM_STATES.includes(s.state)) blocks.push(<RenewClaim key="renew" s={s} onChanged={onChanged} />);
  return (
    <section className="card">
      <h2>Thao tác</h2>
      {blocks.length ? blocks : <p className="muted">Không có thao tác cho trạng thái này.</p>}
    </section>
  );
}

function ResolveForm({ s, onChanged }: { s: SessionDetail; onChanged: () => void }) {
  const navigate = useNavigate();
  const [action, setAction] = useState<"ENTRY" | "EXIT" | "DISMISS">(s.lane_id === "EXIT" ? "EXIT" : "ENTRY");
  const [plate, setPlate] = useState(s.plate_normalized ?? s.plate_text ?? "");
  const [reason, setReason] = useState("");
  const { run, pending, error } = useAction();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const result = await run((key) =>
      api.resolvePlate(s.session_id, { action, plate_text: action === "DISMISS" ? undefined : plate.trim(), reason: reason.trim() }, key),
    );
    if (!result) return;
    const target = result.session;
    if (!target) return onChanged();
    const warning = result.commands_sent === false ? " Không gửi được lệnh tới cổng: thao tác tay tại mô hình." : "";
    const notice = action === "ENTRY"
      ? `Đã cho vào: ô ${target.slot_id}.${warning}`
      : `Đã chốt phí ra ${formatVnd(target.fee_vnd)}.${warning}`;
    navigate(`/admin/sessions/${target.session_id}`, { state: { notice } });
  }

  return (
    <form onSubmit={submit}>
      <h3>Xử lý lượt chờ</h3>
      <div className="radio-row">
        {([["ENTRY", "Cho vào (gán ô mới)"], ["EXIT", "Cho ra (chốt phí phiên đang đỗ)"], ["DISMISS", "Bỏ qua"]] as const).map(
          ([value, label]) => (
            <label key={value}>
              <input type="radio" name="action" checked={action === value} onChange={() => setAction(value)} /> {label}
            </label>
          ),
        )}
      </div>
      {action !== "DISMISS" && (
        <label>
          Biển số đúng
          <input type="text" required value={plate} onChange={(e) => setPlate(e.target.value)} placeholder="51A-12345" />
        </label>
      )}
      <label>
        Lý do (ghi vào nhật ký)
        <input type="text" required maxLength={200} value={reason} onChange={(e) => setReason(e.target.value)}
          placeholder="Ví dụ: OCR đọc thiếu nét, đã kiểm tra tại cổng" />
      </label>
      {error && <p className="error-text">{error}</p>}
      <button type="submit" disabled={pending}>{pending ? "Đang xử lý…" : "Xác nhận"}</button>
    </form>
  );
}

function PaymentForm({ s, onChanged }: { s: SessionDetail; onChanged: () => void }) {
  const [waive, setWaive] = useState(false);
  const [note, setNote] = useState("");
  const { run, pending, error } = useAction();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const input = waive
      ? { payment_status: "WAIVED" as const, note: note.trim() }
      : { payment_status: "PAID_CASH" as const, amount_vnd: s.fee_vnd ?? 0, note: note.trim() || undefined };
    if (await run((key) => api.recordPayment(s.session_id, input, key))) onChanged();
  }

  return (
    <form onSubmit={submit}>
      <h3>Thu phí {formatVnd(s.fee_vnd)}</h3>
      <p className="muted">Chốt lúc {formatTime(s.charge_end_at)}; số tiền không tăng trong lúc chờ thu.</p>
      <div className="radio-row">
        <label><input type="radio" checked={!waive} onChange={() => setWaive(false)} /> Đã thu tiền mặt</label>
        <label><input type="radio" checked={waive} onChange={() => setWaive(true)} /> Miễn thu</label>
      </div>
      <label>
        Ghi chú{waive ? " (bắt buộc khi miễn thu)" : ""}
        <input type="text" required={waive} maxLength={200} value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      {error && <p className="error-text">{error}</p>}
      <button type="submit" disabled={pending}>
        {pending ? "Đang lưu…" : waive ? "Ghi nhận miễn thu" : `Ghi nhận đã thu ${formatVnd(s.fee_vnd)}`}
      </button>
    </form>
  );
}

// Người 2 có thể thay khối này bằng component trạng thái hai cần + nút mở cổng ra (docs/team-tasks.md),
// miễn vẫn gọi api.openExit/api.confirmPassage với Idempotency-Key.
function ExitControls({ s, onChanged }: { s: SessionDetail; onChanged: () => void }) {
  const open = useAction();
  const confirm = useAction();
  const waitingAck = s.state === "EXIT_REQUESTED" && !!s.exit_command_id;

  return (
    <div>
      <h3>Cổng ra</h3>
      {s.state === "EXIT_GATE_OPEN" && <p className="muted">Cần ra đã mở lúc {formatTime(s.exit_gate_opened_at)}.</p>}
      {waitingAck && <p className="muted">Đã gửi lệnh mở, đang chờ gate-01 báo cần đã mở.</p>}
      <div className="actions-row">
        <ConfirmButton
          label={s.exit_command_id ? "Mở lại cần ra" : "Mở cần ra"}
          confirmLabel="Chắc chắn mở cần ra"
          disabled={open.pending}
          onConfirm={async () => {
            if (await open.run((key) => api.openExit(s.session_id, undefined, key))) onChanged();
          }}
        />
        {s.exit_command_id && (
          <ConfirmButton
            label="Xác nhận xe đã qua"
            confirmLabel="Chắc chắn xe đã qua cổng"
            className="secondary"
            disabled={confirm.pending}
            onConfirm={async () => {
              if (await confirm.run((key) => api.confirmPassage(s.session_id, undefined, key))) onChanged();
            }}
          />
        )}
      </div>
      {open.error && <p className="error-text">{open.error}</p>}
      {confirm.error && <p className="error-text">{confirm.error}</p>}
    </div>
  );
}

function RenewClaim({ s, onChanged }: { s: SessionDetail; onChanged: () => void }) {
  const [claim, setClaim] = useState<ActiveClaim>();
  const { run, pending, error } = useAction();

  return (
    <div>
      <h3>Mã QR của khách</h3>
      <p className="muted">Hết hạn lúc {formatTime(s.claim_expires_at)}. Cấp lại thì mã cũ hết hiệu lực ngay.</p>
      <button type="button" className="secondary" disabled={pending} onClick={async () => {
        const result = await run((key) => api.renewClaim(s.session_id, undefined, key));
        if (result) {
          setClaim(result);
          onChanged();
        }
      }}>
        {pending ? "Đang cấp…" : "Cấp lại mã QR"}
      </button>
      {error && <p className="error-text">{error}</p>}
      {claim && (
        <p className="copy-row">
          <a href={claim.claim_url} target="_blank" rel="noreferrer">{claim.claim_url}</a>
          <button type="button" className="secondary" onClick={() => navigator.clipboard?.writeText(claim.claim_url)}>Chép</button>
        </p>
      )}
    </div>
  );
}
