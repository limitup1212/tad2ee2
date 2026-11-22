"""Sample batch used by the unit tests and by the app's "try without photos" mode."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from .models import Row, Summary

PREVIOUS_LAST_SERIAL = 1200
QUARTER = (2026, 3)   # July-September 2026

_AMOUNTS = [150000, 275000, 90000, 410000, 125000, 60000, 330000, 85000, 220000, 155000]


def sample_rows() -> list[Row]:
    """Ten rows, serials 1201-1210, two sheets, all in July 2026. Sum = 1,900,000."""
    rows = []
    for i, amount in enumerate(_AMOUNTS):
        rows.append(
            Row(
                sheet=1 if i < 5 else 2,
                serial=PREVIOUS_LAST_SERIAL + 1 + i,
                is_repeat=False,
                amount=Decimal(amount),
                date=date(2026, 7, 1 + i),
            )
        )
    return rows


def sample_summary() -> Summary:
    """Matches sample_rows(): total 1,900,000, exact tax 95,000, rounding 5,000."""
    return Summary(
        total=Decimal(1900000),
        tax=Decimal(95000),
        rounding=Decimal(5000),
        stamp=Decimal(2500),
    )
