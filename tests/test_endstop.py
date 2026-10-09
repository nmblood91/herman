"""The home switch diagnostic.

The switch is wired normally-closed, so a closed contact reads untriggered and
an open circuit reads triggered. That is deliberate -- a broken wire makes
homing refuse instead of driving into the end of the rail -- and it is also why
this needs testing: the fail-safe means a switch wired to the wrong terminal
and a switch wired to nothing produce the identical reading. The diagnostic has
to say so rather than pick one.
"""

import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb.config import settings
from greenthumb.hardware.soil_sensors import unavailable_sample
from greenthumb.services.automation import GreenThumbAutomation, HardwareBusyError
from tests.helpers import temp_state, temp_store

settings.auto_watering_enabled = False
settings.idle_motion_enabled = False

TRAVEL = 890.0


class Klip:
    def __init__(self, triggered=False, position=0.0, homed=True, readable=True):
        self.triggered = triggered
        self.position = position
        self._homed = homed
        self.readable = readable
        self.queries = 0

    def status(self):
        return {
            "ok": True,
            "position": self.position,
            "homed": self._homed,
            "max_x": TRAVEL,
        }

    def endstop_state(self):
        self.queries += 1
        if not self.readable:
            return {"ok": False, "error": "Klipper did not respond within 5s"}
        return {"ok": True, "triggered": self.triggered}

    def send_gcode(self, gcode, timeout=5.0):
        return {"ok": True}

    def home_gantry(self):
        return {"ok": True}

    def water_supply_present(self):
        return True


class Hub:
    addresses = [0x36, 0x37, 0x38, 0x39]
    def read_one(self, a): return unavailable_sample(a)


class Nul:
    mode = "off"; color = (0, 0, 0); brightness = 0
    def __getattr__(self, n): return lambda *a, **k: {}


def build(klip):
    return GreenThumbAutomation(
        Hub(), klip, Nul(), Nul(), history=temp_store(), state_path=temp_state()
    )


# --- the healthy case ---

auto = build(Klip(triggered=False, position=0.0, homed=True))
result = auto.endstop_diagnostic()
assert result["ok"] is True, result
assert result["verdict"] == "healthy", result
assert result["triggered"] is False
assert result["wiring"] == "normally closed", result
# The fail-safe only exists if someone checks it, so the healthy path has to be
# the place that tells you to.
assert "unplug" in result["detail"], result["detail"]
print("ok: open with the carriage away from the switch reads healthy")


# --- the ambiguous case, which is the whole reason this exists ---

auto = build(Klip(triggered=True, position=0.0, homed=True))
result = auto.endstop_diagnostic()
assert result["verdict"] == "suspect", result
detail = result["detail"]
# It must name both causes, and each is checked on its own: an "or" here would
# pass on almost any English sentence. Naming only one would send someone off to
# re-wire a switch whose wire is actually broken, or the reverse.
assert "NO" in detail, detail
assert "broken wire" in detail, detail
assert "unseated" in detail, detail
# And it must give the test that separates them, since no single reading can.
assert "Press the switch" in detail, detail
print("ok: triggered away from the switch names both causes and the press test")


# --- parked on the switch ---

auto = build(Klip(triggered=True, position=TRAVEL, homed=True))
result = auto.endstop_diagnostic()
assert result["verdict"] == "at_switch", result
print("ok: triggered while parked at the switch is not reported as a fault")

# Just off the switch still counts as on it: a failed home leaves the carriage
# retracted a few mm, and calling that "away from the switch" would turn a
# correct reading into a suspected fault.
auto = build(Klip(triggered=True, position=TRAVEL - 5.0, homed=True))
assert auto.endstop_diagnostic()["verdict"] == "at_switch"
print("ok: a few mm off the switch is still parked at it")

# Far enough away and triggered is suspect again.
auto = build(Klip(triggered=True, position=TRAVEL - 200.0, homed=True))
assert auto.endstop_diagnostic()["verdict"] == "suspect"
print("ok: well clear of the switch, triggered is suspect once more")

# At the switch and NOT triggered is the other way round: the switch should be
# depressed and is not reading it.
auto = build(Klip(triggered=False, position=TRAVEL, homed=True))
result = auto.endstop_diagnostic()
assert result["verdict"] == "suspect", result
assert "mounting" in result["detail"] or "depressed" in result["detail"], result["detail"]
print("ok: at the switch but reading open points at mounting or the NO terminal")


# --- an unhomed axis cannot be reasoned about ---

# Klipper reports a position whether or not the axis is homed, and unhomed it is
# a counter rather than a measurement. Trusting it would let "0 mm" mean "away
# from the switch" when the carriage is physically sitting on it.
auto = build(Klip(triggered=True, position=0.0, homed=False))
result = auto.endstop_diagnostic()
assert result["verdict"] == "unknown", result
assert "not homed" in result["detail"], result["detail"]
print("ok: unhomed, it declines to read the position as proof of anything")

auto = build(Klip(triggered=False, position=0.0, homed=False))
assert auto.endstop_diagnostic()["verdict"] == "unknown"
print("ok: and declines either way round, not just when triggered")


# --- failures are reported, not guessed at ---

