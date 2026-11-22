"""Builds dist/tadqeeq-kushoof.zip: everything another computer needs, nothing private.

Saved batches, phone photos, test images and local caches are left out.
Usage:  python scripts/make_package.py
"""
from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "tadqeeq-kushoof"
INCLUDE = [
    "START_HERE.html", "README.md", "requirements.txt", "config.yaml",
    "setup.bat", "run.bat", "run_phone.bat", "_python.bat", "diagnose.bat", "app.py",
    ".streamlit/config.toml",
]
FOLDERS = ["sheetcheck", "scripts", "tests", "templates"]
SKIP_PARTS = {"__pycache__", ".pytest_cache"}


def files():
    for rel in INCLUDE:
        yield ROOT / rel
    for folder in FOLDERS:
        for path in sorted((ROOT / folder).rglob("*")):
            if path.is_file() and not SKIP_PARTS & set(path.parts) and path.suffix != ".pyc":
                yield path


def main() -> None:
    out = ROOT / "dist" / f"{NAME}.zip"
    out.parent.mkdir(exist_ok=True)
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path in files():
            if not path.exists():
                raise SystemExit(f"missing file: {path}")
            z.write(path, f"{NAME}/{path.relative_to(ROOT).as_posix()}")
            count += 1
    print(f"{out}  ({count} files, {out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
