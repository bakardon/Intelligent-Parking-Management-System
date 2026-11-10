"""
PostgreSQL access: connection pool, schema migrations, occupancy history
and analytics queries.

Configuration entities (cameras, zones, users, ...) live in
`src/repositories.py` and use the same pool.
"""

import logging
import threading
from contextlib import contextmanager
from datetime import timedelta

import psycopg2
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor, execute_values

from src import config


log = logging.getLogger(__name__)

# Serialises concurrent migration runs (e.g. two app instances starting).
MIGRATION_LOCK_ID = 7_331_001


class DatabaseUnavailable(RuntimeError):
    """Raised when PostgreSQL cannot be reached."""


class Database:
    def __init__(self, **overrides):
        self.params = {
            "host": config.DB_HOST,
            "port": config.DB_PORT,
            "dbname": config.DB_NAME,
            "user": config.DB_USER,
            "password": config.DB_PASSWORD,
            "connect_timeout": 5,
            "application_name": "parksight",
        }
        self.params.update(overrides)
        self.max_connections = config.DB_POOL_MAX
        self._pool = None
        self._pool_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Connections
    # ------------------------------------------------------------------

    def _get_pool(self):
        if self._pool is None:
            with self._pool_lock:
                if self._pool is None:
                    try:
                        self._pool = pg_pool.ThreadedConnectionPool(
                            1, self.max_connections, **self.params
                        )
                    except psycopg2.OperationalError as error:
                        raise DatabaseUnavailable(
                            f"Cannot connect to PostgreSQL at "
                            f"{self.params['host']}:{self.params['port']}"
                            f"/{self.params['dbname']}"
                        ) from error
        return self._pool

    @contextmanager
    def connection(self):
        """Pooled connection; commits on success, rolls back on error.

        Connections that failed at the transport level are discarded so a
        PostgreSQL restart does not leave dead connections in the pool.
        """
        pool = self._get_pool()
        try:
            conn = pool.getconn()
        except pg_pool.PoolError as error:
            raise DatabaseUnavailable("Database connection pool exhausted") from error

        broken = False
        try:
            yield conn
            conn.commit()
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            broken = True
            raise
        except Exception:
            if not conn.closed:
                conn.rollback()
            raise
        finally:
            pool.putconn(conn, close=broken or bool(conn.closed))

    @contextmanager
    def cursor(self):
        with self.connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                yield cur

    def fetch_all(self, sql, params=None):
        with self.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def fetch_one(self, sql, params=None):
        with self.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def execute(self, sql, params=None):
        with self.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount

    def ping(self):
        try:
            self.fetch_one("SELECT 1 AS ok")
            return True
        except Exception:
            return False

    def close(self):
        with self._pool_lock:
            if self._pool is not None:
                self._pool.closeall()
                self._pool = None

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def initialize(self):
        """Apply pending migrations. Safe to call on every start."""
        self.migrate()

    def migrate(self):
        files = sorted(config.MIGRATIONS_DIR.glob("*.sql"))
        applied_now = []
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_ID,))
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version VARCHAR(100) PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                cur.execute("SELECT version FROM schema_migrations")
                applied = {row[0] for row in cur.fetchall()}
                # Each migration and its bookkeeping row share this
                # transaction: a failure rolls back everything.
                for path in files:
                    version = path.stem
                    if version in applied:
                        continue
                    log.info("Applying database migration %s", version)
                    cur.execute(path.read_text(encoding="utf-8"))
                    cur.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)",
                        (version,),
                    )
                    applied_now.append(version)
        return applied_now

    def schema_version(self):
        row = self.fetch_one("SELECT max(version) AS version FROM schema_migrations")
        return row["version"] if row else None

    # ------------------------------------------------------------------
    # Occupancy history
    # ------------------------------------------------------------------

    def insert_snapshot(self, recorded_at, rows):
        """Insert one snapshot (one row per zone) atomically.

        Duplicate (zone, recorded_at) pairs are ignored, so a retried or
        doubled snapshot cannot create duplicate history.
        """
        if not rows:
            return 0
        values = []
        for row in rows:
            if row["occupied"] + row["available"] + row["unknown"] != row["capacity"]:
                raise ValueError(f"Inconsistent occupancy counts: {row}")
            values.append(
                (
                    recorded_at,
                    row["camera_id"],
                    row["zone_id"],
                    row["camera_name"],
                    row["zone_name"],
                    row["capacity"],
                    row["occupied"],
                    row["available"],
                    row["unknown"],
                )
            )
        with self.connection() as conn:
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    """
                    INSERT INTO occupancy_history
                        (recorded_at, camera_id, zone_id, camera_name, zone_name,
                         capacity, occupied, available, unknown)
                    VALUES %s
                    ON CONFLICT (zone_id, recorded_at) WHERE zone_id IS NOT NULL
                    DO NOTHING
                    """,
                    values,
                )
                return cur.rowcount

    def get_history(self, limit=100):
        """Legacy `/history` shape: site totals, newest first."""
        return self.fetch_all(
            """
            SELECT min(id) AS id, recorded_at AS timestamp,
                   sum(capacity)::int AS capacity,
                   sum(occupied)::int AS occupied,
                   sum(available)::int AS available,
                   sum(unknown)::int AS unknown
            FROM occupancy_history
            GROUP BY recorded_at
            ORDER BY recorded_at DESC
            LIMIT %s
            """,
            (limit,),
        )

    @staticmethod
    def _range_filter(start, end, zone_id):
        clauses = ["recorded_at >= %(start)s", "recorded_at < %(end)s"]
        params = {"start": start, "end": end}
        if zone_id is not None:
            clauses.append("zone_id = %(zone_id)s")
            params["zone_id"] = zone_id
        return " AND ".join(clauses), params

    def list_history(self, start, end, zone_id=None, limit=100, offset=0):
        where, params = self._range_filter(start, end, zone_id)
        params.update(limit=limit, offset=offset)
        total = self.fetch_one(
            f"SELECT count(*) AS n FROM occupancy_history WHERE {where}", params
        )["n"]
        items = self.fetch_all(
            f"""
            SELECT id, recorded_at, camera_id, zone_id, camera_name, zone_name,
                   capacity, occupied, available, unknown
            FROM occupancy_history
            WHERE {where}
            ORDER BY recorded_at DESC, zone_name
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            params,
        )
        return total, items

    def _snapshots_cte(self, start, end, zone_id):
        where, params = self._range_filter(start, end, zone_id)
        cte = f"""
            WITH snap AS (
                SELECT recorded_at,
                       sum(capacity) AS capacity,
                       sum(occupied) AS occupied,
                       sum(available) AS available,
                       sum(unknown) AS unknown,
                       sum(occupied)::float
                         / NULLIF(sum(capacity) - sum(unknown), 0) AS rate
                FROM occupancy_history
                WHERE {where}
                GROUP BY recorded_at
            )
        """
        return cte, params

    def occupancy_series(self, start, end, bucket_seconds, zone_id=None):
        cte, params = self._snapshots_cte(start, end, zone_id)
        params["bucket"] = timedelta(seconds=bucket_seconds)
        return self.fetch_all(
            cte
            + """
            SELECT date_bin(%(bucket)s, recorded_at, TIMESTAMPTZ '2000-01-01') AS bucket,
                   (avg(occupied) FILTER (WHERE unknown = 0))::float AS occupied,
                   (avg(available) FILTER (WHERE unknown = 0))::float AS available,
                   avg(capacity)::float AS capacity,
                   avg(unknown)::float AS unknown,
                   (max(occupied) FILTER (WHERE unknown = 0))::int AS peak_occupied,
                   avg(rate) AS rate,
                   count(*)::int AS samples
            FROM snap
            GROUP BY 1
            ORDER BY 1
            """,
            params,
        )

    def occupancy_summary(self, start, end, zone_id=None):
        cte, params = self._snapshots_cte(start, end, zone_id)
        return self.fetch_one(
            cte
            + """
            SELECT count(*)::int AS samples,
                   min(recorded_at) AS first_at,
                   max(recorded_at) AS last_at,
                   avg(rate) AS avg_rate,
                   max(rate) AS peak_rate,
                   (SELECT recorded_at FROM snap WHERE rate IS NOT NULL
                    ORDER BY rate DESC, recorded_at LIMIT 1) AS peak_at,
                   -- Count-based figures only use complete snapshots (every
                   -- space known); rates already exclude unknown spaces.
                   count(*) FILTER (WHERE unknown = 0)::int AS complete_samples,
                   (avg(occupied) FILTER (WHERE unknown = 0))::float AS avg_occupied,
                   (max(occupied) FILTER (WHERE unknown = 0))::int AS peak_occupied,
                   (min(available) FILTER (WHERE unknown = 0))::int AS min_available
            FROM snap
            """,
            params,
        )

    def daily_summary(self, start, end, tz, zone_id=None):
        cte, params = self._snapshots_cte(start, end, zone_id)
        params["tz"] = tz
        return self.fetch_all(
            cte
            + """
            SELECT (recorded_at AT TIME ZONE %(tz)s)::date AS day,
                   avg(rate) AS avg_rate,
                   max(rate) AS peak_rate,
                   (max(occupied) FILTER (WHERE unknown = 0))::int AS peak_occupied,
                   (min(available) FILTER (WHERE unknown = 0))::int AS min_available,
                   max(capacity)::int AS capacity,
                   count(*)::int AS samples
            FROM snap
            GROUP BY 1
            ORDER BY 1
            """,
            params,
        )

    def hourly_profile(self, start, end, tz, zone_id=None):
        cte, params = self._snapshots_cte(start, end, zone_id)
        params["tz"] = tz
        return self.fetch_all(
            cte
            + """
            SELECT extract(hour FROM recorded_at AT TIME ZONE %(tz)s)::int AS hour,
                   avg(rate) AS avg_rate,
                   count(*)::int AS samples
            FROM snap
            GROUP BY 1
            ORDER BY 1
            """,
            params,
        )

    def zone_comparison(self, start, end):
        where, params = self._range_filter(start, end, None)
        return self.fetch_all(
            f"""
            SELECT zone_id, zone_name, max(camera_name) AS camera_name,
                   avg(occupied::float / NULLIF(capacity - unknown, 0)) AS avg_rate,
                   max(occupied::float / NULLIF(capacity - unknown, 0)) AS peak_rate,
                   avg(occupied)::float AS avg_occupied,
                   max(capacity)::int AS capacity,
                   count(*)::int AS samples
            FROM occupancy_history
            WHERE {where} AND zone_name IS NOT NULL
            GROUP BY zone_id, zone_name
            ORDER BY zone_name
            """,
            params,
        )

    def iter_history_rows(self, start, end, tz, zone_id=None, batch=2000):
        """Stream history rows (oldest first) with a server-side cursor.
        `local_time` is the timestamp in the site's reporting time zone."""
        where, params = self._range_filter(start, end, zone_id)
        params["tz"] = tz
        with self.connection() as conn:
            with conn.cursor(name="history_export", cursor_factory=RealDictCursor) as cur:
                cur.itersize = batch
                cur.execute(
                    f"""
                    SELECT recorded_at, recorded_at AT TIME ZONE %(tz)s AS local_time,
                           camera_name, zone_name, capacity,
                           occupied, available, unknown
                    FROM occupancy_history
                    WHERE {where}
                    ORDER BY recorded_at, zone_name
                    """,
                    params,
                )
                yield from cur

    def delete_history_before(self, before):
        return self.execute(
            "DELETE FROM occupancy_history WHERE recorded_at < %s", (before,)
        )

    def history_stats(self):
        return self.fetch_one(
            """
            SELECT count(*)::int AS records,
                   min(recorded_at) AS oldest,
                   max(recorded_at) AS newest,
                   pg_total_relation_size('occupancy_history')::bigint AS size_bytes
            FROM occupancy_history
            """
        )

    def purge_expired(self, retention_days):
        """Apply data retention. Returns number of deleted history rows."""
        with self.cursor() as cur:
            cur.execute(
                "DELETE FROM occupancy_history WHERE recorded_at < now() - make_interval(days => %s)",
                (retention_days,),
            )
            deleted = cur.rowcount
            cur.execute(
                "DELETE FROM camera_events WHERE recorded_at < now() - make_interval(days => %s)",
                (retention_days,),
            )
            cur.execute("DELETE FROM sessions WHERE expires_at < now()")
        return deleted
