// Sơ đồ 18 ô công khai: chú thích màu, số ô trống mỗi tầng, nhãn cảm biến/mô phỏng, cảnh báo UNKNOWN.
import { api, type Slot } from "../../api";
import { FloorMap } from "../../components/FloorMap";
import { useLoad } from "../../components/useLoad";

const LEGEND: [string, string][] = [
  ["available", "Trống"],
  ["occupied", "Có xe"],
  ["unknown", "Chưa rõ (mất kết nối cảm biến)"],
];

export function LayoutPage() {
  const { data, error } = useLoad(() => api.getLayout(), [], 5_000);
  const slots = data?.slots ?? [];
  const free = (floor: number) => slots.filter((s) => s.slot_id.startsWith(`F${floor}`) && s.status === "AVAILABLE").length;
  const unknown = slots.filter((s) => s.status === "UNKNOWN").length;
  const updated = latest(slots);

  return (
    <main className="page">
      <h1>Sơ đồ bãi xe</h1>
      {error && <div className="card error">{error.message}</div>}
      {data && (
        <div className="stats">
          <div className="card"><b>{free(1) + free(2)}</b> ô trống</div>
          <div className="card"><b>{free(1)}</b> trống tầng 1</div>
          <div className="card"><b>{free(2)}</b> trống tầng 2</div>
        </div>
      )}
      {unknown > 0 && (
        <div className="card warn">{unknown} ô chưa rõ trạng thái — bảng nút bấm đang mất kết nối, tạm không gợi ý chỗ trống.</div>
      )}
      <div className="floors">
        <FloorMap floor={1} slots={slots} />
        <FloorMap floor={2} slots={slots} />
      </div>
      <div className="legend">
        {LEGEND.map(([k, label]) => (
          <span key={k}><i className={`swatch slot-${k}`} />{label}</span>
        ))}
      </div>
      <p className="muted">
        Cả 18 ô là nút bấm mô phỏng trên sa bàn.
        {updated && ` Cập nhật lúc ${new Date(updated).toLocaleTimeString("vi-VN")}.`}
      </p>
    </main>
  );
}

function latest(slots: Slot[]) {
  return slots.reduce<string | undefined>((m, s) => (!m || s.updated_at > m ? s.updated_at : m), undefined);
}
