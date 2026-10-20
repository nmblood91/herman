import sys, types, time
from datetime import time as dtime

sys.modules["smbus2"] = types.ModuleType("smbus2")

from greenthumb.hardware.led_strip import AddressableStrip, CHIPS, DEFAULT_CHIP, encoding_table, RESET
from greenthumb.hardware.lighting import (
    DEFAULT_RAINBOW_SPEED,
    FASTEST_CYCLE_SECONDS,
    FRAME_INTERVAL,
    SLOWEST_CYCLE_SECONDS,
    LedController,
    Zone,
    rainbow_cycle_seconds,
)
from greenthumb.services.automation import within_window

# --- bit encoding, per chip: this is what the strip actually sees on the wire ---
# Datasheet high times, in ns: (T0H, T1H), each with +/-150 tolerance.
DATASHEET = {
    "WS2815": (300, 900),
    "GS8208": (300, 900),
    "WS2811": (250, 600),
}

for chip, spec in CHIPS.items():
    table = encoding_table(chip)
    zero_bits = f"{spec.zero:0{spec.symbol_bits}b}"
    one_bits = f"{spec.one:0{spec.symbol_bits}b}"

    for value in range(256):
        encoded = table[value]
        assert len(encoded) == spec.symbol_bits, (chip, value)
        bits = "".join(f"{b:08b}" for b in encoded)
        groups = [bits[i:i + spec.symbol_bits] for i in range(0, len(bits), spec.symbol_bits)]
        decoded = 0
        for group in groups:
            assert group in (zero_bits, one_bits), (chip, value, group)
            decoded = (decoded << 1) | (1 if group == one_bits else 0)
        assert decoded == value, (chip, value, decoded)

    bit_ns = 1e9 / spec.spi_hz
    zero_high = bit_ns * zero_bits.count("1")
    one_high = bit_ns * one_bits.count("1")
    period = bit_ns * spec.symbol_bits
    t0h, t1h = DATASHEET[chip]

    assert t0h - 150 <= zero_high <= t0h + 150, f"{chip} T0H {zero_high:.0f}ns vs {t0h}+/-150"
    assert t1h - 150 <= one_high <= t1h + 150, f"{chip} T1H {one_high:.0f}ns vs {t1h}+/-150"
    assert 1150 < period < 1350, (chip, period)
    assert len(RESET) * 8 * bit_ns > 280_000, f"{chip} reset too short"
    print(
        f"ok: {chip:8s} T0H={zero_high:3.0f}ns (spec {t0h}) "
        f"T1H={one_high:3.0f}ns (spec {t1h}) period={period:.0f}ns"
    )


# --- frame building ---
class FakeStrip:
    available = True
    error = None

    def __init__(self, order="RGB"):
        self.color_order = order
        self.frames = []

    def show(self, pixels):
        self.frames.append(list(pixels))
        return True

    def close(self):
        pass


def controller(count=60):
    strip = FakeStrip()
    return LedController(led_count=count, strip=strip), strip


led, strip = controller()
led.set_mode("off")
led._render()
assert set(strip.frames[-1]) == {(0, 0, 0)}, strip.frames[-1]
print("ok: off mode blanks every pixel")

led.set_static_color((255, 0, 0))
led.set_brightness(100)
led._render()
assert set(strip.frames[-1]) == {(255, 0, 0)}
assert led.mode == "manual", led.mode
print("ok: manual mode fills the strip and switches mode")

led.set_brightness(50)
led._render()
assert set(strip.frames[-1]) == {(127, 0, 0)}, strip.frames[-1]
print("ok: brightness scales the frame")

led.set_brightness(0)
led._render()
assert set(strip.frames[-1]) == {(0, 0, 0)}
print("ok: zero brightness goes dark without changing mode")
assert led.mode == "manual"

# identical frames must not be rewritten
led.set_brightness(100)
led._render()
before = len(strip.frames)
led._render()
led._render()
assert len(strip.frames) == before, "rewrote an unchanged frame"
print("ok: unchanged frames are not re-sent")

# rainbow spans hues and advances
led, strip = controller()
led.set_mode("rainbow")
led.set_brightness(100)
led._render()
first = strip.frames[-1]
assert len(set(first)) > 5, f"rainbow not varied: {set(first)}"
led._rainbow_offset = 40
led._render()
assert strip.frames[-1] != first, "rainbow did not advance"
print(f"ok: rainbow spans {len(set(first))} distinct colours and animates")

