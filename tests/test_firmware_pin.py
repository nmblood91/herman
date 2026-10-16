"""The committed firmware and the pinned Klipper commit are the same source.

The package bundles Klipper's host code at deploy/klipper/KLIPPER_COMMIT and
ships deploy/klipper/firmware.bin for the SKR. If those two disagree, an update
moves the Pi to a Klipper the board's firmware does not match. Bumping one
without the other must fail here, before it fails on somebody's planter.
"""

from pathlib import Path

from greenthumb.firmware_info import firmware_version, mismatch, same_commit

KLIPPER = Path(__file__).resolve().parent.parent / "deploy" / "klipper"

pinned = (KLIPPER / "KLIPPER_COMMIT").read_text(encoding="utf-8").strip()
assert len(pinned) == 40 and all(c in "0123456789abcdef" for c in pinned), (
    f"KLIPPER_COMMIT must be a full commit hash, not {pinned!r}"
)

built = firmware_version(KLIPPER / "firmware.bin")
assert built, "firmware.bin has no Klipper data dictionary in it"
assert same_commit(built, pinned), (
    f"firmware.bin was built from Klipper {built} but KLIPPER_COMMIT is {pinned}. "
    "Rebuild it with deploy/klipper/build-firmware.sh, flash it, and commit both."
)
print(f"ok: firmware.bin ({built}) matches KLIPPER_COMMIT")

assert same_commit("2d7717e", pinned)
assert same_commit("v0.13.0-120-g2d7717e", pinned)
assert same_commit("v0.13.0-120-g2d7717e-dirty", pinned)
assert not same_commit("v0.13.0-120-g1234567", pinned)
assert not same_commit("?", pinned)
assert not same_commit(None, pinned)
print("ok: bare hashes and git describe output both compare by commit")

assert not mismatch("2d7717e", "v0.13.0-120-g2d7717e")
assert mismatch("2d7717e", "1234567")
# Unknown is not a mismatch: the board may simply not have connected yet.
assert not mismatch("2d7717e", None)
assert not mismatch("?", "2d7717e")
print("ok: a firmware mismatch is only reported when both versions are known")

print("\nall firmware pin checks passed")
