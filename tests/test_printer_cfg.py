"""printer.cfg comes out right for each motion board.

The template names the SKR Mini E3's pins and the SKR Pico's config is made
from it by swapping names (deploy/klipper/make-printer-cfg.py). A Mini E3 pin
the map missed would reach Klipper on a Pico as a name the RP2040 does not
have, and Klipper refuses the whole config over it, so the planter is dead
until somebody reads klippy.log. This catches that, and checks the swapped
pins against Klipper's stock Pico config, before it gets that far.
"""

import importlib.util
import re
from pathlib import Path

KLIPPER = Path(__file__).resolve().parent.parent / "deploy" / "klipper"

spec = importlib.util.spec_from_file_location("make_printer_cfg", KLIPPER / "make-printer-cfg.py")
make = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make)

TEMPLATE = (KLIPPER / "printer.cfg.example").read_text(encoding="utf-8")
STM32_PIN = re.compile(r"\bP[A-F]\d{1,2}\b")


def settings(text):
    """{section: {key: value}} for the plain key: value lines of a config."""
    found, section = {}, None
    for line in text.splitlines():
        if not line.strip() or line.startswith((" ", "\t", "#")):
            continue
        heading = re.fullmatch(r"\[(.+)\]", line.strip())
        if heading:
            section = found.setdefault(heading.group(1), {})
        elif ":" in line and section is not None:
            key, value = line.split(":", 1)
            section[key.strip()] = value.split("#", 1)[0].strip()
    return found


# The Mini E3: the template untouched apart from the serial line, which is what
# the installer's sed used to produce.
mini = make.printer_cfg("skr-mini-e3", "/dev/serial/by-id/usb-Klipper_stm32g0b1xx_123-if00")
assert mini == TEMPLATE.replace(
    make.TEMPLATE_SERIAL, "serial: /dev/serial/by-id/usb-Klipper_stm32g0b1xx_123-if00"
)
print("ok: the Mini E3 config is the template with its serial filled in")

pico = make.printer_cfg("skr-pico", "/dev/ttyAMA0")
leftover = sorted(set(STM32_PIN.findall(pico)))
assert not leftover, f"Mini E3 pins with no Pico mapping, comments included: {leftover}"
print("ok: no Mini E3 pin name is left in the Pico config")

# Every entry in the map is used. One that matches nothing is a pin the
# template stopped using, or a typo that leaves the real pin unmapped.
for pin in make.pin_map("skr-pico"):
    assert re.search(rf"\b{pin}\b", TEMPLATE), f"pins.map maps {pin}, which the template never uses"
print("ok: every pins.map entry matches a pin in the template")

# Two Mini E3 pins landing on one Pico pin would be the same header claimed
# twice, which Klipper refuses ("pin used multiple times").
targets = list(make.pin_map("skr-pico").values())
assert len(targets) == len(set(targets)), f"pins.map sends two pins to one: {targets}"

# The pins Herman actually drives, against Klipper's
# config/generic-bigtreetech-skr-pico-v1.0.cfg. The X dir keeps the template's
# inversion, as the stock config's does: which way is right depends on the
# motor's wiring, and the direction test on the Calibration tab sorts it out.
cfg = settings(pico)
assert cfg["mcu"]["serial"] == "/dev/ttyAMA0"
assert cfg["mcu"]["restart_method"] == "command"
assert cfg["stepper_x"]["step_pin"] == "gpio11"
assert cfg["stepper_x"]["dir_pin"] == "!gpio10"
assert cfg["stepper_x"]["enable_pin"] == "!gpio12"
assert cfg["stepper_x"]["endstop_pin"] == "^gpio4"
for axis, address in (("stepper_x", "0"), ("stepper_y", "2"), ("stepper_z", "1")):
    driver = cfg[f"tmc2209 {axis}"]
    assert (driver["uart_pin"], driver["tx_pin"], driver["uart_address"]) == ("gpio9", "gpio8", address), driver
assert (cfg["stepper_y"]["step_pin"], cfg["stepper_y"]["dir_pin"], cfg["stepper_y"]["enable_pin"]) == ("gpio6", "gpio5", "!gpio7")
assert (cfg["stepper_z"]["step_pin"], cfg["stepper_z"]["dir_pin"], cfg["stepper_z"]["enable_pin"]) == ("gpio19", "gpio28", "!gpio2")
assert cfg["output_pin pump"]["pin"] == "gpio21"
print("ok: the Pico's motor, endstop, driver and pump pins match Klipper's stock config")

# Nothing else moved: every setting that is not a pin or the serial line is
# the same on both boards.
mini_cfg = settings(mini)
for section, values in mini_cfg.items():
    for key, value in values.items():
        if key == "serial" or STM32_PIN.search(value):
            continue
        assert cfg[section][key] == value, f"[{section}] {key} differs: {cfg[section][key]} vs {value}"
print("ok: the boards differ only in pins and the serial line")

try:
    make.printer_cfg("skr-pico", "/dev/ttyAMA0", template="[mcu]\nserial: /dev/ttyUSB0\n")
except ValueError:
    pass
else:
    raise AssertionError("a template with no serial placeholder was accepted")
print("ok: a template without the serial placeholder is refused, not half-filled")

print("\nall printer.cfg checks passed")
