"""Moisture bands: five descriptions computed per soil.

The band logic has three places it can go quietly wrong, and each gets its own
section. A gap or overlap at a boundary makes a reading fall in no band or two.
Missing hysteresis makes a reading parked on a threshold flip label every poll.
And collapsing "cannot say" into "very dry" turns an unplugged probe into the
thirstiest plant on the rail, which gets it watered.
"""

import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import moisture
from greenthumb.moisture import BANDS, DRY, MEDIUM, ORDER, UNKNOWN, VERY_DRY, VERY_WET, WET
from greenthumb.soil_library import LIBRARY

PEAT = 0.57
COIR = 0.27


# --- the scale is continuous and ordered ---

assert ORDER == (VERY_WET, WET, MEDIUM, DRY, VERY_DRY), ORDER
assert [band.index for band in BANDS] == [0, 1, 2, 3, 4]
print("ok: five bands, wettest to driest, indexed in order")

# No gap and no overlap: each band starts where the last one ended.
for earlier, later in zip(BANDS, BANDS[1:]):
    assert earlier.depleted_to == later.depleted_from, (earlier.name, later.name)
assert BANDS[0].depleted_from == 0.0 and BANDS[-1].depleted_to == 1.0
print("ok: the bands tile 0 to 1 with no gap and no overlap")

# The conventional MAD trigger is the DRY boundary, not a number invented here.
assert moisture.BY_NAME[DRY].depleted_from == 0.50
print("ok: dry begins at 50% depletion, the standard watering trigger")

# Every reading lands in exactly one band.
for step in range(0, 101):
    name = moisture.band_for(step, PEAT)
    assert name in ORDER, (step, name)
print("ok: every reading from 0 to 100 resolves to exactly one band")


# --- the soil decides, which is the whole point ---

# The same reading means different things in different mixes, because wilting
# point sits in a different place. If this ever stops being true, the bands
# have silently become a fixed table again.
assert moisture.band_for(80, PEAT) == MEDIUM
assert moisture.band_for(80, COIR) == WET
print("ok: 80% is medium in peat and wet in coir, because the soil differs")

assert moisture.band_for(100, PEAT) == VERY_WET
assert moisture.band_for(57, PEAT) == VERY_DRY
print("ok: field capacity is very wet, wilting point is very dry")

# A reading above field capacity means the pot was caught still draining, and
# one below wilting point is drier than the plant can work with. Both are real
# and neither should escape the range.
assert moisture.depletion(140, PEAT) == 0.0
assert moisture.depletion(10, PEAT) == 1.0
print("ok: readings beyond either end clamp rather than running off the scale")

# No band may collapse to nothing, even for the narrowest mix in the library.
for soil in LIBRARY:
    spans = moisture.window_for(soil.wilting_fraction)
    assert len(spans) == len(BANDS), soil.name
    for span in spans:
        width = span["percent_to"] - span["percent_from"]
        assert width > 0.5, f"{soil.name}: {span['name']} is only {width} wide"
    # And they must cover the usable range without crossing.
    assert spans[0]["percent_to"] == 100.0, soil.name
    assert abs(spans[-1]["percent_from"] - soil.wilting_fraction * 100) < 0.5, soil.name
print(f"ok: all {len(LIBRARY)} library soils give five bands, none of them zero-width")


# --- cannot say is not a band ---

for reading in (-1, -1.0, None):
    assert moisture.band_for(reading, PEAT) == UNKNOWN, reading
print("ok: an unavailable reading is unknown, not very dry")

for ratio in (None, 0.0, 1.0, 1.4, -0.2):
    assert moisture.band_for(80, ratio) == UNKNOWN, ratio
print("ok: a missing or impossible soil ratio is unknown, not a guess")

# The consequence that matters: unknown must not read as thirsty. Watering on a
# reading we do not have is the failure this prevents.
assert moisture.is_wetter_or_equal(UNKNOWN, DRY) is True
assert moisture.is_wetter_or_equal(UNKNOWN, VERY_DRY) is True
print("ok: unknown never counts as thirsty, so a dead probe is not watered")


# --- the watering comparison ---

# Thirsty means drier than the target.
assert moisture.is_wetter_or_equal(VERY_WET, DRY) is True
assert moisture.is_wetter_or_equal(MEDIUM, DRY) is True
assert moisture.is_wetter_or_equal(DRY, DRY) is True, "reaching the target is not yet past it"
assert moisture.is_wetter_or_equal(VERY_DRY, DRY) is False
print("ok: a plant is thirsty only once it is drier than its target")

assert moisture.is_wetter_or_equal(DRY, MEDIUM) is False
assert moisture.is_wetter_or_equal(WET, MEDIUM) is True
print("ok: a wetter target makes a plant thirsty sooner")

