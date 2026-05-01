from __future__ import annotations

import json
import unittest
from pathlib import Path

from source_code import mcp_server


class McpServerTests(unittest.TestCase):
    def test_find_documents_falls_back_to_safe_index(self):
        root = Path.cwd() / ".test_tmp" / "mcp_find"
        base = root / "knowledge_base"
        base.mkdir(parents=True, exist_ok=True)
        (base / "notebooks.json").write_text(
            json.dumps([{"id": "nb1", "name": "AI使用"}], ensure_ascii=False),
            encoding="utf-8",
        )
        doc = {
            "id": "doc1",
            "notebook_id": "nb1",
            "notebook_name": "AI使用",
            "hpath": "/AI常用提示词",
            "title": "AI常用提示词",
            "tags": [],
            "word_count": 123,
            "updated": "20260501010101",
        }
        (base / "docs.jsonl").write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")

        server = mcp_server.McpServer(root)
        original = mcp_server.get_working_client

        def offline_client(_config):
            raise mcp_server.SiYuanConnectionError("offline")

        mcp_server.get_working_client = offline_client
        try:
            output = server.siyuan_find_documents({
                "keyword": "提示词",
                "mode": "keyword",
                "scope": "headings",
                "notebooks": "nb1",
            })
        finally:
            mcp_server.get_working_client = original

        self.assertIn("doc1", output)
        self.assertIn("/AI常用提示词", output)
        self.assertIn("safe index", output)


if __name__ == "__main__":
    unittest.main()
