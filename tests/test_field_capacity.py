"""Field capacity: the top of the moisture scale, one reading per soil profile.

This is the half of the scale that could not be looked up. The VWC figures on a
soil give the *shape* of the usable window; this gives its position on the
scale a probe actually reports, so it has to be measured in a real pot.

The reason it moved off the probe: a wet reading is a property of the mix as
much as of the sensor, and the old per-address "wet" endpoint recorded one with
no note of which mix it was taken against. Two pots of different soil wanted
different figures and there was nowhere to put them.

Ordered below by how quietly a wrong value mis-waters. The first few matter
most: a missing field capacity must never produce a plausible percentage,
because nothing downstream can tell a wrong number from a right one -- the
soak check confirms water arrived, not that it was needed.
"""

import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import soil_library, state
from greenthumb.config import settings
from greenthumb.hardware import soil_sensors
from greenthumb.hardware.soil_sensors import MIN_CALIBRATION_SPAN, measure_endpoint
from greenthumb.history import HistoryStore
from greenthumb.models import SensorSample
from greenthumb.services.automation import GreenThumbAutomation
from tests.helpers import CalibrationSurface, give_every_plant_soil, temp_state, temp_store

settings.auto_watering_enabled = False
settings.auto_patrol_enabled = False

DRY = settings.moisture_raw_dry       # 320
CAPACITY = 800


class Klip:
    def status(self): return {"ok": True, "position": 0.0, "homed": True, "max_x": 890.0}
    def __getattr__(self, n): return lambda *a, **k: {"ok": True}


class Hub(CalibrationSurface):
    addresses = [0x36, 0x37, 0x38, 0x39]

    def __init__(self, raw=600.0):
        self.raw = raw
        self.calibration = {}
        self.field_capacity = {}

    def read_one(self, address):
        return SensorSample(address, self.raw_to_percent(self.raw, address), self.raw, 21.0)


class Nul:
    mode = "off"; color = (0, 0, 0); brightness = 0
    def __getattr__(self, n): return lambda *a, **k: {}


def build(path=None, raw=600.0):
    return GreenThumbAutomation(
        Hub(raw), Klip(), Nul(), Nul(),
        history=temp_store(), state_path=path or temp_state(),
    )


def canned(values, errors=0):
    """Stand in for the sampling pass so the decision rules can be driven fast.

    _collect is the seam on purpose: measure_endpoint's real drift, noise and
    span rules then run against known values, without 5s of real I2C per case.
    """
    def fake(hub, seconds, interval, progress=True, addresses=None):
        target = (addresses or hub.addresses)[0]
        return {
            target: {
                "reads": len(values) + errors,
                "errors": errors,
                "values": [float(v) for v in values],
            }
        }
    return fake


def capacity_of(auto, plant):
    """The field capacity a pot is being read against, or None."""
    return auto.sensor_hub.field_capacity.get(plant.sensor_address)


def without_readings(path):
    """Install the library with no field capacity readings on any soil.

    The library may ship default readings; these tests need the unmeasured
    case, so they clear them rather than depending on what ships.
    """
    soil_library.install(path=path)
    for name in state.load_soils(path):
        state.save_soil(name, {"field_capacity_raw": None, "wilting_point_raw": None}, path)


# --- 1. no field capacity is never a number ---

auto = build()
pot = auto.plants[0]
assert capacity_of(auto, pot) is None
auto._history[pot.sensor_address].extend([600.0] * 10)

# 600 against the old configured pair (320 dry, 800 wet) would have been a
# perfectly plausible 58%. Nothing about it would have looked wrong.
assert auto.percent_for_plant(pot) == -1.0, auto.percent_for_plant(pot)
print("ok: a full window of good readings with no field capacity is -1, not a percentage")

assert auto.sensor_hub.span_for(pot.sensor_address) is None
print("ok: and there is no span to compute one from")


# --- 2. that -1 reaches "not watered" ---

