"""Build package.zip for SiYuan marketplace submission.

Usage:  python scripts/build_package.py

Requires running sync_siyuan_plugin_bridge.py first (it's called automatically).
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import sync_siyuan_plugin_bridge

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "siyuan-plugin"
DIST = ROOT / "dist"
PACKAGE = DIST / "package.zip"

PLUGIN_ROOT_FILES = [
    "icon.png",
    "index.css",
    "index.js",
    "plugin.json",
    "preview.png",
    "README_en_US.md",
    "README_zh_CN.md",
]

PLUGIN_ROOT_DIRS = [
    "bridge",
    "dist",
    "i18n",
    "src",
]


def verify_required(paths: list[Path]) -> None:
    missing = [str(p.relative_to(ROOT)) for p in paths if not p.exists()]
    if missing:
        raise SystemExit(f"Missing required files:\n  " + "\n  ".join(missing))


def main() -> int:
    print("Syncing bridge...")
    sync_siyuan_plugin_bridge.main()

    files = [PLUGIN / f for f in PLUGIN_ROOT_FILES]
    dirs = [PLUGIN / d for d in PLUGIN_ROOT_DIRS if (PLUGIN / d).exists()]

    verify_required(files)

    DIST.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(PACKAGE, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in files:
            arcname = file_path.name
            zf.write(file_path, arcname)
            print(f"  + {arcname}")

        for dir_path in dirs:
            arcroot = dir_path.name + "/"
            for p in dir_path.rglob("*"):
                if p.is_file() and "__pycache__" not in p.parts:
                    arcname = str(p.relative_to(PLUGIN))
                    zf.write(p, arcname)
                elif p.is_dir():
                    pass
            print(f"  + {arcroot}*")

    size_kb = PACKAGE.stat().st_size / 1024
    print(f"\nBuilt {PACKAGE.relative_to(ROOT)} ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
