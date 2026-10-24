"""Shared fixtures for the test scripts.

These are plain assert scripts rather than a pytest suite, so there is no
conftest to hang fixtures off. This module is the equivalent: imported by name,
with tests/run_all.py putting the repo root on PYTHONPATH.
"""

import tempfile
from pathlib import Path

from greenthumb.config import settings
from greenthumb.hardware.soil_sensors import SoilSensorHub
from greenthumb.history import HistoryStore

# A real planter refuses to home until its motor direction test has passed.
# The fakes here have no motor to test, so every script starts with it passed;
# tests/test_motor_direction.py turns it back off to test the gate itself.
settings.motor_direction_checked = True


class CalibrationSurface:
    """The calibration half of SoilSensorHub, for test doubles to mix in.

    Most fakes only need to answer read_one. But anything reaching
    system_status, percent_for_plant or the calibration report also needs the
    two ends of each probe's scale -- and a fake that invented its own answer
    for those would stop agreeing with the real hub the moment the rule for
    judging a span changed. Borrowing the real methods is what keeps them
    honest.

    field_capacity is left empty on purpose: the automation layer owns that map
    and rebuilds it from the plants, so give_every_plant_soil is what fills it.
    """

    raw_dry = 320
    calibration: dict = {}
    field_capacity: dict = {}
    dry_for = SoilSensorHub.dry_for
    span_for = SoilSensorHub.span_for
    raw_to_percent = SoilSensorHub.raw_to_percent


def temp_store() -> HistoryStore:
    """A throwaway history database. Tests must never touch the real one."""
    return HistoryStore(Path(tempfile.mkdtemp()) / "test.db")


def temp_state() -> Path:
    """A throwaway settings file. Tests must never touch the real one."""
    return Path(tempfile.mkdtemp()) / "state.json"


def give_every_plant_soil(
    auto,
    soil: str = "Rich & Retentive Mix",
    field_capacity: int = 800,
    wilting_point: int = 320,
):
    """Install the soil library, set a soil profile on every plant, and give
    it both ends of the scale.

    Watering needs a field capacity reading at the top; wilting point at the
    bottom is estimated from it unless the soil has a reading. Without a scale
    there is no reading at all -- percent_for_plant returns -1 and the plant
    is never judged thirsty. Both readings are set here so the scale is exact
    and does not depend on the estimate.

    That is deliberate, which is why this fixture exists: a test exercising
    watering has to opt in to its plants being judgeable. And it is why both
    readings are set here rather than left out -- without them every test
    using this helper would pass while watering nothing, which is worse than
    failing. The wilting point defaults to 320, the old dry fallback, so a
    reading lands where it did when the bottom of the scale was air.

    Returns the automation so it can be chained onto a constructor.
    """
    from greenthumb import soil_library, state

    soil_library.install(path=auto._state_path)
    state.save_soil(
        soil,
        {"field_capacity_raw": int(field_capacity), "wilting_point_raw": int(wilting_point)},
        auto._state_path,
    )
    for plant in auto.plants:
        auto.update_plant_soil(plant.plant_id, soil)
    auto._persist()
    auto._sync_scales()

    # Asserted in the fixture, not left to each caller. If this ever stops
    # taking effect, every watering test goes quietly green while judging
    # nothing.
    for plant in auto.plants:
        assert auto.sensor_hub.span_for(plant.sensor_address) == (
            int(wilting_point), int(field_capacity)
        ), plant.plant_id
    return auto
