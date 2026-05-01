from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .client import SiYuanClient
from .ignore import filter_documents, filter_notebooks, load_privacy_rules


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

GUIDE_TEMPLATE = """# Personal Knowledge Base Guide

This file is the reading map for AI agents. Keep it short, explicit, and personal.
`python -m source_code refresh` will not overwrite this file after it exists.

## Startup Rules

1. Read this guide first.
2. Read `knowledge_base/tree.md` before exploring the knowledge base.
3. Do not scan the whole tree just to understand the knowledge base.
4. Read document trees only when a task points to that notebook or topic.
5. Use `python -m source_code read <doc-id>` only when a specific document is worth reading deeply.
6. Put derived notes, task context, and drafts in `ai_workspace/`.

## Important Areas

- TODO: Add the notebooks, paths, or topics that matter most.

## Personal Preferences

- TODO: Add your durable preferences, recurring constraints, and working style.

## Recurring Workflows

- TODO: Add where an AI agent should look for common tasks.
"""


@dataclass(frozen=True)
class RefreshResult:
    total_notebook_count: int
    total_document_count: int
    notebook_count: int
    document_count: int
    hidden_notebook_count: int
    hidden_document_count: int
    cache_dir: Path


def refresh_index(client: SiYuanClient, root: Path) -> RefreshResult:
    cache_dir = root / KNOWLEDGE_BASE_DIR
    workspace_dir = root / AI_WORKSPACE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    all_notebooks = client.list_notebooks()
    privacy = load_privacy_rules(root, include_temporary=False)
    notebooks = filter_notebooks(all_notebooks, privacy)
    all_docs = normalize_documents(client.query_sql(DOCS_SQL), all_notebooks)
    docs = filter_documents(all_docs, privacy)

    write_json(cache_dir / "notebooks.json", notebooks)
    write_jsonl(cache_dir / "docs.jsonl", docs)
    ensure_text(cache_dir / "guide.md", GUIDE_TEMPLATE)
    write_text(cache_dir / "tree.md", render_tree(notebooks, docs))
    ensure_text(workspace_dir / "README.md", render_workspace_readme())

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
    def _stats(nid: str) -> tuple[int, int, str]:
        ndocs = docs_by_notebook.get(nid, [])
        nwords = sum(d.get("word_count", 0) for d in ndocs)
        nupdated = max((d.get("updated", "") for d in ndocs), default="")
        return len(ndocs), nwords, nupdated

    total_docs = sum(len(ndocs) for ndocs in docs_by_notebook.values())
    total_words = sum(sum(d.get("word_count", 0) for d in ndocs) for ndocs in docs_by_notebook.values())

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    lines = [
        "# SiYuan Knowledge Tree",
        "",
        f"> {now} | {len(notebook_list)} notebooks | {total_docs} docs | {total_words:,} 字",
        "",
    ]

    # Layer 1: notebook overview table
    lines.append("| Notebook | ID | Docs | 字数 | 最近更新 |")
    lines.append("|----------|----|------|------|----------|")
    for nb in notebook_list:
        nid = str(nb.get("id", ""))
        name = str(nb.get("name") or nid or "Unknown Notebook")
        count, words, updated = _stats(nid)
        date = format_date(updated) if updated else "-"
        lines.append(f"| {name} | `{nid}` | {count} | {words:,} | {date} |")
    lines.append("")

    # Layer 2: per-notebook document tree
    for nb in notebook_list:
        nid = str(nb.get("id", ""))
        name = str(nb.get("name") or nid or "Unknown Notebook")
        count, words, updated = _stats(nid)
        date = format_date(updated) if updated else "-"
        lines.append(f"## {name} (`{nid}`) | {count} docs | {words:,} 字 | 最近 {date}")
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

    def _stats(nid: str) -> tuple[int, int, str]:
        ndocs = docs_by_notebook.get(nid, [])
        nwords = sum(d.get("word_count", 0) for d in ndocs)
        nupdated = max((d.get("updated", "") for d in ndocs), default="")
        return len(ndocs), nwords, nupdated

    total_words = sum(d.get("word_count", 0) for d in doc_list)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    lines = [
        "# SiYuan Knowledge Tree",
        "",
        f"> {now} | {len(notebook_list)} notebooks | {len(doc_list)} docs | {total_words:,} 字",
        "",
        "| Notebook | ID | Docs | 字数 | 最近更新 |",
        "|----------|----|------|------|----------|",
    ]
    for nb in notebook_list:
        nid = str(nb.get("id", ""))
        name = str(nb.get("name") or nid or "Unknown Notebook")
        count, words, updated = _stats(nid)
        date = format_date(updated) if updated else "-"
        lines.append(f"| {name} | `{nid}` | {count} | {words:,} | {date} |")
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
                date = format_date(doc.get("updated", ""))
                tags = ",".join(doc.get("tags", []))
                tag_text = f" tags:{tags}" if tags else ""
                lines.append(f"{indent}- /{name} `{doc['id']}` {wc} {date}{tag_text}".rstrip())
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
    types: dict[str, bool] | None = {"d": True, "h": True} if scope == "headings" else None
    paths: list[str] | None = [f"{nid}/" for nid in notebooks] if notebooks else None
    return client.search_full_text(
        query=query,
        method=method,
        types=types,
        paths=paths,
        page_size=max(limit * 2, 32),
    )


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
