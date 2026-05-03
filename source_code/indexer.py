from __future__ import annotations

import json
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Iterable

from .client import SiYuanClient
from .ignore import filter_documents, filter_notebooks, load_privacy_rules


KNOWLEDGE_BASE_DIR = "knowledge_base"
AI_WORKSPACE_DIR = "ai_workspace"
SYSTEM_NOTEBOOK_NAME = "思源代理桥"

ABOUT_TEMPLATE = """<!-- template_version: 1 -->

# 关于 SiYuan Agent Bridge / About SiYuan Agent Bridge

本文档由 SiYuan Agent Bridge 自动维护，可能在刷新时更新。请不要在这里记录个人内容。This document is maintained by SiYuan Agent Bridge and may be updated during refresh. Do not store personal notes here.

SiYuan Agent Bridge 是连接思源笔记和 AI agent 的本地桥接工具。它让 AI 在隐私规则保护下阅读、搜索和维护你的思源知识库。SiYuan Agent Bridge is a local bridge between SiYuan notes and AI agents, letting AI read, search, and maintain your knowledge base under privacy rules.

## 系统笔记本里的三份文档 / Three Documents in This Notebook

- **AI Guide**：给 AI 看的长期规则，你可以在这里写下偏好、重点笔记本、写作风格和限制。AI Guide stores long-term instructions for AI — your preferences, important notebooks, writing style, and constraints.
- **Workspace Index**：AI 生成的语义导航索引，帮助新会话快速了解这个工作空间里有什么。Workspace Index is an AI-generated semantic navigation map for new sessions.
- **About SiYuan Agent Bridge**：就是本文档，给人看的工具说明。About SiYuan Agent Bridge is this document — a human-readable introduction to the tool.

## 日常怎么用 / How to Use

你平时正常在思源里写笔记。需要时告诉 AI"帮我查一下笔记里关于 XX 的内容"。如果某些笔记不想被 AI 看到，使用隐藏规则，不要删除或隐藏这个系统笔记本。You write notes in SiYuan as usual. When needed, ask AI to search your notes. To hide content from AI, use hide rules — do not delete or hide this system notebook.

更多信息请阅读项目 README、项目网站，或联系开发者。For more details, read the project README, visit the project website, or contact the developer.
"""

ABOUT_TEMPLATE_VERSION_MARKER = "<!-- template_version: 1 -->"

DOCS_SQL = """
SELECT
  id, box, path, hpath, name, alias, memo, tag, content, markdown, type, created, updated
FROM blocks
WHERE type = 'd'
ORDER BY box, hpath
LIMIT 100000
""".strip()

@dataclass(frozen=True)
class RefreshResult:
    total_notebook_count: int
    total_document_count: int
    notebook_count: int
    document_count: int
    hidden_notebook_count: int
    hidden_document_count: int
    cache_dir: Path


@contextmanager
def ensure_notebooks_open(
    client: SiYuanClient,
    notebook_ids: Iterable[str] | None = None,
) -> Generator[None, None, None]:
    """Temporarily open closed notebooks, restoring original state afterwards.

    If *notebook_ids* is None, all closed notebooks are opened.
    Otherwise only the specified IDs are opened.
    """
    all_notebooks = client.list_notebooks()
    closed_map: dict[str, bool] = {}
    for nb in all_notebooks:
        nid = str(nb.get("id", ""))
        if nid and nb.get("closed"):
            closed_map[nid] = True

    to_open: set[str]
    if notebook_ids is None:
        to_open = set(closed_map)
    else:
        to_open = {str(nid) for nid in notebook_ids} & set(closed_map)

    for nid in to_open:
        client.open_notebook(nid)

    # SiYuan loads notebook data asynchronously — poll until all are available
    pending = set(to_open)
    if pending:
        deadline = time.monotonic() + 10.0
        while pending and time.monotonic() < deadline:
            for nid in list(pending):
                rows = client.query_sql(
                    f"SELECT 1 FROM blocks WHERE type='d' AND box='{nid}' LIMIT 1"
                )
                if rows:
                    pending.discard(nid)
            if pending:
                time.sleep(0.5)
    try:
        yield
    finally:
        for nid in to_open:
            client.close_notebook(nid)


