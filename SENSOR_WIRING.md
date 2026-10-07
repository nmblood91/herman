# Moisture Sensor Wiring Guide

## Overview

Herman uses four Adafruit STEMMA soil moisture sensors, reached through three passive STEMMA QT hubs, on the Raspberry Pi's I2C bus 1. Each sensor reads capacitive moisture and temperature for one plant.

## Master Hub Connection to Raspberry Pi

The master hub connects to the Raspberry Pi's I2C Bus 1 using four wires:

| Wire Color | Function | Raspberry Pi Pin |
|-----------|----------|------------------|
| Black | Ground (GND) | Pin 6, 9, 14, 20, 25, 30, 34, or 39 |
| Red | 3.3V Power | Pin 1 or Pin 17 |
| Blue | SDA (Serial Data) | GPIO 2, Pin 3 |
| Yellow | SCL (Serial Clock) | GPIO 3, Pin 5 |

## Sensor Addressing

Each STEMMA soil sensor must be configured with a unique I2C address to prevent collisions on the shared bus. The default addresses are:

| Plant | Address | Hex |
|------|---------|-----|
| Plant 1 | 54 | 0x36 |
| Plant 2 | 55 | 0x37 |
| Plant 3 | 56 | 0x38 |
| Plant 4 | 57 | 0x39 |

Configure sensor addresses using the A0 and A1 address pads on each sensor according to the Adafruit STEMMA documentation.

## Sensor Hub Layout

Four 5-port passive hubs. The three that do the fan-out hang over the plants
on the **front** rail; the fourth sits at the electronics box and joins them
to the Pi.

| Hub | Where | Ports used | To |
|---|---|---|---|
| Left sub | front, over the plants | 3 of 5 | front master · two soil sensors |
| Right sub | front, over the plants | 3 of 5 | front master · two soil sensors |
| Front master | front, over the plants | 3 of 5 | both sub hubs · the junction hub |
| Junction | at the electronics box | 2 of 5 | the front master · the Pi |

**The hubs hang rather than lie flat.** Turned ninety degrees so they sit over
the plants, each sub hub ends up more or less above the two pots it serves,
which turns the sensor drops into short vertical runs instead of diagonals
across the shelf.

Two things to check once they are hanging, both consequences of putting a
bare board above a pot that gets watered:

- **Keep them out of the splash line.** The nozzle dribbles into the pot from
  the travelling carriage, and these hubs are unsealed PCBs with open JST
  sockets facing whichever way they are hung. Sitting over the rim or the gap
  between pots keeps the drop just as short as sitting over the soil, without
  putting the board under the water. Point the connectors sideways or down so
  nothing can pool in them.
- **Check carriage clearance across the full travel.** The gantry sweeps the
  whole rail now that it re-homes and runs routines on its own, so anything
  hanging into that path gets found eventually. Run a *Patrol* and watch it
  rather than trusting a static measurement.

**The junction hub is a junction, not a fan-out** — two ports used, and
nothing else hangs off it. It is there because joining two stock cables end to
end is easier than sourcing one long enough to span the whole path, and
splicing STEMMA QT is not something to volunteer for. Worth knowing before
anyone decides it looks redundant: the replacement is a single cable longer
than any in the kit.

**The bus never goes near the back rail.** That rail carries the stepper, the
pump and the LED data line, and running I2C alongside an 800 kHz LED data line
causes more trouble than cable capacitance ever will. The run from the front
master crosses over the plants and enters the **front** face of the
electronics box, so it never parallels any of it.

The hubs are passive, so this is still electrically **one** bus. Which sub hub
a sensor hangs off changes nothing about its address — that is set by the A0
and A1 pads on the sensor itself, and a sensor keeps its address wherever it
is plugged in.

What the chain does change is total capacitance, which is the sum of every
cable on the bus rather than the longest single run. That is why the clock is
slowed to 50 kHz and why the I2C runs are routed away from the motor, pump and
LED wiring. See [deploy/README.md](deploy/README.md) for the measurements and
the failure mode.

