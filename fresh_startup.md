# Fresh startup

From a blank SD card to a planter that waters on its own. Follow it in order:
each step assumes the one before it worked.

This is the short route. The wiring, the reasoning behind each choice and the
recovery steps are in [deploy/README.md](deploy/README.md), and this guide links
there where you need more.

## What you need first

- A Raspberry Pi with a microSD card, on your network
- An SKR Mini E3 V2 or V3 board, wired to the gantry motor and X endstop
- The pump, wired to the SKR's HB connector with its fuse and flyback diode
- The four soil sensors on their hub, each at its own address (see
  [SENSOR_WIRING.md](SENSOR_WIRING.md))
- A computer with [Raspberry Pi Imager](https://www.raspberrypi.com/software/)

Wire the hardware before step 5 if you can. The installer detects the SKR and
reads the sensors, and it reports what it cannot find. Re-running it later is safe.

## 1. Flash the SKR board (once per board)

Skip this if the board has already been flashed.

1. Copy your board's firmware to the root of a micro-SD card:
   `deploy/klipper/skr-mini-e3-v2/firmware.bin` for a V2, or
   `deploy/klipper/skr-mini-e3-v3/firmware.bin` for a V3. Check the version
   printed on the board: the wrong one won't boot. The file must be named
   exactly `firmware.bin`.
2. Power the SKR off, put the card in the SKR's card slot, and power it on.
   On 12V, or for a V3, from a laptop's USB with a jumper across the two
   **SW_USB** pins. Remove that jumper before the board goes into the planter.
3. Wait for the second red light to start and then stop. That is the flash.
4. The bootloader renames the file to `FIRMWARE.CUR` when it succeeds.

## 2. Flash the Pi

In Raspberry Pi Imager:

- **OS:** Raspberry Pi OS (64-bit)
- **Hostname:** `herman`. With two planters on one network, give each its own
  name, or rename one later under **Network name** on the Calibration tab.
  Otherwise whichever boots first gets `herman.local` and the other becomes
  `herman-2.local`.
- **Username:** `pi`. This is not optional. The service, the Klipper paths and
  the installer all assume `/home/pi`.
- **SSH:** enabled
- **WiFi:** your network and country

Boot it and give it about two minutes.

## 3. Connect

```bash
ssh pi@herman.local
```

If `herman.local` does not resolve, use the Pi's IP address from your router.

## 4. Get the code

```bash
sudo apt update
sudo apt install -y git
sudo mkdir -p /opt/greenthumb
sudo chown pi:pi /opt/greenthumb
git clone --depth 1 https://github.com/nmblood91/herman.git /opt/greenthumb
```

The repo is `herman` but it goes in `/opt/greenthumb`. That is deliberate.

Do the clone **without `sudo`**. A root-owned checkout breaks every later
`git pull`.

## 5. Run the installer

Plug the SKR into the Pi by USB first, so the installer can find it.

```bash
sudo bash /opt/greenthumb/deploy/pi/install-green-thumb.sh
```

It takes about 6 minutes on a Pi 4 and 15 on a Pi 3 A+. It enables I2C and SPI, installs
Klipper, installs the starter soil and plant libraries, builds the web app, and
starts three services: `klipper`, `greenthumb-api` and `nginx`.

Use `bash` and `sudo` exactly as written. The script is not marked executable
and it needs root.

It ends with "GreenThumb install complete" and prints the address to open.

**Reboot after the first run**, even if it does not ask. It changes the I2C clock
and that only takes effect after a reboot. If it says I2C or SPI is missing,
reboot and run the same command again:

```bash
sudo reboot
# after it comes back
ssh pi@herman.local
sudo bash /opt/greenthumb/deploy/pi/install-green-thumb.sh
```

The second run is much quicker, since most of the work is already done.

**If it says no Klipper device was found**, the SKR is not visible. Check the USB
cable and that the board is powered, then run the installer again.

## 6. Check it came up

Open **http://herman.local** in a browser. If the app loads, the install
worked.

For a closer look, or if something isn't working:

```bash
sudo systemctl status klipper
sudo systemctl status greenthumb-api.service
sudo systemctl status nginx
```

All three should say `active (running)`. Then read the sensors directly:

```bash
cd /opt/greenthumb && .venv/bin/python -m greenthumb.hardware.soil_sensors
```

Four numbers means four working probes. A probe that is missing or unplugged
shows `-1`.

After any cabling change, check the bus is reliable and not just working:

```bash
cd /opt/greenthumb && .venv/bin/python -m greenthumb.hardware.soil_sensors --soak 120
```

Zero errors is clean. Under 1% is tolerable.

The API docs are at `http://herman.local/docs`.

## 7. Check the gantry before it moves anything

These are in [deploy/README.md](deploy/README.md) under *Wiring the X Endstop*.
Do them before the first home, because a wrong motor direction drives the
carriage into the end of the rail at full homing speed.

1. **Endstop.** Released it must read `stepper_x:open`; held down,
   `TRIGGERED`.

   ```bash
   python3 /opt/greenthumb/deploy/pi/send-gcode.py QUERY_ENDSTOPS
   ```

   Y and Z read `TRIGGERED`. Ignore them.

2. **Motor direction.** On the **Calibration** tab, under **Motor direction**:
   slide the carriage to mid-rail by hand, press **Turn motor**, and say which
   way it went. If it moved away from the switch, the app reverses the
   direction and restarts Klipper; test again until it moves toward the
   switch. Nothing homes until this passes, so the Home button stays grayed
   out until then. The correction is saved in
   `~/printer_data/config/motor-direction.cfg`, which the installer never
   rewrites, so it survives reinstalls.

3. **Home.** Use the app's home control. The carriage parks at X0.

4. **Travel.** The rail is 1000 mm, but the carriage can move through 890 mm of
   it, and `position_endstop` and `position_max` ship as 890 for this build. On
   a different build, measure your own and set both to it, plus
   `GANTRY_TRAVEL_MM` in `.env`. Do not jog to X0 until you have.

## 8. Mix the soil and calibrate the sensors

**Mix the soil.** Herman ships with three soil profiles, each a recipe made from
hardware-store ingredients. [SOIL_PROFILES.md](SOIL_PROFILES.md) has the
recipes and which plants go in which:

- **Rich & Retentive Mix** — vegetables, leafy greens, herbs, thirsty houseplants
- **Fast-Draining Mix** — cacti, succulents, drought-tolerant houseplants, woody herbs
- **Ultra-Coarse Epiphytic Mix** — orchids, aroids, jungle epiphytes

**Air readings, once.** Hold all four probes in open air, clean and dry, and
press **Calibrate dry (air)** on the **Calibration** tab, or run:

```bash
cd /opt/greenthumb && .venv/bin/python -m greenthumb.hardware.soil_sensors --calibrate dry
```

Each probe's air reading is its 0% water point, which wilting point is worked
out from. It is also a probe check: one that reads far from the others needs a
look.

**Field capacity is already set.** Each built-in soil profile ships with a
default field capacity reading, so nothing else needs measuring. Wilting point
is worked out for each pot from that reading, its probe's air reading and the
soil profile's percentages.

If a mix waters too early or too late, measure your own field capacity: in the
Soil Profile Editor under **Plants and Soil**, pick the soil profile and a pot
whose probe sits in that mix. Soak that pot through, let it drain for 24 hours,
and press **Measure field capacity**. A soil profile you add yourself needs this
before its pots are watered.

## 9. Set up the pots

In **Plants and Soil**:

1. **Plant.** Load a plant profile onto each pot from its card, or write your
   own in the Plant Profile Editor. Loading one also sets the pot's soil profile
   to the one the plant prefers, so pot each plant in that mix (see
   SOIL_PROFILES.md).
2. **Soil.** If a pot is filled with something else, choose that soil profile
   on its card instead. The card will note that the plant prefers another.
3. **Position.** Jog the carriage until the nozzle is over the pot, then press
   **Use current position** on that card. It fills the field without saving, so
   you can check the number first. It refuses an unhomed gantry.

## 10. Measure the pump

The pump's real flow rate decides how long it runs to deliver a given volume,
and the shipped 1.1 mL/s was measured on the reference build. Your tubing and
lift may differ, so it is worth checking.

On the **Calibration** tab, under **Pump**, press **Run calibration** (60 s) with
the nozzle over a cup on a scale, enter the milliliters that came out, and press
**Save flow rate**. Throw away the first run, since it fills the tube. The
measurement overrides the value in `.env`.

## 11. Turn on automatic watering

Leave it off until the pump has been tested by hand and the flow rate is
measured. Then enable it in the **Settings** tab. The switch persists in
`data/state.json` and wins over `AUTO_WATERING_ENABLED` in `.env`.

Optional extras, each covered in [deploy/README.md](deploy/README.md):

- **LED strip:** pick the chip type in the app before the color order.
- **Camera:** the service account needs the `video` group:
  `sudo usermod -aG video pi`.
- **Homing:** once the endstop is confirmed and the rail is clear, switch on
  *Home after startup* and *Hourly auto-patrol* in the Automation tab. Both
  start off so the arm never moves before you are ready for it.
- **Quiet hours:** hold automatic watering and the hourly patrol overnight.

## Day-to-day

Update:

```bash
cd /opt/greenthumb
git pull
sudo systemctl restart greenthumb-api.service
```

Never `sudo git pull`. If the change touches `frontend/`, the systemd units, the
nginx config or `printer.cfg.example`, re-run the installer instead. A pull
alone does not rebuild the web app or reapply those files.

Re-running the installer regenerates `printer.cfg` from the template. It backs up
any differing copy to `~/printer_data/config/` first and prints the `diff`
command, so a hand-tuned `position_endstop` is recoverable.

## When something is wrong

```bash
sudo journalctl -u greenthumb-api.service -n 50   # the API
tail -50 ~/klipper_logs/klippy.log                # Klipper
sudo journalctl -b -1 -n 80 --no-pager            # the end of the last boot
sudo systemctl restart klipper greenthumb-api.service nginx
```

Read `klippy.log` before guessing. A bad pin name makes Klipper reject the whole
config, which looks like the entire machine being dead.

More in [deploy/README.md](deploy/README.md), under *Troubleshooting* and
*Recovering a diverged checkout*.

## Keep safe

- Keep the first gantry tests short, and make sure the carriage moves freely
  before commanding motion from the app.
- Have a physical e-stop or power switch within reach.
- Never open the pump's junction block while the SKR is powered. The positive
  side is live whenever the board is.