shared = temp_state()
auto = build(shared)
without_readings(shared)
pot = auto.plants[0]
auto.update_plant_soil(pot.plant_id, "Rich & Retentive Mix")
auto._history[pot.sensor_address].extend([600.0] * 10)

assert capacity_of(auto, pot) is None, "a soil profile with no reading handed one over"
assert auto._moisture_level(pot) is None, auto._moisture_level(pot)
assert auto.thirsty(pot) is False, "a pot with no field capacity was judged thirsty"
print("ok: no field capacity means unknown, and unknown is never thirsty")


# --- 3. field capacity belongs to the soil profile, not the pot ---

auto = build(temp_state(), raw=600.0)
without_readings(auto._state_path)
state.save_soil("Rich & Retentive Mix", {"field_capacity_raw": 700}, auto._state_path)
state.save_soil("Fast-Draining Mix", {"field_capacity_raw": 1000}, auto._state_path)
first, second = auto.plants[0], auto.plants[1]
auto.update_plant_soil(first.plant_id, "Rich & Retentive Mix")
auto.update_plant_soil(second.plant_id, "Fast-Draining Mix")
for plant in (first, second):
    auto._history[plant.sensor_address].extend([600.0] * 10)

assert (capacity_of(auto, first), capacity_of(auto, second)) == (700, 1000)
assert auto.percent_for_plant(first) > auto.percent_for_plant(second)
print(
    f"ok: the same raw count is {auto.percent_for_plant(first)}% in one soil and "
    f"{auto.percent_for_plant(second)}% in another"
)

# Moving a pot to another soil profile moves it onto that scale at once.
auto.update_plant_soil(second.plant_id, "Rich & Retentive Mix")
assert capacity_of(auto, second) == 700
assert auto.percent_for_plant(second) == auto.percent_for_plant(first)
auto.update_plant_soil(second.plant_id, "")
assert capacity_of(auto, second) is None, "a pot with no soil profile kept a scale"
print("ok: changing a pot's soil profile changes its scale, and clearing it leaves none")

# A pot has no field capacity of its own any more. A state file from a build
# that had one must not bring it back.
assert not hasattr(first, "field_capacity_raw")
assert not hasattr(auto, "calibrate_plant_field_capacity")
assert not hasattr(auto, "clear_plant_field_capacity")
legacy = temp_state()
one = build(legacy)
one._persist()
blob = state.load_state(legacy)
blob["plants"][0].update(field_capacity_raw=915, field_capacity_source="pot")
state.save_state(blob, legacy)
again = build(legacy)
assert again.sensor_hub.field_capacity == {}, again.sensor_hub.field_capacity
print("ok: there is no per-pot field capacity, and an old state file cannot revive one")

# A file written by an older build still carries a per-address "wet". It must
# not come back into play either.
legacy = temp_state()
state.save_state({"moisture_calibration": {"0x36": {"dry": 320, "wet": 1016}}}, legacy)
auto = build(legacy)
pot = auto.plants[0]
auto._history[pot.sensor_address].extend([600.0] * 10)
assert auto.sensor_hub.dry_for(0x36) == 320, "the dry half should still be read"
assert auto.percent_for_plant(pot) == -1.0, "a stale wet endpoint was used as a scale"
print("ok: a wet endpoint left by an older build is ignored, not revived")


# --- 4. a span too narrow or inverted is refused, not clamped ---
#
# Clamped, the top reads as "just watered", which stops watering for ever.

auto = build(temp_state())
without_readings(auto._state_path)
pot = auto.plants[0]
auto.update_plant_soil(pot.plant_id, "Rich & Retentive Mix")
auto._history[pot.sensor_address].extend([600.0] * 10)


def set_scale(capacity, wilting):
    state.save_soil(
        "Rich & Retentive Mix",
        {"field_capacity_raw": capacity, "wilting_point_raw": wilting},
        auto._state_path,
    )
    auto._sync_scales()


