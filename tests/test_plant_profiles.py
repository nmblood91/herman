"""Plant profiles: a library of care settings keyed by name.

Two rules carry the design. The name is the key, so saving overwrites rather
than accumulating "Basil (1)", "Basil (2)". And a profile is care settings
only -- never placement, because loading one plant onto a second pot must not
drag the first pot's rail coordinate across, which would put two plants at the
same coordinate and water one into the other.
"""

import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import state
from greenthumb.config import settings
from greenthumb.hardware.soil_sensors import unavailable_sample
from greenthumb.services.automation import GreenThumbAutomation
from tests.helpers import CalibrationSurface, temp_state, temp_store

settings.auto_watering_enabled = False
settings.auto_patrol_enabled = False


class Klip:
    def status(self): return {"ok": True, "position": 0.0, "homed": True, "max_x": 890.0}
    def water_supply_present(self): return True
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


def ids(auto):
    return [p.plant_id for p in auto.plants]


# --- saving and loading ---

auto = build()
first, second = ids(auto)[0], ids(auto)[1]

# A fresh pot has no plant profile behind it, and the card says so instead of
# presenting the code's placeholder care settings as a choice.
assert all(plant.profile == "" for plant in auto.plants)
print("ok: a fresh pot has no plant profile loaded")

auto.update_plant_name(first, "Basil - Wet")
auto.update_target_vwc(first, 28)
auto.update_watering_volume(first, 150)

auto.save_plant_profile(first)
names = [p["name"] for p in auto.list_plant_profiles()]
assert "Basil - Wet" in names, names
print("ok: a plant's settings save under its own name")

auto.apply_plant_profile(second, "Basil - Wet")
plant = auto.get_plant(second)
assert plant.name == "Basil - Wet", plant.name
assert plant.target_vwc == 28, plant.target_vwc
assert plant.watering_volume_ml == 150, plant.watering_volume_ml
print("ok: loading copies the name and the care settings onto another pot")

assert plant.profile == "Basil - Wet", plant.profile
assert auto.get_plant(first).profile == "Basil - Wet", "saving a pot as a plant did not mark it"
print("ok: loading or saving a plant marks the pot as having that profile")

shared = temp_state()
marked = build(shared)
marked.save_plant_profile(first)
marked.apply_plant_profile(second, marked.get_plant(first).name)
again = build(shared)
assert again.get_plant(second).profile == marked.get_plant(first).name
assert again.get_plant(ids(again)[2]).profile == ""
print("ok: which pots have a profile survives a restart")

# Clearing takes the plant off the pot and puts its care settings back to the
# default, so it does not keep watering to a plant it no longer claims to be.
# The pot keeps what describes the pot.
from greenthumb.plants import default_plants

cleared = build(temp_state())
pot = cleared.get_plant(second)
cleared.update_plant_name(first, "Fern")
cleared.update_target_vwc(first, 35)
cleared.update_watering_volume(first, 250)
cleared.save_plant_profile(first)
cleared.apply_plant_profile(second, "Fern")
cleared.set_plant_position(second, 300)
position, soil = pot.position_mm, pot.soil

cleared.clear_plant_profile(second)
fresh = next(p for p in default_plants() if p.plant_id == second)
assert pot.profile == ""
assert pot.name == fresh.name, pot.name
assert pot.target_vwc == fresh.target_vwc, pot.target_vwc
assert pot.watering_volume_ml == fresh.watering_volume_ml, pot.watering_volume_ml
assert (pot.light_start_time, pot.light_hours, pot.light_brightness) == (
    fresh.light_start_time, fresh.light_hours, fresh.light_brightness
)
assert pot.notes == fresh.notes
assert (pot.position_mm, pot.soil) == (position, soil), "clearing moved or re-potted the pot"
assert "Fern" in [p["name"] for p in cleared.list_plant_profiles()], "clearing deleted the plant profile"
assert cleared.get_plant(first).profile == "Fern", "clearing one pot cleared another"
print("ok: clearing a profile resets the pot's plant settings, keeps its placement and the plant profile")


# --- the rule that matters: placement never travels ---

auto = build()
first, second = ids(auto)[0], ids(auto)[1]
auto.update_plant_name(first, "Basil")
auto.set_plant_position(first, 130)
auto.set_plant_position(second, 350)
auto.save_plant_profile(first)

auto.apply_plant_profile(second, "Basil")
assert auto.get_plant(second).position_mm == 350, (
    "loading a profile moved the pot to the other plant's coordinate"
)
assert auto.get_plant(first).position_mm == 130
print("ok: loading leaves the rail position alone, so two pots cannot collide")

