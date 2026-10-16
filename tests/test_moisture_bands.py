"""Moisture bands: five descriptions of plant-available water.

A reading is plant-available water, 0-100: 100 at the soil's field capacity
reading and 0 at its wilting point reading. The bands are fixed slices of that.

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
    name = moisture.band_for(step)
    assert name in ORDER, (step, name)
print("ok: every reading from 0 to 100 resolves to exactly one band")


# --- the reading is the usable window ---

# 100 is field capacity and 0 is wilting point, so the bands sit at the same
# percentages for every soil -- the soil is already in the two readings.
assert moisture.band_for(100) == VERY_WET
assert moisture.band_for(0) == VERY_DRY
assert moisture.band_for(60) == MEDIUM
assert moisture.band_for(40) == DRY
print("ok: field capacity is very wet, wilting point is very dry, the middle is the trigger")

assert moisture.depletion(100) == 0.0
assert moisture.depletion(50) == 0.5
assert moisture.depletion(0) == 1.0
print("ok: depletion is the share of plant-available water used up")

# A reading above field capacity means the pot was caught still draining, and
# one below wilting point is drier than the plant can work with. The hub
# clamps, but depletion must not run off the scale even if handed one.
assert moisture.depletion(140) == 0.0
print("ok: readings beyond the top clamp rather than running off the scale")


# --- cannot say is not a band ---

for reading in (-1, -1.0, None):
    assert moisture.band_for(reading) == UNKNOWN, reading
print("ok: an unavailable reading is unknown, not very dry")

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
at_edge = 100 - moisture.BY_NAME[DRY].depleted_from * 100   # 50%

changes = 0
held = moisture.band_for(at_edge + 1.0)
for offset in (0.3, -0.3, 0.2, -0.2, 0.1, -0.1, 0.25, -0.25):
    now = moisture.band_for(at_edge + offset, previous=held)
    if now != held:
        changes += 1
    held = now
assert changes == 0, f"the band changed {changes} times while hovering on the boundary"
print("ok: a reading wobbling on a boundary does not change band")

# But a genuine move across it does change, once.
held = moisture.band_for(at_edge + 2.0)
assert held == MEDIUM, held
drier = moisture.band_for(at_edge - 4.0, previous=held)
assert drier == DRY, drier
print("ok: a reading that properly crosses the boundary does change band")

# And it comes back, rather than sticking in the drier band forever.
back = moisture.band_for(at_edge + 4.0, previous=drier)
assert back == MEDIUM, back
print("ok: and it changes back, so hysteresis is not a one-way latch")

# Without a previous band there is nothing to hold, so the raw answer stands.
assert moisture.band_for(at_edge - 0.1) == DRY
print("ok: with no previous band the reading is taken at face value")

# An unknown previous band must not block a real answer.
assert moisture.band_for(60, previous=UNKNOWN) == MEDIUM
assert moisture.band_for(60, previous="nonsense") == MEDIUM
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
settings.auto_patrol_enabled = False


class _Klip:
    def status(self): return {"ok": True, "position": 0.0, "homed": True, "max_x": 890.0}
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

reading = [0.0]
auto.percent_for_plant = lambda plant: reading[0]

reading[0] = 52.0
assert auto.band_for_plant(pot) == MEDIUM, auto.band_for_plant(pot)

# The medium/dry edge sits at 50%. This is past it, so without the previous
# band threaded through it would read dry -- but it is inside the hysteresis
# margin, so it must not.
reading[0] = 49.0
assert auto.band_for_plant(pot) == MEDIUM, (
    "band_for_plant did not pass the previous band through, so a reading "
    "hovering on a boundary would relabel every poll"
)
print("ok: band_for_plant threads the previous band through, so wobble is damped")

# A real move still gets through, or the damping would just be a freeze.
reading[0] = 40.0
assert auto.band_for_plant(pot) == DRY, auto.band_for_plant(pot)
print("ok: and a genuine change in moisture still changes the band")

# A pot with no soil profile has no wilting point, so no scale: it cannot be
# judged, and must never read as thirsty. Driven through the real reading,
# not the stand-in above, since the stand-in would happily give it a number.
del auto.percent_for_plant
bare = auto.plants[1]
auto._history[bare.sensor_address].extend([400.0] * settings.moisture_window_size)
auto.update_plant_soil(bare.plant_id, "")
assert auto.scale_problem(bare) == "No soil profile set."
assert auto.percent_for_plant(bare) == -1.0
assert auto.band_for_plant(bare) == UNKNOWN
assert auto.thirsty(bare) is False, "a pot with no soil profile was judged thirsty"
print("ok: a pot with no soil profile is unknown and never thirsty")


print("\nall moisture band checks passed")