set_scale(760 + MIN_CALIBRATION_SPAN - 1, 760)
assert auto.percent_for_plant(pot) == -1.0, auto.percent_for_plant(pot)
assert "too close" in auto.scale_problem(pot), auto.scale_problem(pot)

set_scale(400, 760)  # below the wilting point entirely
assert auto.percent_for_plant(pot) == -1.0, auto.percent_for_plant(pot)

set_scale(760 + MIN_CALIBRATION_SPAN, 760)
assert auto.percent_for_plant(pot) >= 0.0

# An estimated wilting point narrows the same way: a field capacity barely
# above the air reading leaves no room.
set_scale(DRY + 40, None)
assert auto.percent_for_plant(pot) == -1.0, auto.percent_for_plant(pot)
print(f"ok: a span under {MIN_CALIBRATION_SPAN} points is refused rather than clamped")


# --- 5. measuring a soil profile, and who reads against it ---

original_collect = soil_sensors._collect
shared = temp_state()
auto = build(shared)
without_readings(shared)
first, second, third = auto.plants[0], auto.plants[1], auto.plants[2]
auto.update_plant_soil(first.plant_id, "Rich & Retentive Mix")
auto.update_plant_soil(second.plant_id, "Rich & Retentive Mix")
auto.update_plant_soil(third.plant_id, "Fast-Draining Mix")

try:
    soil_sensors._collect = canned([CAPACITY] * 40)
    outcome = auto.calibrate_soil_field_capacity("Rich & Retentive Mix", first.plant_id)
    assert outcome["written"] is True, outcome
    assert outcome["value"] == CAPACITY, outcome
    assert outcome["measured_with"] == first.name

    assert sorted(outcome["inherited_by"]) == sorted([first.name, second.name]), outcome
    assert capacity_of(auto, first) == CAPACITY
    assert capacity_of(auto, second) == CAPACITY
    assert capacity_of(auto, third) is None, "a pot of a different soil took it anyway"
    print("ok: measuring a soil profile applies it to every pot using it, and no others")

    stored = state.load_soils(shared)["Rich & Retentive Mix"]
    assert stored["field_capacity_raw"] == CAPACITY, stored
    assert stored["field_capacity_address"] == first.sensor_address
    assert stored["field_capacity_measured_at"]
    # The looked-up figures are still there: a write of one must not drop the
    # other.
    assert stored["field_capacity_vwc"] == 50, stored
    print("ok: it is stored on the soil profile beside the % figures, not instead of them")

    fourth = auto.plants[3]
    auto.update_plant_soil(fourth.plant_id, "Rich & Retentive Mix")
    assert capacity_of(auto, fourth) == CAPACITY, "a pot filled later did not take it"
    print("ok: a pot filled with a measured soil later reads against it too")

    # Re-measuring moves every pot using it.
    soil_sensors._collect = canned([900.0] * 40)
    auto.calibrate_soil_field_capacity("Rich & Retentive Mix", second.plant_id)
    assert [capacity_of(auto, p) for p in (first, second, fourth)] == [900, 900, 900]
    print("ok: re-measuring moves every pot using the soil profile")

    # --- 6. a rejected run stores nothing ---
    #
    # Asserted against the state file, not the return value: a version that
    # reports the reason and writes anyway passes the weaker check.

    before = dict(state.load_soils(shared)["Fast-Draining Mix"])

    soil_sensors._collect = canned([400.0] * 20 + [1200.0] * 20)   # drifting
    drifted = auto.calibrate_soil_field_capacity("Fast-Draining Mix", third.plant_id)
    assert drifted["written"] is False and drifted["reason"], drifted

    soil_sensors._collect = canned([300.0, 1400.0] * 20)           # noisy
    noisy = auto.calibrate_soil_field_capacity("Fast-Draining Mix", third.plant_id)
    assert noisy["written"] is False and noisy["reason"], noisy

    soil_sensors._collect = canned([DRY + 10] * 40)                # still in air
    in_air = auto.calibrate_soil_field_capacity("Fast-Draining Mix", third.plant_id)
    assert in_air["written"] is False, in_air
    assert "dry point" in in_air["reason"], in_air["reason"]

    # Well *below* the dry point, which a direction-blind check would wave
    # through as "plenty of separation". It means the dry pass was taken in
    # soil, or the probe is faulty.
    soil_sensors._collect = canned([DRY - 170] * 40)
    inverted = auto.calibrate_soil_field_capacity("Fast-Draining Mix", third.plant_id)
    assert inverted["written"] is False, inverted
    assert "dry point" in inverted["reason"], inverted["reason"]

    assert state.load_soils(shared)["Fast-Draining Mix"] == before, "a rejected run wrote"
    assert capacity_of(auto, third) is None
    print("ok: a run rejected for drift, noise or being in air stores nothing at all")

