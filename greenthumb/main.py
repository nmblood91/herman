from __future__ import annotations

import logging

from contextlib import asynccontextmanager
from datetime import datetime, time
from typing import AsyncIterator

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Body, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from greenthumb.config import settings
from greenthumb.hardware.camera import CameraStream, MJPEG_CONTENT_TYPE, mjpeg_stream
from greenthumb.logging_setup import log_event, read_recent_logs, setup_logging
from greenthumb import system_clock, version
from greenthumb.services.automation import GreenThumbAutomation, HardwareBusyError

setup_logging()

automation = GreenThumbAutomation()

# The camera sits outside the automation service, and deliberately outside its
# hardware lock. That lock serialises the gantry, the pump and the I2C bus, and
# a watering cycle holds it for minutes -- the picture has to keep moving
# through that rather than freeze until the dose finishes. The camera is a
# separate device that nothing else here contends for.
camera = CameraStream(
    width=settings.camera_width,
    height=settings.camera_height,
    fps=settings.camera_fps,
    quality=settings.camera_jpeg_quality,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        automation.tick,
        "interval",
        seconds=settings.sensor_poll_seconds,
        next_run_time=datetime.now(),
        max_instances=1,
        coalesce=True,
    )
    # Daily rather than per tick: pruning 90 day old rows is not urgent work.
    scheduler.add_job(
        lambda: automation.history.prune(settings.history_retention_days),
        "interval",
        hours=24,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    automation.leds.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        automation.leds.stop()
        # Terminate and reap the capture, or a restart finds the camera still
        # held by a process whose parent systemd just killed.
        camera.stop()
        # The SQLite connection was being left open at shutdown. Closing it
        # flushes cleanly rather than relying on the process exiting, which
        # matters on a Pi that loses power more often than it is stopped.
        automation.history.close()


app = FastAPI(
    title=settings.app_name,
    description="Local API for Herman the Gardening Robot. Internally the greenthumb package.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(ValueError)
async def handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})


@app.exception_handler(RuntimeError)
async def handle_runtime_error(request: Request, exc: RuntimeError) -> JSONResponse:
    """Carry the reason to the browser instead of a plain-text 500.

    system_clock raises this with timedatectl's own explanation attached, and
    without a handler Starlette answers text/plain "Internal Server Error" --
    so the UI parsed JSON, found nothing, and showed a bare status code.
    """
    return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})


@app.exception_handler(HardwareBusyError)
async def handle_hardware_busy(request: Request, exc: HardwareBusyError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})


def log_motion(result: dict[str, object], action: str) -> dict[str, object]:
    if result.get("ok"):
        log_event(f"{action}: ok")
    else:
        log_event(f"{action}: failed - {result.get('error')}")
    return result


@app.get("/")
async def index() -> dict[str, str]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "api": settings.api_prefix,
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


# Endpoints that reach hardware are sync so FastAPI runs them in its threadpool;
# as coroutines their blocking socket and I2C calls would stall the event loop.
@app.get(f"{settings.api_prefix}/overview")
def get_overview() -> dict[str, object]:
    return automation.get_overview()


@app.get(f"{settings.api_prefix}/sensors")
async def read_sensors() -> list[dict[str, object]]:
    return automation.read_sensors()


@app.get(f"{settings.api_prefix}/version")
def get_version() -> dict[str, object]:
    """What is running, and whether the checkout has moved on without it."""
    return version.status()


@app.get(f"{settings.api_prefix}/system/time")
def get_system_time() -> dict[str, object]:
    return system_clock.status()


@app.post(f"{settings.api_prefix}/system/timezone")
def set_system_timezone(payload: dict[str, str] = Body(default_factory=dict)) -> dict[str, object]:
    """Point the host at a timezone, normally the one the browser reports.

    An unknown zone raises ValueError and comes back as a 400; a timedatectl
    that refuses raises RuntimeError and comes back as a 409 carrying its
    reason. Both go through app-level handlers, so both answer in the
    {"ok": false, "error": ...} shape the rest of the API uses.
    """
    name = str(payload.get("timezone", ""))
    result = system_clock.set_timezone(name)
    log_event(f"System timezone set to {result['timezone']}")
    return result


@app.get(f"{settings.api_prefix}/diagnostics/endstop")
def get_endstop_diagnostic() -> dict[str, object]:
    """Read the home switch and interpret it.

    Sync, like the other hardware routes: it takes the gantry lock and talks to
    Klipper, and answers 409 through the HardwareBusyError handler if the gantry
    is mid-move rather than waiting for it.
    """
    return automation.endstop_diagnostic()


@app.get(f"{settings.api_prefix}/watering/auto")
def get_auto_watering() -> dict[str, object]:
    return automation.watering_status()


