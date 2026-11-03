"""The 12- or 24-hour clock: how the planter writes times of day.

It is stored on the planter rather than in the browser because the planter
writes times itself -- the status bar's "snoozed until" and the log -- and
those should read the same as the page around them.
"""

import sys, types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from datetime import datetime, time, timedelta

from greenthumb.models import SensorSample
from greenthumb.services.automation import GreenThumbAutomation
from tests.helpers import CalibrationSurface, temp_state, temp_store


class Klip:
    def status(self): return {"ok": True, "homed": True, "position": 0.0}
    def __getattr__(self, n): return lambda *a, **k: {"ok": True}


class Nul:
    mode = "off"; color = (0, 0, 0); brightness = 0
    def __getattr__(self, n): return lambda *a, **k: {}


class Hub(CalibrationSurface):
    addresses = [0x36, 0x37, 0x38, 0x39]
    def read_one(self, a): return SensorSample(a, 0.0, 900.0, 21.0)
    def raw_to_percent(self, raw, address=None): return 50.0


def build(state_path):
    return GreenThumbAutomation(Hub(), Klip(), Nul(), Nul(), history=temp_store(), state_path=state_path)


state_path = temp_state()
auto = build(state_path)

# --- formatting ---

assert auto.clock_24h is False
assert auto.format_clock(time(14, 0)) == "2:00 PM"
assert auto.format_clock(time(0, 5)) == "12:05 AM"
assert auto.format_clock(time(12, 30)) == "12:30 PM"
assert auto.format_clock("07:00") == "7:00 AM"
assert auto.format_clock("2026-11-02T21:15:00") == "9:15 PM"
print("ok: a new planter writes times on the 12-hour clock")

auto.set_clock_24h(True)
assert auto.format_clock(time(14, 0)) == "14:00"
assert auto.format_clock(time(7, 5)) == "07:05"
assert auto.format_clock("2026-11-02T21:15:00") == "21:15"
print("ok: the 24-hour clock writes 14:00")

# --- the status bar's own times follow it ---

auto.set_clock_24h(False)
auto.snooze_until = datetime.now().replace(hour=15, minute=0, second=0, microsecond=0) + timedelta(days=1)
assert auto._motion_held() == "snoozed until 3:00 PM", auto._motion_held()
auto.set_clock_24h(True)
assert auto._motion_held() == "snoozed until 15:00", auto._motion_held()
auto.snooze_until = None
print("ok: the snooze line in the status bar follows the setting")

assert auto.get_overview()["clock_24h"] is True
print("ok: the overview carries the setting for the page")

# --- stored, so it survives a restart ---

again = build(state_path)
assert again.clock_24h is True
print("ok: the choice survives a restart")

again._restore_defaults_locked()
assert again.clock_24h is False
print("ok: restoring defaults goes back to the 12-hour clock")

print("\nall clock format checks passed")
