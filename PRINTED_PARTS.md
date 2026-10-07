# Herman Printed Parts

Every printed part in the build, what holds it together, and what it weighs.

Weight is here because it is the one number that turns into money at volume:
filament cost per unit is weight times spool price, and it is also what decides
whether a part is worth redesigning. Inserts and screws are here because they
are the parts that get ordered in the wrong size, and because a part that has
already been printed cannot be re-tapped for a different insert.

**One planter is 1,424 g of printed parts**, everything but the camera mount.
At typical PETG pricing that is roughly $30–35 of filament per unit, which is
enough to be worth watching — three parts are 44% of it: the main electronics
rear at 270 g, the right gantry holder rear at 205 g, and the cable chain at
150 g, which is 50 links of 3 g rather than one big part.

## Conventions

- **Weight** — the printed part on a scale, supports and brim removed, in
  grams. **Plastic only**: no inserts, no screws, and none of the hardware the
  part carries. The right-hand gantry parts are heavier than the left because
  of the plastic needed to mount a motor, an endstop and the pump, not because
  any of those are on the scale.
- **`0` versus `—`** — `0` means the part genuinely takes none of that
  fastener. `—` means the part does not exist yet, so the answer is unknown
  rather than zero. Only the camera mount uses `—`.
- **Heat-set inserts** — count × thread, then the length. `long` and `short`
  are the working shorthand; the real dimensions are not written down here
  because the inserts ship as a kit from the store rather than being sourced
  by the builder. See *Open items*.
- **Screws** — count × thread × length: `4 × M4×16`. Head type is the column
  it sits in.
- **Wago** — lever connectors, by slot count. These are the method for
  component terminals throughout this build, not an alternative to soldering;
  see [deploy/README.md](deploy/README.md).
- **Qty** — how many of that part are in one planter.

## Parts

| Part | Qty | Weight | Heat-set inserts | Socket cap | #4 | M5 shoulder bolt | Flat head | Wago |
|---|---|---|---|---|---|---|---|---|
| Left gantry holder, rear | 1 | 71 g | 5 × M4 (long) | 5 × M4×16, 1 × M5×16 | 0 | 0 | 0 | 0 |
| Left gantry holder, front | 1 | 45 g | 2 × M4 (long) | 0 | 0 | 2 | 0 | 0 |
| Right gantry holder, rear | 1 | 205 g | 5 × M4 (long) | 5 × M4×16, 1 × M5×16 | 0 | 0 | 0 | 2 × 3-slot |
| Right gantry holder, front | 1 | 85 g | 1 × M4 (long), 2 × M3 (long) | 2 × M3 (pump, into inserts), 4 × M3 (motor, into motor) | 2 | 1 | 0 | 0 |
| Left gantry cover | 1 | 10 g | 0 | 2 × M5×16 | 0 | 0 | 0 | 0 |
| Right gantry cover | 1 | 35 g | 0 | 2 × M5×16 | 0 | 0 | 0 | 0 |
| Gantry V-slot adapter | 1 | 100 g | 4 × M5 (short), 1 x M4(short) 6 × M3 (long) | 4 × M5×16 1 x M4x? | 0 | 0 | 4 × M5×10 | 0 |
| Gantry face top | 1 | 50 g | 0 | 4 × M3 | 0 | 0 | 0 | 0 |
| Gantry face bottom (nozzle holder) | 1 | 50 g | 0 | 2 × M3 | 0 | 0 | 0 | 0 |
| Main electronics, rear | 1 | 270 g | 4 × M4 (long) | 4 × M4×16 | 12 | 0 | 0 | 2 × 5-slot |
| Main electronics, front | 1 | 120 g | 0 | 0 | 0 | 0 | 0 | 0 |
| Left STEMMA QT sub hub, rear | 1 | 85 g | 2 × M4 (long) | 2 × M4×16 | 4 | 0 | 0 | 0 |
| Left STEMMA QT sub hub, front | 1 | 30 g | 0 | 0 | 0 | 0 | 0 | 0 |
| Right STEMMA QT sub hub, rear | 1 | 85 g | 2 × M4 (long) | 2 × M4×16 | 4 | 0 | 0 | 0 |
| Right STEMMA QT sub hub, front | 1 | 30 g | 0 | 0 | 0 | 0 | 0 | 0 |
| Cable chain for water tube | 50 links | 150 g | 0 | 0 | 0 | 0 | 0 | 0 |
| Cable chain anchor | 1 | 3 g | 0 | 0 | 2 | 0 | 0 | 0 |
| Camera module mount | 1 | — | — | — | — | — | — | — |