auto = build(Klip(readable=False))
result = auto.endstop_diagnostic()
assert result["ok"] is False, result
assert result["verdict"] == "unavailable", result
assert "triggered" not in result, "invented a reading from a failed query"
print("ok: a query that failed reports unavailable rather than a made-up state")


# --- it does not fight the gantry ---

# Klipper waits for moves in flight before answering an endstop query, so this
# must refuse while the hardware is held rather than block for the length of a
# watering cycle.
klip = Klip()
auto = build(klip)
auto._hardware_lock.acquire()
try:
    auto.endstop_diagnostic()
except HardwareBusyError:
    assert klip.queries == 0, "queried Klipper anyway while the gantry was busy"
    print("ok: refused while the hardware is busy, and did not query")
else:
    raise AssertionError("expected HardwareBusyError")
finally:
    auto._hardware_lock.release()

# And the lock is given back, or one diagnostic would wedge the control loop.
assert auto.endstop_diagnostic()["ok"] is True
assert auto._hardware_lock.acquire(blocking=False), "the diagnostic kept the lock"
auto._hardware_lock.release()
print("ok: the lock is released afterwards")

# --- the client query itself ---

# The tests above stub endstop_state, so the parsing underneath it went
# unexercised and was wrong in three ways at once. The shape below is what a
# real board returns, captured from one:
#
#   {"ok": True, "result": {"stepper_x": "open",
#                           "stepper_y": "TRIGGERED",
#                           "stepper_z": "TRIGGERED"}}
#
# No last_query wrapper, keys carrying the stepper_ prefix, and values that are
# words rather than numbers.
from greenthumb.hardware.klipper_client import KlipperClient


class FakeKlipper(KlipperClient):
    def __init__(self, result, gcode_ok=True):
        super().__init__(socket_path="/nonexistent")
        self.result = result
        self.gcode_ok = gcode_ok
        self.scripts = []

    def send_gcode(self, gcode, timeout=5.0):
        self.scripts.append(gcode)
        if not self.gcode_ok:
            return {"ok": False, "error": "Klipper is shutting down"}
        return {"ok": True}

    def _send_command(self, method, params=None, timeout=5.0):
        assert method == "query_endstops/status", method
        return {"ok": True, "result": self.result}


REAL = {"stepper_x": "open", "stepper_y": "TRIGGERED", "stepper_z": "TRIGGERED"}

client = FakeKlipper(REAL)
assert client.endstop_state() == {"ok": True, "triggered": False}, client.endstop_state()
print("ok: the shape a real board returns is read correctly")

# The dangerous one. Every non-empty string is truthy, so bool("open") is True
# and a plain bool() cast reports an untriggered switch as triggered -- a
# diagnostic confidently stating the opposite of the truth.
assert FakeKlipper({"stepper_x": "open"}).endstop_state()["triggered"] is False
assert FakeKlipper({"stepper_x": "TRIGGERED"}).endstop_state()["triggered"] is True
print("ok: open and TRIGGERED are distinguished, not cast with bool()")

# Case and spacing are not worth failing over.
for text, expected in (("triggered", True), (" Open ", False), ("OPEN", False)):
    got = FakeKlipper({"stepper_x": text}).endstop_state()["triggered"]
    assert got is expected, (text, got)
print("ok: the words are read case-insensitively")

# The status object exposes the same state as 0 and 1.
assert FakeKlipper({"stepper_x": 1}).endstop_state()["triggered"] is True
assert FakeKlipper({"stepper_x": 0}).endstop_state()["triggered"] is False
print("ok: numeric 0 and 1 are accepted too")

# Something unrecognised must be reported, never guessed at.
result = FakeKlipper({"stepper_x": "maybe"}).endstop_state()
assert result["ok"] is False, result
assert "maybe" in result["error"], result["error"]
print("ok: an unrecognised value is reported rather than guessed")

# Moonraker and some versions wrap the same mapping in last_query.
assert FakeKlipper({"last_query": REAL}).endstop_state() == {"ok": True, "triggered": False}
print("ok: the last_query wrapper is unwrapped when present")

# Short-form naming still works, so a rename does not break this.
assert FakeKlipper({"x": "TRIGGERED"}).endstop_state()["triggered"] is True
print("ok: the short x spelling is accepted as well")

# y and z are placeholders on unused headers, reading triggered forever. Taking
# either for the home switch would report a permanent fault.
result = FakeKlipper({"stepper_y": "TRIGGERED", "stepper_z": "TRIGGERED"}).endstop_state()
assert result["ok"] is False, result
assert "stepper_y, stepper_z" in result["error"], result["error"]
print("ok: the y and z placeholders are not mistaken for the home switch")

result = FakeKlipper({}).endstop_state()
assert result["ok"] is False and "no endstops at all" in result["error"], result
print("ok: an empty response says so")

# A fresh query is forced, so a cached reading can never be shown as current.
assert client.scripts == ["QUERY_ENDSTOPS"], client.scripts
print("ok: a fresh MCU query is forced before the reading is read back")

client = FakeKlipper(REAL, gcode_ok=False)
result = client.endstop_state()
assert result["ok"] is False and "shutting down" in result["error"], result
print("ok: a refused query is reported rather than answered from a cache")

print("\nall endstop diagnostic checks passed")
