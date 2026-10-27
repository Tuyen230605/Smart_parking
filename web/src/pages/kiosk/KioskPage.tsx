// Người 2: màn hình kiosk tại cổng vào. Khung chạy được; cần hoàn thiện theo docs/team-tasks.md.
import { api } from "../../api";
import { useLoad } from "../../components/useLoad";

export function KioskPage() {
  const { data, error } = useLoad(() => api.getActiveClaims(), [], 3_000);
  return (
    <main className="page">
      <h1>Kiosk cổng vào</h1>
      {error && <div className="card error">{error.message}</div>}
      <ul>
        {data?.map((c) => (
          <li key={c.session_ref}>
            {c.session_ref} → {c.slot_id} — <a href={c.claim_url}>{c.claim_url}</a>
          </li>
        ))}
      </ul>
      {/* TODO người 2: hiện QR lớn của phiên mới nhất (thư viện qrcode), ô + lộ trình, tự ẩn khi hết hạn. */}
    </main>
  );
}
