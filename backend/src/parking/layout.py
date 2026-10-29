"""18 ô theo docs/parking-layout.md: ID, nguồn tín hiệu, thứ tự ưu tiên và lộ trình."""
import re

FLOORS = (1, 2)
ROWS = ("A", "B", "C")
COLS = (1, 2, 3)

# Thứ tự cũng là độ ưu tiên gán ô: tầng 1 trước, hàng A → C, cột 1 → 3.
SLOT_IDS = tuple(f"F{f}-{r}{c}" for f in FLOORS for r in ROWS for c in COLS)
SENSOR_SLOT = "F1-A1"
SLOT_RE = re.compile(r"F([12])-([ABC])([123])")


def source_of(slot_id: str) -> str:
    return "SENSOR" if slot_id == SENSOR_SLOT else "BUTTON"


def _parts(slot_id: str) -> tuple[int, str, int]:
    floor, row, col = SLOT_RE.fullmatch(slot_id).groups()
    return int(floor), row, int(col)


def route_steps(slot_id: str) -> list[str]:
    """Lộ trình đầy đủ cho web/email; giống routeSteps trong web/src/api/mock.ts."""
    floor, row, col = _parts(slot_id)
    return ["Tầng 1" if floor == 1 else f"Lên ram tầng {floor}", f"Đi đến hàng {row}", f"Ô số {col}"]


def oled_route_lines(slot_id: str) -> list[str]:
    """Bản rút gọn ASCII ≤ 20 ký tự/dòng cho OLED."""
    floor, row, col = _parts(slot_id)
    second = f"Tang 1 - Hang {row}" if floor == 1 else f"Len tang {floor} - Hang {row}"
    return [f"VAO: {slot_id}", second, f"O so {col}"]
