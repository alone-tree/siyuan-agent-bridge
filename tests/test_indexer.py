from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from source_code.ignore import (
    PrivacyRules,
    PrivacyRulesParseError,
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
        self.assertIn("Document ID 为空", str(ctx.exception))

    def test_invalid_hide_value_errors(self):
        markdown = """## 隐藏笔记本

| Hide | 笔记本ID（建议填） | 笔记本名称 |
|------|---------------------|------------|
| maybe | nb-test | 测试 |
"""
        with self.assertRaises(PrivacyRulesParseError) as ctx:
            parse_privacy_rules_markdown(markdown)
        self.assertIn("Hide 只能填写", str(ctx.exception))

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
        self.assertIn("Document ID 不存在", str(ctx.exception))

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
        self.assertIn("Hide/Enabled 列", str(ctx.exception))

    def test_missing_header_document_id_column_errors(self):
        markdown = """## 隐藏文档

| Hide | 标题 |
|------|------|
| yes | 测试 |
"""
        with self.assertRaises(PrivacyRulesParseError) as ctx:
            parse_privacy_rules_markdown(markdown)
        self.assertIn("Document ID 列", str(ctx.exception))

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


if __name__ == "__main__":
    unittest.main()