@app.post(f"{settings.api_prefix}/watering/auto")
def set_auto_watering(payload: dict[str, object] = Body(default_factory=dict)) -> dict[str, object]:
    """Turn unattended watering on or off."""
    result = automation.set_auto_watering(bool(payload.get("enabled", False)))
    log_event(
        f"Automatic watering turned {'on' if result['auto_watering_enabled'] else 'off'}"
    )
    return result


@app.get(f"{settings.api_prefix}/dances")
def list_dances() -> dict[str, object]:
    return {**automation.idle_motion_status(), "dances": automation.dance_catalogue()}


# /dances/run/{name} rather than /dances/{name}: the latter would be matched
# by a POST to /dances/auto as well, and which one wins would depend on the
# order they happen to be registered in.
@app.post(f"{settings.api_prefix}/dances/run/{{name}}")
def run_dance(name: str) -> dict[str, object]:
    result = automation.run_dance(name)
    if result.get("ok"):
        log_event(f"Ran the {name} routine")
    else:
        log_event(f"Routine {name} did not run: {result.get('error')}", level=logging.WARNING)
    return result


@app.post(f"{settings.api_prefix}/dances/auto")
def set_idle_motion(payload: dict[str, object] = Body(default_factory=dict)) -> dict[str, object]:
    """Turn the periodic re-home and routine on or off, and set its interval."""
    minutes = payload.get("minutes")
    result = automation.set_idle_motion(
        enabled=bool(payload.get("enabled", False)),
        minutes=int(minutes) if minutes is not None else None,
    )
    log_event(
        f"Idle motion {'on' if result['enabled'] else 'off'}, every {result['minutes']} min"
    )
    return result


@app.get(f"{settings.api_prefix}/quiet")
def get_quiet() -> dict[str, object]:
    return automation.quiet_status()


@app.post(f"{settings.api_prefix}/quiet/hours")
def set_quiet_hours(payload: dict[str, object] = Body(default_factory=dict)) -> dict[str, object]:
    """Set the nightly window in which automatic watering is held back."""
    result = automation.set_quiet_hours(
        enabled=bool(payload.get("enabled", False)),
        start=payload.get("start"),
        stop=payload.get("stop"),
    )
    log_event(
        f"Quiet hours {'on' if result['quiet_hours_enabled'] else 'off'} "
        f"({result['quiet_hours_start']}-{result['quiet_hours_stop']})"
    )
    return result


@app.post(f"{settings.api_prefix}/quiet/snooze")
def snooze_watering(payload: dict[str, float] = Body(default_factory=dict)) -> dict[str, object]:
    """Hold automatic watering off for a few hours, starting now."""
    result = automation.snooze_watering(float(payload.get("hours", 1)))
    log_event(f"Automatic watering snoozed until {result['snooze_until']}")
    return result


@app.post(f"{settings.api_prefix}/quiet/resume")
def cancel_snooze() -> dict[str, object]:
    result = automation.cancel_snooze()
    log_event("Watering snooze cancelled")
    return result


@app.get(f"{settings.api_prefix}/sensors/calibration")
def get_moisture_calibration() -> dict[str, object]:
    return automation.moisture_calibration()


# Registered before the {endpoint} route below, which would otherwise match
# "reset" as an endpoint name and reject it as invalid.
@app.post(f"{settings.api_prefix}/sensors/calibration/reset")
def reset_moisture_calibration() -> dict[str, object]:
    result = automation.reset_moisture_calibration()
    log_event("Moisture calibration cleared")
    return result


@app.post(f"{settings.api_prefix}/sensors/calibration/{{endpoint}}")
def calibrate_moisture(endpoint: str, payload: dict[str, int] = Body(default_factory=dict)) -> dict[str, object]:
    """Measure the dry or wet point for every sensor.

    Deliberately synchronous. It blocks for the sampling window, the way a
    gantry move blocks for its travel, rather than introducing a job queue for
    one operation the user is standing in front of anyway.
    """
    # A bad endpoint name raises ValueError and a watering cycle in progress
    # raises HardwareBusyError; both already have app-level handlers that return
    # the {"ok": false, "error": ...} shape the rest of the API uses.
    seconds = int(payload.get("seconds", 20))
    result = automation.calibrate_moisture(endpoint, seconds)
    log_event(
        f"Moisture {endpoint} calibration: {result['stored']}/{result['total']} sensors stored"
    )
    return result


@app.get(f"{settings.api_prefix}/history")
def get_history(hours: float = 24.0) -> dict[str, object]:
    # Clamped to the retention window: asking for more only returns empty
    # leading buckets and makes the chart look broken.
    bounded = max(0.5, min(hours, settings.history_retention_days * 24))
    return automation.get_history(bounded)


@app.get(f"{settings.api_prefix}/logs")
async def get_logs(lines: int = 100) -> list[str]:
    return read_recent_logs(lines)


