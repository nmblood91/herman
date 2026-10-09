"""Shared fixtures for the test scripts.

These are plain assert scripts rather than a pytest suite, so there is no
conftest to hang fixtures off. This module is the equivalent: imported by name,
with tests/run_all.py putting the repo root on PYTHONPATH.
"""

import tempfile
from pathlib import Path

from greenthumb.history import HistoryStore


def temp_store() -> HistoryStore:
    """A throwaway history database. Tests must never touch the real one."""
    return HistoryStore(Path(tempfile.mkdtemp()) / "test.db")


def temp_state() -> Path:
    """A throwaway settings file. Tests must never touch the real one."""
    return Path(tempfile.mkdtemp()) / "state.json"


def give_every_plant_soil(auto, soil: str = "Peat potting mix"):
    """Install the soil library and set a soil on every plant.

    Watering needs this. Without a soil there is no wilting point, so a reading
    cannot be turned into a band and the plant is never judged thirsty -- which
    is deliberate, and means any test exercising watering has to opt in to its
    plants being judgeable at all.

    Returns the automation so it can be chained onto a constructor.
    """
    from greenthumb import soil_library

    soil_library.install(path=auto._state_path)
    for plant in auto.plants:
        auto.update_plant_soil(plant.plant_id, soil)
    return auto
