from __future__ import annotations

import json
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .cli import get_working_client, load_live_docs
from .client import SiYuanApiError, SiYuanClient, SiYuanConnectionError
from .config import load_config
from .ignore import (
    PrivacyRules,
    compile_rules,
    filter_documents,
    load_privacy_rules,
    rule_matches_doc,
    write_privacy_rules_cache,
)
from .indexer import (
    KNOWLEDGE_BASE_DIR,
    build_notebook_overview,
    compute_word_count,
    ensure_notebooks_open,
    extract_snippet,
    format_date,
    load_docs,
    refresh_index,
    render_doc_tree,
    resolve_document,
    search_content,
)
from .agent_notebook import (
    AgentNotebookState,
    ensure_agent_notebook,
    is_privacy_rules_document,
    is_system_notebook_name,
)
from .i18n import build_language_config


SERVER_NAME = "siyuan-agent-bridge"
SERVER_VERSION = "0.1.0"
DEFAULT_SNIPPETS_PER_DOC = 5


def normalize_new_document_markdown(title: str, markdown: str) -> str:
    """Remove the first H1 line if it duplicates the document title."""
    lines = markdown.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# ") and stripped[2:].strip() == title.strip():
            del lines[i]
            return "\n".join(lines)
        # Stop at first non-empty line — only strip immediate duplicate H1
        break
    return markdown


SKIP_BLOCK_TYPES = frozenset({"l", "d"})
SUBTREE_MARKDOWN_BLOCK_TYPES = frozenset({"i", "t"})
COMMENT_ONLY_BLOCK_TYPES = frozenset({"s"})
CHILD_TRAVERSAL_BLOCK_TYPES = frozenset({"h", "l", "s"})


def block_field(block: dict[str, Any], *names: str) -> str:
    for name in names:
        value = block.get(name)
        if value is not None:
            return str(value)
    return ""


def block_sort_key(block: dict[str, Any]) -> tuple[int, str]:
    raw = block.get("sort", 0)
    try:
        sort = int(raw)
    except (TypeError, ValueError):
        sort = 0
    return (sort, block_field(block, "id"))


def render_block_with_id(block: dict[str, Any]) -> str:
    block_type = block_field(block, "type")
    block_id = block_field(block, "id")

    if not block_id or block_type in SKIP_BLOCK_TYPES:
        return ""

    subtype = block_field(block, "subtype", "subType")
    subtype_str = f" subtype={subtype}" if subtype else ""
    comment = f"<!-- siyuan:block id={block_id} type={block_type}{subtype_str} -->"

    if block_type in COMMENT_ONLY_BLOCK_TYPES:
        return comment

    block_md = block_field(block, "markdown")
    if not block_md.strip():
        return ""

    return f"{comment}\n{block_md}"


def build_markdown_from_blocks(blocks: list[dict[str, Any]], root_id: str | None = None) -> str:
    """Build markdown from block records, each prefixed with its block ID comment.

    When root_id is provided, traverse parent_id + sort as a block tree instead of
    treating sort as a document-global order.
    """
    if not root_id:
        return "\n\n".join(rendered for block in blocks if (rendered := render_block_with_id(block)))

    children: dict[str, list[dict[str, Any]]] = {}
    for block in blocks:
        parent_id = block_field(block, "parent_id", "parentID")
        children.setdefault(parent_id, []).append(block)

    for child_blocks in children.values():
        child_blocks.sort(key=block_sort_key)

    parts: list[str] = []
    visited: set[str] = set()

    def mark_descendants_visited(parent_id: str) -> None:
        for child in children.get(parent_id, []):
            child_id = block_field(child, "id")
            if not child_id or child_id in visited:
                continue
            visited.add(child_id)
            mark_descendants_visited(child_id)

    def visit(block: dict[str, Any]) -> None:
        block_id = block_field(block, "id")
        if not block_id or block_id in visited:
            return
        visited.add(block_id)

        rendered = render_block_with_id(block)
        if rendered:
            parts.append(rendered)

        block_type = block_field(block, "type")
        if block_type in SUBTREE_MARKDOWN_BLOCK_TYPES:
            mark_descendants_visited(block_id)
            return

        for child in children.get(block_id, []):
            visit(child)

    for child in children.get(root_id, []):
        visit(child)

    for block in sorted(blocks, key=lambda item: (block_field(item, "parent_id", "parentID"), *block_sort_key(item))):
        visit(block)

    return "\n\n".join(parts)


def build_markdown_from_child_blocks(client: Any, root_id: str) -> str:
    """Build a block-ID diagnostic view using SiYuan's child-block order."""
    parts: list[str] = []
    visited: set[str] = set()

    def visit(block: dict[str, Any]) -> None:
        block_id = block_field(block, "id")
        if not block_id or block_id in visited:
            return
        visited.add(block_id)

        rendered = render_block_with_id(block)
        if rendered:
            parts.append(rendered)

        block_type = block_field(block, "type")
        if block_type in SUBTREE_MARKDOWN_BLOCK_TYPES:
            return
        if block_type not in CHILD_TRAVERSAL_BLOCK_TYPES:
            return

        for child in client.get_child_blocks(block_id):
            visit(child)

    for child in client.get_child_blocks(root_id):
        visit(child)

    return "\n\n".join(parts)


# ── Block Window data model and helpers ──────────────────────────────

DEFAULT_BLOCK_LIMIT = 200
MIN_BLOCK_LIMIT = 1
MAX_BLOCK_LIMIT = 1000
DEFAULT_TOKEN_BUDGET = 50000
MIN_TOKEN_BUDGET = 1000
MAX_TOKEN_BUDGET = 200000
WINDOW_PREVIEW_INTERVAL = 50
WINDOW_PREVIEW_MIN_HEADINGS = 5
WINDOW_PREVIEW_MIN_BLOCKS = 100
WINDOW_PREVIEW_PREFIX_LEN = 80


