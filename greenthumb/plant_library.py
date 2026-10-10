"""Starting profiles for five common plants.

The photoperiods come from published work and are the solid part. The moisture
targets are **bands**, not percentages, and that is deliberate rather than a
simplification: no plant-care source publishes a sensor percentage, because the
number depends on the probe and the mix. What the literature does describe is
behaviour -- "let the top inch dry", "let it dry out completely" -- and a band
is the closest honest expression of that.

A band is a depletion of plant-available water, so what a target means in
percentage terms is worked out per soil from the mix's wilting point. See
`greenthumb.moisture`. The consequence worth knowing: **a plant will not be
watered automatically until its pot has a soil set**, because without one a
reading cannot be turned into a band at all.

Several plants sharing a band is honest, not a loss of precision. The research
does not separate basil from lettuce to within a few percent, and pretending
otherwise was the problem with the old numbers.

Volumes assume a **15 cm (6 inch) pot**, roughly 1.5 L of mix, sized for
frequent small doses rather than a weekly soak. Scale them with the pot: a
10 cm pot wants about half, a 20 cm pot about double.

Sources are cited per plant. The houseplants have no published DLI because
nobody grows them for yield, so their photoperiods are ordinary houseplant
practice rather than research, and they say so.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from greenthumb import state


@dataclass(frozen=True)
class LibraryPlant:
    name: str
    # A band name from greenthumb.moisture: water once the pot reaches this.
    moisture_target: str
    watering_volume_ml: int
    light_start_time: str
    light_stop_time: str
    # Why these numbers, and how much to trust them.
    note: str


# Ordered by when they want water, soonest first -- the part of this that is
# defensible. Several plants sharing a band is expected, not a loss.
LIBRARY: tuple[LibraryPlant, ...] = (
    LibraryPlant(
        name="Lettuce",
        moisture_target="medium",
        watering_volume_ml=150,
        light_start_time="06:00",
        light_stop_time="22:00",
        note=(
            "16 h is both the grower default and the research optimum: a DLI of "
            "14.4 mol/m2/d over 16 h gave the greatest fresh biomass and leaf "
            "area, and going from 12 to 16 h can add up to 30% fresh weight "
            "where intensity allows. Leafy crops plateau near 17 h and "
            "sensitive lettuce varieties get tip burn beyond it, so 16 is the "
            "ceiling worth using. Shallow roots dry out fast, hence the high "
            "target and a dose on the generous side."
        ),
    ),
    LibraryPlant(
        name="Peace Lily",
        moisture_target="dry",
        watering_volume_ml=150,
        light_start_time="08:00",
        light_stop_time="20:00",
        note=(
            "Consistently moist but never soggy, with the top inch allowed to "
            "dry slightly before the next watering -- about weekly in average "
            "indoor conditions. The wettest plant here, and the one that tells "
            "you it is thirsty by drooping, so it is a forgiving one to tune "
            "against. 12 h of light is houseplant practice, not research: it "
            "tolerates low indirect light and is not being grown for yield."
        ),
    ),
    LibraryPlant(
        name="Basil",
        moisture_target="dry",
        watering_volume_ml=150,
        light_start_time="06:00",
        light_stop_time="22:00",
        note=(
            "Consensus optimum DLI is 13-15 mol/m2/d, with 14.4 over a 16 h "
            "photoperiod the best energy-efficiency trade-off; photoperiod "
            "length itself barely changed growth, so 16 h is chosen for the "
            "DLI it delivers. Wants steady moisture but resents waterlogging "
            "more than lettuce does, which is why its target sits slightly "
            "lower."
        ),
    ),
    LibraryPlant(
        name="Pothos",
        moisture_target="very dry",
        watering_volume_ml=120,
        light_start_time="08:00",
        light_stop_time="20:00",
        note=(
            "Wants the top inch dry before watering again, roughly weekly. The "
            "most commonly overwatered houseplant there is, so the target is "
            "set to let the pot genuinely dry down rather than to keep it "
            "damp. 12 h of light is houseplant practice: it is famously "
            "tolerant of low light."
        ),
    ),
    LibraryPlant(
        name="Snake Plant",
        moisture_target="very dry",
        watering_volume_ml=80,
        light_start_time="08:00",
        light_stop_time="18:00",
        note=(
            "Soil should dry out almost completely between waterings -- every "
            "10-14 days, stretching to two or three weeks in cooler months. "
            "The driest plant here by a wide margin. On an uncalibrated "
            "planter a target this low may mean it is never watered "
            "automatically at all, which for a snake plant is the safe way to "
            "be wrong. 10 h of light, again practice rather than research."
        ),
    ),
)


def install(overwrite: bool = False, path=None) -> dict[str, str]:
    """Write the library into the saved-plant store.

    Existing entries are left alone unless `overwrite` is set, so this never
    quietly replaces a plant somebody has tuned to their own readings.
    """
    existing = {name.casefold() for name in state.load_profiles(path)}
    outcome: dict[str, str] = {}

    for plant in LIBRARY:
        if plant.name.casefold() in existing and not overwrite:
            outcome[plant.name] = "kept"
            continue
        state.save_profile(
            plant.name,
            {
                "moisture_target": plant.moisture_target,
                "watering_volume_ml": plant.watering_volume_ml,
                "light_start_time": plant.light_start_time,
                "light_stop_time": plant.light_stop_time,
                # Why these numbers, and how far to trust them. Carried through
                # now rather than discarded on install: the hedging is the most
                # useful part of a looked-up profile.
                "notes": plant.note,
            },
            path,
        )
        outcome[plant.name] = "written"
    return outcome


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Starting profiles for five common plants.",
        epilog=(
            "The photoperiods are researched; the moisture targets are "
            "conservative starting points, not measurements. Calibrate the "
            "sensors before tuning against them."
        ),
    )
    parser.add_argument(
        "--install", action="store_true", help="write these into the saved-plant library"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace entries of the same name instead of keeping yours",
    )
    args = parser.parse_args(argv)

    if not args.install:
        for plant in LIBRARY:
            hours = (
                int(plant.light_stop_time[:2]) - int(plant.light_start_time[:2])
            ) % 24
            print(f"\n{plant.name}")
            print(
                f"  water at {plant.moisture_target:<9} dose {plant.watering_volume_ml} mL"
                f"   light {plant.light_start_time}-{plant.light_stop_time} ({hours} h)"
            )
            print(f"  {plant.note}")
        print("\nRe-run with --install to add these to the saved-plant library.")
        return 0

    outcome = install(overwrite=args.overwrite)
    for name, result in outcome.items():
        print(f"{name:<14} {result}")
    kept = sum(1 for result in outcome.values() if result == "kept")
    if kept:
        print(f"\n{kept} left as they were. Re-run with --overwrite to replace them.")
    print("\nLoad any of them onto a pot from the Plants tab.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
