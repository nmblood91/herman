"""The hardware lock: who holds it, and what a shutdown may go ahead over.

A dry calibration once held the lock for four sampling windows in a row, one
per probe, while the page counted down one. Every other button said "busy"
with nothing to say why, Reboot and Shutdown included.
"""

import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb.config import settings
from greenthumb.hardware import soil_sensors
from greenthumb.hardware.soil_sensors import calibrate, unavailable_sample
from greenthumb.services import automation as automation_module
from greenthumb.services.automation import GreenThumbAutomation, HardwareBusyError
from tests.helpers import CalibrationSurface, temp_state, temp_store

settings.auto_watering_enabled = False
settings.auto_patrol_enabled = False


class Hub(CalibrationSurface):
    addresses = [0x36, 0x37, 0x38, 0x39]
    def read_one(self, a): return unavailable_sample(a)


class Klip:
    def status(self): return {"ok": True, "position": 0.0, "homed": True, "max_x": 890.0}
    def send_gcode(self, gcode, timeout=5.0): return {"ok": True}
    def home_gantry(self): return {"ok": True}


class Nul:
    mode = "off"; color = (0, 0, 0); brightness = 0
    def __getattr__(self, n): return lambda *a, **k: {}


def build():
    return GreenThumbAutomation(
        Hub(), Klip(), Nul(), Nul(), history=temp_store(), state_path=temp_state()
    )


# --- dry calibration samples every probe in one window ---

windows = []
real_collect = soil_sensors._collect


def counting_collect(hub, seconds, interval, progress=True, addresses=None):
    targets = list(addresses) if addresses else list(hub.addresses)
    windows.append((seconds, targets))
    return {a: {"reads": 100, "errors": 0, "values": [400.0] * 100} for a in targets}


soil_sensors._collect = counting_collect
try:
    hub = Hub()
    hub.field_capacity = {}
    results = calibrate(hub, "dry", seconds=20, state_path=temp_state())
finally:
    soil_sensors._collect = real_collect

assert len(windows) == 1, f"sampled in {len(windows)} windows, not one: {windows}"
assert windows[0] == (20, Hub.addresses), windows
assert all(outcome["written"] for outcome in results.values()), results
print("ok: dry calibration samples all four probes in one 20 s window")


# --- the busy message names what holds the lock ---

auto = build()
with auto._exclusive("Calibrating the dry point", reads_only=True):
    try:
        auto.home_gantry()
    except HardwareBusyError as exc:
        assert "Calibrating the dry point" in str(exc), exc
    else:
        raise AssertionError("homing ran over a calibration")
assert auto._lock_holder is None and auto._hardware_lock.acquire(blocking=False)
auto._hardware_lock.release()
print("ok: busy says what it is busy with, and the holder is cleared after")


# --- a shutdown goes ahead over a sensor read, not over a dose or a move ---

scheduled = []


def fake_request(action, delay=None, on_failure=None):
    scheduled.append((action, on_failure))
    return {"status": "ok", "action": action, "in_seconds": 0}


automation_module.system_power.request = fake_request

auto = build()
with auto._exclusive("Calibrating the dry point", reads_only=True):
    result = auto.request_power("reboot")
    assert result["status"] == "ok", result
    # Once it is scheduled, nothing new may take the hardware.
    try:
        auto.home_gantry()
    except HardwareBusyError as exc:
        assert "shutting down" in str(exc), exc
    else:
        raise AssertionError("homing started after a reboot was scheduled")
print("ok: Reboot goes ahead during a calibration, and blocks anything new")

# The calibration let go; a dose still may not start before the Pi goes down.
try:
    auto.water_plant(auto.plants[0].plant_id)
except HardwareBusyError as exc:
    assert "shutting down" in str(exc), exc
else:
    raise AssertionError("a dose started while the Pi was going down")
print("ok: and once the calibration ends, no dose can start either")

# A reboot that fails leaves a planter that works.
_, on_failure = scheduled[-1]
on_failure()
assert auto._powering_down is False
assert auto.home_gantry()["ok"] is True
print("ok: a failed reboot hands the hardware back")

auto = build()
with auto._exclusive("Moving to Plant 1"):
    try:
        auto.request_power("shutdown")
    except HardwareBusyError as exc:
        assert "Moving to Plant 1" in str(exc), exc
    else:
        raise AssertionError("shut down in the middle of a move")
assert auto._powering_down is False
print("ok: Shutdown is still refused during a move, and says which")

# With nothing running, power takes the lock and keeps it until the Pi is down.
auto = build()
before = len(scheduled)
auto.request_power("shutdown")
assert len(scheduled) == before + 1
assert not auto._hardware_lock.acquire(blocking=False), "the lock was let go"
scheduled[-1][1]()
assert auto._hardware_lock.acquire(blocking=False), "a failed shutdown kept the lock"
auto._hardware_lock.release()
print("ok: an idle shutdown holds the lock, and a failed one releases it")

print("\nall hardware lock checks passed")
