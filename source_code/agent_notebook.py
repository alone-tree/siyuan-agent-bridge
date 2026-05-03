from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .client import SiYuanClient
from .i18n import (
    AI_GUIDE_TEMPLATES,
    PRIVACY_RULES_TEMPLATES,
    ABOUT_TEMPLATES,
    ABOUT_TEMPLATE_VERSION_MARKER,
    SYSTEM_DOC_KEYS,
    get_doc_name,
    get_notebook_name,
    match_doc_key,
    match_notebook_name,
    all_notebook_names,
    resolve_language,
)
from .ignore import PrivacyRules, parse_privacy_rules_markdown


@dataclass(frozen=True)
class AgentNotebookState:
    language: str
    notebook_id: str
    notebook_name: str
    ai_guide_doc_id: str
    ai_guide_markdown: str
    workspace_index_doc_id: str | None
    workspace_index_markdown: str | None
    about_doc_id: str
    privacy_rules_doc_id: str
    privacy_rules: PrivacyRules


def ensure_agent_notebook(
    client: SiYuanClient,
    root: Path,
    config_language: str | None = None,
    *,
    detect_existing_language: bool = True,
) -> AgentNotebookState:
    """Find or create the system notebook and its fixed documents.

    Returns the complete state of the system notebook.
    """
    language = resolve_language(config_language)

    # Step 1: Find or create system notebook
    notebook_id, notebook_name, nb_language = _ensure_system_notebook(
        client, language, detect_existing_language
    )

    # If we found an existing notebook in a different language, use that language
    if nb_language and nb_language != language:
        effective_language = nb_language
    else:
        effective_language = language

    # Step 2: Find or create system documents
    docs = _list_system_docs(client, notebook_id)

    # AI Guide: create if missing, never overwrite
    ai_guide = _ensure_ai_guide(client, notebook_id, docs, effective_language)

    # About: create if missing, overwrite if template version changed
    about = _ensure_about(client, notebook_id, docs, effective_language)

    # Privacy Rules: create if missing, never overwrite; always parse
    privacy_rules = _ensure_privacy_rules(client, notebook_id, docs, effective_language)

    # Workspace Index: never auto-create
    ws_index = _find_workspace_index(client, notebook_id, docs)

    return AgentNotebookState(
        language=effective_language,
        notebook_id=notebook_id,
        notebook_name=notebook_name,
        ai_guide_doc_id=ai_guide["id"],
        ai_guide_markdown=ai_guide["markdown"],
        workspace_index_doc_id=ws_index.get("id"),
        workspace_index_markdown=ws_index.get("markdown"),
        about_doc_id=about["id"],
        privacy_rules_doc_id=privacy_rules["id"],
        privacy_rules=privacy_rules["rules"],
    )


def _ensure_system_notebook(
    client: SiYuanClient, language: str, detect_existing: bool
) -> tuple[str, str, str | None]:
    """Find or create the system notebook.

    Returns (notebook_id, notebook_name, detected_language | None).
    detected_language is set when we find an existing notebook in a known language.
    """
    all_notebooks = client.list_notebooks()
    known_names = all_notebook_names()

    # Look for existing system notebook by known names
    for nb in all_notebooks:
        nb_name = str(nb.get("name", ""))
        matched_lang = match_notebook_name(nb_name)
        if matched_lang:
            return str(nb.get("id", "")), nb_name, matched_lang

    # Not found — create with current language name
    target_name = get_notebook_name(language)
    result = client.create_notebook(target_name)
    nb_id = str(result.get("id", ""))

    if not nb_id:
        # Re-list to find the newly created notebook
        for nb in client.list_notebooks():
            if str(nb.get("name", "")) == target_name:
                nb_id = str(nb.get("id", ""))
                break

    if not nb_id:
        raise RuntimeError(f"无法创建系统笔记本: {target_name}")

    return nb_id, target_name, None


def _list_system_docs(
    client: SiYuanClient, notebook_id: str
) -> list[dict[str, Any]]:
    """List all documents in the system notebook."""
    from .indexer import ensure_notebooks_open

    with ensure_notebooks_open(client, [notebook_id]):
        return client.query_sql(
            f"SELECT id, path, hpath, markdown, content "
            f"FROM blocks WHERE type='d' AND box='{notebook_id}'"
        )


def _find_doc_by_key(
    docs: list[dict[str, Any]], key: str
) -> dict[str, Any] | None:
    """Find a system document by its stable key."""
    for doc in docs:
        hpath = str(doc.get("hpath", "")).strip("/")
        if match_doc_key(hpath) == key:
            return doc
    # Also try matching by path
    for doc in docs:
        path = str(doc.get("path", "")).strip("/")
        if match_doc_key(path) == key:
            return doc
    return None


