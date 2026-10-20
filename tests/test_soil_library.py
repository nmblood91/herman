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
from tests.helpers import CalibrationSurface, temp_state, temp_store

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

# Exactly the three recipes in SOIL_PROFILES.md, wettest to driest, with the
# midpoints of their published ranges. Pinned so the library and the document
# users follow cannot drift apart.
assert [(s.name, s.field_capacity_vwc, s.wilting_point_vwc) for s in LIBRARY] == [
    ("Rich & Retentive Mix", 50, 17.5),
    ("Fast-Draining Mix", 25, 8),
    ("Ultra-Coarse Epiphytic Mix", 15, 4),
], [(s.name, s.field_capacity_vwc, s.wilting_point_vwc) for s in LIBRARY]
print("ok: the library is exactly the three recipes, wettest to driest")

# Each note carries its recipe, so it reaches the editor and not just the docs.
for soil, recipe in zip(LIBRARY, ("Recipe 1", "Recipe 2", "Recipe 3")):
    assert soil.note.startswith(recipe), soil.note
    assert "parts" in soil.note and "For:" in soil.note, soil.note
print("ok: every soil profile's note carries its recipe and its plants")


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

state.save_soil("Rich & Retentive Mix", {"field_capacity_vwc": 33, "wilting_point_vwc": 19}, path)
outcome = soil_library.install(path=path)
assert outcome["Rich & Retentive Mix"] == "kept", outcome
assert state.load_soils(path)["Rich & Retentive Mix"]["field_capacity_vwc"] == 33
print("ok: re-installing keeps a mix you measured yourself")

state.save_soil("fast-draining mix", {"field_capacity_vwc": 50, "wilting_point_vwc": 14}, path)
assert soil_library.install(path=path)["Fast-Draining Mix"] == "kept"
assert len(state.load_soils(path)) == len(names), sorted(state.load_soils(path))
print("ok: a differently capitalised mix still counts as yours")

assert set(soil_library.install(overwrite=True, path=path).values()) == {"written"}
assert state.load_soils(path)["Rich & Retentive Mix"]["field_capacity_vwc"] == 50
print("ok: --overwrite restores the library figures")


# --- a plant's soil ---

shared = temp_state()
soil_library.install(path=shared)
auto = build(shared)
first, second = auto.plants[0].plant_id, auto.plants[1].plant_id

assert auto.get_plant(first).soil == "", "a plant started with a soil already set"
print("ok: a plant starts with no soil, which is distinct from a bad one")

auto.update_plant_soil(first, "rich & retentive mix")
assert auto.get_plant(first).soil == "Rich & Retentive Mix", auto.get_plant(first).soil
print("ok: setting a soil matches case-insensitively and stores the library's spelling")

# An unknown mix supplies no ratio, so storing it would read as "set" while
# behaving exactly like "not set".
for bad in ("Moon dust", "rich retentive mix"):
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


# --- a plant profile's preferred soil ---

auto.update_plant_soil(first, "Rich & Retentive Mix")
auto.update_plant_soil(second, "Rich & Retentive Mix")
auto.update_plant_name(first, "Fern")
auto.get_plant(first).preferred_soil = "Fast-Draining Mix"
auto.save_plant_profile(first)

# Saving a pot keeps the preference it was loaded with. The soil it happens
# to be growing in is not written over it: a plant potted in something else
# for now still wants what it wants.
saved = state.load_profiles(shared)["Fern"]
assert saved["preferred_soil"] == "Fast-Draining Mix", saved
assert "soil" not in saved, saved
auto.get_plant(first).preferred_soil = ""
auto.save_plant_profile(first)
assert state.load_profiles(shared)["Fern"]["preferred_soil"] == "", (
    "saving a pot with no preference recorded the soil it is in as one"
)
auto.write_plant_profile("Fern", {
    "preferred_soil": "Fast-Draining Mix", "target_available": 20, "watering_volume_ml": 50,
    "light_start_time": "07:00", "light_hours": 12, "light_brightness": 50,
})
print("ok: saving a pot keeps its preferred soil, never the soil it is in")

