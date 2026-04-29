from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

from .cli import get_working_client, load_live_docs, render_start_packet
from .client import SiYuanApiError, SiYuanConnectionError
from .config import load_config
from .ignore import filter_documents, load_privacy_rules
from .indexer import (
    KNOWLEDGE_BASE_DIR,
    find_documents,
    load_docs,
    refresh_index,
    resolve_document,
)


SERVER_NAME = "siyuan-knowledge"
SERVER_VERSION = "0.1.0"


def main() -> int:
    server = McpServer(Path.cwd())
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = server.handle(request)
        except Exception as exc:
            response = make_error(None, -32603, str(exc))
        if response is not None:
            write_message(response)
    return 0


class McpServer:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or {}

        if method == "initialize":
            return make_result(
                request_id,
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            )
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            return make_result(request_id, {"tools": tool_specs()})
        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            return self.call_tool(request_id, str(name), args)
        if method == "ping":
            return make_result(request_id, {})

        return make_error(request_id, -32601, f"Unknown method: {method}")

    def call_tool(self, request_id: Any, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tools: dict[str, Callable[[dict[str, Any]], str]] = {
            "siyuan_start": self.siyuan_start,
            "siyuan_refresh_index": self.siyuan_refresh_index,
            "siyuan_list_notebooks": self.siyuan_list_notebooks,
            "siyuan_list_documents": self.siyuan_list_documents,
            "siyuan_find_documents": self.siyuan_find_documents,
            "siyuan_read_document": self.siyuan_read_document,
            "siyuan_propose_guide_update": self.siyuan_propose_guide_update,
            "siyuan_apply_guide_update": self.siyuan_apply_guide_update,
        }
        if name not in tools:
            return make_error(request_id, -32602, f"Unknown tool: {name}")
        try:
            text = tools[name](args)
            return make_result(request_id, {"content": [{"type": "text", "text": text}]})
        except (SiYuanConnectionError, SiYuanApiError, ValueError, FileNotFoundError) as exc:
            return make_result(
                request_id,
                {"content": [{"type": "text", "text": f"Tool failed: {exc}"}], "isError": True},
            )

    def siyuan_start(self, _args: dict[str, Any]) -> str:
        config = load_config(self.root)
        client = get_working_client(config)
        return render_start_packet(self.root, client.version())

    def siyuan_refresh_index(self, _args: dict[str, Any]) -> str:
        config = load_config(self.root)
        client = get_working_client(config)
        result = refresh_index(client, self.root)
        return (
            "# SiYuan Index Refreshed\n\n"
            f"Scanned {result.total_document_count} documents from {result.total_notebook_count} notebooks.\n"
            f"Visible: {result.document_count} documents from {result.notebook_count} notebooks.\n"
            f"Hidden: {result.hidden_document_count} documents from {result.hidden_notebook_count} notebooks.\n\n"
            "Run `siyuan_start` before using the refreshed index."
        )

    def siyuan_list_notebooks(self, _args: dict[str, Any]) -> str:
        notebooks = read_json(self.root / KNOWLEDGE_BASE_DIR / "notebooks.json")
        lines = ["# Visible SiYuan Notebooks", ""]
        for notebook in notebooks:
            lines.append(f"- `{notebook.get('id', '')}` {notebook.get('name', '')}")
        lines.append("")
        lines.append("Read `knowledge_base/overview.md` before choosing notebook maps.")
        return "\n".join(lines)

    def siyuan_list_documents(self, args: dict[str, Any]) -> str:
        notebook_id = str(args.get("notebook_id") or "").strip()
        notebook_name = str(args.get("notebook_name") or "").strip()
        if not notebook_id and notebook_name:
            notebook_id = self.resolve_notebook_id(notebook_name)
        if not notebook_id:
            raise ValueError("Provide notebook_id or notebook_name")
        path = self.root / KNOWLEDGE_BASE_DIR / "notebooks" / f"{notebook_id}.md"
        if not path.exists():
            raise FileNotFoundError(f"No visible notebook map found for {notebook_id}")
        return path.read_text(encoding="utf-8")

    def siyuan_find_documents(self, args: dict[str, Any]) -> str:
        keyword = str(args.get("keyword") or "").strip()
        if not keyword:
            raise ValueError("keyword is required")
        limit = int(args.get("limit") or 20)
        docs = filter_documents(load_docs(self.root), load_privacy_rules(self.root))
        matches = find_documents(docs, keyword, limit=max(limit, 1))
        if not matches:
            return "No visible matching documents."
        lines = ["# Matching Visible Documents", ""]
        for doc in matches:
            lines.append(f"- `{doc.get('id', '')}` {doc.get('notebook_name', '')} {doc.get('hpath', '')}")
        return "\n".join(lines)

    def siyuan_read_document(self, args: dict[str, Any]) -> str:
        locator = str(args.get("document_id") or args.get("locator") or "").strip()
        if not locator:
            raise ValueError("document_id is required")
        docs = filter_documents(load_docs(self.root), load_privacy_rules(self.root))
        status, matches = resolve_document(docs, locator)
        if status == "ambiguous":
            choices = "\n".join(f"- `{doc.get('id')}` {doc.get('hpath')}" for doc in matches)
            raise ValueError(f"Document locator is ambiguous:\n{choices}")
        if status in ("missing", "no_index"):
            privacy = load_privacy_rules(self.root)
            if privacy.allow:
                config = load_config(self.root)
                client = get_working_client(config)
                live_docs = filter_documents(load_live_docs(client), privacy)
                status, matches = resolve_document(live_docs, locator)
        if status != "ok":
            raise ValueError("No matching visible document. It may be hidden, unindexed, or the locator is wrong.")
        config = load_config(self.root)
        client = get_working_client(config)
        return client.export_markdown(str(matches[0]["id"]))

    def siyuan_propose_guide_update(self, args: dict[str, Any]) -> str:
        title = str(args.get("title") or "Guide update proposal").strip()
        body = str(args.get("proposal") or args.get("body") or "").strip()
        if not body:
            raise ValueError("proposal is required")
        path = self.root / "ai_workspace" / "guide_update_proposals.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"\n## {title}\n\n{body}\n")
        return f"Guide update proposal saved to {path}. Do not apply it until the user explicitly approves."

    def siyuan_apply_guide_update(self, args: dict[str, Any]) -> str:
        content = str(args.get("content") or "").strip()
        mode = str(args.get("mode") or "append").strip().casefold()
        confirmed = bool(args.get("confirmed"))
        if not confirmed:
            raise ValueError("confirmed=true is required. Only use this after explicit user approval.")
        if not content:
            raise ValueError("content is required")
        path = self.root / KNOWLEDGE_BASE_DIR / "guide.md"
        if mode == "replace":
            path.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")
        elif mode == "append":
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write("\n" + content.rstrip() + "\n")
        else:
            raise ValueError("mode must be append or replace")
        return f"Guide updated at {path}. Run siyuan_start before using the updated guide."

    def resolve_notebook_id(self, notebook_name: str) -> str:
        notebooks = read_json(self.root / KNOWLEDGE_BASE_DIR / "notebooks.json")
        exact = [item for item in notebooks if str(item.get("name", "")).casefold() == notebook_name.casefold()]
        if len(exact) == 1:
            return str(exact[0]["id"])
        partial = [item for item in notebooks if notebook_name.casefold() in str(item.get("name", "")).casefold()]
        if len(partial) == 1:
            return str(partial[0]["id"])
        if len(exact) + len(partial) > 1:
            raise ValueError("Notebook name is ambiguous; use notebook_id")
        raise ValueError(f"No visible notebook matched: {notebook_name}")


def tool_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": "siyuan_start",
            "description": "Check SiYuan connectivity and return the mandatory startup packet with existing guide and overview. Does not refresh indexes.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "siyuan_refresh_index",
            "description": "Explicitly refresh the safe SiYuan index when the user asks or the index is missing/stale.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "siyuan_list_notebooks",
            "description": "List visible SiYuan notebooks from the existing safe index.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "siyuan_list_documents",
            "description": "Return the existing document map for one visible notebook. Does not rescan SiYuan.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "notebook_id": {"type": "string"},
                    "notebook_name": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "siyuan_find_documents",
            "description": "Find visible documents by title, path, notebook, tag, or id using the safe index.",
            "inputSchema": {
                "type": "object",
                "properties": {"keyword": {"type": "string"}, "limit": {"type": "integer", "default": 20}},
                "required": ["keyword"],
                "additionalProperties": False,
            },
        },
        {
            "name": "siyuan_read_document",
            "description": "Read one visible SiYuan document as Markdown by document id.",
            "inputSchema": {
                "type": "object",
                "properties": {"document_id": {"type": "string"}, "locator": {"type": "string"}},
                "additionalProperties": False,
            },
        },
        {
            "name": "siyuan_propose_guide_update",
            "description": "Save a proposed guide update in ai_workspace without modifying the guide.",
            "inputSchema": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "proposal": {"type": "string"}, "body": {"type": "string"}},
                "required": ["proposal"],
                "additionalProperties": False,
            },
        },
        {
            "name": "siyuan_apply_guide_update",
            "description": "Append or replace knowledge_base/guide.md only after explicit user approval.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "mode": {"type": "string", "enum": ["append", "replace"], "default": "append"},
                    "confirmed": {"type": "boolean"},
                },
                "required": ["content", "confirmed"],
                "additionalProperties": False,
            },
        },
    ]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def make_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def make_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def write_message(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
