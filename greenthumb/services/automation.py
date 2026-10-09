from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from pathlib import Path

from greenthumb.config import settings
from greenthumb.hardware.klipper_client import KlipperClient, MOTION_TIMEOUT
from greenthumb.hardware.lighting import LedController
from greenthumb.hardware.pump import PumpController
from greenthumb.hardware.soil_sensors import SoilSensorHub, calibrate, unavailable_sample
from greenthumb.history import DEFAULT_DB_PATH, HistoryStore
from greenthumb.models import SensorSample, PlantSpec, PlantStatus
from greenthumb.plants import default_plants, label_for
from greenthumb import dances, state

logger = logging.getLogger(__name__)

# How often to re-read the outlet sensor while a dose is running.
DELIVERY_POLL_SECONDS = 1.0
# Slack for the watcher thread to notice the dose ended and return its verdict.
DELIVERY_JOIN_SECONDS = 5.0
# How close to position_max counts as parked on the home switch. Wider than
# homing_retract_dist so a carriage resting just off the switch after a failed
# home is still read as being at it.
NEAR_SWITCH_MM = 15.0


class HardwareBusyError(RuntimeError):
    """Raised when the gantry, pump, or I2C bus is already in use."""


def within_window(now: time, start: time, stop: time) -> bool:
    if start <= stop:
        return start <= now < stop
    # A window that stops before it starts runs overnight, e.g. 20:00 to 06:00.
    return now >= start or now < stop


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
            raw_wet=settings.moisture_raw_wet,
            calibration=state.load_calibration(self._state_path),
        )
        self.klipper = klipper_client or KlipperClient(socket_path=settings.klipper_host)
        self.pump = pump or PumpController(
            self.klipper,
            pin_name=settings.pump_pin_name,
            flow_ml_per_second=settings.pump_flow_ml_per_second,
        )
        self.leds = leds or LedController(
            led_count=settings.led_count,
            chip=settings.led_chip,
            color_order=settings.led_color_order,
            spi_bus=settings.led_spi_bus,
            spi_device=settings.led_spi_device,
        )

        # The gantry, the pump, and the I2C bus all tolerate exactly one user at
        # a time, and a watering cycle holds them for minutes. A single lock for
        # all three is what keeps the control loop and manual commands apart.
        self._hardware_lock = threading.Lock()
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
        self._last_delivery: dict[str, object] | None = None
        # Consecutive doses that reached nothing. One can be a clog on a single
        # line; a run of them across plants is the shared thing, which is the
        # tank. Seeded from history at startup so a reboot does not forget that
        # the reservoir is empty.
        self._delivery_failures = 0
        self._pump_timer: threading.Timer | None = None
        self._pump_lock_held = False

        # The master switch for unattended watering. Seeded from the
        # environment, then owned by the UI and persisted like every other
        # user choice: editing .env and restarting the service is not
        # something the person who owns a planter should have to do.
        self.auto_watering_enabled = settings.auto_watering_enabled

        # Idle motion: a periodic re-home plus a short routine. The re-home
        # is the useful half -- steppers are open-loop, so a slipped belt or a
        # nudged carriage leaves every plant position wrong until the next
        # home, and doing it hourly caps how long that can go unnoticed.
        self.idle_motion_enabled = settings.idle_motion_enabled
        self.idle_motion_minutes = settings.idle_motion_minutes
        self.idle_motion_next = 0
        self._last_idle_motion: datetime | None = None

        self.quiet_hours_enabled = settings.quiet_hours_enabled
        self.quiet_hours_start = time.fromisoformat(settings.quiet_hours_start)
        self.quiet_hours_stop = time.fromisoformat(settings.quiet_hours_stop)
        # Absolute instant, not a duration, so it survives a restart with the
        # right amount of time left rather than starting over -- and a Pi that
        # was off for a week comes back with it already expired.
        self.snooze_until: datetime | None = None

        self.plants = default_plants()
        self.apply_default_led_ranges()
        self._warn_on_orphaned_plants()
        self._seed_delivery_failures()
        # Plant edits, dose volumes, rail positions and LED preferences are all
        # user choices that used to live only in memory, so every restart reset
        # them to the literals above. Restore whatever was saved last.
        self._restore_state()

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
            for text_field in ("name", "soil"):
                value = saved.get(text_field)
                if isinstance(value, str) and value.strip():
                    setattr(plant, text_field, value.strip())
            for field_name in ("moisture_target", "watering_volume_ml", "position_mm"):
                value = saved.get(field_name)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                setattr(plant, field_name, type(getattr(plant, field_name))(value))
            for field_name in ("light_start_time", "light_stop_time"):
                text = saved.get(field_name)
                if not isinstance(text, str):
                    continue
                try:
                    setattr(plant, field_name, time.fromisoformat(text))
                except ValueError:
                    logger.warning("Ignoring bad %s %r", field_name, text)

        idle = stored.get("idle_motion")
        if isinstance(idle, dict):
            if isinstance(idle.get("enabled"), bool):
                self.idle_motion_enabled = idle["enabled"]
            minutes = idle.get("minutes")
            if isinstance(minutes, int) and not isinstance(minutes, bool) and minutes > 0:
                self.idle_motion_minutes = minutes
            nxt = idle.get("next")
            if isinstance(nxt, int) and not isinstance(nxt, bool):
                # Keeps the rotation going across a restart instead of always
                # opening with the same routine.
                self.idle_motion_next = nxt % len(dances.DEFAULT_ORDER)

        watering = stored.get("watering")
        if isinstance(watering, dict) and isinstance(watering.get("auto_enabled"), bool):
            self.auto_watering_enabled = watering["auto_enabled"]

        quiet = stored.get("quiet")
        if isinstance(quiet, dict):
            self._restore_quiet_state(quiet)

        leds = stored.get("leds")
        if isinstance(leds, dict):
            self._restore_led_state(leds)

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
                    "moisture_target": plant.moisture_target,
                    "watering_volume_ml": plant.watering_volume_ml,
                    "position_mm": plant.position_mm,
                    "soil": plant.soil,
                    "light_start_time": plant.light_start_time.isoformat(timespec="minutes"),
                    "light_stop_time": plant.light_stop_time.isoformat(timespec="minutes"),
                }
                for plant in self.plants
            ],
            # getattr throughout: a controller that does not expose one of
            # these simply has it left out of the snapshot, rather than a
            # settings save failing because of an LED attribute.
            "watering": {"auto_enabled": self.auto_watering_enabled},
            "idle_motion": {
                "enabled": self.idle_motion_enabled,
                "minutes": self.idle_motion_minutes,
                "next": self.idle_motion_next,
            },
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
                    ("chip", getattr(getattr(self.leds, "strip", None), "chip", None)),
                    (
                        "color_order",
                        getattr(getattr(self.leds, "strip", None), "color_order", None),
                    ),
                )
                if value is not None
            },
        }

    def _persist(self) -> None:
        """Write the current settings. Never raises: a failed save must not
        turn a successful setting change into an API error."""
        try:
            state.update_state(self._snapshot(), self._state_path)
        except Exception:
            logger.exception("Could not persist settings")

    def apply_default_led_ranges(self) -> None:
        plant_count = len(self.plants)
        if plant_count == 0:
            return

        total_leds = max(settings.led_count, 1)
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

    def usable_travel_mm(self) -> float:
        """Reachable X range, where 0 is the first position the carriage can occupy.

        Asks Klipper, because Klipper is the one enforcing it: position_max in
        printer.cfg is the real limit, and it changes whenever the rail is
        measured properly. Deriving a second answer from the rail length and a
        margin meant the two disagreed the moment that happened -- which is how
        a plant ended up configured at a position the carriage could not reach.

        Falls back to the configured estimate when Klipper is not answering, so
        a plant position can still be saved with the board unplugged.
        """
        reported = self.klipper.status().get("max_x")
        if reported:
            return max(float(reported), 1.0)
        rail_length = max(float(settings.gantry_rail_length_mm), 1.0)
        margin = max(float(settings.gantry_position_margin_mm), 0.0)
        return max(rail_length - (margin * 2), 1.0)

    def set_plant_position(self, plant_id: str, position_mm: float) -> dict[str, object]:
        plant = next((item for item in self.plants if item.plant_id == plant_id), None)
        if plant is None:
            raise ValueError(f"Unknown plant_id: {plant_id}")

        bounded_position = max(0.0, min(float(position_mm), self.usable_travel_mm()))
        plant.position_mm = round(bounded_position, 1)
        self._persist()

        return {
            "status": "ok",
            "plant_id": plant_id,
            "position_mm": plant.position_mm,
        }

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

        # Outside the block above so it takes the lock on its own terms: a
        # dance is the lowest-priority thing this machine does and should
        # never be the reason a watering cycle was skipped.
        self._maybe_idle_motion()

    def _apply_lighting(self) -> None:
        now = datetime.now().time()
        self.leds.set_plant_segments(
            [
                (
                    plant.led_start_index,
                    plant.led_end_index,
                    within_window(now, plant.light_start_time, plant.light_stop_time),
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

    def smoothed_percent(self, address: int) -> float:
        """Mean moisture over the window; this, not a single read, drives watering."""
        window = self._history.get(address)
        if not window:
            return -1.0
        # Pass the address: without it raw_to_percent falls back to the global
        # endpoints, so per-sensor calibration applied to individual reads was
        # being dropped from the averaged value -- the one that actually decides
        # watering and feeds the overview.
        return self.sensor_hub.raw_to_percent(sum(window) / len(window), address)

    def _seed_delivery_failures(self) -> None:
        """Count the run of failed deliveries at the end of the history."""
        try:
            recent = self.history.waterings(hours=24 * 7)
        except Exception:
            logger.exception("Could not read watering history for delivery state")
            return
        for watering in reversed(recent):
            if watering.get("delivered") is False:
                self._delivery_failures += 1
            else:
                # Stops at the first dose that worked or could not be checked:
                # only an unbroken run means the tank is still empty now.
                break

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

        # 2. Doses are running and nothing is coming out.
        if self._delivery_failures >= 2:
            return state(
                "problem",
                f"{self._delivery_failures} waterings in a row reached nothing. "
                "The reservoir is probably empty.",
            )
        if self._delivery_failures == 1:
            return state(
                "attention",
                "The last watering did not reach the plant. Check the water level, "
                "then the line for a kink or a clog.",
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
        thirsty = [
            plant.name
            for plant in self.plants
            if 0 <= self.smoothed_percent(plant.sensor_address) < plant.moisture_target
        ]
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

    def watering_status(self) -> dict[str, object]:
        return {
            "status": "ok",
            "auto_watering_enabled": self.auto_watering_enabled,
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

            moisture = self.smoothed_percent(plant.sensor_address)
            if moisture >= plant.moisture_target:
                continue
            if not self._cooldown_elapsed(plant.plant_id):
                continue

            logger.info(
                "Plant %s at %.1f%% is below target %.1f%%, watering",
                plant.plant_id,
                moisture,
                plant.moisture_target,
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
        """Start the pump and leave it running, for bench testing.

        Not gated on the water sensor: running a dry line on purpose is part of
        what this is for.
        """
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

    def _watch_delivery(
        self,
        duration_seconds: float,
        verdict: dict[str, bool | None],
        finished: threading.Event,
    ) -> None:
        """Watch the outlet sensor during a dose and record whether water arrived.

        Runs on its own thread because deliver_ml does not return until Klipper
        finishes the dwell. That is safe: the sensor is read over objects/query,
        which Klipper answers even while the gcode queue is busy.
        """
        # The falling leg has to fill before there is anything to see.
        finished.wait(timeout=min(settings.delivery_check_delay_seconds, duration_seconds))

        saw_dry = False
        while True:
            present = self.klipper.water_supply_present()
            if present is True:
                verdict["delivered"] = True
                return
            if present is False:
                # A definite dry read proves the sensor answers, which is what
                # separates "no water arrived" from "we could not tell".
                saw_dry = True
            # Ends with the dose rather than on a timer, so a dose cut short by
            # a Klipper error does not hold the watering call open. Always one
            # read first: the loop is entered before this is checked.
            if finished.wait(timeout=DELIVERY_POLL_SECONDS):
                break

        verdict["delivered"] = False if saw_dry else None

    def _move_and_water(
        self, plant: PlantSpec, volume_ml: int | None = None, trigger: str = "auto"
    ) -> dict[str, object]:
        volume = plant.watering_volume_ml if volume_ml is None else max(0, int(volume_ml))

        move = self.klipper.move_gantry_absolute(plant.position_mm)
        if not move.get("ok"):
            logger.warning(
                "Not watering %s: gantry move failed (%s)", plant.plant_id, move.get("error")
            )
            return {"status": "error", "plant_id": plant.plant_id, "error": move.get("error")}

        verdict: dict[str, bool | None] = {"delivered": None}
        watcher: threading.Thread | None = None
        finished = threading.Event()
        if settings.water_sensor_enabled and volume > 0:
            # settings, not a literal fallback. A stale 1.67 here would time the
            # delivery window against the uncalibrated rate while the operator
            # believed their measured one was in use -- the silent wrong-flow-rate
            # failure HOW_WATERING_WORKS.md calls out as the unguarded one.
            flow = getattr(self.pump, "flow_ml_per_second", settings.pump_flow_ml_per_second)
            duration = volume / max(flow, 0.01)
            watcher = threading.Thread(
                target=self._watch_delivery,
                args=(duration, verdict, finished),
                daemon=True,
            )
            watcher.start()

        try:
            self.pump.deliver_ml(volume)
        finally:
            finished.set()

        if watcher is not None:
            watcher.join(timeout=DELIVERY_JOIN_SECONDS)
        delivered = verdict["delivered"]

        if delivered is False:
            # The failure this whole sensor exists to catch: the pump ran, the
            # dose was logged, and nothing came out the other end.
            logger.warning(
                "Watered %s with %d mL but no water reached the outlet sensor",
                plant.plant_id,
                volume,
            )
        elif settings.water_sensor_enabled and delivered is None:
            logger.warning("Could not verify delivery for %s, sensor unreadable", plant.plant_id)

        if delivered is False:
            self._delivery_failures += 1
        elif delivered is True:
            self._delivery_failures = 0
        # delivered is None means the sensor did not answer, which is neither
        # evidence of water nor of its absence, so the count is left alone.

        self._last_watered[plant.plant_id] = datetime.now()
        self._last_delivery = {
            "plant_id": plant.plant_id,
            "at": self._last_watered[plant.plant_id].isoformat(timespec="seconds"),
            "delivered": delivered,
        }
        try:
            self.history.record_watering(plant.plant_id, volume, trigger, delivered=delivered)
        except Exception:
            logger.exception("Failed to record watering for %s", plant.plant_id)
        return {
            "status": "ok",
            "plant_id": plant.plant_id,
            "volume_ml": volume,
            "delivered": delivered,
        }

    def _last_watered_iso(self, plant_id: str) -> str | None:
        last = self._last_watered.get(plant_id)
        return last.isoformat(timespec="seconds") if last else None

    def get_overview(self) -> dict[str, object]:
        plant_status = [
            PlantStatus(
                plant_id=spec.plant_id,
                moisture_percent=self.smoothed_percent(spec.sensor_address),
                target_moisture=spec.moisture_target,
                pump_active=self.pump.is_running,
                lighting_mode=self.leds.mode,
                last_watered=self._last_watered_iso(spec.plant_id),
                sample_count=len(self._history.get(spec.sensor_address) or ()),
                window_size=settings.moisture_window_size,
            )
            for spec in self.plants
        ]

        return {
            "app": settings.app_name,
            "movement": self.klipper.status(),
            "lighting": self.leds.status(),
            # Reports the last dose, not the line's current state: the outlet
            # reads dry between doses by design, so "dry right now" is normal
            # and would be alarming to show.
            "delivery": {
                "enabled": settings.water_sensor_enabled,
                "last": self._last_delivery,
            },
            "plants": [status.__dict__ for status in plant_status],
            # So the UI can say why nothing is watering rather than leaving it
            # looking broken.
            "watering": self.watering_status(),
            "idle_motion": self.idle_motion_status(),
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
                    "moisture_target": plant.moisture_target,
                    **series[plant.sensor_address],
                }
                for plant in self.plants
            ],
            "waterings": self.history.waterings(hours),
        }

    def read_sensors(self) -> list[dict[str, object]]:
        """Last polled reading per sensor; the control loop owns the I2C bus."""
        return [
            {
                **self._latest[address].__dict__,
                "moisture_percent_avg": self.smoothed_percent(address),
                "sample_count": len(self._history[address]),
            }
            for address in self.sensor_hub.addresses
        ]

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
        if endpoint not in ("dry", "wet"):
            raise ValueError(f"endpoint must be 'dry' or 'wet', not {endpoint!r}")
        bounded = max(5, min(int(seconds), 120))

        with self._exclusive(f"Calibrating {endpoint} point"):
            results = calibrate(self.sensor_hub, endpoint, bounded, state_path=self._state_path)

        stored = sum(1 for item in results.values() if item.get("written"))
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
        stored = state.load_calibration(self._state_path)
        names = self.plant_names()
        return {
            "status": "ok",
            "default_dry": settings.moisture_raw_dry,
            "default_wet": settings.moisture_raw_wet,
            "sensors": [
                {
                    "address": f"0x{address:02x}",
                    "plant": names.get(address),
                    "label": label_for(address, names),
                    "dry": self.sensor_hub.endpoints_for(address)[0],
                    "wet": self.sensor_hub.endpoints_for(address)[1],
                    "calibrated_dry": "dry" in stored.get(address, {}),
                    "calibrated_wet": "wet" in stored.get(address, {}),
                }
                for address in self.sensor_hub.addresses
            ],
        }

    def reset_moisture_calibration(self) -> dict[str, object]:
        state.clear_calibration(self._state_path)
        self.sensor_hub.calibration = {}
        return {"status": "ok", "message": "Calibration cleared, using .env defaults"}

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
        self._persist()
        return result

    def set_light_brightness(self, brightness: int) -> dict[str, object]:
        result = self.leds.set_brightness(brightness)
        self._persist()
        return {
            "status": "ok",
            "brightness": result["brightness"],
        }

    # --- idle motion ------------------------------------------------------

    def run_dance(self, name: str, home_first: bool = False) -> dict[str, object]:
        """Run one routine now. Not gated by quiet hours -- see _maybe_idle_motion."""
        steps = dances.steps_for(
            name, self.usable_travel_mm(), [plant.position_mm for plant in self.plants]
        )
        seconds = dances.estimated_seconds(steps)

        with self._exclusive(f"Dance {name}"):
            status = self.klipper.status()
            if not status.get("ok"):
                return {"ok": False, "error": status.get("error") or "Klipper is not responding"}

            # An unhomed axis refuses every move, so there is no point
            # starting. Homing anyway is also the honest thing for a routine
            # whose job is partly to re-establish where the carriage is.
            if home_first or not status.get("homed"):
                homed = self.klipper.home_gantry()
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

        # A routine you asked for also resets the clock, so pressing the
        # button does not get followed by an automatic one a minute later.
        self._last_idle_motion = datetime.now()
        return {"ok": True, "dance": name, "seconds": seconds}

    def _maybe_idle_motion(self) -> None:
        """Called every tick. Runs at most one routine per interval."""
        if not self.idle_motion_enabled:
            return

        now = datetime.now()
        if self._last_idle_motion is None:
            # Start the clock rather than dancing the instant the service
            # comes up, which would make every restart twitch.
            self._last_idle_motion = now
            return
        if now < self._last_idle_motion + timedelta(minutes=self.idle_motion_minutes):
            return

        held = self.watering_suppressed(now)
        if held:
            # Deliberately does not reset the clock: once the window closes the
            # next tick runs the routine rather than waiting another hour.
            logger.debug("Skipping idle motion, %s", held)
            return

        name = dances.DEFAULT_ORDER[self.idle_motion_next % len(dances.DEFAULT_ORDER)]
        self._last_idle_motion = now
        try:
            result = self.run_dance(name, home_first=True)
        except HardwareBusyError:
            logger.debug("Skipping idle motion, hardware is busy")
            return
        except Exception:
            logger.exception("Idle motion failed")
            return

        if result.get("ok"):
            self.idle_motion_next = (self.idle_motion_next + 1) % len(dances.DEFAULT_ORDER)
            logger.info("Homed and ran the %s routine", name)
        else:
            logger.warning("Idle motion did not run: %s", result.get("error"))
        self._persist()

    def set_idle_motion(self, enabled: bool, minutes: int | None = None) -> dict[str, object]:
        if minutes is not None:
            if not 5 <= int(minutes) <= 1440:
                raise ValueError("Interval must be between 5 minutes and 24 hours")
            self.idle_motion_minutes = int(minutes)
        self.idle_motion_enabled = bool(enabled)
        self._persist()
        return self.idle_motion_status()

    def idle_motion_status(self) -> dict[str, object]:
        """Cheap enough for /overview -- asks Klipper nothing."""
        return {
            "status": "ok",
            "enabled": self.idle_motion_enabled,
            "minutes": self.idle_motion_minutes,
            "next_dance": dances.DEFAULT_ORDER[
                self.idle_motion_next % len(dances.DEFAULT_ORDER)
            ],
            "last_at": (
                self._last_idle_motion.isoformat(timespec="minutes")
                if self._last_idle_motion
                else None
            ),
        }

    def dance_catalogue(self) -> list[dict]:
        """The routines, with durations. Asks Klipper for the rail length."""
        return dances.catalogue(
            self.usable_travel_mm(), [plant.position_mm for plant in self.plants]
        )

    def home_gantry(self) -> dict[str, object]:
        with self._exclusive("Homing gantry"):
            return self.klipper.home_gantry()

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

    # --- saved plants ----------------------------------------------------
    #
    # A library of care settings keyed by plant name, so a plant can be set up
    # once and copied onto any pot. Saving overwrites the entry of that name
    # rather than accumulating near-duplicates.

    def list_plant_profiles(self) -> list[dict[str, object]]:
        """Every saved plant, sorted for a picker rather than by recency."""
        profiles = state.load_profiles(self._state_path)
        entries = [{"name": name, **values} for name, values in profiles.items()]
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

        entry = state.save_profile(
            plant.name,
            {
                "moisture_target": plant.moisture_target,
                "watering_volume_ml": plant.watering_volume_ml,
                "light_start_time": plant.light_start_time.isoformat(timespec="minutes"),
                "light_stop_time": plant.light_stop_time.isoformat(timespec="minutes"),
                "soil": plant.soil,
            },
            self._state_path,
        )
        return {"status": "ok", "name": plant.name.strip(), "profile": entry}

    def apply_plant_profile(self, plant_id: str, name: str) -> dict[str, object]:
        """Copy a saved plant onto a pot.

        The name comes across too, so the pot and the profile it came from
        agree. Two pots can then carry the same name, which is allowed on
        purpose: plant_id is the identity and the name is a label, and copying
        one plant's settings onto a second pot is the whole point. Nothing is
        suffixed to make the names unique.

        position_mm is untouched -- see state.PROFILE_FIELDS for why.
        """
        plant = self.get_plant(plant_id)
        if plant is None:
            raise ValueError(f"Unknown plant_id: {plant_id}")

        wanted = str(name).strip()
        profiles = state.load_profiles(self._state_path)
        key = next((k for k in profiles if k.casefold() == wanted.casefold()), None)
        if key is None:
            raise ValueError(f"No saved plant called {wanted!r}")

        entry = profiles[key]
        plant.name = key

        for field_name in ("moisture_target", "watering_volume_ml"):
            value = entry.get(field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            setattr(plant, field_name, max(0, int(value)))

        for field_name in ("light_start_time", "light_stop_time"):
            text = entry.get(field_name)
            if not isinstance(text, str):
                continue
            try:
                setattr(plant, field_name, time.fromisoformat(text))
            except ValueError:
                logger.warning("Ignoring bad %s %r in profile %r", field_name, text, key)

        if isinstance(entry.get("soil"), str):
            plant.soil = entry["soil"].strip()

        self._persist()
        return {
            "status": "ok",
            "plant_id": plant_id,
            "name": plant.name,
            "moisture_target": plant.moisture_target,
            "watering_volume_ml": plant.watering_volume_ml,
            "light_start_time": plant.light_start_time.isoformat(timespec="minutes"),
            "light_stop_time": plant.light_stop_time.isoformat(timespec="minutes"),
            # Echoed so the caller can see it was left alone rather than
            # wonder whether the profile moved the pot.
            "position_mm": plant.position_mm,
        }

    def delete_plant_profile(self, name: str) -> dict[str, object]:
        """Remove a saved plant. Pots already using it keep their settings."""
        wanted = str(name).strip()
        if not state.delete_profile(wanted, self._state_path):
            raise ValueError(f"No saved plant called {wanted!r}")
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

    def update_light_schedule(self, plant_id: str, start_time: time, stop_time: time) -> dict[str, object]:
        plant = self.get_plant(plant_id)
        if plant is None:
            raise ValueError(f"Unknown plant_id: {plant_id}")

        if not isinstance(start_time, time) or not isinstance(stop_time, time):
            raise ValueError("Light times must be valid Python time objects")

        plant.light_start_time = start_time
        plant.light_stop_time = stop_time
        self._persist()

        return {
            "status": "ok",
            "plant_id": plant_id,
            "light_start_time": plant.light_start_time.isoformat(timespec="minutes"),
            "light_stop_time": plant.light_stop_time.isoformat(timespec="minutes"),
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
                    f"No soil called {wanted!r}. Install the library with "
                    f"python -m greenthumb.soil_library --install"
                )
            wanted = key

        plant.soil = wanted
        self._persist()
        return {"status": "ok", "plant_id": plant_id, "soil": plant.soil}

    def list_soils(self) -> list[dict[str, object]]:
        """Every saved soil, with the ratio the bands need, widest window first."""
        soils = state.load_soils(self._state_path)
        entries = []
        for name, values in soils.items():
            entry = {"name": name, **values}
            entry["wilting_fraction"] = state.available_water_fraction(values)
            capacity = values.get("field_capacity_vwc")
            wilting = values.get("wilting_point_vwc")
            if isinstance(capacity, (int, float)) and isinstance(wilting, (int, float)):
                entry["available_points"] = round(capacity - wilting, 1)
            entries.append(entry)
        # Widest usable window first: that is the one most forgiving to
        # automate, and the ordering says something, unlike alphabetical.
        entries.sort(key=lambda e: e.get("available_points") or 0, reverse=True)
        return entries

    def delete_soil(self, name: str) -> dict[str, object]:
        """Remove a soil. Plants still naming it keep the name, unresolved."""
        wanted = str(name).strip()
        if not state.delete_soil(wanted, self._state_path):
            raise ValueError(f"No soil called {wanted!r}")
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

    def update_moisture_target(self, plant_id: str, moisture_target: float) -> dict[str, object]:
        plant = self.get_plant(plant_id)
        if plant is None:
            raise ValueError(f"Unknown plant_id: {plant_id}")

        clamped_target = max(0.0, min(float(moisture_target), 100.0))
        plant.moisture_target = round(clamped_target, 1)
        self._persist()

        return {
            "status": "ok",
            "plant_id": plant_id,
            "moisture_target": plant.moisture_target,
        }
