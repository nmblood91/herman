"""Durable storage for the settings a user changes at runtime.

Plant targets, dose volumes, rail positions, plant names, per-sensor moisture
calibration and LED preferences were all held in memory only, so every API
restart reverted them to the literals in `Automation.__init__`. This keeps them
in one JSON file beside the history database.

Two deliberate choices:

* **Everything is optional.** A missing file, a missing key or a value of the
  wrong type falls back to the code default rather than raising. The appliance
  has to boot with a corrupt or hand-edited state file, not refuse to start.
* **Writes are atomic.** A temporary file in the same directory followed by
  `os.replace`, so a power cut mid-write leaves either the old state or the new
  one. A truncated JSON file here would silently reset every setting the user
  had configured, which is the exact failure this module exists to prevent.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "state.json"

# Bumped only when a reader needs to tell old layouts apart. Unknown versions are
# loaded on a best-effort basis rather than discarded.
SCHEMA_VERSION = 1

CALIBRATION_KEY = "moisture_calibration"
PROFILES_KEY = "plant_profiles"
SOILS_KEY = "soil_profiles"

# What a saved plant carries, and the list is a whitelist rather than
# "everything on the plant" on purpose.
#
# position_mm is the omission that matters: a profile is care settings, not
# placement. Loading "Basil" into the third pot must not drag the first pot's
# rail coordinate along with it -- two plants would then share a coordinate
# and watering one would dribble into the other. plant_id and the LED range
# are excluded for the same reason, being properties of the slot.
#
# watering_mode and the two sweep bounds are left out on the same grounds, and
# the mode is the one that looks arguable. "This plant likes a spread-out
# drink" sounds like care -- but the bounds it needs are rail coordinates that
# cannot travel, so a profile carrying mode without them would load as "sweep"
# over a span of zero. That falls back to point watering, which means the pot
# would read as configured for something it was never doing.
PROFILE_FIELDS = (
    "moisture_target",
    "watering_volume_ml",
    "light_start_time",
    "light_stop_time",
    # Which mix the plant is potted in. Care settings, not placement: a plant
    # moved to another pot keeps its soil, so it travels on load like the rest.
    "soil",
)

# A soil holds the two water contents that bound what a plant can actually use,
# as volumetric water content.
#
# Only their *ratio* leaves this table usefully. It is dimensionless, so a
# published figure applies to any pot of that mix. The absolute values do not
# transfer to raw sensor counts -- converting water content into a reading needs
# a response curve for that specific medium -- which is why field capacity is
# still measured per pot by --calibrate wet, and why this supplies the shape of
# the window rather than its position.
SOIL_FIELDS = (
    "field_capacity_vwc",
    "wilting_point_vwc",
)


def resolve_path(override: str | Path | None = None) -> Path:
    return Path(override) if override else DEFAULT_STATE_PATH


def load_state(path: str | Path | None = None) -> dict[str, Any]:
    """Return the stored state, or an empty dict if there is nothing usable."""
    target = resolve_path(path)
    if not target.exists():
        return {}

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # Deliberately not fatal. Losing customised settings is bad; refusing to
        # boot because a JSON file got truncated is worse.
        logger.warning("Ignoring unreadable state file %s: %s", target, exc)
        return {}

    if not isinstance(data, dict):
        logger.warning("Ignoring state file %s: expected an object", target)
        return {}
    return data


def save_state(data: dict[str, Any], path: str | Path | None = None) -> bool:
    """Write state atomically. Returns False instead of raising on failure."""
    target = resolve_path(path)
    payload = dict(data)
    payload["schema_version"] = SCHEMA_VERSION

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Same directory as the target, so os.replace is a rename within one
        # filesystem and therefore atomic.
        handle, temp_name = tempfile.mkstemp(
            dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, target)
        except BaseException:
            # Leaving a stray .tmp behind on failure would accumulate one file
            # per failed write.
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
    except OSError as exc:
        logger.warning("Could not write state file %s: %s", target, exc)
        return False
    return True


# Keys written by an older version that nothing reads any more. Merging rather
# than replacing on save is deliberate -- storing plants must not clobber
# calibration -- but the side effect is that a renamed key lives forever. One
# of these cost real debugging time: a state file carrying both "zones" and
# "plants" with different names in each, where only one was live.
SUPERSEDED_KEYS = {
    "zones": "plants",  # renamed when zones became plants
}


def _drop_superseded(data: dict[str, Any]) -> bool:
    """Remove dead keys, but only once their replacement exists."""
    dropped = False
    for old_key, replacement in SUPERSEDED_KEYS.items():
        # Guarded on the replacement being present so this never throws away
        # the only copy: if the rename has not happened yet, the old key is
        # still the live one.
        if old_key in data and replacement in data:
            del data[old_key]
            dropped = True
            logger.info("Removed superseded state key %r, replaced by %r", old_key, replacement)
    return dropped


def update_state(
    changes: dict[str, Any], path: str | Path | None = None
) -> dict[str, Any]:
    """Merge top-level keys into the stored state and write it back."""
    data = load_state(path)
    data.update(changes)
    _drop_superseded(data)
    save_state(data, path)
    return data


# --- moisture calibration -------------------------------------------------
#
# Stored under one key so the calibration CLI can read and write it without
# constructing an Automation. Addresses are kept as "0x36" strings because JSON
# object keys must be strings and the hex form is what every other document and
# every i2cdetect listing uses.


def _address_key(address: int) -> str:
    return f"0x{int(address):02x}"


def _parse_address(key: Any) -> int | None:
    try:
        return int(key, 0) if isinstance(key, str) else int(key)
    except (TypeError, ValueError):
        return None


def load_calibration(path: str | Path | None = None) -> dict[int, dict[str, int]]:
    """Per-address {"dry": int, "wet": int}, skipping anything unusable.

    Either endpoint may be absent: calibrating dry and calibrating wet are
    separate passes, and a half-calibrated sensor should keep using the global
    default for the endpoint it has not measured yet.
    """
    stored = load_state(path).get(CALIBRATION_KEY)
    if not isinstance(stored, dict):
        return {}

    result: dict[int, dict[str, int]] = {}
    for key, value in stored.items():
        address = _parse_address(key)
        if address is None or not isinstance(value, dict):
            logger.warning("Skipping malformed calibration entry %r", key)
            continue

        entry: dict[str, int] = {}
        for endpoint in ("dry", "wet"):
            raw = value.get(endpoint)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                continue
            entry[endpoint] = int(raw)
        if entry:
            result[address] = entry
    return result


def save_calibration_point(
    address: int,
    endpoint: str,
    value: int,
    samples: int | None = None,
    measured_at: str | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Record one endpoint for one sensor, leaving the other one alone."""
    if endpoint not in ("dry", "wet"):
        raise ValueError(f"endpoint must be 'dry' or 'wet', not {endpoint!r}")

    data = load_state(path)
    stored = data.get(CALIBRATION_KEY)
    if not isinstance(stored, dict):
        stored = {}

    key = _address_key(address)
    entry = stored.get(key)
    if not isinstance(entry, dict):
        entry = {}

    entry[endpoint] = int(value)
    if samples is not None:
        entry[f"{endpoint}_samples"] = int(samples)
    if measured_at is not None:
        entry[f"{endpoint}_measured_at"] = measured_at

    stored[key] = entry
    data[CALIBRATION_KEY] = stored
    save_state(data, path)
    return entry


