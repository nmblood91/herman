from __future__ import annotations

import logging
import statistics
import struct
import time
from datetime import datetime

import smbus2

from greenthumb import state
from greenthumb.models import SensorSample
from greenthumb.plants import label_for

logger = logging.getLogger(__name__)

I2C_BUS = 1

SEESAW_STATUS_BASE = 0x00
SEESAW_TOUCH_BASE = 0x0F

SEESAW_STATUS_HW_ID = 0x01
SEESAW_STATUS_TEMP = 0x04
SEESAW_STATUS_SWRST = 0x7F

SEESAW_TOUCH_CHANNEL_OFFSET = 0x10

# The soil sensor ships on a SAMD09; later seesaw boards report the tiny8x7 id.
VALID_HW_IDS = (0x55, 0x87)

MOISTURE_TOUCH_PIN = 0
NOT_READY = 0xFFFF


class SensorReadError(RuntimeError):
    """Raised when the sensing stack is unavailable."""


def unavailable_sample(address: int) -> SensorSample:
    """Reading for a sensor that is absent or failed; -1 never looks like real data."""
    return SensorSample(
        sensor_address=address,
        moisture_percent=-1.0,
        moisture_raw=-1.0,
        temperature_c=-1.0,
    )


class SoilSensorHub:
    """Reads Adafruit STEMMA soil sensors over I2C using the seesaw protocol."""

    def __init__(
        self,
        addresses: list[int] | None = None,
        raw_dry: int = 320,
        calibration: dict[int, dict[str, int]] | None = None,
        field_capacity: dict[int, int] | None = None,
    ) -> None:
        self.addresses = addresses or [0x36, 0x37, 0x38, 0x39]
        self.raw_dry = raw_dry
        # Per-address dry points measured by --calibrate, overriding raw_dry for
        # the sensors that have them. Sensors read meaningfully differently from
        # each other in identical conditions, so one global figure puts that
        # spread straight into the reported percentage.
        self.calibration = calibration or {}
        # The other end of the scale, per address, and it is kept separately
        # because it is a different kind of fact. A dry reading is a property of
        # the probe -- prongs in open air. Field capacity is a property of the
        # *mix*, measured in a pot, and the same mix in another pot gives
        # roughly the same figure. So it hangs off the plant rather than the
        # probe, and the automation layer syncs this map from the plants.
        #
        # There is deliberately no fallback. A pot with nothing here reads -1,
        # not a percentage against a number nobody measured.
        self.field_capacity = field_capacity or {}
        self.bus: smbus2.SMBus | None = None
        self._initialized_sensors: set[int] = set()

        try:
            self.bus = smbus2.SMBus(I2C_BUS)
        except Exception as exc:
            logger.error("Failed to open I2C bus %d: %s", I2C_BUS, exc)
            return

        for address in self.addresses:
            self._try_initialize(address)

    def _try_initialize(self, address: int) -> bool:
        try:
            self._reset(address)
            hw_id = self._read(address, SEESAW_STATUS_BASE, SEESAW_STATUS_HW_ID, 1)[0]
            if hw_id not in VALID_HW_IDS:
                raise SensorReadError(f"unexpected seesaw hardware id 0x{hw_id:02x}")
        except Exception as exc:
            logger.debug("No STEMMA sensor at 0x%02x: %s", address, exc)
            return False

        self._initialized_sensors.add(address)
        logger.info("Initialized STEMMA sensor at 0x%02x (hw id 0x%02x)", address, hw_id)
        return True

    def _write(self, address: int, base: int, function: int, payload: list[int] | None = None) -> None:
        if not self.bus:
            raise SensorReadError("I2C bus not initialized")
        message = smbus2.i2c_msg.write(address, [base, function, *(payload or [])])
        self.bus.i2c_rdwr(message)

    def _read(self, address: int, base: int, function: int, length: int, delay: float = 0.008) -> bytes:
        if not self.bus:
            raise SensorReadError("I2C bus not initialized")
        # Seesaw needs a STOP and a settling delay between the register write and
        # the read; a repeated start hands back stale bytes instead of the value.
        self._write(address, base, function)
        time.sleep(delay)
        message = smbus2.i2c_msg.read(address, length)
        self.bus.i2c_rdwr(message)
        return bytes(message)

    def _reset(self, address: int) -> None:
        self._write(address, SEESAW_STATUS_BASE, SEESAW_STATUS_SWRST, [0xFF])
        time.sleep(0.5)

    def _read_moisture(self, address: int) -> int:
        # The capacitive peripheral reports 0xFFFF until its conversion finishes,
        # so retry rather than surfacing the sentinel as a reading.
        for _ in range(10):
            raw = self._read(
                address,
                SEESAW_TOUCH_BASE,
                SEESAW_TOUCH_CHANNEL_OFFSET + MOISTURE_TOUCH_PIN,
                2,
                delay=0.005,
            )
            value = struct.unpack(">H", raw)[0]
            if value != NOT_READY:
                return value
            time.sleep(0.001)
        raise SensorReadError(f"moisture read at 0x{address:02x} never became ready")

    def _read_temperature(self, address: int) -> float:
        raw = bytearray(self._read(address, SEESAW_STATUS_BASE, SEESAW_STATUS_TEMP, 4, delay=0.005))
        raw[0] &= 0x3F  # high bits are status flags, not part of the fixed-point value
        return struct.unpack(">I", bytes(raw))[0] / 65536.0

    def dry_for(self, address: int | None) -> int:
        """This probe's dry point, or the configured default.

        The default is defensible here in a way it is not for the other end:
        dry is the floor of the scale, so being wrong about it compresses a
        reading rather than inventing a ceiling for it.
        """
        entry = self.calibration.get(address) if address is not None else None
        if entry and "dry" in entry:
            return int(entry["dry"])
        return self.raw_dry

    def span_for(self, address: int | None) -> tuple[int, int] | None:
        """The two ends of this probe's scale, or None if they are unusable.

        Renamed from endpoints_for rather than re-pointed, on purpose. The old
        name always returned a pair, so every caller would have gone on
        compiling against a function that had quietly changed what it means.

        None in two cases, and both have to stay distinguishable from a real
        reading:

        * No field capacity for this pot. Nothing has been measured, so there
          is no top of the scale.
        * The two ends are too close together. Field capacity is measured once
          per mix on one probe and then used by the others, so a pot whose own
          dry point sits near that figure produces a span that would read as a
          permanent 0% or 100%. The old code clamped, and the 100% end of that
          clamp reads as "just watered" and stops watering for ever.
        """
        capacity = self.field_capacity.get(address) if address is not None else None
        if capacity is None:
            return None

        dry = self.dry_for(address)
        if int(capacity) - dry < MIN_CALIBRATION_SPAN:
            return None
        return dry, int(capacity)

    def raw_to_percent(self, raw: float, address: int | None = None) -> float:
        """A raw count as a percentage of field capacity, or -1 for cannot say.

        -1 is the same sentinel an unreadable probe gives, and that is the
        point: both mean "no judgement available", and everything downstream
        already refuses to water on it.
        """
        span = self.span_for(address)
        if span is None:
            return -1.0
        dry, capacity = span
        percent = (raw - dry) / (capacity - dry) * 100.0
        return round(max(0.0, min(percent, 100.0)), 1)

    def read_all(self) -> list[SensorSample]:
        return [self.read_one(address) for address in self.addresses]

    def read_one(self, address: int) -> SensorSample:
        # Sensors get plugged in after startup, so re-probe addresses that have
        # not answered yet instead of writing them off until the next restart.
        if address not in self._initialized_sensors and not self._try_initialize(address):
            return unavailable_sample(address)

        try:
            moisture = self._read_moisture(address)
            temperature = self._read_temperature(address)
        except Exception as exc:
            logger.error("Error reading sensor at 0x%02x: %s", address, exc)
            # Forget it so the next poll re-probes; a reset often recovers a
            # sensor that dropped off, and this covers unplug/replug too.
            self._initialized_sensors.discard(address)
            return unavailable_sample(address)

        logger.debug("0x%02x moisture=%d temp=%.1fC", address, moisture, temperature)
        return SensorSample(
            sensor_address=address,
            moisture_percent=self.raw_to_percent(moisture, address),
            moisture_raw=float(moisture),
            temperature_c=round(temperature, 1),
        )

    def __del__(self) -> None:
        # getattr, not self.bus: if __init__ raised before setting it, __del__
        # still runs and an AttributeError here is unraisable noise that buries
        # the real error.
        if getattr(self, "bus", None):
            try:
                self.bus.close()
            except Exception:
                pass


