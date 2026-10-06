# Herman Product Specification

## Product concept

Herman is a smart indoor planter system designed to automate and optimize plant care for home, office, and premium interior environments. The system combines hardware and software to provide automatic watering, lighting control, environmental visibility, and plant management.

**Architectural note:** The software organizes the frame into four **plants** — fixed positions, each with its own soil sensor, rail coordinate and LED segment. A plant is the unit of configuration, control and monitoring, and what is growing there is recorded as that plant's name, which the owner can change.

## Target product

A 4-plant smart indoor planter system using:
- modified IKEA VITTSJÖ frame
- melamine lower shelf and glass top shelf
- 1000 mm 2020 aluminum rail mounted behind the plants
- GT2 belt and pulley carriage motion system
- NEMA 17 stepper motor with TMC2209 control
- homing against a mechanical endstop at the motor end of the rail
- four capacitive soil moisture sensors
- I2C address configuration to prevent collisions
- peristaltic pump feeding a tube carried on the gantry, which dribbles into whichever plant the carriage is parked over
- addressable LED strip for plant lighting and ambient modes
- Raspberry Pi as host controller
- Pi camera for monitoring and timelapse, as an optional paid add-on
- BTT SKR Mini E3 V2 motion board

## Functional goals

### Plant care
- monitor soil moisture for each plant
- water plants based on target moisture thresholds
- support custom moisture targets by plant type
- provide low-moisture alerts
- track watering history

### Lighting
- support ambient lighting modes
- support static color modes
- support per-plant lighting control
- allow schedules for day/night simulations or plant-specific photoperiods

### Motion and positioning
- allow the watering carriage to move to each plant
- establish a repeatable zero by homing against a normally-closed endstop, so a
  broken wire or unseated connector fails homing instead of driving the carriage
  into the end of the rail
- support manual control for calibration and maintenance

### Monitoring
- capture status data from sensors and system health checks
- capture camera images and time-lapse content, on units with the camera add-on
- show plant condition trends over time

## Non-functional goals

- reliable operation for daily household or office use
- safe fluid handling and non-leaking pump design
- simple maintenance and sensor replacement
- local-first system operation
- scalable architecture for future commercial variants
- production-friendly design and serviceability

## User experience goals

- easy setup in under 15 minutes
- no technical knowledge required for basic operation
- simple one-tap watering or scheduling
- clear status display for each plant
- visual plant health insight from moisture history, and from the camera where fitted

## Constraints

- must fit within the modified frame geometry
- must use the selected motion system and control board stack
- must remain safe for indoor use
- must avoid overwatering and sensor failures
- must support calibration and maintenance without full disassembly

## Success metrics

- plants remain in target moisture range
- watering events occur only when needed
- LED lighting supports healthy growth routines
- user can easily interact with plant status via dashboard
- system is stable over multi-day automated operation

## Potential future variants

- smaller desktop planter
- larger multi-plant wall system
- premium designer version with custom frame finish
- office commercial unit with centralized management
- agricultural or research prototype variant

## Commercial definition

This is a sellable product category: a smart indoor planter system for people who want healthier plants without manual maintenance. The system is the product; the software is the intelligence layer that enables it.
