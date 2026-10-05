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
    # pump hangs off the SKR's HE0 MOSFET and is switched by Klipper.
    pump_pin_name: str = "pump"
    # 100 mL/min rated, and that rating assumes no head pressure. Real delivery
    # through lift and tubing runs lower, so measure against a real dose: this
    # converts millilitres into a run time, and an error here scales every
    # watering by the same factor while still reporting success.
    pump_flow_ml_per_second: float = 1.67
    # Dead-man limit for the manual run button, not a dosing figure. A pump left
    # running empties the reservoir onto the floor, so it stops itself at this
    # regardless of what the browser does.
    pump_max_run_seconds: int = 120
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
    # Wet is the reading in plain water, which soil never quite reaches.
    moisture_raw_dry: int = 320
    moisture_raw_wet: int = 1020

    # Off by default. The pump is real, but an unattended pump is the one
    # failure here that can drown a plant or empty the reservoir onto a dose
    # that never arrives. Turn this on only after running the pump by hand and
    # measuring pump_flow_ml_per_second against a real dose, since that figure
    # is what converts a requested volume into a run time.
    auto_watering_enabled: bool = False
    watering_cooldown_minutes: int = 30

    # Quiet hours. The pump and the gantry are the only loud parts of this
    # machine, and it lives in a room people sit in. Suppresses *automatic*
    # watering only: a dose you asked for by pressing a button still runs,
    # because you are standing there and already know the noise is coming.
    # Defaults here; the UI persists any change to data/state.json.
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