def _collect(
    hub: SoilSensorHub,
    seconds: int,
    interval: float,
    progress: bool = True,
    addresses: list[int] | None = None,
) -> dict[int, dict]:
    """Read addresses repeatedly, returning per-address reads/errors/values.

    Shared by the soak test and by calibration: both want many samples per
    address over a fixed window, and differ only in what they do with them.

    `addresses` narrows it to a subset. Field capacity is measured on one probe
    at a time, and without this it would sample all four and then pick -- which
    takes four times as long on a bus that is the slow part, and reports reads
    against sensors nobody asked about.
    """
    targets = list(addresses) if addresses else list(hub.addresses)
    stats: dict[int, dict] = {
        address: {"reads": 0, "errors": 0, "values": []} for address in targets
    }
    started = time.monotonic()
    deadline = started + seconds
    next_report = started + 10

    while time.monotonic() < deadline:
        for address in targets:
            sample = hub.read_one(address)
            entry = stats[address]
            entry["reads"] += 1
            if sample.moisture_raw < 0:
                entry["errors"] += 1
            else:
                entry["values"].append(sample.moisture_raw)

        now = time.monotonic()
        if progress and now >= next_report:
            errors = sum(e["errors"] for e in stats.values())
            reads = sum(e["reads"] for e in stats.values())
            print(f"  {now - started:5.0f}s  {reads} reads, {errors} errors")
            next_report = now + 10
        time.sleep(interval)

    return stats


