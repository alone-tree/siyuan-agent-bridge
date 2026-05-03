from __future__ import annotations

import locale
import sys
from dataclasses import dataclass
from typing import Any, Iterable

SUPPORTED_LANGUAGES = ("zh-CN", "en")
DEFAULT_LANGUAGE = "zh-CN"

SYSTEM_NOTEBOOK_NAMES: dict[str, str] = {
    "zh-CN": "思源代理桥",
    "en": "SiYuan Agent Bridge",
}

SYSTEM_DOC_KEYS = [
    "ai_guide",
    "workspace_index",
    "about",
    "privacy_rules",
]

SYSTEM_DOC_NAMES: dict[str, dict[str, str]] = {
    "ai_guide": {
        "zh-CN": "AI 使用指南",
        "en": "AI Guide",
    },
    "workspace_index": {
        "zh-CN": "工作空间索引",
        "en": "Workspace Index",
    },
    "about": {
        "zh-CN": "关于思源代理桥",
        "en": "About SiYuan Agent Bridge",
    },
    "privacy_rules": {
        "zh-CN": "隐私规则",
        "en": "Privacy Rules",
    },
}

AI_GUIDE_TEMPLATES: dict[str, str] = {
    "zh-CN": (
        "# AI 使用指南\n\n"
        "此文档存储给 AI 的长期规则。你可以在这里写下偏好、重点笔记本、写作风格和限制。\n\n"
        "## 使用说明\n\n"
        "- 在思源中直接编辑本文档即可修改规则。\n"
        "- 系统刷新不会覆盖已存在的 AI 使用指南。\n"
        "- 保持简洁 —— AI 读到的是 Markdown。\n\n"
        "## 偏好与规则\n\n"
        "> TODO: 在这里添加你的长期偏好。\n"
    ),
    "en": (
        "# AI Guide\n\n"
        "This document stores long-term instructions for AI — your preferences, important notebooks, writing style, and constraints.\n\n"
        "## Usage\n\n"
        "- Edit this document directly in SiYuan to change rules.\n"
        "- System refresh will not overwrite an existing AI Guide.\n"
        "- Keep it concise — AI reads Markdown.\n\n"
        "## Preferences & Rules\n\n"
        "> TODO: Add your long-term preferences here.\n"
    ),
}

