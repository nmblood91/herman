from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Literal

from greenthumb.care import DEFAULT_LIGHT_BRIGHTNESS, DEFAULT_LIGHT_COLOR

from greenthumb.hardware.led_strip import CHIPS, DEFAULT_CHIP, AddressableStrip, pixel_count

logger = logging.getLogger(__name__)

Mode = Literal["off", "schedule", "manual", "rainbow"]
VALID_MODES = {"off", "schedule", "manual", "rainbow"}
VALID_COLOR_ORDERS = ("RGB", "RBG", "GRB", "GBR", "BRG", "BGR")
# Manual mode lights the whole strip one way, or each pot's zone its own way.
VALID_MANUAL_SCOPES = ("all", "zones")


@dataclass(frozen=True)
class Zone:
    """One pot's stretch of strip and everything that decides how it is lit.

    Schedule mode uses lit, brightness and color; manual mode with the zones
    scope uses manual_color and manual_brightness. They are separate settings,
    so changing a pot's manual look never changes its scheduled one.
    """

    start: int
    end: int
    lit: bool = False
    brightness: int = DEFAULT_LIGHT_BRIGHTNESS
    color: tuple[int, int, int] = DEFAULT_LIGHT_COLOR
    manual_color: tuple[int, int, int] = DEFAULT_LIGHT_COLOR
    manual_brightness: int = DEFAULT_LIGHT_BRIGHTNESS

FRAME_INTERVAL = 1 / 30
IDLE_INTERVAL = 0.5


def color_wheel(position: int) -> tuple[int, int, int]:
    position %= 256
    if position < 85:
        return (position * 3, 255 - position * 3, 0)
    if position < 170:
        position -= 85
        return (255 - position * 3, 0, position * 3)
    position -= 170
    return (0, position * 3, 255 - position * 3)


# Rainbow speed is 0-100. 0 holds the rainbow still where it is; 1-100 is
# mapped onto the time one full trip round the color wheel takes: two minutes
# at 1, two seconds at 100. Exponential, so each step of the slider feels like
# the same change whether it is slow or fast.
SLOWEST_CYCLE_SECONDS = 120.0
FASTEST_CYCLE_SECONDS = 2.0
PAUSED_RAINBOW_SPEED = 0


def clamp_rainbow_speed(speed: object) -> int:
    if isinstance(speed, bool):
        raise ValueError(f"Unsupported rainbow speed: {speed}")
    return max(PAUSED_RAINBOW_SPEED, min(int(speed), 100))


def rainbow_cycle_seconds(speed: int) -> float | None:
    """Seconds for one trip round the color wheel, or None when paused."""
    speed = clamp_rainbow_speed(speed)
    if speed == PAUSED_RAINBOW_SPEED:
        return None
    fraction = (speed - 1) / 99
    return SLOWEST_CYCLE_SECONDS * (FASTEST_CYCLE_SECONDS / SLOWEST_CYCLE_SECONDS) ** fraction


def _dim(pixel: tuple[int, int, int], brightness: int) -> tuple[int, int, int]:
    scale = max(0, min(int(brightness), 100)) / 100
    red, green, blue = pixel
    return (int(red * scale), int(green * scale), int(blue * scale))


# What a new controller starts with, and what Restore to Defaults returns to.
# Chip and color order are not here: those come from .env.
DEFAULT_MODE = "schedule"
DEFAULT_COLOR = DEFAULT_LIGHT_COLOR
DEFAULT_BRIGHTNESS = DEFAULT_LIGHT_BRIGHTNESS
DEFAULT_MANUAL_SCOPE = "all"
# About 4 s a cycle, the speed the rainbow ran at before it had a setting.
DEFAULT_RAINBOW_SPEED = 82


