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
    timeout: float = 2.0
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
        req.add_header("Connection", "close")
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

    def list_document_blocks(self, doc_id: str) -> list[dict[str, Any]]:
        """Return all non-document blocks for a document."""
        stmt = (
            f"SELECT id, parent_id, root_id, type, subtype, markdown, content, sort "
            f"FROM blocks WHERE root_id = '{doc_id}' AND type != 'd' "
            f"ORDER BY parent_id, sort"
        )
        data = self.query_sql(stmt)
        if not isinstance(data, list):
            raise SiYuanApiError("Unexpected blocks response shape")
        return data

    def get_child_blocks(self, block_id: str) -> list[dict[str, Any]]:
        data = self._post("/api/block/getChildBlocks", {"id": block_id})
        if not isinstance(data, list):
            raise SiYuanApiError("Unexpected child blocks response shape")
        return [item for item in data if isinstance(item, dict)]

    def delete_block(self, block_id: str) -> None:
        self._post("/api/block/deleteBlock", {"id": block_id})

    def create_snapshot(self, memo: str) -> dict[str, Any]:
        data = self._post("/api/repo/createSnapshot", {"memo": memo})
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise SiYuanApiError("Unexpected snapshot response shape")
        return data

    def get_repo_snapshots(self, *, page: int = 1) -> dict[str, Any]:
        data = self._post("/api/repo/getRepoSnapshots", {"page": page})
        if not isinstance(data, dict):
            raise SiYuanApiError("Unexpected repo snapshots response shape")
        return data

    def create_notebook(self, name: str) -> dict[str, Any]:
        data = self._post("/api/notebook/createNotebook", {"name": name})
        if data is None:
            return {}
        if isinstance(data, str):
            for nb in self.list_notebooks():
                if str(nb.get("name", "")) == name:
                    return {"id": str(nb.get("id", ""))}
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def create_doc_with_md(self, notebook: str, path: str, markdown: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "notebook": notebook,
            "path": path,
            "markdown": markdown,
        }
        data = self._post("/api/filetree/createDocWithMd", payload)
        if data is None:
            return {}
        if isinstance(data, str):
            return {"id": data}
        if not isinstance(data, dict):
            raise SiYuanApiError("Unexpected createDocWithMd response shape")
        return data

    def update_block(self, block_id: str, markdown: str, ial: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": block_id,
            "dataType": "markdown",
            "data": markdown,
        }
        if ial is not None:
            payload["ial"] = ial
        data = self._post("/api/block/updateBlock", payload)
        if data is None:
            return {}
        if isinstance(data, list):
            return {"blocks": data}
        if not isinstance(data, dict):
            return {}
        return data

    def set_block_attrs(self, block_id: str, attrs: dict[str, str]) -> dict[str, Any]:
        result = self._post("/api/attr/setBlockAttrs", {"id": block_id, "attrs": attrs})
        if not result:
            return {}
        return result

    def get_attribute_view(self, av_id: str) -> dict[str, Any]:
        result = self._post("/api/av/getAttributeView", {"id": av_id})
        if not result:
            return {}
        return result.get("av", {})

    def append_block(self, parent_id: str, markdown: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "dataType": "markdown",
            "data": markdown,
            "parentID": parent_id,
        }
        data = self._post("/api/block/appendBlock", payload)
        if data is None:
            return {}
        if isinstance(data, list):
            return {"blocks": data}
        if not isinstance(data, dict):
            return {}
        return data

    def insert_block_after(self, previous_id: str, markdown: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "dataType": "markdown",
            "data": markdown,
            "previousID": previous_id,
        }
        data = self._post("/api/block/insertBlock", payload)
        if data is None:
            return {}
        if isinstance(data, list):
            return {"blocks": data}
        if not isinstance(data, dict):
            return {}
        return data

    def insert_block_before(self, next_id: str, markdown: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "dataType": "markdown",
            "data": markdown,
            "nextID": next_id,
        }
        data = self._post("/api/block/insertBlock", payload)
        if data is None:
            return {}
        if isinstance(data, list):
            return {"blocks": data}
        if not isinstance(data, dict):
            return {}
        return data

    def push_msg(self, msg: str, timeout: int = 7000) -> None:
        self._post("/api/notification/pushMsg", {"msg": msg, "timeout": timeout})

    def push_err_msg(self, msg: str, timeout: int = 7000) -> None:
        self._post("/api/notification/pushErrMsg", {"msg": msg, "timeout": timeout})

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Connection": "close"}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                return self._post_once(path, body, headers)
            except SiYuanConnectionError as exc:
                last_error = exc
                if attempt < 1:
                    import time
                    time.sleep(0.3)
            else:
                break
        raise last_error  # type: ignore[misc]

    def _post_once(self, path: str, body: bytes, headers: dict[str, str]) -> Any:
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
