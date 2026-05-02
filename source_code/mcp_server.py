from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

from .cli import get_working_client, load_live_docs, resolve_privacy_locator
from .client import SiYuanApiError, SiYuanClient, SiYuanConnectionError
from .config import load_config
from .ignore import (
    add_persistent_ignore,
    close_temporary_allow,
    filter_documents,
    initialize_ignore_files,
    load_privacy_rules,
    load_temporary_allow,
    make_privacy_rule,
    make_temporary_allow,
    remove_persistent_ignore,
    write_temporary_allow,
)
from .indexer import (
    KNOWLEDGE_BASE_DIR,
    build_notebook_overview,
    compute_word_count,
    ensure_notebooks_open,
    extract_snippet,
    find_documents,
    format_date,
    load_docs,
    refresh_index,
    render_doc_tree,
    resolve_document,
    search_content,
)


SERVER_NAME = "siyuan-knowledge"
SERVER_VERSION = "0.1.0"
DEFAULT_CHUNK_CHARS = 10000
MAX_CHUNK_CHARS = 30000


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
            "siyuan_list": self.siyuan_list,
            "siyuan_find_documents": self.siyuan_find_documents,
            "siyuan_read_document": self.siyuan_read_document,
            "siyuan_propose_guide_update": self.siyuan_propose_guide_update,
            "siyuan_apply_guide_update": self.siyuan_apply_guide_update,
            "siyuan_privacy": self.siyuan_privacy,
            "siyuan_temporary_allow": self.siyuan_temporary_allow,
        }
        if name not in tools:
            return make_error(request_id, -32602, f"Unknown tool: {name}")
        try:
            text = tools[name](args)
            return make_result(request_id, {"content": [{"type": "text", "text": text}]})
        except SiYuanConnectionError as exc:
            return make_result(
                request_id,
                {"content": [{"type": "text", "text": "思源笔记似乎没有启动，请提示用户手动打开思源笔记后重试。"}], "isError": True},
            )
        except (SiYuanApiError, ValueError, FileNotFoundError) as exc:
            return make_result(
                request_id,
                {"content": [{"type": "text", "text": f"Tool failed: {exc}"}], "isError": True},
            )

    def siyuan_start(self, _args: dict[str, Any]) -> str:
        config = load_config(self.root)
        client = get_working_client(config)
        refresh_index(client, self.root)
        version = client.version()
        base = self.root / KNOWLEDGE_BASE_DIR
        start_here = _read_optional(self.root / "START_HERE.md")
        guide = _read_optional(base / "guide.md")
        index_md = _read_optional(base / "index.md")
        overview = build_notebook_overview(self.root)
        parts: list[str] = [
            "# SiYuan Knowledge Startup Packet",
            "",
            f"SiYuan connection: OK, version {version}",
            "",
            overview,
        ]
        if index_md:
            parts.extend([
                "",
                "## Semantic Index (index.md)",
                "",
                index_md.strip(),
            ])
        else:
            parts.extend([
                "",
                "> 当前没有导航索引。如果你希望 AI 更快速地定位到相关内容，可以告诉 AI 先快速扫一遍我的笔记本结构，创建一个导航索引。之后每次新会话启动，AI 都能直接拿到这份导航。",
            ])
        parts.extend([
            "",
            "## Mandatory Workflow",
            "",
            "1. Use this startup packet first.",
            "2. If an index.md was provided above, use its quick navigation table to locate relevant notebooks.",
            "3. Follow `knowledge_base/guide.md` for durable preferences.",
            "4. Use the notebook overview table to choose relevant notebooks.",
            "5. Use `siyuan_list` with a `notebook_id` to see one notebook's document tree.",
            "6. Read documents with `siyuan_read_document`.",
            "7. Use `siyuan_refresh_index` mid-session only when the user explicitly asks to refresh.",
            "",
            "## Start Here",
            "",
            start_here.strip() if start_here else "(START_HERE.md is missing)",
            "",
            "## Guide",
            "",
            guide.strip() if guide else "(guide.md is missing — run `python -m source_code refresh`)",
            "",
        ])
        return "\n".join(parts)

    def siyuan_refresh_index(self, _args: dict[str, Any]) -> str:
        config = load_config(self.root)
        client = get_working_client(config)

        workspace_dir = self.root / "ai_workspace"
        if workspace_dir.exists():
            for item in workspace_dir.iterdir():
                if item.name == "README.md":
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

        result = refresh_index(client, self.root)
        return (
            "# SiYuan Index Refreshed\n\n"
            f"Scanned {result.total_document_count} documents from {result.total_notebook_count} notebooks.\n"
            f"Visible: {result.document_count} documents from {result.notebook_count} notebooks.\n"
            f"Hidden: {result.hidden_document_count} documents from {result.hidden_notebook_count} notebooks.\n\n"
            "Run `siyuan_start` before using the refreshed index."
        )

    def siyuan_list(self, args: dict[str, Any]) -> str:
        notebook_id = str(args.get("notebook_id") or "").strip()
        notebook_name = str(args.get("notebook_name") or "").strip()

        if not notebook_id and not notebook_name:
            # List all notebooks
            notebooks = read_json(self.root / KNOWLEDGE_BASE_DIR / "notebooks.json")
            lines = ["# Visible SiYuan Notebooks", ""]
            for notebook in notebooks:
                lines.append(f"- `{notebook.get('id', '')}` {notebook.get('name', '')}")
            lines.append("")
            return "\n".join(lines)

        # List documents for one notebook
        if not notebook_id and notebook_name:
            notebook_id = self.resolve_notebook_id(notebook_name)
        docs = [d for d in load_docs(self.root) if str(d.get("notebook_id", "")) == notebook_id]
        if not docs:
            raise FileNotFoundError(f"No visible documents found for notebook {notebook_id}")
        docs.sort(key=lambda d: (str(d.get("hpath", "")).casefold(), str(d.get("id", ""))))
        nb_name = self._notebook_name(notebook_id)
        total_words = sum(d.get("word_count", 0) for d in docs)
        total_blocks = sum(d.get("block_count", 0) for d in docs)
        lines = [
            f"# {nb_name} (`{notebook_id}`) | {len(docs)} docs | {total_words:,} 字 | {total_blocks} 块",
            "",
        ]
        lines.extend(render_doc_tree(docs))
        return "\n".join(lines)

    def _notebook_name(self, notebook_id: str) -> str:
        notebooks = read_json(self.root / KNOWLEDGE_BASE_DIR / "notebooks.json")
        for nb in notebooks:
            if str(nb.get("id", "")) == notebook_id:
                return str(nb.get("name", notebook_id))
        return notebook_id

    def siyuan_find_documents(self, args: dict[str, Any]) -> str:
        keyword = str(args.get("keyword") or "").strip()
        if not keyword:
            raise ValueError("keyword is required")

        mode = str(args.get("mode") or "keyword").strip().casefold()
        if mode not in ("keyword", "query", "regex", "sql"):
            raise ValueError("mode must be keyword, query, regex, or sql")

        scope = str(args.get("scope") or "headings").strip().casefold()
        if scope not in ("headings", "full"):
            raise ValueError("scope must be headings or full")

        limit = max(int(args.get("limit") or 20), 1)

        notebooks_raw = args.get("notebooks")
        notebooks: list[str] | None = None
        if notebooks_raw and notebooks_raw != "ALL":
            if isinstance(notebooks_raw, list):
                notebooks = [str(n) for n in notebooks_raw if n]
            elif isinstance(notebooks_raw, str) and notebooks_raw.strip().upper() != "ALL":
                notebooks = [notebooks_raw.strip()]
            if not notebooks:
                notebooks = None

        privacy = load_privacy_rules(self.root)
        local_docs = filter_documents(load_docs(self.root), privacy)
        local_hits = self._search_local_index(keyword, mode, local_docs, notebooks, limit)
        api_error = ""

        if mode == "sql":
            config = load_config(self.root)
            client = get_working_client(config)
            try:
                with ensure_notebooks_open(client, notebooks):
                    rows = client.query_sql(keyword)
            except SiYuanApiError as exc:
                if "administrator" in str(exc).casefold() or "privilege" in str(exc).casefold():
                    raise ValueError("SQL search requires SiYuan administrator privileges. Use mode=keyword, mode=query, or mode=regex instead.") from exc
                raise
            enriched = self._enrich_sql_results(rows, local_docs, notebooks)
        else:
            enriched = local_hits
            try:
                config = load_config(self.root)
                client = get_working_client(config)
                method_map = {"keyword": 0, "query": 1, "regex": 3}
                api_method = method_map[mode]
                with ensure_notebooks_open(client, notebooks):
                    data = search_content(
                        client,
                        keyword,
                        method=api_method,
                        scope=scope,
                        notebooks=notebooks,
                        limit=limit,
                    )
                blocks: list[dict[str, Any]] = data.get("blocks", [])
                keywords = search_terms(keyword, mode)
                live_hits = self._enrich_search_blocks(blocks, local_docs, keywords, notebooks)
                enriched = merge_search_results(local_hits, live_hits)
            except (SiYuanConnectionError, SiYuanApiError) as exc:
                api_error = str(exc)

        if not enriched:
            return f"# Search: \"{keyword}\" ({scope}, {mode})\n\nNo matching visible documents."

        enriched = enriched[:limit]
        grouped = self._group_by_notebook(enriched)

        scope_label = "标题" if scope == "headings" else "全文"
        lines = [f"# Search: \"{keyword}\" ({scope_label}, {mode}, {len(enriched)} matches in {len(grouped)} notebooks)", ""]
        if api_error:
            lines.extend([
                "> Live SiYuan search failed; showing matches from the safe local index.",
                "",
            ])

        remaining = limit
        for nb_name in sorted(grouped, key=str.casefold):
            items = grouped[nb_name]
            lines.append(f"## {nb_name} ({len(items)} matches)")
            for item in items[:remaining]:
                wc = item.get("word_count", 0)
                bc = item.get("block_count", 0)
                date = format_date(str(item.get("updated", "")))
                hpath = str(item.get("hpath") or "/")
                doc_id = str(item.get("id") or "")
                source = str(item.get("source") or "")
                source_text = f" [{source}]" if source else ""
                lines.append(f"- `{doc_id}` {hpath} {wc:,}字 {bc}块 {date}{source_text}".rstrip())
                snippet = item.get("snippet", "")
                if snippet:
                    lines.append(f"  > {snippet}")
            lines.append("")
            remaining -= len(items)
            if remaining <= 0:
                break

        return "\n".join(lines)

    def _search_local_index(
        self,
        keyword: str,
        mode: str,
        local_docs: list[dict[str, Any]],
        notebook_filter: list[str] | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        docs = [
            doc for doc in local_docs
            if not notebook_filter or str(doc.get("notebook_id", "")) in notebook_filter
        ]
        terms = search_terms(keyword, mode)
        if mode == "keyword":
            matches = find_documents(docs, keyword, limit=limit)
        elif mode == "query":
            matches = [doc for doc in docs if query_matches(local_search_text(doc), keyword)]
        elif mode == "regex":
            try:
                pattern = re.compile(keyword, re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"invalid regex: {exc}") from exc
            matches = [doc for doc in docs if pattern.search(local_search_text(doc))]
        else:
            matches = []

        results = []
        for doc in matches[:limit]:
            snippet = extract_snippet(local_search_text(doc), terms)
            results.append({
                "id": str(doc.get("id", "")),
                "notebook_id": str(doc.get("notebook_id", "")),
                "notebook_name": str(doc.get("notebook_name", "")),
                "hpath": str(doc.get("hpath", "")),
                "word_count": doc.get("word_count", 0),
                "block_count": doc.get("block_count", 0),
                "updated": str(doc.get("updated", "")),
                "snippet": snippet,
                "source": "safe index",
            })
        return results

    def _enrich_search_blocks(
        self,
        blocks: list[dict[str, Any]],
        local_docs: list[dict[str, Any]],
        keywords: list[str],
        notebook_filter: list[str] | None,
    ) -> list[dict[str, Any]]:
        doc_index: dict[str, dict[str, Any]] = {}
        for doc in local_docs:
            doc_index[str(doc.get("id", ""))] = doc

        seen: set[str] = set()
        results: list[dict[str, Any]] = []

        for block in blocks:
            block_type = str(block.get("type", ""))
            if block_type == "d":
                doc_id = str(block.get("id", ""))
            else:
                doc_id = str(block.get("root_id", ""))

            if not doc_id or doc_id in seen:
                continue

            doc = doc_index.get(doc_id)
            if doc is None:
                continue
            nb_id = str(doc.get("notebook_id", ""))
            if notebook_filter and nb_id not in notebook_filter:
                continue

            seen.add(doc_id)

            content = str(block.get("content") or block.get("markdown") or "")
            snippet = extract_snippet(content, keywords)

            results.append({
                "id": doc_id,
                "notebook_id": nb_id,
                "notebook_name": str(doc.get("notebook_name", "")),
                "hpath": str(doc.get("hpath", "")),
                "word_count": doc.get("word_count", 0),
                "block_count": doc.get("block_count", 0),
                "updated": str(doc.get("updated", "")),
                "snippet": snippet,
                "source": "live search",
            })

        results.sort(key=lambda r: (r["notebook_name"].casefold(), r["hpath"].casefold()))
        return results

    def _enrich_sql_results(
        self,
        rows: list[dict[str, Any]],
        local_docs: list[dict[str, Any]],
        notebook_filter: list[str] | None,
    ) -> list[dict[str, Any]]:
        doc_index: dict[str, dict[str, Any]] = {}
        for doc in local_docs:
            doc_index[str(doc.get("id", ""))] = doc

        seen: set[str] = set()
        results: list[dict[str, Any]] = []

        for row in rows:
            block_type = str(row.get("type", ""))
            if block_type == "d":
                doc_id = str(row.get("id", ""))
            else:
                doc_id = str(row.get("root_id", ""))

            if not doc_id or doc_id in seen:
                continue

            doc = doc_index.get(doc_id)
            if doc is None:
                continue

            nb_id = str(doc.get("notebook_id", ""))
            if notebook_filter and nb_id not in notebook_filter:
                continue

            seen.add(doc_id)
            results.append({
                "id": doc_id,
                "notebook_id": nb_id,
                "notebook_name": str(doc.get("notebook_name", "")),
                "hpath": str(doc.get("hpath", "")),
                "word_count": doc.get("word_count", 0),
                "block_count": doc.get("block_count", 0),
                "updated": str(doc.get("updated", "")),
                "snippet": "",
                "source": "sql",
            })

        results.sort(key=lambda r: (r["notebook_name"].casefold(), r["hpath"].casefold()))
        return results

    @staticmethod
    def _group_by_notebook(results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in results:
            nb = str(item.get("notebook_name") or "Unknown")
            groups.setdefault(nb, []).append(item)
        return groups

    def siyuan_read_document(self, args: dict[str, Any]) -> str:
        doc = self.resolve_visible_document(args)
        notebook_id = str(doc.get("notebook_id", ""))
        config = load_config(self.root)
        client = get_working_client(config)
        with ensure_notebooks_open(client, [notebook_id]):
            markdown = client.export_markdown(str(doc["id"]))
        doc_id = str(doc.get("id"))
        attachment_count = extract_attachments(markdown, client, doc_id, self.root)
        max_chars = clamp_int(args.get("max_chars"), DEFAULT_CHUNK_CHARS, 2000, MAX_CHUNK_CHARS)
        chunk_param = int(args.get("chunk") or 0)
        chunks = split_markdown_chunks(markdown, max_chars=max_chars)

        doc_path = str(doc.get("hpath") or doc.get("title") or doc.get("id"))
        markdown_wc = compute_word_count(markdown)
        date = format_date(str(doc.get("updated", "")))

        header_lines = [
            f"# Document: {doc_path}",
            f"Document ID: `{doc_id}`",
            f"字数: {markdown_wc:,} | 块数: {doc.get('block_count', 0)} | 字符: {len(markdown):,} | 更新: {date}",
        ]
        if attachment_count:
            header_lines.append(f"附件: {attachment_count} 个已提取到 ai_workspace/attachments/{doc_id}/")
        header = "\n".join(header_lines)

        outline = build_outline(markdown, chunks, max_chars)

        if len(chunks) <= 1:
            return "\n".join([header, "", outline, "", "---", "", markdown])

        if chunk_param == 0:
            chunk_index = 1
        elif chunk_param < 1 or chunk_param > len(chunks):
            raise ValueError(f"chunk must be between 1 and {len(chunks)}")
        else:
            chunk_index = chunk_param

        chunk_content = chunks[chunk_index - 1]
        chunk_wc = compute_word_count(chunk_content)

        return "\n".join([
            header,
            "",
            outline,
            "",
            "> 输入 `chunk=N` 跳转到指定 chunk。chunk 0 返回 chunk 1。",
            "",
            "---",
            "",
            f"## Chunk {chunk_index}/{len(chunks)} ({chunk_wc:,} 字)",
            "",
            chunk_content,
        ])

    def resolve_visible_document(self, args: dict[str, Any]) -> dict[str, Any]:
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
                with ensure_notebooks_open(client):
                    live_docs = filter_documents(load_live_docs(client), privacy)
                status, matches = resolve_document(live_docs, locator)
        if status != "ok":
            raise ValueError("No matching visible document. It may be hidden, unindexed, or the locator is wrong.")
        return matches[0]

    def export_document_markdown(self, document_id: str) -> str:
        config = load_config(self.root)
        client = get_working_client(config)
        return client.export_markdown(document_id)

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

    def siyuan_privacy(self, args: dict[str, Any]) -> str:
        action = str(args.get("action") or "").strip()
        if action not in ("hide", "unhide"):
            raise ValueError("action must be 'hide' or 'unhide'")
        confirmed = bool(args.get("confirmed"))
        if not confirmed:
            raise ValueError("confirmed=true is required. Only set after explicit user approval.")
        scope = str(args.get("scope") or "").strip()
        if scope not in ("notebook", "document", "subtree"):
            raise ValueError("scope must be notebook, document, or subtree")
        locator = str(args.get("locator") or "").strip()
        if not locator:
            raise ValueError("locator is required")

        config = load_config(self.root)
        client = get_working_client(config)
        resolved = resolve_privacy_locator(client, scope, locator)

        if action == "hide":
            reason = str(args.get("reason") or "").strip()
            initialize_ignore_files(self.root)
            rule = make_privacy_rule(scope, locator, reason=reason, resolved=resolved)
            added = add_persistent_ignore(self.root, rule)
            result = refresh_index(client, self.root)
            target = str(resolved.get("title") or resolved.get("name") or locator) if resolved else locator
            status = "Added" if added else "Already exists"
            return (
                f"# Privacy: hide {scope}\n\n"
                f"**{status}** hide rule for {scope}: {target}\n\n"
                f"Refreshed safe index. Visible: {result.document_count}/{result.total_document_count} documents. "
                f"Hidden: {result.hidden_document_count}."
            )
        else:
            rule = make_privacy_rule(scope, locator, resolved=resolved)
            removed = remove_persistent_ignore(self.root, rule)
            result = refresh_index(client, self.root)
            target = str(resolved.get("title") or resolved.get("name") or locator) if resolved else locator
            return (
                f"# Privacy: unhide {scope}\n\n"
                f"**Removed {removed} hide rule(s)** for {scope}: {target}\n\n"
                f"Refreshed safe index. Visible: {result.document_count}/{result.total_document_count} documents. "
                f"Hidden: {result.hidden_document_count}."
            )

    def siyuan_temporary_allow(self, args: dict[str, Any]) -> str:
        action = str(args.get("action") or "open").strip()
        if action not in ("open", "close"):
            raise ValueError("action must be 'open' or 'close'")

        if action == "close":
            count = close_temporary_allow(self.root)
            plural = "s" if count != 1 else ""
            return f"# Privacy: close temporary allow\n\nCleared {count} temporary allow rule{plural}. Hidden items are closed again."

        confirmed = bool(args.get("confirmed"))
        if not confirmed:
            raise ValueError("confirmed=true is required for open. Only set after explicit user approval.")
        scope = str(args.get("scope") or "").strip()
        if scope not in ("notebook", "document", "subtree"):
            raise ValueError("scope must be notebook, document, or subtree")
        locator = str(args.get("locator") or "").strip()
        if not locator:
            raise ValueError("locator is required")
        minutes = max(int(args.get("minutes") or 60), 1)
        reason = str(args.get("reason") or "").strip()

        config = load_config(self.root)
        client = get_working_client(config)
        resolved = resolve_privacy_locator(client, scope, locator)
        rule = make_temporary_allow(scope, locator, minutes=minutes, reason=reason, resolved=resolved)
        existing = load_temporary_allow(self.root)
        existing.append(rule)
        write_temporary_allow(self.root, existing)

        target = str(resolved.get("title") or resolved.get("name") or locator) if resolved else locator
        return (
            f"# Privacy: temporary allow {scope}\n\n"
            f"Temporary allow added for {scope}: {target}\n"
            f"Expires in {minutes} minutes.\n\n"
            "This does not rewrite `knowledge_base/`. The item will be hidden again after expiry."
        )

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


def _read_optional(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def local_search_text(doc: dict[str, Any]) -> str:
    return " ".join([
        str(doc.get("id", "")),
        str(doc.get("title", "")),
        str(doc.get("hpath", "")),
        str(doc.get("notebook_name", "")),
        str(doc.get("alias", "")),
        str(doc.get("memo", "")),
        " ".join(str(tag) for tag in doc.get("tags", [])),
    ])


def search_terms(query: str, mode: str) -> list[str]:
    if mode == "regex":
        return [query]
    terms = []
    for quoted, word in re.findall(r'"([^"]+)"|(\S+)', query):
        token = quoted or word
        if token.upper() in ("AND", "OR", "NOT"):
            continue
        token = token.strip("*")
        if token:
            terms.append(token)
    return terms


def query_matches(text: str, query: str) -> bool:
    folded = text.casefold()
    parts = re.split(r"\s+OR\s+", query, flags=re.IGNORECASE)
    return any(query_part_matches(folded, part) for part in parts)


def query_part_matches(folded_text: str, query: str) -> bool:
    required: list[str] = []
    denied: list[str] = []
    negate = False
    for raw in re.findall(r'"[^"]+"|\S+', query):
        token = raw.strip()
        upper = token.upper()
        if upper == "AND":
            continue
        if upper == "NOT":
            negate = True
            continue
        if negate:
            denied.append(token)
            negate = False
        else:
            required.append(token)
    return all(query_token_matches(folded_text, token) for token in required) and not any(
        query_token_matches(folded_text, token) for token in denied
    )


def query_token_matches(folded_text: str, token: str) -> bool:
    text = token.strip('"').casefold()
    if text.endswith("*"):
        text = text[:-1]
    return bool(text and text in folded_text)


def merge_search_results(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for item in group:
            doc_id = str(item.get("id", ""))
            if not doc_id:
                continue
            if doc_id in merged:
                existing = merged[doc_id]
                if item.get("snippet") and not existing.get("snippet"):
                    existing["snippet"] = item["snippet"]
                if item.get("source") and item["source"] not in str(existing.get("source", "")):
                    existing["source"] = f"{existing.get('source')}, {item['source']}"
            else:
                merged[doc_id] = dict(item)
    results = list(merged.values())
    results.sort(key=lambda r: (str(r.get("notebook_name", "")).casefold(), str(r.get("hpath", "")).casefold()))
    return results


def tool_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": "siyuan_start",
            "description": "Refresh the safe index and return the mandatory startup packet: notebook overview table, index.md (if it exists — an AI-generated semantic navigation map), START_HERE.md, and guide.md. Always call this first — it ensures the index is up to date.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "siyuan_refresh_index",
            "description": "Explicitly refresh the safe SiYuan index when the user asks or the index is missing/stale. Also cleans ai_workspace (preserves README.md).",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "siyuan_list",
            "description": "List visible notebooks (no arguments) or return the document tree for one notebook (provide notebook_id or notebook_name). When listing documents, word counts and update times are included.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "notebook_id": {"type": "string", "description": "Notebook ID. Omit to list all notebooks."},
                    "notebook_name": {"type": "string", "description": "Notebook name. Omit to list all notebooks."},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "siyuan_find_documents",
            "description": "Search the SiYuan knowledge base. Uses the safe local index for document titles, paths, tags, and notebook names, and live SiYuan search for block content when available. Supports 4 modes: keyword (space-separated keywords, AND logic, default), query (AND/OR/NOT/phrase/prefix*), regex, sql (direct SQL, requires admin). Scope: headings (document titles + headings, default) or full (all block text).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Search query. For keyword mode: space-separated terms (AND logic). For query mode: FTS5 syntax. For regex mode: Go RE2 regex. For sql mode: raw SQL statement."},
                    "mode": {"type": "string", "enum": ["keyword", "query", "regex", "sql"], "default": "keyword", "description": "Search mode. Must be explicit."},
                    "scope": {"type": "string", "enum": ["headings", "full"], "default": "headings", "description": "headings = document titles and outline headings only. full = all block content."},
                    "notebooks": {"description": "Notebook ID or list of IDs to scope the search. 'ALL' (default) searches all notebooks."},
                    "limit": {"type": "integer", "default": 20, "description": "Maximum results."},
                },
                "required": ["keyword"],
                "additionalProperties": False,
            },
        },
        {
            "name": "siyuan_read_document",
            "description": "Read a visible SiYuan document as Markdown. Always returns the document outline (heading to chunk mapping). Short documents (≤max_chars) return the full text. Long documents return the outline plus one chunk; use chunk=0 for the first chunk or chunk=N to jump to a specific chunk.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string", "description": "Document id, exact hpath, title, or unique partial match."},
                    "chunk": {"type": "integer", "default": 0, "description": "0=auto (chunk 1 for long docs, full text for short docs), 1..N=specific chunk."},
                    "max_chars": {"type": "integer", "default": DEFAULT_CHUNK_CHARS, "description": "Characters per chunk, 2000–30000."},
                },
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
        {
            "name": "siyuan_privacy",
            "description": "Manage persistent hide rules. action='hide': hide a notebook, document, or subtree and refresh the index. action='unhide': remove the hide rule and refresh. Both require confirmed=true. Changes persist across sessions.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["hide", "unhide"], "description": "Whether to add or remove a hide rule."},
                    "scope": {"type": "string", "enum": ["notebook", "document", "subtree"], "description": "What to hide or unhide."},
                    "locator": {"type": "string", "description": "Notebook name/id, document id, exact hpath, title, or unique partial match."},
                    "reason": {"type": "string", "description": "Optional reason for hiding."},
                    "confirmed": {"type": "boolean", "description": "Must be true. This is a destructive privacy action."},
                },
                "required": ["action", "scope", "locator", "confirmed"],
                "additionalProperties": False,
            },
        },
        {
            "name": "siyuan_temporary_allow",
            "description": "Manage temporary allow rules for hidden content. action='open': temporarily allow a hidden notebook, document, or subtree (expires in N minutes, requires confirmed=true). action='close': immediately clear all temporary allow rules. Items become hidden again after expiry or close.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["open", "close"], "default": "open", "description": "open = add a temporary allow rule; close = clear all temporary allow rules."},
                    "scope": {"type": "string", "enum": ["notebook", "document", "subtree"], "description": "What to temporarily allow. Required for action='open'."},
                    "locator": {"type": "string", "description": "Notebook name/id, document id, exact hpath, title, or unique partial match. Required for action='open'."},
                    "minutes": {"type": "integer", "default": 60, "description": "How many minutes before the allow expires. Only for action='open'."},
                    "reason": {"type": "string", "description": "Optional reason for the temporary allow."},
                    "confirmed": {"type": "boolean", "description": "Must be true for action='open'. Only set after explicit user approval."},
                },
                "additionalProperties": False,
            },
        },
    ]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def split_markdown_chunks(markdown: str, *, max_chars: int = DEFAULT_CHUNK_CHARS) -> list[str]:
    text = markdown.strip()
    if not text:
        return [""]
    blocks = re.split(r"(\n{2,})", text)
    units = []
    for index in range(0, len(blocks), 2):
        block = blocks[index]
        sep = blocks[index + 1] if index + 1 < len(blocks) else ""
        if block:
            units.append(block + sep)

    chunks: list[str] = []
    current = ""
    for unit in units:
        if len(unit) > max_chars:
            if current.strip():
                chunks.append(current.strip())
                current = ""
            chunks.extend(split_large_unit(unit, max_chars))
            continue
        if current and len(current) + len(unit) > max_chars:
            chunks.append(current.strip())
            current = unit
        else:
            current += unit
    if current.strip() or not chunks:
        chunks.append(current.strip())
    return chunks


