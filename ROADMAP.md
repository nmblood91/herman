# Herman Roadmap

## Phase 1: Prototype and validation
- confirm hardware layout and enclosure fit
- validate motion rail and carriage movement
- verify soil sensor placement and I2C addressing
- validate peristaltic pump flow and watering accuracy
- test LED lighting and effect modes
- build the controller stack around Raspberry Pi + Klipper + Python service
- validate automation on four plants

## Phase 2: Software maturity
- implement real sensor reading drivers
- add persistent profiles per plant
- add watering schedules and thresholds
- track moisture trend history
- build a dashboard with each plant's status
- add camera capturing and timelapse generation
- implement alerts and diagnostics

## Phase 3: Productization
- improve user experience and UI polish
- harden the physical design and wiring harness
- simplify installation and setup steps
- replace `git pull` with a real update mechanism — see below
- build a service and support process
- create a replacement parts catalog
- define quality control and calibration procedures

### Updates, eventually

Not a near-term task, but worth recording now so the constraint is not
rediscovered later.

`git pull` is not an update mechanism. It brings new source, but the systemd
units, the nginx config, `printer.cfg.example` and any `requirements.txt` change
are only applied by re-running the install script, and the frontend has to be
rebuilt on the device. So a user who pulls gets a partial update, silently, and
the device needs Node and `node_modules` purely to regenerate a static bundle.

What we want instead:

- **Users should not have to SSH in at all.** An update action in the web UI, or
  unattended upgrades, with SSH as the fallback for support rather than the
  supported path.
- **If someone does SSH in, one line should do it** — ideally a Debian package,
  so the whole thing is `sudo apt update && sudo apt upgrade`. A `.deb` can carry
  a prebuilt frontend, the systemd units, the nginx config and the Python deps as
  one versioned artifact, and its `postinst` can do the `printer.cfg`
  backup-and-merge the install script does today.
- **Build the frontend once, in CI, not on every device.** The reasons are
  update reliability and image size, *not* install time: no dependency on the
  npm registry resolving correctly on a device in someone's house, no
  `npm install` rewriting the lockfile mid-update, and no Node toolchain or
  `node_modules` on the shipped SD card. See the measurements below — the build
  itself is seconds, so install time is not an argument here.

### Getting onto the customer's WiFi

Also not near-term, and also recorded so the constraints are not rediscovered.

A shipped unit is headless, has no Ethernet and has one USB port with the SKR
in it. There is no fallback: if it cannot reach WiFi, there is no way in short
of pulling the SD card. So first-run provisioning is a hard requirement for
shipping, not a nicety.

**`herman.local` does not solve this.** mDNS resolves a hostname on a
network the Pi has already joined -- it is link-local multicast, so with no
connection there is no link to multicast over. A Pi with no WiFi configured
broadcasts nothing and is simply unreachable. Whatever the answer is, it has
to reach a planter that is not yet on any network.

There are two ways to do it, and they are not equally constrained.

**Over the device's own access point.** The setup page is served by the Pi
itself and the customer's phone joins its network to reach it. This is the
browser-only path, and it carries a real limitation:

- **The built-in WiFi chip cannot scan while acting as an access point.** So
  the setup page cannot offer "pick your network from a list" on a unit that
  has never connected -- there is nothing cached to list. Either the customer
  types their SSID, or the firmware cycles scan/AP, which is slow and
  unreliable. Design the screen around typing.

**Over BLE, from a phone app.** Credentials arrive over Bluetooth while the
WiFi radio stays in station mode, so **the scanning limitation above does not
apply** -- the chip is free to scan and the app can show a real network picker.
The Pi 3 A+ has BT 4.2 on the same combo chip as its WiFi; the two share an
antenna, but coexistence is irrelevant for a one-time setup exchange.

This is the better experience and it is why provisioning and the mobile app are
one piece of work rather than two. It also settles authentication, which the
API does not have yet: a phone provisioning over BLE is physically next to the
planter, and that proximity is the proof of presence that issues the pairing
token. A code on a sticker in the box is the recovery path for re-pairing
later.

