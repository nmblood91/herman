"""Watering on a target share of available water.

A pot's moisture is the share of its soil's available water that is left:
100% at the soil profile's field capacity reading, 0% at its wilting point
reading. A plant's target is on that same scale, so a pot is watered once its
reading drops to the target, and one target means the same thirst in any
soil. Targets used to be % VWC, which only fitted the soil they were written
for: 25% VWC was more than the coarse mix can hold at all.

The fixture's pots read 800 at field capacity and 320 at wilting point, so a
raw count r is (r - 320) / 480 * 100 % soil water.
"""

import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import care, soil_library, state
from greenthumb.config import settings
from greenthumb.hardware.soil_sensors import unavailable_sample
from greenthumb.services.automation import GreenThumbAutomation
from tests.helpers import CalibrationSurface, give_every_plant_soil, temp_state, temp_store

settings.auto_watering_enabled = False
settings.auto_patrol_enabled = False


class Klip:
    def status(self): return {"ok": True, "position": 0.0, "homed": True, "max_x": 890.0}
    def __getattr__(self, n): return lambda *a, **k: {"ok": True}


class Hub(CalibrationSurface):
    addresses = [0x36, 0x37, 0x38, 0x39]
    def read_one(self, a): return unavailable_sample(a)


class Nul:
    mode = "off"; color = (0, 0, 0); brightness = 0
    def __getattr__(self, n): return lambda *a, **k: {}


def build(soil="Rich & Retentive Mix"):
    return give_every_plant_soil(GreenThumbAutomation(
        Hub(), Klip(), Nul(), Nul(), history=temp_store(), state_path=temp_state(),
    ), soil=soil)


def raw_at(percent):
    """The raw count that reads as this % soil water in the fixture."""
    return 320 + percent / 100 * 480


def reading(auto, plant, raw):
    window = auto._history[plant.sensor_address]
    window.clear()
    window.extend([float(raw)] * window.maxlen)


# --- watered at the target, not before ---

auto = build()
pot = auto.plants[0]
auto.update_target_available(pot.plant_id, 40)
reading(auto, pot, raw_at(39.5))
assert auto.thirsty(pot), auto.percent_for_plant(pot)
reading(auto, pot, raw_at(40.5))
assert not auto.thirsty(pot), auto.percent_for_plant(pot)
print("ok: thirsty once the soil water drops to the target, not a point before")

status = next(p for p in auto.get_overview()["plants"] if p["plant_id"] == pot.plant_id)
assert status["target_available"] == 40, status
assert round(status["moisture_percent"]) == 40 and status["moisture_level"] == "Medium-Dry", status
assert status["thirsty"] is False, status
for gone in ("moisture_vwc", "moisture_band", "target_problem"):
    assert gone not in status, f"the overview still reports {gone}"
print("ok: the overview gives the gauge, its word and the target, all on one scale")


# --- one target, the same thirst in every soil ---

# The old VWC scale could not do this: 90% VWC is beyond every mix here, and
# 10% VWC is below the Rich mix's wilting point. As a share of available
# water, both ends are reachable in every soil.
for soil in soil_library.LIBRARY:
    auto = build(soil.name)
    pot = auto.plants[0]
    for target in (care.MIN_TARGET_AVAILABLE, care.DEFAULT_TARGET_AVAILABLE, care.MAX_TARGET_AVAILABLE):
        auto.update_target_available(pot.plant_id, target)
        reading(auto, pot, raw_at(target - 1))
        assert auto.thirsty(pot), (soil.name, target)
        reading(auto, pot, raw_at(target + 1))
        assert not auto.thirsty(pot), (soil.name, target)
print(f"ok: targets from {care.MIN_TARGET_AVAILABLE} to {care.MAX_TARGET_AVAILABLE}% work in all three soils")


# --- the soil's % VWC figures are only needed to estimate wilting point ---

auto = build()
pot = auto.plants[0]
state.save_soil("Rich & Retentive Mix", {"field_capacity_vwc": None, "wilting_point_vwc": None}, auto._state_path)
auto._sync_scales()
auto.update_target_available(pot.plant_id, 40)
reading(auto, pot, raw_at(30))
assert auto.thirsty(pot), "a measured wilting point should be enough without the % figures"
print("ok: with a measured wilting point, a soil needs no % VWC figures to water")

state.save_soil("Rich & Retentive Mix", {"wilting_point_raw": None}, auto._state_path)
auto._sync_scales()
assert auto.percent_for_plant(pot) < 0 and not auto.thirsty(pot)
assert "wilting point" in auto.scale_problem(pot), auto.scale_problem(pot)
print("ok: with neither, there is no scale, nothing waters, and the card says why")


# --- bad targets are refused ---

auto = build()
pot = auto.plants[0]
auto.update_target_available(pot.plant_id, 40)
for bad in (0, 9, 91, 100, 12.5, "40", None, True):
    try:
        auto.update_target_available(pot.plant_id, bad)
    except ValueError:
        continue
    raise AssertionError(f"accepted target {bad!r}")
assert pot.target_available == 40
print("ok: a target outside 10-90%, or not a whole number, is refused and the old one kept")

print("\nall watering target checks passed")