## Fastener totals

One planter, before spares. Totalled from the table above rather than counted
by hand, so re-total it if the table changes.

| Fastener | Qty | Unit | Line total | Goes into |
|---|---|---|---|---|
| M4 heat-set insert (long) | 21 | $0.25 | $5.25 | gantry holders 13, electronics rear 4, sub hubs 4 |
| M3 heat-set insert (long) | 8 | $0.24 | $1.92 | V-slot adapter 6, right gantry holder front 2 |
| M5 heat-set insert (short) | 4 | $0.25 | $1.00 | V-slot adapter |
| M4×16 socket cap | 18 | $0.07 | $1.26 | M4 inserts — gantry holders 10, electronics rear 4, sub hubs 4 |
| M5×16 socket cap | 10 | $0.08 | $0.80 | 2 into the VITTSJÖ frame, one per rear holder · 8 into T-nuts in the V-slot rail, 4 from the adapter and 2 from each cover |
| M3 socket cap, length TBD | 12 | $0.05 | $0.60 | 6 into the adapter's M3 inserts, from the two gantry faces · 2 into the right gantry holder front's inserts, holding the pump · 4 into the motor's own tapped holes |
| M5×12 flat head | 4 | $0.40 | $1.60 | the V-slot adapter's 4 M5 inserts — flat, not socket, see below |
| #4 × 3/8" | 24 | $0.08 | $1.92 | electronics rear 12, sub hubs 8, right gantry front 2, cable chain anchor 2 |
| M5 shoulder bolt | 3 | $1.00 | $3.00 | M4 inserts — left gantry holder front 2, right gantry holder front 1 |
| Wago 5-slot | 2 | $0.50 | $1.00 | main electronics rear |
| Wago 3-slot | 2 | $0.30 | $0.60 | right gantry holder rear |
| **Total** | **108** | | **$21.95** | |

**33 heat-set inserts, 71 fasteners and 4 Wago connectors per planter —
$18.95 of hardware.**

The heat-set inserts are $8.17 of that: 43% of the cost from 31% of the
pieces, and the single biggest line at $5.25 for the M4s alone. That is what
a $0.25 part does sitting next to a $0.05 screw, and it is worth knowing
before a redesign adds two more bosses to something.

The idler wheels the shoulder bolts carry are not counted here — they are a
drive component and sit in [BOM.md](BOM.md) under core structure.

Against the filament: 1,424 g is roughly $30–36 at typical PETG pricing, so
**$49–55 of raw material per planter** for everything printed and everything
holding it together.

**The thread-by-thread check**, worth re-running after any edit:

- **M4 balances.** 21 inserts against 18 M4×16 plus 3 shoulder bolts.
- **M5 balances.** The adapter's 4 inserts take the 4 M5×12 flat heads; all
  10 M5×16 go elsewhere — 2 into the VITTSJÖ frame, 8 into rail T-nuts.
- **M3 balances.** 8 inserts against 12 screws, and the 4 over are
  deliberate: the motor is tapped, so its four screws go straight into it.
  The pump is not, which is exactly why the right gantry holder front carries
  two M3 inserts. The gantry faces take the adapter's other six.

Every thread is accounted for. A mismatch means a fastener is missing from
the table, or a part has a boss nothing uses — and note that a screw going
into tapped hardware is not a mismatch: the motor here, and the eight M5×16
in rail T-nuts.

A note on the shoulder bolts, because the naming invites a mistake: an M5
shoulder bolt is 5 mm at the shoulder and **M4 at the thread**, so all three go
into M4 inserts. They are not M5 fasteners and do not belong in that line.

## Open items

Every fastener is placed and every part but the camera mount is weighed.

**The M3 screw lengths are missing** — all 12 of them, and they may not be
one length: 6 into the adapter from the gantry faces, 2 holding the pump, 4
into the motor. That is the only line that cannot be ordered against. The
`#4` are 3/8" and every other fastener is dimensioned.

Insert dimensions are deliberately left as `long` and `short`. The inserts are
sold as a kit from the store rather than sourced by whoever assembles the unit,
so the shorthand is enough for the build. The kit itself still needs the real
dimensions written down somewhere — just not here.

## What each part carries

Only the parts with a constraint worth recording.