def _soak(hub: SoilSensorHub, seconds: int, interval: float) -> int:
    """Hammer the bus and report per-address error rates.

    Intermittent I2C trouble from cable capacitance or noise shows up as
    occasional failed reads, which are invisible in a single sample and easy to
    mistake for a flaky sensor weeks later. This turns it into a number.
    """
    print(f"Soaking the I2C bus for {seconds}s across {len(hub.addresses)} addresses...")
    stats = _collect(hub, seconds, interval)

    print(f"\n{'sensor':<20} {'reads':>7} {'errors':>7} {'rate':>7}  {'raw min/mean/max':<22} verdict")
    worst = 0.0
    for address, entry in stats.items():
        reads, errors = entry["reads"], entry["errors"]
        values = entry["values"]
        rate = (errors / reads * 100) if reads else 0.0

        if not values:
            spread, verdict = "-", "no sensor at this address"
        else:
            spread = f"{min(values):.0f} / {sum(values) / len(values):.0f} / {max(values):.0f}"
            worst = max(worst, rate)
            if errors == 0:
                verdict = "clean"
            elif rate < 1:
                verdict = "occasional dropouts, acceptable"
            else:
                verdict = "unreliable - check routing, hub pull-ups, cable length"

        print(f"{label_for(address):<20} {reads:>7} {errors:>7} {rate:>6.2f}%  {spread:<22} {verdict}")

    if worst == 0:
        print("\nNo errors. The bus is healthy at this cable length.")
    elif worst < 1:
        print(f"\nWorst address {worst:.2f}% errors. Tolerable, but watch it if cabling changes.")
    else:
        print(
            f"\nWorst address {worst:.2f}% errors. Try a slower I2C clock "
            "(dtparam=i2c_arm_baudrate), check the hubs for stacked pull-up "
            "resistors, and keep the run away from the LED data and motor wiring."
        )
    return 0 if worst < 1 else 1


# Below this, a measured wet point is not plausibly wetter than the dry point --
# almost always a prong that never reached the water, or a sensor still sitting
# in air. Writing it would make the plant read 100% permanently.
MIN_CALIBRATION_SPAN = 50

