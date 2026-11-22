"""Turning handwritten-style text (Arabic or Latin digits) into numbers and dates.

The vision model only transcribes what it sees as text; every conversion to a
number or a date happens here so it is deterministic and unit-tested.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

# Arabic-Indic (٠-٩) and Eastern Arabic/Persian (۰-۹) digits -> ASCII
_DIGIT_MAP = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}
_DIGIT_MAP.update({ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")})

REPEAT_MARK = "م"


def normalize_digits(text: str) -> str:
    return str(text).translate(_DIGIT_MAP)


def parse_amount(text) -> Decimal | None:
    """'١٥٠٬٠٠٠' / '150,000' / '150 000 ل.س' -> Decimal(150000). None if unreadable."""
    if text is None:
        return None
    if isinstance(text, (int, Decimal)):
        return Decimal(text)
    if isinstance(text, float):
        if text != text:  # NaN from an empty table cell
            return None
        return Decimal(str(text))
    s = normalize_digits(str(text)).strip()
    if not s:
        return None
    # "٫" is the Arabic decimal separator, "٬" the thousands separator.
    s = s.replace("٫", ".").replace("٬", ",")
    # A letter or symbol stuck between digits ("9x000", "15?000") means the reading
    # is garbled; refuse it rather than silently dropping the character.
    if re.search(r"\d[^\d\s.,]+\d", s):
        return None
    s = re.sub(r"[^\d.,\-]", "", s)
    if not re.search(r"\d", s):
        return None
    # A dot/comma followed by exactly 1-2 trailing digits is a decimal part;
    # everything else is a thousands separator.
    m = re.match(r"^(-?[\d.,]*?)[.,](\d{1,2})$", s)
    if m and re.search(r"\d", m.group(1)):
        whole = re.sub(r"[.,]", "", m.group(1))
        s = f"{whole}.{m.group(2)}"
    else:
        s = re.sub(r"[.,]", "", s)
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_serial(text) -> tuple[int | None, bool]:
    """'١٢٥٥م' -> (1255, True). Returns (None, flag) if no number is readable."""
    if text is None:
        return None, False
    if isinstance(text, int):
        return text, False
    if isinstance(text, float):
        if text != text:
            return None, False
        return int(text), False
    s = normalize_digits(str(text)).strip()
    # "م" counts only when attached to the number (1255م / م1255), not inside a word.
    is_repeat = "مكرر" in s.replace("ّ", "") or bool(
        re.search(r"\d\s*م(?![ء-ي])|(?<![ء-ي])م\s*\d", s)
    )
    digits = re.sub(r"\D", "", s)
    if not digits:
        return None, is_repeat
    return int(digits), is_repeat


def format_serial(serial: int | None, is_repeat: bool = False) -> str:
    if serial is None:
        return ""
    return f"{serial}{REPEAT_MARK}" if is_repeat else str(serial)


def parse_date(text, default_year: int | None = None) -> date | None:
    """Day-first dates: '٣/٧/٢٠٢٦', '3-7-26', '2026-07-03', '3/7' (needs default_year)."""
    if text is None:
        return None
    if isinstance(text, date):
        return text
    s = normalize_digits(str(text)).strip()
    if not s:
        return None
    parts = [p for p in re.split(r"[^\d]+", s) if p]
    try:
        if len(parts) == 3:
            a, b, c = (int(p) for p in parts)
            if len(parts[0]) == 4:  # ISO: yyyy-mm-dd
                y, m, d = a, b, c
            else:  # day/month/year
                d, m, y = a, b, c
                if y < 100:
                    y += 2000
            return date(y, m, d)
        if len(parts) == 2 and default_year:
            d, m = int(parts[0]), int(parts[1])
            return date(default_year, m, d)
    except ValueError:
        return None
    return None


def quarter_of(month: int) -> int:
    return (month - 1) // 3 + 1


def quarter_months(quarter: int) -> list[int]:
    start = (quarter - 1) * 3 + 1
    return [start, start + 1, start + 2]


def fmt_money(value) -> str:
    """Thousands-separated, no trailing zeros: Decimal('7512.50') -> '7,512.5'."""
    if value is None:
        return "—"
    d = Decimal(value)
    if d == d.to_integral_value():
        return f"{int(d):,}"
    return f"{d.normalize():,f}"
