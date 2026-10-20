"""What a plant asks for: when to water, and how long and how bright to light it.

Shared by the plant library, the plant profile editor and the pots, so all
three validate the same way. Nothing here touches hardware or the state file.

**Watering** is a target share of the soil's available water, a whole
percentage: 100% at the soil's field capacity, 0% at its wilting point. A pot
is watered once it has used up all but that share. Because it is a share of
whatever the pot's own soil can hold, one target means the same thirst in any
mix. A VWC target did not: 25% VWC was fairly dry in the rich mix and more
than the coarse mix can hold at all.

The water level is the same thing in words, kept because "Dry" says more at a
glance than 30%. The card uses the same words for a pot's live reading. It is
never stored: it is always worked out (water_level_for), so changing the key
below relabels every plant and every card at once. Eight equal slices of the
gauge:

    Ultra Wet    88-100%  -- just watered
    Very Wet     76-87%
    Wet          63-75%
    Medium-Wet   51-62%
    Medium-Dry   38-50%
    Dry          26-37%
    Very Dry     13-25%
    Ultra Dry    0-12%    -- close to wilting point

**Lighting** is a start time, a number of hours and a brightness. There is no
stop time to keep in step with the other two: it is worked out (light_stop).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

# The library's four light intensities, as the strip brightness each one sets.
# A pot stores the percentage, so a brightness between these is allowed; the
# names are how the library and the editor describe them.
LIGHT_LEVELS: tuple[tuple[str, int], ...] = (
    ("Low", 25),
    ("Medium", 50),
    ("High", 75),
    ("Intense", 100),
)
BRIGHTNESS_FOR = {name: percent for name, percent in LIGHT_LEVELS}

# Medium-Dry: about half the reserve used, the usual point irrigation waters at.
DEFAULT_TARGET_AVAILABLE = 40
# A target outside this can't be acted on sensibly: below 10% the plant is
# nearly at wilting point before it is watered, and above 90% the pot would be
# watered again almost as soon as it drained.
MIN_TARGET_AVAILABLE = 10
MAX_TARGET_AVAILABLE = 90
DEFAULT_LIGHT_HOURS = 12
DEFAULT_LIGHT_BRIGHTNESS = 75
# White, so a pot nobody has chosen a colour for lights as plain light rather
# than as whatever colour was last picked for something else.
DEFAULT_LIGHT_COLOR = (255, 255, 255)


# The lowest % available water each water level starts at, wettest first: the
# key in the module docstring. Mirrored in the Plant Profile Editor's slider
# and in the pot card.
WATER_LEVEL_FLOORS: tuple[tuple[int, str], ...] = (
    (88, "Ultra Wet"),
    (76, "Very Wet"),
    (63, "Wet"),
    (51, "Medium-Wet"),
    (38, "Medium-Dry"),
    (26, "Dry"),
    (13, "Very Dry"),
    (0, "Ultra Dry"),
)
WATER_LEVELS: tuple[str, ...] = tuple(name for _, name in WATER_LEVEL_FLOORS)


def water_level_for(target_available: int) -> str:
    """The water level a target falls in, for a label."""
    return next(name for floor, name in WATER_LEVEL_FLOORS if target_available >= floor)


def light_level_name(brightness: int) -> str:
    """The nearest named level, for describing a brightness in words."""
    return min(LIGHT_LEVELS, key=lambda level: abs(level[1] - brightness))[0]


def light_stop(start: time, hours: int) -> time:
    """When the lights go off: start plus hours, wrapping past midnight."""
    moment = datetime.combine(datetime(2000, 1, 1), start) + timedelta(hours=hours)
    return moment.time().replace(second=0, microsecond=0)


def light_on(now: time, start: time, hours: int) -> bool:
    """True inside the photoperiod. 24 hours is always on, 0 never."""
    if hours >= 24:
        return True
    if hours <= 0:
        return False
    stop = light_stop(start, hours)
    if start <= stop:
        return start <= now < stop
    # Runs past midnight, e.g. 18:00 for 12 hours.
    return now >= start or now < stop


def _whole(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a whole number, not {value!r}")
    if value != int(value):
        raise ValueError(f"{label} must be a whole number, not {value!r}")
    return int(value)


def check_target_available(value: object) -> int:
    target = _whole(value, "Watering target (% soil water)")
    if not MIN_TARGET_AVAILABLE <= target <= MAX_TARGET_AVAILABLE:
        raise ValueError(
            f"The watering target must be between {MIN_TARGET_AVAILABLE} and "
            f"{MAX_TARGET_AVAILABLE}% soil water, not {target}"
        )
    return target


def check_light_hours(value: object) -> int:
    hours = _whole(value, "Light hours")
    if not 0 <= hours <= 24:
        raise ValueError(f"Light hours must be between 0 and 24, not {hours}")
    return hours


def check_light_brightness(value: object) -> int:
    brightness = _whole(value, "Brightness")
    if not 0 <= brightness <= 100:
        raise ValueError(f"Brightness must be between 0 and 100%, not {brightness}")
    return brightness


def check_light_color(value: object) -> tuple[int, int, int]:
    """Three whole numbers from 0 to 255, red, green and blue."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"A colour must be three numbers, red, green and blue, not {value!r}")
    channels = []
    for channel in value:
        if isinstance(channel, bool) or not isinstance(channel, int) or not 0 <= channel <= 255:
            raise ValueError(f"Each colour channel must be a whole number from 0 to 255, not {channel!r}")
        channels.append(channel)
    return tuple(channels)


def check_start_time(value: object) -> time:
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    if not isinstance(value, str):
        raise ValueError("Light start must be a time like 08:00")
    try:
        return time.fromisoformat(value).replace(second=0, microsecond=0)
    except ValueError:
        raise ValueError(f"Light start must be a time like 08:00, not {value!r}") from None
