"""The plant profiles a planter ships with, grouped by category.

Each says which of the three soil profiles the plant wants (see
SOIL_PROFILES.md), the soil moisture to water it at as a target % VWC, and
how long and how brightly to light it. Its water level in words is worked
out from the target (care.water_level_for), not taken from the table. See greenthumb.care for what the fields mean and how they are
checked.

Not in the source table, and filled in here the same for every plant:

* **Watering volume**, 100 mL: the table says when to water, not how much,
  and a dose depends on the pot more than on the plant.
* **Light start**, 07:00: the table gives hours, not a clock. The longest
  photoperiod here, 15 h, then ends at 22:00.

Loading a profile onto a pot switches the pot to its preferred soil profile.
A few targets sit outside their preferred soil's range (wetter than it holds,
or drier than its wilting point); the pot's card says so when that happens,
rather than the library pretending otherwise.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import time

from greenthumb import care, state

RICH = "Rich & Retentive Mix"
FAST = "Fast-Draining Mix"
COARSE = "Ultra-Coarse Epiphytic Mix"

VEG = "Indoor Vegetables & Fruiting Crops"
HERBS = "Culinary Herbs & Leafy Greens"
HOUSE = "Common Indoor Houseplants & Foliage"
SUCC = "Succulents, Cacti & Epiphytes"

DEFAULT_VOLUME_ML = 100
DEFAULT_START = time(7, 0)


@dataclass(frozen=True)
class LibraryPlant:
    name: str
    category: str
    preferred_soil: str
    light_hours: int
    # One of care.LIGHT_LEVELS by name.
    light_level: str
    target_vwc: int

    @property
    def light_brightness(self) -> int:
        return care.BRIGHTNESS_FOR[self.light_level]

    @property
    def water_level(self) -> str:
        # Worked out from the target, like every pot's.
        return care.water_level_for(self.target_vwc)


def _p(name, category, soil, hours, light, vwc) -> LibraryPlant:
    return LibraryPlant(name, category, soil, hours, light, vwc)


# In the order of the source table.
LIBRARY: tuple[LibraryPlant, ...] = (
    _p("Cherry Tomato", VEG, RICH, 15, "Intense", 28),
    _p("Beefsteak Tomato", VEG, RICH, 15, "Intense", 28),
    _p("Bell Pepper", VEG, RICH, 15, "Intense", 22),
    _p("Jalapeño Pepper", VEG, RICH, 15, "Intense", 22),
    _p("Habanero Pepper", VEG, RICH, 15, "Intense", 20),
    _p("Bush Beans", VEG, RICH, 13, "High", 25),
    _p("Dwarf Cucumber", VEG, RICH, 15, "Intense", 35),
    _p("Strawberries", VEG, RICH, 13, "Intense", 28),
    _p("Dwarf Eggplant", VEG, RICH, 15, "Intense", 28),
    _p("Dwarf Zucchini / Squash", VEG, RICH, 15, "Intense", 32),
    _p("Radish", VEG, RICH, 13, "High", 25),
    _p("Micro-Carrot", VEG, RICH, 13, "High", 25),
    _p("Spring Onion / Green Onion", VEG, RICH, 13, "Medium", 28),
    _p("Dwarf Peas (Sugar Snap)", VEG, RICH, 13, "High", 28),
    _p("Sweet Basil", HERBS, RICH, 13, "High", 28),
    _p("Thai Basil", HERBS, RICH, 13, "High", 28),
    _p("Butterhead Lettuce", HERBS, RICH, 11, "Low", 32),
    _p("Romaine Lettuce", HERBS, RICH, 11, "Low", 32),
    _p("Spinach", HERBS, RICH, 11, "Low", 28),
    _p("Lacinato / Curly Kale", HERBS, RICH, 11, "Low", 28),
    _p("Swiss Chard", HERBS, RICH, 11, "Medium", 28),
    _p("Arugula", HERBS, RICH, 11, "Medium", 25),
    _p("Spearmint / Peppermint", HERBS, RICH, 13, "Medium", 32),
    _p("Flat-Leaf Parsley", HERBS, RICH, 13, "Medium", 25),
    _p("Cilantro", HERBS, RICH, 11, "Medium", 25),
    _p("Chives", HERBS, RICH, 13, "High", 25),
    _p("Rosemary", HERBS, FAST, 13, "Intense", 14),
    _p("Thyme", HERBS, FAST, 13, "Intense", 14),
    _p("Oregano", HERBS, FAST, 13, "Intense", 14),
    _p("Sage", HERBS, FAST, 13, "Intense", 14),
    _p("French Tarragon", HERBS, RICH, 13, "High", 21),
    _p("Golden Pothos", HOUSE, RICH, 10, "Low", 19),
    _p("Marble Queen Pothos", HOUSE, RICH, 11, "Medium", 19),
    _p("Monstera Deliciosa", HOUSE, RICH, 11, "High", 21),
    _p("Monstera Adansonii (Swiss Cheese Plant)", HOUSE, COARSE, 11, "High", 11),
    _p("Heartleaf Philodendron", HOUSE, RICH, 10, "Low", 20),
    _p("Philodendron Birkin", HOUSE, RICH, 11, "High", 20),
    _p("Boston Fern", HOUSE, RICH, 11, "Low", 38),
    _p("Maidenhair Fern", HOUSE, RICH, 11, "Low", 38),
    _p("Kimberly Queen Fern", HOUSE, RICH, 11, "Medium", 32),
    _p("Peace Lily (Spathiphyllum)", HOUSE, RICH, 9, "Low", 28),
    _p("Calathea Orbifolia", HOUSE, RICH, 9, "Medium", 32),
    _p("Maranta Leuconeura (Prayer Plant)", HOUSE, RICH, 9, "Medium", 32),
    _p("Ficus Elastica (Rubber Tree)", HOUSE, RICH, 11, "High", 21),
    _p("Fiddle Leaf Fig (Ficus Lyrata)", HOUSE, RICH, 11, "Intense", 21),
    _p("Spider Plant (Chlorophytum Comosum)", HOUSE, RICH, 10, "Medium", 19),
    _p("Chinese Evergreen (Aglaonema)", HOUSE, RICH, 9, "Low", 21),
    _p("Cast Iron Plant (Aspidistra Elatior)", HOUSE, RICH, 8, "Low", 19),
    _p("Peperomia Obtusifolia", HOUSE, RICH, 11, "Medium", 16),
    _p("Watermelon Peperomia", HOUSE, RICH, 11, "Medium", 24),
    _p("Snake Plant (Sansevieria Trifasciata)", HOUSE, FAST, 8, "Low", 9),
    _p("ZZ Plant (Zamioculcas Zamiifolia)", HOUSE, FAST, 8, "Low", 9),
    _p("Echeveria", SUCC, FAST, 13, "Intense", 9),
    _p("Haworthia (Zebra Plant)", SUCC, FAST, 11, "High", 9),
    _p("Aloe Vera", SUCC, FAST, 11, "High", 9),
    _p("Jade Plant (Crassula Ovata)", SUCC, FAST, 11, "High", 10),
    _p("String of Pearls (Senecio Rowleyanus)", SUCC, FAST, 13, "Intense", 9),
    _p("Burro's Tail (Sedum Morganianum)", SUCC, FAST, 13, "Intense", 9),
    _p("Ponytail Palm (Beaucarnea Recurvata)", SUCC, FAST, 11, "Intense", 9),
    _p("Desert Cactus (Mammillaria)", SUCC, FAST, 13, "Intense", 7),
    _p("Prickly Pear Cactus (Opuntia)", SUCC, FAST, 13, "Intense", 7),
    _p("Phalaenopsis Orchid", SUCC, COARSE, 11, "Medium", 7),
    _p("Dendrobium Orchid", SUCC, COARSE, 11, "High", 7),
    _p("Cattleya Orchid", SUCC, COARSE, 11, "High", 7),
    _p("Anthurium Andreeanum", SUCC, COARSE, 11, "High", 9),
    _p("Anthurium Clarinervium", SUCC, COARSE, 11, "High", 9),
    _p("Hoya Carnosa (Wax Plant)", SUCC, COARSE, 11, "High", 9),
    _p("Hoya Kerrii", SUCC, COARSE, 11, "High", 9),
    _p("Christmas / Thanksgiving Cactus (Schlumbergera)", SUCC, COARSE, 11, "Medium", 21),
    _p("Staghorn Fern (Platycerium)", SUCC, COARSE, 11, "Medium", 9),
)


def profile_entry(plant: LibraryPlant) -> dict[str, object]:
    """A library plant as the fields stored in the plant profile library."""
    return {
        "category": plant.category,
        "preferred_soil": plant.preferred_soil,
        "target_vwc": plant.target_vwc,
        "watering_volume_ml": DEFAULT_VOLUME_ML,
        "light_start_time": DEFAULT_START.isoformat(timespec="minutes"),
        "light_hours": plant.light_hours,
        "light_brightness": plant.light_brightness,
        "notes": "",
    }


def install(overwrite: bool = False, path=None) -> dict[str, str]:
    """Write the library into the plant profile store.

    Existing entries are left alone unless `overwrite` is set, so this never
    quietly replaces a plant somebody has tuned to their own readings.
    """
    existing = {name.casefold() for name in state.load_profiles(path)}
    outcome: dict[str, str] = {}

    for plant in LIBRARY:
        if plant.name.casefold() in existing and not overwrite:
            outcome[plant.name] = "kept"
            continue
        state.save_profile(plant.name, profile_entry(plant), path)
        outcome[plant.name] = "written"
    return outcome


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"The {len(LIBRARY)} plant profiles a planter ships with.",
    )
    parser.add_argument(
        "--install", action="store_true", help="write these into the plant profile library"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace entries of the same name instead of keeping yours",
    )
    args = parser.parse_args(argv)

    if not args.install:
        category = None
        for plant in LIBRARY:
            if plant.category != category:
                category = plant.category
                print(f"\n{category}")
            stop = care.light_stop(DEFAULT_START, plant.light_hours)
            print(
                f"  {plant.name:<48} {plant.preferred_soil:<27} "
                f"water at {plant.target_vwc:>2}% ({plant.water_level}), "
                f"light {DEFAULT_START:%H:%M}-{stop:%H:%M} at {plant.light_level}"
            )
        print("\nRe-run with --install to add these to the plant profile library.")
        return 0

    outcome = install(overwrite=args.overwrite)
    written = sum(1 for result in outcome.values() if result == "written")
    kept = len(outcome) - written
    print(f"{written} plant profiles written.")
    if kept:
        print(f"{kept} left as they were. Re-run with --overwrite to replace them.")
    print("\nLoad any of them onto a pot under Plants and Soil.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
