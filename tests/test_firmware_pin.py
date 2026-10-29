"""The committed firmware and the pinned Klipper commit are the same source.

The package bundles Klipper's host code at deploy/klipper/KLIPPER_COMMIT and
ships firmware for each supported SKR board, in that board's folder. If
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

# Each supported board: its firmware file, the chip it has to be built for, and
# the link to the Pi. A V2 build on a V3 (or the reverse) does not boot at all,
# so the chip is checked as well as the commit. The link is checked too: a Pico
# built for USB boots fine and then never answers on the UART the installer
# points Klipper at.
BOARDS = {
    "skr-mini-e3-v2": ("firmware.bin", "stm32f103xe", "usb"),
    "skr-mini-e3-v3": ("firmware.bin", "stm32g0b1xx", "usb"),
    "skr-pico": ("firmware.uf2", "rp2040", "uart"),
}

found = {p.parent.name for p in KLIPPER.glob("*/klipper.config")}
assert found == set(BOARDS), (
    f"board folders {sorted(found)} do not match the boards checked here {sorted(BOARDS)}"
)
for stray in ("firmware.bin", "firmware.uf2"):
    assert not (KLIPPER / stray).exists(), (
        f"a {stray} at the top of deploy/klipper names no board; it belongs in a board's folder"
    )

for board, (name, chip, link) in BOARDS.items():
    firmware = KLIPPER / board / name
    assert firmware.is_file(), f"{board} has build options but no {name}"
    built = firmware_version(firmware)
    assert built, f"{board}/{name} has no Klipper data dictionary in it"
    assert same_commit(built, pinned), (
        f"{board}/{name} was built from Klipper {built} but KLIPPER_COMMIT is {pinned}. "
        f"Rebuild it with deploy/klipper/build-firmware.sh {board}, flash it, and commit both."
    )
    config = (data_dictionary(firmware.read_bytes()) or {}).get("config", {})
    mcu = config.get("MCU")
    assert mcu == chip, f"{board}/{name} is built for {mcu}, not {chip}"
    # A serial build declares its baud rate; a USB build reserves the USB pins.
    built_link = "uart" if "SERIAL_BAUD" in config else "usb"
    assert built_link == link, f"{board}/{name} talks over {built_link}, not {link}"
    if link == "uart":
        # Klipper on the Pi opens the port at 250000 unless printer.cfg says
        # otherwise, and the template does not.
        assert config["SERIAL_BAUD"] == 250000, f"{board}/{name} runs at {config['SERIAL_BAUD']} baud"
    print(f"ok: {board}/{name} ({built}, {mcu}, {link}) matches KLIPPER_COMMIT")

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
