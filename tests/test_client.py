from __future__ import annotations

import json
import unittest

from source_code.client import SiYuanClient, SiYuanConnectionError


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

    def test_create_snapshot_posts_memo_and_tags(self):
        seen = {}

        def transport(req, timeout):
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"code": 0, "data": {"id": "20260503080000-abc123", "created": "20260503080000"}})

        client = SiYuanClient("http://127.0.0.1:6806", transport=transport)

        snapshot = client.create_snapshot("before edit", tags=["siyuan-agent-bridge"])

        self.assertEqual(seen["url"], "http://127.0.0.1:6806/api/repo/createSnapshot")
        self.assertEqual(seen["body"], {"memo": "before edit", "tags": ["siyuan-agent-bridge"]})
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


if __name__ == "__main__":
    unittest.main()
