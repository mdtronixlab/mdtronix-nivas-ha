"""Constants for MDtronix Smart Nivas."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "mdtronix_nivas"
MANUFACTURER: Final = "MDtronix"

CONF_KEY: Final = "key"
CONF_SERIAL: Final = "serial"
CONF_TANK_LITRES: Final = "tank_litres"

# Where a unit listens (wtlc firmware, include/config.h): the live link is a
# WebSocket on LOCAL_SOCKET_PORT, setup and pairing are plain HTTP on 80.
SOCKET_PORT: Final = 81
HTTP_PORT: Final = 80

# The unit announces itself as _mdtronix._tcp with these TXT keys.
TXT_SERIAL: Final = "sn"
TXT_TYPE: Final = "type"
TXT_FIRMWARE: Final = "fw"
TXT_HARDWARE: Final = "hw"

DEVICE_TYPE_WTLC: Final = "wtlc"
WTLC_MODEL: Final = "FloX water tank controller"

# Limits the firmware enforces (wtlc include/config.h). It ignores a command
# outside them, so they're checked here first to give the user a reason.
LEVEL_MIN: Final = 0.0
LEVEL_MAX: Final = 100.0
DRY_RUN_INTERVAL_MIN: Final = 1
DRY_RUN_INTERVAL_MAX: Final = 10
MAX_RUN_TIME_MIN: Final = 1
MAX_RUN_TIME_MAX: Final = 1440  # the firmware allows up to 65535 minutes

# What last started or stopped the pump (PumpEvents.cpp CAUSE_NAMES), as
# Home Assistant enum states.
PUMP_EVENT_CAUSES: Final = {
    "unknown": "unknown",
    "auto": "auto",
    "app": "app",
    "button": "button",
    "starter": "starter",
    "resume": "resume",
    "tankFull": "tank_full",
    "dryRun": "dry_run",
    "maxRunTime": "max_run_time",
    "quietHours": "quiet_hours",
    "sensorFault": "sensor_fault",
    "restart": "restart",
    "powerLoss": "power_loss",
    "starterSetting": "starter_setting",
    "starterFull": "starter_full",
}
