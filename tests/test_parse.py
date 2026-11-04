"""账单整理与统计点。"""

from datetime import date

from custom_components.pudong_water.api import start_month
from custom_components.pudong_water.parse import (
    bill_history,
    cost_points,
    latest,
    parse_bills,
    to_date,
    water_points,
)

from .conftest import BILLS, bill


def test_dates_and_order():
    assert to_date("2026/3/4 0:00:00") == date(2026, 3, 4)
    assert to_date("2026-01-06 00:00:00") == date(2026, 1, 6)
    bills = parse_bills(list(reversed(BILLS)))
    assert [b.ym for b in bills] == ["2026-01", "2026-03", "2026-05", "2026-07"]
    last = latest(bills)
    assert last.ym == "2026-07" and last.next_read_date == date(2026, 9, 6)
    assert last.amount == 55.92 and last.balance == 12.5


def test_water_points_ignore_meter_swap():
    pts = water_points(parse_bills(BILLS))
    assert pts == [
        (date(2026, 1, 6), 20.0, 20.0),
        (date(2026, 3, 4), 18.0, 38.0),
        (date(2026, 5, 6), 22.0, 60.0),
        (date(2026, 7, 6), 24.0, 84.0),
    ]
    assert water_points(parse_bills(BILLS), date(2026, 5, 6), 60.0) == [(date(2026, 7, 6), 24.0, 84.0)]


def test_cost_uses_sumfee_not_paid():
    pts = cost_points(parse_bills(BILLS))
    assert [p[1] for p in pts] == [46.6, 41.94, 51.26, 55.92]


def test_history_has_no_name_or_address():
    rows = bill_history(parse_bills(BILLS))
    assert rows[0]["账单年月"] == "2026-07"
    assert "样例" not in str(rows)


def test_start_month():
    assert start_month(date(2026, 11, 5)) == "2025-10"
    assert start_month(date(2026, 1, 15)) == "2024-12"
