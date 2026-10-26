# Herman the Gardening Robot

**Herman** is the product. **GreenThumb** is the software that runs it — the
Python package, the systemd units and `/opt/greenthumb` all keep that name, and
none of it is shown to whoever owns the planter. If a string reaches a screen
it says Herman.

Herman is a smart indoor planter / grow frame that combines:
- a motion system driven by a BTT SKR Mini E3 (V2 or V3) and Klipper
- a Raspberry Pi host running Klipper
- four capacitive soil sensors on an I2C hub
- per-plant watering and lighting control
- an optional Pi camera add-on for monitoring and timelapse capture

This repository is intentionally structured as a product-ready foundation for a future commercial offering, not just a one-off prototype.

## Documentation

**Building and wiring one**

| Document | Covers |
|---|---|
| [deploy/README.md](deploy/README.md) | Flashing the SKR, Pi setup, and the wiring for every subsystem — endstop, pump, soil sensors, LED strip, camera — plus how to route the harness |
| [POWER_SYSTEM.md](POWER_SYSTEM.md) | 12V busbar, fuse sizing and why each rating was chosen, power budget |
| [SENSOR_WIRING.md](SENSOR_WIRING.md) | Soil sensor I2C addressing and the per-plant address mapping |
| [BOM.md](BOM.md) | Parts list |

**How it behaves**

| Document | Covers |
|---|---|
| [HOW_WATERING_WORKS.md](HOW_WATERING_WORKS.md) | The watering rules and the reasoning, in plain language |
| [SOIL_PROFILES.md](SOIL_PROFILES.md) | The three soil recipes, which plants go in which, and how to take each one's readings |
| [frontend/README.md](frontend/README.md) | Web UI build and layout |

**Product direction**

[PRODUCT_SPEC.md](PRODUCT_SPEC.md) · [ROADMAP.md](ROADMAP.md) · [COMMERCIAL_STRATEGY.md](COMMERCIAL_STRATEGY.md) · [PRIVACY_SECURITY_SPEC.md](PRIVACY_SECURITY_SPEC.md)

## Product concept

The system is a modular smart planter based on a modified IKEA VITTSJÖ frame with:
- black-brown melamine lower shelf and glass upper shelf
- 1000 mm 2020 extrusion rail mounted to the rear uprights, with 890 mm of
  usable carriage travel
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
| `/plants/...` | per-plant name, light window and scheduled light color, moisture target, dose volume, rail position, watering mode and sweep span, and move-to |
| `/plant-profiles`, `/plants/{id}/profile` | the plant profile library: list, read one, write one from a body, snapshot a pot, load onto a pot, delete |
| `/soils`, `/plants/{id}/soil` | the soil library — list, add, remove — and which mix a pot is filled with |
| `/water/{plant_id}` | move to a plant and dose it |
| `/gantry/home`, `/gantry/move`, `/gantry/end` | homing, jogging, and running to either end of the rail |
| `/pump/run`, `/pump/stop` | the pump directly, for bench testing |
| `/watering/auto` | the master switch for unattended watering |
| `/dances`, `/dances/run/{name}` | the routines, run by hand |
| `/patrol/auto`, `/gantry/home-on-startup` | the hourly auto-patrol and the startup home, each on or off |
| `/quiet`, `/quiet/hours`, `/quiet/snooze`, `/quiet/resume` | quiet hours and the snooze |
| `/lights/...` | mode (Zone Schedule, Manual, Rainbow, Off), brightness, color, Manual for all zones or each zone (`/lights/manual-scope`, `/lights/zones/{plant_id}`), rainbow speed, strip type, color order |
| `/sensors/calibration...` | read, measure and reset per-sensor moisture calibration |
| `/system/restore-defaults` | back to a fresh install; the plant profile and soil libraries and the history are kept |
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

## Plant profiles

