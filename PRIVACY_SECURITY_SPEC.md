# Herman Privacy and Security Specification

## Purpose

This document defines the product security and privacy posture for Herman. The system is planned as a local-only smart planter product intended for installation in private homes. The camera, sensor data, and automation controls are not to be exposed to the public internet by default.

This document is intended to guide future AI agents, contributors, and engineers so they understand the security requirements before making changes to the project.

## Core design principle

Herman is a privacy-first local system.

- No cloud backend is required for normal operation.
- No public internet exposure is required for normal operation.
- The camera stays on the user's home network.
- The product must minimize attack surface.
- The product must be designed for trust in a residential environment.

## Mandatory constraints

The following rules are mandatory for all future implementation work:

1. No cloud dependency for core functionality.
2. No remote camera access from the public internet by default.
3. No default open ports to the internet.
4. No authentication bypass or insecure default credentials.
5. No unencrypted sensitive data storage.
6. No camera feed exposure outside the local LAN without explicit user action.
7. No use of external telemetry services for product operation.
8. No AI or analytics service that sends home data off-device unless separately approved by a product design decision.

## Product security model

### Local-first architecture
- Raspberry Pi runs the planter software locally.
- Dashboard is served on the local network.
- Camera footage is stored locally.
- All automation logic runs on-device.
- The system only needs access to the home Wi-Fi network.

### Network isolation
- The device should sit on the home LAN only.
- The camera should not be reachable from the public internet.
- Home router firewall rules should block inbound access by default.
- NAT and private addressing should be used.
- Port forwarding is not part of the normal product setup.

### Access model
- Access to the product should be local network only unless the user intentionally opts into a separate local-exposure feature.
- A local admin login should be required for device settings.
- Default credentials must be changed during setup.
- Session handling must be secure and minimal.

**Not yet implemented.** The API currently has no authentication: anything on
the LAN can reach every endpoint. Closing that is tied to the phone-app
pairing work, where proximity over BLE is what issues the token — see
[ROADMAP.md](ROADMAP.md).

## Camera privacy policy

The camera is a sensitive component because it is inside a home environment.

**Current scope.** The camera is an optional add-on, not part of the base unit.
Two things exist, and they have different standing:

- **A live view**, served as MJPEG over the LAN by the API. Built, with no UI
  in front of it, and
  covered by the requirements below rather than exempt from them.
- **Timelapse capture**, which is the product feature and is not built. See
  [ROADMAP.md](ROADMAP.md).

Nothing is recorded today, so every requirement about stored footage is a
standing constraint on work still to come rather than a description of what
runs. The requirements on access are live now.

**How the live view meets them, and where it does not.** The capture process
runs only while somebody is reading the stream and is released about fifteen
seconds after the last viewer leaves, so the camera is off whenever nobody is
looking at it — which is a stronger default than an off switch that has to be
found. There is still **no explicit disable control**, and the requirement for
one below is not yet satisfied. On a unit with no camera the tab says so and no
capture is ever started.

### Camera requirements
- Camera access is local-only by default.
- Recording must be optional and user-controlled. If live streaming is ever
  added, the same applies to it, and it does not leave the LAN by default.
- Recorded footage should be stored on local storage devices only.
- There should be no automatic upload to third-party services.
- The user must be able to disable the camera at any time.
- There should be a clear physical or software disable mechanism.

### Camera data handling
- Camera images and video should not leave the device unless the user explicitly chooses a local backup or mirrored storage path.
- Storage locations must be controlled and transparent.
- The system should support local deletion of recordings.
- The system should avoid unnecessary retention periods.

## Sensor privacy

The moisture sensors and other environment sensors are not inherently high-risk, but they still represent data about the user’s home.

- Sensor readings should remain local to the device.
- Data should not be transmitted to a remote backend without explicit opt-in.
- Data retention should be user-configurable and limited.

## Security design expectations for code

Future code changes must respect the following standards:

1. Do not introduce cloud APIs or external data transmission into the default product path.
2. Do not add internet-based auth flows as the default experience.
3. Do not expose camera streams through a public endpoint.
4. Do not use unverified remote scripts or package installs for production operation.
5. Do not store secrets in code repositories.
6. Do not log sensitive camera data or raw images in plain text logs.
7. Do not create hardcoded credentials or insecure defaults.
8. Do not add network listeners that bind to all interfaces unless explicitly required.

## Hardening recommendations

### Raspberry Pi hardening
- use a dedicated non-root user
- keep OS packages updated
- disable unused system services
- enable firewall rules to allow only local traffic needed by the app
- avoid exposing SSH externally
- restrict local network access to Herman's web app

### Application hardening
- use HTTPS locally if serving over a browser on the LAN, with local certificate management
- prefer local-only API endpoints
- limit access to admin endpoints by local authentication
- validate and sanitize all user-supplied commands and settings
- use controlled permissions for watering and motion actions

### Authentication
- The app should not rely on public cloud auth.
- Local authentication should use secure, self-contained credentials.
- User passwords must be strong by default and changeable during setup.
- Admin routes must not be public or unauthenticated.

## Data retention and controls

- camera footage should be stored locally, ideally on a dedicated local drive
- timers should exist to automatically delete old footage if configured by the user
- manual deletion should be available from the local dashboard
- the setup flow should clearly tell the user where data is stored and what stays local

## Allowed future additions

Optional features may be added only if they are clearly opt-in and privacy-safe, for example:
- local scheduled backups to a local NAS
- local-only camera archive on a USB drive
- optional networked dashboard on the LAN
- user-controlled local log export

These remain secondary features and must not become default remote-connected behavior.

## Disallowed future additions

The following are explicitly disallowed in the default product configuration:
- cloud login or cloud account sign-in required for use
- camera livestreaming to public servers
- remote control from internet via NAT loopback or port forwarding by default
- sending sensor or camera data to third-party services without user opt-in and clear disclosure
- any automatic internet pings or telemetry in the base firmware

## Commercial positioning

Herman is a privacy-first smart home product, not a cloud-connected surveillance device.

This is a product advantage, not a limitation. Customers who place a camera in a home environment will trust a local-only system far more than a cloud-connected one.

## Final policy statement

Any future work on Herman must preserve local-first, privacy-safe operation. If a proposed feature requires cloud connectivity, public exposure, remote camera access, or outbound telemetry, it must be explicitly flagged and rejected unless the product design decides to create a separate optional feature with clear user consent and strong documentation.
