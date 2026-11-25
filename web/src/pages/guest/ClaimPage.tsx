// Người 1: trang khách mở từ QR phiên (UC-01, UC-02). Không gán ô: gợi ý ô trống gần nhất, khách chạm chọn
// ô trống bất kỳ trên bản đồ và xem đường đi vẽ từ cổng vào đến ô (ô tầng 2 có bước lên ram). Không hiện biển số.
import { useEffect, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError, type Claim, type Slot } from "../../api";
import { RouteMap, routeSteps } from "../../components/RouteMap";
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
  const layout = useLoad(() => api.getLayout(), [], 5_000);
  const [picked, setPicked] = useState<string | null>(null);

  if (loading) return <main className="page narrow"><p>Đang tải thông tin chỗ đỗ…</p></main>;
  if (error || !claim) {
    return (
      <main className="page narrow">
        <div className="card error">{CLAIM_ERRORS[error?.code ?? ""] ?? error?.message}</div>
      </main>
    );
  }
  const target = picked ?? claim.slot_id;

  return (
    <main className="page narrow">
      <section className="card">
        <p className="muted">Mã lượt {claim.session_ref}</p>
        <Guide claim={claim} picked={picked} />
        <Countdown until={claim.claim_expires_at} />
      </section>

      <section className="card">
        <p className="muted">Chạm vào một ô trống (viền xanh) để chọn chỗ và xem đường đi từ cổng vào.</p>
        <RouteMaps slots={layout.data?.slots ?? []} target={target} onSelect={setPicked} />
      </section>

      <EmailForm token={token} claim={claim} slotId={target} onSent={(remember, email) => setData({
        ...claim, email_submitted: true,
        linked_email: remember ? `${email.slice(0, 2)}***@${email.split("@")[1]}` : claim.linked_email,
      })} />
      {claim.linked_email && <LinkedEmail token={token} masked={claim.linked_email} onForget={() => setData({ ...claim, linked_email: null })} />}
    </main>
  );
}

/** Ô đang chọn (hoặc gợi ý ô trống gần cổng nhất) + các bước đi. Chỉ là chỉ đường, không giữ chỗ. */
export function Guide({ claim, picked = null }: {
  claim: { slot_id: string | null; free_count?: number | null };
  picked?: string | null;
}) {
  const target = picked ?? claim.slot_id;
  if (!target) {
    return (
      <p className="slot-hint">
        {claim.free_count === 0 ? "Bãi đang đầy." : "Chọn một ô trống trên bản đồ bên dưới."}
      </p>
    );
  }
  return (
    <>
      <p className="muted">{picked ? "Ô bạn chọn" : "Gợi ý: ô trống gần cổng nhất (bạn có thể chọn ô khác)"}</p>
      <h1 className="slot-id">{target}</h1>
      <ol className="route">
        {routeSteps(target).map((step) => <li key={step}>{step}</li>)}
      </ol>
      {claim.free_count != null && <p className="muted">Còn {claim.free_count} chỗ trống</p>}
    </>
  );
}

/** Tầng 1 luôn hiện (đường từ cổng); thêm tầng 2 khi ô đích ở tầng 2 hoặc khi khách đang chọn ô. */
export function RouteMaps({ slots, target, onSelect }: { slots: Slot[]; target: string | null; onSelect?: (id: string) => void }) {
  const showF2 = !!onSelect || !!target?.startsWith("F2");
  return (
    <div className="floors">
      <RouteMap floor={1} slots={slots} target={target} onSelect={onSelect} />
      {showF2 && <RouteMap floor={2} slots={slots} target={target} onSelect={onSelect} />}
    </div>
  );
}

function Countdown({ until }: { until: string }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  const left = Math.max(0, Math.floor((Date.parse(until) - now) / 1000));
  if (left === 0) return <p className="muted">Trang này đã hết hạn.</p>;
  const mm = String(Math.floor(left / 60)).padStart(2, "0");
  const ss = String(left % 60).padStart(2, "0");
  return <p className="muted">Trang có hiệu lực thêm {mm}:{ss}</p>;
}

/** Biển số đã liên kết email: chỉ dẫn tự gửi mỗi lần xe vào. Khách có thể bỏ liên kết ngay tại đây. */
function LinkedEmail({ token, masked, onForget }: { token: string; masked: string; onForget: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  async function forget() {
    setBusy(true);
    setError(undefined);
    try {
      await api.forgetClaimEmail(token);
      onForget();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Có lỗi xảy ra.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card">
      <p>Biển số xe này đang liên kết email <b>{masked}</b>: mỗi lần xe vào bãi, chỉ dẫn được tự gửi, không cần quét mã.</p>
      {error && <p className="error-text">{error}</p>}
      <button className="secondary" disabled={busy} onClick={forget}>Bỏ liên kết email</button>
    </section>
  );
}

function EmailForm({ token, claim, slotId, onSent }: {
  token: string; claim: Claim; slotId: string | null; onSent: (remember: boolean, email: string) => void;
}) {
  const [remember, setRemember] = useState(false);
  const [email, setEmail] = useState("");
  const [consent, setConsent] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string>();
  // Giữ cùng key khi bấm gửi lại sau lỗi mạng để backend không gửi trùng.
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());

  if (claim.email_submitted) {
    return (
      <section className="card success">
        {claim.email_auto
          ? "Chỉ dẫn đã được tự gửi tới email liên kết với biển số xe này."
          : "Đã nhận yêu cầu gửi email hướng dẫn cho lượt này."} Nếu không thấy, hãy kiểm tra thư rác.
      </section>
    );
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSending(true);
    setError(undefined);
    try {
      await api.submitClaimEmail(token, email.trim(), consent, idempotencyKey, slotId, remember);
      onSent(remember, email.trim());
    } catch (err) {
      const apiErr = err instanceof ApiError ? err : undefined;
      if (apiErr?.code === "EMAIL_ALREADY_SENT") return onSent(false, email);
      if (apiErr?.code === "INVALID_INPUT") setIdempotencyKey(crypto.randomUUID());
      setError(EMAIL_ERRORS[apiErr?.code ?? ""] ?? apiErr?.message ?? "Có lỗi xảy ra.");
    } finally {
      setSending(false);
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h2>Nhận chỉ dẫn qua email (không bắt buộc)</h2>
      {slotId && <p className="muted">Email sẽ ghi đường đến ô <b>{slotId}</b>.</p>}
      <label>
        Email
        <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="ban@example.com" autoComplete="email" />
      </label>
      <label className="check">
        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} required />
        <span>Tôi đồng ý nhận một email hướng dẫn cho lượt gửi xe này.</span>
      </label>
      <label className="check">
        <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
        <span>
          Ghi nhớ email cho biển số xe này (không bắt buộc): lần sau xe vào bãi sẽ <b>tự gửi chỉ dẫn</b>, không cần quét mã.
          Hủy bất kỳ lúc nào bằng link trong email hoặc nút "Bỏ liên kết". Không chọn thì email bị xóa sau tối đa 10 ngày.
        </span>
      </label>
      {error && <p className="error-text">{error}</p>}
      <button type="submit" disabled={sending}>{sending ? "Đang gửi…" : "Gửi email"}</button>
    </form>
  );
}
