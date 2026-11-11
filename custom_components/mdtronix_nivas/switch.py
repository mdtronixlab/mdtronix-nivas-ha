"""The pump, Auto, and the protections that can be switched."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NivasConfigEntry
from .entity import NivasEntity


@dataclass(frozen=True, kw_only=True)
class NivasSwitchDescription(SwitchEntityDescription):
    state_key: str
    on_command: str
    off_command: str


SWITCHES: tuple[NivasSwitchDescription, ...] = (
    NivasSwitchDescription(
        key="pump",
        translation_key="pump",
        device_class=SwitchDeviceClass.SWITCH,
        state_key="pump",
        on_command="pump:on",
        off_command="pump:off",
    ),
    NivasSwitchDescription(
        key="auto",
        translation_key="auto",
        state_key="auto",
        on_command="mode:auto",
        off_command="mode:manual",
    ),
    NivasSwitchDescription(
        key="dry_run_protection",
        translation_key="dry_run_protection",
        entity_category=EntityCategory.CONFIG,
        state_key="dryRunProtection",
        on_command="dryrun:on",
        off_command="dryrun:off",
    ),
    # The unit's Safety Mode: the pump never starts during quiet hours.
    NivasSwitchDescription(
        key="quiet_hours_mode",
        translation_key="quiet_hours_mode",
        entity_category=EntityCategory.CONFIG,
        state_key="safetyMode",
        on_command="safety:on",
        off_command="safety:off",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: NivasConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(NivasSwitch(entry.runtime_data, entry.data, d) for d in SWITCHES)


class NivasSwitch(NivasEntity, SwitchEntity):
    entity_description: NivasSwitchDescription

    @property
    def is_on(self) -> bool | None:
        return self.state_data.get(self.entity_description.state_key)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.send(self.entity_description.on_command)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.send(self.entity_description.off_command)
