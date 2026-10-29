"""Hạ tầng HTTP API: đọc event API Gateway (payload 2.0), lỗi chuẩn, kiểm nhóm, đọc body."""
import base64
import json
import re
from dataclasses import dataclass, field

IDEMPOTENCY_KEY_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")
MAX_BODY_BYTES = 4096


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class Request:
    method: str
    path: str
    headers: dict
    body: str | None
    claims: dict | None  # None: request không qua JWT authorizer
    query: dict = field(default_factory=dict)

    @property
    def groups(self) -> set[str] | None:
        if self.claims is None:
            return None
        raw = self.claims.get("cognito:groups", "")
        # HTTP API chuyển mảng trong JWT thành chuỗi dạng "[ADMIN KIOSK]".
        return set(raw) if isinstance(raw, list) else {g for g in re.split(r"[\s,\[\]]+", raw) if g}

    @property
    def actor(self) -> dict:
        claims = self.claims or {}
        return {"actor_id": claims.get("sub", "unknown"),
                "actor": claims.get("username") or claims.get("cognito:username") or ""}


def parse_event(event: dict) -> Request:
    ctx = event.get("requestContext", {})
    path = event.get("rawPath") or "/"
    stage = ctx.get("stage")
    if stage and stage != "$default" and path.startswith(f"/{stage}/"):
        path = path[len(stage) + 1:]
    body = event.get("body")
    if body is not None and event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8", errors="replace")
    return Request(
        method=ctx.get("http", {}).get("method", "GET").upper(),
        path=path.rstrip("/") or "/",
        headers={k.lower(): v for k, v in (event.get("headers") or {}).items()},
        body=body,
        claims=ctx.get("authorizer", {}).get("jwt", {}).get("claims"),
        query=event.get("queryStringParameters") or {},
    )


def response(status: int, body) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json; charset=utf-8", "cache-control": "no-store"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def authorize(req: Request, roles: set[str]):
    if req.groups is None:
        raise ApiError(401, "UNAUTHENTICATED", "Cần đăng nhập")
    if not req.groups & roles:
        raise ApiError(403, "FORBIDDEN", "Tài khoản không có quyền này")


def idempotency_key(req: Request) -> str:
    key = req.headers.get("idempotency-key", "")
    if not IDEMPOTENCY_KEY_RE.fullmatch(key):
        raise ApiError(400, "INVALID_INPUT", "Thiếu header Idempotency-Key hợp lệ")
    return key


def json_body(req: Request, optional: bool = False) -> dict:
    if not req.body:
        if optional:
            return {}
        raise ApiError(400, "INVALID_INPUT", "Thiếu body JSON")
    if len(req.body.encode()) > MAX_BODY_BYTES:
        raise ApiError(400, "INVALID_INPUT", "Body quá lớn")
    try:
        body = json.loads(req.body)
    except ValueError:
        raise ApiError(400, "INVALID_INPUT", "Body không phải JSON") from None
    if not isinstance(body, dict):
        raise ApiError(400, "INVALID_INPUT", "Body phải là object JSON")
    return body


def text_field(body: dict, name: str, required: bool = False, max_len: int = 200) -> str | None:
    value = body.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ApiError(400, "INVALID_INPUT", f"Thiếu {name}")
        return None
    if not isinstance(value, str) or len(value) > max_len:
        raise ApiError(400, "INVALID_INPUT", f"{name} phải là chuỗi tối đa {max_len} ký tự")
    return value.strip()
