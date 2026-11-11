"""The live link against a stand-in unit over real sockets on 127.0.0.1."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from custom_components.mdtronix_nivas import client as client_module
from custom_components.mdtronix_nivas.client import (
    InvalidKey,
    NotNivas,
    WtlcClient,
    WtlcData,
    apply_message,
    fetch_device,
    fetch_pair_key,
    probe,
)

from .fake_unit import KEY, SERIAL, FakeUnit, snapshot


@pytest.fixture
async def unit(socket_enabled):
    fake = FakeUnit()
    fake.port = await fake.start()
    yield fake
    await fake.close()


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s


async def _wait_for(predicate, timeout=5.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


async def test_device_info_and_pairing(unit, session):
    info = await fetch_device(session, "127.0.0.1", port=unit.port)
    assert info["serialNumber"] == SERIAL and info["nivas"] is True
    assert await fetch_pair_key(session, "127.0.0.1", port=unit.port) == KEY

    unit.pair_open = False
    assert await fetch_pair_key(session, "127.0.0.1", port=unit.port) is None

    unit.nivas = False
    with pytest.raises(NotNivas):
        await fetch_pair_key(session, "127.0.0.1", port=unit.port)


async def test_probe_checks_the_key(unit, session):
    state = await probe(session, "127.0.0.1", KEY, port=unit.port)
    assert state["level"] == 62.5
    with pytest.raises(InvalidKey):
        await probe(session, "127.0.0.1", "f" * 32, port=unit.port)


async def test_live_link_state_commands_and_clock(unit, session):
    changes = []
    client = WtlcClient(session, "127.0.0.1", KEY, port=unit.port, clock=lambda: (1762700000, 330))
    client.add_listener(lambda: changes.append(client.data.state.get("pump")))
    task = asyncio.create_task(client.run_forever())
    try:
        await _wait_for(lambda: client.connected and client.data.last_event is not None)
        assert client.data.state["level"] == 62.5
        assert client.data.usage["u"] == 1234
        assert client.data.last_event["cause"] == "tankFull"
        # The unit gets the time and Home Assistant's offset as soon as it's connected.
        await _wait_for(lambda: unit.commands)
        assert unit.commands[0] == "clock:1762700000:330"

        await client.send("pump:on")
        await _wait_for(lambda: client.data.state.get("pump") is True)
        assert "pump:on" in unit.commands
        assert changes[-1] is True
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_wrong_key_stops_and_asks_for_reauth(unit, session):
    refused = asyncio.Event()
    client = WtlcClient(session, "127.0.0.1", "f" * 32, port=unit.port, on_invalid_key=refused.set)
    async with asyncio.timeout(5):
        await client.run_forever()  # returns instead of retrying a key that can't work
    assert refused.is_set()
    assert not client.connected


async def test_reconnects_after_the_unit_drops(unit, session, monkeypatch):
    monkeypatch.setattr(client_module, "RETRY_DELAYS", (0.05,))
    client = WtlcClient(session, "127.0.0.1", KEY, port=unit.port)
    task = asyncio.create_task(client.run_forever())
    try:
        await _wait_for(lambda: client.connected)
        for ws in list(unit.sockets):
            await ws.close()
        await _wait_for(lambda: not client.connected)
        await _wait_for(lambda: client.connected)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_send_while_down_raises(session):
    client = WtlcClient(session, "127.0.0.1", KEY, port=1)
    with pytest.raises(client_module.NivasError):
        await client.send("pump:on")


def test_heap_and_uptime_alone_are_not_a_change():
    data = WtlcData()
    assert apply_message(data, snapshot())
    assert not apply_message(data, snapshot(heap=20000, uptime=13))
    assert apply_message(data, snapshot(level=61.0))
    assert not apply_message(data, {"days": {"k": 0}})
    assert apply_message(data, {"lastEvent": {}}) and data.last_event is None
