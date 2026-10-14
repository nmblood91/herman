"""Routines, the hourly auto-patrol, and the startup home.

Two things matter here and neither is the choreography. A routine must never
hand Klipper a move outside the rail, and it must never be the reason
something that actually matters did not happen -- a watering cycle, or a quiet
evening.
"""

import sys
import types
from datetime import datetime, timedelta

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import dances
from greenthumb.config import settings
from greenthumb.hardware.soil_sensors import unavailable_sample
from greenthumb.services.automation import GreenThumbAutomation, HardwareBusyError
from tests.helpers import CalibrationSurface, temp_state, temp_store

settings.auto_watering_enabled = False
settings.auto_patrol_enabled = False
settings.home_on_startup = False

TRAVEL = 890.0


class Klip:
    def __init__(self, homed=True):
        self.gcode = []
        self.homes = 0
        self._homed = homed

    def status(self):
        return {"ok": True, "position": 0.0, "homed": self._homed, "max_x": TRAVEL}

    def home_gantry(self):
        self.homes += 1
        self._homed = True
        return {"ok": True}

    def send_gcode(self, gcode, timeout=5.0):
        self.gcode.append(gcode)
        return {"ok": True}

    def move_gantry_absolute(self, p):
        return {"ok": True}

    def water_supply_present(self):
        return True


class Hub(CalibrationSurface):
    # The real hub answers with an unavailable sample rather than None when a
    # sensor does not reply, and the control loop relies on that.
    addresses = [0x36, 0x37, 0x38, 0x39]
    def read_one(self, a): return unavailable_sample(a)


class Nul:
    mode = "off"; color = (0, 0, 0); brightness = 0
    def __getattr__(self, n): return lambda *a, **k: {}


def build(state=None, klip=None):
    klip = klip or Klip()
    auto = GreenThumbAutomation(
        Hub(), klip, Nul(), Nul(),
        history=temp_store(), state_path=state or temp_state(),
    )
    return auto, klip


# --- no routine may leave the rail ---

for name in dances.DEFAULT_ORDER:
    steps = dances.steps_for(name, TRAVEL, [130, 355, 580, 800])
    assert steps, f"{name} produced no steps"
    for position, feedrate, dwell in steps:
        assert 0.0 <= position <= TRAVEL, f"{name} goes to {position}, rail is {TRAVEL}"
        assert feedrate > 0, f"{name} has a zero feedrate"
    assert steps[-1][0] == 0.0, f"{name} ends at {steps[-1][0]} rather than parked at 0"
print(f"ok: all {len(dances.DEFAULT_ORDER)} routines stay on the rail and park at 0")

# A plant saved beyond a rail that was later measured shorter must not become
# a move Klipper refuses -- that would kill the whole routine mid-way.
steps = dances.steps_for("patrol", 500.0, [130, 355, 580, 800])
assert all(p <= 500.0 for p, _, _ in steps), steps
print("ok: a plant beyond the rail is clamped rather than sent as-is")

# Patrol with nothing configured still does something visible.
assert dances.steps_for("patrol", TRAVEL, []) == dances.steps_for("stretch", TRAVEL)
print("ok: patrol with no plants falls back instead of standing still")

try:
    dances.steps_for("moonwalk", TRAVEL)
except ValueError:
    print("ok: an unknown routine is refused")
else:
    raise AssertionError("expected ValueError")


# --- the gcode is one block, and dwells survive ---

gcode = dances.gcode_for(dances.steps_for("shuffle", TRAVEL))
assert gcode.startswith("G90"), gcode
assert gcode.count("G1 X") == len(dances.steps_for("shuffle", TRAVEL)), gcode
assert "G4 P" in gcode, "the pause in shuffle was dropped"
print("ok: a routine is one absolute-mode block, pauses included")


# --- running one by hand ---

auto, klip = build()
result = auto.run_dance("wave")
assert result["ok"] is True, result
assert len(klip.gcode) == 1, "a routine should be one script, not a move at a time"
assert klip.homes == 0, "homed an already-homed axis for a manual routine"
print("ok: a manual routine sends one script and does not re-home needlessly")

auto, klip = build(klip=Klip(homed=False))
auto.run_dance("shuffle")
assert klip.homes == 1, "ran a routine on an unhomed axis"
print("ok: an unhomed axis is homed first, since every move would be refused")

