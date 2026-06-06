from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from source_code.ignore import (
    PrivacyRules,
    PrivacyRulesParseError,
    document_permission,
    filter_documents,
    load_privacy_rules,
    parse_privacy_rules_markdown,
    write_privacy_rules_cache,
)
from source_code.indexer import find_documents, normalize_documents, refresh_index, resolve_document


class FakeClient:
    def __init__(self):
        self._system_docs: dict[str, str] = {}
        self._notebooks: list[dict] = [
            {"id": "nb1", "name": "Main"},
        ]

    def list_notebooks(self):
        return list(self._notebooks)

    def query_sql(self, stmt):
        if any(name in stmt for name in ("思源代理桥", "SiYuan Agent Bridge", "思源桥", "SiYuan Bridge")):
            result = []
            if "/AI Guide" in self._system_docs:
                result.append({"id": "system-ai-guide", "path": "/AI Guide", "markdown": self._system_docs["/AI Guide"]})
            if "/About SiYuan Bridge" in self._system_docs:
                result.append({"id": "system-about", "path": "/About SiYuan Bridge", "markdown": self._system_docs["/About SiYuan Bridge"]})
            if "/Workspace Index" in self._system_docs:
                result.append({"id": "system-ws-index", "path": "/Workspace Index", "markdown": self._system_docs["/Workspace Index"]})
            if "/Privacy Rules" in self._system_docs:
                result.append({"id": "system-pr", "path": "/Privacy Rules", "markdown": self._system_docs["/Privacy Rules"]})
            if "/隐私规则" in self._system_docs:
                result.append({"id": "system-pr-zh", "path": "/隐私规则", "markdown": self._system_docs["/隐私规则"]})
            return result
        if "GROUP BY root_id" in stmt:
            return [
                {"root_id": "20260429120000-abcdefg", "block_count": 3, "char_count": 100},
                {"root_id": "20260429130000-hijklmn", "block_count": 2, "char_count": 50},
            ]
        if "ORDER BY root_id" in stmt:
            return [
                {"root_id": "20260429120000-abcdefg", "content": "SiYuan Agent Bridge"},
                {"root_id": "20260429120000-abcdefg", "content": "This document has a longer exported body."},
                {"root_id": "20260429120000-abcdefg", "content": "More content here."},
                {"root_id": "20260429130000-hijklmn", "content": "Other"},
                {"root_id": "20260429130000-hijklmn", "content": "Short body."},
            ]
        return [
            {
                "id": "20260429120000-abcdefg",
                "box": "nb1",
                "hpath": "/Projects/SiYuan Agent Bridge",
                "path": "/20260429120000-abcdefg.sy",
                "name": "",
                "content": "SiYuan Agent Bridge",
                "tag": "#ai# #notes#",
                "created": "20260429120000",
                "updated": "20260429120100",
            },
            {
                "id": "20260429130000-hijklmn",
                "box": "nb1",
                "hpath": "/Projects/Other",
                "path": "/20260429130000-hijklmn.sy",
                "content": "Other",
                "tag": "",
            },
        ]

    def export_markdown(self, block_id):
        markdown = {
            "20260429120000-abcdefg": "# SiYuan Agent Bridge\n\nThis document has a longer exported body.",
            "20260429130000-hijklmn": "# Other\n\nShort body.",
            "20260429140000-child": "# Child\n\nChild body.",
        }
        return markdown.get(block_id, "")

    def create_notebook(self, name):
        nb = {"id": "system-nb-id", "name": name}
        self._notebooks.append(nb)
        return nb

    def create_doc_with_md(self, notebook, path, markdown):
        doc_id = f"system-{path.strip('/').replace(' ', '-').lower()}"
        self._system_docs[path] = markdown
        return {"id": doc_id}

    def update_block(self, block_id, markdown):
        pass

    def open_notebook(self, notebook_id):
        pass

    def close_notebook(self, notebook_id):
        pass

    def get_child_blocks(self, block_id):
        return []


