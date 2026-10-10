"""The master switch for unattended watering.

This is the one setting that decides whether the pump can run with nobody
watching, so it is checked in both directions: that off really means the loop
never waters, and that the choice survives a restart. A switch that silently
reverts to the compiled-in default after a power cut would be worse than no
switch at all -- the planter would look armed and not be, or the reverse.
"""

import json
import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb.config import settings
from greenthumb.hardware.soil_sensors import SoilSensorHub
from greenthumb.models import SensorSample
from greenthumb.services.automation import GreenThumbAutomation
from tests.helpers import give_every_plant_soil, temp_state, temp_store

settings.water_sensor_enabled = False
# The starting value only. Every case below sets the switch explicitly, so a
# test must never be passing because of what the environment happened to say.
settings.auto_watering_enabled = False


class DryHub:
    """Every plant reading bone dry, so anything that can water, will."""

    raw_dry = settings.moisture_raw_dry
    calibration = {}
    calibration: dict = {}
    field_capacity: dict = {}
    dry_for = SoilSensorHub.dry_for
    span_for = SoilSensorHub.span_for
    raw_to_percent = SoilSensorHub.raw_to_percent
    addresses = [0x36, 0x37, 0x38, 0x39]

    def read_one(self, address):
        raw = self.raw_dry + 5
        return SensorSample(address, self.raw_to_percent(raw, address), float(raw), 22.0)


class FakePump:
    is_running = False

    def __init__(self):
        self.doses = []

    def deliver_ml(self, volume_ml=180, **kw):
        self.doses.append(volume_ml)


class FakeKlipper:
    def __init__(self):
        self.moves = []

    def move_gantry_absolute(self, pos):
        self.moves.append(pos)
        return {"ok": True}

    def status(self):
        return {"ok": True, "position": 0.0, "homed": True}

    def water_supply_present(self):
        return True


class FakeLeds:
    mode = "schedule"
    def set_plant_segments(self, segments): pass
    def status(self): return {"mode": self.mode, "connected": True}


def build(state=None):
    pump = FakePump()
    auto = give_every_plant_soil(
        GreenThumbAutomation(
            DryHub(), FakeKlipper(), pump, FakeLeds(),
            history=temp_store(), state_path=state or temp_state(),
        )
    )
    return auto, pump


def run_loop(auto, ticks=None):
    """Tick enough times to fill the moisture window and then act."""
    for _ in range(ticks or settings.moisture_window_size + 2):
        auto.tick()


# --- off means the pump never runs on its own ---

auto, pump = build()
auto.set_auto_watering(False)
run_loop(auto)
assert pump.doses == [], f"watered with the switch off: {pump.doses}"
print("ok: with automatic watering off, a bone-dry planter is never watered")

# Sensors and history keep running, which is what makes "watching only" honest.
assert len(auto._history.get(0x36) or ()) > 0, "stopped polling sensors when off"
print("ok: it keeps reading sensors while switched off")


# --- on means it does ---

auto, pump = build()
auto.set_auto_watering(True)
run_loop(auto)
assert pump.doses, "did not water with the switch on and every plant dry"
print(f"ok: with it on, the dry planter is watered ({len(pump.doses)} doses)")


# --- flipping it off mid-run stops the next cycle ---

auto, pump = build()
auto.set_auto_watering(True)
run_loop(auto)
assert pump.doses
before = len(pump.doses)
auto.set_auto_watering(False)
auto._last_watered.clear()  # clear the cooldown, so only the switch can stop it
run_loop(auto)
assert len(pump.doses) == before, "kept watering after being switched off"
print("ok: switching it off stops the very next cycle")


# --- the choice outlives a restart ---

shared = temp_state()
first, _ = build(shared)
first.set_auto_watering(True)
restored, _ = build(shared)
assert restored.auto_watering_enabled is True, "the switch was lost across a restart"
print("ok: turning it on survives a restart")

# And the stored value wins over the compiled-in default, in both directions.
assert settings.auto_watering_enabled is False, "this case needs a False default"
assert build(shared)[0].auto_watering_enabled is True
build(shared)[0].set_auto_watering(False)
assert build(shared)[0].auto_watering_enabled is False
print("ok: what is stored beats the default, on and off alike")


# --- a corrupt file must not stop the planter booting ---

shared = temp_state()
shared.parent.mkdir(parents=True, exist_ok=True)
shared.write_text(json.dumps({"watering": {"auto_enabled": "yes please"}}), encoding="utf-8")
recovered, _ = build(shared)
assert recovered.auto_watering_enabled is settings.auto_watering_enabled
print("ok: a junk stored value falls back to the default instead of crashing")


# --- what the rest of the system says about it ---

auto, _ = build()
auto.set_auto_watering(False)
assert auto.watering_status()["auto_watering_enabled"] is False
assert auto.get_overview()["watering"]["auto_watering_enabled"] is False
print("ok: the overview reports the switch, so the UI can show it")

# Off is a standing choice, not a fault and not a pause -- the status bar words
# those three differently and the distinction is the point.
message = auto.system_status()["message"]
assert "Watching only" in message, message
assert auto.watering_suppressed() is None, "off must not read as suppressed"
print("ok: off reads as 'watching only' rather than as paused or broken")

print("\nall automatic watering checks passed")
