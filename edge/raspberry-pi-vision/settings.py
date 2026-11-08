"""Đọc config.toml rồi ghi đè bằng config.local.toml (nếu có) cùng thư mục.

config.local.toml do infra/aws/provision-devices.sh sinh ra, chứa endpoint AWS IoT và đường dẫn cert;
không commit file này.
"""
import tomllib
from pathlib import Path


def _merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path="config.toml"):
    path = Path(path)
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    local = path.with_name("config.local.toml")
    if local.exists():
        with open(local, "rb") as f:
            _merge(cfg, tomllib.load(f))
    return cfg