# Quality thresholds for a sampling run, both relative to the reading itself.
#
# An absolute count does not work here: sensor noise scales with the value, so
# a fixed budget that is comfortable at a dry ~330 is roughly two and a half
# times stricter at a wet ~800. Calibrating the wet point in water failed on
# that alone, at 54-64 counts, while air passed at 6-13.
#
# DRIFT is the one that means "had not settled" -- a sensor still taking up
# water, or coming to temperature, moves steadily in one direction, which shows
# as a gap between the first half of the run and the second. Symmetric noise
# does not move it.
#
# NOISE_BAND is the looser sanity check, measured p5-to-p95 rather than
# min-to-max so that one bubble letting go, or a single glitched read out of
# several hundred, cannot veto an otherwise clean run.
DRIFT_FLOOR = 15
DRIFT_FRACTION = 0.03
NOISE_FLOOR = 30
NOISE_FRACTION = 0.08


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, max(0, int(round(fraction * (len(sorted_values) - 1)))))
    return sorted_values[index]


def sample_quality(values: list[float]) -> dict[str, int]:
    """Median, settling drift and noise band for one sensor's samples."""
    ordered = sorted(values)
    median = statistics.median(values)
    half = len(values) // 2
    # Compared by median per half, so the drift figure is not itself dragged
    # around by the noise it is meant to look past.
    drift = (
        abs(statistics.median(values[half:]) - statistics.median(values[:half]))
        if half
        else 0.0
    )
    return {
        "value": int(round(median)),
        "drift": int(round(drift)),
        "band": int(round(_percentile(ordered, 0.95) - _percentile(ordered, 0.05))),
        "drift_allowed": int(round(max(DRIFT_FLOOR, DRIFT_FRACTION * median))),
        "band_allowed": int(round(max(NOISE_FLOOR, NOISE_FRACTION * median))),
    }


def measure_endpoint(
    hub: SoilSensorHub,
    address: int,
    seconds: int = 20,
    interval: float = 0.2,
    opposite: int | None = None,
    expect: str = "above",
    opposite_label: str = "the other end of the scale",
) -> dict[str, object]:
    """Sample one probe and decide whether the figure is worth keeping.

    **Writes nothing.** The caller stores the value if `written` comes back
    true, and that separation is the point: the same sampling and the same
    three rejection rules now feed three destinations -- a probe's dry point, a
    soil's field capacity, and one pot's override. Keeping the write out here
    also means "a rejected run stores nothing" is testable against the state
    file rather than against a return value.

    `opposite` is the count at the other end of this probe's scale, and
    `expect` says which side of it the new figure should land on. None skips
    that check, for the case where the other end has not been measured yet.

    The median is used rather than the mean: it ignores a single outlier read,
    and with hundreds of samples there is no reason to be sensitive to one.
    """
    stats = _collect(hub, seconds, interval, progress=False, addresses=[address])
    entry = stats[address]
    values = entry["values"]
    outcome: dict[str, object] = {
        "address": address,
        "reads": entry["reads"],
        "errors": entry["errors"],
    }

    if not values:
        outcome.update(
            written=False,
            reason=(
                "No sensor answered at this address. Check it is plugged "
                "into the hub and set to the address it is configured for."
            ),
        )
        return outcome

    quality = sample_quality(values)
    value = quality["value"]
    outcome.update(samples=len(values), **quality)
    # Kept under its old name so the CLI table and the web panel, which both
    # print a "spread" column, keep working.
    outcome["spread"] = quality["band"]

    if quality["drift"] > quality["drift_allowed"]:
        outcome.update(
            written=False,
            reason=(
                f"Reading moved {quality['drift']} points from the start of the "
                f"run to the end, more than the {quality['drift_allowed']} expected "
                f"of a settled sensor at this level. It is still taking up water "
                "or coming to temperature. Leave it in place for a minute, then "
                "run this again."
            ),
        )
        return outcome

    if quality["band"] > quality["band_allowed"]:
        outcome.update(
            written=False,
            reason=(
                f"Readings are jumping around by {quality['band']} points, more "
                f"than the {quality['band_allowed']} expected at this level. Check "
                "the sensor is held still and not touching the side of the "
                "container, and run the bus soak test if it persists."
            ),
        )
        return outcome

    # The obvious operator error: capturing field capacity with the probe still
    # in air, or the dry point with it still in wet soil. Either produces a
    # span that makes every later percentage meaningless.
    if opposite is not None:
        gap = value - opposite if expect == "above" else opposite - value
        if gap < MIN_CALIBRATION_SPAN:
            outcome.update(
                written=False,
                reason=(
                    f"Reading {value} is only {gap} points {expect} "
                    f"{opposite_label} of {opposite}, and at least "
                    f"{MIN_CALIBRATION_SPAN} is expected. Is the probe where you "
                    "think it is?"
                ),
            )
            return outcome

    outcome["written"] = True
    return outcome


