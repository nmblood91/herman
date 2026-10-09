"""The soil library, and the soil recorded against each plant.

A soil exists to supply one number the bands need: where wilting point sits as
a fraction of field capacity. That ratio is the only thing that transfers
between pots -- the absolute water contents do not convert into raw sensor
counts -- so the tests are mostly about that ratio being usable, and about the
"unknown" case staying distinguishable from a real answer.
"""

import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import soil_library, state
from greenthumb.config import settings
from greenthumb.hardware.soil_sensors import unavailable_sample
from greenthumb.services.automation import GreenThumbAutomation
from greenthumb.soil_library import LIBRARY
from tests.helpers import temp_state, temp_store

settings.auto_watering_enabled = False
settings.idle_motion_enabled = False


class Klip:
    def status(self): return {"ok": True, "position": 0.0, "homed": True, "max_x": 890.0}
    def water_supply_present(self): return True
    def __getattr__(self, n): return lambda *a, **k: {"ok": True}


class Hub:
    addresses = [0x36, 0x37, 0x38, 0x39]
    def read_one(self, a): return unavailable_sample(a)


class Nul:
    mode = "off"; color = (0, 0, 0); brightness = 0
    def __getattr__(self, n): return lambda *a, **k: {}


def build(path=None):
    return GreenThumbAutomation(
        Hub(), Klip(), Nul(), Nul(),
        history=temp_store(), state_path=path or temp_state(),
    )


# --- the figures are usable ---

for soil in LIBRARY:
    assert 0 < soil.wilting_point_vwc < soil.field_capacity_vwc, soil.name
    assert soil.available_points > 0, soil.name
    assert soil.note.strip(), f"{soil.name} has no explanation"
    # A ratio at either extreme would mean either no usable water or a window
    # so wide the soil holds nothing back, and neither is a real mix.
    assert 0.15 < soil.wilting_fraction < 0.75, (soil.name, soil.wilting_fraction)
print(f"ok: all {len(LIBRARY)} soils have a usable window and a sane ratio")

names = [soil.name for soil in LIBRARY]
assert len(set(n.casefold() for n in names)) == len(names), names
print(f"ok: names are distinct -> {', '.join(names)}")

# Ordered widest window first, which is the ordering that says something.
widths = [soil.available_points for soil in LIBRARY]
assert widths == sorted(widths, reverse=True), widths
assert LIBRARY[0].name == "Coco coir" and LIBRARY[-1].name == "Cactus / sandy mix"
print("ok: ordered widest usable window to narrowest")

# The published peat figure is what the band design rests on, so pin it: a
# quiet edit here would silently move every band.
peat = next(s for s in LIBRARY if s.name == "Peat potting mix")
assert 0.55 <= peat.wilting_fraction <= 0.60, peat.wilting_fraction
print(f"ok: peat wilting point stays at {peat.wilting_fraction*100:.0f}% of field capacity")


# --- the ratio helper ---

assert state.available_water_fraction({"field_capacity_vwc": 28, "wilting_point_vwc": 16}) is not None
# Unusable figures must come back None, not a number, or a band is computed
# from nonsense and nobody notices.
for bad in (
    None,
    {},
    {"field_capacity_vwc": 28},
    {"field_capacity_vwc": 10, "wilting_point_vwc": 20},   # wilting above capacity
    {"field_capacity_vwc": 28, "wilting_point_vwc": 28},   # no usable water
    {"field_capacity_vwc": 28, "wilting_point_vwc": 0},
    {"field_capacity_vwc": "28", "wilting_point_vwc": "16"},
    {"field_capacity_vwc": True, "wilting_point_vwc": True},
):
    assert state.available_water_fraction(bad) is None, bad
print("ok: unusable soil figures give None rather than a made-up ratio")


# --- installing ---

path = temp_state()
outcome = soil_library.install(path=path)
assert set(outcome.values()) == {"written"}, outcome
assert set(state.load_soils(path)) == set(names), sorted(state.load_soils(path))
print("ok: installing writes every soil")

state.save_soil("Peat potting mix", {"field_capacity_vwc": 33, "wilting_point_vwc": 19}, path)
outcome = soil_library.install(path=path)
assert outcome["Peat potting mix"] == "kept", outcome
assert state.load_soils(path)["Peat potting mix"]["field_capacity_vwc"] == 33
print("ok: re-installing keeps a mix you measured yourself")

state.save_soil("coco coir", {"field_capacity_vwc": 50, "wilting_point_vwc": 14}, path)
assert soil_library.install(path=path)["Coco coir"] == "kept"
assert len(state.load_soils(path)) == len(names), sorted(state.load_soils(path))
print("ok: a differently capitalised mix still counts as yours")

assert set(soil_library.install(overwrite=True, path=path).values()) == {"written"}
assert state.load_soils(path)["Peat potting mix"]["field_capacity_vwc"] == 28
print("ok: --overwrite restores the library figures")


# --- a plant's soil ---

shared = temp_state()
soil_library.install(path=shared)
auto = build(shared)
first, second = auto.plants[0].plant_id, auto.plants[1].plant_id

assert auto.get_plant(first).soil == "", "a plant started with a soil already set"
print("ok: a plant starts with no soil, which is distinct from a bad one")

auto.update_plant_soil(first, "peat potting mix")
assert auto.get_plant(first).soil == "Peat potting mix", auto.get_plant(first).soil
print("ok: setting a soil matches case-insensitively and stores the library's spelling")

# An unknown mix supplies no ratio, so storing it would read as "set" while
# behaving exactly like "not set".
for bad in ("Moon dust", "peat pottingmix"):
    try:
        auto.update_plant_soil(second, bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"accepted unknown soil {bad!r}")
