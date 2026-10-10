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
# Off, so the home counted below is the routine's own. The startup home has
# its own section at the end of this file.
auto.home_on_startup = False
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
# Anchored to the clock rather than written as 00:00-23:59. within_window
# treats a non-wrapping window as start <= now < stop, so that one leaves the
# minute 23:59 outside itself -- and this test failed for that minute every
# day. A window that wraps past midnight has no such gap: a start five minutes
# ago and a stop an hour ahead contains now whatever the time is.
_now = datetime.now()
auto.set_quiet_hours(
    True,
    (_now - timedelta(minutes=5)).time().isoformat(timespec="minutes"),
    (_now + timedelta(hours=1)).time().isoformat(timespec="minutes"),
)
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


# --- the startup home ---
#
# Until the arm is homed Klipper reports a position relative to wherever the
# carriage happened to power up, so every saved plant coordinate is wrong by an
# unknown amount and watering is refused outright. Without this the first home
# is up to a whole idle-motion interval away.

auto, klip = build(klip=Klip(homed=False))
auto.set_idle_motion(False)
assert klip.homes == 0, "homed during construction, before anything held the lock"
print("ok: nothing homes while the service is still starting up")

auto.tick()
assert klip.homes == 1, klip.homes
assert klip.gcode == [], "ran a routine as well as homing"
print("ok: the first tick homes, and only homes")

for _ in range(5):
    auto.tick()
assert klip.homes == 1, f"homed {klip.homes} times, so it is homing every tick"
print("ok: and does not home again on every tick after that")

# Off means off.
auto, klip = build(klip=Klip(homed=False))
auto.set_idle_motion(False, home_on_startup=False)
for _ in range(3):
    auto.tick()
assert klip.homes == 0, klip.homes
print("ok: switched off, it never homes by itself")

# Held during quiet hours like every other unattended movement -- the arm is
# the noisy part whether or not it was asked nicely.
auto, klip = build(klip=Klip(homed=False))
auto.set_idle_motion(False)
auto.snooze_watering(2)
auto.tick()
assert klip.homes == 0, "homed through a snooze"
print("ok: a snooze defers the startup home")

# And the deferral is not a cancellation: the flag is left clear so the next
# tick after the window closes does it, rather than waiting for a restart.
auto.cancel_snooze()
auto.tick()
assert klip.homes == 1, klip.homes
print("ok: once the snooze lifts it homes, rather than waiting for a restart")


# --- a board that cannot home ---
#
# Retrying every second would fill the log and hold the lock against real work,
# and a board that cannot home will not start being able to on the next tick.

class Broken(Klip):
    def home_gantry(self):
        self.homes += 1
        raise RuntimeError("no endstop")


broken = Broken(homed=False)
auto = GreenThumbAutomation(
    Hub(), broken, Nul(), Nul(), history=temp_store(), state_path=temp_state()
)
auto.set_idle_motion(False)
for _ in range(4):
    auto.tick()
assert broken.homes == 1, f"retried a failing home {broken.homes} times"
print("ok: a home that raises is tried once, not every tick")


# --- the choice persists ---

shared = temp_state()
auto = GreenThumbAutomation(
    Hub(), Klip(), Nul(), Nul(), history=temp_store(), state_path=shared
)
auto.set_idle_motion(True, 60, home_on_startup=False)
again = GreenThumbAutomation(
    Hub(), Klip(), Nul(), Nul(), history=temp_store(), state_path=shared
)
assert again.home_on_startup is False
assert again.idle_motion_status()["home_on_startup"] is False
print("ok: the startup-home choice survives a restart")


print("\nall idle motion checks passed")
