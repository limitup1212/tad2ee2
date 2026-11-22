"""Plain data structures shared by all modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

CLEAR = "clear"
UNCLEAR = "unclear"

# Field keys used across extraction / review / verification
F_SERIAL = "serial"
F_AMOUNT = "amount"
F_DATE = "date"
F_TOTAL = "total"
F_TAX = "tax"
F_ROUNDING = "rounding"
F_STAMP = "stamp"
F_SHEET = "sheet_number"

FIELD_LABELS = {
    F_SERIAL: "التسلسل",
    F_AMOUNT: "المبلغ",
    F_DATE: "التاريخ",
    F_TOTAL: "الرقم 1 (المجموع)",
    F_TAX: "الرقم 2 (الضريبة)",
    F_ROUNDING: "الرقم 3 (فرق التقريب)",
    F_STAMP: "الطابع",
    F_SHEET: "رقم الورقة",
}


@dataclass
class Reading:
    """One value as transcribed from a photo, with its confidence."""
    text: str = ""
    confidence: str = CLEAR          # "clear" | "unclear"
    reason: str = ""
    alternatives: list[str] = field(default_factory=list)

    @property
    def is_unclear(self) -> bool:
        return self.confidence == UNCLEAR

    def hint(self) -> str:
        """Short Arabic description of the doubt, for the review table."""
        if not self.is_unclear:
            return ""
        parts = [self.reason] if self.reason else []
        if self.alternatives:
            parts.append("بدائل: " + " / ".join(self.alternatives))
        return " — ".join(parts) or "غير واضح"


@dataclass
class RowReading:
    serial: Reading = field(default_factory=Reading)
    amount: Reading = field(default_factory=Reading)
    date: Reading = field(default_factory=Reading)


@dataclass
class SheetExtraction:
    sheet_number: Reading = field(default_factory=Reading)
    rows: list[RowReading] = field(default_factory=list)


@dataclass
class SummaryExtraction:
    total: Reading = field(default_factory=Reading)
    tax: Reading = field(default_factory=Reading)
    rounding: Reading = field(default_factory=Reading)   # empty text = not written
    stamp: Reading = field(default_factory=Reading)


@dataclass
class Row:
    """A reviewed sheet row, ready for verification."""
    sheet: int | None
    serial: int | None
    is_repeat: bool
    amount: Decimal | None
    date: date | None
    unclear: bool = False     # still flagged as doubtful after review
    hint: str = ""            # why it is doubtful / alternative readings


@dataclass
class Summary:
    """The reviewed summary page."""
    total: Decimal | None = None      # number 1
    tax: Decimal | None = None        # number 2
    rounding: Decimal | None = None   # number 3 — None when not written separately
    stamp: Decimal | None = None      # copied as-is
    unclear: dict[str, str] = field(default_factory=dict)   # field -> hint
