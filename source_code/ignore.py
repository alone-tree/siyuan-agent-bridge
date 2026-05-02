from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


IGNORE_FILE = "siyuan.ignore.local.json"
IGNORE_EXAMPLE_FILE = "siyuan.ignore.example.json"
ALLOW_FILE = "siyuan.allow.local.json"


IGNORE_TEMPLATE = {
    "ignore": [
        {
            "scope": "notebook",
            "id": "notebook-id-to-hide",
            "reason": "Hide an entire notebook from generated indexes.",
        },
        {
            "scope": "document",
            "id": "document-id-to-hide",
            "reason": "Hide this document and all child documents under it.",
        },
        {
            "scope": "subtree",
            "id": "root-document-id-to-hide-with-children",
            "reason": "Hide this document and all child documents under it.",
        },
        {
            "scope": "subtree",
            "notebook_id": "notebook-id",
            "hpath": "/Private/Path",
            "reason": "Hide a document path and all child documents under it.",
        },
    ]
}


@dataclass(frozen=True)
class PrivacyRules:
    ignore: list[dict[str, Any]]
    allow: list[dict[str, Any]]


def load_privacy_rules(root: Path, *, include_temporary: bool = True) -> PrivacyRules:
    ignore_data = _read_json(root / IGNORE_FILE)
    ignore_rules = _coerce_rules(ignore_data.get("ignore", []))
    allow_rules: list[dict[str, Any]] = []
    if include_temporary:
        allow_data = _read_json(root / ALLOW_FILE)
        allow_rules = [rule for rule in _coerce_rules(allow_data.get("temporary_allow", [])) if is_active(rule)]
    return PrivacyRules(ignore=ignore_rules, allow=allow_rules)


def initialize_ignore_files(root: Path) -> tuple[bool, Path, Path]:
    example_path = root / IGNORE_EXAMPLE_FILE
    local_path = root / IGNORE_FILE
    created_local = False
    if not example_path.exists():
        _write_json(example_path, IGNORE_TEMPLATE)
    if not local_path.exists():
        _write_json(local_path, {"ignore": []})
        created_local = True
    return created_local, local_path, example_path


def load_temporary_allow(root: Path) -> list[dict[str, Any]]:
    data = _read_json(root / ALLOW_FILE)
    return _coerce_rules(data.get("temporary_allow", []))


def load_persistent_ignore(root: Path) -> list[dict[str, Any]]:
    data = _read_json(root / IGNORE_FILE)
    return _coerce_rules(data.get("ignore", []))


def write_persistent_ignore(root: Path, rules: Iterable[dict[str, Any]]) -> None:
    _write_json(root / IGNORE_FILE, {"ignore": list(rules)})


def add_persistent_ignore(root: Path, rule: dict[str, Any]) -> bool:
    existing = load_persistent_ignore(root)
    if any(rules_equivalent(item, rule) for item in existing):
        return False
    existing.append(rule)
    write_persistent_ignore(root, existing)
    return True


def remove_persistent_ignore(root: Path, target: dict[str, Any]) -> int:
    existing = load_persistent_ignore(root)
    kept = [rule for rule in existing if not rules_equivalent(rule, target)]
    removed = len(existing) - len(kept)
    if removed:
        write_persistent_ignore(root, kept)
    return removed


def write_temporary_allow(root: Path, rules: Iterable[dict[str, Any]]) -> None:
    active_or_future = [rule for rule in rules if is_active(rule)]
    _write_json(root / ALLOW_FILE, {"temporary_allow": active_or_future})


def close_temporary_allow(root: Path) -> int:
    existing = load_temporary_allow(root)
    if (root / ALLOW_FILE).exists():
        _write_json(root / ALLOW_FILE, {"temporary_allow": []})
    return len(existing)


