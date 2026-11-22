"""Verification rules. Pure functions: no I/O, no model calls, fully unit-tested.

Rules (see README for the full wording):
  a) sum of all amounts (repeated "م" rows included) == number 1
  b) exact tax = total x rate; underpayment warning; rounding difference handling
  c) stamp copied as-is
  d) serial sequence: starts at previous_last + 1, no gaps, in order, count matches
     (previous_last is the smallest serial on the sheets minus 1 unless given)
  e) dates: month / quarter, warn on dates outside the selected quarter
  f) anything not read clearly is listed under "unclear numbers"
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

from .models import FIELD_LABELS, F_STAMP, F_TAX, F_TOTAL, Row, Summary
from .parsing import fmt_money, format_serial, quarter_of


@dataclass
class Settings:
    tax_rate: Decimal = Decimal("0.05")
    rounding_unit: Decimal = Decimal("10000")
    # Differences up to this size between number 2 and the exact tax are ignored.
    tax_tolerance: Decimal = Decimal("0")


@dataclass
class Result:
    # a) totals
    computed_total: Decimal = Decimal(0)
    written_total: Decimal | None = None
    total_diff: Decimal | None = None          # computed - written
    # b) tax
    exact_tax: Decimal = Decimal(0)
    tax_written: Decimal | None = None
    tax_owed: Decimal | None = None            # set when number 2 < exact tax
    reference_rounding: Decimal = Decimal(0)
    rounding_written: Decimal | None = None    # number 3 when written separately
    merged_rounding: Decimal | None = None     # set when merged into number 2
    # c) stamp
    stamp: Decimal | None = None
    # d) serials
    previous_last_serial: int | None = None
    first_serial: int | None = None
    last_serial: int | None = None
    serial_count: int = 0
    expected_count: int | None = None
    missing_serials: list[int] = field(default_factory=list)
    out_of_order_serials: list[int] = field(default_factory=list)
    duplicate_serials: list[int] = field(default_factory=list)   # repeated WITHOUT "م"
    repeated_serials: list[int] = field(default_factory=list)    # marked "م"
    # e) dates
    months: list[tuple[int, int]] = field(default_factory=list)  # (year, month), sorted
    main_month: tuple[int, int] | None = None                    # most frequent month
    quarters: list[tuple[int, int]] = field(default_factory=list)
    quarter: tuple[int, int] | None = None   # (year, quarter) checked, from the dates unless given
    dates_outside: list[Row] = field(default_factory=list)
    # output
    numbers: list[tuple[str, Decimal | None]] = field(default_factory=list)  # 3 or 4
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    unclear: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.warnings and not self.unclear

    def notes_text(self) -> str:
        """Everything worth writing into the form's notes cell."""
        lines = list(self.notes) + list(self.warnings)
        if self.unclear:
            lines.append("أرقام غير واضحة: " + "؛ ".join(self.unclear))
        return "\n".join(lines)


def reference_rounding(exact_tax: Decimal, unit: Decimal) -> Decimal:
    """Exact tax rounded UP to the next multiple of `unit`, minus the exact tax."""
    if unit <= 0:
        return Decimal(0)
    rounded_up = Decimal(math.ceil(exact_tax / unit)) * unit
    return rounded_up - exact_tax


def format_ranges(numbers: list[int]) -> str:
    """[5, 6, 7, 10] -> '5–7، 10' so a long gap stays readable."""
    if not numbers:
        return ""
    nums = sorted(set(numbers))
    out, start, prev = [], nums[0], nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        out.append(str(start) if start == prev else f"{start}–{prev}")
        start = prev = n
    out.append(str(start) if start == prev else f"{start}–{prev}")
    return "، ".join(out)


def _row_label(row: Row) -> str:
    parts = []
    if row.sheet is not None:
        parts.append(f"ورقة {row.sheet}")
    if row.serial is not None:
        parts.append(f"تسلسل {format_serial(row.serial, row.is_repeat)}")
    return "، ".join(parts) or "سطر بدون تسلسل"


