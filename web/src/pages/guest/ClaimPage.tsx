// Người 1: trang khách mở từ QR phiên (UC-01, UC-02). Chỉ hiện ô/lộ trình của phiên, không hiện biển số.
import { useEffect, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError, type Claim } from "../../api";
import { FloorMap, floorOf } from "../../components/FloorMap";
import { useLoad } from "../../components/useLoad";

const CLAIM_ERRORS: Partial<Record<string, string>> = {
  TOKEN_EXPIRED: "Mã QR đã hết hạn. Vui lòng nhờ nhân viên cấp lại mã tại cổng.",
  NOT_FOUND: "Không tìm thấy lượt gửi xe của mã QR này.",
  NETWORK_ERROR: "Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.",
};

const EMAIL_ERRORS: Partial<Record<string, string>> = {
  INVALID_INPUT: "Email không hợp lệ hoặc chưa đồng ý nhận email.",
  EMAIL_ALREADY_SENT: "Lượt gửi xe này đã gửi email hướng dẫn rồi.",
  TOKEN_EXPIRED: "Mã QR đã hết hạn, không thể gửi email nữa.",
  RATE_LIMITED: "Bạn thao tác quá nhanh, thử lại sau ít phút.",
  NETWORK_ERROR: "Không kết nối được máy chủ. Thử gửi lại.",
};

export function ClaimPage() {
  const { token = "" } = useParams();
  const { data: claim, error, loading, setData } = useLoad(() => api.getClaim(token), [token]);

  if (loading) return <main className="page narrow"><p>Đang tải thông tin chỗ đỗ…</p></main>;
  if (error || !claim) {
    return (
      <main className="page narrow">
        <div className="card error">{CLAIM_ERRORS[error?.code ?? ""] ?? error?.message}</div>
      </main>
    );
  }

  return (
    <main className="page narrow">
      <section className="card">
        <p className="muted">Mã lượt {claim.session_ref}</p>
        <h1 className="slot-id">{claim.slot_id}</h1>
        <ol className="route">
          {claim.route_steps.map((step) => <li key={step}>{step}</li>)}
        </ol>
        <Countdown until={claim.claim_expires_at} />
      </section>

      <section className="card">
        <FloorMap floor={floorOf(claim.slot_id)} highlight={claim.slot_id} />
      </section>

      <EmailForm token={token} claim={claim} onSent={() => setData({ ...claim, email_submitted: true })} />
    </main>
  );
}

function Countdown({ until }: { until: string }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  const left = Math.max(0, Math.floor((Date.parse(until) - now) / 1000));
  if (left === 0) return <p className="muted">Trang này đã hết hạn; lộ trình ở trên vẫn đúng cho lượt của bạn.</p>;
  const mm = String(Math.floor(left / 60)).padStart(2, "0");
  const ss = String(left % 60).padStart(2, "0");
  return <p className="muted">Trang có hiệu lực thêm {mm}:{ss}</p>;
}

function EmailForm({ token, claim, onSent }: { token: string; claim: Claim; onSent: () => void }) {
  const [email, setEmail] = useState("");
  const [consent, setConsent] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string>();
  // Giữ cùng key khi bấm gửi lại sau lỗi mạng để backend không gửi trùng.
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());

  if (claim.email_submitted) {
    return (
      <section className="card success">
        Đã nhận yêu cầu gửi email hướng dẫn cho lượt này. Nếu không thấy, hãy kiểm tra thư rác.
      </section>
    );
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSending(true);
    setError(undefined);
    try {
      await api.submitClaimEmail(token, email.trim(), consent, idempotencyKey);
      onSent();
    } catch (err) {
      const apiErr = err instanceof ApiError ? err : undefined;
      if (apiErr?.code === "EMAIL_ALREADY_SENT") return onSent();
      if (apiErr?.code === "INVALID_INPUT") setIdempotencyKey(crypto.randomUUID());
      setError(EMAIL_ERRORS[apiErr?.code ?? ""] ?? apiErr?.message ?? "Có lỗi xảy ra.");
    } finally {
      setSending(false);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h2>Nhận chỉ dẫn qua email (không bắt buộc)</h2>
      <label>
        Email
        <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="ban@example.com" autoComplete="email" />
      </label>
      <label className="check">
        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} required />
        <span>Tôi đồng ý nhận một email hướng dẫn cho lượt gửi xe này. Email được xóa sau tối đa 10 ngày và không dùng cho lượt sau.</span>
      </label>
      {error && <p className="error-text">{error}</p>}
      <button type="submit" disabled={sending}>{sending ? "Đang gửi…" : "Gửi email"}</button>
    </form>
  );
}