def calibrate(
    hub: SoilSensorHub,
    endpoint: str = "dry",
    seconds: int = 20,
    interval: float = 0.2,
    state_path=None,
) -> dict[int, dict[str, object]]:
    """Sample every sensor and record its dry point.

    Dry only, and the probe should be in open air. The other end of the scale
    is field capacity, which is a property of the *mix* rather than of the
    probe -- two pots of different soil want different figures with identical
    sensors -- so it is measured per mix and stored on the soil and the pot,
    not here. The endpoint argument stays so a stale caller gets a readable
    refusal rather than silently calibrating the wrong thing.

    All four at once, because the probes are in the air together: there is no
    per-pot state involved, unlike field capacity.
    """
    if endpoint != "dry":
        raise ValueError(
            f"endpoint must be 'dry', not {endpoint!r}. Field capacity is "
            "measured per soil mix, not per probe."
        )

    measured_at = datetime.utcnow().isoformat(timespec="seconds")
    results: dict[int, dict[str, object]] = {}

    for address in hub.addresses:
        # The opposite end comes from the hub's field-capacity map, which the
        # automation layer syncs from the pots. Absent for a pot that has not
        # been measured, in which case the span check is skipped -- the same
        # shape as the old "wet not measured yet" path.
        outcome = measure_endpoint(
            hub,
            address,
            seconds=seconds,
            interval=interval,
            opposite=hub.field_capacity.get(address),
            expect="below",
            opposite_label="this pot's field capacity",
        )
        if outcome.get("written"):
            state.save_calibration_point(
                address,
                "dry",
                outcome["value"],
                samples=outcome.get("samples"),
                measured_at=measured_at,
                path=state_path,
            )
        results[address] = outcome

    # Apply immediately so a running process reflects the new calibration
    # without a restart -- which is the whole point of persisting it.
    hub.calibration = state.load_calibration(state_path)
    return results


def _print_calibration(hub: SoilSensorHub, state_path=None) -> int:
    """Both ends of every probe's scale, and where each one came from.

    The two halves no longer come from the same place: dry is measured per
    probe and lives in moisture_calibration, field capacity is measured per
    mix and reaches the hub from the pots. Printing them side by side with
    their provenance is the only way to see a pot that has one and not the
    other -- which reads as -1 rather than as a percentage.
    """
    stored = state.load_calibration(state_path)
    plants = {
        plant.get("sensor_address"): plant
        for plant in (state.load_state(state_path).get("plants") or [])
        if isinstance(plant, dict)
    }

    print(f"{'sensor':<20} {'dry':>6} {'source':<16} {'capacity':>9} {'span':>6}  from")
    for address in hub.addresses:
        dry = hub.dry_for(address)
        dry_source = "calibrated" if "dry" in stored.get(address, {}) else "MOISTURE_RAW_DRY"

        capacity = hub.field_capacity.get(address)
        span = hub.span_for(address)
        if capacity is None:
            shown, width, origin = "-", "-", "not measured"
        else:
            shown = str(capacity)
            width = str(capacity - dry) if span else "too narrow"
            entry = plants.get(address) or {}
            source = entry.get("field_capacity_source")
            if source == "pot":
                origin = "measured in this pot"
            elif source == "soil":
                origin = f"soil {entry.get('field_capacity_soil') or '?'!r}"
            else:
                origin = "unknown"

        print(
            f"{label_for(address, state_path=state_path):<20} {dry:>6} "
            f"{dry_source:<16} {shown:>9} {width:>6}  {origin}"
        )

    if not stored:
        print("\nNo dry point measured yet. Every probe is using MOISTURE_RAW_DRY.")
    if not hub.field_capacity:
        print(
            "\nNo field capacity anywhere, so every pot reads -1 and nothing is "
            "watered automatically. Measure it per soil mix under Plants and "
            "Soil in the app."
        )
    return 0


