from __future__ import annotations

import io
import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
# In the flattened structure, scripts/ lives directly in bridge/,
# and source_code/ is alongside scripts/ in the same bridge/ directory.
# run_mcp.py: scripts/run_mcp.py → parents[0]=scripts → parents[1]=bridge (REPO_ROOT)
REPO_ROOT = PLUGIN_ROOT

os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))
sys.stdin = io.TextIOWrapper(sys.stdin.detach(), encoding="utf-8", errors="replace")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from source_code.mcp_server import main


if __name__ == "__main__":
    raise SystemExit(main())
