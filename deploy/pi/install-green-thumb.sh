#!/usr/bin/env bash
set -euo pipefail

echo "Installing GreenThumb on the Pi..."

# Enable I2C interface for sensor communication
echo "Enabling I2C interface..."
sudo raspi-config nonint do_i2c 0

# Halve the I2C clock. The sensor tree is around 1.5 m of cable across three
# hubs, and capacitance that long slows the rise time of SDA/SCL; a slower clock
# leaves more time for the line to reach a valid high. Sensors are read once a
# minute, so the lost bandwidth costs nothing.
I2C_BAUDRATE=50000
BOOT_CONFIG=/boot/firmware/config.txt
[ -f "$BOOT_CONFIG" ] || BOOT_CONFIG=/boot/config.txt
I2C_CLOCK_CHANGED=0
if [ -f "$BOOT_CONFIG" ]; then
  if grep -q "^dtparam=i2c_arm_baudrate=$I2C_BAUDRATE$" "$BOOT_CONFIG"; then
    echo "✓ I2C clock already $I2C_BAUDRATE Hz"
  elif grep -q "^dtparam=i2c_arm_baudrate=" "$BOOT_CONFIG"; then
    sudo sed -i "s/^dtparam=i2c_arm_baudrate=.*/dtparam=i2c_arm_baudrate=$I2C_BAUDRATE/" "$BOOT_CONFIG"
    I2C_CLOCK_CHANGED=1
  else
    echo "dtparam=i2c_arm_baudrate=$I2C_BAUDRATE" | sudo tee -a "$BOOT_CONFIG" >/dev/null
    I2C_CLOCK_CHANGED=1
  fi
  [ "$I2C_CLOCK_CHANGED" -eq 1 ] && echo "✓ Set I2C clock to $I2C_BAUDRATE Hz (applies after reboot)"
else
  echo "⚠️  No boot config found, leaving the I2C clock at its default"
fi

# Enable SPI; the LED strip is clocked out over MOSI (GPIO10, header pin 19)
echo "Enabling SPI interface..."
sudo raspi-config nonint do_spi 0

# The API runs as pi, so it needs these groups to reach /dev/i2c-1 and
# /dev/spidev0.0. Raspberry Pi OS usually grants them to the first user, but not
# to one created later, and the failure looks like a wiring fault.
# video is for the camera add-on: libcamera reaches the sensor through
# /dev/video* and /dev/media*, both owned by that group.
sudo usermod -aG i2c,spi,gpio,video pi

# raspi-config normally applies these live, but on a first boot the device nodes
# can be absent until the modules load.
sudo modprobe i2c-dev 2>/dev/null || true
sudo modprobe spi-bcm2835 2>/dev/null || true

sudo apt update
sudo apt install -y git python3-venv python3-pip nginx curl

# Install core dependencies
echo "Installing build dependencies..."
sudo apt install -y python3-dev libffi-dev build-essential libncurses-dev libusb-dev avrdude gcc-arm-none-eabi binutils-arm-none-eabi swig i2c-tools

# The checkout has to exist before anything below reads a template out of it.
# The documented flow clones it as pi first (see deploy/README.md); this is the
# fallback for running the script from a copied-in file, and it has to come
# before printer.cfg is generated rather than after.
if [ ! -d /opt/greenthumb ]; then
  sudo mkdir -p /opt/greenthumb
  sudo chown pi:pi /opt/greenthumb
  # Clone as pi rather than root. A later chown -R repairs the ownership either
  # way, but cloning as the owning user is what deploy/README.md documents and
  # leaves nothing to repair.
  sudo -u pi git clone --depth 1 https://github.com/nmblood91/herman.git /opt/greenthumb
fi

# Create printer_data and log directories
sudo -u pi mkdir -p /home/pi/printer_data/config /home/pi/printer_data/gcodes /home/pi/klipper_logs

# Auto-detect Klipper device with retry (up to 30 seconds)
echo "Detecting Klipper device (waiting up to 30 seconds)..."
KLIPPER_DEVICE=""
for i in {1..30}; do
  # grep exits non-zero when the board is not up yet, which pipefail would
  # otherwise turn into an immediate exit instead of a retry.
  KLIPPER_DEVICE=$(ls /dev/serial/by-id/ 2>/dev/null | grep -i klipper | head -1 || true)
  if [ -n "$KLIPPER_DEVICE" ]; then
    echo "✓ Found Klipper device: $KLIPPER_DEVICE"
    break
  fi
  if [ $i -lt 30 ]; then
    echo "  Waiting... ($i/30)"
    sleep 1
  fi
done

if [ -z "$KLIPPER_DEVICE" ]; then
  echo ""
  echo "⚠️  No Klipper device detected after 30 seconds"
  echo "Make sure your SKR board is connected and powered on."
  echo "After connecting it, run:"
  echo "  sudo bash /opt/greenthumb/deploy/pi/install-green-thumb.sh"
  echo ""
fi

