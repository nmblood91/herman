"""Editing a plant profile directly, and the notes that go with it.

Until now the only way to write a plant profile was to snapshot a pot. So fixing
one meant loading it onto a spare pot, editing, and saving back -- changing
what the planter is actually running in order to edit something it is not.

There are now two paths into the same store, which is the risk this file
exists for: if the direct path validates less than the snapshot path, the
library fills with entries that load badly. The equivalence check below is the
one that matters most.
"""

import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from datetime import time as clock

from greenthumb import care, plant_library, soil_library, state
from greenthumb.config import settings
from greenthumb.hardware.soil_sensors import unavailable_sample
from greenthumb.services.automation import GreenThumbAutomation
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


BODY = {
    "category": "",
    "preferred_soil": "",
    "target_vwc": 21,
    "watering_volume_ml": 120,
    "light_start_time": "07:30",
    "light_hours": 13,
    "light_brightness": 75,
    "notes": "South window, dries fast in summer.",
}


# --- the two paths agree ---
#
# The property that matters: a plant written from a body and a plant
# snapshotted from a pot holding the same settings must be the same entry. If
# they diverge, one of the two editors is lying about what it saved.

auto = build()
pot = auto.plants[0]
pot.name = "From a pot"
pot.target_vwc = 21
pot.watering_volume_ml = 120
pot.light_start_time = clock(7, 30)
pot.light_hours = 13
pot.light_brightness = 75
pot.notes = "South window, dries fast in summer."
auto.save_plant_profile(pot.plant_id)
auto.write_plant_profile("From a body", BODY)

stored = state.load_profiles(auto._state_path)
snapshotted = {k: v for k, v in stored["From a pot"].items() if k != "saved_at"}
written = {k: v for k, v in stored["From a body"].items() if k != "saved_at"}
assert snapshotted == written, (snapshotted, written)
print("ok: writing a plant from a body gives the same entry as snapshotting a pot")

# Both carry every field a profile is meant to carry, and nothing else.
assert set(written) == set(state.PROFILE_FIELDS), sorted(written)
print(f"ok: and it carries exactly {', '.join(sorted(state.PROFILE_FIELDS))}")


# --- what the direct path refuses ---

auto = build()

# The target is the one that matters. One that cannot be used leaves a plant
# never thirsty -- a planter that looks like it works and has stopped watering.
for value, why in (
    ("damp", "a word"),
    (None, "no target at all"),
    (0, "zero, which nothing dries to"),
    (61, "wetter than any mix here holds"),
    (12.5, "a fraction"),
    (True, "a boolean"),
):
    try:
        auto.write_plant_profile("Rejected", {**BODY, "target_vwc": value})
    except ValueError:
        continue
    raise AssertionError(f"accepted {why}: {value!r}")
print("ok: an unusable target is refused")

for field_name, bad_values in (
    ("light_hours", (-1, 25, 1.5, None, "twelve")),
    ("light_brightness", (-1, 101, "bright", None)),
    ("light_start_time", ("25:00", "half seven", "", None, 730)),
):
    for bad in bad_values:
        try:
            auto.write_plant_profile("Rejected", {**BODY, field_name: bad})
        except ValueError:
            continue
        raise AssertionError(f"accepted {field_name}={bad!r}")
print("ok: a bad light length, brightness or start time is refused")


for volume, why in (
    ("lots", "a non-numeric dose"),
    (None, "no dose"),
    (True, "a boolean dose"),
):
    try:
        auto.write_plant_profile("Bad volume", {**BODY, "watering_volume_ml": volume})
    except ValueError:
        pass
    else:
        raise AssertionError(f"accepted {why}: {volume!r}")
print("ok: a dose that is not a number is refused")

# Clamped at zero and unbounded above, matching update_watering_volume. An
# editor stricter than the plant card would refuse what the card accepts.
assert auto.write_plant_profile("Zero", {**BODY, "watering_volume_ml": -5})
assert state.load_profiles(auto._state_path)["Zero"]["watering_volume_ml"] == 0
print("ok: a negative dose clamps to zero, as it does on the plant card")

