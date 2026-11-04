"""定期查浦东威立雅账单，写入能源面板用的长期统计。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import VolumeConverter

from .api import ApiError, InvalidAccount, PudongWaterClient
from .const import (
    CONF_SCAN_INTERVAL_DAYS,
    DEFAULT_SCAN_INTERVAL_DAYS,
    DOMAIN,
    STATS_SCHEMA,
    STORAGE_VERSION,
)
from .parse import WaterBill, cost_points, parse_bills, water_points

_LOGGER = logging.getLogger(__name__)

# 缓存里只留这些字段：不存户名（CUSTRNAME）、地址（CUSTADDRESS）
BILL_KEEP = (
    "YEAR", "MONTH", "COPYMETERDATE", "NEXTDATE", "COPYMETERSTATUS", "METERDATA",
    "PREVMETERDATA", "WATERNUM", "DIRTYNUM", "WATERPRICE", "DIRTYPRICE", "WATERFEE",
    "DIRTYFEE", "SUMFEE", "FACTFEE", "PAYTIME", "NOWLEFT", "GARBAGEFEE", "LATEFEES", "OTHERFEE",
)

type PudongWaterConfigEntry = ConfigEntry["PudongWaterCoordinator"]


@dataclass
class WaterData:
    fetched_at: datetime
    bills: list[WaterBill]


def keep_fields(raw: dict[str, Any]) -> dict[str, Any]:
    return {k: raw[k] for k in BILL_KEEP if k in raw}


def statistic_ids(cid: str) -> tuple[str, str]:
    object_id = "".join(c for c in cid.lower() if c.isalnum())
    return f"{DOMAIN}:{object_id}_water", f"{DOMAIN}:{object_id}_cost"


class PudongWaterCoordinator(DataUpdateCoordinator[WaterData]):
    """默认半个月查一次；HA 重启时先用本地缓存。"""

    config_entry: PudongWaterConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: PudongWaterConfigEntry,
        client: PudongWaterClient,
        cid: str,
    ) -> None:
        self.interval = timedelta(
            days=entry.options.get(CONF_SCAN_INTERVAL_DAYS, DEFAULT_SCAN_INTERVAL_DAYS)
        )
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=self.interval
        )
        self.client = client
        self.cid = cid
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._startup = True
        self._raw_bills: list[dict[str, Any]] = []
        self._stats_schema = 0

    async def _async_update_data(self) -> WaterData:
        data: WaterData | None = None
        if self._startup:
            self._startup = False
            cached = await self._load_cache()
            if cached is not None:
                age = dt_util.utcnow() - cached.fetched_at
                if age < self.interval:
                    self.update_interval = max(self.interval - age, timedelta(minutes=5))
                    data = cached
        if data is None:
            self.update_interval = self.interval
            data = await self._fetch()
            await self._save_cache(data)
        await self._sync_statistics(data)
        return data

    async def _fetch(self) -> WaterData:
        try:
            raws = await self.client.bills()
        except InvalidAccount as err:
            raise UpdateFailed(f"接口不认这个户号：{err}") from err
        except ApiError as err:
            raise UpdateFailed(str(err)) from err
        if not raws:
            raise UpdateFailed("没有查到账单")
        self._raw_bills = [keep_fields(r) for r in raws]
        return WaterData(fetched_at=dt_util.utcnow(), bills=parse_bills(self._raw_bills))

    async def _save_cache(self, data: WaterData) -> None:
        await self._store.async_save(
            {
                "fetched_at": data.fetched_at.isoformat(),
                "bills": self._raw_bills,
                "stats_schema": self._stats_schema,
            }
        )

    async def _load_cache(self) -> WaterData | None:
        stored = await self._store.async_load()
        if not stored:
            return None
        self._stats_schema = int(stored.get("stats_schema") or 0)
        fetched_at = dt_util.parse_datetime(stored.get("fetched_at") or "")
        self._raw_bills = [keep_fields(r) for r in stored.get("bills") or [] if isinstance(r, dict)]
        if fetched_at is None or not self._raw_bills:
            return None
        return WaterData(fetched_at=fetched_at, bills=parse_bills(self._raw_bills))

    @staticmethod
    def _start(day: date) -> datetime:
        return datetime(day.year, day.month, day.day, tzinfo=dt_util.get_default_time_zone())

    def _metadata(self) -> dict[str, StatisticMetaData]:
        water_id, cost_id = statistic_ids(self.cid)
        name = f"浦东威立雅 {self.cid[-4:]}"
        return {
            water_id: StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"{name} 用水量",
                source=DOMAIN,
                statistic_id=water_id,
                unit_class=VolumeConverter.UNIT_CLASS,
                unit_of_measurement=UnitOfVolume.CUBIC_METERS,
            ),
            cost_id: StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"{name} 水费",
                source=DOMAIN,
                statistic_id=cost_id,
                unit_class=None,
                unit_of_measurement=None,
            ),
        }

    async def _sync_statistics(self, data: WaterData) -> None:
        """第一次清掉重写；之后只追加比库里最后一行更新的账单，接着累计值往上加。"""
        rebuild = self._stats_schema < STATS_SCHEMA
        recorder = get_instance(self.hass)
        meta = self._metadata()
        water_id, cost_id = list(meta)
        if rebuild:
            recorder.async_clear_statistics([water_id, cost_id])
        for stat_id, fn in ((water_id, water_points), (cost_id, cost_points)):
            after: date | None = None
            start_sum = 0.0
            if not rebuild:
                last = await recorder.async_add_executor_job(
                    get_last_statistics, self.hass, 1, stat_id, True, {"sum"}
                )
                if last.get(stat_id):
                    row = last[stat_id][0]
                    after = dt_util.as_local(dt_util.utc_from_timestamp(row["start"])).date()
                    start_sum = float(row.get("sum") or 0.0)
            points = fn(data.bills, after, start_sum)
            if points:
                async_add_external_statistics(
                    self.hass,
                    meta[stat_id],
                    [StatisticData(start=self._start(d), state=v, sum=t) for d, v, t in points],
                )
        if rebuild:
            self._stats_schema = STATS_SCHEMA
            await self._save_cache(data)
