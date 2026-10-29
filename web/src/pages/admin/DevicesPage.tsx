import { api, type DeviceView } from "../../api";
import { formatTime } from "./format";
import { ErrorCard, useAdminLoad } from "./shared";

const DEVICE_NAMES: Record<DeviceView["device_id"], string> = {
  "pi-01": "Raspberry Pi + camera",
  "gate-01": "ESP32 cổng (2 cần + OLED)",
  "slots-01": "ESP32 ô (1 cảm biến + 17 nút)",
};

export function DevicesPage() {
  const { data, error } = useAdminLoad(() => api.getDevices(), [], 5_000);
  return (
    <>
      <ErrorCard error={error} />
      <p className="muted" style={{ marginBottom: 12 }}>Thiết bị offline khi quá 90 giây không gửi tin. Tự làm mới mỗi 5 giây.</p>
      {data?.devices.map((d) => (
        <section key={d.device_id} className="card">
          <div className="admin-head" style={{ marginBottom: 8 }}>
            <h2 style={{ margin: 0 }}>{d.device_id} <span className="muted">· {DEVICE_NAMES[d.device_id]}</span></h2>
            <span className={`badge ${d.online ? "badge-ok" : "badge-bad"}`}>{d.online ? "Online" : "Offline"}</span>
          </div>
          <dl className="facts">
            <dt>Trạng thái báo về</dt><dd>{d.state ?? "—"}</dd>
            <dt>Tin gần nhất</dt><dd>{formatTime(d.last_seen_at)}</dd>
            <dt>Firmware</dt><dd>{d.firmware_version ?? "—"}</dd>
            {d.gates && (["ENTRY", "EXIT"] as const).map((gate) => (
              <div key={gate} style={{ display: "contents" }}>
                <dt>Cần {gate === "ENTRY" ? "vào" : "ra"}</dt>
                <dd>
                  {d.gates![gate].state ?? "chưa có tin"}
                  {d.gates![gate].error_code && <> <span className="badge badge-bad">{d.gates![gate].error_code}</span></>}
                  {d.gates![gate].updated_at && <span className="muted"> · {formatTime(d.gates![gate].updated_at)}</span>}
                </dd>
              </div>
            ))}
            {d.display && (
              <>
                <dt>OLED</dt>
                <dd>{d.display.state ?? "chưa có tin"}{d.display.updated_at && <span className="muted"> · {formatTime(d.display.updated_at)}</span>}</dd>
              </>
            )}
            {d.device_id === "slots-01" && (
              <>
                <dt>Snapshot 18 ô</dt>
                <dd>
                  {formatTime(d.last_snapshot_at)}{" "}
                  <span className={`badge ${d.snapshot_fresh ? "badge-ok" : "badge-bad"}`}>
                    {d.snapshot_fresh ? "Còn mới" : "Cũ: mọi ô UNKNOWN"}
                  </span>
                </dd>
              </>
            )}
          </dl>
        </section>
      ))}
    </>
  );
}