auto, klip = build()
auto._hardware_lock.acquire()
try:
    auto.run_dance("stretch")
except HardwareBusyError:
    print("ok: a routine is refused while the hardware is busy, not queued")
else:
    raise AssertionError("expected HardwareBusyError")
finally:
    auto._hardware_lock.release()


# --- the patrol moves the way each plant waters ---

from greenthumb import sweep

stops = [
    dances.PatrolStop(600.0),
    dances.PatrolStop(100.0, sweep_to_mm=250.0, feedrate=2400),
]
steps = dances.steps_for("patrol", TRAVEL, stops)
assert steps == [
    (100.0, dances.CRUISE, 0),
    (250.0, 2400, 0),
    (100.0, 2400, 0),
    (250.0, 2400, dances.SWEEP_DWELL_MS),
    (600.0, dances.CRUISE, dances.POINT_DWELL_MS),
    (0.0, dances.CRUISE, 0),
], steps
print("ok: a sweeping plant gets passes across its span, ending at the far side, then it moves on")


class Limits(Klip):
    """A board that reports the motion limits a sweep is timed against."""

    velocity = 300.0

    def status(self):
        return {**super().status(), "max_velocity": self.velocity, "max_accel": 3000.0}


auto, klip = build(klip=Limits())
swept, pointed = auto.plants[0], auto.plants[1]
auto.set_plant_sweep(swept.plant_id, 20.0, 180.0)
auto.set_watering_mode(swept.plant_id, sweep.SWEEP)
_, _, plan = auto._resolve_sweep(swept, swept.watering_volume_ml)
auto.run_dance("patrol")
gcode = klip.gcode[-1]
assert f"G1 X180 F{plan.feedrate_mm_min}" in gcode, gcode
assert f"G1 X20 F{plan.feedrate_mm_min}" in gcode, gcode
assert f"G1 X{pointed.position_mm} F{dances.CRUISE}" in gcode, gcode
print("ok: a sweep plant is swept at the speed its own dose would use; point plants still pause")

# The patrol must not show a sweep the watering would not make. A dose too
# short to cross the span waters as a point, so the patrol pauses instead.
# Plant 3, on a slow board, so 1 mL clearly cannot cross its whole zone.
wide = auto.plants[2]
klip.velocity = 100.0
auto.set_plant_sweep(wide.plant_id, 445.0, 690.0)
auto.set_watering_mode(wide.plant_id, sweep.SWEEP)
wide.watering_volume_ml = 1
assert isinstance(auto._resolve_sweep(wide, 1), str), "1 mL crossed 245 mm"
auto.run_dance("patrol")
gcode = klip.gcode[-1]
assert "X690" not in gcode, gcode
assert f"G1 X{wide.position_mm} F{dances.CRUISE}" in gcode, gcode
print("ok: a sweep that would fall back to a point is patrolled as a point")

# A spot stored outside its zone -- before the zones existed, or by hand -- is
# one watering refuses, so the patrol does not stop there either.
wide.watering_mode = sweep.POINT
wide.position_mm = 900.0
assert len(auto._patrol_stops()) == len(auto.plants) - 1
print("ok: a watering spot outside its zone is left out of the patrol")

# Without the motion limits a dose cannot be timed and waters as a point; the
# patrol follows suit.
auto, klip = build()
auto.plants[0].watering_mode = sweep.SWEEP
auto.plants[0].sweep_min_mm, auto.plants[0].sweep_max_mm = 20.0, 180.0
assert all(stop.sweep_to_mm is None for stop in auto._patrol_stops())
print("ok: no motion limits from Klipper, no sweep in the patrol either")


# --- the hourly auto-patrol ---
#
# auto_patrol is what the scheduler calls at minute 0. Called directly here
# with a fixed time, so nothing below depends on what the clock says while
# the test runs.

AT_TWO = datetime(2026, 10, 14, 14, 0)


def patrol_gcode(auto):
    return dances.gcode_for(dances.steps_for(
        "patrol", auto.usable_travel_mm(), auto._patrol_stops()
    ))


