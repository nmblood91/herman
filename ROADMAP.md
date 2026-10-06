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

This used to name the 3 B+ as the floor, on the grounds of 1 GB of RAM, the
85 x 56 mm outline and the standard 15-pin CSI connector. That was wrong twice
over. The plain 3 B has the same 1 GB, the same Cortex-A53 and the same
outline -- the B+ adds dual-band WiFi, Bluetooth 4.2 and gigabit Ethernet, and
nothing here needs any of them. And a floor of 1 GB sat *above* the 512 MB
board actually being shipped, which is backwards. See [BOM.md](BOM.md) for the
boards being tested and in what order.

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

**The camera is a paid optional add-on, scoped to timelapse.** That is what makes
the A+ safe to commit to. The base unit ships without a camera and has no need
for the headroom at all; the add-on adds the module and timelapse capture, which
is periodic stills rather than continuous encode — well within 512 MB.

**Live streaming is explicitly out of scope** and far enough out that it should
not influence the board choice. Because the camera is a tier rather than a base
feature, **the board can differ by tier**: if streaming ever ships, that tier can
carry a Pi 4 and the base unit stays on an A+. This is the thing that keeps a
someday feature from constraining a today decision.

Two design constraints that follow from timelapse on an A+:

- **Stills accumulate, so retention is required, not optional.** One frame every
  15 minutes at a few hundred KB is on the order of a gigabyte a month onto an SD
  card. This wants the same treatment as sensor history, which already prunes on
  `history_retention_days`.
- **Don't assemble video on the device.** Encoding a timelapse from stills is a
  batch job that does not belong on a 512 MB host competing with Klipper. Serve
  the stills and assemble on demand elsewhere, or do it nightly at low priority.

Still worth validating capture on an actual A+ before the chassis is designed
around that mounting pattern — but the bar is now timelapse stills, not a live
stream, which is a much lower one.

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
