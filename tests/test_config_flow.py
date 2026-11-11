"""Adding a unit: by address, by discovery, with or without the pairing window, and re-pairing."""

from __future__ import annotations

from ipaddress import ip_address
from unittest.mock import patch

import pytest

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mdtronix_nivas.client import CannotConnect, InvalidKey
from custom_components.mdtronix_nivas.config_flow import normalize_key
from custom_components.mdtronix_nivas.const import CONF_KEY, CONF_SERIAL, CONF_TANK_LITRES, DOMAIN

from .fake_unit import KEY, SERIAL

FLOW = "custom_components.mdtronix_nivas.config_flow"
DEVICE = {"serialNumber": SERIAL, "firmwareVersion": "1.1.12", "type": "WTLC", "nivas": True}


@pytest.fixture(autouse=True)
def no_setup():
    with patch("custom_components.mdtronix_nivas.async_setup_entry", return_value=True):
        yield


def _discovery(host="192.168.1.50", **txt):
    properties = {"sn": SERIAL, "type": "wtlc", "fw": "1.1.12", "hw": "10.0", "proto": "1"}
    properties.update(txt)
    return ZeroconfServiceInfo(
        ip_address=ip_address(host),
        ip_addresses=[ip_address(host)],
        port=81,
        hostname="mdt-wtlc-7af23c.local.",
        type="_mdtronix._tcp.local.",
        name="mdt-wtlc-7af23c._mdtronix._tcp.local.",
        properties=properties,
    )


async def test_by_address_inside_the_pairing_window(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    with patch(f"{FLOW}.fetch_device", return_value=DEVICE), patch(f"{FLOW}.fetch_pair_key", return_value=KEY):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: " 192.168.1.50 "})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "FloX 7AF23C"
    assert result["data"] == {CONF_HOST: "192.168.1.50", CONF_SERIAL: SERIAL, CONF_KEY: KEY}
    assert result["result"].unique_id == SERIAL


async def test_by_address_after_the_window_asks_for_the_key(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    with patch(f"{FLOW}.fetch_device", return_value=DEVICE), patch(f"{FLOW}.fetch_pair_key", return_value=None):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: "192.168.1.50"})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "key"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_KEY: "not a key"})
    assert result["errors"] == {CONF_KEY: "invalid_key_format"}

    with patch(f"{FLOW}.probe", side_effect=InvalidKey):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_KEY: "f" * 32})
    assert result["errors"] == {CONF_KEY: "invalid_key"}

    with patch(f"{FLOW}.probe", side_effect=CannotConnect):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_KEY: KEY})
    assert result["errors"] == {"base": "cannot_connect"}

    grouped = "0123-4567 89AB-CDEF 0123-4567 89ab-cdef"
    with patch(f"{FLOW}.probe", return_value={"fw": "1.1.12"}) as probe:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_KEY: grouped})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_KEY] == KEY
    assert probe.call_args.args[2] == KEY


async def test_unit_not_in_smart_nivas_mode(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    with patch(f"{FLOW}.fetch_device", return_value={**DEVICE, "nivas": False}):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: "192.168.1.50"})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "not_nivas"


async def test_unreachable_address(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    with patch(f"{FLOW}.fetch_device", side_effect=CannotConnect):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: "192.168.1.99"})
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "cannot_connect"}


async def test_discovered_unit(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=_discovery()
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "confirm"
    with patch(f"{FLOW}.fetch_pair_key", return_value=KEY):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: "192.168.1.50", CONF_SERIAL: SERIAL, CONF_KEY: KEY}


async def test_discovery_follows_a_new_address(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=SERIAL, data={CONF_HOST: "192.168.1.50", CONF_SERIAL: SERIAL, CONF_KEY: KEY}
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=_discovery("192.168.1.77")
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "192.168.1.77"


async def test_discovery_of_another_device_type_is_ignored(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=_discovery(type="hub")
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "not_supported"


async def test_reauth_with_the_key_from_the_app(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=SERIAL, data={CONF_HOST: "192.168.1.50", CONF_SERIAL: SERIAL, CONF_KEY: "a" * 32}
    )
    entry.add_to_hass(hass)
    with patch(f"{FLOW}.fetch_pair_key", return_value=None):
        result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "key"
    with patch(f"{FLOW}.probe", return_value={"fw": "1.1.12"}):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_KEY: KEY})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reauth_successful"
    assert entry.data[CONF_KEY] == KEY


async def test_tank_size_option(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=SERIAL, data={CONF_HOST: "192.168.1.50", CONF_SERIAL: SERIAL, CONF_KEY: KEY}
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_TANK_LITRES: 1000})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_TANK_LITRES] == 1000


def test_key_normalisation():
    assert normalize_key(" 0123-4567-89AB-CDEF-0123-4567-89ab-cdef ") == KEY
    assert normalize_key("0123") is None
    assert normalize_key("g" * 32) is None
