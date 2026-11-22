"""Bridges between model readings, the editable review table, and verification input."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pandas as pd

from .models import (
    FIELD_LABELS,
    F_AMOUNT,
    F_DATE,
    F_ROUNDING,
    F_SERIAL,
    F_STAMP,
    F_TAX,
    F_TOTAL,
    Reading,
    Row,
    SheetExtraction,
    Summary,
    SummaryExtraction,
)
from .parsing import parse_amount, parse_date, parse_serial

COL_SHEET = "الورقة"
COL_SERIAL = "التسلسل"
COL_REPEAT = "م"
COL_AMOUNT = "المبلغ"
COL_DATE = "التاريخ"
COL_UNCLEAR = "غير واضح"
COL_HINT = "ملاحظة القراءة"
COLUMNS = [COL_SHEET, COL_SERIAL, COL_REPEAT, COL_AMOUNT, COL_DATE, COL_UNCLEAR, COL_HINT]


def _is_blank(value) -> bool:
    return value is None or (not isinstance(value, str) and pd.isna(value)) or value == ""


def _to_decimal(value) -> Decimal | None:
    if _is_blank(value):
        return None
    if isinstance(value, float) and value == int(value):
        return Decimal(int(value))
    return parse_amount(value)


def _hint(field: str, reading: Reading, parsed) -> str:
    """Why a value needs the reviewer's eye; '' when it is fine."""
    parts = []
    if reading.is_unclear:
        parts.append(reading.hint())
    if parsed is None and reading.text:
        parts.append(f"النص المقروء «{reading.text}»")
    return f"{FIELD_LABELS[field]}: " + " — ".join(parts) if parts else ""


def empty_frame() -> pd.DataFrame:
    return _typed(pd.DataFrame(columns=COLUMNS))


def _typed(df: pd.DataFrame) -> pd.DataFrame:
    df = df.reindex(columns=COLUMNS)
    df[COL_SHEET] = pd.to_numeric(df[COL_SHEET], errors="coerce").astype("Int64")
    df[COL_SERIAL] = pd.to_numeric(df[COL_SERIAL], errors="coerce").astype("Int64")
    df[COL_AMOUNT] = pd.to_numeric(df[COL_AMOUNT], errors="coerce").astype("float64")
    df[COL_REPEAT] = df[COL_REPEAT].fillna(False).astype(bool)
    df[COL_UNCLEAR] = df[COL_UNCLEAR].fillna(False).astype(bool)
    df[COL_HINT] = df[COL_HINT].fillna("").astype(str)
    df[COL_DATE] = pd.to_datetime(df[COL_DATE], errors="coerce")
    return df.reset_index(drop=True)


def combine(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """All sheets as one table ordered by sheet number (photos may arrive in any order)."""
    frames = [f for f in frames if f is not None and len(f)]
    if not frames:
        return empty_frame()
    df = pd.concat(frames, ignore_index=True)
    return _typed(df.sort_values(COL_SHEET, kind="stable", na_position="last"))


def sheet_to_frame(
    sheet: SheetExtraction, fallback_number: int, default_year: int | None = None
) -> pd.DataFrame:
    """One editable table per photographed sheet."""
    number, _ = parse_serial(sheet.sheet_number.text)
    number = number if number is not None else fallback_number
    records = []
    for row in sheet.rows:
        serial, is_repeat = parse_serial(row.serial.text)
        amount = parse_amount(row.amount.text)
        day = parse_date(row.date.text, default_year)
        if day is not None and not 1990 <= day.year <= 2100:
            day = None                    # an impossible year is a misreading
        hints = [
            h
            for h in (
                _hint(F_SERIAL, row.serial, serial),
                _hint(F_AMOUNT, row.amount, amount),
                _hint(F_DATE, row.date, day),
            )
            if h
        ]
        records.append(
            {
                COL_SHEET: number,
                COL_SERIAL: serial,
                COL_REPEAT: is_repeat,
                COL_AMOUNT: float(amount) if amount is not None else None,
                COL_DATE: day,
                COL_UNCLEAR: bool(hints),
                COL_HINT: "؛ ".join(hints),
            }
        )
    return _typed(pd.DataFrame(records, columns=COLUMNS))


def rows_to_frame(rows: list[Row]) -> pd.DataFrame:
    records = [
        {
            COL_SHEET: r.sheet,
            COL_SERIAL: r.serial,
            COL_REPEAT: r.is_repeat,
            COL_AMOUNT: float(r.amount) if r.amount is not None else None,
            COL_DATE: r.date,
            COL_UNCLEAR: r.unclear,
            COL_HINT: r.hint,
        }
        for r in rows
    ]
    return _typed(pd.DataFrame(records, columns=COLUMNS))


def _to_date(value) -> date | None:
    if _is_blank(value):
        return None
    if isinstance(value, datetime):       # includes pandas Timestamp
        return value.date()
    if isinstance(value, date):
        return value
    return parse_date(value)


def frame_to_rows(df: pd.DataFrame) -> list[Row]:
    """Reviewed table -> verification rows. Lines left completely empty are dropped."""
    rows = []
    for rec in df.to_dict("records"):
        serial = None if _is_blank(rec.get(COL_SERIAL)) else int(rec[COL_SERIAL])
        amount = _to_decimal(rec.get(COL_AMOUNT))
        day = _to_date(rec.get(COL_DATE))
        if serial is None and amount is None and day is None:
            continue
        sheet = None if _is_blank(rec.get(COL_SHEET)) else int(rec[COL_SHEET])
        hint = rec.get(COL_HINT)
        rows.append(
            Row(
                sheet=sheet,
                serial=serial,
                is_repeat=bool(rec.get(COL_REPEAT)) and not _is_blank(rec.get(COL_REPEAT)),
                amount=amount,
                date=day,
                unclear=bool(rec.get(COL_UNCLEAR)) and not _is_blank(rec.get(COL_UNCLEAR)),
                hint="" if _is_blank(hint) else str(hint),
            )
        )
    return rows


def summary_values(summary: SummaryExtraction) -> dict:
    """Parsed summary numbers plus per-field hints, for the review widgets."""
    out = {"unclear": {}}
    for key, reading in (
        (F_TOTAL, summary.total),
        (F_TAX, summary.tax),
        (F_ROUNDING, summary.rounding),
        (F_STAMP, summary.stamp),
    ):
        value = parse_amount(reading.text)
        out[key] = value
        parts = []
        if reading.is_unclear:
            parts.append(reading.hint())
        if value is None and reading.text:
            parts.append(f"النص المقروء «{reading.text}»")
        if parts:
            out["unclear"][key] = " — ".join(parts)
    return out


def make_summary(total, tax, rounding, stamp, unclear: dict | None = None) -> Summary:
    return Summary(
        total=_to_decimal(total),
        tax=_to_decimal(tax),
        rounding=_to_decimal(rounding),
        stamp=_to_decimal(stamp),
        unclear=dict(unclear or {}),
    )
