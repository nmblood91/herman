# Herman Pi Deployment

This folder contains the deployment files needed to run Herman on a Raspberry Pi with a single-axis gantry driven by Klipper.

## Files

- `systemd/greenthumb-api.service` — runs the FastAPI backend on port 8000
- `nginx/greenthumb.conf` — serves the built React app and proxies `/api` to the backend
- `klipper/firmware.bin` — pre-built Klipper MCU firmware for SKR Mini E3 V2 (flash via SD card)
- `klipper/printer.cfg.example` — bare-bones single-axis gantry Klipper template
- `pi/install-green-thumb.sh` — install script for the Pi
- `pi/send-gcode.py` — sends one gcode command to Klipper and prints the reply

## Flashing the SKR Mini E3 V2 Board

The SKR Mini E3 V2 board comes with an onboard micro-SD card reader that contains the bootloader. The Klipper MCU firmware is flashed via this SD card.

**Pre-flashed firmware location:** `deploy/klipper/firmware.bin`

### Flashing steps (per unit):

1. **Get the firmware file onto an SD card:**
   - On your laptop: Clone or download the GreenThumb repo (the software keeps its own name)
   - Locate `deploy/klipper/firmware.bin`
   - Insert the SD card into your laptop's card reader
   - Copy `firmware.bin` to the root of the SD card (it must be named exactly `firmware.bin`)

2. **Flash the board:**
   - Safely eject the SD card from your laptop
   - Turn off SKR
   - Insert the SD card into the SKR Mini E3 V2
   - Turn on SKR
   - Watch for 2nd red light to begin flashing
   - Once that stops it is flashed
   - After a successful flash, the bootloader renames the file to `FIRMWARE.CUR` to prevent re-flashing

## Fresh Pi Setup

For a clean installation with the latest OS, start here:

