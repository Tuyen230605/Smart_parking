"""Ghép phụ thuộc cho Lambda (DynamoDB, IoT, SES, khóa QR). Test thay bằng bản giả."""
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol

import boto3

from .claims import KeyRing
from .config import Config
from .store import Db
from .timeutil import utc_now


class Publisher(Protocol):
    def publish(self, topic: str, payload: dict) -> None: ...


class Mailer(Protocol):
    def send(self, to: str, subject: str, text: str) -> str: ...


class IotPublisher:
    def __init__(self, endpoint: str = ""):
        self.client = boto3.client("iot-data", **({"endpoint_url": endpoint} if endpoint else {}))

    def publish(self, topic: str, payload: dict) -> None:
        self.client.publish(topic=topic, qos=1, payload=json.dumps(payload, ensure_ascii=False).encode())


class SesMailer:
    def __init__(self, sender: str):
        self.sender = sender
        self.client = boto3.client("sesv2")

    def send(self, to: str, subject: str, text: str) -> str:
        r = self.client.send_email(
            FromEmailAddress=self.sender,
            Destination={"ToAddresses": [to]},
            Content={"Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": text, "Charset": "UTF-8"}},
            }},
        )
        return r["MessageId"]


@dataclass
class App:
    cfg: Config
    db: Db
    publisher: Publisher
    mailer: Mailer
    keys: KeyRing
    clock: Callable[[], datetime] = utc_now


def _ssm_loader(name: str) -> Callable[[], str]:
    def load() -> str:
        return boto3.client("ssm").get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    return load


def build_app(env=os.environ) -> App:
    cfg = Config.from_env(env)
    load = (lambda: cfg.claim_keys) if cfg.claim_keys else _ssm_loader(cfg.claim_keys_param)
    return App(cfg, Db(), IotPublisher(cfg.iot_data_endpoint), SesMailer(cfg.ses_sender), KeyRing(load))


_app: App | None = None


def get_app() -> App:
    """Tạo một lần cho mỗi container Lambda để tái dùng kết nối boto3."""
    global _app
    if _app is None:
        _app = build_app()
    return _app
