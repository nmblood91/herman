"""The Calibration tab's live check: a fresh reading from every probe.

It exists to watch a probe respond by hand, so it has to read the probes now,
not hand back the last poll, which can be a minute old.
"""

import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb.config import settings
from greenthumb.models import SensorSample
from greenthumb.services.automation import GreenThumbAutomation, HardwareBusyError
from tests.helpers import CalibrationSurface, temp_state, temp_store

settings.auto_watering_enabled = False
settings.auto_patrol_enabled = False


class Hub(CalibrationSurface):
    addresses = [0x36, 0x37, 0x38, 0x39]
    reading = 400.0

    def read_one(self, a):
        return SensorSample(
            sensor_address=a, moisture_percent=-1.0,
            moisture_raw=self.reading, temperature_c=21.5,
        )


class Nul:
    mode = "off"; color = (0, 0, 0); brightness = 0
    def __getattr__(self, n): return lambda *a, **k: {}


hub = Hub()
auto = GreenThumbAutomation(hub, Nul(), Nul(), Nul(), history=temp_store(), state_path=temp_state())

recorded = []
auto.history.record_readings = lambda samples: recorded.append(samples)
before = {address: auto._latest[address] for address in hub.addresses}

hub.reading = 612.0
live = auto.live_moisture()
sensors = live["sensors"]
assert [s["address"] for s in sensors] == ["0x36", "0x37", "0x38", "0x39"], sensors
assert all(s["raw"] == 612.0 for s in sensors), "did not read the probes now"
assert all(s["dry"] == Hub.raw_dry for s in sensors), sensors
assert all(s["temperature_c"] == 21.5 for s in sensors), sensors
assert all(s["label"] for s in sensors), sensors
print("ok: reads every probe now, with its air reading beside it")

assert not recorded, "a live check was written to history"
assert all(auto._latest[a] is before[a] for a in hub.addresses), "a live check replaced the last poll"
print("ok: leaves history and the last poll alone")

assert auto._lock_holder is None and auto._hardware_lock.acquire(blocking=False)
auto._hardware_lock.release()
with auto._exclusive("Watering Plant 1"):
    try:
        auto.live_moisture()
    except HardwareBusyError as exc:
        assert "Watering Plant 1" in str(exc), exc
    else:
        raise AssertionError("read the probes in the middle of a dose")
print("ok: gives way to a dose, and says what it is waiting on")

print("\nall live moisture checks passed")
