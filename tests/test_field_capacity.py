"""Field capacity: the top of the moisture scale, measured per soil mix.

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
outlet sensor confirms water arrived, not that it was needed.
"""

import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import moisture, soil_library, state
from greenthumb.config import settings
from greenthumb.hardware import soil_sensors
from greenthumb.hardware.soil_sensors import MIN_CALIBRATION_SPAN, measure_endpoint
from greenthumb.history import HistoryStore
from greenthumb.models import SensorSample
from greenthumb.services.automation import GreenThumbAutomation
from tests.helpers import CalibrationSurface, give_every_plant_soil, temp_state, temp_store

settings.auto_watering_enabled = False
settings.idle_motion_enabled = False

DRY = settings.moisture_raw_dry       # 320
CAPACITY = 800


class Klip:
    def status(self): return {"ok": True, "position": 0.0, "homed": True, "max_x": 890.0}
    def water_supply_present(self): return True
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


# --- 1. no field capacity is never a number ---

auto = build()
pot = auto.plants[0]
assert pot.field_capacity_raw is None
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
soil_library.install(path=shared)
pot = auto.plants[0]
auto.update_plant_soil(pot.plant_id, "Peat potting mix")
auto._history[pot.sensor_address].extend([600.0] * 10)

assert pot.field_capacity_raw is None, "a mix with no measured capacity handed one over"
assert auto.band_for_plant(pot) == moisture.UNKNOWN, auto.band_for_plant(pot)
assert auto.thirsty(pot) is False, "a pot with no field capacity was judged thirsty"
print("ok: no field capacity means unknown, and unknown is never thirsty")


# --- 3. the percentage belongs to the pot, not the address ---

auto = build(temp_state(), raw=600.0)
first, second = auto.plants[0], auto.plants[1]
for plant in (first, second):
    auto._history[plant.sensor_address].extend([600.0] * 10)

first.field_capacity_raw = 700
second.field_capacity_raw = 1000
auto._sync_field_capacity()

assert auto.percent_for_plant(first) != auto.percent_for_plant(second)
assert auto.percent_for_plant(first) > auto.percent_for_plant(second)
print(
    f"ok: the same raw count is {auto.percent_for_plant(first)}% in one pot and "
    f"{auto.percent_for_plant(second)}% in another"
)

# A file written by an older build still carries a per-address "wet". It must
# not come back into play, or the pot is scaled against a figure taken in
# whatever mix happened to be in it at the time.
legacy = temp_state()
raw = {"moisture_calibration": {"0x36": {"dry": 320, "wet": 1016}}}
state.save_state(raw, legacy)
auto = build(legacy)
pot = auto.plants[0]
auto._history[pot.sensor_address].extend([600.0] * 10)
assert auto.sensor_hub.dry_for(0x36) == 320, "the dry half should still be read"
assert auto.percent_for_plant(pot) == -1.0, "a stale wet endpoint was used as a scale"
print("ok: a wet endpoint left by an older build is ignored, not revived")


# --- 4. a span too narrow or inverted is refused, not clamped ---
#
# Field capacity is measured on one probe and used by the others, so a pot
# whose own dry point sits near that figure has no usable scale. The old code
# clamped, and the top of that clamp reads as "just watered" -- which stops
# watering for ever.

auto = build(temp_state())
pot = auto.plants[0]
auto._history[pot.sensor_address].extend([600.0] * 10)
auto.sensor_hub.calibration = {pot.sensor_address: {"dry": 760}}

pot.field_capacity_raw = 760 + MIN_CALIBRATION_SPAN - 1
auto._sync_field_capacity()
assert auto.percent_for_plant(pot) == -1.0, auto.percent_for_plant(pot)

pot.field_capacity_raw = 400  # below the dry point entirely
auto._sync_field_capacity()
assert auto.percent_for_plant(pot) == -1.0, auto.percent_for_plant(pot)

