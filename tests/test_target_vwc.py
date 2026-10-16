"""Watering on a target % VWC.

A plant is watered once its pot's soil dries to its target volumetric water
content. The pot reads plant-available water between its soil profile's
wilting point and field capacity readings; the soil profile's two % figures
place that on the VWC scale the target is written in.

The fixture's pots are in Rich & Retentive Mix (50% at field capacity, 17.5%
at wilting point) with readings 800 and 320, so a raw count r is
17.5 + (r - 320) / 480 * 32.5 % VWC.
"""

import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import state
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


def build():
    return give_every_plant_soil(GreenThumbAutomation(
        Hub(), Klip(), Nul(), Nul(), history=temp_store(), state_path=temp_state(),
    ))


def vwc_at(raw):
    return 17.5 + (raw - 320) / 480 * 32.5


def reading(auto, plant, raw):
    window = auto._history[plant.sensor_address]
    window.clear()
    window.extend([float(raw)] * window.maxlen)


# --- the pot's moisture as % VWC ---

auto = build()
pot = auto.plants[0]
reading(auto, pot, 560)
assert auto.vwc_for_plant(pot) == round(vwc_at(560), 1), auto.vwc_for_plant(pot)
reading(auto, pot, 800)
assert auto.vwc_for_plant(pot) == 50.0
reading(auto, pot, 200)  # drier than wilting point: clamped, not below it
assert auto.vwc_for_plant(pot) == 17.5
print("ok: a reading is placed on the soil's VWC scale, field capacity to wilting point")


# --- watered at the target, not before ---

auto.update_target_vwc(pot.plant_id, 28)
reading(auto, pot, 470)          # about 27.7%
assert vwc_at(470) < 28 and auto.thirsty(pot), auto.vwc_for_plant(pot)
reading(auto, pot, 480)          # about 28.3%
assert vwc_at(480) > 28 and not auto.thirsty(pot), auto.vwc_for_plant(pot)
print("ok: thirsty once the soil dries to the target, not a point before")

status = next(p for p in auto.get_overview()["plants"] if p["plant_id"] == pot.plant_id)
assert status["target_vwc"] == 28 and status["moisture_vwc"] == round(vwc_at(480), 1), status
assert status["thirsty"] is False and status["target_problem"] is None, status
print("ok: the overview reports the moisture, the target and the verdict")


# --- a target the soil cannot reach ---

auto.update_target_vwc(pot.plant_id, 50)  # Rich & Retentive holds 50% at most
for other in auto.plants:
    reading(auto, other, 700)
reading(auto, pot, 330)
assert not auto.thirsty(pot), "a target the soil can never dry past watered anyway"
assert "held" in auto.target_problem(pot), auto.target_problem(pot)
auto.auto_watering_enabled = True
assert "wetter than its soil profile holds" in auto.system_status()["message"], auto.system_status()
auto.auto_watering_enabled = False
print("ok: a target at or above field capacity is held and flagged, not watered constantly")


# --- a target below wilting point ---

auto.update_target_vwc(pot.plant_id, 9)
assert auto.effective_target(pot) == 18.5, auto.effective_target(pot)
assert "18.5" in auto.target_problem(pot), auto.target_problem(pot)
reading(auto, pot, 320)          # at wilting point
assert auto.thirsty(pot), "a pot at wilting point with a target below it was never watered"
reading(auto, pot, 340)          # about 18.9%
assert not auto.thirsty(pot)
print("ok: a target below wilting point waters just above it, and says so")


# --- no % figures, no judgement ---

state.save_soil("Rich & Retentive Mix", {"field_capacity_vwc": None, "wilting_point_vwc": None}, auto._state_path)
auto.update_target_vwc(pot.plant_id, 28)
reading(auto, pot, 330)
assert auto.vwc_for_plant(pot) is None
assert not auto.thirsty(pot)
assert "% VWC" in auto.scale_problem(pot), auto.scale_problem(pot)
print("ok: a soil profile without its % figures cannot place a target, so nothing waters")


# --- bad targets are refused ---

for bad in (0, 61, 12.5, "28", None, True):
    try:
        auto.update_target_vwc(pot.plant_id, bad)
    except ValueError:
        continue
    raise AssertionError(f"accepted target {bad!r}")
assert pot.target_vwc == 28
print("ok: an unusable target is refused and the old one kept")

print("\nall target VWC checks passed")
