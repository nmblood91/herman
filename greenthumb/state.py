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
# 2 since field capacity moved off the per-address calibration and onto the
# soil and the pot. The marker is what lets a later reader tell "no field
# capacity because this file predates the change" from "nobody has measured
# one yet" -- which look identical otherwise and want different advice.
SCHEMA_VERSION = 2

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
#
# soil is out for the plainest reason of all: it is in the pot. Loading a
# profile does not repot anything, so a travelling soil would have a saved
# plant assert a physical fact about a pot nobody touched. And the two ways of
# being wrong are not symmetrical. If soil stays and you *did* repot, you pick
# the mix again from a dropdown you are already looking at. If soil travelled
# and you did not, the pot silently bands every reading against the wrong
# wilting point and waters to it, and nothing looks broken.
PROFILE_FIELDS = (
    "moisture_target",
    "watering_volume_ml",
    "light_start_time",
    "light_stop_time",
    # Why this plant is set up the way it is. Free text, and the only field here
    # the planter never acts on -- which is the point: the numbers say what it
    # does, and this says why, for whoever reads it next.
    "notes",
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
    # Field capacity again, this time as a raw sensor count, measured in a real
    # pot of this mix with one probe. This is the half that could not be looked
    # up: the VWC figures above give the *shape* of the usable window, and this
    # gives its position on the scale a probe actually reports.
    #
    # Measured once per mix rather than once per pot, because probes of the
    # same kind read closely enough that one good figure beats four nobody got
    # round to taking. A pot that wants better can measure its own, which
    # overrides this.
    "field_capacity_raw",
    "field_capacity_samples",
    "field_capacity_measured_at",
    # Which probe took it, so the figure can be reported with its provenance
    # and so a cross-probe span can be sanity-checked.
    "field_capacity_address",
    # Where the figures came from, and how much to trust them. The library
    # ships this text for its own mixes; before this field existed it was
    # written in soil_library.py and thrown away on install.
    "notes",
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
    """Per-address {"dry": int}, skipping anything unusable.

    Dry only. The wet endpoint used to live here too, measured per probe -- but
    it is field capacity, which is a property of the mix in the pot rather than
    of the probe, and it now lives on the soil and the plant.

    Files written before that change still carry "wet" keys. They are left
    where they are, because they record a real measurement and merging state
    rather than replacing it means removing them needs code not worth writing.
    They are simply never read: this iterates ("dry",) so nothing can pick one
    up by accident, and save_calibration_point refuses to write one.
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
        for endpoint in ("dry",):
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
    """Record the dry point for one sensor.

    Dry is the only endpoint that belongs to a probe. Field capacity is a
    property of the mix and is written to the soil or the plant instead, so
    this refuses it rather than leaving a second, stale copy here.
    """
    if endpoint != "dry":
        raise ValueError(
            f"endpoint must be 'dry', not {endpoint!r}. Field capacity belongs "
            "to the soil or the pot, not to the probe."
        )

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
    """Drop the dry calibration, returning every sensor to the configured dry.

    Field capacity is untouched: it lives on the soils and the pots, and the
    two are no longer reset together. That separation is the point -- re-doing
    a dry pass should not throw away a measurement of somebody's potting mix.
    """
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
    merge: bool = False,
) -> dict[str, Any]:
    """Upsert one entry, replacing any of the same name.

    `merge` carries forward whitelisted fields the caller did not supply,
    instead of dropping them. Without it, a caller that knows about some of an
    entry's fields silently deletes the rest -- which is how editing a soil's
    two VWC figures would have thrown away the field capacity somebody
    measured in a pot. Handled here rather than in that one caller, or the next
    caller reopens the same hole.
    """
    clean = str(name).strip()
    if not clean:
        raise ValueError(f"A {noun} needs a name")

    entry = {field: settings[field] for field in fields if field in settings}
    if not entry:
        raise ValueError(f"Nothing to save: no recognised {noun} settings given")

    data = load_state(path)
    stored = data.get(key)
    if not isinstance(stored, dict):
        stored = {}

    # Drop the old key rather than writing alongside it, so a change of
    # capitalisation renames the entry instead of duplicating it.
    previous = _match_name(stored, clean)
    if previous is not None:
        if merge and isinstance(stored[previous], dict):
            kept = {
                field: stored[previous][field]
                for field in fields
                if field in stored[previous]
            }
            entry = {**kept, **entry}
        del stored[previous]

    entry["saved_at"] = datetime.now().isoformat(timespec="seconds")

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
    name: str,
    settings: dict[str, Any],
    path: str | Path | None = None,
    merge: bool = True,
) -> dict[str, Any]:
    """Upsert one soil, keeping fields the caller did not mention.

    Merging by default, unlike saved plants. A soil is written from two
    directions -- the editor supplies the VWC figures and a note, a calibration
    supplies the measured field capacity -- and neither knows about the other's
    fields. Replacing wholesale means whichever saved last wipes the rest.
    """
    return _save_named(SOILS_KEY, SOIL_FIELDS, "soil", name, settings, path, merge)


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
