"""The committed firmware and the pinned Klipper commit are the same source.

The package bundles Klipper's host code at deploy/klipper/KLIPPER_COMMIT and
ships a firmware.bin for each supported SKR board, in that board's folder. If
any of them disagrees with the pin, an update moves the Pi to a Klipper that
board's firmware does not match. Bumping one without the others must fail here,
before it fails on somebody's planter.
"""

from pathlib import Path

from greenthumb.firmware_info import data_dictionary, firmware_version, mismatch, same_commit

KLIPPER = Path(__file__).resolve().parent.parent / "deploy" / "klipper"

pinned = (KLIPPER / "KLIPPER_COMMIT").read_text(encoding="utf-8").strip()
assert len(pinned) == 40 and all(c in "0123456789abcdef" for c in pinned), (
    f"KLIPPER_COMMIT must be a full commit hash, not {pinned!r}"
)

# Each supported board, and the chip its firmware has to be built for. A V2
# build on a V3 (or the reverse) does not boot at all, so the chip is checked
# as well as the commit.
BOARDS = {
    "skr-mini-e3-v2": "stm32f103xe",
    "skr-mini-e3-v3": "stm32g0b1xx",
}

found = {p.parent.name for p in KLIPPER.glob("*/klipper.config")}
assert found == set(BOARDS), (
    f"board folders {sorted(found)} do not match the boards checked here {sorted(BOARDS)}"
)
assert not (KLIPPER / "firmware.bin").exists(), (
    "a firmware.bin at the top of deploy/klipper names no board; it belongs in a board's folder"
)

for board, chip in BOARDS.items():
    firmware = KLIPPER / board / "firmware.bin"
    assert firmware.is_file(), f"{board} has build options but no firmware.bin"
    built = firmware_version(firmware)
    assert built, f"{board}/firmware.bin has no Klipper data dictionary in it"
    assert same_commit(built, pinned), (
        f"{board}/firmware.bin was built from Klipper {built} but KLIPPER_COMMIT is {pinned}. "
        f"Rebuild it with deploy/klipper/build-firmware.sh {board}, flash it, and commit both."
    )
    mcu = (data_dictionary(firmware.read_bytes()) or {}).get("config", {}).get("MCU")
    assert mcu == chip, f"{board}/firmware.bin is built for {mcu}, not {chip}"
    print(f"ok: {board}/firmware.bin ({built}, {mcu}) matches KLIPPER_COMMIT")

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
