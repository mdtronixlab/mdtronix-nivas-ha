"""Start and stop levels, the run-time cutoff and the dry-run check interval."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NivasConfigEntry
from .const import (
    DOMAIN,
    DRY_RUN_INTERVAL_MAX,
    DRY_RUN_INTERVAL_MIN,
    LEVEL_MAX,
    LEVEL_MIN,
    MAX_RUN_TIME_MAX,
    MAX_RUN_TIME_MIN,
)
from .entity import NivasEntity


def _format(value: float) -> str:
    return f"{value:g}"


def _check_start(value: float, state: dict[str, Any]) -> None:
    stop = state.get("stopPumpAt")
    if stop is not None and value >= stop:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="start_not_below_stop",
            translation_placeholders={"stop": _format(stop)},
        )


def _check_stop(value: float, state: dict[str, Any]) -> None:
    start = state.get("startPumpAt")
    if (start is not None and value <= start) or value <= LEVEL_MIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="stop_not_above_start",
            translation_placeholders={"start": _format(start or 0)},
        )


@dataclass(frozen=True, kw_only=True)
class NivasNumberDescription(NumberEntityDescription):
    state_key: str
    command: str
    check: Callable[[float, dict[str, Any]], None] | None = None


NUMBERS: tuple[NivasNumberDescription, ...] = (
    NivasNumberDescription(
        key="start_level",
        translation_key="start_level",
        entity_category=EntityCategory.CONFIG,
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=LEVEL_MIN,
        native_max_value=LEVEL_MAX - 1,
        native_step=1,
        mode=NumberMode.BOX,
        state_key="startPumpAt",
        command="start",
        check=_check_start,
    ),
    NivasNumberDescription(
        key="stop_level",
        translation_key="stop_level",
        entity_category=EntityCategory.CONFIG,
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=LEVEL_MIN + 1,
        native_max_value=LEVEL_MAX,
        native_step=1,
        mode=NumberMode.BOX,
        state_key="stopPumpAt",
        command="stop",
        check=_check_stop,
    ),
    NivasNumberDescription(
        key="max_run_time",
        translation_key="max_run_time",
        entity_category=EntityCategory.CONFIG,
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        native_min_value=MAX_RUN_TIME_MIN,
        native_max_value=MAX_RUN_TIME_MAX,
        native_step=1,
        mode=NumberMode.BOX,
        state_key="maxPumpRunTime",
        command="maxruntime",
    ),
    NivasNumberDescription(
        key="dry_run_interval",
        translation_key="dry_run_interval",
        entity_category=EntityCategory.CONFIG,
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        native_min_value=DRY_RUN_INTERVAL_MIN,
        native_max_value=DRY_RUN_INTERVAL_MAX,
        native_step=1,
        state_key="dryRunInterval",
        command="dryruninterval",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: NivasConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(NivasNumber(entry.runtime_data, entry.data, d) for d in NUMBERS)


class NivasNumber(NivasEntity, NumberEntity):
    entity_description: NivasNumberDescription

    @property
    def native_value(self) -> float | None:
        return self.state_data.get(self.entity_description.state_key)

    async def async_set_native_value(self, value: float) -> None:
        if self.entity_description.check:
            self.entity_description.check(value, self.state_data)
        number = _format(value) if self.entity_description.native_unit_of_measurement == PERCENTAGE else str(int(value))
        await self.send(f"{self.entity_description.command}:{number}")
