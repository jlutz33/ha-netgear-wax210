"""Binary sensor platform for the NETGEAR WAX210 integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WAX210Coordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WAX210Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WAX210NetworkStatusBinarySensor(coordinator, entry)])


class WAX210NetworkStatusBinarySensor(CoordinatorEntity[WAX210Coordinator], BinarySensorEntity):
    """
    Reflects the AP's own bridged management/LAN interface (the 'wan' key
    in the API is misleadingly named -- the WAX210 has no true WAN port;
    ifname is 'br-lan'). There's no explicit up/down flag in the payload,
    so the API layer infers it from having a real IP and non-zero uptime.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_translation_key = "network_status"

    def __init__(self, coordinator: WAX210Coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_network_status"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("network_up"))

    @property
    def extra_state_attributes(self) -> dict:
        return self.coordinator.data.get("network_info", {})