@dataclass
class DisplayBlock:
    index: int
    id: str
    type: str
    subtype: str
    markdown: str
    estimated_tokens: int
    is_heading: bool = False
    heading_level: int | None = None
    heading_text: str = ""


def estimate_token_count(text: str) -> int:
    """Heuristic token estimator. CJK ~1.0 tok/char, Latin ~1.3 tok/word, digits ~0.8 tok/item, punctuation ~0.4 tok/char."""
    if not text:
        return 0
    cjk = 0
    latin_words = 0
    digits = 0
    punct = 0
    buf = ""
    for ch in text:
        cp = ord(ch)
        if cp >= 0x4E00 and cp <= 0x9FFF or cp >= 0x3400 and cp <= 0x4DBF or cp >= 0x20000 and cp <= 0x2A6DF:
            if buf:
                latin_words += len(buf.split())
                buf = ""
            cjk += 1
        elif ch.isdigit():
            if buf:
                latin_words += len(buf.split())
                buf = ""
            digits += 1
        elif ch.isalpha():
            buf += ch
        else:
            if buf:
                latin_words += len(buf.split())
                buf = ""
            if not ch.isspace() and not cp >= 0x4E00:
                punct += 1
    if buf:
        latin_words += len(buf.split())
    return int(cjk * 1.0 + latin_words * 1.3 + digits * 0.8 + punct * 0.4)


def build_display_blocks(client: Any, root_id: str, *, include_block_ids: bool = False) -> list[DisplayBlock]:
    """Build ordered list of DisplayBlock using SiYuan's getChildBlocks API."""
    blocks: list[DisplayBlock] = []
    visited: set[str] = set()

    def visit(block: dict[str, Any]) -> None:
        block_id = block_field(block, "id")
        if not block_id or block_id in visited:
            return
        visited.add(block_id)

        block_type = block_field(block, "type")
        # Skip document roots and list containers (they are structural)
        if block_type in SKIP_BLOCK_TYPES:
            # Still traverse children of list containers
            if block_type in CHILD_TRAVERSAL_BLOCK_TYPES:
                for child in client.get_child_blocks(block_id):
                    visit(child)
            return

        subtype = block_field(block, "subtype", "subType")
        block_md = block_field(block, "markdown")

        is_heading = block_type == "h"
        heading_level = None
        heading_text = ""
        if is_heading:
            try:
                heading_level = int(subtype[1]) if subtype.startswith("h") else None
            except (ValueError, IndexError):
                heading_level = None
            heading_text = block_md.lstrip("#").strip()

        display_md = block_md
        if block_type in COMMENT_ONLY_BLOCK_TYPES:
            if include_block_ids:
                subtype_str = f" subtype={subtype}" if subtype else ""
                display_md = f"<!-- siyuan:block id={block_id} type={block_type}{subtype_str} -->"
            else:
                for child in client.get_child_blocks(block_id):
                    visit(child)
                return
        elif include_block_ids and block_md.strip():
            subtype_str = f" subtype={subtype}" if subtype else ""
            comment = f"<!-- siyuan:block id={block_id} type={block_type}{subtype_str} -->"
            display_md = f"{comment}\n{block_md}"

        # Skip blocks with no visible content in normal mode
        if not include_block_ids and not block_md.strip():
            if block_type in CHILD_TRAVERSAL_BLOCK_TYPES:
                for child in client.get_child_blocks(block_id):
                    visit(child)
            return

        estimated_tokens = estimate_token_count(block_md)
        blocks.append(DisplayBlock(
            index=len(blocks) + 1,
            id=block_id,
            type=block_type,
            subtype=subtype,
            markdown=display_md,
            estimated_tokens=estimated_tokens,
            is_heading=is_heading,
            heading_level=heading_level,
            heading_text=heading_text,
        ))

        # List items and tables: their markdown already contains subtree content — skip children
        if block_type in SUBTREE_MARKDOWN_BLOCK_TYPES:
            return
        # Continue traversing children for headings, super blocks, list containers
        if block_type in CHILD_TRAVERSAL_BLOCK_TYPES:
            for child in client.get_child_blocks(block_id):
                visit(child)

    for child in client.get_child_blocks(root_id):
        visit(child)

    return blocks


def build_block_outline(display_blocks: list[DisplayBlock]) -> str:
    """Build an outline showing heading block positions."""
    headings = [b for b in display_blocks if b.is_heading]
    if not headings:
        return "## 大纲\n\n(文档无标题结构)"

    roots: list[dict[str, Any]] = []
    stack: list[tuple[int, dict[str, Any]]] = []

    for db in headings:
        node: dict[str, Any] = {
            "text": db.heading_text,
            "level": db.heading_level or 1,
            "block_index": db.index,
            "children": [],
        }

        while stack and stack[-1][0] >= (db.heading_level or 1):
            stack.pop()

        if stack:
            stack[-1][1]["children"].append(node)
        else:
            roots.append(node)

        stack.append((db.heading_level or 1, node))

    def _fmt(node: dict[str, Any], indent: int) -> list[str]:
        prefix = "  " * indent
        lines = [f"{prefix}- block {node['block_index']}: {'#' * node['level']} {node['text']}"]
        for child in node["children"]:
            lines.extend(_fmt(child, indent + 1))
        return lines

    body: list[str] = []
    for r in roots:
        body.extend(_fmt(r, 0))

    total = len(display_blocks)
    parts = [f"## 大纲 ({len(headings)} 个标题, {total} 个展示块)"]
    parts.extend(body)
    return "\n".join(parts)