pot.field_capacity_raw = 760 + MIN_CALIBRATION_SPAN
auto._sync_field_capacity()
assert auto.percent_for_plant(pot) >= 0.0
print(f"ok: a span under {MIN_CALIBRATION_SPAN} points is refused rather than clamped")


# --- 5. measuring a mix, and what inherits it ---

original_collect = soil_sensors._collect
shared = temp_state()
auto = build(shared)
soil_library.install(path=shared)
first, second, third = auto.plants[0], auto.plants[1], auto.plants[2]
auto.update_plant_soil(first.plant_id, "Peat potting mix")
auto.update_plant_soil(second.plant_id, "Peat potting mix")
auto.update_plant_soil(third.plant_id, "Coco coir")

try:
    soil_sensors._collect = canned([CAPACITY] * 40)
    outcome = auto.calibrate_soil_field_capacity("Peat potting mix", first.plant_id)
    assert outcome["written"] is True, outcome
    assert outcome["value"] == CAPACITY, outcome
    assert outcome["measured_with"] == first.name

    # Both peat pots take it; the coir one does not.
    assert sorted(outcome["inherited_by"]) == sorted([first.name, second.name]), outcome
    assert first.field_capacity_raw == CAPACITY
    assert second.field_capacity_raw == CAPACITY
    assert third.field_capacity_raw is None, "a pot of a different mix inherited anyway"
    assert first.field_capacity_source == "soil"
    print("ok: measuring a mix applies it to every pot filled with that mix, and no others")

    # Stored on the soil, so a pot filled with it later inherits too.
    stored = state.load_soils(shared)["Peat potting mix"]
    assert stored["field_capacity_raw"] == CAPACITY, stored
    assert stored["field_capacity_address"] == first.sensor_address
    assert stored["field_capacity_measured_at"]
    # And the looked-up figures are still there: the two describe different
    # things and a write of one must not drop the other.
    assert stored["field_capacity_vwc"] == 28, stored
    print("ok: it is stored on the mix beside the published figures, not instead of them")

    fourth = auto.plants[3]
    auto.update_plant_soil(fourth.plant_id, "Peat potting mix")
    assert fourth.field_capacity_raw == CAPACITY, "a pot filled later did not inherit"
    assert fourth.field_capacity_source == "soil"
    print("ok: a pot filled with a measured mix inherits when the mix is set")

    # --- 6. a pot that measures its own keeps it ---

    soil_sensors._collect = canned([900.0] * 40)
    own = auto.calibrate_plant_field_capacity(second.plant_id)
    assert own["written"] is True, own
    assert second.field_capacity_raw == 900
    assert second.field_capacity_source == "pot"
    print("ok: a pot can measure its own field capacity, overriding the mix")

    # Re-measuring the mix must not overwrite it: a per-pot figure is more
    # specific, and losing it silently is the whole hazard.
    soil_sensors._collect = canned([CAPACITY] * 40)
    again = auto.calibrate_soil_field_capacity("Peat potting mix", first.plant_id)
    assert second.name not in again["inherited_by"], again
    assert second.field_capacity_raw == 900, "the mix overwrote a measured pot"
    assert first.field_capacity_raw == CAPACITY
    print("ok: re-measuring the mix leaves a pot that measured its own alone")

    # --- 7. an override survives the same mix and is dropped by a different one ---

    auto.update_plant_soil(second.plant_id, "peat potting mix")
    assert second.field_capacity_raw == 900, "re-saving the same mix dropped the override"
    assert second.field_capacity_source == "pot"
    print("ok: re-assigning the same mix keeps a measured figure")

    auto.update_plant_soil(second.plant_id, "Coco coir")
    assert second.field_capacity_source != "pot", (
        "a figure measured in peat survived a repot into coir, so the pot now "
        "reads against a mix it does not contain"
    )
    assert second.field_capacity_raw is None, second.field_capacity_raw
    print("ok: assigning a different mix drops a figure measured in the old one")

    # --- 8. clearing an override goes back to inheriting ---

    auto.update_plant_soil(second.plant_id, "Peat potting mix")
    soil_sensors._collect = canned([950.0] * 40)
    auto.calibrate_plant_field_capacity(second.plant_id)
    assert second.field_capacity_raw == 950
    cleared = auto.clear_plant_field_capacity(second.plant_id)
    assert cleared["field_capacity_source"] == "soil", cleared
    assert second.field_capacity_raw == CAPACITY, second.field_capacity_raw
    print("ok: clearing a pot's own figure falls back to the mix's, rather than to nothing")

    # --- 9. a rejected run stores nothing ---
    #
    # Asserted against the state file, not the return value: a version that
    # reports the reason and writes anyway passes the weaker check.

    before_soil = dict(state.load_soils(shared)["Coco coir"])
    before_pot = third.field_capacity_raw

    soil_sensors._collect = canned([400.0] * 20 + [1200.0] * 20)   # drifting
    drifted = auto.calibrate_soil_field_capacity("Coco coir", third.plant_id)
    assert drifted["written"] is False and drifted["reason"], drifted

    soil_sensors._collect = canned([300.0, 1400.0] * 20)           # noisy
    noisy = auto.calibrate_soil_field_capacity("Coco coir", third.plant_id)
    assert noisy["written"] is False and noisy["reason"], noisy

    soil_sensors._collect = canned([DRY + 10] * 40)                # still in air
    in_air = auto.calibrate_plant_field_capacity(third.plant_id)
    assert in_air["written"] is False, in_air
    assert "dry point" in in_air["reason"], in_air["reason"]

    # Well *below* the dry point, which a direction-blind check would wave
    # through as "plenty of separation". It is not a field capacity at all --
    # it means the dry pass was taken in soil, or the probe is faulty -- and
    # storing it leaves the pot reading nothing with no hint as to why.
    soil_sensors._collect = canned([DRY - 170] * 40)
    inverted = auto.calibrate_plant_field_capacity(third.plant_id)
    assert inverted["written"] is False, inverted
    assert "dry point" in inverted["reason"], inverted["reason"]

    assert state.load_soils(shared)["Coco coir"] == before_soil, "a rejected run wrote to the mix"
    assert third.field_capacity_raw == before_pot, "a rejected run wrote to the pot"
    print("ok: a run rejected for drift, noise or being in air stores nothing at all")

