"""Turning a pot off, and back on.

An off pot is one nobody is using: an empty spot, or a probe taken out. It
must drop out of everything the planter does on its own -- the readings, the
status bar, the patrol, the scheduled lights -- without losing its settings,
and without the moves you make by hand being refused.
"""

import sys
import types
from datetime import datetime

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import dances
from greenthumb.config import settings
from greenthumb.models import SensorSample
from greenthumb.services.automation import GreenThumbAutomation
from tests.helpers import CalibrationSurface, give_every_plant_soil, temp_state, temp_store

settings.auto_watering_enabled = False
settings.home_on_startup = False
settings.soak_check_enabled = True
settings.quiet_hours_enabled = False

TRAVEL = 890.0
DRY, WET = 320.0, 800.0


class Klip:
    def __init__(self):
        self.events = []
        self.homed = False

    def status(self):
        return {"ok": True, "position": 0.0, "homed": self.homed, "max_x": TRAVEL}

    def home_gantry(self):
        self.events.append("home")
        self.homed = True
        return {"ok": True}

    def move_gantry_absolute(self, position):
        self.events.append(("move", position))
        return {"ok": True}

    def send_gcode(self, gcode, timeout=5.0):
        self.events.append(("gcode", gcode))
        return {"ok": True}

    def release_motors(self):
        self.events.append("release")
        self.homed = False
        return {"ok": True}


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
        self.reads = []

    def read_one(self, address):
        self.reads.append(address)
        raw = self.raws[address]
        return SensorSample(address, self.raw_to_percent(raw, address) if raw >= 0 else -1.0, raw, 21.0)


class Leds:
    # Real values, not left to __getattr__: the settings snapshot reads these,
    # and a stub function there fails every save.
    mode = "schedule"; color = (0, 0, 0); brightness = 0
    segments = []
    def set_plant_segments(self, segments): Leds.segments = segments
    def status(self): return {"mode": self.mode}
    # Everything else (a restore to defaults resets the strip) is a no-op.
    def __getattr__(self, name): return lambda *a, **k: {}


def build(raws, state_path=None):
    klip = Klip()
    hub = Hub(dict(raws))
    auto = give_every_plant_soil(GreenThumbAutomation(
        hub, klip, Pump(klip), Leds(), history=temp_store(), state_path=state_path or temp_state(),
    ))
    return auto, klip, hub


def settle(auto):
    for _ in range(settings.moisture_window_size):
        auto._poll_sensors()


# --- the probe is not read, and a missing one is not a fault ---

# Plant 3's probe is unplugged (-1).
auto, klip, hub = build({0x36: WET, 0x37: WET, 0x38: -1.0, 0x39: WET})
auto.set_auto_watering(True)  # so the bar gets as far as counting the pots
settle(auto)
assert "Plant 3" in auto.system_status()["message"], auto.system_status()

auto.set_plant_enabled("plant_3", False)
hub.reads.clear()
settle(auto)
assert 0x38 not in hub.reads and set(hub.reads) == {0x36, 0x37, 0x39}, hub.reads
print("ok: an off pot's probe is not read")

state = auto.system_status()
assert state["level"] == "ok" and "Plant 3" not in state["message"], state
assert state["message"].startswith("All 3 plants are happy"), state
print("ok: its unplugged probe is not reported, and the count leaves it out")

for plant_id in ("plant_1", "plant_2", "plant_4"):
    auto.set_plant_enabled(plant_id, False)
assert auto.system_status() == {"level": "info", "message": "Every pot is turned off."}
print("ok: with every pot off, the status bar says so")


# --- the patrol neither waters nor visits it ---

auto, klip, hub = build({0x36: DRY, 0x37: WET, 0x38: DRY, 0x39: WET})
auto.set_auto_watering(True)
settle(auto)
off = auto.get_plant("plant_1")
on = auto.get_plant("plant_3")
auto.set_plant_enabled("plant_1", False)
auto.live_patrol(now=datetime.now())

moves = [event[1] for event in klip.events if isinstance(event, tuple) and event[0] == "move"]
doses = [event for event in klip.events if isinstance(event, tuple) and event[0] == "dose"]
gcode = " ".join(event[1] for event in klip.events if isinstance(event, tuple) and event[0] == "gcode")
assert moves == [on.position_mm] and len(doses) == 1, klip.events
assert f"G1 X{off.position_mm} F{dances.CRUISE}" not in gcode, gcode
assert auto.patrol_status()["last"]["watered"] == [f"{on.name} ({on.watering_volume_ml} mL)"]
print("ok: the patrol waters the dry pot that is on, and passes the off one by without a visit")


# --- by hand: move yes, water no ---

try:
    auto.water_plant("plant_1")
except ValueError as error:
    assert "turned off" in str(error), error