# Normalised on the way in, not stored as typed. Both paths into the store
# have to agree byte for byte -- the snapshot path writes
# isoformat(timespec="minutes") -- or the equivalence above holds only for
# input that happened to be formatted the same way already.
auto.write_plant_profile("Odd times", {**BODY, "light_start_time": "07:30:45"})
odd = state.load_profiles(auto._state_path)["Odd times"]
assert odd["light_start_time"] == "07:30", odd
assert "light_stop_time" not in odd, "a stop time was stored beside the hours"
print("ok: a loosely typed start time is normalised, and no stop time is stored")

try:
    auto.write_plant_profile("Bad notes", {**BODY, "notes": 42})
except ValueError:
    pass
else:
    raise AssertionError("accepted a number as notes")
print("ok: notes have to be text")

for blank in ("", "   "):
    try:
        auto.write_plant_profile(blank, BODY)
    except ValueError:
        pass
    else:
        raise AssertionError(f"accepted a blank name {blank!r}")
print("ok: a blank name is refused")

# Nothing partial landed from any of the refusals above.
names = set(state.load_profiles(auto._state_path))
assert names == {"Zero", "Odd times"}, sorted(names)
print("ok: and a refused write stores nothing at all")


# --- name as key, like everything else named here ---

auto = build()
auto.write_plant_profile("Basil", BODY)
auto.write_plant_profile("basil", {**BODY, "watering_volume_ml": 55})
stored = state.load_profiles(auto._state_path)
assert len(stored) == 1, sorted(stored)
assert stored["basil"]["watering_volume_ml"] == 55, stored
print("ok: saving the same name replaces it, capitalisation included")


# --- reading one back ---

found = auto.get_plant_profile("BASIL")
assert found["name"] == "basil", found
assert found["profile"]["watering_volume_ml"] == 55
print("ok: a plant profile reads back by name, case-insensitively")

try:
    auto.get_plant_profile("Nothing")
except ValueError:
    pass
else:
    raise AssertionError("read back a plant that does not exist")
print("ok: reading an unknown name is refused rather than returning an empty form")

# A body straight from the reader must be writable again without editing, or
# the editor cannot round-trip its own form.
again = auto.write_plant_profile("Basil", found["profile"])
assert again["profile"]["watering_volume_ml"] == 55
print("ok: what the reader returns can be written straight back")


# --- notes travel, and an empty one is a real value ---

shared = temp_state()
auto = build(shared)
soil_library.install(path=shared)
first, second = auto.plants[0].plant_id, auto.plants[1].plant_id

auto.write_plant_profile("Fern", {**BODY, "notes": "Bathroom. Never direct sun."})
result = auto.apply_plant_profile(first, "Fern")
assert result["notes"] == "Bathroom. Never direct sun.", result
assert auto.get_plant(first).notes == "Bathroom. Never direct sun."
print("ok: a note loads onto a pot with the rest of the care settings")

restored = build(shared)
assert restored.get_plant(first).notes == "Bathroom. Never direct sun."
print("ok: and survives a restart")

# Clearing a note through the editor has to reach the pot. apply_plant_profile
# tests the stored value for being a string rather than for being truthy,
# which is what makes an emptied note overwrite the old one instead of being
# skipped as "nothing to apply".
restored.write_plant_profile("Fern", {**BODY, "notes": ""})
restored.apply_plant_profile(first, "Fern")
assert restored.get_plant(first).notes == "", restored.get_plant(first).notes
again = build(shared)
assert again.get_plant(first).notes == "", again.get_plant(first).notes
print("ok: an emptied note stays empty across a restart, rather than reverting")

