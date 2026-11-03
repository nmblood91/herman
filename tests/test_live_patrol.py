"""The hourly live patrol, and the gantry motor idling between moves.

The patrol is the only place automatic watering happens: on the hour it homes,
then makes one trip down the rail, dosing the pots that are due and visiting
the rest. What matters is that it waters exactly the pots it should, that one
pot's trouble never leaves the others dry, and that it leaves the motor off.

Between moves the motor is switched off and Klipper forgets the home. That has
to read as normal, and the next move has to home first rather than be refused.
"""

import logging
import sys
import types
from datetime import datetime, timedelta

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import dances
from greenthumb.config import settings
from greenthumb.models import SensorSample
from greenthumb.services.automation import GreenThumbAutomation
from tests.helpers import CalibrationSurface, give_every_plant_soil, temp_state, temp_store

settings.auto_watering_enabled = False
settings.home_on_startup = False
# These pots never get wetter, so every dose would stay unconfirmed and turn
# the next patrol dry. That hold has its own case below.
settings.soak_check_enabled = False
settings.quiet_hours_enabled = False

TRAVEL = 890.0
DRY, WET = 320.0, 800.0


class Klip:
    """A board that records everything the planter asks of it, in order."""

    def __init__(self, refuse_at=None, home_ok=True):
        self.events = []
        self.homed = False
        self.refuse_at = refuse_at
        self.home_ok = home_ok

    def status(self):
        return {"ok": True, "position": 0.0, "homed": self.homed, "max_x": TRAVEL}

    def home_gantry(self):
        self.events.append("home")
        if not self.home_ok:
            return {"ok": False, "error": "endstop not triggered"}
        self.homed = True
        return {"ok": True}

    def move_gantry_absolute(self, position):
        if position == self.refuse_at:
            return {"ok": False, "error": "Move out of range"}
        self.events.append(("move", position))
        return {"ok": True}

    def send_gcode(self, gcode, timeout=5.0):
        self.events.append(("gcode", gcode))
        return {"ok": True}

    def release_motors(self):
        self.events.append("release")
        self.homed = False
        return {"ok": True}

    @property
    def homes(self):
        return self.events.count("home")


class Pump:
    is_running = False

    def __init__(self, klip):
        self.klip = klip

    def deliver_ml(self, volume_ml=100, **kw):
        self.klip.events.append(("dose", volume_ml))


class Hub(CalibrationSurface):
    addresses = [0x36, 0x37, 0x38, 0x39]

    def __init__(self, raws):
        self.raws = raws

    def read_one(self, address):
        raw = self.raws[address]
        return SensorSample(address, self.raw_to_percent(raw, address), raw, 21.0)


class Leds:
    mode = "schedule"
    def set_plant_segments(self, segments): pass
    def status(self): return {"mode": self.mode}