def clear_calibration(path: str | Path | None = None) -> None:
    """Drop all calibration, returning every sensor to the global defaults."""
    data = load_state(path)
    if CALIBRATION_KEY in data:
        del data[CALIBRATION_KEY]
        save_state(data, path)


# --- saved plants ---------------------------------------------------------
#
# A small library of care settings keyed by plant name, so "Basil - Wet" can be
# set up once and copied onto any pot. The name is the key, so saving overwrites
# rather than accumulating "Basil (1)", "Basil (2)".


def _match_name(stored: dict[str, Any], name: str) -> str | None:
    """The stored key meaning the same name, ignoring case.

    So "basil" overwrites "Basil" instead of sitting beside it. Keying on the
    name is only useful if one plant means one entry, and a stray capital is
    not a different plant.
    """
    folded = name.casefold()
    for key in stored:
        if isinstance(key, str) and key.casefold() == folded:
            return key
    return None


def _load_named(
    key: str, fields: tuple[str, ...], path: str | Path | None = None
) -> dict[str, dict[str, Any]]:
    """Every entry in one named library, keyed by name.

    Unusable entries are skipped rather than fatal, the same tolerance as the
    rest of this module: a hand-edited file with one bad entry loses that entry,
    not the library.
    """
    stored = load_state(path).get(key)
    if not isinstance(stored, dict):
        return {}

    result: dict[str, dict[str, Any]] = {}
    for name, value in stored.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(value, dict):
            logger.warning("Skipping malformed %s entry %r", key, name)
            continue
        entry = {field: value[field] for field in fields if field in value}
        if not entry:
            # An entry with a name and no settings would show in the picker and
            # then do nothing when applied.
            logger.warning("Skipping empty %s entry %r", key, name)
            continue
        if isinstance(value.get("saved_at"), str):
            entry["saved_at"] = value["saved_at"]
        result[name.strip()] = entry
    return result


