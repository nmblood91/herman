"""The camera, as a single shared MJPEG source.

The camera is a USB (UVC) webcam, which Linux exposes through V4L2 as
/dev/video*. Capture goes through ffmpeg as a subprocess. A camera that
compresses to MJPEG on board -- the kind to buy -- has its frames copied
through untouched, so the Pi does no image work at all; one that only gives
raw video is compressed by ffmpeg instead, which costs real CPU.

One process holds the camera and only one can -- a second open fails -- so this
is a single capture whose latest frame is handed to every viewer, rather than a
capture per viewer. It starts when somebody watches and stops shortly after the
last one leaves, which is the difference between the camera costing memory and
a sensor's worth of heat only while someone is looking and costing it always.

The camera is an optional add-on, so nothing here assumes it exists: with no
capture tool installed every call answers "not fitted" rather than raising.
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import shutil
import subprocess
import threading
import time
from collections import deque
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# JPEG start- and end-of-image markers. Inside entropy-coded scan data every
# 0xFF byte is stuffed with a following 0x00, so an EOI cannot occur there --
# which is what makes scanning for these a sound way to find frame boundaries.
SOI = b"\xff\xd8"
EOI = b"\xff\xd9"

CAPTURE_BINARY = "ffmpeg"

# Where udev lists USB cameras by name. A UVC camera usually registers two
# nodes: index0 delivers the picture and index1 only metadata, so index0 is the
# one to open. Named rather than /dev/video0, whose number depends on what else
# was plugged in first.
USB_CAMERA_GLOB = "/dev/v4l/by-id/*-video-index0"

# Read in chunks rather than per frame: a 640x480 JPEG is tens of kilobytes and
# arrives across several pipe reads.
READ_CHUNK = 65536

# How long a viewer waits for a new frame before concluding the capture has
# stalled and ending the response. Generous next to a 10 fps stream, so only a
# real stall trips it.
FRAME_WAIT_SECONDS = 5.0

# A USB camera takes a second or two to negotiate its mode and settle its
# exposure, so the wait for frame one is longer than the wait for frame two.
START_WAIT_SECONDS = 10.0

# Keep the capture alive this long after the last viewer leaves. A page refresh
# or a tab switch and back would otherwise pay the startup above again.
IDLE_LINGER_SECONDS = 15.0

STOP_TIMEOUT_SECONDS = 5.0

# If this much arrives with no frame boundary in it, whatever is on the pipe is
# not MJPEG and the buffer must not grow until the Pi runs out of memory.
MAX_BUFFER_BYTES = 8 * 1024 * 1024

# Multipart boundary for the MJPEG response. Any token works as long as it
# cannot appear in JPEG data; this one is announced in the Content-Type header
# and repeated before every frame.
BOUNDARY = "hermanframe"
MJPEG_CONTENT_TYPE = f"multipart/x-mixed-replace; boundary={BOUNDARY}"


def take_frames(buffer: bytearray) -> list[bytes]:
    """Pull every complete JPEG out of `buffer`, leaving the partial tail.

    Frames arrive back to back on the pipe, and a single read can carry several
    of them or half of one. Mutates the buffer so the caller keeps only what
    has not been framed yet.
    """
    frames: list[bytes] = []
    while True:
        start = buffer.find(SOI)
        if start < 0:
            # Nothing here can begin a frame, so none of it is worth keeping --
            # except the last byte, which may be the first half of a start
            # marker whose second half is still in the pipe. Dropping that too
            # would corrupt the next frame.
            del buffer[: max(len(buffer) - (len(SOI) - 1), 0)]
            break
        end = buffer.find(EOI, start + len(SOI))
        if end < 0:
            # Drop anything ahead of the start marker: it is the tail of a
            # frame already emitted, or leading noise, and keeping it would
            # make every later scan walk it again.
            del buffer[:start]
            break
        stop = end + len(EOI)
        frames.append(bytes(buffer[start:stop]))
        del buffer[:stop]
    return frames


def find_usb_camera() -> str | None:
    """The first USB camera's picture node, or None if none is plugged in."""
    found = sorted(glob.glob(USB_CAMERA_GLOB))
    if found:
        return found[0]
    # Some cameras do not register under by-id. video0 is then the best guess,
    # and nothing else in this build claims it.
    return "/dev/video0" if os.path.exists("/dev/video0") else None


