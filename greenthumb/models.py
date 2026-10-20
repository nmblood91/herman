from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time

from greenthumb import care


@dataclass
class PlantSpec:
    name: str
    plant_id: str
    sensor_address: int
    watering_volume_ml: int
    # Water once the soil dries to this, as a whole % volumetric water content.
    # Turned into a point on the pot's own scale through its soil profile's
    # field capacity and wilting point %; see greenthumb.care. Its water level
    # in words is worked out from it (care.water_level_for), never stored.
    target_vwc: int = care.DEFAULT_TARGET_VWC
    # The soil profile this plant wants. Loading a plant profile switches the
    # pot to it; the card warns if the pot is later given a different one.
    preferred_soil: str = ""
    # When the lights come on, for how many hours, and how bright this plant's
    # stretch of strip is, in percent. The stop time is worked out from the
    # first two (care.light_stop) rather than stored beside them.
    light_start_time: time = time(8, 0)
    light_hours: int = care.DEFAULT_LIGHT_HOURS
    light_brightness: int = care.DEFAULT_LIGHT_BRIGHTNESS
    # Whole millimetres, like the sweep bounds below. The carriage cannot be
    # placed over a pot to a fraction of a millimetre by eye, so a decimal
    # here would only be noise on the card.
    position_mm: int = 0
    # Which soil library entry this pot is filled with. Empty means not set,
    # which is distinct from a mix whose figures are unusable -- callers report
    # "no soil set" rather than assuming one.
    #
    # A property of the pot rather than of the plant, and grouped here with the
    # rest of them for that reason: the mix is physically in the pot, so
    # loading a plant profile leaves it alone.
    soil: str = ""
    # No field capacity of its own: a pot reads against its soil profile's
    # readings, looked up live (GreenThumbAutomation._sync_scales).
    #
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
    sweep_min_mm: int = 0
    sweep_max_mm: int = 0
    # Free text about this plant, saved and loaded with the rest of its care
    # settings. A property of the plant, not the pot: the reason you water
    # something at a given band travels with it.
    notes: str = ""
    # Which plant profile this pot's care settings came from, or "" for none.
    # Set by loading one onto the pot or saving the pot as one. Until then the
    # care settings are the code's placeholders, and the card says so rather
    # than presenting them as though somebody chose them.
    profile: str = ""
    # Auto-managed LED segment for the global strip. This is calculated by the app,
    # not exposed to the user for manual editing.
    led_start_index: int = 0
    led_end_index: int = 0
    # How this pot's stretch of strip is lit. Properties of the pot, like its
    # position, so loading a plant profile leaves them alone. light_color is
    # used during its scheduled hours (the brightness then comes from the
    # profile); the manual pair is used in manual mode with each zone set
    # separately. Two settings on purpose: changing one never changes the other.
    light_color: tuple[int, int, int] = care.DEFAULT_LIGHT_COLOR
    manual_color: tuple[int, int, int] = care.DEFAULT_LIGHT_COLOR
    manual_brightness: int = care.DEFAULT_LIGHT_BRIGHTNESS


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
    # The band the reading falls in, for describing it in words. The raw
    # percentage stays alongside: the history chart needs it, and the rate of
    # drying says more than the level.
    moisture_band: str
    # What waters: the pot's soil moisture as % VWC, None when it cannot be
    # worked out, against the plant's target.
    moisture_vwc: float | None
    target_vwc: int
    thirsty: bool = False
    # Why the target cannot be used as written for this pot's soil, or None.
    target_problem: str | None = None
    pump_active: bool = False
    lighting_mode: str = "ambient"
    last_watered: str | None = None
    # How many readings are in the averaging window. Below the full window the
    # loop will not water yet, so the UI can say "still gathering" rather than
    # showing a percentage that is not yet trusted to act on.
    sample_count: int = 0
    window_size: int = 0
    # Why the pot has no reading, when it has no scale to read on: no soil
    # profile, or one missing a sensor reading. None when it has one.
    scale_problem: str | None = None
    # What the pot's probe made of its last watering: {"state", "at",
    # "minutes", "rise"}, state being pending, soaked, missed, unknown or
    # skipped. None when it has never been watered with the check on.
    last_soak: dict | None = None
