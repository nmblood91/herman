from __future__ import annotations

import logging
import math
import threading
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, time, timedelta
# Not datetime: the Pi has no battery-backed clock, so an NTP sync can
# land mid-run and move the wall clock. A calibration divides by this
# duration, so it has to come from a clock that only goes forwards.
from time import monotonic, sleep
from pathlib import Path

from greenthumb.config import settings
from greenthumb.hardware.klipper_client import KlipperClient, MOTION_TIMEOUT
from greenthumb.hardware.lighting import (
    DEFAULT_BRIGHTNESS,
    DEFAULT_COLOR,
    DEFAULT_MANUAL_SCOPE,
    DEFAULT_MODE,
    DEFAULT_RAINBOW_SPEED,
    LedController,
    Zone,
)
from greenthumb.hardware.led_strip import pixel_count
from greenthumb.hardware.pump import PumpController
from greenthumb import sweep
from greenthumb.hardware.soil_sensors import (
    SoilSensorHub,
    calibrate,
    measure_endpoint,
    unavailable_sample,
    wilting_point_for,
)
from greenthumb.history import DEFAULT_DB_PATH, HistoryStore
from greenthumb.models import SensorSample, PlantSpec, PlantStatus
from greenthumb.plants import default_plants, label_for, sweep_edge_limits, zone_for
from greenthumb import care, dances, soak, state, system_power

logger = logging.getLogger(__name__)

# How close to position_max counts as parked on the home switch. Wider than
# homing_retract_dist so a carriage resting just off the switch after a failed
# home is still read as being at it.
NEAR_SWITCH_MM = 15.0
# How long the hourly patrol waits out busy hardware before giving up on the
# hour, and how often it looks. A dose finishes well inside this.
PATROL_BUSY_WAIT_SECONDS = 300.0
PATROL_BUSY_POLL_SECONDS = 5.0


# "Not given" for optional fields where None means "clear it". See save_soil.
UNCHANGED = object()


class HardwareBusyError(RuntimeError):
    """Raised when the gantry, pump, or I2C bus is already in use."""


# In care_fields for showing, and never stored.
DERIVED_CARE_FIELDS = ("water_level", "light_stop_time")

# Marks a file as a library backup, so importing some other JSON by mistake
# is refused rather than half-read.
LIBRARY_FORMAT = "greenthumb-library"
LIBRARY_VERSION = 1


def _water_level_of(profile: dict) -> dict[str, str]:
    """A stored plant profile's water level, worked out from its target."""
    try:
        return {"water_level": care.water_level_for(care.check_target_available(profile.get("target_available")))}
    except ValueError:
        return {}


def care_fields(plant: PlantSpec) -> dict[str, object]:
    """A pot's care settings as stored and reported: what a plant profile sets.

    One place for the list, so the state file, the API and a saved plant
    profile cannot drift apart. The water level and the stop time are derived,
    reported for the UI and never read back (DERIVED_CARE_FIELDS).
    """
    return {
        "preferred_soil": plant.preferred_soil,
        "target_available": plant.target_available,
        "water_level": care.water_level_for(plant.target_available),
        "watering_volume_ml": plant.watering_volume_ml,
        "light_start_time": plant.light_start_time.isoformat(timespec="minutes"),
        "light_hours": plant.light_hours,
        "light_brightness": plant.light_brightness,
        "light_stop_time": care.light_stop(
            plant.light_start_time, plant.light_hours
        ).isoformat(timespec="minutes"),
        "notes": plant.notes,
    }


def within_window(now: time, start: time, stop: time) -> bool:
    if start <= stop:
        return start <= now < stop
    # A window that stops before it starts runs overnight, e.g. 20:00 to 06:00.
    return now >= start or now < stop


# A calibration run has to be long enough for the volume to be weighable.
# This is about the scale, not the pump: a kitchen scale reading to the gram is
# a few percent of 20 g and about one percent of 100 g.
MIN_CALIBRATION_SECONDS = 20.0

# What a flow rate is allowed to come out as. The peristaltic pump here is
# rated at 100 mL/min, so a plausible measured figure sits near 1.67 mL/s and
# below it once lift and tubing are in the way. These bounds are wide enough to
# accept any real result and narrow enough to catch a misplaced decimal, which
# is the realistic mistake -- and one that would otherwise store happily and
# mis-dose every pot by that factor.
MIN_FLOW_ML_PER_SECOND = 0.05
MAX_FLOW_ML_PER_SECOND = 20.0