## Configuration

Set sensor addresses in `.env`:

```
MOISTURE_SENSOR_ADDRESSES=54,55,56,57
```

## Calibration

Raw capacitance readings only become a percentage once each sensor's dry and wet
endpoints are known. Measure them per sensor rather than globally: four sensors
in identical conditions read measurably differently — on this build they span
about 25 counts in open air — and one global pair puts that spread straight into
every reported percentage.

Two passes, in either order. Each samples every sensor for 20 seconds and takes
the median, so one bad read cannot skew the result:

```bash
cd /opt/greenthumb

# all four sensors in open air, clean and dry
.venv/bin/python -m greenthumb.hardware.soil_sensors --calibrate dry

# prongs in water
.venv/bin/python -m greenthumb.hardware.soil_sensors --calibrate wet

.venv/bin/python -m greenthumb.hardware.soil_sensors --show-calibration
```

> **Only the prongs go in the water, up to the marked line.** These boards are
> not waterproof. Submerging the PCB or the connector end destroys the sensor,
> and doing all four at once destroys all four.

Results are written to `data/state.json`, which is gitignored and survives both
restarts and `git pull`. Each endpoint is stored separately, so the wet pass can
be redone without losing the dry one, and a sensor with only one endpoint
measured uses the `.env` default for the other.

Both passes can also be run from the web UI, which is the same code path.

### Air and water measure the sensor, not the soil

Calibrating against air and water gives you the sensor's **full electrical
span**. It does not mean 0% is "needs water" and 100% is "saturated" — dry soil
will read somewhere around 30-40% and a well-watered pot perhaps 80%.

That is deliberate. Air and a cup of water are repeatable anywhere, including on
a production line; "soil the plant would want watering in" is not. The
consequence is that a plant's **moisture target is a number you tune by
observation**, not a physical quantity. The history chart in the Sensors tab exists for exactly that:
watch moisture against watering events over a few days and move the target until
the plant is being watered when you would have watered it.

### When it refuses to store a reading

The calibrator will not write a value it does not believe, and says why:

| Message begins | Cause |
|---|---|
| `No sensor answered at this address` | unplugged, wrong address, or a bus fault — run `--soak` |
| `Reading moved N points from the start of the run to the end` | still taking up water or coming to temperature; leave it and retry |
| `Readings are jumping around by N points` | the sensor is being moved, touching the container wall, or the bus is unreliable |
| `Wet reading X is only N points above…` | the wet pass ran with the sensor still in air, or it never reached the water |
| `Dry reading X is only N points below…` | the dry pass ran on a sensor that was still wet |

Each message names what was measured and what was expected, so the numbers tell
you whether it was marginal or nowhere near.

**Both quality limits scale with the reading**, because sensor noise does. A
budget that is comfortable at a dry reading of ~330 is about two and a half
times stricter at a wet ~800, so a fixed count would fail the wet pass on
nothing but arithmetic — which it did, at 54-64 points, while air passed at
6-13. Drift is measured between the first and second half of the run, and noise
as a 5th-to-95th percentile band so a single bubble or glitched read cannot veto
several hundred good samples.

Nothing is stored for that sensor, so a refused pass leaves the previous
calibration intact rather than half-overwriting it.

To start over:

```bash
curl -X POST http://localhost:8000/api/v1/sensors/calibration/reset
```

## Testing

Check sensor connectivity before running the app:

```bash
i2cdetect -y 1
```

This should show devices at the configured addresses (e.g., 0x36, 0x37, 0x38, 0x39).

Read sensor values via the API:

```bash
curl http://<pi-host>:8000/api/v1/sensors
```

Raw sensor readings will be returned. If a sensor cannot be read, the value will be `-1`.

### Single Sensor Testing

To test with just one sensor (e.g., 0x36 in Plant 1):

```
MOISTURE_SENSOR_ADDRESSES=54
```

The API will return `-1` for any sensor that fails to initialize or read.
