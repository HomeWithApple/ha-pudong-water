"""添加与选项。"""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import build_client
from .api import ApiError, InvalidAccount
from .const import (
    CONF_CID,
    CONF_SCAN_INTERVAL_DAYS,
    DEFAULT_SCAN_INTERVAL_DAYS,
    DOMAIN,
    MAX_SCAN_INTERVAL_DAYS,
    MIN_SCAN_INTERVAL_DAYS,
)

_LOGGER = logging.getLogger(__name__)
_CID_RE = re.compile(r"[0-9A-Za-z]{5,20}")


class PudongWaterConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            cid = user_input[CONF_CID].strip()
            if not _CID_RE.fullmatch(cid):
                errors[CONF_CID] = "invalid_cid"
            else:
                await self.async_set_unique_id(cid)
                self._abort_if_unique_id_configured()
                try:
                    bills = await build_client(self.hass, cid).bills()
                except InvalidAccount:
                    errors["base"] = "invalid_account"
                except ApiError:
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("添加浦东威立雅时出现意外错误")
                    errors["base"] = "unknown"
                else:
                    if not bills:
                        errors["base"] = "no_bills"
                    else:
                        return self.async_create_entry(
                            title=f"浦东威立雅 尾号{cid[-4:]}", data={CONF_CID: cid}
                        )
        schema = vol.Schema(
            {vol.Required(CONF_CID): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))}
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return PudongWaterOptionsFlow()


class PudongWaterOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL_DAYS: int(user_input[CONF_SCAN_INTERVAL_DAYS])}
            )
        current = self.config_entry.options.get(CONF_SCAN_INTERVAL_DAYS, DEFAULT_SCAN_INTERVAL_DAYS)
        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL_DAYS, default=current): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL_DAYS,
                        max=MAX_SCAN_INTERVAL_DAYS,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="天",
                    )
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
