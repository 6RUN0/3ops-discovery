"""Make the container-flat mini-app importable as `import app`."""

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "e2e" / "stack" / "app"
sys.path.insert(0, str(APP_DIR))
