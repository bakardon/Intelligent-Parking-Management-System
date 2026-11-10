"""Database initialisation, migrations, persistence and history queries."""

from datetime import datetime, timedelta, timezone

import psycopg2
import pytest

from src.database import Database
from tests.conftest import recreate_database


def zone_row(zone_id=None, capacity=10, occupied=4, available=6, unknown=0, name="Zone A"):
    return {"camera_id": None, "zone_id": zone_id, "camera_name": "Cam", "zone_name": name,
            "capacity": capacity, "occupied": occupied, "available": available, "unknown": unknown}


def make_zone(repos, name="Zone A", camera="Cam"):
    camera = repos.create_camera({"name": camera, "location": "", "source_type": "rtsp",
                                  "source_url": "rtsp://10.0.0.1/s", "username": None, "password": None,
                                  "rtsp_transport": "tcp", "enabled": True})
    return repos.create_zone({"camera_id": camera["id"], "name": name, "area": ""})


def test_connectivity(db):
    assert db.ping()
    assert db.fetch_one("SELECT current_database() AS name")["name"].endswith("_test")


def test_migrations_are_idempotent(db):
    assert db.migrate() == []
    assert db.schema_version() == "002_product_schema"


def test_upgrade_preserves_legacy_history():
    """An installation created by the original code is upgraded in place."""
    name = "parksight_test_upgrade"
    recreate_database(name)
    legacy = Database(dbname=name, options="-c timezone=Asia/Karachi")
    with legacy.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE occupancy_history (
                id SERIAL PRIMARY KEY, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                capacity INTEGER NOT NULL, occupied INTEGER NOT NULL, available INTEGER NOT NULL);
            INSERT INTO occupancy_history (timestamp, capacity, occupied, available)
            VALUES ('2026-09-19 19:55:21', 6, 4, 2), ('2026-09-19 19:55:31', 6, 0, 6);
            """
        )
    legacy.close()

    upgraded = Database(dbname=name, options="-c timezone=Asia/Karachi")
    assert upgraded.migrate() == ["001_baseline", "002_product_schema"]
    rows = upgraded.get_history(limit=10)
    assert [(r["capacity"], r["occupied"], r["available"]) for r in rows] == [(6, 0, 6), (6, 4, 2)]
    # 19:55:31 Karachi time (UTC+5) is 14:55:31 UTC.
    assert rows[0]["timestamp"] == datetime(2026, 9, 19, 14, 55, 31, tzinfo=timezone.utc)
    upgraded.close()


def test_snapshot_insert_and_duplicate_protection(db, repos):
    zone = make_zone(repos)
    at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert db.insert_snapshot(at, [zone_row(zone["id"])]) == 1
    assert db.insert_snapshot(at, [zone_row(zone["id"], occupied=5, available=5)]) == 0
    total, items = db.list_history(at - timedelta(hours=1), at + timedelta(hours=1))
    assert total == 1 and items[0]["occupied"] == 4


def test_inconsistent_counts_rejected(db, repos):
    zone = make_zone(repos)
    at = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        db.insert_snapshot(at, [zone_row(zone["id"], occupied=5, available=6)])
    with pytest.raises(psycopg2.errors.CheckViolation):
        db.execute("INSERT INTO occupancy_history (capacity, occupied, available) VALUES (1, 1, 1)")


def test_snapshot_is_atomic(db, repos):
    zone = make_zone(repos)
    at = datetime.now(timezone.utc)
    bad = zone_row(999999)  # foreign key violation on the second row
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        db.insert_snapshot(at, [zone_row(zone["id"]), bad])
    assert db.list_history(at - timedelta(minutes=1), at + timedelta(minutes=1))[0] == 0


def test_data_persists_across_connections(db, repos):
    zone = make_zone(repos)
    at = datetime.now(timezone.utc).replace(microsecond=0)
    db.insert_snapshot(at, [zone_row(zone["id"])])
    other = Database(**db.params)
    try:
        assert other.list_history(at - timedelta(minutes=1), at + timedelta(minutes=1))[0] == 1
        assert other.fetch_one("SELECT name FROM zones")["name"] == "Zone A"
    finally:
        other.close()


def test_pool_recovers_after_connection_loss(db):
    with db.connection() as conn:
        pid = conn.get_backend_pid()
    other = Database(**db.params)
    other.execute("SELECT pg_terminate_backend(%s)", (pid,))
    other.close()
    with pytest.raises(psycopg2.OperationalError):
        db.fetch_one("SELECT 1 AS ok")  # the dead connection is discarded...
    assert db.fetch_one("SELECT 1 AS ok")["ok"] == 1  # ...and replaced


def test_analytics_queries(db, repos):
    a = make_zone(repos, "Zone A", "Cam A")
    b = make_zone(repos, "Zone B", "Cam B")
    base = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)
    for minute, (occ_a, occ_b) in enumerate([(2, 1), (4, 3), (10, 5)]):
        at = base + timedelta(minutes=minute)
        db.insert_snapshot(at, [
            zone_row(a["id"], 10, occ_a, 10 - occ_a, name="Zone A"),
            zone_row(b["id"], 10, occ_b, 10 - occ_b, name="Zone B"),
        ])
    start, end = base - timedelta(hours=1), base + timedelta(hours=1)

    summary = db.occupancy_summary(start, end)
    assert summary["samples"] == 3
    assert summary["peak_occupied"] == 15
    assert summary["peak_rate"] == pytest.approx(0.75)
    assert summary["avg_rate"] == pytest.approx((3 / 20 + 7 / 20 + 15 / 20) / 3)
    assert summary["peak_at"] == base + timedelta(minutes=2)

    series = db.occupancy_series(start, end, 3600)
    assert len(series) == 1 and series[0]["samples"] == 3

    daily = db.daily_summary(start, end, "Asia/Karachi")
    assert len(daily) == 1 and daily[0]["peak_occupied"] == 15 and daily[0]["min_available"] == 5

    zones = {z["zone_name"]: z for z in db.zone_comparison(start, end)}
    assert zones["Zone A"]["peak_rate"] == pytest.approx(1.0)
    assert zones["Zone B"]["avg_rate"] == pytest.approx(0.3)

    only_b = db.occupancy_summary(start, end, zone_id=b["id"])
    assert only_b["peak_occupied"] == 5


def test_unknown_spaces_excluded_from_rate(db, repos):
    zone = make_zone(repos)
    at = datetime(2026, 3, 1, tzinfo=timezone.utc)
    db.insert_snapshot(at, [zone_row(zone["id"], capacity=10, occupied=2, available=3, unknown=5)])
    summary = db.occupancy_summary(at - timedelta(minutes=1), at + timedelta(minutes=1))
    assert summary["avg_rate"] == pytest.approx(0.4)
    # Counts from a snapshot with unknown spaces would understate occupancy
    # and availability, so they are not reported.
    assert summary["complete_samples"] == 0
    assert summary["min_available"] is None and summary["peak_occupied"] is None


def test_empty_range_returns_no_fabricated_values(db):
    now = datetime.now(timezone.utc)
    summary = db.occupancy_summary(now - timedelta(days=1), now)
    assert summary["samples"] == 0
    assert summary["avg_rate"] is None and summary["peak_rate"] is None


def test_retention_and_delete(db, repos):
    zone = make_zone(repos)
    now = datetime.now(timezone.utc)
    db.insert_snapshot(now - timedelta(days=40), [zone_row(zone["id"])])
    db.insert_snapshot(now - timedelta(days=5), [zone_row(zone["id"])])
    assert db.purge_expired(30) == 1
    assert db.history_stats()["records"] == 1
    assert db.delete_history_before(now) == 1
    assert db.history_stats()["records"] == 0


def test_history_keeps_names_after_zone_deleted(db, repos):
    zone = make_zone(repos)
    at = datetime.now(timezone.utc)
    db.insert_snapshot(at, [zone_row(zone["id"])])
    repos.delete_zone(zone["id"])
    _total, items = db.list_history(at - timedelta(minutes=1), at + timedelta(minutes=1))
    assert items[0]["zone_id"] is None and items[0]["zone_name"] == "Zone A"


def test_csv_rows_stream(db, repos):
    zone = make_zone(repos)
    at = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    db.insert_snapshot(at, [zone_row(zone["id"])])
    rows = list(db.iter_history_rows(at - timedelta(hours=1), at + timedelta(hours=1), "Asia/Karachi"))
    assert len(rows) == 1
    assert rows[0]["local_time"] == datetime(2026, 5, 1, 15, 0)
