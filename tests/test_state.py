import sys, types, json, tempfile
from pathlib import Path

sys.modules["smbus2"] = types.ModuleType("smbus2")  # no I2C on the laptop

from greenthumb import state
from greenthumb.hardware.soil_sensors import SoilSensorHub


def temp_path():
    return Path(tempfile.mkdtemp()) / "state.json"


# --- the store itself ---

p = temp_path()
assert state.load_state(p) == {}, "a missing file reads as empty, not an error"
print("ok: a missing state file is empty rather than fatal")

assert state.save_state({"plants": [{"plant_id": "plant_1", "name": "Fern"}]}, p)
assert state.load_state(p)["plants"][0]["name"] == "Fern"
assert state.load_state(p)["schema_version"] == state.SCHEMA_VERSION
print("ok: state round-trips and is stamped with a schema version")

p.write_text("{not json at all", encoding="utf-8")
assert state.load_state(p) == {}, "corrupt JSON must not raise"
print("ok: a corrupt state file degrades to defaults instead of crashing")

p.write_text('["a list, not an object"]', encoding="utf-8")
assert state.load_state(p) == {}, "wrong top-level type must not raise"
print("ok: a state file of the wrong shape is ignored")

# A write must leave no .tmp files behind, or they accumulate one per save.
p = temp_path()
for _ in range(3):
    state.save_state({"n": 1}, p)
strays = [f for f in p.parent.iterdir() if f.name != p.name]
assert not strays, f"temp files left behind: {strays}"
print("ok: atomic writes leave no stray temp files")


# --- calibration storage ---

p = temp_path()
assert state.load_calibration(p) == {}

state.save_calibration_point(0x36, "dry", 338, samples=474, path=p)
loaded = state.load_calibration(p)
assert loaded == {0x36: {"dry": 338}}, loaded
print("ok: a dry point stores for one sensor")

# The wet endpoint used to live here, measured per probe. It is field capacity,
# which belongs to the mix in the pot rather than to the probe, so writing one
# here is refused outright -- a second, stale copy is how two sources of truth
# start.
try:
    state.save_calibration_point(0x36, "wet", 700, path=p)
except ValueError as error:
    assert "soil or the pot" in str(error), error
else:
    raise AssertionError("stored a wet point in the per-probe calibration")
assert state.load_calibration(p)[0x36] == {"dry": 338}
print("ok: a wet point is refused -- field capacity is not a property of a probe")

raw = json.loads(p.read_text(encoding="utf-8"))
assert "0x36" in raw[state.CALIBRATION_KEY], raw
assert raw[state.CALIBRATION_KEY]["0x36"]["dry_samples"] == 474
print("ok: addresses are stored in readable hex with sample counts")

# Files written before field capacity moved still carry wet keys. They record a
# real measurement, so they are left alone rather than migrated -- and simply
# never read, which is what stops a stale one being picked up.
raw[state.CALIBRATION_KEY]["0x36"]["wet"] = 1004
p.write_text(json.dumps(raw), encoding="utf-8")
assert state.load_calibration(p)[0x36] == {"dry": 338}, state.load_calibration(p)
assert "wet" in json.loads(p.read_text(encoding="utf-8"))[state.CALIBRATION_KEY]["0x36"]
print("ok: a wet key left by an older build is ignored, not read and not deleted")

# Junk entries are skipped individually, not fatally.
raw[state.CALIBRATION_KEY]["not-an-address"] = {"dry": 1}
raw[state.CALIBRATION_KEY]["0x37"] = "not a dict"
raw[state.CALIBRATION_KEY]["0x38"] = {"dry": "banana", "wet": 900}
p.write_text(json.dumps(raw), encoding="utf-8")
loaded = state.load_calibration(p)
assert 0x36 in loaded and 0x37 not in loaded
assert 0x38 not in loaded, "a non-numeric dry point became an entry anyway"
print("ok: malformed calibration entries are skipped, good ones survive")

state.clear_calibration(p)
assert state.load_calibration(p) == {}
print("ok: calibration clears back to defaults")

# Resetting the dry pass must not throw away somebody's measured mix.
state.save_soil("Mix", {"field_capacity_vwc": 30, "wilting_point_vwc": 14}, p)
state.save_soil("Mix", {"field_capacity_raw": 812}, p)
state.save_calibration_point(0x36, "dry", 330, path=p)
state.clear_calibration(p)
assert state.load_soils(p)["Mix"]["field_capacity_raw"] == 812
print("ok: clearing the dry calibration leaves field capacity alone")

# And editing a mix's figures must not throw away its measured capacity. The
# whitelist write replaces the whole entry, so without a merge the editor --
# which knows nothing about raw counts -- silently deletes one.
state.save_soil("Mix", {"field_capacity_vwc": 32, "wilting_point_vwc": 15}, p)
kept = state.load_soils(p)["Mix"]
assert kept["field_capacity_raw"] == 812, kept
assert kept["field_capacity_vwc"] == 32, kept
print("ok: editing a soil's percentages keeps the capacity measured in a pot")


# --- the scale: wilting point to field capacity ---

hub = SoilSensorHub.__new__(SoilSensorHub)  # no I2C bus needed for the maths
hub.addresses = [0x36, 0x37]
hub.raw_dry = 350
hub.calibration = {}
hub.field_capacity = {}
hub.wilting_point = {}

# Neither end falls back to anything, so there is no scale yet.
assert hub.dry_for(0x36) == 350
assert hub.span_for(0x36) is None
assert hub.raw_to_percent(683, 0x36) == -1.0
print("ok: with neither reading there is no scale, and no percentage")

