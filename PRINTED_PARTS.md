# Herman Printed Parts

Every printed part in the build, what holds it together, and what it weighs.

Weight is here because it is the one number that turns into money at volume:
filament cost per unit is weight times spool price, and it is also what decides
whether a part is worth redesigning. Inserts and screws are here because they
are the parts that get ordered in the wrong size, and because a part that has
already been printed cannot be re-tapped for a different insert.

**One planter is 1,171 g of printed parts**, excluding the cable chain and the
camera mount. At typical PETG pricing that is roughly $25–30 of filament per
unit, which is enough to be worth watching — the two heaviest parts alone, the
main electronics rear at 270 g and the right gantry holder rear at 205 g, are
40% of it.

## Conventions

- **Weight** — the finished part on a scale, supports and brim removed, in
  grams.
- **`0` versus `—`** — `0` means the part genuinely takes none of that
  fastener. `—` means the part does not exist yet, so the answer is unknown
  rather than zero. Only the camera mount uses `—`.
- **Heat-set inserts** — count × thread, then the length. The table currently
  says `long` and `short`, which is the shorthand used while building; see
  *Open items* for why that needs resolving to millimetres before anyone can
  order from this.
- **Screws** — count × thread × length: `4 × M4×16`. Head type is the column
  it sits in. If a screw goes into an insert in a *different* part, say which
  part, because that is the pairing that gets lost.
- **Qty** — how many of that part are in one planter.

## Parts

| Part | Qty | Weight | Heat-set inserts | Socket cap | #4 | M5 shoulder + pulley | Flat head |
|---|---|---|---|---|---|---|---|
| Left gantry holder, rear | 1 | 71 g | 5 × M4 (long) | 4 × M4×16, 1 × M5×16 | 0 | 0 | 0 |
| Left gantry holder, front | 1 | 45 g | 2 × M4 (long) | 0 | 0 | 2 | 0 |
| Right gantry holder, rear | 1 | 205 g | 5 × M4 (long) | 4 × M4×16 | 0 | 0 | 0 |
| Right gantry holder, front | 1 | 85 g | 1 × M4 (long), 2 × M3 (long) | 2 × M3 (length TBD) | 2 | 1 | 0 |
| Left gantry cover | 1 | 10 g | 0 | 2 × M5×16 | 0 | 0 | 0 |
| Right gantry cover | 1 | 35 g | 0 | 2 × M5×16 | 0 | 0 | 0 |
| Gantry V-slot adapter | 1 | 100 g | 4 × M5 (short) | 0 | 0 | 0 | 4 × M5×12 |
| Main electronics, rear | 1 | 270 g | 4 × M4 (long) | 4 × M4×16 | 12 | 0 | 0 |
| Main electronics, front | 1 | 120 g | 0 | 0 | 0 | 0 | 0 |
| Left STEMMA QT sub hub, rear | 1 | 85 g | 2 × M4 (long) | 2 × M4×16 | 4 | 0 | 0 |
| Left STEMMA QT sub hub, front | 1 | 30 g | 0 | 0 | 0 | 0 | 0 |
| Right STEMMA QT sub hub, rear | 1 | 85 g | 2 × M4 (long) | 2 × M4×16 | 4 | 0 | 0 |
| Right STEMMA QT sub hub, front | 1 | 30 g | 0 | 0 | 0 | 0 | 0 |
| Cable chain for water tube | TBD links | TBD per link | 0 | 0 | 2 | 0 | 0 |
| Camera module mount | 1 | — | — | — | — | — | — |

## Fastener totals

One planter, before spares. Totalled from the table above rather than counted
by hand, so re-total it if the table changes.

| Fastener | Total | Where |
|---|---|---|
| M4 heat-set insert (long) | 21 | gantry holders 13, electronics rear 4, sub hubs 4 |
| M3 heat-set insert (long) | 2 | right gantry holder front |
| M5 heat-set insert (short) | 4 | V-slot adapter |
| M4×16 socket cap | 16 | gantry holders 8, electronics rear 4, sub hubs 4 |
| M5×16 socket cap | 5 | gantry covers 4, left gantry holder rear 1 |
| M3 socket cap, length TBD | 2 | right gantry holder front |
| M5×12 flat head | 4 | V-slot adapter |
| #4, length TBD | 24 | electronics rear 12, sub hubs 8, right gantry front 2, cable chain 2 |
| M5 shoulder bolt with pulley | 3 | left gantry holder front 2, right gantry holder front 1 |

