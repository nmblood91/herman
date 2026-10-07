# Herman Power System

## Overview
Herman uses a 12V primary bus with a DC-DC converter for 5V logic. All components draw from a central busbar with fused circuits.

## Power Supply Specifications

### Main Charger
- **Input:** AC wall power
- **Output:** 12V DC @ minimum 5A (60W)
- **Recommended:** 12V @ 7A (84W) for headroom
- **Type:** Standard barrel jack or XT60 connector

**Why 5A minimum?**
- Pump (12V peristaltic, 100 mL/min): 0.2-0.3A
- LED strip (60 LEDs, 12V WS2811): ~1.2A @ full white
- SKR + Pi + sensors: ~0.5-1A
- Total peak: **25-29W**, the spread being how hard the LED strip is driven.
  So 5A (60W) is generous headroom rather than a floor. Itemised in the
  Power Budget below — the two ends of that range are the same system with
  the strip at 14W and at 18W, not two different estimates.

## Busbar Setup

```
12V Charger
    │
  [5A Inline Fuse Holder]
    │
  Busbar (+12V / GND)
    ├─→ 12V-to-5V DC-DC Converter (3A output) ─→ Raspberry Pi
    ├─→ [2A Inline Fuse Holder] ─→ LED strip +12V
    └─→ BTT SKR Mini E3 V2 (main power input)
             │
             └─→ HE0 connector ─→ [1A Inline Fuse Holder] ─→ 12V Peristaltic Pump
```

**The pump hangs off the SKR, not off the busbar**, so Klipper can switch it.
HE0's mosfet switches the pump's *return* path to ground; the connector's
12/24V pin is the board's own input rail and is live whenever the board is.
See [deploy/README.md](deploy/README.md) for the connector-level wiring.

## Fuse Specifications

### Main Circuit Protection
- **Location:** Charger output → Busbar input
- **Type:** Fast-blow glass fuse (automotive style)
- **Rating:** 5A
- **Purpose:** Protects entire system from shorts in busbar or downstream

### Pump Circuit Protection
- **Location:** SKR HE0 "12/24V" pin → the `+` junction block, upstream of where
  the diode and the pump lead branch off
- **Type:** Fast-blow glass fuse
- **Rating:** 1A
- **Purpose:** Protects the pump circuit, and is the only thing standing between
  a reversed flyback diode and the HE0 mosfet

**Why it sits on the pump's positive lead.** The pump's current path is
SKR VIN → HE0 12/24V pin → pump (+) → motor → pump (−) → PC8 → mosfet → ground.
Only a fuse somewhere in that loop protects anything. A fuse on a *second* wire
run from the busbar to the HE0 12/24V pin protects nothing, because that pin is
already the same node as the busbar — it is the board's own input rail brought
out to the connector.

**Why upstream of the junction, not on the pump branch.** The `+` block joins
three conductors: the feed, the diode cathode, and the pump lead. Fused upstream,
the fuse is in series with every path through that node. Fused on the pump branch
instead, a reversed diode shorts `12V → diode → PC8 → mosfet → GND` without ever
crossing it, leaving only the 5A main fuse — which the mosfet does not survive
waiting for. See [deploy/README.md](deploy/README.md).

**Why 1A and not 2A.** The pump draws 0.2-0.3A running. A 2A fuse would let a
fault pull nearly 2A indefinitely without ever blowing, which is barely
protection at all. 1A sits above the stall current of a motor this small — so a
jammed pump trips it, which is the point — while leaving room for start-up
inrush. Size a pump fuse against the pump, not against the supply.

### LED Circuit Protection
- **Location:** Busbar → LED strip +12V wire
- **Type:** Fast-blow glass fuse
- **Rating:** 2A
- **Purpose:** A shorted solder joint at the strip's input end, or a pinched
  strip, pulls until *something* blows. Without this that something is the 5A
  main fuse, which takes the Pi and the motion board down with it.

**Why 2A.** Sixty 12V pixels draw roughly 1.2-1.5A at full white depending on
the chip, and 2A is the usual 125-165% of maximum load. If it ever nuisance-blows
on a full-white scene, move to 3A rather than assuming a fault.

**A 5V strip does not belong on this branch at all**, and the software no
longer offers one: only 12V chips are selectable. Sixty WS2812B pixels pull
about 3.6A at 5V, which the DC-DC converter's 3A budget cannot absorb on top of
the Pi. A 5V strip needs its own 5V supply and its own fuse sized to it.

## Power Budget

