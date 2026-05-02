from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib import error, parse, request


Transport = Callable[[request.Request, float], Any]


class SiYuanConnectionError(RuntimeError):
    pass


class SiYuanApiError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, code: int | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class SiYuanClient:
    base_url: str
    token: str | None = None
    timeout: float = 10.0
    transport: Transport | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))

    def version(self) -> str:
        data = self._post("/api/system/version", {})
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            for key in ("version", "ver"):
                if key in data:
                    return str(data[key])
        return str(data)

    def list_notebooks(self) -> list[dict[str, Any]]:
        data = self._post("/api/notebook/lsNotebooks", {})
        if isinstance(data, dict):
            notebooks = data.get("notebooks", [])
        else:
            notebooks = data
        if not isinstance(notebooks, list):
            raise SiYuanApiError("Unexpected notebooks response shape")
        return [item for item in notebooks if isinstance(item, dict)]

    def open_notebook(self, notebook_id: str) -> None:
        self._post("/api/notebook/openNotebook", {"notebook": notebook_id})

    def close_notebook(self, notebook_id: str) -> None:
        self._post("/api/notebook/closeNotebook", {"notebook": notebook_id})

    def query_sql(self, stmt: str) -> list[dict[str, Any]]:
        data = self._post("/api/query/sql", {"stmt": stmt})
        if not isinstance(data, list):
            raise SiYuanApiError("Unexpected SQL response shape")
        return [item for item in data if isinstance(item, dict)]

    def export_markdown(self, block_id: str) -> str:
        data = self._post(
            "/api/export/exportMdContent",
            {"id": block_id, "refMode": 0, "embedMode": 0},
        )
        if isinstance(data, dict):
            for key in ("content", "markdown", "md", "kramdown"):
                value = data.get(key)
                if isinstance(value, str):
                    return value
        if isinstance(data, str):
            return data
        raise SiYuanApiError("Unexpected markdown export response shape")

    def get_block_kramdown(self, block_id: str) -> str:
        data = self._post("/api/block/getBlockKramdown", {"id": block_id})
        if isinstance(data, dict):
            value = data.get("kramdown")
            if isinstance(value, str):
                return value
        if isinstance(data, str):
            return data
        raise SiYuanApiError("Unexpected kramdown response shape")

    def get_asset(self, asset_path: str) -> bytes:
        """Download an asset file from SiYuan's HTTP asset server."""
        parts = asset_path.lstrip("/").split("/")
        encoded = "/".join(parse.quote(p, safe="") for p in parts)
        url = f"{self.base_url}/{encoded}"
        req = request.Request(url, method="GET")
        if self.token:
            req.add_header("Authorization", f"Token {self.token}")
        try:
            opener = self.transport or request.urlopen
            with opener(req, timeout=self.timeout) as response:
                return response.read()
        except error.HTTPError as exc:
            raise SiYuanApiError(f"Asset not found: {asset_path}", status=exc.code) from exc
        except error.URLError as exc:
            raise SiYuanConnectionError(str(exc.reason)) from exc

    def search_full_text(
        self,
        query: str,
        *,
        method: int = 0,
        types: dict[str, bool] | None = None,
        paths: list[str] | None = None,
        group_by: int = 1,
        order_by: int = 7,
        page: int = 1,
        page_size: int = 64,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query": query,
            "method": method,
            "groupBy": group_by,
            "orderBy": order_by,
            "page": page,
            "pageSize": page_size,
        }
        if types:
            payload["types"] = types
        if paths:
            payload["paths"] = paths

        data = self._post("/api/search/fullTextSearchBlock", payload)
        if not isinstance(data, dict):
            raise SiYuanApiError("Unexpected search response shape")
        return data

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        req = request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method="POST",
        )

        try:
            opener = self.transport or request.urlopen
            with opener(req, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            message = _read_http_error(exc)
            raise SiYuanApiError(message, status=exc.code) from exc
        except error.URLError as exc:
            raise SiYuanConnectionError(str(exc.reason)) from exc
        except TimeoutError as exc:
            raise SiYuanConnectionError("Request timed out") from exc
        except OSError as exc:
            raise SiYuanConnectionError(str(exc)) from exc

        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SiYuanApiError("SiYuan returned non-JSON response") from exc

        if not isinstance(envelope, dict):
            raise SiYuanApiError("SiYuan returned unexpected response shape")

        code = envelope.get("code", 0)
        if code != 0:
            msg = envelope.get("msg") or envelope.get("message") or f"API returned code {code}"
            raise SiYuanApiError(str(msg), code=int(code) if isinstance(code, int) else None)

        return envelope.get("data")


def _read_http_error(exc: error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8")
    except Exception:
        raw = ""
    return raw or f"HTTP {exc.code}"