**27 heat-set inserts and 54 fasteners per planter.**

## Open items

Three things this table cannot yet be ordered from.

1. **`long` and `short` are not sizes.** Every insert is recorded that way, so
   nothing here can be bought without going back to the drawer. Resolving them
   to real dimensions is the single edit that makes this document usable by
   someone who is not you. Same for the `#4` screws and the `2 × M3` on the
   right gantry holder front, which have counts but no lengths.

2. **Five M4 inserts have no screw going into them.** 21 M4 inserts against 16
   M4×16 screws, and the gap is all in the gantry holders — one each in the
   left rear, right rear and right front, and both in the left front. That is
   probably the case the conventions above anticipate: the screw lives in the
   mating part, so the pairing was never written down. Worth confirming it is
   that rather than five unused bosses.

3. **The M5×16 screws may not go into printed inserts at all.** M5 is the
   standard T-nut thread for 2020 extrusion, and the covers and the left rear
   holder take five between them while no printed part has an M5 insert except
   the V-slot adapter. If they thread into the rail, say so — it changes what
   has to be in the box.

The right-hand sub hub front was left as `TBD` for `#4` where its left twin was
blank. The two parts are identical in every other column, so it is recorded as
`0`; correct it if that is wrong.

## What each part carries

Only the parts with a constraint worth recording.

- **The two gantry holders are not mirror images, and the weights now prove
  it.** `printer.cfg` homes in the positive direction onto `position_endstop:
  890`, and the comment there notes homing happens at the motor end so the belt
  span is shortest when the switch trips. X0 is the left end of the rail, so
  the motor and the limit switch both live in the right-hand holder. The
  measured weights agree from the other direction: the right side is heavier at
  all three parts — 205 g against 71 g at the rear, 85 g against 45 g at the
  front, 35 g against 10 g on the cover. That is what carrying a NEMA 17 and an
  endstop looks like. This was originally inferred from the config alone and
  flagged as needing a check against the build; the weights are that check.

- **The pulley count is the other asymmetry.** Two M5 shoulder bolts with
  pulleys on the left holder front against one on the right. Worth a line in
  the assembly notes when those get written, because it is the kind of thing
  that is obvious while building and invisible six months later.

- **Main electronics holder** (rear and front) has to take the BTT SKR Mini E3
  V2 and the Pi, and [BOM.md](BOM.md) calls for **two Pi mounting patterns**,
  not one: 85 × 56 mm for the Pi 4 / 3 B / 3 B+ development boards, and
  65 × 56 mm for the Pi 3 A+ that is the production target. Port faces differ
  too. It also sits inside the enclosure while the water path stays outside, so
  nothing on it should be reachable by a leak from above. The 12 `#4` screws
  here are half of every `#4` in the build, which fits — that is board
  mounting.

- **STEMMA QT sub hubs** (each rear and front) — the cable runs back to the
  main hub are not equal: **300 mm on the left, 400 mm on the right**, measured
  on the build rather than estimated. The two hubs are otherwise identical,
  85 g and 30 g a side. I2C is routed away from the motor, pump and LED wiring
  deliberately; see [SENSOR_WIRING.md](SENSOR_WIRING.md) for why bus
  capacitance and the 50 kHz clock make that routing a requirement rather than
  tidiness.

- **Cable chain for water tube** — carries the outlet tube to the moving
  carriage. The liquid sensor clamps to that tube's *falling* leg, after the
  high point and before the nozzle, so whatever the chain does to the tube's
  routing has to leave that stretch accessible and still falling. See
  [HOW_WATERING_WORKS.md](HOW_WATERING_WORKS.md). Weight is per link rather
  than per planter, so it needs a link count before it can join the total
  above.

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