class IndexerTests(unittest.TestCase):
    def test_refresh_writes_indexes_and_preserves_existing_guide(self):
        root = Path.cwd() / ".test_tmp" / "indexer_refresh"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        guide = root / "knowledge_base" / "guide.md"
        guide.parent.mkdir(exist_ok=True)
        guide.write_text("keep me\n", encoding="utf-8")

        # Write a privacy rules cache first
        write_privacy_rules_cache(root, PrivacyRules(ignore=[], allow=[]))

        result = refresh_index(FakeClient(), root)

        self.assertEqual(result.document_count, 2)
        self.assertEqual(guide.read_text(encoding="utf-8"), "keep me\n")
        self.assertTrue((root / "knowledge_base" / "notebooks.json").exists())
        self.assertTrue((root / "knowledge_base" / "docs.jsonl").exists())
        self.assertFalse((root / "knowledge_base" / "overview.md").exists())
        self.assertFalse((root / "knowledge_base" / "notebooks").exists())
        tree = (root / "knowledge_base" / "tree.md").read_text(encoding="utf-8")
        self.assertIn("SiYuan Agent Bridge", tree)
        self.assertIn("20260429120000-abcdefg", tree)
        self.assertIn("| 笔记本 | ID | 文档数 | 字数 | 块数 | 最近更新 |", tree)
        self.assertIn(" 字", tree)

    def test_normalize_documents_extracts_tags(self):
        docs = normalize_documents(FakeClient().query_sql(""), FakeClient().list_notebooks())
        by_id = {doc["id"]: doc for doc in docs}

        self.assertEqual(by_id["20260429120000-abcdefg"]["tags"], ["ai", "notes"])
        self.assertEqual(by_id["20260429120000-abcdefg"]["notebook_name"], "Main")

    def test_refresh_populates_block_count_and_word_count(self):
        root = Path.cwd() / ".test_tmp" / "indexer_stats"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        write_privacy_rules_cache(root, PrivacyRules(ignore=[], allow=[]))

        refresh_index(FakeClient(), root)
        docs = {
            doc["id"]: doc
            for doc in (
                json.loads(line)
                for line in (root / "knowledge_base" / "docs.jsonl").read_text(encoding="utf-8").splitlines()
            )
        }

        self.assertEqual(docs["20260429120000-abcdefg"]["block_count"], 3)
        self.assertGreater(docs["20260429120000-abcdefg"]["word_count"], 0)
        self.assertIn("block_count", docs["20260429120000-abcdefg"])
        self.assertNotIn("index_word_count", docs["20260429120000-abcdefg"])

    def test_find_and_resolve_documents(self):
        docs = normalize_documents(FakeClient().query_sql(""), FakeClient().list_notebooks())

        matches = find_documents(docs, "siyuan")
        self.assertEqual(matches[0]["id"], "20260429120000-abcdefg")

        status, resolved = resolve_document(docs, "/Projects/SiYuan Agent Bridge")
        self.assertEqual(status, "ok")
        self.assertEqual(resolved[0]["id"], "20260429120000-abcdefg")

    def test_resolve_ambiguous_partial_locator(self):
        docs = normalize_documents(FakeClient().query_sql(""), FakeClient().list_notebooks())

        status, resolved = resolve_document(docs, "Projects")

        self.assertEqual(status, "ambiguous")
        self.assertEqual(len(resolved), 2)

    def test_subtree_ignore_hides_root_and_children(self):
        rows = FakeClient().query_sql("") + [
            {
                "id": "20260429140000-child",
                "box": "nb1",
                "hpath": "/Projects/SiYuan Agent Bridge/Child",
                "path": "/20260429140000-child.sy",
                "content": "Child",
                "tag": "",
            }
        ]
        docs = normalize_documents(rows, FakeClient().list_notebooks())

        visible = filter_documents(
            docs,
            PrivacyRules(ignore=[{"scope": "subtree", "id": "20260429120000-abcdefg"}], allow=[]),
        )
        visible_ids = {doc["id"] for doc in visible}

        self.assertNotIn("20260429120000-abcdefg", visible_ids)
        self.assertNotIn("20260429140000-child", visible_ids)
        self.assertIn("20260429130000-hijklmn", visible_ids)

    def test_document_ignore_hides_root_and_children(self):
        rows = FakeClient().query_sql("") + [
            {
                "id": "20260429140000-child",
                "box": "nb1",
                "hpath": "/Projects/SiYuan Agent Bridge/Child",
                "path": "/20260429140000-child.sy",
                "content": "Child",
                "tag": "",
            }
        ]
        docs = normalize_documents(rows, FakeClient().list_notebooks())

        visible = filter_documents(
            docs,
            PrivacyRules(ignore=[{"scope": "document", "id": "20260429120000-abcdefg"}], allow=[]),
        )
        visible_ids = {doc["id"] for doc in visible}

        self.assertNotIn("20260429120000-abcdefg", visible_ids)
        self.assertNotIn("20260429140000-child", visible_ids)
        self.assertIn("20260429130000-hijklmn", visible_ids)

    def test_load_privacy_rules_from_cache(self):
        root = Path.cwd() / ".test_tmp" / "privacy_cache"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)

        rules = PrivacyRules(
            ignore=[{"scope": "document", "id": "doc1"}],
            allow=[],
        )
        write_privacy_rules_cache(root, rules)

        loaded = load_privacy_rules(root)
        self.assertEqual(len(loaded.ignore), 1)
        self.assertEqual(loaded.ignore[0]["id"], "doc1")

    def test_load_privacy_rules_missing_cache_returns_empty(self):
        root = Path.cwd() / ".test_tmp" / "privacy_missing"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)

        loaded = load_privacy_rules(root)
        self.assertEqual(len(loaded.ignore), 0)
        self.assertEqual(len(loaded.allow), 0)

    def test_refresh_filters_privacy_rules_document(self):
        root = Path.cwd() / ".test_tmp" / "indexer_filter_pr"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        write_privacy_rules_cache(root, PrivacyRules(ignore=[], allow=[]))

        client = FakeClient()
        # Add a Privacy Rules document in Main notebook
        client._system_docs["/Privacy Rules"] = "# Privacy Rules\n\n| Hide | ... |"

        result = refresh_index(client, root, system_notebook_id="nb1", privacy_rules_doc_id="system-pr")

        docs = {
            doc["id"]: doc
            for doc in (
                json.loads(line)
                for line in (root / "knowledge_base" / "docs.jsonl").read_text(encoding="utf-8").splitlines()
            )
        }
        # Privacy Rules doc should NOT be in the index
        self.assertNotIn("system-pr", docs)


