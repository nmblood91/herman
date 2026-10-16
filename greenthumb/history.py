from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path

from greenthumb.models import SensorSample
from greenthumb.paths import DATA_DIR

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = DATA_DIR / "greenthumb.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id               INTEGER PRIMARY KEY,
    recorded_at      INTEGER NOT NULL,
    sensor_address   INTEGER NOT NULL,
    moisture_raw     REAL NOT NULL,
    moisture_percent REAL NOT NULL,
    temperature_c    REAL
);
CREATE INDEX IF NOT EXISTS idx_readings_addr_time
    ON readings(sensor_address, recorded_at);

CREATE TABLE IF NOT EXISTS waterings (
    id          INTEGER PRIMARY KEY,
    recorded_at INTEGER NOT NULL,
    plant_id     TEXT NOT NULL,
    volume_ml   INTEGER NOT NULL,
    trigger     TEXT NOT NULL,
    -- Whether the pot's own moisture probe saw the water arrive: pending,
    -- soaked, missed, unknown (the probe went quiet) or skipped (could not be
    -- judged). NULL for rows from before the check existed.
    soak        TEXT,
    -- How far the raw reading rose above its pre-dose baseline, in counts.
    soak_rise   REAL
);
CREATE INDEX IF NOT EXISTS idx_waterings_time ON waterings(recorded_at);
"""

# Enough points to show shape without sending 129,600 of them for a 90 day range.
# The most points any range can produce per series, which is what the chart has
# to stay drawable at. The real worst case is 576, at 48 hours in five-minute
# buckets; this is that rounded up for headroom. Exported so the test asserts
# against the same number the buckets were chosen for, rather than its own.
MAX_POINTS_PER_SERIES = 600
MINUTE = 60


def bucket_seconds_for(hours: float) -> int:
    """Time bucket keeping any range under MAX_POINTS_PER_SERIES per series."""
    if hours <= 6:
        return MINUTE
    if hours <= 48:
        return 5 * MINUTE
    if hours <= 24 * 7:
        return 30 * MINUTE
    return 6 * 60 * MINUTE


class HistoryStore:
    """Stores sensor readings and waterings in SQLite for the history chart."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # The control loop writes from an APScheduler thread while API reads come
        # from FastAPI's threadpool, so the connection is shared and every access
        # goes through the lock.
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        # WAL lets reads proceed during a write; NORMAL keeps this crash-safe
        # while only risking the last transaction on a power cut, which for
        # telemetry is worth the reduction in SD card wear.
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(SCHEMA)
        self._migrate()
        self._db.commit()
        logger.info("History database ready at %s", self.path)

    def _migrate(self) -> None:
        """Add columns that CREATE TABLE IF NOT EXISTS cannot add to an old file."""
        columns = {row["name"] for row in self._db.execute("PRAGMA table_info(waterings)")}
        if "zone_id" in columns and "plant_id" not in columns:
            # Zones were renamed to plants. CREATE TABLE IF NOT EXISTS does
            # nothing to a table that already exists, so without this an
            # upgraded install inserts plant_id into a table that only has
            # zone_id and every watering write fails.
            self._db.execute("ALTER TABLE waterings RENAME COLUMN zone_id TO plant_id")
            # The values carried the old prefix too, so without this the
            # existing rows stay keyed to zone_2 and no longer line up with
            # any current plant -- history that silently stops being charted.
            self._db.execute(
                "UPDATE waterings SET plant_id = 'plant_' || substr(plant_id, 6) "
                "WHERE plant_id LIKE 'zone_%'"
            )
            logger.info("Renamed waterings.zone_id to plant_id in the existing history database")
            columns = {row["name"] for row in self._db.execute("PRAGMA table_info(waterings)")}
        for column, kind in (("soak", "TEXT"), ("soak_rise", "REAL")):
            if column not in columns:
                # NULL on old rows: they were never checked, which is neither
                # a pass nor a miss.
                self._db.execute(f"ALTER TABLE waterings ADD COLUMN {column} {kind}")
                logger.info("Added waterings.%s to the existing history database", column)

    def record_readings(self, samples: list[SensorSample], at: int | None = None) -> int:
        """Store one tick's readings. Returns how many were kept."""
        timestamp = int(time.time()) if at is None else at
        rows = [
            (timestamp, s.sensor_address, s.moisture_raw, s.moisture_percent, s.temperature_c)
            # A failed or absent sensor reads -1, which would drag the chart to
            # the floor and poison every bucket average it landed in.
            for s in samples
            if s.moisture_raw >= 0
        ]
        if not rows:
            return 0

        # One transaction for the whole tick rather than one per sensor.
        with self._lock:
            self._db.executemany(
                "INSERT INTO readings"
                " (recorded_at, sensor_address, moisture_raw, moisture_percent, temperature_c)"
                " VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            self._db.commit()
        return len(rows)

    def record_watering(
        self,
        plant_id: str,
        volume_ml: int,
        trigger: str,
        *,
        at: int | None = None,
        soak: str | None = None,
    ) -> int:
        """Store one dose. Returns its row id, for record_soak to update."""
        timestamp = int(time.time()) if at is None else at
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO waterings (recorded_at, plant_id, volume_ml, trigger, soak)"
                " VALUES (?, ?, ?, ?, ?)",
                (timestamp, plant_id, int(volume_ml), trigger, soak),
            )
            self._db.commit()
            return int(cursor.lastrowid)

    def record_soak(self, watering_id: int, soak: str, rise: float | None = None) -> None:
        """Record what the pot's probe made of one dose."""
        with self._lock:
            self._db.execute(
                "UPDATE waterings SET soak = ?, soak_rise = ? WHERE id = ?",
                (soak, None if rise is None else round(float(rise), 1), int(watering_id)),
            )
            self._db.commit()

    def pending_soaks(self) -> list[dict[str, object]]:
        """Doses still waiting for their probe to show the water, oldest first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, recorded_at, plant_id, volume_ml FROM waterings"
                " WHERE soak = 'pending' ORDER BY recorded_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def judged_soaks(self, since: int, limit: int = 10) -> list[dict[str, object]]:
        """The latest doses the probe gave a verdict on (soaked or missed),
        newest first. Unknown and skipped are left out: they say nothing about
        whether water arrives."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, recorded_at, plant_id, soak FROM waterings"
                " WHERE soak IN ('soaked', 'missed') AND recorded_at > ?"
                " ORDER BY recorded_at DESC, id DESC LIMIT ?",
                (int(since), int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def raw_readings(self, address: int, since: int, until: int) -> list[tuple[int, float]]:
        """(time, raw) for one probe over [since, until], oldest first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT recorded_at, moisture_raw FROM readings"
                " WHERE sensor_address = ? AND recorded_at >= ? AND recorded_at <= ?"
                " ORDER BY recorded_at",
                (int(address), int(since), int(until)),
            ).fetchall()
        return [(row["recorded_at"], row["moisture_raw"]) for row in rows]

    def last_waterings(self) -> dict[str, dict[str, object]]:
        """The most recent dose per plant: when, and what its probe made of it."""
        with self._lock:
            rows = self._db.execute(
                "SELECT w.plant_id, w.recorded_at, w.soak, w.soak_rise FROM waterings w"
                " JOIN (SELECT plant_id, MAX(id) AS id FROM waterings GROUP BY plant_id) last"
                " ON w.id = last.id"
            ).fetchall()
        return {row["plant_id"]: dict(row) for row in rows}

    def series(
        self, addresses: list[int], hours: float, now: int | None = None
    ) -> tuple[int, list[int], dict[int, dict[str, list[float | None]]]]:
        """Bucketed readings per address, aligned onto one shared timestamp axis.

        uPlot needs a single x array shared by every series, so the alignment
        happens here rather than being reimplemented in the browser. A None means
        that address had no reading in that bucket, which is real information --
        the sensor was unreadable.
        """
        bucket = bucket_seconds_for(hours)
        end = int(time.time()) if now is None else now
        since = end - int(hours * 3600)

        with self._lock:
            rows = self._db.execute(
                "SELECT sensor_address,"
                "       (recorded_at / ?) * ? AS bucket,"
                "       AVG(moisture_percent) AS moisture_percent,"
                "       AVG(temperature_c) AS temperature_c"
                " FROM readings"
                # The write filter admits any row with a usable raw count,
                # which is right -- a raw is worth keeping for forensics even
                # when no field capacity existed to turn it into a percentage.
                # But -1 in that column is "cannot say", and averaging it into
                # a bucket drags the line to the floor, which reads as a bone
                # dry pot.
                " WHERE recorded_at >= ? AND moisture_percent >= 0"
                " GROUP BY sensor_address, bucket"
                " ORDER BY bucket",
                (bucket, bucket, since),
            ).fetchall()

        by_address: dict[int, dict[int, sqlite3.Row]] = {}
        stamps: set[int] = set()
        for row in rows:
            by_address.setdefault(row["sensor_address"], {})[row["bucket"]] = row
            stamps.add(row["bucket"])

        timestamps = sorted(stamps)
        series: dict[int, dict[str, list[float | None]]] = {}
        for address in addresses:
            buckets = by_address.get(address, {})
            series[address] = {
                "moisture_percent": [
                    round(buckets[t]["moisture_percent"], 1) if t in buckets else None
                    for t in timestamps
                ],
                "temperature_c": [
                    round(buckets[t]["temperature_c"], 1)
                    if t in buckets and buckets[t]["temperature_c"] is not None
                    else None
                    for t in timestamps
                ],
            }
        return bucket, timestamps, series

    def waterings(self, hours: float, now: int | None = None) -> list[dict[str, object]]:
        end = int(time.time()) if now is None else now
        since = end - int(hours * 3600)
        with self._lock:
            rows = self._db.execute(
                "SELECT recorded_at, plant_id, volume_ml, trigger, soak FROM waterings"
                " WHERE recorded_at >= ? ORDER BY recorded_at",
                (since,),
            ).fetchall()
        return [
            {
                "t": row["recorded_at"],
                "plant_id": row["plant_id"],
                "volume_ml": row["volume_ml"],
                "trigger": row["trigger"],
                "soak": row["soak"],
            }
            for row in rows
        ]

    def prune(self, retention_days: int, now: int | None = None) -> int:
        """Drop rows past the retention window. Returns rows deleted."""
        end = int(time.time()) if now is None else now
        cutoff = end - retention_days * 24 * 3600
        with self._lock:
            # DELETE does not shrink the file, but SQLite reuses the freed pages
            # and steady state is only tens of megabytes, so no VACUUM.
            readings = self._db.execute(
                "DELETE FROM readings WHERE recorded_at < ?", (cutoff,)
            ).rowcount
            waterings = self._db.execute(
                "DELETE FROM waterings WHERE recorded_at < ?", (cutoff,)
            ).rowcount
            self._db.commit()

        deleted = readings + waterings
        if deleted:
            logger.info("Pruned %d rows older than %d days", deleted, retention_days)
        return deleted

    def close(self) -> None:
        with self._lock:
            self._db.close()
