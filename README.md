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
| [deploy/README.md](deploy/README.md) | Flashing the SKR, Pi setup, and the wiring for every subsystem — endstop, pump, water level sensor, soil sensors, LED strip, camera — plus how to route the harness |
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
   `uvicorn greenthumb.main:app --host 127.0.0.1 --port 8000 --reload`

## API

Everything is under `/api/v1`, grouped roughly as:

| Group | What it covers |
|---|---|
| `/overview`, `/sensors`, `/history`, `/logs` | reading current state, readings and history |
| `/plants/...` | per-plant name, light window, moisture target, dose volume, rail position, and move-to |
| `/plant-profiles`, `/plants/{id}/profile` | the saved-plant library: list, save, load, delete |
| `/soils`, `/plants/{id}/soil` | the soil library, and which mix a pot is filled with |
| `/water/{plant_id}` | move to a plant and dose it |
| `/gantry/home`, `/gantry/move`, `/gantry/end` | homing, jogging, and running to either end of the rail |
| `/pump/run`, `/pump/stop` | the pump directly, for bench testing |
| `/watering/auto` | the master switch for unattended watering |
| `/dances`, `/dances/run/{name}`, `/dances/auto` | the routines, and the periodic re-home |
| `/quiet`, `/quiet/hours`, `/quiet/snooze`, `/quiet/resume` | quiet hours and the snooze |
| `/lights/...` | mode, brightness, colour, strip type, colour order |
| `/sensors/calibration...` | read, measure and reset per-sensor moisture calibration |
| `/camera`, `/camera/stream`, `/camera/snapshot` | whether a camera is fitted, the live MJPEG view, and one frame. No UI — reach these directly |
| `/diagnostics/endstop` | reads the home switch and interprets it |
| `/system/time`, `/system/timezone` | the planter's clock |
| `/version` | what is running, and whether the checkout has moved on without it |

**The full, current list is generated from the routes themselves** at
<http://herman.local/docs> — interactive, and it cannot go stale.

Everything is on port 80. The API binds to `127.0.0.1` and does not listen on
the network itself, so nginx is the only way in from another machine — it
proxies `/api/`, `/health`, `/docs` and `/openapi.json`.

Example:

`curl http://herman.local/api/v1/overview`

## Local web UI

Nginx serves the built React app from the Pi. **Open `http://herman.local`.**

There is nothing to reach on any other port: the API listens on `127.0.0.1`
only. That closes a second unauthenticated door onto the LAN, which matters
because **the API still has no authentication** — anything on the WiFi can
reach every endpoint through nginx. See
[PRIVACY_SECURITY_SPEC.md](PRIVACY_SECURITY_SPEC.md).

Four tabs:

| Tab | What it does |
|---|---|
| **Plants** | Each plant's current moisture, its name, light window, moisture target, dose volume and rail position, plus saving and loading plants from the library — then the moisture and temperature history below |
| **Controls** | Home and jog the gantry, run a dance, move to a plant, water a plant, lighting, run the pump |
| **Diagnostics** | Home switch test, the planter's clock, what version is running, per-sensor moisture calibration, and the log |
| **Settings** | Four groups — Watering, Movement, Quiet hours and Lighting |

Tabs are grouped by how often you touch a thing rather than by subsystem:
Plants is the screen to open daily, Settings holds only what you set once, and
Diagnostics is where everything you reach for when something looks wrong now
lives together.

## Saved plants

Saving a plant stores its care settings under its **name**, which is the key:
saving again under the same name replaces that entry rather than making a
second one. "Basil - Wet" and "Basil - Dry" are simply two names, so they are
two saved plants. Capitalisation is not a difference — saving "basil" over
"Basil" renames the entry rather than duplicating it.

Loading copies a saved plant onto a pot, including its name. Two pots may end
up with the same name, which is allowed: `plant_id` is the identity and the
name is a label, and copying one plant onto a second pot is the point.

**The watering location is not part of a saved plant.** It describes where the
pot sits on the rail, not how the plant is cared for, so loading never moves
it. If it travelled, loading one plant onto a second pot would give both the
same rail coordinate and watering one would dribble into the other.

Stored in `data/state.json` under `plant_profiles`, alongside the rest of the
settings.

### Soils

Each plant records which mix it is potted in, chosen from a soil library that
works the same way as the saved plants — name as the key, overwrite on save:

```bash
python -m greenthumb.soil_library              # read them and the figures
python -m greenthumb.soil_library --install    # add them to the library
```

