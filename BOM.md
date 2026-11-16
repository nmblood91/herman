# Herman Bill of Materials (Initial Prototype / Production Planning)

Parts, quantities and cost. Prices are per planter at prototype quantities —
what one unit costs to build today, not a volume quote.

**Most unit prices are `TBD`.** They get filled in from real invoices rather
than estimated, the same way [PRINTED_PARTS.md](PRINTED_PARTS.md) was. A line
with a `TBD` unit price has a `TBD` line total, and any section containing one
cannot be subtotalled yet.

## Cost summary

| Section | Priced so far | Lines still to price |
|---|---|---|
| Core structure | $156.00 | complete |
| Printed parts — filament | $15.41 | complete — 1,284 g at $12 per kg |
| Printed parts — fasteners and inserts | $21.19 | complete |
| Motion and control | $43.00 | 1 — wiring harness |
| Compute and monitoring | $40.00 | complete for the base build |
| Sensing | $61.00 | complete |
| Watering system | $45.00 | complete |
| Lighting | $10.00 | 2 — hook-up wire, connectors |
| Power and electronics | $14.00 | 8 — fuses, fuse holders, wire, heat shrink |
| **Running total** | **$405.60** | **11 lines outstanding** |

Close to final. The frame, motion, compute and sensing are all fully costed.
What is left is small electrical hardware — three fuses and their holders,
wire, connectors and heat shrink. Call it another $25, which puts a finished
prototype around **$431**.

Two lines carry no cost on purpose. The reservoir is bring-your-own, and
there is no bought nozzle — the tube is held by a printed part.

The **webcam add-on is $20 on top** and is deliberately in none of the totals
above, since it is sold as an upgrade rather than built into every unit. It
needs a printed mount that does not exist yet, so budget that separately.

## Core structure

| Item | Qty | Unit | Line total | Notes |
|---|---|---|---|---|
| IKEA VITTSJÖ frame | 1 | $80.00 | $80.00 | as-is; includes both shelves |
| 2020 aluminium extrusion rail, 1000 mm | 1 | $50.00 | $50.00 | VBX.com; comes with the gantry plate. 890 mm usable travel |
| T nuts | 4 | $0.50 | $2.00 | to secure rail |
| GT2 belt | 1 | $4.00 | $4.00 | roughly twice the rail plus pulley wrap, so about 2.1 m |
| GT2 drive pulley | 1 | $2.00 | $2.00 | motor end |
| GT2 idler pulley | 3 | $2.00 | $6.00 | ride on the shoulder bolts in the gantry holder fronts |
| NEMA 17 stepper motor | 1 | $10.00 | $10.00 | right-hand gantry holder |
| Belt tensioner block | 1 | $2.00 | $2.00 |  |

## Printed parts

Weights, heat-set inserts, screws and their costs are tracked in
**[PRINTED_PARTS.md](PRINTED_PARTS.md)** — 17 parts at 1,284 g, plus $21.19 of
fasteners across 122 pieces. Covers the gantry holders and covers, the V-slot
adapter, the two gantry faces, the electronics holder, the STEMMA QT sub hubs
and the cable chain anchor. The chain itself is bought, under the watering
system.

## Motion and control

| Item | Qty | Unit | Line total | Notes |
|---|---|---|---|---|
| BTT SKR Pico | 1 | $40.00 | $40.00 | TMC2209 drivers are **embedded**, not a separate purchase; often cheaper on Alibaba |
| Wiring harness and JST/XH connectors | TBD | TBD | TBD |  |
| Mechanical limit switch, X homing | 1 | $3.00 | $3.00 | wired normally-closed |

The limit switch is wired normally-closed. Printer endstop modules are usually
sold 3-pin; one wire comes off — see [deploy/README.md](deploy/README.md) for
which.

Motion power and fuse protection live in *Power and electronics* rather than
being duplicated here; there is one 12 V supply for the whole machine.

## Compute and monitoring

| Item | Qty | Unit | Line total | Notes |
|---|---|---|---|---|
| Raspberry Pi 3 Model A+ | 1 | $30.00 | $30.00 | production target; allow +$20 for a larger board or a price rise |
| MicroSD card | 1 | $10.00 | $10.00 |  |
| Webcam | 1 | $20.00 | $20.00 | **optional — future roadmap** |

