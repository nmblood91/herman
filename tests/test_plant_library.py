"""The plant library a planter ships with.

The numbers are the source table's, so what is worth testing is that every one
of them is something a pot can use, that a few are pinned against the table,
and that installing never overwrites a plant somebody has already tuned.
"""

import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import care, plant_library, soil_library, state
from greenthumb.plant_library import LIBRARY
from tests.helpers import temp_state


# --- every field is usable ---

soils = {soil.name: soil for soil in soil_library.LIBRARY}
for plant in LIBRARY:
    assert care.check_target_vwc(plant.target_vwc) == plant.target_vwc, plant.name
    assert plant.water_level in care.WATER_LEVELS, (plant.name, plant.water_level)
    assert plant.light_level in care.BRIGHTNESS_FOR, (plant.name, plant.light_level)
    assert 8 <= plant.light_hours <= 15, (plant.name, plant.light_hours)
    assert plant.preferred_soil in soils, (plant.name, plant.preferred_soil)
    assert plant.category, plant.name
print(f"ok: all {len(LIBRARY)} plants have a usable target, light and soil profile")

names = [plant.name for plant in LIBRARY]
# 14 vegetables, 17 herbs and greens, 21 houseplants, 18 succulents and epiphytes.
counts = {}
for plant in LIBRARY:
    counts[plant.category] = counts.get(plant.category, 0) + 1
assert list(counts.values()) == [14, 17, 21, 18], counts
assert len(set(name.casefold() for name in names)) == len(names), names
print(f"ok: {len(names)} plants in four categories, names distinct")

# Pinned against the source table, one per soil profile.
by_name = {plant.name: plant for plant in LIBRARY}
for name, expected in (
    ("Cherry Tomato", (soil_library.LIBRARY[0].name, 15, "Intense", "Medium", 28)),
    ("Snake Plant (Sansevieria Trifasciata)", ("Fast-Draining Mix", 8, "Low", "Very Dry", 9)),
    ("Staghorn Fern (Platycerium)", ("Ultra-Coarse Epiphytic Mix", 11, "Medium", "Medium-Dry", 9)),
):
    plant = by_name[name]
    got = (plant.preferred_soil, plant.light_hours, plant.light_level, plant.water_level, plant.target_vwc)
    assert got == expected, (name, got)
assert by_name["Cherry Tomato"].light_brightness == 100
assert by_name["Peace Lily (Spathiphyllum)"].light_brightness == 25
print("ok: spot checks match the source table, and intensities map to brightness")

# Which targets do not fit their preferred soil's range. Pinned so the list
# cannot grow unnoticed: each of these is flagged on the pot's card.
wetter_than_soil, at_or_below_wilting = [], []
for plant in LIBRARY:
    soil = soils[plant.preferred_soil]
    if plant.target_vwc >= soil.field_capacity_vwc:
        wetter_than_soil.append(plant.name)
    elif plant.target_vwc <= soil.wilting_point_vwc:
        at_or_below_wilting.append(plant.name)
assert wetter_than_soil == ["Christmas / Thanksgiving Cactus (Schlumbergera)"], wetter_than_soil
assert at_or_below_wilting == [
    "Peperomia Obtusifolia",
    "Desert Cactus (Mammillaria)",
    "Prickly Pear Cactus (Opuntia)",
], at_or_below_wilting
print("ok: the targets outside their soil's range are exactly the known four")


# --- installing ---

path = temp_state()
outcome = plant_library.install(path=path)
assert set(outcome.values()) == {"written"}, outcome
stored = state.load_profiles(path)
assert set(stored) == set(names), sorted(stored)
entry = {k: v for k, v in stored["Sweet Basil"].items() if k != "saved_at"}
assert entry == {
    "category": "Culinary Herbs & Leafy Greens",
    "preferred_soil": "Rich & Retentive Mix",
    "target_vwc": 28,
    "water_level": "Medium",
    "watering_volume_ml": 100,
    "light_start_time": "07:00",
    "light_hours": 13,
    "light_brightness": 75,
    "notes": "",
}, entry
print("ok: installing writes every plant with all its fields")

for name, entry in stored.items():
    assert "position_mm" not in entry, (name, entry)
print("ok: no rail position is stored, so loading one cannot move a pot")

# The important one: a tuned plant is not silently replaced.
state.save_profile("Sweet Basil", {"target_vwc": 33, "watering_volume_ml": 11}, path)
outcome = plant_library.install(path=path)
assert outcome["Sweet Basil"] == "kept", outcome
assert state.load_profiles(path)["Sweet Basil"]["target_vwc"] == 33, (
    "installing overwrote a plant the user had tuned"
)
print("ok: re-installing keeps your own numbers rather than replacing them")

state.save_profile("aloe vera", {"target_vwc": 12}, path)
outcome = plant_library.install(path=path)
assert outcome["Aloe Vera"] == "kept", outcome
assert len(state.load_profiles(path)) == len(names), sorted(state.load_profiles(path))
print("ok: a differently capitalised entry still counts as yours")

outcome = plant_library.install(overwrite=True, path=path)
assert set(outcome.values()) == {"written"}, outcome
restored = state.load_profiles(path)
assert restored["Sweet Basil"]["target_vwc"] == 28, restored["Sweet Basil"]
assert len(restored) == len(names), sorted(restored)
print("ok: --overwrite replaces them, and does not leave a stray duplicate behind")


# --- light windows ---

from datetime import time

assert care.light_stop(time(7, 0), 15) == time(22, 0)
assert care.light_stop(time(18, 0), 12) == time(6, 0)
assert care.light_on(time(21, 59), time(7, 0), 15) is True
assert care.light_on(time(22, 0), time(7, 0), 15) is False
assert care.light_on(time(6, 59), time(7, 0), 15) is False
assert care.light_on(time(2, 0), time(18, 0), 12) is True, "past midnight"
assert care.light_on(time(12, 0), time(18, 0), 12) is False
assert care.light_on(time(3, 0), time(7, 0), 24) is True
assert care.light_on(time(12, 0), time(7, 0), 0) is False
print("ok: the stop time is start plus hours, wrapping past midnight")


# --- the CLI ---

assert plant_library.main([]) == 0
print("ok: listing the library exits cleanly")

print("\nall plant library checks passed")
