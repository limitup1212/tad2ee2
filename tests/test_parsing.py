from datetime import date
from decimal import Decimal

from sheetcheck.parsing import (
    fmt_money,
    format_serial,
    parse_amount,
    parse_date,
    parse_serial,
    quarter_months,
    quarter_of,
)


def test_parse_amount_arabic_digits_and_separators():
    assert parse_amount("١٥٠٬٠٠٠") == Decimal(150000)
    assert parse_amount("150,000") == Decimal(150000)
    assert parse_amount("150.000") == Decimal(150000)
    assert parse_amount("1 250 000 ل.س") == Decimal(1250000)
    assert parse_amount("7512.5") == Decimal("7512.5")
    assert parse_amount("٧٥١٢٫٥٠") == Decimal("7512.50")
    assert parse_amount(95000) == Decimal(95000)


def test_parse_amount_unreadable():
    assert parse_amount("") is None
    assert parse_amount(None) is None
    assert parse_amount("؟؟") is None
    assert parse_amount("9x000") is None
    assert parse_amount("15?000") is None
    assert parse_amount(float("nan")) is None


def test_parse_serial_with_repeat_mark():
    assert parse_serial("1255م") == (1255, True)
    assert parse_serial("١٢٥٥ م") == (1255, True)
    assert parse_serial("1255 مكرر") == (1255, True)
    assert parse_serial("1255") == (1255, False)
    assert parse_serial("") == (None, False)
    assert format_serial(1255, True) == "1255م"
    assert format_serial(1255) == "1255"


def test_parse_date_day_first():
    assert parse_date("٣/٧/٢٠٢٦") == date(2026, 7, 3)
    assert parse_date("3-7-26") == date(2026, 7, 3)
    assert parse_date("2026-07-03") == date(2026, 7, 3)
    assert parse_date("3/7", default_year=2026) == date(2026, 7, 3)
    assert parse_date("3/7") is None
    assert parse_date("31/2/2026") is None
    assert parse_date("") is None


def test_quarters():
    assert [quarter_of(m) for m in (1, 3, 4, 9, 10, 12)] == [1, 1, 2, 3, 4, 4]
    assert quarter_months(3) == [7, 8, 9]


def test_fmt_money():
    assert fmt_money(Decimal(1900000)) == "1,900,000"
    assert fmt_money(Decimal("7512.50")) == "7,512.5"
    assert fmt_money(None) == "—"
