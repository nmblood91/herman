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
| `/plants/...` | per-plant name, light window, moisture target, dose volume, rail position, watering mode and sweep span, and move-to |
| `/plant-profiles`, `/plants/{id}/profile` | the saved-plant library: list, read one, write one from a body, snapshot a pot, load onto a pot, delete |
| `/soils`, `/plants/{id}/soil` | the soil library — list, add, remove — and which mix a pot is filled with |
| `/moisture-bands` | the band scale, for pickers and legends |
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

**A saved plant is edited in its own right**, in the plant editor on the Plants
and Soil tab, or over the API:

```bash
curl -X POST http://herman.local/api/v1/plant-profiles -H 'Content-Type: application/json' \
  -d '{"name":"Basil","moisture_target":"dry","watering_volume_ml":120,"light_start_time":"07:30","light_stop_time":"21:00","notes":"South window, dries fast in summer."}'
curl http://herman.local/api/v1/plant-profiles/Basil
```

That is a change in direction worth knowing about. Previously the only way to
write a saved plant was `POST /plants/{id}/profile`, which snapshots a pot — so
fixing a saved plant meant loading it onto a spare pot, editing, and saving
back, which changes what the planter is actually running in order to edit
something it is not. Both paths still exist and write the same entry; there is
a test asserting they agree field for field, since two editors that validate
differently would fill the library with entries that load badly.

A plant card no longer edits care settings at all. It picks a saved plant and
loads it, picks a soil, and sets the pot's own geometry. Those pot fields
**save themselves** a moment after the last edit, so the card stores geometry
and nothing else — saving used to also write a profile as a side effect, so you
could not store a rail coordinate without saving a plant.

Two kinds of edit are deliberately held back rather than sent: a blank watering
location, because an empty box reads as 0 mm and would park the nozzle at the
left end of the rail; and a sweep whose span is not yet wide enough to be one,
because the API refuses it and the card is usually still being filled in. Both
say so on the card.

Each saved plant and each soil also carries **notes**: free text, and the only
field the planter never acts on. The numbers say what it does; the note says
why, which is the part nobody remembers a season later. The starter libraries
have always carried this text in `plant_library.py` and `soil_library.py` — it
was discarded on install until now, so the reasoning stayed in the source and
never reached anyone reading the library in the app.

**Nothing describing the pot is part of a saved plant** -- not the watering
location, not the watering mode or its sweep bounds, and not the soil. A saved
plant is care settings, and loading one onto a pot must not assert physical
facts about a pot nobody touched.

The watering location is the obvious case: if it travelled, loading one plant
onto a second pot would give both the same rail coordinate and watering one
would dribble into the other.

The soil is the one that looks arguable, since you usually *do* repot when you
set a pot up for a different plant. But the two ways of being wrong are not
symmetrical. If the soil stays and you did repot, you pick the mix again from a
dropdown you are already looking at. If the soil travelled and you did not, the
pot silently bands every reading against the wrong wilting point and waters to
it -- and nothing about that looks broken.

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
is a pot labelled "sweep" that waters as a point for ever — configured for
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

A sweep that cannot honour the dose falls back to watering at the pot's point
position, with the reason logged — a dose too small to cross the span, a span
that has fallen off a re-measured rail, or Klipper not reporting its motion
limits. The plant still drinks either way: the sweep decides how the water is
spread, not whether it arrives.

The mode and the two bounds are **not** part of a saved plant profile, for the
same reason `position_mm` is not. They are rail coordinates, so they cannot
travel between pots, and a profile carrying the mode without them would load as
a sweep over a span of zero.

### Soils

Each pot records which mix it is filled with, chosen from a soil library that
works the same way as the saved plants — name as the key, overwrite on save:

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

A soil entry holds field capacity and wilting point as volumetric water
content. **Only their ratio transfers**: it is dimensionless, so a published
figure applies to any pot of that mix, and it is what says where the bottom of
the usable range sits. The absolute figures do *not* convert into raw sensor
counts — that needs a response curve for the specific medium — which is why
field capacity is also **measured** per mix, in raw sensor counts, from a real
pot. The published figures supply the *shape* of the usable window; the
measurement supplies its *position* on the scale a probe reports.

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
holds measurably more than the same mix after a season — so re-measure after a
repot rather than trusting the old figure.

### Measuring a mix's field capacity

Plants and Soil → Soils. Soak a pot of the mix through, let it drain 24 hours,
pick which pot's probe to read it with, and press Measure.

```bash
curl -X POST http://herman.local/api/v1/soils/Coco%20coir/field-capacity \
  -H 'Content-Type: application/json' -d '{"plant_id":"plant_2","seconds":20}'
```

