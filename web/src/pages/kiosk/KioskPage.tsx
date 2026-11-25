// Màn hình kiosk tại cổng vào: QR lớn của phiên mới nhất + gợi ý ô trống gần nhất; tự ẩn khi QR hết hạn.
import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { api, type ActiveClaim } from "../../api";
import { RequireAuth } from "../../components/RequireAuth";
import { useLoad } from "../../components/useLoad";
import { Guide, RouteMaps } from "../guest/ClaimPage";

export function KioskPage() {
  return (
    <RequireAuth groups={["KIOSK", "ADMIN"]}>
      <Kiosk />
    </RequireAuth>
  );
}

function Kiosk() {
  const { data, error } = useLoad(() => api.getActiveClaims(), [], 2_000);
  const now = useNow();
  const live = (data ?? []).filter((c) => Date.parse(c.claim_expires_at) > now);
  const [latest, ...others] = live;

  return (
    <main className="page kiosk">
      <div className="kiosk-head">
        <h1>Quét mã để xem chỗ trống</h1>
        <button className="secondary" onClick={() => document.documentElement.requestFullscreen?.()}>Toàn màn hình</button>
      </div>
      {error && <div className="card error">{error.message}</div>}
      {latest ? <BigClaim claim={latest} now={now} /> : <div className="card kiosk-idle">Mời xe tiếp theo vào làn</div>}
      {others.length > 0 && (
        <p className="muted">
          Lượt khác còn hiệu lực: {others.map((c) => c.session_ref).join(" · ")}
        </p>
      )}
    </main>
  );
}

function BigClaim({ claim, now }: { claim: ActiveClaim; now: number }) {
  const layout = useLoad(() => api.getLayout(), [], 5_000);
  const [svg, setSvg] = useState("");
  useEffect(() => {
    QRCode.toString(claim.claim_url, { type: "svg", margin: 1, errorCorrectionLevel: "M" }).then(setSvg);
  }, [claim.claim_url]);
  const left = Math.max(0, Math.floor((Date.parse(claim.claim_expires_at) - now) / 1000));

  return (
    <section className="card kiosk-claim">
      <div className="qr" dangerouslySetInnerHTML={{ __html: svg }} aria-label="Mã QR lượt gửi xe" />
      <div>
        <p className="muted">Mã lượt {claim.session_ref}</p>
        <Guide claim={claim} />
        <RouteMaps slots={layout.data?.slots ?? []} target={claim.slot_id} />
        <p className="muted">Quét bằng camera điện thoại · nhận chỉ dẫn qua email nếu muốn · còn {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}</p>
      </div>
    </section>
  );
}

function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}
