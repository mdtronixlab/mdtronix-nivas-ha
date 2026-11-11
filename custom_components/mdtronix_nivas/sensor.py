"""Level, run time, water used and the last pump event."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfLength, UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import NivasConfigEntry
from .client import WtlcData
from .const import CONF_TANK_LITRES, PUMP_EVENT_CAUSES
from .entity import NivasEntity

_EPOCH_ORDINAL = date(1970, 1, 1).toordinal()


def _today_index(usage: dict[str, Any] | None) -> int | None:
    """Where today sits in the usage summary's 7-day lists, None if not there.

    "d" is the device-local day number of the lists' first entry, 0 until the
    unit has had the time. The unit's offset matches Home Assistant's, which
    gives it the time on every connect.
    """
    if not usage or not usage.get("d"):
        return None
    today = dt_util.now().date().toordinal() - _EPOCH_ORDINAL
    index = usage["d"] - today
    return 0 if index == 0 else None


def _today(usage: dict[str, Any] | None, key: str) -> int | None:
    if not usage:
        return None
    values = usage.get(key) or []
    if _today_index(usage) is None:
        # Nothing recorded yet today (the newest entry is an earlier day).
        return 0 if usage.get("d") else None
    return values[0] if values else 0


@dataclass(frozen=True, kw_only=True)
class NivasSensorDescription(SensorEntityDescription):
    value_fn: Callable[[WtlcData, int], Any]
    needs_tank_size: bool | None = None  # True: only with a tank size; False: only without


def _litres(tenths_of_percent: int | None, tank_litres: int) -> float | None:
    if tenths_of_percent is None:
        return None
    return round(tenths_of_percent / 1000 * tank_litres, 1)


def _last_event_time(data: WtlcData, _: int) -> datetime | None:
    event = data.last_event or {}
    return dt_util.utc_from_timestamp(event["t"]) if event.get("t") else None


SENSORS: tuple[NivasSensorDescription, ...] = (
    NivasSensorDescription(
        key="level",
        translation_key="level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d, _: d.state.get("level") if d.state.get("levelValid") else None,
    ),
    NivasSensorDescription(
        key="water",
        translation_key="water",
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        needs_tank_size=True,
        value_fn=lambda d, litres: (
            round(d.state["level"] / 100 * litres, 1) if d.state.get("levelValid") and "level" in d.state else None
        ),
    ),
    NivasSensorDescription(
        key="pump_run_time",
        translation_key="pump_run_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda d, _: d.state.get("pumpRunMinutes") if d.state.get("pump") else 0,
    ),
    NivasSensorDescription(
        key="pump_time_today",
        translation_key="pump_time_today",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d, _: _today(d.usage, "s"),
    ),
    NivasSensorDescription(
        key="pump_time_total",
        translation_key="pump_time_total",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _: (d.usage or {}).get("t"),
    ),
    # Water drawn from the tank, as the level falls. Without a tank size only
    # as a share of the tank; with one in litres, which the Energy dashboard
    # can use for water consumption.
    NivasSensorDescription(
        key="tank_used_today",
        translation_key="tank_used_today",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        needs_tank_size=False,
        value_fn=lambda d, _: None if (v := _today(d.usage, "su")) is None else v / 10,
    ),
    NivasSensorDescription(
        key="water_used_today",
        translation_key="water_used_today",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        needs_tank_size=True,
        value_fn=lambda d, litres: _litres(_today(d.usage, "su"), litres),
    ),
    NivasSensorDescription(
        key="water_used_total",
        translation_key="water_used_total",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        needs_tank_size=True,
        value_fn=lambda d, litres: _litres((d.usage or {}).get("u"), litres),
    ),
    NivasSensorDescription(
        key="last_pump_event",
        translation_key="last_pump_event",
        device_class=SensorDeviceClass.ENUM,
        options=sorted(set(PUMP_EVENT_CAUSES.values())),
        value_fn=lambda d, _: PUMP_EVENT_CAUSES.get((d.last_event or {}).get("cause", ""), None),
    ),
    NivasSensorDescription(
        key="last_pump_event_time",
        translation_key="last_pump_event_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_last_event_time,
    ),
    NivasSensorDescription(
        key="distance",
        translation_key="distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.CENTIMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _: d.state.get("distanceCm"),
    ),
    NivasSensorDescription(
        key="status",
        translation_key="status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _: d.state.get("status") or None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: NivasConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    tank_litres = int(entry.options.get(CONF_TANK_LITRES) or 0)
    async_add_entities(
        NivasSensor(entry.runtime_data, entry.data, description, tank_litres)
        for description in SENSORS
        if description.needs_tank_size is None or description.needs_tank_size == (tank_litres > 0)
    )


class NivasSensor(NivasEntity, SensorEntity):
    entity_description: NivasSensorDescription

    def __init__(self, client, entry_data, description: NivasSensorDescription, tank_litres: int) -> None:
        super().__init__(client, entry_data, description)
        self._tank_litres = tank_litres

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self._client.data, self._tank_litres)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "last_pump_event" or not self._client.data.last_event:
            return None
        event = self._client.data.last_event
        attributes: dict[str, Any] = {"pump": "on" if event.get("on") else "off", "via": event.get("via")}
        if "level" in event:
            attributes["level"] = event["level"]
        if event.get("run"):
            attributes["run_seconds"] = event["run"]
        return attributes