# Off by default, for the same reason as the startup home: nobody assembling
# a planter should have the arm set off before they are ready for it.
assert type(settings).model_fields["auto_patrol_enabled"].default is False
auto, klip = build()
auto.auto_patrol(now=AT_TWO)
assert klip.gcode == [] and klip.homes == 0, (klip.gcode, klip.homes)
print("ok: the hourly patrol is off by default, and off means off")

auto, klip = build()
auto.set_auto_patrol(True)
for hour in range(3):
    auto.auto_patrol(now=AT_TWO + timedelta(hours=hour))
assert klip.homes == 3, f"homed {klip.homes} times for 3 patrols"
assert klip.gcode == [patrol_gcode(auto)] * 3, klip.gcode
assert auto.auto_patrol_status()["last"] == {"at": "2026-10-14T16:00", "ok": True, "error": None}
print("ok: every run homes first and then patrols -- always the patrol, never a rotation")

# The control loop no longer moves the arm on a timer: on the hour is the
# scheduler's job, and a tick a minute apart could not land on it.
auto, klip = build()
auto.set_auto_patrol(True)
for _ in range(3):
    auto.tick()
assert klip.gcode == [] and klip.homes == 0, (klip.gcode, klip.homes)
print("ok: the control loop never patrols by itself")

# A manual routine is never held, and has no bearing on the schedule.
auto, klip = build()
auto.set_auto_patrol(True)
auto.run_dance("shuffle")
auto.auto_patrol(now=AT_TWO)
assert len(klip.gcode) == 2, "a manual routine suppressed the hourly patrol"
print("ok: a manual routine does not push the hourly patrol back")


# --- it yields to quiet hours and a snooze ---

auto, klip = build()
auto.set_auto_patrol(True)
auto.set_quiet_hours(True, "21:00", "08:00")
auto.auto_patrol(now=datetime(2026, 10, 14, 23, 0))
assert klip.gcode == [] and klip.homes == 0, "patrolled during quiet hours"
assert auto.auto_patrol_status()["last"] is None, "a skipped hour was reported as a run"
auto.auto_patrol(now=datetime(2026, 10, 15, 9, 0))
assert len(klip.gcode) == 1, "did not patrol once quiet hours were over"
print("ok: quiet hours skip the hour, and the next hour after the window runs")

auto, klip = build()
auto.set_auto_patrol(True)
auto.snooze_watering(2)
auto.auto_patrol()
assert klip.gcode == [], "patrolled while snoozed"
print("ok: a snooze skips it too")


# --- busy hardware is waited out, briefly ---

import threading
import greenthumb.services.automation as automation_module

automation_module.PATROL_BUSY_POLL_SECONDS = 0.02

auto, klip = build()
auto.set_auto_patrol(True)
auto._hardware_lock.acquire()
try:
    auto.auto_patrol(now=AT_TWO, busy_wait_seconds=0)
finally:
    auto._hardware_lock.release()
assert klip.gcode == [], klip.gcode
last = auto.auto_patrol_status()["last"]
assert last["ok"] is False and last["error"] == "hardware was busy", last
print("ok: hardware that stays busy past the wait gives up the hour and says so")

auto, klip = build()
auto.set_auto_patrol(True)
auto._hardware_lock.acquire()
threading.Timer(0.1, auto._hardware_lock.release).start()
auto.auto_patrol(now=AT_TWO, busy_wait_seconds=5)
assert len(klip.gcode) == 1, "gave up instead of waiting for a dose to finish"
print("ok: hardware that frees up within the wait gets its patrol")


class NoHome(Klip):
    def home_gantry(self):
        self.homes += 1
        return {"ok": False, "error": "endstop not triggered"}


auto, klip = build(klip=NoHome())
auto.set_auto_patrol(True)
auto.auto_patrol(now=AT_TWO)
assert klip.gcode == [], "patrolled without a home"
last = auto.auto_patrol_status()["last"]
assert last["ok"] is False and "endstop not triggered" in last["error"], last
print("ok: a failed home stops the patrol, and the reason reaches the UI")


# --- settings survive a restart ---

shared = temp_state()
first, _ = build(shared)
first.set_auto_patrol(True)
restored, _ = build(shared)
assert restored.auto_patrol_enabled is True
print("ok: the patrol switch survives a restart")


# --- the startup home ---
#
# Until the arm is homed Klipper reports a position relative to wherever the
# carriage happened to power up, so every plant profile coordinate is wrong by an
# unknown amount and watering is refused outright.