assert auto.get_plant(second).soil == ""
print("ok: an unknown soil is refused rather than stored as a dead name")

auto.update_plant_soil(first, "")
assert auto.get_plant(first).soil == ""
print("ok: an empty name clears it, which is how you say the mix is unknown")


# --- it belongs to the pot, not to the saved plant ---

auto.update_plant_soil(first, "Coco coir")
auto.update_plant_soil(second, "Peat potting mix")
auto.update_plant_name(first, "Fern")
auto.save_plant_profile(first)
result = auto.apply_plant_profile(second, "Fern")

# The mix is physically in the pot, and loading a saved plant repots nothing.
# The two ways of being wrong here are not symmetrical: if the soil stays and
# you did repot, you pick the mix again from a dropdown you are looking at. If
# it travelled and you did not, the pot bands every reading against the wrong
# wilting point and waters to it, and nothing looks broken.
assert auto.get_plant(second).soil == "Peat potting mix", auto.get_plant(second).soil
print("ok: loading a saved plant leaves the pot's soil alone")

# Reported back, so the caller can say it was left rather than leave someone
# wondering whether the profile changed the mix.
assert result["soil"] == "Peat potting mix", result
print("ok: and the load reports the soil it did not touch")

# Not written into the entry at all, rather than written and then ignored.
assert "soil" not in state.load_profiles(shared)["Fern"], state.load_profiles(shared)["Fern"]
print("ok: soil is not saved into a plant in the first place")

# An entry saved while soil still travelled still has the key in it. The
# whitelist filters on read as well as write, so the old behaviour cannot come
# back for profiles saved up to now.
raw = state.load_state(shared)
raw["plant_profiles"]["Legacy"] = {
    "moisture_target": "dry",
    "watering_volume_ml": 50,
    "soil": "Cactus / sandy mix",
}
state.save_state(raw, shared)
assert "soil" not in state.load_profiles(shared)["Legacy"]

auto.update_plant_soil(second, "Loam")
auto.apply_plant_profile(second, "Legacy")
assert auto.get_plant(second).soil == "Loam", auto.get_plant(second).soil
print("ok: a profile saved with a soil in it does not apply it")

auto.update_plant_soil(second, "Peat potting mix")
restored = build(shared)
assert restored.get_plant(first).soil == "Coco coir"
assert restored.get_plant(second).soil == "Peat potting mix"
print("ok: each pot keeps its own soil across a restart")


# --- listing ---

listed = restored.list_soils()
assert len(listed) == len(names), [s["name"] for s in listed]
assert all(entry["wilting_fraction"] is not None for entry in listed)
widths = [entry["available_points"] for entry in listed]
assert widths == sorted(widths, reverse=True), widths
print("ok: listing reports the ratio and window, widest first")

# Deleting a soil must not rewrite plants that name it. The name stays and
# simply stops resolving, which is visible; silently clearing it would hide
# that a pot's mix is no longer described.
restored.delete_soil("Coco coir")
assert restored.get_plant(first).soil == "Coco coir"
assert "Coco coir" not in state.load_soils(shared)
print("ok: deleting a soil leaves plants naming it alone, so the gap is visible")

assert soil_library.main([]) == 0
print("ok: listing the library from the CLI exits cleanly")

# --- adding your own ---
#
# The whole design expects a measured mix to beat a looked-up one, so saving
# one has to work and has to refuse figures that cannot support a ratio.

own = build(temp_state())

result = own.save_soil("My mix", 30, 14)
assert result["available_points"] == 16.0, result
assert abs(result["wilting_fraction"] - 14 / 30) < 1e-9, result
assert state.load_soils(own._state_path)["My mix"]["field_capacity_vwc"] == 30
print("ok: a measured mix saves, and reports its window and ratio back")

# Name as key, so saving replaces rather than accumulating.
own.save_soil("my mix", 26, 12)
stored = state.load_soils(own._state_path)
assert len(stored) == 1, sorted(stored)
assert stored["my mix"]["field_capacity_vwc"] == 26, stored
print("ok: saving the same name replaces it, capitalisation included")

# Figures that cannot support a ratio must be refused, not stored. A soil that
# stores happily and then yields no ratio behaves exactly like no soil at all,
# so the pot reads as configured and is never watered.
for capacity, wilting, why in (
    (0, 10, "zero field capacity"),
    (-5, 2, "negative field capacity"),
    (120, 30, "field capacity above 100% VWC"),
    (30, 30, "wilting point equal to field capacity"),
    (30, 40, "wilting point above field capacity"),
    (30, 0, "zero wilting point"),
    (30, -4, "negative wilting point"),
    ("thirty", 14, "a non-numeric figure"),
    (30, True, "a boolean"),
    (None, 14, "a missing figure"),
):
    try:
        own.save_soil("Rejected", capacity, wilting)
    except ValueError:
        pass
    else:
        raise AssertionError(f"accepted {why}: {capacity}/{wilting}")
assert "Rejected" not in state.load_soils(own._state_path)
print("ok: figures that cannot support a ratio are refused, and nothing is stored")

for blank in ("", "   "):
    try:
        own.save_soil(blank, 30, 14)
    except ValueError:
        pass
    else:
        raise AssertionError(f"accepted a blank name {blank!r}")
print("ok: a blank name is refused")

# Anything saved must be usable by the band maths, which is the point of the
# validation rather than tidiness.
from greenthumb import moisture

saved = state.load_soils(own._state_path)["my mix"]
ratio = state.available_water_fraction(saved)
assert ratio is not None, saved
assert moisture.band_for(90, ratio) in moisture.ORDER
print("ok: a saved soil always yields a ratio the bands can use")


print("\nall soil library checks passed")
