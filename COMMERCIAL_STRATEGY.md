# Herman Commercial Strategy

This document clarifies that Herman is a physical product business, not just a software project. The hardware system is the core product, and the software is the system layer that makes the hardware useful, reliable, and commercially viable.

## Product definition

Herman is a smart indoor planter system built around:
- a modified IKEA VITTSJÖ frame
- black-brown melamine shelf at the bottom and glass on top
- 1000 mm 2020 extrusion rail mounted to the rear uprights
- GT2 belt and pulley drive system powered by a NEMA 17 stepper
- homing against a mechanical endstop at the motor end of the rail
- four capacitive soil moisture sensors with unique I2C addresses
- addressable LED lighting for targeted plant lighting and ambient effects
- 12V peristaltic pump feeding a tube carried on the gantry, for controlled fluid delivery
- Raspberry Pi as the host controller
- BTT SKR Mini E3 V2 with embedded TMC2209 drivers
- Pi Camera for monitoring and timelapses — an optional paid add-on rather than
  part of the base unit

This is a complete hardware + software product that can be sold as a consumer or premium home-garden appliance.

## Business model

The business model should be framed around selling the full system, not just code.

### Revenue streams
- one-time sale of the complete planter system
- **camera add-on**: the module plus timelapse capture, sold as an upgrade on the
  base unit. Keeping it a tier rather than a base feature also lets a future
  streaming tier ship different compute without changing the base build
- premium versions with more sensors, larger capacity, higher-end materials, or improved aesthetics
- optional subscription for remote monitoring, updates, plant care recommendations, and advanced automation
- consumables: nutrient solution, replacement pump tubing, filters, cleaning kits, sensor replacements
- maintenance plans and extended warranty
- B2B / hospitality / office / commercial indoor plant installations

## Product architecture

### Hardware layer
- plant frame and enclosure
- pump, reservoir and tubing
- motion rail and carriage drive
- lighting strip and power system
- sensors and wiring harness
- Raspberry Pi, and the camera on units that have the add-on
- motion control board and stepper motor
- electrical protection and safety systems

### Embedded software layer
- Klipper for motion control and hardware interfacing
- TMC2209 tuning and motion safety settings
- stepper configuration, homing behavior, and position control
- firmware update and diagnostic tooling

### Host software layer
- Raspberry Pi running Klipper
- Python service for automation and hardware orchestration
- local API for plant control, watering, LEDs, and motion
- sensor polling and health checks
- camera integration for time-lapse and monitoring

### User application layer
- web dashboard or mobile app
- plant status overview
- moisture trends
- watering schedules
- lighting modes
- manual watering controls
- notifications for low water or pump issues
- plant profile configuration

## Commercial priorities

To turn this into a saleable product, priority should be placed on:
- reliability
- clean aesthetics
- easy setup and maintenance
- calibration and sensor accuracy
- software stability and safety
- remote supportability
- manufacturability and quality control

## Recommended product strategy

### Phase 1: prototype-to-product
Build and validate a single product variant with:
- 4 plant positions
- local app dashboard
- automated moisture-based watering
- scheduled lighting
- camera monitoring, as a paid add-on rather than part of the base unit
- reliable pump and sensor calibration

### Phase 2: commercial-ready hardware
Harden the physical design:
- safer power delivery
- improved tubing and reservoir design
- better cable management
- moisture-resistant enclosure and connectors
- quality assembly process

### Phase 3: packaged product
Offer a polished retail version with:
- branded UI and packaging
- warranty and support process
- onboarding instructions
- calibration procedure and service manual
- replacement accessories and consumables

## Important positioning note

The product should be sold as a smart indoor growing system, not as "just a Raspberry Pi project" or "just a software app." The hardware product is what customers buy. The software is what makes the hardware valuable, useful, and maintainable.

## Suggested tagline

"A smart indoor planter system that automates watering, lighting, and plant care through a fully integrated hardware + software platform."

## Long-term commercial opportunity

This can evolve into a broader product family:
- small home unit
- larger multi-planter unit
- office/commercial installations
- greenhouse automation modules
- plant care subscriptions and recommendations
- enterprise plant health monitoring for interior design and facilities

The foundation here is a real product, with software enabling the experience and operations.