def _ensure_ai_guide(
    client: SiYuanClient,
    notebook_id: str,
    docs: list[dict[str, Any]],
    language: str,
) -> dict[str, Any]:
    """Find or create the AI Guide document. Never overwrites existing."""
    existing = _find_doc_by_key(docs, "ai_guide")
    if existing:
        doc_id = str(existing.get("id", ""))
        # SQL markdown column is empty in SiYuan ≥3.x; use export API instead.
        markdown = client.export_markdown(doc_id)
        return {
            "id": doc_id,
            "markdown": markdown,
            "exists": True,
        }

    from .indexer import ensure_notebooks_open

    template = AI_GUIDE_TEMPLATES.get(language, AI_GUIDE_TEMPLATES["zh-CN"])
    doc_name = get_doc_name("ai_guide", language)
    with ensure_notebooks_open(client, [notebook_id]):
        result = client.create_doc_with_md(notebook_id, f"/{doc_name}", template)

    doc_id = str(result.get("id", ""))
    return {"id": doc_id, "markdown": template, "exists": False}


def _ensure_about(
    client: SiYuanClient,
    notebook_id: str,
    docs: list[dict[str, Any]],
    language: str,
) -> dict[str, Any]:
    """Find or create the About document. Overwrites if template version changed."""
    existing = _find_doc_by_key(docs, "about")
    template = ABOUT_TEMPLATES.get(language, ABOUT_TEMPLATES["zh-CN"])

    from .indexer import ensure_notebooks_open

    if existing:
        doc_id = str(existing.get("id", ""))
        # SQL markdown column is empty in SiYuan ≥3.x; use export API instead.
        current_md = client.export_markdown(doc_id)
        if ABOUT_TEMPLATE_VERSION_MARKER in current_md:
            return {
                "id": str(existing.get("id", "")),
                "markdown": current_md,
                "exists": True,
            }
        # Version changed — overwrite
        doc_id = str(existing.get("id", ""))
        with ensure_notebooks_open(client, [notebook_id]):
            client.update_block(doc_id, template)
        return {"id": doc_id, "markdown": template, "exists": True}

    doc_name = get_doc_name("about", language)
    with ensure_notebooks_open(client, [notebook_id]):
        result = client.create_doc_with_md(notebook_id, f"/{doc_name}", template)

    doc_id = str(result.get("id", ""))
    return {"id": doc_id, "markdown": template, "exists": False}


def _ensure_privacy_rules(
    client: SiYuanClient,
    notebook_id: str,
    docs: list[dict[str, Any]],
    language: str,
) -> dict[str, Any]:
    """Find or create the Privacy Rules document. Never overwrites existing.
    Always parses the current markdown into PrivacyRules.
    Raises ValueError if parsing fails.
    """
    existing = _find_doc_by_key(docs, "privacy_rules")

    from .indexer import ensure_notebooks_open

    if existing:
        doc_id = str(existing.get("id", ""))
        # SQL markdown column is empty in SiYuan ≥3.x; use export API instead.
        markdown = client.export_markdown(doc_id)
        rules = parse_privacy_rules_markdown(markdown)
        return {
            "id": doc_id,
            "markdown": markdown,
            "rules": rules,
            "exists": True,
        }

    template = PRIVACY_RULES_TEMPLATES.get(language, PRIVACY_RULES_TEMPLATES["zh-CN"])
    doc_name = get_doc_name("privacy_rules", language)
    with ensure_notebooks_open(client, [notebook_id]):
        result = client.create_doc_with_md(notebook_id, f"/{doc_name}", template)

    doc_id = str(result.get("id", ""))
    rules = parse_privacy_rules_markdown(template)
    return {"id": doc_id, "markdown": template, "rules": rules, "exists": False}


def _find_workspace_index(
    client: SiYuanClient,
    notebook_id: str,
    docs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Find the Workspace Index document. Never creates it."""
    existing = _find_doc_by_key(docs, "workspace_index")
    if existing:
        doc_id = str(existing.get("id", ""))
        # SQL markdown column is empty in SiYuan ≥3.x; use export API instead.
        markdown = client.export_markdown(doc_id)
        return {
            "id": doc_id,
            "markdown": markdown,
            "exists": True,
        }
    return {"id": None, "markdown": None, "exists": False}


def is_system_document(hpath: str) -> bool:
    """Check if a document path is a system document (by stable key)."""
    return match_doc_key(hpath) is not None


def is_privacy_rules_document(hpath: str) -> bool:
    """Check if a document path is the Privacy Rules document."""
    return match_doc_key(hpath) == "privacy_rules"


def is_system_notebook_name(name: str) -> bool:
    """Check if a notebook name matches any known system notebook name."""
    return match_notebook_name(name) is not None
