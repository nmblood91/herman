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
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "state.json"

# Bumped only when a reader needs to tell old layouts apart. Unknown versions are
# loaded on a best-effort basis rather than discarded.
SCHEMA_VERSION = 1

CALIBRATION_KEY = "moisture_calibration"


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