# Generate printer.cfg from template with actual device ID.
#
# The template is the source of truth, so this overwrites the live config. That
# is deliberate -- it is how a config fix in the repo reaches the Pi -- but
# position_endstop is meant to be measured against your own switch mounting, so
# back up anything that differs before replacing it rather than discarding it
# silently. Nothing is written when the generated file already matches, so
# re-running the script does not pile up backups.
PRINTER_CFG=/home/pi/printer_data/config/printer.cfg
if [ -n "$KLIPPER_DEVICE" ]; then
  sed "s|serial: /dev/serial/by-id/usb-Klipper_xxx|serial: /dev/serial/by-id/$KLIPPER_DEVICE|" /opt/greenthumb/deploy/klipper/printer.cfg.example > /tmp/printer.cfg
  if [ -f "$PRINTER_CFG" ] && ! cmp -s /tmp/printer.cfg "$PRINTER_CFG"; then
    PRINTER_CFG_BACKUP="$PRINTER_CFG.$(date +%Y%m%d-%H%M%S).bak"
    sudo -u pi cp "$PRINTER_CFG" "$PRINTER_CFG_BACKUP"
    echo "⚠️  Existing printer.cfg differed from the template; backed up to:"
    echo "    $PRINTER_CFG_BACKUP"
    echo "    Re-apply any local tuning with:"
    echo "    diff \"$PRINTER_CFG_BACKUP\" \"$PRINTER_CFG\""
  fi
  sudo -u pi cp /tmp/printer.cfg "$PRINTER_CFG"
  echo "✓ Generated printer.cfg with device serial ID"
else
  # Fallback: copy template as-is if device not detected yet
  if [ ! -f "$PRINTER_CFG" ]; then
    sudo -u pi cp /opt/greenthumb/deploy/klipper/printer.cfg.example "$PRINTER_CFG"
  fi
fi

if ! command -v node >/dev/null 2>&1; then
  echo "Installing Node.js 20 LTS..."
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt install -y nodejs
fi

cd /opt/greenthumb
sudo mkdir -p /opt/greenthumb/logs
# The installer runs as root, so without this the checkout is root-owned and
# pi cannot pull updates or run the helper scripts. Repeated after the venv and
# npm build below, which run as root and would otherwise leave .venv and
# node_modules root-owned.
sudo chown -R pi:pi /opt/greenthumb

# Create .env from template if it doesn't exist
if [ ! -f /opt/greenthumb/.env ]; then
  cp /opt/greenthumb/.env.example /opt/greenthumb/.env
  echo "✓ Created .env from template"
fi

python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
# Install the project itself, editable. Without this, `greenthumb` is importable
# only when the working directory happens to be /opt/greenthumb -- which is why
# the API service sets WorkingDirectory, and why running a module by hand from
# anywhere else failed with ModuleNotFoundError. Editable so a git pull takes
# effect without reinstalling.
pip install -e .

cd /opt/greenthumb/frontend
# install rather than ci: the committed lockfile is generated on Windows and
# lacks the ARM Rollup binary, which ci would faithfully omit and then fail to
# build. install resolves the right platform package.
npm install
npm run build

# venv and npm both ran as root, so hand the tree back to pi before anything
# below touches git as pi. A root-owned .venv also means a later `pip install`
# as pi fails for no visible reason.
sudo chown -R pi:pi /opt/greenthumb

# That resolution rewrites package-lock.json, which leaves the checkout dirty
# and makes the next git pull refuse to fast-forward. The churn is per-platform
# and regenerated every install, so drop it.
sudo -u pi git -C /opt/greenthumb checkout -- frontend/package-lock.json

# Install Klipper host software (last, to avoid blocking on large clone)
echo "Installing Klipper host software..."
if [ ! -d /home/pi/klipper ]; then
  sudo -u pi bash -c 'cd ~ && git clone --depth 1 https://github.com/Klipper3d/klipper.git'
fi
# Always install/update Klipper dependencies
sudo -u pi bash -c 'pip install --break-system-packages cffi greenlet jinja2 markupsafe pyserial'

# Always create/update the systemd service (even if Klipper was already cloned)
cat > /tmp/klipper.service << 'EOF'
[Unit]
Description=Klipper 3D Printer Firmware
Documentation=https://www.klipper3d.org/
After=network-online.target
Wants=network-online.target

[Install]
WantedBy=multi-user.target

[Service]
Type=simple
User=pi
RemainAfterExit=yes
RuntimeDirectory=klipper
ExecStart=/usr/bin/python3 /home/pi/klipper/klippy/klippy.py /home/pi/printer_data/config/printer.cfg -l /home/pi/klipper_logs/klippy.log -a /run/klipper/uds
Restart=always
RestartSec=10
EOF

sudo cp /tmp/klipper.service /etc/systemd/system/klipper.service
sudo systemctl daemon-reload

