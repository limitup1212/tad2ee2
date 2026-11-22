"""Fills the .xlsx form (Excel 2007+) using the cell map from config.yaml."""
from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils.cell import coordinate_from_string, column_index_from_string

from .verification import Result, month_label

FIELD_NAMES = {
    "name": "الاسم",
    "serial_from": "أول تسلسل",
    "serial_to": "آخر تسلسل",
    "date": "التاريخ",
    "month": "الشهر",
    "total": "الرقم 1 — المجموع",
    "tax": "الرقم 2 — الضريبة",
    "rounding": "الرقم 3 — فرق التقريب",
    "stamp": "الطابع",
    "notes": "الملاحظات",
}
MONEY_KEYS = ("total", "tax", "rounding", "stamp")


def _excel_number(value):
    """Decimal -> int when whole, else float; other types unchanged."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def build_values(name: str, form_date: date, result: Result) -> dict:
    """The values the form can receive. `rounding` is None when there are 3 numbers."""
    return {
        "name": name,
        "serial_from": result.first_serial,
        "serial_to": result.last_serial,
        "date": form_date,
        "month": month_label(result.main_month) if result.main_month else None,
        "total": result.computed_total,
        "tax": result.tax_written,
        "rounding": result.rounding_written,
        "stamp": result.stamp,
        "notes": result.notes_text(),
    }


def _anchor(ws, coord: str):
    """A merged range can only be written through its top-left cell."""
    col_letter, row = coordinate_from_string(coord)
    col = column_index_from_string(col_letter)
    for rng in ws.merged_cells.ranges:
        if rng.min_row <= row <= rng.max_row and rng.min_col <= col <= rng.max_col:
            return ws.cell(row=rng.min_row, column=rng.min_col)
    return ws.cell(row=row, column=col)


def fill_form(template, cells: dict, values: dict, sheet: str | None = None) -> bytes:
    """`template` is a path or the bytes of an .xlsx file. Returns the filled file."""
    source = io.BytesIO(template) if isinstance(template, (bytes, bytearray)) else template
    wb = load_workbook(source)
    if sheet:
        if sheet not in wb.sheetnames:
            raise ValueError(f"الورقة «{sheet}» غير موجودة في ملف النموذج")
        ws = wb[sheet]
    else:
        ws = wb.worksheets[0]

    for key, coord in (cells or {}).items():
        if not coord or key not in values:
            continue
        try:
            cell = _anchor(ws, str(coord).strip().upper())
        except Exception as e:
            raise ValueError(
                f"عنوان الخلية «{coord}» للحقل «{FIELD_NAMES.get(key, key)}» غير صحيح"
            ) from e
        value = _excel_number(values[key])
        cell.value = value
        if cell.number_format == "General":
            if isinstance(value, date):
                cell.number_format = "DD/MM/YYYY"
            elif key in MONEY_KEYS and isinstance(value, (int, float)):
                cell.number_format = "#,##0" if isinstance(value, int) else "#,##0.00"

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def create_default_template(path: Path) -> Path:
    """A simple right-to-left form matching the default cell map in config.yaml."""
    wb = Workbook()
    ws = wb.active
    ws.title = "النموذج"
    ws.sheet_view.rightToLeft = True

    thin = Side(style="thin", color="999999")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    label_fill = PatternFill("solid", fgColor="EEF2F7")
    bold = Font(bold=True, size=12)

    for col, width in zip("ABCDE", (3, 20, 22, 12, 22)):
        ws.column_dimensions[col].width = width

    ws.merge_cells("B1:E1")
    ws["B1"] = "نموذج تدقيق الكشوف"
    ws["B1"].font = Font(bold=True, size=16)
    ws["B1"].alignment = Alignment(horizontal="center")

    labels = {
        "B3": "الاسم",
        "B4": "التسلسل من", "D4": "إلى",
        "B5": "التاريخ", "D5": "الشهر",
        "B7": "المجموع",
        "B8": "الضريبة",
        "B9": "فرق التقريب",
        "B10": "الطابع",
        "B11": "الملاحظات",
    }
    for coord, text in labels.items():
        ws[coord] = text
        ws[coord].font = bold
        ws[coord].fill = label_fill
        ws[coord].border = box
        ws[coord].alignment = Alignment(horizontal="right", vertical="center")

    ws.merge_cells("C3:E3")
    ws.merge_cells("B12:E17")
    for coord in ("C3", "C4", "E4", "C5", "E5", "C7", "C8", "C9", "C10"):
        ws[coord].border = box
        ws[coord].alignment = Alignment(horizontal="center", vertical="center")
    ws["C5"].number_format = "DD/MM/YYYY"
    ws["B12"].alignment = Alignment(horizontal="right", vertical="top", wrap_text=True)
    for row in ws["B12:E17"]:
        for cell in row:
            cell.border = box

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