def _save_named(
    key: str,
    fields: tuple[str, ...],
    noun: str,
    name: str,
    settings: dict[str, Any],
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Upsert one entry, replacing any of the same name."""
    clean = str(name).strip()
    if not clean:
        raise ValueError(f"A {noun} needs a name")

    entry = {field: settings[field] for field in fields if field in settings}
    if not entry:
        raise ValueError(f"Nothing to save: no recognised {noun} settings given")
    entry["saved_at"] = datetime.now().isoformat(timespec="seconds")

    data = load_state(path)
    stored = data.get(key)
    if not isinstance(stored, dict):
        stored = {}

    # Drop the old key rather than writing alongside it, so a change of
    # capitalisation renames the entry instead of duplicating it.
    previous = _match_name(stored, clean)
    if previous is not None:
        del stored[previous]

    stored[clean] = entry
    data[key] = stored
    save_state(data, path)
    return entry


def _delete_named(key: str, name: str, path: str | Path | None = None) -> bool:
    """Remove one entry. False if there was nothing by that name."""
    data = load_state(path)
    stored = data.get(key)
    if not isinstance(stored, dict):
        return False

    existing = _match_name(stored, str(name).strip())
    if existing is None:
        return False

    del stored[existing]
    data[key] = stored
    save_state(data, path)
    return True


def load_profiles(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Every saved plant, keyed by name."""
    return _load_named(PROFILES_KEY, PROFILE_FIELDS, path)


def save_profile(
    name: str, settings: dict[str, Any], path: str | Path | None = None
) -> dict[str, Any]:
    """Upsert one saved plant, replacing any entry of the same name."""
    return _save_named(PROFILES_KEY, PROFILE_FIELDS, "saved plant", name, settings, path)


def delete_profile(name: str, path: str | Path | None = None) -> bool:
    """Remove a saved plant. False if there was nothing by that name."""
    return _delete_named(PROFILES_KEY, name, path)


# --- soils ----------------------------------------------------------------
#
# The same library shape as saved plants, and deliberately a separate store:
# soil is a property of what is in the pot, plants are a property of what grows
# in it, and several plants share one mix.


def load_soils(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Every saved soil, keyed by name."""
    return _load_named(SOILS_KEY, SOIL_FIELDS, path)


def save_soil(
    name: str, settings: dict[str, Any], path: str | Path | None = None
) -> dict[str, Any]:
    """Upsert one soil, replacing any entry of the same name."""
    return _save_named(SOILS_KEY, SOIL_FIELDS, "soil", name, settings, path)


def delete_soil(name: str, path: str | Path | None = None) -> bool:
    """Remove a soil. False if there was nothing by that name."""
    return _delete_named(SOILS_KEY, name, path)


def available_water_fraction(soil: dict[str, Any] | None) -> float | None:
    """Where wilting point sits as a fraction of field capacity.

    This is the only number that leaves the soil table usefully, and it is the
    bottom of the usable scale: at field capacity a reading is 1.0, at wilting
    point it is this, and everything a plant can actually use lies between.

    None when the soil is unknown or its figures are not usable, so callers
    report "no soil set" rather than silently assuming one.
    """
    if not isinstance(soil, dict):
        return None
    field_capacity = soil.get("field_capacity_vwc")
    wilting_point = soil.get("wilting_point_vwc")
    for value in (field_capacity, wilting_point):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
    if not 0 < wilting_point < field_capacity:
        # Wilting point at or above field capacity would mean no usable water
        # at all, and a negative window breaks every band derived from it.
        return None
    return wilting_point / field_capacity
