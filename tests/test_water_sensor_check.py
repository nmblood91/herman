"""The water sensor check on the calibration page.

One read of the outlet tube's liquid sensor. What matters is that it answers
while the pump holds the hardware lock, because a running pump is the only time
the falling leg is full, and that a sensor Klipper cannot read is reported as
unreadable rather than as dry.
"""

import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb.config import settings
from greenthumb.hardware.soil_sensors import unavailable_sample
from greenthumb.services.automation import GreenThumbAutomation
from tests.helpers import CalibrationSurface, temp_state, temp_store

settings.auto_watering_enabled = False
settings.auto_patrol_enabled = False


class Klip:
    def __init__(self, present):
        self.present = present

    def status(self):
        return {"ok": True, "position": 0.0, "homed": True}

    def water_supply_present(self):
        return self.present


class Hub(CalibrationSurface):
    addresses = [0x36, 0x37, 0x38, 0x39]
    def read_one(self, a): return unavailable_sample(a)


class Pump:
    is_running = False


class Nul:
    mode = "off"; color = (0, 0, 0); brightness = 0
    def __getattr__(self, n): return lambda *a, **k: {}


def build(present):
    return GreenThumbAutomation(
        Hub(), Klip(present), Pump(), Nul(), history=temp_store(), state_path=temp_state()
    )


auto = build(True)
result = auto.water_sensor_diagnostic()
assert result["ok"] is True and result["wet"] is True, result
print("ok: a full tube reads wet")

auto = build(False)
result = auto.water_sensor_diagnostic()
assert result["ok"] is True and result["wet"] is False, result
print("ok: an empty tube reads dry")

auto = build(None)
result = auto.water_sensor_diagnostic()
assert result["ok"] is False and result["wet"] is None, result
assert "water_supply" in result["detail"], result["detail"]
print("ok: an unreadable sensor is reported as unreadable, not as dry")

for setting in (True, False):
    settings.water_sensor_enabled = setting
    assert build(True).water_sensor_diagnostic()["enabled"] is setting
settings.water_sensor_enabled = False
print("ok: reports whether delivery checks are switched on")

# The pump holds the hardware lock for a whole dose, and that is exactly when
# the check needs to read wet. Taking the lock here would make the full-tube
# step impossible.
auto = build(True)
auto.pump.is_running = True
auto._hardware_lock.acquire()
try:
    result = auto.water_sensor_diagnostic()
finally:
    auto._hardware_lock.release()
assert result["wet"] is True and result["pump_running"] is True, result
print("ok: reads while the pump holds the hardware lock")

print("\nall water sensor check checks passed")