1. **Flash Pi OS** using [Raspberry Pi Imager](https://www.raspberrypi.com/software/):
   - Choose **Raspberry Pi OS (64-bit)**
   - Set hostname: `herman` — this is the address the owner types, so it is
     the product name rather than the software's. The Python package, the
     service and `/opt/greenthumb` keep their own name and are never shown
   - Enable SSH
   - Set your WiFi network and country in the imager's advanced options.
     That is how a *development* Pi joins a network, and it is not how a
     shipped unit can work, since the customer's network is unknown at
     flashing time. See *Getting onto the customer's WiFi* in
     [ROADMAP.md](../ROADMAP.md)
   - **Username must be `pi`** — the systemd service, the Klipper paths, and the
     install script all reference `/home/pi` and run the API as `pi`. Any other
     username requires editing those in step with each other.

2. **Boot the Pi and wait ~2 minutes** for initial setup to complete.

3. **SSH into the Pi**:
   ```bash
   ssh pi@herman.local
   ```

4. **Install git and clone the repo**:
   ```bash
   sudo apt update
   sudo apt install -y git
   sudo mkdir -p /opt/greenthumb
   sudo chown pi:pi /opt/greenthumb
   git clone --depth 1 https://github.com/nmblood91/herman.git /opt/greenthumb
   ```

   The repo is `herman` but it is cloned into `/opt/greenthumb`, and that is
   deliberate: Herman is the product, GreenThumb is the software, and the
   install path, the Python package and the systemd units all use the software
   name. Only things an owner reads say Herman.

   `sudo` creates the directory because `/opt` is root-owned, but the clone
   itself runs as `pi` so the checkout and `.git` belong to `pi` from the start.
   Cloning with `sudo` instead leaves a root-owned repo, and every later
   `sudo git` writes root-owned objects into `.git` that plain git then can't
   update.

5. **Run the installation script** (this installs everything):
   ```bash
   sudo bash /opt/greenthumb/deploy/pi/install-green-thumb.sh
   ```
   This will take 10-15 minutes. Watch for "GreenThumb install complete" at the end.

6. **Configure Klipper** (if SKR board is connected):
   - If auto-detected: ✓ Already configured
   - If not detected: See **Configure Klipper** section below

7. **Verify everything is running**:
   ```bash
   sudo systemctl status klipper
   sudo systemctl status greenthumb-api.service
   sudo systemctl status nginx
   ```

   The install script also prints an interface check at the end. If it reports
   `/dev/i2c-1` or `/dev/spidev0.0` missing, reboot and re-run it — the script is
   idempotent and safe to run repeatedly.

   Read the sensors directly, without going through the API:
   ```bash
   cd /opt/greenthumb && .venv/bin/python -m greenthumb.hardware.soil_sensors
   ```
   Sensors that are absent or unplugged report `-1` rather than a fake value.

   Check the bus is reliable, not just working, after any cabling change:
   ```bash
   cd /opt/greenthumb && .venv/bin/python -m greenthumb.hardware.soil_sensors --soak 120
   ```
   This hammers every address for two minutes and reports an error rate each.
   Intermittent I2C trouble is invisible in a single read and easy to mistake for
   a flaky sensor months later — see **Wiring the Soil Sensors** below.

8. **Open the web UI**:
   - Open `http://herman.local` in your browser
   - Or use the Pi's IP: `http://<pi-ip>`


## Repointing an existing checkout

The repo was renamed from `GreenThumb` to `herman`. GitHub redirects the old
URL, so a Pi cloned before the rename keeps working — but the redirect stops if
anything is ever created at the old path, and a remote pointing at a name that
no longer exists is a trap for whoever debugs it next. One command:

```bash
git -C /opt/greenthumb remote set-url origin https://github.com/nmblood91/herman.git
git -C /opt/greenthumb remote -v
```

The checkout stays at `/opt/greenthumb`. The product is Herman; the software,
the package and the paths are GreenThumb.

## Renaming an existing Pi

A Pi flashed before the product was named `herman` still answers to
`greenthumb.local`. Nothing in the code depends on the hostname, so it is one
command and a reboot:

```bash
sudo hostnamectl set-hostname herman
sudo sed -i 's/greenthumb/herman/g' /etc/hosts
sudo reboot
```

After that it is `herman.local`, and `greenthumb.local` stops resolving — so
update any bookmark or SSH config pointing at the old name. `/opt/greenthumb`,
the systemd units and the Python package are unaffected and keep their names.

## Updating an installed Pi

```bash
cd /opt/greenthumb
git pull
sudo systemctl restart greenthumb-api.service
```

**Never `sudo git pull`.** The repo is owned by `pi`, and running git as root
writes root-owned objects into `.git` that plain git can no longer update. `sudo`
is only needed for the initial clone's parent directory and for the install
script.

Re-run the install script instead of pulling when the change touches
`printer.cfg.example`, the systemd units, or the nginx config — those are copied
out of the repo at install time, so a pull alone does not apply them.

**A frontend change also needs a build, not just a pull.** `frontend/dist` is
gitignored and built here, so a pull brings new source without new output. Either
re-run the install script or build it directly:

```bash
cd /opt/greenthumb/frontend && npm run build
```

Build output used to be committed, which meant every install rewrote tracked
files and left the checkout permanently dirty — and then the next `git pull`
aborted with "local changes would be overwritten by merge". If you hit that on an
older checkout, see **Recovering a diverged checkout** below.

Taken together, the above is why **`git pull` is a developer workflow, not an
update mechanism** — too much of an update lives outside what a pull applies. A
shippable path is sketched under *Updates, eventually* in
[ROADMAP.md](../ROADMAP.md).

**Re-running regenerates `printer.cfg` from the template.** The template is the
source of truth, which is how a config fix in the repo reaches the Pi, but it
means local tuning is replaced. Anything that differs is backed up first to
`~/printer_data/config/printer.cfg.<timestamp>.bak`, and the script prints the
`diff` command to recover from it. `position_endstop` is the one you will most
likely have changed, since it is measured against your own switch mounting.

If you would rather not have it touched at all, edit the live config by hand and
restart Klipper instead of re-running the installer:

```bash
nano ~/printer_data/config/printer.cfg
sudo systemctl restart klipper
tail -20 ~/klipper_logs/klippy.log
```

## Recovering a diverged checkout

If `git pull` aborts with "Your local changes to the following files would be
overwritten by merge", or lists untracked files it refuses to overwrite, the
checkout has drifted from the repo. Two things cause it: build output that used
to be committed and rebuilt in place, and files copied onto the Pi by hand
instead of pulled, which git has never heard of.

The repo is the source of truth, so the fix is to discard whatever is local. Take
a snapshot first — `.env` and `data/` are gitignored, so the git commands below
leave them alone, but they are the two things worth keeping:

```bash
cd /opt/greenthumb
tar czf ~/greenthumb-pi-snapshot.tar.gz .env data
```

Look before resetting. The second command is a dry run that lists exactly what
would be deleted:

```bash
git status --short
git clean -nd
```

Everything listed should be build output or files that exist in the repo anyway.
If something there was genuinely written on the Pi, save it before continuing.

```bash
git clean -fd
git fetch origin
git reset --hard origin/main
git log --oneline -1
```

`clean -fd` removes untracked files but not ignored ones, so `.venv`, `.env`,
`data/`, `logs/` and `node_modules/` survive. Then rebuild the derived files,
since a reset only restores what git tracks:

```bash
sudo bash /opt/greenthumb/deploy/pi/install-green-thumb.sh
```

Prefer this over `rm -rf /opt/greenthumb` and a fresh clone. It reaches the same
tracked-file state, while `rm -rf` would take `.env` and the history database
with it.

## Service behavior

- The backend runs as a systemd service on port 8000.
- Nginx serves the built frontend from `/opt/greenthumb/frontend/dist`.
- `/api` requests are proxied to the Python API.

## Wiring the X Endstop

X homes against a mechanical switch on the **X-STOP** connector. Sensorless
(StallGuard) homing is not usable on this board: the TMC2209 drives its DIAG
output correctly, but that signal is not routed to `PC0`, so the pin reads high
forever and `G28 X` completes instantly without moving.

Mount the switch inside the dead zone at the **right** end of the rail, next to
the motor, so the carriage trips it before reaching the mechanical limit.

Homing at the motor end keeps the belt span between the pulley and the carriage
at its shortest when the switch trips, which makes the reference the most
repeatable point on the rail. The effect is tens of microns on a 1 m GT2 belt, so
treat it as a tiebreaker rather than a requirement -- either end works, and the
switch can move as long as `position_endstop`, `position_max` and the park
position in `homing_override` move together.

**Wiring** — two pins, no power needed:

```
Switch COM ──→ X-STOP  GND
Switch NC  ──→ X-STOP  signal (PC0)
```

X-STOP is a 2-pin connector, and a mechanical switch is a passive contact:
`^PC0` enables the MCU's internal pull-up, so the pin idles high on its own and
the switch only has to pull it to ground. Nothing here needs power.

**Most limit switches sold for printers are 3-pin, so one wire comes off.**
Which one depends on the board, and the S / G / V silkscreen is not a reliable
guide — on many of them it is generic connector labelling over a straight
passthrough of the microswitch's own C / NO / NC terminals, with no LED and no
supply pin at all. Trace it before cutting: multimeter on continuity, work the
lever, and find the pair that is **closed with the lever released**. That is
common and NC, and those are the two you keep.

A common case is S=C, G=NO, V=NC, which means keeping the *outer* two pins and
removing the middle one. Lift the retention tab in the connector housing with a
pin and slide the unwanted contact out rather than re-crimping.

**That layout is the one confirmed on this build** — S common, V the NC contact —
so S and V are the pair to keep and G is the wire that comes off. Still trace
your own module rather than trusting this: it is a property of the module, not of
the board, and a different batch can differ.

**Prefer NC over NO** when the switch offers both. A broken wire or an unseated
connector then reads the same as triggered, so homing fails immediately. Wired
normally-open, a broken wire is indistinguishable from a healthy untriggered
switch, and the first sign of trouble is the carriage driving into the end of
the rail.

`printer.cfg` uses `endstop_pin: ^PC0`, which expects a **normally-closed**
switch. The polarity convention is worth getting straight, because it is easy to
state backwards — "TRIGGERED" is a logical 1, `^` is the pull-up, and `!` inverts:

| Config | Switch | Released | Pressed |
|---|---|---|---|
| `^PC0` | **NC** | closed → pin low → `open` | open → pull-up high → `TRIGGERED` |
| `^!PC0` | **NO** | open → high → inverted → `open` | closed → low → inverted → `TRIGGERED` |

So the bare `^PC0` is the normally-closed config and `^!PC0` is the
normally-open one. Verify before homing:

```bash
python3 /opt/greenthumb/deploy/pi/send-gcode.py QUERY_ENDSTOPS
```

Released it must read `stepper_x:open`; held down by hand, `stepper_x:TRIGGERED`.

**If those are backwards, you are on the switch's normally-open pair** — move the
signal wire to the pair that is closed with the lever released, rather than
adding `!` to the pin. Adding `!` makes the reading correct and silently gives up
the fail-safe below, which is the whole reason for wiring NC.

Then confirm the fail-safe itself, by unplugging the connector with the lever
released:

```bash
python3 /opt/greenthumb/deploy/pi/send-gcode.py QUERY_ENDSTOPS
```

Unplugged it must read `stepper_x:TRIGGERED`. A disconnected switch reading as
triggered is the point: homing fails immediately instead of driving the carriage
into the end of the rail.

Y and Z read `TRIGGERED` and should be ignored. They are placeholder axes with
nothing wired to PC15 and PC14, and an unconnected pin with a pull-up reads high
— which is deliberate, so a stray `G28 Y` fails fast.

### If homing reports "Unknown command: G28.1"

The `homing_override` block must call plain `G28`, not `G28.1`. `G28.1` is a
Marlin command; Klipper does not have it, so the override fails on its first
line and the park move that follows refuses with `Must home axis first`,
leaving the axis unhomed with two errors that do not obviously point at the
config.

Calling `G28` from inside `homing_override` looks like it would recurse
forever and does not: Klipper sets a flag while the override script runs and
dispatches a nested `G28` to the real homing routine.

### Check the motor direction before homing

`homing_positive_dir: True` sends `G28 X` toward the switch at
`homing_speed: 40` mm/s. If the motor turns the other way it drives the
carriage into the far end of the rail at that speed, belt and all. Which way
it turns depends on the order of the coil pairs in the connector and on how
the belt is routed, so it is a property of the machine, not something the
board decides.

Park the carriage mid-rail, then nudge it:

```bash
python3 /opt/greenthumb/deploy/pi/send-gcode.py   "FORCE_MOVE STEPPER=stepper_x DISTANCE=10 VELOCITY=20"
```

It must move **10 mm toward the switch**. If it moves away, invert `dir_pin`
in `[stepper_x]` — `PB12` becomes `!PB12` or back again — and restart Klipper.
This build needs `!PB12`.

`FORCE_MOVE` ignores endstops and soft limits entirely, which is what makes it
usable before homing and also why the distances here are small.

**Put the value in `printer.cfg.example`, not just in the live config.**
Re-running the install script regenerates `printer.cfg` from the template, so
a direction fixed only on the Pi is backed up and then lost on the next
install.

### Do not jog to X0 until the rail is measured

After homing, Klipper believes the carriage is at `position_endstop` and that
there is that much travel below it. While that value is still the shipped
placeholder, `G1 X0` is an instruction to drive the carriage somewhere that
may be past the end of the rail.

Work leftward in steps instead, watching:

```bash
python3 /opt/greenthumb/deploy/pi/send-gcode.py "G91"
python3 /opt/greenthumb/deploy/pi/send-gcode.py "G1 X-100 F3000"   # repeat
python3 /opt/greenthumb/deploy/pi/send-gcode.py "G90"
```

The total distance from the trip point to the left end of usable travel is the
real `position_endstop`.

**Setting plant positions.** Jog the carriage until the nozzle sits over a
pot, then use *Use current position* on that plant's card in the Plants tab.
It fills the field without saving, so the number can be checked first. Aim the
nozzle rather than the carriage body: the offset between them is the same
error on every plant.

It refuses an unhomed gantry, because an unhomed axis reports a position
relative to wherever it powered up -- a meaningless number that looks like a
real one. It also refuses anything outside the rail, and warns when the
captured position is within 50 mm of another plant, which is what pressing the
button on the wrong card looks like.

**Plant positions have to fit inside it.** `position_max` is the furthest the
carriage can go, and a plant configured past it simply cannot be reached --
the move is refused and that plant is never watered. The defaults in
`greenthumb/plants.py` are scaled to the travel measured here; if yours is
shorter, they need scaling again. The app asks Klipper for the real limit
rather than keeping its own copy, so it follows `position_max` automatically
once Klipper is restarted.

**Calibrating `position_endstop`.** X960 is the last usable position and the
switch sits past it, so homing can retract clear of the switch instead of resting
on the upper limit. `position_endstop` is the coordinate at which the switch
trips — at `980`, it sits 20 mm beyond usable travel. Measure it against your own
mounting, then set `position_max` to the same value and park 20 mm short of it in
`homing_override`. X0 stays the left end of usable travel, so plant positions are
unaffected by which end the switch lives at.

**Homing parks the carriage at X0**, the far end from the switch, rather than
leaving it where it tripped. That is a choice about who reads the screen: the
app shows the carriage position, and `0 mm` means something to the person who
owns one of these, while `870 mm` is a number they cannot interpret. It costs a
full traverse of the rail after every home, so raise the feedrate in
`homing_override` if the wait is irritating.

`homing_positive_dir: True` is stated explicitly. Klipper would infer it from
`position_endstop` sitting at the top of the range, but then a later edit to
`position_max` could silently reverse which way the carriage homes.

## Wiring the Pump to SKR Board

The peristaltic pump is controlled via the SKR's **HE0 (heater) connector** on
the bottom edge of the board, which is how Klipper can switch it on and off.

**HE0 switches the ground side, not the positive side.** The mosfet sits between
PC8 and ground. The connector's other pin is the board's own 12V input rail
brought out, so it is live whenever the SKR is powered — but the pump does not
run, because its return path through PC8 stays open until Klipper closes the
mosfet.

That is worth being clear about, because it decides where the fuse goes. The
pump's current path is:

```
SKR VIN → HE0 12/24V pin → pump (+) → motor → pump (−) → PC8 → mosfet → GND
```

A fuse protects the pump only if it sits somewhere in *that* loop.

**Wiring — both pump leads land on HE0:**
```
HE0 "12/24V" ──[1A Pump Fuse]──→ Pump (+)
HE0 "PC8"    ──────────────────→ Pump (−)
```

**Connection summary:**
- HE0 12/24V pin → 1A fuse → pump positive
- Pump negative → HE0 PC8 pin
- Nothing from the pump goes to the busbar — the SKR's own power feed supplies it
- If your HE0 connector has a third GND pin, it is unused here; the mosfet
  already grounds the pump through PC8

Pump (+) could equally be taken from the busbar, since the HE0 12/24V pin is
electrically the same node. Keeping the pair together at the connector just
means one plug to pull and one fuse unambiguously in series with the motor.

### Flyback diode (required)

HE0's mosfet is designed for a heater cartridge, which is purely resistive. A
pump is an inductive motor: when the mosfet switches off, the collapsing field
drives the negative terminal above +12V, and that spike can destroy the mosfet.
A flyback diode gives the current a loop through the motor winding instead.

Fit it **across the pump's own two terminals**, in parallel with the motor — not
inline with a wire, and not at the board end.

```
  HE0 "12/24V"
       │
  [1A Pump Fuse]        in series, at the board end
       │
       ├──────────────┐
       │              │
    Pump (+)         ═╧═   STRIPED band at the top
       │              ▲    (cathode to the positive side)
   [ MOTOR ]          │
       │              │    1N5822, in parallel,
    Pump (−)          │    at the pump end
       │              │
       ├──────────────┘
       │
  HE0 "PC8"  ──→ mosfet ──→ GND
```

**Striped end (cathode) to the positive terminal.** Orientation is not optional.
Reversed, the diode is forward-biased from +12V toward PC8, which is a dead
short through the mosfet.

It does not short at power-up, though, and that is worth being precise about:
the diode's path to ground runs through PC8, and the mosfet holds that open
until Klipper switches it. **A reversed diode draws nothing until the first time
the pump is commanded on**, and blows the 1A fuse then. So a clean power-up is
not evidence the diode is the right way round — check continuity before
powering, rather than letting the fuse answer the question.

### Where the fuse goes, and why

Put the fuse **upstream of the junction** — between the SKR and the `+` block —
not between the block and the pump.

The `+` node joins three things: the feed from the SKR, the diode's cathode, and
the pump's positive lead. A fuse upstream of that branch point is in series with
every path through it. A fuse on the pump branch alone protects only the pump,
and leaves two faults uncovered:

- **A reversed diode.** Its fault path is `12V → diode → PC8 → mosfet → GND`,
  which never passes through a fuse sitting on the pump branch. That short is
  then held back only by the 5A main fuse, and the mosfet fails long before a 5A
  fast-blow responds. The component the diode protects is destroyed by the diode.
- **The block itself.** The `+` node is live whenever the SKR is powered. A
  bridged connector or chafed insulation there is unfused for the same reason.

A fuse on the pump branch also sits *inside* the flyback loop, so the circulating
current at turn-off runs `motor → diode → fuse → motor`, adding length to the one
loop that is supposed to be short.

Part: a **1N5822** (3A Schottky) is comfortable overkill for a 0.2-0.3A pump and
costs the same as anything smaller, so it is the easy choice. A 1N5817 or 1N4001
is electrically adequate here too. Schottky parts switch faster and clamp the
spike more cleanly than a 1N400x.

### Mounting it: a junction block at the pump

Mount the diode on a pair of 3-way lever connectors (Wago 221 or similar) next
to the pump. Nothing is soldered to the pump terminals: the diode is the part
most worth being able to inspect or replace, and a joint you cannot open is a
joint you cannot check. All three slots of a lever connector are one node
internally, so each block becomes a junction of three conductors:

```
  SKR HE0 "12/24V" ──[1A fast-blow]──┐
                                     │
                          ┌──────────┴──────────┐
                          │  "+" BLOCK (3-way)  │   fused feed · cathode · pump+
                          └────┬──────────┬─────┘
                               │          │
                 STRIPED end  ═╧═         └──────────→ Pump (+)
                               ▲  1N5822
                               │
                          ┌────┴─────────────────┐
                          │  "−" BLOCK (3-way)   │   PC8 · anode · pump−
                          └────┬──────────┬──────┘
                               │          └──────────→ Pump (−)
  SKR HE0 "PC8" ───────────────┘
```

That puts the diode in parallel with the motor, cathode to positive, downstream
of the fuse — the topology the diagram above describes. Four things to respect:

- **Keep the block-to-pump leads short**, under about 10 cm, with the two leads
  running together. Wire between the diode and the winding is unprotected
  inductance, which is the whole thing the diode exists to absorb.
- **The "+" block is live whenever the SKR is powered.** HE0's 12/24V pin is the
  board's input rail, not a switched output — the pump is off because PC8 is
  open, not because the positive side is dead. Power the board down before
  opening the block, and do not assume an idle pump means a safe node.
- **Seat the diode leads fully.** They are stiff 0.9 mm solid wire, within a
  Wago 221's range, but leave a few millimetres straight out of the diode body
  before any bend so the glass seal is not stressed, and sleeve the legs.
- **Label the block.** Reinstalling the diode backwards during maintenance is
  the one mistake that costs a mosfet, and nothing about the assembled block
  makes the orientation obvious.

Before powering it, check continuity across the pump terminals both ways with
the board off: the motor winding in one direction, the diode's forward drop in
the other. A dead short either way means a reversed diode or a bridged lead.

If the pump is mounted through an enclosure wall with the tube head outside and
the motor terminals inside, the block belongs inside with the terminals. Mount it
above the pump rather than beneath it.

The pump is declared in `printer.cfg` as an `[output_pin]`, not a heater:

```
[output_pin pump]
pin: PC8
value: 0
shutdown_value: 0
```

`shutdown_value: 0` stops the pump if Klipper errors out mid-dose. It is
deliberately not a `[heater_generic]` — that requires a temperature sensor, and
Klipper's `verify_heater` watchdog would fault partway through every watering
when commanded heat produced no temperature rise.

The backend doses with `SET_PIN PIN=pump VALUE=1`, a `G4` dwell, then
`SET_PIN PIN=pump VALUE=0`, sent as a single script so the switch-off is queued
on the MCU and a dropped connection cannot strand the pump running.

See [POWER_SYSTEM.md](../POWER_SYSTEM.md) for complete busbar and fusing specifications.

## Wiring the Soil Sensors

Four Adafruit STEMMA soil moisture sensors hang off a passive I2C hub on the Pi's
**Bus 1**. Each needs a unique address; addressing, the `.env` setting and the
per-plant mapping are in [SENSOR_WIRING.md](../SENSOR_WIRING.md).

### Pi header pins

```
Hub red (3.3V) ----> Pin 1   (or pin 17)
Hub blue (SDA) ----> Pin 3   (GPIO 2)
Hub yellow (SCL) --> Pin 5   (GPIO 3)
Hub black (GND) ---> Pin 6   (or any GND: 9, 14, 20, 25, 30, 34, 39)
```

Bus 1 is what `i2cdetect -y 1` queries and what the install script's
`dtparam=i2c_arm_baudrate` applies to. Nothing else in the build touches these
pins — the LED data line is GPIO10 (pin 19) and the water level sensor takes 5V
from pin 2.

**Power the sensors from 3.3V, not 5V.** The STEMMA boards and the Pi's I2C pins
are both 3.3V parts, and the pull-ups discussed below reference whatever the
sensors are fed. Feeding them 5V puts 5V on SDA and SCL through those pull-ups,
which the Pi's pins are not tolerant of.

### Cable length and bus capacitance

The soil sensors hang off a hub tree rather than home runs back to the Pi. As
built:

| Run | Length |
|---|---|
| 4 × sensor drops into the two sub-hubs | 150 mm each |
| Left sub-hub → master hub | 300 mm |
| Right sub-hub → master hub | 400 mm |
| Master hub → Pi | 100 mm |
| **Total** | **≈ 1.4 m** |

The two sub-hub runs do not have to match — they are separate branches, and only
the total matters. The right side needed 400 mm to reach; the left came in at
300 mm.

**Total bus capacitance is what matters, not the longest run**, and it is the sum
of every branch. I2C allows 400 pF; at roughly 60 pF/m that 1.4 m contributes
about 85 pF, plus ~10 pF per sensor pin and a little for the three hub boards.
Call it 135 pF, so about a third of budget. The tree also uses *less* cable than
home running each sensor would.

If your runs differ, redo that sum rather than comparing against the total here —
the figure that matters is the sum of every branch, not the longest one.

**Measured, as a baseline.** A 120 s soak on this layout at 50 kHz, with the
harness open and nothing else in the loom:

```
addr     reads  errors    rate  raw min/mean/max       verdict
0x36       474       0   0.00%  332 / 338 / 345        clean
0x37       474       0   0.00%  322 / 328 / 334        clean
0x38       474       0   0.00%  327 / 332 / 337        clean
0x39       474       0   0.00%  320 / 324 / 328        clean
```

1896 reads, no errors, and a raw spread of only 6-13 counts per address — so the
bus is quiet, not merely working. Worth keeping as the reference point: once the
LED data line and stepper leads are in the loom, a soak that degrades against
this is a routing problem rather than a cable-length or pull-up problem, which
narrows the search considerably.

Too much capacitance slows the rise time of SDA and SCL, so the line has not
reached a valid high when the clock samples it. It does not fail cleanly — you
get occasional NACKs, which surface here as sensors randomly reporting `-1`.

Three things keep it healthy:

- **The I2C clock is set to 50 kHz** by the install script
  (`dtparam=i2c_arm_baudrate` in the boot config, applied after a reboot). Half
  the default speed means twice the time for the line to rise. The sensors are
  read once a minute, so the lost bandwidth costs nothing.
- **Use passive hubs with no pull-up resistors.** Each STEMMA sensor already
  carries 10 kΩ pull-ups; four in parallel with the Pi's built-in 1.8 kΩ is
  already about 1 kΩ, or 3.3 mA, which is at the I2C sink limit. Every hub that
  adds its own drags that lower until the sensors cannot pull the line
  convincingly low. If your hubs have them, remove the resistors rather than
  buying different hubs.
- **Route away from the LED data line and the stepper wiring.** 1.5 m of I2C run
  parallel to an 800 kHz addressable-LED data line will cause more trouble than the
  capacitance ever will. Crossing at right angles is fine; running alongside is
  not. Sharing a few centimetres near the Pi header is harmless.

Verify with a soak test rather than a single read:

```bash
cd /opt/greenthumb && .venv/bin/python -m greenthumb.hardware.soil_sensors --soak 120
```

Clean means zero errors. Under 1% is tolerable. Above that, slow the clock
further, check the hubs for stacked pull-ups, and look at routing. Exit status is
non-zero when any populated address exceeds 1%, so it can gate a scripted check.

## Plumbing layout

Vertical order matters more than anything else about the water path. Top to
bottom: **nozzle, pump, reservoir.**

```
   HIGH POINT  ──────── top of the outlet run
     │      ╲
     │       ╲  falling leg  ──[ level sensor clamps here ]
     │        ╲
     │       NOZZLE  ──────── over the pot
     │
     │   outlet line (rising)
     │
   PUMP  ────────────── above the reservoir water line
     │
     │   suction line, short and steadily rising
     │
   RESERVOIR  ───────── lowest; water line below the nozzle
```

### Nozzle above the reservoir water line

This is the safety-critical one. A siphon can only run downhill, so with the
tank at the bottom a failed tube seal or a popped fitting means nothing happens
— the water has nowhere to go. Invert it and the same failure drains the whole
tank onto the floor.

What makes this safe rather than merely lucky is that **a stopped peristaltic
pump is a closed valve**: its rollers occlude the tube, so there is no open path
even when it is off. That is also why raising the reservoir would not let you
drop the pump — you would just be relying on that same occlusion to hold back a
gravity feed permanently instead of only while idle.

### Pump above the water line

The pump does not need to sit below the water; peristaltic pumps self-prime.
The cost is that the pump inlet becomes the *highest* point of the suction line
and so the first place to go dry if prime slips. That is a non-event in itself —
prime recovers in seconds — but it decides where the level sensor goes.

Keep the suction line short and steadily rising, with no high spots to trap air.
Suction joints are far less forgiving than pressure joints: a pinhole that would
never drip on the outlet side will break prime on the inlet side.

### Reservoir, and the suction tube

A tank with a **bottom or side bulkhead outlet** is the tidier option: the tube
leaves at the lowest point and stays wet whenever there is water above it. Worth
looking for — *bulkhead fitting*, *hydroponic reservoir with drain*, or any tank
sold with a spigot. A plain tank plus an aftermarket bulkhead fitting works too.

**A tube simply dipped in from the top is fine.** It needs no fittings and
pumps identically. Two things to watch, both about prime rather than sensing:

- **The rim crossing is a high spot**, which is exactly what a suction line is
  not supposed to have. Keep it as low as you can — through a hole in the lid
  rather than over the edge — and keep the whole run short.
- **Weight the intake end** so it stays at the bottom. A tube that floats up as
  the tank drains starts sucking air well before the tank is empty.

Note that with a dipped tube there is nowhere useful to sense *reservoir level*:
every reachable section of tube sits above the water line. That is why the
sensor lives on the outlet instead, described next.

## Wiring the Water Level Sensor

A non-contact liquid sensor (CQRobot CQRSENYW001 or similar) clamped around the
**outlet** tube confirms that a dose actually delivered water, instead of the
system running the pump and logging a dose that delivered nothing.

**Clamp it on the falling leg — after the high point, before the nozzle.**

### Why it verifies rather than blocks

This sensor does not gate watering. It cannot: the falling leg drains into the
pot after every dose, so it reads dry whenever the pump is idle, and a pre-check
would refuse every watering forever.

Instead the software starts the pump, watches the sensor a few seconds in, and
records whether water arrived. Running a peristaltic pump dry for a few seconds
is harmless, so there is nothing to protect against by checking first. What you
get in exchange is a better question answered: not "is water available at the
inlet" but "did water reach the plant" — which also catches a clog, a kink, a
split pump tube, or a pump turning with nothing engaged.

A dose that delivers nothing is logged as a warning, flagged on the history chart in the Sensors tab
as a solid red marker, and reported in the status bar. Nothing is blocked; the
next dose runs and re-checks, so a refilled tank clears the condition by itself.

### Where exactly to clamp it

The placement is fussier than it looks, because half the outlet run holds water
permanently:

- **Rising leg (pump → high point): stays full.** The stopped pump seals the
  bottom and water cannot climb over the peak to escape. A sensor here reads wet
  forever and tells you nothing.
- **Falling leg (high point → nozzle): drains.** It siphons into the pot when
  the pump stops and refills on the next dose. This is the only section with a
  signal in it.

**Do not fit an anti-drip fitting on the falling leg.** It exists to stop
exactly the drain-back this depends on. The cost of leaving it out is a few mL
dribbling into the pot it was already headed for.

Sizing: about 7 mL of 4 mm ID tube fills in roughly four seconds at the pump's
flow rate, against a 500 ms sensor response and a 60-second dose, so the timing
is not tight. `delivery_check_delay_seconds` in `greenthumb/config.py` sets how
long to wait before the first look; raise it if the falling leg is unusually
long.

**Set the board's dial switch to 3.3V output before wiring.** The SKR's endstop
inputs are 3.3V; at the 5V setting the sensor would overdrive the pin. With it at
3.3V the signal wire connects directly, no divider or level shifter.

```
Sensor VCC (red)   ----> 5V (Pi header pin 2, or the busbar 5V rail)
Sensor GND (black) ----> common ground, shared with the SKR
Sensor OUT (green) ----> Y-STOP signal pin (PC1)
```

Z-STOP (PC2) is the spare if Y-STOP is taken. Both are free because the
`stepper_y` and `stepper_z` sections in `printer.cfg` are placeholders — a
single-axis gantry still needs all three for `kinematics: cartesian` — and their
endstop pins are pointed at the unused E0-STOP and PROBE headers to keep them out
of the way. Leave them there: pointing `stepper_y` back at PC1 collides with this
sensor, and Klipper rejects the whole config with "pin PC1 used multiple times in
config" rather than picking one.

The sensor senses through 0-13 mm, so
check your tube's outer diameter falls inside that, and adjust the sensitivity
pot if the board has one.

**Confirm polarity before trusting it.** Bench the sensor first, powered at 5V
with the dial at 3.3V, and read the output on a full tube and an empty one —
allow 500 ms between changing the tube and reading, that is its response time.
Then check Klipper agrees:

```bash
python3 /opt/greenthumb/deploy/pi/send-gcode.py QUERY_FILAMENT_SENSOR SENSOR=water_supply
```

A full tube must report detected. If it reads backwards, change `switch_pin` to
`^!PC1` in `printer.cfg` and re-run the install script rather than rewiring.

Once confirmed, set `WATER_SENSOR_ENABLED=true` in `/opt/greenthumb/.env` and
restart the API.

Enabling it changes nothing about when watering happens — it only adds the
check afterwards. Three outcomes are recorded per dose: **delivered** (the line
read wet during the run), **not delivered** (it read dry throughout, logged as a
warning and drawn in red on the chart), and **unknown** (the sensor never
answered). Unknown is deliberately distinct from a failure: "we did not look" and
"we looked and saw nothing" are different problems.

## Wiring the LED Strip

Supported strips, selectable as **LED strip type** in the Settings tab:

All 12V. A 5V strip is deliberately not supported: sixty 5V pixels pull about
3.6A, well past what the 12V-to-5V converter can give on top of the Pi.

| Chip | Supply | Pixels | Pads | Notes |
|---|---|---|---|---|
| **WS2811** | 12V | one per **3** LEDs | 3 | **Default.** Set LED count to LEDs / 3 |
| WS2815 | 12V | one per LED | 4 | 4th pad is a backup data line |
| GS8208 | 12V | one per LED | 3 | Often sold as "12V WS2812B" |

They use different bit timing, so picking the wrong one gives no light or
garbage rather than a subtle colour shift. **To tell 12V strips apart, check the
cut marks.** Cuttable between every LED means one pixel per LED (WS2815 /
GS8208); cuttable only every third LED means WS2811.

```
12V Busbar (+) --[2A Fuse]--> Strip +V     (12V strips; a 5V strip needs its
Busbar GND -----> Strip GND --+-- Pi GND    own 5V supply, not the DC-DC)
Pi GPIO10 (pin 19, MOSI) -----+-> [74AHCT125 level shifter] --> Strip DIN
```

The 2A fuse is what keeps a shorted solder joint at the strip's input end from
taking down the Pi and the motion board with it. Sizing and the 5V case are in
[POWER_SYSTEM.md](../POWER_SYSTEM.md).

**The data pin must be GPIO10 (header pin 19).** The driver clocks the waveform
out of the SPI peripheral, which only exists on that pin. This avoids needing
root, which the usual PWM/DMA approach requires.

Two things that look like software faults but are not:

- **Pi ground must tie to the supply ground.** The data line is measured against
  ground; without a shared reference the strip sees nothing. Most common failure.
- **Use a level shifter.** These chips want logic high at roughly 70% of their
  supply, and the Pi only swings to 3.3V. Some strips tolerate it; flicker or junk
  on the first few pixels is this, not a bug.

**Do not power the strip from the Pi.** The supported 12V strips draw around
1.2-1.5A at 60 LEDs full white, and a 5V strip of the same length would pull
about 3.6A -- which is one of the reasons 5V is not supported. Either way the
strip's supply must not touch the Pi's pins.

If red and green come out swapped, change **LED colour order** in settings.
Selecting a strip type resets that order to the one that chip normally uses, so
choose the type first and adjust the order afterwards.

## Harness routing

Dress the wiring as **two groups that do not run alongside each other**:

```
  POWER / MOTION  (may share one bundle)      SIGNAL  (separate runs)
  ────────────────────────────────────        ──────────────────────────
  stepper motor leads                         I2C soil sensor tree
  pump power (HE0 pair)                       LED data line to GPIO10
  X endstop pair (X-STOP)                     camera ribbon
```

Crossing between groups at right angles is fine. Running parallel for any
distance is what causes trouble.

### Why the first group can share a bundle

The aggressor is the stepper leads, not the pump. With `stealthchop_threshold:
999999` the TMC2209 sits in stealthChop permanently — roughly 23 kHz voltage PWM
at `run_current: 0.7` — and those leads stay active even with the carriage
parked, because holding current is chopped too. The pump is the milder one: a
0.2-0.3A brushed motor with two switching events per dose.

The endstop would normally be the victim, except that **the way it is wired keeps
it out of trouble**. `endstop_pin: ^PC0` with an NC switch means the untriggered
state is *switch closed*, so PC0 is tied to ground through a few ohms of contact
resistance for the whole approach. Capacitive coupling from a 12V bundle cannot
lift that to a logic high. The high-impedance state — the MCU's internal pull-up,
tens of kΩ — only exists *after* the switch trips, by which point homing has
already stopped. Klipper also wants `endstop_sample_count` consecutive agreeing
samples (4, 15 µs apart) before it believes a transition, which filters anything
shorter than about 60 µs.

Nothing in the bundle is above 12V, so there is no isolation or insulation
concern, and at 0.7A and 0.3A bundling derates nothing worth calculating.

### Keep each pair paired

Loop area is what couples, and a pair carrying equal and opposite current has
almost none. So:

- **Use the stock 4-conductor motor cable.** Don't pull individual conductors
  into different parts of the bundle; keep each coil's two wires together.
- **Keep the endstop's two wires together**, twisted if convenient. One wire in
  the bundle with its ground returning by some other path is the one arrangement
  that would actually pick up noise.

### The NC wiring is load-bearing

When `QUERY_ENDSTOPS` reads inverted, the tempting fix is to add `!` to the pin
and move on. It does make the reading correct — `^!PC0` is the normally-open
config — but it costs both properties this section depends on. Wired NO, the pin
floats on the internal pull-up for the whole homing approach instead of being
clamped to ground, which is the susceptible arrangement in a shared bundle; and a
broken wire becomes indistinguishable from a healthy untriggered switch.

So if the reading is backwards, re-trace the switch for the pair that is closed
with the lever released and move the signal wire there, rather than flipping the
config.

### The one adjacency worth watching

The water level sensor is the only signal input that gets **read while the pump is
running**, and its wire naturally follows the same tube as the pump leads, so the
two are hard to separate. That is acceptable: the sensor board drives its output
actively and at low impedance, unlike a passive switch.

If delivery checks ever start reading dry on a dose that visibly watered, suspect
the pump rather than the routing. Brushed-motor commutation noise is broadband and
continuous, and the flyback diode does nothing about it — the diode only clamps
the turn-off spike. Fit a **100 nF ceramic across the pump terminals**, alongside
the 1N5822. Note that this noise is conducted onto the 12V rail regardless of how
the wires are dressed, which is why re-routing is not the fix here.

### Signal runs

The I2C tree is the genuinely sensitive bus in this system: open-drain, about 1 kΩ
of effective pull-up, and deliberately slowed to 50 kHz. It fails as intermittent
`-1` readings rather than cleanly, so give it its own route and verify with a soak
rather than a single read — see
[Cable length and bus capacitance](#cable-length-and-bus-capacitance). Soak it
after any change to how the harness is dressed, not just after changing a cable:

```bash
cd /opt/greenthumb && .venv/bin/python -m greenthumb.hardware.soil_sensors --soak 120
```

The LED data line belongs in this group as an aggressor rather than a victim —
800 kHz edges that the I2C run in particular should stay away from.

## Troubleshooting

If the installation script disconnects or fails, use these commands to diagnose:

**Check service status:**
```bash
sudo systemctl status klipper
sudo systemctl status greenthumb-api.service
sudo systemctl status nginx
```

**Check Klipper logs:**
```bash
tail -50 ~/klipper_logs/klippy.log
```

**Check the API logs:**
```bash
sudo journalctl -u greenthumb-api.service -n 50
```

**Verify directories exist:**
```bash
ls -la /opt/greenthumb/
ls -la ~/printer_data/config/
```

**Restart services if needed:**
```bash
sudo systemctl restart klipper
sudo systemctl restart greenthumb-api.service
sudo systemctl restart nginx
```

If the install script fails midway, you can safely re-run it — it checks for existing installations and skips already-completed steps.

## Safety

- Keep the first gantry tests very short.
- Confirm the gantry can move freely before sending motion commands from the UI.
- Use a physical e-stop or kill switch for early hardware testing.
