from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

import sync_siyuan_plugin_bridge


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PLUGIN = ROOT / "siyuan-plugin"
PLUGIN_NAME = "siyuan-bridge"
CONFIG_RELATIVE_PATHS = [
    Path("bridge") / "config.local.json",
    Path("bridge") / "telemetry.json",
]


def resolve_plugins_dir(path: Path) -> Path:
    candidates = [
        path / "data" / "plugins",
        path / "workspace" / "data" / "plugins",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def copy_local_configs(target: Path, backup: Path) -> None:
    for relative in CONFIG_RELATIVE_PATHS:
        src = target / relative
        if src.exists():
            dst = backup / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def restore_local_configs(target: Path, backup: Path) -> None:
    for relative in CONFIG_RELATIVE_PATHS:
        src = backup / relative
        if src.exists():
            dst = target / relative
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def remove_local_configs(target: Path) -> None:
    for relative in CONFIG_RELATIVE_PATHS:
        path = target / relative
        if path.exists():
            path.unlink()


def remove_target(target: Path, plugins_dir: Path) -> None:
    resolved_target = target.resolve()
    resolved_plugins_dir = plugins_dir.resolve()
    if resolved_target.parent != resolved_plugins_dir:
        raise SystemExit(f"Refusing to remove unexpected path: {resolved_target}")
    if resolved_target.exists():
        shutil.rmtree(resolved_target)


def verify_import(target: Path, fresh: bool) -> None:
    required = [
        "plugin.json",
        "index.js",
        "dist/index.js",
        "src/index.js",
        "bridge/source_code/mcp_server.py",
        "bridge/scripts/run_mcp.py",
    ]
    for relative in required:
        path = target / relative
        if not path.exists():
            raise SystemExit(f"Missing after import: {path}")
    config_path = target / "bridge" / "config.local.json"
    if fresh and config_path.exists():
        raise SystemExit(f"Fresh import should not keep config: {config_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import siyuan-plugin into a SiYuan test workspace.")
    parser.add_argument(
        "--workspace",
        default=os.environ.get("SIYUAN_TEST_WORKSPACE", ""),
        help="SiYuan workspace root. Also accepts a parent containing workspace/data/plugins.",
    )
    parser.add_argument(
        "--plugin-dir",
        default=os.environ.get("SIYUAN_TEST_PLUGIN_DIR", ""),
        help="Explicit target plugin directory. Overrides --workspace.",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Simulate first install by not preserving config.local.json or telemetry.json.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.workspace and not args.plugin_dir:
        raise SystemExit("Pass --workspace or set SIYUAN_TEST_WORKSPACE.")

    sync_siyuan_plugin_bridge.main()

    if args.plugin_dir:
        target = Path(args.plugin_dir).resolve()
        plugins_dir = target.parent
    else:
        plugins_dir = resolve_plugins_dir(Path(args.workspace))
        target = plugins_dir / PLUGIN_NAME

    backup = ROOT / "ai_workspace" / "plugin_import_backup"

    if not args.fresh and target.exists():
        # Overwrite any stale backup with the live config files
        if backup.exists():
            shutil.rmtree(backup)
        backup.mkdir(parents=True, exist_ok=True)
        copy_local_configs(target, backup)
    else:
        backup.mkdir(parents=True, exist_ok=True)

    plugins_dir.mkdir(parents=True, exist_ok=True)
    remove_target(target, plugins_dir)
    shutil.copytree(SOURCE_PLUGIN, target)
    remove_local_configs(target)

    if not args.fresh:
        restore_local_configs(target, backup)

    verify_import(target, args.fresh)
    shutil.rmtree(backup)
    print(f"Imported {SOURCE_PLUGIN} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