def ensure_system_notebook(client: SiYuanClient, root: Path) -> dict[str, Any]:
    """Ensure the system notebook and its fixed documents exist.

    Returns a dict with keys: notebook_id, ai_guide_exists, workspace_index_exists, about_exists.
    """
    notebooks = client.list_notebooks()
    system_nb = None
    for nb in notebooks:
        if str(nb.get("name", "")) == SYSTEM_NOTEBOOK_NAME:
            system_nb = nb
            break

    if system_nb is None:
        result = client.create_notebook(SYSTEM_NOTEBOOK_NAME)
        nb_id = str(result.get("id", ""))
        if not nb_id:
            # Re-list to find the newly created notebook
            for nb in client.list_notebooks():
                if str(nb.get("name", "")) == SYSTEM_NOTEBOOK_NAME:
                    nb_id = str(nb.get("id", ""))
                    break
        if not nb_id:
            raise RuntimeError(f"无法创建系统笔记本: {SYSTEM_NOTEBOOK_NAME}")
    else:
        nb_id = str(system_nb.get("id", ""))

    # Ensure /AI Guide
    ai_guide_exists = False
    with ensure_notebooks_open(client, [nb_id]):
        for doc in client.query_sql(f"SELECT id, path FROM blocks WHERE type='d' AND box='{nb_id}'"):
            if str(doc.get("path", "")).strip("/") == "/AI Guide":
                ai_guide_exists = True
                break

    if not ai_guide_exists:
        with ensure_notebooks_open(client, [nb_id]):
            guide_content = "# AI Guide\n\n此文档给 AI 看的长期规则。你可以在这里写下偏好、重点笔记本、写作风格和限制。This document stores long-term instructions for AI — your preferences, important notebooks, writing style, and constraints.\n\n## 使用说明 / Usage\n\n- 在思源中直接编辑本文档即可修改规则。Edit this document directly in SiYuan to change rules.\n- `siyuan_refresh_index` 不会覆盖已存在的 AI Guide。siyuan_refresh_index will not overwrite an existing AI Guide.\n- 让 AI 读到的格式是 Markdown，保持简洁。Keep it concise — AI reads Markdown.\n\n## 偏好与规则 / Preferences & Rules\n\n> TODO: 在这里添加你的长期偏好。Add your long-term preferences here.\n"
            client.create_doc_with_md(nb_id, "/AI Guide", guide_content)

    # Ensure /About SiYuan Agent Bridge
    about_exists = False
    about_doc_id = None
    about_content_current = ""
    with ensure_notebooks_open(client, [nb_id]):
        for doc in client.query_sql(f"SELECT id, path, markdown FROM blocks WHERE type='d' AND box='{nb_id}'"):
            if str(doc.get("path", "")).strip("/") == "/About SiYuan Agent Bridge":
                about_exists = True
                about_doc_id = str(doc.get("id", ""))
                about_content_current = str(doc.get("markdown", ""))
                break

    if not about_exists:
        with ensure_notebooks_open(client, [nb_id]):
            client.create_doc_with_md(nb_id, "/About SiYuan Agent Bridge", ABOUT_TEMPLATE)
    elif ABOUT_TEMPLATE_VERSION_MARKER not in about_content_current:
        # Template version changed — overwrite with new version
        with ensure_notebooks_open(client, [nb_id]):
            if about_doc_id:
                client.update_block(about_doc_id, ABOUT_TEMPLATE)

    # Check /Workspace Index (never auto-create)
    workspace_index_exists = False
    with ensure_notebooks_open(client, [nb_id]):
        for doc in client.query_sql(f"SELECT id, path FROM blocks WHERE type='d' AND box='{nb_id}'"):
            if str(doc.get("path", "")).strip("/") == "/Workspace Index":
                workspace_index_exists = True
                break

    return {
        "notebook_id": nb_id,
        "ai_guide_exists": ai_guide_exists,
        "workspace_index_exists": workspace_index_exists,
        "about_exists": about_exists,
    }


