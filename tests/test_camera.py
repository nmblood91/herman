"""The camera: frame boundaries, and the one capture everybody shares.

Two things carry real risk here and neither is the picture. Splitting a pipe of
concatenated JPEGs into frames has to survive arbitrary chunk boundaries, and
the shared capture has to start when someone watches, stop when nobody does,
and never leave a process holding the camera -- because until it is reaped the
next start is refused.

Runs with no camera and no Pi: the capture command is injected, so the pipe,
the reader thread and the viewer counting are all exercised for real against a
stand-in process.
"""

import subprocess
import sys
import threading
import time

from greenthumb.hardware import camera as cam
from greenthumb.hardware.camera import CameraStream, take_frames

# A JPEG as far as the splitter is concerned: starts FFD8, ends FFD9.
def jpeg(body: bytes = b"body") -> bytes:
    return cam.SOI + body + cam.EOI


# --- frame boundaries ---

buffer = bytearray(jpeg(b"one") + jpeg(b"two") + jpeg(b"three"))
frames = take_frames(buffer)
assert frames == [jpeg(b"one"), jpeg(b"two"), jpeg(b"three")], frames
assert buffer == bytearray(), f"complete frames left residue: {bytes(buffer)!r}"
print("ok: several frames in one read all come out, and nothing is left behind")

# The common case: a read lands mid-frame. The partial tail must be kept, or
# every frame straddling a chunk boundary is lost.
buffer = bytearray(jpeg(b"whole") + cam.SOI + b"half")
frames = take_frames(buffer)
assert frames == [jpeg(b"whole")], frames
buffer += b"-rest" + cam.EOI
assert take_frames(buffer) == [jpeg(b"half-rest")], "a frame split across reads was lost"
print("ok: a frame split across two reads is rejoined rather than dropped")

# rpicam-vid writes nothing before the first frame, but a restart or a garbled
# first read can leave bytes with no start marker in front of them.
buffer = bytearray(b"\x00\x01noise" + jpeg(b"real"))
assert take_frames(buffer) == [jpeg(b"real")], "leading noise was not skipped"
print("ok: bytes before the first start marker are skipped")

# Junk with no boundary in it must not be kept forever -- that is the leak.
buffer = bytearray(b"\x00" * 4096)
assert take_frames(buffer) == []
assert len(buffer) <= 1, f"junk with no start marker was retained: {len(buffer)} bytes"
print("ok: input with no frame in it is discarded, not accumulated")

# The byte it is allowed to keep is why: a start marker can land with one half
# in each read, and discarding the first half would corrupt the frame.
buffer = bytearray(b"junk" + cam.SOI[:1])
assert take_frames(buffer) == []
buffer += cam.SOI[1:] + b"split" + cam.EOI
assert take_frames(buffer) == [jpeg(b"split")], "a start marker split across reads was lost"
print("ok: a start marker split across two reads is still found")

# A start marker with no end yet is a partial frame and must survive.
buffer = bytearray(cam.SOI + b"still arriving")
assert take_frames(buffer) == []
assert bytes(buffer) == cam.SOI + b"still arriving", bytes(buffer)
print("ok: an unterminated frame is held rather than thrown away")


# --- no camera fitted ---

absent = CameraStream()
absent._binary = None
absent._command = None
assert absent.fitted is False
status = absent.status()
assert status["fitted"] is False, status
assert status["streaming"] is False, status
print("ok: with no capture tool the status answers plainly instead of raising")

# Asking an absent camera to stream must not hang the request.
started = time.monotonic()
assert absent.snapshot(timeout=0.3) is None
assert time.monotonic() - started < 3.0, "a missing camera blocked for the full timeout"
assert "ribbon" in (absent.status()["error"] or ""), absent.status()
print("ok: a missing camera fails fast and says what to check")

# Stopping something that never started is what shutdown does on a base unit.
absent.stop()
print("ok: stopping a camera that never ran is harmless")


# --- a timeout is a timeout ---

idle = CameraStream(capture_command=[sys.executable, "-c", "import time; time.sleep(30)"])
started = time.monotonic()
assert idle.next_frame(0, timeout=0.4) is None, "claimed a frame that never arrived"
elapsed = time.monotonic() - started
assert 0.3 < elapsed < 3.0, f"waited {elapsed:.2f}s for a 0.4s timeout"
print("ok: waiting for a frame gives up on time rather than blocking forever")


# --- the real lifecycle, against a stand-in capture ---

# Writes two frames, then holds the pipe open like a real capture would.
EMITTER = (
    "import sys, time\n"
    "sys.stdout.buffer.write(b'\\xff\\xd8first\\xff\\xd9')\n"
    "sys.stdout.buffer.flush()\n"
    "time.sleep(0.2)\n"
    "sys.stdout.buffer.write(b'\\xff\\xd8second\\xff\\xd9')\n"
    "sys.stdout.buffer.flush()\n"
    "time.sleep(30)\n"
)

cam.IDLE_LINGER_SECONDS = 0.3

