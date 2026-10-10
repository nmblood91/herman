"""Starting entries for the soil library.

A soil holds the two water contents that bound what a plant can actually use:
**field capacity**, what the mix holds once free drainage stops, and **wilting
point**, where the remaining water is gripped too tightly for roots to pull
out. The difference is plant-available water.

**What transfers from this table, and what does not.** Only the *ratio* of
wilting point to field capacity leaves here usefully. It is dimensionless, so a
published figure applies to any pot of that mix. The absolute water contents do
*not* convert into raw sensor counts -- a capacitive probe reads dielectric
permittivity, and that relationship depends on texture, organic matter, bulk
density and salinity, so turning water content into a reading needs a response
curve for that specific medium. Which is why field capacity is also *measured*,
once per mix in a real pot: this table supplies the *shape* of the usable
window, the measurement supplies its *position*.

That same soil-dependence is the reason recording the mix matters at all. Two
identical probes in two different mixes will disagree, and without the mix
written down that spread looks like sensor variation.

**Two things to know before trusting these.** Published figures for mineral
soils come from standard tensions (-33 kPa and -1500 kPa) and are reasonably
settled. Container substrates are not: they are mostly organic, far more
porous, release water at lower tensions, and vary by manufacturer and by how
firmly they were packed. And they **change with use** -- unused peat holds
measurably more water than the same mix after a season, as it compacts and
breaks down. So re-measure after a repot rather than assuming the entry still
describes the pot.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from greenthumb import state
from greenthumb.config import settings


@dataclass(frozen=True)
class LibrarySoil:
    name: str
    # Volumetric water content, as a percentage.
    field_capacity_vwc: float
    wilting_point_vwc: float
    note: str

    @property
    def available_points(self) -> float:
        """Width of the usable window, in VWC points."""
        return round(self.field_capacity_vwc - self.wilting_point_vwc, 1)

    @property
    def wilting_fraction(self) -> float:
        """Wilting point as a fraction of field capacity."""
        return self.wilting_point_vwc / self.field_capacity_vwc


# Ordered by how much usable water they hold, widest first.
LIBRARY: tuple[LibrarySoil, ...] = (
    LibrarySoil(
        name="Coco coir",
        field_capacity_vwc=55,
        wilting_point_vwc=15,
        note=(
            "The widest window here and the most forgiving to automate: it "
            "holds a great deal of water and releases most of it. Wilting "
            "point sits at only about a quarter of field capacity, so a "
            "reading has a long way to fall before the plant is in trouble."
        ),
    ),
    LibrarySoil(
        name="Clay loam",
        field_capacity_vwc=36,
        wilting_point_vwc=18,
        note=(
            "Holds the most water of the mineral soils but grips half of it "
            "below wilting point, so its usable window is no wider than "
            "loam's. The classic trap: wettest on paper, not the most "
            "forgiving in practice."
        ),
    ),
    LibrarySoil(
        name="Loam",
        field_capacity_vwc=28,
        wilting_point_vwc=11,
        note=(
            "The reference mineral soil, and the figures most irrigation "
            "guidance assumes. Rarely what is in a houseplant pot, but useful "
            "as the benchmark the container mixes are compared against."
        ),
    ),
    LibrarySoil(
        name="Peat potting mix",
        field_capacity_vwc=28,
        wilting_point_vwc=16,
        note=(
            "What most bagged potting compost is, and the default to assume. "
            "Wilting point sits at about 57% of field capacity, so the whole "
            "usable range is the top 43% of a field-capacity-referenced "
            "scale -- and published work notes the transition from field "
            "capacity to wilting is fast. Comfortable to needing water is a "
            "small change in water content, which is why a percentage reads "
            "as more precise than it is."
        ),
    ),
    LibrarySoil(
        name="Cactus / sandy mix",
        field_capacity_vwc=12,
        wilting_point_vwc=5,
        note=(
            "The narrowest window by far: it holds little and loses it "
            "quickly. Suits plants that want to dry out, which is the point, "
            "but it leaves very little margin -- the same absolute error in "
            "calibration spans a far larger share of the usable range here "
            "than in coir."
        ),
    ),
)


def install(overwrite: bool = False, path=None) -> dict[str, str]:
    """Write the library into the soil store.

    Existing entries are kept unless `overwrite` is set, so this never quietly
    replaces a mix somebody has measured for themselves.
    """
    existing = {name.casefold() for name in state.load_soils(path)}
    outcome: dict[str, str] = {}

    for soil in LIBRARY:
        if soil.name.casefold() in existing and not overwrite:
            outcome[soil.name] = "kept"
            continue
        state.save_soil(
            soil.name,
            {
                "field_capacity_vwc": soil.field_capacity_vwc,
                "wilting_point_vwc": soil.wilting_point_vwc,
                # The explanation of where these figures came from, which this
                # file has always carried and install used to discard -- so
                # the reasoning stayed in the source and never reached anyone
                # reading the library in the app.
                "notes": soil.note,
            },
            path,
        )
        outcome[soil.name] = "written"
    return outcome


# Mirrors soil_sensors.MIN_CALIBRATION_SPAN. Copied rather than imported: that
# module imports smbus2, so importing it here would make this CLI need I2C to
# print a table. If the two drift, this one is only ever too permissive --
# span_for is what actually refuses a reading.
MIN_CALIBRATION_SPAN = 50


def set_field_capacity(name: str, raw: int, path=None) -> str:
    """Write a mix's field capacity as a raw count, without measuring it.

    Measuring is the app's job and takes a pot of the mix soaked through and
    left to drain for a day. This is for a figure you already have: putting one
    back after a reflash, or copying a known-good reading onto a second
    planter. A clean Pi is this project's upgrade path, and re-soaking four
    pots to recover a number somebody wrote down is not one.

    No measurement date is written, and samples is 0. That absence is the tell:
    the app shows a date beside a measured figure and nothing beside this one.
    """
    soils = state.load_soils(path)
    key = next((k for k in soils if k.casefold() == name.strip().casefold()), None)
    if key is None:
        known = ", ".join(sorted(soils)) or "none installed"
        raise ValueError(f"No soil called {name.strip()!r}. Installed: {known}")

    # A figure at or below the dry floor cannot produce a reading: span_for
    # returns None under MIN_CALIBRATION_SPAN, every pot on that mix reads -1,
    # and nothing is ever watered. Refused here rather than stored, because
    # from the app that state is indistinguishable from never having measured.
    floor = settings.moisture_raw_dry + MIN_CALIBRATION_SPAN
    if raw < floor:
        raise ValueError(
            f"{raw} is too low to read against: the dry floor is "
            f"{settings.moisture_raw_dry} and a usable span needs at least "
            f"{MIN_CALIBRATION_SPAN} counts above it, so {floor} or more."
        )

    state.save_soil(
        key,
        {
            "field_capacity_raw": int(raw),
            "field_capacity_samples": 0,
            "field_capacity_measured_at": "",
            "field_capacity_address": None,
        },
        path,
    )
    return key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Starting entries for the soil library.",
        epilog=(
            "Only the wilting-point-to-field-capacity ratio transfers between "
            "pots. Field capacity itself is measured per mix in the app, under "
            "Plants and Soil, and must be re-measured after a repot."
        ),
    )
    parser.add_argument(
        "--install", action="store_true", help="write these into the soil library"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace entries of the same name instead of keeping yours",
    )
    parser.add_argument(
        "--set-field-capacity",
        nargs=2,
        metavar=("SOIL", "RAW"),
        help="write a mix's field capacity by hand, as a raw sensor count",
    )
    args = parser.parse_args(argv)

    if args.set_field_capacity:
        name, raw = args.set_field_capacity
        try:
            key = set_field_capacity(name, int(raw))
        except ValueError as error:
            print(error)
            return 1
        print(f"{key}: field capacity set to {int(raw)} by hand, not measured.")
        print(
            "Pots already filled with it keep the figure they have -- the copy "
            "is deliberate. Re-pick the mix on a pot's card to take this one."
        )
        return 0

    if not args.install:
        for soil in LIBRARY:
            print(f"\n{soil.name}")
            print(
                f"  field capacity {soil.field_capacity_vwc}% VWC"
                f"   wilting point {soil.wilting_point_vwc}%"
                f"   usable {soil.available_points} pts"
                f"   (wilting at {soil.wilting_fraction * 100:.0f}% of field capacity)"
            )
            print(f"  {soil.note}")
        print("\nRe-run with --install to add these to the soil library.")
        return 0

    outcome = install(overwrite=args.overwrite)
    for name, result in outcome.items():
        print(f"{name:<20} {result}")
    kept = sum(1 for result in outcome.values() if result == "kept")
    if kept:
        print(f"\n{kept} left as they were. Re-run with --overwrite to replace them.")
    print(
        "\nSet a soil on each pot under Plants and Soil, then measure each "
        "mix's field capacity there. A pot is not watered automatically until "
        "both are done."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
