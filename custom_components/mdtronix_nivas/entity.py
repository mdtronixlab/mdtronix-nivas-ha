"""Shared base for one unit's entities."""

from __future__ import annotations

from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription

from .client import NivasError, WtlcClient
from .const import CONF_SERIAL, DOMAIN, MANUFACTURER, WTLC_MODEL


class NivasEntity(Entity):
    """Pushed by the unit: no polling, unavailable while the link is down."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, client: WtlcClient, entry_data: dict[str, Any], description: EntityDescription) -> None:
        self.entity_description = description
        self._client = client
        serial = entry_data[CONF_SERIAL]
        self._attr_unique_id = f"{serial}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            manufacturer=MANUFACTURER,
            model=WTLC_MODEL,
            name=f"FloX {serial[-6:]}",
            serial_number=serial,
        )

    @property
    def available(self) -> bool:
        return self._client.connected and bool(self._client.data.state)

    @property
    def state_data(self) -> dict[str, Any]:
        return self._client.data.state

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._client.add_listener(self.async_write_ha_state))

    async def send(self, command: str) -> None:
        """Send a command, as a Home Assistant error if the unit can't be reached."""
        try:
            await self._client.send(command)
        except NivasError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_connected",
                translation_placeholders={"host": self._client.host},
            ) from err
