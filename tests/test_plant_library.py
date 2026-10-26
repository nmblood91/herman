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
    assert care.check_target_available(plant.target_available) == plant.target_available, plant.name
    assert plant.water_level in care.WATER_LEVELS, (plant.name, plant.water_level)
    assert plant.light_level in care.BRIGHTNESS_FOR, (plant.name, plant.light_level)
    assert 8 <= plant.light_hours <= 15, (plant.name, plant.light_hours)
    assert plant.preferred_soil in soils, (plant.name, plant.preferred_soil)
    assert plant.category, plant.name
print(f"ok: all {len(LIBRARY)} plants have a usable target, light and soil profile")

names = [plant.name for plant in LIBRARY]
# The newer table's 15 herbs, 34 vegetables and 6 bulbs; the vegetables gain
# the older table's tomatoes, strawberries, spinach and chard; then its 21
# houseplants and 18 succulents and epiphytes.
counts = {}
for plant in LIBRARY:
    counts[plant.category] = counts.get(plant.category, 0) + 1
assert counts == {
    "Culinary Herbs & Kitchen Greens": 15,
    "Indoor Vegetables & Crops": 39,
    "Flowering Bulbs & Ornamentals": 6,
    "Common Indoor Houseplants & Foliage": 21,
    "Succulents, Cacti & Epiphytes": 18,
}, counts
assert len(set(name.casefold() for name in names)) == len(names), names
print(f"ok: {len(names)} plants in five categories, names distinct")

# A plant on both tables appears once, under the newer table's name.
for old_name in ("Bush Beans", "Spring Onion / Green Onion", "Dwarf Zucchini / Squash"):
    assert old_name not in names, old_name
print("ok: plants renamed in the newer table are not listed twice")

# Pinned, one per soil profile. The targets are the tables' % VWC converted
# through each plant's preferred soil: Sweet Basil's 28% VWC in Rich &
# Retentive (FC 50, WP 17.5) is 32% available water, Lavender's 12% in
# Fast-Draining (FC 25, WP 8) is 24%, the Staghorn Fern's 9% in Ultra-Coarse
# (FC 15, WP 4) is 45%, and the Snake Plant's 9% in Fast-Draining came out at
# 6% and was raised to the 10% floor.
by_name = {plant.name: plant for plant in LIBRARY}
for name, expected in (
    ("Sweet Basil", ("Rich & Retentive Mix", 13, "High", "Dry", 32)),
    ("Lavender", ("Fast-Draining Mix", 14, "Intense", "Very Dry", 24)),
    ("Snake Plant (Sansevieria Trifasciata)", ("Fast-Draining Mix", 8, "Low", "Ultra Dry", 10)),
    ("Staghorn Fern (Platycerium)", ("Ultra-Coarse Epiphytic Mix", 11, "Medium", "Medium-Dry", 45)),
):
    plant = by_name[name]
    got = (plant.preferred_soil, plant.light_hours, plant.light_level, plant.water_level, plant.target_available)
    assert got == expected, (name, got)
assert by_name["Sweet Corn (Dwarf)"].light_brightness == 100
assert by_name["Peace Lily (Spathiphyllum)"].light_brightness == 25
assert by_name["Spinach"].category == "Indoor Vegetables & Crops"
print("ok: spot checks match the source tables, and intensities map to brightness")

# The four whose VWC targets sat outside their own soil were chosen by hand.
# The Christmas cactus's 21% VWC was more than its 15% soil holds, so it was
# never watered automatically; the others were below their wilting point.
assert by_name["Christmas / Thanksgiving Cactus (Schlumbergera)"].target_available == 35
for name in ("Peperomia Obtusifolia", "Desert Cactus (Mammillaria)", "Prickly Pear Cactus (Opuntia)"):
    assert by_name[name].target_available == 10, (name, by_name[name].target_available)
print("ok: the four targets that never fitted their soil keep their chosen values")

# Habanero's 20% VWC converts to 8%, under the lowest target allowed.
assert by_name["Habanero Pepper"].target_available == 10
# The fast-draining bulbs keep their converted figure even though the table's
# words call them Medium-Dry: 18% VWC is most of what that soil holds.
assert by_name["Hyacinth"].target_available == 59
assert by_name["Hyacinth"].water_level == "Medium-Wet"
print("ok: Habanero is raised to the floor, and the bulbs keep their measured figure")


# --- installing ---

path = temp_state()
outcome = plant_library.install(path=path)
assert set(outcome.values()) == {"written"}, outcome
stored = state.load_profiles(path)
assert set(stored) == set(names), sorted(stored)
entry = {k: v for k, v in stored["Sweet Basil"].items() if k != "saved_at"}
assert entry == {
    "category": "Culinary Herbs & Kitchen Greens",
    "preferred_soil": "Rich & Retentive Mix",
    "target_available": 32,
    "watering_volume_ml": 100,
    "light_start_time": "07:00",
    "light_hours": 13,
    "light_brightness": 75,
    "notes": "",
}, entry
print("ok: installing writes every plant with all its fields, and no water level")

for name, entry in stored.items():
    assert "position_mm" not in entry, (name, entry)
print("ok: no rail position is stored, so loading one cannot move a pot")

# The important one: a tuned plant is not silently replaced.
state.save_profile("Sweet Basil", {"target_available": 33, "watering_volume_ml": 11}, path)
outcome = plant_library.install(path=path)
assert outcome["Sweet Basil"] == "kept", outcome
assert state.load_profiles(path)["Sweet Basil"]["target_available"] == 33, (
    "installing overwrote a plant the user had tuned"
)
print("ok: re-installing keeps your own numbers rather than replacing them")

state.save_profile("sweet corn (dwarf)", {"target_available": 12}, path)
outcome = plant_library.install(path=path)
assert outcome["Sweet Corn (Dwarf)"] == "kept", outcome
assert len(state.load_profiles(path)) == len(names), sorted(state.load_profiles(path))
print("ok: a differently capitalised entry still counts as yours")

outcome = plant_library.install(overwrite=True, path=path)
assert set(outcome.values()) == {"written"}, outcome
restored = state.load_profiles(path)
assert restored["Sweet Basil"]["target_available"] == 32, restored["Sweet Basil"]
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
