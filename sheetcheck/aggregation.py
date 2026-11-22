"""Saved batches -> monthly and quarterly totals -> Excel.

Each saved batch (one person's summary page + sheets) belongs to one month.
Every batch saved for a month is added into that month; three months make the quarter.
All data stays in local JSON files under data/batches/.
"""
from __future__ import annotations

import io
import json
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .parsing import quarter_months
from .verification import Result

NUMBER_KEYS = ("total", "tax", "rounding", "stamp")
NUMBER_LABELS = {
    "total": "المجموع",
    "tax": "الضريبة",
    "rounding": "فرق التقريب",
    "stamp": "الطابع",
}
COL_MONTH = "الشهر"
COL_COUNT = "عدد الدفعات"
QUARTER_ROW = "مجموع الربع"


def _num(value) -> int | float:
    d = Decimal(str(value or 0))
    return int(d) if d == d.to_integral_value() else float(d)


def batch_from_result(name: str, year: int, month: int, result: Result) -> dict:
    return {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "year": int(year),
        "month": int(month),
        "total": str(result.computed_total),
        "tax": str(result.tax_written or 0),
        "rounding": str(result.rounding_written or 0),
        "stamp": str(result.stamp or 0),
        "first_serial": result.first_serial,
        "last_serial": result.last_serial,
        "ok": result.ok,
        "notes": result.notes_text(),
    }


# --- storage -------------------------------------------------------------------

def save_batch(batch: dict, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{batch['id']}.json"
    path.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_batches(folder: Path) -> list[dict]:
    if not folder.exists():
        return []
    batches = []
    for path in sorted(folder.glob("*.json")):
        try:
            batches.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return sorted(batches, key=lambda b: b.get("saved_at", ""))


def delete_batch(batch_id: str, folder: Path) -> None:
    path = folder / f"{batch_id}.json"
    if path.exists():
        path.unlink()


def last_serial_for(name: str, batches: list[dict]) -> int | None:
    """Last serial of the most recently saved batch for this person, if any."""
    name = (name or "").strip()
    for batch in reversed(batches):
        if name and batch.get("name", "").strip() == name and batch.get("last_serial"):
            return int(batch["last_serial"])
    return None


# --- aggregation -------------------------------------------------------------------

def monthly_table(batches: list[dict], year: int, quarter: int) -> pd.DataFrame:
    """Three month rows (4 numbers each) plus the quarter total row."""
    records = []
    for month in quarter_months(quarter):
        mine = [b for b in batches if b["year"] == year and b["month"] == month]
        rec = {COL_MONTH: f"{month}/{year}", COL_COUNT: len(mine)}
        for key in NUMBER_KEYS:
            rec[NUMBER_LABELS[key]] = _num(sum((Decimal(b[key]) for b in mine), Decimal(0)))
        records.append(rec)
    total = {COL_MONTH: QUARTER_ROW, COL_COUNT: sum(r[COL_COUNT] for r in records)}
    for key in NUMBER_KEYS:
        label = NUMBER_LABELS[key]
        total[label] = _num(sum(Decimal(str(r[label])) for r in records))
    return pd.DataFrame(records + [total])


def batches_table(batches: list[dict], year: int, quarter: int) -> pd.DataFrame:
    """The individual batches behind a quarter, for the detail sheet."""
    months = quarter_months(quarter)
    records = [
        {
            "الاسم": b["name"],
            COL_MONTH: f"{b['month']}/{b['year']}",
            "من تسلسل": b.get("first_serial"),
            "إلى تسلسل": b.get("last_serial"),
            **{NUMBER_LABELS[k]: _num(b[k]) for k in NUMBER_KEYS},
            "الحالة": "مطابق" if b.get("ok") else "فيه ملاحظات",
            "الملاحظات": b.get("notes", ""),
            "تاريخ الحفظ": b.get("saved_at", ""),
        }
        for b in batches
        if b["year"] == year and b["month"] in months
    ]
    return pd.DataFrame(records)


def export_excel(batches: list[dict], year: int, quarter: int) -> bytes:
    summary = monthly_table(batches, year, quarter)
    details = batches_table(batches, year, quarter)
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="الربع", index=False)
        details.to_excel(writer, sheet_name="الدفعات", index=False)
        for ws in writer.book.worksheets:
            ws.sheet_view.rightToLeft = True
            for cell in ws[1]:
                cell.font = Font(bold=True)
                cell.fill = PatternFill("solid", fgColor="EEF2F7")
                cell.alignment = Alignment(horizontal="center")
            for idx, column in enumerate(ws.columns, start=1):
                width = max(len(str(c.value)) if c.value is not None else 0 for c in column)
                ws.column_dimensions[get_column_letter(idx)].width = min(max(width + 4, 12), 60)
            money_columns = {
                c.column for c in ws[1] if c.value in NUMBER_LABELS.values()
            }
            for row in ws.iter_rows(min_row=2):
                for cell in row:
                    if cell.column in money_columns and isinstance(cell.value, (int, float)):
                        cell.number_format = (
                            "#,##0" if isinstance(cell.value, int) else "#,##0.00"
                        )
        quarter_ws = writer.book["الربع"]
        for cell in quarter_ws[quarter_ws.max_row]:
            cell.font = Font(bold=True)
    return out.getvalue()
