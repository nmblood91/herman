"""Shutdown and reboot from the UI.

The command arrives from a browser and runs as root, so the action is an
allow-list and the command a fixed list. The other thing worth pinning is the
hardware lock: it is kept until the Pi goes down, so no dose can start in the
gap and be left running by a pump nothing will turn off, and it is handed back
whenever the Pi turns out not to be going down after all.
"""

import sys
import time
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import system_power
from greenthumb.config import settings
from greenthumb.hardware.soil_sensors import unavailable_sample
from greenthumb.services.automation import GreenThumbAutomation, HardwareBusyError
from tests.helpers import CalibrationSurface, temp_state, temp_store

settings.auto_watering_enabled = False
settings.auto_patrol_enabled = False

calls = []
allowed = True
command_ok = True


def fake_run(cmd, **kwargs):
    calls.append(cmd)
    if "-l" in cmd:
        return types.SimpleNamespace(returncode=0 if allowed else 1, stdout="", stderr="")
    return types.SimpleNamespace(
        returncode=0 if command_ok else 1, stdout="", stderr="" if command_ok else "Access denied"
    )


system_power.subprocess.run = fake_run


def wait_for(predicate, seconds=2.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# --- the action is an allow-list ---

for hostile in ("", "halt", "reboot; rm -rf /", "poweroff", "SHUTDOWN", "shutdown "):
    calls.clear()
    try:
        system_power.request(hostile, delay=0)
    except ValueError:
        assert not calls, (hostile, calls)
    else:
        raise AssertionError(f"accepted {hostile!r}")
print("ok: anything but shutdown or reboot is rejected before any command runs")

for action, verb in (("shutdown", "poweroff"), ("reboot", "reboot")):
    calls.clear()
    result = system_power.request(action, delay=0)
    assert result["action"] == action, result
    assert calls[0] == ["sudo", "-n", "-l", "/usr/bin/systemctl", verb], calls
    assert wait_for(lambda: len(calls) == 2), calls
    assert calls[1] == ["sudo", "-n", "/usr/bin/systemctl", verb], calls
print("ok: checks permission first, then runs systemctl poweroff or reboot as a list")

# Refused by sudo: an error now, while the page is still listening, and nothing run.
allowed = False
calls.clear()
try:
    system_power.request("shutdown", delay=0)
except RuntimeError as exc:
    assert "installer" in str(exc), exc
else:
    raise AssertionError("expected RuntimeError without the sudoers rule")
time.sleep(0.05)
assert len(calls) == 1, calls
allowed = True
print("ok: a missing sudoers rule is reported up front and nothing runs")


# --- the hardware lock ---

class Hub(CalibrationSurface):
    addresses = [0x36, 0x37, 0x38, 0x39]
    def read_one(self, a): return unavailable_sample(a)


class Nul:
    mode = "off"; color = (0, 0, 0); brightness = 0; is_running = False
    def __getattr__(self, n): return lambda *a, **k: {}


def build():
    return GreenThumbAutomation(
        Hub(), Nul(), Nul(), Nul(), history=temp_store(), state_path=temp_state()
    )


# Read at call time, so the automation path runs without the real two seconds.
system_power.DELAY_SECONDS = 0

auto = build()
auto._hardware_lock.acquire()
calls.clear()
try:
    auto.request_power("shutdown")
except HardwareBusyError:
    assert not calls, calls
else:
    raise AssertionError("shut down mid-dose")
auto._hardware_lock.release()
print("ok: refused while the hardware is busy")

auto = build()
auto.request_power("shutdown")
assert wait_for(lambda: len(calls) >= 2)
assert auto._hardware_lock.locked(), "a dose could start before the Pi goes down"
print("ok: the lock is kept once a shutdown is on its way")

allowed = False
auto = build()
try:
    auto.request_power("reboot")
except RuntimeError:
    pass
assert not auto._hardware_lock.locked(), "a refused reboot left the planter locked"
allowed = True

auto = build()
try:
    auto.request_power("explode")
except ValueError:
    pass
assert not auto._hardware_lock.locked(), "an unknown action left the planter locked"

command_ok = False
auto = build()
auto.request_power("shutdown")
assert wait_for(lambda: not auto._hardware_lock.locked()), (
    "a shutdown that failed left the planter locked"
)
command_ok = True
print("ok: the lock is handed back when the Pi is not going down after all")

print("\nall system power checks passed")