The cost is that BLE provisioning cannot be done from a web page -- browsers
cannot speak to a GATT server on iOS at all. So the AP path probably still has
to exist as the fallback for a customer without the app, which means the
typing-based screen above gets built either way.

Two further constraints apply to both paths:

- **The usual tools are mid-churn.** balena wifi-connect, comitup and RaspAP
  all have problems with the netplan + NetworkManager stack that current
  Raspberry Pi OS is moving to. Newer options exist but are young. Whatever is
  picked, pick it against the OS image actually being shipped.
- **The OS image is not pinned.** deploy/README.md says "Raspberry Pi OS
  (64-bit)", which is whatever rpi-imager is offering that week. Bookworm and
  Trixie behave differently here. Pin the image before choosing a tool, or the
  choice is made against a moving target.

This belongs with the packaging work above rather than before it. Provisioning,
the .deb and the factory image are one push: the image is where provisioning is
baked in, and doing it first means doing it twice.

**Supported hardware floor: Raspberry Pi 3 Model A+**, which is also the
production target. The constraint that actually binds is ARMv8 and 512 MB: a
64-bit Pi OS has to run, so a release artifact can be arm64-only, and the whole
stack has to fit in half a gigabyte. Every Pi 3 clears the first. Only the A+
is tight on the second, which is why it is the board that has to be proven.

See [BOM.md](BOM.md) for the boards being tested and in what order.

**The intended production target is the Pi 3 Model A+**, chosen on cost. Most of
the objections to it do not apply: same BCM2837B0 and same 1.4 GHz quad A53 as
the B+, same dual-band WiFi, same 40-pin pinout, and the same standard 15-pin
CSI connector, so neither the wiring nor the camera ribbon changes. Its smaller
outline means a different mounting pattern, which is a chassis change rather
than a blocker.

Three consequences follow from choosing it, and they are decisions rather than
details:

- **The prebuilt frontend bundle moves onto the critical path.** On 1 GB it was
  optional. On 512 MB it is how you stop caring what the build costs, and the
  cold measurement below has not been taken yet.
- **WiFi onboarding becomes a product requirement.** The A+ has no Ethernet and
  one USB port, which the SKR occupies. A headless unit with a bad WiFi
  configuration cannot be recovered in the field without pulling the SD card.
  Written up under *Getting onto the customer's WiFi* above, including why
  `herman.local` does not solve it.
- **32-bit versus 64-bit reopens.** A 1 GB floor had settled this on arm64. At
  512 MB, armhf is meaningfully lighter, and a release artifact has to target
  one or build both. Decide before the packaging work, not after.

The question is whether 512 MB survives an on-device Vite build. Measured on a
Pi 4 (1 GB) with Klipper, the API and nginx all running:

| | Wall time | Peak RSS |
|---|---|---|
| `npm install` | 14.7 s | 153 MB |
| `npm run build` | 1.7 s | 123 MB |
| Peak system-wide used | | **371 MB** |

**Caveat: that was a warm run** — `node_modules` was populated and npm's cache
was primed, which is why `npm install` finished in seconds. A factory first boot
is cold and will peak higher. Re-measure after `rm -rf node_modules` and
`npm cache clean --force` before treating 371 MB as the real figure.

Taken at face value those numbers suggest an A+ would cope, and the per-process
ceilings are nowhere near the limit. Either way the A+ becomes viable as a side
effect of shipping a prebuilt bundle rather than as separate work, so the
cheapest path is to do that and stop caring what the build costs.

**Nothing on this unit encodes video**, which is what makes 512 MB a
comfortable budget rather than a tight one. The load is four I2C reads a minute,
an SPI write per LED update, a Klipper host loop, and a web API nobody is
usually looking at. The one thing that ever threatened the figure was a camera,
and there is no camera.

So the A+ is not a board chosen despite a constraint — the constraint is gone.
The open question is narrower than it was: whether a **cold** on-device Vite
build fits, which the measurement above does not answer. Shipping the frontend
prebuilt removes even that, which is why it is on the critical path.

**The A+ is in production until at least January 2030**, so staying on it is
safe for the life of the product rather than a bet. See [BOM.md](BOM.md) for why
the Pi Zero 2 W is not the saving it looks like, and for where the cost
actually sits.