class GreenThumbAutomation:
    """Application service that coordinates sensors, watering, lighting, and movement."""

    def __init__(
        self,
        sensor_hub: SoilSensorHub | None = None,
        klipper_client: KlipperClient | None = None,
        pump: PumpController | None = None,
        leds: LedController | None = None,
        history: HistoryStore | None = None,
        state_path: str | Path | None = None,
    ) -> None:
        # Injectable so tests do not read or overwrite the real settings file.
        self._state_path = state_path
        self.sensor_hub = sensor_hub or SoilSensorHub(
            addresses=settings.moisture_sensor_addresses_list,
            raw_dry=settings.moisture_raw_dry,
            calibration=state.load_calibration(self._state_path),
        )
        self.klipper = klipper_client or KlipperClient(socket_path=settings.klipper_host)
        self.pump = pump or PumpController(
            self.klipper,
            pin_name=settings.pump_pin_name,
            flow_ml_per_second=settings.pump_flow_ml_per_second,
        )
        self.leds = leds or LedController(
            led_count=settings.led_count or None,
            chip=settings.led_chip,
            color_order=settings.led_color_order,
            spi_bus=settings.led_spi_bus,
            spi_device=settings.led_spi_device,
        )

        # The gantry, the pump, and the I2C bus all tolerate exactly one user at
        # a time, and a watering cycle holds them for minutes. A single lock for
        # all three is what keeps the control loop and manual commands apart.
        self._hardware_lock = threading.Lock()
        # True for the length of a G28. See _home.
        self._homing = False
        self._history: dict[int, deque[float]] = {
            address: deque(maxlen=settings.moisture_window_size)
            for address in self.sensor_hub.addresses
        }
        self._latest: dict[int, SensorSample] = {
            address: unavailable_sample(address) for address in self.sensor_hub.addresses
        }
        # _latest is pre-seeded with unavailable samples, so "every reading is
        # -1" is also what a planter looks like one second after boot. This
        # distinguishes the two.
        self._has_polled = False
        self._last_watered: dict[str, datetime] = {}
        self.history = history or HistoryStore(settings.history_db_path or DEFAULT_DB_PATH)
        # Misses before this moment (epoch seconds) no longer count towards the
        # soak-check pause: Resume sets it. Persisted, so a restart neither
        # forgets a pause nor brings back one already resumed.
        self._soak_reset_at = 0.0
        # The startup home is owed until any home succeeds -- its own, a
        # patrol's, or the button -- or until the first tick finds it switched
        # off. Switching it on later takes effect on the next start rather than
        # setting the arm off unannounced. See _maybe_home_on_startup.
        self.home_on_startup = settings.home_on_startup
        self._startup_home_pending = True
        self._startup_homed = False
        self._startup_home_attempts = 0
        self._startup_home_error: str | None = None
        self._pump_timer: threading.Timer | None = None
        self._pump_lock_held = False
        # How long the last manual run actually lasted, which is the
        # denominator of a flow calibration. Measured rather than assumed to be
        # the dead-man limit: the run can be stopped early, and the timer that
        # ends it is a host-side one with its own small lateness.
        self._pump_run_started: float | None = None
        self._last_pump_run: dict[str, object] | None = None
        # When the flow rate in use was measured, or None for the code default.
        # The UI needs to tell "measured on the real plumbing" from "a figure
        # off the datasheet", because only one of those is trustworthy.
        self._flow_measured_at: str | None = None

        # The master switch for unattended watering. Seeded from the
        # environment, then owned by the UI and persisted like every other
        # user choice: editing .env and restarting the service is not
        # something the person who owns a planter should have to do.
        self.auto_watering_enabled = settings.auto_watering_enabled

        # Hourly auto-patrol: a re-home and a pass over every plant, on the
        # hour. The re-home is the useful half -- steppers are open-loop, so a
        # slipped belt or a nudged carriage leaves every plant position wrong
        # until the next home, and doing it hourly caps how long that can go
        # unnoticed. Run by its own scheduler job; see main.lifespan.
        self.auto_patrol_enabled = settings.auto_patrol_enabled
        self._last_patrol: dict[str, object] | None = None

        self.quiet_hours_enabled = settings.quiet_hours_enabled
        self.quiet_hours_start = time.fromisoformat(settings.quiet_hours_start)
        self.quiet_hours_stop = time.fromisoformat(settings.quiet_hours_stop)
        # Absolute instant, not a duration, so it survives a restart with the
        # right amount of time left rather than starting over -- and a Pi that
        # was off for a week comes back with it already expired.
        self.snooze_until: datetime | None = None

        self.plants = default_plants()
        self._warn_on_orphaned_plants()
        self._seed_last_watered()
        # Plant edits, dose volumes, rail positions and LED preferences are all
        # user choices that used to live only in memory, so every restart reset
        # them to the literals above. Restore whatever was saved last.
        self._restore_state()
        # After the restore: the saved strip type sets the pixel count the
        # zones are split from.
        self.apply_default_led_ranges()
        self._sync_scales()

    def _sync_scales(self) -> None:
        """Hand the hub both ends of each pot's scale.

        The top is the pot's soil profile's field capacity reading. The bottom
        is its soil profile's wilting point reading if it has one, otherwise an
        estimate from that field capacity, the pot's probe's air reading and
        the soil's % figures (soil_sensors.wilting_point_for). Both are looked
        up live: a pot stores neither, so a soil profile's new reading reaches
        every pot using it at once.

        The hub reads raw counts and knows nothing about soils or plants, so it
        is given plain address-to-count maps. Called after every write that can
        change either end, because a stale map means readings mapped against
        the previous soil.
        """
        capacity, wilting = {}, {}
        for plant in self.plants:
            address = plant.sensor_address
            soil = self._soil_entry(plant)
            top = soil.get("field_capacity_raw")
            if isinstance(top, bool) or not isinstance(top, (int, float)):
                continue
            capacity[address] = int(top)
            bottom = wilting_point_for(soil, int(top), self.sensor_hub.dry_for(address))
            if bottom is not None:
                wilting[address] = bottom
        self.sensor_hub.field_capacity = capacity
        self.sensor_hub.wilting_point = wilting

    def _soil_entry(self, plant: PlantSpec) -> dict[str, object]:
        """The stored soil profile a pot is filled with, or {} for none."""
        if not plant.soil:
            return {}
        wanted = plant.soil.casefold()
        for name, entry in state.load_soils(self._state_path).items():
            if name.casefold() == wanted and isinstance(entry, dict):
                return entry
        return {}

    def wilting_point_source(self, plant: PlantSpec) -> str:
        """"reading" when the soil profile has one, "estimated" or "" for none."""
        if self.sensor_hub.wilting_point.get(plant.sensor_address) is None:
            return ""
        if self._soil_entry(plant).get("wilting_point_raw") is not None:
            return "reading"
        return "estimated"

    def scale_problem(self, plant: PlantSpec) -> str | None:
        """Why this pot has no moisture reading, or None when it has a scale.

        Said per pot and in plain words, because "no reading" on its own does
        not tell anybody which of the setup steps is missing.
        """
        if not plant.soil:
            return "No soil profile set."
        address = plant.sensor_address
        capacity = self.sensor_hub.field_capacity.get(address)
        wilting = self.sensor_hub.wilting_point.get(address)
        if capacity is None:
            return "Its soil profile needs a field capacity reading."
        if wilting is None:
            return (
                "Its soil profile needs its field capacity and wilting point %, "
                "or a wilting point reading."
            )
        if self.sensor_hub.span_for(address) is None:
            return (
                f"Its wilting point ({wilting}) and field capacity ({capacity}) "
                "readings are too close together to read between."
            )
        return None

    def plant_for_address(self, address: int) -> PlantSpec | None:
        """Which pot a bus address belongs to, or None if no pot claims it.

        The converse of _warn_on_orphaned_plants: that covers a plant whose
        address is never polled, this covers an address polled that no plant
        owns. Both are reachable, because the two lists are configured
        separately.
        """
        for plant in self.plants:
            if plant.sensor_address == address:
                return plant
        return None

    def _warn_on_orphaned_plants(self) -> None:
        """Say so when a plant's sensor address is not one the hub polls.

        The plant list fixes each address in plants.py while the hub takes its
        addresses from MOISTURE_SENSOR_ADDRESSES. Nothing ties the two
        together, so setting that variable to a subset -- which SENSOR_WIRING.md
        tells you to do for single-sensor testing -- leaves the other plants
        reading a bus address nobody polls. They then report -1 forever and are
        skipped by every watering cycle, silently. This does not fix the
        divergence, it just refuses to let it be silent.
        """
        polled = set(getattr(self.sensor_hub, "addresses", []) or [])
        if not polled:
            return
        orphaned = [plant for plant in self.plants if plant.sensor_address not in polled]
        if orphaned:
            logger.warning(
                "%s will never be watered: sensor address%s %s not in "
                "MOISTURE_SENSOR_ADDRESSES. They will report -1 and be skipped.",
                ", ".join(plant.name for plant in orphaned),
                "es" if len(orphaned) > 1 else "",
                ", ".join(f"0x{plant.sensor_address:02x}" for plant in orphaned),
            )

    # --- persistence ------------------------------------------------------

    def _restore_state(self) -> None:
        stored = state.load_state(self._state_path)

        for saved in stored.get("plants", []) or []:
            if not isinstance(saved, dict):
                continue
            plant = self.get_plant(str(saved.get("plant_id", "")))
            if plant is None:
                # A plant id that no longer exists is skipped rather than
                # treated as an error: the plant set is defined by the code.
                continue
            for text_field in ("name", "soil", "preferred_soil", "profile"):
                value = saved.get(text_field)
                if isinstance(value, str) and value.strip():
                    setattr(plant, text_field, value.strip())
            # The care settings, each checked the way the editor checks it. A
            # bad value keeps the default rather than failing the restore.
            for field_name, check in (
                ("target_available", care.check_target_available),
                ("light_hours", care.check_light_hours),
                ("light_brightness", care.check_light_brightness),
                ("light_start_time", care.check_start_time),
            ):
                if field_name not in saved:
                    continue
                try:
                    setattr(plant, field_name, check(saved[field_name]))
                except ValueError:
                    logger.warning("Ignoring bad %s %r", field_name, saved[field_name])
            # Separately from the loop above, which skips blanks so that a
            # cleared name cannot wipe the default. An empty note is a real
            # value, so it is tested for being a string rather than for being
            # truthy -- though with the dataclass default also empty, the two
            # behave the same here. The distinction earns its keep in
            # apply_plant_profile, where skipping an empty note would leave the
            # previous one on the pot.
            if isinstance(saved.get("notes"), str):
                plant.notes = saved["notes"].strip()
            # Validated rather than taken as written, unlike the names: an
            # unknown mode would make every dose fall back to a point while the
            # card said otherwise.
            mode = saved.get("watering_mode")
            if isinstance(mode, str) and mode.strip().casefold() in sweep.MODES:
                plant.watering_mode = mode.strip().casefold()
            elif mode is not None:
                logger.warning("Ignoring unknown watering mode %r", mode)

            for field_name, check in (
                ("light_color", care.check_light_color),
                ("manual_color", care.check_light_color),
                ("manual_brightness", care.check_light_brightness),
            ):
                if field_name not in saved:
                    continue
                try:
                    setattr(plant, field_name, check(saved[field_name]))
                except ValueError:
                    logger.warning("Ignoring bad %s %r", field_name, saved[field_name])

            for field_name in (
                "watering_volume_ml",
                "position_mm",
                "sweep_min_mm",
                "sweep_max_mm",
            ):
                value = saved.get(field_name)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                if not math.isfinite(value):
                    continue
                # All whole numbers. Rounded rather than truncated, so a
                # position stored with a decimal before positions became whole
                # millimetres comes back at the nearest one, not the one below.
                setattr(plant, field_name, round(value))

        patrol = stored.get("auto_patrol")
        if isinstance(patrol, dict) and isinstance(patrol.get("enabled"), bool):
            self.auto_patrol_enabled = patrol["enabled"]

        startup_home = stored.get("startup_home")
        if isinstance(startup_home, dict) and isinstance(startup_home.get("enabled"), bool):
            self.home_on_startup = startup_home["enabled"]

        watering = stored.get("watering")
        if isinstance(watering, dict):
            if isinstance(watering.get("auto_enabled"), bool):
                self.auto_watering_enabled = watering["auto_enabled"]
            self._restore_pump_flow(watering)
            reset = watering.get("soak_reset_at")
            if isinstance(reset, (int, float)) and not isinstance(reset, bool):
                self._soak_reset_at = float(reset)

        quiet = stored.get("quiet")
        if isinstance(quiet, dict):
            self._restore_quiet_state(quiet)

        leds = stored.get("leds")
        if isinstance(leds, dict):
            self._restore_led_state(leds)

    def _restore_pump_flow(self, watering: dict) -> None:
        """Take the measured flow rate back out of state, if there is one.

        Left at the configured default when there is not, which is the case
        that must stay visible: a planter that has never been calibrated is
        dosing off a datasheet figure, and measured_at being None is how the
        UI says so.
        """
        flow = watering.get("flow_ml_per_second")
        if isinstance(flow, bool) or not isinstance(flow, (int, float)):
            if flow is not None:
                logger.warning("Ignoring unusable stored pump flow rate %r", flow)
            return
        if not (MIN_FLOW_ML_PER_SECOND <= float(flow) <= MAX_FLOW_ML_PER_SECOND):
            logger.warning("Ignoring out-of-range stored pump flow rate %r", flow)
            return

        self.pump.flow_ml_per_second = float(flow)
        measured = watering.get("flow_measured_at")
        self._flow_measured_at = measured if isinstance(measured, str) else None

    def _restore_quiet_state(self, quiet: dict) -> None:
        if isinstance(quiet.get("enabled"), bool):
            self.quiet_hours_enabled = quiet["enabled"]
        for key, attr in (("start", "quiet_hours_start"), ("stop", "quiet_hours_stop")):
            text = quiet.get(key)
            if not isinstance(text, str):
                continue
            try:
                setattr(self, attr, time.fromisoformat(text))
            except ValueError:
                logger.warning("Ignoring bad quiet hours %s %r", key, text)

        text = quiet.get("snooze_until")
        if isinstance(text, str):
            try:
                restored = datetime.fromisoformat(text)
            except ValueError:
                logger.warning("Ignoring bad snooze_until %r", text)
                return
            # Dropped rather than restored once it is in the past, so a Pi that
            # was off overnight does not come back still holding a stale snooze.
            if restored > datetime.now():
                self.snooze_until = restored

    def _restore_led_state(self, leds: dict) -> None:
        # Chip first: selecting one resets the channel order to that chip's
        # default, so a saved order has to be applied after it.
        for key, setter_name in (
            ("chip", "set_chip"),
            ("color_order", "set_color_order"),
            ("brightness", "set_brightness"),
            ("rainbow_speed", "set_rainbow_speed"),
            ("manual_scope", "set_manual_scope"),
            ("mode", "set_mode"),
        ):
            value = leds.get(key)
            # Resolved by name rather than as an attribute up front: a
            # controller that does not implement one of these should skip it,
            # not fail startup before the try block is even reached.
            setter = getattr(self.leds, setter_name, None)
            if value is None or setter is None:
                continue
            try:
                setter(value)
            except (ValueError, TypeError, KeyError) as exc:
                logger.warning("Ignoring stored LED %s %r: %s", key, value, exc)

        color = leds.get("color")
        if isinstance(color, (list, tuple)) and len(color) == 3:
            try:
                self.leds.color = tuple(int(channel) for channel in color)
            except (ValueError, TypeError):
                logger.warning("Ignoring stored LED color %r", color)

    def _snapshot(self) -> dict:
        return {
            "plants": [
                {
                    "plant_id": plant.plant_id,
                    "name": plant.name,
                    "position_mm": plant.position_mm,
                    "watering_mode": plant.watering_mode,
                    "sweep_min_mm": plant.sweep_min_mm,
                    "sweep_max_mm": plant.sweep_max_mm,
                    "soil": plant.soil,
                    "profile": plant.profile,
                    "light_color": list(plant.light_color),
                    "manual_color": list(plant.manual_color),
                    "manual_brightness": plant.manual_brightness,
                    **{
                        key: value for key, value in care_fields(plant).items()
                        if key not in DERIVED_CARE_FIELDS
                    },
                }
                for plant in self.plants
            ],
            # getattr throughout: a controller that does not expose one of
            # these simply has it left out of the snapshot, rather than a
            # settings save failing because of an LED attribute.
            "watering": {
                "auto_enabled": self.auto_watering_enabled,
                # Calibration, not configuration: a property of this pump, this
                # tubing and this lift. It lives here rather than in .env so it
                # is set where it is measured, and so it comes back with the
                # rest of the hand-tuned values after a reflash.
                "flow_ml_per_second": self._pump_flow(),
                "flow_measured_at": self._flow_measured_at,
                "soak_reset_at": self._soak_reset_at,
            },
            "auto_patrol": {"enabled": self.auto_patrol_enabled},
            "startup_home": {"enabled": self.home_on_startup},
            "quiet": {
                "enabled": self.quiet_hours_enabled,
                "start": self.quiet_hours_start.isoformat(timespec="minutes"),
                "stop": self.quiet_hours_stop.isoformat(timespec="minutes"),
                "snooze_until": self.snooze_until.isoformat() if self.snooze_until else None,
            },
            "leds": {
                key: value
                for key, value in (
                    ("mode", getattr(self.leds, "mode", None)),
                    ("color", list(getattr(self.leds, "color", []) or []) or None),
                    ("brightness", getattr(self.leds, "brightness", None)),
                    ("rainbow_speed", self._rainbow_speed()),
                    ("manual_scope", self._manual_scope()),
                    ("chip", getattr(getattr(self.leds, "strip", None), "chip", None)),
                    (
                        "color_order",
                        getattr(getattr(self.leds, "strip", None), "color_order", None),
                    ),
                )
                if value is not None
            },
        }

    def _rainbow_speed(self) -> int | None:
        """The strip's rainbow speed, or None when the controller has none.

        Type-checked rather than read with a getattr default: a test double
        with __getattr__ hands back a function, which would poison the state
        snapshot and silently stop every settings save.
        """
        speed = getattr(self.leds, "rainbow_speed", None)
        if isinstance(speed, bool) or not isinstance(speed, int):
            return None
        return speed

    def _manual_scope(self) -> str | None:
        """Whether manual lights the whole strip or each zone, or None.

        Type-checked for the same reason as _rainbow_speed.
        """
        scope = getattr(self.leds, "manual_scope", None)
        return scope if isinstance(scope, str) else None

    def _persist(self) -> None:
        """Write the current settings. Never raises: a failed save must not
        turn a successful setting change into an API error."""
        try:
            state.update_state(self._snapshot(), self._state_path)
        except Exception:
            logger.exception("Could not persist settings")

    def _led_count(self) -> int:
        """The strip's pixel count, from the controller when it has one.

        Type-checked rather than read with a getattr default, since a test
        double answers any attribute with a function.
        """
        count = getattr(self.leds, "led_count", None)
        if isinstance(count, int) and not isinstance(count, bool) and count > 0:
            return count
        return settings.led_count or pixel_count(settings.led_chip)

    def apply_default_led_ranges(self) -> None:
        plant_count = len(self.plants)
        if plant_count == 0:
            return

        total_leds = self._led_count()
        segment_length = total_leds // plant_count
        remainder = total_leds % plant_count

        start_index = 0
        for index, plant in enumerate(self.plants):
            segment_size = segment_length + (1 if index < remainder else 0)
            plant.led_start_index = start_index
            plant.led_end_index = start_index + segment_size - 1
            start_index += segment_size

        if self.plants:
            self.plants[-1].led_end_index = total_leds - 1

    def gantry_position(self) -> dict[str, object]:
        """The carriage's live position, for the Controls tab to poll.

        Deliberately outside the hardware lock: it is a read Klipper answers
        immediately, and the readout is most useful exactly while something
        else -- a watering cycle, the hourly patrol -- holds the lock and is moving
        the carriage.

        While homing, the number is Klipper's invention rather than a place:
        it starts the axis at a made-up position far enough from the switch to
        cover the whole rail (about -445 here) and marks it homed for that
        move. So it is flagged, and the readout says "homing" instead.
        """
        reading = self.klipper.live_position()
        if self._homing and reading.get("ok"):
            reading["homing"] = True
        return reading

    def _home(self) -> dict[str, object]:
        """Home X, flagged so the position readout knows the number is not real.

        The caller holds the hardware lock. G28 blocks until the switch trips
        and Klipper resets the coordinate, so clearing the flag when it returns
        is exactly when the position starts meaning something again.
        """
        self._homing = True
        try:
            result = self.klipper.home_gantry()
        finally:
            self._homing = False
        # Any home that lands settles the startup one: a patrol or the button
        # getting there first should not be followed by a second home.
        if result.get("ok") and self._startup_home_pending:
            self._startup_home_pending = False
            self._startup_homed = True
        return result

    def usable_travel_mm(self) -> float:
        """Reachable X range, where 0 is the first position the carriage can occupy.

        Asks Klipper, because Klipper is the one enforcing it: position_max in
        printer.cfg is the real limit, and it changes whenever the rail is
        measured properly. Deriving a second answer from the rail length and a
        margin meant the two disagreed the moment that happened -- which is how
        a plant ended up configured at a position the carriage could not reach.

        Falls back to the configured travel when Klipper is not answering, so a
        plant position can still be saved with the board unplugged. That used to
        be the rail length less a margin at each end -- 960 against a real 890,
        so a position saved offline could be one the carriage never reaches.
        """
        reported = self.klipper.status().get("max_x")
        if reported:
            return max(float(reported), 1.0)
        return max(float(settings.gantry_travel_mm), 1.0)

    def plant_zone(self, plant: PlantSpec) -> tuple[int, int]:
        """The stretch of rail this plant's watering may use. See plants.ZONES."""
        return zone_for(plant.plant_id, self.usable_travel_mm())

    def _outside_zone(self, plant: PlantSpec, *positions: float) -> str | None:
        """Why these positions are not this plant's to water, or None."""
        low, high = self.plant_zone(plant)
        # Written so not-a-number fails too: every comparison against nan is
        # false, so it never counts as inside.
        if all(low <= position <= high for position in positions):
            return None
        return f"{plant.name} waters between {low} and {high} mm"

    def set_plant_position(self, plant_id: str, position_mm: float) -> dict[str, object]:
        """Record a pot's watering spot.

        Refused outside the plant's zone rather than clamped into it. A spot
        out there is nearly always captured over the wrong pot, and clamping
        would quietly water the edge of the zone instead.
        """
        plant = next((item for item in self.plants if item.plant_id == plant_id), None)
        if plant is None:
            raise ValueError(f"Unknown plant_id: {plant_id}")

        # Whole millimetres, rounded before the range check so the value
        # checked is the value stored. Infinity and not-a-number have no whole
        # millimetre, and round() raises on both with a message nobody wants.
        raw = float(position_mm)
        if not math.isfinite(raw):
            raise ValueError("The watering position must be a number")
        position = round(raw)
        problem = self._outside_zone(plant, position)
        if problem:
            raise ValueError(
                f"{problem}, so {position} mm is out of range. "
                "Is this the right plant?"
            )
        plant.position_mm = position
        self._persist()

        return {
            "status": "ok",
            "plant_id": plant_id,
            "position_mm": plant.position_mm,
        }

    def set_plant_sweep(
        self, plant_id: str, min_mm: float, max_mm: float
    ) -> dict[str, object]:
        """Record the span an oscillating dose travels across.

        Refused rather than clamped, like set_plant_position: a span clamped to
        fit would water a different stretch of the planter than the one asked
        for, and report success. Both edges have to sit inside the plant's
        zone. The bounds are swapped if given the wrong way round, which is an
        ordering, not a value.
        """
        plant = self.get_plant(plant_id)
        if plant is None:
            raise ValueError(f"Unknown plant_id: {plant_id}")

        # Before float(), which turns True into 1.0 and would accept a boolean
        # as a rail coordinate.
        if isinstance(min_mm, bool) or isinstance(max_mm, bool):
            raise ValueError("Sweep bounds must be numbers")
        try:
            low, high = float(min_mm), float(max_mm)
        except (TypeError, ValueError):
            raise ValueError("Sweep bounds must be numbers")
        if low > high:
            low, high = high, low
        # Ordered already, so this is purely the infinity and not-a-number
        # check: every comparison against nan is false, so both fail here.
        if not (float("-inf") < low <= high < float("inf")):
            raise ValueError("Sweep bounds must be numbers")
        # Whole millimetres, rounded before any check so the span checked is
        # the span stored.
        low, high = round(low), round(high)

        limit = self.usable_travel_mm()
        if low < 0 or high > limit:
            raise ValueError(
                f"A sweep has to stay on the rail, which is 0 to {limit:.0f} mm"
            )
        problem = self._outside_zone(plant, low, high)
        if problem:
            raise ValueError(
                f"{problem}, so a sweep from {low} to {high} mm is out "
                "of range. Is this the right plant?"
            )
        zone_low, zone_high = self.plant_zone(plant)
        left_max, right_min = sweep_edge_limits(zone_low, zone_high)
        if low > left_max:
            raise ValueError(f"{plant.name}'s left edge has to be between {zone_low} and {left_max} mm, not {low}")
        if high < right_min:
            raise ValueError(f"{plant.name}'s right edge has to be between {right_min} and {zone_high} mm, not {high}")
        if high - low < sweep.MIN_SPAN_MM:
            raise ValueError(
                f"A sweep needs at least {sweep.MIN_SPAN_MM:.0f} mm to cross. "
                "Use point watering for a pot narrower than that."
            )

        plant.sweep_min_mm = low
        plant.sweep_max_mm = high
        self._persist()
        return {
            "status": "ok",
            "plant_id": plant_id,
            "sweep_min_mm": plant.sweep_min_mm,
            "sweep_max_mm": plant.sweep_max_mm,
            "sweep_span_mm": plant.sweep_max_mm - plant.sweep_min_mm,
        }

    def set_watering_mode(self, plant_id: str, mode: str) -> dict[str, object]:
        """Switch a pot between a fixed point and an oscillating sweep.

        Turning on sweep is refused while the span is too narrow to be one. The
        mode and the span are separate settings, so the alternative is a pot
        labelled "sweep" that waters as a point every time -- configured for
        something it never does, which is the failure mode this codebase keeps
        running into and the reason for the refusal rather than a default span.
        """
        plant = self.get_plant(plant_id)
        if plant is None:
            raise ValueError(f"Unknown plant_id: {plant_id}")

        wanted = str(mode).strip().casefold()
        if wanted not in sweep.MODES:
            raise ValueError(
                "Watering mode has to be one of: " + ", ".join(sweep.MODES)
            )
        if wanted == sweep.SWEEP:
            span = abs(plant.sweep_max_mm - plant.sweep_min_mm)
            if span < sweep.MIN_SPAN_MM:
                raise ValueError(
                    "Set the sweep span first -- it needs at least "
                    f"{sweep.MIN_SPAN_MM:.0f} mm to cross, and is currently "
                    f"{span:.0f} mm."
                )

        plant.watering_mode = wanted
        self._persist()
        return {
            "status": "ok",
            "plant_id": plant_id,
            "watering_mode": plant.watering_mode,
        }

    def _pump_flow(self) -> float:
        """The flow rate every dose is timed against, in mL/s.

        One checked reader rather than three unchecked ones, and the check is
        not decoration. getattr with a default cannot fall back on an object
        that defines __getattr__ -- which the test doubles do -- so reading
        this straight off the pump hands back a bound method where a number is
        wanted. That then reached the state snapshot, where it is not JSON
        serialisable, and took every settings save down with it.
        """
        flow = getattr(self.pump, "flow_ml_per_second", None)
        if isinstance(flow, bool) or not isinstance(flow, (int, float)) or flow <= 0:
            return float(settings.pump_flow_ml_per_second)
        return float(flow)

    def _dose_seconds(self, volume_ml: float) -> float:
        """How long the pump runs for a dose, and so how long a sweep lasts."""
        return max(float(volume_ml) / max(self._pump_flow(), 0.01), 0.1)

    def _motion_limits(self) -> tuple[float, float] | None:
        """Klipper's top speed and acceleration, or None if it did not say.

        None rather than a fallback pair. A sweep's passes are timed to fill
        the dose, so an invented acceleration that is too high leaves the pump
        running through ramps nobody budgeted for and over-waters the pot. No
        sweep is better than a mistimed one.
        """
        status = self.klipper.status()
        speed, accel = status.get("max_velocity"), status.get("max_accel")
        for value in (speed, accel):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            if value <= 0:
                return None
        return float(speed), float(accel)

    def _sweep_motion(
        self, plant: PlantSpec, volume_ml: int
    ) -> tuple[float, list[str] | None]:
        """Where to start the dose, and what to run while it is delivered.

        A motion of None is a point dose, and that is also the fallback every
        time a configured sweep cannot be honoured. The plant still drinks and
        the log says the sweep did not happen, which is the right way round:
        the sweep decides how the water is spread, not whether it arrives.
        """
        resolved = self._resolve_sweep(plant, volume_ml)
        if resolved is None:
            return float(plant.position_mm), None
        if isinstance(resolved, str):
            logger.warning("Watering %s as a point: %s", plant.plant_id, resolved)
            return float(plant.position_mm), None

        low, high, plan = resolved
        logger.info(
            "Sweeping %s across %.0f mm: %d passes at F%d, %.1fs of a %.1fs dose",
            plant.plant_id, high - low, plan.passes, plan.feedrate_mm_min,
            plan.predicted_seconds, self._dose_seconds(volume_ml),
        )
        return low, sweep.gcode(plan, low, high)

    def _resolve_sweep(
        self, plant: PlantSpec, volume_ml: int
    ) -> tuple[float, float, sweep.Plan] | str | None:
        """Whether a dose of this plant would really sweep, and how.

        None for a point plant. A string when it is set to sweep but this dose
        cannot -- the reason it falls back to a point. Otherwise the span and
        the plan. No logging here: the patrol asks the same question every hour
        to show the motion a dose would make, and a "watering as a point"
        warning from a patrol would be about a watering that never happened.
        """
        if plant.watering_mode != sweep.SWEEP:
            return None

        low = min(plant.sweep_min_mm, plant.sweep_max_mm)
        high = max(plant.sweep_min_mm, plant.sweep_max_mm)
        span = high - low

        limit = self.usable_travel_mm()
        if low < 0 or high > limit:
            # A saved span can fall off the rail later: position_max is
            # re-measured from time to time, and Klipper refuses an
            # out-of-range move outright, which would abort the dose rather
            # than spread it differently.
            return (
                f"its sweep of {low:.0f} to {high:.0f} mm is off the usable "
                f"rail (0 to {limit:.0f} mm)"
            )
        # Saves are refused outside the zone, but a span stored before the
        # zones existed, or by hand, can still be out there.
        problem = self._outside_zone(plant, low, high)
        if problem:
            return f"its sweep of {low:.0f} to {high:.0f} mm is outside its zone ({problem})"

        limits = self._motion_limits()
        if limits is None:
            return (
                "Klipper did not report its motion limits, so the passes "
                "cannot be timed against the dose"
            )

        duration = self._dose_seconds(volume_ml)
        plan = sweep.plan(span, duration, limits[0], limits[1])
        if plan is None:
            return (
                f"{volume_ml} mL runs the pump for {duration:.1f}s, which is not "
                f"long enough to cross {span:.0f} mm. Stretching the dose to fit "
                "the motion would over-water it."
            )
        return low, high, plan

    def _patrol_stops(self) -> list[dances.PatrolStop]:
        """Each plant as the patrol should visit it: the way its dose moves.

        A plant that would sweep is swept across, at the speed its own dose
        would use; everything else, including a sweep that would fall back to
        a point, is a pause at its point position. Asked of _resolve_sweep so
        the patrol cannot show a motion the watering would not make.
        """
        stops = []
        for plant in self.plants:
            resolved = self._resolve_sweep(plant, plant.watering_volume_ml)
            if isinstance(resolved, tuple):
                low, high, plan = resolved
                stops.append(dances.PatrolStop(
                    low, sweep_to_mm=high, feedrate=plan.feedrate_mm_min,
                ))
            elif not self._outside_zone(plant, float(plant.position_mm)):
                stops.append(dances.PatrolStop(plant.position_mm))
            # A spot outside its zone is skipped: watering refuses it, so
            # visiting it would show a stop the planter will never water at.
        return stops

    @contextmanager
    def _exclusive(self, what: str) -> Iterator[None]:
        # Fail fast rather than queue: a manual command that waited its turn
        # behind a watering cycle would run minutes after the button was pressed,
        # and a backed-up control loop would water the same plant repeatedly.
        if not self._hardware_lock.acquire(blocking=False):
            raise HardwareBusyError(f"{what} rejected: hardware is busy")
        try:
            yield
        finally:
            self._hardware_lock.release()

    def tick(self) -> None:
        """One pass of the control loop: read every sensor, then water what needs it."""
        # Lighting first and outside the lock: the strip is on its own SPI bus,
        # so it should keep following its schedule even while the gantry is busy.
        try:
            self._apply_lighting()
        except Exception:
            logger.exception("Failed to apply lighting schedule")

        try:
            with self._exclusive("Control loop tick"):
                self._poll_sensors()
                # After the poll, so a verdict sees this tick's reading, and
                # before deciding to water, so a dose just confirmed releases
                # the hold on the same tick.
                try:
                    self._check_soaks()
                except Exception:
                    logger.exception("Could not check whether the last watering reached the soil")
                if self.auto_watering_enabled:
                    held = self.watering_suppressed()
                    if held:
                        # Debug rather than info: this fires every minute for
                        # hours, and at info it would bury the log the user
                        # reads to find out what actually happened.
                        logger.debug("Not watering automatically, %s", held)
                    else:
                        self._run_watering_cycle()
        except HardwareBusyError:
            logger.info("Skipping control loop tick, hardware is busy")
        except Exception:
            # A scheduler job that raises stops being rescheduled, which would
            # silently end all polling.
            logger.exception("Control loop tick failed")

        # Outside the block above so it takes the lock on its own terms: it
        # should never be the reason a watering cycle was skipped. The hourly
        # patrol is not here -- it has its own job pinned to the top of the
        # hour, which a tick a minute apart could not land on.
        self._maybe_home_on_startup()

    def _apply_lighting(self) -> None:
        now = datetime.now().time()
        self.leds.set_plant_segments(
            [
                Zone(
                    start=plant.led_start_index,
                    end=plant.led_end_index,
                    lit=care.light_on(now, plant.light_start_time, plant.light_hours),
                    brightness=plant.light_brightness,
                    color=plant.light_color,
                    manual_color=plant.manual_color,
                    manual_brightness=plant.manual_brightness,
                )
                for plant in self.plants
            ]
        )

    def _poll_sensors(self) -> None:
        samples = []
        for address in self.sensor_hub.addresses:
            sample = self.sensor_hub.read_one(address)
            self._latest[address] = sample
            samples.append(sample)
            if sample.moisture_raw >= 0:
                self._history[address].append(sample.moisture_raw)

        self._has_polled = True

        # One transaction for the whole tick. The store drops failed reads, and
        # a storage fault must not stop the loop from watering.
        try:
            self.history.record_readings(samples)
        except Exception:
            logger.exception("Failed to record readings")

    def thirsty(self, plant: PlantSpec) -> bool:
        """True when this pot has used its water down to the plant's target.

        Both are shares of the pot's own soil's available water, so a target
        can never sit outside what the soil holds. A pot whose moisture cannot
        be said (-1) is never thirsty. That is the whole protection against
        watering on a reading we do not have -- a probe that fell out, or a pot
        whose soil was never recorded.
        """
        percent = self.percent_for_plant(plant)
        return 0 <= percent <= plant.target_available

    def _smoothed_raw(self, address: int) -> float | None:
        """Mean raw count over the window, or None while it is empty."""
        window = self._history.get(address)
        if not window:
            return None
        return sum(window) / len(window)

    def percent_for_plant(self, plant: PlantSpec) -> float:
        """Mean moisture for one pot; this, not a single read, drives watering.

        Takes the plant rather than an address because the top of the scale is
        the pot's field capacity, and two pots on two probes reading the same
        raw count are not at the same place on their own scales.

        smoothed_percent(address) used to do this and has been deleted rather
        than kept alongside. While any function can turn an address into a
        percentage on its own, something will call it and get a number computed
        against the wrong pot's scale -- and a plausible wrong percentage is
        the failure here that nothing downstream can catch.

        -1.0 when there is no judgement to make: an empty window, or no usable
        scale for this pot (see scale_problem).
        """
        mean = self._smoothed_raw(plant.sensor_address)
        if mean is None:
            return -1.0
        return self.sensor_hub.raw_to_percent(mean, plant.sensor_address)

    def _seed_last_watered(self) -> None:
        """Each pot's last dose, from history, so a restart keeps the cooldown.

        Kept only in memory before, which meant a restart let every pot be
        watered again at once -- harmless at a few minutes, not at an hour.
        """
        try:
            last = self.history.last_waterings()
        except Exception:
            logger.exception("Could not read watering history for the cooldown")
            return
        for plant_id, row in last.items():
            self._last_watered[plant_id] = datetime.fromtimestamp(int(row["recorded_at"]))

    # --- did the water reach the soil? -------------------------------------

    def _soak_start_state(self, plant: PlantSpec, volume_ml: int) -> str | None:
        """What a dose about to be recorded starts as: pending, or skipped when
        it cannot be judged. None when the check is switched off."""
        if not settings.soak_check_enabled:
            return None
        if volume_ml <= 0:
            return soak.SKIPPED
        address = plant.sensor_address
        now = int(datetime.now().timestamp())
        start = soak.baseline(
            [raw for _, raw in self.history.raw_readings(address, now - soak.BASELINE_SECONDS, now)]
        )
        return soak.PENDING if soak.can_judge(start, self.sensor_hub.span_for(address)) else soak.SKIPPED

    def _check_soaks(self, now: float | None = None) -> None:
        """Give a verdict on every dose still waiting for its probe to show it."""
        moment = int(datetime.now().timestamp() if now is None else now)
        window = settings.watering_cooldown_minutes * 60
        expected = window // max(1, settings.sensor_poll_seconds)
        for row in self.history.pending_soaks():
            plant = self.get_plant(str(row["plant_id"]))
            dosed = int(row["recorded_at"])
            if plant is None:
                self.history.record_soak(int(row["id"]), soak.SKIPPED)
                continue
            address = plant.sensor_address
            span = self.sensor_hub.span_for(address)
            start = soak.baseline(
                [raw for _, raw in self.history.raw_readings(address, dosed - soak.BASELINE_SECONDS, dosed)]
            )
            if not soak.can_judge(start, span):
                # The soil profile or its reading changed since the dose.
                self.history.record_soak(int(row["id"]), soak.SKIPPED)
                continue
            after = [
                raw for _, raw in
                self.history.raw_readings(address, dosed + 1, min(moment, dosed + window))
            ]
            verdict, rise = soak.judge(
                start, after, span, settings.soak_rise_percent,
                window_done=moment >= dosed + window, expected_readings=expected,
            )
            if verdict == soak.PENDING:
                continue
            self.history.record_soak(int(row["id"]), verdict, rise)
            minutes = round((moment - dosed) / 60)
            if verdict == soak.SOAKED:
                logger.info("Watering of %s showed on its probe after %d min", plant.name, minutes)
            elif verdict == soak.MISSED:
                logger.warning(
                    "Watering of %s never showed on its probe in %d min", plant.name, minutes
                )
            else:
                logger.warning("Could not confirm the watering of %s: its probe went quiet", plant.name)

    def _soak_misses(self) -> list[dict[str, object]]:
        """The unbroken run of misses at the end of the history, newest first,
        since the last Resume."""
        if not settings.soak_check_enabled:
            return []
        try:
            judged = self.history.judged_soaks(since=int(self._soak_reset_at))
        except Exception:
            logger.exception("Could not read the soak check history")
            return []
        misses = []
        for row in judged:
            if row["soak"] != soak.MISSED:
                break
            misses.append(row)
        return misses

    def _plant_name(self, plant_id: object) -> str:
        plant = self.get_plant(str(plant_id))
        return plant.name if plant else str(plant_id)

    def soak_pause_reason(self) -> str | None:
        """What to tell the owner when two misses in a row have paused watering."""
        misses = self._soak_misses()
        if len(misses) < 2:
            return None
        pots = {row["plant_id"] for row in misses[:2]}
        if len(pots) == 1:
            name = self._plant_name(misses[0]["plant_id"])
            return (
                f"{name}'s last 2 waterings didn't show up on its probe. Check the "
                "reservoir has water, then that the nozzle lines up with the pot and "
                "the probe is in the soil."
            )
        return (
            "The last 2 waterings didn't reach the soil. The reservoir is probably "
            "empty. Refill it, then press Resume."
        )

    def resume_watering(self) -> dict[str, object]:
        """Clear a soak-check pause. Earlier misses stop counting."""
        self._soak_reset_at = datetime.now().timestamp()
        self._persist()
        logger.info("Automatic watering resumed after a soak-check pause")
        return self.watering_status()

    # --- what the owner is told ------------------------------------------

    def system_status(self) -> dict[str, object]:
        """The single most important thing to say about the planter right now.

        The status bar used to show the newest log line, which meant it showed
        whatever the software last felt like writing down -- timestamps, levels
        and internal phrasing included. This answers a different question: of
        everything true at this moment, what would the owner most want to know?

        Ordered by urgency, first match wins. Anything that stops the planter
        working comes before anything that is merely worth knowing.
        """
        def state(level: str, message: str) -> dict[str, object]:
            return {"level": level, "message": message}

        # 1. Nothing can be watered if the motion board is not answering.
        movement = self.klipper.status()
        if movement.get("ok") is False:
            return state("problem", "Lost contact with the motion board. Nothing can be watered.")

        # 2. Waterings are running and the pot's own probe never saw the water
        # arrive: an empty tank, a misaimed nozzle or a probe out of the soil.
        paused = self.soak_pause_reason()
        if paused:
            return state("problem", f"Automatic watering is paused. {paused}")
        misses = self._soak_misses()
        if misses:
            name = self._plant_name(misses[0]["plant_id"])
            return state(
                "attention",
                f"{name}'s last watering didn't show up on its moisture probe. Check the "
                "nozzle lines up with the pot and the probe is in the soil.",
            )

        # 3. A probe that answered, and answered that it is not there.
        #
        # Judged on the most recent sample rather than on an empty window:
        # _poll_sensors only records successful reads, so an empty window means
        # "not polled yet" and saying "no sensors are reporting" on a fresh
        # boot would be alarming and wrong. A plant with no sample at all falls
        # through to the gathering case below.
        dead = [
            plant.name
            for plant in self.plants
            if self._has_polled
            and (latest := self._latest.get(plant.sensor_address)) is not None
            and latest.moisture_raw < 0
        ]
        if len(dead) == len(self.plants) and dead:
            return state("problem", "No sensors are reporting. Check the hub connection.")
        if dead:
            return state("attention", f"No reading from {', '.join(dead)}. Check the probe.")

        # 4. Able to water, but not yet allowed to.
        if not movement.get("homed"):
            return state("attention", "The arm has not been homed, so watering is held.")

        held = self.watering_suppressed()
        if held:
            return state("info", f"Automatic watering is paused: {held}.")

        if not self.auto_watering_enabled:
            return state("info", "Watching only. Automatic watering is switched off.")

        # 5. Working, but not yet able to act.
        filling = [
            plant.name
            for plant in self.plants
            if len(self._history.get(plant.sensor_address) or ()) < settings.moisture_window_size
        ]
        if filling:
            return state(
                "info",
                f"Getting to know {', '.join(filling)} — watering starts once "
                "there are enough readings.",
            )

        # 6. Nothing to report, which is the normal case.
        # Pots with no soil cannot be judged at all, and saying so is the
        # point: automatic watering is held for them, and silence would read
        # as "nothing to do" rather than "cannot tell".
        unset = [plant.name for plant in self.plants if not plant.soil]
        if unset and self.auto_watering_enabled:
            return state(
                "attention",
                f"No soil set on {', '.join(unset)}, so watering is held there. "
                f"Set it under Plants and Soil.",
            )

        # A pot with a soil profile but no usable scale cannot be judged at
        # all: its reading is -1, its band is unknown, and it is skipped by
        # every cycle. Without this it fell through to "all plants are happy".
        unmeasured = [
            plant
            for plant in self.plants
            if plant.soil and self.scale_problem(plant) is not None
        ]
        if unmeasured and self.auto_watering_enabled:
            profiles = sorted({plant.soil for plant in unmeasured})
            return state(
                "attention",
                f"Watering is held on {', '.join(p.name for p in unmeasured)} "
                f"({', '.join(profiles)}): {self.scale_problem(unmeasured[0])} "
                "Set it up in the Soil Profile Editor.",
            )

        thirsty = [plant.name for plant in self.plants if self.thirsty(plant)]
        if thirsty:
            return state("ok", f"{', '.join(thirsty)} due a drink shortly.")
        count = len(self.plants)
        return state("ok", f"All {count} plants are happy.")

    # --- automatic watering ----------------------------------------------

    def set_auto_watering(self, enabled: bool) -> dict[str, object]:
        """Turn unattended watering on or off.

        Distinct from quiet hours and snooze, which only pause it. This decides
        whether the loop waters at all, and system_status() words the two
        differently for that reason: "switched off" is a standing choice,
        "paused" resolves itself.
        """
        self.auto_watering_enabled = bool(enabled)
        self._persist()
        logger.info(
            "Automatic watering %s",
            "enabled" if self.auto_watering_enabled else "disabled",
        )
        return self.watering_status()

    def endstop_diagnostic(self) -> dict[str, object]:
        """Read the home switch and say what the reading means.

        The switch is wired normally-closed (`endstop_pin: ^PC0`), so a closed
        contact pulls the pin low and that is the *untriggered* reading. An open
        circuit therefore reads the same as a pressed switch -- which is the
        whole point, because it makes homing refuse rather than drive into the
        end of the rail when a wire breaks.

        That fail-safe is what makes diagnosis interesting: wired-to-NO and
        wired-to-nothing look identical with the carriage parked away from the
        switch. Both read triggered. Nothing in a single reading separates them,
        so this reports the ambiguity and asks for the press test instead of
        guessing, since pressing the switch does separate them -- a NO contact
        closes and the reading flips, a broken wire does not change at all.
        """
        with self._exclusive("Endstop diagnostic"):
            movement = self.klipper.status()
            reading = self.klipper.endstop_state()

        if not reading.get("ok"):
            return {
                "ok": False,
                "verdict": "unavailable",
                "detail": f"Could not read the switch: {reading.get('error')}",
            }

        triggered = bool(reading["triggered"])
        homed = bool(movement.get("homed"))
        position = movement.get("position")
        switch_end = movement.get("max_x")

        # The switch sits at the top of travel and homing drives onto it, so a
        # carriage well below position_max cannot be pressing it. Only true if
        # the axis is homed; unhomed, the reported position is a counter rather
        # than a measurement and proves nothing about where the carriage is.
        at_switch = (
            homed
            and switch_end is not None
            and position is not None
            and float(position) >= float(switch_end) - NEAR_SWITCH_MM
        )

        result: dict[str, object] = {
            "ok": True,
            "triggered": triggered,
            "homed": homed,
            "position": position,
            "switch_end_mm": switch_end,
            "wiring": "normally closed",
        }

        if not homed:
            result["verdict"] = "unknown"
            result["detail"] = (
                f"The switch reads {'triggered' if triggered else 'open'}, but the axis is "
                "not homed, so the carriage could be sitting on the switch for all this "
                "knows. Press and release the switch by hand and watch the reading change."
            )
        elif at_switch and triggered:
            result["verdict"] = "at_switch"
            result["detail"] = (
                "Triggered, and the carriage is parked at the switch end, which is exactly "
                "what that should read. Jog away from the switch to learn anything more."
            )
        elif at_switch:
            result["verdict"] = "suspect"
            result["detail"] = (
                "The carriage is at the switch end but the switch reads open. Either it is "
                "not being depressed -- check the mounting and the alignment -- or it is "
                "wired to the NO terminal rather than NC."
            )
        elif triggered:
            result["verdict"] = "suspect"
            result["detail"] = (
                "Triggered while the carriage is nowhere near the switch. Two things look "
                "like this and a single reading cannot tell them apart: the switch is wired "
                "to NO instead of NC, or the circuit is open -- a broken wire or an unseated "
                "connector. Press the switch: if the reading flips to open you are on NO, "
                "and if it does not change at all the circuit is broken."
            )
        else:
            result["verdict"] = "healthy"
            result["detail"] = (
                "Open, with the carriage away from the switch, which is correct for "
                "normally-closed wiring. Press the switch to confirm it reads triggered, "
                "and unplug it once to confirm that reads triggered too -- that is the "
                "fail-safe, and it is the reason this build specifies NC."
            )

        return result

    def request_power(self, action: str) -> dict[str, object]:
        """Shut down or reboot, but never in the middle of a dose or a move.

        Takes the hardware lock and keeps it: nothing may start a dose in the
        seconds between the reply and the Pi going down, because the pump is
        switched through Klipper and nothing turns it off once the host has
        gone. It is handed back only if the command is refused or fails, so a
        planter that stays up does not stay locked.
        """
        if not self._hardware_lock.acquire(blocking=False):
            raise HardwareBusyError(
                f"{action.capitalize() or 'Power action'} rejected: hardware is busy. "
                "Wait for the watering or move to finish."
            )
        try:
            return system_power.request(action, on_failure=self._hardware_lock.release)
        except Exception:
            self._hardware_lock.release()
            raise

    def pump_status(self) -> dict[str, object]:
        """The flow rate in use, and the run a calibration would divide by."""
        return {
            "status": "ok",
            # Read back off the pump rather than from settings, because the
            # pump is what a dose is actually timed against.
            "flow_ml_per_second": round(self._pump_flow(), 4),
            "seconds_for_100ml": round(self._dose_seconds(100), 1),
            "measured_at": self._flow_measured_at,
            "max_run_seconds": settings.pump_max_run_seconds,
            "min_calibration_seconds": MIN_CALIBRATION_SECONDS,
            "last_run": self._last_pump_run,
        }

    def calibrate_pump_flow(self, measured_ml: float) -> dict[str, object]:
        """Work the flow rate out from the last timed run and what came out.

        Dividing here rather than asking for mL/s directly, because the figure
        someone has in front of them is a reading off a scale. A rate they
        worked out themselves is a rate with their arithmetic in it, and this
        number scales every dose the planter ever gives.

        Refused rather than stored whenever the answer could not be a real
        measurement. A wrong flow rate is worse than no flow rate: it is the
        one error that scales every watering by the same factor and still
        reports success, which is exactly what nobody notices.
        """
        if self._last_pump_run is None:
            raise ValueError(
                "Run the pump first -- a flow rate is a volume divided by the "
                "time it took to deliver it."
            )

        if isinstance(measured_ml, bool) or not isinstance(measured_ml, (int, float)):
            raise ValueError("Give the measured volume as a number of millilitres")
        volume = float(measured_ml)

        seconds = float(self._last_pump_run["seconds"])
        if seconds < MIN_CALIBRATION_SECONDS:
            # Not about the pump settling -- it is about the scale. A short run
            # delivers a small volume, and a kitchen scale reading to the gram
            # is a far bigger share of 20 g than of 100 g.
            raise ValueError(
                f"That run was only {seconds:.0f}s. Run the pump for at least "
                f"{MIN_CALIBRATION_SECONDS:.0f}s, or the volume is too small "
                "to weigh accurately."
            )

        flow = volume / seconds
        if not (MIN_FLOW_ML_PER_SECOND <= flow <= MAX_FLOW_ML_PER_SECOND):
            # Catches the realistic slip: a decimal in the wrong place, or
            # millilitres confused with something else. Both give a number that
            # stores happily and then mis-doses every pot by that factor.
            #
            # It is also what rejects a volume of zero, a negative one, or an
            # infinity: each produces a rate outside this range. A separate
            # check for those sat here until mutation testing showed it could
            # never fail on its own.
            raise ValueError(
                f"{volume:.0f} mL in {seconds:.0f}s is {flow:.2f} mL/s, which is "
                f"outside what this pump can do ({MIN_FLOW_ML_PER_SECOND} to "
                f"{MAX_FLOW_ML_PER_SECOND} mL/s). Check the figure."
            )

        self.pump.flow_ml_per_second = flow
        self._flow_measured_at = datetime.now().isoformat(timespec="seconds")
        self._persist()
        logger.info(
            "Pump flow calibrated to %.3f mL/s from %.1f mL in %.1fs",
            flow, volume, seconds,
        )
        return {
            "status": "ok",
            "flow_ml_per_second": round(flow, 4),
            "measured_ml": volume,
            "run_seconds": seconds,
            "measured_at": self._flow_measured_at,
            # What the calibration means in the units the user actually sets,
            # so the number can be sanity-checked against a real dose.
            "seconds_for_100ml": round(100 / flow, 1),
        }

    def watering_status(self) -> dict[str, object]:
        return {
            "status": "ok",
            "auto_watering_enabled": self.auto_watering_enabled,
            "soak_check_enabled": settings.soak_check_enabled,
            # Why automatic watering is paused after misses, or None. The
            # Automation tab shows it with the Resume button.
            "soak_paused": self.soak_pause_reason(),
            "cooldown_minutes": settings.watering_cooldown_minutes,
        }

    # --- quiet hours and snooze ------------------------------------------

    def watering_suppressed(self, now: datetime | None = None) -> str | None:
        """Why automatic watering is being held back, or None if it is not.

        Returns the reason rather than a bare bool so the UI and the log can
        say which of the two is in force. A plant that comes due during a quiet
        period is not skipped, only deferred: the loop runs every minute and
        waters it on the first tick after the window closes.
        """
        moment = now or datetime.now()

        if self.soak_pause_reason():
            return "2 waterings in a row didn't reach the soil. Press Resume once it's sorted"

        # One unconfirmed dose holds every pot, not just its own: if the tank
        # is empty, watering the next pot and the next would run the pump dry
        # on each of them before the first miss was even known.
        if settings.soak_check_enabled:
            try:
                pending = self.history.pending_soaks()
            except Exception:
                logger.exception("Could not read pending soak checks")
                pending = []
            if pending:
                name = self._plant_name(pending[-1]["plant_id"])
                return f"waiting to confirm the last watering reached {name}"

        if self.snooze_until and moment < self.snooze_until:
            return f"snoozed until {self.snooze_until.strftime('%H:%M')}"

        if self.quiet_hours_enabled and within_window(
            moment.time(), self.quiet_hours_start, self.quiet_hours_stop
        ):
            return (
                f"quiet hours until {self.quiet_hours_stop.strftime('%H:%M')}"
            )
        return None

    def set_quiet_hours(self, enabled: bool, start: str | None = None, stop: str | None = None) -> dict[str, object]:
        if start is not None:
            self.quiet_hours_start = time.fromisoformat(start)
        if stop is not None:
            self.quiet_hours_stop = time.fromisoformat(stop)
        self.quiet_hours_enabled = bool(enabled)
        self._persist()
        return self.quiet_status()

    def snooze_watering(self, hours: float) -> dict[str, object]:
        """Hold off automatic watering for a while, from now."""
        if hours <= 0:
            raise ValueError("Snooze length must be positive")
        if hours > 24:
            raise ValueError("Snooze is capped at 24 hours")
        self.snooze_until = datetime.now() + timedelta(hours=hours)
        self._persist()
        logger.info("Automatic watering snoozed until %s", self.snooze_until)
        return self.quiet_status()

    def cancel_snooze(self) -> dict[str, object]:
        self.snooze_until = None
        self._persist()
        logger.info("Watering snooze cancelled")
        return self.quiet_status()

    def quiet_status(self) -> dict[str, object]:
        return {
            "status": "ok",
            "quiet_hours_enabled": self.quiet_hours_enabled,
            "quiet_hours_start": self.quiet_hours_start.isoformat(timespec="minutes"),
            "quiet_hours_stop": self.quiet_hours_stop.isoformat(timespec="minutes"),
            "snooze_until": self.snooze_until.isoformat(timespec="minutes") if self.snooze_until else None,
            "suppressed_because": self.watering_suppressed(),
        }

    def _run_watering_cycle(self) -> None:
        for plant in self.plants:
            window = self._history.get(plant.sensor_address)
            # Only act on a full window, so neither a single bad reading nor the
            # first minutes after a restart can start the pump.
            if not window or len(window) < window.maxlen:
                continue

            if not self.thirsty(plant):
                continue
            if not self._cooldown_elapsed(plant.plant_id):
                continue

            logger.info(
                "Plant %s is at %.0f%% soil water against a target of %s%%, watering",
                plant.plant_id,
                self.percent_for_plant(plant),
                plant.target_available,
            )
            self._move_and_water(plant)

    def _cooldown_elapsed(self, plant_id: str) -> bool:
        # Soil needs time to wick, and the window needs a full cycle to reflect
        # the change. Without this the loop would water every tick until the
        # average caught up, which is how a plant drowns.
        last = self._last_watered.get(plant_id)
        if last is None:
            return True
        return datetime.now() - last >= timedelta(minutes=settings.watering_cooldown_minutes)

    def run_pump(self) -> dict[str, object]:
        """Start the pump and leave it running, for bench testing."""
        # Held across requests rather than through _exclusive, so the control
        # loop cannot start a watering cycle while the pump is manually on.
        if not self._hardware_lock.acquire(blocking=False):
            raise HardwareBusyError("Pump run rejected: hardware is busy")
        self._pump_lock_held = True

        result = self.pump.start()
        if not result.get("ok", True) or not self.pump.is_running:
            # Release rather than strand the lock and block watering forever.
            self._release_pump_lock()
            return {"status": "error", "error": "pump did not start"}

        # Nothing else stops this if the browser closes or the network drops.
        self._pump_timer = threading.Timer(settings.pump_max_run_seconds, self._auto_stop_pump)
        self._pump_timer.daemon = True
        self._pump_timer.start()

        self._pump_run_started = monotonic()
        logger.info("Pump running, auto-stop in %ds", settings.pump_max_run_seconds)
        return {
            "status": "ok",
            "running": True,
            "max_run_seconds": settings.pump_max_run_seconds,
        }

    def stop_pump(self) -> dict[str, object]:
        """Stop the pump. Safe to call at any time, running or not."""
        if self._pump_timer:
            self._pump_timer.cancel()
            self._pump_timer = None

        self.pump.stop()
        if self._pump_run_started is not None:
            self._last_pump_run = {
                "seconds": round(monotonic() - self._pump_run_started, 2),
                "at": datetime.now().isoformat(timespec="seconds"),
            }
            self._pump_run_started = None
            logger.info("Pump ran for %ss", self._last_pump_run["seconds"])
        self._release_pump_lock()
        return {"status": "ok", "running": False}

    def _auto_stop_pump(self) -> None:
        logger.warning("Pump hit its %ds limit, stopping", settings.pump_max_run_seconds)
        self.stop_pump()

    def _release_pump_lock(self) -> None:
        # Guarded: releasing a lock nobody holds would let the control loop and a
        # manual command run the hardware at the same time.
        if self._pump_lock_held:
            self._pump_lock_held = False
            self._hardware_lock.release()

    def _move_and_water(
        self, plant: PlantSpec, volume_ml: int | None = None, trigger: str = "auto"
    ) -> dict[str, object]:
        volume = plant.watering_volume_ml if volume_ml is None else max(0, int(volume_ml))

        # Resolved before the move, because a sweep starts at one end of its
        # span rather than at the pot's point position.
        start_mm, motion = self._sweep_motion(plant, volume)
        # A sweep was already checked against the zone. A point is checked
        # here, because a spot stored before the ranges existed would otherwise
        # water whichever pot sits under it.
        if motion is None:
            problem = self._outside_zone(plant, start_mm)
            if problem:
                error = (
                    f"its watering spot of {start_mm:g} mm is out of range "
                    f"({problem}). Set it again in the Plants tab."
                )
                logger.warning("Not watering %s: %s", plant.plant_id, error)
                return {"status": "error", "plant_id": plant.plant_id, "error": error}
        move = self.klipper.move_gantry_absolute(start_mm)
        if not move.get("ok"):
            logger.warning(
                "Not watering %s: gantry move failed (%s)", plant.plant_id, move.get("error")
            )
            return {"status": "error", "plant_id": plant.plant_id, "error": move.get("error")}

        self.pump.deliver_ml(volume, motion=motion)

        self._last_watered[plant.plant_id] = datetime.now()
        try:
            # Pending until the pot's probe shows the water (see _check_soaks),
            # which also holds automatic watering for every pot meanwhile.
            soak_state = self._soak_start_state(plant, volume)
        except Exception:
            logger.exception("Could not start the soak check for %s", plant.plant_id)
            soak_state = None
        try:
            self.history.record_watering(plant.plant_id, volume, trigger, soak=soak_state)
        except Exception:
            logger.exception("Failed to record watering for %s", plant.plant_id)
        return {"status": "ok", "plant_id": plant.plant_id, "volume_ml": volume}

    def _last_watered_iso(self, plant_id: str) -> str | None:
        last = self._last_watered.get(plant_id)
        return last.isoformat(timespec="seconds") if last else None

    def _last_soaks(self) -> dict[str, dict[str, object]]:
        """Each pot's last dose and its soak verdict, for the plant cards."""
        try:
            last = self.history.last_waterings()
        except Exception:
            logger.exception("Could not read the last waterings")
            return {}
        now = datetime.now().timestamp()
        result = {}
        for plant_id, row in last.items():
            if row.get("soak") is None:
                continue
            dosed = int(row["recorded_at"])
            result[plant_id] = {
                "state": row["soak"],
                "at": datetime.fromtimestamp(dosed).isoformat(timespec="seconds"),
                # Minutes since the dose: how long it has waited, while pending.
                "minutes": max(0, round((now - dosed) / 60)),
                "rise": row.get("soak_rise"),
            }
        return result

    def _moisture_level(self, plant: PlantSpec) -> str | None:
        """The pot's live reading in the plant profiles' own words, or None."""
        percent = self.percent_for_plant(plant)
        return care.water_level_for(percent) if percent >= 0 else None

    def get_overview(self) -> dict[str, object]:
        soaks = self._last_soaks()
        plant_status = [
            PlantStatus(
                plant_id=spec.plant_id,
                moisture_percent=self.percent_for_plant(spec),
                moisture_level=self._moisture_level(spec),
                target_available=spec.target_available,
                thirsty=self.thirsty(spec),
                pump_active=self.pump.is_running,
                lighting_mode=self.leds.mode,
                last_watered=self._last_watered_iso(spec.plant_id),
                sample_count=len(self._history.get(spec.sensor_address) or ()),
                window_size=settings.moisture_window_size,
                scale_problem=self.scale_problem(spec),
                last_soak=soaks.get(spec.plant_id),
            )
            for spec in self.plants
        ]

        return {
            "app": settings.app_name,
            "movement": self.klipper.status(),
            "lighting": {
                **self.leds.status(),
                # The pots' own manual settings, for the zone picker.
                "zones": [self._zone_status(plant) for plant in self.plants],
            },
            "plants": [status.__dict__ for status in plant_status],
            # So the UI can say why nothing is watering rather than leaving it
            # looking broken.
            "watering": self.watering_status(),
            "auto_patrol": self.auto_patrol_status(),
            "startup_home": self.startup_home_status(),
            "quiet": self.quiet_status(),
            # What the status bar shows. Computed rather than echoed from the
            # log, so it says what is true now instead of what was last written.
            "system_status": self.system_status(),
        }

    def get_history(self, hours: float) -> dict[str, object]:
        """Bucketed history for the chart, plants aligned onto one timestamp axis."""
        addresses = [plant.sensor_address for plant in self.plants]
        bucket, timestamps, series = self.history.series(addresses, hours)

        return {
            "hours": hours,
            "bucket_seconds": bucket,
            "timestamps": timestamps,
            "plants": [
                {
                    "plant_id": plant.plant_id,
                    "name": plant.name,
                    "sensor_address": plant.sensor_address,
                    "target_available": plant.target_available,
                    **series[plant.sensor_address],
                }
                for plant in self.plants
            ],
            "waterings": self.history.waterings(hours),
        }

    def read_sensors(self) -> list[dict[str, object]]:
        """Last polled reading per sensor; the control loop owns the I2C bus.

        Keyed by bus address rather than by plant, so an address no pot claims
        still appears -- it is reported with a null plant_id and no average,
        which is how a stray or misconfigured sensor stays visible instead of
        borrowing another pot's scale.
        """
        entries = []
        for address in self.sensor_hub.addresses:
            plant = self.plant_for_address(address)
            entries.append(
                {
                    **self._latest[address].__dict__,
                    "plant_id": plant.plant_id if plant else None,
                    "sample_count": len(self._history[address]),
                }
            )
        return entries

    def water_plant(self, plant_id: str, volume_ml: int | None = None) -> dict[str, object]:
        plant = self.get_plant(plant_id)
        if plant is None:
            raise ValueError(f"Unknown plant_id: {plant_id}")

        # Moves first, like the automatic path. Pumping without moving waters
        # whatever the nozzle happens to be parked over.
        with self._exclusive(f"Watering {plant_id}"):
            return self._move_and_water(plant, volume_ml, trigger="manual")

    def calibrate_moisture(self, endpoint: str, seconds: int = 20) -> dict[str, object]:
        """Measure one calibration endpoint for every sensor.

        Holds the hardware lock: this hammers the I2C bus for the whole window,
        and a watering cycle running at the same time would both skew the
        readings and be slowed by them.
        """
        if endpoint != "dry":
            raise ValueError(
                f"endpoint must be 'dry', not {endpoint!r}. Field capacity is "
                "measured per soil mix: POST /soils/{name}/field-capacity."
            )
        bounded = max(5, min(int(seconds), 120))

        with self._exclusive(f"Calibrating {endpoint} point"):
            results = calibrate(self.sensor_hub, endpoint, bounded, state_path=self._state_path)
        # A new air reading moves every estimated wilting point.
        self._sync_scales()

        stored =sum(1 for item in results.values() if item.get("written"))
        # Carries the plant name as well as the address: the owner of one of
        # these should be told "Plant 2", not asked to recognise 0x37.
        names = self.plant_names()
        return {
            "status": "ok",
            "endpoint": endpoint,
            "seconds": bounded,
            "stored": stored,
            "total": len(results),
            "sensors": [
                {
                    "address": f"0x{address:02x}",
                    "plant": names.get(address),
                    "label": label_for(address, names),
                    **{key: value for key, value in outcome.items() if key != "address"},
                }
                for address, outcome in sorted(results.items())
            ],
        }

    def plant_names(self) -> dict[int, str]:
        """Address to the name currently shown for that plant."""
        return {plant.sensor_address: plant.name for plant in self.plants}

    def moisture_calibration(self) -> dict[str, object]:
        """Both ends of every probe's scale, with where each came from.

        The halves do not share a source. Dry is measured per probe and read
        back from moisture_calibration; field capacity comes from the pot's
        soil profile, and wilting point from both. Reporting them together is
        what makes a pot missing one visible -- it reads -1 rather than a
        percentage, and is never watered.
        """
        stored = state.load_calibration(self._state_path)
        names = self.plant_names()
        sensors = []
        for address in self.sensor_hub.addresses:
            plant = self.plant_for_address(address)
            sensors.append(
                {
                    "address": f"0x{address:02x}",
                    "plant": names.get(address),
                    "plant_id": plant.plant_id if plant else None,
                    "label": label_for(address, names),
                    "dry": self.sensor_hub.dry_for(address),
                    "calibrated_dry": "dry" in stored.get(address, {}),
                    "soil": plant.soil if plant else "",
                    "field_capacity_raw": self.sensor_hub.field_capacity.get(address),
                    "wilting_point_raw": self.sensor_hub.wilting_point.get(address),
                    "wilting_point_source": self.wilting_point_source(plant) if plant else "",
                    # The pot's scale runs wilting point to field capacity; the
                    # dry point is only a check on the probe.
                    "usable": self.sensor_hub.span_for(address) is not None,
                    "scale_problem": self.scale_problem(plant) if plant else None,
                }
            )
        return {
            "status": "ok",
            "default_dry": settings.moisture_raw_dry,
            "sensors": sensors,
        }

    def _capture_field_capacity(self, plant: PlantSpec, seconds: int) -> dict[str, object]:
        """Sample one probe for a field-capacity figure. Stores nothing.

        The span check compares against that probe's own dry point rather than
        anything on the soil, because the figure is denominated in this
        probe's counts. Unlike the old wet pass the dry side always has a
        value -- the configured default if nothing was measured -- so the check
        always runs rather than being skipped.
        """
        bounded = max(5, min(int(seconds), 120))
        with self._exclusive(f"Measuring field capacity on {plant.name}"):
            return measure_endpoint(
                self.sensor_hub,
                plant.sensor_address,
                seconds=bounded,
                opposite=self.sensor_hub.dry_for(plant.sensor_address),
                expect="above",
                opposite_label="this probe's dry point",
            )

    def calibrate_soil_field_capacity(
        self, soil_name: str, plant_id: str, seconds: int = 20
    ) -> dict[str, object]:
        """Measure a mix's field capacity using one pot's probe.

        `plant_id` names only *which probe* to read; the figure lands on the
        mix. Probes of the same kind read closely enough that one good figure
        per mix beats four nobody got round to taking, and one figure per mix
        is far simpler to explain than one per pot.

        Every pot filled with this mix reads against it at once. Their names
        are reported, because it changes how those pots read.
        """
        plant = self.get_plant(plant_id)
        if plant is None:
            raise ValueError(f"Unknown plant_id: {plant_id}")

        soils = state.load_soils(self._state_path)
        key = next((k for k in soils if k.casefold() == str(soil_name).strip().casefold()), None)
        if key is None:
            raise ValueError(f"No soil profile called {str(soil_name).strip()!r}")

        outcome = self._capture_field_capacity(plant, seconds)
        outcome["soil"] = key
        outcome["measured_with"] = plant.name
        outcome["inherited_by"] = []
        if not outcome.get("written"):
            return outcome

        measured_at = datetime.now().isoformat(timespec="seconds")
        state.save_soil(
            key,
            {
                "field_capacity_raw": int(outcome["value"]),
                "field_capacity_samples": outcome.get("samples"),
                "field_capacity_measured_at": measured_at,
                "field_capacity_address": plant.sensor_address,
            },
            self._state_path,
        )

        self._sync_scales()
        inherited = self._pots_using(key)
        outcome["inherited_by"] = inherited
        logger.info(
            "Field capacity for %r is %s, measured on %s, used by %d pot(s)",
            key, outcome["value"], plant.name, len(inherited),
        )
        return outcome

    def _pots_using(self, soil: str) -> list[str]:
        """Names of the pots filled with this soil profile."""
        return [pot.name for pot in self.plants if pot.soil.casefold() == soil.casefold()]

    def calibrate_soil_wilting_point(
        self, soil_name: str, plant_id: str, seconds: int = 20
    ) -> dict[str, object]:
        """Measure a mix's wilting point as a raw reading, using one pot's probe.

        Optional: without it, each pot estimates one. It must land between the
        probe's dry point and the mix's field capacity, when that has been
        measured -- a wilting reading wetter than field capacity means the
        wrong probe or the wrong pot.
        """
        plant = self.get_plant(plant_id)
        if plant is None:
            raise ValueError(f"Unknown plant_id: {plant_id}")

        soils = state.load_soils(self._state_path)
        key = next((k for k in soils if k.casefold() == str(soil_name).strip().casefold()), None)
        if key is None:
            raise ValueError(f"No soil profile called {str(soil_name).strip()!r}")

        bounded = max(5, min(int(seconds), 120))
        with self._exclusive(f"Measuring wilting point on {plant.name}"):
            outcome = measure_endpoint(
                self.sensor_hub,
                plant.sensor_address,
                seconds=bounded,
                opposite=self.sensor_hub.dry_for(plant.sensor_address),
                expect="above",
                opposite_label="this probe's dry point",
            )
        outcome["soil"] = key
        outcome["measured_with"] = plant.name
        if not outcome.get("written"):
            return outcome

        capacity = soils[key].get("field_capacity_raw")
        if isinstance(capacity, (int, float)) and outcome["value"] >= capacity:
            outcome.update(
                written=False,
                reason=(
                    f"Reading {outcome['value']} is not below this mix's field "
                    f"capacity of {int(capacity)}. Wilting point is the dry end "
                    "of the usable window, so this is the wrong pot or the wrong "
                    "probe, or the field capacity figure is stale."
                ),
            )
            return outcome

        state.save_soil(
            key,
            {
                "wilting_point_raw": int(outcome["value"]),
                "wilting_point_samples": outcome.get("samples"),
                "wilting_point_measured_at": datetime.now().isoformat(timespec="seconds"),
                "wilting_point_address": plant.sensor_address,
            },
            self._state_path,
        )
        # The bottom of every pot using this soil profile just moved.
        self._sync_scales()
        logger.info(
            "Wilting point for %r is %s, measured on %s", key, outcome["value"], plant.name
        )
        return outcome

    def reset_moisture_calibration(self) -> dict[str, object]:
        state.clear_calibration(self._state_path)
        self.sensor_hub.calibration = {}
        # An estimated wilting point is measured up from the air reading.
        self._sync_scales()
        return {"status": "ok", "message": "Calibration cleared, using .env defaults"}

    # What Restore to Defaults keeps from the state file: the two libraries,
    # which are reference data built up over time rather than this planter's
    # configuration. Everything else in the file goes, as on a fresh install.
    # History lives in its own database and is not touched either.
    KEPT_STATE_KEYS = (state.PROFILES_KEY, state.SOILS_KEY)

    def restore_system_defaults(self) -> dict[str, object]:
        """Put the planter back as it was freshly installed, live.

        Every setting returns to .env or the code default, and every pot to its
        default plant: name, watering spot, sweep span and mode, soil profile,
        care settings. The plant profile and soil libraries and
        the history database are kept.

        Applied in memory as well as on disk, so the planter runs on the
        defaults now rather than after a restart. Under the hardware lock,
        because it replaces the plant list a watering cycle would be iterating.
        """
        with self._exclusive("Restore to defaults"):
            self._restore_defaults_locked()
        logger.info("Restored the planter to its defaults, libraries kept")
        return {"status": "ok"}

    def _restore_defaults_locked(self) -> None:
        self.plants = default_plants()
        self.apply_default_led_ranges()
        # Before the sync: an estimated wilting point is measured up from it.
        self.sensor_hub.calibration = {}
        self._sync_scales()
        # Last-watered times are kept: they are about the water already in the
        # pots, and dropping them would let the cooldown be skipped.

        self.auto_watering_enabled = settings.auto_watering_enabled
        self.pump.flow_ml_per_second = float(settings.pump_flow_ml_per_second)
        self._flow_measured_at = None

        self.auto_patrol_enabled = settings.auto_patrol_enabled
        self.home_on_startup = settings.home_on_startup

        self.quiet_hours_enabled = settings.quiet_hours_enabled
        self.quiet_hours_start = time.fromisoformat(settings.quiet_hours_start)
        self.quiet_hours_stop = time.fromisoformat(settings.quiet_hours_stop)
        self.snooze_until = None
        # The history is kept, so its old misses must not pause the fresh
        # planter: a restore counts as a Resume.
        self._soak_reset_at = datetime.now().timestamp()

        # Chip before order: choosing a chip resets the order to that chip's
        # usual one, and .env may override it.
        self.leds.set_chip(settings.led_chip)
        if settings.led_color_order:
            self.leds.set_color_order(settings.led_color_order)
        self.leds.set_brightness(DEFAULT_BRIGHTNESS)
        self.leds.set_rainbow_speed(DEFAULT_RAINBOW_SPEED)
        self.leds.set_manual_scope(DEFAULT_MANUAL_SCOPE)
        self.leds.color = DEFAULT_COLOR
        self.leds.set_mode(DEFAULT_MODE)
        # Again, after the chip: it sets the pixel count the zones split.
        self.apply_default_led_ranges()

        state.keep_only(self.KEPT_STATE_KEYS, self._state_path)

    def set_light_mode(self, mode: str) -> dict[str, object]:
        result = self.leds.set_mode(mode)
        self._persist()
        return {"status": "ok", "mode": result["mode"]}

    def set_light_color(self, color: tuple[int, int, int]) -> dict[str, object]:
        result = self.leds.set_static_color(color)
        self._persist()
        return {
            "status": "ok",
            "mode": result["mode"],
            "color": result["color"],
        }

    def set_light_color_order(self, order: str) -> dict[str, object]:
        result = self.leds.set_color_order(order)
        self._persist()
        return result

    def set_light_chip(self, chip: str) -> dict[str, object]:
        result = self.leds.set_chip(chip)
        # The chip sets the pixel count, so the zones are split again now
        # rather than after a restart.
        self.apply_default_led_ranges()
        self._apply_lighting()
        self._persist()
        return result

    def set_light_brightness(self, brightness: int) -> dict[str, object]:
        result = self.leds.set_brightness(brightness)
        self._persist()
        return {
            "status": "ok",
            "brightness": result["brightness"],
        }

    def set_light_rainbow_speed(self, speed: int) -> dict[str, object]:
        result = self.leds.set_rainbow_speed(speed)
        self._persist()
        return result

    def set_light_manual_scope(self, scope: str) -> dict[str, object]:
        result = self.leds.set_manual_scope(scope)
        self._persist()
        return result

    def _plant_or_error(self, plant_id: str) -> PlantSpec:
        plant = self.get_plant(plant_id)
        if plant is None:
            raise ValueError(f"Unknown plant_id: {plant_id}")
        return plant

    def set_plant_light_color(self, plant_id: str, color: object) -> dict[str, object]:
        """The colour this pot's stretch of strip shows during its scheduled hours."""
        plant = self._plant_or_error(plant_id)
        plant.light_color = care.check_light_color(color)
        self._persist()
        self._apply_lighting()
        return {"status": "ok", "plant_id": plant_id, "light_color": list(plant.light_color)}

    def set_zone_manual(
        self, plant_id: str, color: object = None, brightness: object = None
    ) -> dict[str, object]:
        """This pot's own colour and brightness in manual mode, zones scope."""
        plant = self._plant_or_error(plant_id)
        # Both checked before either is applied, so a bad one changes nothing.
        checked_color = care.check_light_color(color) if color is not None else plant.manual_color
        checked_brightness = (
            care.check_light_brightness(brightness) if brightness is not None else plant.manual_brightness
        )
        plant.manual_color = checked_color
        plant.manual_brightness = checked_brightness
        self._persist()
        self._apply_lighting()
        return {"status": "ok", **self._zone_status(plant)}

    @staticmethod
    def _zone_status(plant: PlantSpec) -> dict[str, object]:
        return {
            "plant_id": plant.plant_id,
            "name": plant.name,
            "manual_color": list(plant.manual_color),
            "manual_brightness": plant.manual_brightness,
        }

    # --- routines ---------------------------------------------------------

    def run_dance(self, name: str, home_first: bool = False) -> dict[str, object]:
        """Run one routine now. Not gated by quiet hours -- see auto_patrol."""
        # Only a routine that visits the plants needs them resolved, and doing
        # so asks Klipper for its motion limits once per sweeping plant.
        dance = dances.DANCES.get(name)
        visits = dance is not None and dance.visits_plants
        steps = dances.steps_for(
            name, self.usable_travel_mm(), self._patrol_stops() if visits else None
        )

        with self._exclusive(f"Dance {name}"):
            status = self.klipper.status()
            if not status.get("ok"):
                return {"ok": False, "error": status.get("error") or "Klipper is not responding"}

            # An unhomed axis refuses every move, so there is no point
            # starting. Homing anyway is also the honest thing for a routine
            # whose job is partly to re-establish where the carriage is.
            if home_first or not status.get("homed"):
                homed = self._home()
                if not homed.get("ok"):
                    return {"ok": False, "error": f"Homing failed: {homed.get('error')}"}

            # One script for the whole routine, at the motion timeout: the
            # default five seconds is shorter than any of these take, and the
            # socket does not answer until the last move lands.
            result = self.klipper.send_gcode(
                dances.gcode_for(steps), timeout=MOTION_TIMEOUT
            )

        if not result.get("ok"):
            return {"ok": False, "error": result.get("error")}
        return {"ok": True, "dance": name}

    # --- the startup home -------------------------------------------------

    def _maybe_home_on_startup(self) -> None:
        """Home after startup, retrying every tick until it lands.

        Not in the lifespan hook, where it would hold the API down for the
        length of the travel before serving anything. Not in __init__ either,
        for the same reason and because nothing has the hardware lock yet.

        A failure is retried rather than given up on. The usual cause is the
        Pi bringing this service up before Klipper is ready, which sorts itself
        out within a minute or two -- and until the arm is homed, watering is
        refused outright, so giving up would leave the planter dry until a
        restart. One attempt a tick is slow enough not to crowd real work.

        Held during quiet hours and a snooze like every other unattended
        movement; still owed, so it homes as soon as the window closes.
        """
        if not self._startup_home_pending:
            return
        if not self.home_on_startup:
            # The startup moment has passed with it switched off. Turning it on
            # afterwards waits for the next start rather than homing out of
            # nowhere, which is the surprise the switch exists to prevent.
            self._startup_home_pending = False
            return

        held = self.watering_suppressed()
        if held:
            logger.debug("Deferring the startup home, %s", held)
            return

        self._startup_home_attempts += 1
        try:
            result = self.home_gantry()
        except HardwareBusyError:
            # Someone else has the arm; that is not a failed attempt.
            self._startup_home_attempts -= 1
            logger.debug("Deferring the startup home, hardware is busy")
            return
        except Exception as exc:
            result = {"ok": False, "error": str(exc) or type(exc).__name__}

        if result.get("ok"):
            # _home has already settled the pending flag.
            self._startup_home_error = None
            if self._startup_home_attempts > 1:
                logger.info("Homed on startup, attempt %d", self._startup_home_attempts)
            else:
                logger.info("Homed on startup")
            return

        self._startup_home_error = str(result.get("error") or "unknown error")
        # Warned once, then quiet: Klipper being down for an hour would
        # otherwise write sixty identical lines.
        log = logger.warning if self._startup_home_attempts == 1 else logger.debug
        log(
            "Startup home did not run (%s), retrying every tick",
            self._startup_home_error,
        )

    def set_home_on_startup(self, enabled: bool) -> dict[str, object]:
        self.home_on_startup = bool(enabled)
        self._persist()
        return self.startup_home_status()

    def startup_home_status(self) -> dict[str, object]:
        """Where the startup home stands. Asks Klipper nothing."""
        if not self.home_on_startup:
            phase = "off"
        elif self._startup_homed:
            phase = "done"
        elif not self._startup_home_pending:
            # Switched on after this start had already gone by.
            phase = "next_start"
        elif self._startup_home_error:
            phase = "retrying"
        else:
            phase = "waiting"
        return {
            "enabled": self.home_on_startup,
            "phase": phase,
            "attempts": self._startup_home_attempts,
            "error": self._startup_home_error,
            "held": self.watering_suppressed() if phase in ("waiting", "retrying") else None,
        }

    # --- hourly auto-patrol -----------------------------------------------

    def auto_patrol(
        self,
        now: datetime | None = None,
        busy_wait_seconds: float = PATROL_BUSY_WAIT_SECONDS,
    ) -> None:
        """Home and patrol the plants. Called by the scheduler on the hour.

        Its own job rather than part of tick: the loop runs a minute apart
        from wherever the service happened to start, so it could only ever
        land somewhere in the first minute of the hour.

        Quiet hours or a snooze skip the hour rather than defer it, so the
        patrol only ever happens on the hour. Busy hardware is waited out
        for a few minutes instead -- that is nearly always a dose in
        progress, and skipping a whole hour for one would be a waste.
        """
        if not self.auto_patrol_enabled:
            return

        moment = now or datetime.now()
        held = self.watering_suppressed(moment)
        if held:
            logger.debug("Skipping the hourly patrol, %s", held)
            return

        deadline = monotonic() + busy_wait_seconds
        while True:
            try:
                result = self.run_dance("patrol", home_first=True)
                break
            except HardwareBusyError:
                if monotonic() >= deadline:
                    logger.info("Skipping the hourly patrol, hardware stayed busy")
                    self._last_patrol = {
                        "at": moment.isoformat(timespec="minutes"),
                        "ok": False,
                        "error": "hardware was busy",
                    }
                    return
                sleep(PATROL_BUSY_POLL_SECONDS)
            except Exception as exc:
                logger.exception("Hourly patrol failed")
                result = {"ok": False, "error": str(exc) or type(exc).__name__}
                break

        self._last_patrol = {
            "at": moment.isoformat(timespec="minutes"),
            "ok": bool(result.get("ok")),
            "error": None if result.get("ok") else result.get("error"),
        }
        if result.get("ok"):
            logger.info("Homed and patrolled the plants")
        else:
            logger.warning("Hourly patrol did not run: %s", result.get("error"))

    def set_auto_patrol(self, enabled: bool) -> dict[str, object]:
        self.auto_patrol_enabled = bool(enabled)
        self._persist()
        return self.auto_patrol_status()

    def auto_patrol_status(self) -> dict[str, object]:
        """Cheap enough for /overview -- asks Klipper nothing."""
        return {
            "enabled": self.auto_patrol_enabled,
            "last": self._last_patrol,
        }

    def dance_catalogue(self) -> list[dict]:
        """The routines and what they do. No Klipper round trip -- the list
        does not depend on the rail length."""
        return dances.catalogue()

    def home_gantry(self) -> dict[str, object]:
        with self._exclusive("Homing gantry"):
            return self._home()

    def move_gantry_relative(self, distance_mm: float) -> dict[str, object]:
        with self._exclusive("Gantry move"):
            return self.klipper.move_gantry_relative(distance_mm)

    def move_gantry_to_end(self, end: str) -> dict[str, object]:
        """Send the carriage to one end of the rail.

        The far end is resolved here rather than passed in, through
        usable_travel_mm(), which reads Klipper's own axis_maximum. The rail
        length has one source and the browser is not it -- a page left open
        across a re-measure would otherwise send a stale target.

        Both ends are legal positions. Klipper only watches endstops while
        homing, so arriving at position_max presses the switch without
        complaint; it is the same place homing passes through.
        """
        if end not in ("left", "right"):
            raise ValueError(f"Unknown end: {end!r}. Use 'left' or 'right'.")

        with self._exclusive(f"Move gantry all the way {end}"):
            target = 0.0 if end == "left" else self.usable_travel_mm()
            return self.klipper.move_gantry_absolute(round(target, 1))

    def move_to_plant(self, plant_id: str) -> dict[str, object]:
        plant = next((item for item in self.plants if item.plant_id == plant_id), None)
        if plant is None:
            raise ValueError(f"Unknown plant_id: {plant_id}")

        with self._exclusive(f"Move to {plant_id}"):
            return self.klipper.move_gantry_absolute(plant.position_mm)

    # --- plant profiles ----------------------------------------------------
    #
    # A library of care settings keyed by plant name, so a plant can be set up
    # once and copied onto any pot. Saving overwrites the entry of that name
    # rather than accumulating near-duplicates.

    def list_plant_profiles(self) -> list[dict[str, object]]:
        """Every plant profile, sorted for a picker rather than by recency."""
        profiles = state.load_profiles(self._state_path)
        entries = [
            {"name": name, **values, **_water_level_of(values)}
            for name, values in profiles.items()
        ]
        entries.sort(key=lambda entry: str(entry["name"]).casefold())
        return entries

    def save_plant_profile(self, plant_id: str) -> dict[str, object]:
        """Store a plant's care settings under its own name.

        Reads from the plant rather than from a request body, so what gets
        saved is what the planter is actually running -- a profile that
        disagrees with the pot it was captured from would be worse than none.
        """
        plant = self.get_plant(plant_id)
        if plant is None:
            raise ValueError(f"Unknown plant_id: {plant_id}")

        fields = care_fields(plant)
        for derived in DERIVED_CARE_FIELDS:
            fields.pop(derived)
        # preferred_soil is the preference the pot was loaded with, not the
        # soil it happens to be in: a pot potted in something else for now
        # must not rewrite what the plant asks for.
        # A pot has no category; keep the one the profile already has, so
        # saving a pot back over a library plant does not ungroup it.
        existing = state.load_profiles(self._state_path)
        same = next((v for k, v in existing.items() if k.casefold() == plant.name.strip().casefold()), {})
        fields["category"] = same["category"] if isinstance(same.get("category"), str) else ""
        entry = state.save_profile(plant.name, fields, self._state_path)
        # The pot is now what that plant profile describes.
        plant.profile = plant.name.strip()
        self._persist()
        return {"status": "ok", "name": plant.name.strip(), "profile": entry}

    def write_plant_profile(
        self, name: str, settings: dict[str, object]
    ) -> dict[str, object]:
        """Create or replace a plant profile from a body, with no pot involved.

        The counterpart to save_plant_profile, which can only snapshot a pot.
        That left no way to fix a plant profile without a spare pot to load it
        onto, edit and save back -- and that round trip changes what the
        planter is running in order to edit something it is not.

        Validated the same way apply_plant_profile validates on the way in,
        because a profile is only worth having if loading it does something
        sensible.
        """
        clean = str(name).strip()
        entry: dict[str, object] = {}

        category = settings.get("category", "")
        if category is not None and not isinstance(category, str):
            raise ValueError("Category must be text")
        entry["category"] = (category or "").strip()

        # Refused rather than stored when it names no soil profile: loading
        # the profile could not switch the pot to it, and a typo would
        # otherwise sit there looking like a preference.
        preferred = str(settings.get("preferred_soil") or "").strip()
        if preferred:
            soils = state.load_soils(self._state_path)
            key = next((k for k in soils if k.casefold() == preferred.casefold()), None)
            if key is None:
                raise ValueError(f"No soil profile called {preferred!r}")
            preferred = key
        entry["preferred_soil"] = preferred

        # A water level in the body is ignored: it is worked out from this.
        entry["target_available"] = care.check_target_available(settings.get("target_available"))

        volume = settings.get("watering_volume_ml")
        if isinstance(volume, bool) or not isinstance(volume, (int, float)):
            raise ValueError("Watering volume must be a number of millilitres")
        # Clamped at zero and left unbounded above, matching
        # update_watering_volume. An upper limit enforced only here would mean
        # the editor refusing a dose the plant card accepts.
        entry["watering_volume_ml"] = max(0, int(volume))

        entry["light_start_time"] = care.check_start_time(
            settings.get("light_start_time")
        ).isoformat(timespec="minutes")
        entry["light_hours"] = care.check_light_hours(settings.get("light_hours"))
        entry["light_brightness"] = care.check_light_brightness(settings.get("light_brightness"))

        notes = settings.get("notes", "")
        if notes is not None and not isinstance(notes, str):
            raise ValueError("Notes must be text")
        entry["notes"] = (notes or "").strip()

        stored = state.save_profile(clean, entry, self._state_path)
        return {"status": "ok", "name": clean, "profile": stored}

    def get_plant_profile(self, name: str) -> dict[str, object]:
        """One plant profile, for an editor to load into its form."""
        wanted = str(name).strip()
        profiles = state.load_profiles(self._state_path)
        key = next((k for k in profiles if k.casefold() == wanted.casefold()), None)
        if key is None:
            raise ValueError(f"No plant profile called {wanted!r}")
        return {
            "status": "ok",
            "name": key,
            "profile": {**profiles[key], **_water_level_of(profiles[key])},
        }

    def apply_plant_profile(self, plant_id: str, name: str) -> dict[str, object]:
        """Copy a plant profile onto a pot.

        The name comes across too, so the pot and the profile it came from
        agree. Two pots can then carry the same name, which is allowed on
        purpose: plant_id is the identity and the name is a label, and copying
        one plant's settings onto a second pot is the whole point. Nothing is
        suffixed to make the names unique.

        The pot is switched to the profile's preferred soil profile, when it
        has one that exists. position_mm, the watering mode and the sweep
        bounds are untouched -- see state.PROFILE_FIELDS for why. They describe
        the pot, not the plant.
        """
        plant = self.get_plant(plant_id)
        if plant is None:
            raise ValueError(f"Unknown plant_id: {plant_id}")

        wanted = str(name).strip()
        profiles = state.load_profiles(self._state_path)
        key = next((k for k in profiles if k.casefold() == wanted.casefold()), None)
        if key is None:
            raise ValueError(f"No plant profile called {wanted!r}")

        entry = profiles[key]
        plant.name = key
        plant.profile = key

        volume = entry.get("watering_volume_ml")
        if not isinstance(volume, bool) and isinstance(volume, (int, float)):
            plant.watering_volume_ml = max(0, int(volume))

        # Each checked rather than taken as written, and a bad one is dropped
        # with a warning: a profile written by hand, or by an older build,
        # should load what it can rather than nothing.
        fresh = next(p for p in default_plants() if p.plant_id == plant_id)
        for field_name, check in (
            ("target_available", care.check_target_available),
            ("light_start_time", care.check_start_time),
            ("light_hours", care.check_light_hours),
            ("light_brightness", care.check_light_brightness),
        ):
            try:
                value = check(entry[field_name]) if field_name in entry else getattr(fresh, field_name)
            except ValueError:
                logger.warning(
                    "Ignoring unusable %s %r in profile %r", field_name, entry[field_name], key
                )
                value = getattr(fresh, field_name)
            setattr(plant, field_name, value)

        # Tested for being a string, not for being truthy: an emptied note is a
        # real value and must overwrite the old one. A profile with no notes key
        # at all leaves the pot's note alone.
        if isinstance(entry.get("notes"), str):
            plant.notes = entry["notes"].strip()

        # Pot the plant in the mix it wants. One that is not installed is
        # reported and the pot keeps the soil profile it has.
        preferred = entry.get("preferred_soil") if isinstance(entry.get("preferred_soil"), str) else ""
        plant.preferred_soil = preferred.strip()
        soil_note = ""
        if plant.preferred_soil:
            soils = state.load_soils(self._state_path)
            soil_key = next((k for k in soils if k.casefold() == plant.preferred_soil.casefold()), None)
            if soil_key is None:
                soil_note = (
                    f"{key} prefers {plant.preferred_soil}, which is not in the soil "
                    "profiles, so the pot's soil profile was left as it was."
                )
            else:
                plant.preferred_soil = soil_key
                plant.soil = soil_key

        self._persist()
        self._sync_scales()
        return {
            "status": "ok",
            "plant_id": plant_id,
            "name": plant.name,
            "profile": plant.profile,
            **care_fields(plant),
            "soil": plant.soil,
            "soil_note": soil_note,
            # Echoed so the caller can see it was left alone.
            "position_mm": plant.position_mm,
        }

    def clear_plant_profile(self, plant_id: str) -> dict[str, object]:
        """Take the plant profile off a pot: the undo of apply_plant_profile.

        Everything a profile brings -- the name and the care settings -- goes
        back to the pot's default, so the pot does not go on watering to a
        plant it no longer claims to be. Placement, watering mode and the soil
        profile stay: the mix is still physically in the pot.
        """
        plant = self.get_plant(plant_id)
        if plant is None:
            raise ValueError(f"Unknown plant_id: {plant_id}")

        fresh = next(p for p in default_plants() if p.plant_id == plant_id)
        plant.name = fresh.name
        plant.profile = ""
        for field_name in (
            "target_available",
            "preferred_soil",
            "watering_volume_ml",
            "light_start_time",
            "light_hours",
            "light_brightness",
            "notes",
        ):
            setattr(plant, field_name, getattr(fresh, field_name))
        self._persist()
        return {"status": "ok", "plant_id": plant_id, "name": plant.name}

    def delete_plant_profile(self, name: str) -> dict[str, object]:
        """Remove a plant profile. Pots already using it keep their settings."""
        wanted = str(name).strip()
        if not state.delete_profile(wanted, self._state_path):
            raise ValueError(f"No plant profile called {wanted!r}")
        return {"status": "ok", "deleted": wanted}

    def get_plant(self, plant_id: str) -> PlantSpec | None:
        return next((plant for plant in self.plants if plant.plant_id == plant_id), None)

    def update_plant_name(self, plant_id: str, name: str) -> dict[str, object]:
        plant = self.get_plant(plant_id)
        if plant is None:
            raise ValueError(f"Unknown plant_id: {plant_id}")
        plant.name = name.strip() or plant.name
        self._persist()
        return {"status": "ok", "plant_id": plant_id, "name": plant.name}

    def update_light_schedule(
        self, plant_id: str, start_time: object, hours: object, brightness: object
    ) -> dict[str, object]:
        """When this pot's lights come on, for how long, and how bright."""
        plant = self.get_plant(plant_id)
        if plant is None:
            raise ValueError(f"Unknown plant_id: {plant_id}")

        # All three checked before any is applied, so a bad one changes nothing.
        start = care.check_start_time(start_time)
        checked_hours = care.check_light_hours(hours)
        checked_brightness = care.check_light_brightness(brightness)
        plant.light_start_time = start
        plant.light_hours = checked_hours
        plant.light_brightness = checked_brightness
        self._persist()

        fields = care_fields(plant)
        return {
            "status": "ok",
            "plant_id": plant_id,
            **{k: fields[k] for k in ("light_start_time", "light_hours", "light_brightness", "light_stop_time")},
        }

    def update_plant_soil(self, plant_id: str, soil: str) -> dict[str, object]:
        """Record which mix this pot is filled with.

        An unknown name is refused rather than stored: a soil that is not in
        the library supplies no wilting-point ratio, so it would read as "set"
        while behaving exactly like "not set". Empty clears it, which is the
        honest way to say the mix is unknown.
        """
        plant = self.get_plant(plant_id)
        if plant is None:
            raise ValueError(f"Unknown plant_id: {plant_id}")

        wanted = str(soil).strip()
        if wanted:
            soils = state.load_soils(self._state_path)
            key = next((k for k in soils if k.casefold() == wanted.casefold()), None)
            if key is None:
                raise ValueError(
                    f"No soil profile called {wanted!r}. Install the library with "
                    f"python -m greenthumb.soil_library --install"
                )
            wanted = key

        plant.soil = wanted
        self._persist()
        # The pot's scale is its soil profile's, so a new soil is a new scale.
        self._sync_scales()
        return {
            "status": "ok",
            "plant_id": plant_id,
            "soil": plant.soil,
            "field_capacity_raw": self.sensor_hub.field_capacity.get(plant.sensor_address),
        }

    def list_soils(self) -> list[dict[str, object]]:
        """Every soil profile, widest published window first."""
        soils = state.load_soils(self._state_path)
        entries = []
        for name, values in soils.items():
            entry = {"name": name, **values}
            entry["wilting_fraction"] = state.available_water_fraction(values)
            # What a pot of this soil uses as its wilting point when the soil
            # profile has no reading of its own, on the probe the field
            # capacity was measured with. Each pot works out its own from its
            # own probe's air reading, so this is the soil profile's figure.
            top = values.get("field_capacity_raw")
            if isinstance(top, (int, float)) and not isinstance(top, bool):
                estimate = wilting_point_for(
                    {key: value for key, value in values.items() if key != "wilting_point_raw"},
                    int(top),
                    self.sensor_hub.dry_for(values.get("field_capacity_address")),
                )
                if estimate is not None:
                    entry["estimated_wilting_raw"] = estimate
            capacity = values.get("field_capacity_vwc")
            wilting = values.get("wilting_point_vwc")
            if isinstance(capacity, (int, float)) and isinstance(wilting, (int, float)):
                entry["available_points"] = round(capacity - wilting, 1)
            entries.append(entry)
        # Widest usable window first: that is the one most forgiving to
        # automate, and the ordering says something, unlike alphabetical.
        entries.sort(key=lambda e: e.get("available_points") or 0, reverse=True)
        return entries

    def save_soil(
        self,
        name: str,
        field_capacity_vwc: float,
        wilting_point_vwc: float,
        notes: str = "",
        field_capacity_raw: object = UNCHANGED,
        wilting_point_raw: object = UNCHANGED,
    ) -> dict[str, object]:
        """Add or replace a soil profile, keyed on its name like the plant library.

        What watering uses is the field capacity reading and, to estimate
        wilting point from, the two % VWC figures -- or a wilting point reading
        in place of the estimate. The readings are optional and typed here, the
        alternative to measuring them. UNCHANGED leaves a stored reading alone,
        so saving the rest does not wipe a measurement; None clears it; a
        number replaces it and drops the measured-on details, which no longer
        describe it. A new field capacity reaches the pots filled with this
        soil at once, the same as a measured one.

        The two % VWC figures are both or neither: one on its own places
        nothing. None for both clears them.
        """
        raw_changes = self._soil_raw_changes(name, field_capacity_raw, wilting_point_raw)
        # The name is validated by state.save_soil, which owns the keying for
        # every named library. Checking it again here would be a branch that
        # can never behave differently from the one beneath it.
        clean = str(name).strip()
        readings: dict[str, object] = {}
        if field_capacity_vwc is None and wilting_point_vwc is None:
            readings = {"field_capacity_vwc": None, "wilting_point_vwc": None}
        else:
            for label, value in (
                ("field_capacity_vwc", field_capacity_vwc),
                ("wilting_point_vwc", wilting_point_vwc),
            ):
                if value is None:
                    raise ValueError(
                        "Give both % VWC figures or neither: one on its own "
                        "suggests nothing"
                    )
                if isinstance(value, bool):
                    raise ValueError(f"{label} must be a number")
                try:
                    readings[label] = float(value)
                except (TypeError, ValueError):
                    raise ValueError(f"{label} must be a number, not {value!r}") from None

            capacity = readings["field_capacity_vwc"]
            wilting = readings["wilting_point_vwc"]

            # Volumetric water content is a share of the pot's volume, so above
            # 100 is not a measurement of anything.
            if not 0 < capacity <= 100:
                raise ValueError(
                    f"Field capacity must be between 0 and 100% VWC, not {capacity}"
                )
            if not 0 < wilting < capacity:
                raise ValueError(
                    f"Wilting point must be above 0 and below field capacity "
                    f"({capacity}% VWC), not {wilting}"
                )

        if notes is not None and not isinstance(notes, str):
            raise ValueError("Notes must be text")
        readings["notes"] = (notes or "").strip()

        entry = state.save_soil(clean, {**readings, **raw_changes}, self._state_path)

        inherited = self._pots_using(clean) if "field_capacity_raw" in raw_changes else []
        # Both ends are read live from the soil profile, so any change moves
        # the scale of every pot using it.
        self._sync_scales()
        return {
            "status": "ok",
            "name": clean,
            "soil": entry,
            "wilting_fraction": state.available_water_fraction(readings),
            "available_points": (
                round(readings["field_capacity_vwc"] - readings["wilting_point_vwc"], 1)
                if readings["field_capacity_vwc"] is not None
                else None
            ),
            "inherited_by": inherited,
        }

    def _soil_raw_changes(
        self, name: str, field_capacity_raw: object, wilting_point_raw: object
    ) -> dict[str, object]:
        """Validate typed sensor readings and turn them into state fields.

        Checked against each other using the stored value for whichever one is
        not being changed, so wilting point can never end up at or above field
        capacity -- the dry end of the window above the wet end.
        """
        stored = next(
            (
                values
                for key, values in state.load_soils(self._state_path).items()
                if key.casefold() == str(name).strip().casefold()
            ),
            {},
        )

        def parse(value: object, label: str) -> int | None:
            if value is None:
                return None
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
                raise ValueError(f"{label} must be a whole sensor reading, not {value!r}")
            if int(value) <= 0:
                raise ValueError(f"{label} must be above 0, not {value!r}")
            return int(value)

        changes: dict[str, object] = {}
        for value, prefix, label in (
            (field_capacity_raw, "field_capacity", "Field capacity (sensor reading)"),
            (wilting_point_raw, "wilting_point", "Wilting point (sensor reading)"),
        ):
            if value is UNCHANGED:
                continue
            changes[f"{prefix}_raw"] = parse(value, label)
            # Typed, not measured: the old measurement's details would now
            # describe a number that is not there.
            changes[f"{prefix}_samples"] = None
            changes[f"{prefix}_measured_at"] = None
            changes[f"{prefix}_address"] = None

        capacity = changes.get("field_capacity_raw", stored.get("field_capacity_raw"))
        wilting = changes.get("wilting_point_raw", stored.get("wilting_point_raw"))
        if (
            changes
            and isinstance(capacity, (int, float))
            and isinstance(wilting, (int, float))
            and wilting >= capacity
        ):
            raise ValueError(
                f"Wilting point (sensor reading) must be below field capacity "
                f"({int(capacity)}), not {int(wilting)}"
            )
        return changes

    def export_library(self) -> dict[str, object]:
        """Every soil profile and plant profile, as one file to keep.

        Exactly what is stored, measured readings and their provenance
        included, so a restore puts back the field capacity somebody spent a
        day measuring rather than only the published figures.
        """
        return {
            "format": LIBRARY_FORMAT,
            "version": LIBRARY_VERSION,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "soil_profiles": state.load_soils(self._state_path),
            "plant_profiles": state.load_profiles(self._state_path),
        }

    def import_library(self, data: object, replace: bool = False) -> dict[str, object]:
        """Load a file from export_library back in.

        Every entry goes through the same validation as the editors, so a
        hand-edited backup cannot store something the UI would refuse. One bad
        entry is reported and skipped rather than failing the rest. Soil
        profiles go first, because a plant profile's preferred soil has to
        exist before it can be stored.

        Without `replace`, an entry whose name is already here is kept as it
        is: importing an old backup must not quietly undo newer tuning.
        """
        # A planter's own data/state.json is accepted too: it stores both
        # libraries under the same two keys, and it is what can be pulled off
        # the card of a Pi that will not boot. Only those two keys are read.
        is_backup = isinstance(data, dict) and data.get("format") == LIBRARY_FORMAT
        is_state = (
            isinstance(data, dict)
            and "format" not in data
            and (state.PROFILES_KEY in data or state.SOILS_KEY in data)
        )
        if not (is_backup or is_state):
            raise ValueError("Not a GreenThumb library backup or state.json")
        soils_in = data.get("soil_profiles") or {}
        plants_in = data.get("plant_profiles") or {}
        if not isinstance(soils_in, dict) or not isinstance(plants_in, dict):
            raise ValueError("The backup's soil_profiles and plant_profiles must each map names to entries")

        def exists(name: str, stored: dict[str, object]) -> bool:
            return any(key.casefold() == name.strip().casefold() for key in stored)

        soils_out: dict[str, str] = {}
        existing_soils = state.load_soils(self._state_path)
        for name, entry in soils_in.items():
            if not isinstance(name, str) or not name.strip() or not isinstance(entry, dict):
                soils_out[str(name)] = "skipped: not a soil profile"
                continue
            if exists(name, existing_soils) and not replace:
                soils_out[name] = "kept"
                continue
            try:
                # None for anything missing, so a replace leaves the soil
                # exactly as the backup has it rather than merged with what
                # was here.
                self.save_soil(
                    name,
                    entry.get("field_capacity_vwc"),
                    entry.get("wilting_point_vwc"),
                    entry.get("notes", ""),
                    entry.get("field_capacity_raw"),
                    entry.get("wilting_point_raw"),
                )
            except ValueError as exc:
                soils_out[name] = f"skipped: {exc}"
                continue
            # save_soil treats a reading as typed and clears where it came
            # from; put the backup's provenance back beside it.
            provenance = {
                f"{end}_{detail}": entry[f"{end}_{detail}"]
                for end in ("field_capacity", "wilting_point")
                if entry.get(f"{end}_raw") is not None
                for detail in ("samples", "measured_at", "address")
                if entry.get(f"{end}_{detail}") is not None
            }
            if provenance:
                state.save_soil(name, provenance, self._state_path)
            soils_out[name] = "written"

        plants_out: dict[str, str] = {}
        existing_plants = state.load_profiles(self._state_path)
        for name, entry in plants_in.items():
            if not isinstance(name, str) or not name.strip() or not isinstance(entry, dict):
                plants_out[str(name)] = "skipped: not a plant profile"
                continue
            if exists(name, existing_plants) and not replace:
                plants_out[name] = "kept"
                continue
            try:
                self.write_plant_profile(name, entry)
            except ValueError as exc:
                plants_out[name] = f"skipped: {exc}"
                continue
            plants_out[name] = "written"

        return {"status": "ok", "soil_profiles": soils_out, "plant_profiles": plants_out}

    def delete_soil(self, name: str) -> dict[str, object]:
        """Remove a soil. Plants still naming it keep the name, unresolved."""
        wanted = str(name).strip()
        if not state.delete_soil(wanted, self._state_path):
            raise ValueError(f"No soil profile called {wanted!r}")
        # Pots still naming it lose their wilting point, and so their reading.
        self._sync_scales()
        return {"status": "ok", "deleted": wanted}

    def update_watering_volume(self, plant_id: str, volume_ml: int) -> dict[str, object]:
        plant = self.get_plant(plant_id)
        if plant is None:
            raise ValueError(f"Unknown plant_id: {plant_id}")

        plant.watering_volume_ml = max(0, int(volume_ml))
        self._persist()
        return {
            "status": "ok",
            "plant_id": plant_id,
            "watering_volume_ml": plant.watering_volume_ml,
        }

    def update_target_available(self, plant_id: str, target_available: object) -> dict[str, object]:
        """Set the share of available water at which this plant is watered.

        Refused rather than coerced if it is not a whole percentage: a target
        that does not resolve would leave the plant never thirsty, which looks
        like a working planter that has quietly stopped watering.
        """
        plant = self.get_plant(plant_id)
        if plant is None:
            raise ValueError(f"Unknown plant_id: {plant_id}")

        plant.target_available = care.check_target_available(target_available)
        self._persist()

        return {
            "status": "ok",
            "plant_id": plant_id,
            "target_available": plant.target_available,
            "water_level": care.water_level_for(plant.target_available),
        }