finally:
    soil_sensors._collect = original_collect


# --- 7. _collect reads only what it was asked for ---

class Counting(Hub):
    def __init__(self):
        super().__init__()
        self.seen = []

    def read_one(self, address):
        self.seen.append(address)
        return super().read_one(address)


counting = Counting()
stats = soil_sensors._collect(counting, 0, 0.0, progress=False, addresses=[0x37])
assert set(stats) == {0x37}, sorted(stats)
assert 0x36 not in stats, "an unasked-for address got a slot in the results"
everything = soil_sensors._collect(counting, 0, 0.0, progress=False)
assert set(everything) == set(counting.addresses)
print("ok: a single-address pass scopes to that address, and the default still covers all")


# --- 8. the status bar says why it went quiet, and wilting point ---

shared = temp_state()
auto = build(shared)
without_readings(shared)
for plant in auto.plants:
    auto.update_plant_soil(plant.plant_id, "Rich & Retentive Mix")
    auto._history[plant.sensor_address].extend([600.0] * 10)
auto.auto_watering_enabled = True

status = auto.system_status()
assert status["level"] == "attention", status
assert "field capacity" in status["message"], status["message"]
assert "Rich & Retentive Mix" in status["message"], status["message"]
assert "happy" not in status["message"], (
    "every pot is unjudgeable and the status bar said they were happy"
)
print("ok: pots held for want of a field capacity are named, not reported as happy")

state.save_soil("Rich & Retentive Mix", {"field_capacity_raw": CAPACITY}, shared)
auto._sync_scales()
# Field capacity is enough for a soil profile with its % figures: wilting point
# is estimated the same fraction of the way up from the probe's air reading as
# wilting point % is of field capacity % (17.5 / 50 for Rich & Retentive).
expected = round(DRY + (CAPACITY - DRY) * 17.5 / 50)
assert auto.sensor_hub.wilting_point[auto.plants[0].sensor_address] == expected, (
    auto.sensor_hub.wilting_point
)
assert auto.scale_problem(auto.plants[0]) is None, auto.scale_problem(auto.plants[0])
assert "held" not in auto.system_status()["message"], auto.system_status()["message"]
assert auto.wilting_point_source(auto.plants[0]) == "estimated"
print(f"ok: field capacity alone is enough; wilting point is estimated at {expected}")

# Each pot estimates from its own probe's air reading, not a shared one.
auto.sensor_hub.calibration = {auto.plants[1].sensor_address: {"dry": 400}}
auto._sync_scales()
assert auto.sensor_hub.wilting_point[auto.plants[1].sensor_address] == round(
    400 + (CAPACITY - 400) * 17.5 / 50
)
assert auto.sensor_hub.wilting_point[auto.plants[0].sensor_address] == expected
auto.sensor_hub.calibration = {}
auto._sync_scales()
print("ok: the estimate is per probe, from that probe's air reading")

