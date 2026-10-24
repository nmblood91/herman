"""The motor direction test, and the lock it puts on homing.

Every unit is wired by hand, and a motor turning the wrong way homes away from
the switch and into the far end of the rail at homing speed. So nothing homes
until the test has passed, the test itself has to work before any home, and a
"wrong way" answer has to flip the direction in a file the installer leaves
alone.
"""

import sys
import tempfile
import types
from pathlib import Path

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb.config import settings
from greenthumb.hardware.soil_sensors import unavailable_sample
from greenthumb.services import automation as automation_module
from greenthumb.services.automation import DIRECTION_FILE, GreenThumbAutomation
from tests.helpers import CalibrationSurface, temp_state, temp_store

settings.auto_watering_enabled = False
settings.auto_patrol_enabled = False
settings.home_on_startup = True
# helpers.py passes the test for every other script; this one is about the lock.
settings.motor_direction_checked = False

TRAVEL = 890.0


class Klip:
    def __init__(self, homed=False, position=0.0, dir_pin="!PB12"):
        self._homed = homed
        self.position = position
        self._dir_pin = dir_pin
        self.calls = []

    def status(self):
        return {"ok": True, "position": self.position, "homed": self._homed, "max_x": TRAVEL}

    def home_gantry(self):
        self.calls.append("home")
        return {"ok": True}

    def send_gcode(self, gcode, timeout=5.0):
        self.calls.append(gcode)
        return {"ok": True}

    def test_direction(self, distance_mm):
        self.calls.append(("force_move", distance_mm))
        return {"ok": True}

    def release_motors(self):
        self.calls.append("release")
        return {"ok": True}

    def dir_pin(self):
        return self._dir_pin

    def restart(self):
        self.calls.append("restart")
        # What a real restart usually answers: the socket goes away first.
        return {"ok": False, "error": "Klipper closed the connection"}


class Hub(CalibrationSurface):
    addresses = [0x36, 0x37, 0x38, 0x39]
    def read_one(self, a): return unavailable_sample(a)


class Nul:
    mode = "off"; color = (0, 0, 0); brightness = 0
    def __getattr__(self, n): return lambda *a, **k: {}


def build(klip, state_path=None):
    return GreenThumbAutomation(
        Hub(), klip, Nul(), Nul(), history=temp_store(),
        state_path=state_path or temp_state(),
    )


config_dir = Path(tempfile.mkdtemp())
settings.klipper_config_dir = str(config_dir)
direction_file = config_dir / DIRECTION_FILE


# --- untested, nothing homes ---

klip = Klip()
auto = build(klip)
result = auto.home_gantry()
assert result["ok"] is False, result
assert "Calibration" in result["error"], result
assert "home" not in klip.calls, klip.calls
print("ok: the Home button is refused until the direction test has passed")

result = auto.run_dance("patrol")
assert result["ok"] is False, result
assert "home" not in klip.calls and not any("G1" in str(c) for c in klip.calls), klip.calls
print("ok: a routine on an unhomed gantry is refused too, before it moves")

auto._maybe_home_on_startup()
assert "home" not in klip.calls, klip.calls
assert auto.startup_home_status()["phase"] == "retrying", auto.startup_home_status()
assert "Calibration" in (auto.startup_home_status()["error"] or "")
print("ok: the startup home waits, and says why")

status = auto.system_status()
assert status["level"] == "attention" and "Calibration" in status["message"], status
assert auto.get_overview()["motor_direction"]["checked"] is False
print("ok: the status bar and the overview both say the test is still to do")


# --- the test itself works unhomed, and hands the carriage back ---

result = auto.test_motor_direction()
assert result["ok"] is True, result
assert ("force_move", 10.0) in klip.calls, klip.calls
assert auto.motor_direction_checked is False, "turning the motor is not passing the test"
print("ok: the test turns the motor 10 mm toward the switch, before any home")

klip = Klip(homed=True, position=TRAVEL - 5)
result = build(klip).test_motor_direction()
assert result["ok"] is False and "too close" in result["error"], result
assert not any(isinstance(c, tuple) for c in klip.calls), klip.calls
print("ok: a homed carriage right by the switch is not run into it")

