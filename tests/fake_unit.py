"""A stand-in WTLC unit speaking the firmware's Smart Nivas protocol (LocalSocket.cpp, DeviceWebServer.cpp)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer

KEY = "0123456789abcdef0123456789abcdef"
SERIAL = "MDT-WTLC-7AF23C"


def snapshot(**changes: Any) -> dict[str, Any]:
    state = {
        "fw": "1.1.12",
        "hw": "10.0",
        "levelValid": True,
        "level": 62.5,
        "distanceCm": 41.2,
        "pump": False,
        "auto": True,
        "sensorError": False,
        "dryRunActive": False,
        "autoSuppressed": False,
        "autoSuppressedWaitingAboveStop": False,
        "quietHours": False,
        "safetyModePending": False,
        "pumpRunMinutes": 0,
        "status": "Auto",
        "dryRunProtection": True,
        "safetyMode": False,
        "dolStarterMode": False,
        "startPumpAt": 30,
        "stopPumpAt": 95,
        "maxPumpRunTime": 60,
        "dryRunInterval": 2,
        "configured": True,
        "tankHeightCm": 200,
        "fullDistanceCm": 25,
        "emptyDistanceCm": 180,
        "resetReason": "Power On",
        "heap": 21000,
        "uptime": 12,
    }
    state.update(changes)
    return state


class FakeUnit:
    """HTTP and the live socket on one port; the real unit uses 80 and 81."""

    def __init__(self, *, key: str = KEY, nivas: bool = True, pair_open: bool = True) -> None:
        self.key = key
        self.nivas = nivas
        self.pair_open = pair_open
        self.state = snapshot()
        self.usage = {"t": 5400, "u": 1234, "p": 1500, "d": 0, "s": [600, 0], "su": [180, 90], "sp": [200, 0]}
        self.last_event = {"on": False, "cause": "tankFull", "via": "local", "t": 1762700000, "run": 840, "level": 95.5}
        self.commands: list[str] = []
        self.sockets: list[web.WebSocketResponse] = []
        app = web.Application()
        app.router.add_get("/", self._socket)
        app.router.add_get("/api/device", self._device)
        app.router.add_post("/api/nivas/pair", self._pair)
        self.server = TestServer(app, host="127.0.0.1")

    async def start(self) -> int:
        await self.server.start_server()
        return self.server.port

    async def close(self) -> None:
        for ws in list(self.sockets):
            await ws.close()
        await self.server.close()

    async def _device(self, request: web.Request) -> web.Response:
        return web.json_response({"serialNumber": SERIAL, "firmwareVersion": "1.1.12", "type": "WTLC", "nivas": self.nivas})

    async def _pair(self, request: web.Request) -> web.Response:
        if not self.nivas:
            return web.json_response({"success": False, "error": "not in Smart Nivas mode"}, status=404)
        if not self.pair_open:
            return web.json_response({"success": False, "error": "pairing window closed"}, status=403)
        return web.json_response({"serialNumber": SERIAL, "type": "WTLC", "firmwareVersion": "1.1.12", "key": self.key})

    async def push_state(self, **changes: Any) -> None:
        self.state.update(changes)
        for ws in list(self.sockets):
            await ws.send_str(json.dumps(self.state))

    async def _socket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_str('{"auth":"required"}')
        msg = await ws.receive()
        if msg.type is not WSMsgType.TEXT or msg.data != f"auth:{self.key}":
            await ws.send_str('{"auth":"failed"}')
            await ws.close()
            return ws
        await ws.send_str('{"auth":"ok"}')
        await ws.send_str(json.dumps(self.state))
        await ws.send_str(json.dumps({"usage": self.usage}))
        await ws.send_str(json.dumps({"lastEvent": self.last_event}))
        self.sockets.append(ws)
        try:
            async for msg in ws:
                if msg.type is not WSMsgType.TEXT:
                    break
                self.commands.append(msg.data)
                if msg.data in ("pump:on", "pump:off"):
                    await self.push_state(pump=msg.data == "pump:on")
                await asyncio.sleep(0)
        finally:
            self.sockets.remove(ws)
        return ws
