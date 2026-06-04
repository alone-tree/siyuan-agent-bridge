from __future__ import annotations

import json
import unittest

from source_code.client import SiYuanApiError, SiYuanClient, SiYuanConnectionError


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ClientTests(unittest.TestCase):
    def test_token_header_is_sent(self):
        seen = {}

        def transport(req, timeout):
            seen["auth"] = req.get_header("Authorization")
            seen["timeout"] = timeout
            return FakeResponse({"code": 0, "data": {"version": "3.0.0"}})

        client = SiYuanClient("http://127.0.0.1:6806", token="secret", timeout=7, transport=transport)

        self.assertEqual(client.version(), "3.0.0")
        self.assertEqual(seen["auth"], "Token secret")
        self.assertEqual(seen["timeout"], 7)

    def test_connection_errors_are_wrapped(self):
        def transport(req, timeout):
            raise OSError("boom")

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)

        with self.assertRaises(SiYuanConnectionError):
            client.version()

    def test_create_snapshot_posts_memo_only(self):
        seen = {}

        def transport(req, timeout):
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"code": 0, "data": {"id": "20260503080000-abc123", "created": "20260503080000"}})

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)

        snapshot = client.create_snapshot("before edit")

        self.assertEqual(seen["url"], "http://127.0.0.1:6806/api/repo/createSnapshot")
        self.assertEqual(seen["body"], {"memo": "before edit"})
        self.assertEqual(snapshot["id"], "20260503080000-abc123")

    def test_create_snapshot_accepts_null_data(self):
        def transport(req, timeout):
            return FakeResponse({"code": 0, "data": None})

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)

        self.assertEqual(client.create_snapshot("before edit"), {})

    def test_get_repo_snapshots_posts_page(self):
        seen = {}

        def transport(req, timeout):
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"code": 0, "data": {"snapshots": [], "pageCount": 1, "totalCount": 0}})

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)

        data = client.get_repo_snapshots(page=2)

        self.assertEqual(seen["url"], "http://127.0.0.1:6806/api/repo/getRepoSnapshots")
        self.assertEqual(seen["body"], {"page": 2})
        self.assertEqual(data["totalCount"], 0)


    def test_create_doc_with_md_payload(self):
        seen = {}

        def transport(req, timeout):
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"code": 0, "data": {"id": "20260503090000-newdoc"}})

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)

        result = client.create_doc_with_md("nb1", "/Test Doc", "# Hello\n\nWorld")

        self.assertEqual(seen["url"], "http://127.0.0.1:6806/api/filetree/createDocWithMd")
        self.assertEqual(seen["body"], {"notebook": "nb1", "path": "/Test Doc", "markdown": "# Hello\n\nWorld"})
        self.assertEqual(result["id"], "20260503090000-newdoc")

    def test_create_doc_with_md_accepts_null_data(self):
        def transport(req, timeout):
            return FakeResponse({"code": 0, "data": None})

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)
        self.assertEqual(client.create_doc_with_md("nb1", "/Test", "# Hi"), {})

    def test_create_doc_with_md_accepts_string_id(self):
        def transport(req, timeout):
            return FakeResponse({"code": 0, "data": "20260503090000-newdoc-string"})

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)
        result = client.create_doc_with_md("nb1", "/Test", "# Hi")
        self.assertEqual(result["id"], "20260503090000-newdoc-string")

    def test_rename_doc_by_id_payload(self):
        seen = {}

        def transport(req, timeout):
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"code": 0, "data": {}})

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)
        client.rename_doc_by_id("doc1", "New Title")

        self.assertEqual(seen["url"], "http://127.0.0.1:6806/api/filetree/renameDocByID")
        self.assertEqual(seen["body"], {"id": "doc1", "title": "New Title"})

    def test_remove_doc_by_id_payload(self):
        seen = {}

        def transport(req, timeout):
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"code": 0, "data": {}})

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)
        client.remove_doc_by_id("doc1")

        self.assertEqual(seen["url"], "http://127.0.0.1:6806/api/filetree/removeDocByID")
        self.assertEqual(seen["body"], {"id": "doc1"})

    def test_move_docs_by_id_payload(self):
        seen = {}

        def transport(req, timeout):
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"code": 0, "data": {}})

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)
        client.move_docs_by_id(["doc1"], "target")

        self.assertEqual(seen["url"], "http://127.0.0.1:6806/api/filetree/moveDocsByID")
        self.assertEqual(seen["body"], {"fromIDs": ["doc1"], "toID": "target"})

    def test_update_block_payload(self):
        seen = {}

        def transport(req, timeout):
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"code": 0, "data": {}})

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)
        client.update_block("block123", "new content")

        self.assertEqual(seen["url"], "http://127.0.0.1:6806/api/block/updateBlock")
        self.assertEqual(seen["body"], {"id": "block123", "dataType": "markdown", "data": "new content"})

    def test_append_block_payload(self):
        seen = {}

        def transport(req, timeout):
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"code": 0, "data": {}})

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)
        client.append_block("doc1", "appended text")

        self.assertEqual(seen["url"], "http://127.0.0.1:6806/api/block/appendBlock")
        self.assertEqual(seen["body"], {"dataType": "markdown", "data": "appended text", "parentID": "doc1"})

    def test_insert_block_after_payload(self):
        seen = {}

        def transport(req, timeout):
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"code": 0, "data": {}})

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)
        client.insert_block_after("prev123", "inserted text")

        self.assertEqual(seen["url"], "http://127.0.0.1:6806/api/block/insertBlock")
        self.assertEqual(seen["body"], {"dataType": "markdown", "data": "inserted text", "previousID": "prev123"})

    def test_push_msg_payload(self):
        seen = {}

        def transport(req, timeout):
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"code": 0, "data": None})

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)
        client.push_msg("Hello SiYuan", timeout=5000)

        self.assertEqual(seen["url"], "http://127.0.0.1:6806/api/notification/pushMsg")
        self.assertEqual(seen["body"], {"msg": "Hello SiYuan", "timeout": 5000})

    def test_list_document_blocks_returns_block_list(self):
        fake_blocks = [
            {"id": "block1", "parent_id": "doc1", "root_id": "doc1", "type": "p", "subtype": "", "markdown": "First para.", "content": "", "sort": 1},
            {"id": "block2", "parent_id": "doc1", "root_id": "doc1", "type": "h", "subtype": "h2", "markdown": "## Heading", "content": "", "sort": 2},
        ]

        def transport(req, timeout):
            return FakeResponse({"code": 0, "data": fake_blocks})

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)
        blocks = client.list_document_blocks("doc1")
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["id"], "block1")
        self.assertEqual(blocks[1]["type"], "h")

    def test_list_document_blocks_returns_empty_list(self):
        def transport(req, timeout):
            return FakeResponse({"code": 0, "data": []})

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)
        blocks = client.list_document_blocks("doc1")
        self.assertEqual(blocks, [])

    def test_list_document_blocks_non_list_raises(self):
        def transport(req, timeout):
            return FakeResponse({"code": 0, "data": {"foo": "bar"}})

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)
        with self.assertRaises(SiYuanApiError):
            client.list_document_blocks("doc1")

    def test_get_child_blocks_posts_parent_id(self):
        seen = {}

        def transport(req, timeout):
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"code": 0, "data": [{"id": "child1", "type": "p"}]})

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)
        blocks = client.get_child_blocks("parent1")
        self.assertEqual(seen["url"], "http://127.0.0.1:6806/api/block/getChildBlocks")
        self.assertEqual(seen["body"], {"id": "parent1"})
        self.assertEqual(blocks, [{"id": "child1", "type": "p"}])

    def test_get_child_blocks_filters_non_dict_items(self):
        def transport(req, timeout):
            return FakeResponse({"code": 0, "data": [{"id": "child1"}, "bad"]})

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)
        self.assertEqual(client.get_child_blocks("parent1"), [{"id": "child1"}])

    def test_get_child_blocks_non_list_raises(self):
        def transport(req, timeout):
            return FakeResponse({"code": 0, "data": {"foo": "bar"}})

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)
        with self.assertRaises(SiYuanApiError):
            client.get_child_blocks("parent1")


if __name__ == "__main__":
    unittest.main()