# Loading it pots the plant in the mix it wants, and says so.
result = auto.apply_plant_profile(second, "Fern")
assert auto.get_plant(second).soil == "Fast-Draining Mix", auto.get_plant(second).soil
assert auto.get_plant(second).preferred_soil == "Fast-Draining Mix"
assert result["soil"] == "Fast-Draining Mix" and not result["soil_note"], result
print("ok: loading a plant profile switches the pot to its preferred soil profile")

# A preference naming a soil profile that is not installed leaves the pot's
# soil alone and says why, rather than clearing it.
raw = state.load_state(shared)
raw["plant_profiles"]["Exotic"] = {
    "target_available": 20,
    "watering_volume_ml": 50,
    "preferred_soil": "Moon dust",
}
state.save_state(raw, shared)
result = auto.apply_plant_profile(second, "Exotic")
assert auto.get_plant(second).soil == "Fast-Draining Mix", auto.get_plant(second).soil
assert "Moon dust" in result["soil_note"], result
print("ok: a preferred soil that is not installed leaves the pot's soil, and says so")

# An entry written by an older build carried "soil". The whitelist filters on
# read, so it neither loads nor moves the pot.
raw = state.load_state(shared)
raw["plant_profiles"]["Legacy"] = {
    "watering_volume_ml": 50,
    "soil": "Ultra-Coarse Epiphytic Mix",
}
state.save_state(raw, shared)
assert "soil" not in state.load_profiles(shared)["Legacy"]
auto.apply_plant_profile(second, "Legacy")
assert auto.get_plant(second).soil == "Fast-Draining Mix", auto.get_plant(second).soil
print("ok: a profile saved with an old soil key does not apply it")

# A preferred soil written in the editor must name a soil profile.
try:
    auto.write_plant_profile("Typo", {
        "target_available": 20, "watering_volume_ml": 50, "light_start_time": "07:00",
        "light_hours": 12, "light_brightness": 50, "preferred_soil": "Rich and Retentive",
    })
except ValueError:
    pass
else:
    raise AssertionError("stored a preferred soil that names no soil profile")
print("ok: a preferred soil that names no soil profile is refused")

auto.update_plant_soil(first, "Fast-Draining Mix")
auto.update_plant_soil(second, "Rich & Retentive Mix")
restored = build(shared)
assert restored.get_plant(first).soil == "Fast-Draining Mix"
assert restored.get_plant(second).soil == "Rich & Retentive Mix"
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
restored.delete_soil("Fast-Draining Mix")
assert restored.get_plant(first).soil == "Fast-Draining Mix"
assert "Fast-Draining Mix" not in state.load_soils(shared)
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

# The % VWC pair is optional now -- watering runs on the two sensor readings --
# but when given it must still make a usable ratio, since it is what suggests
# where wilting point should read.
saved = state.load_soils(own._state_path)["my mix"]
assert state.available_water_fraction(saved) is not None, saved
print("ok: a saved % pair always yields a usable ratio")

blank = own.save_soil("Readings only", None, None, field_capacity_raw=800, wilting_point_raw=450)
stored = state.load_soils(own._state_path)["Readings only"]
assert stored["field_capacity_vwc"] is None and stored["wilting_point_vwc"] is None, stored
assert blank["available_points"] is None, blank
try:
    own.save_soil("Half a pair", 30, None)
except ValueError:
    pass
else:
    raise AssertionError("accepted one % figure without the other")
print("ok: a soil profile can be saved on its sensor readings alone, but not half a % pair")


# --- a field capacity entered by hand ------------------------------------
#
# The measuring path needs a pot soaked and drained for a day, so the figure
# has to be enterable from a note as well: a reflash is this project's upgrade
# path, and re-soaking four pots to recover a number nobody lost is not one.

path = temp_state()
soil_library.install(path=path)

# With no wilting point yet, a probe in open air is the floor: soil never
# reads below it.
for raw, why in (
    (settings.moisture_raw_dry, "the air reading itself"),
    (0, "zero"),
):
    try:
        soil_library.set_field_capacity("Fast-Draining Mix", raw, path=path)
    except ValueError:
        pass
    else:
        raise AssertionError(f"accepted {why}: {raw}")
    assert state.load_soils(path)["Fast-Draining Mix"].get("field_capacity_raw") is None, raw

