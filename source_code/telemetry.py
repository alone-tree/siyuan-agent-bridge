"""
遥测与反馈核心模块。

仅依赖 Python 标准库，不引入第三方依赖。
所有 HTTP 操作均为 fire-and-forget：失败静默丢弃，不影响主流程。
"""

from __future__ import annotations

import json
import os
import platform as _platform_module
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import request as urllib_request

from source_code import __version__ as MCP_VERSION

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_PLATFORM: str = _platform_module.system()  # Windows / Darwin / Linux
DEFAULT_TELEMETRY_CONFIG: dict[str, str] = {
    "telemetry": "off",
    "telemetry_endpoint": "",
    "proxy": "",
    "local_copy": "false",
}
_TELEMETRY_FILE = "telemetry.json"
_STATS_DIR = "stats"
_EVENTS_SUBDIR = "events"
_TELEMETRY_ID_FILE = "telemetry_id"
_UPLOAD_TIMEOUT = 5  # 秒
_USER_AGENT = f"siyuan-bridge/{MCP_VERSION}"
DEFAULT_ENDPOINT: str = "https://siyuanbridgetelemetry.zingerplayground.top"

# ---------------------------------------------------------------------------
# 模块级状态（MCP server 单线程，无需锁）
# ---------------------------------------------------------------------------

_session_id: str | None = None
_anonymous_id: str | None = None
_siyuan_ver: str | None = None


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TelemetryEvent:
    """单条遥测事件。"""

    ts: str  # ISO 8601 UTC
    anonymous_id: str
    platform: str
    siyuan_ver: str | None
    mcp_ver: str
    session_id: str
    tool: str
    action: str | None
    ok: int  # 1 = success, 0 = failure
    error_type: str | None
    dur_ms: int | None


# ---------------------------------------------------------------------------
# 匿名 ID
# ---------------------------------------------------------------------------


def generate_anonymous_id(root: Path) -> str:
    """生成新的匿名 ID 并写入 stats/telemetry_id。"""
    global _anonymous_id
    stats_dir = root / _STATS_DIR
    stats_dir.mkdir(parents=True, exist_ok=True)
    aid = uuid.uuid4().hex
    (stats_dir / _TELEMETRY_ID_FILE).write_text(aid, encoding="utf-8")
    _anonymous_id = aid
    return aid


def load_anonymous_id(root: Path) -> str:
    """读取或生成匿名 ID。结果缓存到模块变量。"""
    global _anonymous_id
    if _anonymous_id is not None:
        return _anonymous_id
    id_file = root / _STATS_DIR / _TELEMETRY_ID_FILE
    if id_file.exists():
        aid = id_file.read_text(encoding="utf-8").strip()
        if aid:
            _anonymous_id = aid
            return aid
    return generate_anonymous_id(root)


# ---------------------------------------------------------------------------
# 会话 ID
# ---------------------------------------------------------------------------


def ensure_session_id() -> str:
    """确保当前进程有 session_id。"""
    global _session_id
    if _session_id is None:
        _session_id = uuid.uuid4().hex
    return _session_id


# ---------------------------------------------------------------------------
# 思源版本
# ---------------------------------------------------------------------------


def set_siyuan_version(ver: str) -> None:
    """记录当前思源版本号。"""
    global _siyuan_ver
    _siyuan_ver = ver


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------


def load_telemetry_config(root: Path) -> dict[str, str]:
    """读取 telemetry.json，缺失或损坏返回默认。"""
    config_file = root / _TELEMETRY_FILE
    if not config_file.exists():
        return dict(DEFAULT_TELEMETRY_CONFIG)
    try:
        raw = json.loads(config_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_TELEMETRY_CONFIG)
    if not isinstance(raw, dict):
        return dict(DEFAULT_TELEMETRY_CONFIG)
    cfg = dict(DEFAULT_TELEMETRY_CONFIG)
    for key in ("telemetry", "telemetry_endpoint", "proxy"):
        val = raw.get(key)
        if isinstance(val, str) and val:
            cfg[key] = val
        elif key == "telemetry" and isinstance(val, str):
            cfg[key] = val  # 保留空字符串 -> 视为 off
    # 校验 telemetry 字段
    if cfg["telemetry"] not in ("off", "upload"):
        cfg["telemetry"] = "off"
    # local_copy: 可选布尔，默认 false
    raw_local = raw.get("local_copy")
    if isinstance(raw_local, bool) and raw_local:
        cfg["local_copy"] = "true"
    elif isinstance(raw_local, str) and raw_local.strip().casefold() in ("true", "1"):
        cfg["local_copy"] = "true"
    return cfg


def should_upload(root: Path) -> bool:
    """是否应上传遥测事件（upload 模式即可，endpoint 由默认值兜底）。"""
    cfg = load_telemetry_config(root)
    return cfg["telemetry"] == "upload"


def should_keep_local(root: Path) -> bool:
    """用户是否额外要求在本地保留一份遥测数据。"""
    cfg = load_telemetry_config(root)
    return cfg["local_copy"] == "true"


