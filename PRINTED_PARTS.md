# Herman Printed Parts

Every printed part in the build, what holds it together, and what it weighs.

Weight is here because it is the one number that turns into money at volume:
filament cost per unit is weight times spool price, and it is also what decides
whether a part is worth redesigning. Inserts and screws are here because they
are the parts that get ordered in the wrong size, and because a part that has
already been printed cannot be re-tapped for a different insert.

**This table is mostly empty on purpose.** It is filled in by measuring, not by
estimating. See the conventions below so it does not end up half in one
notation and half in another.

## Conventions

- **Weight** — the finished part on a scale, supports and brim removed, in
  grams. A kitchen scale reading to 1 g is enough for filament cost; use 0.1 g
  if you want to compare design revisions against each other.
- **Heat-set inserts** — `M3 × 5.7 × 4.6` is diameter × length × outer
  diameter, in millimetres, the way CNC Kitchen and Ruthex label them. Give the
  count too: `4 × M3 × 5.7 × 4.6`.
- **Screws** — thread, length, head type: `M3×8 SHCS` (socket head cap),
  `M3×6 BHCS` (button head). Note the count the same way. If a screw goes into
  an insert in a *different* part, say which part, because that is the pairing
  that gets lost.
- **Qty** — how many of that part are in one planter.

## Parts

| Part | Qty | Weight | Heat-set inserts | Screws |
|---|---|---|---|---|
| Left gantry holder, rear | 1 | TBD | TBD | TBD |
| Left gantry holder, front | 1 | TBD | TBD | TBD |
| Right gantry holder, rear | 1 | TBD | TBD | TBD |
| Right gantry holder, front | 1 | TBD | TBD | TBD |
| Left gantry cover | 1 | TBD | TBD | TBD |
| Right gantry cover | 1 | TBD | TBD | TBD |
| Gantry V-slot adapter | TBD | TBD | TBD | TBD |
| Main electronics holder | 1 | TBD | TBD | TBD |
| Left STEMMA QT sub hub | 1 | TBD | TBD | TBD |
| Right STEMMA QT sub hub | 1 | TBD | TBD | TBD |
| Cable chain for water tube | TBD links | TBD per link | — | TBD |
| Camera module mount | 1 | — | — | — |

The camera mount is a paid add-on rather than part of the base build, and does
not exist yet. See *Still to come* below.

## Fastener totals

Fill this in once the table above is complete. It is the part that becomes a
kit: one line per insert size and one per screw size, with the count for a
whole planter plus a few spares. Ordering against the per-part column means
counting it by hand every time.

| Fastener | Total per planter |
|---|---|
| TBD | TBD |

## What each part carries

Only the parts with a constraint worth recording. The rest are in the table and
need no commentary.

- **The two gantry holders are not mirror images.** `printer.cfg` homes in the
  positive direction onto `position_endstop: 890`, and the comment there notes
  homing happens at the motor end so the belt span is shortest when the switch
  trips. X0 is the left end of the rail, so **the motor and the limit switch
  both live in the right-hand holder** and the left one carries the idler.
  Expect different insert and screw counts on the two sides, and check this
  against the physical build before trusting it — it is read out of the config,
  not measured.

- **Main electronics holder** has to take the BTT SKR Mini E3 V2 and the Pi,
  and [BOM.md](BOM.md) calls for **two Pi mounting patterns**, not one: 85 × 56
  mm for the Pi 4 / 3 B / 3 B+ development boards, and 65 × 56 mm for the Pi 3
  A+ that is the production target. Port faces differ too. It also sits inside
  the enclosure while the water path stays outside, so nothing on it should be
  reachable by a leak from above.

- **STEMMA QT sub hubs** — the cable runs back to the main hub are not equal:
  **300 mm on the left, 400 mm on the right**, measured on the build rather
  than estimated. I2C is routed away from the motor, pump and LED wiring
  deliberately; see [SENSOR_WIRING.md](SENSOR_WIRING.md) for why bus
  capacitance and the 50 kHz clock make that routing a requirement rather than
  tidiness.

- **Cable chain for water tube** — carries the outlet tube to the moving
  carriage. The liquid sensor clamps to that tube's *falling* leg, after the
  high point and before the nozzle, so whatever the chain does to the tube's
  routing has to leave that stretch accessible and still falling. See
  [HOW_WATERING_WORKS.md](HOW_WATERING_WORKS.md).

## Still to come

- **Camera module mount.** An optional paid add-on scoped to timelapse, not
  part of the base build. It takes the standard 15-pin CSI ribbon, which the
  Pi 3 A+ and every development board share — the narrow 22-pin connector on
  the Pi Zero 2 W is the reason that board is deferred until after launch. See
  [BOM.md](BOM.md) and [ROADMAP.md](ROADMAP.md).

## Worth capturing later

Not now, but the obvious next columns once the table above is filled: material
and colour, print time, layer height and whether the part needs supports. Of
those, **material matters most** — several of these parts sit near the water
path or under the LED strip, and that is a PETG-or-PLA decision with a real
consequence rather than a preference.
