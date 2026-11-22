from datetime import date
from decimal import Decimal

from sheetcheck.models import Row, Summary
from sheetcheck.sample_data import PREVIOUS_LAST_SERIAL, QUARTER, sample_rows, sample_summary
from sheetcheck.verification import (
    Settings,
    format_ranges,
    reference_rounding,
    verify,
)


def run(rows=None, summary=None, prev=PREVIOUS_LAST_SERIAL, quarter=QUARTER, settings=None):
    return verify(
        sample_rows() if rows is None else rows,
        sample_summary() if summary is None else summary,
        prev,
        quarter,
        settings,
    )


def repeat_of(row: Row, amount=50000) -> Row:
    return Row(sheet=row.sheet, serial=row.serial, is_repeat=True,
               amount=Decimal(amount), date=row.date)


# --- baseline ---------------------------------------------------------------

def test_clean_batch_passes():
    r = run()
    assert r.ok
    assert r.warnings == [] and r.unclear == [] and r.notes == []
    assert r.computed_total == Decimal(1900000)
    assert r.exact_tax == Decimal(95000)


# --- a) total ------------------------------------------------------------------

def test_total_mismatch_is_flagged_with_difference():
    summary = sample_summary()
    summary.total = Decimal(1890000)
    r = run(summary=summary)
    assert not r.ok
    assert r.total_diff == Decimal(10000)
    assert any("لا يطابق الرقم 1" in w for w in r.warnings)


def test_repeated_rows_are_included_in_the_sum():
    rows = sample_rows()
    rows.insert(5, repeat_of(rows[4], amount=50000))      # 1205م
    summary = Summary(total=Decimal(1950000), tax=Decimal(97500),
                      rounding=Decimal(2500), stamp=Decimal(2500))
    r = run(rows=rows, summary=summary)
    assert r.computed_total == Decimal(1950000)
    assert r.ok


# --- b) tax and rounding ---------------------------------------------------------

def test_exact_tax_is_five_percent():
    assert run().exact_tax == Decimal(1900000) * Decimal("0.05")


def test_tax_underpaid_warns_with_amount_owed():
    summary = sample_summary()
    summary.tax = Decimal(90000)
    r = run(summary=summary)
    assert r.tax_owed == Decimal(5000)
    assert any("المبلغ المستحق 5,000" in w for w in r.warnings)
    assert not r.ok


def test_reference_rounding_rounds_up_to_next_10000():
    assert reference_rounding(Decimal(95000), Decimal(10000)) == Decimal(5000)
    assert reference_rounding(Decimal(90001), Decimal(10000)) == Decimal(9999)
    assert reference_rounding(Decimal(100000), Decimal(10000)) == Decimal(0)
    assert reference_rounding(Decimal("7512.5"), Decimal(10000)) == Decimal("2487.5")
    assert run().reference_rounding == Decimal(5000)


def test_separate_rounding_never_warns_below_or_above_reference():
    for written in (Decimal(1000), Decimal(5000), Decimal(9000)):
        summary = sample_summary()
        summary.rounding = written
        r = run(summary=summary)
        assert r.ok, written
        assert r.rounding_written == written
        assert r.merged_rounding is None
        assert len(r.numbers) == 4
        assert r.numbers[2] == ("فرق التقريب", written)


def test_merged_rounding_adds_note_and_shows_three_numbers():
    summary = sample_summary()
    summary.tax = Decimal(100000)     # exact tax 95,000 + rounding 5,000 merged
    summary.rounding = None
    r = run(summary=summary)
    assert r.merged_rounding == Decimal(5000)
    assert len(r.numbers) == 3
    assert [label for label, _ in r.numbers] == ["المجموع", "الضريبة", "الطابع"]
    note = next(n for n in r.notes if "مدمج" in n)
    assert "5,000" in note
    assert "كان يجب دفع كل مبلغ على حدة" in note
    assert r.warnings == []           # a note, not a warning


