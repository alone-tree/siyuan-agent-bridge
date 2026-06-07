from __future__ import annotations

import json
import os
import shutil
import unittest
from datetime import datetime, timezone
from pathlib import Path

from source_code import telemetry
from source_code.telemetry import (
    TelemetryEvent,
    _build_proxy_handler,
    _resolve_proxy,
    _with_telemetry,
    ensure_session_id,
    generate_anonymous_id,
    load_anonymous_id,
    load_telemetry_config,
    record_event,
    set_siyuan_version,
    should_collect,
    should_upload,
    submit_feedback,
)


class TestAnonymousId(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / ".test_tmp" / "telemetry_id"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)
        telemetry._anonymous_id = None

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        telemetry._anonymous_id = None

    def test_generate_creates_id_file(self):
        aid = generate_anonymous_id(self.root)
        self.assertEqual(len(aid), 32)
        id_file = self.root / "stats" / "telemetry_id"
        self.assertTrue(id_file.exists())
        self.assertEqual(id_file.read_text(encoding="utf-8").strip(), aid)

    def test_load_returns_existing_id(self):
        generate_anonymous_id(self.root)
        telemetry._anonymous_id = None
        aid1 = load_anonymous_id(self.root)
        telemetry._anonymous_id = None
        aid2 = load_anonymous_id(self.root)
        self.assertEqual(aid1, aid2)

    def test_load_generates_when_missing(self):
        telemetry._anonymous_id = None
        aid = load_anonymous_id(self.root)
        self.assertTrue(len(aid) == 32)

    def test_load_uses_cache(self):
        telemetry._anonymous_id = "cached_id"
        self.assertEqual(load_anonymous_id(self.root), "cached_id")


class TestSessionId(unittest.TestCase):
    def setUp(self):
        telemetry._session_id = None

    def tearDown(self):
        telemetry._session_id = None

    def test_session_id_stable_per_process(self):
        sid1 = ensure_session_id()
        sid2 = ensure_session_id()
        self.assertEqual(sid1, sid2)
        self.assertEqual(len(sid1), 32)


class TestSiyuanVersion(unittest.TestCase):
    def tearDown(self):
        telemetry._siyuan_ver = None

    def test_set_and_read(self):
        set_siyuan_version("3.1.25")
        self.assertEqual(telemetry._siyuan_ver, "3.1.25")


class TestTelemetryConfig(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / ".test_tmp" / "telemetry_config"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_missing_file_returns_off(self):
        cfg = load_telemetry_config(self.root)
        self.assertEqual(cfg["telemetry"], "off")
        self.assertEqual(cfg["telemetry_endpoint"], "")
        self.assertEqual(cfg["proxy"], "")

    def test_invalid_json_returns_off(self):
        (self.root / "telemetry.json").write_text("{bad json", encoding="utf-8")
        cfg = load_telemetry_config(self.root)
        self.assertEqual(cfg["telemetry"], "off")

    def test_not_dict_returns_off(self):
        (self.root / "telemetry.json").write_text("[1, 2, 3]", encoding="utf-8")
        cfg = load_telemetry_config(self.root)
        self.assertEqual(cfg["telemetry"], "off")

    def test_local_mode(self):
        (self.root / "telemetry.json").write_text(
            json.dumps({"telemetry": "local"}), encoding="utf-8"
        )
        self.assertTrue(should_collect(self.root))
        self.assertFalse(should_upload(self.root))

    def test_upload_mode(self):
        (self.root / "telemetry.json").write_text(
            json.dumps({"telemetry": "upload", "telemetry_endpoint": "https://example.com"}),
            encoding="utf-8",
        )
        self.assertTrue(should_collect(self.root))
        self.assertTrue(should_upload(self.root))

    def test_upload_mode_no_endpoint(self):
        (self.root / "telemetry.json").write_text(
            json.dumps({"telemetry": "upload"}), encoding="utf-8"
        )
        self.assertTrue(should_collect(self.root))
        self.assertFalse(should_upload(self.root))

    def test_off_mode(self):
        (self.root / "telemetry.json").write_text(
            json.dumps({"telemetry": "off"}), encoding="utf-8"
        )
        self.assertFalse(should_collect(self.root))
        self.assertFalse(should_upload(self.root))

    def test_invalid_mode_treated_as_off(self):
        (self.root / "telemetry.json").write_text(
            json.dumps({"telemetry": "invalid"}), encoding="utf-8"
        )
        self.assertFalse(should_collect(self.root))

    def test_proxy_field_preserved(self):
        (self.root / "telemetry.json").write_text(
            json.dumps({"telemetry": "upload", "proxy": "http://127.0.0.1:7897"}),
            encoding="utf-8",
        )
        cfg = load_telemetry_config(self.root)
        self.assertEqual(cfg["proxy"], "http://127.0.0.1:7897")


class TestProxyResolution(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / ".test_tmp" / "telemetry_proxy"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        for var in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
            os.environ.pop(var, None)

    def test_explicit_proxy_wins(self):
        (self.root / "telemetry.json").write_text(
            json.dumps({"proxy": "http://127.0.0.1:7897"}), encoding="utf-8"
        )
        self.assertEqual(_resolve_proxy(self.root), "http://127.0.0.1:7897")

    def test_env_var_when_no_explicit(self):
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:9999"
        self.assertEqual(_resolve_proxy(self.root), "http://127.0.0.1:9999")

    def test_http_proxy_fallback(self):
        os.environ["HTTP_PROXY"] = "http://127.0.0.1:8888"
        self.assertEqual(_resolve_proxy(self.root), "http://127.0.0.1:8888")

    def test_all_proxy_fallback(self):
        os.environ["ALL_PROXY"] = "http://127.0.0.1:7777"
        self.assertEqual(_resolve_proxy(self.root), "http://127.0.0.1:7777")

    def test_explicit_over_env(self):
        (self.root / "telemetry.json").write_text(
            json.dumps({"proxy": "http://explicit:1234"}), encoding="utf-8"
        )
        os.environ["HTTPS_PROXY"] = "http://env:9999"
        self.assertEqual(_resolve_proxy(self.root), "http://explicit:1234")

    def test_empty_when_nothing_set(self):
        # When no explicit config or env vars, returns system proxy or empty
        result = _resolve_proxy(self.root)
        # result may be empty (no system proxy) or a valid proxy URL
        self.assertIsInstance(result, str)

    def test_build_proxy_handler_with_url(self):
        handler = _build_proxy_handler("http://127.0.0.1:7897")
        self.assertIn("https", handler.proxies)
        self.assertEqual(handler.proxies["https"], "http://127.0.0.1:7897")

    def test_build_proxy_handler_empty(self):
        handler = _build_proxy_handler("")
        # ProxyHandler with empty dict uses system proxy
        self.assertIsNotNone(handler)


class TestRecordEvent(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / ".test_tmp" / "telemetry_record"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "telemetry.json").write_text(
            json.dumps({"telemetry": "local"}), encoding="utf-8"
        )
        telemetry._anonymous_id = None
        telemetry._session_id = None
        telemetry._siyuan_ver = None

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        telemetry._anonymous_id = None
        telemetry._session_id = None
        telemetry._siyuan_ver = None

    def _make_event(self, **overrides):
        defaults = {
            "ts": "2026-06-07T10:00:00+00:00",
            "anonymous_id": load_anonymous_id(self.root),
            "platform": telemetry._PLATFORM,
            "siyuan_ver": None,
            "mcp_ver": telemetry.MCP_VERSION,
            "session_id": ensure_session_id(),
            "tool": "siyuan_read",
            "action": None,
            "ok": 1,
            "error_type": None,
            "dur_ms": 100,
        }
        defaults.update(overrides)
        return TelemetryEvent(**defaults)

    def test_writes_to_daily_jsonl(self):
        event = self._make_event()
        record_event(self.root, event)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        jsonl_file = self.root / "stats" / "events" / f"{date_str}.jsonl"
        self.assertTrue(jsonl_file.exists())
        lines = jsonl_file.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), 1)
        parsed = json.loads(lines[0])
        self.assertEqual(parsed["tool"], "siyuan_read")
        self.assertEqual(parsed["ok"], 1)

    def test_multiple_events_same_file(self):
        for i in range(3):
            event = self._make_event(tool=f"tool_{i}")
            record_event(self.root, event)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        jsonl_file = self.root / "stats" / "events" / f"{date_str}.jsonl"
        lines = jsonl_file.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), 3)

    def test_no_record_when_off(self):
        (self.root / "telemetry.json").write_text(
            json.dumps({"telemetry": "off"}), encoding="utf-8"
        )
        event = self._make_event()
        record_event(self.root, event)
        events_dir = self.root / "stats" / "events"
        self.assertFalse(events_dir.exists())


