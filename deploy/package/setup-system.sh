#!/usr/bin/env bash
# Everything the planter needs from the system, run as root by the package's
# postinst on every install and every upgrade. Idempotent: running it twice
# changes nothing the second time.
#
# This used to be deploy/pi/install-green-thumb.sh, run by hand after a
# git pull. A pull without it was a silent partial update -- new code, old
# services -- and that is the problem the package exists to remove.
set -euo pipefail

APP=/opt/greenthumb
PI_USER=pi
DATA=/var/lib/greenthumb
PRINTER_CFG=/home/$PI_USER/printer_data/config/printer.cfg

if ! id "$PI_USER" >/dev/null 2>&1; then
  echo "GreenThumb runs as the user '$PI_USER', which does not exist." >&2
  echo "Flash Raspberry Pi OS with the username set to $PI_USER." >&2
  exit 1
fi

# --- hardware interfaces -----------------------------------------------------

REBOOT_NEEDED=0
if command -v raspi-config >/dev/null 2>&1; then
  raspi-config nonint do_i2c 0
  # The LED strip is clocked out over SPI MOSI (GPIO10, header pin 19).
  raspi-config nonint do_spi 0
fi

# Halve the I2C clock. The sensor tree is around 1.5 m of cable across three
# hubs, and that much capacitance slows the rise time of SDA/SCL; a slower clock
# leaves more time to reach a valid high. Sensors are read once a minute.
I2C_BAUDRATE=50000
BOOT_CONFIG=/boot/firmware/config.txt
[ -f "$BOOT_CONFIG" ] || BOOT_CONFIG=/boot/config.txt
if [ -f "$BOOT_CONFIG" ]; then
  if ! grep -q "^dtparam=i2c_arm_baudrate=$I2C_BAUDRATE$" "$BOOT_CONFIG"; then
    if grep -q "^dtparam=i2c_arm_baudrate=" "$BOOT_CONFIG"; then
      sed -i "s/^dtparam=i2c_arm_baudrate=.*/dtparam=i2c_arm_baudrate=$I2C_BAUDRATE/" "$BOOT_CONFIG"
    else
      echo "dtparam=i2c_arm_baudrate=$I2C_BAUDRATE" >>"$BOOT_CONFIG"
    fi
    REBOOT_NEEDED=1
  fi
fi

# The API runs as pi and needs /dev/i2c-1 and /dev/spidev0.0. Pi OS grants these
# groups to the first user but not to one created later, and the failure looks
# like a wiring fault.
usermod -aG i2c,spi,gpio "$PI_USER"
modprobe i2c-dev 2>/dev/null || true
modprobe spi-bcm2835 2>/dev/null || true
[ -e /dev/i2c-1 ] && [ -e /dev/spidev0.0 ] || REBOOT_NEEDED=1

# --- Python environments -----------------------------------------------------
#
# Built from the wheelhouse inside the package, never from PyPI: an update must
# not depend on a package index resolving the same way on a device in someone's
# house as it did in CI.

make_venv() {
  local venv=$1 requirements=$2
  # Recreated when the system Python changed underneath it, which would
  # otherwise leave a venv pointing at an interpreter that is gone.
  if [ -x "$venv/bin/python" ] && ! "$venv/bin/python" -c "" 2>/dev/null; then
    rm -rf "$venv"
  fi
  [ -x "$venv/bin/python" ] || python3 -m venv "$venv"
  "$venv/bin/pip" install --quiet --no-index --find-links "$APP/wheelhouse" -r "$requirements"
}

