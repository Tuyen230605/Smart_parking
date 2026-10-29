"""Cấu hình đọc từ biến môi trường. Mặc định khớp docs/mqtt-contract.md và docs/api-contract.md."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Tables:
    slots: str
    sessions: str
    active_plates: str
    processed: str
    devices: str
    pricing: str


@dataclass(frozen=True)
class Config:
    site_id: str
    tables: Tables
    web_base_url: str = "http://localhost:5173"
    ses_sender: str = ""
    # Khóa HMAC ký QR: CLAIM_KEYS (chạy local/test) hoặc tên SSM SecureString CLAIM_KEYS_PARAM (AWS).
    claim_keys: str = ""
    claim_keys_param: str = ""
    iot_data_endpoint: str = ""
    plate_confidence_threshold: float = 0.85
    event_max_age_s: int = 60
    clock_skew_s: int = 30
    claim_ttl_s: int = 15 * 60
    gate_command_ttl_s: int = 5
    display_command_ttl_s: int = 15
    device_timeout_s: int = 90
    reservation_timeout_s: int = 5 * 60
    identity_retention_s: int = 10 * 24 * 3600
    # Purge chạy theo giờ nên bắt đầu xóa sớm hơn hạn 10 ngày một giờ.
    purge_lead_s: int = 3600
    processed_ttl_s: int = 7 * 24 * 3600

    @classmethod
    def from_env(cls, env=os.environ) -> "Config":
        return cls(
            site_id=env.get("SITE_ID", "site-01"),
            tables=Tables(
                slots=env["SLOTS_TABLE"],
                sessions=env["SESSIONS_TABLE"],
                active_plates=env["ACTIVE_PLATES_TABLE"],
                processed=env["PROCESSED_TABLE"],
                devices=env["DEVICES_TABLE"],
                pricing=env["PRICING_TABLE"],
            ),
            web_base_url=env.get("WEB_BASE_URL", cls.web_base_url).rstrip("/"),
            ses_sender=env.get("SES_SENDER", ""),
            claim_keys=env.get("CLAIM_KEYS", ""),
            claim_keys_param=env.get("CLAIM_KEYS_PARAM", ""),
            iot_data_endpoint=env.get("IOT_DATA_ENDPOINT", ""),
            plate_confidence_threshold=float(env.get("PLATE_CONFIDENCE_THRESHOLD", cls.plate_confidence_threshold)),
        )
