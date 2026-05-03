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
        self.base_url = "http://127.0.0.1:6806"
        self.opened: list[str] = []
        self.closed_again: list[str] = []
        self.seen_payloads: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._docs: dict[str, str] = {}  # doc_id -> markdown
        self._blocks: dict[str, dict[str, Any]] = {}  # block_id -> block info
        self._push_msgs: list[str] = []

    def version(self):
        return "3.0.0"

    def list_notebooks(self):
        return [{"id": "nb1", "name": "Main", "closed": self.closed}]

    def open_notebook(self, notebook_id):
        self.opened.append(notebook_id)
        self.closed = False

    def close_notebook(self, notebook_id):
        self.closed_again.append(notebook_id)
        self.closed = True

    def query_sql(self, _stmt):
        stmt = str(_stmt).casefold() if _stmt else ""
        if "from blocks" in stmt and "root_id" in stmt:
            # Return the first available blocks set for any document-root query
            for blocks in self._blocks.values():
                if isinstance(blocks, list):
                    return blocks
            return []
        return [{"exists": 1}]

    def search_full_text(self, **payload):
        self.seen_payloads.append(payload)
        return {"blocks": self.blocks}

    # Write methods
    def create_snapshot(self, memo):
        snap = {"memo": memo, "created": "20260503000000"}
        self._snapshots.append(snap)
        return snap

    def create_doc_with_md(self, notebook, path, markdown):
        doc_id = f"new-doc-{len(self._docs)}"
        self._docs[doc_id] = markdown
        return {"id": doc_id}

    def update_block(self, block_id, markdown):
        pass

    def append_block(self, parent_id, markdown):
        pass

    def push_msg(self, msg, timeout=7000):
        self._push_msgs.append(msg)


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
            {
                "id": "doc3",
                "notebook_id": "nb1",
                "notebook_name": "Main",
                "hpath": "/Projects/Doc One/Child",
                "title": "Child",
                "path": "/doc3.sy",
                "tags": [],
                "word_count": 30,
                "block_count": 1,
                "updated": "20260501010103",
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

    def test_find_documents_document_privacy_hides_child_live_results(self):
        (self.root / "siyuan.ignore.local.json").write_text(
            json.dumps({"ignore": [{"scope": "document", "id": "doc1"}]}, ensure_ascii=False),
            encoding="utf-8",
        )
        client = FakeSearchClient([
            {
                "id": "block3",
                "rootID": "doc3",
                "box": "nb1",
                "type": "NodeParagraph",
                "markdown": "子文档里有密匙。",
                "content": "子文档里有<mark>密匙</mark>。",
                "hPath": "/Projects/Doc One/Child",
                "path": "/doc1/doc3.sy",
            }
        ])
        output = self.run_find(client, {"keyword": "密匙", "mode": "keyword", "scope": "full", "notebooks": "nb1"})

        self.assertIn("No matching visible documents", output)
        self.assertNotIn("doc3", output)

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


class McpServerWriteTests(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / ".test_tmp" / "mcp_write"
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
                "block_count": 2,
                "updated": "20260501010101",
            },
        ]
        (base / "docs.jsonl").write_text(
            "".join(json.dumps(doc, ensure_ascii=False) + "\n" for doc in docs),
            encoding="utf-8",
        )

    def _make_client(self, query_sql_blocks=None):
        """Create a FakeSearchClient with optional block data for SQL queries."""
        client = FakeSearchClient([])
        if query_sql_blocks:
            doc_id = list(query_sql_blocks.keys())[0] if query_sql_blocks else "doc1"
            client._blocks = query_sql_blocks
        return client

    def _server_and_client(self, query_sql_blocks=None):
        client = self._make_client(query_sql_blocks)
        server = mcp_server.McpServer(self.root)
        original = mcp_server.get_working_client

        def fake_client(_config):
            return client

        mcp_server.get_working_client = fake_client
        return server, client, original

    def test_create_document_refuses_unconfirmed(self):
        server, client, original = self._server_and_client()
        try:
            with self.assertRaises(ValueError) as ctx:
                server.siyuan_create_document({
                    "notebook_id": "nb1",
                    "title": "New Doc",
                    "markdown": "# Hello",
                    "confirmed": False,
                })
            self.assertIn("confirmed", str(ctx.exception))
        finally:
            mcp_server.get_working_client = original

    def test_create_document_refuses_hidden_notebook(self):
        server, client, original = self._server_and_client()
        try:
            with self.assertRaises(ValueError) as ctx:
                server.siyuan_create_document({
                    "notebook_id": "nb-hidden",
                    "title": "New Doc",
                    "markdown": "# Hello",
                    "confirmed": True,
                })
            self.assertIn("not visible", str(ctx.exception))
        finally:
            mcp_server.get_working_client = original

    def test_create_document_creates_snapshot_before_write(self):
        server, client, original = self._server_and_client()
        try:
            result = server.siyuan_create_document({
                "notebook_id": "nb1",
                "title": "New Doc",
                "markdown": "# Hello\n\nWorld",
                "confirmed": True,
            })
            self.assertIn("New Doc", result)
            self.assertIn("created", result)
            self.assertEqual(len(client._snapshots), 1)
            self.assertIn("siyuan-agent-bridge:auto-snapshot", client._snapshots[0]["memo"])
            self.assertIn("tool=siyuan_create_document", client._snapshots[0]["memo"])
            self.assertIn("target=New Doc", client._snapshots[0]["memo"])
            self.assertIn("New Doc", client._push_msgs[0])
        finally:
            mcp_server.get_working_client = original

    def test_create_document_uses_given_path(self):
        server, client, original = self._server_and_client()
        try:
            result = server.siyuan_create_document({
                "notebook_id": "nb1",
                "title": "My Doc",
                "path": "/custom/path",
                "markdown": "content",
                "confirmed": True,
            })
            self.assertIn("custom/path", result)
        finally:
            mcp_server.get_working_client = original

    def test_edit_document_refuses_unconfirmed(self):
        server, client, original = self._server_and_client()
        try:
            with self.assertRaises(ValueError) as ctx:
                server.siyuan_edit_document({
                    "document_id": "doc1",
                    "old_text": "hello",
                    "new_text": "world",
                    "confirmed": False,
                })
            self.assertIn("confirmed", str(ctx.exception))
        finally:
            mcp_server.get_working_client = original

    def test_edit_document_old_text_not_found(self):
        blocks = {
            "doc1": [
                {"id": "block1", "markdown": "This is some text."},
                {"id": "block2", "markdown": "Another paragraph."},
            ]
        }
        server, client, original = self._server_and_client(query_sql_blocks=blocks)
        try:
            with self.assertRaises(ValueError) as ctx:
                server.siyuan_edit_document({
                    "document_id": "doc1",
                    "old_text": "nonexistent text",
                    "new_text": "replacement",
                    "confirmed": True,
                })
            self.assertIn("not found", str(ctx.exception))
        finally:
            mcp_server.get_working_client = original

    def test_edit_document_old_text_ambiguous(self):
        blocks = {
            "doc1": [
                {"id": "block1", "markdown": "重复文字在这里。"},
                {"id": "block2", "markdown": "这里也有重复文字。"},
            ]
        }
        server, client, original = self._server_and_client(query_sql_blocks=blocks)
        try:
            with self.assertRaises(ValueError) as ctx:
                server.siyuan_edit_document({
                    "document_id": "doc1",
                    "old_text": "重复文字",
                    "new_text": "替换",
                    "confirmed": True,
                })
            self.assertIn("multiple blocks", str(ctx.exception).casefold())
            self.assertIn("block1", str(ctx.exception))
            self.assertIn("block2", str(ctx.exception))
        finally:
            mcp_server.get_working_client = original

    def test_edit_document_single_block_full_replace(self):
        blocks = {
            "doc1": [
                {"id": "block1", "markdown": "Original full text."},
            ]
        }
        server, client, original = self._server_and_client(query_sql_blocks=blocks)
        try:
            result = server.siyuan_edit_document({
                "document_id": "doc1",
                "old_text": "Original full text.",
                "new_text": "Replaced text.",
                "confirmed": True,
            })
            self.assertIn("Document Edited", result)
            self.assertIn("block1", result)
            self.assertIn("Replaced text.", result)
            self.assertEqual(len(client._snapshots), 1)
            self.assertIn("siyuan_edit_document", client._snapshots[0]["memo"])
        finally:
            mcp_server.get_working_client = original

    def test_edit_document_single_block_substring_replace(self):
        blocks = {
            "doc1": [
                {"id": "block1", "markdown": "这里包含旧文字和其他内容。"},
            ]
        }
        server, client, original = self._server_and_client(query_sql_blocks=blocks)
        try:
            result = server.siyuan_edit_document({
                "document_id": "doc1",
                "old_text": "旧文字",
                "new_text": "新文字",
                "confirmed": True,
            })
            self.assertIn("Document Edited", result)
            self.assertIn("block1", result)
        finally:
            mcp_server.get_working_client = original

    def test_edit_document_append_mode(self):
        blocks = {
            "doc1": [
                {"id": "block1", "markdown": "Existing text."},
            ]
        }
        server, client, original = self._server_and_client(query_sql_blocks=blocks)
        try:
            result = server.siyuan_edit_document({
                "document_id": "doc1",
                "old_text": "",
                "new_text": "Appended paragraph.",
                "confirmed": True,
            })
            self.assertIn("append", result.casefold())
            self.assertEqual(len(client._snapshots), 1)
            self.assertIn("siyuan_edit_document", client._snapshots[0]["memo"])
        finally:
            mcp_server.get_working_client = original

    def test_edit_document_delete_mode(self):
        blocks = {
            "doc1": [
                {"id": "block1", "markdown": "待删除的错误文字在这里。"},
            ]
        }
        server, client, original = self._server_and_client(query_sql_blocks=blocks)
        try:
            result = server.siyuan_edit_document({
                "document_id": "doc1",
                "old_text": "待删除的错误文字",
                "new_text": "",
                "confirmed": True,
            })
            self.assertIn("Document Edited", result)
        finally:
            mcp_server.get_working_client = original

    def test_edit_document_refuses_hidden_document(self):
        (self.root / "siyuan.ignore.local.json").write_text(
            json.dumps({"ignore": [{"scope": "document", "id": "doc1"}]}, ensure_ascii=False),
            encoding="utf-8",
        )
        server, client, original = self._server_and_client()
        try:
            with self.assertRaises(ValueError) as ctx:
                server.siyuan_edit_document({
                    "document_id": "doc1",
                    "old_text": "hello",
                    "new_text": "world",
                    "confirmed": True,
                })
            self.assertIn("visible", str(ctx.exception).casefold())
        finally:
            mcp_server.get_working_client = original

    def test_edit_document_both_empty_rejected(self):
        server, client, original = self._server_and_client()
        try:
            with self.assertRaises(ValueError) as ctx:
                server.siyuan_edit_document({
                    "document_id": "doc1",
                    "old_text": "",
                    "new_text": "",
                    "confirmed": True,
                })
            self.assertIn("cannot both be empty", str(ctx.exception).casefold())
        finally:
            mcp_server.get_working_client = original

    def test_normalize_markdown_strips_duplicate_h1(self):
        result = mcp_server.normalize_new_document_markdown(
            "My Title",
            "# My Title\n\nBody text.",
        )
        self.assertEqual(result, "\nBody text.")

    def test_normalize_markdown_keeps_different_h1(self):
        result = mcp_server.normalize_new_document_markdown(
            "My Title",
            "# Different Title\n\nBody text.",
        )
        self.assertEqual(result, "# Different Title\n\nBody text.")

    def test_normalize_markdown_skips_leading_empty_lines(self):
        result = mcp_server.normalize_new_document_markdown(
            "My Title",
            "\n\n# My Title\n\nBody text.",
        )
        self.assertEqual(result, "\n\n\nBody text.")

    def test_normalize_markdown_ignores_h2(self):
        result = mcp_server.normalize_new_document_markdown(
            "My Title",
            "## My Title\n\nBody text.",
        )
        self.assertEqual(result, "## My Title\n\nBody text.")

    def test_create_document_strips_duplicate_h1(self):
        server, client, original = self._server_and_client()
        try:
            result = server.siyuan_create_document({
                "notebook_id": "nb1",
                "title": "My Doc",
                "markdown": "# My Doc\n\nContent here.",
                "confirmed": True,
            })
            self.assertIn("文档创建成功", result)
            self.assertIn("Content here.", client._docs["new-doc-0"])
            self.assertNotIn("# My Doc", client._docs["new-doc-0"])
        finally:
            mcp_server.get_working_client = original

    def test_create_document_keeps_different_h1(self):
        server, client, original = self._server_and_client()
        try:
            result = server.siyuan_create_document({
                "notebook_id": "nb1",
                "title": "My Doc",
                "markdown": "# Other Title\n\nContent here.",
                "confirmed": True,
            })
            self.assertIn("文档创建成功", result)
            self.assertIn("# Other Title", client._docs["new-doc-0"])
        finally:
            mcp_server.get_working_client = original

    def test_create_document_rejects_empty_after_h1_removal(self):
        server, client, original = self._server_and_client()
        try:
            with self.assertRaises(ValueError) as ctx:
                server.siyuan_create_document({
                    "notebook_id": "nb1",
                    "title": "My Doc",
                    "markdown": "# My Doc",
                    "confirmed": True,
                })
            self.assertIn("markdown", str(ctx.exception).casefold())
        finally:
            mcp_server.get_working_client = original


if __name__ == "__main__":
    unittest.main()
