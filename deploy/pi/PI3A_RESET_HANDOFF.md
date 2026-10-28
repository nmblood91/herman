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

## Ruled out or unlikely so far
- **The A+ board itself:** a Pi 3 B+ resets the same way (see above).
- **`core_freq=250`:** removed, and it still happened.
- **`core_freq=400`, heat, CPU load, Klipper and its C helper compile:**
  see 2026-10-27 above.
- **The SKR drawing power over USB:** the SW_USB jumper is off.
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
   the SKR connection may only be exposing. An inline USB meter that records
   the minimum voltage is on order. Both Pi 3s use micro-USB; the Pi 4 does
   not.

The SD card has dropped out: `mmc0` stayed clean through every reset.

## Fixes to try, in order
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
