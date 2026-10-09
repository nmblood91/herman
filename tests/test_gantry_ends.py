"""Sending the carriage to either end of the rail.

The interesting part is where "right" comes from. It is resolved from Klipper's
own axis_maximum rather than passed in by the caller, so the rail length has
one source -- a browser left open across a re-measure cannot send a stale
target, and neither can a .env that drifted from printer.cfg.
"""

import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb.config import settings
from greenthumb.hardware.soil_sensors import unavailable_sample
from greenthumb.services.automation import GreenThumbAutomation, HardwareBusyError
from tests.helpers import temp_state, temp_store

settings.auto_watering_enabled = False
settings.idle_motion_enabled = False

TRAVEL = 890.0


class Klip:
    def __init__(self, max_x=TRAVEL):
        self.max_x = max_x
        self.absolute_moves = []

    def status(self):
        return {"ok": True, "position": 0.0, "homed": True, "max_x": self.max_x}

    def move_gantry_absolute(self, position_mm):
        self.absolute_moves.append(position_mm)
        return {"ok": True}

    def move_gantry_relative(self, distance_mm):
        return {"ok": True}

    def home_gantry(self):
        return {"ok": True}

    def send_gcode(self, gcode, timeout=5.0):
        return {"ok": True}

    def water_supply_present(self):
        return True


class Hub:
    addresses = [0x36, 0x37, 0x38, 0x39]
    def read_one(self, a): return unavailable_sample(a)


class Nul:
    mode = "off"; color = (0, 0, 0); brightness = 0
    def __getattr__(self, n): return lambda *a, **k: {}


def build(klip):
    return GreenThumbAutomation(
        Hub(), klip, Nul(), Nul(), history=temp_store(), state_path=temp_state()
    )


# --- the two ends ---

klip = Klip()
auto = build(klip)
assert auto.move_gantry_to_end("left")["ok"] is True
assert klip.absolute_moves == [0.0], klip.absolute_moves
print("ok: left goes to 0")

klip = Klip()
auto = build(klip)
assert auto.move_gantry_to_end("right")["ok"] is True
assert klip.absolute_moves == [TRAVEL], klip.absolute_moves
print(f"ok: right goes to Klipper's axis_maximum, {TRAVEL}")

# The rail length is read per call, not captured once, so a re-measured rail
# takes effect without restarting anything.
klip = Klip(max_x=600.0)
auto = build(klip)
auto.move_gantry_to_end("right")
assert klip.absolute_moves == [600.0], klip.absolute_moves
print("ok: a shorter rail is followed, so the target is never stale")

# Absolute, not relative. A relative move would stack: pressing "all the way
# right" twice would try to go to 1780 on an 890 mm rail.
klip = Klip()
auto = build(klip)
auto.move_gantry_to_end("right")
auto.move_gantry_to_end("right")
assert klip.absolute_moves == [TRAVEL, TRAVEL], klip.absolute_moves
print("ok: pressing it twice lands in the same place, not twice as far")


# --- bad input ---

for bad in ("up", "", "LEFTISH", "0", None):
    try:
        build(Klip()).move_gantry_to_end(bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"accepted {bad!r} as an end")
print("ok: anything that is not left or right is refused")

# Refused before the hardware is touched, so a typo cannot move the carriage.
klip = Klip()
try:
    build(klip).move_gantry_to_end("rigth")
except ValueError:
    assert klip.absolute_moves == [], "moved the gantry on a misspelled end"
print("ok: a refused end moves nothing")


# --- it queues behind nothing ---

klip = Klip()
auto = build(klip)
auto._hardware_lock.acquire()
try:
    auto.move_gantry_to_end("left")
except HardwareBusyError:
    assert klip.absolute_moves == [], "moved while the hardware was busy"
    print("ok: refused while the hardware is busy rather than queued")
else:
    raise AssertionError("expected HardwareBusyError")
finally:
    auto._hardware_lock.release()

assert auto.move_gantry_to_end("left")["ok"] is True
assert auto._hardware_lock.acquire(blocking=False), "the move kept the lock"
auto._hardware_lock.release()
print("ok: the lock is released afterwards")

print("\nall gantry end checks passed")
