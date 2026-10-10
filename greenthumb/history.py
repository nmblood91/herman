from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path

from greenthumb.models import SensorSample

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "greenthumb.db"

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
    -- 1 delivered, 0 nothing reached the outlet, NULL not checked. Nullable
    -- because "we did not look" and "we looked and saw nothing" are different
    -- answers, and only the second one is a fault.
    delivered   INTEGER
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
        if "delivered" not in columns:
            # Rows written before delivery verification existed are unknown, not
            # failed, and NULL is what the new column defaults to.
            self._db.execute("ALTER TABLE waterings ADD COLUMN delivered INTEGER")
            logger.info("Added waterings.delivered to the existing history database")

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
        delivered: bool | None = None,
        at: int | None = None,
    ) -> None:
        timestamp = int(time.time()) if at is None else at
        with self._lock:
            self._db.execute(
                "INSERT INTO waterings (recorded_at, plant_id, volume_ml, trigger, delivered)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    timestamp,
                    plant_id,
                    int(volume_ml),
                    trigger,
                    None if delivered is None else int(delivered),
                ),
            )
            self._db.commit()

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
                "SELECT recorded_at, plant_id, volume_ml, trigger, delivered FROM waterings"
                " WHERE recorded_at >= ? ORDER BY recorded_at",
                (since,),
            ).fetchall()
        return [
            {
                "t": row["recorded_at"],
                "plant_id": row["plant_id"],
                "volume_ml": row["volume_ml"],
                "trigger": row["trigger"],
                "delivered": None if row["delivered"] is None else bool(row["delivered"]),
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
