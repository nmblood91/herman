"""Two watering modes: a fixed point, and an oscillating sweep.

The sweep's passes stand in for the pump's dwell -- they have to, because a
`G4` blocks Klipper's queue and moves sent from elsewhere would run after the
dose rather than during it. That substitution makes travel time into dose time,
and puts one property above all the others here:

    **the motion must never last longer than the dose.**

Overrun does not show up as a wrong number on a screen. The pump keeps running
and the pot overflows. So the tests below are mostly about that bound holding
across every span, dose and clamp, about acceleration being in the maths at all
(the ramps at fifty reversals are not a rounding error), and about every case a
sweep cannot be honoured falling back to a point dose rather than to no water.
"""

import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb import state, sweep
from greenthumb.config import settings
from greenthumb.hardware.pump import PumpController
from greenthumb.models import SensorSample
from greenthumb.services.automation import GreenThumbAutomation
from tests.helpers import CalibrationSurface, give_every_plant_soil, temp_state, temp_store

settings.auto_watering_enabled = True
settings.water_sensor_enabled = False
settings.idle_motion_enabled = False

ACCEL = 1000.0
TOP_SPEED = 100.0


# --- a pass is not distance over speed ---

# The carriage cannot carry speed through a 180 degree reversal, so it ramps up
# and back down on every pass. Timing a dose against distance/speed would leave
# the pump running through all of that.
plain = 200 / 40
assert sweep.pass_seconds(200, 40, ACCEL) > plain
assert abs(sweep.pass_seconds(200, 40, ACCEL) - (plain + 40 / ACCEL)) < 1e-9
print("ok: a pass costs its ramps on top of distance over speed")

# Short enough and it never reaches the requested speed at all, so the
# trapezoid formula would claim a time below what the accel limit allows.
# 10 mm at 100 mm/s needs 10 mm just to ramp, so this is the exact boundary.
assert sweep.pass_seconds(10, TOP_SPEED, ACCEL) == 2.0 * (10 / ACCEL) ** 0.5
assert sweep.pass_seconds(10, TOP_SPEED, ACCEL) == 0.2
print("ok: a span too short to reach speed is timed as a triangle, not a trapezoid")

# Well inside the triangular region, where the two formulas disagree. The
# assertion above sits exactly on the boundary, where they happen to coincide,
# so on its own it cannot tell whether the triangular case is handled at all.
assert sweep.pass_seconds(10, 200, ACCEL) == 0.2
assert 10 / 200 + 200 / ACCEL == 0.25, "the trapezoid answer here is a different number"
print("ok: and inside the triangular region, where the two formulas disagree")

# And the two formulas agree exactly where they meet, so there is no step in
# the model at the changeover.
boundary = TOP_SPEED**2 / ACCEL
assert abs(
    sweep.pass_seconds(boundary, TOP_SPEED, ACCEL)
    - (boundary / TOP_SPEED + TOP_SPEED / ACCEL)
) < 1e-12
print("ok: triangle and trapezoid meet without a step")

for bad in ((0, 40, ACCEL), (200, 0, ACCEL), (200, 40, 0), (-5, 40, ACCEL)):
    assert sweep.pass_seconds(*bad) == 0.0, bad
print("ok: a pass with no span, speed or acceleration takes no time, rather than raising")


# --- solving the speed back out of a target time ---

solved = sweep.speed_for(200, 5.4, ACCEL)
assert solved is not None
assert abs(sweep.pass_seconds(200, solved, ACCEL) - 5.4) < 1e-9
print("ok: the solved speed round-trips through the pass timing")

# Two speeds give any reachable duration: cruise slowly, or sprint and then
# spend the rest decelerating. Only the slower one is a sweep.
faster = (ACCEL * 5.4 + ((ACCEL * 5.4) ** 2 - 4 * ACCEL * 200) ** 0.5) / 2
assert solved < faster, (solved, faster)
print("ok: the slower of the two roots is chosen, which is the one that sweeps")

# Below the triangular minimum the span simply cannot be crossed that fast.
floor_seconds = 2.0 * (200 / ACCEL) ** 0.5
assert sweep.speed_for(200, floor_seconds * 0.99, ACCEL) is None
assert sweep.speed_for(200, floor_seconds * 1.01, ACCEL) is not None
print("ok: a pass time below the accel limit has no solution, rather than a fast guess")