finally:
    soil_sensors._collect = original_collect


# --- 10. _collect reads only what it was asked for ---

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


# --- 11. the status bar says why it went quiet ---

shared = temp_state()
auto = build(shared)
soil_library.install(path=shared)
for plant in auto.plants:
    auto.update_plant_soil(plant.plant_id, "Peat potting mix")
    auto._history[plant.sensor_address].extend([600.0] * 10)
auto.auto_watering_enabled = True

status = auto.system_status()
assert status["level"] == "attention", status
assert "field capacity" in status["message"], status["message"]
assert "Peat potting mix" in status["message"], status["message"]
assert "happy" not in status["message"], (
    "every pot is unjudgeable and the status bar said they were happy -- which "
    "is what an existing planter looks like the moment field capacity moved"
)
print("ok: pots held for want of a field capacity are named, not reported as happy")

for plant in auto.plants:
    plant.field_capacity_raw = CAPACITY
auto._sync_field_capacity()
assert "field capacity" not in auto.system_status()["message"]
print("ok: and the warning clears once it is measured")


# --- 12. state round-trip, and the type guards ---

shared = temp_state()
auto = build(shared)
soil_library.install(path=shared)
pot = auto.plants[0]
auto.update_plant_soil(pot.plant_id, "Coco coir")
pot.field_capacity_raw = 915
pot.field_capacity_source = "pot"
pot.field_capacity_soil = "Coco coir"
pot.field_capacity_measured_at = "2026-10-09T12:00:00"
pot.field_capacity_address = 0x36
auto._persist()

