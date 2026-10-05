# Herman the Gardening Robot

**Herman** is the product. **GreenThumb** is the software that runs it — the
Python package, the systemd units and `/opt/greenthumb` all keep that name, and
none of it is shown to whoever owns the planter. If a string reaches a screen
it says Herman.

Herman is a smart indoor planter / grow frame that combines:
- a motion system driven by a BTT SKR Mini E3 V2 and Klipper
- a Raspberry Pi host running Klipper
- four capacitive soil sensors on an I2C hub
- per-plant watering and lighting control
- an optional Pi camera add-on for monitoring and timelapse capture

This repository is intentionally structured as a product-ready foundation for a future commercial offering, not just a one-off prototype.

## Documentation

**Building and wiring one**

| Document | Covers |
|---|---|
| [deploy/README.md](deploy/README.md) | Flashing the SKR, Pi setup, and the wiring for every subsystem — endstop, pump, water level sensor, soil sensors, LED strip — plus how to route the harness |
| [POWER_SYSTEM.md](POWER_SYSTEM.md) | 12V busbar, fuse sizing and why each rating was chosen, power budget |
| [SENSOR_WIRING.md](SENSOR_WIRING.md) | Soil sensor I2C addressing and the per-plant address mapping |
| [BOM.md](BOM.md) | Parts list |

**How it behaves**

| Document | Covers |
|---|---|
| [HOW_WATERING_WORKS.md](HOW_WATERING_WORKS.md) | The watering rules and the reasoning, in plain language |
| [frontend/README.md](frontend/README.md) | Web UI build and layout |

**Product direction**

[PRODUCT_SPEC.md](PRODUCT_SPEC.md) · [ROADMAP.md](ROADMAP.md) · [COMMERCIAL_STRATEGY.md](COMMERCIAL_STRATEGY.md) · [PRIVACY_SECURITY_SPEC.md](PRIVACY_SECURITY_SPEC.md)

## Product concept

The system is a modular smart planter based on a modified IKEA VITTSJÖ frame with:
- black-brown melamine lower shelf and glass upper shelf
- 1000 mm 2020 extrusion rail mounted to the rear uprights
- GT2 belt + pulley drive powered by a NEMA 17 stepper
- homing against a mechanical endstop at the motor end of the rail
- addressable LED strip for lighting effects and per-plant segments
- 12V peristaltic pump for controlled watering

## Software architecture

This project lays down the initial application stack:

- `greenthumb/config.py` – configuration and environment-driven runtime settings
- `greenthumb/models.py` – plant, sensor, and status dataclasses
- `greenthumb/hardware/` – hardware adapters for Klipper, sensors, LEDs, and pump
- `greenthumb/services/automation.py` – orchestration layer for automated watering and lighting
- `greenthumb/main.py` – FastAPI service exposing a basic API

## Startup

1. Create a virtual environment
2. Install dependencies:
   `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and adjust values for your station
4. Run the service:
   `uvicorn greenthumb.main:app --host 0.0.0.0 --port 8000 --reload`

## API

Everything is under `/api/v1`, grouped roughly as:

| Group | What it covers |
|---|---|
| `/overview`, `/sensors`, `/history`, `/logs` | reading current state, readings and history |
| `/plants/...` | per-plant name, light window, moisture target, dose volume, rail position, and move-to |
| `/water/{plant_id}` | move to a plant and dose it |
| `/gantry/home`, `/gantry/move` | homing and jogging the one axis |
| `/pump/run`, `/pump/stop` | the pump directly, for bench testing |
| `/quiet`, `/quiet/hours`, `/quiet/snooze`, `/quiet/resume` | quiet hours and the snooze |
| `/lights/...` | mode, brightness, colour, strip type, colour order |
| `/sensors/calibration...` | read, measure and reset per-sensor moisture calibration |
| `/system/time`, `/system/timezone` | the planter's clock |
| `/version` | what is running, and whether the checkout has moved on without it |

**The full, current list is generated from the routes themselves** at
<http://herman.local:8000/docs> — interactive, and it cannot go stale the
way a hand-written list here did.

Note the port. Nginx serves the web UI on 80 but proxies only `/api/` and
`/health`, so `/docs` is reachable only on the API's own port.

Example:

`curl http://herman.local:8000/api/v1/overview`

