"""Checks that the local model is installed and reads an Arabic sheet on this computer.

Draws a small Arabic summary page and a sheet with known numbers, asks the model to
read them, and compares. Exit code 0 = everything was read correctly.

Usage:  python scripts/check_model.py [arabic-digits]

The test pages use Western digits (0-9) by default, which this model reads well.
With "arabic-digits" they use Arabic-Indic digits (٠-٩), which it reads poorly.
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import make_test_image  # noqa: E402
from make_test_image import draw_sheet, draw_summary  # noqa: E402

from sheetcheck import extraction as ex  # noqa: E402
from sheetcheck import review  # noqa: E402
from sheetcheck.config import load_config  # noqa: E402
from sheetcheck.sample_data import sample_rows, sample_summary  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()["extraction"]
    make_test_image.ARABIC_DIGITS = "arabic-digits" in sys.argv[1:]
    style = "Arabic-Indic digits" if make_test_image.ARABIC_DIGITS else "Western digits"

    reachable, installed, message = ex.server_status(cfg["model"])
    if not (reachable and installed):
        print("  FAIL:", "Ollama is not running." if not reachable
              else f"model {cfg['model']} is not downloaded (ollama pull {cfg['model']}).")
        return 1
    print(f"  Model {cfg['model']} is installed. Reading two Arabic test pages ({style})...")

    rows = [r for r in sample_rows() if r.sheet == 1]
    want_summary = sample_summary()
    mistakes = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        draw_summary(want_summary, tmp / "summary.jpg")
        draw_sheet(rows, 1, tmp / "sheet.jpg")

        started = time.time()
        try:
            got = review.summary_values(ex.extract_summary((tmp / "summary.jpg").read_bytes(), cfg))
            for key in ("total", "tax", "rounding", "stamp"):
                if got[key] != getattr(want_summary, key):
                    mistakes.append(f"summary {key}: read {got[key]}, expected {getattr(want_summary, key)}")
            print(f"  Summary page read in {time.time() - started:.0f} seconds.")

            started = time.time()
            sheet = ex.extract_sheet((tmp / "sheet.jpg").read_bytes(), cfg)
            read = review.frame_to_rows(review.sheet_to_frame(sheet, 1))
            if len(read) != len(rows):
                mistakes.append(f"sheet: read {len(read)} rows, expected {len(rows)}")
            for want, have in zip(rows, read):
                for key in ("serial", "amount", "date"):
                    if getattr(have, key) != getattr(want, key):
                        mistakes.append(
                            f"serial {want.serial} {key}: read {getattr(have, key)}, "
                            f"expected {getattr(want, key)}")
            print(f"  Sheet ({len(rows)} rows) read in {time.time() - started:.0f} seconds.")
        except ex.ExtractionError as e:
            print("  FAIL:", e)
            return 1

    if mistakes:
        print("  FAIL: the model misread the printed test pages:")
        for m in mistakes:
            print("    -", m)
        return 1
    print("  PASS: the model read every number on the Arabic test pages correctly.")
    if not make_test_image.ARABIC_DIGITS:
        print("  Note: this model is reliable with Western digits (0-9). It misreads")
        print("        Arabic-Indic digits, so check those sheets digit by digit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
