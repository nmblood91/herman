"""Planning for an oscillating dose: water laid down along a span, not a point.

Point watering drops the whole dose on one spot, which is fine for a small pot
and wrong for a wide one -- the water channels straight down through one column
of mix and runs out the bottom while the rest of the root ball stays dry. A
sweep walks the nozzle back and forth across the pot for exactly as long as the
pump runs, so the same volume arrives spread out.

**The motion replaces the dwell, and that is forced rather than chosen.**
`PumpController.deliver_ml` times a dose by queueing `SET_PIN VALUE=1`, a `G4`
dwell and `SET_PIN VALUE=0` as one script. `G4` blocks Klipper's queue, so a
move sent from another thread would not run alongside the dose -- it would sit
behind the dwell and execute once the pump had already stopped. There is no
version of this that runs the two in parallel. The passes have to *be* the
dwell, inside the same script.

Which makes the travel time the dose, and that is why acceleration is in here.
A pass is not `span / speed`: the carriage ramps up and down at every
reversal, so the real time is longer. Timing a dose against the ideal would
leave the pump running through the extra, over-dosing by the total ramp time --
tens of passes worth of it. So each pass is modelled as the trapezoid Klipper
will actually run, and the speed is then solved backwards from the dose.

Everything here is arithmetic on floats: no hardware, no Klipper, no state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# More passes than this buys nothing a plant can tell apart and makes the
# script needlessly long. Hitting the cap just means a slower sweep, which is
# harmless -- the dose stays exact either way.
# The two ways a dose can be laid down. Stored on the plant as one of these
# strings rather than a boolean, because "not sweeping" is a real choice with
# its own setting (position_mm) rather than the absence of one.
POINT = "point"
SWEEP = "sweep"
MODES = (POINT, SWEEP)

MAX_PASSES = 60

# Below this the sweep is a point with extra steps, and the reversals would
# spend most of the dose accelerating. Refused rather than rounded, so nobody
# configures a 2 mm "sweep" and believes it is doing something.
MIN_SPAN_MM = 10.0

# How fast the nozzle should cross the pot when the dose leaves a free choice.
# Slow enough that water lands rather than flings, fast enough that a pass is
# a pass and not a crawl. The dose always wins over this: it is a preference
# used to pick the number of passes, not a constraint.
PREFERRED_SPEED_MM_S = 40.0


@dataclass(frozen=True)
class Plan:
    """A resolved sweep: how many passes, how fast, and any leftover dwell."""

    passes: int
    feedrate_mm_min: int
    # Whatever the passes do not fill, parked at one end. Zero in the normal
    # case; non-zero only when the solved speed had to be clamped.
    dwell_ms: int
    # What the plan is predicted to take, for logging against the dose it was
    # built from. The two should agree to within rounding.
    predicted_seconds: float

    @property
    def speed_mm_s(self) -> float:
        return self.feedrate_mm_min / 60.0


def pass_seconds(span_mm: float, speed_mm_s: float, accel_mm_s2: float) -> float:
    """How long one traverse really takes, ramps included.

    A reversal is a full stop -- the carriage cannot carry speed through a
    180 degree corner -- so every pass is an independent trapezoid and they
    simply add up. That also means the model is exact here rather than an
    approximation that drifts over many passes.
    """
    if span_mm <= 0 or speed_mm_s <= 0 or accel_mm_s2 <= 0:
        return 0.0

    # Distance burned by ramping up and back down together.
    ramp_distance = speed_mm_s**2 / accel_mm_s2
    if span_mm <= ramp_distance:
        # Too short to reach the requested speed at all: a triangle, peaking
        # somewhere below it. Using the trapezoid formula here would report a
        # time shorter than physically possible.
        return 2.0 * math.sqrt(span_mm / accel_mm_s2)
    return span_mm / speed_mm_s + speed_mm_s / accel_mm_s2


def speed_for(span_mm: float, seconds: float, accel_mm_s2: float) -> float | None:
    """The cruise speed that makes one pass take exactly `seconds`.

    Inverting pass_seconds: ``t = d/v + v/a`` rearranges to
    ``v^2 - a*t*v + a*d = 0``, and the smaller root is the one wanted -- the
    larger one is the same duration reached by sprinting and then spending the
    rest of the time decelerating, which is not a sweep.

    None when the span cannot be crossed that quickly even flat out, which is
    the discriminant going negative.
    """
    if span_mm <= 0 or seconds <= 0 or accel_mm_s2 <= 0:
        return None

    discriminant = (accel_mm_s2 * seconds) ** 2 - 4 * accel_mm_s2 * span_mm
    if discriminant < 0:
        return None
    return (accel_mm_s2 * seconds - math.sqrt(discriminant)) / 2


def plan(
    span_mm: float,
    duration_seconds: float,
    max_speed_mm_s: float,
    accel_mm_s2: float,
    preferred_speed_mm_s: float = PREFERRED_SPEED_MM_S,
) -> Plan | None:
    """Fit whole passes into the dose, then solve the speed to match it exactly.

    None when a sweep cannot honour the dose, and the caller must then water as
    a point rather than adjust anything. Two cases reach it, and neither should
    be papered over:

    * The span is too short to be a sweep at all.
    * The dose is shorter than a single traverse, even flat out. Stretching the
      pump to fit the motion would over-dose, and quietly shrinking the span
      would water part of the pot while reporting a sweep. Both are worse than
      saying no.
    """
    if span_mm < MIN_SPAN_MM or duration_seconds <= 0 or accel_mm_s2 <= 0:
        return None
    if max_speed_mm_s <= 0:
        return None

    # The quickest a pass can go, which bounds everything below. A dose too
    # short to cover even one pass is refused by the loop at the end rather
    # than checked for here: that loop has to compare the two anyway, after
    # the feedrate rounding, and a second copy of the comparison up here could
    # only ever drift from it.
    fastest = pass_seconds(span_mm, max_speed_mm_s, accel_mm_s2)

    # Pick the pass count from the preferred speed, never asking for passes
    # faster than the machine can run them.
    preferred = pass_seconds(
        span_mm, min(preferred_speed_mm_s, max_speed_mm_s), accel_mm_s2
    )
    pass_time = max(preferred, fastest)
    passes = max(1, min(MAX_PASSES, int(duration_seconds // pass_time)))

    # Now solve for the speed that makes those passes fill the dose. A dose too
    # short to be solved at all falls back to running flat out, which is as
    # close as the machine can get; whether that actually fits is settled by
    # the loop further down rather than assumed here.
    solved = speed_for(span_mm, duration_seconds / passes, accel_mm_s2)
    speed = max_speed_mm_s if solved is None else min(solved, max_speed_mm_s)

    # Rounded up, and that direction is load-bearing. Feedrate goes out as a
    # whole number of mm/min, and rounding to the nearest can round the speed
    # *down* -- a slower pass, which takes longer than the dose it was solved
    # for and leaves the pump running past the end of it. Up is the safe way to
    # be wrong: the passes finish early and the dwell below absorbs the
    # remainder. Then clamped back under the machine limit, because a feedrate
    # above max_velocity is one Klipper silently caps, putting the real time
    # back above the prediction.
    feedrate = max(1, min(math.ceil(speed * 60), int(max_speed_mm_s * 60)))

    # The bound the whole module rests on: the passes must not outlast the
    # dose, because the pump stops when they finish. Enforced here rather than
    # argued from the arithmetic above, and that is not belt-and-braces -- the
    # two roundings on the line above can disagree. Clamping to a whole mm/min
    # at or below the machine limit can land under the speed that was solved
    # for, making every pass slightly slower and pushing the total past the
    # dose. Dropping a pass always fits; if even one does not, there is no
    # sweep to be had.
    #
    # Each iteration is recomputed from the rounded feedrate rather than from
    # `speed`, so the prediction describes the gcode that will actually be sent.
    while True:
        predicted = passes * pass_seconds(span_mm, feedrate / 60.0, accel_mm_s2)
        if predicted <= duration_seconds:
            break
        if passes == 1:
            return None
        passes -= 1

    return Plan(
        passes=passes,
        feedrate_mm_min=feedrate,
        # Any shortfall is parked at one end rather than dropped, because the
        # dose is the thing that must not move. Non-negative by construction:
        # the loop above only leaves once the passes fit inside it.
        dwell_ms=int(round((duration_seconds - predicted) * 1000)),
        predicted_seconds=round(predicted, 3),
    )


def gcode(plan_: Plan, start_mm: float, end_mm: float) -> list[str]:
    """The passes as absolute moves, alternating ends.

    Absolute rather than relative: a relative sweep accumulates its own
    rounding and would walk off the pot over fifty passes.
    """
    ends = (round(float(end_mm), 1), round(float(start_mm), 1))
    lines = ["G90"]
    for index in range(plan_.passes):
        lines.append(f"G1 X{ends[index % 2]} F{plan_.feedrate_mm_min}")
    if plan_.dwell_ms > 0:
        lines.append(f"G4 P{plan_.dwell_ms}")
    return lines