# --- the dose is never stretched ---

# The property that matters. Checked across a grid rather than at one point,
# because every branch below -- the pass-count floor, the MAX_PASSES cap and
# the speed clamp -- is a chance to overshoot, and overshoot means the pump
# keeps running into a full pot.
# The top speeds are deliberately not all round numbers. 100 mm/s is 6000
# mm/min exactly, so with that alone the feedrate rounding can never collide
# with the machine limit -- and it is that collision that can make a pass
# slower than the one solved for and push the total past the dose.
checked = 0
for top_speed in (TOP_SPEED, 33.34, 7.77, 61.009):
    for accel in (ACCEL, 180.0, 4500.0):
        for span in (10, 25, 60, 120, 200, 400, 889):
            for duration in (0.5, 1.0, 2.5, 6.0, 20.0, 60.0, 180.0, 600.0):
                plan = sweep.plan(span, duration, top_speed, accel)
                if plan is None:
                    continue
                checked += 1
                where = (top_speed, accel, span, duration, plan)
                assert plan.predicted_seconds <= duration, where
                # And the dwell makes up exactly the difference, so the dose is
                # not quietly shortened either.
                total = plan.predicted_seconds + plan.dwell_ms / 1000
                assert abs(total - duration) < 0.002, where
                assert plan.dwell_ms >= 0, where
                assert 1 <= plan.passes <= sweep.MAX_PASSES, where
                assert plan.feedrate_mm_min >= 1, where
                # A feedrate over the machine limit is one Klipper silently
                # caps, which puts the real time back above the prediction.
                assert plan.speed_mm_s <= top_speed, where
assert checked > 300, checked
print(f"ok: across {checked} plans the motion never outlasts the dose, and fills it")

# The dwell is zero in the ordinary case: the speed is solved to fit, so there
# is nothing left to park for. A dwell that was routinely large would mean the
# dose was mostly delivered standing still.
ordinary = sweep.plan(200, 60, TOP_SPEED, ACCEL)
assert ordinary is not None and ordinary.dwell_ms < 50, ordinary
assert ordinary.passes > 5, ordinary
print(f"ok: a 60s dose over 200 mm is {ordinary.passes} passes at "
      f"F{ordinary.feedrate_mm_min}, with {ordinary.dwell_ms} ms parked")


# --- when a sweep cannot be honoured ---

assert sweep.plan(sweep.MIN_SPAN_MM - 0.1, 60, TOP_SPEED, ACCEL) is None
assert sweep.plan(sweep.MIN_SPAN_MM, 60, TOP_SPEED, ACCEL) is not None
print(f"ok: under {sweep.MIN_SPAN_MM:.0f} mm is not a sweep, and is refused rather than rounded")

# A dose too short to cross the span even flat out. Stretching the pump to fit
# the motion would over-water; shrinking the span would water part of the pot
# while reporting a sweep. Refusing is the only option that keeps the dose.
tight = sweep.pass_seconds(400, TOP_SPEED, ACCEL)
assert sweep.plan(400, tight * 0.9, TOP_SPEED, ACCEL) is None
assert sweep.plan(400, tight * 1.1, TOP_SPEED, ACCEL) is not None
print("ok: a dose too short to cross the span is refused, not stretched to fit")

for bad in (
    (200, 0, TOP_SPEED, ACCEL),
    (200, -5, TOP_SPEED, ACCEL),
    (200, 60, 0, ACCEL),
    (200, 60, TOP_SPEED, 0),
):
    assert sweep.plan(*bad) is None, bad
print("ok: a plan with no dose, no speed or no acceleration is refused")

# A long dose over a narrow span would otherwise run to thousands of passes.
capped = sweep.plan(12, 3600, TOP_SPEED, ACCEL)
assert capped is not None and capped.passes == sweep.MAX_PASSES, capped
# Hitting the cap must still honour the dose, which it does by sweeping slower.
assert abs(capped.predicted_seconds + capped.dwell_ms / 1000 - 3600) < 0.002, capped
print(f"ok: the pass count caps at {sweep.MAX_PASSES} and the dose is filled by going slower")


