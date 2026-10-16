"""Confirming each watering reached the soil, from the pot's own probe.

The probe can take most of an hour to show a dose, so the check has to pass a
dose as soon as the rise appears and only call a miss once the whole window is
gone. While any dose is unconfirmed, automatic watering waits for every pot,
so an empty tank cannot run the pump dry pot after pot; two misses in a row
pause it until Resume.
"""

import sqlite3
import sys
import tempfile
import types
from datetime import datetime
from pathlib import Path

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import soak
from greenthumb.config import settings
from greenthumb.history import HistoryStore
from greenthumb.models import SensorSample
from greenthumb.services.automation import GreenThumbAutomation
from tests.helpers import CalibrationSurface, give_every_plant_soil, temp_state

settings.auto_watering_enabled = True
settings.water_sensor_enabled = False
settings.soak_check_enabled = True
settings.soak_rise_percent = 5.0
settings.watering_cooldown_minutes = 60
settings.sensor_poll_seconds = 60

SPAN = (320, 800)  # wilting point, field capacity: 5% of 480 is 24 counts
MINUTE = 60


# --- the rules on their own ---

def after(*values):
    return [float(v) for v in values]

assert soak.threshold(SPAN, 5.0) == 24.0
assert soak.threshold((320, 400), 5.0) == soak.MIN_RISE_COUNTS, "a narrow span still needs a real rise"

assert soak.judge(400, after(401, 430, 431, 432), SPAN, 5, False, 60)[0] == soak.SOAKED
print("ok: a quick rise passes straight away")

slow = [400.0] * 50 + after(430, 432, 433)
assert soak.judge(400, slow, SPAN, 5, False, 60)[0] == soak.SOAKED
print("ok: a rise that only shows after 50 minutes still passes")

spike = after(400, 470, 401, 400, 402)
assert soak.judge(400, spike, SPAN, 5, False, 60)[0] == soak.PENDING
assert soak.judge(400, spike + [400.0] * 55, SPAN, 5, True, 60)[0] == soak.MISSED
print("ok: one noisy reading cannot pass a dose")

assert soak.judge(400, [401.0] * 20, SPAN, 5, False, 60)[0] == soak.PENDING
verdict, rise = soak.judge(400, [405.0] * 60, SPAN, 5, True, 60)
assert verdict == soak.MISSED and rise == 5.0, (verdict, rise)
print("ok: no rise is pending until the window ends, then a miss")

assert soak.judge(400, [401.0] * 10, SPAN, 5, True, 60)[0] == soak.UNKNOWN
print("ok: a probe that went quiet gives unknown, not a miss")

assert soak.baseline([400, 401]) is None
assert soak.baseline([400, 410, 402]) == 402
assert not soak.can_judge(None, SPAN)
assert not soak.can_judge(400, None)
assert not soak.can_judge(780, SPAN), "soil near field capacity has no room to show a dose"
assert soak.can_judge(500, SPAN)
print("ok: no baseline, no scale, or already-wet soil is not judged")


# --- in the planter ---

class Hub(CalibrationSurface):
    def __init__(self):
        self.addresses = [0x36, 0x37, 0x38, 0x39]
        self.raw = {a: 400.0 for a in self.addresses}

    def read_one(self, address):
        return SensorSample(address, 0.0, self.raw[address], 22.0)


class Klipper:
    def move_gantry_absolute(self, pos): return {"ok": True}
    def status(self): return {"ok": True, "position": 0.0, "homed": True}
    def water_supply_present(self): return True


class Pump:
    is_running = False
    def __init__(self): self.calls = []
    def deliver_ml(self, volume_ml=0, **kw): self.calls.append(volume_ml)


class Leds:
    mode = "schedule"
    def set_plant_segments(self, segments): pass
    def status(self): return {"mode": self.mode, "connected": True}


def build(state_path=None, db=None):
    db = db or Path(tempfile.mkdtemp()) / "history.db"
    auto = GreenThumbAutomation(
        Hub(), Klipper(), Pump(), Leds(), history=HistoryStore(db), state_path=state_path or temp_state()
    )
    return give_every_plant_soil(auto), db


def readings(auto, address, start, values):
    """One stored reading a minute from `start`, for one probe."""
    for i, raw in enumerate(values):
        auto.history.record_readings([SensorSample(address, 0.0, float(raw), 22.0)], at=start + i * MINUTE)


def dose(auto, plant_id, at, soak_state=soak.PENDING):
    return auto.history.record_watering(plant_id, 100, "auto", soak=soak_state, at=at)


now = int(datetime.now().timestamp())
auto, _ = build()
plant1 = auto.get_plant("plant_1")
A = plant1.sensor_address

# A dose recorded as the planter does it: pending when it can be judged.
readings(auto, A, now - 9 * MINUTE, [400] * 10)
assert auto._soak_start_state(plant1, 100) == soak.PENDING
assert auto._soak_start_state(plant1, 0) == soak.SKIPPED
wet = auto.get_plant("plant_2")
readings(auto, wet.sensor_address, now - 9 * MINUTE, [790] * 10)
assert auto._soak_start_state(wet, 100) == soak.SKIPPED
dry_history = auto.get_plant("plant_3")
assert auto._soak_start_state(dry_history, 100) == soak.SKIPPED, "no readings before the dose"
print("ok: a dose starts pending, or skipped when it cannot be judged")

