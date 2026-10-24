from pydantic_settings import BaseSettings, SettingsConfigDict

from greenthumb.paths import ENV_FILE


class Settings(BaseSettings):
    # The product name, which is what any of this that reaches a screen should
    # say. The software, the package and the paths stay "greenthumb"; that name
    # is ours and never shown to whoever owns the planter.
    app_name: str = "Herman"
    api_prefix: str = "/api/v1"
    klipper_host: str = "/run/klipper/uds"
    moisture_sensor_addresses: str = "54,55,56,57"
    # Name of the [output_pin] section in printer.cfg, not a GPIO number: the
    # pump hangs off the SKR's HB MOSFET and is switched by Klipper.
    pump_pin_name: str = "pump"
    # Measured on this build: 66 mL in 60 s after a priming run, through the
    # real lift and tubing. The pump is rated 100 mL/min (1.67 mL/s), but that
    # assumes no head pressure, and this plumbing delivers about a third less.
    # This converts milliliters into a run time, so an error here scales every
    # watering by the same factor while still reporting success.
    # The starting point only. Once the pump has been run against a scale under
    # Calibration, the measured figure lives in state.json and wins over this,
    # so a value worked out on a unit's own plumbing is not replaced by this
    # one on the next restart.
    pump_flow_ml_per_second: float = 1.1
    # Dead-man limit for the manual run button, not a dosing figure. A pump left
    # running empties the reservoir onto the floor, so it stops itself at this
    # regardless of what the browser does.
    # Also the length of a calibration run, which is what sets it: 60s is
    # about 100 mL at the rated rate, and a kitchen scale reads 100 g to
    # roughly a percent. Halving it from 120 also halves what a forgotten run
    # can put on the floor.
    pump_max_run_seconds: int = 60
    # Strip chip: sets the bit timing and the usual channel order. Selectable in
    # the Calibration tab. All 12V: WS2815 and GS8208 are one pixel per LED, WS2811
    # drives three LEDs per pixel so led_count is LEDs/3 for it. No 5V chip is
    # offered -- sixty 5V pixels would pull about 3.6A, past what the DC-DC can
    # give on top of the Pi.
    led_chip: str = "WS2811"
    # 0 means the chip decides: the strip is always one meter at 60 LEDs a
    # meter, so WS2811 is 20 pixels and the others 60 (led_strip.pixel_count).
    # Set it only for a strip of another density, and then in pixels, not LEDs.
    led_count: int = 0
    # Overrides the chip's usual order, for strips wired differently. BRG is
    # what the reference build's WS2811 strip turned out to need.
    led_color_order: str = "BRG"
    led_spi_bus: int = 0
    led_spi_device: int = 0
    # Usable X travel, not the length of the rail. The extrusion is 1000 mm, but
    # the carriage and the end holders take up the rest, leaving 890 mm it can
    # actually move through. Klipper's position_max is the real limit and is
    # asked first; this is only the answer when Klipper is not responding, so a
    # plant position saved with the board unplugged still fits the rail. Keep
    # it equal to position_max in printer.cfg.
    gantry_travel_mm: float = 890.0
    debug: bool = False

    # Camera, an optional add-on. Nothing here assumes one is plugged in: with
    # no capture tool installed the Camera tab says so instead of failing.
    #
    # 640x480 at 10 fps is sized for the smallest board this targets, a Pi 3 A+
    # with 512 MB of RAM. Camera Module 3 captures far larger than this and the
    # ISP scales it down, so a bigger number here spends WiFi bandwidth and
    # JPEG encoding rather than buying detail the lens did not resolve.
    camera_width: int = 640
    camera_height: int = 480
    camera_fps: int = 10
    # MJPEG sends a whole frame every frame, with no delta between them, so
    # this is the main control over how much data crosses the WiFi.
    camera_jpeg_quality: int = 70

    # Control loop
    sensor_poll_seconds: int = 60
    # Watering decisions use the mean of this many polls, so at a 60s interval
    # the loop acts on a 10 minute trend rather than a single noisy reading.
    moisture_window_size: int = 10

    # Fallback endpoints for sensors that have not been calibrated. Real values
    # the dry end is measured per sensor by `--calibrate dry` and kept
    # in data/state.json, which overrides these; probes do read measurably
    # differently from one another, so a shared pair puts that spread straight
    # into the reported percentage.
    #
    # A placeholder, so the exact number carries no measurement -- it only has
    # to be the right order of magnitude. Defensible as a fallback in a way the
    # other end is not: dry is the floor of the scale, so being wrong about it
    # compresses a reading rather than inventing a ceiling for it.
    #
    # There is deliberately no wet counterpart. The top of the scale is field
    # capacity, which is measured per soil mix and stored on the soil and the
    # pot. A configured placeholder there would give a never-calibrated pot a
    # perfectly plausible percentage against a number nobody measured -- the
    # one error in this whole system that nothing downstream can catch. A pot
    # with no measured field capacity reads -1 instead, and -1 is never
    # watered.
    moisture_raw_dry: int = 320

    # Off by default, and only the starting value: the Automation tab owns this
    # switch and persists any change to data/state.json, which wins over this
    # on the next start.
    #
    # Off is the right default because an unattended pump is the one failure
    # here that can drown a plant or empty the reservoir into a dose that never
    # arrives. Turn it on only after running the pump by hand and measuring
    # pump_flow_ml_per_second against a real dose, since that figure is what
    # converts a requested volume into a run time -- get it wrong and every
    # watering is scaled by the same factor while still reporting success.
    auto_watering_enabled: bool = False
    # How long a pot waits before it can be watered again, and also how long
    # its moisture probe is given to show the water arriving before the dose
    # is called a miss. One figure for both: the next watering should not
    # happen before the last one has been judged.
    watering_cooldown_minutes: int = 60

    # Confirm each dose from the pot's own probe: its raw reading has to rise
    # by soak_rise_percent of the pot's span (field capacity minus wilting
    # point, in raw counts) within the cooldown. While a dose is unconfirmed,
    # automatic watering is held for every pot, so an empty tank cannot run
    # the pump dry pot after pot; two misses in a row pause it until Resume.
    soak_check_enabled: bool = True
    soak_rise_percent: float = 5.0

    # Hourly auto-patrol: on the hour, every hour, home and then visit each
    # plant. The home is what earns it -- an open-loop stepper has no other way
    # to notice the carriage is not where Klipper thinks it is. Off by default
    # for the same reason as home_on_startup: nobody assembling a planter
    # should have the arm set off across the rail before they are ready for it.
    # Starting value only; the Automation tab owns it and persists it.
    auto_patrol_enabled: bool = False

    # Quiet hours. The pump and the gantry are the only loud parts of this
    # machine, and it lives in a room people sit in. Suppresses *automatic*
    # watering only: a dose you asked for by pressing a button still runs,
    # because you are standing there and already know the noise is coming.
    # Defaults here; the UI persists any change to data/state.json.
    # Home once when the service comes up. Until it homes, Klipper reports a
    # position relative to wherever the carriage happened to be powered on at,
    # so every plant profile coordinate is wrong by an unknown amount and
    # watering is refused outright. Retried every tick until it lands, since
    # the usual reason it fails is Klipper still coming up alongside us.
    #
    # Off by default: a planter being put together for the first time should
    # not move until someone has checked the endstop and the rail are clear.
    # Only the value a planter starts life with; the stored choice wins.
    home_on_startup: bool = False

    # Whether the motor direction test on the Calibration tab has passed. Until
    # it has, nothing homes: a reversed motor homes away from the switch and
    # drives the carriage into the far end of the rail at homing speed, and
    # every planter is wired by hand. Only the value a planter starts life with;
    # passing the test stores the answer in data/state.json, which wins.
    motor_direction_checked: bool = False
    # Klipper's config folder. A failed direction test writes the flipped
    # dir_pin to motor-direction.cfg here, which printer.cfg includes last so
    # it overrides the template's -- and which the installer never rewrites,
    # so the fix survives a reinstall.
    klipper_config_dir: str = "/home/pi/printer_data/config"

    quiet_hours_enabled: bool = False
    quiet_hours_start: str = "21:00"
    quiet_hours_stop: str = "08:00"

    # History
    history_retention_days: int = 90
    # Empty means the default beside state.json (see greenthumb/paths.py).
    history_db_path: str = ""

    model_config = SettingsConfigDict(
        # .env in a checkout, /etc/greenthumb/greenthumb.env once packaged, so
        # a command run by hand reads the same settings as the service.
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def moisture_sensor_addresses_list(self) -> list[int]:
        """Parse comma-separated sensor addresses to list of integers."""
        return [int(addr.strip()) for addr in self.moisture_sensor_addresses.split(",")]


settings = Settings()