assert "position_mm" not in state.PROFILE_FIELDS
saved = state.load_profiles(auto._state_path)["Basil"]
assert "position_mm" not in saved, saved
print("ok: and the position is not even stored, so it cannot leak later")


# --- overwrite, never accumulate ---

shared = temp_state()
auto = build(shared)
first = ids(auto)[0]
auto.update_plant_name(first, "Basil")
auto.update_target_vwc(first, 20)
auto.save_plant_profile(first)
auto.update_target_vwc(first, 35)
auto.save_plant_profile(first)

profiles = auto.list_plant_profiles()
assert len(profiles) == 1, [p["name"] for p in profiles]
assert profiles[0]["target_vwc"] == 35, profiles[0]
print("ok: saving twice overwrites rather than making a second Basil")

# A stray capital is not a different plant.
auto.update_plant_name(first, "basil")
auto.update_target_vwc(first, 28)
auto.save_plant_profile(first)
profiles = auto.list_plant_profiles()
assert len(profiles) == 1, [p["name"] for p in profiles]
assert profiles[0]["name"] == "basil", profiles[0]["name"]
assert profiles[0]["target_vwc"] == 28
print("ok: a change of capitalisation renames the entry instead of duplicating it")

# And loading is case-insensitive the same way.
auto.apply_plant_profile(ids(auto)[1], "BASIL")
assert auto.get_plant(ids(auto)[1]).target_vwc == 28
print("ok: loading matches a name regardless of case")

# Distinct names are distinct plants, which is how you keep wet and dry apart.
auto.update_plant_name(first, "Basil - Dry")
auto.update_target_vwc(first, 9)
auto.save_plant_profile(first)
names = sorted(p["name"] for p in auto.list_plant_profiles())
assert names == ["Basil - Dry", "basil"], names
print("ok: Basil - Dry and basil are two plant profiles, as intended")


# --- it survives a restart ---

restored = build(shared)
names = sorted(p["name"] for p in restored.list_plant_profiles())
assert names == ["Basil - Dry", "basil"], names
print("ok: the library survives a restart")

# Saving a plant must not wipe the library, since _persist writes the whole
# snapshot and the profiles live under their own key.
restored.update_plant_name(ids(restored)[2], "Mint")
restored._persist()
assert len(restored.list_plant_profiles()) == 2, "persisting plants clobbered the library"
print("ok: persisting plant settings leaves the library alone")


# --- deleting, and bad input ---

assert restored.delete_plant_profile("BASIL")["deleted"] == "BASIL"
assert [p["name"] for p in restored.list_plant_profiles()] == ["Basil - Dry"]
print("ok: deleting works, and matches case-insensitively too")

for bad in ("Nothing", "", "   "):
    try:
        restored.apply_plant_profile(ids(restored)[0], bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"loaded a profile that does not exist: {bad!r}")
print("ok: loading an unknown name is refused")

try:
    restored.delete_plant_profile("Nothing")
except ValueError:
    print("ok: deleting an unknown name is refused rather than silently passing")
else:
    raise AssertionError("expected ValueError")

# A pot still using a deleted profile keeps what it was given -- the library is
# a source to copy from, not a live link.
assert restored.get_plant(ids(restored)[1]).target_vwc == 28
print("ok: deleting a plant profile does not change pots already using it")

try:
    state.save_profile("   ", {"target_vwc": 20}, restored._state_path)
except ValueError:
    print("ok: a blank name is refused")
else:
    raise AssertionError("expected ValueError")

try:
    state.save_profile("Empty", {"position_mm": 500}, restored._state_path)
except ValueError:
    print("ok: a profile with nothing but placement in it is refused")
else:
    raise AssertionError("expected ValueError")


# --- a hand-edited file loses one entry, not the library ---

data = state.load_state(restored._state_path)
data[state.PROFILES_KEY]["Broken"] = "not an object"
data[state.PROFILES_KEY]["Hollow"] = {}
# A string that happens to contain a field name. "field in value" is a
# substring test when value is a string, so without the type guard this reaches
# value["target_vwc"] -- indexing a string with a string -- and the
# TypeError takes the whole library down rather than one entry.
data[state.PROFILES_KEY]["Nasty"] = "target_vwc"
data[state.PROFILES_KEY][""] = {"target_vwc": 20}
data[state.PROFILES_KEY]["Good"] = {"target_vwc": 20}
state.save_state(data, restored._state_path)

names = sorted(state.load_profiles(restored._state_path))
assert names == ["Basil - Dry", "Good"], names
print("ok: malformed and empty entries are skipped, the rest still load")

print("\nall plant profile checks passed")