Saving a plant stores its care settings under its **name**, which is the key:
saving again under the same name replaces that entry rather than making a
second one. "Basil - Wet" and "Basil - Dry" are simply two names, so they are
two plant profiles. Capitalisation is not a difference — saving "basil" over
"Basil" renames the entry rather than duplicating it.

Loading copies a plant profile onto a pot, including its name. Two pots may end
up with the same name, which is allowed: `plant_id` is the identity and the
name is a label, and copying one plant onto a second pot is the point.

**A plant profile is edited in its own right**, in the Plant Profile Editor on the Plants
and Soil tab, or over the API:

```bash
curl -X POST http://herman.local/api/v1/plant-profiles -H 'Content-Type: application/json' \
  -d '{"name":"Basil","category":"Culinary Herbs & Kitchen Greens","preferred_soil":"Rich & Retentive Mix","target_available":32,"watering_volume_ml":120,"light_start_time":"07:30","light_hours":13,"light_brightness":75,"notes":"South window, dries fast in summer."}'
curl http://herman.local/api/v1/plant-profiles/Basil
```

What a plant profile carries:

| Field | Meaning |
|---|---|
| Category | Groups the profile in the dropdowns. Optional. |
| Preferred soil | The soil profile the plant wants. Loading the profile switches the pot to it. |
| Water at (% soil water) | The pot is watered once its soil water drops to this, from 10 to 90%. See *Watering targets* below. |
| Water level | The target in words, from Ultra Dry to Ultra Wet. Worked out from the target, never stored; see *Watering targets*. |
| Watering volume | Milliliters per dose. |
| Lights on at, hours | When this plant's stretch of strip comes on, and for how long. The card and editor show when it goes off; nothing stores a stop time. |
| Brightness | 0–100% for this plant's stretch of strip. Low 25%, Medium 50%, High 75%, Intense 100%. |

That is a change in direction worth knowing about. Previously the only way to
write a plant profile was `POST /plants/{id}/profile`, which snapshots a pot — so
fixing a plant profile meant loading it onto a spare pot, editing, and saving
back, which changes what the planter is actually running in order to edit
something it is not. Both paths still exist and write the same entry; there is
a test asserting they agree field for field, since two editors that validate
differently would fill the library with entries that load badly.

A plant card no longer edits care settings at all. It picks a plant profile and
loads it, picks a soil, and sets the pot's own geometry. Those pot fields
**save themselves** a moment after the last edit, so the card stores geometry
and nothing else — saving used to also write a profile as a side effect, so you
could not store a rail coordinate without saving a plant.

Two kinds of edit are deliberately held back rather than sent: a blank watering
position, because an empty box reads as 0 mm and would park the nozzle at the
left end of the rail; and a sweep whose span is not yet wide enough to be one,
because the API refuses it and the card is usually still being filled in. Both
say so on the card.

Each plant profile and each soil also carries **notes**: free text, and the only
field the planter never acts on. The numbers say what it does; the note says
why, which is the part nobody remembers a season later. The soil library's
recipes are carried this way.

**Nothing describing the pot's placement is part of a plant profile** -- not
the watering position, the watering mode or its sweep bounds. If the position
traveled, loading one plant onto a second pot would give both the same rail
coordinate and watering one would dribble into the other.

The soil is different: a plant profile names the soil profile the plant
*prefers*, and loading it **switches the pot to that soil profile**, since you
pot a plant in the mix it wants. If the pot is later given a different soil
profile, its card says the plant prefers another and offers to switch back.
Clearing a plant profile leaves the pot's soil profile alone: the mix is still
in the pot.

Stored in `data/state.json` under `plant_profiles`, alongside the rest of the
settings.

### Watering modes

A pot either takes its dose in one place or has it swept across a span:

```bash
curl -X POST http://herman.local/api/v1/plants/plant_1/sweep -H 'Content-Type: application/json' -d '{"sweep_min_mm":120,"sweep_max_mm":320}'
curl -X POST http://herman.local/api/v1/plants/plant_1/watering-mode -H 'Content-Type: application/json' -d '{"watering_mode":"sweep"}'
```

