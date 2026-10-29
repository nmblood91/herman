# SKR Pico

The BTT SKR Pico V1.0 as Herman's motion board, in place of an SKR Mini E3.
It powers the Pi from its own 5 V regulator and talks to it over the Pi's GPIO
UART, so one 5-wire cable replaces both the DC-DC converter and the USB cable.

**Status: supported in software, not yet proven on the planter.** The firmware
builds and is checked by `tests/test_firmware_pin.py`, the printer.cfg it gets
is checked against Klipper's stock Pico config by `tests/test_printer_cfg.py`,
and the installer sets up the UART. None of it has run on hardware yet. The
checks in *First power-up* below are what prove it.

## Why it might end the reset hunt

The Pi 3 + SKR Mini E3 V3 resets ([pi/PI3A_RESET_HANDOFF.md](pi/PI3A_RESET_HANDOFF.md))
are tied to two things the Pico takes away:

- **The USB link.** Klipper resets a USB board when it connects and the board
  re-enumerates. Over UART nothing re-enumerates, and `restart_method: command`
  restarts the firmware without touching the bus.
- **Two supplies with grounds joined through a USB cable.** On the Pico there is
  one supply. The Pi's 5 V and ground both come from the board that the motors
  and pump are on, over the same cable, so no ground loop runs through a signal
  cable.

What it does not fix is a weak 5 V. That moves from the DC-DC converter to the
Pico's regulator, which is covered next.

## Power: what the board actually delivers

From BTT's schematic (`Hardware/BTT SKR Pico V1.0-SCH.pdf` in
[bigtreetech/SKR-Pico](https://github.com/bigtreetech/SKR-Pico)):

- **Regulator:** a TI TPS5450 buck converter. It's a 5 A part, running from the
  board's 12 V input.
- **Output fuse:** 3.5 A (F4), between the regulator and the 5 V rail.
- **Set point:** about **4.99 V**. The feedback divider is 10 kΩ over 3.24 kΩ on
  a 1.221 V reference, which is 1.221 × (1 + 10/3.24) = 4.99 V. With the
  reference's ±1.5% that's 4.92–5.07 V at the regulator, before the fuse and
  the cable to the Pi.

So the Pi sees roughly 4.9–5.0 V. **That is below the "5.1 V minimum" written
into BOM.md and POWER_SYSTEM.md after the 4.90 V micro-USB converter failed**,
and those edits are still uncommitted, waiting on exactly this kind of result.
The Pico's path is better than the converter's in ways that number doesn't
show:

- a real regulator with tight load regulation, where the cheap module sagged
  as load rose
- 330 µF of bulk capacitance on the output
- no micro-USB connector and no Pi input polyfuse in the path
- two 5 V wires in the cable

None of that is proof. **`vcgencmd get_throttled` is the test**, as it was for
the converter.

A Pi 3 draws well under 1 A here. A Pi 4 with a USB camera can approach 2 A,
which is within the regulator and the fuse but leaves the least margin of any
configuration. Test that one separately if the camera tier is going to run on
a Pico.

**Never power the Pi from its own USB port at the same time.** The Pico's 5 V
reaches the Pi's 5 V rail directly through header pins 2 and 4. A second supply
on the Pi's USB input would be wired straight against it.

## Wiring

### Pi link: one 5-wire cable

BTT's UART wiring picture shows a 5-wire cable from the Pico's 5-pin header
(labeled `IO0 IO1 GND 5V 5V`, on the left edge next to FAN1) to the first five
pins of the Pi header's outer row:

| Pico | Pi header | Pi function |
|---|---|---|
| 5V | pin 2 | 5 V in |
| 5V | pin 4 | 5 V in |
| GND | pin 6 | ground |
| IO1 (RP2040 UART0 RX) | pin 8 | GPIO14, TXD |
| IO0 (RP2040 UART0 TX) | pin 10 | GPIO15, RXD |

TX goes to RX, both ways. If a cable didn't come with the board, five
female-to-female jumpers do the same job, crossed as in the table.

**Move the soil-sensor hub's ground off pin 6**, which this cable takes. Pin 9
or 14 works the same, as any ground pin does (see *Wiring the Soil Sensors* in
[README.md](README.md)). The hub's 3.3 V (pin 1), SDA and SCL (pins 3 and 5),
and the LED strip's data and ground (pins 19 and 20) are not affected.

### Gantry and pump

Every connector Herman uses on the Mini E3 is on the Pico under the same name.
The installer writes the matching pins, mapped in
[klipper/skr-pico/pins.map](klipper/skr-pico/pins.map):

| What | Connector | Pico pin |
|---|---|---|
| Gantry motor | X | gpio11 step, gpio10 dir, gpio12 enable |
| Home switch | X-STOP (`IO4 GND 5V`) | gpio4: signal and GND only, leave 5V empty |
| Pump | HB screw terminal (`IO21 12/24V`) | gpio21 |
| 12 V in | POWER | — |

The pump wiring is the same as on the Mini E3, and so is the 1 A fuse on the
pump's positive lead, upstream of the flyback diode (see
[README.md](README.md)): HB's `12/24V` terminal is the board's input rail, and
`IO21` is the low-side MOSFET.

