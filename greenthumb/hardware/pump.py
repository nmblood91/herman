from __future__ import annotations

import logging
from typing import Any

from greenthumb.hardware.klipper_client import KlipperClient

logger = logging.getLogger(__name__)

# Klipper does not reply until the dwell finishes, so the wait has to outlast the
# dose itself with room for the board to answer.
RESPONSE_MARGIN_SECONDS = 30.0


class PumpController:
    """Drives the pump through Klipper's output_pin on the HB MOSFET."""

    def __init__(
        self,
        klipper: KlipperClient,
        pin_name: str = "pump",
        flow_ml_per_second: float = 1.67,
    ) -> None:
        self.klipper = klipper
        self.pin_name = pin_name
        self.flow_ml_per_second = max(flow_ml_per_second, 0.01)
        self.is_running = False

    def start(self) -> dict[str, Any]:
        result = self._set_pin(1)
        self.is_running = bool(result.get("ok"))
        return result

    def stop(self) -> dict[str, Any]:
        result = self._set_pin(0)
        self.is_running = False
        return result

    def deliver_ml(self, volume_ml: int = 100) -> dict[str, Any]:
        duration_seconds = max(volume_ml / self.flow_ml_per_second, 0.1)
        # One script so the dwell and the switch-off are queued together on the
        # MCU; splitting them would let a dropped connection strand the pump on.
        script = (
            f"SET_PIN PIN={self.pin_name} VALUE=1\n"
            f"G4 P{int(duration_seconds * 1000)}\n"
            f"SET_PIN PIN={self.pin_name} VALUE=0"
        )

        self.is_running = True
        try:
            result = self.klipper.send_gcode(
                script, timeout=duration_seconds + RESPONSE_MARGIN_SECONDS
            )
        finally:
            # A timeout or transport error can return with the pin still high,
            # so command it off regardless of how the script ended.
            self.stop()

        if not result.get("ok"):
            logger.error("Pump failed to deliver %d mL: %s", volume_ml, result.get("error"))
            return {"status": "error", "volume_ml": volume_ml, "error": result.get("error")}

        return {
            "status": "ok",
            "volume_ml": volume_ml,
            "duration_seconds": round(duration_seconds, 2),
        }

    def _set_pin(self, value: int) -> dict[str, Any]:
        return self.klipper.send_gcode(f"SET_PIN PIN={self.pin_name} VALUE={value}")
