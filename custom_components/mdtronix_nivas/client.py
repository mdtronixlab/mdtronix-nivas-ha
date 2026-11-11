"""Live link to one WTLC unit in Smart Nivas mode (wtlc firmware 1.1.12 or newer).

Kept free of Home Assistant imports so it can be tested on its own.

The unit (src/network/LocalSocket.cpp) serves a WebSocket on port 81. On the
home network it first sends {"auth":"required"}; the client answers
"auth:<key>" and gets {"auth":"ok"}, or {"auth":"failed"} and a closed
socket. After that it gets what the app gets on the unit's hotspot:

- a snapshot of state and settings about once a second (it carries "fw");
- {"usage": {...}}: totals and the last 7 days (PumpUsage.h);
- {"days": {...}} and {"levels": {...}}: longer history, not used here;
- {"lastEvent": {...}}: what last started or stopped the pump.

Commands are plain text frames such as "pump:on" or "start:30"
(src/tank/TankCommands.cpp). The unit ignores one it can't accept, and a
change it does accept shows in the next snapshot, sent at once.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import json
import logging
from typing import Any

import aiohttp

from .const import HTTP_PORT, SOCKET_PORT

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10.0
# The unit sends a snapshot every second; this long without one means the
# link is dead even if TCP hasn't noticed.
STALE_AFTER = 15.0
RETRY_DELAYS = (2, 5, 10, 30, 60)


class NivasError(Exception):
    """Base error for talking to a unit."""


class CannotConnect(NivasError):
    """The unit didn't answer."""


class InvalidKey(NivasError):
    """The unit refused the key."""


class NotNivas(NivasError):
    """The unit is not in Smart Nivas mode."""


@dataclass
class WtlcData:
    """The latest of each kind of message from a unit."""

    state: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] | None = None
    last_event: dict[str, Any] | None = None


# Snapshot fields that change every second without meaning anything changed.
_VOLATILE = frozenset({"uptime", "heap"})


def _shown(state: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in state.items() if k not in _VOLATILE}


def apply_message(data: WtlcData, message: dict[str, Any]) -> bool:
    """Store one message from the unit. True if anything shown changed."""
    if "usage" in message:
        data.usage = message["usage"]
        return True
    if "lastEvent" in message:
        data.last_event = message["lastEvent"] or None
        return True
    if "days" in message or "levels" in message or "auth" in message:
        return False
    if "fw" in message:
        changed = _shown(message) != _shown(data.state)
        data.state = message
        return changed
    return False


def _http_url(host: str, path: str, port: int = HTTP_PORT) -> str:
    return f"http://{host}:{port}{path}"


def _ws_url(host: str, port: int = SOCKET_PORT) -> str:
    return f"ws://{host}:{port}/"


async def fetch_device(session: aiohttp.ClientSession, host: str, *, port: int = HTTP_PORT) -> dict[str, Any]:
    """The unit's GET /api/device: serial, firmware, and whether it's in Smart Nivas mode."""
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT):
            async with session.get(_http_url(host, "/api/device", port)) as resp:
                resp.raise_for_status()
                info = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise CannotConnect(str(err)) from err
    if not isinstance(info, dict) or not info.get("serialNumber"):
        raise CannotConnect("not an MDtronix unit")
    return info


async def fetch_pair_key(session: aiohttp.ClientSession, host: str, *, port: int = HTTP_PORT) -> str | None:
    """The key from POST /api/nivas/pair, or None once its pairing window has closed.

    The unit only hands it out for 10 minutes after it joins Wi-Fi following a
    setup in the app; after that the user enters the key the app shows.
    """
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT):
            async with session.post(_http_url(host, "/api/nivas/pair", port)) as resp:
                if resp.status == 403:
                    return None
                if resp.status == 404:
                    raise NotNivas
                resp.raise_for_status()
                body = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise CannotConnect(str(err)) from err
    key = body.get("key") if isinstance(body, dict) else None
    if not isinstance(key, str) or len(key) != 32:
        raise CannotConnect("the unit sent no key")
    return key


