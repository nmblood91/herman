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
| Printed parts — filament | ~$30–36 | complete |
| Printed parts — fasteners and inserts | $18.95 | complete |
| Motion and control | $43.00 | 1 — wiring harness |
| Compute and monitoring | $40.00 | complete for the base build |
| Sensing | $69.00 | complete |
| Watering system | $35.00 | 2 — intake weight, level sensor |
| Lighting | $10.00 | 2 — hook-up wire, connectors |
| Power and electronics | $27.00 | 9 — fuses, fuse holders, level shifter, wire, heat shrink |
| **Running total** | **~$429–435** | **15 lines outstanding** |

Close to final. The frame, motion, compute and sensing are all fully costed.
What is left is small electrical hardware — three fuses and their holders, the
level shifter, wire, connectors and heat shrink — plus the intake weight and
the liquid level sensor. Call it another $25, which puts a finished prototype
around **$455**.

Two lines carry no cost on purpose. The reservoir is bring-your-own, and
there is no bought nozzle — the tube is held by a printed part.

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
**[PRINTED_PARTS.md](PRINTED_PARTS.md)** — 18 parts at 1,424 g, plus $18.95 of
fasteners across 108 pieces. Covers the gantry holders and covers, the V-slot
adapter, the two gantry faces, the electronics holder, the STEMMA QT sub hubs
and the water-tube cable chain.

## Motion and control

| Item | Qty | Unit | Line total | Notes |
|---|---|---|---|---|
| BTT SKR Mini E3 V2 control board | 1 | $40.00 | $40.00 | TMC2209 drivers are **embedded**, not a separate purchase |
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
| Pi Camera v2 or compatible CSI camera | 1 | TBD | TBD | **paid add-on, not base build** |

**Base subtotal $40.00**, the camera excluded as an add-on. The 12 V to 5 V
step-down that feeds the Pi is priced under *Power and electronics* with the
rest of the supply chain, so it is not counted twice here.

**Production target: Raspberry Pi 3 Model A+.** Chosen on cost. Same BCM2837B0
and 1.4 GHz quad A53 as the 3 B+, dual-band WiFi, the standard 15-pin CSI
camera connector, and the same 40-pin pinout — so nothing about the wiring or
the camera ribbon changes. What differs: 512 MB RAM, a single USB-A port
(the SKR takes it), no Ethernet, and a smaller 65 × 56 mm board with its own
mounting pattern. See the hardware notes in [ROADMAP.md](ROADMAP.md) for the
two things still to validate before this is locked.

**Boards to test, highest to lowest.** Each step answers whether the stack
still fits as RAM and ports come off:

| Board | RAM | What it adds to the test |
|---|---|---|
| Pi 4 (1 GB) | 1 GB | development board; every measurement so far is from here |
| Pi 3 B | 1 GB | the 3 B+ without dual-band WiFi, BT 4.2 or gigabit Ethernet — none of which this uses |
| Pi 3 B+ | 1 GB | same 85 × 56 mm outline and mounting holes as the Pi 4 |
| Pi 3 A+ | 512 MB | the production target, and the only one that tests anything new |

The A+ is the one that matters: the only 512 MB board, the only one without
Ethernet, and the only one with a different mounting pattern. **If the
on-device frontend build fits on the A+, it fits on everything above it** — so
test that first rather than working down the list.

A Pi 4 and a 3 B/3 B+ share mounting holes but **not** port positions: the
Pi 4 has two micro-HDMI jacks, USB-C power, and Ethernet and USB swapped.

**Deferred until after launch: Pi Zero 2 W.** On paper it works and it is
cheaper — the same Cortex-A53 and the same 512 MB as the A+, at 1 GHz rather
than 1.4. What defers it is the camera: it carries the narrow 22-pin CSI
connector instead of the standard 15-pin, so it needs a different ribbon and a
third mounting pattern. Not worth carrying that while the A+ is still unproven.
Revisit once the product has shipped.

**Not suitable at all:** Pi Zero / Zero W and any ARMv6 Pi — no 64-bit, and
NodeSource ships no ARMv6 packages.

The enclosure needs to carry both the A+ and a development board — different
outlines and different port faces, so plan for two mounting patterns rather
than one.

The camera is scoped to timelapse; the standard 15-pin ribbon fits both the A+
and the development boards. Live streaming is out of scope, see
[ROADMAP.md](ROADMAP.md).

## Sensing

