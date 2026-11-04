"""浦东威立雅水费集成。"""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PudongWaterClient
from .const import CONF_CID
from .coordinator import PudongWaterConfigEntry, PudongWaterCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


def build_client(hass: HomeAssistant, cid: str) -> PudongWaterClient:
    return PudongWaterClient(async_get_clientsession(hass), cid)


async def async_setup_entry(hass: HomeAssistant, entry: PudongWaterConfigEntry) -> bool:
    cid = entry.data[CONF_CID]
    coordinator = PudongWaterCoordinator(hass, entry, build_client(hass, cid), cid)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: PudongWaterConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: PudongWaterConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