make_venv "$APP/.venv" "$APP/requirements.txt"
# What `pip install -e .` did in a checkout, without needing setuptools: puts
# /opt/greenthumb on the path so `python -m greenthumb...` works from anywhere.
SITE=$("$APP/.venv/bin/python" -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")
echo "$APP" >"$SITE/greenthumb.pth"

make_venv "$APP/klippy-env" "$APP/klipper/scripts/klippy-requirements.txt"
# Klipper compiles its C helper on first start, into its own source tree. Done
# here, as root, because that tree belongs to the package and pi cannot write
# it. Removed first so an upgraded helper is never paired with an old build.
rm -f "$APP/klipper/klippy/chelper/c_helper.so"
(cd "$APP/klipper/klippy" && "$APP/klippy-env/bin/python" -c "import chelper; chelper.get_ffi()")

# --- Klipper's printer.cfg -----------------------------------------------------
#
# Lives in pi's home rather than in the package, because position_endstop is
# measured against each planter's own switch mounting. The template is still
# the source of truth: a config fix in a release has to reach the planter. So
# a printer.cfg that differs from the new template is backed up, never just
# overwritten, and nothing is written when they already match.

sudo -u "$PI_USER" mkdir -p "$(dirname "$PRINTER_CFG")"
KLIPPER_DEVICE=$(ls /dev/serial/by-id/ 2>/dev/null | grep -i klipper | head -1 || true)
GENERATED=$(mktemp)
if [ -n "$KLIPPER_DEVICE" ]; then
  sed "s|serial: /dev/serial/by-id/usb-Klipper_xxx|serial: /dev/serial/by-id/$KLIPPER_DEVICE|" \
    "$APP/deploy/klipper/printer.cfg.example" >"$GENERATED"
elif [ -f "$PRINTER_CFG" ]; then
  # The SKR is unplugged. Keep the serial line the planter already has rather
  # than replace it with the template's placeholder.
  SERIAL_LINE=$(grep -m1 "^serial:" "$PRINTER_CFG" || true)
  sed "s|^serial: /dev/serial/by-id/usb-Klipper_xxx|${SERIAL_LINE:-serial: /dev/serial/by-id/usb-Klipper_xxx}|" \
    "$APP/deploy/klipper/printer.cfg.example" >"$GENERATED"
else
  cp "$APP/deploy/klipper/printer.cfg.example" "$GENERATED"
fi
if [ -f "$PRINTER_CFG" ] && ! cmp -s "$GENERATED" "$PRINTER_CFG"; then
  BACKUP="$PRINTER_CFG.$(date +%Y%m%d-%H%M%S).bak"
  sudo -u "$PI_USER" cp "$PRINTER_CFG" "$BACKUP"
  echo "printer.cfg differed from this release's template; the old one is at $BACKUP"
fi
if ! cmp -s "$GENERATED" "$PRINTER_CFG" 2>/dev/null; then
  install -o "$PI_USER" -g "$PI_USER" -m 0644 "$GENERATED" "$PRINTER_CFG"
fi
rm -f "$GENERATED"
[ -n "$KLIPPER_DEVICE" ] || echo "No SKR board found on USB. Plug it in and run: sudo dpkg-reconfigure greenthumb"

# --- the planter's data --------------------------------------------------------

install -d -o "$PI_USER" -g "$PI_USER" -m 0755 "$DATA" /var/log/greenthumb
# Both keep any entry already there, so an upgrade never replaces a mix or a
# plant somebody tuned. Run as pi so state.json stays pi's.
sudo -u "$PI_USER" "$APP/.venv/bin/python" -m greenthumb.soil_library --install >/dev/null
sudo -u "$PI_USER" "$APP/.venv/bin/python" -m greenthumb.plant_library --install >/dev/null

# --- services --------------------------------------------------------------------

ln -sf /etc/nginx/sites-available/greenthumb.conf /etc/nginx/sites-enabled/greenthumb.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t

# Building an SD card image installs this package in a chroot, where nothing is
# running to restart. The services start on the image's first boot instead.
if [ ! -d /run/systemd/system ]; then
  systemctl enable klipper.service greenthumb-api.service greenthumb-update-check.timer
  exit 0
fi

systemctl daemon-reload
# enable then restart rather than `enable --now`, which does nothing to a unit
# that is already running -- so an upgrade would keep serving the old code.
systemctl enable klipper.service greenthumb-api.service greenthumb-update-check.timer
systemctl restart klipper.service
systemctl restart greenthumb-api.service
systemctl restart nginx.service
systemctl start greenthumb-update-check.timer

if [ "$REBOOT_NEEDED" -eq 1 ]; then
  echo "Reboot once to finish enabling I2C and SPI and the I2C clock speed: sudo reboot"
fi
