from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from typing import Any

from source_code import mcp_server
from source_code.config import Profile
from source_code.ignore import PrivacyRules, write_privacy_rules_cache


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

    def create_notebook(self, name):
        return {"id": f"nb-{name}", "name": name}

    def open_notebook(self, notebook_id):
        self.opened.append(notebook_id)
        self.closed = False

    def close_notebook(self, notebook_id):
        self.closed_again.append(notebook_id)
        self.closed = True

    def query_sql(self, _stmt):
        stmt = str(_stmt).casefold() if _stmt else ""
        if "from blocks" in stmt and "root_id" in stmt:
            # Extract root_id from WHERE clause for filtering
            import re
            m = re.search(r"root_id\s*=\s*'([^']+)'", stmt)
            if m:
                doc_id = m.group(1)
                return self._blocks.get(doc_id, [])
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

    def export_markdown(self, block_id):
        if block_id in self._docs:
            return self._docs[block_id]
        return ""

    def get_asset(self, asset_path):
        return b""

    def list_document_blocks(self, doc_id):
        stmt = f"SELECT id, parent_id, root_id, type, subtype, markdown, content, sort FROM blocks WHERE root_id = '{doc_id}' AND type != 'd' ORDER BY sort"
        return self.query_sql(stmt)

    def get_child_blocks(self, block_id):
        blocks = self._blocks.get(block_id)
        if isinstance(blocks, list):
            return blocks
        children = []
        for block_list in self._blocks.values():
            if isinstance(block_list, list):
                children.extend(block for block in block_list if str(block.get("parent_id", "")) == block_id)
        children.sort(key=lambda block: int(block.get("sort", 0)))
        return children


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
        write_privacy_rules_cache(self.root, PrivacyRules(ignore=[], allow=[]))
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
        self.assertIn("实时搜索", output)
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
        write_privacy_rules_cache(
            self.root,
            PrivacyRules(ignore=[{"scope": "document", "id": "doc2"}], allow=[]),
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

        self.assertIn("未找到匹配的可见文档", output)
        self.assertNotIn("doc2", output)

    def test_find_documents_document_privacy_hides_child_live_results(self):
        write_privacy_rules_cache(
            self.root,
            PrivacyRules(ignore=[{"scope": "document", "id": "doc1"}], allow=[]),
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

        self.assertIn("未找到匹配的可见文档", output)
        self.assertNotIn("doc3", output)

    def test_find_documents_filters_notebook_name_rules_with_live_names(self):
        write_privacy_rules_cache(
            self.root,
            PrivacyRules(ignore=[{"scope": "notebook", "name": "Main"}], allow=[]),
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

        self.assertIn("未找到匹配的可见文档", output)
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
        original = mcp_server.detect_active_profile

        profile = Profile(name="test", token="test")
        def fake_detect(_config):
            return profile, client

        mcp_server.detect_active_profile = fake_detect
        try:
            return server.siyuan_find_documents(args)
        finally:
            mcp_server.detect_active_profile = original


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
        write_privacy_rules_cache(self.root, PrivacyRules(ignore=[], allow=[]))
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
        original = mcp_server.detect_active_profile

        profile = Profile(name="test", token="test")
        def fake_detect(_config):
            return profile, client

        mcp_server.detect_active_profile = fake_detect
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
            mcp_server.detect_active_profile = original

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
            self.assertIn("不可见", str(ctx.exception))
        finally:
            mcp_server.detect_active_profile = original

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
            mcp_server.detect_active_profile = original

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
            mcp_server.detect_active_profile = original

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
            mcp_server.detect_active_profile = original

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
            self.assertIn("未找到", str(ctx.exception))
        finally:
            mcp_server.detect_active_profile = original

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
            self.assertIn("匹配到多个块", str(ctx.exception))
            self.assertIn("block1", str(ctx.exception))
            self.assertIn("block2", str(ctx.exception))
        finally:
            mcp_server.detect_active_profile = original

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
            self.assertIn("文档已编辑", result)
            self.assertIn("block1", result)
            self.assertIn("Replaced text.", result)
            self.assertEqual(len(client._snapshots), 1)
            self.assertIn("siyuan_edit_document", client._snapshots[0]["memo"])
        finally:
            mcp_server.detect_active_profile = original

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
            self.assertIn("文档已编辑", result)
            self.assertIn("block1", result)
        finally:
            mcp_server.detect_active_profile = original

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
            self.assertIn("追加", result)
            self.assertEqual(len(client._snapshots), 1)
            self.assertIn("siyuan_edit_document", client._snapshots[0]["memo"])
        finally:
            mcp_server.detect_active_profile = original

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
            self.assertIn("文档已编辑", result)
        finally:
            mcp_server.detect_active_profile = original

    def test_edit_document_refuses_hidden_document(self):
        write_privacy_rules_cache(
            self.root,
            PrivacyRules(ignore=[{"scope": "document", "id": "doc1"}], allow=[]),
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
            self.assertIn("可见", str(ctx.exception))
        finally:
            mcp_server.detect_active_profile = original

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
            self.assertIn("不能同时为空", str(ctx.exception))
        finally:
            mcp_server.detect_active_profile = original

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
            mcp_server.detect_active_profile = original

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
            mcp_server.detect_active_profile = original

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
            mcp_server.detect_active_profile = original


class BlockIdBuildTests(unittest.TestCase):
    """Tests for build_markdown_from_blocks — builds markdown directly from blocks."""

    def test_builds_markdown_with_comments(self):
        blocks = [
            {"id": "block-h1", "type": "h", "subtype": "h2", "markdown": "## My Heading", "content": "My Heading"},
            {"id": "block-p1", "type": "p", "subtype": "", "markdown": "Some paragraph text here.", "content": "Some paragraph text here."},
        ]
        result = mcp_server.build_markdown_from_blocks(blocks)
        self.assertIn("<!-- siyuan:block id=block-h1 type=h subtype=h2 -->", result)
        self.assertIn("## My Heading", result)
        self.assertIn("<!-- siyuan:block id=block-p1 type=p -->", result)
        self.assertIn("Some paragraph text here.", result)

    def test_skips_list_container_type(self):
        blocks = [
            {"id": "list-cont", "type": "l", "subtype": "u", "markdown": "* item 1\n* item 2", "content": ""},
            {"id": "item-1", "type": "i", "subtype": "u", "markdown": "* item 1", "content": ""},
        ]
        result = mcp_server.build_markdown_from_blocks(blocks)
        self.assertNotIn("list-cont", result)
        self.assertIn("item-1", result)

    def test_skips_empty_markdown(self):
        blocks = [
            {"id": "block1", "type": "p", "subtype": "", "markdown": "Visible text here.", "content": ""},
            {"id": "block2", "type": "p", "subtype": "", "markdown": "", "content": ""},
        ]
        result = mcp_server.build_markdown_from_blocks(blocks)
        self.assertIn("block1", result)
        self.assertNotIn("block2", result)

    def test_handles_empty_blocks_list(self):
        result = mcp_server.build_markdown_from_blocks([])
        self.assertEqual(result, "")

    def test_skips_document_type(self):
        blocks = [
            {"id": "doc-root", "type": "d", "subtype": "", "markdown": "root", "content": ""},
            {"id": "block-p1", "type": "p", "subtype": "", "markdown": "Body text.", "content": ""},
        ]
        result = mcp_server.build_markdown_from_blocks(blocks)
        self.assertNotIn("doc-root", result)
        self.assertIn("block-p1", result)

    def test_duplicate_text_each_gets_own_id(self):
        blocks = [
            {"id": "block-a", "type": "p", "subtype": "", "markdown": "重复文本", "content": ""},
            {"id": "block-b", "type": "p", "subtype": "", "markdown": "重复文本", "content": ""},
        ]
        result = mcp_server.build_markdown_from_blocks(blocks)
        self.assertIn("block-a", result)
        self.assertIn("block-b", result)
        self.assertEqual(result.count("<!-- siyuan:block "), 2)

    def test_tree_order_uses_parent_then_sort(self):
        blocks = [
            {"id": "a", "parent_id": "doc1", "root_id": "doc1", "type": "p", "subtype": "", "markdown": "A", "sort": 1},
            {"id": "b", "parent_id": "doc1", "root_id": "doc1", "type": "p", "subtype": "", "markdown": "B", "sort": 2},
            {"id": "a1", "parent_id": "a", "root_id": "doc1", "type": "p", "subtype": "", "markdown": "A1", "sort": 1},
            {"id": "b1", "parent_id": "b", "root_id": "doc1", "type": "p", "subtype": "", "markdown": "B1", "sort": 1},
        ]
        result = mcp_server.build_markdown_from_blocks(blocks, root_id="doc1")
        self.assertLess(result.index("id=a "), result.index("id=a1 "))
        self.assertLess(result.index("id=a1 "), result.index("id=b "))
        self.assertLess(result.index("id=b "), result.index("id=b1 "))

    def test_list_item_does_not_duplicate_child_paragraph(self):
        blocks = [
            {"id": "list", "parent_id": "doc1", "root_id": "doc1", "type": "l", "subtype": "u", "markdown": "- item", "sort": 1},
            {"id": "item", "parent_id": "list", "root_id": "doc1", "type": "i", "subtype": "u", "markdown": "- item", "sort": 1},
            {"id": "leaf", "parent_id": "item", "root_id": "doc1", "type": "p", "subtype": "", "markdown": "item", "sort": 1},
        ]
        result = mcp_server.build_markdown_from_blocks(blocks, root_id="doc1")
        self.assertNotIn("id=list", result)
        self.assertIn("id=item", result)
        self.assertNotIn("id=leaf", result)

    def test_superblock_comment_only_then_children(self):
        blocks = [
            {"id": "super", "parent_id": "doc1", "root_id": "doc1", "type": "s", "subtype": "", "markdown": "{{{col\nA\n\n}}}", "sort": 1},
            {"id": "leaf", "parent_id": "super", "root_id": "doc1", "type": "p", "subtype": "", "markdown": "A", "sort": 1},
        ]
        result = mcp_server.build_markdown_from_blocks(blocks, root_id="doc1")
        self.assertIn("id=super", result)
        self.assertIn("id=leaf", result)
        self.assertNotIn("{{{col", result)

    def test_child_blocks_builder_uses_api_order(self):
        class ChildClient:
            def __init__(self):
                self.children = {
                    "doc1": [
                        {"id": "b", "type": "p", "markdown": "B"},
                        {"id": "a", "type": "p", "markdown": "A"},
                    ]
                }

            def get_child_blocks(self, block_id):
                return self.children.get(block_id, [])

        result = mcp_server.build_markdown_from_child_blocks(ChildClient(), "doc1")
        self.assertLess(result.index("id=b "), result.index("id=a "))


# ── Token estimation tests ────────────────────────────────────────────

class TokenEstimationTests(unittest.TestCase):
    def test_empty_string_returns_zero(self):
        self.assertEqual(mcp_server.estimate_token_count(""), 0)

    def test_pure_cjk(self):
        tokens = mcp_server.estimate_token_count("人工智能芯片市场分析报告")
        # 10 CJK chars * 1.0 = 10
        self.assertGreater(tokens, 8)
        self.assertLessEqual(tokens, 12)

    def test_pure_english(self):
        tokens = mcp_server.estimate_token_count("The quick brown fox jumps over the lazy dog")
        # 9 words * 1.3 ≈ 11-12
        self.assertGreater(tokens, 9)
        self.assertLess(tokens, 14)

    def test_mixed_cjk_english(self):
        tokens = mcp_server.estimate_token_count("NVIDIA B300 芯片性能分析报告 2026")
        self.assertGreater(tokens, 6)
        self.assertLess(tokens, 20)

    def test_digits_count_lower(self):
        tokens = mcp_server.estimate_token_count("12345")
        # 5 digits * 0.8 = 4
        self.assertGreater(tokens, 3)
        self.assertLess(tokens, 6)

    def test_table_row(self):
        tokens = mcp_server.estimate_token_count("| 指标 | 数值 | 增长率 |")
        # some bars, some cjk, some spaces
        self.assertGreater(tokens, 3)
        self.assertLess(tokens, 15)


# ── Display block building tests ──────────────────────────────────────

class DisplayBlockBuildTests(unittest.TestCase):
    def _make_client(self, blocks_for_doc):
        class ChildClient:
            def __init__(self, blocks):
                self.blocks = blocks

            def get_child_blocks(self, block_id):
                return self.blocks.get(block_id, [])

        return ChildClient(blocks_for_doc)

    def test_builds_ordered_display_blocks(self):
        client = self._make_client({
            "doc1": [
                {"id": "h1", "type": "h", "subtype": "h2", "markdown": "## Hello"},
                {"id": "p1", "type": "p", "markdown": "World"},
            ]
        })
        blocks = mcp_server.build_display_blocks(client, "doc1")
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].index, 1)
        self.assertEqual(blocks[0].id, "h1")
        self.assertTrue(blocks[0].is_heading)
        self.assertEqual(blocks[0].heading_level, 2)
        self.assertEqual(blocks[1].index, 2)
        self.assertEqual(blocks[1].id, "p1")
        self.assertFalse(blocks[1].is_heading)

    def test_skips_list_container(self):
        client = self._make_client({
            "doc1": [
                {"id": "list", "type": "l", "subtype": "u", "markdown": "- item 1\n- item 2"},
                {"id": "item", "type": "i", "subtype": "u", "markdown": "- item 1"},
            ]
        })
        blocks = mcp_server.build_display_blocks(client, "doc1")
        ids = [b.id for b in blocks]
        self.assertNotIn("list", ids)
        self.assertIn("item", ids)

    def test_include_block_ids_injects_comments(self):
        client = self._make_client({
            "doc1": [
                {"id": "p1", "type": "p", "markdown": "Text here."},
            ]
        })
        blocks = mcp_server.build_display_blocks(client, "doc1", include_block_ids=True)
        self.assertIn("<!-- siyuan:block id=p1 type=p -->", blocks[0].markdown)
        self.assertIn("Text here.", blocks[0].markdown)

    def test_no_comments_when_ids_off(self):
        client = self._make_client({
            "doc1": [
                {"id": "p1", "type": "p", "markdown": "Text here."},
            ]
        })
        blocks = mcp_server.build_display_blocks(client, "doc1", include_block_ids=False)
        self.assertEqual(blocks[0].markdown, "Text here.")

    def test_heading_detection(self):
        client = self._make_client({
            "doc1": [
                {"id": "h1", "type": "h", "subtype": "h1", "markdown": "# Main"},
                {"id": "h2", "type": "h", "subtype": "h2", "markdown": "## Sub"},
                {"id": "h3", "type": "h", "subtype": "h3", "markdown": "### Subsub"},
            ]
        })
        blocks = mcp_server.build_display_blocks(client, "doc1")
        self.assertEqual(blocks[0].heading_level, 1)
        self.assertEqual(blocks[1].heading_level, 2)
        self.assertEqual(blocks[2].heading_level, 3)
        self.assertEqual(blocks[0].heading_text, "Main")

    def test_recursive_traversal(self):
        client = self._make_client({
            "doc1": [
                {"id": "h1", "type": "h", "subtype": "h2", "markdown": "## Section"},
            ],
            "h1": [
                {"id": "p1", "type": "p", "markdown": "Paragraph under heading."},
            ]
        })
        blocks = mcp_server.build_display_blocks(client, "doc1")
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[1].id, "p1")

    def test_superblock_does_not_duplicate_child_content_in_normal_mode(self):
        client = self._make_client({
            "doc1": [
                {"id": "super", "type": "s", "markdown": "{{{col\nA\n\n}}}"},
            ],
            "super": [
                {"id": "p1", "type": "p", "markdown": "A"},
            ],
        })
        blocks = mcp_server.build_display_blocks(client, "doc1")
        self.assertEqual([b.id for b in blocks], ["p1"])
        self.assertEqual(blocks[0].markdown, "A")

    def test_estimated_tokens_set(self):
        client = self._make_client({
            "doc1": [
                {"id": "p1", "type": "p", "markdown": "Some text for token estimation."},
            ]
        })
        blocks = mcp_server.build_display_blocks(client, "doc1")
        self.assertGreater(blocks[0].estimated_tokens, 0)


# ── Block window outline tests ────────────────────────────────────────

class BlockOutlineTests(unittest.TestCase):
    def test_outline_shows_block_positions(self):
        blocks = [
            mcp_server.DisplayBlock(index=3, id="h1", type="h", subtype="h2", markdown="## Intro", estimated_tokens=5, is_heading=True, heading_level=2, heading_text="Intro"),
            mcp_server.DisplayBlock(index=7, id="h2", type="h", subtype="h3", markdown="### Detail", estimated_tokens=5, is_heading=True, heading_level=3, heading_text="Detail"),
        ]
        # Add some non-heading blocks
        blocks.insert(0, mcp_server.DisplayBlock(index=1, id="p1", type="p", subtype="", markdown="A", estimated_tokens=2))
        blocks.insert(1, mcp_server.DisplayBlock(index=2, id="p2", type="p", subtype="", markdown="B", estimated_tokens=2))
        result = mcp_server.build_block_outline(blocks)
        self.assertIn("block 3", result)
        self.assertIn("## Intro", result)
        self.assertIn("block 7", result)
        self.assertIn("### Detail", result)
        self.assertIn("2 个标题", result)

    def test_outline_no_headings(self):
        blocks = [
            mcp_server.DisplayBlock(index=1, id="p1", type="p", subtype="", markdown="Text", estimated_tokens=2),
        ]
        result = mcp_server.build_block_outline(blocks)
        self.assertIn("文档无标题结构", result)

    def test_outline_hierarchy(self):
        blocks = [
            mcp_server.DisplayBlock(index=1, id="h1", type="h", subtype="h2", markdown="## Parent", estimated_tokens=5, is_heading=True, heading_level=2, heading_text="Parent"),
            mcp_server.DisplayBlock(index=5, id="h2", type="h", subtype="h3", markdown="### Child", estimated_tokens=5, is_heading=True, heading_level=3, heading_text="Child"),
            mcp_server.DisplayBlock(index=10, id="h3", type="h", subtype="h2", markdown="## Sibling", estimated_tokens=5, is_heading=True, heading_level=2, heading_text="Sibling"),
        ]
        result = mcp_server.build_block_outline(blocks)
        # Child should be indented under Parent
        self.assertIn("block 1", result)
        self.assertIn("## Parent", result)
        self.assertIn("block 5", result)
        self.assertIn("### Child", result)
        self.assertIn("block 10", result)
        self.assertIn("## Sibling", result)


# ── Window preview tests ──────────────────────────────────────────────

class WindowPreviewTests(unittest.TestCase):
    def _make_blocks(self, count: int, with_headings: int = 0, start_hlevel: int = 2) -> list:
        blocks = []
        for i in range(1, count + 1):
            if i <= with_headings:
                htext = f"Section {i}"
                blocks.append(mcp_server.DisplayBlock(
                    index=i, id=f"h{i}", type="h", subtype=f"h{start_hlevel}",
                    markdown=f"{'#' * start_hlevel} {htext}", estimated_tokens=5,
                    is_heading=True, heading_level=start_hlevel, heading_text=htext,
                ))
            else:
                blocks.append(mcp_server.DisplayBlock(
                    index=i, id=f"p{i}", type="p", subtype="",
                    markdown=f"Paragraph number {i} with some content to fill space and test preview extraction.", estimated_tokens=10,
                ))
        return blocks

    def test_no_preview_when_enough_headings(self):
        blocks = self._make_blocks(150, with_headings=5)
        result = mcp_server.build_window_preview(blocks)
        self.assertEqual(result, "")

    def test_no_preview_when_few_blocks(self):
        blocks = self._make_blocks(50, with_headings=2)
        result = mcp_server.build_window_preview(blocks)
        self.assertEqual(result, "")

    def test_preview_when_low_headings_many_blocks(self):
        blocks = self._make_blocks(120, with_headings=3)
        result = mcp_server.build_window_preview(blocks)
        self.assertIn("标题较少", result)
        self.assertIn("block 1:", result)
        self.assertIn("block 51:", result)
        self.assertIn("block 101:", result)

    def test_preview_sampling_every_50(self):
        blocks = self._make_blocks(200, with_headings=2)
        result = mcp_server.build_window_preview(blocks)
        self.assertIn("block 1:", result)
        self.assertIn("block 51:", result)
        self.assertIn("block 101:", result)
        self.assertIn("block 151:", result)
        # Should only have 4 samples for 200 blocks
        self.assertEqual(result.count("block "), 4)

    def test_preview_unaffected_by_heading_count_equal_five(self):
        blocks = self._make_blocks(120, with_headings=5)
        result = mcp_server.build_window_preview(blocks)
        self.assertEqual(result, "")


# ── Read document integration tests (new block window path) ───────────

class McpServerReadBlockWindowTests(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / ".test_tmp" / "mcp_blockwin"
        shutil.rmtree(self.root, ignore_errors=True)
        base = self.root / "knowledge_base"
        base.mkdir(parents=True, exist_ok=True)
        (base / "notebooks.json").write_text(
            json.dumps([{"id": "nb1", "name": "Main"}], ensure_ascii=False),
            encoding="utf-8",
        )
        write_privacy_rules_cache(self.root, PrivacyRules(ignore=[], allow=[]))
        docs = [
            {
                "id": "doc1",
                "notebook_id": "nb1",
                "notebook_name": "Main",
                "hpath": "/Test Doc",
                "title": "Test Doc",
                "path": "/doc1.sy",
                "tags": [],
                "word_count": 10,
                "block_count": 3,
                "updated": "20260501010101",
            },
        ]
        (base / "docs.jsonl").write_text(
            "".join(json.dumps(doc, ensure_ascii=False) + "\n" for doc in docs),
            encoding="utf-8",
        )

    def _make_client(self, blocks_for_doc=None):
        class ChildFakeClient(FakeSearchClient):
            def get_child_blocks(self, block_id):
                blocks = self._blocks.get(block_id)
                if isinstance(blocks, list):
                    return blocks
                # Fallback: search across all stored blocks for matching parent_id
                children = []
                for block_list in self._blocks.values():
                    if isinstance(block_list, list):
                        children.extend(b for b in block_list if str(b.get("parent_id", "")) == block_id)
                children.sort(key=lambda b: int(b.get("sort", 0)))
                return children

        client = ChildFakeClient([])
        if blocks_for_doc:
            client._blocks = blocks_for_doc
        client._docs["doc1"] = "## Section\n\nBody text here.\n"
        return client

    def _read(self, args: dict[str, Any], blocks_for_doc=None):
        client = self._make_client(blocks_for_doc)
        server = mcp_server.McpServer(self.root)
        original = mcp_server.detect_active_profile

        profile = Profile(name="test", token="test")
        def fake_detect(_config):
            return profile, client

        mcp_server.detect_active_profile = fake_detect
        try:
            return server.siyuan_read_document(args)
        finally:
            mcp_server.detect_active_profile = original

    def test_default_block_window_mode(self):
        blocks = {
            "doc1": [
                {"id": "h1", "parent_id": "doc1", "type": "h", "subtype": "h2", "markdown": "## Section", "sort": 1},
                {"id": "p1", "parent_id": "doc1", "type": "p", "markdown": "Body text here.", "sort": 2},
            ]
        }
        result = self._read({"document_id": "doc1"}, blocks_for_doc=blocks)
        self.assertIn("普通阅读", result)
        self.assertIn("展示块：", result)
        self.assertIn("估算令牌数：", result)
        self.assertIn("## Section", result)
        self.assertIn("Body text here.", result)
        # Should NOT contain old chunk header
        self.assertNotIn("Chunk ", result)

    def test_block_window_header_shows_range(self):
        blocks = {
            "doc1": [
                {"id": "h1", "parent_id": "doc1", "type": "h", "subtype": "h2", "markdown": "## Section", "sort": 1},
                {"id": "p1", "parent_id": "doc1", "type": "p", "markdown": "Body text here.", "sort": 2},
            ]
        }
        result = self._read({"document_id": "doc1"}, blocks_for_doc=blocks)
        self.assertIn("展示块：1-2 / 2", result)

    def test_block_start_pagination(self):
        blocks = {
            "doc1": [
                {"id": "h1", "parent_id": "doc1", "type": "h", "subtype": "h2", "markdown": "## First", "sort": 1},
                {"id": "p1", "parent_id": "doc1", "type": "p", "markdown": "First paragraph.", "sort": 2},
                {"id": "h2", "parent_id": "doc1", "type": "h", "subtype": "h2", "markdown": "## Second", "sort": 3},
                {"id": "p2", "parent_id": "doc1", "type": "p", "markdown": "Second paragraph.", "sort": 4},
            ]
        }
        result = self._read({"document_id": "doc1", "block_start": 3}, blocks_for_doc=blocks)
        self.assertIn("展示块：3-4 / 4", result)
        # Body (after last ---) should contain Second but not First
        body_start = result.rindex("---")
        body = result[body_start:]
        self.assertIn("## Second", body)
        self.assertIn("Second paragraph.", body)
        self.assertNotIn("## First", body)
        # Outline (above body) still shows all headings
        self.assertIn("block 1: ## First", result)

    def test_block_limit_restricts_window(self):
        blocks = {}
        blocks["doc1"] = []
        for i in range(10):
            blocks["doc1"].append({
                "id": f"p{i}", "parent_id": "doc1", "type": "p",
                "markdown": f"Paragraph {i}.", "sort": i,
            })
        result = self._read({"document_id": "doc1", "block_limit": 3}, blocks_for_doc=blocks)
        self.assertIn("展示块：1-3 / 10", result)
        self.assertIn("Paragraph 0.", result)
        self.assertIn("Paragraph 2.", result)
        self.assertNotIn("Paragraph 3.", result)

    def test_token_budget_stops_at_block_boundary(self):
        blocks = {
            "doc1": [
                {"id": "p1", "parent_id": "doc1", "type": "p", "markdown": "Short.", "sort": 1},
                {"id": "p2", "parent_id": "doc1", "type": "p", "markdown": "Another.", "sort": 2},
                {"id": "p3", "parent_id": "doc1", "type": "p", "markdown": "A" + "x" * 500 + " really long paragraph that would blow budget.", "sort": 3},
            ]
        }
        # Very small budget should return at least block 1
        result = self._read({"document_id": "doc1", "token_budget": 10}, blocks_for_doc=blocks)
        self.assertIn("Short.", result)
        # Budget 10 should be very tight
        self.assertIn("估算令牌数：", result)
        # At least one block returned
        self.assertIn("Short.", result)

    def test_next_window_hint(self):
        blocks = {}
        blocks["doc1"] = []
        for i in range(10):
            blocks["doc1"].append({
                "id": f"p{i}", "parent_id": "doc1", "type": "p",
                "markdown": f"Paragraph {i}.", "sort": i,
            })
        result = self._read({"document_id": "doc1", "block_limit": 5}, blocks_for_doc=blocks)
        self.assertIn("下一窗口：", result)
        self.assertIn("block_start=6", result)

    def test_include_block_ids_is_reference_reading(self):
        blocks = {
            "doc1": [
                {"id": "p1", "parent_id": "doc1", "type": "p", "markdown": "Hello world.", "sort": 1},
            ]
        }
        result = self._read({"document_id": "doc1", "include_block_ids": True}, blocks_for_doc=blocks)
        self.assertIn("引用阅读", result)
        self.assertIn("<!-- siyuan:block id=p1 type=p -->", result)

    def test_window_preview_integration(self):
        blocks = {}
        blocks["doc1"] = []
        for i in range(1, 121):
            blocks["doc1"].append({
                "id": f"p{i}", "parent_id": "doc1", "type": "p",
                "markdown": f"Paragraph number {i} content here.", "sort": i,
            })
        result = self._read({"document_id": "doc1", "block_limit": 200, "token_budget": 200000}, blocks_for_doc=blocks)
        # 0 headings, 120 blocks → should show window preview
        self.assertIn("标题较少（0 个）", result)
        self.assertIn("block 1:", result)
        self.assertIn("block 51:", result)
        self.assertIn("block 101:", result)

    def test_no_window_preview_with_headings(self):
        blocks = {}
        blocks["doc1"] = []
        # 5 headings, 120 blocks → no preview
        for i in range(1, 121):
            if i <= 5:
                blocks["doc1"].append({
                    "id": f"h{i}", "parent_id": "doc1", "type": "h", "subtype": "h2",
                    "markdown": f"## Heading {i}", "sort": i,
                })
            else:
                blocks["doc1"].append({
                    "id": f"p{i}", "parent_id": "doc1", "type": "p",
                    "markdown": f"Paragraph {i}.", "sort": i,
                })
        result = self._read({"document_id": "doc1", "block_limit": 200, "token_budget": 200000}, blocks_for_doc=blocks)
        self.assertNotIn("标题较少", result)
        self.assertIn("大纲", result)

    def test_outline_shows_block_positions(self):
        blocks = {
            "doc1": [
                {"id": "h1", "parent_id": "doc1", "type": "h", "subtype": "h2", "markdown": "## Section One", "sort": 1},
                {"id": "p1", "parent_id": "doc1", "type": "p", "markdown": "Body paragraph.", "sort": 2},
            ]
        }
        result = self._read({"document_id": "doc1"}, blocks_for_doc=blocks)
        self.assertIn("block 1:", result)
        self.assertIn("## Section One", result)

class McpServerReadBlockIdTests(unittest.TestCase):
    """Integration tests for reference reading with include_block_ids."""

    def setUp(self):
        self.root = Path.cwd() / ".test_tmp" / "mcp_blockid"
        shutil.rmtree(self.root, ignore_errors=True)
        base = self.root / "knowledge_base"
        base.mkdir(parents=True, exist_ok=True)
        (base / "notebooks.json").write_text(
            json.dumps([{"id": "nb1", "name": "Main"}], ensure_ascii=False),
            encoding="utf-8",
        )
        write_privacy_rules_cache(self.root, PrivacyRules(ignore=[], allow=[]))
        self.doc_md = "## Section One\n\nBody paragraph here.\n\nAnother paragraph.\n"
        docs = [
            {
                "id": "doc1",
                "notebook_id": "nb1",
                "notebook_name": "Main",
                "hpath": "/Test Doc",
                "title": "Test Doc",
                "path": "/doc1.sy",
                "tags": [],
                "word_count": 10,
                "block_count": 3,
                "updated": "20260501010101",
            },
        ]
        (base / "docs.jsonl").write_text(
            "".join(json.dumps(doc, ensure_ascii=False) + "\n" for doc in docs),
            encoding="utf-8",
        )

    def _make_client(self, blocks_for_doc=None):
        class ChildFakeClient(FakeSearchClient):
            def get_child_blocks(self, block_id):
                blocks = self._blocks.get(block_id)
                if isinstance(blocks, list):
                    return blocks
                children = []
                for block_list in self._blocks.values():
                    if isinstance(block_list, list):
                        children.extend(b for b in block_list if str(b.get("parent_id", "")) == block_id)
                children.sort(key=lambda b: int(b.get("sort", 0)))
                return children

        client = ChildFakeClient([])
        if blocks_for_doc:
            client._blocks = blocks_for_doc
        client._docs["doc1"] = self.doc_md
        return client

    def test_default_excludes_block_ids(self):
        blocks = {
            "doc1": [
                {"id": "h1", "parent_id": "doc1", "type": "h", "subtype": "h2", "markdown": "## Section One", "sort": 1},
                {"id": "p1", "parent_id": "doc1", "type": "p", "markdown": "Body paragraph here.", "sort": 2},
            ]
        }
        client = self._make_client(blocks_for_doc=blocks)
        server = mcp_server.McpServer(self.root)
        original = mcp_server.detect_active_profile

        profile = Profile(name="test", token="test")
        def fake_detect(_config):
            return profile, client

        mcp_server.detect_active_profile = fake_detect
        try:
            result = server.siyuan_read_document({"document_id": "doc1"})
            self.assertNotIn("<!-- siyuan:block", result)
            self.assertIn("普通阅读", result)
            self.assertIn("## Section One", result)
            self.assertIn("Body paragraph here.", result)
        finally:
            mcp_server.detect_active_profile = original

    def test_include_block_ids_builds_reference_view(self):
        blocks = {
            "doc1": [
                {"id": "block-h1", "parent_id": "doc1", "type": "h", "subtype": "h2", "markdown": "## Section One", "sort": 1},
                {"id": "block-p1", "parent_id": "doc1", "type": "p", "markdown": "Body paragraph here.", "sort": 2},
            ]
        }
        client = self._make_client(blocks_for_doc=blocks)
        server = mcp_server.McpServer(self.root)
        original = mcp_server.detect_active_profile

        profile = Profile(name="test", token="test")
        def fake_detect(_config):
            return profile, client

        mcp_server.detect_active_profile = fake_detect
        try:
            result = server.siyuan_read_document({"document_id": "doc1", "include_block_ids": True})
            self.assertIn("<!-- siyuan:block id=block-h1 type=h subtype=h2 -->", result)
            self.assertIn("## Section One", result)
            self.assertIn("<!-- siyuan:block id=block-p1 type=p -->", result)
            self.assertIn("Body paragraph here.", result)
            self.assertIn("引用阅读", result)
        finally:
            mcp_server.detect_active_profile = original

    def test_include_block_ids_preserves_outline(self):
        blocks = {
            "doc1": [
                {"id": "block-h1", "parent_id": "doc1", "type": "h", "subtype": "h2", "markdown": "## Section One", "sort": 1},
                {"id": "block-p1", "parent_id": "doc1", "type": "p", "markdown": "Body paragraph here.", "sort": 2},
                {"id": "block-p2", "parent_id": "doc1", "type": "p", "markdown": "Another paragraph.", "sort": 3},
            ]
        }
        client = self._make_client(blocks_for_doc=blocks)
        server = mcp_server.McpServer(self.root)
        original = mcp_server.detect_active_profile

        profile = Profile(name="test", token="test")
        def fake_detect(_config):
            return profile, client

        mcp_server.detect_active_profile = fake_detect
        try:
            result = server.siyuan_read_document({"document_id": "doc1", "include_block_ids": True})
            self.assertIn("<!-- siyuan:block", result)
            self.assertIn("大纲", result)
            self.assertIn("Section One", result)
        finally:
            mcp_server.detect_active_profile = original


if __name__ == "__main__":
    unittest.main()
