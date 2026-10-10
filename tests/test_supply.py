"""Delivery verification: the outlet sensor confirms a dose, it does not gate one.

The sensor sits on the falling leg of the outlet tube, which drains between
doses. It therefore reads dry whenever the pump is idle, and a pre-check would
refuse every watering. These tests pin the behaviour that replaced that gate.
"""

import sys, types
sys.modules["smbus2"] = types.ModuleType("smbus2")

import time

import greenthumb.services.automation as automation_module
from greenthumb.config import settings
from greenthumb.models import SensorSample
from tests.helpers import CalibrationSurface, give_every_plant_soil, temp_state, temp_store
from greenthumb.services.automation import GreenThumbAutomation

settings.auto_watering_enabled = True
# No point waiting for a line to fill that no real pump is filling.
settings.delivery_check_delay_seconds = 0.0
# A real dose runs for a minute and is polled every second. Compress both so
# the watcher still gets several looks per dose without the suite taking one.
automation_module.DELIVERY_POLL_SECONDS = 0.01
DOSE_SECONDS = 0.2


class Hub(CalibrationSurface):
    addresses = [0x36, 0x37, 0x38, 0x39]
    def raw_to_percent(self, raw, address=None): return 0.0
    def read_one(self, a): return SensorSample(a, 0.0, 350.0, 22.0)

class Pump:
    flow_ml_per_second = 1.67
    def __init__(self): self.calls = []; self.is_running = False
    def deliver_ml(self, v=100, **k):
        self.calls.append(v)
        # Blocks like the real one, which does not return until Klipper
        # finishes the dwell. An instant dose would only ever be polled once.
        time.sleep(DOSE_SECONDS)

class Klip:
    """`supply` may be a value, or a list consumed one read at a time."""
    def __init__(self, supply=True):
        self.supply = supply
        self.moves = []
        self.reads = 0
    def water_supply_present(self):
        self.reads += 1
        if isinstance(self.supply, list):
            return self.supply.pop(0) if self.supply else False
        return self.supply
    def move_gantry_absolute(self, p): self.moves.append(p); return {"ok": True}
    def status(self): return {"ok": True}

class Leds:
    mode = "schedule"
    def set_plant_segments(self, s): pass
    def status(self): return {"mode": "schedule"}


def build(supply=True):
    pump, klip, store = Pump(), Klip(supply), temp_store()
    auto = give_every_plant_soil(
        GreenThumbAutomation(Hub(), klip, pump, Leds(), history=store, state_path=temp_state())
    )
    return auto, pump, klip, store


# sensor off: never queried, watering unaffected, no verdict recorded
settings.water_sensor_enabled = False
auto, pump, klip, store = build(supply=False)
klip.water_supply_present = lambda: (_ for _ in ()).throw(AssertionError("queried while disabled"))
result = auto.water_plant("plant_1")
assert result["status"] == "ok"
assert result["delivered"] is None, result
assert pump.calls == [100], "disabled sensor blocked watering"
print("ok: sensor disabled -> not queried, watering proceeds, delivered is None")

settings.water_sensor_enabled = True

# water reaches the outlet
auto, pump, klip, store = build(supply=True)
result = auto.water_plant("plant_1")
assert result["status"] == "ok"
assert result["delivered"] is True, result
assert store.waterings(1)[0]["delivered"] is True
print("ok: wet outlet -> delivered True, recorded")

# nothing reaches the outlet: the dose still runs, and is flagged
auto, pump, klip, store = build(supply=False)
result = auto.water_plant("plant_1")
assert result["status"] == "ok", "a failed delivery must not read as a refused dose"
assert result["delivered"] is False, result
assert pump.calls == [100], "dry outlet stopped the pump; it must not gate"
# Read rather than hardcoded: this used to assert 150 and broke when the
# default moved with the measured rail length. What matters is that the
# gantry went to the plant, not what that number happens to be.
expected = next(p.position_mm for p in auto.plants if p.plant_id == "plant_1")
assert klip.moves == [expected], "dry outlet stopped the gantry; it must not gate"
assert store.waterings(1)[0]["delivered"] is False
print("ok: dry outlet -> dose runs anyway, recorded as delivered False")

# a failed delivery still consumes the cooldown: the pump did run
auto, pump, klip, store = build(supply=False)
auto.water_plant("plant_1")
assert "plant_1" in auto._last_watered, "a dose that ran must start a cooldown"
print("ok: a failed delivery still starts the cooldown, because water may have moved")

# unreadable sensor is unknown, not failed
auto, pump, klip, store = build(supply=None)
result = auto.water_plant("plant_1")
assert result["delivered"] is None, result
assert pump.calls == [100]
assert store.waterings(1)[0]["delivered"] is None
print("ok: unreadable sensor -> delivered None, distinct from a failure")

# dry at first then wet: the line takes time to fill, so one dry read is not a verdict
auto, pump, klip, store = build(supply=[False, False, True])
result = auto.water_plant("plant_1")
assert result["delivered"] is True, result
assert klip.reads >= 3, klip.reads
print("ok: an initially dry line that fills reads as delivered")

# the control loop waters regardless of the outlet state
auto, pump, klip, store = build(supply=False)
for _ in range(12):
    auto.tick()
assert pump.calls, "control loop was gated by a dry outlet"
print("ok: the control loop is not gated by the outlet sensor")

# a gantry failure still blocks, and records nothing
auto, pump, klip, store = build(supply=True)
klip.move_gantry_absolute = lambda p: {"ok": False, "error": "not homed"}
result = auto.water_plant("plant_1")
assert result["status"] == "error", result
assert pump.calls == [], "pumped without reaching the plant"
assert store.waterings(1) == [], "recorded a watering that never happened"
print("ok: a gantry failure still blocks the pump and records nothing")

# overview reports the last dose, not the live line state
auto, pump, klip, store = build(supply=False)
assert auto.get_overview()["delivery"]["last"] is None
auto.water_plant("plant_2")
last = auto.get_overview()["delivery"]["last"]
assert last["plant_id"] == "plant_2" and last["delivered"] is False, last
print("ok: overview reports the last dose's verdict")

print("\nall delivery verification checks passed")