def verify(
    rows: list[Row],
    summary: Summary,
    previous_last_serial: int | None = None,
    quarter: tuple[int, int] | None = None,   # (year, quarter 1-4)
    settings: Settings | None = None,
) -> Result:
    st = settings or Settings()
    r = Result(previous_last_serial=previous_last_serial)

    _check_total(rows, summary, r)
    _check_tax(summary, r, st)
    r.stamp = summary.stamp                      # c) as-is, no checks
    _check_serials(rows, r)
    _check_dates(rows, quarter, r)
    _collect_unclear(rows, summary, r)

    # The 3 or 4 numbers that go on the form.
    r.numbers = [("المجموع", r.computed_total), ("الضريبة", r.tax_written)]
    if r.rounding_written is not None:
        r.numbers.append(("فرق التقريب", r.rounding_written))
    r.numbers.append(("الطابع", r.stamp))
    return r


# --- a) total -------------------------------------------------------------

def _check_total(rows: list[Row], summary: Summary, r: Result) -> None:
    # Repeated "م" rows are real amounts and are included in the sum.
    r.computed_total = sum((row.amount for row in rows if row.amount is not None), Decimal(0))
    r.written_total = summary.total
    if summary.total is None:
        return
    r.total_diff = r.computed_total - summary.total
    if r.total_diff != 0:
        r.warnings.append(
            f"مجموع المبالغ المحسوب ({fmt_money(r.computed_total)}) لا يطابق الرقم 1 "
            f"المكتوب ({fmt_money(summary.total)}) — الفرق {fmt_money(r.total_diff)}"
        )


# --- b) tax and rounding difference ---------------------------------------

def _check_tax(summary: Summary, r: Result, st: Settings) -> None:
    r.exact_tax = r.computed_total * st.tax_rate
    r.reference_rounding = reference_rounding(r.exact_tax, st.rounding_unit)
    r.tax_written = summary.tax
    r.rounding_written = summary.rounding
    if summary.tax is None:
        return

    diff = summary.tax - r.exact_tax
    if diff < -st.tax_tolerance:
        r.tax_owed = -diff
        r.warnings.append(
            f"الضريبة المدفوعة ({fmt_money(summary.tax)}) أقل من الضريبة الدقيقة "
            f"({fmt_money(r.exact_tax)}) — المبلغ المستحق {fmt_money(r.tax_owed)}"
        )
    elif diff > st.tax_tolerance and summary.rounding is None:
        # No separate number 3 and number 2 exceeds the exact tax:
        # the rounding difference was merged into the tax.
        r.merged_rounding = diff
        r.notes.append(
            f"فرق التقريب مدمج مع الضريبة بقيمة {fmt_money(diff)} — "
            "كان يجب دفع كل مبلغ على حدة"
        )
    # A separately written number 3 is shown as-is: no warning whether it is
    # below or above the reference rounding difference.


# --- d) serial sequence ----------------------------------------------------

