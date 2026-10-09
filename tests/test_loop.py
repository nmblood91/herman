import sys, types, threading
from datetime import datetime, timedelta

sys.modules["smbus2"] = types.ModuleType("smbus2")  # no I2C on the laptop

from greenthumb.config import settings
from greenthumb.hardware.soil_sensors import SoilSensorHub
from greenthumb.models import SensorSample
from tests.helpers import give_every_plant_soil, temp_state, temp_store
from greenthumb.services.automation import GreenThumbAutomation, HardwareBusyError

settings.auto_watering_enabled = True


class FakeHub:
    # Borrows the real conversion rather than copying it. The copy that used to
    # live here had already drifted: it took no address, so it knew nothing
    # about per-sensor calibration, and it divided by a raw span with no
    # divide-by-zero guard -- meaning these tests were exercising the test's
    # arithmetic instead of the shipped function.
    raw_dry = settings.moisture_raw_dry
    raw_wet = settings.moisture_raw_wet
    calibration = {}
    endpoints_for = SoilSensorHub.endpoints_for
    raw_to_percent = SoilSensorHub.raw_to_percent

    def __init__(self, raw):
        self.addresses = [0x36, 0x37, 0x38, 0x39]
        self.raw = raw

    def read_one(self, address):
        if address != 0x36:
            return SensorSample(address, -1.0, -1.0, -1.0)
        return SensorSample(address, self.raw_to_percent(self.raw), float(self.raw), 22.0)


class FakePump:
    def __init__(self):
        self.calls = []
        self.is_running = False

    def deliver_ml(self, volume_ml=180, **kw):
        self.calls.append(volume_ml)


class FakeKlipper:
    def __init__(self):
        self.moves = []

    def move_gantry_absolute(self, pos):
        self.moves.append(pos)
        return {"ok": True}

    def status(self):
        return {"ok": True, "position": 0.0, "homed": True}


class FakeLeds:
    mode = "schedule"

    def __init__(self):
        self.segments = None

    def set_plant_segments(self, segments):
        self.segments = segments

    def status(self):
        return {"mode": self.mode, "connected": True}


def build(raw):
    hub = FakeHub(raw)
    pump = FakePump()
    auto = give_every_plant_soil(
        GreenThumbAutomation(hub, FakeKlipper(), pump, FakeLeds(), history=temp_store(), state_path=temp_state())
    )
    return auto, pump


# 1. window must fill before anything waters
auto, pump = build(settings.moisture_raw_dry)
for _ in range(9):
    auto.tick()
assert pump.calls == [], f"watered before window filled: {pump.calls}"
auto.tick()
assert len(pump.calls) == 1, f"expected one watering at full window, got {pump.calls}"
print("ok: no watering until window is full, then waters once")

# 2. cooldown blocks repeat watering while still dry
for _ in range(5):
    auto.tick()
assert len(pump.calls) == 1, f"cooldown did not hold: {pump.calls}"
print("ok: cooldown suppresses repeat watering")

# 3. cooldown expiry allows watering again
auto._last_watered["plant_1"] = datetime.now() - timedelta(
    minutes=settings.watering_cooldown_minutes + 1
)
auto.tick()
assert len(pump.calls) == 2, f"expected watering after cooldown, got {pump.calls}"
print("ok: waters again once cooldown expires")

# 4. wet soil never waters
auto, pump = build(settings.moisture_raw_wet)
for _ in range(15):
    auto.tick()
assert pump.calls == [], f"watered wet soil: {pump.calls}"
assert auto.smoothed_percent(0x36) == 100.0
print("ok: saturated soil is left alone")

# 5. averaging reflects the window, not the last read
auto, pump = build(settings.moisture_raw_dry)
for _ in range(5):
    auto.tick()
auto.sensor_hub.raw = settings.moisture_raw_wet
for _ in range(5):
    auto.tick()
avg = auto.smoothed_percent(0x36)
assert 45 < avg < 55, f"expected mid-range average, got {avg}"
print(f"ok: rolling average smooths a step change -> {avg}%")

# 6. a manual command is rejected while the loop holds the hardware
auto, pump = build(settings.moisture_raw_dry)
auto._hardware_lock.acquire()
try:
    auto.water_plant("plant_1")
except HardwareBusyError as exc:
    print(f"ok: manual command rejected while busy -> {exc}")
else:
    raise AssertionError("expected HardwareBusyError")
finally:
    auto._hardware_lock.release()

# 7. the loop skips rather than blocking when a manual command holds the lock
auto._hardware_lock.acquire()
auto.tick()
auto._hardware_lock.release()
assert len(auto._history[0x36]) == 0, "tick polled while hardware was busy"
print("ok: tick skips instead of blocking")

# 8. missing sensors never enter the average or trigger watering
assert auto.smoothed_percent(0x37) == -1.0
print("ok: absent sensor reports -1 and is excluded")

# 9. a sensor read that raises must not kill the loop
class Exploding(FakeHub):
    def read_one(self, address):
        raise OSError("bus fell over")

