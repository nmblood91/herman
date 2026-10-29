# Pi 3 A+ resets and Wi-Fi drops: handoff for reading its SD card

For a Claude Code session on an Ubuntu machine, with the A+'s SD card in a
card reader. The goal is to find out from the card why the A+ keeps dropping
off the network. The planter software itself is not suspected.

## Rules for this session
- **Mount the card read-only and never write to it.** It is the evidence.
  Ask before running anything with `sudo`.
- **Do not print the Wi-Fi password.** If you look in
  `/etc/NetworkManager/system-connections/`, show the SSID and settings, not
  the `psk=` line.

## The hardware
- **Raspberry Pi 3 Model A+:** 512 MB RAM, Raspberry Pi OS 64-bit, headless,
  hostname `herman3a`, on Wi-Fi only (the A+ has no Ethernet port).
- **Power:** a 12 V supply, then a DC-DC converter with a USB output (sold as
  "stable 3 A, for Pi"), then a micro-USB lead to the Pi.
- **Motion board:** a BTT SKR Mini E3 V3 on the Pi's only USB-A port, running
  Klipper. Klipper on the Pi runs from `~/klippy-env`. The SKR's SW_USB jumper
  is **off**, so the SKR does not draw power from the Pi.
- **LED strip:** WS2811, data on header pin 19 (SPI MOSI), ground on pin 20.
- **Similar setup on a Pi 4:** the same planter and supply chain run on a
  Pi 4 with no resets, but with an **SKR Mini E3 V2**. The A+ has the V3
  (`stm32g0b1` in the Klipper log), so the Pi 4 does not clear the board.

## What happened (2026-10-26)
1. With `core_freq=250` in `config.txt`, a reboot hung with the red and green
   LEDs on solid. After a power cycle the Pi booted and ran the LED rainbow
   (so the planter software had started) but was unreachable over SSH and the
   web page. Removing `core_freq=250` did not bring the network back.
2. The card was reflashed. The installer now writes `core_freq=400` and
   `core_freq_min=400` for a Pi 3 (check what is actually in `config.txt`).
   **Update 2026-10-27:** resets continued with the 400 pin, with no
   under-voltage flagged but the 60 °C soft limit hit (`throttled=0x80000`).
   The installer no longer pins a Pi 3, and comments out an existing pin.
3. During the install, SSH dropped twice at "Verifying Klipper connection".
   That is the heaviest point of the install: Klipper compiling its C helper
   on all cores while the SKR connects. Afterwards `uptime` showed **4 and 8
   minutes**, so the whole Pi had reset; it was not just the Wi-Fi dropping.
4. A logger wrote `vcgencmd get_throttled` and the core voltage to
   `~/power.log` once a second. It ran clean, `throttled=0x0`, up to the
   last line (12:10:08), then stopped with no warning. Core voltage switched
   normally between 1.375 V and 1.2 V.
5. The install finished on a later attempt. Klipper reached the board fine
   ("Configured MCU 'mcu' (1024 moves)"). Memory was fine: 238 MB available,
   swap unused.
6. Later, while **idle**, the Wi-Fi was gone again. That is the event to
   explain.

## What happened (2026-10-27)
Fresh 64-bit card, persistent journal on, installer run several times.
1. **The Pi reset at the Klipper step on every run.** Each previous boot's
   journal just stops: no shutdown, no under-voltage, no Oops or panic, no
   `mmc0` (SD card) errors. The last lines are the Klipper environment check;
   writeback can lose the last ~30 s, which covers starting Klipper.
2. **Not CPU load.** The npm build and the `pip install` of Klipper's
   requirements finished on the same runs.
3. **Not the core clock or heat.** With `core_freq` unpinned and the Pi
   rebooted, it still reset at the same step, peaking at 51 °C.
4. **Not Klipper's C helper compile.** Klipper compiled `c_helper.so` on its
   own at boot (02:01) and the Pi stayed up.
5. **Not Klipper itself.** With the SKR's USB unplugged, Klipper ran and
   retried the serial port with the Pi up.
6. **Plugging in the SKR's USB reset the Pi.** That is the trigger.
7. **A reset can leave empty files behind.** Files written in the last ~30 s
   reach the card empty: `cffi` in `~/klippy-env` came back with no `FFI`
   after one, and only a fresh venv plus `sync` fixed it. Expect the same in
   anything else written just before a reset.
8. Side findings, not the reset:
   - The Wi-Fi chip's own bus failed and recovered under load
     (`mmc1: Controller never released inhibit bit(s)`, `brcmf_sdio_isr:
     failed backplane access`), 2½ minutes before one reset. That fits
     brief supply dips.
   - The router sends `WNM: Disassociation Imminent` (band steering or mesh
     roaming). A likely cause of the idle Wi-Fi drops; fixed at the router.
     The installer now turns Wi-Fi power saving off as well.
   - The `klipper` unit was found **masked**, which nothing in the repo
     does. The installer now unmasks it before writing the unit.

