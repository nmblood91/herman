from __future__ import annotations

import logging

from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncIterator

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Body, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from greenthumb.config import settings
from greenthumb.hardware.camera import CameraStream, MJPEG_CONTENT_TYPE, mjpeg_stream
from greenthumb.hardware.lighting import DEFAULT_RAINBOW_SPEED
from greenthumb.logging_setup import log_event, read_recent_logs, setup_logging
from greenthumb import firmware_info, system_clock, system_hostname, system_power, version
from greenthumb.plants import sweep_edge_limits, zone_for
from greenthumb.services.automation import (
    UNCHANGED,
    GreenThumbAutomation,
    HardwareBusyError,
    care_fields,
)

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
    # On the hour, every hour. Scheduled whether or not the patrol is on, so
    # switching it on needs no rescheduling -- auto_patrol checks the switch.
    # The grace covers a thread pool that starts the job a little late; past
    # it, the hour is skipped rather than run at some arbitrary minute.
    scheduler.add_job(
        automation.auto_patrol,
        "cron",
        minute=0,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
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
    """What is running, and whether the code on disk has moved on without it.

    Also Klipper's version on the Pi and the firmware's on the SKR. They have
    to come from the same commit, and the board can only be reflashed by hand,
    so a mismatch is reported rather than left to show up as a gantry that
    refuses to move.
    """
    result = version.status()
    klipper = automation.klipper.versions()
    result["klipper"] = {
        **klipper,
        "firmware_mismatch": firmware_info.mismatch(klipper["host"], klipper["mcu"]),
    }
    return result


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


@app.get(f"{settings.api_prefix}/system/hostname")
def get_hostname() -> dict[str, object]:
    return system_hostname.status()


@app.post(f"{settings.api_prefix}/system/hostname")
def set_hostname(payload: dict[str, object] = Body(default_factory=dict)) -> dict[str, object]:
    """Rename the Pi: {"hostname": "herman-kitchen"} -> herman-kitchen.local.

    A bad name is a 400 and a refused rename a 409, through the app-level
    handlers, the same as the timezone.
    """
    before = system_hostname.current()
    result = system_hostname.rename(payload.get("hostname"))
    if result["hostname"] != before:
        log_event(f"Planter renamed from {before} to {result['hostname']}")
    return result


@app.post(f"{settings.api_prefix}/system/power")
def system_power_action(payload: dict[str, object] = Body(default_factory=dict)) -> dict[str, object]:
    """Shut the Pi down or reboot it: {"action": "shutdown" | "reboot"}.

    Refused with a 409 while the hardware is busy, so a shutdown cannot cut
    a dose or a gantry move off halfway. An unknown action is a 400, and a
    missing sudoers rule a 409 saying how to add it.
    """
    action = str(payload.get("action", ""))
    result = automation.request_power(action)
    log_event(f"{action.capitalize()} requested from the UI")
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


@app.post(f"{settings.api_prefix}/watering/resume")
def resume_watering() -> dict[str, object]:
    """Clear the pause after two waterings in a row didn't reach the soil."""
    result = automation.resume_watering()
    log_event("Automatic watering resumed after waterings didn't reach the soil")
    return result


@app.get(f"{settings.api_prefix}/dances")
def list_dances() -> dict[str, object]:
    return {"dances": automation.dance_catalog()}


@app.post(f"{settings.api_prefix}/dances/run/{{name}}")
def run_dance(name: str) -> dict[str, object]:
    result = automation.run_dance(name)
    if result.get("ok"):
        log_event(f"Ran the {name} routine")
    else:
        log_event(f"Routine {name} did not run: {result.get('error')}", level=logging.WARNING)
    return result


def _require_enabled(payload: dict[str, object]) -> bool:
    # A missing or non-boolean value is refused rather than read as False, so
    # a malformed request cannot quietly switch something off.
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be true or false")
    return enabled


@app.post(f"{settings.api_prefix}/patrol/auto")
def set_auto_patrol(payload: dict[str, object] = Body(default_factory=dict)) -> dict[str, object]:
    """Switch the hourly auto-patrol: a re-home and a pass over every plant."""
    result = automation.set_auto_patrol(_require_enabled(payload))
    log_event(f"Hourly auto-patrol {'on' if result['enabled'] else 'off'}")
    return result


@app.post(f"{settings.api_prefix}/gantry/home-on-startup")
def set_home_on_startup(payload: dict[str, object] = Body(default_factory=dict)) -> dict[str, object]:
    """Switch homing after startup. Takes effect on the next start."""
    result = automation.set_home_on_startup(_require_enabled(payload))
    log_event(f"Home on startup {'on' if result['enabled'] else 'off'}")
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
    log_event("Watering snooze canceled")
    return result


@app.get(f"{settings.api_prefix}/sensors/calibration")
def get_moisture_calibration() -> dict[str, object]:
    return automation.moisture_calibration()


@app.get(f"{settings.api_prefix}/sensors/live")
def read_live_moisture() -> dict[str, object]:
    """A fresh reading from every probe, for the Calibration tab's live check."""
    return automation.live_moisture()


# Registered before the {endpoint} route below, which would otherwise match
# "reset" as an endpoint name and reject it as invalid.
@app.post(f"{settings.api_prefix}/sensors/calibration/reset")
def reset_moisture_calibration() -> dict[str, object]:
    result = automation.reset_moisture_calibration()
    log_event("Moisture calibration cleared")
    return result


@app.post(f"{settings.api_prefix}/system/restore-defaults")
def restore_system_defaults() -> dict[str, object]:
    """Back to a fresh install, keeping the plant profile and soil libraries
    and the history."""
    result = automation.restore_system_defaults()
    log_event("Planter restored to defaults (plant and soil libraries kept)")
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


@app.get(f"{settings.api_prefix}/pump")
def pump_status() -> dict[str, object]:
    """The flow rate in use, and the last timed run a calibration can use."""
    return automation.pump_status()


@app.post(f"{settings.api_prefix}/pump/calibrate")
def calibrate_pump_flow(payload: dict[str, object] = Body(default_factory=dict)) -> dict[str, object]:
    """Turn the last run plus a measured volume into a flow rate.

    Expects {"measured_ml": ...} -- what came out, weighed on a scale.
    """
    result = automation.calibrate_pump_flow(payload.get("measured_ml"))
    log_event(
        f"Pump flow calibrated to {result['flow_ml_per_second']} mL/s "
        f"({result['measured_ml']} mL in {result['run_seconds']}s)"
    )
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
    # settings.led_color_order, not a literal: a request with the key missing
    # used to silently set RGB and scramble the colors on the strip.
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


@app.post(f"{settings.api_prefix}/lights/rainbow-speed")
async def set_light_rainbow_speed(payload: dict[str, int] = Body(default_factory=dict)) -> dict[str, object]:
    result = automation.set_light_rainbow_speed(payload.get("rainbow_speed", DEFAULT_RAINBOW_SPEED))
    cycle = result["rainbow_cycle_seconds"]
    log_event(
        f"Rainbow speed set to {result['rainbow_speed']} "
        f"({'paused' if cycle is None else f'{cycle} s a cycle'})"
    )
    return result


@app.post(f"{settings.api_prefix}/lights/manual-scope")
async def set_light_manual_scope(payload: dict[str, str] = Body(default_factory=dict)) -> dict[str, object]:
    """{"scope": "all"} lights the whole strip one way; "zones" each pot its own."""
    result = automation.set_light_manual_scope(str(payload.get("scope", "all")))
    log_event(f"Manual lighting set to {'each zone separately' if result['manual_scope'] == 'zones' else 'all zones'}")
    return result


def _rgb(payload: dict) -> list[object] | None:
    """{"r", "g", "b"} as a color, None when none of them is given.

    Left unclamped: care.check_light_color refuses a bad channel, where a clamp
    would quietly show a color nobody picked.
    """
    if not any(key in payload for key in ("r", "g", "b")):
        return None
    return [payload.get("r"), payload.get("g"), payload.get("b")]


@app.post(f"{settings.api_prefix}/lights/zones/{{plant_id}}")
async def set_zone_manual(plant_id: str, payload: dict[str, object] = Body(default_factory=dict)) -> dict[str, object]:
    """{"r", "g", "b"} and/or {"brightness"}: this pot's own manual lighting."""
    result = automation.set_zone_manual(plant_id, _rgb(payload), payload.get("brightness"))
    log_event(
        f"{result['name']} manual lighting set to {tuple(result['manual_color'])} "
        f"at {result['manual_brightness']}%"
    )
    return result


# Declared last: a path parameter here matches anything, so it would otherwise
# swallow /lights/mode, /lights/color, /lights/color-order, /lights/brightness,
# /lights/rainbow-speed and /lights/manual-scope.
@app.get(f"{settings.api_prefix}/plants")
async def list_plants() -> list[dict[str, object]]:
    plants = automation.plants
    # Once, not per plant: it is a round trip to Klipper.
    travel = automation.usable_travel_mm()
    return [
        {
            "plant_id": plant.plant_id,
            "name": plant.name,
            "position_mm": plant.position_mm,
            # Where this plant may be watered, so the card can say so before
            # a save is refused. See plants.ZONES.
            **dict(zip(("zone_min_mm", "zone_max_mm"), zone_for(plant.plant_id, travel))),
            # The narrower range each sweep edge accepts within that zone.
            **dict(
                zip(
                    ("sweep_left_max_mm", "sweep_right_min_mm"),
                    sweep_edge_limits(*zone_for(plant.plant_id, travel)),
                )
            ),
            "watering_mode": plant.watering_mode,
            "sweep_min_mm": plant.sweep_min_mm,
            "sweep_max_mm": plant.sweep_max_mm,
            # Which plant profile the care settings came from; "" until one is
            # loaded, which the card shows instead of the placeholders.
            "profile": plant.profile,
            **care_fields(plant),
            "soil": plant.soil,
            "led_start_index": plant.led_start_index,
            "led_end_index": plant.led_end_index,
            "light_color": list(plant.light_color),
        }
        for plant in plants
    ]


# --- plant profiles -----------------------------------------------------------
#
# Keyed by plant name, so saving overwrites the entry of that name. Two pots
# may carry the same name; a profile is care settings, not a slot.


@app.get(f"{settings.api_prefix}/soils")
def list_soils() -> dict[str, object]:
    return {"soils": automation.list_soils()}


@app.post(f"{settings.api_prefix}/soils")
def save_soil(payload: dict[str, object] = Body(default_factory=dict)) -> dict[str, object]:
    """Add or replace a soil. Keyed on name, so saving overwrites.

    Expects {"name": ..., "field_capacity_vwc": ..., "wilting_point_vwc": ...}
    as volumetric water content percentages. Optionally field_capacity_raw and
    wilting_point_raw, typed sensor readings: left out to keep what is stored,
    null to clear it.
    """
    result = automation.save_soil(
        str(payload.get("name", "")),
        payload.get("field_capacity_vwc"),
        payload.get("wilting_point_vwc"),
        payload.get("notes", ""),
        payload.get("field_capacity_raw", UNCHANGED),
        payload.get("wilting_point_raw", UNCHANGED),
    )
    log_event(
        f"Saved soil {result['name']}: field capacity "
        f"{result['soil']['field_capacity_vwc']}% VWC, wilting point "
        f"{result['soil']['wilting_point_vwc']}%"
    )
    return result


@app.post(f"{settings.api_prefix}/soils/{{name}}/field-capacity")
def calibrate_soil_field_capacity(
    name: str, payload: dict[str, object] = Body(default_factory=dict)
) -> dict[str, object]:
    """Measure a mix's field capacity using one pot's probe.

    Expects {"plant_id": "plant_2", "seconds": 20}. plant_id names only which
    probe to read -- the figure lands on the mix, and is copied onto every pot
    filled with it that has not measured its own.
    """
    result = automation.calibrate_soil_field_capacity(
        name,
        str(payload.get("plant_id", "")),
        int(payload.get("seconds", 20) or 20),
    )
    if result.get("written"):
        log_event(
            f"Field capacity for {result['soil']} is {result['value']}, measured "
            f"on {result['measured_with']}, applied to "
            f"{len(result.get('inherited_by') or [])} pot(s)"
        )
    else:
        log_event(f"Field capacity for {name} not stored: {result.get('reason')}")
    return result


@app.post(f"{settings.api_prefix}/soils/{{name}}/wilting-point")
def calibrate_soil_wilting_point(
    name: str, payload: dict[str, object] = Body(default_factory=dict)
) -> dict[str, object]:
    """Measure a mix's wilting point as a sensor reading using one pot's probe.

    Expects {"plant_id": "plant_2", "seconds": 20}. plant_id names only which
    probe to read; the figure lands on the mix and is not copied to any pot.
    """
    result = automation.calibrate_soil_wilting_point(
        name,
        str(payload.get("plant_id", "")),
        int(payload.get("seconds", 20) or 20),
    )
    if result.get("written"):
        log_event(
            f"Wilting point for {result['soil']} is {result['value']}, measured "
            f"on {result['measured_with']}"
        )
    else:
        log_event(f"Wilting point for {name} not stored: {result.get('reason')}")
    return result


@app.delete(f"{settings.api_prefix}/soils/{{name}}")
def delete_soil(name: str) -> dict[str, object]:
    result = automation.delete_soil(name)
    log_event(f"Deleted soil {name}")
    return result


@app.post(f"{settings.api_prefix}/plants/{{plant_id}}/soil")
def set_plant_soil(
    plant_id: str, payload: dict[str, str] = Body(default_factory=dict)
) -> dict[str, object]:
    """Record the mix in this pot. An empty name clears it."""
    result = automation.update_plant_soil(plant_id, str(payload.get("soil", "")))
    log_event(f"Set {plant_id} soil to {result.get('soil') or 'unset'}")
    return result


@app.get(f"{settings.api_prefix}/plant-profiles")
def list_plant_profiles() -> dict[str, object]:
    return {"profiles": automation.list_plant_profiles()}


@app.post(f"{settings.api_prefix}/plant-profiles")
def write_plant_profile(payload: dict[str, object] = Body(default_factory=dict)) -> dict[str, object]:
    """Create or replace a plant profile directly, with no pot involved.

    Expects {"name", "category", "preferred_soil", "target_available",
    "watering_volume_ml", "light_start_time", "light_hours",
    "light_brightness", "notes"}. The water level is worked out from
    target_available. Name is the key, so saving replaces -- the same rule as the
    soil library.
    """
    result = automation.write_plant_profile(
        str(payload.get("name", "")), payload
    )
    log_event(f"Plant profile {result['name']}")
    return result


@app.get(f"{settings.api_prefix}/library/export")
def export_library() -> dict[str, object]:
    """Every soil profile and plant profile, as one JSON backup."""
    return automation.export_library()


@app.post(f"{settings.api_prefix}/library/import")
def import_library(payload: dict[str, object] = Body(default_factory=dict)) -> dict[str, object]:
    """Load a backup from /library/export.

    Expects {"backup": <the exported file>, "replace": false}. Without
    replace, entries whose name already exists are kept as they are.
    """
    result = automation.import_library(payload.get("backup"), bool(payload.get("replace")))
    written = sum(
        outcome == "written"
        for section in ("soil_profiles", "plant_profiles")
        for outcome in result[section].values()
    )
    log_event(f"Imported a library backup: {written} entries written")
    return result


@app.get(f"{settings.api_prefix}/plant-profiles/{{name}}")
def read_plant_profile(name: str) -> dict[str, object]:
    """One plant profile, for an editor to load into its form."""
    return automation.get_plant_profile(name)


@app.delete(f"{settings.api_prefix}/plant-profiles/{{name}}")
def delete_plant_profile(name: str) -> dict[str, object]:
    result = automation.delete_plant_profile(name)
    log_event(f"Deleted plant profile {name}")
    return result


# /profile and /profile/load rather than one route taking a verb: the save
# reads the pot and the load writes to it, so they are different operations on
# the same thing and a single endpoint would need a mode flag.
@app.post(f"{settings.api_prefix}/plants/{{plant_id}}/profile")
def save_plant_profile(plant_id: str) -> dict[str, object]:
    """Store this plant's current settings under its own name."""
    result = automation.save_plant_profile(plant_id)
    log_event(f"Plant profile settings as {result.get('name')}")
    return result


@app.post(f"{settings.api_prefix}/plants/{{plant_id}}/profile/load")
def load_plant_profile(
    plant_id: str, payload: dict[str, str] = Body(default_factory=dict)
) -> dict[str, object]:
    """Copy a plant profile onto this one. Leaves its rail position alone."""
    result = automation.apply_plant_profile(plant_id, str(payload.get("name", "")))
    log_event(f"Loaded plant profile {result.get('name')} onto {plant_id}")
    return result


@app.post(f"{settings.api_prefix}/plants/{{plant_id}}/profile/clear")
def clear_plant_profile(plant_id: str) -> dict[str, object]:
    """Take the plant profile off this pot. Placement and soil are kept."""
    result = automation.clear_plant_profile(plant_id)
    log_event(f"Cleared the plant profile from {plant_id}")
    return result


@app.post(f"{settings.api_prefix}/plants/{{plant_id}}/name")
async def update_plant_name(plant_id: str, payload: dict[str, str] = Body(default_factory=dict)) -> dict[str, object]:
    name = str(payload.get("name", "")).strip()
    result = automation.update_plant_name(plant_id, name)
    log_event(f"Plant {plant_id} plant name updated to {name}")
    return result


@app.post(f"{settings.api_prefix}/plants/{{plant_id}}/light-color")
async def set_plant_light_color(plant_id: str, payload: dict[str, object] = Body(default_factory=dict)) -> dict[str, object]:
    """{"r", "g", "b"}: the color this pot shows during its scheduled hours."""
    result = automation.set_plant_light_color(plant_id, _rgb(payload))
    log_event(f"Plant {plant_id} scheduled light color set to {tuple(result['light_color'])}")
    return result


@app.post(f"{settings.api_prefix}/plants/{{plant_id}}/lighting")
async def update_light_schedule(plant_id: str, payload: dict[str, object] = Body(default_factory=dict)) -> dict[str, object]:
    """{"light_start_time": "07:00", "light_hours": 13, "light_brightness": 75}."""
    plant = automation.get_plant(plant_id)
    result = automation.update_light_schedule(
        plant_id,
        payload.get("light_start_time", plant.light_start_time if plant else None),
        payload.get("light_hours", plant.light_hours if plant else None),
        payload.get("light_brightness", plant.light_brightness if plant else None),
    )
    log_event(
        f"Plant {plant_id} lights {result['light_start_time']} for {result['light_hours']} h "
        f"(off at {result['light_stop_time']}) at {result['light_brightness']}%"
    )
    return result


@app.post(f"{settings.api_prefix}/plants/{{plant_id}}/moisture")
async def update_target_available(plant_id: str, payload: dict[str, object] = Body(default_factory=dict)) -> dict[str, object]:
    """Set the share of available water this plant is watered at, e.g. {"target_available": 40}."""
    result = automation.update_target_available(plant_id, payload.get("target_available"))
    log_event(f"Plant {plant_id} watering target set to {result['target_available']}% soil water")
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
    log_event(f"Plant {plant_id} position set to {result['position_mm']} mm")
    return result


@app.post(f"{settings.api_prefix}/plants/{{plant_id}}/sweep")
async def set_plant_sweep(plant_id: str, payload: dict[str, float] = Body(default_factory=dict)) -> dict[str, object]:
    """The span an oscillating dose travels across, in rail coordinates."""
    result = automation.set_plant_sweep(
        plant_id, payload.get("sweep_min_mm"), payload.get("sweep_max_mm")
    )
    log_event(
        f"Plant {plant_id} sweep set to {result['sweep_min_mm']}"
        f"-{result['sweep_max_mm']} mm"
    )
    return result


@app.post(f"{settings.api_prefix}/plants/{{plant_id}}/watering-mode")
async def set_watering_mode(plant_id: str, payload: dict[str, str] = Body(default_factory=dict)) -> dict[str, object]:
    """Lay the dose down at one point, or sweep it across a span."""
    result = automation.set_watering_mode(plant_id, payload.get("watering_mode", ""))
    log_event(f"Plant {plant_id} watering mode set to {result['watering_mode']}")
    return result


@app.post(f"{settings.api_prefix}/plants/{{plant_id}}/move")
def move_to_plant(plant_id: str) -> dict[str, object]:
    return log_motion(automation.move_to_plant(plant_id), f"Move gantry to plant {plant_id}")


@app.get(f"{settings.api_prefix}/gantry/position")
def gantry_position() -> dict[str, object]:
    """Live carriage position. Polled by the Controls tab, so not logged."""
    return automation.gantry_position()


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


@app.post(f"{settings.api_prefix}/gantry/direction/test")
def test_motor_direction() -> dict[str, object]:
    """Turn the X motor 10 mm toward the switch, homed or not."""
    return log_motion(automation.test_motor_direction(), "Motor direction test")


@app.post(f"{settings.api_prefix}/gantry/direction/answer")
def answer_motor_direction(payload: dict[str, object] = Body(default_factory=dict)) -> dict[str, object]:
    """Which way the test went: {"toward_switch": true} passes, false flips it."""
    toward = payload.get("toward_switch")
    # Refused rather than read as False, so a malformed request cannot flip
    # the motor's direction.
    if not isinstance(toward, bool):
        raise ValueError("toward_switch must be true or false")
    result = automation.answer_motor_direction(toward)
    if not result.get("ok"):
        log_event(f"Motor direction not changed: {result.get('error')}", level=logging.WARNING)
    elif toward:
        log_event("Motor direction test passed")
    else:
        log_event("Motor direction reversed; Klipper restarting. Test it again.")
    return result


@app.post(f"{settings.api_prefix}/gantry/release")
def release_motors() -> dict[str, object]:
    """Switch the motors off, so the carriage slides by hand."""
    return log_motion(automation.release_motors(), "Release motors")


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

    # Localhost, matching the systemd unit. Reach it through nginx on port 80,
    # or from the machine it is running on.
    uvicorn.run("greenthumb.main:app", host="127.0.0.1", port=8000, reload=settings.debug)