def split_large_unit(text: str, max_chars: int) -> list[str]:
    lines = text.splitlines(keepends=True)
    chunks: list[str] = []
    current = ""
    for line in lines:
        if current and len(current) + len(line) > max_chars:
            chunks.append(current.strip())
            current = line
        else:
            current += line
    if current.strip():
        chunks.append(current.strip())
    return chunks


def first_heading(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return "(empty chunk)"


def find_markdown_images(markdown: str) -> list[str]:
    return re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown)


def extract_attachments(markdown: str, client: SiYuanClient, doc_id: str, workspace_root: Path) -> int:
    """Extract all assets (images, PDF, etc.) referenced in markdown to ai_workspace/attachments/<doc_id>/.
    Preserves the original assets/ directory structure. Returns count of successfully extracted files."""
    assets = re.findall(r"\]\(assets/([^)]+)\)", markdown)
    if not assets:
        return 0

    dest_dir = workspace_root / "ai_workspace" / "attachments" / doc_id / "assets"
    dest_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for filename in assets:
        try:
            data = client.get_asset(f"assets/{filename}")
            filepath = dest_dir / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_bytes(data)
            count += 1
        except Exception:
            pass

    return count


def build_outline(markdown: str, chunks: list[str], max_chars: int) -> str:
    heading_pattern = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
    raw: list[tuple[int, str]] = []
    for m in heading_pattern.finditer(markdown):
        raw.append((len(m.group(1)), m.group(2).strip()))

    header = f"## 大纲 ({len(chunks)} chunks, {max_chars:,} 字/chunk)"

    if not raw:
        return header + "\n\n(文档无标题结构)"

    heading_chunk: dict[tuple[int, str], int] = {}
    for level, text in raw:
        marker = "#" * level + " " + text
        found = False
        for i, chunk in enumerate(chunks, start=1):
            if marker in chunk:
                heading_chunk[(level, text)] = i
                found = True
                break
        if not found:
            heading_chunk[(level, text)] = 1

    roots: list[dict[str, Any]] = []
    stack: list[tuple[int, dict[str, Any]]] = []

    for level, text in raw:
        chunk_num = heading_chunk[(level, text)]
        node: dict[str, Any] = {"text": text, "level": level, "chunk": chunk_num, "children": []}

        while stack and stack[-1][0] >= level:
            stack.pop()

        if stack:
            stack[-1][1]["children"].append(node)
        else:
            roots.append(node)

        stack.append((level, node))

    def _fmt(node: dict[str, Any], indent: int) -> list[str]:
        prefix = "  " * indent
        if node["children"]:
            child_chunks = [c["chunk"] for c in node["children"]]
            all_c = [node["chunk"]] + child_chunks
            mn, mx = min(all_c), max(all_c)
            cs = f"**chunk {mn}**" if mn == mx else f"**chunk {mn}-{mx}**"
        else:
            cs = f"chunk {node['chunk']}"

        lines = [f"{prefix}- {node['text']} → {cs}"]
        for child in node["children"]:
            lines.extend(_fmt(child, indent + 1))
        return lines

    body: list[str] = []
    for r in roots:
        body.extend(_fmt(r, 0))

    return header + "\n\n" + "\n".join(body)


def make_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def make_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def write_message(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