restored = build(shared)
kept = restored.get_plant(pot.plant_id)
assert kept.field_capacity_raw == 915
assert kept.field_capacity_source == "pot"
assert kept.field_capacity_soil == "Coco coir"
assert kept.field_capacity_measured_at == "2026-10-09T12:00:00"
assert kept.field_capacity_address == 0x36
assert restored.sensor_hub.field_capacity[0x36] == 915, "restored but never synced to the hub"
print("ok: every field survives a restart, and reaches the hub")

for bad in ("banana", True, None, {}, []):
    fresh = temp_state()
    one = build(fresh)
    one.plants[0].field_capacity_raw = 800
    one._persist()
    blob = state.load_state(fresh)
    blob["plants"][0]["field_capacity_raw"] = bad
    state.save_state(blob, fresh)
    again = build(fresh)
    assert again.get_plant(one.plants[0].plant_id).field_capacity_raw is None, bad
print("ok: an unusable stored figure is dropped rather than coerced -- True included")

fresh = temp_state()
one = build(fresh)
one.plants[0].field_capacity_source = "pot"
one._persist()
blob = state.load_state(fresh)
blob["plants"][0]["field_capacity_source"] = "moon"
state.save_state(blob, fresh)
assert build(fresh).plants[0].field_capacity_source == ""
print("ok: an unrecognised source falls back to unset")


# --- 13. it never enters a saved plant ---

assert "field_capacity_raw" not in state.PROFILE_FIELDS
assert not any(f.startswith("field_capacity") for f in state.PROFILE_FIELDS)
print("ok: no field capacity field is part of a saved plant")

shared = temp_state()
auto = build(shared)
soil_library.install(path=shared)
first, second = auto.plants[0], auto.plants[1]
auto.update_plant_soil(first.plant_id, "Coco coir")
first.field_capacity_raw = 915
first.field_capacity_source = "pot"
auto.update_plant_name(first.plant_id, "Fern")
auto.save_plant_profile(first.plant_id)

saved = state.load_profiles(shared)["Fern"]
assert not any(k.startswith("field_capacity") for k in saved), saved
auto.apply_plant_profile(second.plant_id, "Fern")
assert second.field_capacity_raw is None, (
    "loading a saved plant carried a figure measured in another pot's soil"
)
print("ok: a saved plant carries no field capacity, and loading one applies none")

# A hand-written entry containing the key must not apply it either.
blob = state.load_state(shared)
blob["plant_profiles"]["Smuggled"] = {
    "moisture_target": "dry",
    "watering_volume_ml": 100,
    "field_capacity_raw": 1234,
}
state.save_state(blob, shared)
auto.apply_plant_profile(second.plant_id, "Smuggled")
assert second.field_capacity_raw is None, second.field_capacity_raw
print("ok: and a profile with one written into it by hand is still ignored")


# --- 14. the chart does not draw "cannot say" as bone dry ---

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


# --- 15. the old wet route is refused, readably ---

auto = build()
try:
    auto.calibrate_moisture("wet")
except ValueError as error:
    assert "field-capacity" in str(error), error
else:
    raise AssertionError("ran a wet pass through the per-probe calibration")
print("ok: a stale caller asking for a wet pass is told where field capacity lives")


# --- 16. a bus address no pot claims ---

class Extra(Hub):
    addresses = [0x36, 0x3A]


auto = GreenThumbAutomation(
    Extra(), Klip(), Nul(), Nul(), history=temp_store(), state_path=temp_state()
)
rows = {row["sensor_address"]: row for row in auto.read_sensors()}
assert rows[0x3A]["plant_id"] is None
assert rows[0x3A]["moisture_percent_avg"] == -1.0
assert rows[0x36]["plant_id"] == "plant_1"
print("ok: an address no pot claims reports no plant and no average, rather than borrowing one")


# --- 17. the fixture every watering test leans on ---

auto = give_every_plant_soil(build(temp_state()))
for plant in auto.plants:
    assert plant.field_capacity_raw is not None, plant.plant_id
    assert auto.sensor_hub.span_for(plant.sensor_address) is not None
print("ok: give_every_plant_soil leaves every pot judgeable, so watering tests mean something")


print("\nall field capacity checks passed")