PRIVACY_RULES_TEMPLATES: dict[str, str] = {
    "zh-CN": (
        "# 隐私规则\n\n"
        "隐私规则完全由人类在本文档控制，AI 无法阅读/编辑/删除该文档。\n\n"
        "请只编辑下面两张表格。你可以新增或删除表格行，但不要新增表格，也不要编辑表头，否则会报错。"
        "`Hide` 填 `yes` 才会对 AI 隐藏；填 `no` 表示暂不启用。"
        "你可以把某一行临时改为 `no` 来短暂开放给 AI，交流完毕后再改回 `yes`。"
        "文档修改会在每次工具刷新时生效，你可以告诉 AI「刷新一下」。\n\n"
        "隐藏文档必须填写文档 ID。标题只给你自己确认，系统不会按标题匹配，因为文档标题容易重复。\n\n"
        "隐藏笔记本时优先填写笔记本 ID。获取方法：在笔记本列表中点击笔记本右侧三个点，选择「设置」，然后点击「复制 ID」。"
        "如果暂时不知道 ID，也可以只填写笔记本名称；若多个笔记本重名，同名笔记本都会被隐藏。\n\n"
        "## 隐藏笔记本\n\n"
        "| Hide | 笔记本ID（建议填） | 笔记本名称 | 备注（可选） |\n"
        "|------|---------------------|------------|--------------|\n"
        "| no | 20260503123456-abcdefg | 示例笔记本 | 示例，不会生效 |\n"
        "| yes | 20260503123456-abcdefg | 示例：私人资料 | 示例，会隐藏 |\n"
        "| yes |  | 示例：个人日记 | 按名称隐藏 |\n\n"
        "## 隐藏文档\n\n"
        "| Hide | 文档ID（必填，不填会报错） | 标题（仅供确认） | 备注（可选） |\n"
        "|------|---------------------------|------------------|--------------|\n"
        "| no | 20260503123456-abcdefg | 示例文档 | 示例，不会生效 |\n"
        "| yes | 20260503123456-abcdefg | 示例：未公开项目 | 示例，会隐藏 |\n"
    ),
    "en": (
        "# Privacy Rules\n\n"
        "This document controls which notes are hidden from AI. AI cannot read this document.\n\n"
        "Only edit the two tables below. You may add or remove rows, but do not add tables or edit table headers. "
        "A row hides content from AI only when `Hide` is `yes`; `no` means disabled.\n\n"
        "Document hiding requires Document ID. Title is only for your confirmation and is not used for matching.\n\n"
        "For notebooks, Notebook ID is preferred. To get it, click the three-dot menu next to the notebook, "
        "open Settings, and click Copy ID. If you do not know the ID yet, use Notebook Name. "
        "If multiple notebooks share the same name, all matching notebooks will be hidden.\n\n"
        "## Hide Notebooks\n\n"
        "| Hide | Notebook ID | Notebook Name | Reason |\n"
        "|---------------|-------------------------|---------------|-----------------|\n"
        "| no | 20260503123456-abcdefg | Example: Private Notebook | Example, ignored |\n"
        "| yes | 20260503123456-abcdefg | Example: Private Data | Example, hidden |\n\n"
        "## Hide Documents\n\n"
        "| Hide | Document ID | Title | Reason |\n"
        "|---------------|------------------------|-------------------------------|-----------------|\n"
        "| no | 20260503123456-abcdefg | Example: Private Project | Example, ignored |\n"
        "| yes | 20260503123456-abcdefg | Example: Unpublished Project | Example, hidden |\n"
    ),
}

ABOUT_TEMPLATES: dict[str, str] = {
    "zh-CN": (
        "<!-- template_version: 1 -->\n\n"
        "# 关于思源代理桥\n\n"
        "本文档由思源代理桥自动维护，可能在刷新时更新。请不要在这里记录个人内容。\n\n"
        "思源代理桥是连接思源笔记和 AI 助手的本地桥接工具。"
        "它让 AI 在隐私规则保护下阅读、搜索和维护你的思源知识库。\n\n"
        "## 系统笔记本里的四份文档\n\n"
        "- **AI 使用指南**：给 AI 看的长期规则，你可以在这里写下偏好、重点笔记本、写作风格和限制。\n"
        "- **工作空间索引**：AI 生成的语义导航索引，帮助新会话快速了解这个工作空间里有什么。\n"
        "- **隐私规则**：由人类在思源中维护的 Markdown 表格，控制哪些笔记对 AI 隐藏。AI 无法读取此文档。\n"
        "- **关于思源代理桥**：就是本文档，给人看的工具说明。\n\n"
        "## 日常怎么用\n\n"
        "你平时正常在思源里写笔记。需要时告诉 AI「帮我查一下笔记里关于 XX 的内容」。"
        "如果某些笔记不想被 AI 看到，在隐私规则文档的表格里添加规则即可。"
        "不要删除或隐藏这个系统笔记本。\n\n"
        "更多信息请阅读项目 README、项目网站，或联系开发者。\n"
    ),
    "en": (
        "<!-- template_version: 1 -->\n\n"
        "# About SiYuan Agent Bridge\n\n"
        "This document is maintained by SiYuan Agent Bridge and may be updated during refresh. Do not store personal notes here.\n\n"
        "SiYuan Agent Bridge is a local bridge between SiYuan notes and AI agents, "
        "letting AI read, search, and maintain your knowledge base under privacy rules.\n\n"
        "## Four Documents in This Notebook\n\n"
        "- **AI Guide**: Long-term instructions for AI — your preferences, important notebooks, writing style, and constraints.\n"
        "- **Workspace Index**: AI-generated semantic navigation map for new sessions.\n"
        "- **Privacy Rules**: Human-maintained Markdown tables controlling which notes are hidden from AI. AI cannot read this document.\n"
        "- **About SiYuan Agent Bridge**: This document — a human-readable introduction to the tool.\n\n"
        "## How to Use\n\n"
        "Write notes in SiYuan as usual. When needed, ask AI to search your notes. "
        "To hide content from AI, add rules in the Privacy Rules document tables. "
        "Do not delete or hide this system notebook.\n\n"
        "For more details, read the project README, visit the project website, or contact the developer.\n"
    ),
}

