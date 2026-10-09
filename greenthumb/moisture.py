"""Moisture as five descriptive bands, computed per soil.

A reading is a percentage of the span between the dry endpoint and field
capacity. That number is kept — the history chart needs it, and the *rate* of
drying is a better signal than the level, because it follows light, temperature
and growth stage on its own where a fixed threshold cannot. What the bands add
is a way to say what the number means without implying precision the hardware
cannot deliver.

**Why they have to be per soil.** The bottom of the usable range is wilting
point, and where that sits as a fraction of field capacity differs sharply by
mix: about 27% for coco coir, 57% for a peat potting mix. So coir's plants work
across nearly the whole scale while a peat pot's live in the top 43% of it. A
fixed table of thresholds would put half of coir's bands below wilting point
and squash a peat pot's into two.

**Why bands rather than the number.** On a peat mix the difference between
comfortable and needing water is about eight points of a 0-100 display, and the
whole actionable range is a narrow strip at the top. A few percent of
calibration error moves you two bands. A percentage invites reading precision
off a scale that cannot support it; a band states the decision and hides a
distinction the sensor cannot make.

Bands are expressed as depletion of plant-available water, which is what
irrigation practice uses. The DRY boundary at 50% depletion is the conventional
Management Allowable Depletion trigger rather than a number chosen here.
"""

from __future__ import annotations

from dataclasses import dataclass

# Wettest to driest. The order is the scale, and `index` is what makes two
# bands comparable without relying on list position at the call site.
VERY_WET = "very wet"
WET = "wet"
MEDIUM = "medium"
DRY = "dry"
VERY_DRY = "very dry"

# Reading unavailable. Deliberately not a band: an unplugged probe must never
# resolve to "very dry", or it reads as the thirstiest plant on the rail and
# gets watered.
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Band:
    name: str
    index: int
    # Depletion of plant-available water, as a fraction, that this band covers.
    # 0.0 is field capacity, 1.0 is wilting point.
    depleted_from: float
    depleted_to: float
    description: str


BANDS: tuple[Band, ...] = (
    Band(VERY_WET, 0, 0.00, 0.10, "At field capacity. Just watered."),
    Band(WET, 1, 0.10, 0.30, "Comfortable, with most of the reserve intact."),
    Band(MEDIUM, 2, 0.30, 0.50, "Working through the reserve. Nothing to do yet."),
    Band(DRY, 3, 0.50, 0.75, "Past the usual watering trigger. Most plants want water."),
    Band(VERY_DRY, 4, 0.75, 1.00, "Near the limit of what the roots can pull out."),
)

BY_NAME = {band.name: band for band in BANDS}
ORDER = tuple(band.name for band in BANDS)

# A reading has to clear a boundary by this much, as a fraction of the usable
# window, before the band changes. Without it a value parked on a threshold
# flips label every poll and flaps the status bar; the 10-sample smoothing
# upstream damps noise but does nothing for a value genuinely sitting on the
# line.
HYSTERESIS = 0.03


def is_wetter_or_equal(name: str, target: str) -> bool:
    """True when `name` is at least as wet as `target`.

    The comparison watering uses: a plant is thirsty once its band is *drier*
    than its target, which is `not is_wetter_or_equal`.
    """
    band, wanted = BY_NAME.get(name), BY_NAME.get(target)
    if band is None or wanted is None:
        # An unknown reading or an unrecognised target is not a decision to
        # water. Saying "wet enough" is the safe answer: it withholds water
        # rather than dosing a plant on the strength of a reading we do not
        # have.
        return True
    return band.index <= wanted.index


def depletion(percent: float, wilting_fraction: float) -> float | None:
    """Fraction of plant-available water used up, from a reading.

    `percent` is the 0-100 reading against field capacity; `wilting_fraction`
    is where wilting point sits on that same scale, from the soil library.
    None when there is nothing usable to work from.

    Clamped to 0-1: a reading above field capacity means the pot was caught
    still draining, and one below wilting point means the soil is drier than
    the plant can work with. Both are real, and neither is a reason to return
    a figure outside the range every caller then has to guard.
    """
    if percent is None or percent < 0:
        return None
    if wilting_fraction is None or not 0.0 < wilting_fraction < 1.0:
        return None

    bottom = wilting_fraction * 100.0
    window = 100.0 - bottom
    used = (100.0 - float(percent)) / window
    return max(0.0, min(used, 1.0))


def band_for(
    percent: float, wilting_fraction: float | None, previous: str | None = None
) -> str:
    """Which band a reading falls in, given the soil.

    `previous` applies the hysteresis: pass the band last reported for this
    plant and the answer only changes once the reading has cleared the boundary
    properly, rather than on every wobble across it.

    UNKNOWN when the reading is unavailable or the soil supplies no usable
    ratio. Both mean "cannot say", which is not the same as "very dry" and must
    not collapse into it.
    """
    used = depletion(percent, wilting_fraction)
    if used is None:
        return UNKNOWN

    settled = next(band for band in BANDS if used <= band.depleted_to or band.name == VERY_DRY)

    held = BY_NAME.get(previous or "")
    if held is None or held.name == settled.name:
        return settled.name

    # Moving to a drier band needs the reading past the old band's lower edge
    # by the margin; moving wetter needs it past the upper edge by the same.
    if settled.index > held.index:
        return settled.name if used >= held.depleted_to + HYSTERESIS else held.name
    return settled.name if used <= held.depleted_from - HYSTERESIS else held.name


def describe(name: str) -> str:
    """One line on what a band means, for the UI."""
    band = BY_NAME.get(name)
    if band is None:
        return "No usable reading. Check the probe, and that the pot has a soil set."
    return band.description


def window_for(wilting_fraction: float | None) -> list[dict[str, object]]:
    """Each band as a reading range, for showing the scale a soil actually has.

    Returns the percentages a band spans on the 0-100 display, which is what
    makes the squeeze visible: on a peat mix every band lands above 57%.
    """
    if wilting_fraction is None or not 0.0 < wilting_fraction < 1.0:
        return []

    bottom = wilting_fraction * 100.0
    window = 100.0 - bottom
    return [
        {
            "name": band.name,
            "percent_from": round(100.0 - band.depleted_to * window, 1),
            "percent_to": round(100.0 - band.depleted_from * window, 1),
            "description": band.description,
        }
        for band in BANDS
    ]