The span goes first, because switching a pot to `sweep` is refused while its
span is narrower than 10 mm. The two are separate settings, so the alternative
is a pot labeled "sweep" that waters as a point for ever — configured for
something it never does.

**The sweep's passes replace the pump's dwell, and that is forced rather than
chosen.** A dose is one gcode block — pin on, time passes, pin off — and the
`G4` that times it blocks Klipper's queue, so moves sent from another thread
during a dose would run *after* the pump stopped rather than during it. The
passes have to be the timer, inside the same script.

Which makes travel time into dose time, and puts acceleration in the maths. A
pass is not distance over speed: the carriage ramps up and down at every
reversal, and at fifty reversals that is not a rounding error. So
`greenthumb/sweep.py` models each pass as the trapezoid Klipper will actually
run — using `max_velocity` and `max_accel` queried from Klipper, never a second
copy in `.env` — and then solves the feedrate backwards from the dose.

One property outranks the rest: **the motion must never outlast the dose**,
because the pump stops when the passes finish. An overrun does not show up as a
wrong number on a screen; the pot overflows. It is enforced by dropping a pass
until the plan fits, rather than inferred from the arithmetic, since the
feedrate has to go out as a whole number of mm/min and that rounding can land
below the speed that was solved for.

A sweep that cannot honor the dose falls back to watering at the pot's point
position, with the reason logged — a dose too small to cross the span, a span
that has fallen off a re-measured rail, or Klipper not reporting its motion
limits. The plant still drinks either way: the sweep decides how the water is
spread, not whether it arrives.

The mode and the two bounds are **not** part of a plant profile, for the
same reason `position_mm` is not. They are rail coordinates, so they cannot
travel between pots, and a profile carrying the mode without them would load as
a sweep over a span of zero.

### Soils

Each pot records which mix it is filled with, chosen from a soil library that
works the same way as the plant profiles — name as the key, overwrite on save:

```bash
python -m greenthumb.soil_library              # read them and the figures
python -m greenthumb.soil_library --install    # add them to the library
python -m greenthumb.soil_library --install --overwrite   # and discard your edits
```

**Why the soil is recorded at all is a sensor argument before an agronomic
one.** A capacitive probe reads dielectric permittivity, and texture, organic
matter, bulk density and salinity all shift that relationship — so two
identical probes in two different mixes genuinely disagree. Without the mix
written down, that spread looks like sensor variation.

**A soil profile's working figures are one sensor reading and two
percentages**: its field capacity reading (what a probe reads in that soil
soaked and drained 24 hours), and the mix's field capacity and wilting point as
% volumetric water content, the table below. Every pot using the soil profile is
read between field capacity and wilting point — see *Watering targets* below.

Wilting point is not measured. Each pot estimates it from its field capacity
reading and its probe's air reading, counted as 0% water. It is placed the
same fraction of the way up as the mix's wilting point % is of its field
capacity %. A soil profile can hold a measured wilting point reading instead,
which then wins over the estimate.

**Three soil profiles ship, and no others** — three soilless recipes made from
hardware-store ingredients that between them cover every plant this planter is
meant for. **[SOIL_PROFILES.md](SOIL_PROFILES.md)** has the recipes, the
figures, which plants go in which, and how to take the field capacity reading.

| Soil profile | For | Field capacity | Wilting point |
|---|---|---|---|
| Rich & Retentive Mix | vegetables, herbs, thirsty tropicals | 45–55% VWC | 15–20% |
| Fast-Draining Mix | cacti, succulents, woody herbs | 20–30% VWC | 6–10% |
| Ultra-Coarse Epiphytic Mix | orchids, aroids, jungle epiphytes | 12–18% VWC | 3–5% |

The midpoint of each range is stored on the soil profile, and the full recipe,
ranges and plant list are in its note in the editor.

Every batch comes out a little different with the brand of potting mix and how
firmly it is packed, and mixes **lose capacity as they age and compact** — so
re-measure field capacity after a repot rather than trusting the old reading.