def _check_serials(rows: list[Row], r: Result) -> None:
    # A repeated serial ("م") does not advance the sequence; it is only listed.
    r.repeated_serials = [row.serial for row in rows if row.is_repeat and row.serial is not None]
    if r.repeated_serials:
        r.notes.append(
            "تسلسلات مكررة: " + "، ".join(format_serial(s, True) for s in r.repeated_serials)
        )

    seq = [row.serial for row in rows if not row.is_repeat and row.serial is not None]
    r.serial_count = len(seq)
    if not seq:
        return

    if r.previous_last_serial is None:
        # The previous batch ended just before the smallest serial in this one.
        r.previous_last_serial = min(seq) - 1
    prev_last = r.previous_last_serial
    r.first_serial = seq[0]
    r.last_serial = max(seq)
    r.expected_count = r.last_serial - prev_last

    if r.first_serial != prev_last + 1:
        r.warnings.append(
            f"أول تسلسل هو {r.first_serial} والمتوقع {prev_last + 1} "
            f"(آخر تسلسل في الدفعة السابقة {prev_last})"
        )

    seen: set[int] = set()
    running_max = None
    for s in seq:
        if s in seen:
            if s not in r.duplicate_serials:
                r.duplicate_serials.append(s)
        elif running_max is not None and s < running_max:
            r.out_of_order_serials.append(s)
        seen.add(s)
        running_max = s if running_max is None else max(running_max, s)

    r.missing_serials = [n for n in range(min(seen), r.last_serial + 1) if n not in seen]

    if r.missing_serials:
        r.warnings.append("تسلسلات ناقصة: " + format_ranges(r.missing_serials))
    if r.out_of_order_serials:
        r.warnings.append(
            "تسلسلات خارج الترتيب: " + "، ".join(str(s) for s in r.out_of_order_serials)
        )
    if r.duplicate_serials:
        r.warnings.append(
            "تسلسلات متكررة بدون علامة م: " + "، ".join(str(s) for s in r.duplicate_serials)
        )
    if r.serial_count != r.expected_count:
        r.warnings.append(
            f"عدد التسلسلات {r.serial_count} والمتوقع {r.expected_count} "
            f"(آخر تسلسل {r.last_serial} − آخر تسلسل سابق {prev_last})"
        )


# --- e) dates ----------------------------------------------------------------

def _check_dates(rows: list[Row], quarter: tuple[int, int] | None, r: Result) -> None:
    dated = [row for row in rows if row.date is not None]
    month_counts = Counter((row.date.year, row.date.month) for row in dated)
    r.months = sorted(month_counts)
    r.quarters = sorted({(y, quarter_of(m)) for y, m in month_counts})
    if month_counts:
        r.main_month = month_counts.most_common(1)[0][0]
    if quarter is None and dated:
        # Not given: the quarter most of the dates fall in (months 1-3 -> 1, 4-6 -> 2, ...).
        votes = Counter((row.date.year, quarter_of(row.date.month)) for row in dated)
        quarter = votes.most_common(1)[0][0]
    if quarter is None:
        return
    r.quarter = (int(quarter[0]), int(quarter[1]))
    r.dates_outside = [
        row for row in dated if (row.date.year, quarter_of(row.date.month)) != tuple(quarter)
    ]
    if r.dates_outside:
        listed = "، ".join(
            f"{row.date.day}/{row.date.month}/{row.date.year} ({_row_label(row)})"
            for row in r.dates_outside
        )
        r.warnings.append(
            f"تواريخ خارج الربع {quarter[1]} لسنة {quarter[0]}: {listed}"
        )


# --- f) unclear numbers --------------------------------------------------------

def _collect_unclear(rows: list[Row], summary: Summary, r: Result) -> None:
    for row in rows:
        label = _row_label(row)
        problems = []
        if row.serial is None:
            problems.append("التسلسل غير مقروء")
        if row.amount is None:
            problems.append("المبلغ غير مقروء")
        if row.date is None:
            problems.append("التاريخ غير مقروء")
        if row.unclear:
            problems.append(row.hint or "قراءة غير واضحة")
        if problems:
            r.unclear.append(f"{label}: " + "، ".join(problems))

    for key, value in ((F_TOTAL, summary.total), (F_TAX, summary.tax), (F_STAMP, summary.stamp)):
        if value is None:
            r.unclear.append(f"{FIELD_LABELS[key]}: غير مقروء")
    for key, hint in summary.unclear.items():
        r.unclear.append(f"{FIELD_LABELS.get(key, key)}: {hint or 'قراءة غير واضحة'}")


def month_label(ym: tuple[int, int] | None) -> str:
    if ym is None:
        return "—"
    return f"{ym[1]}/{ym[0]}"
