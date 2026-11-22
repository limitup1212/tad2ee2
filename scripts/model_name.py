"""Prints the model name from config.yaml (used by setup.bat)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sheetcheck.config import load_config  # noqa: E402

print(load_config()["extraction"]["model"])
