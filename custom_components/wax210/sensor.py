"""Sensor platform for the NETGEAR WAX210 integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from datetime import datetime, timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import WAX210Coordinator


def _compute_last_boot(uptime_s: float | None) -> datetime | None:
    """
    Converts the AP's reported uptime (seconds) into an absolute boot
    timestamp, rounded to the nearest minute. HA's frontend renders
    device_class=TIMESTAMP entities as relative text ("Yesterday", "3
    hours ago") automatically -- that's not custom formatting, it's built
    into HA itself. Rounding to the minute (rather than leaving sub-minute
    jitter in) means the state only actually changes when the AP really
    reboots, rather than drifting by a couple seconds every poll -- which
    keeps this out of the logbook almost entirely, unlike a ticking
    "uptime" display string would.
    """
    if uptime_s is None:
        return None
    boot = dt_util.utcnow() - timedelta(seconds=uptime_s)
    return boot.replace(second=0, microsecond=0)


@dataclass(frozen=True, kw_only=True)
class WAX210SensorDescription(SensorEntityDescription):
    """Adds a value_fn to pull this sensor's state out of coordinator.data."""

    value_fn: Callable[[dict], Any] = lambda data: None
    attrs_fn: Callable[[dict], dict] | None = None


SENSOR_DESCRIPTIONS: tuple[WAX210SensorDescription, ...] = (
    WAX210SensorDescription(
        key="connected_clients",
        translation_key="connected_clients",
        icon="mdi:devices",
        native_unit_of_measurement="clients",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data["client_count"],
        attrs_fn=lambda data: {"clients": data["clients"]},
    ),
    WAX210SensorDescription(
        key="cpu_load",
        translation_key="cpu_load",
        icon="mdi:chip",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data["cpu_pct"],
    ),
    WAX210SensorDescription(
        key="memory_load",
        translation_key="memory_load",
        icon="mdi:memory",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data["mem_pct"],
    ),
    WAX210SensorDescription(
        key="last_boot",
        translation_key="last_boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _compute_last_boot(data["uptime_s"]),
        attrs_fn=lambda data: {"uptime_seconds": data["uptime_s"]},
    ),
    WAX210SensorDescription(
        # Numeric companion with state_class=total_increasing for anyone
        # who wants proper statistics/history graphing -- can't live on
        # the timestamp sensor above, which needs an actual datetime as
        # its native_value. Its own unit_of_measurement + state_class
        # should already keep this one out of the logbook as a
        # "continuous" sensor, same as connected_clients/cpu_load/etc.
        key="uptime_seconds",
        translation_key="uptime_seconds",
        icon="mdi:timer-outline",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data["uptime_s"],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WAX210Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        WAX210Sensor(coordinator, entry, description)
        for description in SENSOR_DESCRIPTIONS
    )


class WAX210Sensor(CoordinatorEntity[WAX210Coordinator], SensorEntity):
    """A single WAX210 metric."""

    _attr_has_entity_name = True
    entity_description: WAX210SensorDescription

    def __init__(self, coordinator: WAX210Coordinator, entry: ConfigEntry,
                 description: WAX210SensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)