**Once per mix, not once per pot.** Probes of the same kind read closely enough
that one good figure beats four nobody got round to taking, so the result is
copied onto every pot filled with that mix. A pot that disagrees can measure
its own on its card, which overrides the mix's for that pot; assigning a
different mix drops the override, since a reading taken in coir says nothing
about cactus mix.

**This moved off the probe, and the old per-address wet endpoint is gone.** It
recorded a wet reading with no note of which mix it was taken against, so two
pots of different soil wanted different figures and there was nowhere to put
them. Files written by older builds keep their `wet` keys; they are never read
and never rewritten. Nothing is migrated, because there is no honest derivation
— the old figure could have been taken in any mix, and the pot may have been
repotted since.

**A pot with no field capacity reads -1 and is never watered automatically**,
the same as an unplugged probe. The status bar names the mixes and pots waiting
on a measurement. There is deliberately no fallback: a placeholder would give
an unmeasured pot a plausible percentage against a number nobody took, which is
the one error in this system that nothing downstream can catch.

An unknown soil name is refused rather than stored, since a mix that is not in
the library supplies no ratio and would read as "set" while behaving exactly
like "not set".

**Add your own mix** in the Soils panel on the Plants and Soil tab, or over the API:

```bash
curl -X POST http://herman.local/api/v1/soils -H 'Content-Type: application/json'   -d '{"name":"My potting mix","field_capacity_vwc":30,"wilting_point_vwc":14}'
```

A soil takes a note too, for where its figures came from.

Saving replaces any soil of that name. Figures that cannot support a ratio are
refused rather than stored: one that saved happily and then yielded no ratio
would behave exactly like no soil at all, so the pot would read as configured
and never be watered.

A measured mix beats a looked-up one, and the measurement needs only a kitchen
scale: weigh the pot soaked and drained 24 hours, weigh it again bone dry, and
the difference is the water it holds. That matters because bagged mixes vary by
manufacturer and by packing, and lose capacity as they age.

## Moisture bands

A plant is watered when its pot reaches a **band**, not a percentage:

| Band | Depletion of plant-available water |
|---|---|
| very wet | 0-10% — just watered |
| wet | 10-30% |
| medium | 30-50% |
| **dry** | **50-75% — the conventional watering trigger** |
| very dry | 75-100% — near the limit of what roots can pull out |

The percentage is still kept and still charted — the *rate* of drying says more
than the level, because it follows light, temperature and growth stage on its
own where a fixed threshold cannot. The band is what a target is expressed in.

**Bands are computed per soil, which is the point.** The bottom of the usable
range is wilting point, and that sits at about 27% of field capacity for coco
coir but 57% for a peat mix. So the same reading means different things: 80% is
*medium* in peat and *wet* in coir. A fixed table of thresholds would put half
of coir's bands below wilting point and squash a peat pot's into two.

**Why bands rather than the number.** On a peat mix the whole actionable range
is the top 43% of the scale, and the step from comfortable to needing water is
about eight points of a 0-100 display. A few percent of calibration error moves
you two bands. A percentage invites reading precision the sensor cannot
deliver; a band states the decision and hides a distinction the hardware cannot
make.

Readings hold their band until one clears a boundary properly, so a value
parked on a threshold does not relabel on every poll.

**A pot with no soil set is never watered automatically.** Without the mix
there is no wilting point, so a reading cannot become a band at all — and
"cannot say" must not collapse into "very dry", or an unplugged probe would
read as the thirstiest plant on the rail. The status bar names any pot in that
state. Manual watering is unaffected.

### Starter profiles

Five common plants ship as a starting library, ordered by when they want water:
Lettuce (medium), Peace Lily and Basil (dry), Pothos and Snake Plant (very
dry).

```bash
python -m greenthumb.plant_library              # read them and why
python -m greenthumb.plant_library --install    # add them to the library
```

Installing keeps any entry you have already tuned; `--overwrite` replaces them.

**The photoperiods are researched; the targets are bands for a reason.** No
horticultural source publishes a sensor percentage, because the number depends
on the probe and the mix. What the literature describes is behaviour — "let the
top inch dry", "let it dry out completely" — and a band is the closest honest
expression of that. Several plants sharing a band is honest too: the research
does not separate basil from lettuce to within a few percent.

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
readings per plant, and waters a plant once its band is drier than its target.
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
automatically** in the Automation tab; the choice persists across restarts.
`AUTO_WATERING_ENABLED` only sets the value a planter starts life with, and a
saved choice overrides it.

Enable it only after measuring the pump's flow rate, since that figure is what
converts a requested volume into a pump run time.

### Measuring the pump flow rate

Calibration → Pump. Press **Run calibration**, weigh what comes out, and type
the millilitres in; the planter divides by the run it timed itself. This is the
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