**Base subtotal $40.00**, the webcam excluded as an add-on. The Pi is powered
from the SKR Pico's own 5 V regulator, so there is no separate step-down to
buy; see [deploy/SKR_PICO.md](deploy/SKR_PICO.md).

**Production target: Raspberry Pi 3 Model A+.** Chosen on cost. Same BCM2837B0
and 1.4 GHz quad A53 as the 3 B+, dual-band WiFi, and the same 40-pin pinout —
so nothing about the wiring changes. What differs: 512 MB RAM, a single USB-A
port, no Ethernet, and a smaller 65 × 56 mm board with the same mounting
pattern. See the hardware notes in [ROADMAP.md](ROADMAP.md) for the
two things still to validate before this is locked.

**Boards to test, highest to lowest.** Each step answers whether the stack
still fits as RAM and ports come off:

| Board | RAM | What it adds to the test |
|---|---|---|
| Pi 4 (1 GB) | 1 GB | development board; every measurement so far is from here |
| Pi 3 B | 1 GB | the 3 B+ without dual-band WiFi, BT 4.2 or gigabit Ethernet — none of which this uses |
| Pi 3 B+ | 1 GB | same 85 × 56 mm outline and mounting holes as the Pi 4 |
| Pi 3 A+ | 512 MB | the production target, and the only one that tests anything new |

The A+ is the one that matters: the only 512 MB board and the only one
without Ethernet. **If the
on-device frontend build fits on the A+, it fits on everything above it** — so
test that first rather than working down the list.

**The A+ is in production until at least January 2030**, per Raspberry Pi's
own obsolescence statement. Worth having written down, because several retailer
listings still show the older January 2026 date, and that would mean the board
was already past its declared window. It is not. Nothing is forcing a change.

**Not worth it: Pi Zero 2 W.** It is hard to buy at list price, saves only
about $10 a unit, and needs a mounting pattern of its own. Revisit if supply
normalizes *and* volume makes that saving worth a second chassis.

**Not suitable at all:** Pi Zero / Zero W and any ARMv6 Pi. No 64-bit, and
NodeSource ships no ARMv6 packages — though note that second objection
disappears once the frontend ships prebuilt, since no Node runs on the device
at all. What remains is the disqualifier: one ARMv11 core at 1 GHz shared
between the Klipper host, the API and nginx, and Klipper's host loop is
latency-sensitive.

## Sensing

| Item | Qty | Unit | Line total | Notes |
|---|---|---|---|---|
| Capacitive soil moisture sensor (Adafruit STEMMA) | 4 | $9.00 | $36.00 | one per plant; its cable is the line below |
| STEMMA QT cable, 200 mm | 4 | $2.00 | $8.00 | each sensor to its sub hub |
| STEMMA QT (Qwiic) to Dupont header cable, 200 mm | 1 | $2.00 | $2.00 | the branch hub to the Pi's header pins |
| STEMMA QT 5-port passive hub | 3 | $3.00 | $9.00 | two sub hubs over the plants, and a branch hub in the electronics box |
| STEMMA QT cable, 500 mm | 2 | $3.00 | $6.00 | each sub hub to the branch hub |

**Three hubs.** A left and a right sub hub hang over the plants on the front
rail, feeding two sensors each over 200 mm cables. Each runs 500 mm back to a
branch hub in the electronics box, and 200 mm joins that to the Pi. Keeping
the bus off the back rail takes it away from the stepper, the pump and the LED
data line; see [SENSOR_WIRING.md](SENSOR_WIRING.md).

Three sensor address pads (A0/A1) give the sensors unique I2C addresses; those
are solder pads on the sensors rather than a purchased part.

## Watering system

| Item | Qty | Unit | Line total | Notes |
|---|---|---|---|---|
| 12 V peristaltic pump | 1 | $30.00 | $30.00 | not tapped — mounts on M3 inserts |
| Reservoir | 1 | BYO | — | top-loaded; a Nalgene works |
| Tubing and barb fittings | 1 set | $5.00 | $5.00 | |
| Cable chain, S10, 1 m | 1 | $10.00 | $10.00 | Amazon; carries the tube to the carriage. Moving end takes 2 × M4×8 into the V-slot adapter, fixed end sits in the printed anchor. Was printed — see [ROADMAP.md](ROADMAP.md) |

