from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time


@dataclass
class PlantSpec:
    name: str
    plant_id: str
    sensor_address: int
    # Required rather than defaulted: every plant sets these, and a default that
    # no caller uses is a value nobody notices is wrong.
    #
    # The target is a band name from greenthumb.moisture, not a percentage.
    # "water when this reaches dry" is a decision; "water at 42%" is a number
    # against a scale whose meaning depends on the soil.
    moisture_target: str
    watering_volume_ml: int
    light_start_time: time = time(8, 0)
    light_stop_time: time = time(20, 0)
    position_mm: int = 0
    # How the dose is laid down. "point" empties it at position_mm, which suits
    # a small pot. "sweep" walks the nozzle between the two bounds below for
    # the length of the dose, so a wide pot is watered across its width instead
    # of down one channel through the middle of the root ball.
    #
    # See greenthumb.sweep for the modes and for why the motion has to be the
    # dose rather than run beside it.
    watering_mode: str = "point"
    # Absolute rail coordinates, the same frame as position_mm, and ignored in
    # point mode. Equal values mean no span, which is why the mode cannot be
    # set to sweep until they are apart -- a sweep with no width would read as
    # configured and behave as a point.
    sweep_min_mm: float = 0.0
    sweep_max_mm: float = 0.0
    # Which soil library entry this pot is filled with. Empty means not set,
    # which is distinct from a mix whose figures are unusable -- callers report
    # "no soil set" rather than assuming one. A property of the plant rather
    # than of the slot, so it travels with a saved plant.
    soil: str = ""
    # Auto-managed LED segment for the global strip. This is calculated by the app,
    # not exposed to the user for manual editing.
    led_start_index: int = 0
    led_end_index: int = 0


@dataclass
class SensorSample:
    sensor_address: int
    moisture_percent: float
    moisture_raw: float = -1.0
    temperature_c: float | None = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))


@dataclass
class PlantStatus:
    plant_id: str
    moisture_percent: float
    # The band the reading falls in, and the band it is aimed at. The raw
    # percentage stays alongside: the history chart needs it, and the rate of
    # drying says more than the level.
    moisture_band: str
    target_moisture: str
    pump_active: bool = False
    lighting_mode: str = "ambient"
    last_watered: str | None = None
    # How many readings are in the averaging window. Below the full window the
    # loop will not water yet, so the UI can say "still gathering" rather than
    # showing a percentage that is not yet trusted to act on.
    sample_count: int = 0
    window_size: int = 0