# A wilting point reading, when the soil profile has one, wins over the estimate.
auto.save_soil("Rich & Retentive Mix", 50, 17.5, field_capacity_raw=CAPACITY, wilting_point_raw=600)
assert auto.sensor_hub.wilting_point[auto.plants[0].sensor_address] == 600
assert auto.wilting_point_source(auto.plants[0]) == "reading"
print("ok: a wilting point reading overrides the estimate")

# Without the % figures there is nothing to estimate from, so it is held again.
auto.save_soil("Rich & Retentive Mix", None, None, field_capacity_raw=CAPACITY, wilting_point_raw=None)
assert "held" in auto.system_status()["message"], auto.system_status()["message"]
assert "wilting point" in auto.scale_problem(auto.plants[0]), auto.scale_problem(auto.plants[0])
print("ok: with neither the % figures nor a reading, watering is held, and says why")


# --- 9. it never enters a plant profile ---

assert not any(f.startswith("field_capacity") for f in state.PROFILE_FIELDS)
print("ok: no field capacity field is part of a plant profile")

shared = temp_state()
auto = build(shared)
without_readings(shared)
state.save_soil("Fast-Draining Mix", {"field_capacity_raw": 915}, shared)
first, second = auto.plants[0], auto.plants[1]
auto.update_plant_soil(first.plant_id, "Fast-Draining Mix")
auto.update_plant_name(first.plant_id, "Fern")
first.preferred_soil = "Fast-Draining Mix"
auto.save_plant_profile(first.plant_id)

saved = state.load_profiles(shared)["Fern"]
assert not any(k.startswith("field_capacity") for k in saved), saved
# Loading it switches the pot to the plant's preferred soil profile, and the
# scale then comes from that soil profile -- not from the profile itself.
auto.apply_plant_profile(second.plant_id, "Fern")
assert second.soil == "Fast-Draining Mix", second.soil
assert capacity_of(auto, second) == 915, capacity_of(auto, second)
state.save_soil("Fast-Draining Mix", {"field_capacity_raw": 870}, shared)
auto._sync_scales()
assert capacity_of(auto, second) == 870, "the scale traveled with the plant profile"
print("ok: a plant profile carries no field capacity; the pot reads its soil profile's")


# --- 10. the chart does not draw "cannot say" as bone dry ---

store = HistoryStore(temp_store().path)
store.record_readings(
    [SensorSample(0x36, -1.0, 600.0, 21.0), SensorSample(0x37, 55.0, 650.0, 21.0)],
    at=1_000_000,
)
_, _, plotted = store.series([0x36, 0x37], hours=24, now=1_000_060)
kept = [v for v in plotted[0x37]["moisture_percent"] if v is not None]
dropped = [v for v in plotted[0x36]["moisture_percent"] if v is not None]
assert kept == [55.0], kept
assert dropped == [], dropped
print("ok: a reading with no usable percentage is left off the chart, not averaged in at zero")


# --- 11. the old wet route is refused, readably ---

auto = build()
try:
    auto.calibrate_moisture("wet")
except ValueError as error:
    assert "field-capacity" in str(error), error
else:
    raise AssertionError("ran a wet pass through the per-probe calibration")
print("ok: a stale caller asking for a wet pass is told where field capacity lives")


# --- 12. a bus address no pot claims ---

class Extra(Hub):
    addresses = [0x36, 0x3A]


auto = GreenThumbAutomation(
    Extra(), Klip(), Nul(), Nul(), history=temp_store(), state_path=temp_state()
)
rows = {row["sensor_address"]: row for row in auto.read_sensors()}
assert rows[0x3A]["plant_id"] is None
assert rows[0x36]["plant_id"] == "plant_1"
print("ok: an address no pot claims reports no plant, rather than borrowing one")


# --- 13. the fixture every watering test leans on ---

auto = give_every_plant_soil(build(temp_state()))
for plant in auto.plants:
    assert auto.sensor_hub.span_for(plant.sensor_address) is not None
print("ok: give_every_plant_soil leaves every pot judgeable, so watering tests mean something")


print("\nall field capacity checks passed")