async def probe(session: aiohttp.ClientSession, host: str, key: str, *, port: int = SOCKET_PORT) -> dict[str, Any]:
    """Connect once with the key and return the first snapshot. Raises InvalidKey or CannotConnect."""
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT):
            async with session.ws_connect(_ws_url(host, port)) as ws:
                async for msg in ws:
                    if msg.type is not aiohttp.WSMsgType.TEXT:
                        break
                    try:
                        payload = json.loads(msg.data)
                    except ValueError:
                        continue
                    auth = payload.get("auth")
                    if auth == "required":
                        await ws.send_str(f"auth:{key}")
                    elif auth == "failed":
                        raise InvalidKey
                    elif "fw" in payload:
                        return payload
    except (aiohttp.ClientError, TimeoutError, OSError) as err:
        raise CannotConnect(str(err)) from err
    raise CannotConnect("the unit closed the connection")


class WtlcClient:
    """Keeps one unit's live link open, reconnecting with backoff, and tells listeners about changes."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        key: str,
        *,
        port: int = SOCKET_PORT,
        clock: Callable[[], tuple[int, int]] | None = None,
        on_invalid_key: Callable[[], None] | None = None,
    ) -> None:
        self._session = session
        self._host = host
        self._port = port
        self._key = key
        self._clock = clock
        self._on_invalid_key = on_invalid_key
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._listeners: list[Callable[[], None]] = []
        self._connected = False
        self.data = WtlcData()

    @property
    def host(self) -> str:
        return self._host

    @property
    def connected(self) -> bool:
        """True while the link is up and the unit has sent its state."""
        return self._connected

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call listener on every change. Returns a function that removes it."""
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    def _set_connected(self, connected: bool) -> None:
        if connected != self._connected:
            self._connected = connected
            self._notify()

    async def send(self, command: str) -> None:
        """Send one command. Raises NivasError if the link is down."""
        ws = self._ws
        if ws is None or ws.closed or not self._connected:
            raise NivasError("not connected")
        try:
            await ws.send_str(command)
        except (aiohttp.ClientError, ConnectionError) as err:
            raise NivasError(str(err)) from err

    async def run_forever(self) -> None:
        """Hold the link open until cancelled, or until the unit refuses the key."""
        attempt = 0
        while True:
            try:
                if await self._run_once():
                    attempt = 0
            except InvalidKey:
                _LOGGER.warning("%s refused the Smart Nivas key", self._host)
                self._set_connected(False)
                if self._on_invalid_key:
                    self._on_invalid_key()
                return
            except (aiohttp.ClientError, TimeoutError, OSError, NivasError) as err:
                _LOGGER.debug("link to %s dropped: %s", self._host, err)
            finally:
                self._ws = None
            self._set_connected(False)
            delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
            attempt += 1
            await asyncio.sleep(delay)

    async def _run_once(self) -> bool:
        """One connection, until it drops. True if the unit sent its state at least once."""
        got_state = False
        async with asyncio.timeout(CONNECT_TIMEOUT):
            ws = await self._session.ws_connect(_ws_url(self._host, self._port), heartbeat=30)
        self._ws = ws
        try:
            while True:
                try:
                    async with asyncio.timeout(STALE_AFTER):
                        msg = await ws.receive()
                except TimeoutError as err:
                    raise NivasError("no state for 15 s") from err
                if msg.type is not aiohttp.WSMsgType.TEXT:
                    return got_state
                try:
                    payload = json.loads(msg.data)
                except ValueError:
                    continue
                if not isinstance(payload, dict):
                    continue
                auth = payload.get("auth")
                if auth == "required":
                    await ws.send_str(f"auth:{self._key}")
                    continue
                if auth == "failed":
                    raise InvalidKey
                changed = apply_message(self.data, payload)
                if "fw" in payload and not got_state:
                    got_state = True
                    await self._send_clock(ws)
                    self._connected = True
                    changed = True
                if changed:
                    self._notify()
        finally:
            await ws.close()

    async def _send_clock(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Give the unit the time: it has no clock of its own, and may have no internet for NTP.

        Its quiet hours and daily figures need it. A unit already synced only
        takes the time-zone offset from this.
        """
        if self._clock is None:
            return
        epoch, offset_minutes = self._clock()
        await ws.send_str(f"clock:{epoch}:{offset_minutes}")