# The speed slider runs from a two-minute cycle to a two-second one, and the
# default keeps the speed the rainbow had before the slider existed.
assert rainbow_cycle_seconds(1) == SLOWEST_CYCLE_SECONDS
assert abs(rainbow_cycle_seconds(100) - FASTEST_CYCLE_SECONDS) < 1e-9
cycles = [rainbow_cycle_seconds(speed) for speed in range(1, 101)]
assert cycles == sorted(cycles, reverse=True), "a faster setting gave a slower rainbow"
assert 3.5 < rainbow_cycle_seconds(DEFAULT_RAINBOW_SPEED) < 5, rainbow_cycle_seconds(DEFAULT_RAINBOW_SPEED)
assert led.set_rainbow_speed(-5)["rainbow_speed"] == 0
assert led.set_rainbow_speed(250)["rainbow_speed"] == 100
for bad in (True, "fast", None):
    try:
        led.set_rainbow_speed(bad)
    except (ValueError, TypeError):
        pass
    else:
        raise AssertionError(f"accepted rainbow speed {bad!r}")
assert led.rainbow_speed == 100
print("ok: rainbow speed maps 1-100 onto a 2 min to 2 s cycle and refuses junk")

# Even the slowest setting must still move: the offset is fractional, so the
# per-frame step of about 0.07 accumulates instead of rounding to nothing.
led.set_rainbow_speed(1)
led._rainbow_offset = 0.0
frames = round(rainbow_cycle_seconds(1) / FRAME_INTERVAL)
led._advance_rainbow()
assert 0 < led._rainbow_offset < 1, led._rainbow_offset
for _ in range(frames - 1):
    led._advance_rainbow()
assert abs(led._rainbow_offset % 256) < 1e-6 or abs(led._rainbow_offset - 256) < 1e-6, led._rainbow_offset
print("ok: the slowest rainbow still advances, and takes its full two minutes a cycle")

# 0 pauses it where it is: the colours stay, and stop moving.
led.set_rainbow_speed(37)
for _ in range(10):
    led._advance_rainbow()
held = led._rainbow_offset
paused = led.set_rainbow_speed(0)
assert paused["rainbow_speed"] == 0 and paused["rainbow_cycle_seconds"] is None, paused
assert rainbow_cycle_seconds(0) is None
for _ in range(100):
    led._advance_rainbow()
assert led._rainbow_offset == held, (led._rainbow_offset, held)
led._render()
assert len(set(strip.frames[-1])) > 5, "a paused rainbow went blank instead of holding its colours"
led.set_rainbow_speed(50)
led._advance_rainbow()
assert led._rainbow_offset != held, "it did not start again from where it paused"
print("ok: speed 0 holds the rainbow still, keeps its colours, and it moves on again from there")

# schedule mode lights only the plants that are on, each in its own colour
led, strip = controller(count=60)
GREEN, RED = (0, 255, 0), (255, 0, 0)
led.set_mode("schedule")
led.set_plant_segments([
    Zone(0, 4, lit=True, brightness=100, color=GREEN),
    Zone(5, 9, lit=False, brightness=100, color=GREEN),
    Zone(10, 14, lit=True, brightness=100, color=RED),
    Zone(15, 19, lit=False, brightness=100),
])
led._render()
frame = strip.frames[-1]
assert frame[0:5] == [GREEN] * 5, frame[0:5]
assert frame[5:10] == [(0, 0, 0)] * 5, frame[5:10]
assert frame[10:15] == [RED] * 5, frame[10:15]
assert frame[15:20] == [(0, 0, 0)] * 5
print("ok: schedule lights only the plants inside their window, each in its own colour")

# The regression: schedule used to light every pot in the colour last picked
# for manual mode.
led.set_static_color((0, 0, 255))
led.set_mode("schedule")
led.set_plant_segments([Zone(0, 4, lit=True, brightness=100)])
led._render()
assert strip.frames[-1][0:5] == [(255, 255, 255)] * 5, strip.frames[-1][0:5]
print("ok: a manual colour no longer leaks into schedule, which defaults to white")

# Each plant's stretch runs at that plant's own brightness, and the strip-wide
# brightness does not scale it on top.
led.set_brightness(10)
led.set_plant_segments([
    Zone(0, 4, lit=True, brightness=100, color=GREEN),
    Zone(5, 9, lit=True, brightness=50, color=GREEN),
    Zone(10, 14, lit=False, brightness=100, color=GREEN),
    Zone(15, 19, lit=True, brightness=0, color=GREEN),
])
led._render()
frame = strip.frames[-1]
assert frame[0:5] == [GREEN] * 5, frame[0:5]
assert frame[5:10] == [(0, 127, 0)] * 5, frame[5:10]
assert frame[10:15] == [(0, 0, 0)] * 5, "an unlit plant was drawn"
assert frame[15:20] == [(0, 0, 0)] * 5, "a plant at 0% was drawn"
print("ok: in schedule mode each plant is lit at its own brightness")

