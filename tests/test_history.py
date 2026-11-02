"""Storage and bucketing for the history chart.

Run with: python -m tests.test_history
"""

import sys
import tempfile
import threading
import types
from pathlib import Path

# The hardware modules import smbus2, which only exists on the Pi.
sys.modules.setdefault("smbus2", types.ModuleType("smbus2"))

from greenthumb.history import MAX_POINTS_PER_SERIES, HistoryStore, bucket_seconds_for  # noqa: E402
from greenthumb.models import SensorSample  # noqa: E402

HOUR = 3600


def sample(address, raw=650.0, percent=45.0, temp=22.0):
    return SensorSample(address, percent, raw, temp)


def store():
    path = Path(tempfile.mkdtemp()) / "history.db"
    return HistoryStore(path)


# --- bucket selection ---
assert bucket_seconds_for(1) == 60
assert bucket_seconds_for(6) == 60
assert bucket_seconds_for(24) == 300
assert bucket_seconds_for(24 * 7) == 1800
assert bucket_seconds_for(24 * 90) == 21600
for hours in (1, 6, 24, 48, 24 * 7, 24 * 30, 24 * 90):
    points = hours * 3600 / bucket_seconds_for(hours)
    assert points <= MAX_POINTS_PER_SERIES, (
        f"{hours}h yields {points:.0f} points, over the {MAX_POINTS_PER_SERIES} cap"
    )
print(f"ok: every range stays under {MAX_POINTS_PER_SERIES} points per series")


# --- failed reads are never stored ---
db = store()
kept = db.record_readings(
    [sample(0x36), SensorSample(0x37, -1.0, -1.0, -1.0), sample(0x38)], at=1000
)
assert kept == 2, kept
_, stamps, series = db.series([0x36, 0x37, 0x38], hours=1, now=1000)
assert series[0x37]["moisture_percent"] == [None], series[0x37]
print("ok: a failed read is excluded rather than stored as -1")


# --- bucketing averages within a bucket ---
db = store()
# Divisible by every bucket size (60/300/1800/21600) so the tests below are not
# accidentally straddling a bucket boundary.
base = 108_000
# three readings inside one 60s bucket, at 40/50/60 percent
for offset, percent in ((0, 40.0), (20, 50.0), (40, 60.0)):
    db.record_readings([sample(0x36, percent=percent)], at=base + offset)
_, stamps, series = db.series([0x36], hours=1, now=base + 60)
assert len(stamps) == 1, stamps
assert series[0x36]["moisture_percent"] == [50.0], series[0x36]
print("ok: readings inside a bucket are averaged")


# --- plants share one timestamp axis, gaps become null ---
db = store()
db.record_readings([sample(0x36, percent=40.0)], at=base)
db.record_readings([sample(0x37, percent=60.0)], at=base + 120)
_, stamps, series = db.series([0x36, 0x37], hours=1, now=base + 180)
assert len(stamps) == 2, stamps
assert len(series[0x36]["moisture_percent"]) == len(stamps)
assert len(series[0x37]["moisture_percent"]) == len(stamps)
assert series[0x36]["moisture_percent"] == [40.0, None], series[0x36]
assert series[0x37]["moisture_percent"] == [None, 60.0], series[0x37]
print("ok: plants align to one axis with null where a plant has no reading")


# --- an address with no data at all still returns a full-length series ---
_, stamps, series = db.series([0x36, 0x39], hours=1, now=base + 180)
assert series[0x39]["moisture_percent"] == [None] * len(stamps), series[0x39]
print("ok: an address with no readings returns nulls, not a short array")


# --- only readings inside the window come back ---
db = store()
db.record_readings([sample(0x36)], at=base - 10 * HOUR)
db.record_readings([sample(0x36)], at=base - 1)
_, stamps, series = db.series([0x36], hours=2, now=base)
assert len(stamps) == 1, stamps
print("ok: readings outside the requested window are excluded")


# --- waterings, in and out of window ---
db = store()
db.record_watering("plant_1", 100, "auto", at=base - 30 * 60)
db.record_watering("plant_2", 50, "manual", at=base - 10 * HOUR)
marks = db.waterings(hours=2, now=base)
assert len(marks) == 1, marks
assert marks[0]["plant_id"] == "plant_1" and marks[0]["trigger"] == "auto"
assert marks[0]["volume_ml"] == 100
assert len(db.waterings(hours=24, now=base)) == 2
print("ok: waterings are returned with trigger and filtered by window")


# --- pruning ---
db = store()
db.record_readings([sample(0x36)], at=base - 100 * 24 * HOUR)
db.record_readings([sample(0x36)], at=base - 10 * 24 * HOUR)
db.record_watering("plant_1", 100, "auto", at=base - 100 * 24 * HOUR)
deleted = db.prune(retention_days=90, now=base)
assert deleted == 2, f"expected the old reading and watering, deleted {deleted}"
_, stamps, _ = db.series([0x36], hours=24 * 90, now=base)
assert len(stamps) == 1, stamps
assert db.waterings(hours=24 * 365, now=base) == []
print("ok: prune drops rows past retention and keeps the rest")


# --- how far back the readings go ---
db = store()
assert db.recorded_hours(now=base) == 0.0
# A failed read is stored with a raw but no percentage; it is not chartable,
# so it must not make the history look older than it is.
db.record_readings([SensorSample(0x36, -1.0, 650.0, 22.0)], at=base - 50 * HOUR)
assert db.recorded_hours(now=base) == 0.0, db.recorded_hours(now=base)
db.record_readings([sample(0x36)], at=base - 30 * HOUR)
db.record_readings([sample(0x36)], at=base - HOUR)
assert db.recorded_hours(now=base) == 30.0, db.recorded_hours(now=base)
print("ok: recorded_hours measures from the oldest chartable reading")


# --- clearing keeps the doses the cooldown still needs ---
db = store()
db.record_readings([sample(0x36)], at=base - 10 * HOUR)
db.record_readings([sample(0x36)], at=base - 60)
db.record_watering("plant_1", 100, "auto", at=base - 10 * HOUR)
recent = db.record_watering("plant_2", 50, "auto", at=base - 30 * 60, soak="pending")
deleted = db.clear(keep_waterings_since=base - HOUR)
assert deleted == 3, deleted
assert db.recorded_hours(now=base) == 0.0
assert [row["id"] for row in db.pending_soaks()] == [recent], db.pending_soaks()
assert list(db.last_waterings()) == ["plant_2"], db.last_waterings()
print("ok: clear drops every reading and old waterings, keeps recent doses")


# --- concurrent writes do not raise ---
db = store()
errors = []


def hammer(address):
    try:
        for index in range(50):
            db.record_readings([sample(address)], at=base + index)
    except Exception as exc:  # noqa: BLE001
        errors.append(exc)


threads = [threading.Thread(target=hammer, args=(addr,)) for addr in (0x36, 0x37, 0x38)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
assert not errors, errors
_, stamps, series = db.series([0x36, 0x37, 0x38], hours=1, now=base + 60)
assert all(v is not None for v in series[0x36]["moisture_percent"])
print("ok: concurrent writes from several threads are serialised safely")

print("\nall history checks passed")
