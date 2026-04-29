from __future__ import annotations

import json
import unittest

from siyuan_kb.client import SiYuanClient, SiYuanConnectionError


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


if __name__ == "__main__":
    unittest.main()
