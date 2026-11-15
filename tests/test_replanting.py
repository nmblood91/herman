"""A new plant in a pot starts its own line on the History chart.

Readings are stored by probe, and a probe stays with its pot. So without a
cutoff, the plant that just went in is drawn with the last one's weeks of
readings and waterings behind it. Loading a different plant profile onto the
pot marks the moment; nothing before it is charted for that pot, and nothing
is deleted.
"""

import sys
import time
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import plant_library, soil_library
from greenthumb.config import settings
from greenthumb.hardware.soil_sensors import unavailable_sample
from greenthumb.models import SensorSample
from greenthumb.services.automation import GreenThumbAutomation
from tests.helpers import CalibrationSurface, temp_state, temp_store

settings.auto_watering_enabled = False

HOUR = 3600


class Hub(CalibrationSurface):
    addresses = [0x36, 0x37, 0x38, 0x39]
    def read_one(self, a): return unavailable_sample(a)


class Nul:
    mode = "off"; color = (0, 0, 0); brightness = 0; is_running = False
    def __getattr__(self, n): return lambda *a, **k: {}


def build(path):
    return GreenThumbAutomation(Hub(), Nul(), Nul(), Nul(), history=temp_store(), state_path=path)


def line(auto, plant_id, hours=24):
    history = auto.get_history(hours)
    plant = next(p for p in history["plants"] if p["plant_id"] == plant_id)
    return [value for value in plant["moisture_percent"] if value is not None]


def doses(auto, plant_id, hours=24):
    return [d["trigger"] for d in auto.get_history(hours)["waterings"] if d["plant_id"] == plant_id]


path = temp_state()
soil_library.install(path=path)
plant_library.install(path=path)
auto = build(path)
FIRST, SECOND = [entry["name"] for entry in auto.list_plant_profiles()[:2]]

pot, other = auto.get_plant("plant_1"), auto.get_plant("plant_2")
auto.apply_plant_profile("plant_1", FIRST)
auto.apply_plant_profile("plant_2", FIRST)
# As though both went in long ago, so the readings below are theirs.
pot.planted_at = other.planted_at = int(time.time()) - 30 * 24 * HOUR

now = int(time.time())
for hours_ago in (10, 8, 6):
    auto.history.record_readings(
        [SensorSample(pot.sensor_address, 20.0, 400.0, 21.0),
         SensorSample(other.sensor_address, 30.0, 450.0, 21.0)],
        at=now - hours_ago * HOUR,
    )
auto.history.record_watering("plant_1", 100, "old", at=now - 7 * HOUR)
auto.history.record_watering("plant_2", 100, "old", at=now - 7 * HOUR)
assert line(auto, "plant_1") == [20.0, 20.0, 20.0] and doses(auto, "plant_1") == ["old"]


# --- the same plant again is not a new plant ---

before = pot.planted_at
auto.apply_plant_profile("plant_1", FIRST)
auto.update_plant_name("plant_1", "Kitchen window")
assert pot.planted_at == before
assert line(auto, "plant_1") == [20.0, 20.0, 20.0] and doses(auto, "plant_1") == ["old"]
print("ok: reloading the same profile, or renaming the pot, keeps its history")


# --- a different plant starts from now ---

auto.apply_plant_profile("plant_1", SECOND)
assert abs(pot.planted_at - time.time()) < 5, pot.planted_at
assert line(auto, "plant_1") == [] and doses(auto, "plant_1") == []
print("ok: a different plant's chart starts empty")

assert line(auto, "plant_2") == [30.0, 30.0, 30.0] and doses(auto, "plant_2") == ["old"]
print("ok: the other pots keep theirs")

auto.history.record_readings([SensorSample(pot.sensor_address, 55.0, 600.0, 21.0)])
auto.history.record_watering("plant_1", 100, "new")
assert line(auto, "plant_1") == [55.0] and doses(auto, "plant_1") == ["new"]
print("ok: what the new plant does from here on is charted")

kept = auto.history.raw_readings(pot.sensor_address, 0, now - HOUR)
assert len(kept) == 3, kept
print("ok: the old plant's readings are still in the database")


# --- the moment is stored with the pot ---

again = GreenThumbAutomation(Hub(), Nul(), Nul(), Nul(), history=auto.history, state_path=path)
assert again.get_plant("plant_1").planted_at == pot.planted_at
assert line(again, "plant_1") == [55.0]
print("ok: the cutoff survives a restart")


# --- taking the plant out and putting a plant in ---

auto.clear_plant_profile("plant_2")
auto.apply_plant_profile("plant_2", FIRST)
assert line(auto, "plant_2") == [], "an emptied pot's old line came back with the next plant"
print("ok: a pot emptied and planted again starts fresh, even with the same kind of plant")


# --- each probe is still found through the index ---

plan = " ".join(
    row["detail"] for row in auto.history._db.execute(
        "EXPLAIN QUERY PLAN SELECT sensor_address, AVG(moisture_percent) FROM readings"
        " WHERE ((sensor_address = ? AND recorded_at >= ?) OR (sensor_address = ? AND recorded_at >= ?))"
        " AND moisture_percent >= 0 GROUP BY sensor_address",
        (0x36, 0, 0x37, 0),
    )
)
assert "idx_readings_addr_time" in plan and "SCAN readings" not in plan, plan
print("ok: a start per probe still searches the index instead of walking the table")

print("\nall replanting checks passed")
