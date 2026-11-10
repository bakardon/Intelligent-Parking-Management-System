"""
Shared fixtures.

Database tests run against a separate database (default `parksight_test`,
override with PARKSIGHT_TEST_DB_NAME) that is dropped and re-created for
every test session. They are skipped when PostgreSQL is not reachable.
The production database named in DB_NAME is never touched.
"""

import os

import psycopg2
import pytest
from psycopg2 import sql

from src import config


TEST_DB_NAME = os.getenv("PARKSIGHT_TEST_DB_NAME", "parksight_test")
CSRF = {"X-Requested-With": "ParkSight"}
ADMIN = ("admin", "Admin-Passw0rd")
VIEWER = ("viewer", "Viewer-Passw0rd")


def _admin_connection():
    conn = psycopg2.connect(host=config.DB_HOST, port=config.DB_PORT, dbname="postgres",
                            user=config.DB_USER, password=config.DB_PASSWORD, connect_timeout=3)
    conn.autocommit = True
    return conn


def recreate_database(name):
    assert name != config.DB_NAME, "refusing to use the production database for tests"
    conn = _admin_connection()
    with conn.cursor() as cur:
        cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    conn.close()


@pytest.fixture(scope="session")
def database():
    from src.database import Database

    try:
        recreate_database(TEST_DB_NAME)
    except psycopg2.OperationalError as error:
        pytest.skip(f"PostgreSQL not available: {error}")
    db = Database(dbname=TEST_DB_NAME)
    db.migrate()
    yield db
    db.close()


@pytest.fixture
def db(database):
    with database.cursor() as cur:
        cur.execute(
            "TRUNCATE occupancy_history, camera_events, parking_spaces, zones, cameras, "
            "sessions, users, app_settings RESTART IDENTITY CASCADE"
        )
    return database


@pytest.fixture
def repos(db):
    from src.repositories import Repositories

    return Repositories(db)


@pytest.fixture
def video_dir(tmp_path, monkeypatch):
    directory = tmp_path / "videos"
    directory.mkdir()
    monkeypatch.setattr(config, "VIDEO_DIR", directory)
    return directory


def make_client(db, **kwargs):
    from fastapi.testclient import TestClient

    from src.api import create_app

    app = create_app(database=db, monitor_enabled=kwargs.pop("monitor_enabled", False), **kwargs)
    return TestClient(app, headers=CSRF)


@pytest.fixture
def client(db, video_dir):
    with make_client(db) as test_client:
        yield test_client


def setup_admin(client):
    token = client.app.state.setup_token.value
    response = client.post("/api/auth/setup", json={"setup_token": token, "username": ADMIN[0],
                                                   "password": ADMIN[1]})
    assert response.status_code == 200, response.text
    return response


@pytest.fixture
def admin(client):
    setup_admin(client)
    return client


def login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})