def make_temporary_allow(
    scope: str,
    locator: str,
    *,
    minutes: int,
    reason: str = "",
    resolved: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    rule: dict[str, Any] = {
        "scope": scope,
        "expires_at": (now + timedelta(minutes=minutes)).isoformat(),
    }
    if reason:
        rule["reason"] = reason
    if resolved:
        rule.update(
            {
                key: value
                for key, value in {
                    "id": resolved.get("id"),
                    "notebook_id": resolved.get("notebook_id"),
                    "notebook_name": resolved.get("notebook_name"),
                    "hpath": resolved.get("hpath"),
                    "title": resolved.get("title"),
                }.items()
                if value
            }
        )
    else:
        if locator.startswith("/"):
            rule["hpath"] = locator
        else:
            rule["id"] = locator
    return rule


def make_privacy_rule(
    scope: str,
    locator: str,
    *,
    reason: str = "",
    resolved: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rule: dict[str, Any] = {"scope": scope}
    if reason:
        rule["reason"] = reason
    if resolved:
        if scope == "notebook":
            rule.update(
                {
                    key: value
                    for key, value in {
                        "id": resolved.get("notebook_id") or resolved.get("id"),
                        "name": resolved.get("notebook_name") or resolved.get("title"),
                    }.items()
                    if value
                }
            )
        else:
            rule.update(
                {
                    key: value
                    for key, value in {
                        "id": resolved.get("id"),
                        "notebook_id": resolved.get("notebook_id"),
                        "notebook_name": resolved.get("notebook_name"),
                        "hpath": resolved.get("hpath"),
                        "title": resolved.get("title"),
                    }.items()
                    if value
                }
            )
    else:
        if locator.startswith("/"):
            rule["hpath"] = locator
        else:
            rule["id"] = locator
    return rule


def rules_equivalent(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if _equivalent_scope(_scope(left)) != _equivalent_scope(_scope(right)):
        return False
    scope = _equivalent_scope(_scope(left))
    if scope == "notebook":
        left_id = str(left.get("id") or left.get("notebook_id") or "")
        right_id = str(right.get("id") or right.get("notebook_id") or "")
        left_name = str(left.get("name") or left.get("notebook_name") or "")
        right_name = str(right.get("name") or right.get("notebook_name") or "")
        return bool((left_id and right_id and left_id == right_id) or (left_name and right_name and left_name == right_name))
    left_id = str(left.get("id") or "")
    right_id = str(right.get("id") or "")
    if left_id and right_id and left_id == right_id:
        return True
    left_path = _normalize_hpath(left.get("hpath"))
    right_path = _normalize_hpath(right.get("hpath"))
    left_box = str(left.get("notebook_id") or "")
    right_box = str(right.get("notebook_id") or "")
    if left_path and right_path and left_path == right_path:
        return not left_box or not right_box or left_box == right_box
    return False


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


def compile_rules(rules: Iterable[dict[str, Any]], docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
    return bool((rule_id and rule_id == notebook_id) or (rule_name and rule_name == notebook_name))


def rule_matches_doc(rule: dict[str, Any], doc: dict[str, Any]) -> bool:
    scope = _scope(rule)
    if scope == "notebook":
        notebook = {"id": doc.get("notebook_id"), "name": doc.get("notebook_name")}
        return rule_matches_notebook(rule, notebook)
    if scope == "document":
        return _matches_subtree(rule, doc)
    if scope == "subtree":
        return _matches_subtree(rule, doc)
    return False


def is_active(rule: dict[str, Any]) -> bool:
    expires_at = str(rule.get("expires_at") or "").strip()
    if not expires_at:
        return True
    try:
        expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > datetime.now(timezone.utc)


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


def _equivalent_scope(scope: str) -> str:
    return "document" if scope == "subtree" else scope


def _normalize_hpath(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return "/" + text.strip("/")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _coerce_rules(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    if not isinstance(value, list):
        raise ValueError("ignore and temporary_allow must be lists")
    return [item for item in value if isinstance(item, dict)]
