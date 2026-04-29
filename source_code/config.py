from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_URLS = ("http://127.0.0.1:6806", "http://localhost:6806")
LOCAL_CONFIG = "config.local.json"


@dataclass(frozen=True)
class Config:
    urls: tuple[str, ...]
    token: str | None
    root: Path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _coerce_urls(value: Any) -> tuple[str, ...]:
    if not value:
        return DEFAULT_URLS
    if isinstance(value, str):
        return (value.rstrip("/"),)
    if isinstance(value, list):
        urls = tuple(str(item).rstrip("/") for item in value if str(item).strip())
        return urls or DEFAULT_URLS
    raise ValueError("siyuan_url must be a string or siyuan_urls must be a list")


def load_config(root: Path | None = None) -> Config:
    project_root = (root or Path.cwd()).resolve()
    local = _read_json(project_root / LOCAL_CONFIG)

    env_url = os.environ.get("SIYUAN_URL")
    env_token = os.environ.get("SIYUAN_TOKEN")

    if env_url:
        urls = _coerce_urls(env_url)
    elif "siyuan_urls" in local:
        urls = _coerce_urls(local.get("siyuan_urls"))
    else:
        urls = _coerce_urls(local.get("siyuan_url"))

    token = env_token if env_token is not None else local.get("siyuan_token")
    token = str(token).strip() if token else None

    return Config(urls=urls, token=token, root=project_root)
