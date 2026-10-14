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


# The stretch of rail each plant's watering may use, inclusive at both ends,
# so neighbours share a boundary. A watering spot or sweep edge outside its
# plant's zone is refused: it is almost always a position captured on the
# wrong card, and the result would water the neighbouring pot. Plant 4 runs to
# the end of this build's 890 mm rail; zone_for clips every zone to the rail
# Klipper actually reports, so a rail measured shorter still wins.
# Whole millimetres throughout, like every stored position.
ZONES: dict[str, tuple[int, int]] = {
    "plant_1": (0, 200),
    "plant_2": (200, 445),
    "plant_3": (445, 690),
    "plant_4": (690, 890),
}

# A new plant's sweep span: this far either side of the middle of its zone.
# A starting point, not a limit -- the edges can be set anywhere in the zone.
DEFAULT_SWEEP_REACH_MM = 50


def zone_midpoint(plant_id: str) -> int | None:
    """The middle of a plant's zone, rounded down to a whole millimetre, or
    None if it has none. Down rather than to nearest so 322.5 and 567.5 do not
    go opposite ways under Python's round-half-to-even."""
    zone = ZONES.get(plant_id)
    return None if zone is None else (zone[0] + zone[1]) // 2


def zone_for(plant_id: str, travel_mm: float) -> tuple[int, int]:
    """Where this plant may be swept, clipped to the rail.

    A plant with no zone gets the whole rail, so adding a plant to
    default_plants without a zone cannot strand it. The rail is floored to a
    whole millimetre: Klipper reports position_max as a float, and the top of
    a zone must not land past it.
    """
    rail = int(travel_mm)
    low, high = ZONES.get(plant_id, (0, rail))
    return low, min(high, rail)


def default_placement(plant_id: str) -> dict[str, int]:
    """Where a new plant starts: watering at the middle of its zone, with a
    sweep span DEFAULT_SWEEP_REACH_MM either side of it, kept inside the zone.

    The span is filled in even though the mode starts as a fixed spot, so
    switching a pot to Sweep Range works straight away instead of being
    refused for having no span.
    """
    zone = ZONES[plant_id]
    middle = zone_midpoint(plant_id)
    return {
        "position_mm": middle,
        "sweep_min_mm": max(zone[0], middle - DEFAULT_SWEEP_REACH_MM),
        "sweep_max_mm": min(zone[1], middle + DEFAULT_SWEEP_REACH_MM),
    }


def default_plants() -> list[PlantSpec]:
    """Fresh PlantSpec instances, so callers cannot mutate a shared default."""
    # Each plant starts at the middle of its zone, which is where its pot
    # should sit. Set each properly once the pots are placed; the Plants tab
    # writes them to data/state.json and they persist from then on.
    return [
        PlantSpec(name="Plant 1", plant_id="plant_1", sensor_address=0x36, watering_volume_ml=100, light_start_time=time(8, 0), **default_placement("plant_1")),
        PlantSpec(name="Plant 2", plant_id="plant_2", sensor_address=0x37, watering_volume_ml=100, light_start_time=time(8, 0), **default_placement("plant_2")),
        PlantSpec(name="Plant 3", plant_id="plant_3", sensor_address=0x38, watering_volume_ml=100, light_start_time=time(8, 0), **default_placement("plant_3")),
        PlantSpec(name="Plant 4", plant_id="plant_4", sensor_address=0x39, watering_volume_ml=100, light_start_time=time(8, 0), **default_placement("plant_4")),
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