### Setting a soil profile's field capacity reading

The three built-in soil profiles ship with a default field capacity reading,
taken on the reference build with each recipe mixed as written, so a new
planter can water as soon as each pot has a soil profile. Take the probes' air
readings too (Calibration → Moisture probes → Calibrate dry), since each pot's
wilting point is estimated up from its own probe's.

To replace a default with your own, or set one on a soil profile you added,
go to the Soil Profile Editor on the Plants and Soil tab. Either type the
reading in, or soak a pot of the mix through, let it drain 24 hours, pick that
pot's probe and press Measure field capacity.

```bash
curl -X POST "http://herman.local/api/v1/soils/Rich%20%26%20Retentive%20Mix/field-capacity" \
  -H 'Content-Type: application/json' -d '{"plant_id":"plant_2","seconds":20}'
```

**Optional: a measured wilting point.** The estimate errs slightly wet, so a
pot is watered a little late rather than early. To replace it, use a pot of the
mix with no plant. Weigh it at field capacity and work out how much water it
holds at wilting point from the mix's % figures and the pot's volume. Let it
dry until it has lost the rest, then press Measure wilting point with the same
probe (or `POST .../wilting-point`). Clear the field to go back to the
estimate.

**Once per soil profile, not once per pot.** Probes of the same kind read
closely enough that one good figure beats four nobody got round to taking, so
the reading serves every pot using that soil profile, and moving a pot to
another soil profile moves it onto that one's scale. There is deliberately no
per-pot override: one figure per soil profile is far easier to reason about.

**A pot without a field capacity reading reads -1 and is never watered
automatically**, the same as an unplugged probe. So does one whose soil profile
has neither its % figures nor a wilting point reading. The card and the status
bar say what is missing. There is deliberately no fallback for field capacity:
a placeholder would give a pot a plausible percentage against a number nobody
took, which is the one error in this system that nothing downstream can catch.

An unknown soil profile name is refused rather than stored on a pot.

**Add your own** in the Soil Profile Editor, or over the API. Only the name is
required, so a profile can be saved first and measured later; watering needs
the field capacity reading and the % pair (or a wilting point reading in place
of the pair). Readings left out keep what is stored, and `null` clears one:

```bash
curl -X POST http://herman.local/api/v1/soils -H 'Content-Type: application/json' \
  -d '{"name":"My potting mix","field_capacity_vwc":40,"wilting_point_vwc":14,"field_capacity_raw":820}'
```

A soil profile takes a note too, for where its figures came from. Saving
replaces any soil profile of that name; a % pair must be given whole or not at
all, and wilting point must read below field capacity.

## Watering targets

