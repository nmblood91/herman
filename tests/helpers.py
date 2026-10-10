"""Shared fixtures for the test scripts.

These are plain assert scripts rather than a pytest suite, so there is no
conftest to hang fixtures off. This module is the equivalent: imported by name,
with tests/run_all.py putting the repo root on PYTHONPATH.
"""

import tempfile
from pathlib import Path

from greenthumb.hardware.soil_sensors import SoilSensorHub
from greenthumb.history import HistoryStore


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
    auto, soil: str = "Peat potting mix", field_capacity: int = 800
):
    """Install the soil library, set a soil on every plant, and measure it.

    Watering needs both halves. Without a soil there is no wilting-point ratio,
    so a reading cannot become a band. Without a field capacity there is no top
    of the scale, so there is no reading at all -- percent_for_plant returns -1
    and the plant is never judged thirsty.

    Both are deliberate, which is why this fixture exists: a test exercising
    watering has to opt in to its plants being judgeable. And it is why the
    field capacity is set here rather than left out -- without it every test
    using this helper would pass while watering nothing, which is worse than
    failing.

    Returns the automation so it can be chained onto a constructor.
    """
    from greenthumb import soil_library

    soil_library.install(path=auto._state_path)
    for plant in auto.plants:
        auto.update_plant_soil(plant.plant_id, soil)
        plant.field_capacity_raw = int(field_capacity)
        plant.field_capacity_source = "pot"
        plant.field_capacity_soil = soil
    auto._persist()
    auto._sync_field_capacity()

    # Asserted in the fixture, not left to each caller. If this ever stops
    # taking effect, every watering test goes quietly green while judging
    # nothing.
    for plant in auto.plants:
        assert isinstance(plant.field_capacity_raw, int), plant.plant_id
        assert auto.sensor_hub.span_for(plant.sensor_address) is not None, plant.plant_id
    return auto