if __name__ == "__main__":
    import argparse
    import sys

    from greenthumb.config import settings

    parser = argparse.ArgumentParser(description="Read the soil sensors directly.")
    parser.add_argument(
        "--soak",
        type=int,
        nargs="?",
        const=60,
        metavar="SECONDS",
        help="hammer the bus for this long (default 60s) and report error rates",
    )
    parser.add_argument(
        "--interval", type=float, default=0.2, help="seconds between soak passes"
    )
    parser.add_argument(
        "--calibrate",
        choices=("dry",),
        help=(
            "record the dry point for every sensor, with the probes in open "
            "air. The other end of the scale is field capacity, which belongs "
            "to the soil mix rather than the probe -- measure that under "
            "Plants and Soil in the app"
        ),
    )
    parser.add_argument(
        "--seconds",
        type=int,
        default=20,
        help="how long to sample during --calibrate (default 20s)",
    )
    parser.add_argument(
        "--show-calibration",
        action="store_true",
        help="print the stored calibration and exit",
    )
    args = parser.parse_args()

    # Per-read errors are the thing being counted during a soak, so logging each
    # one would bury the summary in exactly the case the summary is for. The
    # same applies to calibration, which reads just as hard.
    quiet = args.soak or args.calibrate
    logging.basicConfig(
        level=logging.CRITICAL if quiet else logging.DEBUG,
        format="%(levelname)s %(name)s: %(message)s",
    )

    hub = SoilSensorHub(
        addresses=settings.moisture_sensor_addresses_list,
        raw_dry=settings.moisture_raw_dry,
        calibration=state.load_calibration(),
        # Taken from the pots, the same way the running service syncs it. The
        # CLI has no automation instance, so it reads the stored plants
        # directly -- without this, --show-calibration would report no field
        # capacity on a planter that has plenty.
        field_capacity={
            plant["sensor_address"]: int(plant["field_capacity_raw"])
            for plant in (state.load_state().get("plants") or [])
            if isinstance(plant, dict)
            and isinstance(plant.get("sensor_address"), int)
            and isinstance(plant.get("field_capacity_raw"), (int, float))
            and not isinstance(plant.get("field_capacity_raw"), bool)
        },
    )

    if args.show_calibration:
        sys.exit(_print_calibration(hub))

    if args.soak:
        sys.exit(_soak(hub, args.soak, args.interval))

    if args.calibrate:
        print(
            f"Calibrating the DRY point over {args.seconds}s. All "
            f"{len(hub.addresses)} sensors should be in open air."
        )
        results = calibrate(hub, args.calibrate, args.seconds, args.interval)

        print(f"\n{'sensor':<20} {'value':>6} {'spread':>7} {'samples':>8}  result")
        failures = 0
        for address, outcome in results.items():
            if outcome.get("written"):
                print(
                    f"{label_for(address):<20} {outcome['value']:>6} {outcome['spread']:>7} "
                    f"{outcome['samples']:>8}  stored as dry"
                )
            else:
                failures += 1
                value = outcome.get("value", "-")
                shown = f"{value:>6}" if value != "-" else f"{'-':>6}"
                print(f"{label_for(address):<20} {shown} {'-':>7} {'-':>8}  NOT STORED: {outcome['reason']}")

        if failures:
            print(f"\n{failures} sensor(s) not stored. Fix the cause and re-run.")
        else:
            print("\nAll sensors stored. Run --show-calibration to review.")
        sys.exit(1 if failures else 0)

    for sample in hub.read_all():
        print(
            f"{label_for(sample.sensor_address):<20} raw={sample.moisture_raw:.0f}  "
            f"moisture={sample.moisture_percent}%  temp={sample.temperature_c}C"
        )