klip = Klip()
assert build(klip).release_motors()["ok"] is True
assert klip.calls == ["release"], klip.calls
print("ok: Release motors switches them off so the arm slides by hand")


# --- "toward the switch" passes, and stays passed ---

state_path = temp_state()
klip = Klip()
auto = build(klip, state_path)
result = auto.answer_motor_direction(True)
assert result["ok"] is True and result["checked"] is True, result
assert result["reversed"] is False, result
assert not direction_file.exists(), "a pass must not write an override"
assert auto.home_gantry()["ok"] is True
assert "home" in klip.calls
print("ok: a pass unlocks homing")

assert build(Klip(), state_path).motor_direction_checked is True
print("ok: the pass survives a restart")

auto.restore_system_defaults()
assert auto.motor_direction_checked is True
assert build(Klip(), state_path).motor_direction_checked is True
print("ok: Restore to Defaults keeps it, since it is how the unit is wired")


# --- "away" flips it, restarts Klipper, and wants another test ---

state_path = temp_state()
klip = Klip(dir_pin="!PB12")
auto = build(klip, state_path)
auto.answer_motor_direction(True)
result = auto.answer_motor_direction(False)
assert result["ok"] is True, result
text = direction_file.read_text(encoding="utf-8")
assert "[stepper_x]" in text and "dir_pin: PB12" in text, text
assert "dir_pin: !PB12" not in text, text
assert result["reversed"] is True and result["checked"] is False, result
assert "restart" in klip.calls, klip.calls
assert auto.home_gantry()["ok"] is False
assert build(Klip(), state_path).motor_direction_checked is False
print("ok: 'away' writes the flipped dir_pin, restarts Klipper and locks homing again")

# A failed restart reply is normal and must not read as a failed flip.
assert result["ok"] is True
print("ok: Klipper dropping the socket on restart is not reported as a failure")

# Klipper now runs the override, so the next flip goes back to the template by
# emptying the file rather than stacking a second override on the first.
klip = Klip(dir_pin="PB12")
auto = build(klip, state_path)
result = auto.answer_motor_direction(False)
assert result["ok"] is True, result
text = direction_file.read_text(encoding="utf-8")
assert "dir_pin" not in "\n".join(
    line for line in text.splitlines() if not line.startswith("#")
), text
assert result["reversed"] is False, result
print("ok: flipping an overridden direction empties the override")

# A plain pin flips to a negated one too.
direction_file.unlink()
build(Klip(dir_pin="PB12"), temp_state()).answer_motor_direction(False)
assert "dir_pin: !PB12" in direction_file.read_text(encoding="utf-8")
print("ok: an unnegated pin flips to a negated one")


# --- nothing is written when the current direction is unknown ---

direction_file.unlink()
state_path = temp_state()
auto = build(Klip(dir_pin=None), state_path)
auto.answer_motor_direction(True)
result = auto.answer_motor_direction(False)
assert result["ok"] is False and "Klipper" in result["error"], result
assert not direction_file.exists()
assert auto.motor_direction_checked is True, "an unchanged motor keeps its pass"
print("ok: with Klipper not saying its dir_pin, nothing is flipped or written")


# --- the shipped config includes the override last ---

cfg = (
    Path(__file__).resolve().parent.parent / "deploy" / "klipper" / "printer.cfg.example"
).read_text(encoding="utf-8")
include = f"[include {DIRECTION_FILE}]"
assert include in cfg, "printer.cfg.example must include the direction override"
sections = [line for line in cfg.splitlines() if line.startswith("[")]
assert sections[-1] == include, (
    f"the override has to be the last section, or a later [stepper_x] wins: {sections[-1]}"
)
print("ok: printer.cfg.example includes the override as its last section")

installer = (
    Path(__file__).resolve().parent.parent / "deploy" / "pi" / "install-green-thumb.sh"
).read_text(encoding="utf-8")
assert DIRECTION_FILE in installer, "the installer must create the override file"
print("ok: the installer creates the file, since Klipper refuses a missing include")

assert automation_module.DIRECTION_TEST_MM == 10.0

print("\nall motor direction checks passed")
