"""Calibrating the pump's flow rate, and keeping it in state.

This is the one number in the planter that is a guess until somebody measures
it, and it is the guess with the worst failure mode: a dose is a run time
worked out from it, so a wrong figure scales *every* watering by the same
factor and still reports success. Nothing downstream can detect it -- the water
sensor confirms that water arrived, not how much.

So the tests here are about the arithmetic being right, about the figure
surviving a restart, and most of all about the ways a bad number is refused
rather than stored.
"""

import sys
import types
from time import sleep

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import state
from greenthumb.config import settings
from greenthumb.hardware.pump import PumpController
from greenthumb.models import SensorSample
from greenthumb.services.automation import (
    MAX_FLOW_ML_PER_SECOND,
    MIN_CALIBRATION_SECONDS,
    MIN_FLOW_ML_PER_SECOND,
    GreenThumbAutomation,
)
from tests.helpers import give_every_plant_soil, temp_state, temp_store

settings.auto_watering_enabled = False
settings.water_sensor_enabled = False
settings.idle_motion_enabled = False


class Klip:
    def __init__(self):
        self.gcode = []

    def send_gcode(self, script, timeout=5.0):
        self.gcode.append(script)
        return {"ok": True}

    def move_gantry_absolute(self, position):
        return {"ok": True}

    def status(self):
        return {"ok": True, "position": 0.0, "homed": True, "max_x": 890.0}

    def water_supply_present(self):
        return True


class Hub:
    addresses = [0x36, 0x37, 0x38, 0x39]
    def raw_to_percent(self, raw, address=None): return 0.0
    def read_one(self, a): return SensorSample(a, 0.0, 350.0, 22.0)


class Leds:
    mode = "schedule"
    def set_plant_segments(self, s): pass
    def status(self): return {"mode": "schedule"}


def build(path=None):
    klip = Klip()
    auto = give_every_plant_soil(
        GreenThumbAutomation(
            Hub(), klip, PumpController(klip), Leds(),
            history=temp_store(), state_path=path or temp_state(),
        )
    )
    return auto, klip


def fake_run(auto, seconds):
    """Stand in for a timed run, so the tests do not wait a real minute.

    The real timing path is driven separately, below -- faking it everywhere
    would leave the thing being divided by untested.
    """
    auto._last_pump_run = {"seconds": float(seconds), "at": "2026-10-09T12:00:00"}


# --- it starts out a guess, and says so ---

auto, _ = build()
status = auto.pump_status()
assert status["flow_ml_per_second"] == settings.pump_flow_ml_per_second
# The whole point of recording this: a planter running on the datasheet figure
# has to be distinguishable from one that has been measured.
assert status["measured_at"] is None
assert status["last_run"] is None
print("ok: an uncalibrated planter reports the default and no measurement date")

# The dose timing is derived from it, so the readout and the behaviour agree.
assert abs(status["seconds_for_100ml"] - auto._dose_seconds(100)) < 0.05
print("ok: the reported 100 mL run time is the one a dose would actually use")


# --- the arithmetic ---

auto, _ = build()
fake_run(auto, 60)
result = auto.calibrate_pump_flow(72)
assert abs(result["flow_ml_per_second"] - 72 / 60) < 1e-6, result
assert abs(auto.pump.flow_ml_per_second - 1.2) < 1e-9
print(f"ok: 72 mL in 60s is {result['flow_ml_per_second']} mL/s")

# The figure that matters to the user is the run time it implies, because that
# is what they can check against a real dose and a scale.
assert result["seconds_for_100ml"] == 83.3, result
assert abs(auto._dose_seconds(100) - 100 / 1.2) < 1e-9
print(f"ok: and a 100 mL dose now runs for {result['seconds_for_100ml']}s")

# Dividing by the run that actually happened, not by the dead-man limit. A run
# stopped early is still a valid measurement; assuming it was the full length
# would silently inflate the rate.
auto, _ = build()
fake_run(auto, 41.5)
reported = auto.calibrate_pump_flow(50)["flow_ml_per_second"]
# The reported figure is rounded for display; the one doses are timed against
# is not, and that is the one that has to be exact.
assert abs(auto.pump.flow_ml_per_second - 50 / 41.5) < 1e-12
assert abs(reported - 50 / 41.5) < 1e-4, reported
print("ok: a run stopped early divides by its real length, not the limit")


# --- the run really is timed, rather than assumed ---
#
# Everything above divides by a figure the planter measured. If that figure
# were the dead-man limit rather than the real elapsed time, every calibration
# would be wrong by however early the run was stopped -- and silently, since
# the arithmetic would still look right.

auto, _ = build()
auto.run_pump()
assert auto._last_pump_run is None, "a run still going already had a length"
sleep(0.05)
auto.stop_pump()

run = auto._last_pump_run
assert run is not None, "the run was never timed"
assert run["seconds"] > 0, run
# The giveaway if the limit were being used instead of the clock.
assert run["seconds"] < 5, run
assert run["seconds"] != float(settings.pump_max_run_seconds), run
assert run["at"], run
print(f"ok: a run that lasted {run['seconds']}s is recorded as that, not as the limit")

# And that real measurement is what the length guard sees, so a hurried run
# cannot become a calibration.
try:
    auto.calibrate_pump_flow(100)
except ValueError as error:
    assert "weigh" in str(error), error
else:
    raise AssertionError("calibrated from a run of a twentieth of a second")
print("ok: and a run stopped straight away is refused as a calibration")