auto2 = give_every_plant_soil(GreenThumbAutomation(Exploding(settings.moisture_raw_dry), FakeKlipper(), FakePump(), FakeLeds(), history=temp_store(), state_path=temp_state()))
auto2.tick()
assert not auto2._hardware_lock.locked(), "lock leaked after a failing tick"
print("ok: failing tick is contained and releases the lock")


# --- manual watering goes to the plant first ---
auto, pump = build(settings.moisture_raw_dry)
plant1 = auto.get_plant("plant_1")
result = auto.water_plant("plant_1")
assert auto.klipper.moves == [plant1.position_mm], auto.klipper.moves
assert pump.calls == [plant1.watering_volume_ml], pump.calls
assert result["volume_ml"] == plant1.watering_volume_ml
print("ok: manual watering moves to the plant and uses its own volume")

result = auto.water_plant("plant_2", volume_ml=25)
assert pump.calls[-1] == 25, pump.calls
print("ok: an explicit volume overrides the plant default")

try:
    auto.water_plant("plant_9")
except ValueError as exc:
    print(f"ok: unknown plant rejected -> {exc}")
else:
    raise AssertionError("expected ValueError")


class RefusingKlipper(FakeKlipper):
    def move_gantry_absolute(self, pos):
        return {"ok": False, "error": "must home first"}


auto2 = give_every_plant_soil(GreenThumbAutomation(FakeHub(settings.moisture_raw_dry), RefusingKlipper(), FakePump(), FakeLeds(), history=temp_store(), state_path=temp_state()))
result = auto2.water_plant("plant_1")
assert result["status"] == "error", result
assert auto2.pump.calls == [], "pumped despite a failed move"
print("ok: a failed move blocks the pump instead of watering the wrong spot")

# --- pump driver over Klipper ---
from greenthumb.hardware.pump import PumpController


class ScriptRecorder:
    def __init__(self, ok=True, boom=False):
        self.scripts = []
        self.ok = ok
        self.boom = boom

    def send_gcode(self, gcode, timeout=5.0):
        self.scripts.append(gcode)
        if self.boom and len(self.scripts) == 1:
            raise OSError("socket died mid-dose")
        return {"ok": self.ok, "error": None if self.ok else "shutdown"}


rec = ScriptRecorder()
result = PumpController(rec, flow_ml_per_second=2.5).deliver_ml(180)
assert result["status"] == "ok", result
assert result["duration_seconds"] == 72.0, result
dose = rec.scripts[0]
assert dose.splitlines() == [
    "SET_PIN PIN=pump VALUE=1",
    "G4 P72000",
    "SET_PIN PIN=pump VALUE=0",
], dose
print(f"ok: 180 mL at 2.5 mL/s -> 72s dwell")

# the trailing off command must always follow, success or not
assert rec.scripts[-1] == "SET_PIN PIN=pump VALUE=0", rec.scripts
print("ok: pump commanded off after a successful dose")

rec = ScriptRecorder(ok=False)
result = PumpController(rec).deliver_ml(180)
assert result["status"] == "error", result
assert rec.scripts[-1] == "SET_PIN PIN=pump VALUE=0", rec.scripts
print("ok: Klipper rejection reported as error, pump still switched off")

rec = ScriptRecorder(boom=True)
pump = PumpController(rec)
try:
    pump.deliver_ml(180)
except OSError:
    pass
assert rec.scripts[-1] == "SET_PIN PIN=pump VALUE=0", rec.scripts
assert pump.is_running is False
print("ok: dropped connection mid-dose still forces the pump off")

print("\nall checks passed")


# --- settings survive a restart ---------------------------------------------
# The bug this guards: plants were rebuilt from hardcoded literals on every
# startup, so anything changed through the UI was lost on the next restart.

shared = temp_state()


def fresh(state_file):
    return GreenThumbAutomation(
        FakeHub(settings.moisture_raw_dry), FakeKlipper(), FakePump(), FakeLeds(),
        history=temp_store(), state_path=state_file,
    )


before = fresh(shared)
default_target = before.get_plant("plant_1").moisture_target
before.update_moisture_target("plant_1", "very dry")
before.update_watering_volume("plant_2", 250)
before.set_plant_position("plant_3", 500)
before.update_plant_name("plant_4", "Monstera")

after = fresh(shared)
assert after.get_plant("plant_1").moisture_target == "very dry", after.get_plant("plant_1").moisture_target
assert after.get_plant("plant_2").watering_volume_ml == 250
assert after.get_plant("plant_3").position_mm == 500
assert after.get_plant("plant_4").name == "Monstera"
assert default_target != 61, "test would pass vacuously if 61 were the default"
print("ok: plant edits survive a restart")

untouched = fresh(temp_state())
assert untouched.get_plant("plant_1").moisture_target == default_target
print("ok: a fresh install still gets the built-in defaults")

# A corrupt settings file must not stop the service booting.
bad = temp_state()
bad.parent.mkdir(parents=True, exist_ok=True)
bad.write_text("{truncated", encoding="utf-8")
recovered = fresh(bad)
assert recovered.get_plant("plant_1").moisture_target == default_target
print("ok: a corrupt settings file falls back to defaults instead of failing to start")
