"""把账单整理成集成要用的数据。不依赖 Home Assistant。

字段含义（2026-11 用真实账单核对，6 期都成立）：
- SUMFEE = WATERFEE + DIRTYFEE，是这一期应缴的钱；SUMPAY = FACTFEE 是实际缴的，可能因预存而不同；
- WATERFEE = WATERNUM × WATERPRICE，DIRTYFEE = DIRTYNUM × DIRTYPRICE，污水量约为用水量的 9 成；
- METERDATA − PREVMETERDATA = WATERNUM，换表那期例外（PREVMETERDATA 还是旧表的数）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
import re
from typing import Any

_DATE_RE = re.compile(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})")


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def to_date(value: Any) -> date | None:
    if not value:
        return None
    m = _DATE_RE.search(str(value))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


@dataclass(frozen=True)
class WaterBill:
    year: int
    month: int
    read_date: date | None
    next_read_date: date | None
    meter_status: str | None
    reading: float | None
    water: float | None
    sewage: float | None
    water_price: float | None
    sewage_price: float | None
    water_fee: float | None
    sewage_fee: float | None
    amount: float | None
    paid: float | None
    pay_time: str | None
    balance: float | None
    garbage_fee: float | None = None
    late_fee: float | None = None
    other_fee: float | None = None

    @property
    def ym(self) -> str:
        return f"{self.year}-{self.month:02d}"


def parse_bill(raw: dict[str, Any]) -> WaterBill:
    return WaterBill(
        year=int(to_float(raw.get("YEAR")) or 0),
        month=int(to_float(raw.get("MONTH")) or 0),
        read_date=to_date(raw.get("COPYMETERDATE")),
        next_read_date=to_date(raw.get("NEXTDATE")),
        meter_status=_text(raw.get("COPYMETERSTATUS")),
        reading=to_float(raw.get("METERDATA")),
        water=to_float(raw.get("WATERNUM")),
        sewage=to_float(raw.get("DIRTYNUM")),
        water_price=to_float(raw.get("WATERPRICE")),
        sewage_price=to_float(raw.get("DIRTYPRICE")),
        water_fee=to_float(raw.get("WATERFEE")),
        sewage_fee=to_float(raw.get("DIRTYFEE")),
        amount=to_float(raw.get("SUMFEE")),
        paid=to_float(raw.get("FACTFEE")),
        pay_time=_text(raw.get("PAYTIME")),
        balance=to_float(raw.get("NOWLEFT")),
        garbage_fee=to_float(raw.get("GARBAGEFEE")),
        late_fee=to_float(raw.get("LATEFEES")),
        other_fee=to_float(raw.get("OTHERFEE")),
    )


def parse_bills(raws: list[dict[str, Any]]) -> list[WaterBill]:
    """按账单年月从早到晚排。"""
    bills = [parse_bill(r) for r in raws if isinstance(r, dict)]
    return sorted(bills, key=lambda b: (b.year, b.month, b.read_date or date.min))


def latest(bills: list[WaterBill]) -> WaterBill | None:
    return bills[-1] if bills else None


def cumulative_points(
    bills: list[WaterBill],
    value: Callable[[WaterBill], float | None],
    after: date | None,
    start_sum: float,
) -> list[tuple[date, float, float]]:
    """长期统计点：(抄表日, 本期值, 累计值)。从 start_sum 往上加，只取 after 之后的。

    不用表读数当累计值：换表时读数会变小，而且能源面板会把第一行的累计值整个当成那一期的量。
    """
    points: list[tuple[date, float, float]] = []
    total = start_sum
    for b in bills:
        v = value(b)
        if b.read_date is None or v is None:
            continue
        if after is not None and b.read_date <= after:
            continue
        if points and points[-1][0] == b.read_date:
            total -= points.pop()[1]
        total += v
        points.append((b.read_date, v, total))
    return points


def water_points(bills, after=None, start_sum=0.0):
    return cumulative_points(bills, lambda b: b.water, after, start_sum)


def cost_points(bills, after=None, start_sum=0.0):
    return cumulative_points(bills, lambda b: b.amount, after, start_sum)


def year_cost(bills: list[WaterBill]) -> dict[str, Any] | None:
    """最新一期账单所在自然年（按账单年月）的累计水费与用水量。接口只给约一年，所以只算今年。"""
    if not bills:
        return None
    year = bills[-1].year
    this = [b for b in bills if b.year == year]
    water = sum(b.water or 0 for b in this)
    cost = sum(b.amount or 0 for b in this)
    return {
        "year": year,
        "cost": round(cost, 2),
        "water": round(water, 2),
        "periods": len(this),
        "unit_price": round(cost / water, 3) if water else None,
    }


def extra_fees(bill: WaterBill | None) -> dict[str, Any]:
    """水费、污水费之外的费用项，不为 0 才列。"""
    if bill is None:
        return {}
    return {k: v for k, v in (("垃圾费", bill.garbage_fee), ("滞纳金", bill.late_fee), ("其他费用", bill.other_fee)) if v}


def bill_history(bills: list[WaterBill]) -> list[dict[str, Any]]:
    """给传感器属性用的近期账单（新的在前）。"""
    return [
        {
            "账单年月": b.ym,
            "抄表日": b.read_date.isoformat() if b.read_date else None,
            "用水量": b.water,
            "污水量": b.sewage,
            "金额": b.amount,
            "抄表方式": b.meter_status,
        }
        for b in reversed(bills)
    ]
