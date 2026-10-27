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
- **Same setup on a Pi 4:** the same planter, SKR and supply chain run on a
  Pi 4 with no resets.

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

## Ruled out or unlikely so far
- **`core_freq=250`:** removed, and it still happened.
- **The SKR drawing power over USB:** the SW_USB jumper is off.
- **Running out of memory:** plenty free.
- **Klipper failing to connect:** the installer's "not reached the motion
  board" warning was a bug in its check (fixed in commit c7936be). The board
  connects fine.
- **Sagging voltage the Pi could notice:** `throttled` read 0x0 right up to a
  reset. That does **not** clear power: a drop fast and deep enough resets
  the Pi before the firmware flags it.

## Suspects, in order
1. **Fast power dips** from the DC-DC converter or the micro-USB lead. An
   inline USB meter that records the minimum voltage is on order.
2. **The SD card**, either worn out or corrupted by the hung reboot.
3. **The A+ board itself.**

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
