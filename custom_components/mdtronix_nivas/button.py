"""Restart the unit, or clear a dry-run trip."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NivasConfigEntry
from .entity import NivasEntity


@dataclass(frozen=True, kw_only=True)
class NivasButtonDescription(ButtonEntityDescription):
    command: str


BUTTONS: tuple[NivasButtonDescription, ...] = (
    # After a dry-run trip the pump stays off until someone has checked the
    # water supply and cleared it; Auto then decides whether to restart.
    NivasButtonDescription(key="clear_dry_run", translation_key="clear_dry_run", command="dryrun:clear"),
    NivasButtonDescription(
        key="restart",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        command="restart",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: NivasConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(NivasButton(entry.runtime_data, entry.data, d) for d in BUTTONS)


class NivasButton(NivasEntity, ButtonEntity):
    entity_description: NivasButtonDescription

    async def async_press(self) -> None:
        await self.send(self.entity_description.command)