## Local web UI

Nginx serves the built React app from the Pi. **Open `http://herman.local`**
— port 80, not 8000. Port 8000 is the API, and asking it for `/` returns a JSON
status blob rather than the page.

Four tabs:

| Tab | What it does |
|---|---|
| **Controls** | Home and jog the gantry, move to a plant, water a plant, lighting, run the pump |
| **Plants** | Each plant's current moisture, and its name, light window, moisture target, dose volume and rail position |
| **Sensors** | Moisture and temperature history, and per-sensor calibration |
| **Settings** | LED strip type and colour order, the planter's clock, and the log |

## Hardware assumptions

The code is written to be easy to adapt to the actual hardware stack:

- Klipper is the motion layer running on the BTT SKR Mini E3 V2
- Raspberry Pi hosts the application and camera services, on 64-bit Pi OS. A
  **Pi 3 Model B+ is the supported floor** — same board outline, mounting holes
  and CSI connector as the Pi 4, and 1 GB of RAM. See [BOM.md](BOM.md)
- 4 capacitive moisture sensors are mapped to unique addresses and read through a passive I2C hub
- optical / camera monitoring can be integrated later into the same service layer

## Production / commercialization roadmap

This repository is set up to become a real product in stages:

1. Device abstraction layer
   - real vendor-specific drivers for soil sensors, LEDs, and pump control
   - resilient error handling and calibration profiles

2. User dashboards
   - web dashboard with plant health, schedule editor, and plant controls
   - user authentication and access controls

3. Automation rules
   - scheduling, threshold-based irrigation, seasonal growth tuning
   - alerting for low moisture, pump errors, camera anomalies

4. Commercial productization
   - configuration profiles per plant of different species
   - MQTT / websocket streaming, telemetry retention, remote monitoring
   - manufacturing-aware diagnostics and service support workflows

5. Device management
   - onboarding flows, firmware update support, fleet telemetry
   - OTA configuration and remote support tooling

## How watering decisions are made

A background loop polls every sensor once a minute, averages the last ten
readings per plant, and waters a plant whose average falls below its target.
[HOW_WATERING_WORKS.md](HOW_WATERING_WORKS.md) explains the rules and the
reasoning in plain language, for people who won't be reading the code.

## Settings persistence

Anything changed at runtime — plant targets, dose volumes, rail positions, plant
names, per-sensor moisture calibration and LED preferences — is written to
`data/state.json` and reloaded at startup. The file is gitignored, so it
survives `git pull`, and writes are atomic so a power cut cannot truncate it.

A missing, corrupt or hand-edited file falls back to built-in defaults per
field rather than refusing to start: the appliance has to boot.

Plant definitions themselves (how many, which I2C address) still live in code —
only the user-editable fields are stored.

## History

Every reading is written to SQLite (`data/greenthumb.db`) once a minute, along
with each watering. The **History** tab charts moisture or temperature per plant
over 6 hours to 90 days, with dashed marks where waterings happened — which is
what makes it possible to tell whether a moisture target and dose are actually
right for a plant, rather than guessing.

Readings older than `history_retention_days` (90) are pruned daily. Gaps in a
line mean that sensor could not be read; failed reads are never stored.

## Tests

```bash
python tests/run_all.py
```

Plain assert scripts, no test dependency to install on the Pi. They stub `smbus2`
and `spidev`, so they run on a development machine with no hardware attached.

## Hardware status

| Component | State |
|---|---|
| Soil sensors | Real — I2C via the seesaw protocol, no simulation |
| Gantry | Real — Klipper over its Unix socket |
| Pump | Real — Klipper `output_pin` on the SKR's HE0 MOSFET |
| LEDs | Real — WS2812B/WS2815/GS8208/WS2811 over SPI, strip type selectable in settings |
| Water level sensor | Real — non-contact sensor on the outlet tube, via Klipper; verifies a dose rather than gating it |
| Camera | Not built — the UI controls for it are inert |

Automatic watering is disabled by default (`auto_watering_enabled` in
`greenthumb/config.py`). Enable it only after testing the pump by hand and
measuring `pump_flow_ml_per_second` against a real dose, since that figure
converts a requested volume into a pump run time.