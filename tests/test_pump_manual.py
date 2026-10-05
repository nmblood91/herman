import sys, types, time
sys.modules["smbus2"] = types.ModuleType("smbus2")

from greenthumb.config import settings
from greenthumb.models import SensorSample
from greenthumb.hardware.pump import PumpController
from tests.helpers import temp_state, temp_store
from greenthumb.services.automation import GreenThumbAutomation, HardwareBusyError

settings.auto_watering_enabled = True
settings.water_sensor_enabled = False


class Klip:
    def __init__(self): self.gcode = []; self.moves = []
    def send_gcode(self, g, timeout=5.0):
        self.gcode.append(g); return {"ok": True}
    def move_gantry_absolute(self, p): self.moves.append(p); return {"ok": True}
    def status(self): return {"ok": True}
    def water_supply_present(self): return True

class Hub:
    addresses = [0x36, 0x37, 0x38, 0x39]
    def raw_to_percent(self, raw, address=None): return 0.0
    def read_one(self, a): return SensorSample(a, 0.0, 350.0, 22.0)

class Leds:
    mode = "schedule"
    def set_plant_segments(self, s): pass
    def status(self): return {"mode": "schedule"}


def build():
    klip = Klip()
    auto = GreenThumbAutomation(Hub(), klip, PumpController(klip), Leds(), history=temp_store(), state_path=temp_state())
    return auto, klip


# run then stop drives the pin both ways
auto, klip = build()
result = auto.run_pump()
assert result["status"] == "ok" and result["running"] is True, result
assert klip.gcode[-1] == "SET_PIN PIN=pump VALUE=1", klip.gcode
assert auto.pump.is_running
auto.stop_pump()
assert klip.gcode[-1] == "SET_PIN PIN=pump VALUE=0", klip.gcode
assert auto.pump.is_running is False
print("ok: run then stop drives the pin on and off")

# no dwell queued, so a stop is not stuck behind a G4
assert not any("G4" in g for g in klip.gcode), klip.gcode
print("ok: no G4 dwell queued, so stop takes effect immediately")

# the control loop cannot water while a manual run holds the hardware
auto, klip = build()
for _ in range(10):
    auto.tick()
watered_before = len(klip.moves)
auto.run_pump()
klip.gcode.clear()
for _ in range(5):
    auto.tick()
assert len(klip.moves) == watered_before, "control loop watered during a manual pump run"
print("ok: control loop skips while a manual run holds the lock")

# and resumes once stopped, proving the lock was really released
auto.stop_pump()
assert not auto._hardware_lock.locked(), "lock leaked after stop"
auto._last_watered.clear()  # plants are in cooldown from the first ticks
auto.tick()
assert len(klip.moves) > watered_before, "control loop did not resume after stop"
print("ok: control loop resumes after stop, lock was released")

# stop is idempotent and safe when nothing is running
auto, klip = build()
auto.stop_pump()
auto.stop_pump()
assert not auto._hardware_lock.locked(), "released a lock nobody held"
auto.tick()
print("ok: stop on an idle pump is harmless and does not corrupt the lock")

# a second run while already running is refused, not silently stacked
auto, klip = build()
auto.run_pump()
try:
    auto.run_pump()
except HardwareBusyError as exc:
    print(f"ok: second run rejected -> {exc}")
else:
    raise AssertionError("expected HardwareBusyError")
auto.stop_pump()

# a pump that fails to start must not strand the lock
class DeadPump:
    is_running = False
    def start(self): return {"status": "ok", "pin": 1, "active": False}
    def stop(self): return {}
auto, klip = build()
auto.pump = DeadPump()
result = auto.run_pump()
assert result["status"] == "error", result
assert not auto._hardware_lock.locked(), "failed start stranded the lock"
print("ok: a pump that fails to start releases the lock instead of stranding it")

# the auto-stop timer fires and cleans up without any request
settings.pump_max_run_seconds = 1
auto, klip = build()
auto.run_pump()
assert auto.pump.is_running


def wait_until(predicate, timeout=10.0, interval=0.05):
    """Wait for a real timer, without betting on how long it takes.

    This used to be a flat sleep of 1.4s against a 1s timer. Four hundred
    milliseconds of margin is not much to hand a thread scheduler, and the
    suite failed intermittently because of it -- on a loaded machine, or on
    the Pi, more so. Polling passes as soon as the condition holds and only
    spends the full timeout when something is genuinely wrong.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


assert wait_until(lambda: auto.pump.is_running is False), "auto-stop did not fire"
assert klip.gcode[-1] == "SET_PIN PIN=pump VALUE=0", klip.gcode
assert not auto._hardware_lock.locked(), "auto-stop left the lock held"
auto.tick()
print("ok: auto-stop fires unattended, switches off, and frees the lock")

print("\nall manual pump checks passed")
