# MDtronix Smart Nivas for Home Assistant

Control MDtronix devices from Home Assistant over your own Wi-Fi, with no cloud.

The first device it supports is the **FloX water tank controller**.

## Requirements

- FloX firmware 1.1.12 or newer.
- The FloX set up in the MDtronix app as **MDtronix Smart Nivas**, on the same network as Home Assistant.
- Home Assistant 2025.1 or newer.

In Smart Nivas mode the FloX doesn't connect to the MDtronix cloud. The MDtronix app sets it up, and from then on you use it in Home Assistant.

## Install

1. In HACS, add this repository as a custom repository (category: Integration).
2. Install **MDtronix Smart Nivas**, then restart Home Assistant.
3. Set up the FloX in the MDtronix app and choose **MDtronix Smart Nivas**.
4. In Home Assistant, open **Settings → Devices & services**. The FloX shows up there as discovered within a minute. Select **Add**.

**Pairing:**
- In the first 10 minutes after the FloX joins your Wi-Fi from a setup, Home Assistant collects the unit's key by itself.
- After that, Home Assistant asks for the key. Open the unit in the MDtronix app to see its **Smart Nivas key**.

You can also add a FloX by its IP address: **Add integration → MDtronix Smart Nivas**.

## What you get

| Type | Entities |
|---|---|
| Sensors | Level; current run; pump time today and in total; tank used today; last pump change and its time; sensor distance; status |
| Sensors with a tank size set | Water in tank; water used today; water used in total (works with the Energy dashboard's water consumption) |
| Binary sensors | Pump running; level sensor fault; dry run; Auto paused; quiet hours |
| Switches | Pump; Auto; dry-run protection; quiet hours mode |
| Numbers | Start level; stop level; maximum run time; dry-run check interval |
| Buttons | Clear dry run; restart |

**Tank size:** the FloX measures the level, not the volume. Enter the tank's size in litres in the integration's options to get the litre sensors.

**Clock:** Home Assistant gives the FloX the time each time it connects, so quiet hours and daily figures work even without internet.

## Security

The FloX only accepts a connection from your network once it has been given its key. Anyone who has the key can control the pump, so keep it private.

If the unit is factory reset, or set up again in another mode, Home Assistant loses access. Set it up as Smart Nivas again in the app; it keeps the same key.

## How it talks to the FloX

- **Discovery:** the FloX announces itself over mDNS as `_mdtronix._tcp`, with TXT `sn`, `type`, `fw`, `hw` and `proto`.
- **Pairing:** `POST http://<unit>/api/nivas/pair` returns the key while the unit's pairing window is open.
- **Live link:** a WebSocket at `ws://<unit>:81/`.
  1. The unit sends `{"auth":"required"}`.
  2. The client answers `auth:<key>`.
  3. The unit then sends a state snapshot every second, plus `usage`, `days`, `levels` and `lastEvent` messages.
  4. Commands are text frames such as `pump:on` or `start:30`.

Firmware source: the `wtlc` repo, `src/network/NivasLink.cpp` and `src/network/LocalSocket.cpp`.

## Development

Home Assistant's test harness runs on Linux (WSL works):

```
pip install pytest-homeassistant-custom-component
pytest
```

`tests/fake_unit.py` stands in for a FloX over real sockets.
