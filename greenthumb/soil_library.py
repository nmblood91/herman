"""The soil profiles a planter ships with: three soilless substrate recipes.

Three mixes cover every plant this planter is meant for, each built from
hardware-store ingredients: a rich, retentive mix for vegetables, herbs and
thirsty tropicals; a fast-draining mix for desert plants, succulents and woody
herbs; and an ultra-coarse epiphytic mix for orchids and jungle epiphytes.
SOIL_PROFILES.md is the user-facing write-up -- recipes, figures and which
plants go in which.

Each carries its published **field capacity** and **permanent wilting point**
as % volumetric water content. Watering also needs a field capacity *sensor
reading*, which this table cannot supply -- a capacitive probe's reading
depends on the exact mix, how firmly it was packed and the probe itself, so it
is measured in a real pot. The ratio of the two % figures then places each
pot's wilting point between its probe's air reading and that field capacity
(soil_sensors.wilting_point_for), so these figures are working numbers, not
just reference.

The figures are ranges in the source. The midpoint of each is stored, and the
range is kept in the note so it reaches the editor. Mixes **change with use**
as they compact and break down, so re-measure field capacity after a repot.
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
    # Volumetric water content, as a percentage: the midpoint of the published
    # range, which is kept in the note.
    field_capacity_vwc: float
    wilting_point_vwc: float
    note: str
    # The default field capacity sensor reading, measured on the reference
    # build with the recipe mixed as written. None until it has been. It is
    # what lets a new planter water straight away; a batch that reads
    # differently is re-measured in the Soil Profile Editor.
    field_capacity_raw: int | None = None

    @property
    def available_points(self) -> float:
        """Width of the usable window, in VWC points."""
        return round(self.field_capacity_vwc - self.wilting_point_vwc, 1)

    @property
    def wilting_fraction(self) -> float:
        """Wilting point as a fraction of field capacity."""
        return self.wilting_point_vwc / self.field_capacity_vwc


# The only three a planter ships with. Ordered wettest to driest, which is also
# the order of the recipes in SOIL_PROFILES.md.
LIBRARY: tuple[LibrarySoil, ...] = (
    LibrarySoil(
        name="Rich & Retentive Mix",
        field_capacity_vwc=50,
        wilting_point_vwc=17.5,
        note=(
            "Recipe 1, for vegetables and tropicals. 2 parts potting mix, "
            "1 part peat or coir, 1 part perlite, 1 part vermiculite. Fine "
            "organic matter and vermiculite hold water and nutrients so "
            "fast-growing plants never dry out. Field capacity 45-55% VWC, "
            "permanent wilting point 15-20%, about 30% available water. "
            "Dries out in 5-10 days indoors. "
            "For: tomatoes, peppers, bush beans, strawberries, cucumbers; "
            "lettuce, spinach, kale, basil, parsley, mint, cilantro; ferns, "
            "calatheas, peace lilies, begonias, fittonia."
        ),
    ),
    LibrarySoil(
        name="Fast-Draining Mix",
        field_capacity_vwc=25,
        wilting_point_vwc=8,
        note=(
            "Recipe 2, for desert plants and succulents. 2 parts potting mix, "
            "2 parts perlite, 1 part coarse sand (or fine orchid bark). Large "
            "pores drain water almost at once, protecting dryland plants from "
            "root rot. Field capacity 20-30% VWC, permanent wilting point "
            "6-10%, about 15% available water. Dries out in 3-5 days indoors. "
            "For: echeveria, aloe vera, jade, haworthia, cacti; snake plants, "
            "ZZ plants, ponytail palms; rosemary, thyme, lavender, oregano."
        ),
    ),
    LibrarySoil(
        name="Ultra-Coarse Epiphytic Mix",
        field_capacity_vwc=15,
        wilting_point_vwc=4,
        note=(
            "Recipe 3, for orchids and jungle epiphytes. 3 parts coarse bark, "
            "1 part chunk coir or peat, 1 part coarse perlite (or pumice). "
            "Maximum air around thick, fleshy roots; water is held only inside "
            "the bark and the coir fibres. Field capacity 12-18% VWC, "
            "permanent wilting point 3-5%, about 10% available water. Dries "
            "out in 1-3 days indoors. "
            "For: phalaenopsis, cattleya, dendrobium, oncidium orchids; "
            "anthuriums, monsteras, philodendrons, syngoniums; Christmas and "
            "Thanksgiving cactus, hoyas, staghorn ferns, tillandsia."
        ),
    ),
)


def install(overwrite: bool = False, path=None) -> dict[str, str]:
    """Write the library into the soil store.

    Existing entries are kept unless `overwrite` is set, so this never quietly
    replaces a mix somebody has measured for themselves. The one exception is
    a kept entry with no field capacity reading at all: it is given the
    default, since there is nothing of anyone's to lose and without it the
    planter cannot water.
    """
    existing = {name.casefold(): entry for name, entry in state.load_soils(path).items()}
    outcome: dict[str, str] = {}

    for soil in LIBRARY:
        stored = existing.get(soil.name.casefold())
        if stored is not None and not overwrite:
            if soil.field_capacity_raw is not None and stored.get("field_capacity_raw") is None:
                state.save_soil(soil.name, _default_reading(soil), path)
                outcome[soil.name] = "kept, default field capacity added"
            else:
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
                **(_default_reading(soil) if soil.field_capacity_raw is not None else {}),
            },
            path,
        )
        outcome[soil.name] = "written"
    return outcome


def _default_reading(soil: LibrarySoil) -> dict[str, object]:
    """The shipped field capacity reading, marked as not measured here.

    No date and no samples, the same tell as a figure typed by hand: the app
    shows a date beside a reading taken on this planter and nothing beside
    this one.
    """
    return {
        "field_capacity_raw": int(soil.field_capacity_raw),
        "field_capacity_samples": 0,
        "field_capacity_measured_at": "",
        "field_capacity_address": None,
    }


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
        raise ValueError(f"No soil profile called {name.strip()!r}. Installed: {known}")

    # A figure too close to the soil profile's wilting point cannot produce a
    # reading: span_for returns None under MIN_CALIBRATION_SPAN, every pot on
    # it reads -1, and nothing is ever watered. Refused here rather than
    # stored, because from the app that state is indistinguishable from never
    # having measured. With no wilting point yet, the probes' air reading is
    # the floor: soil never reads below it.
    wilting = soils[key].get("wilting_point_raw")
    if isinstance(wilting, (int, float)) and not isinstance(wilting, bool):
        floor, what = int(wilting) + MIN_CALIBRATION_SPAN, f"its wilting point of {int(wilting)}"
    else:
        floor, what = settings.moisture_raw_dry + 1, f"a probe in open air ({settings.moisture_raw_dry})"
    if raw < floor:
        raise ValueError(
            f"{raw} is too low: field capacity has to read above {what}, "
            f"so {floor} or more."
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
        description="The three soil profiles a planter ships with. See SOIL_PROFILES.md.",
        epilog=(
            "Watering runs on each soil profile's field capacity sensor "
            "reading, with wilting point estimated from it and the %% VWC "
            "figures. A shipped default reading is used until you measure your "
            "own in the Soil Profile Editor in the app."
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
        print("Every pot filled with it reads against this once the service restarts.")
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
            reading = soil.field_capacity_raw
            print(f"  default field capacity reading {reading if reading is not None else 'not set yet'}")
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
        "\nSet a soil profile on each pot under Plants and Soil. A soil profile "
        "without a field capacity reading needs one measured in the Soil "
        "Profile Editor before its pots are watered automatically."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