## What happened later on 2026-10-27
- **A Pi 3 B+ also reset at "Verifying Klipper connection"**, on the same
  12 V supply and DC-DC converter as the A+. The B+ has a USB hub chip and a
  stronger input stage, so **the A+ board itself is now unlikely**. What the
  two Pi 3s share and the Pi 4 does not: a micro-USB power input (and its
  lead), and possibly the SKR Mini E3 V3 (confirm which SKR the B+ had).
- **The Pi 4 has its own converter**, the same make and look but with a
  USB-C output. So the Pi 4 working does not clear the micro-USB unit the
  Pi 3s share: that unit, or its built-in lead, could be the weak part.

## Inline USB meter readings (2026-10-28)
The meter sits between the converter's USB output and the Pi. Its voltage
reads true; its current reads low below about 1 A (a Pi 4 at full load showed
0.32 A, about 1.6 W against the 5-6 W it draws), though it read a phone's
1.5 A charge correctly. Use its current only to compare one moment with
another, not as a figure.

| Converter | Board | Rest | Full load (4 cores) |
|-----------|-------|------|---------------------|
| USB-C (the Pi 4's) | Pi 4 B Rev 1.5, herman4 | 5.10 V | 5.05 V |
| Micro-USB (shared by both Pi 3s) | Pi 3 | **4.90 V** | not yet |

- **The micro-USB converter starts 0.2 V low**, at 4.90 V with almost no
  load, under the 5.1 V a Pi 3 wants. Little is left before the Pi's
  4.63 V under-voltage line, and a dip too fast to be flagged can go below
  the point the Pi resets at. This is the part both Pi 3s share and the Pi 4
  does not.
- **No backfeed from the SKR V2 on herman4:** unplugging its USB cut the
  Pi's draw rather than raising it, so the SKR draws a little from the Pi
  over USB (about 30 mA by this meter) and supplies none.
- **Backfeed from the SKR V3: suspected, then mostly cleared.** Plugging
  its USB into the Pi 3 once *lowered* the current through the meter, which
  would mean the SKR took over part of the Pi's load. But with a Pi 3 B's SD
  card out and its own power unplugged, the SKR on 12 V and on its USB port
  did **not** light the red LED, so the SKR cannot carry a Pi. That LED is a
  power-good light (about 4.63 V), so a weak path through a diode is not
  quite ruled out, and the one drop may have been idle noise on a meter
  that reads low currents poorly. (No ground ran from the Pi to the 12 V
  side for that test; the cable's own ground is the return, so it did not
  matter.)
- **The SKR V2 also lowers the Pi 3's current when plugged in**, so both
  boards put their 5 V on the cable whatever the jumper says. Read that way,
  the two 5 V rails are joined through the cable and the higher one feeds
  the other: on herman4 (5.10 V) the Pi feeds the V2, which is the "draw"
  noted above; on the Pi 3 (4.90 V) the SKR feeds the Pi.
- **Swap: the V2 on the Pi 3 B installs fine.** Same Pi, the V3 resets it,
  the V2 does not -- so the V3 is necessary, and the Pi boards are cleared.
  Working idea: the V3 carries more of the Pi's load than the V2, and when
  Klipper resets its chip that share drops at once onto a converter with no
  headroom. Or the V3 draws a surge at that moment instead. Either way it is
  the V3 together with the weak converter.
- **The V2 installs fine on the Pi 3 A+ too.** Both Pi 3s: V2 fine, V3 resets.
- **5 V cut, still resets (2026-10-29).** The V3 on the Pi 3 B through a
  cable with its red 5 V wire removed (checked against the pinout) still
  stopped the install at "Verifying Klipper connection". **Power through
  the cable's 5 V is not the cause**, and a 5 V blocker would not fix it.
- **The current drop was never backfeed.** With the 5 V wire gone the meter
  still read less with the SKR plugged in. The meter measures on the ground
  wire, and the Pi has other ground paths back to the 12 V negative: through
  the converter, the SKR's USB cable, and (on herman4) the LED strip's ground
  on pin 20. Return current shared across them skips the meter. That is
  also why herman4 read about a fifth of a Pi 4's draw while the meter read
  a phone, with no loop, correctly. **On this rig the meter's current means
  nothing; its voltage still holds.**
- **Nothing in printer.cfg switches on at configure**: the pump starts at
  `value: 0` and the steppers stay disabled until a move.
- **New suspect: the Pi 3's USB host driver (dwc_otg), not power.** Both
  Pi 3s use it and the Pi 4 does not, and the V3's STM32G0B1 has a different
  USB block from the V2's F103. Klipper resets the MCU at start, so the
  board drops off USB and comes back. A hard lockup there leaves a journal
  that just stops, with no under-voltage, and a watchdog reboot after it
  looks like power loss.
- **`dwc_otg.speed=1` test: inconclusive (2026-10-29).** Fresh card,
  setting confirmed (`/sys/module/dwc_otg/parameters/speed` read 1), V3 on
  the cut cable, the 4.90 V converter. The install died **early, while apt
  was unpacking**, well before Klipper. The previous boot ended in Wi-Fi
  chip errors (`brcmf_sdio_txfail`, `failed backplane access over SDIO,
  halting operation`) for at least 24 s, with no USB errors. The setting
  never got its chance. Also: the setting only removes the hub's speed
  translation, and the A+ has no hub, so it was never likely to explain the
  A+.
- **The Pi 3 B is under-voltage on this converter even near idle.** After
  that reset, in a 6-minute-old boot: `throttled=0x50000` and four
  "Undervoltage detected!" episodes of 4-6 s each, two during boot and two
  while running a few shell commands. Earlier runs read 0x0, so something in
  the chain got worse: the meter's extra connectors and shunt, a worn
  micro-USB plug or lead, or the plain 3 B drawing more than the A+.
  `get_rsts=1000` after it (not yet compared with a clean reboot's value).
  **Every Pi 3 result on this converter is now suspect**; that card also
  needs reflashing after dying mid-unpack.
- **Board jumpers checked.** The V3's factory-fitted jumper is the 5 V source
  selector (onboard supply vs BTT's DCDC5V add-on) for the BLTouch, TFT and
  RGB headers, and stays on. The separate USB_5V jumper (below the I/O
  header) is the one used for flashing and is off.

## Next session (from 2026-10-29)
Nothing below runs on the 4.90 V converter. Every run: fresh card, no
`dwc_otg.speed=1`, the meter out of the chain, the shortest lead, the V3 on
a normal (uncut) cable. Pass is no reset through the install, then
`uptime` and `vcgencmd get_throttled` reading `0x0`.

1. **The V3 on a good supply.** Either an official Pi micro-USB supply
   (5.1 V, 2.5 A) or the new buck converter, measured first: at least 5.1 V
   at the Pi at rest, about 5.0 V or more under the stress loop. A wall
   supply fixes the voltage *and* drops the converter's ground path, so a
   pass there does not say which; the buck converter keeps the ground tied,
   so a pass there means voltage was the cause and a single-plug design
   works.
2. **If it still resets on a good supply: a USB isolator** (ADuM3160 type,
   full speed only, which is all the SKR uses). It breaks both 5 V and
   ground between Pi and SKR. A pass means the ground path; a fail clears
   power and ground both and leaves the V3 itself.
3. **Decision either way.** The V2 works on every Pi tried, but is the older
   board and may be scarce, so check it can be bought in quantity before
   committing to it. If the V3 passes on a good supply, use the V3 and
   specify the supply instead. Manta with a CM4/CB1 was set aside: a
   redesign, and modules hard to find.

   **Update 2026-10-29: an SKR Pico was bought.** It powers the Pi itself
   (TPS5450, set to about 4.99 V, 3.5 A fuse) and talks over UART, which takes
   the USB link and the ground loop out of the picture altogether. It's
   supported in software now: [../SKR_PICO.md](../SKR_PICO.md). Its
   *First power-up* checks are the next hardware test, and may make tests 1
   and 2 above moot.

Uncommitted doc edits made during this session and not yet decided:
`BOM.md` and `POWER_SYSTEM.md` were changed to require a 5.1 V minimum
converter. The V2 installing fine on the 4.90 V unit weakens that as a hard
rule; settle the wording after step 1.

## Ruled out or unlikely so far
- **The A+ board itself:** a Pi 3 B+ resets the same way (see above), and a
  Pi 3 B with the V2 instead of the V3 installs fine (2026-10-28).
- **`core_freq=250`:** removed, and it still happened.
- **`core_freq=400`, heat, CPU load, Klipper and its C helper compile:**
  see 2026-10-27 above.
- **The SKR drawing power over USB:** the SW_USB jumper is off. **Not the
  same as the SKR *feeding* power over USB**, which it does anyway (see the
  meter readings above), so this line no longer clears the USB link.
- **Running out of memory:** plenty free.
- **Klipper failing to connect:** the installer's "not reached the motion
  board" warning was a bug in its check (fixed in commit c7936be). The board
  connects fine.
- **Sagging voltage the Pi could notice:** `throttled` read 0x0 right up to a
  reset. That does **not** clear power: a drop fast and deep enough resets
  the Pi before the firmware flags it.

## Suspects, in order (updated 2026-10-27)
1. **The SKR's USB connection disturbing the Pi's supply.** The Pi and the
   SKR already share ground through the 12 V supply and the DC-DC converter,
   and the USB cable adds a second ground path straight to the SoC (the A+
   has no hub chip). The A+'s micro-USB input has less margin than the
   Pi 4's USB-C. The Pi 4 runs a V2 without resets, so either the A+ or the
   V3 could be the weak side. Not yet split: whether the reset comes at the
   physical plug-in (Klipper stopped) or when Klipper configures the board,
   and which of the two it follows (swap the SKRs). The B+ resetting too
   weakens the "no hub chip" part of this and points at the V3 or the supply.
2. **Fast power dips** from the DC-DC converter or the micro-USB lead, which
   the SKR connection may only be exposing. Both Pi 3s use micro-USB; the
   Pi 4 does not. **Update 2026-10-28:** this is now the leading suspect. The
   micro-USB converter reads 4.90 V at rest against 5.10 V on the Pi 4's (see
   the meter readings above), and backfeed from the SKR is mostly cleared.

The SD card has dropped out: `mmc0` stayed clean through every reset.

## Fixes to try, in order
0. **A good supply for the Pi**, then a **USB isolator** -- see "Next
   session" above. (A 5 V blocker was tried as a cut 5 V wire and did not
   help; `dwc_otg.speed=1` was tried but the run died of under-voltage
   first.)
1. A **powered USB hub** between the Pi and the SKR.
2. A **separate 5 V supply for the Pi** (an official Pi supply) instead of
   the DC-DC converter off the 12 V rail.
3. A better **5.1 V buck converter** with a large output capacitor, and a
   short, thick lead to the Pi.

## What to read from the card
Mount it read-only first (check `lsblk` for the right device; it is usually
`/dev/sdb` or `/dev/mmcblk0`):
```
sudo mkdir -p /mnt/pi-root /mnt/pi-boot
sudo mount -o ro /dev/sdb2 /mnt/pi-root
sudo mount -o ro /dev/sdb1 /mnt/pi-boot
```

1. **The system journal**, if persistent logs were turned on (that is, if
   `/mnt/pi-root/var/log/journal/` exists and holds files):
   ```
   journalctl --directory=/mnt/pi-root/var/log/journal --list-boots
   journalctl --directory=/mnt/pi-root/var/log/journal -b -1 -n 80 --no-pager
   ```
   For each boot that ended unexpectedly, look at its **last lines**:
   - it just stops, with no shutdown messages: power loss;
   - `Under-voltage detected`: power;
   - `mmc0`, `mmcblk0` or `EXT4-fs error` lines: the SD card;
   - `brcmfmac` errors, or `wlan0` / NetworkManager disconnects: Wi-Fi only;
   - `watchdog`, `Oops`, `panic`, `Out of memory`: a crash.

   Also search every boot for those patterns:
   ```
   journalctl --directory=/mnt/pi-root/var/log/journal --no-pager | grep -iE "under-voltage|mmc0|mmcblk|EXT4-fs|brcmf|wlan0.*(disconnect|deauth)|watchdog|oops|panic|out of memory"
   ```
   If there is no `journal` folder, earlier boots' logs were never kept. Say
   so, and suggest turning persistent logs on before the next test.
2. **`/mnt/pi-root/home/pi/power.log`:** the last lines before each gap in
   the timestamps.
3. **`/mnt/pi-root/home/pi/klipper_logs/klippy.log`:** whether Klipper was
   starting or restarting near each reset.
4. **`/mnt/pi-boot/config.txt`:** the `core_freq`, `dtparam`, `dtoverlay` and
   `arm_` lines.
5. **`/mnt/pi-root/etc/fake-hwclock.data`:** the time saved at the last clean
   shutdown or hourly save. That helps line up the logs, since the Pi has no
   real-time clock.
6. **The filesystem**, check only, which needs the root partition unmounted:
   ```
   sudo umount /mnt/pi-root
   sudo fsck.ext4 -n /dev/sdb2
   ```
   Errors here point at the card.

## What to report back
- Which suspect the evidence points at, quoting the lines that show it.
- Whether the card looks healthy.
- What to try next. For example:
  - power, if the journal shows power loss or under-voltage;
  - a new card, if `mmc` or `EXT4` errors show up;
  - the Wi-Fi power-save setting, if it is only the Wi-Fi dropping
    (`brcmf_cfg80211_set_power_mgmt: power save enabled` appears at every
    boot and is the usual default).
