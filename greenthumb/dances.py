"""Routines — the planter moving for its own sake.

A gantry that only moves when it waters spends almost all its time perfectly
still, which reads as broken rather than idle. These routines exist so it
visibly does something between waterings. All of them can be run by hand from
Controls; Patrol is also what the hourly auto-patrol runs after its re-home.

The re-home is the part that earns its keep. Steppers are open-loop: nothing
tells Klipper the carriage is where it thinks it is, so a belt that slips or a
carriage nudged by hand leaves every plant position quietly wrong until the
next home. Doing it hourly keeps that window to an hour, and patrolling after
it shows where the planter now thinks each plant is.

Positions are fractions of usable travel rather than millimetres, so a dance
scales to whatever the rail measures and cannot be sent somewhere the carriage
cannot reach. Every routine ends at 0.0 — the same place homing parks — so the
carriage always comes to rest at the end a reader can interpret.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    """One move of a routine.

    `at` is a fraction of usable travel: 0.0 is the left end, 1.0 the right.
    `feedrate` is mm/min, the units G1 expects. `dwell_ms` pauses after
    arriving, which is what makes a pause read as deliberate rather than as
    the machine hesitating.
    """

    at: float
    feedrate: int
    dwell_ms: int = 0


@dataclass(frozen=True)
class Dance:
    title: str
    description: str
    steps: tuple[Step, ...] = ()
    # Patrol visits the plants themselves rather than fractions of the rail,
    # so its steps cannot be written down here -- they depend on where the
    # plants are. steps_for() builds them.
    visits_plants: bool = False


# Feedrates, so the character of each routine is set in one place. printer.cfg
# allows a good deal more than any of these; the ceiling here is what looks
# unhurried rather than what the machine can do.
SLOW = 6000      # 100 mm/s
CRUISE = 9000    # 150 mm/s
BRISK = 12000    # 200 mm/s
SNAP = 15000     # 250 mm/s


DANCES: dict[str, Dance] = {
    "stretch": Dance(
        title="Stretch",
        description="One slow sweep to the far end and back, like waking up.",
        steps=(
            Step(0.92, SLOW),
            Step(0.0, SLOW),
        ),
    ),
    "wave": Dance(
        title="Wave",
        description="Swings either side of centre, each pass smaller than the last.",
        steps=(
            Step(0.50, CRUISE),
            Step(0.88, BRISK),
            Step(0.12, BRISK),
            Step(0.72, BRISK),
            Step(0.28, BRISK),
            Step(0.60, CRUISE),
            Step(0.40, CRUISE),
            Step(0.50, CRUISE, dwell_ms=300),
            Step(0.0, CRUISE),
        ),
    ),
    "shuffle": Dance(
        title="Shuffle",
        description="A quick fidget near the middle. Over in a few seconds.",
        steps=(
            Step(0.50, SNAP),
            Step(0.60, SNAP),
            Step(0.40, SNAP),
            Step(0.60, SNAP),
            Step(0.40, SNAP),
            Step(0.50, SNAP, dwell_ms=200),
            Step(0.0, BRISK),
        ),
    ),
    "patrol": Dance(
        title="Patrol",
        description=(
            "Visits each plant in turn, moving the way its watering does: a "
            "pause over a point pot, a few passes across a sweep."
        ),
        visits_plants=True,
    ),
}

DEFAULT_ORDER = ("stretch", "wave", "shuffle", "patrol")


@dataclass(frozen=True)
class PatrolStop:
    """One plant as the patrol visits it.

    A point plant is just `position_mm`. A sweeping plant also has
    `sweep_to_mm`, the far end of its span, and the feedrate its dose would
    cross it at -- so the patrol shows the real motion, not a stand-in.
    """

    position_mm: float
    sweep_to_mm: float | None = None
    feedrate: int = 0


# Passes across a sweeping plant. Enough to read as a sweep and show both
# ends; a real dose runs as many as fit the pump time, which could be minutes.
# Odd so the carriage finishes at the far end and carries on to the next pot
# rather than doubling back over the one it just did.
PATROL_SWEEP_PASSES = 3
POINT_DWELL_MS = 500
SWEEP_DWELL_MS = 300


def steps_for(
    name: str,
    travel_mm: float,
    plants: list[PatrolStop | float] | None = None,
) -> list[tuple[float, int, int]]:
    """Resolve a routine to absolute (position_mm, feedrate, dwell_ms) steps.

    `plants` is what a patrol visits; a bare number is a point plant. Positions
    are clamped to the rail. A plant configured outside usable travel is a real
    possibility -- the rail can be re-measured shorter than a saved position --
    and a patrol should shuffle that plant to the end rather than handing
    Klipper a move it will refuse and killing the whole routine.
    """
    dance = DANCES.get(name)
    if dance is None:
        raise ValueError(f"Unknown dance: {name}")

    limit = max(float(travel_mm), 1.0)

    # Whole millimetres, like every stored position. Floored at the top end
    # rather than rounded, so a rail reported as 889.6 cannot be sent to 890.
    def clamp(mm: float) -> int:
        return min(round(max(mm, 0.0)), int(limit))

    if dance.visits_plants:
        stops = [
            stop if isinstance(stop, PatrolStop) else PatrolStop(float(stop))
            for stop in plants or []
        ]
        if not stops:
            # No plants configured yet. Fall back rather than return an empty
            # routine, so the button still does something visible.
            return steps_for("stretch", travel_mm)

        # Left to right by where each visit starts, so the carriage makes one
        # trip down the rail rather than criss-crossing it.
        steps = []
        for stop in sorted(stops, key=lambda s: s.position_mm):
            if stop.sweep_to_mm is None or stop.feedrate <= 0:
                steps.append((clamp(stop.position_mm), CRUISE, POINT_DWELL_MS))
                continue
            near, far = clamp(stop.position_mm), clamp(stop.sweep_to_mm)
            steps.append((near, CRUISE, 0))
            for index in range(PATROL_SWEEP_PASSES):
                last = index == PATROL_SWEEP_PASSES - 1
                steps.append((
                    far if index % 2 == 0 else near,
                    stop.feedrate,
                    SWEEP_DWELL_MS if last else 0,
                ))
        steps.append((0, CRUISE, 0))
        return steps

    return [(clamp(step.at * limit), step.feedrate, step.dwell_ms) for step in dance.steps]


def gcode_for(steps: list[tuple[float, int, int]]) -> str:
    """One script for the whole routine.

    Sent as a single block rather than a move at a time: Klipper queues them
    and runs the corners together, so the motion is continuous instead of
    stopping dead at every step while a round trip over the socket completes.
    """
    lines = ["G90"]
    for position, feedrate, dwell_ms in steps:
        lines.append(f"G1 X{position} F{feedrate}")
        if dwell_ms:
            lines.append(f"G4 P{dwell_ms}")
    # Without it the reply comes back while the routine is still running, and
    # the hardware lock is released mid-dance. See klipper_client.WAIT_FOR_MOVES.
    lines.append("M400")
    return "\n".join(lines)


def catalogue() -> list[dict]:
    """Every routine, with what it does.

    Names and descriptions only, so this needs neither the rail length nor the
    plant positions: the routines are the same list whatever the rail measures.
    """
    return [
        {
            "name": name,
            "title": DANCES[name].title,
            "description": DANCES[name].description,
        }
        for name in DEFAULT_ORDER
    ]