class LedController:
    """Renders lighting modes onto an addressable strip from a background thread."""

    def __init__(
        self,
        led_count: int | None = None,
        strip: AddressableStrip | None = None,
        chip: str = DEFAULT_CHIP,
        color_order: str | None = None,
        spi_bus: int = 0,
        spi_device: int = 0,
    ) -> None:
        # A count given here is fixed (LED_COUNT in .env, or a test). Without
        # one, the count follows the chip on the standard one-meter strip, and
        # changes when the chip does.
        self._fixed_count = max(int(led_count), 1) if led_count else None
        self.mode: Mode = DEFAULT_MODE
        self.color = DEFAULT_COLOR
        self.brightness = DEFAULT_BRIGHTNESS
        self.rainbow_speed = DEFAULT_RAINBOW_SPEED
        self.manual_scope = DEFAULT_MANUAL_SCOPE
        self.strip = strip if strip is not None else AddressableStrip(
            bus=spi_bus, device=spi_device, chip=chip, color_order=color_order
        )
        self.led_count = self._count_for(getattr(self.strip, "chip", chip))

        self._zones: list[Zone] = []
        # A float, so a slow rainbow can advance by less than one wheel step a
        # frame.
        self._rainbow_offset = 0.0
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

            if self.mode == "rainbow" and self.rainbow_speed != PAUSED_RAINBOW_SPEED:
                self._advance_rainbow()
                time.sleep(FRAME_INTERVAL)
            else:
                # A paused rainbow too: its frame stops changing, so it waits
                # like a static mode, and set_rainbow_speed wakes it to move on.
                # Static modes only need redrawing when something changes, so
                # wait to be woken instead of burning a core on identical frames.
                self._wake.wait(IDLE_INTERVAL)
                self._wake.clear()

    def _advance_rainbow(self) -> None:
        """One frame's turn of the color wheel at the current speed."""
        cycle = rainbow_cycle_seconds(self.rainbow_speed)
        if cycle is None:
            return
        step = 256 * FRAME_INTERVAL / cycle
        self._rainbow_offset = (self._rainbow_offset + step) % 256

    def _render(self) -> None:
        frame = self._build_frame()
        if frame == self._last_frame:
            return
        if self.strip.show(frame):
            self._last_frame = frame

    def _build_frame(self) -> list[tuple[int, int, int]]:
        if self.mode == "schedule":
            return self._zone_frame(lambda zone: (zone.color, zone.brightness) if zone.lit else None)
        if self.mode == "manual" and self.manual_scope == "zones":
            return self._zone_frame(lambda zone: (zone.manual_color, zone.manual_brightness))
        if self.mode == "off":
            pixels = [(0, 0, 0)] * self.led_count
        elif self.mode == "manual":
            pixels = [self.color] * self.led_count
        else:
            pixels = [
                color_wheel(index * 256 // self.led_count + int(self._rainbow_offset))
                for index in range(self.led_count)
            ]
        return [_dim(pixel, self.brightness) for pixel in pixels]

    def _zone_frame(self, look) -> list[tuple[int, int, int]]:
        """Each pot's stretch of strip lit its own way.

        look(zone) gives (color, brightness %), or None to leave that zone
        dark. LEDs outside every zone stay dark. Neither the strip-wide color
        nor the strip-wide brightness is applied on top: until this was split
        out, schedule mode lit every pot in the color last picked for manual.
        """
        pixels = [(0, 0, 0)] * self.led_count
        for zone in self._zones:
            chosen = look(zone)
            if chosen is None:
                continue
            color = _dim(*chosen)
            for index in range(max(zone.start, 0), min(zone.end, self.led_count - 1) + 1):
                pixels[index] = color
        return pixels

    def set_plant_segments(self, zones: list[Zone]) -> None:
        """Each pot's stretch of strip, and how schedule and manual light it."""
        zones = list(zones)
        if zones != self._zones:
            self._zones = zones
            self._wake.set()

    def set_manual_scope(self, scope: str) -> dict[str, object]:
        normalized = str(scope).strip().lower()
        if normalized not in VALID_MANUAL_SCOPES:
            raise ValueError(f"Manual lighting covers all zones or each zone separately, not {scope!r}")
        self.manual_scope = normalized
        self._wake.set()
        return {"status": "ok", "manual_scope": normalized}

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

    def set_rainbow_speed(self, speed: int) -> dict[str, object]:
        self.rainbow_speed = clamp_rainbow_speed(speed)
        # Wakes a paused rainbow's idle wait, so it starts moving at once.
        self._wake.set()
        cycle = rainbow_cycle_seconds(self.rainbow_speed)
        return {
            "status": "ok",
            "rainbow_speed": self.rainbow_speed,
            "rainbow_cycle_seconds": round(cycle, 1) if cycle is not None else None,
        }

    def set_color_order(self, order: str) -> dict[str, object]:
        normalized = str(order).strip().upper()
        if normalized not in VALID_COLOR_ORDERS:
            raise ValueError(f"Unsupported LED color order: {order}")
        self.strip.color_order = normalized
        # Only the wire encoding changes, not the pixel values, so the
        # unchanged-frame check would otherwise skip sending the new order.
        self._last_frame = None
        self._wake.set()
        return {"status": "ok", "color_order": normalized}

    def _count_for(self, chip: str) -> int:
        return self._fixed_count or pixel_count(chip)

    def set_chip(self, chip: str) -> dict[str, object]:
        spec = self.strip.set_chip(chip)
        self.led_count = self._count_for(self.strip.chip)
        # Timing and channel order both change, and neither alters the pixel
        # values, so the unchanged-frame check would skip sending the new one.
        self._last_frame = None
        self._wake.set()
        return {
            "status": "ok",
            "chip": self.strip.chip,
            "color_order": self.strip.color_order,
            "description": spec.description,
            "led_count": self.led_count,
        }

    def status(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "color": self.color,
            "brightness": self.brightness,
            "rainbow_speed": self.rainbow_speed,
            "manual_scope": self.manual_scope,
            "led_count": self.led_count,
            # True when LED_COUNT in .env sets the count rather than the chip.
            "led_count_fixed": self._fixed_count is not None,
            "chip": self.strip.chip,
            "chip_options": [
                {"name": name, "description": spec.description, "pixels": self._count_for(name)}
                for name, spec in CHIPS.items()
            ],
            "color_order": self.strip.color_order,
            "color_order_options": list(VALID_COLOR_ORDERS),
            # Whether frames can be sent, not whether a strip is listening: the
            # data line is write-only, so an attached strip is not detectable.
            "spi_ready": self.strip.available,
            "error": self.strip.error,
        }