def build_window_preview(display_blocks: list[DisplayBlock]) -> str:
    """Build a window preview for low-heading, high-block documents.

    Only when headings < 5 AND total blocks > 100.
    Previews every 50 blocks with a short snippet of the block text.
    """
    heading_count = sum(1 for b in display_blocks if b.is_heading)
    total = len(display_blocks)
    if heading_count >= WINDOW_PREVIEW_MIN_HEADINGS or total <= WINDOW_PREVIEW_MIN_BLOCKS:
        return ""

    lines = [
        f"本文档标题较少（{heading_count} 个），抽取每 {WINDOW_PREVIEW_INTERVAL} 个块的开头片段帮助选择阅读窗口：",
        "",
    ]
    for db in display_blocks:
        if (db.index - 1) % WINDOW_PREVIEW_INTERVAL == 0:
            text = db.markdown
            # Strip block ID comment for preview
            if text.startswith("<!-- siyuan:block"):
                text = text.split("-->", 1)[-1].strip()
            snippet = text[:WINDOW_PREVIEW_PREFIX_LEN].replace("\n", " ")
            lines.append(f"- block {db.index}: {snippet}")

    lines.append("")
    return "\n".join(lines)


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
            "siyuan_create_document": self.siyuan_create_document,
            "siyuan_edit_document": self.siyuan_edit_document,
        }
        if name not in tools:
            return make_error(request_id, -32602, f"Unknown tool: {name}")
        try:
            text = tools[name](args)
            return make_result(request_id, {"content": [{"type": "text", "text": text}]})
        except SiYuanConnectionError as exc:
            reason = str(exc).strip()
            if not reason:
                reason = "无法连接到思源笔记"
            return make_result(
                request_id,
                {"content": [{"type": "text", "text": f"思源连接失败：{reason}\n\n请提示用户手动打开思源笔记后重试。"}], "isError": True},
            )
        except (SiYuanApiError, ValueError, FileNotFoundError) as exc:
            return make_result(
                request_id,
                {"content": [{"type": "text", "text": f"Tool failed: {exc}"}], "isError": True},
            )

    def siyuan_start(self, _args: dict[str, Any]) -> str:
        config = load_config(self.root)
        client = get_working_client(config)
        version = client.version()

        # Ensure system notebook and parse privacy rules
        state = ensure_agent_notebook(client, self.root)
        nb_id = state.notebook_id

        # Cache privacy rules for other tools
        write_privacy_rules_cache(self.root, state.privacy_rules)

        # Refresh indexes using cached privacy rules
        refresh_index(
            client, self.root,
            system_notebook_id=nb_id,
            privacy_rules_doc_id=state.privacy_rules_doc_id,
        )

        lang_config = build_language_config(state.language)
        overview = build_notebook_overview(self.root)
        parts: list[str] = [
            "# SiYuan Agent Bridge Startup Packet",
            "",
            f"SiYuan connection: OK, version {version}",
            f"System notebook: `{state.notebook_name}` (`{nb_id}`)",
            "",
            lang_config.startup_header,
            "",
            overview,
        ]

        # Privacy rules status (no specific rules exposed)
        ignore_count = len(state.privacy_rules.ignore)
        if ignore_count > 0:
            notebook_rules = [r for r in state.privacy_rules.ignore if r.get("scope") == "notebook"]
            doc_rules = [r for r in state.privacy_rules.ignore if r.get("scope") == "document"]
            parts.append("")
            parts.append(
                f"隐私规则：已加载，{len(notebook_rules)} 条笔记本规则，"
                f"{len(doc_rules)} 条文档规则。"
            )
        else:
            parts.append("")
            parts.append("隐私规则：已加载，无规则。")

        if state.workspace_index_markdown:
            parts.extend([
                "",
                "## Workspace Index (语义导航索引)",
                "",
                state.workspace_index_markdown.strip(),
            ])
        else:
            parts.extend([
                "",
                "> 当前没有导航索引（Workspace Index）。你可以建议用户先快速扫一遍笔记本结构创建导航索引，之后每次新会话都能直接定位。",
            ])
        parts.extend([
            "",
            "## AI Guide (用户偏好与规则)",
            "",
            state.ai_guide_markdown.strip() if state.ai_guide_markdown else "(AI Guide is empty — use siyuan_propose_guide_update to propose content, then siyuan_apply_guide_update with user approval)",
            "",
        ])
        # Mention About document but don't include full text
        parts.extend([
            "---",
            f"**给人看的说明**：系统笔记本中还有一篇 `/About SiYuan Agent Bridge`，是对工具核心思想的简要介绍。普通任务无需读取。需要时可用 `siyuan_read_document` 指定文档 ID 阅读。",
            "",
        ])
        return "\n".join(parts)

    def siyuan_refresh_index(self, _args: dict[str, Any]) -> str:
        config = load_config(self.root)
        client = get_working_client(config)

        # Ensure system notebook and parse privacy rules
        state = ensure_agent_notebook(client, self.root)
        write_privacy_rules_cache(self.root, state.privacy_rules)

        workspace_dir = self.root / "ai_workspace"
        if workspace_dir.exists():
            for item in workspace_dir.iterdir():
                if item.name == "README.md":
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

        result = refresh_index(
            client, self.root,
            system_notebook_id=state.notebook_id,
            privacy_rules_doc_id=state.privacy_rules_doc_id,
        )
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
        max_snippets_per_doc = max(int(args.get("max_snippets_per_doc") or DEFAULT_SNIPPETS_PER_DOC), 1)

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
        indexed_docs = load_docs(self.root)
        notebook_names = self.load_notebook_names()

        if mode == "sql":
            config = load_config(self.root)
            client = get_working_client(config)
            notebook_names.update(list_live_notebook_names(client))
            try:
                with ensure_notebooks_open(client, notebooks):
                    rows = client.query_sql(keyword)
            except SiYuanApiError as exc:
                if "administrator" in str(exc).casefold() or "privilege" in str(exc).casefold():
                    raise ValueError("SQL search requires SiYuan administrator privileges. Use mode=keyword, mode=query, or mode=regex instead.") from exc
                raise
            enriched = self._enrich_sql_results(rows, indexed_docs, notebook_names, privacy, notebooks)
        else:
            config = load_config(self.root)
            client = get_working_client(config)
            notebook_names.update(list_live_notebook_names(client))
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
            enriched = self._enrich_search_blocks(blocks, indexed_docs, notebook_names, privacy, keywords, notebooks)

        if not enriched:
            return f"# Search: \"{keyword}\" ({scope}, {mode})\n\nNo matching visible documents."

        enriched = enriched[:limit]
        grouped = self._group_by_notebook(enriched)

        scope_label = "标题" if scope == "headings" else "全文"
        lines = [f"# Search: \"{keyword}\" ({scope_label}, {mode}, {len(enriched)} matches in {len(grouped)} notebooks)", ""]

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
                snippets = item.get("snippets")
                if isinstance(snippets, list):
                    shown_snippets = snippets[:max_snippets_per_doc]
                    match_count = int(item.get("match_count") or len(snippets))
                    lines.append(f"  命中块：共 {match_count} 个，展示前 {len(shown_snippets)} 个。")
                    for snippet in shown_snippets:
                        if isinstance(snippet, dict):
                            block_id = str(snippet.get("block_id") or "")
                            text = str(snippet.get("text") or "")
                            if block_id and text:
                                lines.append(f"  > `{block_id}` {text}")
                            elif text:
                                lines.append(f"  > {text}")
                else:
                    snippet = item.get("snippet", "")
                    if snippet:
                        lines.append(f"  > {snippet}")
            lines.append("")
            remaining -= len(items)
            if remaining <= 0:
                break

        return "\n".join(lines)

    def _enrich_search_blocks(
        self,
        blocks: list[dict[str, Any]],
        indexed_docs: list[dict[str, Any]],
        notebook_names: dict[str, str],
        privacy: Any,
        keywords: list[str],
        notebook_filter: list[str] | None,
    ) -> list[dict[str, Any]]:
        doc_index = {str(doc.get("id", "")): doc for doc in indexed_docs}
        compiled_ignore = compile_rules(privacy.ignore, indexed_docs)
        compiled_allow = compile_rules(privacy.allow, indexed_docs)

        results_by_doc: dict[str, dict[str, Any]] = {}
        seen_blocks: set[str] = set()

        for block in blocks:
            doc_id = block_document_id(block)
            block_id = str(block.get("id") or "")
            if not doc_id or (block_id and block_id in seen_blocks):
                continue

            doc = live_doc_from_block(block, doc_index, notebook_names)
            nb_id = str(doc.get("notebook_id", ""))
            if notebook_filter and nb_id not in notebook_filter:
                continue
            if not is_live_doc_visible(doc, compiled_ignore, compiled_allow):
                continue
            # Hard-filter Privacy Rules document
            if is_privacy_rules_document(str(doc.get("hpath", ""))):
                continue

            if block_id:
                seen_blocks.add(block_id)

            content = str(block.get("markdown") or block.get("content") or "")
            snippet = extract_snippet(content, keywords)

            result = results_by_doc.get(doc_id)
            if result is None:
                result = {
                    "id": doc_id,
                    "notebook_id": nb_id,
                    "notebook_name": str(doc.get("notebook_name", "")),
                    "hpath": str(doc.get("hpath", "")),
                    "word_count": doc.get("word_count", 0),
                    "block_count": doc.get("block_count", 0),
                    "updated": str(doc.get("updated", "")),
                    "snippet": snippet,
                    "snippets": [],
                    "match_count": 0,
                    "source": "live search",
                }
                results_by_doc[doc_id] = result
            result["match_count"] += 1
            if snippet:
                result["snippets"].append({"block_id": block_id, "text": snippet})

        results = list(results_by_doc.values())
        results.sort(key=lambda r: (r["notebook_name"].casefold(), r["hpath"].casefold()))
        return results

    def _enrich_sql_results(
        self,
        rows: list[dict[str, Any]],
        indexed_docs: list[dict[str, Any]],
        notebook_names: dict[str, str],
        privacy: Any,
        notebook_filter: list[str] | None,
    ) -> list[dict[str, Any]]:
        doc_index = {str(doc.get("id", "")): doc for doc in indexed_docs}
        compiled_ignore = compile_rules(privacy.ignore, indexed_docs)
        compiled_allow = compile_rules(privacy.allow, indexed_docs)

        seen: set[str] = set()
        results: list[dict[str, Any]] = []

        for row in rows:
            doc_id = block_document_id(row)
            if not doc_id or doc_id in seen:
                continue

            doc = live_doc_from_block(row, doc_index, notebook_names)
            nb_id = str(doc.get("notebook_id", ""))
            if notebook_filter and nb_id not in notebook_filter:
                continue
            if not is_live_doc_visible(doc, compiled_ignore, compiled_allow):
                continue
            # Hard-filter Privacy Rules document
            if is_privacy_rules_document(str(doc.get("hpath", ""))):
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

    def load_notebook_names(self) -> dict[str, str]:
        path = self.root / KNOWLEDGE_BASE_DIR / "notebooks.json"
        if not path.exists():
            return {}
        try:
            notebooks = read_json(path)
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(notebooks, list):
            return {}
        return {
            str(notebook.get("id", "")): str(notebook.get("name", ""))
            for notebook in notebooks
            if isinstance(notebook, dict)
        }

    def siyuan_read_document(self, args: dict[str, Any]) -> str:
        doc = self.resolve_visible_document(args)
        config = load_config(self.root)
        client = get_working_client(config)
        include_block_ids = bool(args.get("include_block_ids"))
        return self._read_document_block_window(doc, client, include_block_ids, args)

    def _read_document_block_window(
        self, doc: dict[str, Any], client: Any, include_block_ids: bool, args: dict[str, Any]
    ) -> str:
        """New block window reading path — uses getChildBlocks for display order."""
        doc_id = str(doc.get("id"))
        notebook_id = str(doc.get("notebook_id", ""))

        with ensure_notebooks_open(client, [notebook_id]):
            display_blocks = build_display_blocks(client, doc_id, include_block_ids=include_block_ids)

        # Fallback: if block build returns empty (e.g., very unusual document), use export
        if not display_blocks:
            with ensure_notebooks_open(client, [notebook_id]):
                markdown = client.export_markdown(doc_id)
            attachment_count = extract_attachments(markdown, client, doc_id, self.root)
            doc_path = str(doc.get("hpath") or doc.get("title") or doc.get("id"))
            markdown_wc = compute_word_count(markdown)
            date = format_date(str(doc.get("updated", "")))
            header_lines = [
                f"# Document: {doc_path}",
                f"Document ID: `{doc_id}`",
                f"字数: {markdown_wc:,} | 块数: {doc.get('block_count', 0)} | 字符: {len(markdown):,} | 更新: {date}",
                "阅读模式: 普通阅读（降级到导出 Markdown）",
            ]
            if attachment_count:
                header_lines.append(f"附件: {attachment_count} 个已提取到 ai_workspace/attachments/{doc_id}/")
            return "\n".join(["\n".join(header_lines), "", "---", "", markdown])

        # Compute stats
        total_blocks = len(display_blocks)
        heading_count = sum(1 for b in display_blocks if b.is_heading)

        # Extract attachments from the markdown (use export for attachment discovery)
        with ensure_notebooks_open(client, [notebook_id]):
            full_md = client.export_markdown(doc_id)
        attachment_count = extract_attachments(full_md, client, doc_id, self.root)

        # Clamp block window params
        block_start = max(int(args.get("block_start") or 1), 1)
        block_limit = clamp_int(args.get("block_limit"), DEFAULT_BLOCK_LIMIT, MIN_BLOCK_LIMIT, MAX_BLOCK_LIMIT)
        token_budget = clamp_int(args.get("token_budget"), DEFAULT_TOKEN_BUDGET, MIN_TOKEN_BUDGET, MAX_TOKEN_BUDGET)

        # Select window
        start_idx = max(block_start - 1, 0)
        end_idx = min(start_idx + block_limit, total_blocks)

        # Apply token budget — include at least one block
        window_blocks: list[DisplayBlock] = []
        token_sum = 0
        for db in display_blocks[start_idx:end_idx]:
            if window_blocks and token_sum + db.estimated_tokens > token_budget:
                break
            window_blocks.append(db)
            token_sum += db.estimated_tokens

        window_tokens = token_sum
        first_idx = window_blocks[0].index if window_blocks else start_idx + 1
        last_idx = window_blocks[-1].index if window_blocks else start_idx

        # Build header
        doc_path = str(doc.get("hpath") or doc.get("title") or doc.get("id"))
        date = format_date(str(doc.get("updated", "")))
        total_chars = sum(len(b.markdown) for b in display_blocks)

        mode_label = "引用阅读（已插入块 ID 注释）" if include_block_ids else "普通阅读"
        header_lines = [
            f"# Document: {doc_path}",
            f"Document ID: `{doc_id}`",
            f"展示块: {first_idx}-{last_idx} / {total_blocks}",
            f"估算 tokens: {window_tokens:,} / {token_budget:,}",
        ]
        if start_idx + block_limit < total_blocks:
            next_start = last_idx + 1
            header_lines.append(f"下一窗口: block_start={next_start}, block_limit={block_limit}")
        header_lines.append(f"阅读模式: {mode_label}")
        if attachment_count:
            header_lines.append(f"附件: {attachment_count} 个已提取到 ai_workspace/attachments/{doc_id}/")
        header = "\n".join(header_lines)

        # Build outline (always full document outline with block positions)
        outline = build_block_outline(display_blocks)

        # Build window preview (only when headings < 5 AND total blocks > 100)
        window_preview = build_window_preview(display_blocks)

        # Build block text for current window
        body_lines: list[str] = []
        for db in window_blocks:
            if db.markdown.strip():
                body_lines.append(db.markdown)
        body = "\n\n".join(body_lines)

        parts = [header, "", outline]
        if window_preview:
            parts.extend(["", window_preview])
        parts.extend(["", "---", "", body])

        if last_idx < total_blocks:
            parts.extend([
                "",
                "---",
                f"> 继续阅读: `block_start={last_idx + 1}, block_limit={block_limit}`",
            ])

        return "\n".join(parts)

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
        doc = matches[0]
        if is_privacy_rules_document(str(doc.get("hpath", ""))):
            raise ValueError(
                "Privacy Rules 文档不可通过 AI 访问。隐私规则由人类在思源中维护。"
            )
        return doc

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

        config = load_config(self.root)
        client = get_working_client(config)

        # Find system notebook and AI Guide document
        state = ensure_agent_notebook(client, self.root)
        if not state.ai_guide_doc_id:
            raise ValueError("AI Guide 文档不存在。请先运行 siyuan_start。")

        nb_id = state.notebook_id
        ai_guide_id = state.ai_guide_doc_id
        current_md = state.ai_guide_markdown

        # Create snapshot before editing
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        memo = f"siyuan-agent-bridge:auto-snapshot tool=siyuan_apply_guide_update created={ts}"
        try:
            client.create_snapshot(memo)
        except SiYuanApiError as exc:
            msg = str(exc)
            if "数据仓库密钥" in msg or "data repo key" in msg.casefold() or "key" in msg.casefold():
                raise ValueError(
                    "Snapshot creation failed: data repo key is not initialized. "
                    "Please open SiYuan → Settings → About → Data Repo Key, initialize the key, then retry."
                ) from exc
            raise ValueError(f"Snapshot creation failed, refusing to write. Error: {msg}") from exc

        if mode == "replace":
            new_md = content.rstrip() + "\n"
        elif mode == "append":
            new_md = current_md.rstrip() + "\n\n" + content.rstrip() + "\n"
        else:
            raise ValueError("mode must be append or replace")

        with ensure_notebooks_open(client, [nb_id]):
            client.update_block(ai_guide_id, new_md)

        try:
            client.push_msg("SiYuan Agent Bridge: AI Guide 已更新 / updated")
        except Exception:
            pass

        return f"AI Guide 已更新。Run siyuan_start before using the updated guide."

    def siyuan_create_document(self, args: dict[str, Any]) -> str:
        confirmed = bool(args.get("confirmed"))
        if not confirmed:
            raise ValueError("confirmed=true is required. Writing to SiYuan requires explicit user approval.")

        notebook_id = str(args.get("notebook_id") or "").strip()
        if not notebook_id:
            raise ValueError("notebook_id is required")

        title = str(args.get("title") or "").strip()
        if not title:
            raise ValueError("title is required")

        markdown = str(args.get("markdown") or "").strip()
        if not markdown:
            raise ValueError("markdown is required")

        path = str(args.get("path") or "").strip()
        if not path:
            path = f"/{title}"
        elif not path.startswith("/"):
            path = f"/{path}"

        # Check notebook is visible
        notebooks = read_json(self.root / KNOWLEDGE_BASE_DIR / "notebooks.json")
        nb = next((n for n in notebooks if str(n.get("id", "")) == notebook_id), None)
        if nb is None:
            raise ValueError(f"Notebook {notebook_id} is not visible. It may be hidden by privacy rules.")

        # Prevent creating Privacy Rules document
        if is_privacy_rules_document(path.strip("/")):
            raise ValueError(
                "Privacy Rules 文档不可通过 AI 创建。隐私规则由人类在思源中维护。"
            )

        config = load_config(self.root)
        client = get_working_client(config)

        # Create snapshot before writing
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        memo = f"siyuan-agent-bridge:auto-snapshot tool=siyuan_create_document target={title} created={ts}"
        try:
            client.create_snapshot(memo)
            snapshot_status = "created"
        except SiYuanApiError as exc:
            msg = str(exc)
            if "数据仓库密钥" in msg or "data repo key" in msg.casefold() or "key" in msg.casefold():
                raise ValueError(
                    "Snapshot creation failed: data repo key is not initialized. "
                    "Please open SiYuan → Settings → About → Data Repo Key, initialize the key, then retry."
                ) from exc
            raise ValueError(f"Snapshot creation failed, refusing to write. Error: {msg}") from exc

        # Normalize markdown to avoid duplicate H1
        markdown = normalize_new_document_markdown(title, markdown)
        if not markdown.strip():
            raise ValueError("markdown is required")

        # Create document
        with ensure_notebooks_open(client, [notebook_id]):
            result = client.create_doc_with_md(notebook_id, path, markdown)

        doc_id = str(result.get("id") or result.get("docID") or result.get("doc_id") or "")
        if not doc_id:
            # Try to resolve by path
            try:
                live_docs = load_live_docs(client)
                for doc in live_docs:
                    if str(doc.get("hpath", "")).strip("/") == path.strip("/") and str(doc.get("notebook_id", "")) == notebook_id:
                        doc_id = str(doc.get("id", ""))
                        break
            except Exception:
                pass

        # Notify
        try:
            client.push_msg(f"SiYuan Agent Bridge: created \"{title}\"")
        except Exception:
            pass

        # Auto-refresh index
        refresh_ok = False
        try:
            refresh_index(client, self.root)
            refresh_ok = True
        except Exception:
            pass

        notebook_name = str(nb.get('name', notebook_id))
        parts = [
            "# 文档创建成功",
            "",
            f"**标题:** {title}",
            f"**路径:** {path}",
            f"**笔记本:** {notebook_name} (`{notebook_id}`)",
        ]
        if doc_id:
            parts.append(f"**文档 ID:** `{doc_id}`")
        parts.append(f"**端点:** {client.base_url}")
        parts.append(f"**快照:** {snapshot_status}")
        if refresh_ok:
            parts.append(f"**索引:** 已自动刷新")
        else:
            parts.append(f"**索引:** 自动刷新失败，请手动运行 `siyuan_refresh_index`")
        parts.extend([
            "",
            "如需回滚，可通过思源快照手动恢复。",
        ])
        return "\n".join(parts)

    def siyuan_edit_document(self, args: dict[str, Any]) -> str:
        confirmed = bool(args.get("confirmed"))
        if not confirmed:
            raise ValueError("confirmed=true is required. Editing SiYuan documents requires explicit user approval.")

        doc = self.resolve_visible_document(args)
        doc_id = str(doc.get("id", ""))
        doc_title = str(doc.get("hpath") or doc.get("title") or doc_id)
        notebook_id = str(doc.get("notebook_id", ""))

        old_text = str(args.get("old_text") or "")
        new_text = str(args.get("new_text") or "")

        if not old_text and not new_text:
            raise ValueError("old_text and new_text cannot both be empty")

        config = load_config(self.root)
        client = get_working_client(config)

        if not old_text:
            # Append mode: old_text is empty, append new_text to document end
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            memo = f"siyuan-agent-bridge:auto-snapshot tool=siyuan_edit_document target={doc_title} created={ts}"
            try:
                client.create_snapshot(memo)
                snapshot_status = "created"
            except SiYuanApiError as exc:
                msg = str(exc)
                if "数据仓库密钥" in msg or "data repo key" in msg.casefold() or "key" in msg.casefold():
                    raise ValueError(
                        "Snapshot creation failed: data repo key is not initialized. "
                        "Please open SiYuan → Settings → About → Data Repo Key, initialize the key, then retry."
                    ) from exc
                raise ValueError(f"Snapshot creation failed, refusing to write. Error: {msg}") from exc

            with ensure_notebooks_open(client, [notebook_id]):
                result = client.append_block(doc_id, new_text)

            try:
                client.push_msg(f"SiYuan Agent Bridge: appended to \"{doc_title}\"")
            except Exception:
                pass

            return "\n".join([
                "# Document Edited (append)",
                "",
                f"**Document:** {doc_title} (`{doc_id}`)",
                f"**Operation:** appended new block to end of document",
                f"**Endpoint:** {client.base_url}",
                f"**Snapshot:** {snapshot_status}",
                "",
                "The user can manually roll back via SiYuan snapshots if needed.",
            ])

        # Text anchor mode: search for old_text in document blocks
        with ensure_notebooks_open(client, [notebook_id]):
            match_result = self._match_old_text(client, doc_id, old_text)

        match_type = match_result[0]

        if match_type == "not_found":
            raise ValueError(
                f"old_text not found in document \"{doc_title}\". "
                "The document may have been modified since you last read it. "
                "Please re-read the document with siyuan_read_document and provide the exact current text."
            )

        if match_type == "ambiguous":
            matches = match_result[3]
            context_lines = ["old_text matches multiple blocks. Provide a longer old_text to disambiguate:\n"]
            for i, (bid, md, _) in enumerate(matches[:5], 1):
                preview = md[:80].replace("\n", " ")
                context_lines.append(f"  {i}. block `{bid}`: \"{preview}...\"")
            raise ValueError("\n".join(context_lines))

        # Single match
        block_id = str(match_result[1])
        block_md = str(match_result[2])

        # Create snapshot before writing
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        memo = f"siyuan-agent-bridge:auto-snapshot tool=siyuan_edit_document target={doc_title} created={ts}"
        try:
            client.create_snapshot(memo)
            snapshot_status = "created"
        except SiYuanApiError as exc:
            msg = str(exc)
            if "数据仓库密钥" in msg or "data repo key" in msg.casefold() or "key" in msg.casefold():
                raise ValueError(
                    "Snapshot creation failed: data repo key is not initialized. "
                    "Please open SiYuan → Settings → About → Data Repo Key, initialize the key, then retry."
                ) from exc
            raise ValueError(f"Snapshot creation failed, refusing to write. Error: {msg}") from exc

        # Execute the edit
        if old_text.strip() == block_md.strip():
            # Full block replacement
            new_block_md = new_text
        else:
            # Substring replacement within the block
            new_block_md = block_md.replace(old_text, new_text)

        with ensure_notebooks_open(client, [notebook_id]):
            client.update_block(block_id, new_block_md)

        try:
            client.push_msg(f"SiYuan Agent Bridge: edited \"{doc_title}\"")
        except Exception:
            pass

        preview = new_text[:200] if new_text else "(text deleted)"
        return "\n".join([
            "# Document Edited",
            "",
            f"**Document:** {doc_title} (`{doc_id}`)",
            f"**Changed block:** `{block_id}`",
            f"**Changed block count:** 1",
            f"**Endpoint:** {client.base_url}",
            f"**Snapshot:** {snapshot_status}",
            f"**Preview:** {preview}",
            "",
            "The user can manually roll back via SiYuan snapshots if needed.",
        ])

    @staticmethod
    def _match_old_text(
        client: Any, doc_id: str, old_text: str
    ) -> tuple[str, str | None, str | None, list[tuple[str, str, bool]]]:
        """Search for old_text in document blocks.

        Returns:
            ("found", block_id, block_markdown, matches)  — single match
            ("not_found", None, None, [])                 — no match
            ("ambiguous", None, None, matches)            — multiple matches, each (block_id, markdown, is_full)
        """
        rows = client.query_sql(
            f"SELECT id, markdown FROM blocks WHERE root_id = '{doc_id}' "
            "AND type != 'd' AND markdown IS NOT NULL AND markdown != '' "
            "ORDER BY sort"
        )

        matches: list[tuple[str, str, bool]] = []
        for row in rows:
            block_id = str(row.get("id", ""))
            md = str(row.get("markdown", ""))
            if old_text in md:
                matches.append((block_id, md, md.strip() == old_text.strip()))

        if not matches:
            return ("not_found", None, None, [])
        if len(matches) > 1:
            return ("ambiguous", None, None, matches)
        return ("found", matches[0][0], matches[0][1], matches)

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