# Start Klipper and verify it connects.
#
# enable then restart, not `enable --now`. On an already-running unit `--now`
# is a no-op, so re-running the installer left Klipper on the printer.cfg it
# started with even though the file had just been regenerated -- which is the
# opposite of what re-running it is documented to do.
echo "Starting Klipper..."
sudo systemctl enable klipper
sudo systemctl restart klipper
sleep 3

# Check if Klipper connected to MCU
echo "Verifying Klipper connection..."
if sudo -u pi grep -q "MCU 'mcu' is ready" /home/pi/klipper_logs/klippy.log 2>/dev/null; then
  echo "✓ Klipper connected to MCU successfully"
elif sudo systemctl is-active --quiet klipper; then
  echo "✓ Klipper service is running"
else
  echo "⚠️  Klipper service failed to start"
  echo "Check logs with: tail -50 ~/klipper_logs/klippy.log"
  echo "Or systemd status: sudo systemctl status klipper"
fi

# Let the API set the timezone, and nothing else. The lighting schedule runs on
# wall-clock time, so a planter in the wrong zone lights at the wrong hours, and
# the UI fixes that in one tap -- but the service runs as pi and timedatectl
# needs root. Scoped to the one subcommand: set-timezone only, so this grants no
# ability to change the clock, disable NTP, or run anything else.
SUDOERS_FILE=/etc/sudoers.d/greenthumb-timedatectl
echo "pi ALL=(root) NOPASSWD: /usr/bin/timedatectl set-timezone *" | sudo tee "$SUDOERS_FILE" >/dev/null
sudo chmod 0440 "$SUDOERS_FILE"
# visudo -c rather than trusting the write: a malformed sudoers file can lock
# sudo out entirely, so remove it again rather than leave that behind.
if sudo visudo -c -f "$SUDOERS_FILE" >/dev/null 2>&1; then
  echo "✓ API may set the system timezone"
else
  sudo rm -f "$SUDOERS_FILE"
  echo "⚠️  Could not install the timezone sudoers rule; set the zone with"
  echo "    sudo timedatectl set-timezone <Area/City>"
fi

sudo cp /opt/greenthumb/deploy/systemd/greenthumb-api.service /etc/systemd/system/greenthumb-api.service
sudo systemctl daemon-reload
# Same as Klipper above: `--now` would not restart an already-running service,
# so a pull that brought new Python kept being served by the old process.
sudo systemctl enable greenthumb-api.service
sudo systemctl restart greenthumb-api.service

sudo cp /opt/greenthumb/deploy/nginx/greenthumb.conf /etc/nginx/sites-available/greenthumb.conf
sudo ln -sf /etc/nginx/sites-available/greenthumb.conf /etc/nginx/sites-enabled/greenthumb.conf
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

sudo systemctl status greenthumb-api.service --no-pager

# Verify the buses the hardware actually needs, so a fresh install reports a
# missing device node here rather than as a silent -1 reading later.
echo ""
echo "Verifying hardware interfaces..."
REBOOT_NEEDED=0

if [ -e /dev/i2c-1 ]; then
  echo "✓ I2C bus present"
  echo "  Soil sensors detected at:"
  sudo i2cdetect -y 1 | awk 'NR>1 {for (i=2; i<=NF; i++) if ($i != "--" && $i != "") printf "    0x%s\n", $i}'
else
  echo "⚠️  /dev/i2c-1 missing — soil sensors will not be readable"
  REBOOT_NEEDED=1
fi

if [ -e /dev/spidev0.0 ]; then
  # Write-only bus: whether a strip is actually on the other end is not
  # detectable, so claim only what this proves.
  echo "✓ SPI enabled (required for the LED strip; cannot detect the strip itself)"
else
  echo "⚠️  /dev/spidev0.0 missing — LED strip will not light"
  REBOOT_NEEDED=1
fi

# The camera is an optional add-on, so its absence is not a warning. Report
# what is actually true and let the builder decide whether that is wrong.
if command -v rpicam-vid >/dev/null 2>&1 || command -v libcamera-vid >/dev/null 2>&1; then
  if rpicam-hello --list-cameras 2>/dev/null | grep -q ":"; then
    echo "✓ Camera detected:"
    rpicam-hello --list-cameras 2>/dev/null | sed -n 's/^\([0-9]\+\) : \(.*\)$/    \1: \2/p'
  else
    echo "– No camera detected (optional add-on; the Camera tab will say so)"
  fi
else
  echo "– rpicam-apps not installed, so no camera capture is possible"
fi

printf "\nGreenThumb install complete.\n"
printf "Open: http://$(hostname -I | awk '{print $1}')\n"
printf "API: http://$(hostname -I | awk '{print $1}'):8000\n"

if [ "$REBOOT_NEEDED" -eq 1 ]; then
  printf "\n⚠️  Reboot required to finish enabling I2C/SPI, then re-run this script.\n"
elif [ "$I2C_CLOCK_CHANGED" -eq 1 ]; then
  printf "\n⚠️  Reboot to apply the new I2C clock speed.\n"
fi
