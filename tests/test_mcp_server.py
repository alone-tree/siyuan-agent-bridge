from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from typing import Any

from source_code import mcp_server


class FakeSearchClient:
    def __init__(self, blocks: list[dict[str, Any]], *, closed: bool = False):
        self.blocks = blocks
        self.closed = closed
        self.opened: list[str] = []
        self.closed_again: list[str] = []
        self.seen_payloads: list[dict[str, Any]] = []

    def list_notebooks(self):
        return [{"id": "nb1", "name": "Main", "closed": self.closed}]

    def open_notebook(self, notebook_id):
        self.opened.append(notebook_id)
        self.closed = False

    def close_notebook(self, notebook_id):
        self.closed_again.append(notebook_id)
        self.closed = True

    def query_sql(self, _stmt):
        return [{"exists": 1}]

    def search_full_text(self, **payload):
        self.seen_payloads.append(payload)
        return {"blocks": self.blocks}


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / ".test_tmp" / "mcp_find"
        shutil.rmtree(self.root, ignore_errors=True)
        base = self.root / "knowledge_base"
        base.mkdir(parents=True, exist_ok=True)
        (base / "notebooks.json").write_text(
            json.dumps([{"id": "nb1", "name": "Main"}], ensure_ascii=False),
            encoding="utf-8",
        )
        docs = [
            {
                "id": "doc1",
                "notebook_id": "nb1",
                "notebook_name": "Main",
                "hpath": "/Projects/Doc One",
                "title": "Doc One",
                "path": "/doc1.sy",
                "tags": [],
                "word_count": 123,
                "block_count": 4,
                "updated": "20260501010101",
            },
            {
                "id": "doc2",
                "notebook_id": "nb1",
                "notebook_name": "Main",
                "hpath": "/Projects/Hidden",
                "title": "Hidden",
                "path": "/doc2.sy",
                "tags": [],
                "word_count": 50,
                "block_count": 2,
                "updated": "20260501010102",
            },
        ]
        (base / "docs.jsonl").write_text(
            "".join(json.dumps(doc, ensure_ascii=False) + "\n" for doc in docs),
            encoding="utf-8",
        )

    def test_find_documents_uses_live_full_text_blocks(self):
        client = FakeSearchClient([
            {
                "id": "block1",
                "rootID": "doc1",
                "box": "nb1",
                "type": "NodeParagraph",
                "markdown": "正文里有机器人这个词。",
                "content": "正文里有<mark>机器人</mark>这个词。",
                "hPath": "/Projects/Doc One",
                "path": "/doc1.sy",
            }
        ])
        output = self.run_find(client, {"keyword": "机器人", "mode": "keyword", "scope": "full", "notebooks": "nb1"})

        self.assertIn("doc1", output)
        self.assertIn("正文里有机器人这个词", output)
        self.assertIn("live search", output)
        self.assertEqual(client.seen_payloads[0]["paths"], ["nb1"])
        self.assertEqual(client.seen_payloads[0]["group_by"], 0)

    def test_find_documents_keeps_all_matching_blocks_per_document(self):
        client = FakeSearchClient([
            {
                "id": "block1",
                "rootID": "doc1",
                "box": "nb1",
                "type": "NodeParagraph",
                "markdown": "第一个密匙在这里。",
                "content": "第一个<mark>密匙</mark>在这里。",
                "hPath": "/Projects/Doc One",
                "path": "/doc1.sy",
            },
            {
                "id": "block2",
                "rootID": "doc1",
                "box": "nb1",
                "type": "NodeParagraph",
                "markdown": "第二个密匙也在这里。",
                "content": "第二个<mark>密匙</mark>也在这里。",
                "hPath": "/Projects/Doc One",
                "path": "/doc1.sy",
            },
        ])
        output = self.run_find(client, {"keyword": "密匙", "mode": "keyword", "scope": "full", "notebooks": "nb1"})

        self.assertIn("block1", output)
        self.assertIn("block2", output)
        self.assertIn("命中块：共 2 个，展示前 2 个。", output)
        self.assertIn("第一个密匙", output)
        self.assertIn("第二个密匙", output)

    def test_find_documents_limits_displayed_blocks_per_document(self):
        blocks = []
        for index in range(6):
            number = index + 1
            blocks.append({
                "id": f"block{number}",
                "rootID": "doc1",
                "box": "nb1",
                "type": "NodeParagraph",
                "markdown": f"第{number}个密匙在这里。",
                "content": f"第{number}个<mark>密匙</mark>在这里。",
                "hPath": "/Projects/Doc One",
                "path": "/doc1.sy",
            })
        client = FakeSearchClient(blocks)
        output = self.run_find(client, {"keyword": "密匙", "mode": "keyword", "scope": "full", "notebooks": "nb1"})

        self.assertIn("命中块：共 6 个，展示前 5 个。", output)
        self.assertIn("block5", output)
        self.assertNotIn("block6", output)

    def test_find_documents_allows_adjusting_displayed_blocks_per_document(self):
        blocks = []
        for index in range(6):
            number = index + 1
            blocks.append({
                "id": f"block{number}",
                "rootID": "doc1",
                "box": "nb1",
                "type": "NodeParagraph",
                "markdown": f"第{number}个密匙在这里。",
                "content": f"第{number}个<mark>密匙</mark>在这里。",
                "hPath": "/Projects/Doc One",
                "path": "/doc1.sy",
            })
        client = FakeSearchClient(blocks)
        output = self.run_find(client, {
            "keyword": "密匙",
            "mode": "keyword",
            "scope": "full",
            "notebooks": "nb1",
            "max_snippets_per_doc": 6,
        })

        self.assertIn("命中块：共 6 个，展示前 6 个。", output)
        self.assertIn("block6", output)

    def test_find_documents_filters_live_results_with_privacy_rules(self):
        (self.root / "siyuan.ignore.local.json").write_text(
            json.dumps({"ignore": [{"scope": "document", "id": "doc2"}]}, ensure_ascii=False),
            encoding="utf-8",
        )
        client = FakeSearchClient([
            {
                "id": "block2",
                "rootID": "doc2",
                "box": "nb1",
                "type": "NodeParagraph",
                "markdown": "隐藏正文里有机器人。",
                "content": "隐藏正文里有<mark>机器人</mark>。",
                "hPath": "/Projects/Hidden",
                "path": "/doc2.sy",
            }
        ])
        output = self.run_find(client, {"keyword": "机器人", "mode": "keyword", "scope": "full", "notebooks": "nb1"})

        self.assertIn("No matching visible documents", output)
        self.assertNotIn("doc2", output)

    def test_find_documents_filters_notebook_name_rules_with_live_names(self):
        (self.root / "siyuan.ignore.local.json").write_text(
            json.dumps({"ignore": [{"scope": "notebook", "name": "Main"}]}, ensure_ascii=False),
            encoding="utf-8",
        )
        client = FakeSearchClient([
            {
                "id": "block1",
                "rootID": "doc1",
                "box": "nb1",
                "type": "NodeParagraph",
                "markdown": "正文里有机器人。",
                "content": "正文里有<mark>机器人</mark>。",
                "hPath": "/Projects/Doc One",
                "path": "/doc1.sy",
            }
        ])
        output = self.run_find(client, {"keyword": "机器人", "mode": "keyword", "scope": "full", "notebooks": "nb1"})

        self.assertIn("No matching visible documents", output)
        self.assertNotIn("doc1", output)

    def test_find_documents_temporarily_opens_closed_notebooks(self):
        client = FakeSearchClient([
            {
                "id": "block1",
                "rootID": "doc1",
                "box": "nb1",
                "type": "NodeParagraph",
                "markdown": "关闭笔记本里的机器人。",
                "content": "关闭笔记本里的<mark>机器人</mark>。",
                "hPath": "/Projects/Doc One",
                "path": "/doc1.sy",
            }
        ], closed=True)
        output = self.run_find(client, {"keyword": "机器人", "mode": "keyword", "scope": "full", "notebooks": "nb1"})

        self.assertIn("doc1", output)
        self.assertEqual(client.opened, ["nb1"])
        self.assertEqual(client.closed_again, ["nb1"])

    def run_find(self, client: FakeSearchClient, args: dict[str, Any]) -> str:
        server = mcp_server.McpServer(self.root)
        original = mcp_server.get_working_client

        def fake_client(_config):
            return client

        mcp_server.get_working_client = fake_client
        try:
            return server.siyuan_find_documents(args)
        finally:
            mcp_server.get_working_client = original


if __name__ == "__main__":
    unittest.main()
