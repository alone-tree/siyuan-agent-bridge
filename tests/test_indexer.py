from __future__ import annotations

import json
import unittest
from pathlib import Path

from source_code.ignore import PrivacyRules, filter_documents
from source_code.indexer import find_documents, normalize_documents, refresh_index, resolve_document


class FakeClient:
    def list_notebooks(self):
        return [{"id": "nb1", "name": "Main"}]

    def query_sql(self, stmt):
        return [
            {
                "id": "20260429120000-abcdefg",
                "box": "nb1",
                "hpath": "/Projects/SiYuan Enhance",
                "path": "/20260429120000-abcdefg.sy",
                "name": "",
                "content": "SiYuan Enhance",
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
            "20260429120000-abcdefg": "# SiYuan Enhance\n\nThis document has a longer exported body.",
            "20260429130000-hijklmn": "# Other\n\nShort body.",
            "20260429140000-child": "# Child\n\nChild body.",
        }
        return markdown.get(block_id, "")


class IndexerTests(unittest.TestCase):
    def test_refresh_writes_indexes_and_preserves_existing_guide(self):
        root = Path.cwd() / ".test_tmp" / "indexer_refresh"
        root.mkdir(parents=True, exist_ok=True)
        guide = root / "knowledge_base" / "guide.md"
        guide.parent.mkdir(exist_ok=True)
        guide.write_text("keep me\n", encoding="utf-8")

        result = refresh_index(FakeClient(), root)

        self.assertEqual(result.document_count, 2)
        self.assertEqual(guide.read_text(encoding="utf-8"), "keep me\n")
        self.assertTrue((root / "knowledge_base" / "notebooks.json").exists())
        self.assertTrue((root / "knowledge_base" / "docs.jsonl").exists())
        self.assertFalse((root / "knowledge_base" / "overview.md").exists())
        self.assertFalse((root / "knowledge_base" / "notebooks").exists())
        tree = (root / "knowledge_base" / "tree.md").read_text(encoding="utf-8")
        self.assertIn("SiYuan Enhance", tree)
        self.assertIn("20260429120000-abcdefg", tree)
        self.assertIn("| Notebook | ID | Docs | 字数 | 最近更新 |", tree)
        self.assertIn(" 字", tree)

    def test_normalize_documents_extracts_tags(self):
        docs = normalize_documents(FakeClient().query_sql(""), FakeClient().list_notebooks())
        by_id = {doc["id"]: doc for doc in docs}

        self.assertEqual(by_id["20260429120000-abcdefg"]["tags"], ["ai", "notes"])
        self.assertEqual(by_id["20260429120000-abcdefg"]["notebook_name"], "Main")

    def test_refresh_uses_exported_markdown_for_word_count(self):
        root = Path.cwd() / ".test_tmp" / "indexer_word_count"
        root.mkdir(parents=True, exist_ok=True)

        refresh_index(FakeClient(), root)
        docs = {
            doc["id"]: doc
            for doc in (
                json.loads(line)
                for line in (root / "knowledge_base" / "docs.jsonl").read_text(encoding="utf-8").splitlines()
            )
        }

        self.assertGreater(docs["20260429120000-abcdefg"]["word_count"], docs["20260429120000-abcdefg"]["index_word_count"])

    def test_find_and_resolve_documents(self):
        docs = normalize_documents(FakeClient().query_sql(""), FakeClient().list_notebooks())

        matches = find_documents(docs, "siyuan")
        self.assertEqual(matches[0]["id"], "20260429120000-abcdefg")

        status, resolved = resolve_document(docs, "/Projects/SiYuan Enhance")
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
                "hpath": "/Projects/SiYuan Enhance/Child",
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

    def test_temporary_allow_restores_one_hidden_document(self):
        docs = normalize_documents(FakeClient().query_sql(""), FakeClient().list_notebooks())

        visible = filter_documents(
            docs,
            PrivacyRules(
                ignore=[{"scope": "document", "id": "20260429120000-abcdefg"}],
                allow=[{"scope": "document", "id": "20260429120000-abcdefg"}],
            ),
        )

        self.assertIn("20260429120000-abcdefg", {doc["id"] for doc in visible})

    def test_refresh_applies_local_ignore_file(self):
        root = Path.cwd() / ".test_tmp" / "indexer_ignore"
        root.mkdir(parents=True, exist_ok=True)
        (root / "siyuan.ignore.local.json").write_text(
            json.dumps({"ignore": [{"scope": "document", "id": "20260429120000-abcdefg"}]}),
            encoding="utf-8",
        )

        result = refresh_index(FakeClient(), root)
        docs_jsonl = (root / "knowledge_base" / "docs.jsonl").read_text(encoding="utf-8")

        self.assertEqual(result.hidden_document_count, 1)
        self.assertNotIn("20260429120000-abcdefg", docs_jsonl)


if __name__ == "__main__":
    unittest.main()
