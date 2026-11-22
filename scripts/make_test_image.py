"""Draws synthetic sheet + summary photos to try the local model.

Usage:  python scripts/make_test_image.py [output_folder] [western]
Digits are Arabic-Indic (٠-٩) unless "western" is given.
These are printed, not handwritten, so they only prove the pipeline works end to end.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sheetcheck.sample_data import sample_rows, sample_summary  # noqa: E402

AR = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")

try:  # Pillow needs help to join Arabic letters; digits are fine without it.
    import arabic_reshaper
    from bidi.algorithm import get_display

    def shape(text: str) -> str:
        return get_display(arabic_reshaper.reshape(text))
except ImportError:
    def shape(text: str) -> str:
        return text


def font(size: int):
    for name in ("arial.ttf", "tahoma.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


ARABIC_DIGITS = True      # set to False to draw Western digits (0-9)


def ar(value) -> str:
    return str(value).translate(AR) if ARABIC_DIGITS else str(value)


def draw_sheet(rows, number: int, path: Path) -> None:
    img = Image.new("RGB", (1000, 240 + 90 * len(rows)), "#fbfaf5")
    d = ImageDraw.Draw(img)
    big, mid = font(44), font(40)
    d.text((500, 50), shape(f"كشف رقم {ar(number)}"), font=big, fill="#111", anchor="mm")
    xs = (60, 340, 660, 940)                      # column borders, left to right
    top = 110
    headers = ("التاريخ", "المبلغ", "التسلسل")    # drawn left to right; serial is rightmost
    bottom = top + 90 * (len(rows) + 1)
    for x in xs:
        d.line((x, top, x, bottom), fill="#333", width=3)
    for i in range(len(rows) + 2):
        y = top + 90 * i
        d.line((xs[0], y, xs[-1], y), fill="#333", width=3)
    for i, text in enumerate(headers):
        d.text(((xs[i] + xs[i + 1]) // 2, top + 45), shape(text), font=mid, fill="#111", anchor="mm")
    for r, row in enumerate(rows, start=1):
        y = top + 90 * r + 45
        serial = shape(ar(row.serial) + ("م" if row.is_repeat else ""))
        cells = (ar(f"{row.date.day}/{row.date.month}/{row.date.year}"), ar(row.amount), serial)
        for i, text in enumerate(cells):
            d.text(((xs[i] + xs[i + 1]) // 2, y), text, font=mid, fill="#1a237e", anchor="mm")
    img.save(path, quality=92)


def draw_summary(summary, path: Path) -> None:
    img = Image.new("RGB", (1000, 620), "#fbfaf5")
    d = ImageDraw.Draw(img)
    big, mid = font(46), font(42)
    d.text((500, 60), shape("الخلاصة"), font=big, fill="#111", anchor="mm")
    lines = (
        ("المجموع", summary.total),
        ("الضريبة", summary.tax),
        ("فرق التقريب", summary.rounding),
        ("الطابع", summary.stamp),
    )
    for i, (label, value) in enumerate(lines):
        y = 170 + 110 * i
        d.text((900, y), shape(label), font=mid, fill="#111", anchor="rm")
        d.text((120, y), ar(value), font=mid, fill="#1a237e", anchor="lm")
        d.line((80, y + 45, 920, y + 45), fill="#999", width=2)
    img.save(path, quality=92)


def main() -> None:
    global ARABIC_DIGITS
    ARABIC_DIGITS = "western" not in sys.argv[2:]
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "test_images"
    out.mkdir(parents=True, exist_ok=True)
    rows = sample_rows()
    for number in sorted({r.sheet for r in rows}):
        draw_sheet([r for r in rows if r.sheet == number], number, out / f"sheet_{number}.jpg")
    draw_summary(sample_summary(), out / "summary.jpg")
    print(f"Wrote test images to {out}")


if __name__ == "__main__":
    main()
