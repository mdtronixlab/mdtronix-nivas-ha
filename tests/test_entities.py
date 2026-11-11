"""The entities a unit gets, driven by a stand-in client inside a real Home Assistant."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from homeassistant.const import CONF_HOST, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mdtronix_nivas.client import NivasError, WtlcData
from custom_components.mdtronix_nivas.const import CONF_KEY, CONF_SERIAL, CONF_TANK_LITRES, DOMAIN

from .fake_unit import KEY, SERIAL, snapshot

# Home Assistant's test zone; the usage lists are dated in device-local days.
TODAY = (datetime.now(ZoneInfo("US/Pacific")).date().toordinal() - datetime(1970, 1, 1).date().toordinal())


class FakeClient:
    def __init__(self, session, host, key, **kwargs):
        self.host = host
        self.connected = True
        self.sent: list[str] = []
        self.fail_sends = False
        self.data = WtlcData(
            state=snapshot(),
            usage={"t": 5400, "u": 1234, "p": 1500, "d": TODAY, "s": [600, 0], "su": [180, 90], "sp": [200, 0]},
            last_event={"on": False, "cause": "tankFull", "via": "local", "t": 1762700000, "run": 840, "level": 95.5},
        )
        self._listeners = []
        FakeClient.last = self

    def add_listener(self, listener):
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def push(self, **changes):
        self.data.state = {**self.data.state, **changes}
        for listener in list(self._listeners):
            listener()

    async def send(self, command):
        if self.fail_sends:
            raise NivasError("down")
        self.sent.append(command)

    async def run_forever(self):
        await asyncio.Event().wait()


async def _setup(hass: HomeAssistant, options=None) -> FakeClient:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SERIAL,
        title="FloX 7AF23C",
        data={CONF_HOST: "192.168.1.50", CONF_SERIAL: SERIAL, CONF_KEY: KEY},
        options=options or {},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.mdtronix_nivas.WtlcClient", FakeClient):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    client = FakeClient.last
    client.push()  # as the first snapshot arrives
    await hass.async_block_till_done()
    return client


async def test_readings(hass: HomeAssistant):
    await _setup(hass)
    assert hass.states.get("sensor.flox_7af23c_level").state == "62.5"
    assert hass.states.get("sensor.flox_7af23c_tank_used_today").state == "18.0"
    assert hass.states.get("sensor.flox_7af23c_pump_time_today").state == "10.0"  # 600 s, shown in minutes
    assert hass.states.get("sensor.flox_7af23c_last_pump_change").state == "tank_full"
    assert hass.states.get("sensor.flox_7af23c_last_pump_change").attributes["level"] == 95.5
    assert hass.states.get("binary_sensor.flox_7af23c_pump").state == "off"
    assert hass.states.get("switch.flox_7af23c_auto").state == "on"
    assert hass.states.get("number.flox_7af23c_start_level").state == "30"
    # Litres only once the tank size is known.
    assert hass.states.get("sensor.flox_7af23c_water_used_today") is None

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    (device,) = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert device.identifiers == {(DOMAIN, SERIAL)}
    assert device.manufacturer == "MDtronix" and device.serial_number == SERIAL
    assert device.sw_version == "1.1.12"


async def test_litres_with_a_tank_size(hass: HomeAssistant):
    await _setup(hass, {CONF_TANK_LITRES: 1000})
    assert hass.states.get("sensor.flox_7af23c_water_in_tank").state == "625.0"
    assert hass.states.get("sensor.flox_7af23c_water_used_today").state == "180.0"
    assert hass.states.get("sensor.flox_7af23c_water_used").state == "1234.0"
    assert hass.states.get("sensor.flox_7af23c_tank_used_today") is None


async def test_controls_send_commands(hass: HomeAssistant):
    client = await _setup(hass)
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.flox_7af23c_pump"}, blocking=True)
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.flox_7af23c_auto"}, blocking=True)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.flox_7af23c_start_level", "value": 25}, blocking=True
    )
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.flox_7af23c_maximum_run_time", "value": 90}, blocking=True
    )
    await hass.services.async_call("button", "press", {"entity_id": "button.flox_7af23c_clear_dry_run"}, blocking=True)
    assert client.sent == ["pump:on", "mode:manual", "start:25", "maxruntime:90", "dryrun:clear"]

    client.push(pump=True, pumpRunMinutes=3)
    await hass.async_block_till_done()
    assert hass.states.get("switch.flox_7af23c_pump").state == "on"
    assert hass.states.get("sensor.flox_7af23c_current_run").state == "3"


async def test_levels_are_checked_before_sending(hass: HomeAssistant):
    client = await _setup(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": "number.flox_7af23c_start_level", "value": 95}, blocking=True
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": "number.flox_7af23c_stop_level", "value": 30}, blocking=True
        )
    assert client.sent == []


async def test_unavailable_while_the_link_is_down(hass: HomeAssistant):
    client = await _setup(hass)
    client.connected = False
    client.push()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.flox_7af23c_level").state == STATE_UNAVAILABLE

    client.connected = True
    client.fail_sends = True
    client.push()
    await hass.async_block_till_done()
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.flox_7af23c_pump"}, blocking=True)


async def test_unload(hass: HomeAssistant):
    await _setup(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.flox_7af23c_level").state == STATE_UNAVAILABLE