- **The two gantry holders are not mirror images, and the right side carries
  everything.** `printer.cfg` homes in the positive direction onto
  `position_endstop: 890`, and the comment there notes homing happens at the
  motor end. X0 is the left end of the rail, so the motor and the limit switch
  both live in the right-hand holder — and so does the pump. The left holder
  carries two idler pulleys on shoulder bolts and nothing else.

  The weights corroborate it, but read them carefully: they are printed
  plastic only, so none of that hardware is on the scale. The right
  side is heavier at all three parts — 205 g against 71 g at the rear, 85 g
  against 45 g at the front, 35 g against 10 g on the cover — because of the
  plastic needed to mount it. Roughly 200 g of extra material is the cost of
  putting the motor, the endstop and the pump on one end.

- **The pulley count runs the other way.** Two shoulder bolts on the left
  holder front against one on the right, which is the left side doing the
  idler job while the right drives. The bolts are counted above; the wheels
  that ride on them are in [BOM.md](BOM.md). Worth a line in the assembly
  notes when those get written, because it is obvious while building and
  invisible six months later.

- **The two gantry faces carry the business end.** Top and bottom at 50 g
  each, both bolting into the V-slot adapter's six M3 inserts — four from the
  top, two from the bottom — which is what those inserts are for. The bottom
  face is the nozzle holder, so it is the part that decides where water
  actually lands relative to the position the app reports. If it is ever
  revised, the plant positions captured with the *use current position* button
  are measured against the old geometry and need recapturing.

- **Main electronics holder** (rear and front) has to take the BTT SKR Mini E3
  V2 and the Pi, and [BOM.md](BOM.md) calls for **two Pi mounting patterns**,
  not one: 85 × 56 mm for the Pi 4 / 3 B / 3 B+ development boards, and
  65 × 56 mm for the Pi 3 A+ that is the production target. Port faces differ
  too. It also sits inside the enclosure while the water path stays outside, so
  nothing on it should be reachable by a leak from above. The 12 `#4` screws
  here are half of every `#4` in the build, which fits — that is board
  mounting. The two 5-slot Wagos are the distribution point.

- **STEMMA QT sub hubs** (each rear and front) — the cable runs back to the
  main hub are not equal: **300 mm on the left, 400 mm on the right**, measured
  on the build rather than estimated. The two hubs are otherwise identical:
  85 g and 30 g a side, 2 × M4 inserts, 2 × M4×16 and 4 × `#4` on each rear,
  nothing on either front. I2C is routed away from the motor, pump and LED
  wiring deliberately; see [SENSOR_WIRING.md](SENSOR_WIRING.md) for why bus
  capacitance and the 50 kHz clock make that routing a requirement rather than
  tidiness.

- **Gantry V-slot adapter — the flat heads are deliberate.** Its four M5
  inserts take the M5×12 **flat** heads rather than socket caps, because a
  socket cap stands proud enough to foul the rail as the carriage travels.
  That is a constraint on any future revision of this part, not a parts-bin
  substitution: swapping them back for socket caps would bind the gantry. The
  separate four M5×16 fasten the adapter to the rail through T-nuts, as do the
  two on each cover — eight of the ten M5×16 land in the extrusion rather than
  in anything printed.

- **Cable chain for water tube** — carries the outlet tube to the moving
  carriage. The liquid sensor clamps to that tube's *falling* leg, after the
  high point and before the nozzle, so whatever the chain does to the tube's
  routing has to leave that stretch accessible and still falling. See
  [HOW_WATERING_WORKS.md](HOW_WATERING_WORKS.md). Fifty links at 3 g, which
  makes it the third-heaviest item in the build at 150 g — more than either
  gantry cover and more than both sub hub fronts together. The anchor is a
  separate part and takes the two `#4`.

## Still to come

- **Camera module mount.** An optional paid add-on scoped to timelapse, not
  part of the base build. It takes the standard 15-pin CSI ribbon, which the
  Pi 3 A+ and every development board share — the narrow 22-pin connector on
  the Pi Zero 2 W is the reason that board is deferred until after launch. See
  [BOM.md](BOM.md) and [ROADMAP.md](ROADMAP.md).

## Worth capturing later

The obvious next columns once the open items above are closed: material and
colour, print time, layer height and whether the part needs supports. Of those,
**material matters most** — several of these parts sit near the water path or
under the LED strip, and that is a PETG-or-PLA decision with a real consequence
rather than a preference.
