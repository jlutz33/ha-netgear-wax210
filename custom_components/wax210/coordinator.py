"""Coordinator for the NETGEAR WAX210 integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import WAX210AuthError, WAX210Client, WAX210ConnectionError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, MANUFACTURER, MODEL

_LOGGER = logging.getLogger(__name__)


class WAX210Coordinator(DataUpdateCoordinator):
    """Polls one WAX210 on an interval and shares the result across entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: WAX210Client) -> None:
        self.client = client
        self.entry = entry
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({client.host})",
            update_interval=timedelta(seconds=entry.options.get(
                "scan_interval", DEFAULT_SCAN_INTERVAL)),
        )

    async def _async_update_data(self) -> dict:
        try:
            # WAX210Client is sync (requests-based); run it off the event loop.
            return await self.hass.async_add_executor_job(self.client.get_all_data)
        except WAX210AuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except WAX210ConnectionError as err:
            raise UpdateFailed(f"Error communicating with AP: {err}") from err

    @property
    def device_info(self) -> dict:
        """
        Built from the AP's own reported data rather than just the
        config-entry host: name comes from the AP's configured name
        (falls back to the host-based name if that hasn't loaded yet),
        firmware becomes sw_version and serial_number becomes
        serial_number on the Device Info card -- both rendered natively
        by HA rather than as separate sensor entities.
        """
        data = self.data or {}
        name = data.get("ap_name") or f"WAX210 ({self.client.host})"
        info: dict = {
            "identifiers": {(DOMAIN, self.entry.entry_id)},
            "name": name,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "configuration_url": f"https://{self.client.host}/",
        }
        if data.get("firmware"):
            info["sw_version"] = data["firmware"]
        if data.get("serial_number"):
            info["serial_number"] = data["serial_number"]
        return info