**There is no bought nozzle.** The tube dribbles straight out, held by the
lower gantry face — which PRINTED_PARTS.md already calls the nozzle holder and
already weighs at 50 g. So the delivery end costs nothing beyond the tube, and
it is a printed part rather than a purchased one.

The reservoir is whatever you have to hand. With a top-loaded tank, feed the
tube through a hole in the lid rather than over the rim — the rim crossing is
a high spot in a suction line.

A stopped peristaltic pump already occludes the tube, so there is no check
valve to add.

The nozzle must sit above the reservoir water line. Vertical order is nozzle,
then pump, then reservoir — see [deploy/README.md](deploy/README.md) for why,
and what goes wrong if it is inverted.

## Lighting

| Item | Qty | Unit | Line total | Notes |
|---|---|---|---|---|
| Addressable LED strip, WS2811 12 V, 1 m at 60 LEDs/m | 1 | $10.00 | $10.00 | 3 LEDs per pixel — see note |
| Hook-up wire, LED runs | TBD | TBD | TBD | power and data out to the strip |
| Connectors | TBD | TBD | TBD |  |

Buy it at **60 LEDs per meter**, and use 1 m of it: the length of the table.
The app works out the pixel count from the strip type on that basis, so a
denser or sparser strip splits into zones of the wrong length unless
`LED_COUNT` is set in `.env`. WS2811 is the default and drives three LEDs per
pixel, so it is 20 pixels. WS2815 and GS8208 are also supported and are one
pixel per LED, so 60. All three are 12 V; no 5 V chip is
offered, since sixty 5 V pixels would pull about 3.6 A on top of the Pi.

Strip power comes off the same 12 V supply, and its data line runs straight
from the Pi with no level shifter.

## Power and electronics

| Item | Qty | Unit | Line total | Notes |
|---|---|---|---|---|
| 12 V power supply, 5 A min (7 A recommended) | 1 | $12.00 | $12.00 | the only supply in the build |
| Fuse, 5 A fast-blow | 1 | TBD | TBD | charger output into the busbar |
| Fuse, 1 A fast-blow | 1 | TBD | TBD | SKR HB to pump positive |
| Fuse, 2 A fast-blow | 1 | TBD | TBD | busbar to strip +12 V |
| Inline fuse holder, 16 AWG leads | 3 | TBD | TBD | one per fuse above |
| 1N5822 flyback diode, 3 A Schottky | 1 | $2.00 | $2.00 | **required**, see [POWER_SYSTEM.md](POWER_SYSTEM.md) |
| Wire, 14 AWG | TBD | TBD | TBD | charger to busbar, busbar to SKR |
| Wire, 18 AWG | TBD | TBD | TBD | LED strip and pump runs |
| Wire, 22 AWG | TBD | TBD | TBD | LED data and the Pi ground reference |
| Heat shrink, assorted | TBD | TBD | TBD | used throughout, not only on the LED runs |

**The busbar is the Wago connectors**, not a separate part — the two 5-slot
221s at the main electronics rear are the +12V and ground distribution point
that every "busbar" in [POWER_SYSTEM.md](POWER_SYSTEM.md) refers to. All four
Wagos are counted in [PRINTED_PARTS.md](PRINTED_PARTS.md), so there is no line
for them here. The diode and the pump leads land in the 3-slot pair rather
than being soldered to the pump terminals; see
[deploy/README.md](deploy/README.md).

**See [POWER_SYSTEM.md](POWER_SYSTEM.md) for full electrical specifications.**

## Software stack

- Klipper on Raspberry Pi
- Python FastAPI service
- Local dashboard
- Sensor and watering service logic

## UI

- Local web app served from the Pi, reached at `http://herman.local` on the
  same network. No cloud account, by design — see
  [PRIVACY_SECURITY_SPEC.md](PRIVACY_SECURITY_SPEC.md). There is no phone app
  yet; the one sketched in [ROADMAP.md](ROADMAP.md) is LAN-only too, and
  exists mainly to handle first-run WiFi setup
- A per-species plant profile library is a roadmap item, not a current part;
  plant definitions live in `greenthumb/plants.py` and only the user-editable
  fields persist