def refresh_index(client: SiYuanClient, root: Path) -> RefreshResult:
    cache_dir = root / KNOWLEDGE_BASE_DIR
    workspace_dir = root / AI_WORKSPACE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    all_notebooks = client.list_notebooks()
    privacy = load_privacy_rules(root, include_temporary=False)
    notebooks = filter_notebooks(all_notebooks, privacy)

    with ensure_notebooks_open(client):
        all_docs = normalize_documents(client.query_sql(DOCS_SQL), all_notebooks)
        docs = filter_documents(all_docs, privacy)
        update_document_stats(client, docs)

    write_json(cache_dir / "notebooks.json", notebooks)
    write_jsonl(cache_dir / "docs.jsonl", docs)
    write_text(cache_dir / "tree.md", render_tree(notebooks, docs))
    ensure_text(workspace_dir / "README.md", render_workspace_readme())

    ensure_system_notebook(client, root)

    return RefreshResult(
        total_notebook_count=len(all_notebooks),
        total_document_count=len(all_docs),
        notebook_count=len(notebooks),
        document_count=len(docs),
        hidden_notebook_count=len(all_notebooks) - len(notebooks),
        hidden_document_count=len(all_docs) - len(docs),
        cache_dir=cache_dir,
    )


def compute_word_count(text: str | None) -> int:
    if not text:
        return 0
    cjk_ranges = (
        r'一-鿿㐀-䶿⺀-⻿　-〿＀-￯'
    )
    cjk = len(re.findall(f'[{cjk_ranges}]', text))
    remaining = re.sub(f'[{cjk_ranges}]', ' ', text)
    words = len([w for w in remaining.split() if re.search(r'\w', w)])
    return cjk + words


def format_word_count(count: int) -> str:
    return f"{count:,} 字"


def format_block_count(count: int) -> str:
    return f"{count} 块"


def format_date(ts: str) -> str:
    if not ts or len(ts) < 8:
        return ""
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"


