from __future__ import annotations

import os
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[1]

os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

from source_code.mcp_server import main


if __name__ == "__main__":
    raise SystemExit(main())
