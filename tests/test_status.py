"""The status bar's message: one line saying what the planter is doing.

Ordering is the whole design here. Several of these conditions are true at
once in normal operation, and the bar shows one -- so the tests pin which one
wins, not merely that each can be produced.
"""

import sys, types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb.config import settings
from greenthumb.models import SensorSample
from greenthumb.services.automation import GreenThumbAutomation
from tests.helpers import temp_state, temp_store


class Klip:
    def __init__(self, ok=True, homed=True): self.ok, self.homed = ok, homed
    def status(self): return {"ok": self.ok, "homed": self.homed, "position": 0.0}
    def __getattr__(self, n): return lambda *a, **k: {"ok": True}


class Nul:
    mode = "off"; color = (0, 0, 0); brightness = 0
    def __getattr__(self, n): return lambda *a, **k: {}


class Hub:
    addresses = [0x36, 0x37, 0x38, 0x39]
    raw_dry, raw_wet = 320, 1020
    calibration = {}
    def __init__(self, dead=(), raw=900.0): self.dead, self.raw = set(dead), raw
    def read_one(self, a):
        if a in self.dead:
            return SensorSample(a, -1.0, -1.0, -1.0)
        return SensorSample(a, 0.0, self.raw, 21.0)
    def raw_to_percent(self, raw, address=None):
        return round(max(0.0, min((raw - 320) / 700 * 100, 100.0)), 1)


def build(hub=None, klip=None):
    return GreenThumbAutomation(
        hub or Hub(), klip or Klip(), Nul(), Nul(),
        history=temp_store(), state_path=temp_state(),
    )


def settled(auto):
    for _ in range(settings.moisture_window_size):
        auto._poll_sensors()
    return auto


settings.auto_watering_enabled = True

# --- a fresh planter is not a broken one ---

auto = build()
state = auto.system_status()
assert state["level"] == "info", state
assert "Getting to know" in state["message"], state
print("ok: before the first poll it says it is getting to know the plants")

# The regression this guards: _latest is pre-seeded with unavailable samples,
# so "every reading is -1" is also what one second after boot looks like.
assert "No sensors" not in state["message"], state
print("ok: a fresh boot is not reported as dead hardware")


# --- normal operation ---

auto = settled(build())
assert auto.system_status()["level"] == "ok"
print("ok: settled and wet reads as ok")

auto = settled(build(Hub(raw=400.0)))
state = auto.system_status()
assert state["level"] == "ok" and "drink" in state["message"], state
print("ok: dry plants are named as due a drink, not raised as a fault")


# --- faults, in priority order ---

auto = settled(build(Hub(dead=[0x38])))
state = auto.system_status()
assert state["level"] == "attention" and "Plant 3" in state["message"], state
print("ok: one unplugged probe names that plant")

auto = settled(build(Hub(dead=[0x36, 0x37, 0x38, 0x39])))
assert auto.system_status()["level"] == "problem"
print("ok: every probe silent points at the hub instead of four plants")

auto = settled(build(klip=Klip(homed=False)))
assert "homed" in auto.system_status()["message"]
print("ok: an unhomed arm is reported, since nothing can be watered")

auto = settled(build(klip=Klip(ok=False)))
state = auto.system_status()
assert state["level"] == "problem" and "motion board" in state["message"]
print("ok: a lost motion board outranks everything below it")


# --- running out of water ---

auto = settled(build())
auto._delivery_failures = 1
state = auto.system_status()
assert state["level"] == "attention" and "did not reach" in state["message"], state
print("ok: one missed dose suggests checking the water and the line")

auto._delivery_failures = 3
state = auto.system_status()
assert state["level"] == "problem" and "reservoir" in state["message"].lower(), state
print("ok: a run of missed doses calls out the reservoir")

# A dose that lands clears it: refilling the tank should not need a restart.
auto._delivery_failures = 0
assert auto.system_status()["level"] == "ok"
print("ok: a successful dose clears the empty-reservoir state")

# An empty reservoir outranks a merely unhomed arm.
auto = settled(build(klip=Klip(homed=False)))
auto._delivery_failures = 2
assert "reservoir" in auto.system_status()["message"].lower()
print("ok: an empty reservoir outranks an unhomed arm")


# --- paused states are information, not faults ---

auto = settled(build())
auto.snooze_watering(2)
state = auto.system_status()
assert state["level"] == "info" and "paused" in state["message"], state
print("ok: a snooze reads as paused rather than broken")

auto.cancel_snooze()
settings.auto_watering_enabled = False
state = auto.system_status()
assert state["level"] == "info" and "Watching only" in state["message"], state
print("ok: automatic watering switched off says so plainly")
settings.auto_watering_enabled = True

print("\nall status checks passed")
