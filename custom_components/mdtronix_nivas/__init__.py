"""MDtronix Smart Nivas: MDtronix units on the home network, with no cloud.

One config entry per unit. For now that is the WTLC (FloX water tank
controller) set up in the MDtronix app as "MDtronix Smart Nivas"; see
client.py for how it talks to one.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .client import WtlcClient
from .const import CONF_KEY, CONF_SERIAL, DOMAIN

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

type NivasConfigEntry = ConfigEntry[WtlcClient]


def _clock() -> tuple[int, int]:
    """Now, and Home Assistant's UTC offset in minutes, for the unit's clock."""
    now = dt_util.now()
    offset = now.utcoffset()
    return int(now.timestamp()), int(offset.total_seconds() // 60) if offset else 0


async def async_setup_entry(hass: HomeAssistant, entry: NivasConfigEntry) -> bool:
    """Open the unit's live link. Its entities stay unavailable until it answers."""
    client = WtlcClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_KEY],
        clock=_clock,
        on_invalid_key=lambda: entry.async_start_reauth(hass),
    )
    entry.runtime_data = client
    reported: list[str | None] = []

    @callback
    def update_firmware() -> None:
        # The device page shows the firmware the unit reports, which changes
        # when it is updated from the app.
        firmware = client.data.state.get("fw")
        hardware = client.data.state.get("hw")
        if not firmware or [firmware, hardware] == reported:
            return
        reported[:] = [firmware, hardware]
        # Same identifiers as the entities' DeviceInfo, so this updates that device.
        dr.async_get(hass).async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, entry.data[CONF_SERIAL])},
            sw_version=firmware,
            hw_version=hardware,
        )

    entry.async_on_unload(client.add_listener(update_firmware))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(hass, client.run_forever(), f"{DOMAIN} {entry.data[CONF_SERIAL]}")
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NivasConfigEntry) -> bool:
    """Stop the live link (its background task is cancelled with the entry)."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _options_updated(hass: HomeAssistant, entry: NivasConfigEntry) -> None:
    """A tank size added or changed adds or removes the litre sensors."""
    await hass.config_entries.async_reload(entry.entry_id)