| Item | Qty | Unit | Line total | Notes |
|---|---|---|---|---|
| Capacitive soil moisture sensor (Adafruit STEMMA) + cable | 4 | $12.00 | $48.00 | one per plant; price includes the sensor's own STEMMA QT cable |
| STEMMA QT 5-port passive hub | 4 | $3.00 | $12.00 | two sub hubs and a master on the front rail, plus a junction hub at the Pi |
| STEMMA QT cable, 300 mm | 1 | $3.00 | $3.00 | left sub hub to master |
| STEMMA QT cable, 400 mm | 2 | $3.00 | $6.00 | right sub hub to master, and master to the back hub |

**Four hubs.** The fan-out lives on the front rail with the plants — a left
and a right sub hub feeding two sensors each, into a front master — and a
fourth on the back rail joins that to the Pi. The back one is a junction
rather than a fan-out, which is cheaper than sourcing a single cable long
enough to span the whole path. Moving the bus off the back rail also takes it
away from the stepper, the pump and the LED data line; see
[SENSOR_WIRING.md](SENSOR_WIRING.md).

Three sensor address pads (A0/A1) give the sensors unique I2C addresses; those
are solder pads on the sensors rather than a purchased part.

## Watering system

| Item | Qty | Unit | Line total | Notes |
|---|---|---|---|---|
| 12 V peristaltic pump | 1 | $30.00 | $30.00 | not tapped — mounts on M3 inserts |
| Reservoir | 1 | BYO | — | top-loaded; a Nalgene works |
| Intake weight | 1 | TBD | TBD | only if dipping a tube from the top |
| Tubing and barb fittings | 1 set | $5.00 | $5.00 | sized to the level sensor's 0–13 mm range. **No anti-drip fitting on the falling leg** |
| Non-contact liquid level sensor | 1 | TBD | TBD | CQRobot CQRSENYW001 or similar |

**There is no bought nozzle.** The tube dribbles straight out, held by the
lower gantry face — which PRINTED_PARTS.md already calls the nozzle holder and
already weighs at 50 g. So the delivery end costs nothing beyond the tube, and
it is a printed part rather than a purchased one.

The reservoir is whatever you have to hand. With a top-loaded tank, feed the
tube through a hole in the lid rather than over the rim — the rim crossing is
a high spot in a suction line. The intake weight is what stops that tube
floating up and sucking air as the tank drains, so it is not optional on a
dipped setup.

**No anti-drip fitting on the outlet's falling leg.** The delivery check
depends on that section draining back between doses, which is exactly what an
anti-drip fitting prevents. A stopped peristaltic pump already occludes the
tube, so there is no check valve to add.

The nozzle must sit above the reservoir water line. Vertical order is nozzle,
then pump, then reservoir — see [deploy/README.md](deploy/README.md) for why,
and what goes wrong if it is inverted.

## Lighting

| Item | Qty | Unit | Line total | Notes |
|---|---|---|---|---|
| Addressable LED strip, WS2811 12 V | 1 | $10.00 | $10.00 | 3 LEDs per pixel — see note |
| Hook-up wire, LED runs | TBD | TBD | TBD | power and data out to the strip |
| Connectors | TBD | TBD | TBD |  |

WS2811 is the default and drives three LEDs per pixel, so `LED_COUNT` is a
third of the LEDs you can count on the strip. WS2815 and GS8208 are also
supported and are one pixel per LED. All three are 12 V; no 5 V chip is
offered, since sixty 5 V pixels would pull about 3.6 A on top of the Pi.

Strip power comes off the same 12 V supply, and the level shifter for its data
line is in *Power and electronics*.

## Power and electronics

| Item | Qty | Unit | Line total | Notes |
|---|---|---|---|---|
| 12 V power supply, 5 A min (7 A recommended) | 1 | $15.00 | $15.00 | the only supply in the build |
| DC-DC converter, 12 V to 5 V @ 3 A | 1 | $10.00 | $10.00 | Yipin hexa; this is what powers the Pi |
| Fuse, 5 A fast-blow | 1 | TBD | TBD | charger output into the busbar |
| Fuse, 1 A fast-blow | 1 | TBD | TBD | SKR HE0 to pump positive |
| Fuse, 2 A fast-blow | 1 | TBD | TBD | busbar to strip +12 V |
| Inline fuse holder, 16 AWG leads | 3 | TBD | TBD | one per fuse above |
| 1N5822 flyback diode, 3 A Schottky | 1 | $2.00 | $2.00 | **required**, see [POWER_SYSTEM.md](POWER_SYSTEM.md) |
| 74AHCT125 level shifter | 1 | TBD | TBD | LED data line |
| Wire, 14 AWG | TBD | TBD | TBD | charger to busbar, busbar to SKR and DC-DC |
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

## Notes

This BOM is a functional starting point for a prototype and product planning.
A production version should include manufacturing-ready connectors, safety
certifications, and reliability checks for pump cycle life, moisture
calibration drift, and product enclosure durability.
