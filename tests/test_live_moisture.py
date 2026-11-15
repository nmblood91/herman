"""The Calibration tab's live check: a fresh reading from every probe.

It exists to watch a probe respond by hand, so it has to read the probes now,
not hand back the last poll, which can be a minute old.
"""

import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb.config import settings
from greenthumb.models import SensorSample
from greenthumb.services.automation import GreenThumbAutomation, HardwareBusyError
from tests.helpers import CalibrationSurface, temp_state, temp_store

settings.auto_watering_enabled = False


class Hub(CalibrationSurface):
    addresses = [0x36, 0x37, 0x38, 0x39]
    reading = 400.0

    def read_one(self, a):
        return SensorSample(
            sensor_address=a, moisture_percent=-1.0,
            moisture_raw=self.reading, temperature_c=21.5,
        )


class Nul:
    mode = "off"; color = (0, 0, 0); brightness = 0
    def __getattr__(self, n): return lambda *a, **k: {}


hub = Hub()
auto = GreenThumbAutomation(hub, Nul(), Nul(), Nul(), history=temp_store(), state_path=temp_state())

recorded = []
auto.history.record_readings = lambda samples: recorded.append(samples)
before = {address: auto._latest[address] for address in hub.addresses}

hub.reading = 612.0
live = auto.live_moisture()
sensors = live["sensors"]
assert [s["address"] for s in sensors] == ["0x36", "0x37", "0x38", "0x39"], sensors
assert all(s["raw"] == 612.0 for s in sensors), "did not read the probes now"
assert all(s["dry"] == Hub.raw_dry for s in sensors), sensors
assert all(s["temperature_c"] == 21.5 for s in sensors), sensors
assert all(s["label"] for s in sensors), sensors
print("ok: reads every probe now, with its air reading beside it")

assert not recorded, "a live check was written to history"
assert all(auto._latest[a] is before[a] for a in hub.addresses), "a live check replaced the last poll"
print("ok: leaves history and the last poll alone")

assert auto._lock_holder is None and auto._hardware_lock.acquire(blocking=False)
auto._hardware_lock.release()
with auto._exclusive("Watering Plant 1"):
    try:
        auto.live_moisture()
    except HardwareBusyError as exc:
        assert "Watering Plant 1" in str(exc), exc
    else:
        raise AssertionError("read the probes in the middle of a dose")
print("ok: gives way to a dose, and says what it is waiting on")


# --- an address with no probe is not probed again on every read ---
#
# Probing is a reset and a half-second wait with the hardware held, and this
# check reads every two seconds.

from greenthumb.hardware import soil_sensors  # noqa: E402

# No bus here (smbus2 is a stub), so every probe fails the way an empty
# address does.
real_hub = soil_sensors.SoilSensorHub(addresses=[0x36])
probes = []
probe = real_hub._try_initialize
real_hub._try_initialize = lambda address: probes.append(address) or probe(address)

assert real_hub.read_one(0x36).moisture_raw == -1.0
assert real_hub.read_one(0x36).moisture_raw == -1.0
assert real_hub.read_one(0x36).moisture_raw == -1.0
assert probes == [0x36], f"probed an absent address on every read: {probes}"
print("ok: an address that did not answer is left alone for a while")

real_hub._probe_failed_at[0x36] -= soil_sensors.PROBE_RETRY_SECONDS + 1
real_hub.read_one(0x36)
assert probes == [0x36, 0x36], probes
assert soil_sensors.PROBE_RETRY_SECONDS < settings.sensor_poll_seconds, (
    "a probe plugged in has to show up on the control loop's next reading"
)
print("ok: and probed again once the wait is up, so a probe plugged in is found")


# --- the table's Reading column: the loop's last read, at no cost to the probes ---

hub = Hub()
auto = GreenThumbAutomation(hub, Nul(), Nul(), Nul(), history=temp_store(), state_path=temp_state())
rows = auto.moisture_calibration()["sensors"]
assert all(row["reading"] is None for row in rows), "showed a reading before any was taken"
print("ok: before the first poll there is no reading, rather than a probe that did not answer")

hub.reading = 577.0
auto._poll_sensors()
reads = []
hub.read_one = lambda a: reads.append(a)
rows = {row["address"]: row for row in auto.moisture_calibration()["sensors"]}
assert not reads, "the calibration table read the probes itself"
reading = rows["0x36"]["reading"]
assert reading["raw"] == 577.0 and reading["temperature_c"] == 21.5, reading
assert 0 <= reading["age_seconds"] < 5, reading
print("ok: after a poll the table carries each probe's last reading without reading it again")

auto._latest_at[0x36] -= 200
assert 200 <= auto.moisture_calibration()["sensors"][0]["reading"]["age_seconds"] < 205
print("ok: and says how old it is")

auto.set_plant_enabled("plant_2", False)
rows = {row["address"]: row for row in auto.moisture_calibration()["sensors"]}
assert rows["0x37"]["reading"] is None and rows["0x37"]["enabled"] is False, rows["0x37"]
assert rows["0x36"]["enabled"] is True
print("ok: an off pot has no reading, and is marked off")

print("\nall live moisture checks passed")