**Leave the X-DIAG jumper off.** The Pico's sensorless-homing jumpers connect a
driver's DIAG output to that axis's endstop pin, and BTT notes that an external
endstop can't be used with one fitted. Herman homes on a real switch.

**Leave the USB Power jumper off.** It feeds the board from its USB-C port, and
with 12 V connected, BTT says to remove it.

## Flashing

`deploy/klipper/skr-pico/firmware.uf2` is built for the RP2040 with no
bootloader, talking over UART0 on GPIO0/GPIO1 at 250000 baud. These match
BTT's Klipper instructions, built from the commit in `KLIPPER_COMMIT`.

1. With the board powered off, fit a jumper on the **Boot** pins.
2. Connect the Pico's USB-C to a computer and power it, either from 12 V or
   with the USB Power jumper fitted.
3. Press **Reset**. A USB drive named `RPI-RP2` appears.
4. Copy `firmware.uf2` onto it. The board reboots by itself and the drive goes
   away.
5. Remove the Boot jumper (and the USB Power jumper, if you fitted it) and
   press Reset.

The USB-C port stays the recovery path whatever firmware is on the board. The
Boot jumper starts the RP2040's boot ROM, which flashing never touches, so a bad
build can't lock the board out, and no SD card is involved.

## Installing

On a fresh Pi, or one moving over from a Mini E3:

```bash
sudo bash /opt/greenthumb/deploy/pi/install-green-thumb.sh --board skr-pico
sudo reboot
```

The installer remembers the board, so later re-runs need no option. For the
Pico it:

- writes `enable_uart=1` and `dtoverlay=disable-bt` to `config.txt`
- removes the serial console from `cmdline.txt`
- disables `hciuart`
- adds `pi` to `dialout`
- points Klipper at `/dev/ttyAMA0`

Klipper can't reach the board until the reboot, so the installer skips its
connection check and asks for the reboot instead.

**Bluetooth is turned off.** On a Pi 3 or 4, the good UART (the PL011) is wired
to Bluetooth, and the header gets the mini-UART, whose baud rate follows the
core clock. The installer leaves the Pi 3's core clock unpinned on purpose,
after the A+ reset with it pinned. `disable-bt` gives the PL011 to the header
instead, so Klipper's link doesn't depend on the clock at all. Nothing uses
Bluetooth today. BLE provisioning ([ROADMAP.md](../ROADMAP.md)) would need it
back, which means `miniuart-bt` and, for that, a pinned core clock. That's a
decision for when provisioning is built, and it affects Bluetooth, not the
motion link.

**Moving between boards clears the motor direction test.** A saved direction
override names a pin on the old board, which Klipper on the new one can't
parse, and the motor is plugged into a different connector anyway. So the
installer removes the override and clears the test's pass. Nothing homes until
the test on the Calibration tab has been run again.

## First power-up

1. **Before connecting the Pi,** power the Pico from 12 V and measure across
   its `5V` and `GND` header pins with a multimeter, if you have one. Expect
   about 4.9–5.1 V.
2. Connect the Pi and boot it. After a few minutes idle, `vcgencmd
   get_throttled` should be `0x0`.
3. Load the Pi with the four-`yes` loop for a minute (see
   [pi/PI3A_RESET_HANDOFF.md](pi/PI3A_RESET_HANDOFF.md)), then check
   `get_throttled` again.
4. Run the installer with `--board skr-pico` and reboot.
5. Check `sudo systemctl status klipper`. The app's status bar should show the
   motion board connected.
6. Run the motor direction test on the Calibration tab, then home.
7. Run the pump from the Controls tab and confirm it stops.
8. Run `get_throttled` once more after homing and watering. A non-zero result
   means the Pico's 5 V is sagging under real load, and that has to be dealt
   with before this board can replace the converter.

**Not done until that passes:** BOM.md, POWER_SYSTEM.md and PRINTED_PARTS.md
still describe the Mini E3, the DC-DC converter and its Wago run. The Pico has
a different footprint (85 × 56 mm, Pi-sized) from the Mini E3, so the
electronics holder needs a new mount.