# ── Privacy Rules Markdown Parsing Tests ──────────────────────────────

class PrivacyRulesParsingTests(unittest.TestCase):
    def test_parse_empty_markdown(self):
        rules = parse_privacy_rules_markdown("")
        self.assertEqual(len(rules.ignore), 0)

    def test_parse_chinese_notebook_rule_active(self):
        markdown = """# 隐私规则

## 隐藏笔记本

| Hide | 笔记本ID（建议填） | 笔记本名称 | 备注（可选） |
|------|---------------------|------------|--------------|
| yes | nb-test-id | 测试笔记本 | 测试 |
"""
        rules = parse_privacy_rules_markdown(markdown)
        self.assertEqual(len(rules.ignore), 1)
        self.assertEqual(rules.ignore[0]["scope"], "notebook")
        self.assertEqual(rules.ignore[0]["id"], "nb-test-id")

    def test_parse_chinese_notebook_rule_inactive(self):
        markdown = """## 隐藏笔记本

| Hide | 笔记本ID（建议填） | 笔记本名称 | 备注（可选） |
|------|---------------------|------------|--------------|
| no | nb-test-id | 测试笔记本 | 测试 |
"""
        rules = parse_privacy_rules_markdown(markdown)
        self.assertEqual(len(rules.ignore), 0)

    def test_parse_chinese_document_rule_active(self):
        markdown = """## 隐藏文档

| Hide | 文档ID（必填，不填会报错） | 标题（仅供确认） | 备注（可选） |
|------|---------------------------|------------------|--------------|
| yes | doc-test-id | 测试文档 | 测试 |
"""
        rules = parse_privacy_rules_markdown(
            markdown,
            all_docs=[{"id": "doc-test-id", "title": "测试文档"}],
        )
        self.assertEqual(len(rules.ignore), 1)
        self.assertEqual(rules.ignore[0]["scope"], "document")
        self.assertEqual(rules.ignore[0]["id"], "doc-test-id")

    def test_parse_english_notebook_rule(self):
        markdown = """## Hide Notebooks

| Hide | Notebook ID | Notebook Name | Reason |
|------|-------------|---------------|--------|
| yes | nb-eng-id | English NB | test |
"""
        rules = parse_privacy_rules_markdown(markdown)
        self.assertEqual(len(rules.ignore), 1)
        self.assertEqual(rules.ignore[0]["id"], "nb-eng-id")

    def test_parse_english_document_rule(self):
        markdown = """## Hide Documents

| Hide | Document ID | Title | Reason |
|------|-------------|-------|--------|
| yes | doc-eng-id | English Doc | test |
"""
        rules = parse_privacy_rules_markdown(
            markdown,
            all_docs=[{"id": "doc-eng-id", "title": "English Doc"}],
        )
        self.assertEqual(len(rules.ignore), 1)
        self.assertEqual(rules.ignore[0]["id"], "doc-eng-id")

    def test_document_missing_id_errors(self):
        markdown = """## 隐藏文档

| Hide | 文档ID（必填，不填会报错） | 标题（仅供确认） |
|------|---------------------------|------------------|
| yes |  | 测试文档 |
"""
        with self.assertRaises(PrivacyRulesParseError) as ctx:
            parse_privacy_rules_markdown(markdown)
        self.assertIn("文档ID 为空", str(ctx.exception))

    def test_invalid_hide_value_errors(self):
        markdown = """## 隐藏笔记本

| Hide | 笔记本ID（建议填） | 笔记本名称 |
|------|---------------------|------------|
| maybe | nb-test | 测试 |
"""
        with self.assertRaises(PrivacyRulesParseError) as ctx:
            parse_privacy_rules_markdown(markdown)
        self.assertIn("旧 Hide 列只能填写", str(ctx.exception))

    def test_document_id_not_found_errors(self):
        markdown = """## 隐藏文档

| Hide | 文档ID（必填，不填会报错） | 标题（仅供确认） |
|------|---------------------------|------------------|
| yes | nonexistent-id | 不存在的文档 |
"""
        with self.assertRaises(PrivacyRulesParseError) as ctx:
            parse_privacy_rules_markdown(
                markdown,
                all_docs=[{"id": "other-id", "title": "其他文档"}],
            )
        self.assertIn("文档ID 不存在", str(ctx.exception))

    def test_notebook_by_name_matching(self):
        markdown = """## 隐藏笔记本

| Hide | 笔记本ID（建议填） | 笔记本名称 |
|------|---------------------|------------|
| yes |  | 我的私人笔记 |
"""
        rules = parse_privacy_rules_markdown(
            markdown,
            all_notebooks=[{"id": "nb1", "name": "我的私人笔记"}],
        )
        self.assertEqual(len(rules.ignore), 1)
        self.assertEqual(rules.ignore[0]["name"], "我的私人笔记")

    def test_notebook_name_not_matched_errors(self):
        markdown = """## 隐藏笔记本

| Hide | 笔记本ID（建议填） | 笔记本名称 |
|------|---------------------|------------|
| yes |  | 不存在的笔记本 |
"""
        with self.assertRaises(PrivacyRulesParseError) as ctx:
            parse_privacy_rules_markdown(
                markdown,
                all_notebooks=[{"id": "nb1", "name": "Main"}],
            )
        self.assertIn("笔记本名称未匹配", str(ctx.exception))

    def test_missing_header_active_column_errors(self):
        markdown = """## 隐藏笔记本

| 笔记本ID（建议填） | 笔记本名称 |
|---------------------|------------|
| nb-test | 测试 |
"""
        with self.assertRaises(PrivacyRulesParseError) as ctx:
            parse_privacy_rules_markdown(markdown)
        self.assertIn("权限 列", str(ctx.exception))

    def test_missing_header_document_id_column_errors(self):
        markdown = """## 隐藏文档

| Hide | 标题 |
|------|------|
| yes | 测试 |
"""
        with self.assertRaises(PrivacyRulesParseError) as ctx:
            parse_privacy_rules_markdown(markdown)
        self.assertIn("文档ID 列", str(ctx.exception))

    def test_both_sections_parsed(self):
        markdown = """## 隐藏笔记本

| Hide | 笔记本ID（建议填） | 笔记本名称 |
|------|---------------------|------------|
| yes | nb-1 | 笔记1 |

## 隐藏文档

| Hide | 文档ID（必填，不填会报错） | 标题（仅供确认） |
|------|---------------------------|------------------|
| yes | doc-1 | 文档1 |
"""
        rules = parse_privacy_rules_markdown(
            markdown,
            all_notebooks=[{"id": "nb-1", "name": "笔记1"}],
            all_docs=[{"id": "doc-1", "title": "文档1"}],
        )
        self.assertEqual(len(rules.ignore), 2)
        scopes = {r["scope"] for r in rules.ignore}
        self.assertEqual(scopes, {"notebook", "document"})

    def test_permission_column_parses_read_only_document(self):
        markdown = """## 隐藏文档

| Hide | Permission | Document ID | Title |
|------|------------|-------------|-------|
| no | read_only | doc-1 | 文档1 |
"""
        rules = parse_privacy_rules_markdown(
            markdown,
            all_docs=[{"id": "doc-1", "title": "文档1"}],
        )
        self.assertEqual(rules.ignore, [])
        self.assertEqual(rules.permissions[0]["permission"], "read_only")

    def test_document_permission_returns_read_only(self):
        docs = [
            {
                "id": "doc-1",
                "notebook_id": "nb1",
                "notebook_name": "Main",
                "hpath": "/Doc",
            }
        ]
        rules = PrivacyRules(
            ignore=[],
            allow=[],
            permissions=[{"scope": "document", "id": "doc-1", "permission": "read_only"}],
        )
        self.assertEqual(document_permission(docs[0], rules, docs), "read_only")

    def test_active_values_compatibility(self):
        for active_val in ("是", "yes", "true", "1"):
            markdown = f"""## 隐藏笔记本

| Hide | 笔记本ID（建议填） | 笔记本名称 |
|------|---------------------|------------|
| {active_val} | nb-test | 测试 |
"""
            rules = parse_privacy_rules_markdown(markdown)
            self.assertEqual(len(rules.ignore), 1, f"Failed for value: {active_val}")

    def test_inactive_values_compatibility(self):
        for inactive_val in ("否", "no", "false", "0", ""):
            markdown = f"""## 隐藏笔记本

| Hide | 笔记本ID（建议填） | 笔记本名称 |
|------|---------------------|------------|
| {inactive_val} | nb-test | 测试 |
"""
            rules = parse_privacy_rules_markdown(markdown)
            self.assertEqual(len(rules.ignore), 0, f"Failed for value: {inactive_val}")

    def test_enabled_alias_accepted(self):
        markdown = """## 隐藏笔记本

| Enabled | Notebook ID | Notebook Name |
|---------|-------------|---------------|
| yes | nb-test | Test |
"""
        rules = parse_privacy_rules_markdown(markdown)
        self.assertEqual(len(rules.ignore), 1)

    def test_error_message_does_not_expose_values(self):
        markdown = """## 隐藏文档

| Hide | 文档ID（必填，不填会报错） | 标题（仅供确认） |
|------|---------------------------|------------------|
| yes | secret-doc-id | 我的秘密文档 |
"""
        with self.assertRaises(PrivacyRulesParseError) as ctx:
            parse_privacy_rules_markdown(
                markdown,
                all_docs=[{"id": "other-id", "title": "其他"}],
            )
        error_msg = str(ctx.exception)
        self.assertNotIn("secret-doc-id", error_msg)
        self.assertNotIn("我的秘密文档", error_msg)

    def test_notebook_neither_id_nor_name_errors(self):
        markdown = """## 隐藏笔记本

| Hide | 笔记本ID（建议填） | 笔记本名称 |
|------|---------------------|------------|
| yes |  |  |
"""
        with self.assertRaises(PrivacyRulesParseError) as ctx:
            parse_privacy_rules_markdown(markdown)
        self.assertIn("ID 和名称都为空", str(ctx.exception))


