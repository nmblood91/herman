"""Restore to Defaults: every setting with a .env default goes back to it.

Two things matter. It has to take effect now, not after a restart -- a button
that changes nothing until the service is bounced reads as broken. And it must
not touch the planter's own setup: plants, positions, soils and field capacity
have no default to go back to, and losing them would be a factory reset
nobody asked for.
"""

import sys
import types
from datetime import datetime, time, timedelta

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import state
from greenthumb.config import settings
from greenthumb.hardware.lighting import (
    DEFAULT_BRIGHTNESS,
    DEFAULT_COLOR,
    DEFAULT_MODE,
    LedController,
)
from greenthumb.hardware.soil_sensors import unavailable_sample
from greenthumb.services.automation import GreenThumbAutomation
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

    def read_one(self, a):
        return unavailable_sample(a)


class Pump:
    flow_ml_per_second = settings.pump_flow_ml_per_second


def build(path):
    return GreenThumbAutomation(
        Hub(), Klip(), Pump(), LedController(led_count=10),
        history=temp_store(), state_path=path,
    )


path = temp_state()
auto = build(path)

# Change everything Restore to Defaults owns...
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

# ...and the planter's own setup, which it must leave alone.
auto.update_plant_name("plant_1", "Basil")
auto.set_plant_position("plant_2", 300)
auto._persist()

auto.restore_system_defaults()

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
print("ok: every system value is back on its default, without a restart")

assert auto.get_plant("plant_1").name == "Basil"
assert auto.get_plant("plant_2").position_mm == 300
print("ok: plant names and positions are kept")

# On disk too: the system keys are gone, so .env applies on the next start,
# and the plants are still there.
stored = state.load_state(path)
for key in GreenThumbAutomation.SYSTEM_STATE_KEYS:
    assert key not in stored, f"{key} is still in the state file"
assert state.load_calibration(path) == {}
restarted = build(path)
assert restarted.get_plant("plant_1").name == "Basil"
assert restarted.get_plant("plant_2").position_mm == 300
assert restarted.leds.brightness == DEFAULT_BRIGHTNESS
assert restarted.pump.flow_ml_per_second == settings.pump_flow_ml_per_second
print("ok: the state file drops the system values and keeps the plants across a restart")

print("\nall restore-to-defaults checks passed")
