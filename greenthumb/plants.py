"""The plant set: which plant position each sensor address belongs to.

Kept here rather than inside `Automation.__init__` so that anything needing to
name a sensor can do so without constructing the whole service. An I2C address
is an implementation detail, and nobody who owns one of these should have to
recognise `0x38` as the third plant.

The plant set itself is defined by the code -- how many plants there are, and
which address each one reads. What the user may change is a plant's *name*, which
is persisted; `labels()` prefers a rename over the default here.
"""

from __future__ import annotations

from datetime import time

from greenthumb import state
from greenthumb.models import PlantSpec


def default_plants() -> list[PlantSpec]:
    """Fresh PlantSpec instances, so callers cannot mutate a shared default."""
    # Positions are placeholders scaled to fit the measured 890 mm of travel.
    # Plant 4 used to sit at 900, which the carriage can no longer reach. Set
    # each properly once the pots are placed; the Plants and Soil tab writes them to
    # data/state.json and they persist from then on.
    return [
        PlantSpec(name="Plant 1", plant_id="plant_1", sensor_address=0x36, moisture_target="dry", watering_volume_ml=100, light_start_time=time(8, 0), light_stop_time=time(20, 0), position_mm=130),
        PlantSpec(name="Plant 2", plant_id="plant_2", sensor_address=0x37, moisture_target="dry", watering_volume_ml=100, light_start_time=time(8, 0), light_stop_time=time(20, 0), position_mm=355),
        PlantSpec(name="Plant 3", plant_id="plant_3", sensor_address=0x38, moisture_target="dry", watering_volume_ml=100, light_start_time=time(8, 0), light_stop_time=time(20, 0), position_mm=580),
        PlantSpec(name="Plant 4", plant_id="plant_4", sensor_address=0x39, moisture_target="dry", watering_volume_ml=100, light_start_time=time(8, 0), light_stop_time=time(20, 0), position_mm=800),
    ]


def names_by_address(state_path=None) -> dict[int, str]:
    """Address to plant name, preferring a name the user has saved."""
    names = {plant.sensor_address: plant.name for plant in default_plants()}

    by_id = {plant.plant_id: plant.sensor_address for plant in default_plants()}
    for saved in state.load_state(state_path).get("plants", []) or []:
        if not isinstance(saved, dict):
            continue
        address = by_id.get(str(saved.get("plant_id", "")))
        name = saved.get("name")
        if address is not None and isinstance(name, str) and name.strip():
            names[address] = name.strip()
    return names


def label_for(
    address: int,
    names: dict[int, str] | None = None,
    state_path=None,
) -> str:
    """"Plant 1 (0x36)", or just the address if it belongs to no plant.

    Both halves on purpose: the name is what the owner recognises, and the
    address is what they would read off a sensor or type into `i2cdetect` when
    something needs tracing.

    Pass `names` when labelling several addresses at once. Without it each call
    reads the state file, which is fine for printing a four-row table and not
    fine in a loop that runs per reading.
    """
    if names is None:
        names = names_by_address(state_path)
    name = names.get(address)
    return f"{name} (0x{address:02x})" if name else f"0x{address:02x}"
