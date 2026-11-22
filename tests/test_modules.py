"""Tests for the review table, form filling, aggregation and the offline parts of extraction."""
import io
from datetime import date
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from sheetcheck import aggregation as agg
from sheetcheck import extraction as ex
from sheetcheck import form, review
from sheetcheck.config import DEFAULTS
from sheetcheck.sample_data import PREVIOUS_LAST_SERIAL, QUARTER, sample_rows, sample_summary
from sheetcheck.verification import verify


def result(**summary_changes):
    summary = sample_summary()
    for key, value in summary_changes.items():
        setattr(summary, key, value)
    return verify(sample_rows(), summary, PREVIOUS_LAST_SERIAL, QUARTER)


# --- extraction (no model needed) -----------------------------------------------

SHEET_JSON = {
    "sheet_number": "٢",
    "sheet_date": "",
    "rows": [
        {"serial": "١٢٠١", "amount": "١٥٠٠٠٠", "date": "٣/٧/٢٠٢٦", "unclear": []},
        {"serial": "1202", "amount": "275000", "date": "", "unclear": [
            {"field": "amount", "reason": "الرقم مطموس", "alternatives": ["215000", "275000"]}]},
        {"serial": "1202م", "amount": "9x000", "date": "4/7/2026", "unclear": []},
        {"serial": "", "amount": "", "date": "", "unclear": []},
    ],
}


def test_sheet_json_to_readings():
    sheet = ex.sheet_from_json(SHEET_JSON)
    assert sheet.sheet_number.text == "2"
    assert len(sheet.rows) == 3                       # the empty line is dropped
    assert sheet.rows[0].serial.text == "1201"        # digits normalised
    assert sheet.rows[1].date.text == "3/7/2026"      # blank date repeats the row above
    amount = sheet.rows[1].amount
    assert amount.is_unclear and amount.reason == "الرقم مطموس"
    assert amount.alternatives == ["215000"]          # the reading itself is not an alternative


def test_double_reading_flags_disagreements():
    first = ex.sheet_from_json(SHEET_JSON)
    other = {**SHEET_JSON, "rows": [dict(r) for r in SHEET_JSON["rows"]]}
    other["rows"][0]["amount"] = "180000"
    merged = ex.merge_sheets(first, ex.sheet_from_json(other))
    amount = merged.rows[0].amount
    assert amount.text == "150000" and amount.is_unclear
    assert amount.alternatives == ["180000"]
    assert not merged.rows[0].serial.is_unclear


def test_double_reading_with_different_row_counts_flags_all_rows():
    first = ex.sheet_from_json(SHEET_JSON)
    shorter = ex.sheet_from_json({**SHEET_JSON, "rows": SHEET_JSON["rows"][:1]})
    merged = ex.merge_sheets(first, shorter)
    assert all(row.serial.is_unclear for row in merged.rows)


def test_summary_json_blank_rounding_means_not_written():
    summary = ex.summary_from_json(
        {"total": "١٬٩٠٠٬٠٠٠", "tax": "100000", "rounding": "", "stamp": "2500", "unclear": [
            {"field": "stamp", "reason": "ختم فوق الرقم", "alternatives": ["2600"]}]}
    )
    values = review.summary_values(summary)
    assert values["total"] == Decimal(1900000)
    assert values["rounding"] is None
    assert "ختم فوق الرقم" in values["unclear"]["stamp"]


def test_only_local_ollama_hosts_are_accepted(monkeypatch):
    assert ex.is_local_host("http://127.0.0.1:11434")
    assert ex.is_local_host("http://localhost:11434")
    assert not ex.is_local_host("https://example.com")
    monkeypatch.setenv("OLLAMA_HOST", "https://example.com")
    monkeypatch.delenv("SHEETCHECK_ALLOW_REMOTE", raising=False)
    with pytest.raises(ex.ExtractionError):
        ex._client()


def test_prepare_image_shrinks_and_returns_jpeg():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4000, 3000), "white").save(buf, format="PNG")
    out = Image.open(io.BytesIO(ex.prepare_image(buf.getvalue(), 1600)))
    assert out.format == "JPEG" and max(out.size) == 1600


# --- review table -----------------------------------------------------------------