def test_no_rounding_and_exact_tax_shows_three_numbers_without_note():
    summary = sample_summary()
    summary.rounding = None
    r = run(summary=summary)
    assert len(r.numbers) == 3
    assert r.merged_rounding is None and r.notes == []
    assert r.ok


def test_underpaid_tax_without_rounding_is_not_treated_as_merged():
    summary = sample_summary()
    summary.tax = Decimal(94000)
    summary.rounding = None
    r = run(summary=summary)
    assert r.tax_owed == Decimal(1000)
    assert r.merged_rounding is None


def test_tax_is_computed_on_the_summed_amounts_not_the_written_total():
    summary = sample_summary()
    summary.total = Decimal(2000000)      # written total is wrong
    r = run(summary=summary)
    assert r.exact_tax == Decimal(95000)


def test_tax_tolerance_setting():
    summary = sample_summary()
    summary.tax = Decimal(94999)
    assert run(summary=summary).tax_owed == Decimal(1)
    assert run(summary=summary, settings=Settings(tax_tolerance=Decimal(1))).tax_owed is None


# --- c) stamp ------------------------------------------------------------------

def test_stamp_is_copied_as_is():
    summary = sample_summary()
    summary.stamp = Decimal(123456)
    r = run(summary=summary)
    assert r.stamp == Decimal(123456)
    assert r.numbers[-1] == ("الطابع", Decimal(123456))
    assert r.ok


# --- d) serial sequence ------------------------------------------------------------

def test_sequence_ok_counts_match():
    r = run()
    assert (r.first_serial, r.last_serial) == (1201, 1210)
    assert r.serial_count == r.expected_count == 10


def test_first_serial_must_follow_previous_batch():
    r = run(prev=1198)
    assert any("أول تسلسل هو 1201 والمتوقع 1199" in w for w in r.warnings)
    assert any("عدد التسلسلات 10 والمتوقع 12" in w for w in r.warnings)


def test_gap_is_reported():
    rows = [row for row in sample_rows() if row.serial not in (1204, 1205)]
    r = run(rows=rows)
    assert r.missing_serials == [1204, 1205]
    assert any("تسلسلات ناقصة: 1204–1205" in w for w in r.warnings)
    assert any("عدد التسلسلات 8 والمتوقع 10" in w for w in r.warnings)


def test_out_of_order_is_reported_without_false_gap():
    rows = sample_rows()
    rows[3], rows[4] = rows[4], rows[3]       # 1205 before 1204
    r = run(rows=rows)
    assert r.out_of_order_serials == [1204]
    assert r.missing_serials == []
    assert any("خارج الترتيب: 1204" in w for w in r.warnings)


def test_repeat_does_not_advance_sequence_and_is_listed_in_notes():
    rows = sample_rows()
    rows.insert(5, repeat_of(rows[4]))         # 1205 then 1205م
    summary = Summary(total=Decimal(1950000), tax=Decimal(97500),
                      rounding=Decimal(2500), stamp=Decimal(2500))
    r = run(rows=rows, summary=summary)
    assert r.repeated_serials == [1205]
    assert r.notes == ["تسلسلات مكررة: 1205م"]
    assert r.serial_count == 10 and r.expected_count == 10
    assert r.missing_serials == [] and r.duplicate_serials == []
    assert r.ok


def test_duplicate_without_repeat_mark_is_a_warning():
    rows = sample_rows()
    dup = repeat_of(rows[4], amount=0)
    dup.is_repeat = False
    rows.insert(5, dup)
    r = run(rows=rows)
    assert r.duplicate_serials == [1205]
    assert any("بدون علامة م: 1205" in w for w in r.warnings)


def test_format_ranges():
    assert format_ranges([5, 6, 7, 10]) == "5–7، 10"
    assert format_ranges([3]) == "3"
    assert format_ranges([]) == ""


# --- e) dates ------------------------------------------------------------------