def get_effective_endpoint(root: Path) -> str:
    """返回有效遥测端点：配置优先，否则使用默认端点。"""
    cfg = load_telemetry_config(root)
    explicit = str(cfg.get("telemetry_endpoint", "")).strip()
    return explicit if explicit else DEFAULT_ENDPOINT


# ---------------------------------------------------------------------------
# 代理解析
# ---------------------------------------------------------------------------


def _resolve_proxy(root: Path) -> str:
    """返回用户显式配置的代理地址。

    仅从 telemetry.json 的 proxy 字段读取。不再自动探测环境变量或系统代理，
    因为 Python urllib 通过 Clash 等代理访问自定义域名时可能 SSL 握手失败。
    默认直连即可——项目使用自有域名，无需翻墙。
    """
    cfg = load_telemetry_config(root)
    return str(cfg.get("proxy", "")).strip()


def _build_proxy_handler(proxy_url: str) -> urllib_request.ProxyHandler:
    """根据代理 URL 构建 ProxyHandler。

    proxy_url 为空时使用系统默认代理（urllib 自动探测）。
    """
    if proxy_url:
        return urllib_request.ProxyHandler({"https": proxy_url, "http": proxy_url})
    return urllib_request.ProxyHandler()


def _build_opener(proxy_url: str) -> urllib_request.OpenerDirector:
    """构建带代理的 HTTP opener。"""
    proxy_handler = _build_proxy_handler(proxy_url)
    return urllib_request.build_opener(proxy_handler)


# ---------------------------------------------------------------------------
# 本地记录
# ---------------------------------------------------------------------------


def record_event(root: Path, event: TelemetryEvent) -> None:
    """追加一条遥测事件到本地 JSONL 文件。异常静默丢弃。"""
    if not should_keep_local(root):
        return
    try:
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        events_dir = root / _STATS_DIR / _EVENTS_SUBDIR
        events_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = events_dir / f"{date_str}.jsonl"
        line = json.dumps(asdict(event), ensure_ascii=False, separators=(",", ":"))
        with jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 远端上传
# ---------------------------------------------------------------------------


def _upload_event(endpoint: str, proxy_url: str, event: TelemetryEvent) -> bool:
    """上传单条事件到 Worker /api/telemetry。失败返回 False。"""
    url = f"{endpoint.rstrip('/')}/api/telemetry"
    body = json.dumps([asdict(event)], ensure_ascii=False).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Connection": "close", "User-Agent": _USER_AGENT},
        method="POST",
    )
    try:
        opener = _build_opener(proxy_url)
        with opener.open(req, timeout=_UPLOAD_TIMEOUT) as resp:
            return resp.status == 200
    except Exception:
        return False


def _fire_upload(endpoint: str, proxy_url: str, event: TelemetryEvent) -> None:
    """后台线程 fire-and-forget 上传。"""
    try:
        t = threading.Thread(target=_upload_event, args=(endpoint, proxy_url, event), daemon=True)
        t.start()
    except Exception:
        pass


def submit_feedback(endpoint: str, proxy_url: str, payload: dict[str, str]) -> bool:
    """POST 反馈到 Worker /api/feedback。"""
    if not endpoint or not endpoint.strip():
        return False
    url = f"{endpoint.rstrip('/')}/api/feedback"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Connection": "close", "User-Agent": _USER_AGENT},
        method="POST",
    )
    try:
        opener = _build_opener(proxy_url)
        with opener.open(req, timeout=_UPLOAD_TIMEOUT) as resp:
            return resp.status == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 工具包装器
# ---------------------------------------------------------------------------


def _with_telemetry(root: Path, tool: str, action: str | None, fn: Callable[[], str]) -> str:
    """包装工具调用：计时、上传遥测，可选择本地保留副本。

    遥测失败绝不抛出异常，不影响 fn 的返回值或异常传播。
    """
    if not should_upload(root):
        return fn()

    start = time.monotonic()
    ok = 0
    error_type: str | None = None
    try:
        result = fn()
        ok = 1
        return result
    except Exception as e:
        error_type = getattr(e, 'error_code', None) or type(e).__name__
        raise
    finally:
        dur_ms = int((time.monotonic() - start) * 1000)
        try:
            anon_id = load_anonymous_id(root)
            sid = ensure_session_id()
            event = TelemetryEvent(
                ts=datetime.now(timezone.utc).isoformat(),
                anonymous_id=anon_id,
                platform=_PLATFORM,
                siyuan_ver=_siyuan_ver,
                mcp_ver=MCP_VERSION,
                session_id=sid,
                tool=tool,
                action=action,
                ok=ok,
                error_type=error_type,
                dur_ms=dur_ms,
            )
            record_event(root, event)
            endpoint = get_effective_endpoint(root)
            proxy = _resolve_proxy(root)
            _fire_upload(endpoint, proxy, event)
        except Exception:
            pass
