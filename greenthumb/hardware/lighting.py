from __future__ import annotations

import logging
import threading
import time
from typing import Literal

from greenthumb.hardware.led_strip import CHIPS, DEFAULT_CHIP, AddressableStrip

logger = logging.getLogger(__name__)

Mode = Literal["off", "schedule", "manual", "rainbow"]
VALID_MODES = {"off", "schedule", "manual", "rainbow"}
VALID_COLOR_ORDERS = ("RGB", "RBG", "GRB", "GBR", "BRG", "BGR")

FRAME_INTERVAL = 1 / 30
IDLE_INTERVAL = 0.5


def colour_wheel(position: int) -> tuple[int, int, int]:
    position %= 256
    if position < 85:
        return (position * 3, 255 - position * 3, 0)
    if position < 170:
        position -= 85
        return (255 - position * 3, 0, position * 3)
    position -= 170
    return (0, position * 3, 255 - position * 3)


def _dim(pixel: tuple[int, int, int], brightness: int) -> tuple[int, int, int]:
    scale = max(0, min(int(brightness), 100)) / 100
    red, green, blue = pixel
    return (int(red * scale), int(green * scale), int(blue * scale))


# What a new controller starts with, and what Restore to Defaults returns to.
# Chip and colour order are not here: those come from .env.
DEFAULT_MODE = "schedule"
DEFAULT_COLOR = (0, 255, 128)
DEFAULT_BRIGHTNESS = 75


class LedController:
    """Renders lighting modes onto an addressable strip from a background thread."""

    def __init__(
        self,
        led_count: int = 60,
        strip: AddressableStrip | None = None,
        chip: str = DEFAULT_CHIP,
        color_order: str | None = None,
        spi_bus: int = 0,
        spi_device: int = 0,
    ) -> None:
        self.led_count = max(int(led_count), 1)
        self.mode: Mode = DEFAULT_MODE
        self.color = DEFAULT_COLOR
        self.brightness = DEFAULT_BRIGHTNESS
        self.strip = strip if strip is not None else AddressableStrip(
            bus=spi_bus, device=spi_device, chip=chip, color_order=color_order
        )

        # (first LED, last LED, lit, brightness %). Brightness is per plant and
        # may be None, which means the strip-wide brightness.
        self._segments: list[tuple] = []
        self._rainbow_offset = 0
        self._last_frame: list[tuple[int, int, int]] | None = None
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="leds", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        self.strip.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._render()
            except Exception:
                logger.exception("LED render failed")

            if self.mode == "rainbow":
                self._rainbow_offset = (self._rainbow_offset + 2) % 256
                time.sleep(FRAME_INTERVAL)
            else:
                # Static modes only need redrawing when something changes, so
                # wait to be woken instead of burning a core on identical frames.
                self._wake.wait(IDLE_INTERVAL)
                self._wake.clear()

    def _render(self) -> None:
        frame = self._build_frame()
        if frame == self._last_frame:
            return
        if self.strip.show(frame):
            self._last_frame = frame

    def _build_frame(self) -> list[tuple[int, int, int]]:
        if self.mode == "schedule":
            return self._schedule_frame()
        if self.mode == "off":
            pixels = [(0, 0, 0)] * self.led_count
        elif self.mode == "manual":
            pixels = [self.color] * self.led_count
        else:
            pixels = [
                colour_wheel(index * 256 // self.led_count + self._rainbow_offset)
                for index in range(self.led_count)
            ]
        return [_dim(pixel, self.brightness) for pixel in pixels]

    def _schedule_frame(self) -> list[tuple[int, int, int]]:
        """Each plant's stretch of strip at that plant's own brightness."""
        pixels = [(0, 0, 0)] * self.led_count
        for segment in self._segments:
            start, end, lit = segment[:3]
            if not lit:
                continue
            brightness = segment[3] if len(segment) > 3 and segment[3] is not None else self.brightness
            colour = _dim(self.color, brightness)
            for index in range(max(start, 0), min(end, self.led_count - 1) + 1):
                pixels[index] = colour
        return pixels

    def set_plant_segments(self, segments: list[tuple]) -> None:
        """Which LED ranges the schedule wants lit, and how bright.

        Each is (first, last, lit) or (first, last, lit, brightness %). Ignored
        outside schedule mode.
        """
        if segments != self._segments:
            self._segments = segments
            self._wake.set()

    def set_mode(self, mode: str) -> dict[str, str]:
        if mode not in VALID_MODES:
            raise ValueError(f"Unsupported LED mode: {mode}")
        self.mode = mode  # type: ignore[assignment]
        self._wake.set()
        return {"status": "ok", "mode": mode}

    def set_static_color(self, color: tuple[int, int, int]) -> dict[str, object]:
        self.color = color
        self.mode = "manual"
        self._wake.set()
        return {"status": "ok", "color": color, "mode": self.mode}

    def set_brightness(self, brightness: int) -> dict[str, object]:
        self.brightness = max(0, min(int(brightness), 100))
        self._wake.set()
        return {"status": "ok", "brightness": self.brightness}

    def set_color_order(self, order: str) -> dict[str, object]:
        normalised = str(order).strip().upper()
        if normalised not in VALID_COLOR_ORDERS:
            raise ValueError(f"Unsupported LED color order: {order}")
        self.strip.color_order = normalised
        # Only the wire encoding changes, not the pixel values, so the
        # unchanged-frame check would otherwise skip sending the new order.
        self._last_frame = None
        self._wake.set()
        return {"status": "ok", "color_order": normalised}

    def set_chip(self, chip: str) -> dict[str, object]:
        spec = self.strip.set_chip(chip)
        # Timing and channel order both change, and neither alters the pixel
        # values, so the unchanged-frame check would skip sending the new one.
        self._last_frame = None
        self._wake.set()
        return {
            "status": "ok",
            "chip": self.strip.chip,
            "color_order": self.strip.color_order,
            "description": spec.description,
        }

    def status(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "color": self.color,
            "brightness": self.brightness,
            "led_count": self.led_count,
            "chip": self.strip.chip,
            "chip_options": [
                {"name": name, "description": spec.description}
                for name, spec in CHIPS.items()
            ],
            "color_order": self.strip.color_order,
            "color_order_options": list(VALID_COLOR_ORDERS),
            # Whether frames can be sent, not whether a strip is listening: the
            # data line is write-only, so an attached strip is not detectable.
            "spi_ready": self.strip.available,
            "error": self.strip.error,
        }
