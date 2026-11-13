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
print("ok: a snooze expires without needing to be canceled")

auto.snooze_watering(1)
auto.cancel_snooze()
assert auto.watering_suppressed() is None
print("ok: a snooze can be canceled early")

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


# --- a snooze and a cooldown are instants, not readings of the local clock ---
#
# Kept as a local date and time, both moved by an hour when the clocks changed
# and by hours when the timezone was set from the UI.

import json  # noqa: E402
from datetime import timezone  # noqa: E402
from time import time as epoch_now  # noqa: E402

shared = temp_state()
first = build(shared)
first.snooze_watering(2)
assert abs(first._snooze_until_epoch - (epoch_now() + 2 * 3600)) < 5
stored = datetime.fromisoformat(json.loads(shared.read_text(encoding="utf-8"))["quiet"]["snooze_until"])
assert stored.utcoffset() is not None, "the snooze was stored without its UTC offset"
assert abs(stored.timestamp() - first._snooze_until_epoch) < 1
print("ok: a snooze is stored as an instant, with its UTC offset")


def restored_snooze(text):
    path = temp_state()
    path.write_text(json.dumps({"quiet": {"snooze_until": text}}), encoding="utf-8")
    return build(path)


# Written in a zone ten hours from wherever this runs: still the same instant.
elsewhere = timezone(timedelta(hours=10))
in_an_hour = datetime.now(elsewhere) + timedelta(hours=1)
auto = restored_snooze(in_an_hour.isoformat())
assert abs(auto._snooze_until_epoch - in_an_hour.timestamp()) < 1
remaining = (auto.snooze_until - datetime.now()).total_seconds() / 3600
assert 0.98 < remaining < 1.01, remaining
assert auto.watering_suppressed() is not None
assert auto.watering_suppressed(datetime.now(elsewhere) + timedelta(hours=2)) is None
print("ok: a snooze stored in another timezone ends at the same instant here")

# One stored before the offset was kept is read as the planter's own time.
auto = restored_snooze((datetime.now() + timedelta(hours=1)).isoformat())
assert 0.98 < (auto.snooze_until - datetime.now()).total_seconds() / 3600 < 1.01
print("ok: a snooze stored without an offset is still restored")

minutes = settings.watering_cooldown_minutes
auto = build()
auto._last_watered["plant_1"] = epoch_now() - (minutes - 30) * 60
assert not auto._cooldown_elapsed("plant_1")
assert not auto._cooldown_elapsed("plant_1", now=datetime.now(elsewhere))
assert auto._cooldown_elapsed("plant_1", now=datetime.now(elsewhere) + timedelta(minutes=31))
auto._last_watered["plant_1"] = epoch_now() - (minutes + 1) * 60
assert auto._cooldown_elapsed("plant_1")
assert auto._last_watered_iso("plant_1") == datetime.fromtimestamp(
    auto._last_watered["plant_1"]
).isoformat(timespec="seconds")
print("ok: the cooldown is elapsed real time, whatever zone the clock is read in")

print("\nall quiet hours checks passed")
