"""Did a watering reach the soil? Judged from the pot's own moisture probe.

A dose that lands in the pot raises the probe's raw reading. Not at once:
water has to wick to wherever the probe sits, which can take anything from a
minute to most of an hour depending on the mix and how far the probe is from
where the water lands. So a dose passes as soon as the rise shows, and only
becomes a miss once the whole window has gone by without one.

Everything here works on raw counts and plain numbers, with no database and no
clock, so the rules can be tested directly. The automation layer feeds it the
readings stored either side of each dose.
"""

from __future__ import annotations

from statistics import median

PENDING = "pending"
SOAKED = "soaked"
MISSED = "missed"
# The probe stopped reporting during the window: no evidence either way.
UNKNOWN = "unknown"
# Could not be judged at all: no scale, nothing before the dose to compare
# against, or soil already too wet for a dose to show.
SKIPPED = "skipped"

# Readings before a dose that make up its baseline.
BASELINE_SECONDS = 10 * 60
MIN_BASELINE_READINGS = 3
# A rise has to hold across this many consecutive readings (as their median),
# so one noisy read cannot pass a dose that never arrived.
RUN = 3
# Below this many counts, a rise is within ordinary probe noise whatever the
# pot's span.
MIN_RISE_COUNTS = 10
# Soil already this far up its scale has little room left to rise, and what
# it has drains away fast; a dose there is not judged rather than missed.
TOO_WET_FRACTION = 0.9
# A window with fewer than this share of the readings it should have had means
# the probe was not really reporting.
MIN_COVERAGE = 0.5


def baseline(readings: list[float]) -> float | None:
    """The pre-dose reading to measure a rise from, or None if too few."""
    if len(readings) < MIN_BASELINE_READINGS:
        return None
    return float(median(readings))


def threshold(span: tuple[int, int], rise_percent: float) -> float:
    """How far the reading has to rise, in counts, for this pot's scale."""
    wilting, capacity = span
    return max(float(MIN_RISE_COUNTS), (capacity - wilting) * rise_percent / 100.0)


def can_judge(start: float | None, span: tuple[int, int] | None) -> bool:
    """Whether a dose starting from `start` on this scale can be judged."""
    if start is None or span is None:
        return False
    wilting, capacity = span
    return start < wilting + TOO_WET_FRACTION * (capacity - wilting)


def judge(
    start: float,
    after: list[float],
    span: tuple[int, int],
    rise_percent: float,
    window_done: bool,
    expected_readings: int,
) -> tuple[str, float | None]:
    """The verdict on one dose so far, and the rise behind it.

    `after` is every reading since the dose, oldest first. `window_done` says
    whether the full wait has passed; until it has, no rise yet just means
    pending. `expected_readings` is how many the window should have produced,
    for telling a quiet probe from a dry pot.
    """
    needed = threshold(span, rise_percent)
    best: float | None = None
    for end in range(RUN, len(after) + 1):
        rise = median(after[end - RUN:end]) - start
        best = rise if best is None else max(best, rise)
        if rise >= needed:
            return SOAKED, float(rise)
    if not window_done:
        return PENDING, best
    if len(after) < max(RUN, expected_readings * MIN_COVERAGE):
        return UNKNOWN, best
    return MISSED, best