@app.post(f"{settings.api_prefix}/water/{{plant_id}}")
def water_plant(plant_id: str, volume_ml: int | None = None) -> dict[str, object]:
    result = automation.water_plant(plant_id, volume_ml)
    # Branching rather than logging unconditionally: a failed gantry move comes
    # back as {"status": "error"} with HTTP 200 and no volume_ml, which this
    # used to record as "watered with None mL" -- a dose that never happened,
    # written into the log the user trusts as the record of what occurred.
    if result.get("status") == "error" or result.get("ok") is False:
        log_event(
            f"Plant {plant_id} NOT watered: {result.get('error', 'unknown error')}",
            level=logging.WARNING,
        )
    else:
        log_event(f"Plant {plant_id} watered with {result.get('volume_ml')} mL")
    return result


@app.post(f"{settings.api_prefix}/pump/run")
def run_pump() -> dict[str, object]:
    result = automation.run_pump()
    # Same shape as watering above: a pump that fails to start returns
    # {"status": "error"} with HTTP 200, which logged "auto-stop in Nones".
    if result.get("status") == "error":
        log_event(
            f"Pump did not start: {result.get('error', 'unknown error')}",
            level=logging.WARNING,
        )
    else:
        log_event(f"Pump started manually (auto-stop in {result.get('max_run_seconds')}s)")
    return result


@app.post(f"{settings.api_prefix}/pump/stop")
def stop_pump() -> dict[str, object]:
    result = automation.stop_pump()
    log_event("Pump stopped manually")
    return result


@app.post(f"{settings.api_prefix}/lights/mode")
async def set_light_mode_from_body(payload: dict[str, str] = Body(default_factory=dict)) -> dict[str, object]:
    mode = str(payload.get("mode", "schedule")).strip().lower()
    result = automation.set_light_mode(mode)
    log_event(f"LED mode changed to {mode}")
    return result


@app.post(f"{settings.api_prefix}/lights/color")
async def set_light_color(payload: dict[str, int] = Body(default_factory=dict)) -> dict[str, object]:
    red = int(payload.get("r", 0))
    green = int(payload.get("g", 255))
    blue = int(payload.get("b", 128))
    color = (max(0, min(red, 255)), max(0, min(green, 255)), max(0, min(blue, 255)))
    result = automation.set_light_color(color)
    log_event(f"LED color set to {color}")
    return result


@app.post(f"{settings.api_prefix}/lights/color-order")
async def set_light_color_order(payload: dict[str, str] = Body(default_factory=dict)) -> dict[str, object]:
    # settings.led_color_order, not a literal: every other default in the
    # project is GRB, and a request with the key missing used to silently
    # set RGB and swap red and green on the strip.
    order = str(payload.get("color_order", settings.led_color_order))
    result = automation.set_light_color_order(order)
    log_event(f"LED color order set to {result['color_order']}")
    return result


@app.post(f"{settings.api_prefix}/lights/chip")
async def set_light_chip(payload: dict[str, str] = Body(default_factory=dict)) -> dict[str, object]:
    # settings.led_chip, not a literal: a request with the key missing used to
    # silently select a chip that is no longer even supported.
    chip = str(payload.get("chip", settings.led_chip))
    result = automation.set_light_chip(chip)
    log_event(f"LED chip set to {result['chip']} ({result['color_order']})")
    return result


@app.post(f"{settings.api_prefix}/lights/brightness")
async def set_light_brightness(payload: dict[str, int] = Body(default_factory=dict)) -> dict[str, object]:
    brightness = int(payload.get("brightness", 75))
    result = automation.set_light_brightness(brightness)
    log_event(f"LED brightness set to {result['brightness']}%")
    return result


# Declared last: a path parameter here matches anything, so it would otherwise
# swallow /lights/mode, /lights/color, /lights/color-order and /lights/brightness.
@app.get(f"{settings.api_prefix}/plants")
async def list_plants() -> list[dict[str, object]]:
    plants = automation.plants
    return [
        {
            "plant_id": plant.plant_id,
            "name": plant.name,
            "position_mm": plant.position_mm,
            "light_start_time": plant.light_start_time.isoformat(timespec="minutes"),
            "light_stop_time": plant.light_stop_time.isoformat(timespec="minutes"),
            "moisture_target": plant.moisture_target,
            "watering_volume_ml": plant.watering_volume_ml,
            "led_start_index": plant.led_start_index,
            "led_end_index": plant.led_end_index,
        }
        for plant in plants
    ]


@app.post(f"{settings.api_prefix}/plants/{{plant_id}}/name")
async def update_plant_name(plant_id: str, payload: dict[str, str] = Body(default_factory=dict)) -> dict[str, object]:
    name = str(payload.get("name", "")).strip()
    result = automation.update_plant_name(plant_id, name)
    log_event(f"Plant {plant_id} plant name updated to {name}")
    return result