# A second run re-times rather than keeping the first.
auto.run_pump()
sleep(0.12)
auto.stop_pump()
assert auto._last_pump_run["seconds"] > run["seconds"], (auto._last_pump_run, run)
print("ok: a second run replaces the first run's length")


# --- a bad number is refused, because nothing downstream can catch it ---

auto, _ = build()
try:
    auto.calibrate_pump_flow(100)
except ValueError as error:
    assert "Run the pump" in str(error), error
else:
    raise AssertionError("calibrated against a run that never happened")
print("ok: calibrating before any run is refused, rather than inventing a duration")

auto, _ = build()
fake_run(auto, MIN_CALIBRATION_SECONDS - 0.1)
try:
    auto.calibrate_pump_flow(30)
except ValueError as error:
    assert "weigh" in str(error), error
else:
    raise AssertionError("accepted a run too short to weigh")
fake_run(auto, MIN_CALIBRATION_SECONDS)
assert auto.calibrate_pump_flow(30)["flow_ml_per_second"] > 0
print(f"ok: a run under {MIN_CALIBRATION_SECONDS:.0f}s is refused -- too little water to weigh")

auto, _ = build()
fake_run(auto, 60)
for volume, why in (
    (0, "nothing came out"),
    (-20, "a negative volume"),
    ("lots", "not a number"),
    (None, "nothing at all"),
    (True, "a boolean"),
    (float("nan"), "not-a-number"),
    (float("inf"), "infinite"),
):
    try:
        auto.calibrate_pump_flow(volume)
    except ValueError:
        pass
    else:
        raise AssertionError(f"accepted {why}: {volume!r}")
print("ok: a volume that is not a real measurement is refused")

# The realistic slip is a decimal in the wrong place, and it is dangerous
# precisely because the result stores happily and then mis-doses every pot by
# that factor for ever.
for volume, why in (
    (6000, "a tenfold overshoot"),
    (1, "a hundredfold undershoot"),
):
    try:
        auto.calibrate_pump_flow(volume)
    except ValueError as error:
        assert "mL/s" in str(error), error
    else:
        raise AssertionError(f"accepted {why}: {volume} mL in 60s")
print(f"ok: a rate outside {MIN_FLOW_ML_PER_SECOND} to {MAX_FLOW_ML_PER_SECOND} mL/s is refused as a typo")

# Refused means nothing changed, not partly applied.
assert auto.pump.flow_ml_per_second == settings.pump_flow_ml_per_second
assert auto.pump_status()["measured_at"] is None
print("ok: a refused calibration leaves the old rate and the old date alone")


# --- it survives a restart, which is the reason it left .env ---

shared = temp_state()
auto, _ = build(shared)
fake_run(auto, 60)
auto.calibrate_pump_flow(72)
measured_at = auto.pump_status()["measured_at"]
assert measured_at is not None

restored, _ = build(shared)
assert abs(restored.pump.flow_ml_per_second - 1.2) < 1e-9
assert restored.pump_status()["measured_at"] == measured_at
print("ok: the measured rate and its date come back after a restart")

# And it is what a dose is actually timed against after that restart, which is
# the thing that would quietly not happen if it were only a readout.
assert abs(restored._dose_seconds(100) - 100 / 1.2) < 1e-9
print("ok: and the restored rate is the one a dose is timed against")

# In the settings file rather than in .env, which is the whole reason it
# moved: a reflash restores it with the other hand-tuned values instead of
# needing the file edited again.
saved = state.load_state(shared)["watering"]
assert abs(saved["flow_ml_per_second"] - 1.2) < 1e-9, saved
assert saved["flow_measured_at"] == measured_at, saved
print("ok: and it is written to the settings file, under watering")


# --- a corrupt or hand-edited figure does not take the planter down ---

for bad in (0, -1, "fast", True, None, 999, 0.0001):
    auto, _ = build()
    auto._restore_pump_flow({"flow_ml_per_second": bad})
    assert auto.pump.flow_ml_per_second == settings.pump_flow_ml_per_second, bad
    # And it must not claim to have been measured, or the UI would stop
    # warning that this planter is running on a datasheet figure.
    assert auto.pump_status()["measured_at"] is None, bad
print("ok: an unusable stored rate falls back to the default and is not called measured")

auto, _ = build()
auto._restore_pump_flow({"flow_ml_per_second": 2.5, "flow_measured_at": 12345})
assert auto.pump.flow_ml_per_second == 2.5
assert auto.pump_status()["measured_at"] is None
print("ok: a good rate with a junk date keeps the rate and drops the date")


# --- the flow rate is read safely wherever it is read ---

# A stub pump that answers every attribute used to hand back a bound method
# here, which is not JSON serialisable -- and that reached the state snapshot
# and took every settings save down with it, silently.
class Anything:
    mode = "off"
    def __getattr__(self, name): return lambda *a, **k: {}


auto = GreenThumbAutomation(
    Hub(), Klip(), Anything(), Leds(), history=temp_store(), state_path=temp_state()
)
assert auto._pump_flow() == settings.pump_flow_ml_per_second
assert isinstance(auto._snapshot()["watering"]["flow_ml_per_second"], float)
import json

json.dumps(auto._snapshot())
print("ok: a pump that answers everything does not poison the settings snapshot")


# --- the dead-man limit is also the calibration run length ---

assert settings.pump_max_run_seconds >= MIN_CALIBRATION_SECONDS, (
    "the manual run is shorter than a usable calibration, so the button in "
    "Diagnostics could never produce a measurement it would accept"
)
print(f"ok: the {settings.pump_max_run_seconds}s run is long enough to calibrate from")


print("\nall pump flow checks passed")