ABOUT_TEMPLATE_VERSION_MARKER = "<!-- template_version: 1 -->"


@dataclass(frozen=True)
class LanguageConfig:
    language: str
    preferred_reply_language: str
    startup_header: str


def resolve_language(config_language: str | None = None) -> str:
    """Resolve language preference.

    Priority:
    1. Explicit config (e.g. language="zh-CN" or "en")
    2. System locale
    3. Default zh-CN (with warning)
    """
    if config_language and config_language in SUPPORTED_LANGUAGES:
        return config_language

    try:
        sys_locale = locale.getdefaultlocale()[0]
    except (ValueError, locale.Error):
        sys_locale = None
    if sys_locale:
        sys_locale_lower = sys_locale.lower()
        if sys_locale_lower.startswith("zh"):
            return "zh-CN"
        if sys_locale_lower.startswith("en"):
            return "en"

    # Phase 1: other languages fallback to English
    # But for users whose system locale is not zh/en, default to zh-CN
    return DEFAULT_LANGUAGE


def get_notebook_name(language: str) -> str:
    return SYSTEM_NOTEBOOK_NAMES.get(language, SYSTEM_NOTEBOOK_NAMES[DEFAULT_LANGUAGE])


def get_doc_name(key: str, language: str) -> str:
    names = SYSTEM_DOC_NAMES.get(key, {})
    return names.get(language, names.get(DEFAULT_LANGUAGE, key))


def get_doc_path(key: str, language: str) -> str:
    return f"/{get_doc_name(key, language)}"


def all_notebook_names() -> list[str]:
    return list(SYSTEM_NOTEBOOK_NAMES.values())


def all_doc_names_for_key(key: str) -> list[str]:
    names = SYSTEM_DOC_NAMES.get(key, {})
    return list(names.values())


def match_doc_key(hpath: str) -> str | None:
    """Match a document hpath (e.g. '/AI Guide') to its stable key.
    Returns None if not a system document.
    """
    if not hpath:
        return None
    normalized = hpath.strip("/").casefold()
    for key in SYSTEM_DOC_KEYS:
        for name in SYSTEM_DOC_NAMES[key].values():
            if name.casefold() == normalized:
                return key
    return None


def match_notebook_name(name: str) -> str | None:
    """Check if a notebook name matches any known system notebook name.
    Returns the language code if matched, None otherwise.
    """
    if not name:
        return None
    folded = name.casefold()
    for lang, nb_name in SYSTEM_NOTEBOOK_NAMES.items():
        if nb_name.casefold() == folded:
            return lang
    return None


def build_language_config(language: str) -> LanguageConfig:
    if language == "en":
        return LanguageConfig(
            language="en",
            preferred_reply_language="English",
            startup_header=(
                "## Language Preference\n\n"
                "Detected user/workspace language: en\n"
                "Preferred reply language: English\n"
                "Use English by default when talking to the user, unless the user explicitly asks for another language.\n"
            ),
        )
    return LanguageConfig(
        language="zh-CN",
        preferred_reply_language="中文",
        startup_header=(
            "## 语言偏好\n\n"
            "检测到的用户/工作空间语言：zh-CN\n"
            "优先回复语言：中文\n"
            "除非用户明确要求使用其他语言，否则默认用中文回复。\n"
        ),
    )
