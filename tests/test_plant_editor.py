"""Editing a saved plant directly, and the notes that go with it.

Until now the only way to write a saved plant was to snapshot a pot. So fixing
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

from greenthumb import moisture, plant_library, soil_library, state
from greenthumb.config import settings
from greenthumb.hardware.soil_sensors import unavailable_sample
from greenthumb.services.automation import GreenThumbAutomation
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


BODY = {
    "moisture_target": "dry",
    "watering_volume_ml": 120,
    "light_start_time": "07:30",
    "light_stop_time": "21:00",
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
pot.moisture_target = "dry"
pot.watering_volume_ml = 120
pot.light_start_time = clock(7, 30)
pot.light_stop_time = clock(21, 0)
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

# The band is the one that matters. An unrecognised target is dropped on load
# rather than applied, which leaves a plant permanently not-thirsty -- a
# planter that looks like it works and has quietly stopped watering.
for target, why in (
    ("damp", "a band that does not exist"),
    ("", "an empty band"),
    (None, "no band at all"),
    (3, "a number where a band name goes"),
    ("very  wet", "a band with the wrong spacing inside it"),
):
    try:
        auto.write_plant_profile("Rejected", {**BODY, "moisture_target": target})
    except ValueError:
        continue
    raise AssertionError(f"accepted {why}: {target!r}")
print("ok: an unrecognised band is refused")

# Surrounding whitespace and capitalisation are folded rather than refused,
# matching how apply_plant_profile reads a stored target.
auto.write_plant_profile("Folded", {**BODY, "moisture_target": "  VERY WET "})
assert state.load_profiles(auto._state_path)["Folded"]["moisture_target"] == "very wet"
print("ok: but a stray space or capital is folded away, not rejected")

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
auto.write_plant_profile(
    "Odd times",
    {**BODY, "light_start_time": "07:30:45", "light_stop_time": "21:00:00"},
)
odd = state.load_profiles(auto._state_path)["Odd times"]
assert odd["light_start_time"] == "07:30", odd
assert odd["light_stop_time"] == "21:00", odd
print("ok: a loosely typed light time is normalised, not stored as written")

for field_name in ("light_start_time", "light_stop_time"):
    for bad in ("25:00", "half seven", "", None, 730):
        try:
            auto.write_plant_profile("Bad time", {**BODY, field_name: bad})
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted {field_name}={bad!r}")
print("ok: a light time that is not a time is refused")

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
assert names == {"Zero", "Folded", "Odd times"}, sorted(names)
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
print("ok: a saved plant reads back by name, case-insensitively")

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
assert again.get_plant(second).moisture_target == "wet"
assert again.get_plant(second).notes == "left alone", again.get_plant(second).notes
print("ok: a profile saved before notes existed loads, and leaves the pot's note alone")


# --- the libraries stop throwing their own prose away ---

fresh = temp_state()
assert set(plant_library.install(path=fresh).values()) == {"written"}
profiles = state.load_profiles(fresh)
for entry in plant_library.LIBRARY:
    saved = profiles[entry.name]
    assert saved["notes"] == entry.note, entry.name
    assert saved["notes"].strip(), f"{entry.name} installed with an empty note"
print(f"ok: all {len(plant_library.LIBRARY)} library plants install with their notes")

assert set(soil_library.install(path=fresh).values()) == {"written"}
soils = state.load_soils(fresh)
for soil in soil_library.LIBRARY:
    assert soils[soil.name]["notes"] == soil.note, soil.name
print(f"ok: and all {len(soil_library.LIBRARY)} library soils do too")

# A note is reachable through the API shape the UI reads, not just in state.
listed = {entry["name"]: entry for entry in build(fresh).list_soils()}
assert listed["Coco coir"]["notes"].strip()
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

# Every band still has to be offerable by the editor's picker.
assert all(name in moisture.BY_NAME for name in moisture.ORDER)
print("ok: every band name the editor can offer resolves")


print("\nall plant editor checks passed")
