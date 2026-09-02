"""Make the two component packages importable in tests without installation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for folder in ("server", "client"):
    path = str(ROOT / folder)
    if path not in sys.path:
        sys.path.insert(0, path)
