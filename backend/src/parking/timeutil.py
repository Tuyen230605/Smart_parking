"""Thời gian UTC: một định dạng ISO-8601 cố định để so sánh chuỗi trong DynamoDB."""
import re
from datetime import datetime, timezone

ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    """Luôn có mili giây và hậu tố Z, nên so sánh chuỗi tương đương so sánh thời gian."""
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(value) -> datetime:
    """Đọc timestamp từ thiết bị/DB; bắt buộc có múi giờ. Ném ValueError nếu sai định dạng."""
    if not isinstance(value, str) or not ISO_RE.fullmatch(value):
        raise ValueError("timestamp không đúng ISO-8601 có múi giờ")
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def from_epoch(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, timezone.utc)