class TestWithTelemetry(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / ".test_tmp" / "telemetry_wrapper"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "telemetry.json").write_text(
            json.dumps({"telemetry": "local"}), encoding="utf-8"
        )
        telemetry._anonymous_id = None
        telemetry._session_id = None

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        telemetry._anonymous_id = None
        telemetry._session_id = None

    def test_successful_call_returns_result(self):
        result = _with_telemetry(self.root, "test_tool", None, lambda: "hello")
        self.assertEqual(result, "hello")

    def test_failed_call_reraises(self):
        def failing():
            raise ValueError("something went wrong")

        with self.assertRaises(ValueError):
            _with_telemetry(self.root, "test_tool", None, failing)

    def test_no_record_when_off(self):
        (self.root / "telemetry.json").write_text(
            json.dumps({"telemetry": "off"}), encoding="utf-8"
        )
        events_dir = self.root / "stats" / "events"
        if events_dir.exists():
            shutil.rmtree(events_dir)
        _with_telemetry(self.root, "test_tool", None, lambda: "ok")
        self.assertFalse(events_dir.exists())

    def test_records_event_on_success(self):
        _with_telemetry(self.root, "siyuan_read", None, lambda: "ok")
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        jsonl_file = self.root / "stats" / "events" / f"{date_str}.jsonl"
        self.assertTrue(jsonl_file.exists())

    def test_records_event_on_failure(self):
        def failing():
            raise RuntimeError("fail")

        with self.assertRaises(RuntimeError):
            _with_telemetry(self.root, "siyuan_create", "overwrite", failing)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        jsonl_file = self.root / "stats" / "events" / f"{date_str}.jsonl"
        self.assertTrue(jsonl_file.exists())
        parsed = json.loads(jsonl_file.read_text(encoding="utf-8").strip())
        self.assertEqual(parsed["ok"], 0)
        self.assertEqual(parsed["error_type"], "RuntimeError")
        self.assertEqual(parsed["action"], "overwrite")


class TestSubmitFeedback(unittest.TestCase):
    def test_submit_feedback_missing_endpoint_returns_false(self):
        result = submit_feedback("", "", {"type": "bug", "title": "t", "description": "d"})
        self.assertFalse(result)

    def test_submit_feedback_bad_url_returns_false(self):
        result = submit_feedback(
            "http://0.0.0.0:1",
            "",
            {"type": "bug", "title": "t", "description": "d"},
        )
        self.assertFalse(result)
