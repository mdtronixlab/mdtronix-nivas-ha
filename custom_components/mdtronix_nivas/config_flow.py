"""Adding a unit: found on the network, or by its address.

Pairing tries the unit's pairing route first, which hands out the key for 10
minutes after the unit joins Wi-Fi from a setup in the MDtronix app. After
that the user types in the key the app shows for the unit.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

try:  # Home Assistant 2025.1+
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
except ImportError:  # pragma: no cover
    from homeassistant.components.zeroconf import ZeroconfServiceInfo

from .client import CannotConnect, InvalidKey, NotNivas, fetch_device, fetch_pair_key, probe
from .const import (
    CONF_KEY,
    CONF_SERIAL,
    CONF_TANK_LITRES,
    DEVICE_TYPE_WTLC,
    DOMAIN,
    TXT_SERIAL,
    TXT_TYPE,
)

_LOGGER = logging.getLogger(__name__)

# 32 hex digits; the app may show it in groups, so spaces and dashes are dropped.
_KEY_SEPARATORS = re.compile(r"[\s-]")
_KEY_FORMAT = re.compile(r"^[0-9a-f]{32}$")


def normalize_key(raw: str) -> str | None:
    key = _KEY_SEPARATORS.sub("", raw).lower()
    return key if _KEY_FORMAT.match(key) else None


def _title(serial: str) -> str:
    return f"FloX {serial[-6:]}"


class NivasConfigFlow(ConfigFlow, domain=DOMAIN):
    """Find a unit, pair with it, and add it."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._serial: str | None = None

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        """A unit announced itself on the network."""
        properties = discovery_info.properties
        serial = properties.get(TXT_SERIAL)
        if not serial or properties.get(TXT_TYPE) != DEVICE_TYPE_WTLC:
            return self.async_abort(reason="not_supported")
        self._host = discovery_info.host
        self._serial = serial
        await self.async_set_unique_id(serial)
        # A known unit that moved to a new address: follow it.
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})
        self.context["title_placeholders"] = {"name": _title(serial)}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask before pairing with a unit found on the network."""
        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                description_placeholders={"name": _title(self._serial or ""), "host": self._host or ""},
            )
        return await self._async_pair()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Added by hand, by IP address or host name."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                info = await fetch_device(async_get_clientsession(self.hass), host)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                if not info.get("nivas"):
                    return self.async_abort(reason="not_nivas")
                self._host = host
                self._serial = info["serialNumber"]
                await self.async_set_unique_id(self._serial)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return await self._async_pair()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )

    async def _async_pair(self) -> ConfigFlowResult:
        """Get the key from the unit if it still offers it, else ask for it."""
        assert self._host and self._serial
        try:
            key = await fetch_pair_key(async_get_clientsession(self.hass), self._host)
        except NotNivas:
            return self.async_abort(reason="not_nivas")
        except CannotConnect:
            return self.async_abort(reason="cannot_connect")
        if key is None:
            return await self.async_step_key()
        return self.async_create_entry(
            title=_title(self._serial),
            data={CONF_HOST: self._host, CONF_SERIAL: self._serial, CONF_KEY: key},
        )

    async def async_step_key(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """The pairing window has closed: the user enters the key from the app."""
        errors: dict[str, str] = {}
        if user_input is not None:
            key = normalize_key(user_input[CONF_KEY])
            if key is None:
                errors[CONF_KEY] = "invalid_key_format"
            else:
                try:
                    await probe(async_get_clientsession(self.hass), self._host or "", key)
                except InvalidKey:
                    errors[CONF_KEY] = "invalid_key"
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                else:
                    data = {CONF_HOST: self._host, CONF_SERIAL: self._serial, CONF_KEY: key}
                    if self.source == "reauth":
                        return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=data)
                    return self.async_create_entry(title=_title(self._serial or ""), data=data)
        return self.async_show_form(
            step_id="key",
            data_schema=vol.Schema({vol.Required(CONF_KEY): str}),
            errors=errors,
            description_placeholders={"name": _title(self._serial or "")},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The unit refused its key: it was set up again in the app, or factory reset."""
        self._host = entry_data[CONF_HOST]
        self._serial = entry_data[CONF_SERIAL]
        try:
            key = await fetch_pair_key(async_get_clientsession(self.hass), self._host)
        except (CannotConnect, NotNivas):
            key = None
        if key is not None:
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates={CONF_KEY: key})
        return await self.async_step_key()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return NivasOptionsFlow()


class NivasOptionsFlow(OptionsFlow):
    """The tank's size, which the unit doesn't know, for figures in litres."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_TANK_LITRES, 0)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Optional(CONF_TANK_LITRES, default=current): vol.All(vol.Coerce(int), vol.Range(min=0, max=1_000_000))}
            ),
        )
