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
        raise ValueError(f"{path} 必须包含一个 JSON 对象")
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

    connection_errors: list[str] = []
    token_errors: list[str] = []
    api_errors: list[str] = []

    for profile in config.profiles:
        for url in DEFAULT_URLS:
            client = SiYuanClient(url, token=profile.token)
            try:
                client.list_notebooks()
                return profile, client
            except SiYuanConnectionError as exc:
                connection_errors.append(f"{profile.name} ({url}): {exc}")
            except SiYuanApiError as exc:
                detail = f"{profile.name} ({url}): {exc}"
                if _looks_like_token_error(exc):
                    token_errors.append(detail)
                else:
                    api_errors.append(detail)

    if token_errors and not api_errors:
        raise SiYuanConnectionError(
            "思源 API 可达，但所有已配置工作空间 token 都不可用。"
            "可能打开了未配置的思源工作空间，或当前工作空间 Token 尚未加入 profiles。"
            "请在思源桥插件设置页添加当前工作空间 Token 后重试。"
            + "\n尝试过的连接：" + "; ".join(token_errors)
        )

    if not token_errors and not api_errors:
        raise SiYuanConnectionError(
            "思源笔记似乎没有启动或 API 端口不可达。请提示用户手动打开思源笔记后重试。"
            + ("\n尝试过的连接：" + "; ".join(connection_errors) if connection_errors else "")
        )

    errors = connection_errors + token_errors + api_errors
    raise SiYuanConnectionError(
        "无法连接到可用的思源工作空间。请确认思源已启动，并检查当前工作空间 Token 是否已加入 profiles。"
        + ("\n尝试过的连接：" + "; ".join(errors) if errors else "")
    )


def _looks_like_token_error(exc: SiYuanApiError) -> bool:
    text = str(exc).casefold()
    return exc.status in (401, 403) or exc.code in (401, 403) or "token" in text or "unauthorized" in text
