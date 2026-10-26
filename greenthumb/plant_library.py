"""The plant profiles a planter ships with, grouped by category.

Each says which of the three soil profiles the plant wants (see
SOIL_PROFILES.md), when to water it as a share of the soil's available water
(see greenthumb.care), and how long and how brightly to light it. Its water level in words is worked
out from the target (care.water_level_for), not taken from the table. See greenthumb.care for what the fields mean and how they are
checked.

Not in the source table, and filled in here the same for every plant:

* **Watering volume**, 100 mL: the table says when to water, not how much,
  and a dose depends on the pot more than on the plant.
* **Light start**, 07:00: the table gives hours, not a clock. The longest
  photoperiod here, 15 h, then ends at 22:00.

Loading a profile onto a pot switches the pot to its preferred soil profile.

**Two source tables.** The herbs, vegetables and bulbs come from the newer
table (2026-10-26), in its order, and it wins for any plant on both. After
them come the plants only the older table had: tomatoes, strawberries,
spinach and Swiss chard (filed with the vegetables, as the newer table files
kale and lettuce), and the houseplants and succulents.

**Where the targets came from.** Both tables give % VWC for each plant. Each
was converted once, through its preferred soil's field capacity and wilting
point %: round((vwc - WP) / (FC - WP) * 100). Those that came out under 10%,
the lowest target allowed, were raised to 10%. Four from the older table sat
outside their own soil entirely and were chosen instead: Peperomia
Obtusifolia and the two desert cacti at 10%, and the Christmas cactus at 35%,
whose 21% VWC was more than its soil holds, so it was never watered
automatically.

The tables' own water level words were not kept; the level comes from the
target. They mostly agree, but not for the fast-draining bulbs: the newer
table calls Hyacinth, Tulip and Daffodil Medium-Dry, yet their 18% VWC is most
of what Fast-Draining Mix holds (25%), so they water at 59%, Medium-Wet. The
number is the measured figure, so it was kept.
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

HERBS = "Culinary Herbs & Kitchen Greens"
VEG = "Indoor Vegetables & Crops"
BULBS = "Flowering Bulbs & Ornamentals"
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
    target_available: int

    @property
    def light_brightness(self) -> int:
        return care.BRIGHTNESS_FOR[self.light_level]

    @property
    def water_level(self) -> str:
        # Worked out from the target, like every pot's.
        return care.water_level_for(self.target_available)


def _p(name, category, soil, hours, light, available) -> LibraryPlant:
    return LibraryPlant(name, category, soil, hours, light, available)


# In the order of the source table.
LIBRARY: tuple[LibraryPlant, ...] = (
    _p("Sweet Basil", HERBS, RICH, 13, "High", 32),
    _p("Thai Basil", HERBS, RICH, 13, "High", 32),
    _p("Catnip", HERBS, RICH, 12, "Medium", 23),
    _p("Chives", HERBS, RICH, 13, "High", 23),
    _p("Cilantro", HERBS, RICH, 11, "Medium", 23),
    _p("Dill", HERBS, RICH, 13, "High", 23),
    _p("French Tarragon", HERBS, RICH, 13, "High", 11),
    _p("Lavender", HERBS, FAST, 14, "Intense", 24),
    _p("Lemon Balm", HERBS, RICH, 12, "Medium", 32),
    _p("Oregano", HERBS, FAST, 13, "Intense", 35),
    _p("Flat-Leaf Parsley", HERBS, RICH, 13, "Medium", 23),
    _p("Spearmint / Peppermint", HERBS, RICH, 13, "Medium", 45),
    _p("Rosemary", HERBS, FAST, 13, "Intense", 35),
    _p("Sage", HERBS, FAST, 13, "Intense", 35),
    _p("Thyme", HERBS, FAST, 13, "Intense", 35),
    _p("Artichoke (Globe)", VEG, RICH, 14, "High", 32),
    _p("Arugula", VEG, RICH, 11, "Medium", 23),
    _p("Asparagus", VEG, RICH, 12, "High", 26),
    _p("Yardlong Noodle Bean", VEG, RICH, 14, "Intense", 26),
    _p("Green Bush Beans", VEG, RICH, 13, "High", 23),
    _p("Beet (Dwarf)", VEG, RICH, 13, "High", 26),
    _p("Bok Choy / Baby Pak Choi", VEG, RICH, 11, "Medium", 45),
    _p("Broccoli (Dwarf/Sprouting)", VEG, RICH, 12, "High", 38),
    _p("Brussels Sprouts (Dwarf)", VEG, RICH, 12, "High", 32),
    _p("Cabbage (Mini)", VEG, RICH, 12, "High", 38),
    _p("Cantaloupe / Sweet Melon", VEG, RICH, 15, "Intense", 45),
    _p("Micro-Carrot", VEG, RICH, 13, "High", 23),
    _p("Cauliflower (Dwarf)", VEG, RICH, 12, "High", 38),
    _p("Celery (Container/Dwarf)", VEG, RICH, 12, "High", 57),
    _p("Collard Greens", VEG, RICH, 11, "Medium", 32),
    _p("Sweet Corn (Dwarf)", VEG, RICH, 15, "Intense", 32),
    _p("Dwarf Cucumber", VEG, RICH, 15, "Intense", 54),
    _p("Dwarf Eggplant", VEG, RICH, 15, "Intense", 32),
    _p("Lacinato / Curly Kale", VEG, RICH, 11, "Low", 32),
    _p("Kohlrabi", VEG, RICH, 12, "High", 32),
    _p("Butterhead Lettuce", VEG, RICH, 11, "Low", 45),
    _p("Romaine Lettuce", VEG, RICH, 11, "Low", 45),
    _p("Microgreens (Mixed Greens)", VEG, RICH, 12, "Medium", 54),
    _p("Mustard Greens", VEG, RICH, 11, "Medium", 32),
    _p("Dwarf Okra", VEG, RICH, 14, "Intense", 26),
    _p("Bulb / Spring Onions", VEG, RICH, 13, "Medium", 32),
    _p("Dwarf Peas (Sugar Snap)", VEG, RICH, 13, "High", 32),
    _p("Snow Peas (Dwarf)", VEG, RICH, 13, "High", 32),
    _p("Bell Pepper", VEG, RICH, 15, "Intense", 14),
    _p("Jalapeño Pepper", VEG, RICH, 15, "Intense", 14),
    _p("Habanero Pepper", VEG, RICH, 15, "Intense", 10),
    _p("Pumpkin (Bush/Dwarf)", VEG, RICH, 15, "Intense", 45),
    _p("Radish", VEG, RICH, 13, "High", 23),
    _p("Dwarf Zucchini / Summer Squash", VEG, RICH, 15, "Intense", 45),
    _p("Cherry Tomato", VEG, RICH, 15, "Intense", 32),
    _p("Beefsteak Tomato", VEG, RICH, 15, "Intense", 32),
    _p("Strawberries", VEG, RICH, 13, "Intense", 32),
    _p("Spinach", VEG, RICH, 11, "Low", 32),
    _p("Swiss Chard", VEG, RICH, 11, "Medium", 32),
    _p("Hyacinth", BULBS, FAST, 12, "High", 59),
    _p("Crocus", BULBS, FAST, 12, "High", 47),
    _p("Tulip", BULBS, FAST, 12, "High", 59),
    _p("Ranunculus (Buttercup)", BULBS, RICH, 12, "High", 14),
    _p("Fritillaria", BULBS, FAST, 12, "High", 47),
    _p("Daffodil (Narcissus)", BULBS, FAST, 12, "High", 59),
    _p("Golden Pothos", HOUSE, RICH, 10, "Low", 10),
    _p("Marble Queen Pothos", HOUSE, RICH, 11, "Medium", 10),
    _p("Monstera Deliciosa", HOUSE, RICH, 11, "High", 11),
    _p("Monstera Adansonii (Swiss Cheese Plant)", HOUSE, COARSE, 11, "High", 64),
    _p("Heartleaf Philodendron", HOUSE, RICH, 10, "Low", 10),
    _p("Philodendron Birkin", HOUSE, RICH, 11, "High", 10),
    _p("Boston Fern", HOUSE, RICH, 11, "Low", 63),
    _p("Maidenhair Fern", HOUSE, RICH, 11, "Low", 63),
    _p("Kimberly Queen Fern", HOUSE, RICH, 11, "Medium", 45),
    _p("Peace Lily (Spathiphyllum)", HOUSE, RICH, 9, "Low", 32),
    _p("Calathea Orbifolia", HOUSE, RICH, 9, "Medium", 45),
    _p("Maranta Leuconeura (Prayer Plant)", HOUSE, RICH, 9, "Medium", 45),
    _p("Ficus Elastica (Rubber Tree)", HOUSE, RICH, 11, "High", 11),
    _p("Fiddle Leaf Fig (Ficus Lyrata)", HOUSE, RICH, 11, "Intense", 11),
    _p("Spider Plant (Chlorophytum Comosum)", HOUSE, RICH, 10, "Medium", 10),
    _p("Chinese Evergreen (Aglaonema)", HOUSE, RICH, 9, "Low", 11),
    _p("Cast Iron Plant (Aspidistra Elatior)", HOUSE, RICH, 8, "Low", 10),
    _p("Peperomia Obtusifolia", HOUSE, RICH, 11, "Medium", 10),
    _p("Watermelon Peperomia", HOUSE, RICH, 11, "Medium", 20),
    _p("Snake Plant (Sansevieria Trifasciata)", HOUSE, FAST, 8, "Low", 10),
    _p("ZZ Plant (Zamioculcas Zamiifolia)", HOUSE, FAST, 8, "Low", 10),
    _p("Echeveria", SUCC, FAST, 13, "Intense", 10),
    _p("Haworthia (Zebra Plant)", SUCC, FAST, 11, "High", 10),
    _p("Aloe Vera", SUCC, FAST, 11, "High", 10),
    _p("Jade Plant (Crassula Ovata)", SUCC, FAST, 11, "High", 12),
    _p("String of Pearls (Senecio Rowleyanus)", SUCC, FAST, 13, "Intense", 10),
    _p("Burro's Tail (Sedum Morganianum)", SUCC, FAST, 13, "Intense", 10),
    _p("Ponytail Palm (Beaucarnea Recurvata)", SUCC, FAST, 11, "Intense", 10),
    _p("Desert Cactus (Mammillaria)", SUCC, FAST, 13, "Intense", 10),
    _p("Prickly Pear Cactus (Opuntia)", SUCC, FAST, 13, "Intense", 10),
    _p("Phalaenopsis Orchid", SUCC, COARSE, 11, "Medium", 27),
    _p("Dendrobium Orchid", SUCC, COARSE, 11, "High", 27),
    _p("Cattleya Orchid", SUCC, COARSE, 11, "High", 27),
    _p("Anthurium Andreeanum", SUCC, COARSE, 11, "High", 45),
    _p("Anthurium Clarinervium", SUCC, COARSE, 11, "High", 45),
    _p("Hoya Carnosa (Wax Plant)", SUCC, COARSE, 11, "High", 45),
    _p("Hoya Kerrii", SUCC, COARSE, 11, "High", 45),
    _p("Christmas / Thanksgiving Cactus (Schlumbergera)", SUCC, COARSE, 11, "Medium", 35),
    _p("Staghorn Fern (Platycerium)", SUCC, COARSE, 11, "Medium", 45),
)


def profile_entry(plant: LibraryPlant) -> dict[str, object]:
    """A library plant as the fields stored in the plant profile library."""
    return {
        "category": plant.category,
        "preferred_soil": plant.preferred_soil,
        "target_available": plant.target_available,
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
                f"water at {plant.target_available:>2}% ({plant.water_level}), "
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