# With one, field capacity has to clear it by a usable span, or every pot on
# the soil profile reads -1.
state.save_soil("Ultra-Coarse Epiphytic Mix", {"wilting_point_raw": 600}, path)
floor = 600 + soil_library.MIN_CALIBRATION_SPAN
try:
    soil_library.set_field_capacity("Ultra-Coarse Epiphytic Mix", floor - 1, path=path)
except ValueError as error:
    assert "wilting point" in str(error), error
else:
    raise AssertionError("accepted a field capacity too close to the wilting point")
assert soil_library.set_field_capacity("Ultra-Coarse Epiphytic Mix", floor, path=path)
print("ok: a field capacity below the air reading, or too close to wilting point, is refused")
# The refusal matters because the stored result would be indistinguishable
# from never having measured: span_for returns None under the span, every pot
# on the mix reads -1, and nothing is watered.
print("ok: a figure too low to read against is refused, and nothing is stored")

try:
    soil_library.set_field_capacity("Moon dust", 700, path=path)
except ValueError as error:
    assert "Moon dust" in str(error), error
else:
    raise AssertionError("accepted a mix that is not installed")
print("ok: an unknown mix is refused, and says what is installed")

key = soil_library.set_field_capacity("fast-DRAINING mix", 742, path=path)
assert key == "Fast-Draining Mix", key
entry = state.load_soils(path)["Fast-Draining Mix"]
assert entry["field_capacity_raw"] == 742, entry
print("ok: a hand-entered figure is written, matched on the name case-insensitively")

# The absence of a date is the only thing separating this from a measurement,
# so it has to stay absent.
assert entry["field_capacity_measured_at"] == "", entry
assert entry["field_capacity_samples"] == 0, entry
print("ok: no measurement date and no samples, since nothing was measured")

# The merge trap: save_soil replacing the whole entry would drop the % figures
# and the note, which were installed beside it.
assert entry["field_capacity_vwc"] == 25, entry
assert entry["wilting_point_vwc"] == 8, entry
assert entry["notes"], entry
assert state.available_water_fraction(entry) is not None, entry
print("ok: the VWC figures and the note survive, so the mix still bands")

# And a pot reads against it the way it reads against a measured one.
own = build(path)
own.update_plant_soil("plant_1", "Fast-Draining Mix")
plant = own.plants[0]
assert own.sensor_hub.field_capacity[plant.sensor_address] == 742, own.sensor_hub.field_capacity
print("ok: a pot reads against a hand-entered figure like any other")


# --- a default field capacity reading shipped with the library ---
#
# Measured once on the reference build, so a new planter can water straight
# away. Patched in here, since the shipped values may not be filled in yet.

import dataclasses

shipped = soil_library.LIBRARY
try:
    soil_library.LIBRARY = tuple(
        dataclasses.replace(soil, field_capacity_raw=600 + 50 * i)
        for i, soil in enumerate(shipped)
    )
    path = temp_state()
    soil_library.install(path=path)
    entry = state.load_soils(path)["Rich & Retentive Mix"]
    assert entry["field_capacity_raw"] == 600, entry
    assert entry["field_capacity_measured_at"] == "", "a shipped default claims to be measured here"
    print("ok: install writes the default field capacity reading, marked as not measured")

    fresh = build(path)
    fresh.update_plant_soil("plant_1", "Rich & Retentive Mix")
    assert fresh.scale_problem(fresh.plants[0]) is None, fresh.scale_problem(fresh.plants[0])
    print("ok: with the defaults a pot can be judged as soon as its soil profile is chosen")

    # A soil profile already installed without one gets the default; one with
    # a reading of its own keeps it.
    path = temp_state()
    soil_library.LIBRARY = shipped
    soil_library.install(path=path)
    state.save_soil("Fast-Draining Mix", {"field_capacity_raw": 777}, path)
    soil_library.LIBRARY = tuple(
        dataclasses.replace(soil, field_capacity_raw=600) for soil in shipped
    )
    outcome = soil_library.install(path=path)
    assert outcome["Rich & Retentive Mix"] == "kept, default field capacity added", outcome
    assert outcome["Fast-Draining Mix"] == "kept", outcome
    assert state.load_soils(path)["Rich & Retentive Mix"]["field_capacity_raw"] == 600
    assert state.load_soils(path)["Fast-Draining Mix"]["field_capacity_raw"] == 777
    print("ok: re-installing fills in a missing default and never replaces a reading")
