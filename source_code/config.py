from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .client import SiYuanApiError, SiYuanClient, SiYuanConnectionError

LOCAL_CONFIG = "config.local.json"

ENV_TOKEN = "SIYUAN_TOKEN"
ENV_LANGUAGE = "SIYUAN_AGENT_LANGUAGE"

# SiYuan always starts on 6806 by default. The token is what identifies the workspace.
DEFAULT_URLS = ("http://127.0.0.1:6806", "http://localhost:6806")


@dataclass(frozen=True)
class Profile:
    name: str
    token: str


@dataclass(frozen=True)
class Config:
    profiles: tuple[Profile, ...]
    language: str
    root: Path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def load_config(root: Path | None = None) -> Config:
    project_root = (root or Path.cwd()).resolve()
    local = _read_json(project_root / LOCAL_CONFIG)

    env_lang = os.environ.get(ENV_LANGUAGE)
    language = env_lang if env_lang else str(local.get("language", "") or "")

    env_token = os.environ.get(ENV_TOKEN)
    profiles_raw = local.get("profiles")

    if env_token:
        profiles = (Profile(name="ENV", token=env_token),)
    elif profiles_raw and isinstance(profiles_raw, list):
        profiles = tuple(
            Profile(name=str(p.get("name", f"Profile {i + 1}")), token=str(p.get("token", "")))
            for i, p in enumerate(profiles_raw)
            if isinstance(p, dict) and p.get("token")
        )
    elif local.get("siyuan_token"):
        profiles = (Profile(name="默认", token=str(local["siyuan_token"])),)
    else:
        profiles = ()

    return Config(profiles=profiles, language=language, root=project_root)


def detect_active_profile(config: Config) -> tuple[Profile, SiYuanClient]:
    """Try each profile's token against default SiYuan ports.

    Since SiYuan only allows one workspace online at a time, the first
    token that responds correctly identifies the active workspace.
    """
    if not config.profiles:
        raise SiYuanConnectionError(
            "没有配置任何思源工作空间。请在 config.local.json 的 profiles 中添加至少一个工作空间。"
        )

    errors: list[str] = []

    for profile in config.profiles:
        for url in DEFAULT_URLS:
            client = SiYuanClient(url, token=profile.token)
            try:
                client.list_notebooks()
                return profile, client
            except (SiYuanConnectionError, SiYuanApiError) as exc:
                errors.append(f"{profile.name} ({url}): {exc}")

    raise SiYuanConnectionError(
        "思源笔记似乎没有启动，或所有配置的工作空间 token 都不可达。"
        + ("\n尝试过的连接：" + "; ".join(errors) if errors else "")
    )
