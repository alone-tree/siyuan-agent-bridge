from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from typing import Any

from source_code import config as config_module
from source_code.client import SiYuanApiError, SiYuanConnectionError
from source_code.config import Config, Profile, detect_active_profile, load_config


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / ".test_tmp" / "config"
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)

    def test_load_config_reads_profiles(self):
        (self.root / "config.local.json").write_text(
            json.dumps(
                {
                    "profiles": [
                        {"name": "主工作空间", "token": "tok-main"},
                        {"name": "另一个工作空间", "token": "tok-other"},
                    ],
                    "language": "zh-CN",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        loaded = load_config(self.root)

        self.assertEqual(loaded.language, "zh-CN")
        self.assertEqual(
            loaded.profiles,
            (
                Profile(name="主工作空间", token="tok-main"),
                Profile(name="另一个工作空间", token="tok-other"),
            ),
        )

    def test_detect_active_profile_reports_missing_profiles(self):
        with self.assertRaises(SiYuanConnectionError) as ctx:
            detect_active_profile(Config(profiles=(), language="", root=self.root))

        self.assertIn("config.local.json", str(ctx.exception))

    def test_detect_active_profile_reports_siyuan_not_started(self):
        original = config_module.SiYuanClient

        class FailingClient:
            def __init__(self, *_args: Any, **_kwargs: Any) -> None:
                pass

            def list_notebooks(self) -> list[dict[str, Any]]:
                raise SiYuanConnectionError("connection refused")

        config_module.SiYuanClient = FailingClient
        try:
            with self.assertRaises(SiYuanConnectionError) as ctx:
                detect_active_profile(Config(profiles=(Profile("默认", "tok"),), language="", root=self.root))
        finally:
            config_module.SiYuanClient = original

        self.assertIn("思源笔记似乎没有启动", str(ctx.exception))
        self.assertIn("手动打开思源", str(ctx.exception))

    def test_detect_active_profile_reports_token_mismatch(self):
        original = config_module.SiYuanClient

        class TokenRejectedClient:
            def __init__(self, *_args: Any, **_kwargs: Any) -> None:
                pass

            def list_notebooks(self) -> list[dict[str, Any]]:
                raise SiYuanApiError("token rejected", status=401)

        config_module.SiYuanClient = TokenRejectedClient
        try:
            with self.assertRaises(SiYuanConnectionError) as ctx:
                detect_active_profile(Config(profiles=(Profile("默认", "bad"),), language="", root=self.root))
        finally:
            config_module.SiYuanClient = original

        message = str(ctx.exception)
        self.assertIn("思源 API 可达", message)
        self.assertIn("未配置的思源工作空间", message)
        self.assertIn("插件设置页", message)


if __name__ == "__main__":
    unittest.main()