**Why the soil is recorded at all is a sensor argument before an agronomic
one.** A capacitive probe reads dielectric permittivity, and texture, organic
matter, bulk density and salinity all shift that relationship — so two
identical probes in two different mixes genuinely disagree. Without the mix
written down, that spread looks like sensor variation.

A soil entry holds field capacity and wilting point as volumetric water
content. **Only their ratio transfers**: it is dimensionless, so a published
figure applies to any pot of that mix, and it is what says where the bottom of
the usable range sits. The absolute figures do *not* convert into raw sensor
counts — that needs a response curve for the specific medium — which is why
`--calibrate wet` still measures field capacity in the actual pot. The library
supplies the *shape* of the window, calibration supplies its *position*.

| Mix | Field capacity | Wilting point | Usable |
|---|---|---|---|
| Coco coir | 55% VWC | 15% | 40 pts |
| Clay loam | 36% | 18% | 18 pts |
| Loam | 28% | 11% | 17 pts |
| Peat potting mix | 28% | 16% | 12 pts |
| Cactus / sandy mix | 12% | 5% | 7 pts |

Clay loam is the instructive one: it holds the most water of the mineral soils
but grips half of it below wilting point, so its usable window is no wider than
loam's. Wettest on paper is not most forgiving in practice.

Two caveats. Mineral-soil figures come from standard tensions and are settled;
container substrates are not, varying by manufacturer and by how firmly they
were packed. And mixes **lose capacity as they age and compact** — unused peat
holds measurably more than the same mix after a season — so re-run
`--calibrate wet` after a repot rather than trusting the old endpoint.

An unknown soil name is refused rather than stored, since a mix that is not in
the library supplies no ratio and would read as "set" while behaving exactly
like "not set".

### Starter profiles

Five common plants ship as a starting library — Peace Lily, Lettuce, Basil,
Pothos and Snake Plant, ordered wettest to driest:

```bash
python -m greenthumb.plant_library              # read them and why
python -m greenthumb.plant_library --install    # add them to the library
```

Installing keeps any entry you have already tuned; `--overwrite` replaces them.

**The photoperiods are researched, the moisture targets are not** — and cannot
be, because no horticultural source publishes a sensor percentage. The
literature describes dry-down behaviour ("let the top inch dry", "let it dry out
completely") and the number that corresponds to depends on your sensor and its
calibration. What the targets encode is the *ordering*: a snake plant should
want water far later than a peace lily.

They are also deliberately low, for a reason worth knowing. This scale is
`(raw - dry) / (wet - dry)` with the wet endpoint measured in **plain water**,
which is far wetter than saturated potting mix — so saturated soil reads
somewhere around 60-75%, never 100%. A target above what the soil can reach
makes a plant permanently thirsty, watered every `watering_cooldown_minutes`
until the reservoir is empty. **Calibrate the sensors before tuning against
these**, and keep targets well under what your own wettest reading shows.

Volumes assume a 15 cm (6 inch) pot and frequent small doses rather than a
weekly soak. Scale with the pot.

## Hardware assumptions

The code is written to be easy to adapt to the actual hardware stack:

- Klipper is the motion layer running on the BTT SKR Mini E3 V2
- Raspberry Pi hosts the application, on 64-bit Pi OS. The
  **Pi 3 Model A+ is the floor** — 512 MB and ARMv8 is what the stack has to fit
  in. Any Pi 3 will run it; a Pi 4 or a 3 B is the easier board to develop on.
  See [BOM.md](BOM.md)
- 4 capacitive moisture sensors are mapped to unique addresses and read through a passive I2C hub
- the camera add-on adds timelapse capture to the same service layer

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
   - alerting for low moisture and pump errors

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
with each watering. The **Sensors** tab charts moisture or temperature per plant
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
| Pump | Real — Klipper `output_pin` on the SKR's HB MOSFET |
| LEDs | Real — WS2811 (default), WS2815 or GS8208 over SPI, 12V only, strip type selectable in Settings |
| Water level sensor | Real — non-contact sensor on the outlet tube, via Klipper; verifies a dose rather than gating it |
| Camera | API only — Camera Module 3 Wide via rpicam-vid, MJPEG over HTTP. An optional add-on, with no UI and no timelapse |

Automatic watering is disabled by default. Turn it on with **Water plants
automatically** in the Settings tab; the choice persists across restarts.
`AUTO_WATERING_ENABLED` only sets the value a planter starts life with, and a
saved choice overrides it.

Enable it only after testing the pump by hand and measuring
`pump_flow_ml_per_second` against a real dose, since that figure converts a
requested volume into a pump run time.