// Bản đồ một tầng có vẽ đường đi từ cổng vào (vị trí xe lúc mới qua cần) đến ô đích, theo docs/parking-layout.md:
// lối chính chạy dọc bên trái từ cổng, mỗi hàng A/B/C có lối đi ngang ngay dưới hàng ô, cuối lối C là ram lên tầng 2.
// Ô đích ở tầng 2 → bản đồ tầng 1 vẽ đường tới ram và ghi "Lên tầng 2", bản đồ tầng 2 vẽ tiếp từ đầu ram tới ô.
import type { Slot } from "../api";

const ROWS = ["A", "B", "C"] as const;
const COLS = [1, 2, 3] as const;
const LANE_X = 40;
const START_Y = 34;
const COL_X: Record<number, number> = { 1: 130, 2: 230, 3: 330 };
const SLOT_W = 80;
const SLOT_H = 44;
const ROW_TOP: Record<string, number> = { A: 44, B: 120, C: 196 };
const AISLE_Y: Record<string, number> = { A: 104, B: 180, C: 256 };
const RAMP_X = 388;

interface Props {
  floor: 1 | 2;
  slots?: Slot[];
  target?: string | null;
  onSelect?: (slotId: string) => void;
}

/** Ô có thể chọn: đang trống, hoặc chưa rõ (board ô mất kết nối thì không chặn khách chọn). */
export function selectable(slot?: Slot) {
  return !slot || slot.status === "AVAILABLE" || slot.status === "UNKNOWN";
}

export function routeSteps(slotId: string): string[] {
  const floor = slotId[1], row = slotId[3], col = slotId[4];
  if (floor === "1") {
    return ["Qua cổng vào, đi theo lối chính bên trái", `Rẽ phải vào lối đi hàng ${row}`, `Ô ${slotId} ở cột ${col}, phía trên lối đi`];
  }
  return [
    "Qua cổng vào, đi theo lối chính bên trái đến cuối lối C",
    "Đi hết lối C, LÊN RAM lên tầng 2",
    `Tầng 2: đi theo lối chính, rẽ phải vào lối đi hàng ${row}`,
    `Ô ${slotId} ở cột ${col}, phía trên lối đi`,
  ];
}

function pathTo(slotId: string, floor: 1 | 2): string | null {
  const tFloor = Number(slotId[1]);
  if (floor === 1 && tFloor === 2) {
    return `M${LANE_X},${START_Y} L${LANE_X},${AISLE_Y.C} L${RAMP_X - 6},${AISLE_Y.C}`;
  }
  if (floor !== tFloor) return null;
  const row = slotId[3], x = COL_X[Number(slotId[4])];
  return `M${LANE_X},${START_Y} L${LANE_X},${AISLE_Y[row]} L${x},${AISLE_Y[row]} L${x},${ROW_TOP[row] + SLOT_H + 4}`;
}

export function RouteMap({ floor, slots = [], target, onSelect }: Props) {
  const byId = new Map(slots.map((s) => [s.slot_id, s]));
  const path = target ? pathTo(target, floor) : null;
  const toRamp = floor === 1 && target?.startsWith("F2");
  return (
    <figure className="route-map">
      <figcaption>Tầng {floor}{toRamp && <b className="ramp-note"> → đi tiếp lên tầng 2</b>}</figcaption>
      <svg viewBox="0 0 420 290" role="img" aria-label={`Bản đồ tầng ${floor}${target ? `, đường đến ${target}` : ""}`}>
        <defs>
          <marker id={`arrow-${floor}`} viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" className="route-arrow" />
          </marker>
        </defs>
        {/* lối chính + lối đi từng hàng */}
        <line x1={LANE_X} y1={START_Y} x2={LANE_X} y2={AISLE_Y.C} className="aisle" />
        {ROWS.map((r) => <line key={r} x1={LANE_X} y1={AISLE_Y[r]} x2={RAMP_X} y2={AISLE_Y[r]} className="aisle" />)}
        <rect x={LANE_X - 30} y={4} width={60} height={22} rx={4} className="gate" />
        <text x={LANE_X} y={19} className="gate-label">{floor === 1 ? "CỔNG VÀO" : "TỪ RAM"}</text>
        {floor === 1 ? (
          <text x={RAMP_X} y={AISLE_Y.C + 20} className="ramp-label">ram ↑ T2</text>
        ) : (
          <text x={RAMP_X} y={AISLE_Y.C + 20} className="ramp-label">ram ↓ ra</text>
        )}
        {ROWS.flatMap((r) =>
          COLS.map((c) => {
            const id = `F${floor}-${r}${c}`;
            const slot = byId.get(id);
            const status = slot?.status.toLowerCase() ?? "unknown";
            const canPick = !!onSelect && selectable(slot);
            const cls = ["map-slot", `map-${status}`, id === target ? "map-target" : "", canPick ? "map-pickable" : ""].join(" ");
            return (
              <g key={id} className={cls} onClick={canPick ? () => onSelect(id) : undefined}>
                <rect x={COL_X[c] - SLOT_W / 2} y={ROW_TOP[r]} width={SLOT_W} height={SLOT_H} rx={6} />
                <text x={COL_X[c]} y={ROW_TOP[r] + SLOT_H / 2 + 5}>{id}</text>
              </g>
            );
          }),
        )}
        {path && <path d={path} className="route-line" markerEnd={`url(#arrow-${floor})`} />}
      </svg>
    </figure>
  );
}
