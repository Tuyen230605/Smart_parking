// Sơ đồ một tầng 3×3 theo docs/parking-layout.md. Dùng chung cho trang khách (tô ô được gán)
// và trang sơ đồ công khai (tô theo trạng thái). Người 3 sở hữu component này.
import type { Slot } from "../api";

const ROWS = ["A", "B", "C"];
const COLS = [1, 2, 3];

interface Props {
  floor: 1 | 2;
  slots?: Slot[];
  highlight?: string;
}

export function FloorMap({ floor, slots = [], highlight }: Props) {
  const byId = new Map(slots.map((s) => [s.slot_id, s]));
  return (
    <figure className="floor">
      <figcaption>Tầng {floor}</figcaption>
      <div className="floor-grid">
        {ROWS.flatMap((row) =>
          COLS.map((col) => {
            const id = `F${floor}-${row}${col}`;
            const slot = byId.get(id);
            const classes = ["slot", slot ? `slot-${slot.status.toLowerCase()}` : "", id === highlight ? "slot-target" : ""];
            return (
              <div key={id} className={classes.join(" ")} title={slot ? `${id}: ${slot.status}` : id}>
                {id}
                {slot?.source === "SENSOR" && <small>cảm biến</small>}
              </div>
            );
          }),
        )}
      </div>
    </figure>
  );
}

export function floorOf(slotId: string): 1 | 2 {
  return slotId.startsWith("F2") ? 2 : 1;
}