@app.post(f"{settings.api_prefix}/plants/{{plant_id}}/lighting")
async def update_light_schedule(plant_id: str, payload: dict[str, str] = Body(default_factory=dict)) -> dict[str, object]:
    start_time = time.fromisoformat(str(payload.get("start_time", "08:00")))
    stop_time = time.fromisoformat(str(payload.get("stop_time", "20:00")))
    result = automation.update_light_schedule(plant_id, start_time, stop_time)
    log_event(f"Plant {plant_id} light schedule set to {result['light_start_time']} - {result['light_stop_time']}")
    return result


@app.post(f"{settings.api_prefix}/plants/{{plant_id}}/moisture")
async def update_moisture_target(plant_id: str, payload: dict[str, float] = Body(default_factory=dict)) -> dict[str, object]:
    moisture_target = float(payload.get("moisture_target", 45.0))
    result = automation.update_moisture_target(plant_id, moisture_target)
    log_event(f"Plant {plant_id} moisture target set to {result['moisture_target']}%")
    return result


@app.post(f"{settings.api_prefix}/plants/{{plant_id}}/volume")
async def update_watering_volume(plant_id: str, payload: dict[str, int] = Body(default_factory=dict)) -> dict[str, object]:
    volume_ml = int(payload.get("watering_volume_ml", 100))
    result = automation.update_watering_volume(plant_id, volume_ml)
    log_event(f"Plant {plant_id} watering volume set to {result['watering_volume_ml']} mL")
    return result


@app.post(f"{settings.api_prefix}/plants/{{plant_id}}/position")
async def set_plant_position(plant_id: str, payload: dict[str, float] = Body(default_factory=dict)) -> dict[str, object]:
    position_mm = float(payload.get("position_mm", 0.0))
    result = automation.set_plant_position(plant_id, position_mm)
    log_event(f"Plant {plant_id} position set to {position_mm} mm")
    return result


@app.post(f"{settings.api_prefix}/plants/{{plant_id}}/move")
def move_to_plant(plant_id: str) -> dict[str, object]:
    return log_motion(automation.move_to_plant(plant_id), f"Move gantry to plant {plant_id}")


@app.post(f"{settings.api_prefix}/gantry/home")
def home_gantry() -> dict[str, object]:
    return log_motion(automation.home_gantry(), "Home gantry")


@app.post(f"{settings.api_prefix}/gantry/end")
def move_gantry_to_end(payload: dict[str, str] = Body(default_factory=dict)) -> dict[str, object]:
    """Send the carriage to one end of the rail: {"end": "left"} or "right".

    The target is resolved server-side from Klipper's axis_maximum, so the
    caller does not need to know how long the rail is.
    """
    end = str(payload.get("end", "")).strip().lower()
    return log_motion(
        automation.move_gantry_to_end(end), f"Move gantry all the way {end}"
    )


@app.post(f"{settings.api_prefix}/gantry/move")
def move_gantry(payload: dict[str, float] = Body(default_factory=dict)) -> dict[str, object]:
    distance_mm = float(payload.get("distance_mm", 0.0))
    return log_motion(
        automation.move_gantry_relative(distance_mm), f"Move gantry by {distance_mm} mm"
    )


# --- Camera -----------------------------------------------------------------
#
# Kept together at the bottom so it is one block to lift out or to build on.
# The product plan has the camera as a paid add-on doing timelapse; this is a
# live picture for setup and service, and nothing else.


@app.get(f"{settings.api_prefix}/camera")
def get_camera() -> dict[str, object]:
    return camera.status()


# Async, unlike the hardware endpoints above, and for the opposite reason. They
# are sync so their blocking calls run in the threadpool; a sync generator here
# would hold one of those threadpool workers for as long as the tab stays open.
# This holds a thread only while waiting for each frame.
@app.get(f"{settings.api_prefix}/camera/stream")
async def get_camera_stream() -> Response:
    if not camera.fitted:
        return JSONResponse(status_code=503, content=camera.status())
    return StreamingResponse(
        mjpeg_stream(camera),
        media_type=MJPEG_CONTENT_TYPE,
        headers={
            # A response that never ends is exactly what a cache or a proxy
            # will sit on, and the symptom is one still frame forever.
            # X-Accel-Buffering is read by nginx, which then turns buffering
            # off for this response even where its own config did not.
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


@app.get(f"{settings.api_prefix}/camera/snapshot")
def get_camera_snapshot() -> Response:
    """One frame. Enough to check framing or focus without holding a stream."""
    frame = camera.snapshot()
    if frame is None:
        return JSONResponse(status_code=503, content=camera.status())
    return Response(
        content=frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"}
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("greenthumb.main:app", host="0.0.0.0", port=8000, reload=settings.debug)
