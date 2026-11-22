"""Reads photos with the local model from the command line and prints what it saw.

Usage:
  python scripts/try_model.py sheet  path/to/sheet.jpg  [model]
  python scripts/try_model.py summary path/to/summary.jpg [model]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sheetcheck import extraction as ex  # noqa: E402
from sheetcheck.config import load_config  # noqa: E402


def show(label: str, reading) -> str:
    mark = "" if not reading.is_unclear else f"   [غير واضح: {reading.hint()}]"
    return f"{label}={reading.text!r}{mark}"


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[1] not in ("sheet", "summary"):
        sys.exit(__doc__)
    kind, path = sys.argv[1], Path(sys.argv[2])
    cfg = load_config()["extraction"]
    if len(sys.argv) > 3:
        cfg["model"] = sys.argv[3]
    sys.stdout.reconfigure(encoding="utf-8")

    started = time.time()
    if kind == "sheet":
        sheet = ex.extract_sheet(path.read_bytes(), cfg)
        print(show("sheet_number", sheet.sheet_number))
        for row in sheet.rows:
            print("  ", show("serial", row.serial), show("amount", row.amount), show("date", row.date))
        print(f"{len(sheet.rows)} rows")
    else:
        s = ex.extract_summary(path.read_bytes(), cfg)
        for name in ("total", "tax", "rounding", "stamp"):
            print(show(name, getattr(s, name)))
    print(f"model={cfg['model']}  time={time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