def test_sheet_to_frame_and_back():
    df = review.sheet_to_frame(ex.sheet_from_json(SHEET_JSON), fallback_number=9)
    assert list(df[review.COL_SHEET]) == [2, 2, 2]
    assert list(df[review.COL_REPEAT]) == [False, False, True]
    assert list(df[review.COL_UNCLEAR]) == [False, True, True]
    assert "بدائل: 215000" in df[review.COL_HINT][1]
    assert "9x000" in df[review.COL_HINT][2]          # garbled amount is not guessed

    rows = review.frame_to_rows(df)
    assert [(r.serial, r.is_repeat) for r in rows] == [(1201, False), (1202, False), (1202, True)]
    assert rows[2].amount is None
    assert rows[0].amount == Decimal(150000) and rows[0].date == date(2026, 7, 3)
    assert rows[1].unclear and not rows[0].unclear


def test_rows_round_trip_through_the_table():
    rows = sample_rows()
    back = review.frame_to_rows(review.rows_to_frame(rows))
    assert [(r.sheet, r.serial, r.amount, r.date) for r in back] == [
        (r.sheet, r.serial, r.amount, r.date) for r in rows
    ]


def test_empty_added_lines_are_ignored():
    df = review.rows_to_frame(sample_rows())
    df.loc[len(df)] = [None, None, None, None, None, None, None]
    assert len(review.frame_to_rows(df)) == 10


# --- form ----------------------------------------------------------------------------

def test_fill_form_writes_mapped_cells(tmp_path):
    template = form.create_default_template(tmp_path / "form.xlsx")
    res = result()
    values = form.build_values("أحمد", date(2026, 7, 31), res)
    data = form.fill_form(template, DEFAULTS["form"]["cells"], values)
    ws = load_workbook(io.BytesIO(data)).worksheets[0]
    assert ws["C3"].value == "أحمد"
    assert (ws["C4"].value, ws["E4"].value) == (1201, 1210)
    assert ws["C5"].value.date() == date(2026, 7, 31)
    assert ws["E5"].value == "7/2026"
    assert (ws["C7"].value, ws["C8"].value, ws["C9"].value, ws["C10"].value) == (
        1900000, 95000, 5000, 2500)


def test_fill_form_three_numbers_leaves_rounding_empty_and_writes_note(tmp_path):
    template = form.create_default_template(tmp_path / "form.xlsx")
    res = result(tax=Decimal(100000), rounding=None)
    data = form.fill_form(
        template, DEFAULTS["form"]["cells"], form.build_values("أحمد", date(2026, 7, 31), res)
    )
    ws = load_workbook(io.BytesIO(data)).worksheets[0]
    assert ws["C8"].value == 100000 and ws["C9"].value is None
    assert "كان يجب دفع كل مبلغ على حدة" in ws["B12"].value      # merged range anchor


def test_fill_form_resolves_merged_cells_and_rejects_bad_addresses(tmp_path):
    template = form.create_default_template(tmp_path / "form.xlsx")
    data = form.fill_form(template, {"notes": "D15"}, {"notes": "ملاحظة"})
    assert load_workbook(io.BytesIO(data)).worksheets[0]["B12"].value == "ملاحظة"
    with pytest.raises(ValueError):
        form.fill_form(template, {"name": "not-a-cell"}, {"name": "x"})


# --- aggregation -----------------------------------------------------------------------

def test_batches_in_the_same_month_are_combined_and_months_sum_to_quarter(tmp_path):
    res = result()
    for name, month in (("أحمد", 7), ("سامر", 7), ("أحمد", 8), ("ليلى", 10)):
        agg.save_batch(agg.batch_from_result(name, 2026, month, res), tmp_path)
    batches = agg.load_batches(tmp_path)
    assert len(batches) == 4

    table = agg.monthly_table(batches, 2026, 3)
    assert list(table[agg.COL_MONTH]) == ["7/2026", "8/2026", "9/2026", agg.QUARTER_ROW]
    assert list(table[agg.COL_COUNT]) == [2, 1, 0, 3]
    assert list(table["المجموع"]) == [3800000, 1900000, 0, 5700000]
    assert list(table["الضريبة"]) == [190000, 95000, 0, 285000]
    assert list(table["فرق التقريب"]) == [10000, 5000, 0, 15000]
    assert list(table["الطابع"]) == [5000, 2500, 0, 7500]


def test_delete_batch_and_last_serial_lookup(tmp_path):
    batch = agg.batch_from_result("أحمد", 2026, 7, result())
    agg.save_batch(batch, tmp_path)
    assert agg.last_serial_for("أحمد", agg.load_batches(tmp_path)) == 1210
    assert agg.last_serial_for("غيره", agg.load_batches(tmp_path)) is None
    agg.delete_batch(batch["id"], tmp_path)
    assert agg.load_batches(tmp_path) == []


