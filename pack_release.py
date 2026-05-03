"""Package SiYuan Agent Bridge into a distributable ZIP for beta release.

Generates the skill ZIP internally and bundles it alongside the full source tree.
The skill ZIP is the self-contained plugin package that users import into CC Switch.

Usage:
    python pack_release.py          # packs to dist/siyuan-agent-bridge-release-<timestamp>.zip
    python pack_release.py --check  # list files without creating zip
"""

import argparse
import io
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist"
PLUGIN_DIR = ROOT / "plugins" / "siyuan-agent-bridge"

SOURCE_FILES = [
    "__init__.py",
    "__main__.py",
    "client.py",
    "config.py",
    "indexer.py",
    "ignore.py",
    "i18n.py",
    "agent_notebook.py",
    "cli.py",
    "mcp_server.py",
]

PLUGIN_FILES = [
    ".mcp.json",
    ".codex-plugin/plugin.json",
    "scripts/run_mcp.py",
    "skills/siyuan-agent-bridge/plugin.json",
    "skills/siyuan-agent-bridge/SKILL.md",
    "skills/siyuan-index-builder/plugin.json",
    "skills/siyuan-index-builder/SKILL.md",
]

MCP_CONFIG_FILES = [
    "README.md",
    "cc-switch.json",
    "claude-code-vscode.json",
    "claude-code-desktop.json",
    "openclaw.json",
]

ROOT_FILES = [
    "README.md",
    "config.example.json",
    "INSTALL_FOR_AI.md",
    "PROMPT_FOR_AI_INSTALL.md",
    "install.bat",
    "doctor.bat",
]


def build_skill_zip_bytes() -> bytes:
    """Build the importable skill ZIP in memory and return its bytes."""
    missing = [f for f in PLUGIN_FILES if not (PLUGIN_DIR / f).exists()]
    if missing:
        raise SystemExit(f"Missing plugin files:\n" + "\n".join(f"  - {m}" for m in missing))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in PLUGIN_FILES:
            arcname = f.replace("\\", "/")
            zf.write(PLUGIN_DIR / f, arcname=arcname)
    return buf.getvalue()


def collect_files() -> list[tuple[Path, str]]:
    """Collect all files to package. Returns list of (source_path, arcname)."""
    entries: list[tuple[Path, str]] = []

    for f in SOURCE_FILES:
        src = ROOT / "source_code" / f
        if not src.exists():
            raise SystemExit(f"Missing: {src}")
        entries.append((src, f"source_code/{f}"))

    for f in PLUGIN_FILES:
        src = PLUGIN_DIR / f
        if not src.exists():
            raise SystemExit(f"Missing: {src}")
        entries.append((src, f"plugins/siyuan-agent-bridge/{f}"))

    mcp_dir = ROOT / "mcp_configs"
    for f in MCP_CONFIG_FILES:
        src = mcp_dir / f
        if not src.exists():
            raise SystemExit(f"Missing: {src}")
        entries.append((src, f"mcp_configs/{f}"))

    for f in ROOT_FILES:
        src = ROOT / f
        if not src.exists():
            raise SystemExit(f"Missing: {src}")
        entries.append((src, f))

    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description="Package SiYuan Agent Bridge release ZIP")
    parser.add_argument("--check", action="store_true", help="List files without creating zip")
    args = parser.parse_args()

    entries = collect_files()

    if args.check:
        print(f"Files to package ({len(entries)}):")
        for _, arcname in sorted(entries, key=lambda x: x[1]):
            print(f"  {arcname}")
        print(f"\nSkill ZIP: {len(PLUGIN_FILES)} files from plugins/siyuan-agent-bridge/")
        return

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"siyuan-agent-bridge-release-{timestamp}.zip"
    skill_zip_name = f"siyuan-agent-bridge-skill-{timestamp}.zip"

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DIST_DIR / filename

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, arcname in entries:
            zf.write(src, arcname=arcname)
        skill_bytes = build_skill_zip_bytes()
        zf.writestr(skill_zip_name, skill_bytes)

    print(f"Created: {output_path} ({output_path.stat().st_size:,} bytes)")
    print(f"Files: {len(entries)} + {skill_zip_name} (skill ZIP)")


if __name__ == "__main__":
    main()