class CameraStream:
    """A USB camera capture, started on demand, broadcast to every viewer."""

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        fps: int = 10,
        quality: int = 70,
        device: str = "",
        input_format: str = "mjpeg",
        capture_command: list[str] | None = None,
    ) -> None:
        self.width = width
        self.height = height
        self.fps = fps
        self.quality = quality
        # "" finds the camera when the capture starts, so one plugged in after
        # the service came up is picked up without a restart.
        self.device = device
        # What to ask the camera for. "mjpeg" is passed through as it is;
        # anything else (yuyv422, say) is compressed to JPEG by ffmpeg.
        self.input_format = input_format

        # Injectable so the tests can exercise the pipe, the frame splitting
        # and the start/stop lifecycle against a stand-in process, with no
        # camera and no Pi.
        self._command = capture_command
        # Resolved once. A capture tool installed while the service is running
        # needs a restart to be noticed, the same as every other dependency.
        self._binary = None if capture_command else self._find_binary()

        # Guards every field below, and carries the new-frame signal.
        self._frames = threading.Condition()
        self._frame: bytes | None = None
        self._seq = 0
        self._viewers = 0
        self._process: subprocess.Popen[bytes] | None = None
        self._stopping = False
        self._idle_timer: threading.Timer | None = None
        self._stderr_tail: deque[str] = deque(maxlen=12)
        self._error: str | None = None

    # --- what the UI asks ---

    @property
    def fitted(self) -> bool:
        if self._command is not None:
            return True
        return self._binary is not None and self._device() is not None

    def _device(self) -> str | None:
        if self.device:
            return self.device if os.path.exists(self.device) else None
        return find_usb_camera()

    def status(self) -> dict[str, object]:
        with self._frames:
            return {
                "fitted": self.fitted,
                "streaming": self._process is not None and self._process.poll() is None,
                "viewers": self._viewers,
                "frames": self._seq,
                "width": self.width,
                "height": self.height,
                "fps": self.fps,
                "device": self._device() if self._command is None else None,
                "error": self._error,
            }

    # --- viewers ---

    @contextmanager
    def viewer(self) -> Iterator[None]:
        """Hold the capture open for as long as somebody is watching."""
        self._attach()
        try:
            yield
        finally:
            self._detach()

    def _attach(self) -> None:
        with self._frames:
            self._viewers += 1
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None
            self._start()

    def _detach(self) -> None:
        with self._frames:
            self._viewers = max(self._viewers - 1, 0)
            if self._viewers or self._process is None:
                return
            timer = threading.Timer(IDLE_LINGER_SECONDS, self._stop_if_idle)
            timer.daemon = True
            self._idle_timer = timer
            timer.start()

    def next_frame(
        self, after: int = 0, timeout: float = FRAME_WAIT_SECONDS
    ) -> tuple[int, bytes] | None:
        """Block until a frame newer than `after` exists. None if none arrives.

        A viewer joining a capture that is already running gets the current
        frame immediately rather than waiting for the next one, so the picture
        appears as soon as the tab opens.
        """
        deadline = time.monotonic() + timeout
        with self._frames:
            while self._frame is None or self._seq <= after:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._frames.wait(remaining)
            return self._seq, self._frame

    def snapshot(self, timeout: float = START_WAIT_SECONDS) -> bytes | None:
        """One frame, starting the capture if it is not already running."""
        with self.viewer():
            frame = self.next_frame(0, timeout=timeout)
        return frame[1] if frame else None

    # --- the capture process ---

    def _find_binary(self) -> str | None:
        return shutil.which(CAPTURE_BINARY)

    def _capture_command(self) -> list[str]:
        if self._command is not None:
            return list(self._command)
        device = self._device()
        if self.input_format == "mjpeg":
            # The camera's own JPEGs, copied through: no decoding, no
            # re-encoding, and the quality setting does not apply.
            output = ["-c:v", "copy"]
        else:
            # ffmpeg's JPEG quality runs 2 (best) to 31 (worst), the other way
            # round from the 1-100 everyone else uses.
            qscale = round(2 + (100 - self.quality) * 29 / 100)
            output = ["-c:v", "mjpeg", "-q:v", str(min(max(qscale, 2), 31))]
        return [
            str(self._binary),
            "-hide_banner",
            "-loglevel", "error",
            # Hand frames on as they arrive rather than buffering a few, which
            # is what keeps the picture from lagging behind the plant.
            "-fflags", "nobuffer",
            "-f", "v4l2",
            "-input_format", self.input_format,
            "-video_size", f"{self.width}x{self.height}",
            # No -framerate: many UVC cameras offer only 30 fps, and asking
            # for 10 is refused or quietly ignored. The camera runs at its own
            # rate and _read_frames passes on only every frame self.fps needs.
            "-i", str(device),
            *output,
            "-f", "mjpeg",
            # Push each frame down the pipe as soon as it is written. Without
            # it the picture arrives in batches.
            "-flush_packets", "1",
            "-",
        ]

    def _start(self) -> None:
        """Start the capture. Caller holds the condition."""
        if self._command is None and self._binary is None:
            self._error = (
                "ffmpeg is not installed, so the camera cannot be read. Re-run "
                "the installer with the camera plugged in, which installs it."
            )
            return
        if not self.fitted:
            self._error = (
                "No USB camera found. Check it is plugged into the Pi, then "
                "reload this page."
            )
            return
        if self._process is not None and self._process.poll() is None:
            return

        self._error = None
        self._stopping = False
        self._stderr_tail.clear()
        command = self._capture_command()
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                # Unbuffered, so a read returns the bytes that have arrived
                # rather than blocking until it has a full buffer's worth.
                bufsize=0,
            )
        except OSError as exc:
            self._error = f"Could not start the capture: {exc}"
            logger.error("Camera capture would not start: %s", exc)
            return

        self._process = process
        self._frame = None
        for target in (self._read_frames, self._drain_stderr):
            thread = threading.Thread(target=target, args=(process,), daemon=True)
            thread.start()
        logger.info("Camera capture started")

    def stop(self) -> None:
        """Release the camera now, whoever is watching. Called at shutdown."""
        with self._frames:
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None
            process = self._give_up_process()
        self._reap(process)

    def _stop_if_idle(self) -> None:
        with self._frames:
            self._idle_timer = None
            if self._viewers:
                return
            process = self._give_up_process()
        self._reap(process)

    def _give_up_process(self) -> subprocess.Popen[bytes] | None:
        """Stop treating the current process as ours. Caller holds the lock."""
        process, self._process = self._process, None
        if process is None:
            return None
        self._stopping = True
        self._frame = None
        # Wake every viewer so they end their response rather than sitting out
        # the frame timeout on a capture that is deliberately gone.
        self._frames.notify_all()
        return process

    def _reap(self, process: subprocess.Popen[bytes] | None) -> None:
        """Wait for the process to exit, without holding the lock.

        Terminating is not releasing: until the process is reaped it still owns
        the camera, so the next start -- or anything else on the Pi that wants
        the camera -- would be refused.
        """
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            logger.warning("Camera capture ignored terminate; killing it")
            process.kill()
            try:
                process.wait(timeout=STOP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                logger.error("Camera capture will not die; the camera may stay busy")
        logger.info("Camera capture stopped")

    def _read_frames(self, process: subprocess.Popen[bytes]) -> None:
        buffer = bytearray()
        stdout = process.stdout
        if stdout is None:
            return
        # Frames closer together than this are dropped, so a camera running
        # at 30 fps reaches viewers at self.fps. Dropping a copied JPEG costs
        # nothing; slowing ffmpeg's output instead would mean re-encoding.
        # A little under the full gap, so jitter in arrival does not drop a
        # frame that was due.
        gap = 0.9 / self.fps if self.fps > 0 else 0.0
        last = float("-inf")
        try:
            while True:
                chunk = stdout.read(READ_CHUNK)
                if not chunk:
                    break
                buffer += chunk
                for frame in take_frames(buffer):
                    now = time.monotonic()
                    if now - last < gap:
                        continue
                    last = now
                    self._publish(frame)
                if len(buffer) > MAX_BUFFER_BYTES:
                    logger.warning(
                        "Camera produced %d bytes with no JPEG in them; discarding",
                        len(buffer),
                    )
                    del buffer[:]
        except OSError as exc:
            logger.warning("Camera read failed: %s", exc)
        finally:
            try:
                stdout.close()
            except OSError:
                pass
            self._capture_ended(process)

    def _drain_stderr(self, process: subprocess.Popen[bytes]) -> None:
        """Keep the last few lines, and keep the pipe from filling.

        ffmpeg runs at -loglevel error, but a failing camera can still write a
        line per frame. Left unread the pipe fills and the capture blocks trying
        to write to it, which looks exactly like a camera that has stopped
        producing frames.
        """
        stderr = process.stderr
        if stderr is None:
            return
        try:
            for line in stderr:
                text = line.decode("utf-8", "replace").strip()
                if text:
                    with self._frames:
                        self._stderr_tail.append(text)
        except OSError:
            pass
        finally:
            try:
                stderr.close()
            except OSError:
                pass

    def _publish(self, frame: bytes) -> None:
        with self._frames:
            self._frame = frame
            self._seq += 1
            self._frames.notify_all()

    def _capture_ended(self, process: subprocess.Popen[bytes]) -> None:
        code = process.poll()
        with self._frames:
            if self._process is not process:
                # Already replaced, or deliberately stopped. Its exit is
                # expected and says nothing about the camera.
                return
            self._process = None
            self._frame = None
            if not self._stopping:
                detail = "; ".join(self._stderr_tail) or f"exit status {code}"
                self._error = f"The camera capture stopped on its own: {detail}"
                logger.error("Camera capture exited unexpectedly: %s", detail)
            self._frames.notify_all()


async def mjpeg_stream(camera: CameraStream) -> AsyncIterator[bytes]:
    """The camera as one never-ending multipart response.

    Each frame is a part, and the browser paints each part over the last, which
    is why an <img> tag plays this with no player and no WebSocket.

    The wait for a frame is a blocking condition wait, so it goes to a thread:
    awaiting it on the event loop would stall every other request for as long
    as a frame takes. A thread is held only between frames, never for the life
    of the stream, which is what handing Starlette a sync generator would have
    done instead.
    """
    with camera.viewer():
        seq = 0
        timeout = START_WAIT_SECONDS
        while True:
            frame = await asyncio.to_thread(camera.next_frame, seq, timeout)
            if frame is None:
                # The capture stalled or was stopped. End the response rather
                # than hold a connection open on a dead camera; the UI offers a
                # reconnect, and reconnecting starts the capture again.
                return
            seq, payload = frame
            timeout = FRAME_WAIT_SECONDS
            yield (
                f"--{BOUNDARY}\r\n"
                f"Content-Type: image/jpeg\r\n"
                f"Content-Length: {len(payload)}\r\n\r\n"
            ).encode("ascii") + payload + b"\r\n"