# --- the gcode ---

plan = sweep.plan(200, 60, TOP_SPEED, ACCEL)
lines = sweep.gcode(plan, 100.0, 300.0)
assert lines[0] == "G90", lines[0]
moves = [line for line in lines if line.startswith("G1 ")]
assert len(moves) == plan.passes, (len(moves), plan.passes)

# The first move goes to the far end. The carriage is already parked at the
# near one -- _sweep_motion sends it there before the pump starts -- so a first
# move back to the start would be a no-op pass, and the dose would run one pass
# short while standing still.
assert moves[0] == f"G1 X300.0 F{plan.feedrate_mm_min}", moves[0]
assert moves[1] == f"G1 X100.0 F{plan.feedrate_mm_min}", moves[1]

targets = {line.split()[1] for line in moves}
assert targets == {"X300.0", "X100.0"}, targets
# Alternating, not drifting: every pass is an absolute move, so fifty of them
# cannot accumulate rounding and walk off the pot.
for index, line in enumerate(moves):
    assert line.split()[1] == ("X300.0" if index % 2 == 0 else "X100.0"), (index, line)
print(f"ok: {plan.passes} absolute passes alternating between the two ends")

assert not any(line.startswith("G4") for line in lines), lines
padded = sweep.gcode(sweep.Plan(2, 1200, 450, 3.0), 0.0, 50.0)
assert padded[-1] == "G4 P450", padded
print("ok: a dwell is appended only when there is a shortfall to park for")


# --- the service layer ---

class Klip:
    """Records what it was asked to run, and reports real motion limits."""

    def __init__(self, limits=True):
        self.scripts = []
        self.moves = []
        self._limits = limits

    def send_gcode(self, script, timeout=5.0):
        self.scripts.append(script)
        return {"ok": True}

    def move_gantry_absolute(self, position):
        self.moves.append(position)
        return {"ok": True}

    def status(self):
        reported = {"ok": True, "position": 0.0, "homed": True, "max_x": 890.0}
        if self._limits:
            reported["max_velocity"] = TOP_SPEED
            reported["max_accel"] = ACCEL
        return reported

    def water_supply_present(self):
        return True


class Hub(CalibrationSurface):
    addresses = [0x36, 0x37, 0x38, 0x39]
    def raw_to_percent(self, raw, address=None): return 0.0
    def read_one(self, a): return SensorSample(a, 0.0, 350.0, 22.0)


class Leds:
    mode = "schedule"
    def set_plant_segments(self, s): pass
    def status(self): return {"mode": "schedule"}


def build(limits=True, path=None):
    klip = Klip(limits)
    auto = give_every_plant_soil(
        GreenThumbAutomation(
            Hub(), klip, PumpController(klip), Leds(),
            history=temp_store(), state_path=path or temp_state(),
        )
    )
    return auto, klip


def dose_script(klip):
    """The one script that drives the pump, which is the thing under test."""
    scripts = [s for s in klip.scripts if "SET_PIN PIN=pump VALUE=1" in s]
    assert len(scripts) == 1, scripts
    return scripts[0]


auto, klip = build()
pot = auto.plants[0]
assert pot.watering_mode == sweep.POINT, pot.watering_mode
print("ok: a plant waters at a point until told otherwise")


# --- setting the span ---

result = auto.set_plant_sweep(pot.plant_id, 300, 100)
assert (result["sweep_min_mm"], result["sweep_max_mm"]) == (100.0, 300.0), result
assert result["sweep_span_mm"] == 200.0, result
print("ok: bounds given the wrong way round are ordered, since that is an ordering not a value")

limit = auto.usable_travel_mm()
for low, high, why in (
    (-10, 200, "off the left end"),
    (700, limit + 50, "off the right end"),
    (200, 205, "narrower than a sweep"),
    (200, 200, "no span at all"),
    ("x", 200, "not a number"),
    (True, 200, "a boolean"),
    (None, 200, "missing"),
    (float("nan"), 200, "not-a-number"),
    (0, float("inf"), "infinite"),
):
    try:
        auto.set_plant_sweep(pot.plant_id, low, high)
    except ValueError:
        pass
    else:
        raise AssertionError(f"accepted a span {why}: {low} to {high}")