# Pending holds watering for every pot, and is released once confirmed.
t0 = now - 10 * MINUTE
auto, _ = build()
readings(auto, A, t0 - 9 * MINUTE, [400] * 10)
watering = dose(auto, "plant_1", t0)
held = auto.watering_suppressed()
assert held and "plant_1" not in held and auto.get_plant("plant_1").name in held, held
readings(auto, A, t0 + MINUTE, [402, 430, 432, 433])
auto._check_soaks(now=t0 + 5 * MINUTE)
assert auto.history.pending_soaks() == []
assert auto.watering_suppressed() is None
last = auto.get_overview()["plants"][0]["last_soak"]
assert last["state"] == soak.SOAKED and last["rise"] >= 24, last
print("ok: an unconfirmed dose holds every pot, and confirming it lets them go")

# Still pending part way through the window, a miss once it has passed.
auto, _ = build()
readings(auto, A, t0 - 9 * MINUTE, [400] * 10)
dose(auto, "plant_1", t0)
readings(auto, A, t0 + MINUTE, [401] * 59)
auto._check_soaks(now=t0 + 30 * MINUTE)
assert len(auto.history.pending_soaks()) == 1
auto._check_soaks(now=t0 + 61 * MINUTE)
assert auto.history.pending_soaks() == []
assert auto.history.waterings(hours=48, now=t0 + 61 * MINUTE)[-1]["soak"] == soak.MISSED
status = auto.system_status()
assert status["level"] == "attention" and "moisture probe" in status["message"], status
assert auto.soak_pause_reason() is None, "one miss must not pause watering"
print("ok: a full hour with no rise is a miss, and one miss is a warning")

# Manual watering is not held: somebody asked for it.
auto.history.record_watering("plant_2", 100, "auto", soak=soak.PENDING, at=now)
assert auto.watering_suppressed()
pump_calls = len(auto.pump.calls)
auto.water_plant("plant_2")
assert len(auto.pump.calls) == pump_calls + 1
print("ok: a manual watering still runs while automatic watering is held")


def missed(auto, plant_id, at):
    watering = dose(auto, plant_id, at, soak_state=soak.PENDING)
    auto.history.record_soak(watering, soak.MISSED, 2.0)


# Two misses on one pot: pause, and check the reservoir first.
state_path = temp_state()
auto, db = build(state_path)
missed(auto, "plant_1", now - 300)
missed(auto, "plant_1", now - 200)
reason = auto.soak_pause_reason()
assert reason and "reservoir" in reason and "nozzle" in reason and "probe" in reason, reason
assert auto.watering_suppressed(), "two misses must pause automatic watering"
status = auto.system_status()
assert status["level"] == "problem" and "reservoir" in status["message"], status
print("ok: two misses on one pot pause watering and say to check the reservoir, nozzle and probe")

# It survives a restart, and so does Resume.
restarted, _ = build(state_path, db)
assert restarted.soak_pause_reason(), "a restart forgot the pause"
restarted.resume_watering()
assert restarted.soak_pause_reason() is None and restarted.watering_suppressed() is None
again, _ = build(state_path, db)
assert again.soak_pause_reason() is None, "a restart brought back a pause already resumed"
print("ok: the pause survives a restart, and so does Resume")

# After Resume, one new miss is a warning again, not an instant pause.
missed(again, "plant_2", int(datetime.now().timestamp()) + 1)
assert again.soak_pause_reason() is None
print("ok: misses from before Resume no longer count")

# Two misses on different pots: most likely the tank.
auto, _ = build()
missed(auto, "plant_1", now - 300)
missed(auto, "plant_3", now - 200)
reason = auto.soak_pause_reason()
assert reason and "reservoir is probably empty" in reason, reason
print("ok: misses on two different pots point at an empty reservoir")

# A confirmed dose in between breaks the run.
auto, _ = build()
missed(auto, "plant_1", now - 300)
ok = dose(auto, "plant_2", now - 250)
auto.history.record_soak(ok, soak.SOAKED, 30)
missed(auto, "plant_3", now - 200)
assert auto.soak_pause_reason() is None
print("ok: a dose that reached the soil resets the count")

# Switched off: no hold, no pause.
settings.soak_check_enabled = False
assert auto._soak_start_state(plant1, 100) is None
assert auto.watering_suppressed() is None
settings.soak_check_enabled = True
print("ok: with the check switched off nothing is held")

# A restart keeps the hour's cooldown.
auto, db = build()
auto.history.record_watering("plant_1", 100, "auto", at=now - 600)
restarted, _ = build(db=db)
assert not restarted._cooldown_elapsed("plant_1"), "a restart reset the cooldown"
assert restarted._cooldown_elapsed("plant_2")
print("ok: a restart keeps each pot's cooldown")

# An old history database gains the new columns.
old = Path(tempfile.mkdtemp()) / "old.db"
con = sqlite3.connect(old)
con.execute(
    "CREATE TABLE waterings (id INTEGER PRIMARY KEY, recorded_at INTEGER NOT NULL, plant_id TEXT NOT NULL,"
    " volume_ml INTEGER NOT NULL, trigger TEXT NOT NULL, delivered INTEGER)"
)
con.execute("INSERT INTO waterings (recorded_at, plant_id, volume_ml, trigger) VALUES (1, 'plant_1', 50, 'auto')")
con.commit()
con.close()
store = HistoryStore(old)
columns = {row[1] for row in store._db.execute("PRAGMA table_info(waterings)")}
assert {"soak", "soak_rise"} <= columns, columns
assert store.pending_soaks() == [], "old rows must not count as pending"
print("ok: an old history database gains the soak columns, and its rows are not pending")

print("\nall soak check checks passed")
