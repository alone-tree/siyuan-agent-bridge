from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class PrivacyRules:
    ignore: list[dict[str, Any]]
    allow: list[dict[str, Any]]


# ── Privacy Rules cache ────────────────────────────────────────────────

def load_privacy_rules(root: Path) -> PrivacyRules:
    """Load privacy rules from the cached knowledge_base/privacy_rules.json.

    This cache is written by refresh_index / siyuan_start after parsing the
    Privacy Rules document in the SiYuan system notebook.
    """
    path = root / "knowledge_base" / "privacy_rules.json"
    if not path.exists():
        return PrivacyRules(ignore=[], allow=[])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ignore = [r for r in data.get("ignore", []) if isinstance(r, dict)]
        return PrivacyRules(ignore=ignore, allow=[])
    except (json.JSONDecodeError, OSError):
        return PrivacyRules(ignore=[], allow=[])


def write_privacy_rules_cache(root: Path, rules: PrivacyRules) -> None:
    """Write parsed privacy rules to the cache file."""
    cache_dir = root / "knowledge_base"
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {"ignore": rules.ignore, "allow": rules.allow}
    cache_dir.joinpath("privacy_rules.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


# ── Markdown table parsing ─────────────────────────────────────────────

SECTION_HEADERS = {
    "notebook": re.compile(
        r"^##\s+隐藏笔记本\s*$|^##\s+Hide\s+Notebooks\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    "document": re.compile(
        r"^##\s+隐藏文档\s*$|^##\s+Hide\s+Documents\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
}

ACTIVE_ALIASES: dict[str, list[str]] = {
    "notebook": [
        "Hide", "Enabled",
        "对AI隐藏？", "对 AI 隐藏？",
        "Hide from AI?",
    ],
    "document": [
        "Hide", "Enabled",
        "对AI隐藏？", "对 AI 隐藏？",
        "Hide from AI?",
    ],
}

ID_ALIASES: dict[str, list[str]] = {
    "notebook": [
        "笔记本ID（建议填）", "笔记本 ID（建议填）",
        "笔记本ID（优先）", "笔记本 ID（优先）",
        "Notebook ID (preferred)", "Notebook ID",
    ],
    "document": [
        "文档ID（必填，不填会报错）", "文档 ID（必填，不填会报错）",
        "文档ID（必填）", "文档 ID（必填）",
        "Document ID (required)", "Document ID",
    ],
}

NAME_ALIASES: dict[str, list[str]] = {
    "notebook": ["笔记本名称", "Notebook Name"],
    "document": ["标题（仅供确认）", "标题", "Title (for confirmation only)", "Title"],
}

REASON_ALIASES: dict[str, list[str]] = {
    "notebook": ["备注（可选）", "备注", "Note (optional)", "Reason"],
    "document": ["备注（可选）", "备注", "Note (optional)", "Reason"],
}

ACTIVE_VALUES = frozenset({"是", "yes", "true", "1"})
INACTIVE_VALUES = frozenset({"否", "no", "false", "0", ""})


class PrivacyRulesParseError(ValueError):
    pass


def parse_privacy_rules_markdown(
    markdown: str,
    *,
    all_notebooks: list[dict[str, Any]] | None = None,
    all_docs: list[dict[str, Any]] | None = None,
) -> PrivacyRules:
    """Parse the Privacy Rules markdown document into a PrivacyRules object.

    Raises PrivacyRulesParseError with human-locatable error messages if parsing fails.
    Error messages do NOT expose specific hidden notebook names, document IDs, or titles.
    """
    errors: list[str] = []
    ignore_rules: list[dict[str, Any]] = []

    # Parse notebook section
    notebook_rules, notebook_errors = _parse_section(
        markdown, "notebook", all_notebooks
    )
    ignore_rules.extend(notebook_rules)
    errors.extend(notebook_errors)

    # Parse document section
    doc_rules, doc_errors = _parse_section(
        markdown, "document", all_docs
    )
    ignore_rules.extend(doc_rules)
    errors.extend(doc_errors)

    if errors:
        raise PrivacyRulesParseError("\n".join(errors))

    return PrivacyRules(ignore=ignore_rules, allow=[])


def _parse_section(
    markdown: str,
    section_type: str,
    reference_list: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse one section (notebook or document) of the Privacy Rules.

    Returns (rules, errors).
    """
    errors: list[str] = []
    section_label = "隐藏笔记本" if section_type == "notebook" else "隐藏文档"
    section_label_en = "Hide Notebooks" if section_type == "notebook" else "Hide Documents"

    # Find the section heading
    pattern = SECTION_HEADERS[section_type]
    heading_match = pattern.search(markdown)
    if heading_match is None:
        # Section missing — OK if there are no rules for it
        return [], []

    # Extract content after this heading until next ## heading or end
    start = heading_match.end()
    next_heading = re.search(r"^##\s+", markdown[start:], re.MULTILINE)
    if next_heading:
        section_text = markdown[start:start + next_heading.start()]
    else:
        section_text = markdown[start:]

    # Find the first markdown table in this section
    table_match = re.search(r"^\|.+\|[\s\S]*?(?=\n\n|\n##|\Z)", section_text, re.MULTILINE)
    if not table_match:
        return [], []

    table_text = table_match.group(0).strip()
    lines = [line.strip() for line in table_text.splitlines() if line.strip() and "|" in line]
    if len(lines) < 2:
        return [], []

    # Parse header row
    header_cells = _parse_table_row(lines[0])
    separator_row = lines[1]

    # Map column indices
    active_col = _find_column(header_cells, ACTIVE_ALIASES[section_type])
    id_col = _find_column(header_cells, ID_ALIASES[section_type])
    name_col = _find_column(header_cells, NAME_ALIASES[section_type])
    reason_col = _find_column(header_cells, REASON_ALIASES[section_type])

    # Validate header
    if active_col < 0:
        errors.append(
            f"{section_label_en} 表头缺少 Hide/Enabled 列。"
            f"请确保表头包含 Hide 或 Enabled 列。"
        )
        return [], errors

    if section_type == "document" and id_col < 0:
        errors.append(
            f"{section_label_en} 表头缺少 Document ID 列。"
            f"请确保表头包含 Document ID 列。"
        )
        return [], errors

    # Build reference lookup
    ref_by_id: dict[str, dict[str, Any]] = {}
    ref_by_name: dict[str, list[dict[str, Any]]] = {}
    if reference_list:
        for item in reference_list:
            item_id = str(item.get("id", ""))
            if item_id:
                ref_by_id[item_id] = item
            item_name = str(item.get("name", "") or item.get("title", ""))
            if item_name:
                ref_by_name.setdefault(item_name.casefold(), []).append(item)

    # Parse data rows (skip header and separator)
    rules: list[dict[str, Any]] = []
    for row_idx, line in enumerate(lines[2:], start=3):  # 1-based, header=1, sep=2
        cells = _parse_table_row(line)

        active_raw = _get_cell(cells, active_col)
        # Check valid active value
        active_clean = active_raw.strip().casefold()
        if active_clean in INACTIVE_VALUES:
            continue  # Rule not active
        if active_clean not in ACTIVE_VALUES:
            errors.append(
                f"{section_label_en} 第 {row_idx} 行：Hide 只能填写 yes/no。"
            )
            continue

        rule: dict[str, Any] = {"scope": section_type}

        # Parse ID and validate
        raw_id = _get_cell(cells, id_col) if id_col >= 0 else ""
        rule_id = raw_id.strip()

        if section_type == "document":
            if not rule_id:
                errors.append(
                    f"{section_label_en} 第 {row_idx} 行：Document ID 为空。"
                )
                continue
            # Validate document ID exists
            if ref_by_id and rule_id not in ref_by_id:
                errors.append(
                    f"{section_label_en} 第 {row_idx} 行：Document ID 不存在或不可访问。"
                )
                continue
            rule["id"] = rule_id

        elif section_type == "notebook":
            if rule_id:
                # Validate notebook ID exists
                if ref_by_id and rule_id not in ref_by_id:
                    errors.append(
                        f"{section_label_en} 第 {row_idx} 行：Notebook ID 不存在或不可访问。"
                    )
                    continue
                rule["id"] = rule_id
            else:
                # Try notebook name
                raw_name = _get_cell(cells, name_col) if name_col >= 0 else ""
                rule_name = raw_name.strip()
                if not rule_name:
                    errors.append(
                        f"{section_label_en} 第 {row_idx} 行：Notebook ID 和名称都为空。"
                    )
                    continue
                matched = ref_by_name.get(rule_name.casefold(), []) if ref_by_name else []
                if not matched and ref_by_name:
                    errors.append(
                        f"{section_label_en} 第 {row_idx} 行：笔记本名称未匹配到任何笔记本。"
                    )
                    continue
                # If multiple notebooks share the name, hide all
                rule["name"] = rule_name

        rules.append(rule)

    return rules, errors


def _parse_table_row(line: str) -> list[str]:
    """Parse a markdown table row into cells, stripping whitespace."""
    # Remove leading/trailing pipe
    text = line.strip().strip("|")
    return [cell.strip() for cell in text.split("|")]


def _get_cell(cells: list[str], index: int) -> str:
    if 0 <= index < len(cells):
        return cells[index].strip()
    return ""


def _find_column(headers: list[str], aliases: list[str]) -> int:
    """Find the index of a column matching one of the aliases.

    Uses case-insensitive matching and normalizes whitespace variations.
    """
    def _normalize(text: str) -> str:
        # Remove all whitespace for comparison
        return re.sub(r"\s+", "", text).casefold()

    norm_aliases = [_normalize(a) for a in aliases]
    for i, header in enumerate(headers):
        norm_header = _normalize(header)
        if norm_header in norm_aliases:
            return i
    return -1


# ── Filter functions ───────────────────────────────────────────────────

def filter_notebooks(
    notebooks: Iterable[dict[str, Any]],
    rules: PrivacyRules,
) -> list[dict[str, Any]]:
    return [notebook for notebook in notebooks if is_notebook_visible(notebook, rules)]


def filter_documents(
    docs: Iterable[dict[str, Any]],
    rules: PrivacyRules,
) -> list[dict[str, Any]]:
    doc_list = list(docs)
    compiled_ignore = compile_rules(rules.ignore, doc_list)
    compiled_allow = compile_rules(rules.allow, doc_list)
    visible = []
    for doc in doc_list:
        ignored = any(rule_matches_doc(rule, doc) for rule in compiled_ignore)
        allowed = any(rule_matches_doc(rule, doc) for rule in compiled_allow)
        if not ignored or allowed:
            visible.append(doc)
    return visible


def is_notebook_visible(notebook: dict[str, Any], rules: PrivacyRules) -> bool:
    ignored = any(rule_matches_notebook(rule, notebook) for rule in rules.ignore)
    allowed = any(rule_matches_notebook(rule, notebook) for rule in rules.allow)
    return not ignored or allowed


def compile_rules(
    rules: Iterable[dict[str, Any]], docs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_id = {str(doc.get("id", "")): doc for doc in docs}
    compiled = []
    for rule in rules:
        normalized = dict(rule)
        scope = _scope(normalized)
        if scope in ("document", "subtree") and normalized.get("id") and not normalized.get("hpath"):
            root = by_id.get(str(normalized["id"]))
            if root:
                normalized["notebook_id"] = root.get("notebook_id")
                normalized["hpath"] = root.get("hpath")
        compiled.append(normalized)
    return compiled


def rule_matches_notebook(rule: dict[str, Any], notebook: dict[str, Any]) -> bool:
    if _scope(rule) != "notebook":
        return False
    rule_id = str(rule.get("id") or rule.get("notebook_id") or "")
    rule_name = str(rule.get("name") or rule.get("notebook_name") or "")
    notebook_id = str(notebook.get("id") or "")
    notebook_name = str(notebook.get("name") or "")
    return bool(
        (rule_id and rule_id == notebook_id)
        or (rule_name and rule_name.casefold() == notebook_name.casefold())
    )


def rule_matches_doc(rule: dict[str, Any], doc: dict[str, Any]) -> bool:
    scope = _scope(rule)
    if scope == "notebook":
        notebook = {"id": doc.get("notebook_id"), "name": doc.get("notebook_name")}
        return rule_matches_notebook(rule, notebook)
    if scope in ("document", "subtree"):
        return _matches_subtree(rule, doc)
    return False


# ── Internal helpers ────────────────────────────────────────────────────

def _matches_document_identity(rule: dict[str, Any], doc: dict[str, Any]) -> bool:
    rule_id = str(rule.get("id") or "")
    if rule_id and rule_id == str(doc.get("id") or ""):
        return True
    rule_hpath = _normalize_hpath(rule.get("hpath"))
    doc_hpath = _normalize_hpath(doc.get("hpath"))
    if rule_hpath and rule_hpath == doc_hpath:
        notebook_id = str(rule.get("notebook_id") or "")
        return not notebook_id or notebook_id == str(doc.get("notebook_id") or "")
    return False


def _matches_subtree(rule: dict[str, Any], doc: dict[str, Any]) -> bool:
    if _matches_document_identity(rule, doc):
        return True
    root_hpath = _normalize_hpath(rule.get("hpath"))
    doc_hpath = _normalize_hpath(doc.get("hpath"))
    if not root_hpath or not doc_hpath.startswith(root_hpath + "/"):
        return False
    notebook_id = str(rule.get("notebook_id") or "")
    return not notebook_id or notebook_id == str(doc.get("notebook_id") or "")


def _scope(rule: dict[str, Any]) -> str:
    return str(rule.get("scope") or rule.get("type") or "").strip().casefold()


def _normalize_hpath(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return "/" + text.strip("/")
