"""Pump running, and the conditions that stop or hold it."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NivasConfigEntry
from .entity import NivasEntity


@dataclass(frozen=True, kw_only=True)
class NivasBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], bool | None]


BINARY_SENSORS: tuple[NivasBinarySensorDescription, ...] = (
    NivasBinarySensorDescription(
        key="pump",
        translation_key="pump",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda s: s.get("pump"),
    ),
    NivasBinarySensorDescription(
        key="sensor_error",
        translation_key="sensor_error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda s: s.get("sensorError"),
    ),
    NivasBinarySensorDescription(
        key="dry_run",
        translation_key="dry_run",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda s: s.get("dryRunActive"),
    ),
    # Auto is on, but won't start the pump on its own until the level has
    # been back above the stop level (a manual stop or a dry-run trip).
    NivasBinarySensorDescription(
        key="auto_paused",
        translation_key="auto_paused",
        value_fn=lambda s: bool(s.get("auto")) and bool(s.get("autoSuppressed")),
    ),
    NivasBinarySensorDescription(
        key="quiet_hours",
        translation_key="quiet_hours",
        value_fn=lambda s: s.get("quietHours"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: NivasConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(NivasBinarySensor(entry.runtime_data, entry.data, d) for d in BINARY_SENSORS)


class NivasBinarySensor(NivasEntity, BinarySensorEntity):
    entity_description: NivasBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.state_data)
