"""添加流程、装上以后的传感器、真正写进记录器的统计、缓存。"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from homeassistant import config_entries
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from custom_components.pudong_water.api import ApiError, InvalidAccount
from custom_components.pudong_water.const import DOMAIN

from .conftest import BILLS, CID, bill

WATER_ID = f"pudong_water:{CID}_water"
COST_ID = f"pudong_water:{CID}_cost"


def fake_client(bills=BILLS, exc=None):
    client = MagicMock()
    client.bills = AsyncMock(return_value=bills, side_effect=exc)
    return client


def _entity(hass, key):
    reg = er.async_get(hass)
    entity_id = reg.async_get_entity_id("sensor", DOMAIN, f"{CID}_{key}")
    assert entity_id, key
    return hass.states.get(entity_id)


async def _setup(hass, entry, client):
    with patch("custom_components.pudong_water.build_client", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    await async_wait_recording_done(hass)


async def _monthly(hass, stat_id):
    tz = dt_util.get_default_time_zone()
    res = await get_instance(hass).async_add_executor_job(
        statistics_during_period, hass, datetime(2020, 1, 1, tzinfo=tz), None,
        {stat_id}, "month", None, {"sum", "change"},
    )
    return {
        dt_util.utc_from_timestamp(r["start"]).astimezone(tz).strftime("%Y-%m"): (
            round(r["change"], 2), round(r["sum"], 2))
        for r in res.get(stat_id, [])
    }


async def test_config_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    for client, key in ((fake_client(exc=InvalidAccount("x")), "invalid_account"),
                        (fake_client(exc=ApiError("x")), "cannot_connect"),
                        (fake_client(bills=[]), "no_bills")):
        with patch("custom_components.pudong_water.config_flow.build_client", return_value=client):
            result = await hass.config_entries.flow.async_configure(result["flow_id"], {"cid": CID})
        assert result["errors"] == {"base": key}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"cid": "1"})
    assert result["errors"] == {"cid": "invalid_cid"}
    with (
        patch("custom_components.pudong_water.config_flow.build_client", return_value=fake_client()),
        patch("custom_components.pudong_water.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"cid": CID})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "浦东威立雅 尾号5678"
    assert result["data"] == {"cid": CID}


async def test_sensors_statistics_and_privacy(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Asia/Shanghai")
    entry = MockConfigEntry(domain=DOMAIN, data={"cid": CID}, unique_id=CID)
    entry.add_to_hass(hass)
    await _setup(hass, entry, fake_client())
    assert entry.state is ConfigEntryState.LOADED

    assert _entity(hass, "last_water").state == "24.0"
    assert _entity(hass, "last_sewage").state == "21.6"
    assert _entity(hass, "last_amount").state == "55.92"
    assert _entity(hass, "last_amount").attributes["水价"] == 2.25
    assert _entity(hass, "meter_reading").state == "36.0"
    assert _entity(hass, "meter_reading").attributes["抄表方式"] == "正常"
    assert _entity(hass, "last_read_date").state == "2026-07-06"
    assert _entity(hass, "next_read_date").state == "2026-09-06"
    assert _entity(hass, "balance").state == "12.5"
    assert len(_entity(hass, "last_water").attributes["近期账单"]) == 4
    assert _entity(hass, "year_cost").state == str(round(46.6 + 41.94 + 51.26 + 55.92, 2))
    assert _entity(hass, "year_cost").attributes["今年用水量"] == 84.0

    for state in hass.states.async_all("sensor"):
        assert "样例" not in str(state.attributes) and "样例" not in state.state
    stored = await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_load()
    assert "样例" not in str(stored)
    assert stored["stats_schema"] == 1

    # 换表不影响：每期的变化量就是本期用水量，第一期也不会冒出大柱子
    assert await _monthly(hass, WATER_ID) == {
        "2026-01": (20.0, 20.0), "2026-03": (18.0, 38.0),
        "2026-05": (22.0, 60.0), "2026-07": (24.0, 84.0),
    }
    cost = await _monthly(hass, COST_ID)
    assert cost["2026-01"] == (46.6, 46.6)
    assert cost["2026-07"][1] == round(46.6 + 41.94 + 51.26 + 55.92, 2)


async def test_restart_uses_cache_and_appends_new_bills(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    await hass.config.async_set_time_zone("Asia/Shanghai")
    entry = MockConfigEntry(domain=DOMAIN, data={"cid": CID}, unique_id=CID, options={"scan_interval_days": 15})
    entry.add_to_hass(hass)
    first = fake_client()
    await _setup(hass, entry, first)
    assert first.bills.await_count == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    second = fake_client(bills=BILLS[1:] + [bill(2026, 9, "2026-09-05", "2026-11-04", "36", "55", 19, 44.27)])
    await _setup(hass, entry, second)
    assert second.bills.await_count == 0  # 缓存还新鲜
    assert (await _monthly(hass, WATER_ID))["2026-07"] == (24.0, 84.0)  # 重启不重复累加

    with patch("custom_components.pudong_water.build_client", return_value=second):
        freezer.tick(timedelta(days=15, minutes=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        # 更新里有一步在记录器线程上（查最后一行统计），只等主循环不够，要把记录器也等完
        await async_wait_recording_done(hass)
        await hass.async_block_till_done()
    await async_wait_recording_done(hass)
    assert second.bills.await_count == 1
    water = await _monthly(hass, WATER_ID)
    assert water["2026-01"] == (20.0, 20.0)  # 掉出窗口的老数据没被动
    assert water["2026-09"] == (19.0, 103.0)
    assert _entity(hass, "last_water").state == "19.0"


async def test_invalid_account_retries_later(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={"cid": CID}, unique_id=CID)
    entry.add_to_hass(hass)
    with patch("custom_components.pudong_water.build_client", return_value=fake_client(exc=InvalidAccount("x"))):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
