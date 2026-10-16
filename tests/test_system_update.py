"""Updating from the web UI.

What matters: an update is only offered when apt would really install a newer
version, it is refused mid-dose, and the hardware lock it takes is held until
the API restarts -- or handed back if the update ends without restarting it,
so a failed update cannot leave the planter unable to water.
"""

import json
import sys
import tempfile
import time
import types
from pathlib import Path

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

import greenthumb.services.automation as automation_module
from greenthumb import paths, system_update
from greenthumb.config import settings
from greenthumb.hardware.soil_sensors import unavailable_sample
from greenthumb.services.automation import GreenThumbAutomation, HardwareBusyError
from tests.helpers import CalibrationSurface, temp_state, temp_store

settings.auto_watering_enabled = False
settings.auto_patrol_enabled = False
automation_module.UPDATE_START_GRACE_SECONDS = 0.3
automation_module.UPDATE_POLL_SECONDS = 0.01


def debian_newer(a, b):
    # Enough of Debian's ordering for these tests: "0.3.0~dev4" is below
    # "0.3.0" and above "0.2.0".
    def key(version):
        base, _, pre = version.partition("~")
        return tuple(int(n) for n in base.split(".")), 0 if pre else 1, pre
    return key(a) > key(b)


class Host:
    """dpkg, systemctl and sudo, as far as system_update uses them."""

    def __init__(self):
        self.installed = "0.2.0"
        self.active = set()
        self.allowed = True
        self.started = []
        # What the unit does once started: stay up for a few polls, then stop.
        self.unit_runs_for = 5

    def run(self, cmd, **kwargs):
        ok = lambda out="": types.SimpleNamespace(returncode=0, stdout=out, stderr="")
        no = lambda err="": types.SimpleNamespace(returncode=1, stdout="", stderr=err)
        if cmd[0] == "dpkg-query":
            return ok(self.installed)
        if cmd[:2] == ["dpkg", "--compare-versions"]:
            return ok() if debian_newer(cmd[2], cmd[4]) else no()
        if cmd[0] == system_update.SYSTEMCTL and cmd[1] == "is-active":
            unit = cmd[2]
            if unit in self.active:
                self.polls[unit] = self.polls.get(unit, 0) + 1
                if self.polls[unit] > self.unit_runs_for:
                    self.active.discard(unit)
                    return ok("inactive")
                return ok("active")
            return ok("inactive")
        if cmd[:3] == ["sudo", "-n", "-l"]:
            return ok() if self.allowed else no("not allowed")
        if cmd[:2] == ["sudo", "-n"]:
            self.started.append(cmd[-1])
            self.active.add(cmd[-1])
            self.polls = {}
            return ok()
        raise AssertionError(f"unexpected command {cmd}")


host = Host()
host.polls = {}
system_update.subprocess.run = host.run
data = Path(tempfile.mkdtemp())
paths.DATA_DIR = data


def write_status(**fields):
    (data / "update-status.json").write_text(json.dumps(fields), encoding="utf-8")


# --- a checkout does not offer updates ---

paths.PACKAGED = False
assert system_update.status()["supported"] is False
try:
    system_update.check()
except ValueError:
    pass
else:
    raise AssertionError("a checkout started an update check")
print("ok: a git checkout says it is not updated from the UI")

paths.PACKAGED = True


# --- what counts as available ---

write_status(candidate="0.3.0", checked_at="2026-10-16T08:00:00+00:00", check_state="checked")
result = system_update.status()
assert result["installed"] == "0.2.0" and result["available"] == "0.3.0", result
write_status(candidate="0.2.0")
assert system_update.status()["available"] is None
write_status(candidate="0.3.0~dev4")
assert system_update.status()["available"] == "0.3.0~dev4"
host.installed = "0.3.0"
assert system_update.status()["available"] is None, "a dev build below the installed release was offered"
host.installed = "0.2.0"
print("ok: only a version apt would upgrade to is offered")

write_status(state="running", candidate="0.3.0", log_tail=["E: Sub-process /usr/bin/dpkg returned an error"])
result = system_update.status()
assert result["state"] == "interrupted" and result["log_tail"], result
print("ok: an update that stopped without finishing reads as interrupted, with its log")


# --- installing ---

class Hub(CalibrationSurface):
    addresses = [0x36, 0x37, 0x38, 0x39]
    def read_one(self, a): return unavailable_sample(a)


class Nul:
    mode = "off"; color = (0, 0, 0); brightness = 0; is_running = False
    def __getattr__(self, n): return lambda *a, **k: {}


def build():
    return GreenThumbAutomation(Hub(), Nul(), Nul(), Nul(), history=temp_store(), state_path=temp_state())


write_status(candidate="0.3.0")

auto = build()
auto._hardware_lock.acquire()
try:
    auto.request_update()
except HardwareBusyError:
    assert not host.started, host.started
else:
    raise AssertionError("updated mid-dose")
auto._hardware_lock.release()
print("ok: refused while the hardware is busy")

write_status(candidate="0.2.0")
try:
    build().request_update()
except ValueError as exc:
    assert "up to date" in str(exc), exc
else:
    raise AssertionError("started an update with nothing to install")
write_status(candidate="0.3.0")
print("ok: refused when already up to date")

host.allowed = False
auto = build()
try:
    auto.request_update()
except RuntimeError as exc:
    assert "permission" in str(exc), exc
else:
    raise AssertionError("expected RuntimeError without the sudoers rule")
assert not auto._hardware_lock.locked(), "a refused update left the planter locked"
host.allowed = True
print("ok: a missing permission is reported and the lock handed back")

auto = build()
result = auto.request_update()
assert result["updating_to"] == "0.3.0", result
assert host.started == [system_update.UPDATE_UNIT], host.started
assert auto._hardware_lock.locked(), "a dose could start mid-update"
print("ok: the update unit is started and the hardware held while it runs")

# This unit stops without the API being restarted, as when the upgrade fails.
end = time.monotonic() + 3
while auto._hardware_lock.locked() and time.monotonic() < end:
    time.sleep(0.01)
assert not auto._hardware_lock.locked(), "a failed update left the planter locked"
print("ok: the lock is handed back when the update ends without a restart")

print("\nall system update checks passed")