def list_live_notebook_names(client: Any) -> dict[str, str]:
    return {
        str(notebook.get("id", "")): str(notebook.get("name", ""))
        for notebook in client.list_notebooks()
        if isinstance(notebook, dict)
    }


def block_document_id(block: dict[str, Any]) -> str:
    block_type = str(block.get("type", ""))
    if block_type in ("d", "NodeDocument"):
        return str(block.get("id") or block.get("rootID") or block.get("root_id") or "")
    return str(block.get("rootID") or block.get("root_id") or block.get("id") or "")


def live_doc_from_block(
    block: dict[str, Any],
    doc_index: dict[str, dict[str, Any]],
    notebook_names: dict[str, str],
) -> dict[str, Any]:
    doc_id = block_document_id(block)
    indexed = doc_index.get(doc_id, {})
    notebook_id = str(block.get("box") or indexed.get("notebook_id") or "")
    hpath = str(block.get("hPath") or block.get("hpath") or indexed.get("hpath") or "")
    title = str(indexed.get("title") or hpath.strip("/").split("/")[-1] or block.get("content") or doc_id)
    return {
        "id": doc_id,
        "notebook_id": notebook_id,
        "notebook_name": str(indexed.get("notebook_name") or notebook_names.get(notebook_id) or notebook_id),
        "hpath": hpath or str(indexed.get("hpath") or title),
        "path": str(block.get("path") or indexed.get("path") or ""),
        "title": title,
        "word_count": indexed.get("word_count", 0),
        "block_count": indexed.get("block_count", 0),
        "updated": str(block.get("updated") or indexed.get("updated") or ""),
    }