# Refused means unchanged, not partly applied.
assert (pot.sweep_min_mm, pot.sweep_max_mm) == (100.0, 300.0), (pot.sweep_min_mm, pot.sweep_max_mm)
print("ok: an unusable span is refused outright, and the stored one is untouched")


# --- the mode will not turn on without a span ---

spare = auto.plants[1]
try:
    auto.set_watering_mode(spare.plant_id, "sweep")
except ValueError as error:
    assert "span" in str(error), error
else:
    raise AssertionError("turned on sweep with no span to sweep")
assert spare.watering_mode == sweep.POINT
print("ok: sweep cannot be switched on before the span is set, so no pot is labelled for nothing")

for bad in ("spray", "", "oscillate"):
    try:
        auto.set_watering_mode(pot.plant_id, bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"accepted watering mode {bad!r}")
print("ok: an unknown mode is refused")

assert auto.set_watering_mode(pot.plant_id, "  SWEEP ")["watering_mode"] == "sweep"
print("ok: the mode is matched case-insensitively, like the other names")


# --- watering, point and sweep ---

auto, klip = build()
pot, spare = auto.plants[0], auto.plants[1]
auto.set_plant_position(pot.plant_id, 220)
auto.water_plant(pot.plant_id, 100)

script = dose_script(klip)
assert "G4 P" in script and "G1 " not in script, script
assert klip.moves[-1] == 220.0, klip.moves
print("ok: a point dose still dwells at the pot, unchanged")

# A span set but the mode left alone. The two are separate settings, so
# recording where a sweep would go must not start one -- and with the span
# still at its default of zero this is indistinguishable from the case above.
auto, klip = build()
pot = auto.plants[0]
auto.set_plant_position(pot.plant_id, 220)
auto.set_plant_sweep(pot.plant_id, 120, 320)
auto.water_plant(pot.plant_id, 100)
script = dose_script(klip)
assert "G1 " not in script, script
assert klip.moves[-1] == 220.0, klip.moves
print("ok: a span on its own does not start sweeping, it takes the mode too")

auto, klip = build()
pot = auto.plants[0]
auto.set_plant_position(pot.plant_id, 220)
auto.set_plant_sweep(pot.plant_id, 120, 320)
auto.set_watering_mode(pot.plant_id, "sweep")
auto.water_plant(pot.plant_id, 100)

script = dose_script(klip)
lines = script.splitlines()

# One script, pin on first and off last. If the motion were ever moved out to
# a second call, a dropped connection mid-sweep would strand the pump on with
# the carriage parked over one spot -- which is the flood this guards against.
assert lines[0] == "SET_PIN PIN=pump VALUE=1", lines[0]
assert lines[-1] == "SET_PIN PIN=pump VALUE=0", lines[-1]
assert sum(line.startswith("SET_PIN") for line in lines) == 2, lines

passes = [line for line in lines if line.startswith("G1 ")]
assert len(passes) > 1, lines
assert "G4 P" not in script or passes, script
print(f"ok: the dose and its {len(passes)} passes are queued as one script")

# Pre-positioned to the near end of the span, not to the pot's point position.
assert klip.moves[-1] == 120.0, klip.moves
print("ok: the carriage is sent to the start of the span before the pump starts")

# The dose is right end to end, and this is the check that would survive a
# rewrite of the planning: recompute the script's own running time from its
# feedrate and pass count, and compare it with the dose the pump was asked for.
feedrate = int(passes[0].split("F")[1])
dwell = sum(int(line.split("P")[1]) for line in lines if line.startswith("G4 P"))
running = len(passes) * sweep.pass_seconds(200.0, feedrate / 60.0, ACCEL) + dwell / 1000
asked = auto.pump.seconds_for_ml(100)
assert abs(running - asked) < 0.01, (running, asked)
print(f"ok: the script runs for {running:.2f}s against a dose of {asked:.2f}s")


# --- every way a sweep can fail still waters the plant ---