finally:
    soil_library.LIBRARY = shipped


# --- typed sensor readings on a soil profile ---
#
# The editor's two sensor-reading fields. Optional: left out keeps what is
# stored, so saving the percentages never wipes a measurement; null clears; a
# number replaces it and loses the measurement's details.

from greenthumb.services.automation import UNCHANGED

typed = build()
typed.save_soil("Typed mix", 30, 14)
first, second, third = (p.plant_id for p in typed.plants[:3])
typed.update_plant_soil(first, "Typed mix")
typed.update_plant_soil(second, "Typed mix")
typed.update_plant_soil(third, "Typed mix")

def capacity_of(plant_id):
    return typed.sensor_hub.field_capacity.get(typed.get_plant(plant_id).sensor_address)

result = typed.save_soil("Typed mix", 30, 14, field_capacity_raw=700, wilting_point_raw=450)
stored = state.load_soils(typed._state_path)["Typed mix"]
assert (stored["field_capacity_raw"], stored["wilting_point_raw"]) == (700, 450), stored
assert stored["field_capacity_measured_at"] is None, "a typed figure claims to be measured"
assert [capacity_of(p) for p in (first, second, third)] == [700, 700, 700]
assert sorted(result["inherited_by"]) == sorted(
    typed.get_plant(p).name for p in (first, second, third)
), result["inherited_by"]
print("ok: typed readings save, and field capacity reaches every pot using it at once")

# Saving the percentages alone leaves a measured reading and its date alone.
state.save_soil(
    "Typed mix",
    {"field_capacity_raw": 710, "field_capacity_measured_at": "2026-10-01T12:00:00"},
    typed._state_path,
)
typed.save_soil("Typed mix", 31, 14)
stored = state.load_soils(typed._state_path)["Typed mix"]
assert stored["field_capacity_raw"] == 710, stored
assert stored["field_capacity_measured_at"] == "2026-10-01T12:00:00", stored
assert stored["field_capacity_vwc"] == 31
print("ok: saving without the readings keeps a measurement and when it was taken")

# Cleared: every pot using it reads nothing again.
typed.save_soil("Typed mix", 31, 14, field_capacity_raw=None)
assert state.load_soils(typed._state_path)["Typed mix"]["field_capacity_raw"] is None
assert [capacity_of(p) for p in (first, second, third)] == [None, None, None]
print("ok: clearing the reading leaves every pot using it with no scale")

for capacity, wilting, why in (
    (500, 500, "wilting point equal to field capacity"),
    (500, 600, "wilting point above field capacity"),
    (0, UNCHANGED, "a field capacity of zero"),
    (-5, UNCHANGED, "a negative reading"),
    (512.5, UNCHANGED, "a fraction of a reading"),
    (True, UNCHANGED, "a boolean"),
    ("700", UNCHANGED, "text"),
):
    try:
        typed.save_soil("Typed mix", 31, 14, field_capacity_raw=capacity, wilting_point_raw=wilting)
    except ValueError:
        pass
    else:
        raise AssertionError(f"accepted {why}")
# Checked against the stored figure for whichever one is not being changed.
typed.save_soil("Typed mix", 31, 14, field_capacity_raw=700)
try:
    typed.save_soil("Typed mix", 31, 14, wilting_point_raw=800)
except ValueError:
    pass
else:
    raise AssertionError("accepted a wilting point above the stored field capacity")
print("ok: unusable readings are refused, including a wilting point at or above capacity")


print("\nall soil library checks passed")
