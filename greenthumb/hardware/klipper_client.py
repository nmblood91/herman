from __future__ import annotations

import json
import logging
import socket
from typing import Any

logger = logging.getLogger(__name__)

QUERY_TIMEOUT = 5.0
# gcode/script does not reply until the move completes, so anything that
# physically moves the gantry needs room for the full travel time.
MOTION_TIMEOUT = 180.0


class KlipperClient:
    """Communicate with Klipper via Unix socket."""

    def __init__(self, socket_path: str = "/run/klipper/uds") -> None:
        self.socket_path = socket_path

    def status(self) -> dict[str, Any]:
        response = self._send_command(
            "objects/query",
            # axis_maximum so the rest of the app can ask Klipper how far the
            # rail goes instead of keeping its own copy of the number. The
            # limit lives in printer.cfg as position_max, and a second copy in
            # .env drifts the moment the rail is measured properly.
            {"objects": {"toolhead": ["position", "homed_axes", "axis_maximum"]}},
        )
        if not response.get("ok"):
            return {"ok": False, "error": response.get("error"), "position": 0.0, "homed": False}

        toolhead = response.get("result", {}).get("status", {}).get("toolhead", {})
        position = toolhead.get("position") or [0.0]
        maximum = toolhead.get("axis_maximum") or []
        return {
            "ok": True,
            "position": round(float(position[0]), 1),
            "homed": "x" in (toolhead.get("homed_axes") or ""),
            # None when Klipper did not report it, so callers can tell "not
            # known" from a real limit of zero.
            "max_x": round(float(maximum[0]), 1) if maximum else None,
        }

    def water_supply_present(self) -> bool | None:
        """True if the outlet tube reads wet, None if the sensor cannot be read.

        The Klipper object is still named water_supply, which printer.cfg and
        this query have to agree on; the sensor itself moved to the outlet.
        """
        response = self._send_command(
            "objects/query",
            {"objects": {"filament_switch_sensor water_supply": ["filament_detected"]}},
        )
        if not response.get("ok"):
            return None

        sensor = response.get("result", {}).get("status", {}).get(
            "filament_switch_sensor water_supply"
        )
        # Absent rather than false when printer.cfg has no such section, which
        # must stay distinguishable from the sensor reporting a dry line.
        if not sensor or "filament_detected" not in sensor:
            return None
        return bool(sensor["filament_detected"])

    def endstop_state(self) -> dict[str, Any]:
        """Whether the home switch reads triggered right now.

        Two round trips, and the first one is the point. `last_query` is a
        cache that Klipper fills when a query runs, so straight after a Klipper
        restart it is empty and reading it alone answers nothing -- which is
        exactly when someone is most likely to be checking a switch, having
        just changed the config. Sending QUERY_ENDSTOPS first forces the MCU
        query, and then the cache has something in it. Its gcode output arrives
        as an async notification that _send_command discards; only the side
        effect is wanted.

        Both steps wait for any move in flight to finish, so this must not be
        called while the gantry is moving.

        Only x is reported. stepper_y and stepper_z are placeholders pointed at
        unused headers, and an unconnected pin holding a pull-up reads high,
        which is the triggered reading: they say "triggered" always and mean
        nothing by it. Returning them would invite reading a fault into them.
        """
        refresh = self.send_gcode("QUERY_ENDSTOPS")
        if not refresh.get("ok"):
            return {"ok": False, "error": refresh.get("error")}

        response = self._send_command("query_endstops/status")
        if not response.get("ok"):
            return {"ok": False, "error": response.get("error")}

        query = response.get("result", {}).get("last_query", {})
        # Klipper names an endstop after its stepper with the prefix stripped,
        # so x is expected -- but accept the unstripped spelling too rather
        # than failing on a naming detail of someone else's code.
        for key in ("x", "stepper_x"):
            if key in query:
                return {"ok": True, "triggered": bool(query[key])}

        # Say what did come back. The previous message named only what was
        # missing, which is the half that cannot be acted on.
        reported = ", ".join(sorted(query)) if query else "nothing at all"
        return {
            "ok": False,
            "error": f"Klipper reported no x endstop. It reported: {reported}",
        }

    def home_gantry(self) -> dict[str, Any]:
        return self.send_gcode("G28 X", timeout=MOTION_TIMEOUT)

    def move_gantry_relative(self, distance_mm: float) -> dict[str, Any]:
        return self.send_gcode(f"G91\nG1 X{distance_mm} F6000\nG90", timeout=MOTION_TIMEOUT)

    def move_gantry_absolute(self, position_mm: float) -> dict[str, Any]:
        return self.send_gcode(f"G90\nG1 X{position_mm} F6000", timeout=MOTION_TIMEOUT)

    def send_gcode(self, gcode: str, timeout: float = QUERY_TIMEOUT) -> dict[str, Any]:
        logger.debug("Sending gcode: %r", gcode)
        return self._send_command("gcode/script", {"script": gcode}, timeout=timeout)

    def _send_command(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = QUERY_TIMEOUT,
    ) -> dict[str, Any]:
        request_id = 1
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(self.socket_path)
            request = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
                "id": request_id,
            }
            sock.sendall((json.dumps(request) + "\x03").encode())

            # Klipper interleaves async notifications with replies on the same
            # socket, so keep reading until the message carrying our id arrives.
            buffer = b""
            try:
                while True:
                    data = sock.recv(4096)
                    if not data:
                        return {"ok": False, "error": "Klipper closed the connection"}
                    buffer += data
                    while b"\x03" in buffer:
                        raw, buffer = buffer.split(b"\x03", 1)
                        message = json.loads(raw.decode())
                        if message.get("id") != request_id:
                            continue
                        if "error" in message:
                            detail = message["error"]
                            text = (
                                detail.get("message", str(detail))
                                if isinstance(detail, dict)
                                else str(detail)
                            )
                            logger.warning("Klipper rejected %s: %s", method, text)
                            return {"ok": False, "error": text}
                        return {"ok": True, "result": message.get("result", {})}
            except socket.timeout:
                logger.warning("Klipper %s timed out after %ss", method, timeout)
                return {"ok": False, "error": f"Klipper did not respond within {timeout:.0f}s"}
            finally:
                sock.close()
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Klipper request failed: %s", exc)
            return {"ok": False, "error": str(exc)}