def test_month_and_quarter_are_extracted():
    r = run()
    assert r.months == [(2026, 7)]
    assert r.main_month == (2026, 7)
    assert r.quarters == [(2026, 3)]


def test_date_outside_selected_quarter_warns():
    rows = sample_rows()
    rows[2].date = date(2026, 6, 30)           # Q2
    rows[7].date = date(2025, 8, 1)            # right quarter number, wrong year
    r = run(rows=rows)
    assert len(r.dates_outside) == 2
    warning = next(w for w in r.warnings if "تواريخ خارج الربع 3 لسنة 2026" in w)
    assert "30/6/2026" in warning and "1/8/2025" in warning


def test_dates_in_other_months_of_the_same_quarter_are_fine():
    rows = sample_rows()
    rows[9].date = date(2026, 9, 30)
    r = run(rows=rows)
    assert r.ok
    assert r.months == [(2026, 7), (2026, 9)]
    assert r.main_month == (2026, 7)


# --- f) unclear numbers ------------------------------------------------------------

def test_unreadable_values_go_to_unclear_list():
    rows = sample_rows()
    rows[1].amount = None
    rows[2].unclear = True
    rows[2].hint = "المبلغ: 9 أو 4"
    summary = sample_summary()
    summary.tax = None
    summary.unclear = {"stamp": "ختم فوق الرقم"}
    r = run(rows=rows, summary=summary)
    assert not r.ok
    assert any("تسلسل 1202" in u and "المبلغ غير مقروء" in u for u in r.unclear)
    assert any("تسلسل 1203" in u and "9 أو 4" in u for u in r.unclear)
    assert any("الرقم 2" in u and "غير مقروء" in u for u in r.unclear)
    assert any("الطابع" in u and "ختم فوق الرقم" in u for u in r.unclear)


def test_notes_text_combines_notes_warnings_and_unclear():
    rows = sample_rows()
    rows.insert(5, repeat_of(rows[4], amount=0))
    rows[0].unclear = True
    summary = sample_summary()
    summary.tax = Decimal(90000)
    text = run(rows=rows, summary=summary).notes_text()
    assert "1205م" in text and "المبلغ المستحق" in text and "أرقام غير واضحة" in text


# --- previous batch's last serial is derived when not given -----------------------

def test_previous_serial_is_smallest_serial_minus_one():
    r = run(prev=None)
    assert r.ok and r.previous_last_serial == 1200 and r.expected_count == 10


def test_derived_previous_serial_still_finds_gaps():
    rows = [row for row in sample_rows() if row.serial != 1205]
    r = run(rows=rows, summary=Summary(total=sum(x.amount for x in rows), tax=Decimal(95000)),
            prev=None)
    assert r.previous_last_serial == 1200
    assert any("تسلسلات ناقصة: 1205" in w for w in r.warnings)


def test_derived_previous_serial_ignores_repeats():
    rows = sample_rows()
    rows.insert(0, Row(sheet=1, serial=1100, is_repeat=True, amount=Decimal(0), date=rows[0].date))
    r = run(rows=rows, prev=None)
    assert r.previous_last_serial == 1200


# --- quarter is taken from the dates when not given -------------------------------

def test_quarter_comes_from_most_dates():
    rows = sample_rows()
    stray = rows[0]
    rows[0] = Row(sheet=stray.sheet, serial=stray.serial, is_repeat=False, amount=stray.amount,
                  date=date(QUARTER[0], 1, 15))          # one date in quarter 1
    r = run(rows=rows, quarter=None)
    assert r.quarter == QUARTER
    assert any("تواريخ خارج الربع" in w and "15/1/" in w for w in r.warnings)


def test_no_dates_means_no_quarter_check():
    rows = [Row(sheet=x.sheet, serial=x.serial, is_repeat=x.is_repeat, amount=x.amount, date=None)
            for x in sample_rows()]
    r = run(rows=rows, quarter=None)
    assert r.quarter is None and not any("خارج الربع" in w for w in r.warnings)