def normalize_documents(
    rows: Iterable[dict[str, Any]],
    notebooks: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    notebook_names = {
        str(item.get("id", "")): str(item.get("name", "") or item.get("id", ""))
        for item in notebooks
    }
    docs: list[dict[str, Any]] = []
    for row in rows:
        doc_id = str(row.get("id", "")).strip()
        if not doc_id:
            continue
        notebook_id = str(row.get("box", "")).strip()
        title = _first_non_empty(row.get("name"), row.get("content"), _title_from_hpath(row.get("hpath")), doc_id)
        hpath = str(row.get("hpath") or "").strip()
        docs.append(
            {
                "id": doc_id,
                "notebook_id": notebook_id,
                "notebook_name": notebook_names.get(notebook_id, notebook_id),
                "hpath": hpath,
                "path": str(row.get("path") or "").strip(),
                "title": title,
                "tags": parse_tags(row.get("tag")),
                "alias": str(row.get("alias") or "").strip(),
                "memo": str(row.get("memo") or "").strip(),
                "word_count": compute_word_count(row.get("content")),
                "created": str(row.get("created") or "").strip(),
                "updated": str(row.get("updated") or "").strip(),
            }
        )
    docs.sort(key=lambda item: (item["notebook_name"].casefold(), item["hpath"].casefold(), item["id"]))
    return docs


BLOCK_STATS_SQL = """
SELECT
  root_id,
  COUNT(*) AS block_count,
  SUM(LENGTH(markdown)) AS char_count
FROM blocks
WHERE type != 'd' AND root_id IS NOT NULL
GROUP BY root_id
LIMIT 100000
""".strip()

ALL_CONTENT_SQL = """
SELECT
  root_id, content
FROM blocks
WHERE type != 'd' AND root_id IS NOT NULL
ORDER BY root_id
LIMIT 1000000
""".strip()


def _fetch_block_stats(client: SiYuanClient) -> dict[str, dict[str, int]]:
    rows = client.query_sql(BLOCK_STATS_SQL)
    stats: dict[str, dict[str, int]] = {}
    for row in rows:
        rid = str(row.get("root_id", ""))
        if rid:
            stats[rid] = {
                "block_count": int(row.get("block_count") or 0),
                "char_count": int(row.get("char_count") or 0),
            }
    return stats


def _compute_word_counts_from_blocks(
    client: SiYuanClient, doc_ids: set[str]
) -> dict[str, int]:
    rows = client.query_sql(ALL_CONTENT_SQL)
    groups: dict[str, list[str]] = {}
    for row in rows:
        rid = str(row.get("root_id", ""))
        if rid and rid in doc_ids:
            groups.setdefault(rid, []).append(str(row.get("content") or ""))
    return {rid: compute_word_count("\n".join(pieces)) for rid, pieces in groups.items()}


def update_document_stats(client: SiYuanClient, docs: list[dict[str, Any]]) -> None:
    stats = _fetch_block_stats(client)
    doc_ids = {str(doc["id"]) for doc in docs}
    word_counts = _compute_word_counts_from_blocks(client, doc_ids)
    for doc in docs:
        did = str(doc["id"])
        s = stats.get(did, {})
        doc["block_count"] = s.get("block_count", 0)
        doc["char_count"] = s.get("char_count", 0)
        doc["word_count"] = word_counts.get(did, 0)


def parse_tags(value: Any) -> list[str]:
    if not value:
        return []
    text = str(value)
    tags = re.findall(r"#([^#]+)#", text)
    if not tags:
        tags = [part for part in re.split(r"[\s,]+", text) if part]
    cleaned = []
    for tag in tags:
        tag = tag.strip()
        if tag and tag not in cleaned:
            cleaned.append(tag)
    return cleaned


def render_tree(notebooks: Iterable[dict[str, Any]], docs: Iterable[dict[str, Any]]) -> str:
    docs_by_notebook: dict[str, list[dict[str, Any]]] = {}
    for doc in docs:
        docs_by_notebook.setdefault(str(doc.get("notebook_id", "")), []).append(doc)

    notebook_list = list(notebooks)
    known_ids = {str(item.get("id", "")) for item in notebook_list}
    for notebook_id in sorted(set(docs_by_notebook) - known_ids):
        notebook_list.append({"id": notebook_id, "name": notebook_id or "Unknown Notebook"})

    # Compute per-notebook stats
    def _stats(nid: str) -> tuple[int, int, int, str]:
        ndocs = docs_by_notebook.get(nid, [])
        nwords = sum(d.get("word_count", 0) for d in ndocs)
        nblocks = sum(d.get("block_count", 0) for d in ndocs)
        nupdated = max((d.get("updated", "") for d in ndocs), default="")
        return len(ndocs), nwords, nblocks, nupdated

    total_docs = sum(len(ndocs) for ndocs in docs_by_notebook.values())
    total_words = sum(sum(d.get("word_count", 0) for d in ndocs) for ndocs in docs_by_notebook.values())
    total_blocks = sum(sum(d.get("block_count", 0) for d in ndocs) for ndocs in docs_by_notebook.values())

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    lines = [
        "# SiYuan Agent Bridge Tree",
        "",
        f"> {now} | {len(notebook_list)} notebooks | {total_docs} docs | {total_words:,} 字 | {total_blocks} 块",
        "",
    ]

    # Layer 1: notebook overview table
    lines.append("| Notebook | ID | Docs | 字数 | 块数 | 最近更新 |")
    lines.append("|----------|----|------|------|------|----------|")
    for nb in notebook_list:
        nid = str(nb.get("id", ""))
        name = str(nb.get("name") or nid or "Unknown Notebook")
        count, words, blocks, updated = _stats(nid)
        date = format_date(updated) if updated else "-"
        lines.append(f"| {name} | `{nid}` | {count} | {words:,} | {blocks} | {date} |")
    lines.append("")

    # Layer 2: per-notebook document tree
    for nb in notebook_list:
        nid = str(nb.get("id", ""))
        name = str(nb.get("name") or nid or "Unknown Notebook")
        count, words, blocks, updated = _stats(nid)
        date = format_date(updated) if updated else "-"
        lines.append(f"## {name} (`{nid}`) | {count} docs | {words:,} 字 | {blocks} 块 | 最近 {date}")
        lines.append("")
        if count > 0:
            nb_docs = sorted(
                docs_by_notebook.get(nid, []),
                key=lambda item: (str(item.get("hpath", "")).casefold(), str(item.get("id", ""))),
            )
            lines.extend(render_doc_tree(nb_docs))
        else:
            lines.append("*(empty notebook)*")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_notebook_overview(notebooks: Iterable[dict[str, Any]], docs: Iterable[dict[str, Any]]) -> str:
    notebook_list = list(notebooks)
    doc_list = list(docs)
    docs_by_notebook: dict[str, list[dict[str, Any]]] = {}
    for doc in doc_list:
        docs_by_notebook.setdefault(str(doc.get("notebook_id", "")), []).append(doc)

    def _stats(nid: str) -> tuple[int, int, int, str]:
        ndocs = docs_by_notebook.get(nid, [])
        nwords = sum(d.get("word_count", 0) for d in ndocs)
        nblocks = sum(d.get("block_count", 0) for d in ndocs)
        nupdated = max((d.get("updated", "") for d in ndocs), default="")
        return len(ndocs), nwords, nblocks, nupdated

    total_words = sum(d.get("word_count", 0) for d in doc_list)
    total_blocks = sum(d.get("block_count", 0) for d in doc_list)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    lines = [
        "# SiYuan Agent Bridge Tree",
        "",
        f"> {now} | {len(notebook_list)} notebooks | {len(doc_list)} docs | {total_words:,} 字 | {total_blocks} 块",
        "",
        "| Notebook | ID | Docs | 字数 | 块数 | 最近更新 |",
        "|----------|----|------|------|------|----------|",
    ]
    for nb in notebook_list:
        nid = str(nb.get("id", ""))
        name = str(nb.get("name") or nid or "Unknown Notebook")
        count, words, blocks, updated = _stats(nid)
        date = format_date(updated) if updated else "-"
        lines.append(f"| {name} | `{nid}` | {count} | {words:,} | {blocks} | {date} |")
    lines.append("")
    return "\n".join(lines)


def render_doc_tree(docs: list[dict[str, Any]]) -> list[str]:
    root: dict[str, Any] = {"children": {}, "docs": []}
    for doc in docs:
        parts = _path_parts(doc)
        node = root
        for part in parts:
            node = node["children"].setdefault(part, {"children": {}, "docs": []})
        node["docs"].append(doc)
    return _render_node(root, 0)


def _render_node(node: dict[str, Any], depth: int) -> list[str]:
    lines: list[str] = []
    for name in sorted(node["children"], key=str.casefold):
        child = node["children"][name]
        docs = child["docs"]
        indent = "  " * depth
        if docs:
            for doc in docs:
                wc = format_word_count(doc.get("word_count", 0))
                bc = format_block_count(doc.get("block_count", 0))
                date = format_date(doc.get("updated", ""))
                tags = ",".join(doc.get("tags", []))
                tag_text = f" tags:{tags}" if tags else ""
                lines.append(f"{indent}- /{name} `{doc['id']}` {wc} {bc} {date}{tag_text}".rstrip())
        else:
            lines.append(f"{indent}- /{name}")
        lines.extend(_render_node(child, depth + 1))
    return lines


def _path_parts(doc: dict[str, Any]) -> list[str]:
    hpath = str(doc.get("hpath") or "").strip("/")
    if hpath:
        return [part for part in hpath.split("/") if part]
    return [str(doc.get("title") or doc.get("id"))]


def load_docs(root: Path) -> list[dict[str, Any]]:
    path = root / KNOWLEDGE_BASE_DIR / "docs.jsonl"
    if not path.exists():
        return []
    docs = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                docs.append(json.loads(line))
    return docs


def find_documents(docs: Iterable[dict[str, Any]], keyword: str, limit: int = 20) -> list[dict[str, Any]]:
    keywords = [kw.casefold() for kw in keyword.split() if kw]
    if not keywords:
        return []
    matches = []
    for doc in docs:
        haystack = " ".join(
            [
                str(doc.get("id", "")),
                str(doc.get("title", "")),
                str(doc.get("hpath", "")),
                str(doc.get("notebook_name", "")),
                str(doc.get("alias", "")),
                str(doc.get("memo", "")),
                " ".join(str(tag) for tag in doc.get("tags", [])),
            ]
        ).casefold()
        if all(kw in haystack for kw in keywords):
            matches.append(doc)
        if len(matches) >= limit:
            break
    return matches


def search_content(
    client: object,
    query: str,
    *,
    method: int = 0,
    scope: str = "headings",
    notebooks: list[str] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    types: dict[str, bool] | None = {"document": True, "heading": True} if scope == "headings" else None
    paths: list[str] | None = notebooks if notebooks else None
    page_size = max(limit * 20, 64)
    all_blocks: list[dict[str, Any]] = []
    page = 1
    while True:
        data = client.search_full_text(
            query=query,
            method=method,
            types=types,
            paths=paths,
            group_by=0,
            page=page,
            page_size=page_size,
        )
        blocks = data.get("blocks", []) if isinstance(data, dict) else []
        all_blocks.extend(blocks)
        if len(blocks) < page_size:
            break
        page += 1
    return {"blocks": all_blocks}


def extract_snippet(text: str, keywords: list[str], context_chars: int = 30) -> str:
    if not text or not keywords:
        return ""
    folded = text.casefold()
    best_pos = -1
    best_len = 0
    for kw in keywords:
        pos = folded.find(kw.casefold())
        if pos >= 0 and (best_pos < 0 or pos < best_pos):
            best_pos = pos
            best_len = len(kw)
    if best_pos < 0:
        return text[:context_chars * 2] + ("..." if len(text) > context_chars * 2 else "")
    start = max(0, best_pos - context_chars)
    end = min(len(text), best_pos + best_len + context_chars)
    snippet = text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


def resolve_document(docs: Iterable[dict[str, Any]], locator: str) -> tuple[str, list[dict[str, Any]]]:
    doc_list = list(docs)
    if not doc_list:
        return "no_index", []

    raw = locator.strip()
    folded = raw.casefold()
    trimmed_path = raw.strip("/").casefold()

    exact_id = [doc for doc in doc_list if str(doc.get("id", "")) == raw]
    if exact_id:
        return "ok", exact_id

    exact_path = [
        doc
        for doc in doc_list
        if str(doc.get("hpath", "")).strip("/").casefold() == trimmed_path
        or str(doc.get("hpath", "")).casefold() == folded
    ]
    if exact_path:
        return ("ok" if len(exact_path) == 1 else "ambiguous", exact_path)

    exact_title = [doc for doc in doc_list if str(doc.get("title", "")).casefold() == folded]
    if exact_title:
        return ("ok" if len(exact_title) == 1 else "ambiguous", exact_title)

    contains = [
        doc
        for doc in doc_list
        if folded in str(doc.get("title", "")).casefold()
        or folded in str(doc.get("hpath", "")).casefold()
    ]
    if contains:
        return ("ok" if len(contains) == 1 else "ambiguous", contains)

    return "missing", []


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    lines = [json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows]
    write_text(path, "\n".join(lines) + ("\n" if lines else ""))


def ensure_text(path: Path, text: str) -> None:
    if not path.exists():
        write_text(path, text)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def build_notebook_overview(root: Path) -> str:
    base = root / KNOWLEDGE_BASE_DIR
    notebooks_path = base / "notebooks.json"
    docs_path = base / "docs.jsonl"
    if not notebooks_path.exists() or not docs_path.exists():
        return "Existing index: missing. Ask the user before running a full refresh unless they already requested it."
    try:
        notebooks = json.loads(notebooks_path.read_text(encoding="utf-8"))
    except Exception:
        return "Existing index: present but unreadable. Ask the user before rebuilding it."
    docs = []
    try:
        for line in docs_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                docs.append(json.loads(line))
    except Exception:
        pass
    return render_notebook_overview(notebooks, docs)


def render_workspace_readme() -> str:
    return """# AI Workspace

This private folder is for agent-generated task context, analysis notes, drafts, and outputs.
It is not synchronized back into SiYuan by this tool.
"""


def _title_from_hpath(value: Any) -> str:
    text = str(value or "").strip("/")
    if not text:
        return ""
    return text.split("/")[-1]


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