| Component | Voltage | Current | Power |
|-----------|---------|---------|-------|
| SKR Mini E3 V2 | 12V | 0.3A | 3.6W |
| Raspberry Pi | 5V | 0.6A | 3W |
| Pi Camera *(optional add-on)* | 5V | 0.1A | 0.5W |
| Soil Moisture Sensors (4x) | 3.3V | 0.05A | 0.15W |
| Addressable LEDs (60 LEDs, 12V) | 12V | ~1.2-1.5A (peak full white) | ~14-18W |
| Peristaltic Pump (12V, 100 mL/min) | 12V | 0.2-0.3A | ~3.6W |
| **Total Peak** | — | **~2.4A @ 12V** | **~29W** |
| **Typical Operation** | — | **~1A @ 12V** | **~12W** |

The Pi row is budgeted for a Pi 4, the development board. The Pi 3 A+ that
is the production target draws less, so a supply sized from this table has
margin on the shipping hardware rather than the other way round. The camera
row is the optional add-on and is absent from a base unit — see BOM.md.

**Notes:**
- LEDs typically don't run at full brightness; realistic average is 20-30% brightness
- Pump runs in short bursts; not continuous
- Peak draw occurs if everything runs simultaneously (rare)

**Why the LED figure is lower than 5V strips:**

Running the same light output at 12V instead of 5V draws roughly a third of the
current — about 1.2-1.5A for 60 LEDs against the ~3.6A the same count pulls on a
5V WS2812B strip. That is what keeps the strip inside a 2A fuse and off its own
supply.

**How many pixels you actually address depends on the chip.** WS2815 and GS8208
give one addressable pixel per LED, so 60 LEDs is 60 pixels. WS2811 wires the
LEDs in threes — one controller IC per group — so 60 LEDs is only 20 pixels, and
the three LEDs in a group always show the same colour. Check the cut marks:
cuttable between every LED means one pixel per LED; cuttable every third LED
means WS2811. Set `LED_COUNT` to the number of addressable pixels, not the
number of LEDs you can count.

## DC-DC Converter Specifications

- **Input:** 12V DC (8-18V range typical)
- **Output:** 5V DC @ 3A (15W continuous)
- **Efficiency:** ~85-90%
- **Purpose:** Powers Raspberry Pi, camera, and sensors
- **Mounting:** Secure with thermal paste or small heatsink to prevent shutdown under load

## Wiring & Connectors

### Main Busbar

**The busbar is not a separate component.** It is the pair of 5-slot Wago 221
lever connectors at the main electronics rear — one for +12V, one for ground.
Every "busbar" in this document means those two.

Lever connectors rather than a solder busbar or a screw block, for the same
reason the pump leads land in Wagos rather than on the pump terminals: the
joints have to open for service without a soldering iron.

- Gauge per run is in *Wire gauge* below
- A 221-412/413/415 accepts 24–12 AWG, so **10 AWG will not fit one**. A run
  long enough to want it would need the larger 221-6xx family
- Priced in [PRINTED_PARTS.md](PRINTED_PARTS.md), which is where the Wagos
  are counted

### Wire gauge

**Two spools cover the whole build: 14 AWG and 18 AWG.**

| Run | Current | Fuse | Gauge |
|---|---|---|---|
| Charger → Wago busbar | 2.4 A peak | 5 A | **14 AWG** |
| Wago → SKR | 0.6 A | (5 A main) | **14 AWG** |
| Wago → DC-DC converter | 0.25 A | (5 A main) | **14 AWG** |
| Wago → LED strip, ~750 mm | 1.5 A peak | 2 A | **18 AWG** |
| E0 → pump, ~500 mm | 0.3 A | 1 A | **18 AWG** |
| LED data, Pi ground reference | signal | — | 22 AWG |

**Gauge here is set by the fuse, not by the length.** Nothing in this machine
is long enough or hungry enough for voltage drop to matter: the worst case is
the LED strip, and even 22 AWG over its 750 mm run loses 119 mV — 1% of 12 V,
invisible on a light. At 18 AWG it is 47 mV. The pump is further down still at
6 mV.

What does matter is that a wire has to survive its own fuse. A fuse carries
its rating indefinitely — that is what the rating means — so the wire behind
it has to be comfortable at that current forever, not just at the load's
normal draw.

Get that backwards and **the wire becomes the fuse**. Put 24 AWG, good for
about 0.58 A bundled, on the pump's 1 A circuit: a fault could sit at 0.9 A
indefinitely, under the fuse rating the whole time, and the wire cooks inside
the harness with nothing to stop it.

Bundled inside an enclosure a conductor carries far less than the same wire in
free air, and those are the figures to use here: 20 AWG is good for 1.5 A,
18 AWG for 2.3 A, 14 AWG for 5.9 A. So the LED strip's 2 A fuse wants 18 AWG,
and anything sitting behind the 5 A main fuse wants 14 AWG.

