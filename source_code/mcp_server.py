from __future__ import annotations

import json
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .cli import load_live_docs
from .client import SiYuanApiError, SiYuanClient, SiYuanConnectionError
from .config import detect_active_profile, load_config
from .ignore import (
    PrivacyRules,
    compile_rules,
    document_permission,
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
from .telemetry import (
    _resolve_proxy,
    _with_telemetry,
    ensure_session_id,
    get_effective_endpoint,
    load_anonymous_id,
    load_telemetry_config,
    set_siyuan_version,
    submit_feedback as _telemetry_submit_feedback,
)


SERVER_NAME = "siyuan-bridge"
SERVER_VERSION = "0.3.0"
DEFAULT_SNIPPETS_PER_DOC = 5
POST_WRITE_SYNC_TIMEOUT = 5.0
POST_WRITE_SYNC_INTERVAL = 0.25

# ---------------------------------------------------------------------------
# Error codes for telemetry — category:detail two-level encoding
# category 用于聚合看板，detail 用于下钻诊断
# ---------------------------------------------------------------------------

# validation — AI 传参错误
_ERR_MISSING_PARAM    = "validation:missing_param"
_ERR_INVALID_ENUM     = "validation:invalid_enum"
_ERR_INVALID_TYPE     = "validation:invalid_type"
_ERR_OUT_OF_RANGE     = "validation:out_of_range"
_ERR_WRONG_SHAPE      = "validation:wrong_shape"
_ERR_OPERATION_ORDER  = "validation:operation_order"
_ERR_WRONG_TARGET     = "validation:wrong_target_type"
_ERR_INVALID_TABLE    = "validation:invalid_table"
_ERR_MISMATCH         = "validation:mismatch"
_ERR_MISSING_EDIT_RANGE = "validation:missing_edit_range"

# permission — 权限不足或未确认
_ERR_NOT_CONFIRMED    = "permission:not_confirmed"
_ERR_NOT_READ_WRITE   = "permission:not_read_write"
_ERR_PRIVACY_RULES    = "permission:privacy_rules"
_ERR_SQL_ADMIN        = "permission:sql_admin"
_ERR_SUBTREE_BLOCKED  = "permission:subtree_blocked"
_ERR_ANCESTOR_BLOCKED = "permission:ancestor_blocked"

# not_found — 目标不存在
_ERR_DOC_NOT_FOUND    = "not_found:document"
_ERR_NB_NOT_FOUND     = "not_found:notebook"
_ERR_PARENT_NOT_FOUND = "not_found:parent"
_ERR_BLOCK_NOT_FOUND  = "not_found:block_index"

# conflict — 状态不一致
_ERR_ALREADY_EXISTS      = "conflict:already_exists"
_ERR_AMBIGUOUS           = "conflict:ambiguous_path"
_ERR_STALE_BLOCK_ID      = "conflict:stale_block_id"
_ERR_STALE_CELL_VALUE    = "conflict:stale_cell_value"
_ERR_MULTI_DOC_OVERWRITE = "conflict:multi_doc_overwrite"

# api — 思源 API 层错误（从 SiYuanApiError 转换）
_ERR_SNAPSHOT_KEY   = "api:snapshot_key"
_ERR_SNAPSHOT_FAILED = "api:snapshot_failed"
_ERR_DUPLICATE_NO_ID = "api:duplicate_no_id"


def tool_error(code: str, message: str) -> ValueError:
    """创建一个附带遥测 error_code 的 ValueError。"""
    exc = ValueError(message)
    exc.error_code = code  # type: ignore[attr-defined]
    return exc


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


SKIP_BLOCK_TYPES = frozenset({"d"})
LEGACY_SKIP_BLOCK_TYPES = frozenset({"l", "d"})
SUBTREE_MARKDOWN_BLOCK_TYPES = frozenset({"i", "l", "t"})
LEGACY_SUBTREE_MARKDOWN_BLOCK_TYPES = frozenset({"i", "t"})
COMMENT_ONLY_BLOCK_TYPES = frozenset({"s"})
CHILD_TRAVERSAL_BLOCK_TYPES = frozenset({"h", "l", "s"})
DATABASE_BLOCK_TYPES = frozenset({"av"})
REPLACE_REFUSED_SEMANTIC_TYPES = frozenset({
    "attachment",
    "database",
    "superblock",
    "html",
    "iframe",
    "video",
    "audio",
    "widget",
})


import re as _re

_AV_ID_PATTERN = _re.compile(r'data-av-id="([^"]+)"')
_IAL_ATTR_PATTERN = _re.compile(r'(\w[\w-]*)\s*=\s*"([^"]*)"')


def _parse_ial_attrs(ial: str) -> dict[str, str]:
    """Parse SiYuan IAL into custom attrs, excluding id and updated (managed by kernel)."""
    attrs: dict[str, str] = {}
    for m in _IAL_ATTR_PATTERN.finditer(ial):
        key = m.group(1)
        if key in ("id", "updated"):
            continue
        attrs[key] = m.group(2)
    return attrs


def _extract_av_id(block_md: str) -> str:
    m = _AV_ID_PATTERN.search(block_md) if block_md else None
    return m.group(1) if m else ""


def _render_av_cell(value: dict[str, Any], field_type: str) -> str:
    if field_type == "block":
        block = value.get("block")
        if isinstance(block, dict):
            return str(block.get("content", ""))
        return ""
    if field_type == "select":
        mselect = value.get("mSelect")
        if isinstance(mselect, list) and mselect:
            return ", ".join(str(s.get("content", "")) for s in mselect)
        return ""
    block = value.get("block")
    if isinstance(block, dict):
        val = block.get("content")
        if val is not None:
            return str(val)
    content = value.get("content")
    if content is not None:
        return str(content)
    return ""


def _render_av_as_table(av_data: dict[str, Any], block_id: str, include_block_ids: bool) -> str:
    if not av_data:
        return ""
    key_values = av_data.get("keyValues")
    if not key_values:
        return ""
    key_ids = av_data.get("keyIDs", [])
    fields: list[dict[str, Any]] = []
    kv_by_key_id: dict[str, dict[str, Any]] = {
        kv["key"]["id"]: kv for kv in key_values if kv.get("key", {}).get("id")
    }
    if key_ids and kv_by_key_id:
        for kid in key_ids:
            if kid in kv_by_key_id:
                fields.append(kv_by_key_id[kid])
    if not fields:
        fields = list(key_values)
    row_count = max((len(f.get("values", [])) for f in fields), default=0)
    if row_count == 0:
        return ""
    headers = [f["key"]["name"] for f in fields]
    field_types = [f["key"]["type"] for f in fields]
    rows: list[list[str]] = []
    for i in range(row_count):
        row: list[str] = []
        for f, ftype in zip(fields, field_types):
            values = f.get("values", [])
            if i < len(values):
                row.append(_render_av_cell(values[i], ftype))
            else:
                row.append("")
        rows.append(row)
    lines = ["|" + "|".join(headers) + "|"]
    lines.append("|" + "|".join(" --- " for _ in headers) + "|")
    for row in rows:
        lines.append("|" + "|".join(row) + "|")
    table_md = "\n".join(lines)
    av_id = av_data.get("id", "")
    annotation = "> 此表格为数据库（属性视图），只读。如需补充数据，请在本块下方追加新表格或说明。\n\n"
    if include_block_ids:
        annotation = f"<!-- siyuan:block id={block_id} type=av -->\n" + annotation
    return annotation + table_md


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

    if not block_id or block_type in LEGACY_SKIP_BLOCK_TYPES:
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
        if block_type in LEGACY_SUBTREE_MARKDOWN_BLOCK_TYPES:
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
        if block_type in LEGACY_SUBTREE_MARKDOWN_BLOCK_TYPES:
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
    source_markdown: str = ""


@dataclass
class CreateTarget:
    notebook_id: str
    notebook_name: str
    internal_path: str
    display_path: str
    existing_docs: list[dict[str, Any]]


@dataclass
class PostWriteSyncStatus:
    ok: bool
    detail: str


def semantic_block_type(raw_type: str, subtype: str, markdown: str) -> str:
    if raw_type == "p" and re.search(r"!?\[[^\]]+\]\(assets/[^)]+\)", markdown):
        return "attachment"
    return {
        "h": "heading",
        "p": "paragraph",
        "l": "list",
        "i": "list_item",
        "t": "table",
        "c": "code",
        "s": "superblock",
        "av": "database",
        "b": "blockquote",
        "m": "math",
        "html": "html",
        "iframe": "iframe",
        "video": "video",
        "audio": "audio",
        "widget": "widget",
        "tb": "thematic_break",
    }.get(raw_type, raw_type or "unknown")


def list_kind(subtype: str) -> str:
    return {"o": "ordered", "u": "unordered", "t": "task"}.get(subtype, subtype)


def code_language(markdown: str) -> str:
    first = markdown.strip().splitlines()[0] if markdown.strip() else ""
    if first.startswith("```"):
        return first[3:].strip()
    return ""


def block_metadata_line(index: int, block_id: str, raw_type: str, subtype: str, markdown: str) -> str:
    semantic_type = semantic_block_type(raw_type, subtype, markdown)
    parts = [f"[{index}]", f"id={block_id}", f"type={semantic_type}"]
    if semantic_type == "code":
        lang = code_language(markdown)
        if lang:
            parts.append(f"language={lang}")
    elif semantic_type == "database":
        parts.append("readonly=true")
    return " ".join(parts)


def display_block_source(block: DisplayBlock) -> str:
    return block.source_markdown if block.source_markdown else block.markdown


def display_block_semantic_type(block: DisplayBlock) -> str:
    return semantic_block_type(block.type, block.subtype, display_block_source(block))


def split_markdown_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    cells: list[str] = []
    buf: list[str] = []
    escaped = False
    for ch in stripped:
        if escaped:
            buf.append(ch)
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == "|":
            cells.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if escaped:
        buf.append("\\")
    cells.append("".join(buf).strip())
    return cells


def escape_markdown_table_cell(value: Any) -> str:
    return str(value).replace("\n", "<br>").replace("|", "\\|")


def render_markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    width = len(headers)
    normalized_rows = [(row + [""] * width)[:width] for row in rows]
    lines = [
        "| " + " | ".join(escape_markdown_table_cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in normalized_rows:
        lines.append("| " + " | ".join(escape_markdown_table_cell(cell) for cell in row) + " |")
    return "\n".join(lines)


def parse_markdown_table(markdown: str) -> tuple[list[str], list[list[str]]]:
    lines = [line.strip() for line in markdown.strip().splitlines() if line.strip()]
    if len(lines) < 2 or "|" not in lines[0] or "|" not in lines[1]:
        raise tool_error(_ERR_INVALID_TABLE, "目标块不是可解析的 Markdown 表格。请重新引用阅读，确认目标块 type=table。")
    headers = split_markdown_table_row(lines[0])
    separator = split_markdown_table_row(lines[1])
    if not headers or len(separator) != len(headers):
        raise tool_error(_ERR_INVALID_TABLE, "表格表头或分隔行格式不完整，暂不支持 table_edit。")
    rows = [split_markdown_table_row(line) for line in lines[2:]]
    return headers, [(row + [""] * len(headers))[:len(headers)] for row in rows]


def render_table_coordinate_view(markdown: str) -> str:
    headers, rows = parse_markdown_table(markdown)
    lines = [
        "| row_index | " + " | ".join(f"col {i}" for i in range(1, len(headers) + 1)) + " |",
        "| row 0 | " + " | ".join(escape_markdown_table_cell(header) for header in headers) + " |",
    ]
    for row_number, row in enumerate(rows, start=1):
        normalized = (row + [""] * len(headers))[:len(headers)]
        lines.append(
            f"| row {row_number} | "
            + " | ".join(escape_markdown_table_cell(cell) for cell in normalized)
            + " |"
        )
    return "\n".join(lines)


def table_column_index(headers: list[str], edit: dict[str, Any]) -> int:
    if edit.get("column_index") is not None:
        index = int(edit["column_index"]) - 1
        if index < 0 or index >= len(headers):
            raise tool_error(_ERR_OUT_OF_RANGE, f"column_index 超出范围：当前表格共有 {len(headers)} 列。")
        return index
    column = str(edit.get("column") or "").strip()
    if not column:
        raise tool_error(_ERR_MISSING_PARAM, "table_edit.set_cell 需要 column 或 column_index。")
    matches = [i for i, header in enumerate(headers) if header == column]
    if not matches:
        raise tool_error(_ERR_NOT_FOUND, f"表格中未找到列：{column}。请重新引用阅读确认列名，或使用 column_index。")
    if len(matches) > 1:
        raise tool_error(_ERR_AMBIGUOUS, f"列名存在重复：{column}。请改用 column_index。")
    return matches[0]


def table_position(edit: dict[str, Any]) -> str:
    position = str(edit.get("position") or "").strip().lower()
    if position not in {"before", "after"}:
        raise tool_error(_ERR_INVALID_ENUM, "table_edit.position 只支持 before 或 after。")
    return position


def table_row_values(headers: list[str], values: Any) -> list[str]:
    if isinstance(values, dict):
        return [str(values.get(header, "")) for header in headers]
    if isinstance(values, list):
        return ([str(value) for value in values] + [""] * len(headers))[:len(headers)]
    raise tool_error(_ERR_INVALID_TYPE, "insert_row 需要 values，格式为按列顺序排列的数组，或按表头取值的对象。")


def apply_table_cell_edit(headers: list[str], rows: list[list[str]], cell: dict[str, Any]) -> None:
    if cell.get("row") is None:
        raise tool_error(_ERR_MISSING_PARAM, "set_cell 需要 row。row=0 表示表头，row>=1 表示数据行。")
    row_number = int(cell["row"])
    col_index = table_column_index(headers, cell)
    expected = cell.get("expected_old_value")

    if row_number == 0:
        current = headers[col_index]
        if expected is not None and current != str(expected):
            raise tool_error(_ERR_STALE_CELL_VALUE,
                f"表头单元格旧值校验失败：当前值为 `{current}`，"
                f"但 expected_old_value 为 `{expected}`。请重新引用阅读后再编辑。"
            )
        headers[col_index] = str(cell.get("value") or "")
        return

    row_index = row_number - 1
    if row_index < 0 or row_index >= len(rows):
        raise tool_error(_ERR_OUT_OF_RANGE, f"row 超出范围。当前表格有 {len(rows)} 行数据，row=0 表示表头。")
    current = rows[row_index][col_index]
    if expected is not None and current != str(expected):
        raise tool_error(_ERR_STALE_CELL_VALUE,
            f"单元格旧值校验失败：当前值为 `{current}`，"
            f"但 expected_old_value 为 `{expected}`。请重新引用阅读后再编辑。"
        )
    rows[row_index][col_index] = str(cell.get("value") or "")


def apply_table_edit(markdown: str, edit: dict[str, Any]) -> str:
    headers, rows = parse_markdown_table(markdown)
    operation = str(edit.get("operation") or "").strip()
    legacy_insert_map = {
        "insert_row_before": ("insert_row", "before"),
        "insert_row_after": ("insert_row", "after"),
    }
    if operation in legacy_insert_map:
        operation, default_position = legacy_insert_map[operation]
        edit = {**edit, "operation": operation, "position": edit.get("position") or default_position}
    if operation not in {"set_cell", "insert_row", "delete_row", "insert_column", "delete_column"}:
        raise tool_error(_ERR_INVALID_ENUM, "table_edit.operation 只支持 set_cell、insert_row、delete_row、insert_column、delete_column。")

    if operation == "set_cell":
        cells = edit.get("cells")
        if cells is not None:
            if not isinstance(cells, list) or not cells:
                raise tool_error(_ERR_INVALID_TYPE, "set_cell.cells 必须是非空数组。")
            for cell in cells:
                if not isinstance(cell, dict):
                    raise tool_error(_ERR_INVALID_TYPE, "set_cell.cells 中的每一项都必须是对象。")
                apply_table_cell_edit(headers, rows, cell)
        else:
            cell = edit.get("cell")
            if cell is None:
                cell = edit
            if not isinstance(cell, dict):
                raise tool_error(_ERR_INVALID_TYPE, "set_cell 需要 cell 对象或 cells 数组。")
            apply_table_cell_edit(headers, rows, cell)
    elif operation == "insert_row":
        if edit.get("row") is None:
            raise tool_error(_ERR_MISSING_PARAM, "insert_row 需要 row。row=0 表示表头，row>=1 表示数据行。")
        row_number = int(edit["row"])
        position = table_position(edit)
        if row_number < 0 or row_number > len(rows):
            raise tool_error(_ERR_OUT_OF_RANGE, f"row 超出范围。当前表格有 {len(rows)} 行数据，row=0 表示表头。")
        if row_number == 0 and position == "before":
            raise tool_error(_ERR_OPERATION_ORDER, "不能在表头前插入数据行。请使用 row=0, position=after 或指定数据行。")
        new_row = table_row_values(headers, edit.get("values"))
        insert_at = 0 if row_number == 0 else row_number - 1
        if position == "after" and row_number > 0:
            insert_at += 1
        rows.insert(insert_at, new_row)
    elif operation == "delete_row":
        row_arg = edit.get("row")
        if row_arg is None:
            raise tool_error(_ERR_MISSING_PARAM, "delete_row 需要 row。row>=1 表示数据行，不能删除表头。")
        row_index = int(row_arg) - 1
        if row_index < 0 or row_index >= len(rows):
            raise tool_error(_ERR_OUT_OF_RANGE, f"row 超出范围。当前表格有 {len(rows)} 行数据。")
        rows.pop(row_index)
    elif operation == "insert_column":
        col_index = table_column_index(headers, edit)
        position = table_position(edit)
        values = edit.get("values")
        if not isinstance(values, list):
            raise tool_error(_ERR_INVALID_TYPE, "insert_column 需要 values 数组，values[0] 是表头，其后是数据行。")
        if len(values) > len(rows) + 1:
            raise tool_error(_ERR_OUT_OF_RANGE, f"insert_column.values 过长。当前表格需要最多 {len(rows) + 1} 个值（含表头）。")
        normalized = [str(value) for value in values] + [""] * (len(rows) + 1 - len(values))
        insert_at = col_index if position == "before" else col_index + 1
        headers.insert(insert_at, normalized[0])
        for row, value in zip(rows, normalized[1:]):
            row.insert(insert_at, value)
    elif operation == "delete_column":
        if len(headers) <= 1:
            raise tool_error(_ERR_OPERATION_ORDER, "不能删除最后一列。")
        col_index = table_column_index(headers, edit)
        headers.pop(col_index)
        for row in rows:
            row.pop(col_index)

    return render_markdown_table(headers, rows)


def display_document_path(doc: dict[str, Any]) -> str:
    hpath = str(doc.get("hpath") or doc.get("title") or doc.get("id"))
    notebook_name = str(doc.get("notebook_name") or "").strip()
    if not hpath.startswith("/"):
        hpath = "/" + hpath
    if notebook_name and not hpath.startswith(f"/{notebook_name}/") and hpath != f"/{notebook_name}":
        return f"/{notebook_name}{hpath}"
    return hpath


def normalize_display_path(path: str) -> str:
    text = str(path or "").strip()
    if not text:
        return ""
    return "/" + text.strip("/")


def _notebook_by_id(notebooks: list[dict[str, Any]], notebook_id: str) -> dict[str, Any] | None:
    return next((nb for nb in notebooks if str(nb.get("id", "")) == notebook_id), None)


def _notebook_name_matches(notebooks: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    folded = name.casefold()
    return [nb for nb in notebooks if str(nb.get("name", "")).casefold() == folded]


def _existing_docs_at_path(docs: list[dict[str, Any]], notebook_id: str, internal_path: str) -> list[dict[str, Any]]:
    wanted = normalize_display_path(internal_path).strip("/").casefold()
    return [
        doc for doc in docs
        if str(doc.get("notebook_id", "")) == notebook_id
        and normalize_display_path(str(doc.get("hpath", ""))).strip("/").casefold() == wanted
    ]


def resolve_create_target(
    args: dict[str, Any],
    notebooks: list[dict[str, Any]],
    docs: list[dict[str, Any]],
    title: str,
) -> CreateTarget:
    raw_path = str(args.get("path") or "").strip()
    notebook_id_arg = str(args.get("notebook_id") or "").strip()
    path = normalize_display_path(raw_path)

    if not path:
        if not notebook_id_arg:
            raise tool_error(_ERR_MISSING_PARAM,
                "siyuan_create 优先使用完整路径 path=/Notebook/Folder/Doc。"
                "如果不传 path，则必须提供 notebook_id 和笔记本内路径。"
            )
        nb = _notebook_by_id(notebooks, notebook_id_arg)
        if nb is None:
            raise tool_error(_ERR_NB_NOT_FOUND, f"笔记本 {notebook_id_arg} 不可见，可能已被隐私规则隐藏。")
        internal_path = f"/{title}"
    else:
        parts = path.strip("/").split("/", 1)
        first = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        name_matches = _notebook_name_matches(notebooks, first)

        if len(name_matches) > 1 and not notebook_id_arg:
            choices = "\n".join(f"- `{nb.get('id', '')}` {nb.get('name', '')}" for nb in name_matches)
            raise tool_error(_ERR_AMBIGUOUS,
                "目标笔记本名称存在歧义。请改用 notebook_id + 笔记本内路径，例如 "
                "`notebook_id=<目标笔记本ID>, path=/Folder/Doc`。\n"
                + choices
            )

        if name_matches:
            if notebook_id_arg:
                nb = next((item for item in name_matches if str(item.get("id", "")) == notebook_id_arg), None)
                if nb is None:
                    raise tool_error(_ERR_MISMATCH, "path 中的笔记本名称与 notebook_id 不匹配。")
            else:
                nb = name_matches[0]
            internal_path = normalize_display_path(rest or title)
        else:
            if not notebook_id_arg:
                raise tool_error(_ERR_NB_NOT_FOUND,
                    "path 应使用完整可读路径 /Notebook/Folder/Doc。"
                    "未匹配到路径第一段对应的可见笔记本；如需使用笔记本内路径，请同时提供 notebook_id。"
                )
            nb = _notebook_by_id(notebooks, notebook_id_arg)
            if nb is None:
                raise tool_error(_ERR_NB_NOT_FOUND, f"笔记本 {notebook_id_arg} 不可见，可能已被隐私规则隐藏。")
            internal_path = path

    notebook_id = str(nb.get("id", ""))
    notebook_name = str(nb.get("name", notebook_id))
    internal_path = normalize_display_path(internal_path)
    display_path = normalize_display_path(f"{notebook_name}/{internal_path.strip('/')}")
    existing_docs = _existing_docs_at_path(docs, notebook_id, internal_path)
    return CreateTarget(
        notebook_id=notebook_id,
        notebook_name=notebook_name,
        internal_path=internal_path,
        display_path=display_path,
        existing_docs=existing_docs,
    )


def direct_child_key(parent_path: str, document_path: str) -> str | None:
    parent = normalize_display_path(parent_path)
    doc_path = normalize_display_path(document_path)
    if not parent:
        return None
    if doc_path == parent or not doc_path.startswith(parent + "/"):
        return None
    remainder = doc_path[len(parent):].strip("/")
    if not remainder:
        return None
    return remainder.split("/", 1)[0]


def descendant_count(doc: dict[str, Any], docs: list[dict[str, Any]]) -> int:
    path = display_document_path(doc).rstrip("/")
    return sum(
        1 for item in docs
        if display_document_path(item).startswith(path + "/")
    )


def document_subtree(doc: dict[str, Any], docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    doc_id = str(doc.get("id") or "")
    notebook_id = str(doc.get("notebook_id") or "")
    hpath = normalize_display_path(str(doc.get("hpath") or "")).rstrip("/")
    result = []
    for item in docs:
        if str(item.get("id") or "") == doc_id:
            result.append(item)
            continue
        if str(item.get("notebook_id") or "") != notebook_id:
            continue
        item_hpath = normalize_display_path(str(item.get("hpath") or "")).rstrip("/")
        if hpath and item_hpath.startswith(hpath + "/"):
            result.append(item)
    return result


def parent_display_path(document_path: str) -> str:
    parts = normalize_display_path(document_path).strip("/").split("/")
    if len(parts) <= 1:
        return ""
    return "/" + "/".join(parts[:-1])


def notebook_permission_probe(notebook: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "",
        "notebook_id": str(notebook.get("id", "")),
        "notebook_name": str(notebook.get("name", "")),
        "hpath": "/__siyuan_bridge_permission_probe__",
    }


def format_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


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
        # Skip document roots; list containers are rendered as one display block.
        if block_type in SKIP_BLOCK_TYPES:
            if block_type in CHILD_TRAVERSAL_BLOCK_TYPES:
                for child in client.get_child_blocks(block_id):
                    visit(child)
            return

        # Database/attribute view blocks: render via av API, not raw markdown
        if block_type in DATABASE_BLOCK_TYPES:
            block_md = block_field(block, "markdown")
            av_id = _extract_av_id(block_md)
            if av_id:
                av_data = client.get_attribute_view(av_id)
                display_md = _render_av_as_table(av_data, block_id, False) if av_data else ""
            else:
                display_md = ""
            if not display_md:
                display_md = "> 数据库数据获取失败"
            if include_block_ids:
                display_md = f"{block_metadata_line(len(blocks) + 1, block_id, block_type, '', block_md)}\n{display_md}"
            estimated_tokens = estimate_token_count(display_md)
            blocks.append(DisplayBlock(
                index=len(blocks) + 1,
                id=block_id,
                type=block_type,
                subtype="",
                markdown=display_md,
                estimated_tokens=estimated_tokens,
                is_heading=False,
                heading_level=None,
                heading_text="",
                source_markdown=block_md,
            ))
            return

        subtype = block_field(block, "subtype", "subType")
        block_md = block_field(block, "markdown")

        if block_type == "l" and not block_md.strip():
            for child in client.get_child_blocks(block_id):
                visit(child)
            return

        if not block_md.strip() and block_type not in COMMENT_ONLY_BLOCK_TYPES:
            if block_type in CHILD_TRAVERSAL_BLOCK_TYPES:
                for child in client.get_child_blocks(block_id):
                    visit(child)
            return

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
                display_md = block_metadata_line(len(blocks) + 1, block_id, block_type, subtype, block_md) + "\n{{{ superblock start"
            else:
                for child in client.get_child_blocks(block_id):
                    visit(child)
                return
        elif include_block_ids and block_type == "t" and block_md.strip():
            metadata = block_metadata_line(len(blocks) + 1, block_id, block_type, subtype, block_md)
            try:
                headers, rows = parse_markdown_table(block_md)
                display_md = (
                    f"{metadata} rows={len(rows)} columns={len(headers)}\n\n"
                    f"{render_table_coordinate_view(block_md)}"
                )
            except ValueError:
                display_md = f"{metadata}\n{block_md}"
        elif include_block_ids and block_md.strip():
            metadata = block_metadata_line(len(blocks) + 1, block_id, block_type, subtype, block_md)
            display_md = f"{metadata}\n{block_md}"

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
            source_markdown=block_md,
        ))

        # List items and tables: their markdown already contains subtree content — skip children
        if block_type in SUBTREE_MARKDOWN_BLOCK_TYPES:
            return
        # Continue traversing children for headings, super blocks, list containers
        if block_type in CHILD_TRAVERSAL_BLOCK_TYPES:
            start_index = len(blocks)
            current_display_index = blocks[-1].index if blocks else 0
            for child in client.get_child_blocks(block_id):
                visit(child)
            if include_block_ids and block_type in COMMENT_ONLY_BLOCK_TYPES and blocks:
                end_marker = "}}} superblock end [" + str(current_display_index) + "]"
                target_idx = len(blocks) - 1 if len(blocks) > start_index else start_index - 1
                if 0 <= target_idx < len(blocks):
                    blocks[target_idx].markdown = f"{blocks[target_idx].markdown}\n\n{end_marker}"

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


def format_display_block(block: DisplayBlock) -> str:
    return block.markdown.strip()


def format_display_blocks(blocks: list[DisplayBlock]) -> str:
    if not blocks:
        return "(无)"
    return "\n\n".join(format_display_block(block) for block in blocks)


def block_range_label(blocks: list[DisplayBlock]) -> str:
    if not blocks:
        return "(无)"
    first = blocks[0]
    last = blocks[-1]
    first_label = f"[{first.index}] id={first.id} type={display_block_semantic_type(first)}"
    if len(blocks) == 1:
        return first_label
    return f"{first_label} -> [{last.index}] id={last.id} type={display_block_semantic_type(last)}"


def block_index_by_id(blocks: list[DisplayBlock], block_id: str) -> int | None:
    for index, block in enumerate(blocks):
        if block.id == block_id:
            return index
    return None


def blocks_between_anchors(
    blocks: list[DisplayBlock],
    previous_id: str | None,
    next_id: str | None,
) -> list[DisplayBlock]:
    start = 0
    if previous_id:
        previous_index = block_index_by_id(blocks, previous_id)
        if previous_index is not None:
            start = previous_index + 1
    end = len(blocks)
    if next_id:
        next_index = block_index_by_id(blocks, next_id)
        if next_index is not None:
            end = next_index
    if end < start:
        return []
    return blocks[start:end]


def markdown_has_multiple_blocks(markdown: str) -> bool:
    in_fence = False
    saw_content = False
    saw_blank_after_content = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        if in_fence:
            if stripped:
                saw_content = True
            continue
        if not stripped:
            if saw_content:
                saw_blank_after_content = True
            continue
        if saw_blank_after_content:
            return True
        saw_content = True
    return False


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


def _extract_tool_action(tool_name: str, args: dict[str, Any]) -> str | None:
    """Extract the sub-action from tool arguments for telemetry grouping."""
    if tool_name == "siyuan_edit":
        action = args.get("action")
        return str(action) if action else None
    if tool_name == "siyuan_create":
        if_exists = args.get("if_exists")
        return str(if_exists) if if_exists else None
    if tool_name == "siyuan_doc_manage":
        action = args.get("action")
        return str(action) if action else None
    return None


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
            "siyuan_find": self.siyuan_find,
            "siyuan_read": self.siyuan_read,
            "siyuan_create": self.siyuan_create,
            "siyuan_edit": self.siyuan_edit,
            "siyuan_doc_manage": self.siyuan_doc_manage,
            "siyuan_bridge_feedback": self.siyuan_bridge_feedback,
        }
        if name not in tools:
            return make_error(request_id, -32602, f"Unknown tool: {name}")
        try:
            action = _extract_tool_action(name, args)

            if name == "siyuan_bridge_feedback":
                # Feedback does not require SiYuan to be running
                text = _with_telemetry(
                    self.root, name, action,
                    lambda: tools[name](args),
                )
            else:
                text = _with_telemetry(
                    self.root, name, action,
                    lambda: (detect_active_profile(load_config(self.root)), tools[name](args))[1],
                )
            return make_result(request_id, {"content": [{"type": "text", "text": text}]})
        except SiYuanConnectionError as exc:
            reason = str(exc).strip()
            if not reason:
                reason = "无法连接到思源笔记"
            return make_result(
                request_id,
                {"content": [{"type": "text", "text": f"思源未启动或 API 不可达：{reason}\n\n请提示用户手动打开思源笔记后重试。\n请先手动启动思源笔记，确认当前工作空间已打开且 API Token 配置正确，然后重试。"}], "isError": True},
            )
        except (SiYuanApiError, ValueError, FileNotFoundError) as exc:
            return make_result(
                request_id,
                {"content": [{"type": "text", "text": f"工具执行失败：{exc}"}], "isError": True},
            )

    def _refresh_index_with_system_context(self, client: SiYuanClient) -> None:
        config = load_config(self.root)
        state = ensure_agent_notebook(client, self.root, config_language=config.language or None)
        write_privacy_rules_cache(self.root, state.privacy_rules)
        refresh_index(
            client,
            self.root,
            system_notebook_id=state.notebook_id,
            privacy_rules_doc_id=state.privacy_rules_doc_id,
        )

    def _wait_for_hpath(self, client: SiYuanClient, doc_id: str, expected_hpath: str) -> PostWriteSyncStatus:
        expected = normalize_display_path(expected_hpath).casefold()
        deadline = time.monotonic() + POST_WRITE_SYNC_TIMEOUT
        last_seen_api = ""
        last_seen_sql = ""
        while time.monotonic() < deadline:
            try:
                current = normalize_display_path(client.get_hpath_by_id(doc_id))
            except Exception:
                current = ""
            if current:
                last_seen_api = current
            try:
                live_doc = next((doc for doc in load_live_docs(client) if str(doc.get("id", "")) == doc_id), None)
                live_hpath = normalize_display_path(str(live_doc.get("hpath", ""))) if live_doc else ""
            except Exception:
                live_hpath = ""
            if live_hpath:
                last_seen_sql = live_hpath
            if current and live_hpath and current.casefold() == expected and live_hpath.casefold() == expected:
                return PostWriteSyncStatus(True, f"路径已同步：{current}")
            time.sleep(POST_WRITE_SYNC_INTERVAL)
        if last_seen_api or last_seen_sql:
            details = []
            if last_seen_api:
                details.append(f"路径接口：{last_seen_api}")
            if last_seen_sql:
                details.append(f"索引源：{last_seen_sql}")
            return PostWriteSyncStatus(False, f"路径尚未同步到目标；{'; '.join(details)}，目标路径：{expected_hpath}")
        return PostWriteSyncStatus(False, f"路径尚未同步到目标：{expected_hpath}")

    def _wait_for_deleted_doc(self, client: SiYuanClient, doc_id: str) -> PostWriteSyncStatus:
        deadline = time.monotonic() + POST_WRITE_SYNC_TIMEOUT
        last_seen = ""
        while time.monotonic() < deadline:
            try:
                current = normalize_display_path(client.get_hpath_by_id(doc_id))
            except Exception:
                return PostWriteSyncStatus(True, "文档删除已同步")
            if not current:
                return PostWriteSyncStatus(True, "文档删除已同步")
            last_seen = current
            time.sleep(POST_WRITE_SYNC_INTERVAL)
        return PostWriteSyncStatus(False, f"删除操作尚未从路径接口确认；当前仍可见：{last_seen}")

    def siyuan_start(self, _args: dict[str, Any]) -> str:
        config = load_config(self.root)
        profile, client = detect_active_profile(config)
        version = client.version()

        # Initialize telemetry session
        set_siyuan_version(version)
        load_anonymous_id(self.root)
        ensure_session_id()

        # Ensure system notebook and parse privacy rules
        state = ensure_agent_notebook(client, self.root, config_language=config.language or None)
        nb_id = state.notebook_id

        # Cache privacy rules for other tools
        write_privacy_rules_cache(self.root, state.privacy_rules)

        # Clean ai_workspace (preserve README.md)
        workspace_dir = self.root / "ai_workspace"
        if workspace_dir.exists():
            for item in workspace_dir.iterdir():
                if item.name == "README.md":
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

        # Refresh indexes using cached privacy rules
        refresh_index(
            client, self.root,
            system_notebook_id=nb_id,
            privacy_rules_doc_id=state.privacy_rules_doc_id,
        )

        lang_config = build_language_config(state.language)
        overview = build_notebook_overview(self.root)
        parts: list[str] = [
            "# 思源桥启动包",
            "",
            f"思源连接：正常，版本 {version}",
            f"已连接工作空间：**{profile.name}**",
            f"系统笔记本：`{state.notebook_name}`（`{nb_id}`）",
            "",
            lang_config.startup_header,
            "",
            overview,
        ]

        # Privacy rules status (no specific rule details exposed)
        total_ignore = len(state.privacy_rules.ignore)
        total_permissions = len(state.privacy_rules.permissions)
        if total_ignore > 0 or total_permissions > 0:
            nb_ignore = [r for r in state.privacy_rules.ignore if r.get("scope") == "notebook"]
            doc_ignore = [r for r in state.privacy_rules.ignore if r.get("scope") == "document"]
            nb_perm = [r for r in state.privacy_rules.permissions if r.get("scope") == "notebook"]
            doc_perm = [r for r in state.privacy_rules.permissions if r.get("scope") == "document"]
            total_nb = len(nb_ignore) + len(nb_perm)
            total_doc = len(doc_ignore) + len(doc_perm)
            parts.append("")
            parts.append(
                f"隐私规则：已加载，{total_nb} 条笔记本规则，{total_doc} 条文档规则。"
            )
        else:
            parts.append("")
            parts.append("隐私规则：已加载，无规则。")

        if state.workspace_index_markdown:
            parts.extend([
                "",
                "## 工作空间索引（语义导航索引）",
                "",
                state.workspace_index_markdown.strip(),
            ])
        else:
            parts.extend([
                "",
                "> 当前没有导航索引。你可以建议用户先快速扫一遍笔记本结构创建导航索引，之后每次新会话都能直接定位。",
            ])
        parts.extend([
            "",
            "## AI 使用指南（用户偏好与规则）",
            "",
            state.ai_guide_markdown.strip() if state.ai_guide_markdown else "（AI 使用指南为空——如需补充，请先读取系统笔记本中的 AI Guide，再经用户批准用 siyuan_edit 写入）",
            "",
        ])
        # Mention About document but don't include full text
        parts.extend([
            "---",
            f"**给人看的说明**：系统笔记本中还有一篇 `/关于思源桥`，是对工具核心思想的简要介绍。普通任务无需读取。需要时可用 `siyuan_read` 指定文档 ID 阅读。",
            "",
        ])
        return "\n".join(parts)

    def siyuan_refresh_index(self, _args: dict[str, Any]) -> str:
        config = load_config(self.root)
        _profile, client = detect_active_profile(config)

        # Ensure system notebook and parse privacy rules
        state = ensure_agent_notebook(client, self.root, config_language=config.language or None)
        write_privacy_rules_cache(self.root, state.privacy_rules)

        result = refresh_index(
            client, self.root,
            system_notebook_id=state.notebook_id,
            privacy_rules_doc_id=state.privacy_rules_doc_id,
        )
        total_ignore = len(state.privacy_rules.ignore)
        total_permissions = len(state.privacy_rules.permissions)
        total_rules = total_ignore + total_permissions
        return (
            "# 索引已刷新\n\n"
            f"可见：{result.notebook_count} 个笔记本、{result.document_count} 篇文档。\n"
            f"隐私规则：{total_rules} 条隐私规则已生效。"
        )

    def siyuan_list(self, args: dict[str, Any]) -> str:
        path = normalize_display_path(str(args.get("path") or "").strip())
        notebook_id = str(args.get("notebook_id") or "").strip()
        notebook_name = str(args.get("notebook_name") or "").strip()
        limit = clamp_int(args.get("limit"), 100, 1, 500)
        offset = max(int(args.get("offset") or 0), 0)

        if not path and not notebook_id and not notebook_name:
            # List all notebooks
            notebooks = read_json(self.root / KNOWLEDGE_BASE_DIR / "notebooks.json")
            docs = load_docs(self.root)
            privacy = load_privacy_rules(self.root)
            lines = ["# 可见笔记本", ""]
            lines.extend([
                "| notebook | notebook_id | 权限 |",
                "|---|---|---|",
            ])
            for notebook in notebooks:
                permission = document_permission(notebook_permission_probe(notebook), privacy, docs)
                lines.append(
                    "| "
                    + " | ".join([
                        str(notebook.get("name", "")),
                        f"`{notebook.get('id', '')}`",
                        permission,
                    ])
                    + " |"
                )
            lines.append("")
            return "\n".join(lines)

        docs = load_docs(self.root)
        privacy = load_privacy_rules(self.root)
        notebooks = read_json(self.root / KNOWLEDGE_BASE_DIR / "notebooks.json")

        # Compatibility: old notebook_id/notebook_name args now list the notebook root.
        if not notebook_id and notebook_name:
            notebook_id = self.resolve_notebook_id(notebook_name)
        if notebook_id and not path:
            path = normalize_display_path(self._notebook_name(notebook_id))

        if not path:
            raise tool_error(_ERR_MISSING_PARAM, "path 参数为空。")

        parent_doc = next(
            (doc for doc in docs if display_document_path(doc).casefold() == path.casefold()),
            None,
        )
        notebook = next(
            (nb for nb in notebooks if normalize_display_path(str(nb.get("name", ""))).casefold() == path.casefold()),
            None,
        )
        if parent_doc is None and notebook is None:
            has_descendants = any(
                display_document_path(doc).casefold().startswith(path.casefold() + "/")
                for doc in docs
            )
            if not has_descendants:
                raise FileNotFoundError(f"未找到可见路径：{path}")

        children_by_name: dict[str, dict[str, Any]] = {}
        for doc in docs:
            child_name = direct_child_key(path, display_document_path(doc))
            if not child_name:
                continue
            child_path = normalize_display_path(f"{path}/{child_name}")
            existing = children_by_name.get(child_name)
            exact_doc = display_document_path(doc).casefold() == child_path.casefold()
            if existing is None or exact_doc:
                if exact_doc:
                    children_by_name[child_name] = doc
                else:
                    children_by_name[child_name] = {
                        "id": "",
                        "notebook_id": str(doc.get("notebook_id", "")),
                        "notebook_name": str(doc.get("notebook_name", "")),
                        "hpath": "/" + child_path.strip("/").split("/", 1)[1],
                        "title": child_name,
                        "word_count": 0,
                        "block_count": 0,
                        "updated": "",
                    }

        children = list(children_by_name.values())
        children.sort(key=lambda doc: display_document_path(doc).casefold())
        total = len(children)
        page = children[offset:offset + limit]

        lines = [
            f"# {path}",
            "",
            "| document | document_id | 权限 | 字数 | 块数 | 更新 | 子文档 |",
            "|---|---|---|---:|---:|---|---:|",
        ]
        if not page:
            lines.append("| (无可见子文档) |  |  |  |  |  |  |")
        for doc in page:
            doc_path = display_document_path(doc)
            permission = document_permission(doc, privacy, docs)
            lines.append(
                "| "
                + " | ".join([
                    doc_path,
                    f"`{doc.get('id', '')}`",
                    permission,
                    format_int(doc.get("word_count", 0)),
                    format_int(doc.get("block_count", 0)),
                    format_date(str(doc.get("updated", ""))),
                    format_int(descendant_count(doc, docs)),
                ])
                + " |"
            )
        if offset + limit < total:
            remaining = total - offset - limit
            lines.extend([
                "",
                f"还有 {remaining} 项未显示。",
                f"继续：siyuan_list(path=\"{path}\", offset={offset + limit}, limit={limit})",
            ])
        return "\n".join(lines)

    def _notebook_name(self, notebook_id: str) -> str:
        notebooks = read_json(self.root / KNOWLEDGE_BASE_DIR / "notebooks.json")
        for nb in notebooks:
            if str(nb.get("id", "")) == notebook_id:
                return str(nb.get("name", notebook_id))
        return notebook_id

    def siyuan_find(self, args: dict[str, Any]) -> str:
        keyword = str(args.get("keyword") or "").strip()
        if not keyword:
            raise tool_error(_ERR_MISSING_PARAM, "keyword 参数是必填的")

        mode = str(args.get("mode") or "keyword").strip().casefold()
        if mode not in ("keyword", "query", "regex", "sql"):
            raise tool_error(_ERR_INVALID_ENUM, "mode 必须是 keyword、query、regex 或 sql 之一")

        scope = str(args.get("scope") or "headings").strip().casefold()
        if scope not in ("headings", "full"):
            raise tool_error(_ERR_INVALID_ENUM, "scope 必须是 headings 或 full 之一")

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
            _profile, client = detect_active_profile(load_config(self.root))
            notebook_names.update(list_live_notebook_names(client))
            try:
                with ensure_notebooks_open(client, notebooks):
                    rows = client.query_sql(keyword)
            except SiYuanApiError as exc:
                if "administrator" in str(exc).casefold() or "privilege" in str(exc).casefold():
                    raise tool_error(_ERR_SQL_ADMIN, "SQL 搜索需要思源管理员权限，请改用 keyword、query 或 regex 模式。") from exc
                raise
            enriched = self._enrich_sql_results(rows, indexed_docs, notebook_names, privacy, notebooks)
        else:
            _profile, client = detect_active_profile(load_config(self.root))
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
            return f"# 搜索：\"{keyword}\"（{scope}，{mode}）\n\n未找到匹配的可见文档。"

        enriched = enriched[:limit]
        grouped = self._group_by_notebook(enriched)

        scope_label = "标题" if scope == "headings" else "全文"
        lines = [f"# 搜索：\"{keyword}\"（{scope_label}，{mode}，{len(enriched)} 条结果，{len(grouped)} 个笔记本）", ""]

        remaining = limit
        for nb_name in sorted(grouped, key=str.casefold):
            items = grouped[nb_name]
            lines.append(f"## {nb_name}（{len(items)} 条命中）")
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
                    "source": "实时搜索",
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

    def siyuan_read(self, args: dict[str, Any]) -> str:
        doc = self.resolve_visible_document(args)
        _profile, client = detect_active_profile(load_config(self.root))
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
            markdown = rewrite_local_asset_links(markdown, doc_id, self.root)
            doc_path = display_document_path(doc)
            date = format_date(str(doc.get("updated", "")))
            header_lines = [
                f"# 文档：{doc_path}",
                f"文档 ID：`{doc_id}`",
                f"更新：{date}",
                "阅读模式：普通阅读（降级到导出 Markdown）",
            ]
            if attachment_count:
                header_lines.append(f"附件：{attachment_count} 个已提取到 {attachment_root_dir(self.root, doc_id).resolve()}")
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
        doc_path = display_document_path(doc)
        date = format_date(str(doc.get("updated", "")))
        mode_label = "引用阅读（显示块序号、ID 和类型）" if include_block_ids else "普通阅读"
        header_lines = [
            f"# 文档：{doc_path}",
            f"文档 ID：`{doc_id}`",
            f"更新：{date}",
            f"阅读模式：{mode_label}",
            f"展示块：{first_idx}-{last_idx} / {total_blocks}",
            f"估算令牌数：{window_tokens:,} / {token_budget:,}",
        ]
        if start_idx + block_limit < total_blocks:
            next_start = last_idx + 1
            header_lines.append(f"下一窗口：block_start={next_start}, block_limit={block_limit}")
        if attachment_count:
            header_lines.append(f"附件：{attachment_count} 个已提取到 {attachment_root_dir(self.root, doc_id).resolve()}")
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
        body = rewrite_local_asset_links(body, doc_id, self.root)

        parts = [header, "", outline]
        if window_preview:
            parts.extend(["", window_preview])
        parts.extend(["", "---", "", body])

        if last_idx < total_blocks:
            parts.extend([
                "",
                "---",
                f"> 继续阅读：`block_start={last_idx + 1}, block_limit={block_limit}`",
            ])

        return "\n".join(parts)

    def resolve_visible_document(self, args: dict[str, Any]) -> dict[str, Any]:
        locator = str(args.get("document") or args.get("document_id") or args.get("locator") or "").strip()
        if not locator:
            raise tool_error(_ERR_MISSING_PARAM, "document/document_id 参数是必填的")
        docs = filter_documents(load_docs(self.root), load_privacy_rules(self.root))
        if locator.startswith("/"):
            exact_display_path = [
                doc
                for doc in docs
                if display_document_path(doc).strip("/").casefold() == locator.strip("/").casefold()
            ]
            if exact_display_path:
                if len(exact_display_path) > 1:
                    choices = "\n".join(f"- `{doc.get('id')}` {display_document_path(doc)}" for doc in exact_display_path)
                    raise tool_error(_ERR_AMBIGUOUS, f"文档路径存在歧义，请补充 document_id：\n{choices}")
                doc = exact_display_path[0]
                if is_privacy_rules_document(str(doc.get("hpath", ""))):
                    raise tool_error(_ERR_PRIVACY_RULES,
                        "Privacy Rules 文档不可通过 AI 访问。隐私规则由人类在思源中维护。"
                    )
                return doc
        status, matches = resolve_document(docs, locator)
        if status == "ambiguous":
            choices = "\n".join(f"- `{doc.get('id')}` {doc.get('hpath')}" for doc in matches)
            raise tool_error(_ERR_AMBIGUOUS, f"文档定位符存在歧义：\n{choices}")
        if status in ("missing", "no_index"):
            privacy = load_privacy_rules(self.root)
            if privacy.allow:
                _profile, client = detect_active_profile(load_config(self.root))
                with ensure_notebooks_open(client):
                    live_docs = filter_documents(load_live_docs(client), privacy)
                status, matches = resolve_document(live_docs, locator)
        if status != "ok":
            raise tool_error(_ERR_DOC_NOT_FOUND, "未找到匹配的可见文档。文档可能已被隐藏、尚未索引，或定位符有误。")
        doc = matches[0]
        if is_privacy_rules_document(str(doc.get("hpath", ""))):
            raise tool_error(_ERR_PRIVACY_RULES,
                "Privacy Rules 文档不可通过 AI 访问。隐私规则由人类在思源中维护。"
            )
        return doc

    def export_document_markdown(self, document_id: str) -> str:
        _profile, client = detect_active_profile(load_config(self.root))
        return client.export_markdown(document_id)

    def siyuan_create(self, args: dict[str, Any]) -> str:
        confirmed = bool(args.get("confirmed"))
        if not confirmed:
            raise tool_error(_ERR_NOT_CONFIRMED, "需要 confirmed=true。写入思源必须经过用户明确确认。")

        title = str(args.get("title") or "").strip()
        if not title:
            raise tool_error(_ERR_MISSING_PARAM, "title 参数是必填的")

        markdown = str(args.get("markdown") or "").strip()
        if not markdown:
            raise tool_error(_ERR_MISSING_PARAM, "markdown 参数是必填的")

        if_exists = str(args.get("if_exists") or "reject").strip().casefold()
        if if_exists not in {"reject", "overwrite", "create_new"}:
            raise tool_error(_ERR_INVALID_ENUM, "if_exists 只支持 reject、overwrite、create_new。默认 reject。")

        notebooks = read_json(self.root / KNOWLEDGE_BASE_DIR / "notebooks.json")
        docs = filter_documents(load_docs(self.root), load_privacy_rules(self.root))
        target = resolve_create_target(args, notebooks, docs, title)
        all_docs = load_docs(self.root)
        privacy = load_privacy_rules(self.root)
        target_doc_for_permission = {
            "id": "",
            "notebook_id": target.notebook_id,
            "notebook_name": target.notebook_name,
            "hpath": target.internal_path,
        }
        if document_permission(target_doc_for_permission, privacy, all_docs) != "read_write":
            raise tool_error(_ERR_NOT_READ_WRITE, "目标路径权限不是 read_write，不允许创建或覆盖文档。")

        # Prevent creating Privacy Rules document
        if is_privacy_rules_document(target.internal_path.strip("/")):
            raise tool_error(_ERR_PRIVACY_RULES,
                "Privacy Rules 文档不可通过 AI 创建。隐私规则由人类在思源中维护。"
            )
        for existing in target.existing_docs:
            if document_permission(existing, privacy, all_docs) != "read_write":
                raise tool_error(_ERR_NOT_READ_WRITE, f"目标文档权限不是 read_write，不允许写入：{display_document_path(existing)}")

        if target.existing_docs and if_exists == "reject":
            choices = "\n".join(
                f"- `{doc.get('id', '')}` {display_document_path(doc)}"
                for doc in target.existing_docs
            )
            raise tool_error(_ERR_ALREADY_EXISTS,
                "目标文档已存在，默认拒绝写入以避免误覆盖。\n"
                "可选处理：if_exists=overwrite 清空当前文档所有块后重写，并保留文档 ID；"
                "if_exists=create_new 新增一个同名文档。\n"
                + choices
            )
        if len(target.existing_docs) > 1 and if_exists == "overwrite":
            choices = "\n".join(
                f"- `{doc.get('id', '')}` {display_document_path(doc)}"
                for doc in target.existing_docs
            )
            raise tool_error(_ERR_MULTI_DOC_OVERWRITE,
                "目标路径下已有多个同名文档，无法判断覆盖时应保留哪个文档 ID。"
                "请先用 siyuan_edit 定位具体文档，或使用 if_exists=create_new。\n"
                + choices
            )

        _profile, client = detect_active_profile(load_config(self.root))

        # Create snapshot before writing
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        memo = f"siyuan-bridge:auto-snapshot tool=siyuan_create target={target.display_path} created={ts}"
        try:
            client.create_snapshot(memo)
            snapshot_status = "created"
        except SiYuanApiError as exc:
            msg = str(exc)
            if "数据仓库密钥" in msg or "data repo key" in msg.casefold() or "key" in msg.casefold():
                raise tool_error(_ERR_SNAPSHOT_KEY,
                    "快照创建失败：数据仓库密钥未初始化。"
                    "请打开思源 → 设置 → 关于 → 数据仓库密钥，初始化密钥后重试。"
                ) from exc
            raise tool_error(_ERR_SNAPSHOT_FAILED, f"快照创建失败，拒绝写入。错误：{msg}") from exc

        # Normalize markdown to avoid duplicate H1
        markdown = normalize_new_document_markdown(title, markdown)
        if not markdown.strip():
            raise tool_error(_ERR_MISSING_PARAM, "markdown 参数是必填的")

        action_status = "created"
        overwritten_blocks: list[DisplayBlock] = []
        existing_doc: dict[str, Any] | None = target.existing_docs[0] if target.existing_docs else None

        with ensure_notebooks_open(client, [target.notebook_id]):
            if existing_doc and if_exists == "overwrite":
                doc_id = str(existing_doc.get("id", ""))
                overwritten_blocks = build_display_blocks(client, doc_id, include_block_ids=True)
                for block in reversed(overwritten_blocks):
                    client.delete_block(block.id)
                client.append_block(doc_id, markdown)
                result = {"id": doc_id}
                action_status = "overwritten"
            else:
                result = client.create_doc_with_md(target.notebook_id, target.internal_path, markdown)
                action_status = "created_new" if existing_doc and if_exists == "create_new" else "created"

        doc_id = str(result.get("id") or result.get("docID") or result.get("doc_id") or "")
        if not doc_id:
            # Try to resolve by path
            try:
                live_docs = load_live_docs(client)
                for doc in live_docs:
                    if (
                        str(doc.get("hpath", "")).strip("/") == target.internal_path.strip("/")
                        and str(doc.get("notebook_id", "")) == target.notebook_id
                        and str(doc.get("id", "")) not in {str(item.get("id", "")) for item in target.existing_docs}
                    ):
                        doc_id = str(doc.get("id", ""))
                        break
            except Exception:
                pass

        # Notify
        try:
            client.push_msg(f"思源桥：已写入「{target.display_path}」")
        except Exception:
            pass

        sync_status: PostWriteSyncStatus | None = None
        if doc_id:
            sync_status = self._wait_for_hpath(client, doc_id, target.internal_path)

        # Auto-refresh index
        refresh_ok = False
        try:
            self._refresh_index_with_system_context(client)
            refresh_ok = True
        except Exception:
            pass

        parts = [
            "# 文档写入成功",
            "",
            f"**动作：**{action_status}",
            f"**标题：**{title}",
            f"**路径：**{target.display_path}",
            f"**内部路径：**{target.internal_path}",
            f"**笔记本：**{target.notebook_name}（`{target.notebook_id}`）",
        ]
        if doc_id:
            parts.append(f"**文档 ID：**`{doc_id}`")
        if overwritten_blocks:
            parts.append(f"**覆盖：**已清空并重写 {len(overwritten_blocks)} 个原块，保留当前文档 ID。")
        parts.append(f"**端点：**{client.base_url}")
        parts.append(f"**快照：**{snapshot_status}")
        if sync_status is not None:
            parts.append(f"**路径同步：**{sync_status.detail}")
        if refresh_ok:
            parts.append(f"**索引：**已自动刷新")
        else:
            parts.append(f"**索引：**自动刷新失败，请手动运行 `siyuan_refresh_index`")
        parts.extend([
            "",
            "如需回滚，可通过思源快照手动恢复。",
        ])
        return "\n".join(parts)

    @staticmethod
    def _create_snapshot_or_raise(client: Any, tool: str, target: str) -> str:
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        memo = f"siyuan-bridge:auto-snapshot tool={tool} target={target} created={ts}"
        try:
            client.create_snapshot(memo)
            return "created"
        except SiYuanApiError as exc:
            msg = str(exc)
            if "数据仓库密钥" in msg or "data repo key" in msg.casefold() or "key" in msg.casefold():
                raise tool_error(_ERR_SNAPSHOT_KEY,
                    "快照创建失败：数据仓库密钥未初始化。"
                    "请打开思源 -> 设置 -> 关于 -> 数据仓库密钥，初始化密钥后重试。"
                ) from exc
            raise tool_error(_ERR_SNAPSHOT_FAILED, f"快照创建失败，拒绝写入。错误：{msg}") from exc

    @staticmethod
    def _update_block_preserving_attrs(client: Any, block_id: str, markdown: str) -> None:
        ial_rows = client.query_sql(f"SELECT ial FROM blocks WHERE id = '{block_id}'")
        custom_attrs: dict[str, str] = {}
        if ial_rows:
            custom_attrs = _parse_ial_attrs(str(ial_rows[0].get("ial", "")))
        client.update_block(block_id, markdown)
        if custom_attrs:
            client.set_block_attrs(block_id, custom_attrs)

    @staticmethod
    def _edit_range_from_args(args: dict[str, Any], blocks: list[DisplayBlock]) -> list[DisplayBlock]:
        if args.get("start_index") is None or not str(args.get("start_id") or "").strip():
            raise tool_error(_ERR_MISSING_EDIT_RANGE, "需要 start_index 和 start_id。请先用 siyuan_read(include_block_ids=true) 进行引用阅读。")
        try:
            start_index = int(args["start_index"])
        except (TypeError, ValueError) as exc:
            raise tool_error(_ERR_INVALID_TYPE, "start_index 必须是整数。") from exc
        start_id = str(args.get("start_id") or "").strip()
        start_pos = next((i for i, block in enumerate(blocks) if block.index == start_index), None)
        if start_pos is None:
            raise tool_error(_ERR_BLOCK_NOT_FOUND,
                f"目标块校验失败：当前文档没有 start_index={start_index}。"
                "文档可能在上次读取后发生变化。请重新调用 siyuan_read(include_block_ids=true)，"
                "用新的块序号和块 ID 再编辑。"
            )
        if blocks[start_pos].id != start_id:
            raise tool_error(_ERR_STALE_BLOCK_ID,
                f"目标块校验失败：start_index={start_index} 对应的当前块 ID 是 `{blocks[start_pos].id}`，"
                f"但请求中的 start_id 是 `{start_id}`。请重新调用 siyuan_read(include_block_ids=true)，"
                "不要沿用旧块 ID。"
            )

        if args.get("end_index") is None and not str(args.get("end_id") or "").strip():
            return [blocks[start_pos]]
        if args.get("end_index") is None or not str(args.get("end_id") or "").strip():
            raise tool_error(_ERR_MISSING_EDIT_RANGE, "范围操作需要同时提供 end_index 和 end_id。")
        try:
            end_index = int(args["end_index"])
        except (TypeError, ValueError) as exc:
            raise tool_error(_ERR_INVALID_TYPE, "end_index 必须是整数。") from exc
        end_id = str(args.get("end_id") or "").strip()
        end_pos = next((i for i, block in enumerate(blocks) if block.index == end_index), None)
        if end_pos is None:
            raise tool_error(_ERR_BLOCK_NOT_FOUND,
                f"目标块校验失败：当前文档没有 end_index={end_index}。"
                "文档可能在上次读取后发生变化。请重新调用 siyuan_read(include_block_ids=true)，"
                "用新的范围端点再编辑。"
            )
        if blocks[end_pos].id != end_id:
            raise tool_error(_ERR_STALE_BLOCK_ID,
                f"目标块校验失败：end_index={end_index} 对应的当前块 ID 是 `{blocks[end_pos].id}`，"
                f"但请求中的 end_id 是 `{end_id}`。请重新调用 siyuan_read(include_block_ids=true)，"
                "不要沿用旧块 ID。"
            )
        if end_pos < start_pos:
            raise tool_error(_ERR_OPERATION_ORDER, "范围操作要求 start_index <= end_index。")
        return blocks[start_pos:end_pos + 1]

    def siyuan_edit(self, args: dict[str, Any]) -> str:
        confirmed = bool(args.get("confirmed"))
        if not confirmed:
            raise tool_error(_ERR_NOT_CONFIRMED, "需要 confirmed=true。编辑思源文档必须经过用户明确确认。")

        action = str(args.get("action") or "").strip()
        allowed_actions = {
            "single_block_replace",
            "multi_block_replace",
            "insert_after",
            "insert_before",
            "append",
            "delete",
            "table_edit",
        }
        if action not in allowed_actions:
            raise tool_error(_ERR_INVALID_ENUM,
                "action 只支持 single_block_replace、multi_block_replace、"
                "insert_after、insert_before、append、delete、table_edit。"
            )

        doc = self.resolve_visible_document(args)
        doc_id = str(doc.get("id", ""))
        doc_title = display_document_path(doc)
        notebook_id = str(doc.get("notebook_id", ""))
        all_docs = load_docs(self.root)
        permission = document_permission(doc, load_privacy_rules(self.root), all_docs)
        if permission != "read_write":
            raise tool_error(_ERR_NOT_READ_WRITE, f"当前文档权限为 {permission}，不允许编辑。")

        _profile, client = detect_active_profile(load_config(self.root))

        with ensure_notebooks_open(client, [notebook_id]):
            display_blocks = build_display_blocks(client, doc_id, include_block_ids=True)

        target_blocks: list[DisplayBlock] = []
        if action != "append":
            target_blocks = self._edit_range_from_args(args, display_blocks)
        markdown = str(args.get("markdown") or "")

        if action in {"single_block_replace", "multi_block_replace", "insert_after", "insert_before", "append"} and not markdown.strip():
            raise tool_error(_ERR_MISSING_PARAM, f"action={action} 需要 markdown。")
        if action == "table_edit" and not isinstance(args.get("table_edit"), dict):
            raise tool_error(_ERR_MISSING_PARAM, "action=table_edit 需要 table_edit 对象。")

        if action in {"single_block_replace", "multi_block_replace"}:
            refused = [
                f"[{block.index}] id={block.id} type={display_block_semantic_type(block)}"
                for block in target_blocks
                if display_block_semantic_type(block) in REPLACE_REFUSED_SEMANTIC_TYPES
            ]
            if refused:
                raise tool_error(_ERR_WRONG_TARGET,
                    f"{action} 暂不支持复杂块类型。\n"
                    "处理建议：如需移除目标块，用 delete；如需补充说明，用 insert_before 或 insert_after；"
                    "如需重构复杂块附近内容，请只替换普通文本/标题/代码/表格块。\n"
                    + "\n".join(refused)
                )

        if action == "single_block_replace":
            if len(target_blocks) != 1:
                raise tool_error(_ERR_WRONG_SHAPE,
                    "single_block_replace 只能替换单个块，并保留该块 ID 和块属性。"
                    "当前目标是多个块；请改用 multi_block_replace。注意 multi_block_replace 会重建块，"
                    "旧块 ID 和指向旧块的引用会失效。"
                )
            if markdown_has_multiple_blocks(markdown):
                raise tool_error(_ERR_WRONG_SHAPE,
                    "single_block_replace 的 markdown 必须只生成一个展示块，因为它会复用原块 ID 和块属性。"
                    "当前 markdown 会被思源拆成多个块；请改用 multi_block_replace。"
                    "注意 multi_block_replace 会重建块，旧块 ID 和指向旧块的引用会失效。"
                )

        new_table = ""
        if action == "table_edit":
            target = target_blocks[0]
            if len(target_blocks) != 1:
                raise tool_error(_ERR_WRONG_SHAPE, "table_edit 只能作用于单个普通 Markdown 表格块。范围表格编辑请拆成多次调用。")
            if display_block_semantic_type(target) != "table":
                raise tool_error(_ERR_WRONG_TARGET,
                    f"table_edit 只能作用于 type=table 的普通 Markdown 表格；当前目标为 type={display_block_semantic_type(target)}。"
                    "如果要在该块附近添加表格或说明，请使用 insert_before / insert_after；"
                    "如果要整体替换为普通内容，请使用 multi_block_replace。"
                )
            new_table = apply_table_edit(display_block_source(target), args["table_edit"])

        if target_blocks:
            target_start_pos = block_index_by_id(display_blocks, target_blocks[0].id)
            target_end_pos = block_index_by_id(display_blocks, target_blocks[-1].id)
        else:
            target_start_pos = None
            target_end_pos = None
        previous_anchor = (
            display_blocks[target_start_pos - 1]
            if target_start_pos is not None and target_start_pos > 0
            else None
        )
        next_anchor = (
            display_blocks[target_end_pos + 1]
            if target_end_pos is not None and target_end_pos + 1 < len(display_blocks)
            else None
        )
        last_before_append = display_blocks[-1] if display_blocks else None

        self._create_snapshot_or_raise(client, "siyuan_edit", doc_title)

        with ensure_notebooks_open(client, [notebook_id]):
            if action == "append":
                client.append_block(doc_id, markdown)
            elif action == "insert_after":
                client.insert_block_after(target_blocks[-1].id, markdown)
            elif action == "insert_before":
                client.insert_block_before(target_blocks[0].id, markdown)
            elif action == "delete":
                for block in reversed(target_blocks):
                    client.delete_block(block.id)
            elif action == "table_edit":
                self._update_block_preserving_attrs(client, target_blocks[0].id, new_table)
            elif action == "single_block_replace":
                self._update_block_preserving_attrs(client, target_blocks[0].id, markdown)
            elif action == "multi_block_replace":
                client.insert_block_before(target_blocks[0].id, markdown)
                for block in reversed(target_blocks):
                    client.delete_block(block.id)

            new_display_blocks = build_display_blocks(client, doc_id, include_block_ids=True)

        try:
            client.push_msg(f"思源桥：已编辑「{doc_title}」")
        except Exception:
            pass

        parts = [
            "# 文档已编辑",
            "",
            f"文档：{doc_title}（`{doc_id}`）",
            f"action：{action}",
        ]

        if action in {"single_block_replace", "multi_block_replace"}:
            if action == "single_block_replace":
                replaced = [
                    block for block in new_display_blocks
                    if block.id == target_blocks[0].id
                ]
            else:
                replaced = blocks_between_anchors(
                    new_display_blocks,
                    previous_anchor.id if previous_anchor else None,
                    next_anchor.id if next_anchor else None,
                )
            parts.extend([
                f"已替换 {len(target_blocks)} 个块：{block_range_label(target_blocks)}",
                "",
                "## 原内容",
                "",
                format_display_blocks(target_blocks),
                "",
                "## 新内容",
                "",
                format_display_blocks(replaced),
            ])
        elif action in {"insert_after", "insert_before"}:
            if action == "insert_after":
                inserted = blocks_between_anchors(
                    new_display_blocks,
                    target_blocks[-1].id,
                    next_anchor.id if next_anchor else None,
                )
            else:
                inserted = blocks_between_anchors(
                    new_display_blocks,
                    previous_anchor.id if previous_anchor else None,
                    target_blocks[0].id,
                )
            parts.extend([
                f"锚点：{block_range_label(target_blocks)}",
                "",
                "## 锚点内容",
                "",
                format_display_blocks(target_blocks),
                "",
                "## 插入内容",
                "",
                format_display_blocks(inserted),
            ])
        elif action == "append":
            appended = blocks_between_anchors(
                new_display_blocks,
                last_before_append.id if last_before_append else None,
                None,
            )
            parts.extend([
                "",
                "## 追加内容",
                "",
                format_display_blocks(appended),
            ])
        elif action == "delete":
            current_previous = (
                [block for block in new_display_blocks if previous_anchor and block.id == previous_anchor.id]
            )
            current_next = (
                [block for block in new_display_blocks if next_anchor and block.id == next_anchor.id]
            )
            parts.extend([
                f"已删除 {len(target_blocks)} 个块：{block_range_label(target_blocks)}",
                "",
                "## 已删除内容",
                "",
                format_display_blocks(target_blocks),
                "",
                "## 当前上下文",
                "",
                "（删除位置的前一个块）",
                format_display_blocks(current_previous),
                "",
                "（删除位置现在的块，即原来被删除范围的后一个块）",
                format_display_blocks(current_next),
            ])
        elif action == "table_edit":
            updated_table = [
                block for block in new_display_blocks
                if block.id == target_blocks[0].id
            ]
            parts.extend([
                f"目标：{block_range_label(target_blocks)}",
                "",
                "## 原表格",
                "",
                format_display_block(target_blocks[0]),
                "",
                "## 新表格",
                "",
                format_display_blocks(updated_table),
            ])

        parts.extend([
            "",
            "如需回滚，可通过思源快照手动恢复。",
        ])
        return "\n".join(parts)

    def siyuan_doc_manage(self, args: dict[str, Any]) -> str:
        action = str(args.get("action") or "").strip().casefold()
        allowed_actions = {"rename", "move", "delete", "copy", "export"}
        if action not in allowed_actions:
            raise tool_error(_ERR_INVALID_ENUM, "action 只支持 rename、move、delete、copy、export。")

        doc = self.resolve_visible_document(args)
        doc_id = str(doc.get("id", ""))
        doc_path = display_document_path(doc)
        notebook_id = str(doc.get("notebook_id", ""))
        source_hpath = normalize_display_path(str(doc.get("hpath", "")))
        source_title = str(doc.get("title") or source_hpath.strip("/").split("/")[-1] or doc_id)
        docs = load_docs(self.root)
        privacy = load_privacy_rules(self.root)
        permission = document_permission(doc, privacy, docs)
        if permission == "hidden":
            raise tool_error(_ERR_DOC_NOT_FOUND, "未找到匹配的可见文档。文档可能已被隐藏、尚未索引，或定位符有误。")

        write_actions = {"rename", "move", "delete"}
        if action in write_actions and permission != "read_write":
            raise tool_error(_ERR_NOT_READ_WRITE, f"当前文档权限为 {permission}，不允许 {action}。")
        if action in write_actions | {"copy"} and not bool(args.get("confirmed")):
            raise tool_error(_ERR_NOT_CONFIRMED, f"action={action} 需要 confirmed=true。")

        _profile, client = detect_active_profile(load_config(self.root))

        if action == "export":
            with ensure_notebooks_open(client, [notebook_id]):
                markdown = client.export_markdown(doc_id)
            exports_dir = self.root / "ai_workspace" / "exports"
            exports_dir.mkdir(parents=True, exist_ok=True)
            safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", doc_path.strip("/") or doc_id)
            export_path = exports_dir / f"{safe_name}.md"
            export_path.write_text(markdown, encoding="utf-8")
            return "\n".join([
                "# 文档已导出",
                "",
                f"文档：{doc_path}（`{doc_id}`）",
                f"格式：Markdown",
                f"路径：{export_path.resolve()}",
            ])

        new_title = ""
        target_id = ""
        target_label = ""
        copy_target: CreateTarget | None = None
        copy_title = ""
        copy_parent_id = ""
        if action == "rename":
            new_title = str(args.get("new_title") or "").strip()
            if not new_title:
                raise tool_error(_ERR_MISSING_PARAM, "action=rename 需要 new_title。")
        elif action == "move":
            target_parent = str(args.get("target_parent") or "").strip()
            if not target_parent:
                raise tool_error(_ERR_MISSING_PARAM, "action=move 需要 target_parent，例如 /Notebook 或 /Notebook/Folder。")
            target_id, target_label = self.resolve_doc_manage_parent(target_parent)
            self._ensure_doc_manage_ancestors_writable(doc, privacy, docs, action="move")
            self._ensure_doc_manage_target_parent_writable(target_label, privacy, docs, action="move")
        elif action == "copy":
            target_path = str(args.get("target_path") or "").strip()
            if not target_path:
                raise tool_error(_ERR_MISSING_PARAM, "action=copy 需要 target_path，例如 /Notebook/Folder/New Doc。")
            copy_title = target_path.strip("/").split("/")[-1]
            if not copy_title:
                raise tool_error(_ERR_MISSING_PARAM, "复制目标标题为空。")
            notebooks = read_json(self.root / KNOWLEDGE_BASE_DIR / "notebooks.json")
            visible_docs = filter_documents(load_docs(self.root), privacy)
            copy_target = resolve_create_target({"path": target_path}, notebooks, visible_docs, copy_title)
            target_doc_for_permission = {
                "id": "",
                "notebook_id": copy_target.notebook_id,
                "notebook_name": copy_target.notebook_name,
                "hpath": copy_target.internal_path,
            }
            if document_permission(target_doc_for_permission, privacy, docs) != "read_write":
                raise tool_error(_ERR_NOT_READ_WRITE, "复制目标路径权限不是 read_write，不允许创建副本。")
            if copy_target.existing_docs:
                choices = "\n".join(f"- `{item.get('id', '')}` {display_document_path(item)}" for item in copy_target.existing_docs)
                raise tool_error(_ERR_ALREADY_EXISTS, "复制目标文档已存在，拒绝覆盖。\n" + choices)
            copy_parent = parent_display_path(copy_target.display_path)
            copy_parent_id, _copy_parent_label = self.resolve_doc_manage_parent(copy_parent)
        elif action == "delete":
            self._ensure_doc_manage_subtree_writable(client, doc, privacy, action="delete")

        snapshot_status = self._create_snapshot_or_raise(client, "siyuan_doc_manage", doc_path)
        sync_status: PostWriteSyncStatus | None = None
        try:
            operation_source_hpath = normalize_display_path(client.get_hpath_by_id(doc_id))
        except Exception:
            operation_source_hpath = source_hpath
        operation_source_title = operation_source_hpath.strip("/").split("/")[-1] or source_title

        if action == "rename":
            with ensure_notebooks_open(client, [notebook_id]):
                client.rename_doc_by_id(doc_id, new_title)
            result_line = f"已重命名为：{new_title}"
            parent_hpath = "/" + "/".join(operation_source_hpath.strip("/").split("/")[:-1]) if "/" in operation_source_hpath.strip("/") else ""
            expected_hpath = normalize_display_path(f"{parent_hpath}/{new_title}")
            sync_status = self._wait_for_hpath(client, doc_id, expected_hpath)

        elif action == "move":
            with ensure_notebooks_open(client, [notebook_id]):
                client.move_docs_by_id([doc_id], target_id)
            result_line = f"已移动到：{target_label}"
            target_parent_hpath = "/" + "/".join(target_label.strip("/").split("/")[1:])
            expected_hpath = normalize_display_path(f"{target_parent_hpath}/{operation_source_title}")
            sync_status = self._wait_for_hpath(client, doc_id, expected_hpath)

        elif action == "delete":
            with ensure_notebooks_open(client, [notebook_id]):
                client.remove_doc_by_id(doc_id)
            result_line = "已删除文档。可通过思源快照手动恢复。"
            sync_status = self._wait_for_deleted_doc(client, doc_id)

        elif action == "copy":
            assert copy_target is not None
            duplicated_id = ""
            with ensure_notebooks_open(client, [notebook_id, copy_target.notebook_id]):
                result = client.duplicate_doc(doc_id)
                duplicated_id = str(result.get("id") or result.get("docID") or result.get("doc_id") or "")
                if not duplicated_id:
                    raise tool_error(_ERR_DUPLICATE_NO_ID, "duplicateDoc 未返回新文档 ID，无法完成复制。")
                client.rename_doc_by_id(duplicated_id, copy_title)
                client.move_docs_by_id([duplicated_id], copy_parent_id)
            result_line = f"已复制到：{copy_target.display_path}（`{duplicated_id}`）"
            sync_status = self._wait_for_hpath(client, duplicated_id, copy_target.internal_path)

        try:
            client.push_msg(f"思源桥：文档管理已完成「{doc_path}」")
        except Exception:
            pass

        refresh_ok = False
        if action != "export":
            try:
                self._refresh_index_with_system_context(client)
                refresh_ok = True
            except Exception:
                pass

        parts = [
            "# 文档管理已完成",
            "",
            f"文档：{doc_path}（`{doc_id}`）",
            f"action：{action}",
            result_line,
            f"快照：{snapshot_status}",
        ]
        if sync_status is not None:
            parts.append(f"路径同步：{sync_status.detail}")
        if action != "export":
            parts.append("索引：已自动刷新" if refresh_ok else "索引：自动刷新失败，请手动运行 `siyuan_refresh_index`")
        if action == "delete":
            parts.append("如需回滚，可通过思源快照手动恢复。")
        return "\n".join(parts)

    def _ensure_doc_manage_subtree_writable(
        self,
        client: Any,
        doc: dict[str, Any],
        privacy: PrivacyRules,
        *,
        action: str,
    ) -> None:
        notebook_id = str(doc.get("notebook_id") or "")
        with ensure_notebooks_open(client, [notebook_id]):
            live_docs = load_live_docs(client)
        indexed = {str(item.get("id") or ""): item for item in live_docs}
        live_doc = indexed.get(str(doc.get("id") or ""), doc)
        subtree = document_subtree(live_doc, live_docs)
        blocked = [
            (item, document_permission(item, privacy, live_docs))
            for item in subtree
            if document_permission(item, privacy, live_docs) != "read_write"
        ]
        if blocked:
            raise tool_error(_ERR_SUBTREE_BLOCKED,
                "权限不足，子文档中存在只读或隐藏文档，不允许删除整个文档树。"
                "请让用户调整隐私规则后重试。"
            )

    def _ensure_doc_manage_ancestors_writable(
        self,
        doc: dict[str, Any],
        privacy: PrivacyRules,
        docs: list[dict[str, Any]],
        *,
        action: str,
    ) -> None:
        current = parent_display_path(display_document_path(doc))
        while current:
            matches = [item for item in docs if display_document_path(item).casefold() == current.casefold()]
            if matches:
                permission = document_permission(matches[0], privacy, docs)
                if permission != "read_write":
                    raise tool_error(_ERR_ANCESTOR_BLOCKED,
                        f"权限不足，该文档的祖先路径权限不是 read_write，不允许 {action}。"
                        "请让用户调整隐私规则后重试。"
                    )
            next_parent = parent_display_path(current)
            if next_parent == current:
                break
            current = next_parent

    def _ensure_doc_manage_target_parent_writable(
        self,
        target_label: str,
        privacy: PrivacyRules,
        docs: list[dict[str, Any]],
        *,
        action: str,
    ) -> None:
        path = normalize_display_path(target_label)
        notebooks = read_json(self.root / KNOWLEDGE_BASE_DIR / "notebooks.json")
        notebook = next(
            (nb for nb in notebooks if normalize_display_path(str(nb.get("name", ""))).casefold() == path.casefold()),
            None,
        )
        if notebook is not None:
            probe = {
                "id": "",
                "notebook_id": str(notebook.get("id", "")),
                "notebook_name": str(notebook.get("name", "")),
                "hpath": "/__siyuan_bridge_permission_probe__",
            }
            permission = document_permission(probe, privacy, docs)
        else:
            matches = [doc for doc in docs if display_document_path(doc).casefold() == path.casefold()]
            permission = document_permission(matches[0], privacy, docs) if len(matches) == 1 else "hidden"
        if permission != "read_write":
            raise tool_error(_ERR_NOT_READ_WRITE, f"action={action} 的目标父路径权限为 {permission}，不允许写入。")

    def resolve_doc_manage_parent(self, target_parent: str) -> tuple[str, str]:
        path = normalize_display_path(target_parent)
        if not path:
            raise tool_error(_ERR_MISSING_PARAM, "target_parent 不能为空。")
        docs = filter_documents(load_docs(self.root), load_privacy_rules(self.root))
        notebooks = read_json(self.root / KNOWLEDGE_BASE_DIR / "notebooks.json")
        notebook = next(
            (nb for nb in notebooks if normalize_display_path(str(nb.get("name", ""))).casefold() == path.casefold()),
            None,
        )
        if notebook is not None:
            return str(notebook.get("id", "")), normalize_display_path(str(notebook.get("name", "")))
        matches = [
            doc for doc in docs
            if display_document_path(doc).casefold() == path.casefold()
        ]
        if len(matches) == 1:
            return str(matches[0].get("id", "")), display_document_path(matches[0])
        if len(matches) > 1:
            choices = "\n".join(f"- `{doc.get('id')}` {display_document_path(doc)}" for doc in matches)
            raise tool_error(_ERR_AMBIGUOUS, f"target_parent 存在歧义：\n{choices}")
        raise tool_error(_ERR_PARENT_NOT_FOUND, f"未找到可见 target_parent：{path}")

    def resolve_notebook_id(self, notebook_name: str) -> str:
        notebooks = read_json(self.root / KNOWLEDGE_BASE_DIR / "notebooks.json")
        exact = [item for item in notebooks if str(item.get("name", "")).casefold() == notebook_name.casefold()]
        if len(exact) == 1:
            return str(exact[0]["id"])
        partial = [item for item in notebooks if notebook_name.casefold() in str(item.get("name", "")).casefold()]
        if len(partial) == 1:
            return str(partial[0]["id"])
        if len(exact) + len(partial) > 1:
            raise tool_error(_ERR_AMBIGUOUS, "笔记本名称存在歧义，请使用 notebook_id")
        raise tool_error(_ERR_NB_NOT_FOUND, f"未匹配到可见笔记本：{notebook_name}")

    def siyuan_bridge_feedback(self, args: dict[str, Any]) -> str:
        """Submit feedback to the SiYuan Bridge developer."""
        feedback_type = str(args.get("type", "")).strip()
        if feedback_type not in ("bug", "feature", "idea"):
            raise tool_error(_ERR_INVALID_ENUM, "type must be one of: bug, feature, idea")
        title = str(args.get("title", "")).strip()
        if not title:
            raise tool_error(_ERR_MISSING_PARAM, "title is required")
        description = str(args.get("description", "")).strip()
        if not description:
            raise tool_error(_ERR_MISSING_PARAM, "description is required")
        contact = str(args.get("contact", "")).strip() or None

        endpoint = get_effective_endpoint(self.root)
        proxy = _resolve_proxy(self.root)
        payload: dict[str, str] = {
            "type": feedback_type,
            "title": title,
            "description": description,
        }
        if contact:
            payload["contact"] = contact

        success = _telemetry_submit_feedback(endpoint, proxy, payload)
        if success:
            return "反馈已提交，感谢你的反馈！"
        else:
            return (
                "反馈提交失败，无法连接到反馈端点。请检查 telemetry_endpoint 配置是否正确、"
                "本地代理是否已开启，或稍后重试。你也可以通过 GitHub Issues 提交反馈。"
            )


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
            "description": "Refresh the safe index, ensure the system notebook 思源桥 and its fixed documents, and return the mandatory startup packet: notebook overview table, Workspace Index (if it exists — an AI-generated semantic navigation map), and AI Guide (user preferences and rules). Always call this first — it ensures the index is up to date.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "siyuan_refresh_index",
            "description": "Explicitly refresh the safe SiYuan index when the user asks or the index is missing/stale.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "siyuan_list",
            "description": "List visible notebooks or one level of visible documents. No arguments lists notebooks. Provide path=/Notebook or /Notebook/Folder to list only direct child documents at that path. Each row returns effective permission (read_write/read_only), a full readable document path for siyuan_read/siyuan_edit, plus document_id fallback, word count, block count, update date, and descendant document count. Hidden items are not listed. Results are paginated with offset/limit. notebook_id/notebook_name are compatibility shortcuts for path=/Notebook.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Readable path to list one level under, e.g. /Notebook or /Notebook/Folder. Omit to list all notebooks."},
                    "limit": {"type": "integer", "default": 100, "description": "Maximum direct children to return, 1-500."},
                    "offset": {"type": "integer", "default": 0, "description": "Pagination offset within the direct children of path."},
                    "notebook_id": {"type": "string", "description": "Compatibility shortcut. Lists the root level of this notebook."},
                    "notebook_name": {"type": "string", "description": "Compatibility shortcut. Lists the root level of this notebook."},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "siyuan_find",
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
            "name": "siyuan_read",
            "description": "Read a visible SiYuan document as Markdown. Prefer document path including notebook name, e.g. /Notebook/Folder/Doc; use document_id only as fallback. Always returns the document outline and one complete block window. Set include_block_ids=true before any siyuan_edit call to get exact [index] id type targets. Normal reading keeps Markdown clean and hides block IDs.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "document": {"type": "string", "description": "Document path including notebook name, e.g. /Notebook/Folder/Doc. Preferred for reading and editing workflows."},
                    "document_id": {"type": "string", "description": "Document id fallback when path is ambiguous or unavailable."},
                    "block_start": {"type": "integer", "default": 1, "description": "Starting display block index (1-based). Default 1 reads from the first block."},
                    "block_limit": {"type": "integer", "default": DEFAULT_BLOCK_LIMIT, "description": "Maximum display blocks to return in this window, 1–1000."},
                    "token_budget": {"type": "integer", "default": DEFAULT_TOKEN_BUDGET, "description": "Estimated token ceiling for this window. Blocks stop before exceeding budget (at least one block always returned)."},
                    "include_block_ids": {"type": "boolean", "default": False, "description": "Enable reference reading for editing: each block is shown as [index] id=... type=... followed by content. Use these exact values for siyuan_edit start_index/start_id."},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "siyuan_create",
            "description": "Create or write a SiYuan document. Prefer path as the full readable path including notebook name, e.g. /Notebook/Folder/Doc; the server resolves the notebook ID and internal hpath. If the notebook name is ambiguous, use notebook_id plus an internal path like /Folder/Doc. Creates a SiYuan workspace snapshot before writing. After writing, waits for SiYuan to expose the target path and refreshes the safe index. Existing target behavior is controlled by if_exists: reject refuses by default, overwrite clears all blocks in the existing document and rewrites it while preserving the document ID, create_new asks SiYuan to create another same-name document.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "notebook_id": {"type": "string", "description": "Optional notebook ID. Required only when path is an internal notebook path or when the notebook name in a full path is ambiguous."},
                    "title": {"type": "string", "description": "Document title."},
                    "path": {"type": "string", "description": "Preferred: full readable path /Notebook/Folder/Doc. With notebook_id, legacy internal path /Folder/Doc is also accepted. If omitted, notebook_id is required and path defaults to /<title> inside that notebook."},
                    "markdown": {"type": "string", "description": "Markdown content to write."},
                    "if_exists": {"type": "string", "enum": ["reject", "overwrite", "create_new"], "default": "reject", "description": "Behavior when the target path already exists. reject refuses and explains options. overwrite clears all existing blocks and appends markdown, preserving document ID. create_new creates another same-name document."},
                    "confirmed": {"type": "boolean", "description": "Must be true. Writing to SiYuan requires explicit user approval."},
                },
                "required": ["title", "markdown", "confirmed"],
                "additionalProperties": False,
            },
        },
        {
            "name": "siyuan_edit",
            "description": "Edit a visible SiYuan document by document path plus reference-read block index and block ID. Requires confirmed=true and creates a SiYuan workspace snapshot before writing. Use siyuan_read(include_block_ids=true) first to get start_index/start_id. Actions: single_block_replace = one existing block -> one block, uses updateBlock, preserves the target block ID and block attrs, so existing block references stay valid. multi_block_replace = one or more existing blocks -> one or more new blocks, inserts new markdown then deletes old blocks, so old block IDs/attrs are not preserved and references to old blocks become invalid. Use multi_block_replace whenever block count may change. insert_after/insert_before do not modify the anchor block. append adds to document end. delete removes blocks. table_edit edits one normal Markdown table block.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "document": {"type": "string", "description": "Document path including notebook name, e.g. /Notebook/Folder/Doc. If ambiguous, use document_id instead."},
                    "document_id": {"type": "string", "description": "Optional document id fallback when document path is ambiguous."},
                    "action": {"type": "string", "enum": ["single_block_replace", "multi_block_replace", "insert_after", "insert_before", "append", "delete", "table_edit"], "description": "Choose single_block_replace only when replacing exactly one block with exactly one block and preserving its block ID matters. Choose multi_block_replace when replacing a range or when the new markdown may create multiple blocks; old block IDs and references will be invalidated."},
                    "start_index": {"type": "integer", "description": "Global display block index from reference reading. Required except append."},
                    "start_id": {"type": "string", "description": "Block ID from reference reading. Required except append."},
                    "end_index": {"type": "integer", "description": "Inclusive global display block index for multi_block_replace/delete range operations."},
                    "end_id": {"type": "string", "description": "Inclusive end block ID for multi_block_replace/delete range operations."},
                    "markdown": {"type": "string", "description": "Markdown to insert or replace with. For single_block_replace this must render as exactly one display block. For multi_block_replace it may render as one or more new blocks."},
                    "table_edit": {
                        "type": "object",
                        "description": "Required for action=table_edit on a normal Markdown table block. Use the table coordinate view from siyuan_read(include_block_ids=true): row=0 is header, row>=1 are data rows, column_index is 1-based.",
                        "properties": {
                            "operation": {"type": "string", "enum": ["set_cell", "insert_row", "delete_row", "insert_column", "delete_column", "insert_row_before", "insert_row_after"], "description": "Prefer set_cell, insert_row, delete_row, insert_column, delete_column. insert_row_before/insert_row_after are legacy aliases."},
                            "cell": {"type": "object", "description": "Single cell edit for operation=set_cell. Fields: row, column_index or column, value, optional expected_old_value."},
                            "cells": {"type": "array", "description": "Multiple cell edits for operation=set_cell. Each item has row, column_index or column, value, optional expected_old_value."},
                            "row": {"type": "integer", "description": "Table row coordinate. row=0 is header; row>=1 are data rows. delete_row cannot delete row=0."},
                            "column": {"type": "string", "description": "Legacy column name fallback. Prefer column_index from the reference-reading coordinate view."},
                            "column_index": {"type": "integer", "description": "1-based column number from the reference-reading coordinate view."},
                            "position": {"type": "string", "enum": ["before", "after"], "description": "Required for insert_row and insert_column."},
                            "value": {"type": "string", "description": "Legacy single-cell value for set_cell when not using cell/cells."},
                            "values": {"description": "For insert_row: row values as object keyed by header or array in column order. For insert_column: array where values[0] is header and the rest are data rows."},
                            "expected_old_value": {"type": "string", "description": "Optional old cell value guard for legacy top-level set_cell."},
                        },
                        "additionalProperties": False,
                    },
                    "confirmed": {"type": "boolean", "description": "Must be true. Editing SiYuan documents requires explicit user approval."},
                },
                "required": ["action", "confirmed"],
                "additionalProperties": False,
            },
        },
        {
            "name": "siyuan_doc_manage",
            "description": "Manage visible SiYuan documents at the document-tree level, not document body editing. Actions: rename, move, delete, copy, export. copy/export are allowed for readable documents. rename/move/delete require read_write permission, confirmed=true, and create a SiYuan workspace snapshot before writing. delete affects the whole subtree and is rejected if any descendant is not read_write. move preserves the moved subtree but is rejected if the source document inherits restrictions from any non-read_write ancestor or if the target parent is not read_write. copy uses SiYuan duplicateDoc for the source document only, requires target_path and confirmed=true, then renames/moves the duplicate. After rename/move/delete/copy, waits for SiYuan path sync and refreshes the safe index. export writes Markdown to ai_workspace/exports and does not modify SiYuan.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "document": {"type": "string", "description": "Document path including notebook name, e.g. /Notebook/Folder/Doc. Preferred."},
                    "document_id": {"type": "string", "description": "Document id fallback when path is ambiguous or unavailable."},
                    "action": {"type": "string", "enum": ["rename", "move", "delete", "copy", "export"], "description": "Document management action."},
                    "new_title": {"type": "string", "description": "Required for action=rename."},
                    "target_parent": {"type": "string", "description": "Required for action=move. Visible target notebook or parent document path, e.g. /Notebook or /Notebook/Folder."},
                    "target_path": {"type": "string", "description": "Required for action=copy. Full readable target path /Notebook/Folder/New Doc. The target path must not already exist and must be read_write."},
                    "confirmed": {"type": "boolean", "description": "Required for rename/move/delete/copy. Not required for export."},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
        {
            "name": "siyuan_bridge_feedback",
            "description": "Submit feedback about SiYuan Bridge directly through the AI conversation. Use this to report bugs, request features, or share ideas. This does NOT modify SiYuan notes, does NOT require confirmed=true, and works even when SiYuan is not running (as long as a telemetry endpoint is configured). The feedback is sent to the SiYuan Bridge developer.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["bug", "feature", "idea"],
                        "description": "Feedback type: bug = problem report, feature = feature request, idea = suggestion or general idea.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Short summary of the feedback (required).",
                    },
                    "description": {
                        "type": "string",
                        "description": "Detailed description of the issue, request, or idea (required).",
                    },
                    "contact": {
                        "type": "string",
                        "description": "Optional contact information (email, GitHub handle, etc.) for follow-up.",
                    },
                },
                "required": ["type", "title", "description"],
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


def attachment_root_dir(workspace_root: Path, doc_id: str) -> Path:
    return workspace_root / "ai_workspace" / "attachments" / doc_id


def rewrite_local_asset_links(markdown: str, doc_id: str, workspace_root: Path) -> str:
    """Rewrite SiYuan-relative asset links to extracted absolute local paths."""
    assets_dir = attachment_root_dir(workspace_root, doc_id) / "assets"

    def replace(match: re.Match[str]) -> str:
        filename = match.group(1)
        return f"]({(assets_dir / filename).resolve().as_posix()})"

    return re.sub(r"\]\(assets/([^)]+)\)", replace, markdown)


def extract_attachments(markdown: str, client: SiYuanClient, doc_id: str, workspace_root: Path) -> int:
    """Extract all assets (images, PDF, etc.) referenced in markdown to ai_workspace/attachments/<doc_id>/.
    Preserves the original assets/ directory structure. Returns count of successfully extracted files."""
    assets = re.findall(r"\]\(assets/([^)]+)\)", markdown)
    if not assets:
        return 0

    dest_dir = attachment_root_dir(workspace_root, doc_id) / "assets"
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
