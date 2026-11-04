"""传感器：取自最近一期账单。能源面板请用集成写入的长期统计。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import PudongWaterConfigEntry, PudongWaterCoordinator, WaterData
from .parse import WaterBill, bill_history, latest


@dataclass(frozen=True, kw_only=True)
class WaterSensorDescription(SensorEntityDescription):
    value_fn: Callable[[WaterBill], Any]
    attrs_fn: Callable[[WaterData, WaterBill], dict[str, Any]] | None = None


SENSORS: tuple[WaterSensorDescription, ...] = (
    WaterSensorDescription(
        key="last_water",
        translation_key="last_water",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        value_fn=lambda b: b.water,
        attrs_fn=lambda d, b: {"近期账单": bill_history(d.bills)},
    ),
    WaterSensorDescription(
        key="last_sewage",
        translation_key="last_sewage",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        value_fn=lambda b: b.sewage,
    ),
    WaterSensorDescription(
        key="last_amount",
        translation_key="last_amount",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="CNY",
        value_fn=lambda b: b.amount,
        attrs_fn=lambda d, b: {
            "水费": b.water_fee,
            "污水费": b.sewage_fee,
            "水价": b.water_price,
            "污水价": b.sewage_price,
        },
    ),
    WaterSensorDescription(
        key="meter_reading",
        translation_key="meter_reading",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        value_fn=lambda b: b.reading,
        attrs_fn=lambda d, b: {"抄表方式": b.meter_status},
    ),
    WaterSensorDescription(
        key="last_read_date",
        translation_key="last_read_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda b: b.read_date,
    ),
    WaterSensorDescription(
        key="next_read_date",
        translation_key="next_read_date",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda b: b.next_read_date,
    ),
    WaterSensorDescription(
        key="balance",
        translation_key="balance",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="CNY",
        value_fn=lambda b: b.balance,
    ),
    WaterSensorDescription(
        key="last_paid",
        translation_key="last_paid",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="CNY",
        value_fn=lambda b: b.paid,
        attrs_fn=lambda d, b: {"缴费时间": b.pay_time},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PudongWaterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [WaterSensor(coordinator, d) for d in SENSORS]
    entities.append(LastFetchedSensor(coordinator))
    async_add_entities(entities)


class _Base(CoordinatorEntity[PudongWaterCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: PudongWaterCoordinator, key: str) -> None:
        super().__init__(coordinator)
        cid = coordinator.cid
        self._attr_unique_id = f"{cid}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, cid)},
            name=f"浦东威立雅 {cid[-4:]}",
            manufacturer=MANUFACTURER,
            entry_type=DeviceEntryType.SERVICE,
        )


class WaterSensor(_Base):
    entity_description: WaterSensorDescription

    def __init__(self, coordinator: PudongWaterCoordinator, desc: WaterSensorDescription) -> None:
        super().__init__(coordinator, desc.key)
        self.entity_description = desc

    @property
    def _bill(self) -> WaterBill | None:
        return latest(self.coordinator.data.bills) if self.coordinator.data else None

    @property
    def available(self) -> bool:
        return super().available and self._bill is not None

    @property
    def native_value(self) -> Any:
        bill = self._bill
        return self.entity_description.value_fn(bill) if bill else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        bill = self._bill
        if bill is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data, bill)


class LastFetchedSensor(_Base):
    _attr_translation_key = "last_update"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: PudongWaterCoordinator) -> None:
        super().__init__(coordinator, "last_update")

    @property
    def native_value(self):
        return self.coordinator.data.fetched_at if self.coordinator.data else None