assert moisture.is_wetter_or_equal(MEDIUM, "nonsense") is True
print("ok: an unrecognised target withholds water rather than dosing on it")


# --- hysteresis ---

# A reading sitting on a boundary must not flip every poll. Walk a value across
# the medium/dry edge in small steps and count how often the band changes.
edge = moisture.BY_NAME[DRY].depleted_from   # 0.50 depleted
bottom = PEAT * 100
window = 100 - bottom
at_edge = 100 - edge * window

changes = 0
held = moisture.band_for(at_edge + 1.0, PEAT)
for offset in (0.3, -0.3, 0.2, -0.2, 0.1, -0.1, 0.25, -0.25):
    now = moisture.band_for(at_edge + offset, PEAT, previous=held)
    if now != held:
        changes += 1
    held = now
assert changes == 0, f"the band changed {changes} times while hovering on the boundary"
print("ok: a reading wobbling on a boundary does not change band")

# But a genuine move across it does change, once.
held = moisture.band_for(at_edge + 2.0, PEAT)
assert held == MEDIUM, held
drier = moisture.band_for(at_edge - 3.0, PEAT, previous=held)
assert drier == DRY, drier
print("ok: a reading that properly crosses the boundary does change band")

# And it comes back, rather than sticking in the drier band forever.
back = moisture.band_for(at_edge + 3.0, PEAT, previous=drier)
assert back == MEDIUM, back
print("ok: and it changes back, so hysteresis is not a one-way latch")

# Without a previous band there is nothing to hold, so the raw answer stands.
assert moisture.band_for(at_edge - 0.1, PEAT) == DRY
print("ok: with no previous band the reading is taken at face value")

# An unknown previous band must not block a real answer.
assert moisture.band_for(80, PEAT, previous=UNKNOWN) == MEDIUM
assert moisture.band_for(80, PEAT, previous="nonsense") == MEDIUM
print("ok: an unusable previous band does not hold back a good reading")


# --- descriptions ---

for name in ORDER:
    assert moisture.describe(name).strip(), name
assert "probe" in moisture.describe(UNKNOWN)
print("ok: every band explains itself, and unknown says what to check")

# --- the automation layer actually uses the hysteresis ---
#
# band_for() takes a previous band, but that is worth nothing unless
# band_for_plant() threads the last reported band back in. Testing band_for in
# isolation cannot tell the difference, so this drives the real method.

from greenthumb.config import settings
from greenthumb.hardware.soil_sensors import unavailable_sample
from greenthumb.services.automation import GreenThumbAutomation
from tests.helpers import CalibrationSurface, give_every_plant_soil, temp_state, temp_store

settings.auto_watering_enabled = False
settings.idle_motion_enabled = False


class _Klip:
    def status(self): return {"ok": True, "position": 0.0, "homed": True, "max_x": 890.0}
    def water_supply_present(self): return True
    def __getattr__(self, n): return lambda *a, **k: {"ok": True}


class _Hub(CalibrationSurface):
    addresses = [0x36, 0x37, 0x38, 0x39]
    def read_one(self, a): return unavailable_sample(a)


class _Nul:
    mode = "off"; color = (0, 0, 0); brightness = 0
    def __getattr__(self, n): return lambda *a, **k: {}


auto = give_every_plant_soil(
    GreenThumbAutomation(
        _Hub(), _Klip(), _Nul(), _Nul(),
        history=temp_store(), state_path=temp_state(),
    )
)
pot = auto.plants[0]

# Peat: wilting at 57% of field capacity, so the medium/dry edge sits at 79%.
reading = [0.0]
auto.percent_for_plant = lambda plant: reading[0]

reading[0] = 80.0
assert auto.band_for_plant(pot) == MEDIUM, auto.band_for_plant(pot)

# The medium/dry edge sits at 78.5%. This is past it, so without the previous
# band threaded through it would read dry -- but it is inside the hysteresis
# margin, so it must not.
reading[0] = 78.0
assert auto.band_for_plant(pot) == MEDIUM, (
    "band_for_plant did not pass the previous band through, so a reading "
    "hovering on a boundary would relabel every poll"
)
print("ok: band_for_plant threads the previous band through, so wobble is damped")

# A real move still gets through, or the damping would just be a freeze.
reading[0] = 70.0
assert auto.band_for_plant(pot) == DRY, auto.band_for_plant(pot)
print("ok: and a genuine change in moisture still changes the band")

# A pot with no soil cannot be judged, and must never read as thirsty.
bare = auto.plants[1]
auto.update_plant_soil(bare.plant_id, "")
assert auto.band_for_plant(bare) == UNKNOWN
assert auto.thirsty(bare) is False, "a pot with no soil was judged thirsty"
print("ok: a pot with no soil is unknown and never thirsty")


print("\nall moisture band checks passed")
