"""What a plant asks for: when to water, and how long and how bright to light it.

Shared by the plant library, the plant profile editor and the pots, so all
three validate the same way. Nothing here touches hardware or the state file.

**Watering** is a target volumetric water content, a whole percentage. A pot is
watered once its soil dries to that figure. The water level is only a label for
the same thing in words, kept because "Medium" says more at a glance than 28%:

    Wet        water at about 35-40% VWC  -- keep constantly damp
    Medium     about 25-30%               -- top 1-2 inches dry
    Dry        about 15-20%               -- mostly dry 2-3 inches down
    Very Dry   about 6-10%                -- just above wilting point

with Wet-Medium and Medium-Dry between them. The figures are for a rich mix;
the same label sits lower in a coarser one, which is why the percentage is what
drives watering and the label is never converted into one.

**Lighting** is a start time, a number of hours and a brightness. There is no
stop time to keep in step with the other two: it is worked out (light_stop).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

WATER_LEVELS: tuple[str, ...] = ("Wet", "Wet-Medium", "Medium", "Medium-Dry", "Dry", "Very Dry")

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


def check_water_level(value: object) -> str:
    """A label from WATER_LEVELS, matched loosely, or "" for none."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return ""
    if isinstance(value, str):
        wanted = value.strip().casefold()
        for level in WATER_LEVELS:
            if level.casefold() == wanted:
                return level
    raise ValueError("Water level must be one of: " + ", ".join(WATER_LEVELS))


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


def check_start_time(value: object) -> time:
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    if not isinstance(value, str):
        raise ValueError("Light start must be a time like 08:00")
    try:
        return time.fromisoformat(value).replace(second=0, microsecond=0)
    except ValueError:
        raise ValueError(f"Light start must be a time like 08:00, not {value!r}") from None
