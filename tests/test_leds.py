import sys, types, time
from datetime import time as dtime

sys.modules["smbus2"] = types.ModuleType("smbus2")

from greenthumb.hardware.led_strip import AddressableStrip, CHIPS, DEFAULT_CHIP, encoding_table, RESET
from greenthumb.hardware.lighting import LedController
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

# schedule mode lights only the plants that are on
led, strip = controller(count=60)
led.set_mode("schedule")
led.set_static_color((0, 255, 0))
led.set_mode("schedule")  # set_static_color flips to manual, put it back
led.set_brightness(100)
led.set_plant_segments([(0, 4, True), (5, 9, False), (10, 14, True), (15, 19, False)])
led._render()
frame = strip.frames[-1]
assert frame[0:5] == [(0, 255, 0)] * 5, frame[0:5]
assert frame[5:10] == [(0, 0, 0)] * 5, frame[5:10]
assert frame[10:15] == [(0, 255, 0)] * 5
assert frame[15:20] == [(0, 0, 0)] * 5
print("ok: schedule lights only the plants inside their window")

# segments beyond the strip must not blow up or wrap
led.set_plant_segments([(18, 99, True)])
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
