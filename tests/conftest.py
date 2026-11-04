"""测试公共部分。"""

from __future__ import annotations

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """集成依赖 recorder；recorder 必须先于 hass 准备好。"""
    yield


CID = "9000005678"


def bill(year, month, read, nxt, prev, cur, water, amount, paid=None, status="正常", **extra):
    sewage = round(water * 0.9, 2)
    return {
        "YEAR": str(year),
        "MONTH": month,
        "COPYMETERDATE": read,
        "NEXTDATE": nxt,
        "SHANGCICBRQ": "2026/1/6 0:00:00",
        "COPYMETERSTATUS": status,
        "PREVMETERDATA": prev,
        "METERDATA": cur,
        "WATERNUM": str(water),
        "DIRTYNUM": str(sewage),
        "WATERPRICE": "2.25",
        "DIRTYPRICE": "2.34",
        "WATERFEE": str(round(water * 2.25, 2)),
        "DIRTYFEE": str(round(sewage * 2.34, 2)),
        "SUMFEE": str(amount),
        "SUMPAY": str(paid if paid is not None else amount),
        "FACTFEE": str(paid if paid is not None else amount),
        "NOWLEFT": "12.5",
        "PAYTIME": "2026/3/10 8:00:00",
        "CUSTRNAME": "样例户名",
        "CUSTADDRESS": "样例路1号",
        **extra,
    }


# 与真实账单同样的形状：两月一期、5 月换表（读数重新从小数开始）、实缴与应缴不同
BILLS = [
    bill(2026, 1, "2026-01-06 00:00:00", "2026-03-04 00:00:00", "800", "820", 20, 46.6, paid=50),
    bill(2026, 3, "2026/3/4 0:00:00", "2026/5/6 0:00:00", "820", "838", 18, 41.94, paid=40),
    bill(2026, 5, "2026-05-06", "2026-07-06", "838", "12", 22, 51.26, status="新表实发"),
    bill(2026, 7, "2026-07-06", "2026-09-06", "12", "36", 24, 55.92),
]