# ── Permission Three-Tier Model Tests (subtree, conflict, DocManager safety) ──

class PermissionTreeTests(unittest.TestCase):
    """Tests for the three-tier permission model (hidden > read_only > read_write)
    with subtree inheritance, notebook/document crossover, and conflict resolution."""

    def _make_doc(self, id, notebook_id="nb1", notebook_name="Main", hpath="/Doc"):
        return {"id": id, "notebook_id": notebook_id, "notebook_name": notebook_name, "hpath": hpath}

    # ── Subtree inheritance ──

    def test_subtree_inherits_parent_read_only(self):
        """Child document under a read_only parent inherits read_only."""
        docs = [
            self._make_doc("parent-1", hpath="/ReadOnly"),
            self._make_doc("child-1", hpath="/ReadOnly/Child"),
            self._make_doc("unrelated", hpath="/Other"),
        ]
        rules = PrivacyRules(
            ignore=[],
            allow=[],
            permissions=[{"scope": "document", "id": "parent-1", "permission": "read_only"}],
        )
        self.assertEqual(document_permission(docs[0], rules, docs), "read_only")
        self.assertEqual(document_permission(docs[1], rules, docs), "read_only")
        self.assertEqual(document_permission(docs[2], rules, docs), "read_write")

    def test_subtree_parent_hidden_hides_all_children(self):
        """All descendants of a hidden parent are hidden."""
        docs = [
            self._make_doc("parent-h", hpath="/Hidden"),
            self._make_doc("child-h", hpath="/Hidden/Child"),
            self._make_doc("grandchild-h", hpath="/Hidden/Child/Grandchild"),
            self._make_doc("visible", hpath="/Other"),
        ]
        rules = PrivacyRules(
            ignore=[],
            allow=[],
            permissions=[{"scope": "document", "id": "parent-h", "permission": "hidden"}],
        )
        self.assertEqual(document_permission(docs[0], rules, docs), "hidden")
        self.assertEqual(document_permission(docs[1], rules, docs), "hidden")
        self.assertEqual(document_permission(docs[2], rules, docs), "hidden")
        self.assertEqual(document_permission(docs[3], rules, docs), "read_write")

    def test_subtree_most_restrictive_wins(self):
        """When parent=read_only and child=hidden, hidden wins."""
        docs = [
            self._make_doc("parent-ro", hpath="/RO"),
            self._make_doc("child-h", hpath="/RO/ChildH"),
        ]
        rules = PrivacyRules(
            ignore=[],
            allow=[],
            permissions=[
                {"scope": "document", "id": "parent-ro", "permission": "read_only"},
                {"scope": "document", "id": "child-h", "permission": "hidden"},
            ],
        )
        self.assertEqual(document_permission(docs[0], rules, docs), "read_only")
        # Most restrictive wins: hidden
        self.assertEqual(document_permission(docs[1], rules, docs), "hidden")

    def test_subtree_parent_read_write_child_read_only(self):
        """Parent is read_write, child is read_only. Child should be read_only."""
        docs = [
            self._make_doc("parent-rw", hpath="/RW"),
            self._make_doc("child-ro", hpath="/RW/ChildRO"),
        ]
        rules = PrivacyRules(
            ignore=[],
            allow=[],
            permissions=[{"scope": "document", "id": "child-ro", "permission": "read_only"}],
        )
        self.assertEqual(document_permission(docs[0], rules, docs), "read_write")
        self.assertEqual(document_permission(docs[1], rules, docs), "read_only")

    def test_subtree_grandparent_three_levels_inheritance(self):
        """Three-level decomposition: grandparent read_only → all descendants read_only."""
        docs = [
            self._make_doc("gp", hpath="/A"),
            self._make_doc("p", hpath="/A/B"),
            self._make_doc("c", hpath="/A/B/C"),
            self._make_doc("unrelated", hpath="/X/Y/Z"),
        ]
        rules = PrivacyRules(
            ignore=[],
            allow=[],
            permissions=[{"scope": "document", "id": "gp", "permission": "read_only"}],
        )
        for i in range(3):
            self.assertEqual(document_permission(docs[i], rules, docs), "read_only", f"doc {i}")
        self.assertEqual(document_permission(docs[3], rules, docs), "read_write")

    # ── Notebook × Document crossover ──

    def test_notebook_read_only_all_docs_read_only(self):
        """Notebook-level read_only makes all docs in it read_only by default."""
        docs = [
            self._make_doc("d1", notebook_id="nb-ro", notebook_name="RO_NB", hpath="/Doc1"),
            self._make_doc("d2", notebook_id="nb-ro", notebook_name="RO_NB", hpath="/Doc2"),
            self._make_doc("d3", notebook_id="nb-other", notebook_name="OtherNB", hpath="/Doc3"),
        ]
        rules = PrivacyRules(
            ignore=[],
            allow=[],
            permissions=[{"scope": "notebook", "id": "nb-ro", "permission": "read_only"}],
        )
        self.assertEqual(document_permission(docs[0], rules, docs), "read_only")
        self.assertEqual(document_permission(docs[1], rules, docs), "read_only")
        self.assertEqual(document_permission(docs[2], rules, docs), "read_write")

    def test_notebook_hidden_overrides_doc_read_only(self):
        """Notebook=hidden + document=read_only → hidden wins (more restrictive)."""
        docs = [
            self._make_doc("d1", notebook_id="nb-h", notebook_name="HiddenNB", hpath="/Doc1"),
        ]
        rules = PrivacyRules(
            ignore=[],
            allow=[],
            permissions=[
                {"scope": "notebook", "id": "nb-h", "permission": "hidden"},
                {"scope": "document", "id": "d1", "permission": "read_only"},
            ],
        )
        self.assertEqual(document_permission(docs[0], rules, docs), "hidden")

    def test_notebook_read_only_doc_explicit_hidden(self):
        """Notebook=read_only + document=hidden → hidden wins."""
        docs = [
            self._make_doc("d1", notebook_id="nb-ro", notebook_name="RO_NB", hpath="/Doc1"),
        ]
        rules = PrivacyRules(
            ignore=[],
            allow=[],
            permissions=[
                {"scope": "notebook", "id": "nb-ro", "permission": "read_only"},
                {"scope": "document", "id": "d1", "permission": "hidden"},
            ],
        )
        self.assertEqual(document_permission(docs[0], rules, docs), "hidden")

    def test_notebook_read_only_doc_explicit_read_write(self):
        """Notebook=read_only + document=read_write → most restrictive is read_only.
        The document cannot escalate above its notebook's cap."""
        docs = [
            self._make_doc("d1", notebook_id="nb-ro", notebook_name="RO_NB", hpath="/Doc1"),
        ]
        rules = PrivacyRules(
            ignore=[],
            allow=[],
            permissions=[
                {"scope": "notebook", "id": "nb-ro", "permission": "read_only"},
                {"scope": "document", "id": "d1", "permission": "read_write"},
            ],
        )
        self.assertEqual(document_permission(docs[0], rules, docs), "read_only")

    # ── Permission parsing (three-tier model) ──

    def test_permission_column_parses_chinese_read_only(self):
        markdown = """## 文档权限

| 权限 | 文档ID（必填，不填会报错） | 标题（仅供确认） |
|------|---------------------------|------------------|
| 只读 | doc-1 | 测试文档 |
"""
        rules = parse_privacy_rules_markdown(
            markdown,
            all_docs=[{"id": "doc-1", "title": "测试文档"}],
        )
        self.assertEqual(rules.ignore, [])
        self.assertEqual(len(rules.permissions), 1)
        self.assertEqual(rules.permissions[0]["permission"], "read_only")

    def test_permission_column_parses_chinese_hidden(self):
        markdown = """## 文档权限

| 权限 | 文档ID（必填，不填会报错） | 标题（仅供确认） |
|------|---------------------------|------------------|
| 隐藏 | doc-2 | 隐藏文档 |
"""
        rules = parse_privacy_rules_markdown(
            markdown,
            all_docs=[{"id": "doc-2", "title": "隐藏文档"}],
        )
        # hidden goes to ignore for backward compatibility (same effect via document_permission)
        self.assertEqual(len(rules.ignore), 1)
        self.assertEqual(rules.ignore[0]["id"], "doc-2")
        self.assertEqual(len(rules.permissions), 0)

    def test_permission_column_parses_chinese_read_write(self):
        markdown = """## 文档权限

| 权限 | 文档ID（必填，不填会报错） | 标题（仅供确认） |
|------|---------------------------|------------------|
| 读写 | doc-3 | 正常文档 |
"""
        rules = parse_privacy_rules_markdown(
            markdown,
            all_docs=[{"id": "doc-3", "title": "正常文档"}],
        )
        self.assertEqual(rules.ignore, [])
        self.assertEqual(len(rules.permissions), 1)
        self.assertEqual(rules.permissions[0]["permission"], "read_write")

    def test_permission_column_parses_chinese_notebook(self):
        markdown = """## 笔记本权限

| 权限 | 笔记本ID（建议填） | 笔记本名称 | 备注（可选） |
|------|---------------------|------------|--------------|
| 只读 | nb-ro-id | 只读笔记 | 测试 |
"""
        rules = parse_privacy_rules_markdown(markdown)
        self.assertEqual(len(rules.permissions), 1)
        self.assertEqual(rules.permissions[0]["scope"], "notebook")
        self.assertEqual(rules.permissions[0]["id"], "nb-ro-id")
        self.assertEqual(rules.permissions[0]["permission"], "read_only")

    def test_permission_column_rejects_invalid_value(self):
        markdown = """## 文档权限

| 权限 | 文档ID（必填，不填会报错） | 标题（仅供确认） |
|------|---------------------------|------------------|
| foobar | doc-1 | 测试文档 |
"""
        with self.assertRaises(PrivacyRulesParseError) as ctx:
            parse_privacy_rules_markdown(
                markdown,
                all_docs=[{"id": "doc-1", "title": "测试文档"}],
            )
        self.assertIn("权限只能填写 读写/只读/隐藏", str(ctx.exception))

    def test_permission_column_english_values(self):
        markdown = """## Document Permissions

| Permission | Document ID | Title |
|---------------|-------------|-------|
| hidden | doc-en-1 | English Hidden |
| read_only | doc-en-2 | English Read Only |
"""
        rules = parse_privacy_rules_markdown(
            markdown,
            all_docs=[{"id": "doc-en-1", "title": "English Hidden"}, {"id": "doc-en-2", "title": "English Read Only"}],
        )
        # hidden goes to ignore, read_only goes to permissions
        self.assertEqual(len(rules.ignore), 1)
        self.assertEqual(rules.ignore[0]["id"], "doc-en-1")
        self.assertEqual(len(rules.permissions), 1)
        self.assertEqual(rules.permissions[0]["id"], "doc-en-2")
        self.assertEqual(rules.permissions[0]["permission"], "read_only")

    def test_permission_hidden_goes_to_ignore_not_permissions(self):
        """A rule with permission=hidden is treated as ignore (not permissions list)."""
        markdown = """## 文档权限

| 权限 | 文档ID（必填，不填会报错） | 标题（仅供确认） |
|------|---------------------------|------------------|
| 隐藏 | doc-hidden | 隐藏文档 |
"""
        rules = parse_privacy_rules_markdown(
            markdown,
            all_docs=[{"id": "doc-hidden", "title": "隐藏文档"}],
        )
        # hidden goes to ignore array, not permissions array
        self.assertEqual(len(rules.ignore), 1)
        self.assertEqual(len(rules.permissions), 0)
        self.assertEqual(rules.ignore[0]["id"], "doc-hidden")

    def test_permission_mixed_hidden_and_read_only(self):
        """Mixed: hidden goes to ignore, read_only goes to permissions."""
        markdown = """## 文档权限

| 权限 | 文档ID（必填，不填会报错） | 标题（仅供确认） |
|------|---------------------------|------------------|
| 隐藏 | doc-h | 隐藏 |
| 只读 | doc-ro | 只读 |
| 读写 | doc-rw | 读写 |
"""
        rules = parse_privacy_rules_markdown(
            markdown,
            all_docs=[
                {"id": "doc-h", "title": "隐藏"},
                {"id": "doc-ro", "title": "只读"},
                {"id": "doc-rw", "title": "读写"},
            ],
        )
        self.assertEqual(len(rules.ignore), 1)
        self.assertEqual(len(rules.permissions), 2)
        self.assertEqual(rules.ignore[0]["id"], "doc-h")
        perm_ids = {r["id"] for r in rules.permissions}
        self.assertEqual(perm_ids, {"doc-ro", "doc-rw"})

    # ── document_permission with both ignore and permissions ──

    def test_ignore_overrides_permissions(self):
        """Legacy ignore rules still take effect (hidden > any permission)."""
        docs = [
            self._make_doc("d1", hpath="/Doc1"),
        ]
        rules = PrivacyRules(
            ignore=[{"scope": "document", "id": "d1"}],
            allow=[],
            permissions=[{"scope": "document", "id": "d1", "permission": "read_write"}],
        )
        self.assertEqual(document_permission(docs[0], rules, docs), "hidden")

    # ── Cache round-trip with permissions ──

    def test_privacy_rules_cache_roundtrip_with_permissions(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rules = PrivacyRules(
                ignore=[{"scope": "notebook", "id": "nb-hidden"}],
                allow=[],
                permissions=[
                    {"scope": "notebook", "id": "nb-ro", "permission": "read_only"},
                    {"scope": "document", "id": "doc-ro", "permission": "read_only"},
                ],
            )
            write_privacy_rules_cache(root, rules)
            loaded = load_privacy_rules(root)
            self.assertEqual(len(loaded.ignore), 1)
            self.assertEqual(loaded.ignore[0]["id"], "nb-hidden")
            self.assertEqual(len(loaded.permissions), 2)
            perm_map = {(r["scope"], r["id"]): r["permission"] for r in loaded.permissions}
            self.assertEqual(perm_map[("notebook", "nb-ro")], "read_only")
            self.assertEqual(perm_map[("document", "doc-ro")], "read_only")

    # ── DocManager subtree safety checks ──

    def test_delete_parent_with_read_only_child_requires_subtree_check(self):
        """If parent is read_write but has a read_only descendant, delete should be
        rejected for the subtree as a whole. This test documents the desired behavior:
        a helper function should collect all descendants and fail if any are non-read_write."""
        docs = [
            self._make_doc("parent-rw", hpath="/ParentRW"),
            self._make_doc("child-ro", hpath="/ParentRW/ChildRO"),
        ]
        rules = PrivacyRules(
            ignore=[],
            allow=[],
            permissions=[{"scope": "document", "id": "child-ro", "permission": "read_only"}],
        )
        self.assertEqual(document_permission(docs[0], rules, docs), "read_write")
        self.assertEqual(document_permission(docs[1], rules, docs), "read_only")
        # Demonstrating the gap: parent passes, but subtree has restricted descendants
        # A subtree-aware check would scan descendants:
        parent_hpath = "/ParentRW"
        descendants_perms = [
            document_permission(d, rules, docs)
            for d in docs
            if d["hpath"].startswith(parent_hpath + "/")
        ]
        self.assertIn("read_only", descendants_perms)
        # The subtree is NOT safe for delete/move

    def test_delete_parent_with_hidden_child_requires_subtree_check(self):
        """If parent is read_write but has a hidden descendant, same safety gap."""
        docs = [
            self._make_doc("parent-rw", hpath="/ParentRW"),
            self._make_doc("child-hidden", hpath="/ParentRW/ChildHidden"),
        ]
        rules = PrivacyRules(
            ignore=[],
            allow=[],
            permissions=[{"scope": "document", "id": "child-hidden", "permission": "hidden"}],
        )
        self.assertEqual(document_permission(docs[0], rules, docs), "read_write")
        self.assertEqual(document_permission(docs[1], rules, docs), "hidden")
        # Gap: parent passes, hidden child is exposed through delete/move

    def test_delete_parent_all_descendants_read_write_allowed(self):
        """Parent is read_write and all descendants are read_write — safe to delete."""
        docs = [
            self._make_doc("parent-rw", hpath="/ParentRW"),
            self._make_doc("child-rw", hpath="/ParentRW/ChildRW"),
        ]
        rules = PrivacyRules(ignore=[], allow=[])
        parent_hpath = "/ParentRW"
        all_ok = all(
            document_permission(d, rules, docs) == "read_write"
            for d in docs
            if d["hpath"].startswith(parent_hpath + "/")
        )
        self.assertTrue(all_ok)


if __name__ == "__main__":
    unittest.main()
