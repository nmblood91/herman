"""Which Klipper commit a firmware.bin or firmware.uf2 was built from.

Klipper embeds a zlib-compressed JSON "data dictionary" in the firmware, and its
"version" field is the commit the build came from. The Pi's Klipper host has to
come from the same commit as the firmware on the SKR, so this is what proves
the firmware committed in deploy/klipper matches deploy/klipper/KLIPPER_COMMIT:
the package bundles the host at that commit, and an update would otherwise
leave the planter stopped until somebody reflashed the board.
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

# The second byte of a zlib header, for every compression level.
_ZLIB_LEVELS = (0x01, 0x5E, 0x9C, 0xDA)

# A UF2 file is 512-byte blocks, each carrying at most 476 bytes of the image
# between a 32-byte header and an end magic.
_UF2_MAGIC = (0x0A324655, 0x9E5D5157)
_UF2_END = 0x0AB16F30
_UF2_BLOCK = 512


def _uf2_image(firmware: bytes) -> bytes | None:
    """The flash image inside a UF2 file, or None if it is not one.

    Needed because each block's header cuts into the image every 256 bytes,
    which splits the compressed data dictionary and stops zlib reading it.
    """
    if len(firmware) < _UF2_BLOCK or len(firmware) % _UF2_BLOCK:
        return None
    chunks = []
    for at in range(0, len(firmware), _UF2_BLOCK):
        block = firmware[at:at + _UF2_BLOCK]
        magic0, magic1, _flags, address, size = struct.unpack_from("<5I", block)
        (end,) = struct.unpack_from("<I", block, _UF2_BLOCK - 4)
        if (magic0, magic1) != _UF2_MAGIC or end != _UF2_END or size > 476:
            return None
        chunks.append((address, block[32:32 + size]))
    chunks.sort()
    return b"".join(data for _, data in chunks)


def data_dictionary(firmware: bytes) -> dict | None:
    """The firmware's data dictionary, or None if there is none to find."""
    firmware = _uf2_image(firmware) or firmware
    for start in range(len(firmware) - 1):
        if firmware[start] != 0x78 or firmware[start + 1] not in _ZLIB_LEVELS:
            continue
        try:
            raw = zlib.decompressobj().decompress(firmware[start:])
            found = json.loads(raw)
        except (zlib.error, ValueError):
            continue
        if isinstance(found, dict) and "version" in found:
            return found
    return None


def firmware_version(path: str | Path) -> str | None:
    """The Klipper version a firmware file reports, e.g. "2d7717e"."""
    found = data_dictionary(Path(path).read_bytes())
    version = found.get("version") if found else None
    return version if isinstance(version, str) else None


def commit_of(version: str | None) -> str | None:
    """The commit hash in a Klipper version string, if there is one.

    Klipper reports a bare short hash from a tagless checkout ("2d7717e") and
    `git describe` output otherwise ("v0.13.0-120-g2d7717e", possibly with
    "-dirty"); both end in the hash.
    """
    if not version:
        return None
    tail = version.removesuffix("-dirty").rsplit("-g", 1)[-1].lower()
    if len(tail) >= 7 and all(c in "0123456789abcdef" for c in tail):
        return tail
    return None


def same_commit(version: str | None, commit: str | None) -> bool:
    """Whether a Klipper version string names this commit."""
    tail = commit_of(version)
    return bool(tail and commit and commit.lower().startswith(tail))


def mismatch(host: str | None, mcu: str | None) -> bool:
    """True when Klipper on the Pi and the SKR's firmware are known to differ.

    False when either is unknown: "could not tell" is not a reason to tell
    somebody to reflash their board.
    """
    a, b = commit_of(host), commit_of(mcu)
    if not a or not b:
        return False
    return not (a.startswith(b) or b.startswith(a))