else:
    raise AssertionError("watered a pot that is turned off")
klip.events.clear()
result = auto.move_to_plant("plant_1")
assert result.get("ok") is not False and ("move", off.position_mm) in klip.events, (result, klip.events)
print("ok: an off pot can be moved to but not watered from Controls")


# --- lights: dark on the schedule, manual untouched ---

auto, klip, hub = build({0x36: WET, 0x37: WET, 0x38: WET, 0x39: WET})
for plant in auto.plants:
    plant.light_hours = 24  # always on, whatever the time of the test
auto._apply_lighting()
assert all(zone.lit for zone in Leds.segments)
plant = auto.get_plant("plant_2")
manual = (plant.manual_color, plant.manual_brightness)
auto.set_plant_enabled("plant_2", False)
zones = Leds.segments
assert not zones[1].lit and zones[0].lit and zones[2].lit, [zone.lit for zone in zones]
assert (zones[1].manual_color, zones[1].manual_brightness) == manual
print("ok: an off pot's schedule light goes dark at once, its manual setting is kept")


# --- turning it off forgets its readings and settles its soak check ---

auto, klip, hub = build({0x36: WET, 0x37: WET, 0x38: WET, 0x39: WET})
settle(auto)
auto.history.record_watering("plant_4", 100, "auto", soak="pending")
auto.set_plant_enabled("plant_4", False)
assert not [row for row in auto.history.pending_soaks() if row["plant_id"] == "plant_4"]
assert not auto._history[0x39]
print("ok: turning a pot off skips its pending soak check, so it cannot count as a miss")

auto.set_plant_enabled("plant_4", True)
auto.set_auto_watering(True)
state = auto.system_status()
assert state["level"] == "info" and "Getting to know Plant 4" in state["message"], state
print("ok: turned back on, it starts again from getting to know the pot")


# --- the History chart is told, and nothing is deleted ---

auto.set_plant_enabled("plant_4", False)
lines = {plant["plant_id"]: plant for plant in auto.get_history(24)["plants"]}
assert lines["plant_4"]["enabled"] is False and lines["plant_1"]["enabled"] is True
print("ok: the history marks the off pot for the chart to hide")


# --- stored with the pot ---

path = temp_state()
auto, *_ = build({0x36: WET, 0x37: WET, 0x38: WET, 0x39: WET}, state_path=path)
auto.set_plant_enabled("plant_2", False)
again, *_ = build({0x36: WET, 0x37: WET, 0x38: WET, 0x39: WET}, state_path=path)
assert again.get_plant("plant_2").enabled is False and again.get_plant("plant_1").enabled is True
print("ok: the choice survives a restart")

again._restore_defaults_locked()
assert all(plant.enabled for plant in again.plants)
print("ok: restoring defaults turns every pot back on")

# --- through the API, the way the card's toggle calls it ---
#
# The first version of the card sent the opposite of what it showed, and every
# check above passed because they call the service directly. These go through
# the routes and read back what the page reads.

from greenthumb.services import automation as automation_module

served, served_klip, _ = build({0x36: WET, 0x37: WET, 0x38: WET, 0x39: WET})
real_class = automation_module.GreenThumbAutomation
automation_module.GreenThumbAutomation = lambda *a, **k: served
try:
    from fastapi.testclient import TestClient
    from greenthumb import main
finally:
    automation_module.GreenThumbAutomation = real_class
main.automation = served
client = TestClient(main.app)
api = settings.api_prefix


def card(plant_id):
    return next(p for p in client.get(f"{api}/plants").json() if p["plant_id"] == plant_id)


assert card("plant_2")["enabled"] is True
response = client.post(f"{api}/plants/plant_2/enabled", json={"enabled": False})
assert response.status_code == 200 and response.json()["enabled"] is False, response.text
assert card("plant_2")["enabled"] is False
overview = {p["plant_id"]: p for p in client.get(f"{api}/overview").json()["plants"]}
assert overview["plant_2"]["enabled"] is False and overview["plant_1"]["enabled"] is True
print("ok: switching Off through the API turns the pot off, and /plants and /overview say so")

response = client.post(f"{api}/water/plant_2")
assert response.status_code == 400 and "turned off" in response.json()["error"], response.text
print("ok: watering an off pot through the API is a 400 that says why")

assert client.post(f"{api}/plants/plant_2/enabled", json={}).status_code == 400
assert client.post(f"{api}/plants/plant_2/enabled", json={"enabled": "no"}).status_code == 400
assert card("plant_2")["enabled"] is False
print("ok: a malformed request is refused rather than read as a switch")

response = client.post(f"{api}/plants/plant_2/enabled", json={"enabled": True})
assert response.status_code == 200 and card("plant_2")["enabled"] is True, response.text
print("ok: switching On turns it back on")

print("\nall plant on/off checks passed")
