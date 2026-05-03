"""Package siyuan-agent-bridge skills into a distributable zip.

Usage:
    python pack_skill.py          # packs to dist/siyuan-agent-bridge-skill-<timestamp>.zip
    python pack_skill.py --check  # list files without creating zip
"""

import argparse
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLUGIN_DIR = ROOT / "plugins" / "siyuan-agent-bridge"
DIST_DIR = ROOT / "dist"

FILES = [
    ".mcp.json",
    ".codex-plugin/plugin.json",
    "scripts/run_mcp.py",
    "skills/siyuan-agent-bridge/plugin.json",
    "skills/siyuan-agent-bridge/SKILL.md",
    "skills/siyuan-index-builder/plugin.json",
    "skills/siyuan-index-builder/SKILL.md",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Package SiYuan Agent Bridge skills")
    parser.add_argument("--check", action="store_true", help="List files without creating zip")
    args = parser.parse_args()

    missing = [f for f in FILES if not (PLUGIN_DIR / f).exists()]
    if missing:
        raise SystemExit(f"Missing files:\n" + "\n".join(f"  - {m}" for m in missing))

    if args.check:
        print(f"Files to package ({len(FILES)}):")
        for f in FILES:
            print(f"  {f}")
        return

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"siyuan-agent-bridge-skill-{timestamp}.zip"

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DIST_DIR / filename

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in FILES:
            arcname = f.replace("\\", "/")
            zf.write(PLUGIN_DIR / f, arcname=arcname)

    print(f"Created: {output_path} ({output_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
