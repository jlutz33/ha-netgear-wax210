"""Device tracker platform for the NETGEAR WAX210 integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.device_tracker import ScannerEntity, SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WAX210Coordinator

_LOGGER = logging.getLogger(__name__)

# Fired whenever a new WAX210 coordinator comes online so existing tracker
# entities can subscribe to it without being recreated.
SIGNAL_NEW_COORDINATOR = f"{DOMAIN}_new_coordinator"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WAX210Coordinator = hass.data[DOMAIN][entry.entry_id]

    # Shared across all WAX210 config entries — prevents duplicate entities
    # when two APs see the same MAC.
    if "tracked_macs" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["tracked_macs"] = set()
    tracked: set[str] = hass.data[DOMAIN]["tracked_macs"]

    @callback
    def _add_new_devices() -> None:
        new_macs = [
            client["mac"]
            for client in (coordinator.data or {}).get("clients", [])
            if client["mac"] not in tracked and not tracked.add(client["mac"])  # type: ignore[func-returns-value]
        ]
        if new_macs:
            async_add_entities([WAX210DeviceTracker(hass, mac) for mac in new_macs])

    _add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_devices))

    # Notify any tracker entities already created by a previous entry that a
    # new coordinator is available so they subscribe to its updates too.
    async_dispatcher_send(hass, SIGNAL_NEW_COORDINATOR, coordinator)


class WAX210DeviceTracker(ScannerEntity):
    """
    Tracks a single WiFi client across all configured WAX210 APs.
    Reports home if the device is seen on any AP, not just a specific one.
    """

    _attr_source_type = SourceType.ROUTER
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, mac: str) -> None:
        self.hass = hass
        self._mac = mac
        self._attr_unique_id = f"wax210_{mac}"
        self._last_via_entry_id: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        for coordinator in self._coordinators():
            self.async_on_remove(
                coordinator.async_add_listener(self.async_write_ha_state)
            )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_NEW_COORDINATOR, self._on_new_coordinator
            )
        )

    @callback
    def _on_new_coordinator(self, coordinator: WAX210Coordinator) -> None:
        self.async_on_remove(
            coordinator.async_add_listener(self.async_write_ha_state)
        )

    def _coordinators(self) -> list[WAX210Coordinator]:
        return [
            v for v in self.hass.data.get(DOMAIN, {}).values()
            if isinstance(v, WAX210Coordinator)
        ]

    @property
    def device_info(self) -> DeviceInfo:
        _, coordinator = self._active_client_data()
        if coordinator is not None:
            self._last_via_entry_id = coordinator.entry.entry_id
        info = DeviceInfo(connections={(CONNECTION_NETWORK_MAC, self._mac)})
        if self._last_via_entry_id is not None:
            info["via_device"] = (DOMAIN, self._last_via_entry_id)
        return info

    def _active_client_data(self) -> tuple[dict[str, Any], WAX210Coordinator | None]:
        """Client data + coordinator for the AP the device is currently on."""
        for coordinator in self._coordinators():
            if self._mac in (coordinator.data or {}).get("macs_seen", set()):
                for client in coordinator.data.get("clients", []):
                    if client["mac"] == self._mac:
                        return client, coordinator
        return {}, None

    @property
    def is_connected(self) -> bool:
        return any(
            self._mac in (c.data or {}).get("macs_seen", set())
            for c in self._coordinators()
        )

    @property
    def name(self) -> str:
        data, _ = self._active_client_data()
        return data.get("hostname") or self._mac

    @property
    def ip_address(self) -> str | None:
        data, _ = self._active_client_data()
        return data.get("ip") or None

    @property
    def mac_address(self) -> str:
        return self._mac

    @property
    def hostname(self) -> str | None:
        data, _ = self._active_client_data()
        return data.get("hostname") or None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data, coordinator = self._active_client_data()
        if not data:
            return {}
        attrs: dict[str, Any] = {}
        for key in ("os", "rssi", "rx_kbytes", "tx_kbytes", "mode", "ssid", "band", "channel"):
            if data.get(key) is not None:
                attrs[key] = data[key]
        if coordinator:
            attrs["ap"] = coordinator.data.get("ap_name") or coordinator.client.host
        return attrs
