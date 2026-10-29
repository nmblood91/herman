#!/usr/bin/env python3
"""Write printer.cfg for one motion board, from printer.cfg.example.

    make-printer-cfg.py skr-mini-e3 /dev/serial/by-id/usb-Klipper_stm32g0b1xx_...
    make-printer-cfg.py skr-pico /dev/ttyAMA0

The template is written for the SKR Mini E3 (V2 and V3 share every pin Herman
uses). A board with a pins.map in its folder gets each Mini E3 pin swapped for
its own, so the gantry, endstop and pump settings stay in one place instead of
drifting apart across a template per board. Prints the config to stdout.

Standard library only: the installer runs this before any virtualenv exists.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "printer.cfg.example"
TEMPLATE_SERIAL = "serial: /dev/serial/by-id/usb-Klipper_xxx"

# The boards the installer can be told about, and the folder holding each
# one's pins.map, if it needs one. V2 and V3 are one entry: same pins, and the
# installer finds either on USB by itself.
BOARDS = {
    "skr-mini-e3": None,
    "skr-pico": "skr-pico",
}


def pin_map(board: str) -> dict[str, str]:
    """Mini E3 pin -> this board's pin; empty for the Mini E3 itself."""
    folder = BOARDS[board]
    if folder is None:
        return {}
    pins = {}
    for line in (HERE / folder / "pins.map").read_text(encoding="utf-8").splitlines():
        fields = line.split("#", 1)[0].split()
        if not fields:
            continue
        if len(fields) != 2:
            raise ValueError(f"{folder}/pins.map: expected two pins, got {line!r}")
        pins[fields[0]] = fields[1]
    return pins


def printer_cfg(board: str, serial: str, template: str | None = None) -> str:
    text = TEMPLATE.read_text(encoding="utf-8") if template is None else template
    if TEMPLATE_SERIAL not in text:
        raise ValueError(f"template has no {TEMPLATE_SERIAL!r} line to fill in")
    text = text.replace(TEMPLATE_SERIAL, f"serial: {serial}")
    pins = pin_map(board)
    if pins:
        # Whole names only, so PB1 never rewrites the front of PB10.
        pattern = re.compile(r"\b(" + "|".join(map(re.escape, pins)) + r")\b")
        text = pattern.sub(lambda m: pins[m.group(1)], text)
    return text


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in BOARDS:
        print(f"usage: {Path(argv[0]).name} {{{','.join(BOARDS)}}} SERIAL_DEVICE", file=sys.stderr)
        return 2
    sys.stdout.write(printer_cfg(argv[1], argv[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