# One end is not enough either: the bottom is no longer the probe in air.
hub.field_capacity = {0x36: 900}
assert hub.span_for(0x36) is None, "used the dry point as the bottom"
assert hub.raw_to_percent(683, 0x36) == -1.0
hub.field_capacity = {}
hub.wilting_point = {0x36: 500}
assert hub.span_for(0x36) is None
print("ok: field capacity or wilting point alone gives no scale")

hub.field_capacity = {0x36: 900}
hub.wilting_point = {0x36: 500}
assert hub.span_for(0x36) == (500, 900)
assert hub.raw_to_percent(700, 0x36) == 50.0
assert hub.raw_to_percent(900, 0x36) == 100.0
assert hub.raw_to_percent(500, 0x36) == 0.0
assert hub.raw_to_percent(950, 0x36) == 100.0, "a pot still draining is clamped"
assert hub.raw_to_percent(420, 0x36) == 0.0, "drier than wilting point is clamped"
assert hub.span_for(0x37) is None, "another pot's readings are not borrowed"
print("ok: the reading is plant-available water, 100 at field capacity and 0 at wilting point")

# The dry point is a check on the probe, not part of the scale.
hub.calibration = {0x36: {"dry": 300}}
assert hub.raw_to_percent(700, 0x36) == 50.0
print("ok: calibrating the dry point does not move the reading")

# A too-narrow or inverted span is refused rather than clamped: clamped, the
# top reads as "just watered", which stops watering for ever.
hub.wilting_point = {0x36: 860}
assert hub.span_for(0x36) is None, "a span under MIN_CALIBRATION_SPAN is not usable"
hub.wilting_point = {0x36: 950}
assert hub.span_for(0x36) is None, "an inverted span is refused, not flipped"
assert hub.raw_to_percent(900, 0x36) == -1.0
print("ok: a too-narrow or inverted span is refused rather than clamped")

print("\nall state and calibration checks passed")


# --- the averaged value must honor calibration too ---
# Regression: the averaged figure used to be computed from an address alone,
# which dropped per-sensor calibration from the one number that decides
# watering. It now takes the plant, because the top of the scale belongs to
# the pot rather than the probe.
import tempfile as _tf
from pathlib import Path as _P

sys.modules.setdefault("spidev", types.ModuleType("spidev"))
from greenthumb.services.automation import GreenThumbAutomation
from greenthumb.history import HistoryStore


class _Hub:
    addresses = [0x36]
    raw_dry = 320
    calibration = {0x36: {"dry": 500}}
    field_capacity: dict = {}
    wilting_point: dict = {}
    dry_for = SoilSensorHub.dry_for
    span_for = SoilSensorHub.span_for
    raw_to_percent = SoilSensorHub.raw_to_percent
    def read_one(self, a): return None


class _Nul:
    mode = "off"; color = (0, 0, 0); brightness = 0
    def __getattr__(self, n): return lambda *a, **k: {}


auto = GreenThumbAutomation(
    _Hub(), _Nul(), _Nul(), _Nul(),
    history=HistoryStore(_P(_tf.mkdtemp()) / "t.db"),
    state_path=_P(_tf.mkdtemp()) / "s.json",
)
auto._history[0x36].extend([600.0] * 5)
pot = auto.plant_for_address(0x36)
assert pot is not None, "no plant claims 0x36, so there is nothing to average for"

# Set on the soil profile, not on the hub. The hub's maps are owned by the
# automation layer and rebuilt from it, so a figure poked straight into the
# hub is wiped by the next sync -- which keeps the two from drifting.
state.save_soil(
    "Test mix", {"field_capacity_raw": 800, "wilting_point_raw": 400}, auto._state_path
)
pot.soil = "Test mix"
auto._sync_scales()
assert auto.sensor_hub.field_capacity == {0x36: 800}
assert auto.sensor_hub.wilting_point == {0x36: 400}
# 600 sits midway between the soil's wilting point of 400 and its field
# capacity of 800. With a wilting point reading, the probe's dry point of 500
# plays no part.
got = auto.percent_for_plant(pot)
assert got == 50.0, f"expected 50.0 between wilting point and field capacity, got {got}"
print("ok: the averaged moisture runs from the soil's wilting point to its field capacity")

# And it is deliberately impossible to get a percentage from an address alone.
assert not hasattr(auto, "smoothed_percent"), (
    "smoothed_percent is back, and anything calling it gets a number computed "
    "against whichever pot happens to share the address"
)
print("ok: there is no way left to turn an address into a percentage on its own")


# --- superseded keys do not live forever ---
# A state file carrying both "zones" and "plants", with different names in
# each, cost real debugging time: only one was live and nothing said which.

p = temp_path()
state.save_state({
    "zones": [{"plant_id": "plant_1", "name": "Basil"}],
    "plants": [{"plant_id": "plant_1", "name": "Rosemary"}],
    "moisture_calibration": {"0x36": {"dry": 330}},
}, p)
state.update_state({"leds": {"mode": "off"}}, p)
after = state.load_state(p)
assert "zones" not in after, after
assert [x["name"] for x in after["plants"]] == ["Rosemary"], after
assert "moisture_calibration" in after, "unrelated keys must survive the sweep"
assert after["leds"] == {"mode": "off"}
print("ok: a superseded key is dropped once its replacement exists")

# The guard that matters: never throw away the only copy. If the replacement
# has not been written yet, the old key is still the live one.
p = temp_path()
state.save_state({"zones": [{"plant_id": "plant_1", "name": "Basil"}]}, p)
state.update_state({"leds": {"mode": "off"}}, p)
after = state.load_state(p)
assert "zones" in after, "dropped the old key while it was still the only copy"
print("ok: an old key is kept while nothing has replaced it")