def test_export_excel_has_quarter_and_detail_sheets(tmp_path):
    batches = [agg.batch_from_result("أحمد", 2026, 7, result())]
    wb = load_workbook(io.BytesIO(agg.export_excel(batches, 2026, 3)))
    assert wb.sheetnames == ["الربع", "الدفعات"]
    ws = wb["الربع"]
    assert ws.sheet_view.rightToLeft
    assert ws.cell(row=5, column=1).value == agg.QUARTER_ROW
    assert ws.cell(row=5, column=3).value == 1900000


# --- phone inbox ---------------------------------------------------------------------

def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_inbox_keeps_one_summary_and_sheets_in_order(tmp_path):
    from sheetcheck import inbox

    inbox.save(tmp_path, inbox.SUMMARY, _png())
    inbox.save(tmp_path, inbox.SUMMARY, _png())          # a retake replaces the first
    first = inbox.save(tmp_path, inbox.SHEETS, _png())
    inbox.save(tmp_path, inbox.SHEETS, _png())
    assert inbox.counts(tmp_path) == (1, 2)
    assert first.suffix == ".png" and first.parent.name == "sheets"
    assert inbox.summary(tmp_path) and len(inbox.sheets(tmp_path)) == 2
    inbox.clear(tmp_path)
    assert inbox.counts(tmp_path) == (0, 0) and inbox.summary(tmp_path) is None


def test_inbox_rejects_files_that_are_not_images(tmp_path):
    from sheetcheck import inbox

    with pytest.raises(ValueError):
        inbox.save(tmp_path, inbox.SHEETS, b"not an image")
    assert inbox.counts(tmp_path) == (0, 0)


def test_qr_code_is_a_png():
    from sheetcheck import inbox

    assert inbox.qr_png("http://192.168.1.5:8501/?phone=1")[:4] == b"\x89PNG"


# --- reading in strips ------------------------------------------------------------------

def _lined_page(lines: int = 12, width: int = 900, pitch: int = 100):
    """A white page with `lines` dark text bars, one every `pitch` pixels."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (width, pitch * lines), "white")
    draw = ImageDraw.Draw(img)
    for i in range(lines):
        draw.rectangle((60, i * pitch + 30, width - 60, i * pitch + 70), fill="black")
    return img


def test_strips_are_cut_between_written_lines():
    import numpy as np

    page = _lined_page()
    strips = ex.split_strips(page, ratio=3)            # about 300 px each -> 4 strips
    assert len(strips) == 4
    assert sum(s.height for s in strips) >= page.height     # nothing is lost
    for strip in strips:
        gray = np.asarray(strip.convert("L"))
        assert gray[0].min() > 200 and gray[-1].min() > 200  # top and bottom edges are blank paper


def test_whole_page_when_strips_are_off_or_page_is_short():
    page = _lined_page(lines=2)
    assert len(ex.split_strips(page, ratio=0)) == 1
    assert len(ex.split_strips(page, ratio=3)) == 1


def test_join_strips_keeps_a_row_seen_twice_only_once():
    first = ex.rows_from_json({"rows": [
        {"serial": "1201", "amount": "100", "date": "1/7/2026", "unclear": []},
        {"serial": "1202", "amount": "200", "date": "", "unclear": []}]})
    second = ex.rows_from_json({"rows": [
        {"serial": "1202", "amount": "200", "date": "", "unclear": []},
        {"serial": "1203", "amount": "300", "date": "2/7/2026", "unclear": []}]})
    sheet = ex.build_sheet(ex.join_strips([first, [], second]), "٣", "")
    assert [r.serial.text for r in sheet.rows] == ["1201", "1202", "1203"]
    assert sheet.rows[1].date.text == "1/7/2026"            # ditto date still carried down
    assert sheet.sheet_number.text == "3"


def test_runs_of_dots_next_to_arabic_digits_are_zeros():
    sheet = ex.sheet_from_json({"sheet_number": "", "sheet_date": "", "rows": [
        {"serial": "١٢٠١", "amount": "١٩.....", "date": "١/٧/٢٠٢٦", "unclear": []},
        {"serial": "1202", "amount": "150.000", "date": "1/7/2026", "unclear": []}]})
    assert sheet.rows[0].amount.text == "1900000"
    assert sheet.rows[1].amount.text == "150.000"           # Western thousands separator untouched
