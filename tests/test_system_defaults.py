"""Restore to Defaults: the planter as it was freshly installed.

Three things matter. It has to take effect now, not after a restart -- a
button that changes nothing until the service is bounced reads as broken. It
has to reach every pot, since a saved position quietly outliving a change of
defaults is what prompted it. And it must not touch the plant-profile and soil
libraries or the history, which are built up over time and are not this
planter's configuration.
"""

import sys
import types
from datetime import datetime, time, timedelta

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import soil_library, state
from greenthumb.config import settings
from greenthumb.hardware.lighting import (
    DEFAULT_BRIGHTNESS,
    DEFAULT_COLOR,
    DEFAULT_MODE,
    LedController,
)
from greenthumb.hardware.soil_sensors import unavailable_sample
from greenthumb.models import SensorSample
from greenthumb.plants import default_plants
from greenthumb.services.automation import GreenThumbAutomation, HardwareBusyError
from tests.helpers import CalibrationSurface, temp_state, temp_store

settings.auto_watering_enabled = False
settings.auto_patrol_enabled = False
settings.home_on_startup = False


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


def build(path, history=None):
    return GreenThumbAutomation(
        Hub(), Klip(), Pump(), LedController(led_count=10),
        history=history or temp_store(), state_path=path,
    )


def placement(plant):
    """Everything on a pot that a restore puts back."""
    return (
        plant.name, plant.profile, plant.position_mm, plant.watering_mode, plant.sweep_min_mm,
        plant.sweep_max_mm, plant.soil, plant.preferred_soil, plant.target_vwc,
        plant.watering_volume_ml, plant.light_start_time,
        plant.light_hours, plant.light_brightness,
    )


FRESH = [placement(plant) for plant in default_plants()]

path = temp_state()
history = temp_store()
auto = build(path, history)

# The libraries, which have to survive.
soil_library.install(path=path)
soils_before = state.load_soils(path)
assert soils_before, "the soil library did not install"

# Every system value...
auto.set_auto_watering(True)
auto.pump.flow_ml_per_second = 2.5
auto._flow_measured_at = "2026-10-01T12:00:00"
auto.set_auto_patrol(True)
auto.set_home_on_startup(True)
auto.set_quiet_hours(True, "22:30", "06:15")
auto.snooze_until = datetime.now() + timedelta(hours=2)
auto.set_light_chip("WS2815")
auto.set_light_brightness(20)
auto.set_light_color((255, 0, 0))
auto.sensor_hub.calibration = {0x36: {"dry": 410}}
state.save_calibration_point(0x36, "dry", 410, path=path)

# ...and every pot.
soil = next(iter(soils_before))
state.save_soil(soil, {"field_capacity_raw": 777}, path)
soils_before = state.load_soils(path)  # a reading is library data, so it stays
for plant in auto.plants:
    auto.update_plant_name(plant.plant_id, f"Renamed {plant.plant_id}")
    auto.update_plant_soil(plant.plant_id, soil)
assert auto.sensor_hub.field_capacity, "the pots never got a scale to lose"
auto.set_plant_position("plant_2", 300)
auto.set_plant_sweep("plant_3", 450, 680)
auto.set_watering_mode("plant_3", "sweep")
auto._persist()
auto._sync_scales()
auto.save_plant_profile("plant_1")
profiles_before = state.load_profiles(path)
assert profiles_before, "the plant profile did not save"

history.record_readings([SensorSample(0x36, 50.0, 500, 21.0)])
history.record_watering("plant_1", 100, "manual", True)
readings_before = history.series([0x36], 1)
waterings_before = history.waterings(1)
assert waterings_before, "the watering did not record"

auto.restore_system_defaults()

# --- every pot is as freshly installed ---

assert [placement(plant) for plant in auto.plants] == FRESH, [
    placement(plant) for plant in auto.plants
]
assert auto.sensor_hub.field_capacity == {}, "a pot with no soil profile still has a scale"
print("ok: every pot is back to its default name, spot, sweep and soil profile")

# --- and every setting ---

assert auto.auto_watering_enabled is settings.auto_watering_enabled
assert auto.pump.flow_ml_per_second == settings.pump_flow_ml_per_second
assert auto._flow_measured_at is None, "the flow still claims to have been measured"
assert auto.auto_patrol_enabled is settings.auto_patrol_enabled
assert auto.home_on_startup is settings.home_on_startup
assert auto.quiet_hours_enabled is settings.quiet_hours_enabled
assert auto.quiet_hours_start == time.fromisoformat(settings.quiet_hours_start)
assert auto.quiet_hours_stop == time.fromisoformat(settings.quiet_hours_stop)
assert auto.snooze_until is None, "a snooze survived the restore"
assert auto.leds.strip.chip == settings.led_chip, auto.leds.strip.chip
assert auto.leds.strip.color_order == settings.led_color_order, auto.leds.strip.color_order
assert auto.leds.brightness == DEFAULT_BRIGHTNESS
assert auto.leds.color == DEFAULT_COLOR
assert auto.leds.mode == DEFAULT_MODE
assert auto.sensor_hub.calibration == {}
print("ok: every setting is back on its default, without a restart")

# --- the libraries and the history are kept ---

assert state.load_soils(path) == soils_before, "the soil library changed"
assert state.load_profiles(path) == profiles_before, "the plant profiles changed"
assert history.series([0x36], 1) == readings_before, "readings were lost"
assert history.waterings(1) == waterings_before, "waterings were lost"
print("ok: the plant profiles, the soils and the history are untouched")

# --- and it holds across a restart ---

stored = state.load_state(path)
leftover = set(stored) - {*GreenThumbAutomation.KEPT_STATE_KEYS, "schema_version"}
assert not leftover, f"still in the state file: {sorted(leftover)}"
restarted = build(path)
assert [placement(plant) for plant in restarted.plants] == FRESH
assert restarted.pump.flow_ml_per_second == settings.pump_flow_ml_per_second
assert restarted.leds.brightness == DEFAULT_BRIGHTNESS
assert state.load_calibration(path) == {}
print("ok: the state file holds only the libraries, so a restart comes back fresh too")

# --- not in the middle of a watering ---

auto = build(temp_state())
auto.update_plant_name("plant_1", "Mid-dose")
auto._hardware_lock.acquire()
try:
    auto.restore_system_defaults()
except HardwareBusyError:
    pass
else:
    raise AssertionError("restored while the hardware was busy")
finally:
    auto._hardware_lock.release()
assert auto.get_plant("plant_1").name == "Mid-dose", "partly restored before refusing"
print("ok: refused while a watering holds the hardware, and nothing is half-done")

print("\nall restore-to-defaults checks passed")
