"""Backing up the soil and plant profile libraries, and loading them back.

The point of a backup is surviving a reflash, so the test that matters is the
round trip: what comes back must be what went out, measured readings and where
they came from included. After that, an import must never quietly undo newer
tuning, and a bad entry must cost only itself.
"""

import json
import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import plant_library, soil_library, state
from greenthumb.config import settings
from greenthumb.hardware.soil_sensors import unavailable_sample
from greenthumb.services.automation import GreenThumbAutomation
from tests.helpers import CalibrationSurface, temp_state, temp_store

settings.auto_watering_enabled = False
settings.auto_patrol_enabled = False


class Hub(CalibrationSurface):
    addresses = [0x36, 0x37, 0x38, 0x39]
    def read_one(self, a): return unavailable_sample(a)


class Nul:
    mode = "off"; color = (0, 0, 0); brightness = 0; is_running = False
    def __getattr__(self, n): return lambda *a, **k: {}


def build(path):
    return GreenThumbAutomation(Hub(), Nul(), Nul(), Nul(), history=temp_store(), state_path=path)


def without_saved_at(library):
    # A reading saved through the editor is stored as null when there is none,
    # and the library leaves it out; both mean "no reading".
    return {
        name: {k: v for k, v in entry.items() if k != "saved_at" and v is not None}
        for name, entry in library.items()
    }


RICH = soil_library.LIBRARY[0].name

# --- a planter with real work in it ---

source_path = temp_state()
soil_library.install(path=source_path)
plant_library.install(path=source_path)
source = build(source_path)
# A measured field capacity, provenance and all: the thing worth backing up.
state.save_soil(RICH, {
    "field_capacity_raw": 812,
    "field_capacity_samples": 40,
    "field_capacity_measured_at": "2026-10-14T09:30:00",
    "field_capacity_address": 0x37,
}, source_path)
source.write_plant_profile("My Basil", {
    "category": "Culinary Herbs & Leafy Greens", "preferred_soil": RICH, "target_available": 31,
    "watering_volume_ml": 140, "light_start_time": "06:30", "light_hours": 14,
    "light_brightness": 80, "notes": "south window cutting",
})

backup = source.export_library()
# It has to survive being a file.
backup = json.loads(json.dumps(backup))
assert backup["format"] == "greenthumb-library", backup.keys()
assert backup["soil_profiles"][RICH]["field_capacity_raw"] == 812
print(f"ok: export holds {len(backup['soil_profiles'])} soil and {len(backup['plant_profiles'])} plant profiles")


# --- restore onto a reflashed planter: the round trip ---

fresh_path = temp_state()
fresh = build(fresh_path)
result = fresh.import_library(backup)
assert set(result["soil_profiles"].values()) == {"written"}, result["soil_profiles"]
assert set(result["plant_profiles"].values()) == {"written"}, result["plant_profiles"]
assert without_saved_at(state.load_soils(fresh_path)) == without_saved_at(backup["soil_profiles"])
assert without_saved_at(state.load_profiles(fresh_path)) == without_saved_at(backup["plant_profiles"])
print("ok: restoring onto an empty planter gives back exactly what was exported")


# --- importing over a planter that has moved on ---

target_path = temp_state()
soil_library.install(path=target_path)
plant_library.install(path=target_path)
target = build(target_path)
state.save_soil(RICH, {"field_capacity_raw": 900}, target_path)
target.write_plant_profile("Sweet Basil", {
    **{k: v for k, v in backup["plant_profiles"]["Sweet Basil"].items() if k != "saved_at"},
    "target_available": 33,
})

result = target.import_library(backup)
assert result["plant_profiles"]["Sweet Basil"] == "kept", result
assert result["plant_profiles"]["My Basil"] == "written", result
assert result["soil_profiles"][RICH] == "kept", result
assert state.load_profiles(target_path)["Sweet Basil"]["target_available"] == 33
assert state.load_soils(target_path)[RICH]["field_capacity_raw"] == 900
print("ok: without replace, what is already here is kept and only missing entries are added")

result = target.import_library(backup, replace=True)
assert result["plant_profiles"]["Sweet Basil"] == "written", result
assert state.load_profiles(target_path)["Sweet Basil"]["target_available"] == (
    backup["plant_profiles"]["Sweet Basil"]["target_available"]
)
assert state.load_soils(target_path)[RICH]["field_capacity_raw"] == 812
assert state.load_soils(target_path)[RICH]["field_capacity_address"] == 0x37
print("ok: with replace, the backup's figures win, provenance included")


# --- bad input ---

for bad in (
    None,
    [],
    {"moisture_calibration": {}},  # JSON from somewhere, but no libraries in it
    {"format": "something-else", "soil_profiles": {}},
    {"plant_profiles": ["basil"]},
):
    try:
        build(temp_state()).import_library(bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"accepted {bad!r}")
print("ok: a file that is not a library backup is refused")

# A state.json pulled off the card of a Pi that will not boot.
raw_state = json.loads(source_path.read_text(encoding="utf-8"))
path = temp_state()
result = build(path).import_library(raw_state)
assert result["plant_profiles"]["My Basil"] == "written", result
assert state.load_soils(path)[RICH]["field_capacity_raw"] == 812
print("ok: a planter's own state.json restores the same way")

damaged = json.loads(json.dumps(backup))
damaged["soil_profiles"]["Broken Mix"] = {"field_capacity_vwc": 30, "wilting_point_vwc": 45}
damaged["plant_profiles"]["Bad Light"] = {**damaged["plant_profiles"]["My Basil"], "light_hours": 30}
damaged["plant_profiles"]["Lost Soil"] = {**damaged["plant_profiles"]["My Basil"], "preferred_soil": "Nowhere Mix"}
damaged["plant_profiles"]["Not A Profile"] = "basil"
path = temp_state()
result = build(path).import_library(damaged)
for section, name in (
    ("soil_profiles", "Broken Mix"),
    ("plant_profiles", "Bad Light"),
    ("plant_profiles", "Lost Soil"),
    ("plant_profiles", "Not A Profile"),
):
    assert result[section][name].startswith("skipped"), (name, result[section][name])
assert "Broken Mix" not in state.load_soils(path)
assert "Bad Light" not in state.load_profiles(path)
assert result["plant_profiles"]["My Basil"] == "written", result
print("ok: bad entries are skipped with a reason, and the rest still load")

print("\nall library backup checks passed")
