from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChipSpec:
    spi_hz: int
    symbol_bits: int
    zero: int
    one: int
    color_order: str
    description: str


# These chips share a 1.25us bit period and encode a bit by how long the line
# stays high, but they disagree on how long. Rather than clock SPI at the bit
# rate, clock it faster and spend several SPI bits per data bit, choosing a rate
# where the high time lands mid-tolerance and a whole data byte still maps onto a
# whole number of SPI bytes.
# 12V only. A 5V strip is not offered here on purpose: sixty 5V pixels pull
# about 3.6A, which the 12V-to-5V converter cannot supply on top of the Pi, so
# listing one would invite wiring a strip this power system cannot feed. See
# POWER_SYSTEM.md.
CHIPS = {
    # 12V, one pixel per LED, four pads because it carries a backup data line.
    # T0H 300ns, T1H 900ns: the same 417/833 sits inside both windows.
    "WS2815": ChipSpec(2_400_000, 3, 0b100, 0b110, "GRB", "12V, one pixel per LED, 4 pads"),
    # 12V, one pixel per LED, three pads. Often sold as "12V WS2812B".
    "GS8208": ChipSpec(2_400_000, 3, 0b100, 0b110, "GRB", "12V, one pixel per LED, 3 pads"),
    # T0H 250ns, T1H 600ns. Needs the faster clock, where a SPI bit is 312ns, so
    # 1000 holds high 312ns and 1100 holds 625ns. Drives three LEDs per pixel.
    "WS2811": ChipSpec(3_200_000, 4, 0b1000, 0b1100, "RGB", "12V, three LEDs per pixel"),
}

# These rates are a hardware requirement on the host, not a preference, and it
# is the tightest constraint this project puts on the board.
#
# Because the waveform is made of SPI bits, the achievable clock decides whether
# the high times land inside the chip's tolerance. Both families allow +/-150ns:
#
#   chip       zero      one       bit period gives     working window
#   WS2811     1 bit     2 bits    312ns at 3.2MHz      ~2.7 - 4.4 MHz
#   WS2815 /
#   GS8208     1 bit     2 bits    417ns at 2.4MHz      ~2.2 - 2.7 MHz
#
# The windows barely touch, so a host cannot serve both from one rate -- and the
# strip type is selectable at runtime from Settings, so it has to reach both.
# That is two specific clocks, which is a good deal more than "has SPI".
#
# The failure mode is quiet. spidev treats max_speed_hz as a ceiling and
# substitutes the nearest rate its driver can produce, reporting nothing, so a
# host that cannot land in these windows shows up as a strip with wrong or
# flickering colours rather than as an error. Anyone porting this to a board
# that is not a Pi should scope the line before believing the colours.

# WS2811 is what this build ships with. Note it drives three LEDs per pixel,
# so led_count is a third of the LEDs you can count on the strip.
DEFAULT_CHIP = "WS2811"

# The strip latches on a long low. Later WS281x revisions want 280us rather than
# the original 50us, and idle bytes are nearly free. Sized for the fastest clock
# here, so it still clears 280us at WS2811's 3.2MHz.
RESET = b"\x00" * 120


def encoding_table(chip: str) -> list[bytes]:
    """Maps each byte value to the SPI bytes that clock it out as a waveform."""
    spec = CHIPS[chip]
    table = []
    for value in range(256):
        bits = 0
        for index in range(8):
            symbol = spec.one if (value >> (7 - index)) & 1 else spec.zero
            bits = (bits << spec.symbol_bits) | symbol
        table.append(bits.to_bytes(spec.symbol_bits, "big"))
    return table


class AddressableStrip:
    """Drives an addressable LED strip from the Pi's SPI MOSI line."""

    def __init__(
        self,
        bus: int = 0,
        device: int = 0,
        chip: str = DEFAULT_CHIP,
        color_order: str | None = None,
    ) -> None:
        self.chip = chip if chip in CHIPS else DEFAULT_CHIP
        self.color_order = (color_order or CHIPS[self.chip].color_order).upper()
        self._table = encoding_table(self.chip)
        self.spi = None
        self.error: str | None = None

        try:
            import spidev

            self.spi = spidev.SpiDev()
            self.spi.open(bus, device)
            self.spi.max_speed_hz = CHIPS[self.chip].spi_hz
            self.spi.mode = 0
            logger.info(
                "LED strip ready on SPI %d.%d, chip %s, order %s",
                bus,
                device,
                self.chip,
                self.color_order,
            )
        except Exception as exc:
            # Left unavailable rather than faked: the API reports the output as
            # offline so a wiring problem is visible instead of silent.
            self.error = str(exc)
            self.spi = None
            logger.error("LED strip unavailable on SPI %d.%d: %s", bus, device, exc)

    @property
    def available(self) -> bool:
        return self.spi is not None

    def set_chip(self, chip: str) -> ChipSpec:
        """Switch chip timing, and adopt that chip's usual channel order with it."""
        if chip not in CHIPS:
            raise ValueError(f"Unsupported LED chip: {chip}. Known: {', '.join(CHIPS)}")

        spec = CHIPS[chip]
        self.chip = chip
        self._table = encoding_table(chip)
        self.color_order = spec.color_order
        if self.spi:
            self.spi.max_speed_hz = spec.spi_hz
        logger.info("LED chip set to %s (%s, %s)", chip, spec.description, spec.color_order)
        return spec

    def show(self, pixels: list[tuple[int, int, int]]) -> bool:
        if not self.spi:
            return False

        payload = bytearray()
        for red, green, blue in pixels:
            channels = {"R": red, "G": green, "B": blue}
            for name in self.color_order:
                payload += self._table[max(0, min(channels[name], 255))]
        payload += RESET

        try:
            self.spi.writebytes2(payload)
            return True
        except Exception as exc:
            self.error = str(exc)
            logger.error("Failed to write LED frame: %s", exc)
            return False

    def close(self) -> None:
        if self.spi:
            try:
                self.spi.close()
            except Exception:
                pass
            self.spi = None
