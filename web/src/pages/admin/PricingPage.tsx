import { useEffect, useState, type FormEvent } from "react";
import { api, type PricingRules } from "../../api";
import { computeFee, formatTime, formatVnd } from "./format";
import { ErrorCard, useAdminLoad } from "./shared";
import { useAction } from "./useAction";

const FIELDS: [keyof PricingRules, string, string][] = [
  ["free_minutes", "Miễn phí dưới (phút)", "0–1440"],
  ["first_block_minutes", "Khối đầu đến hết (phút)", "1–1440"],
  ["first_block_vnd", "Giá khối đầu (₫)", "0–10.000.000"],
  ["extra_hour_vnd", "Mỗi giờ tiếp theo bắt đầu (₫)", "0–10.000.000"],
];
const EXAMPLE_MINUTES = [10, 30, 60, 61, 125, 240];

export function PricingPage() {
  const { data, error, setData } = useAdminLoad(() => api.getPricing(), []);
  const [rules, setRules] = useState<PricingRules>();
  const [reason, setReason] = useState("");
  const { run, pending, error: saveError } = useAction();
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (data) setRules({ free_minutes: data.free_minutes, first_block_minutes: data.first_block_minutes,
      first_block_vnd: data.first_block_vnd, extra_hour_vnd: data.extra_hour_vnd });
  }, [data]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!rules) return;
    setSaved(false);
    const result = await run((key) => api.updatePricing({ ...rules, reason: reason.trim() || undefined }, key));
    if (result) {
      setData(result);
      setReason("");
      setSaved(true);
    }
  }

  return (
    <>
      <ErrorCard error={error} />
      {data && rules && (
        <div className="detail-grid">
          <form className="card" onSubmit={submit}>
            <h2>Bảng giá version {data.version}</h2>
            <p className="muted">
              {data.updated_at ? `Sửa lần cuối ${formatTime(data.updated_at)}.` : "Đang dùng giá mặc định."} Xe đang
              trong bãi giữ giá lúc vào; giá mới áp dụng cho lượt vào sau khi lưu.
            </p>
            <div className="form-grid">
              {FIELDS.map(([name, label, range]) => (
                <label key={name}>
                  {label}
                  <input type="number" required min={0} step={1} title={range} value={rules[name]}
                    onChange={(e) => setRules({ ...rules, [name]: Number(e.target.value) })} />
                </label>
              ))}
            </div>
            <label>
              Lý do (không bắt buộc)
              <input type="text" maxLength={200} value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
            {saveError && <p className="error-text">{saveError}</p>}
            {saved && <p className="muted">Đã lưu version {data.version}.</p>}
            <button type="submit" disabled={pending}>{pending ? "Đang lưu…" : "Lưu bảng giá"}</button>
          </form>
          <section className="card">
            <h2>Xem trước</h2>
            <table>
              <thead><tr><th>Thời gian gửi</th><th>Phí</th></tr></thead>
              <tbody>
                {EXAMPLE_MINUTES.map((m) => (
                  <tr key={m}><td>{m} phút</td><td>{formatVnd(computeFee(rules, m))}</td></tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      )}
    </>
  );
}
