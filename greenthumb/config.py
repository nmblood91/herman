from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # 100 mL/min rated, and that rating assumes no head pressure. Real delivery
    # through lift and tubing runs lower, so measure against a real dose: this
    # converts millilitres into a run time, and an error here scales every
    # watering by the same factor while still reporting success.
    # The starting point only. Once the pump has been run against a scale in
    # Diagnostics the measured figure lives in state.json and wins over this,
    # so that a value worked out on the real plumbing is not quietly replaced
    # by a datasheet number on the next restart.
    pump_flow_ml_per_second: float = 1.67
    # Dead-man limit for the manual run button, not a dosing figure. A pump left
    # running empties the reservoir onto the floor, so it stops itself at this
    # regardless of what the browser does.
    # Also the length of a calibration run, which is what sets it: 60s is
    # about 100 mL at the rated rate, and a kitchen scale reads 100 g to
    # roughly a percent. Halving it from 120 also halves what a forgotten run
    # can put on the floor.
    pump_max_run_seconds: int = 60
    # Strip chip: sets the bit timing and the usual channel order. Selectable in
    # the Settings tab. All 12V: WS2815 and GS8208 are one pixel per LED, WS2811
    # drives three LEDs per pixel so led_count is LEDs/3 for it. No 5V chip is
    # offered -- sixty 5V pixels would pull about 3.6A, past what the DC-DC can
    # give on top of the Pi.
    led_chip: str = "WS2811"
    led_count: int = 60
    # Overrides the chip's usual order, for strips wired differently.
    led_color_order: str = "GRB"
    led_spi_bus: int = 0
    led_spi_device: int = 0
    gantry_rail_length_mm: float = 1000.0
    gantry_position_margin_mm: float = 20.0
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
    # are measured per sensor by `--calibrate dry` / `--calibrate wet` and kept
    # in data/state.json, which overrides these; probes do read measurably
    # differently from one another, so a shared pair puts that spread straight
    # into the reported percentage.
    #
    # Placeholders, so the exact numbers carry no measurement -- they only have
    # to be the right order of magnitude and far enough apart to divide by.
    #
    # Wet means the probe in soil at field capacity: soaked and drained 24h,
    # the wettest a pot actually gets. It used to mean plain water, which is not
    # a soil state at all and put the top of the scale somewhere unreachable.
    #
    # The wet placeholder dropped when that changed, and the direction is
    # deliberate. Too high a wet endpoint reads every pot as drier than it is,
    # and with automatic watering on that waters a plant that does not need it.
    # Erring low is the safer way to be wrong before anyone calibrates.
    moisture_raw_dry: int = 320
    moisture_raw_wet: int = 800

    # Off by default, and only the starting value: the Settings tab owns this
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
    watering_cooldown_minutes: int = 30

    # Idle motion: re-home and run a short routine on this interval. On by
    # default -- the re-home is worth having whether or not anyone enjoys the
    # dance, because an open-loop stepper has no other way to notice that the
    # carriage is not where Klipper thinks it is. Starting values only; the
    # Settings tab owns both and persists them.
    idle_motion_enabled: bool = True
    idle_motion_minutes: int = 60

    # Quiet hours. The pump and the gantry are the only loud parts of this
    # machine, and it lives in a room people sit in. Suppresses *automatic*
    # watering only: a dose you asked for by pressing a button still runs,
    # because you are standing there and already know the noise is coming.
    # Defaults here; the UI persists any change to data/state.json.
    # Home once when the service comes up. Until it homes, Klipper reports a
    # position relative to wherever the carriage happened to be powered on at,
    # so every saved plant coordinate is wrong by an unknown amount and
    # watering is refused outright. Without this the first home is up to
    # idle_motion_minutes away.
    #
    # Only the value a planter starts life with; the stored choice wins.
    home_on_startup: bool = True

    quiet_hours_enabled: bool = False
    quiet_hours_start: str = "21:00"
    quiet_hours_stop: str = "08:00"

    # Requires the liquid sensor clamped to the outlet tube, on the falling leg
    # between the high point and the nozzle, with its polarity confirmed.
    #
    # The sensor verifies a dose after the fact rather than gating it. It cannot
    # gate: the outlet reads dry between doses by design, so a pre-check would
    # refuse every watering. Running a peristaltic pump dry for a few seconds is
    # harmless, and watching the line fill proves water reached the plant --
    # which catches a clog or a split tube that an inlet-side check cannot see.
    water_sensor_enabled: bool = False
    # How long to wait after the pump starts before the first look. The falling
    # leg has to fill first: a few mL at the pump's flow rate, a few seconds.
    delivery_check_delay_seconds: float = 5.0

    # History
    history_retention_days: int = 90
    # Empty means the default alongside the app, like logs/.
    history_db_path: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def moisture_sensor_addresses_list(self) -> list[int]:
        """Parse comma-separated sensor addresses to list of integers."""
        return [int(addr.strip()) for addr in self.moisture_sensor_addresses.split(",")]


settings = Settings()
