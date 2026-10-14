"""Quiet hours and snooze: when automatic watering is held back, and when not.

The failure mode here is silence -- a bug leaves the planter never watering,
and nothing looks broken. So these check both directions: that it holds when it
should, and that it releases when it should.
"""

import sys, types, tempfile
from datetime import datetime, time, timedelta
from pathlib import Path

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb.config import settings
from greenthumb.history import HistoryStore
from greenthumb.services.automation import GreenThumbAutomation
from tests.helpers import CalibrationSurface, temp_state, temp_store


class Hub(CalibrationSurface):
    addresses = [0x36, 0x37, 0x38, 0x39]
    def read_one(self, a): return None


class Nul:
    mode = "off"; color = (0, 0, 0); brightness = 0
    def __getattr__(self, n): return lambda *a, **k: {}


def build(state=None):
    return GreenThumbAutomation(
        Hub(), Nul(), Nul(), Nul(),
        history=temp_store(), state_path=state or temp_state(),
    )


# --- an overnight window has to wrap past midnight ---

auto = build()
auto.set_quiet_hours(True, "21:00", "08:00")
held = {h: auto.watering_suppressed(datetime(2026, 10, 3, h, 30)) for h in range(24)}
quiet_hours = sorted(h for h, why in held.items() if why)
assert quiet_hours == [0, 1, 2, 3, 4, 5, 6, 7, 21, 22, 23], quiet_hours
print("ok: a 21:00-08:00 window holds overnight and releases in the morning")

# A window that does not wrap behaves the obvious way.
auto.set_quiet_hours(True, "13:00", "15:00")
held = {h: auto.watering_suppressed(datetime(2026, 10, 3, h, 30)) for h in range(24)}
assert sorted(h for h, why in held.items() if why) == [13, 14]
print("ok: a daytime window holds only inside itself")

# Disabled means disabled, whatever the clock says.
auto.set_quiet_hours(False)
assert auto.watering_suppressed(datetime(2026, 10, 3, 2, 0)) is None
print("ok: disabling quiet hours releases immediately")


# --- snooze ---

auto = build()
auto.snooze_watering(2)
assert auto.watering_suppressed() is not None
assert "snooz" in auto.watering_suppressed()
print("ok: a snooze holds watering and says so")

auto.snooze_until = datetime.now() - timedelta(seconds=1)
assert auto.watering_suppressed() is None, "an expired snooze must release on its own"
print("ok: a snooze expires without needing to be cancelled")

auto.snooze_watering(1)
auto.cancel_snooze()
assert auto.watering_suppressed() is None
print("ok: a snooze can be cancelled early")

for bad in (0, -1, 25):
    try:
        auto.snooze_watering(bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"accepted a {bad}h snooze")
print("ok: zero, negative and absurd snooze lengths are refused")


# --- a snooze outlives a restart, but not its own deadline ---

shared = temp_state()
first = build(shared)
first.snooze_watering(3)
again = build(shared)
assert again.snooze_until is not None, "snooze was lost across a restart"
remaining = (again.snooze_until - datetime.now()).total_seconds() / 3600
assert 2.9 < remaining < 3.01, remaining
print("ok: a snooze survives a restart with the right time left")

stale = build(shared)
stale.snooze_until = datetime.now() - timedelta(hours=5)
stale._persist()
recovered = build(shared)
assert recovered.snooze_until is None, "a stale snooze was restored"
assert recovered.watering_suppressed() is None
print("ok: a snooze that expired while powered off is dropped, not restored")


# --- quiet hours survive a restart too ---

shared = temp_state()
build(shared).set_quiet_hours(True, "22:15", "06:45")
restored = build(shared)
assert restored.quiet_hours_enabled is True
assert restored.quiet_hours_start == time(22, 15), restored.quiet_hours_start
assert restored.quiet_hours_stop == time(6, 45), restored.quiet_hours_stop
print("ok: the quiet window survives a restart")

# A corrupt stored window must not stop the planter booting.
import json
shared = temp_state()
shared.parent.mkdir(parents=True, exist_ok=True)
shared.write_text(json.dumps({"quiet": {"enabled": True, "start": "not a time", "stop": "26:00"}}), encoding="utf-8")
booted = build(shared)
assert booted.quiet_hours_start == time.fromisoformat(settings.quiet_hours_start)
print("ok: a corrupt quiet window falls back to the default instead of failing to start")

print("\nall quiet hours checks passed")