### Why a Pi at all, and what leaving would cost

Asked properly: not "a cheaper Pi" but "anything other than a Pi". The answer
is no, and the binding constraint is not CPU. A Pi is the cheapest thing that
is simultaneously a Linux computer and a microcontroller-grade I/O device, with
first-class Klipper support and a published availability date. Every
alternative gives up one of those four.

What the host actually has to provide:

1. **Linux and Python 3.11.** The Klipper host is not optional - Klipper is
   split host/MCU by design, and the SKR is only the MCU. Add FastAPI,
   APScheduler and SQLite.
2. **Hardware I2C with a settable slow clock.** 50 kHz, set by
   `dtparam=i2c_arm_baudrate` on a Pi. Driven by bus capacitance, not by the
   sensors - see [SENSOR_WIRING.md](../SENSOR_WIRING.md).
3. **Hardware SPI that can hit two specific rates**, roughly 2.4 MHz and
   3.2 MHz. This is the constraint nobody expects and it is written up in
   `greenthumb/hardware/led_strip.py`; the short version is that the LED
   waveform is built out of SPI bits, so the achievable clock decides whether
   the strip works, and the two supported chip families need rates in windows
   that barely touch.
4. **WiFi**, there being no Ethernet in the chassis plan.
5. **A USB host port** for the SKR serial link. Not negotiable — see below
   for why GPIO UART is not the escape hatch it looks like.

Requirement 3 is the one that eliminates whole categories, because `spidev`
silently substitutes the nearest rate its driver supports. A host that cannot
land in those windows fails as "the strip looks wrong", with nothing in the
code detecting it.

**Other ARM SBCs** - Orange Pi Zero 2W, Radxa Zero 3W, NanoPi - are the only
genuine like-for-like. Klipper on Armbian is well-trodden, so that is not the
blocker it is assumed to be. But they run $20-35, which is not cheaper than a
$30 A+, and every Pi-specific line in `deploy/pi/install-green-thumb.sh`
becomes per-vendor device-tree work: `raspi-config nonint do_i2c`,
`/boot/firmware/config.txt`, the I2C baudrate parameter, the module loads. Then
the SPI windows need re-verifying on unfamiliar silicon. More work, no saving,
community OS images, and no availability guarantee.

**An x86 thin client or mini PC** - Wyse 3040, HP t620, a used NUC - is $20-40,
far more capable, has first-class Debian and better longevity than any SBC.
It has no GPIO, no I2C and no SPI, and USB bridges do not rescue it: a USB-SPI
adapter adds millisecond jitter to a protocol needing microsecond precision and
continuous streaming. The LED strip alone disqualifies this category.

**A microcontroller with no Linux at all**, an ESP32-S3 at $5-8, is the real
cost floor. It also means dropping Klipper, and with half a megabyte of RAM
there is no SQLite, no Python and no nginx - so `services/automation.py`,
`history.py`, `dances.py`, the calibration and quiet-hours logic and the whole
API go with it. That is not a substitute for the Pi, it is a different product
that happens to water plants. Roughly $25 saved against rewriting the repo.

**Moving the host off the planter** is worth naming because it is tempting:
nothing says the Linux machine has to be inside the furniture. USB past about
three metres is unreliable, and it makes every unit depend on a household
server. Reasonable on a bench, fatal for something sold.

**At volume the answer is none of the above.** The saving is not a cheaper
host, it is one board instead of four - SKR, Pi, DC-DC converter and the Wago
distribution collapsed into a single PCB. That is where the cost actually
falls, and it is a five-figure tooling decision rather than a parts
substitution. Not near.

### If the camera comes back, USB is the way

The CSI camera was dropped because the frame has nowhere to put it, not because
the camera was wrong. Coverage is `2 · standoff · tan(HFOV/2)`, so framing
890 mm of rail needs:

| Horizontal FOV | Standoff |
|---|---|
| 120° — Camera Module 3 Wide, the widest CSI option | **260 mm** |
| 130° | 200 mm |
| 143° | 120 mm |
| 170°+ fisheye | effectively none |