live = CameraStream(capture_command=[sys.executable, "-c", EMITTER])
assert live.fitted is True, "an injected command should count as fitted"

with live.viewer():
    first = live.next_frame(0, timeout=10.0)
    assert first is not None, "no frame arrived from the capture"
    seq, payload = first
    assert payload == jpeg(b"first"), payload
    assert live.status()["streaming"] is True, live.status()
    process = live._process
    assert process is not None

    # A second viewer must share the capture rather than start another: only
    # one process can hold the camera.
    with live.viewer():
        assert live._process is process, "a second viewer started a second capture"
        assert live.status()["viewers"] == 2, live.status()

    following = live.next_frame(seq, timeout=10.0)
    assert following is not None, "the stream stopped after one frame"
    assert following[1] == jpeg(b"second"), following[1]
    assert following[0] > seq, "the sequence number did not advance"

print("ok: a capture starts on the first viewer and both frames arrive in order")
print("ok: a second viewer shares the one capture instead of opening another")

# Leaving must release the camera. Terminating is not enough -- an unreaped
# process still owns it, so poll() has to report an exit.
deadline = time.monotonic() + 10.0
while process.poll() is None and time.monotonic() < deadline:
    time.sleep(0.05)
assert process.poll() is not None, "the capture process was left holding the camera"
assert live._process is None, live._process
assert live.status()["streaming"] is False, live.status()
print("ok: the last viewer leaving stops the capture and reaps the process")

# And it comes back. A tab switched away and back must not be a dead camera.
with live.viewer():
    again = live.next_frame(0, timeout=10.0)
    assert again is not None, "the capture did not restart for a new viewer"
    restarted = live._process
    assert restarted is not None and restarted is not process
print("ok: a later viewer starts a fresh capture")

# A deliberate stop is not a fault, so it must not leave an error behind for
# the UI to report.
live.stop()
assert live.status()["error"] is None, live.status()
print("ok: stopping on purpose is not reported as a camera failure")


# --- the capture dying on its own is a fault, and is reported ---

dies = CameraStream(
    capture_command=[
        sys.executable,
        "-c",
        "import sys; sys.stderr.write('no cameras available\\n'); sys.exit(1)",
    ]
)
with dies.viewer():
    assert dies.next_frame(0, timeout=5.0) is None
deadline = time.monotonic() + 5.0
while dies.status()["error"] is None and time.monotonic() < deadline:
    time.sleep(0.05)
error = dies.status()["error"] or ""
assert "no cameras available" in error, f"the reason was lost: {error!r}"
print("ok: a capture that exits on its own is reported with what it said")


# --- the multipart framing ---

import asyncio  # noqa: E402  -- only this section needs it


async def read_parts() -> list[bytes]:
    source = CameraStream(capture_command=[sys.executable, "-c", EMITTER])
    chunks = []
    async for chunk in cam.mjpeg_stream(source):
        chunks.append(chunk)
        if len(chunks) == 2:
            break
    source.stop()
    return chunks


parts = asyncio.run(read_parts())
assert len(parts) == 2, len(parts)
for part in parts:
    assert part.startswith(f"--{cam.BOUNDARY}\r\n".encode()), part[:40]
    assert b"Content-Type: image/jpeg" in part, part[:80]
    assert part.endswith(cam.EOI + b"\r\n"), part[-12:]
# Content-Length has to match the frame, or the browser reads into the next part.
header, _, body = parts[0].partition(b"\r\n\r\n")
declared = int(header.split(b"Content-Length: ")[1].split(b"\r\n")[0])
assert declared == len(body) - 2, f"declared {declared}, sent {len(body) - 2}"
print("ok: each frame is a complete multipart part with an honest Content-Length")


# --- it does not wedge the event loop ---

# The stream awaits its blocking wait in a thread. If that ever becomes a plain
# blocking call, nothing else on the loop runs while a frame is pending, which
# would freeze the whole API rather than just the picture.
#
# Counting ticks at the moment the stream ends is the point: a blocked loop
# still finishes everything *afterwards*, so a total taken at the end cannot
# tell the two apart. Only how much ran *during* the wait can.
cam.START_WAIT_SECONDS = 1.0


async def ticks_during_a_pending_frame() -> int:
    stalled = CameraStream(capture_command=[sys.executable, "-c", "import time; time.sleep(30)"])
    ticks = 0
    observed = -1

    async def tick() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    async def drain() -> None:
        nonlocal observed
        async for _ in cam.mjpeg_stream(stalled):
            break
        observed = ticks

    ticker = asyncio.create_task(tick())
    try:
        await asyncio.wait_for(drain(), timeout=30.0)
    finally:
        ticker.cancel()
        stalled.stop()
    return observed


concurrent_ticks = asyncio.run(ticks_during_a_pending_frame())
assert concurrent_ticks > 10, (
    f"only {concurrent_ticks} other tasks ran while a frame was pending; "
    "the event loop was blocked"
)
print(f"ok: the loop served {concurrent_ticks} other turns while a frame was pending")

assert threading.active_count() < 30, f"{threading.active_count()} threads still running"

print("\nall camera checks passed")
