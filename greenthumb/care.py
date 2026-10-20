"""What a plant asks for: when to water, and how long and how bright to light it.

Shared by the plant library, the plant profile editor and the pots, so all
three validate the same way. Nothing here touches hardware or the state file.

**Watering** is a target volumetric water content, a whole percentage. A pot is
watered once its soil dries to that figure. The water level is the same thing
in words, kept because "Medium" says more at a glance than 28%. It is never
stored: it is always worked out from the target (water_level_for), so changing
the key below relabels every plant at once.

    Ultra Wet    over 45% VWC
    Very Wet     41-45%
    Wet          35-40%   -- keep constantly damp
    Wet-Medium   31-34%
    Medium       25-30%   -- top 1-2 inches dry
    Medium-Dry   21-24%
    Dry          16-20%   -- mostly dry 2-3 inches down
    Very Dry     11-15%
    Ultra Dry    10% and under -- just above wilting point

The figures are for a rich mix; coarser mixes hold less, which is why the
percentage is what drives watering and the label is never converted into one.

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

DEFAULT_TARGET_VWC = 25
DEFAULT_LIGHT_HOURS = 12
DEFAULT_LIGHT_BRIGHTNESS = 75
# White, so a pot nobody has chosen a colour for lights as plain light rather
# than as whatever colour was last picked for something else.
DEFAULT_LIGHT_COLOR = (255, 255, 255)


# The lowest target % VWC each water level starts at, wettest first: the key
# in the module docstring. Mirrored in the Plant Profile Editor's slider.
WATER_LEVEL_FLOORS: tuple[tuple[int, str], ...] = (
    (46, "Ultra Wet"),
    (41, "Very Wet"),
    (35, "Wet"),
    (31, "Wet-Medium"),
    (25, "Medium"),
    (21, "Medium-Dry"),
    (16, "Dry"),
    (11, "Very Dry"),
    (0, "Ultra Dry"),
)
WATER_LEVELS: tuple[str, ...] = tuple(name for _, name in WATER_LEVEL_FLOORS)


def water_level_for(target_vwc: int) -> str:
    """The water level a target falls in, for a label."""
    return next(name for floor, name in WATER_LEVEL_FLOORS if target_vwc >= floor)


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


def check_target_vwc(value: object) -> int:
    target = _whole(value, "Target moisture (% VWC)")
    # Above 60% no mix this planter uses holds that much; at 0 nothing would
    # ever be watered.
    if not 1 <= target <= 60:
        raise ValueError(f"Target moisture must be between 1 and 60% VWC, not {target}")
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
