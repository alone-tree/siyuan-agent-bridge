from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .client import SiYuanClient


KB_CACHE_DIR = "kb_cache"
AI_WORKSPACE_DIR = "ai_workspace"

DOCS_SQL = """
SELECT
  id, box, path, hpath, name, alias, memo, tag, content, markdown, type, created, updated
FROM blocks
WHERE type = 'd'
ORDER BY box, hpath
""".strip()

GUIDE_TEMPLATE = """# Personal Knowledge Base Guide

This file is the reading map for AI agents. Keep it short, explicit, and personal.
`python -m siyuan_kb refresh` will not overwrite this file after it exists.

## How To Read

1. Read this guide first.
2. Read `kb_cache/tree.md` to inspect the current SiYuan document structure.
3. Use `python -m siyuan_kb read <doc-id>` when you need a specific document.
4. Put derived notes, task context, and drafts in `ai_workspace/`.

## Important Areas

- TODO: Add the notebooks, paths, or topics that matter most.

## Personal Preferences

- TODO: Add your durable preferences, recurring constraints, and working style.

## Recurring Workflows

- TODO: Add where an AI agent should look for common tasks.
"""


@dataclass(frozen=True)
class RefreshResult:
    notebook_count: int
    document_count: int
    cache_dir: Path


def refresh_index(client: SiYuanClient, root: Path) -> RefreshResult:
    cache_dir = root / KB_CACHE_DIR
    workspace_dir = root / AI_WORKSPACE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    notebooks = client.list_notebooks()
    docs = normalize_documents(client.query_sql(DOCS_SQL), notebooks)

    write_json(cache_dir / "notebooks.json", notebooks)
    write_jsonl(cache_dir / "docs.jsonl", docs)
    write_text(cache_dir / "tree.md", render_tree(notebooks, docs))
    ensure_text(cache_dir / "guide.md", GUIDE_TEMPLATE)
    ensure_text(workspace_dir / "README.md", render_workspace_readme())

    return RefreshResult(
        notebook_count=len(notebooks),
        document_count=len(docs),
        cache_dir=cache_dir,
    )


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

    lines = [
        "# SiYuan Knowledge Tree",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Use `python -m siyuan_kb read <doc-id>` to read a document.",
        "",
    ]

    for notebook in notebook_list:
        notebook_id = str(notebook.get("id", ""))
        name = str(notebook.get("name") or notebook_id or "Unknown Notebook")
        notebook_docs = sorted(
            docs_by_notebook.get(notebook_id, []),
            key=lambda item: (str(item.get("hpath", "")).casefold(), str(item.get("id", ""))),
        )
        if not notebook_docs:
            continue
        lines.append(f"## {name} (`{notebook_id}`)")
        lines.append("")
        lines.extend(_render_notebook_tree(notebook_docs))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_notebook_tree(docs: list[dict[str, Any]]) -> list[str]:
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
                updated = f" updated:{doc['updated']}" if doc.get("updated") else ""
                lines.append(f"{indent}- {name} `{doc['id']}`{updated}")
        else:
            lines.append(f"{indent}- {name}")
        lines.extend(_render_node(child, depth + 1))
    return lines


def _path_parts(doc: dict[str, Any]) -> list[str]:
    hpath = str(doc.get("hpath") or "").strip("/")
    if hpath:
        return [part for part in hpath.split("/") if part]
    return [str(doc.get("title") or doc.get("id"))]


def load_docs(root: Path) -> list[dict[str, Any]]:
    path = root / KB_CACHE_DIR / "docs.jsonl"
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
    needle = keyword.casefold()
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
        if needle in haystack:
            matches.append(doc)
        if len(matches) >= limit:
            break
    return matches


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
