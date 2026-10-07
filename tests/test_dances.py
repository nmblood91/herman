"""Idle motion: the periodic re-home and the routines that go with it.

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
from tests.helpers import temp_state, temp_store

settings.auto_watering_enabled = False
settings.idle_motion_enabled = True
settings.idle_motion_minutes = 60

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


class Hub:
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


# --- the hourly cycle ---

auto, klip = build()
auto.set_idle_motion(True, 60)
auto.tick()
assert klip.gcode == [], "danced on the first tick after startup"
print("ok: a restart does not set it dancing immediately")

auto._last_idle_motion = datetime.now() - timedelta(minutes=61)
auto.tick()
assert klip.homes == 1 and len(klip.gcode) == 1, (klip.homes, klip.gcode)
print("ok: once the interval is up it homes and runs one routine")

before = len(klip.gcode)
auto.tick()
assert len(klip.gcode) == before, "ran again on the very next tick"
print("ok: and then waits out the interval again")

# Rotating matters: four routines that always open with the same one is one
# routine as far as anybody watching is concerned. Fresh instance, so the
# rotation starts where a new planter would.
auto, klip = build()
auto.set_idle_motion(True, 60)
auto._last_idle_motion = datetime.now()
seen = []
for _ in range(len(dances.DEFAULT_ORDER)):
    seen.append(auto.idle_motion_status()["next_dance"])
    auto._last_idle_motion = datetime.now() - timedelta(minutes=61)
    auto.tick()
assert seen == list(dances.DEFAULT_ORDER), seen
print(f"ok: it cycles through all of them -> {', '.join(seen)}")


# --- it yields to everything else ---

auto, klip = build()
auto.set_idle_motion(True, 60)
auto.set_quiet_hours(True, "00:00", "23:59")
auto._last_idle_motion = datetime.now() - timedelta(minutes=61)
auto.tick()
assert klip.gcode == [], "danced during quiet hours"
print("ok: quiet hours holds it, the arm being the other noisy part")

# Held, not skipped: the clock must not advance, or closing the window would
# mean waiting another full interval before anything happens.
auto.set_quiet_hours(False)
auto.tick()
assert len(klip.gcode) == 1, "did not run once quiet hours ended"
print("ok: it runs as soon as the window closes rather than waiting again")

auto, klip = build()
auto.set_idle_motion(True, 60)
auto.snooze_watering(2)
auto._last_idle_motion = datetime.now() - timedelta(minutes=61)
auto.tick()
assert klip.gcode == [], "danced while snoozed"
print("ok: a snooze holds it too")

auto, klip = build()
auto.set_idle_motion(False)
auto._last_idle_motion = datetime.now() - timedelta(days=1)
auto.tick()
assert klip.gcode == [], "danced while switched off"
print("ok: switched off means switched off")


# --- settings survive a restart ---

shared = temp_state()
first, _ = build(shared)
first.set_idle_motion(True, 180)
first._last_idle_motion = datetime.now() - timedelta(minutes=181)
first.tick()
restored, _ = build(shared)
assert restored.idle_motion_enabled is True
assert restored.idle_motion_minutes == 180, restored.idle_motion_minutes
assert restored.idle_motion_status()["next_dance"] == dances.DEFAULT_ORDER[1], (
    "the rotation restarted from the top after a restart"
)
print("ok: interval and position in the rotation both survive a restart")

for bad in (0, 4, 1441, -10):
    try:
        build()[0].set_idle_motion(True, bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"accepted a {bad} minute interval")
print("ok: absurd intervals are refused")

# A routine you asked for counts, so pressing the button is not followed by an
# automatic one a minute later.
auto, klip = build()
auto.set_idle_motion(True, 60)
auto._last_idle_motion = datetime.now() - timedelta(minutes=61)
auto.run_dance("shuffle")
auto.tick()
assert len(klip.gcode) == 1, "an automatic routine followed a manual one"
print("ok: a manual routine resets the interval")

print("\nall idle motion checks passed")