# The rail re-measured shorter than a saved span. Klipper refuses an
# out-of-range move outright, which would abort the dose rather than spread it
# differently, so this has to be caught here.
auto, klip = build()
pot = auto.plants[0]
auto.set_plant_position(pot.plant_id, 400)
auto.set_plant_sweep(pot.plant_id, 700, 880)
auto.set_watering_mode(pot.plant_id, "sweep")
pot.sweep_max_mm = 2000.0          # as if position_max had been reduced
auto.water_plant(pot.plant_id, 100)
assert "G4 P" in dose_script(klip) and klip.moves[-1] == 400.0, klip.moves
print("ok: a span that has fallen off the rail waters as a point, rather than not at all")

# A dose too short to cross the span.
auto, klip = build()
pot = auto.plants[0]
auto.set_plant_position(pot.plant_id, 400)
auto.set_plant_sweep(pot.plant_id, 100, 880)
auto.set_watering_mode(pot.plant_id, "sweep")
auto.water_plant(pot.plant_id, 2)
assert "G1 " not in dose_script(klip), dose_script(klip)
assert klip.moves[-1] == 400.0, klip.moves
print("ok: a dose too small to sweep waters as a point, rather than over-watering")

# Klipper not reporting its motion limits. An invented acceleration that was
# too high would leave the pump running through ramps nobody budgeted for.
auto, klip = build(limits=False)
pot = auto.plants[0]
auto.set_plant_position(pot.plant_id, 400)
auto.set_plant_sweep(pot.plant_id, 120, 320)
auto.set_watering_mode(pot.plant_id, "sweep")
auto.water_plant(pot.plant_id, 100)
assert "G1 " not in dose_script(klip), dose_script(klip)
print("ok: with no motion limits reported there is no sweep, rather than a mistimed one")

# The flow rate comes off the pump, and a stub that answers every attribute
# must not be mistaken for one holding a real figure.
auto, _ = build()
assert abs(auto._dose_seconds(100) - 100 / auto.pump.flow_ml_per_second) < 1e-9
auto.pump.flow_ml_per_second = 0
assert auto._dose_seconds(100) > 0
print("ok: the dose timing survives a pump reporting no usable flow rate")


# --- it survives a restart, and does not travel in a profile ---

shared = temp_state()
auto, _ = build(path=shared)
pot, spare = auto.plants[0], auto.plants[1]
auto.set_plant_sweep(pot.plant_id, 150, 350)
auto.set_watering_mode(pot.plant_id, "sweep")

restored, _ = build(path=shared)
kept = restored.get_plant(pot.plant_id)
assert kept.watering_mode == "sweep", kept.watering_mode
assert (kept.sweep_min_mm, kept.sweep_max_mm) == (150.0, 350.0)
print("ok: the mode and the span survive a restart")

# A saved plant is care settings, not placement. A profile carrying the mode
# without the bounds -- which are rail coordinates and cannot travel -- would
# load as a sweep over a span of zero, fall back to point watering, and leave
# the pot reading as configured for something it never does.
assert "watering_mode" not in state.PROFILE_FIELDS
assert "sweep_min_mm" not in state.PROFILE_FIELDS
assert "sweep_max_mm" not in state.PROFILE_FIELDS

restored.update_plant_name(pot.plant_id, "Wide fern")
restored.save_plant_profile(pot.plant_id)
restored.apply_plant_profile(spare.plant_id, "Wide fern")
moved = restored.get_plant(spare.plant_id)
assert moved.watering_mode == sweep.POINT, moved.watering_mode
assert (moved.sweep_min_mm, moved.sweep_max_mm) == (0.0, 0.0)
print("ok: loading a saved plant does not drag another pot's span onto it")

# A hand-edited state file with a mode nothing recognises. It falls back to
# point rather than being stored as written: an unknown mode would make every
# dose a point dose anyway, so carrying it would only make the card disagree
# with what the pump does.
auto, _ = build(path=shared)
auto.get_plant(pot.plant_id).watering_mode = "nonsense"
auto._persist()
again, _ = build(path=shared)
survivor = again.get_plant(pot.plant_id)
assert survivor.watering_mode == sweep.POINT, survivor.watering_mode
# The span is left alone, so the figures are still there to switch back on.
assert (survivor.sweep_min_mm, survivor.sweep_max_mm) == (150.0, 350.0)
print("ok: an unrecognised stored mode falls back to point, and the span is kept")


print("\nall watering mode checks passed")
