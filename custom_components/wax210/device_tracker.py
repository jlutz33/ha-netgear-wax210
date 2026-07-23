"""Device tracker platform for the NETGEAR WAX210 integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.device_tracker import ScannerEntity, SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WAX210Coordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WAX210Coordinator = hass.data[DOMAIN][entry.entry_id]
    tracked: set[str] = set()

    @callback
    def _add_new_devices() -> None:
        new_entities = [
            WAX210DeviceTracker(coordinator, entry, client["mac"])
            for client in (coordinator.data or {}).get("clients", [])
            if client["mac"] not in tracked and not tracked.add(client["mac"])  # type: ignore[func-returns-value]
        ]
        if new_entities:
            async_add_entities(new_entities)

    _add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_devices))


class WAX210DeviceTracker(CoordinatorEntity[WAX210Coordinator], ScannerEntity):
    """Tracks a single WiFi client seen on a WAX210 AP."""

    _attr_source_type = SourceType.ROUTER

    def __init__(
        self, coordinator: WAX210Coordinator, entry: ConfigEntry, mac: str
    ) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = f"{entry.entry_id}_{mac}"
        self._attr_device_info = coordinator.device_info

    @property
    def name(self) -> str:
        data = self._client_data()
        return data.get("hostname") or self._mac

    @property
    def is_connected(self) -> bool:
        return self._mac in (self.coordinator.data or {}).get("macs_seen", set())

    @property
    def ip_address(self) -> str | None:
        return self._client_data().get("ip") or None

    @property
    def mac_address(self) -> str:
        return self._mac

    @property
    def hostname(self) -> str | None:
        return self._client_data().get("hostname") or None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self._client_data()
        return {
            key: data[key]
            for key in ("os", "rssi", "rx_kbytes", "tx_kbytes", "mode", "ssid", "band", "channel")
            if data.get(key) is not None
        }

    def _client_data(self) -> dict[str, Any]:
        for client in (self.coordinator.data or {}).get("clients", []):
            if client["mac"] == self._mac:
                return client
        return {}
