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
from .ignore import (
    PrivacyRules,
    filter_documents,
    filter_notebooks,
    load_privacy_rules,
    write_privacy_rules_cache,
)


KNOWLEDGE_BASE_DIR = "knowledge_base"
AI_WORKSPACE_DIR = "ai_workspace"

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


def _is_privacy_rules_doc(
    doc: dict[str, Any], system_notebook_id: str, privacy_rules_doc_id: str
) -> bool:
    """Check if a document is the Privacy Rules document (hard-hidden from AI)."""
    if str(doc.get("notebook_id", "")) != system_notebook_id:
        return False
    if privacy_rules_doc_id and str(doc.get("id", "")) == privacy_rules_doc_id:
        return True
    # Also check by known hpath patterns
    hpath = str(doc.get("hpath", "")).strip("/")
    return hpath in ("隐私规则", "Privacy Rules")


def refresh_index(
    client: SiYuanClient,
    root: Path,
    *,
    system_notebook_id: str = "",
    privacy_rules_doc_id: str = "",
) -> RefreshResult:
    cache_dir = root / KNOWLEDGE_BASE_DIR
    workspace_dir = root / AI_WORKSPACE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    all_notebooks = client.list_notebooks()
    privacy = load_privacy_rules(root)
    notebooks = filter_notebooks(all_notebooks, privacy)

    with ensure_notebooks_open(client):
        all_docs = normalize_documents(client.query_sql(DOCS_SQL), all_notebooks)
        docs = filter_documents(all_docs, privacy)
        update_document_stats(client, docs)

    # Hard-remove Privacy Rules document from all AI-facing indexes
    if system_notebook_id:
        docs = [
            doc for doc in docs
            if not _is_privacy_rules_doc(doc, system_notebook_id, privacy_rules_doc_id)
        ]

    write_json(cache_dir / "notebooks.json", notebooks)
    write_jsonl(cache_dir / "docs.jsonl", docs)
    write_text(cache_dir / "tree.md", render_tree(notebooks, docs))
    ensure_text(workspace_dir / "README.md", render_workspace_readme())

    # Cache privacy rules
    write_privacy_rules_cache(root, privacy)

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
        "# 思源代理桥文档树",
        "",
        f"> {now} | {len(notebook_list)} 个笔记本 | {total_docs} 篇文档 | {total_words:,} 字 | {total_blocks} 块",
        "",
    ]

    # Layer 1: notebook overview table
    lines.append("| 笔记本 | ID | 文档数 | 字数 | 块数 | 最近更新 |")
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
        lines.append(f"## {name}（`{nid}`）| {count} 篇 | {words:,} 字 | {blocks} 块 | 最近 {date}")
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
        "# 思源代理桥文档树",
        "",
        f"> {now} | {len(notebook_list)} 个笔记本 | {len(doc_list)} 篇文档 | {total_words:,} 字 | {total_blocks} 块",
        "",
        "| 笔记本 | ID | 文档数 | 字数 | 块数 | 最近更新 |",
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
    return """# AI 工作区

此私有文件夹用于存放 AI 生成的任务上下文、分析笔记、草稿和输出。
本工具不会将这些内容同步回思源。
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