def is_live_doc_visible(
    doc: dict[str, Any],
    compiled_ignore: list[dict[str, Any]],
    compiled_allow: list[dict[str, Any]],
) -> bool:
    ignored = any(rule_matches_live_doc(rule, doc) for rule in compiled_ignore)
    allowed = any(rule_matches_live_doc(rule, doc) for rule in compiled_allow)
    return not ignored or allowed


def rule_matches_live_doc(rule: dict[str, Any], doc: dict[str, Any]) -> bool:
    if rule_matches_doc(rule, doc):
        return True
    if str(rule.get("scope") or "").strip().casefold() not in ("document", "subtree"):
        return False
    root_id = str(rule.get("id") or "")
    path = str(doc.get("path") or "")
    return bool(root_id and f"/{root_id}/" in path)


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
            "description": "Refresh the safe index, ensure the system notebook 思源代理桥 and its fixed documents, and return the mandatory startup packet: notebook overview table, Workspace Index (if it exists — an AI-generated semantic navigation map), and AI Guide (user preferences and rules). Always call this first — it ensures the index is up to date.",
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
            "description": "Search the SiYuan knowledge base through SiYuan search APIs, then apply privacy rules before returning results. Temporarily opens closed notebooks while searching and restores them afterwards. Supports 4 modes: keyword (space-separated keywords, AND logic, default), query (AND/OR/NOT/phrase/prefix*), regex, sql (direct SQL, requires admin). Scope: headings (document titles + headings, default) or full (all block text).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Search query. For keyword mode: space-separated terms (AND logic). For query mode: FTS5 syntax. For regex mode: Go RE2 regex. For sql mode: raw SQL statement."},
                    "mode": {"type": "string", "enum": ["keyword", "query", "regex", "sql"], "default": "keyword", "description": "Search mode. Must be explicit."},
                    "scope": {"type": "string", "enum": ["headings", "full"], "default": "headings", "description": "headings = document titles and outline headings only. full = all block content."},
                    "notebooks": {"description": "Notebook ID or list of IDs to scope the search. 'ALL' (default) searches all notebooks."},
                    "limit": {"type": "integer", "default": 20, "description": "Maximum document results."},
                    "max_snippets_per_doc": {"type": "integer", "default": DEFAULT_SNIPPETS_PER_DOC, "description": "Maximum matching blocks to display per document. The result still reports the total matching block count."},
                },
                "required": ["keyword"],
                "additionalProperties": False,
            },
        },
        {
            "name": "siyuan_read_document",
            "description": "Read a visible SiYuan document as Markdown. Always returns the document outline (heading to block mapping). Reads in block window mode using SiYuan's native block order, returning complete consecutive blocks without mid-character truncation. Use block_start/block_limit for pagination, token_budget as a safety valve. Set include_block_ids=true for reference reading (precise block references and edit targeting).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string", "description": "Document id, exact hpath, title, or unique partial match."},
                    "block_start": {"type": "integer", "default": 1, "description": "Starting display block index (1-based). Default 1 reads from the first block."},
                    "block_limit": {"type": "integer", "default": DEFAULT_BLOCK_LIMIT, "description": "Maximum display blocks to return in this window, 1–1000."},
                    "token_budget": {"type": "integer", "default": DEFAULT_TOKEN_BUDGET, "description": "Estimated token ceiling for this window. Blocks stop before exceeding budget (at least one block always returned)."},
                    "include_block_ids": {"type": "boolean", "default": False, "description": "Enable reference reading — injects block ID HTML comments for precise cross-document block references and edit targeting."},
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
            "description": "Append or replace the AI Guide document in the 思源代理桥 system notebook only after explicit user approval. Requires confirmed=true. Creates a SiYuan workspace snapshot before writing.",
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
            "name": "siyuan_create_document",
            "description": "Create a new SiYuan document in the specified notebook. Creates a SiYuan workspace snapshot before writing. Refuses to write if the snapshot fails, if the notebook is hidden, or if confirmed is not true. The user can manually roll back via SiYuan snapshots if needed.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "notebook_id": {"type": "string", "description": "Notebook ID to create the document in."},
                    "title": {"type": "string", "description": "Document title."},
                    "path": {"type": "string", "description": "Optional path within the notebook. Defaults to /<title>."},
                    "markdown": {"type": "string", "description": "Markdown content for the new document."},
                    "confirmed": {"type": "boolean", "description": "Must be true. Writing to SiYuan requires explicit user approval."},
                },
                "required": ["notebook_id", "title", "markdown", "confirmed"],
                "additionalProperties": False,
            },
        },
        {
            "name": "siyuan_edit_document",
            "description": "Edit a visible SiYuan document using an exact old_text -> new_text anchor. Creates a SiYuan workspace snapshot before writing. Refuses ambiguous, missing, hidden, or unconfirmed edits. old_text=\"\" appends new_text to document end. old_text=\"原文\", new_text=\"\" deletes matching text. Only single-block edits are supported in this phase; cross-block text returns an error asking the AI to re-read and make multiple single-block edits.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string", "description": "Document id, exact hpath, title, or unique partial match."},
                    "old_text": {"type": "string", "default": "", "description": "Exact text to find (from the Markdown you just read). Empty = append new_text to document end."},
                    "new_text": {"type": "string", "default": "", "description": "Replacement text. Empty with non-empty old_text = delete the matching text."},
                    "confirmed": {"type": "boolean", "description": "Must be true. Editing SiYuan documents requires explicit user approval."},
                },
                "required": ["document_id", "old_text", "new_text", "confirmed"],
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


def make_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def make_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def write_message(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