# An entry written before notes existed has no key at all, and must load.
raw = state.load_state(shared)
raw["plant_profiles"]["Legacy"] = {
    "moisture_target": "wet",
    "watering_volume_ml": 80,
    "light_start_time": "09:00",
    "light_stop_time": "18:00",
}
state.save_state(raw, shared)
again.get_plant(second).notes = "left alone"
again.apply_plant_profile(second, "Legacy")
legacy = again.get_plant(second)
assert legacy.watering_volume_ml == 80 and legacy.light_start_time == clock(9, 0)
# Fields it does not have take the pot's defaults rather than whatever the
# previous plant left behind.
assert legacy.target_vwc == care.DEFAULT_TARGET_VWC, legacy.target_vwc
assert legacy.light_hours == care.DEFAULT_LIGHT_HOURS, legacy.light_hours
assert legacy.notes == "left alone", legacy.notes
print("ok: a profile from an older build loads what it can, and leaves the pot's note alone")


# --- the libraries stop throwing their own prose away ---

fresh = temp_state()
assert set(plant_library.install(path=fresh).values()) == {"written"}
profiles = state.load_profiles(fresh)
for entry in plant_library.LIBRARY:
    saved = profiles[entry.name]
    assert saved["category"] == entry.category, entry.name
    assert saved["notes"] == "", entry.name
print(f"ok: all {len(plant_library.LIBRARY)} library plants install with their category")

assert set(soil_library.install(path=fresh).values()) == {"written"}
soils = state.load_soils(fresh)
for soil in soil_library.LIBRARY:
    assert soils[soil.name]["notes"] == soil.note, soil.name
print(f"ok: and all {len(soil_library.LIBRARY)} library soils do too")

# A note is reachable through the API shape the UI reads, not just in state.
listed = {entry["name"]: entry for entry in build(fresh).list_soils()}
assert listed["Fast-Draining Mix"]["notes"].strip()
print("ok: and a soil's note reaches the listing the UI reads")


# --- a soil's note ---

auto = build(temp_state())
saved = auto.save_soil("My mix", 30, 14, "Bagged compost, packed firm.")
assert saved["soil"]["notes"] == "Bagged compost, packed firm.", saved
print("ok: a measured mix saves with a note")

assert auto.save_soil("No note", 30, 14)["soil"]["notes"] == ""
print("ok: and a note is optional")

try:
    auto.save_soil("Bad", 30, 14, 42)
except ValueError:
    pass
else:
    raise AssertionError("accepted a number as a soil note")
print("ok: a soil note has to be text too")

# The key, edge to edge.
for vwc, level in (
    (60, "Ultra Wet"), (46, "Ultra Wet"), (45, "Very Wet"), (41, "Very Wet"),
    (40, "Wet"), (35, "Wet"), (34, "Wet-Medium"), (31, "Wet-Medium"),
    (30, "Medium"), (25, "Medium"), (24, "Medium-Dry"), (21, "Medium-Dry"),
    (20, "Dry"), (16, "Dry"), (15, "Very Dry"), (11, "Very Dry"),
    (10, "Ultra Dry"), (1, "Ultra Dry"),
):
    assert care.water_level_for(vwc) == level, (vwc, care.water_level_for(vwc), level)
print("ok: a target maps to the water level the key gives it")

# Never stored: a label in the body, or one saved by an older build, is
# dropped, and what is reported comes from the target.
labelled = build()
labelled.write_plant_profile("Labelled", {**BODY, "target_vwc": 9, "water_level": "Wet"})
assert "water_level" not in state.load_profiles(labelled._state_path)["Labelled"]
raw = state.load_state(labelled._state_path)
raw["plant_profiles"]["Old"] = {**BODY, "target_vwc": 28, "water_level": "Dry"}
state.save_state(raw, labelled._state_path)
listed = {entry["name"]: entry for entry in labelled.list_plant_profiles()}
assert listed["Labelled"]["water_level"] == "Ultra Dry", listed["Labelled"]
assert listed["Old"]["water_level"] == "Medium", "a stored label outranked the key"
assert labelled.get_plant_profile("Old")["profile"]["water_level"] == "Medium"
labelled.apply_plant_profile(labelled.plants[0].plant_id, "Old")
plant_row = next(p for p in labelled.get_overview()["plants"] if p["plant_id"] == "plant_1")
assert plant_row["target_vwc"] == 28
print("ok: the water level is always worked out from the target, never stored")


print("\nall plant editor checks passed")