A pot's reading is turned into **soil water**, the share of the water a plant
can use that is left: 100% at its soil profile's field capacity reading, 0% at
its wilting point (estimated, or the soil profile's reading).

`soil water % = (reading − wilting point) ÷ (field capacity − wilting point)`

**A plant is watered once its pot's soil water drops to its target**, a whole
percentage from 10 to 90. Because the target is a share of whatever the pot's
own soil holds, one target means the same thirst in any mix. Targets used to
be % VWC, which only fitted the soil they were written for: 25% VWC was fairly
dry in Rich & Retentive Mix and more than Ultra-Coarse Epiphytic Mix can hold
at all. The card shows the pot's soil water beside its target.

The **water level** names a percentage in words: a plant's target in its
profile, and a pot's live reading on its card. It is always worked out by this
key, eight equal slices of the scale, and never stored, so changing the key
relabels everything:

| Water level | Soil water |
|---|---|
| Ultra Wet | 88–100% — just watered |
| Very Wet | 76–87% |
| Wet | 63–75% |
| Medium-Wet | 51–62% |
| Medium-Dry | 38–50% |
| Dry | 26–37% |
| Very Dry | 13–25% |
| Ultra Dry | 0–12% — close to wilting point |

The library's targets were converted from the source table's % VWC through
each plant's preferred soil, so each waters where it did in that soil. See
`greenthumb/plant_library.py` for the four that were chosen by hand.

**How far to trust the estimated wilting point.** Soil reads a little above
air even bone dry, and capacitive probes are not perfectly linear. Both put
real wilting point slightly above the estimate, so a pot reads a little wetter
than it is and is watered a little late, never early. Measuring wilting point
by weight removes that, but it is slow; for most plants, raising the target a
couple of points does the same job.

**A pot whose moisture cannot be worked out is never watered automatically**
— no soil profile, no field capacity reading, a soil profile without its two %
figures, or an unreadable probe. "Cannot say" must not collapse into "bone
dry", or an unplugged probe would read as the thirstiest plant on the rail. The
card and status bar say what is missing. Manual watering is unaffected.

### The plant library

99 plant profiles ship in five categories: culinary herbs and kitchen
greens, indoor vegetables and crops, flowering bulbs and ornamentals, common
houseplants, and succulents, cacti and epiphytes. Each
names its preferred soil profile, watering target, water level, hours of light
and light intensity. The dropdowns group them by
category.

```bash
python -m greenthumb.plant_library              # list them
python -m greenthumb.plant_library --install    # add them to the library
```

Installing keeps any entry you have already tuned; `--overwrite` replaces them.

Two things the source table does not give are filled in the same for every
plant: a **100 mL** dose (it depends on the pot more than the plant) and lights
on at **07:00** (the longest photoperiod, 15 h, then ends at 22:00). Change
either per plant in the Plant Profile Editor.

## Hardware assumptions

The code is written to be easy to adapt to the actual hardware stack:

- Klipper is the motion layer running on the BTT SKR Mini E3 V2 or V3, each
  with its own firmware in `deploy/klipper/`
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
readings per plant, and waters a plant once its soil water drops to its target.
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
| Watering check | Real — each dose is confirmed from the pot's own moisture probe; see HOW_WATERING_WORKS.md |
| Camera | API only — Camera Module 3 Wide via rpicam-vid, MJPEG over HTTP. An optional add-on, with no UI and no timelapse |

Automatic watering is disabled by default. Turn it on with **Water plants
automatically** in the Automation tab; the choice persists across restarts.
`AUTO_WATERING_ENABLED` only sets the value a planter starts life with, and a
saved choice overrides it.

Enable it only after measuring the pump's flow rate, since that figure is what
converts a requested volume into a pump run time.

### Measuring the pump flow rate

Calibration → Pump. Press **Run calibration**, weigh what comes out, and type
the milliliters in; the planter divides by the run it timed itself. This is the
only control in the app that runs the pump directly -- watering a plant asks for
a measured volume, so it stays on the Controls tab.

```bash
curl -X POST http://herman.local/api/v1/pump/run
curl -X POST http://herman.local/api/v1/pump/calibrate -H 'Content-Type: application/json' -d '{"measured_ml":72}'
curl http://herman.local/api/v1/pump                     # the rate in use, and when it was measured
```

Asking for the volume rather than the rate is deliberate: the figure in front
of someone is a reading off a scale, and a rate they worked out themselves is a
rate with their arithmetic in it. The run length comes from a monotonic clock
rather than the wall clock, because the Pi has no RTC and an NTP sync landing
mid-run would otherwise corrupt the divisor.

**It is calibration, so it lives in `data/state.json`, not `.env`.**
`PUMP_FLOW_ML_PER_SECOND` is only the value a planter starts life with; once
measured, the stored figure wins. That means it survives a reflash with the
rest of the hand-tuned values, and `measured_at` being empty is how the UI
knows to warn that a planter is still dosing off a datasheet number.

A measurement that could not be real is refused rather than stored — a run
under 20 s (too little water to weigh to the gram), or a volume that works out
to a rate outside 0.05–20 mL/s, which is the misplaced decimal. This is the one
error nothing downstream can catch: it scales every dose by the same factor and
still reports success.