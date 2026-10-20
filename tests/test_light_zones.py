"""Each pot's own light colours, and manual mode lit zone by zone.

A pot has two looks: the colour it shows during its scheduled hours, and its
own colour and brightness for manual mode with each zone set separately. They
come from the browser and from state.json, so a bad value has to be refused
or ignored rather than drawn, and an old state file with neither has to come
back white.
"""

import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import state
from greenthumb.config import settings
from greenthumb.hardware.lighting import LedController, Zone
from greenthumb.hardware.soil_sensors import unavailable_sample
from greenthumb.services.automation import GreenThumbAutomation
from tests.helpers import CalibrationSurface, temp_state, temp_store

settings.auto_watering_enabled = False
settings.auto_patrol_enabled = False
settings.home_on_startup = False

WHITE = (255, 255, 255)


class Klip:
    def status(self):
        return {"ok": True, "position": 0.0, "homed": True, "max_x": 890.0}

    def move_gantry_absolute(self, p):
        return {"ok": True}

    def send_gcode(self, gcode, timeout=5.0):
        return {"ok": True}


class Hub(CalibrationSurface):
    addresses = [0x36, 0x37, 0x38, 0x39]

    def __init__(self):
        self.calibration = {}
        self.field_capacity = {}

    def read_one(self, a):
        return unavailable_sample(a)


class Pump:
    flow_ml_per_second = settings.pump_flow_ml_per_second
    is_running = False


class RecordingLeds(LedController):
    """A real controller that keeps the zones it was last handed."""

    def set_plant_segments(self, zones):
        self.zones = list(zones)
        super().set_plant_segments(zones)


def build(path):
    return GreenThumbAutomation(
        Hub(), Klip(), Pump(), RecordingLeds(led_count=20),
        history=temp_store(), state_path=path,
    )


# --- an old state file, written before pots had colours ---

path = temp_state()
state.save_state({"plants": [{"plant_id": "plant_1", "name": "Basil"}]}, path)
auto = build(path)
assert auto.get_plant("plant_1").name == "Basil"
for plant in auto.plants:
    assert (plant.light_color, plant.manual_color, plant.manual_brightness) == (WHITE, WHITE, 75), plant
print("ok: a state file from before pot colours comes back white at 75%")

# --- junk in the file is ignored, not drawn ---

path = temp_state()
junk = [None, "red", [255, 0], [255, 0, 0, 0], [256, 0, 0], [-1, 0, 0], [True, 0, 0], [1.5, 0, 0]]
state.save_state(
    {
        "plants": [
            {"plant_id": "plant_1", "light_color": junk[1], "manual_color": junk[4], "manual_brightness": 101},
            {"plant_id": "plant_2", "light_color": junk[6], "manual_color": junk[3], "manual_brightness": True},
            {"plant_id": "plant_3", "light_color": [10, 20, 30], "manual_color": [40, 50, 60], "manual_brightness": 5},
        ],
        "leds": {"manual_scope": "sideways"},
    },
    path,
)
auto = build(path)
for plant_id in ("plant_1", "plant_2"):
    plant = auto.get_plant(plant_id)
    assert (plant.light_color, plant.manual_color, plant.manual_brightness) == (WHITE, WHITE, 75), plant
plant = auto.get_plant("plant_3")
assert (plant.light_color, plant.manual_color, plant.manual_brightness) == ((10, 20, 30), (40, 50, 60), 5)
assert auto.leds.manual_scope == "all", auto.leds.manual_scope
print("ok: bad stored colours, brightness and scope are ignored, good ones restored")

# --- the setters refuse junk and change nothing when they do ---

auto = build(temp_state())
for bad in junk:
    try:
        auto.set_plant_light_color("plant_1", bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"accepted light colour {bad!r}")
    try:
        auto.set_zone_manual("plant_1", bad, 40)
    except ValueError:
        pass
    else:
        if bad is not None:
            raise AssertionError(f"accepted manual colour {bad!r}")
assert auto.get_plant("plant_1").light_color == WHITE
try:
    auto.set_zone_manual("plant_2", [1, 2, 3], 101)
except ValueError:
    pass
else:
    raise AssertionError("accepted a brightness of 101%")
assert auto.get_plant("plant_2").manual_color == WHITE, "a refused brightness still changed the colour"
for call in (lambda: auto.set_plant_light_color("nope", [1, 2, 3]), lambda: auto.set_zone_manual("nope", [1, 2, 3])):
    try:
        call()
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown pot was accepted")
print("ok: bad colours, brightness and unknown pots are refused and change nothing")

# A colour without a brightness keeps the brightness, and the other way round.
# (The colour-only call with None above set plant_1's brightness to 40.)
auto.set_zone_manual("plant_3", [9, 9, 9], None)
auto.set_zone_manual("plant_3", None, 20)
plant = auto.get_plant("plant_3")
assert (plant.manual_color, plant.manual_brightness) == ((9, 9, 9), 20), plant
print("ok: a zone's colour and brightness can each be changed on its own")

# --- the controller sees a change at once, not on the next tick ---

auto.set_plant_light_color("plant_4", [0, 255, 0])
zones = {zone.start: zone for zone in auto.leds.zones}
plant = auto.get_plant("plant_4")
zone = zones[plant.led_start_index]
assert isinstance(zone, Zone)
assert zone.color == (0, 255, 0) and zone.end == plant.led_end_index, zone
assert zones[auto.get_plant("plant_3").led_start_index].manual_color == (9, 9, 9)
print("ok: a pot's new colour reaches the strip straight away")

# --- the overview lists each zone for the picker ---

lighting = auto.get_overview()["lighting"]
by_id = {zone["plant_id"]: zone for zone in lighting["zones"]}
assert set(by_id) == {plant.plant_id for plant in auto.plants}
assert by_id["plant_3"]["manual_color"] == [9, 9, 9] and by_id["plant_3"]["manual_brightness"] == 20
assert lighting["manual_scope"] == "all"
print("ok: the overview lists every zone's manual settings")

print("\nall light zone checks passed")