**Mixing gauges along one run is fine** — a fuse holder's heavy pigtail
spliced into lighter wire, say — as long as every segment clears the fuse on
its own. The practical form of the rule is that **the thinnest segment sets
the largest fuse allowed**, so check the skinny end rather than the heavy one.
Starting a circuit in 14 AWG does nothing for a thin stretch further along.

Watch the splice itself while you are at it. A loose lever joint or a cold
crimp is a resistance heater in series with the load, and no fuse will ever
notice it.

**That includes the SKR and DC-DC feeds**, which look like light loads and are
not separately fused — a fault on either draws until the 5 A main blows, so
they are sized for 5 A rather than for the 0.6 A and 0.25 A they actually
carry. They are short runs, so this costs nothing but stiffness.


### Fuse Holders
- Inline fuse holders with **16 AWG or larger wire leads**. Their own pigtails
  are short and in free air, so 16 AWG is fine even on the 5 A main — the
  gauge table above applies to the runs, not to a 100 mm lead
- Crimp, solder, or use lever connectors (Wago 221 or similar). What to avoid is
  the push-fit "stab-in" type, where the conductor is held only by a spring barb
  and cannot be inspected or re-seated — a lever connector is a different thing
  and is fine on these currents
- Keep fuses accessible for quick replacement

### Pump Wiring
- 18 AWG, straight into the E0 screw terminal — see *Wire gauge* above
- Both pump leads land on the SKR's HE0 connector, not on the busbar — that is
  what lets Klipper switch it
- The flyback diode and the pump leads meet at a pair of 3-way lever connectors
  beside the pump, rather than being soldered to the pump terminals. The diode
  is the part most worth being able to inspect, and that junction keeps it
  openable — see [deploy/README.md](deploy/README.md)

### LED Strip Wiring
- 18 AWG — set by the 2 A fuse rather than by drop, which is 47 mV over a
  750 mm run
- Power the strip from the busbar through its own 2A fuse; **never from the Pi**
- Tie the strip's ground to the busbar ground, and run a separate ground wire
  from a Pi GND pin to the busbar — the data line needs a shared reference or
  the strip sees noise instead of a signal

## Safety Considerations

1. **Always fuse the main charger output** — protects against internal shorts
2. **Use fast-blow fuses** — electronics need quick response; slow-blow is for motors
3. **Flyback diode across the pump terminals** — Required, not optional. HE0's
   mosfet expects a resistive heater; an inductive motor kicks the switched
   terminal above +12V at turn-off and can destroy it. Striped end to pump
   positive. Wiring and part number in [deploy/README.md](deploy/README.md)
4. **Bulk capacitor on the 12V rail — only if you need it.** A 0.2-0.3A pump on
   a 5A supply does not sag the rail meaningfully, and the SKR already carries
   bulk capacitance on VIN, so do not fit one by default. Add a 1000µF
   electrolytic near the SKR's power input only if the Pi reboots or Klipper
   drops the MCU connection *at the moment the pump starts*. Put it on the
   *rail*, not across the pump terminals: a capacitor in parallel with a
   low-side-switched motor is discharged through the mosfet at every turn-on
5. **Label all circuits** — Use tape/labels on busbar pads and fuse holders
6. **No bare connections** — Use heat shrink, electrical tape, or shrouded connectors
7. **Check voltage under load** — Monitor Pi voltage; it should not drop below 4.75V

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Pi won't boot / reboots randomly | Low 5V voltage | Check DC-DC input/output; may need heatsink |
| Pump doesn't run | Blown 1A fuse | Check for shorts in pump wiring, and that the flyback diode is not reversed |
| Strip dead but everything else fine | Blown 2A LED fuse | Inspect the strip's input end for a solder bridge |
| LEDs flicker or dim | Voltage sag under LED draw | Upgrade charger or add capacitor |
| LEDs do nothing at all | Pi and strip grounds not tied together | Run a ground wire from a Pi GND pin to the busbar ground |
| LEDs flicker or show junk on the first pixels | 3.3V data is marginal for WS2811 | Add a 74AHCT125 level shifter on the data line |
| Red and green are swapped | Strip uses a different channel order | Change LED colour order in the Settings tab |
| Charger warm/hot | Overload or internal short | Reduce load; check for shorts; consider larger PSU |
| Fuses blow immediately | Direct short somewhere | Inspect all wiring for damage before replacing |

## Future Expansion

If adding more components (second pump, more LEDs, etc.):
1. Recalculate total current draw
2. Upgrade charger amperage if needed
3. Potentially upgrade fuse ratings proportionally
4. Consider a separate 12V supply for power-hungry subsystems