assert type(settings).model_fields["home_on_startup"].default is False
print("ok: the startup home is off by default")

auto, klip = build(klip=Klip(homed=False))
auto.set_home_on_startup(True)
assert klip.homes == 0, "homed during construction, before anything held the lock"
print("ok: nothing homes while the service is still starting up")

auto.tick()
assert klip.homes == 1, klip.homes
assert klip.gcode == [], "ran a routine as well as homing"
for _ in range(5):
    auto.tick()
assert klip.homes == 1, f"homed {klip.homes} times, so it is homing every tick"
assert auto.startup_home_status()["phase"] == "done", auto.startup_home_status()
print("ok: the first tick homes, only homes, and only once")

# Off at startup means off for this run. Switching it on afterwards must not
# set the arm off out of nowhere -- that is the surprise the default prevents.
auto, klip = build(klip=Klip(homed=False))
for _ in range(3):
    auto.tick()
auto.set_home_on_startup(True)
for _ in range(3):
    auto.tick()
assert klip.homes == 0, klip.homes
assert auto.startup_home_status()["phase"] == "next_start", auto.startup_home_status()
print("ok: switched on after startup, it waits for the next start rather than homing now")

# Deferred, not cancelled, by a snooze.
auto, klip = build(klip=Klip(homed=False))
auto.set_home_on_startup(True)
auto.snooze_watering(2)
auto.tick()
assert klip.homes == 0, "homed through a snooze"
status = auto.startup_home_status()
assert status["phase"] == "waiting" and status["held"].startswith("snoozed"), status
auto.cancel_snooze()
auto.tick()
assert klip.homes == 1, klip.homes
print("ok: a snooze defers the startup home, and it homes once the snooze lifts")


# --- a home that fails is retried until it lands ---
#
# The usual cause is this service starting before Klipper is ready, which
# clears up on its own. Giving up would leave watering refused until a restart.

class Flaky(Klip):
    def __init__(self, failures):
        super().__init__(homed=False)
        self.failures = list(failures)

    def home_gantry(self):
        self.homes += 1
        if self.failures:
            failure = self.failures.pop(0)
            if isinstance(failure, Exception):
                raise failure
            return {"ok": False, "error": failure}
        self._homed = True
        return {"ok": True}


flaky = Flaky(["Klipper not ready", RuntimeError("socket refused")])
auto, _ = build(klip=flaky)
auto.set_home_on_startup(True)

auto.tick()
status = auto.startup_home_status()
assert status["phase"] == "retrying" and status["error"] == "Klipper not ready", status
auto.tick()
status = auto.startup_home_status()
assert status["phase"] == "retrying" and status["error"] == "socket refused", status
assert status["attempts"] == 2, status
print("ok: a refused or raising home is reported and retried, not given up on")

auto.tick()
assert flaky.homes == 3, flaky.homes
status = auto.startup_home_status()
assert status["phase"] == "done" and status["error"] is None, status
for _ in range(3):
    auto.tick()
assert flaky.homes == 3, f"kept homing after it succeeded ({flaky.homes})"
print("ok: once it lands it stops")

# Someone else holding the arm is a wait, not a failed attempt.
auto, klip = build(klip=Klip(homed=False))
auto.set_home_on_startup(True)
auto._hardware_lock.acquire()
try:
    auto.tick()
finally:
    auto._hardware_lock.release()
assert klip.homes == 0 and auto.startup_home_status()["attempts"] == 0, (
    klip.homes, auto.startup_home_status()
)
print("ok: busy hardware does not count as a failed attempt")

# Any home settles it, so pressing the button first is not followed by a
# second home a minute later.
auto, klip = build(klip=Klip(homed=False))
auto.set_home_on_startup(True)
auto.home_gantry()
auto.tick()
assert klip.homes == 1, klip.homes
assert auto.startup_home_status()["phase"] == "done", auto.startup_home_status()
print("ok: a manual home before the first tick settles the startup home")


# --- the choice persists ---

shared = temp_state()
first, _ = build(shared)
first.set_home_on_startup(True)
again, _ = build(shared)
assert again.home_on_startup is True
assert again.startup_home_status()["enabled"] is True
print("ok: the startup-home choice survives a restart")


print("\nall routine, patrol and startup-home checks passed")