# Manual, all zones: the strip-wide colour and brightness, and white at 75%
# out of the box.
led, strip = controller(count=60)
led.set_mode("manual")
assert led.manual_scope == "all"
led._render()
assert set(strip.frames[-1]) == {(191, 191, 191)}, set(strip.frames[-1])
led.set_static_color((0, 200, 0))
led.set_brightness(50)
led._render()
assert set(strip.frames[-1]) == {(0, 100, 0)}, set(strip.frames[-1])
print("ok: manual for all zones fills the strip, white at 75% by default")

# Manual, each zone separately: every pot its own colour and brightness, the
# strip-wide pair ignored, and LEDs between zones dark.
led.set_manual_scope("zones")
led.set_plant_segments([
    Zone(0, 4, manual_color=RED, manual_brightness=100),
    Zone(5, 9),
    Zone(12, 14, lit=True, color=GREEN, manual_color=(0, 0, 255), manual_brightness=0),
])
led._render()
frame = strip.frames[-1]
assert frame[0:5] == [RED] * 5, frame[0:5]
assert frame[5:10] == [(191, 191, 191)] * 5, "an untouched zone is not white at 75%"
assert frame[10:12] == [(0, 0, 0)] * 2, "LEDs between zones were lit"
assert frame[12:15] == [(0, 0, 0)] * 3, "a zone at 0% was drawn, or its schedule colour leaked in"
assert frame[15:] == [(0, 0, 0)] * 45
print("ok: manual for separate zones lights each its own way and leaves the gaps dark")

led.set_manual_scope("ALL")
assert led.manual_scope == "all"
for bad in ("some", "", None):
    try:
        led.set_manual_scope(bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"accepted manual scope {bad!r}")
print("ok: the manual scope is all or zones and nothing else")

# segments beyond the strip must not blow up or wrap
led.set_mode("schedule")
led.set_plant_segments([Zone(18, 99, lit=True)])
led._render()
assert len(strip.frames[-1]) == 60
print("ok: an over-long segment is clipped to the strip")

# colour order actually reorders the wire bytes
# This had been claimed by a comment for a while without being tested: the two
# FakeStrips that used to sit here were assigned and never used, and the
# assertion below them checks something else entirely.
class _Spi:
    def __init__(self): self.written = bytearray()
    def writebytes2(self, payload): self.written += payload


def _wire_bytes(order, pixel):
    strip = AddressableStrip.__new__(AddressableStrip)
    strip.spi = _Spi()
    strip.color_order = order
    strip.chip = DEFAULT_CHIP
    strip._table = encoding_table(DEFAULT_CHIP)
    strip.error = None
    assert strip.show([pixel]) is True
    return bytes(strip.spi.written)


# One channel at a time, so the position of the non-zero run in the payload
# says which channel went out first.
red_first = _wire_bytes("RGB", (255, 0, 0))
green_first = _wire_bytes("GRB", (255, 0, 0))
assert red_first != green_first, "RGB and GRB produced identical bytes"
# Under GRB a pure red pixel puts green (zero) on the wire first, so the two
# payloads are each other's first two channel blocks swapped.
per_channel = (len(red_first) - len(RESET)) // 3
assert red_first[:per_channel] == green_first[per_channel:per_channel * 2], (
    "swapping R and G in the order did not swap those blocks on the wire"
)
assert red_first[per_channel * 2:] == green_first[per_channel * 2:], (
    "the blue block should be unaffected by swapping R and G"
)
print("ok: colour order reorders the channel bytes on the wire")

real = AddressableStrip.__new__(AddressableStrip)
real.spi = None
assert real.show([(1, 2, 3)]) is False
print("ok: an unavailable strip reports failure instead of pretending")

# --- schedule window maths ---
assert within_window(dtime(12, 0), dtime(8, 0), dtime(20, 0)) is True
assert within_window(dtime(7, 0), dtime(8, 0), dtime(20, 0)) is False
assert within_window(dtime(20, 0), dtime(8, 0), dtime(20, 0)) is False
assert within_window(dtime(8, 0), dtime(8, 0), dtime(20, 0)) is True
print("ok: daytime window boundaries")

assert within_window(dtime(23, 0), dtime(20, 0), dtime(6, 0)) is True
assert within_window(dtime(3, 0), dtime(20, 0), dtime(6, 0)) is True
assert within_window(dtime(12, 0), dtime(20, 0), dtime(6, 0)) is False
print("ok: overnight window wraps past midnight")

# --- thread lifecycle ---
led, strip = controller()
led.set_mode("manual")
led.start()
time.sleep(0.2)
led.stop()
assert strip.frames, "render thread produced nothing"
print("ok: render thread starts, draws, and stops cleanly")

print("\nall LED checks passed")