class Lines(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


log = Lines()
logging.getLogger("greenthumb.services.automation").addHandler(log)
logging.getLogger("greenthumb.services.automation").setLevel(logging.INFO)

# Plants 1 and 3 dry, 2 and 4 wet.
RAWS = {0x36: DRY, 0x37: WET, 0x38: DRY, 0x39: WET}


def build(klip=None, raws=None, watering=True):
    klip = klip or Klip()
    auto = give_every_plant_soil(GreenThumbAutomation(
        Hub(dict(raws or RAWS)), klip, Pump(klip), Leds(),
        history=temp_store(), state_path=temp_state(),
    ))
    auto.set_auto_watering(watering)
    for _ in range(settings.moisture_window_size):
        auto._poll_sensors()
    return auto, klip


def doses(klip):
    return [event for event in klip.events if isinstance(event, tuple) and event[0] == "dose"]


NOW = datetime.now()


# --- off means nothing happens on the hour ---

auto, klip = build(watering=False)
auto.live_patrol(now=NOW)
assert klip.events == [], klip.events
assert auto.patrol_status()["last"] is None and auto.patrol_status()["next"] is None
print("ok: with automatic watering off, the hour passes without a home or a move")


# --- on, it homes, waters the due pots and visits the rest, in one trip ---

auto, klip = build()
log.messages.clear()
auto.live_patrol(now=NOW)
dry = [auto.get_plant("plant_1"), auto.get_plant("plant_3")]
wet = [auto.get_plant("plant_2"), auto.get_plant("plant_4")]

assert klip.events[0] == "home", klip.events
assert [volume for _, volume in doses(klip)] == [p.watering_volume_ml for p in dry], klip.events
moves = [event[1] for event in klip.events if isinstance(event, tuple) and event[0] == "move"]
assert moves == [p.position_mm for p in dry], moves
visits = [event[1] for event in klip.events if isinstance(event, tuple) and event[0] == "gcode"]
for plant in wet:
    assert any(f"G1 X{plant.position_mm} F{dances.CRUISE}" in g for g in visits), (plant.name, visits)
print("ok: the dry pots are watered and the wet ones visited, after a home")

# Left to right: the order of the stops follows their position on the rail.
def stop_at(event):
    """Where a dose's move or a visit's first G1 goes."""
    if event[0] == "move":
        return event[1]
    return int(event[1].split("G1 X")[1].split()[0])


stops = [
    stop_at(event) for event in klip.events
    if isinstance(event, tuple) and event[0] in ("move", "gcode")
][:-1]  # the last is the park at X0
assert len(stops) == 4 and stops == sorted(stops), stops
print("ok: one trip down the rail, left to right")

assert "G1 X0 " in visits[-1], "did not park at X0"
assert klip.events[-1] == "release", klip.events
assert auto.motor_status()["state"] == "idle", auto.motor_status()
print("ok: it parks at X0 and switches the motor off")

last = auto.patrol_status()["last"]
assert last["ok"] is True and last["error"] is None, last
assert last["watered"] == [f"{p.name} ({p.watering_volume_ml} mL)" for p in dry], last
assert any(m.startswith("Hourly patrol: homed, watered ") and "visited 2 others" in m for m in log.messages), log.messages
assert "Gantry motor idle after the hourly patrol" in log.messages, log.messages
print("ok: the patrol is summed up in one log line, and the motor going idle in another")


# --- the cooldown, measured patrol to patrol ---

auto.live_patrol(now=NOW + timedelta(minutes=30))
assert len(doses(klip)) == 2, "watered again inside the cooldown"
auto.live_patrol(now=NOW + timedelta(minutes=settings.watering_cooldown_minutes - 2))
assert len(doses(klip)) == 4, "the next hour's patrol did not water the still-dry pots"
print("ok: no second dose inside the cooldown, but the next hour's patrol waters again")


# --- a dose still waiting on its probe makes it a dry patrol ---

settings.soak_check_enabled = True
try:
    auto, klip = build()
    auto.history.record_watering("plant_2", 100, "auto", soak="pending")
    auto.live_patrol(now=NOW)
    assert klip.events[0] == "home", klip.events
    assert doses(klip) == [], "watered with a dose still unconfirmed"
    assert klip.events[-1] == "release", klip.events
finally:
    settings.soak_check_enabled = False
print("ok: an unconfirmed dose turns the patrol dry rather than skipping the home")


# --- quiet hours and a snooze skip the hour ---

auto, klip = build()
auto.set_quiet_hours(True, "21:00", "08:00")
auto.live_patrol(now=NOW.replace(hour=23, minute=0))
assert klip.events == [], "patrolled during quiet hours"
auto.live_patrol(now=NOW.replace(hour=9, minute=0))
assert doses(klip), "did not water once quiet hours were over"
print("ok: quiet hours skip the hour, and the first patrol after waters")

auto, klip = build()
auto.snooze_watering(2)
auto.live_patrol()
assert klip.events == [], "patrolled while snoozed"
print("ok: a snooze skips it too")


# --- one pot's trouble does not leave the rest dry ---

first = build()[0].get_plant("plant_1")
auto, klip = build(klip=Klip(refuse_at=first.position_mm))
auto.live_patrol(now=NOW)
assert [volume for _, volume in doses(klip)] == [auto.get_plant("plant_3").watering_volume_ml], klip.events
last = auto.patrol_status()["last"]
assert last["ok"] is False and first.name in last["error"], last
assert klip.events[-1] == "release", "a failed stop left the motor on"
print("ok: a refused stop is reported, and the rest of the rail is still watered")

auto, klip = build(klip=Klip(home_ok=False))
auto.live_patrol(now=NOW)
assert doses(klip) == [] and klip.events == ["home"], klip.events
assert "Homing failed" in auto.patrol_status()["last"]["error"]
print("ok: a failed home stops the patrol, and says why")

auto, klip = build()
auto._hardware_lock.acquire()
try:
    auto.live_patrol(now=NOW, busy_wait_seconds=0)
finally:
    auto._hardware_lock.release()
assert klip.events == [] and auto.patrol_status()["last"]["error"] == "hardware was busy"
print("ok: hardware that stays busy gives up the hour and says so")


# --- the motor between patrols ---

auto, klip = build(watering=False)
assert auto.motor_status()["state"] == "unhomed", auto.motor_status()
auto.home_gantry()
assert auto.motor_status()["state"] == "active", auto.motor_status()

auto.tick()
assert "release" not in klip.events, "switched the motor off straight after a home"
auto._last_motion_at -= settings.motor_idle_seconds + 1
log.messages.clear()
auto.tick()
assert klip.events[-1] == "release", klip.events
assert f"Gantry motor idle after {settings.motor_idle_seconds} s without a move" in log.messages, log.messages
status = auto.motor_status()
assert status["state"] == "idle" and status["since"], status
print("ok: the motor is switched off a while after the last move, not before, and the log says so")

auto.tick()
assert klip.events.count("release") == 1, "released an idle motor again every tick"
print("ok: an idle motor is left alone")

# A manual watering on an idle motor homes first instead of being refused.
homes = klip.homes
log.messages.clear()
auto.water_plant("plant_2")
assert klip.homes == homes + 1, klip.events
assert klip.events[-2:] == [("move", auto.get_plant("plant_2").position_mm), ("dose", auto.get_plant("plant_2").watering_volume_ml)], klip.events
assert any(m.startswith("Gantry motor idle, homing before watering") for m in log.messages), log.messages
print("ok: watering by hand on an idle motor homes first, then waters")

# Busy hardware puts the switch-off off to a later tick.
auto._last_motion_at -= settings.motor_idle_seconds + 1
auto._hardware_lock.acquire()
try:
    auto.tick()
finally:
    auto._hardware_lock.release()
assert auto.motor_status()["state"] == "active", "switched the motor off over someone holding the arm"
auto.tick()
assert auto.motor_status()["state"] == "idle"
print("ok: busy hardware delays the switch-off to the next tick")

# Klipper switching the motor off by itself is noticed and named.
auto.home_gantry()
released = klip.events.count("release")
klip.homed = False
auto._last_motion_at -= settings.motor_idle_seconds + 1
log.messages.clear()
auto.tick()
assert klip.events.count("release") == released, "released a motor Klipper had already switched off"
assert "Gantry motor went idle (Klipper switched it off)" in log.messages, log.messages
assert auto.motor_status()["state"] == "idle"
print("ok: Klipper switching the motor off on its own is logged as that")


# --- what the overview says ---

auto, klip = build()
overview = auto.get_overview()
assert overview["motor"]["state"] == "unhomed", overview["motor"]
assert overview["patrol"]["next"] == auto.next_patrol().isoformat(timespec="minutes")
assert auto.next_patrol(datetime(2026, 10, 14, 14, 37)) == datetime(2026, 10, 14, 15, 0)
print("ok: the overview carries the motor state and the next patrol, on the hour")

print("\nall live patrol and motor idle checks passed")
