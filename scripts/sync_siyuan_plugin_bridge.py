from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "siyuan-plugin"
BRIDGE_ROOT = PLUGIN_ROOT / "bridge"

SOURCE_DIRS = [
    (ROOT / "source_code", BRIDGE_ROOT / "source_code"),
    (
        ROOT / "plugins" / "siyuan-bridge" / "scripts",
        BRIDGE_ROOT / "scripts",
    ),
    (
        ROOT / "plugins" / "siyuan-bridge" / "skills",
        BRIDGE_ROOT / "skills",
    ),
]

ROOT_FILES = [
    "config.example.json",
    "README.md",
    "LICENSE",
]

PROTECTED_FILES = [
    BRIDGE_ROOT / "config.local.json",
]


def remove_generated_bridge_paths() -> None:
    # Clean legacy container layer if it exists from an older sync
    legacy_container = BRIDGE_ROOT / "plugins"
    if legacy_container.exists():
        shutil.rmtree(legacy_container)
    for path in (
        BRIDGE_ROOT / "source_code",
        BRIDGE_ROOT / "scripts",
        BRIDGE_ROOT / "skills",
    ):
        if path.exists():
            shutil.rmtree(path)


def copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        raise SystemExit(f"Missing source directory: {src}")
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
    )


def copy_root_files() -> None:
    BRIDGE_ROOT.mkdir(parents=True, exist_ok=True)
    for name in ROOT_FILES:
        src = ROOT / name
        if not src.exists():
            raise SystemExit(f"Missing source file: {src}")
        shutil.copy2(src, BRIDGE_ROOT / name)


def main() -> int:
    for protected in PROTECTED_FILES:
        if protected.exists():
            print(f"Preserving local config: {protected}")

    remove_generated_bridge_paths()
    for src, dst in SOURCE_DIRS:
        dst.parent.mkdir(parents=True, exist_ok=True)
        copy_tree(src, dst)
        print(f"Copied {src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}")

    copy_root_files()
    print(f"Bridge synced: {BRIDGE_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