This frame does not give 260 mm. **That ceiling is a Raspberry Pi catalogue
limit rather than a physical one** — 120° is the widest CSI lens they sell, and
UVC modules go far wider for less money. So the interesting alternatives are
all USB.

**Read the FOV spec carefully.** Listings almost always quote *diagonal* FOV,
and a rail cares about horizontal. On a 4:3 sensor a "140°" part is roughly
130° horizontal, which buys 200 mm rather than the 162 mm the headline number
implies. Check for `140°D` before believing it.

**Two form factors worth considering:**

- **A wide UVC module**, around $25 for a 140° 720p board, or less for a 180°
  fisheye. Past about 170° the standoff question disappears entirely and the
  camera can sit almost against the glass. Heavy barrel distortion, which is
  acceptable for looking at plants and not for measuring them.
- **A USB endoscope on the gantry.** Worth taking seriously because it removes
  the objection that made a gantry mount unattractive: a CSI ribbon flexing
  through the cable chain on every move will eventually crack, whereas an
  endoscope cable is thin and flexible by design and the chain already carries
  the water tube. The camera then travels to each plant and framing stops
  mattering at all — and close-ups of individual plants are more useful than
  one distorted wide shot.

**The blocker is the USB port, not the camera.** The A+ has a single USB-A and
the SKR owns it, Klipper talking to the board over USB serial.

**Klipper over GPIO UART is ruled out**, so do not reach for it as the way to
free that port. It looks like the clean fix and is not, mostly because of the
Pi 3 specifically: its good PL011 UART is wired to the Bluetooth radio, leaving
the mini-UART, whose baud rate follows the VPU core clock and so drifts as the
core throttles unless the clock is pinned. Either way the fix is boot-config
surgery plus giving up the serial console. On top of that it trades one plug
for a hand-wired link across the enclosure, and the SKR has to be reflashed for
serial-on-USART, which costs the USB recovery path. A motion link that can
desync under thermal load is the wrong place to economise.

That leaves two honest options, and the second is better:

- **A powered USB hub.** Works, and makes the hub a single point of failure in
  front of both the motion board and the camera, on the port that is also the
  recovery path.
- **The camera unit carries a different board.** A 3 B+ or a Pi 4 has four
  ports and no contention. Since the camera is an add-on rather than base
  equipment, the board is allowed to differ by tier — which keeps a peripheral
  from dictating the base unit's compute. This is the one to take.

The development Pi 4 has four ports, so a camera can be proven out without
deciding any of this.

**Insist on hardware MJPEG.** A UVC camera that compresses on-board means the
host only copies frames, which is *lighter* than the CSI path and its libcamera
ISP plus JPEG encode — worth having on a 512 MB board. Cheap endoscopes often
emit raw YUV only, pushing compression onto the CPU and capping out around
640x480. Confirm with `v4l2-ctl --list-formats-ext` before buying.

**What this costs in software.** `greenthumb/hardware/camera.py` shells out to
`rpicam-vid`, which is libcamera and **cannot see a UVC device at all** — those
are V4L2 on `/dev/video*`. Capture would move to ffmpeg or V4L2 directly.
Everything else in that module survives untouched: the single shared capture,
the viewer reference counting, the JPEG frame splitting, the multipart
generator and the tests. Only `_capture_command` and the binary detection
change, which is the reason the capture command was made injectable.

Prerequisites whenever this starts: there is no CI yet, and the two version
strings (`pyproject.toml`, `frontend/package.json`) are unmanaged — a release
artifact needs one source of truth for version.

## Phase 4: Commercial launch
- package the product as a sellable smart planter system
- prepare warranty, support, and onboarding docs
- define pricing for hardware + optional subscriptions
- create marketing and brand materials
- test launch in limited pilot sales

## Phase 5: Scale and expand
- add premium versions and new product sizes
- support office/commercial deployments
- add remote monitoring features and managed service offerings
- build a plant analytics and recommendations platform
- expand into a broader indoor plant care ecosystem

## Long-term vision

Herman becomes a product line of smart indoor plant systems for homes, offices, and premium spaces, combining plant care automation, environmental monitoring, and consistent design aesthetics.
