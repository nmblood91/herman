"""The starter plant library.

What is worth testing here is not the numbers themselves -- they are editorial
-- but the two properties that make them safe to ship:

* every target sits low enough on the scale that it cannot become a
  permanently thirsty plant, and
* installing never overwrites a plant somebody has already tuned.
"""

import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import moisture, plant_library, state
from greenthumb.plant_library import LIBRARY
from tests.helpers import temp_state


# --- the targets are real bands ---

for plant in LIBRARY:
    assert plant.moisture_target in moisture.BY_NAME, (
        f"{plant.name} targets {plant.moisture_target!r}, which is not a band"
    )
    assert 0 < plant.watering_volume_ml <= 500, f"{plant.name} doses {plant.watering_volume_ml} mL"
    assert plant.note.strip(), f"{plant.name} has no explanation of where its numbers came from"
print(f"ok: all {len(LIBRARY)} targets are real bands")

# Nothing may target "very wet". A pot is only that straight after watering, so
# it would be thirsty again almost immediately and water every cooldown.
for plant in LIBRARY:
    assert plant.moisture_target != moisture.VERY_WET, plant.name
print("ok: nothing targets very wet, which would water on a loop")

# Light windows have to parse, and none may run backwards into an overnight
# window by accident -- these are all daytime photoperiods.
for plant in LIBRARY:
    start = tuple(int(part) for part in plant.light_start_time.split(":"))
    stop = tuple(int(part) for part in plant.light_stop_time.split(":"))
    assert start < stop, f"{plant.name} lights run overnight: {plant.light_start_time}-{plant.light_stop_time}"
    hours = stop[0] - start[0]
    assert 8 <= hours <= 17, f"{plant.name} asks for {hours} h of light"
print("ok: every photoperiod is a daytime window between 8 and 17 hours")

# The ordering is the defensible part, so pin it: each plant waters no later
# than the one before. Several sharing a band is expected.
indexes = [moisture.BY_NAME[plant.moisture_target].index for plant in LIBRARY]
assert indexes == sorted(indexes), [(p.name, p.moisture_target) for p in LIBRARY]
assert LIBRARY[-1].name == "Snake Plant", LIBRARY[-1].name
assert LIBRARY[0].moisture_target == moisture.MEDIUM, LIBRARY[0].moisture_target
print("ok: the library runs wettest-wanting to driest, lettuce down to snake plant")

names = [plant.name for plant in LIBRARY]
assert len(set(name.casefold() for name in names)) == len(names), names
print(f"ok: names are distinct -> {', '.join(names)}")


# --- installing ---

path = temp_state()
outcome = plant_library.install(path=path)
assert set(outcome.values()) == {"written"}, outcome
stored = state.load_profiles(path)
assert set(stored) == set(names), sorted(stored)
print("ok: installing writes all five into the saved-plant library")

# Placement must not have come along, the same rule as any other profile.
for name, entry in stored.items():
    assert "position_mm" not in entry, (name, entry)
print("ok: no rail position is stored, so loading one cannot move a pot")

# The important one: a tuned plant is not silently replaced.
state.save_profile("Basil", {"moisture_target": "very wet", "watering_volume_ml": 11}, path)
outcome = plant_library.install(path=path)
assert outcome["Basil"] == "kept", outcome
assert state.load_profiles(path)["Basil"]["moisture_target"] == "very wet", (
    "installing overwrote a plant the user had tuned"
)
assert outcome["Pothos"] == "kept"
print("ok: re-installing keeps your own numbers rather than replacing them")

# And case is not a loophole for sneaking a duplicate past that check.
state.save_profile("snake plant", {"moisture_target": "wet"}, path)
outcome = plant_library.install(path=path)
assert outcome["Snake Plant"] == "kept", outcome
assert len(state.load_profiles(path)) == len(names), sorted(state.load_profiles(path))
print("ok: a differently capitalised entry still counts as yours")

# Overwrite is available, but only when asked for.
outcome = plant_library.install(overwrite=True, path=path)
assert set(outcome.values()) == {"written"}, outcome
restored = state.load_profiles(path)
assert restored["Basil"]["moisture_target"] == "dry", restored["Basil"]
assert len(restored) == len(names), sorted(restored)
print("ok: --overwrite replaces them, and does not leave a stray duplicate behind")


# --- the CLI ---

assert plant_library.main([]) == 0
print("ok: listing the library exits cleanly")

print("\nall plant library checks passed")
