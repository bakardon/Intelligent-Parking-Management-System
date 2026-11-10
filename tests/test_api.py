"""API behaviour: auth, roles, validation, cameras, zones, history, reports."""

import csv
import io
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import ADMIN, CSRF, VIEWER, login, setup_admin


RTSP = {"name": "Entrance", "location": "Gate 1", "source_type": "rtsp",
        "source_url": "rtsp://operator:Sup3r-secret@192.168.10.20:554/Streaming/101",
        "rtsp_transport": "tcp", "enabled": False}


def make_viewer(admin_client):
    response = admin_client.post("/api/users", json={"username": VIEWER[0], "password": VIEWER[1],
                                                    "role": "viewer"})
    assert response.status_code == 201, response.text


def square(x, y, size=50):
    return [[x, y], [x + size, y], [x + size, y + size], [x, y + size]]


# --- Setup and authentication ------------------------------------------------

def test_health_is_public(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["database"] is True


def test_everything_else_requires_sign_in(client):
    for path in ("/api/status", "/status", "/history", "/api/cameras", "/api/zones",
                 "/api/analytics", "/api/reports/occupancy.csv", "/api/settings", "/api/users"):
        assert client.get(path).status_code == 401, path


def test_setup_requires_token_and_only_works_once(client):
    assert client.get("/api/auth/state").json()["setup_required"] is True
    bad = client.post("/api/auth/setup", json={"setup_token": "wrong", "username": "admin",
                                               "password": ADMIN[1]})
    assert bad.status_code == 403
    weak = client.post("/api/auth/setup", json={"setup_token": client.app.state.setup_token.value,
                                                "username": "admin", "password": "short"})
    assert weak.status_code == 422
    setup_admin(client)
    assert client.get("/api/auth/state").json()["user"]["role"] == "admin"
    again = client.post("/api/auth/setup", json={"setup_token": "x", "username": "other",
                                                 "password": ADMIN[1]})
    assert again.status_code == 409


def test_login_logout(admin):
    admin.post("/api/auth/logout")
    assert admin.get("/api/auth/me").status_code == 401
    assert login(admin, "admin", "wrong-Password1").status_code == 401
    assert login(admin, "ADMIN", ADMIN[1]).status_code == 200  # case-insensitive username
    assert admin.get("/api/auth/me").json()["username"] == "admin"


def test_session_cookie_flags(client):
    response = setup_admin(client)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_login_throttling(admin):
    admin.post("/api/auth/logout")
    for _ in range(5):
        assert login(admin, "admin", "wrong-Password1").status_code == 401
    assert login(admin, "admin", ADMIN[1]).status_code == 429


def test_state_changing_requests_require_csrf_header(admin):
    response = admin.post("/api/zones", json={"name": "X", "camera_id": 1},
                          headers={"X-Requested-With": ""})
    assert response.status_code == 403


def test_viewer_cannot_use_admin_routes(admin):
    make_viewer(admin)
    admin.post("/api/auth/logout")
    assert login(admin, *VIEWER).status_code == 200
    assert admin.get("/api/status").status_code == 200
    assert admin.get("/api/cameras").status_code == 200
    assert admin.post("/api/cameras", json=RTSP).status_code == 403
    assert admin.put("/api/settings", json={"retention_days": 5}).status_code == 403
    assert admin.get("/api/users").status_code == 403
    assert admin.get("/api/cameras/1/snapshot").status_code == 403
    assert admin.post("/api/history/delete", json={"before": "2026-01-01T00:00:00Z",
                                                   "confirm": "DELETE"}).status_code == 403


def test_last_admin_cannot_be_removed(admin):
    me = admin.get("/api/auth/me").json()
    assert admin.patch(f"/api/users/{me['id']}", json={"role": "viewer"}).status_code == 409
    assert admin.delete(f"/api/users/{me['id']}").status_code == 409


def test_deactivated_user_loses_session(admin):
    make_viewer(admin)
    viewer_id = next(u["id"] for u in admin.get("/api/users").json() if u["username"] == "viewer")
    from fastapi.testclient import TestClient

    other = TestClient(admin.app, headers=CSRF)
    assert login(other, *VIEWER).status_code == 200
    assert admin.patch(f"/api/users/{viewer_id}", json={"active": False}).status_code == 200
    assert other.get("/api/status").status_code == 401


def test_password_change(admin):
    response = admin.post("/api/auth/password", json={"current_password": ADMIN[1],
                                                      "new_password": "New-Passw0rd-123"})
    assert response.status_code == 200
    admin.post("/api/auth/logout")
    assert login(admin, *ADMIN).status_code == 401
    assert login(admin, "admin", "New-Passw0rd-123").status_code == 200


# --- Cameras ---------------------------------------------------------------

def test_camera_credentials_are_never_returned(admin, db):
    response = admin.post("/api/cameras", json=RTSP)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source_url"] == "rtsp://192.168.10.20:554/Streaming/101"
    assert body["username"] == "operator" and body["has_password"] is True
    assert "Sup3r-secret" not in response.text
    listing = admin.get("/api/cameras").text
    assert "Sup3r-secret" not in listing
    stored = db.fetch_one("SELECT password_encrypted FROM cameras")["password_encrypted"]
    assert stored and "Sup3r-secret" not in stored


def test_camera_update_keeps_or_clears_password(admin):
    camera = admin.post("/api/cameras", json=RTSP).json()
    update = {**RTSP, "source_url": "rtsp://192.168.10.21/stream", "username": "operator"}
    kept = admin.put(f"/api/cameras/{camera['id']}", json=update).json()
    assert kept["has_password"] is True and kept["source_url"] == "rtsp://192.168.10.21/stream"
    cleared = admin.put(f"/api/cameras/{camera['id']}", json={**update, "password": ""}).json()
    assert cleared["has_password"] is False


def test_camera_enable_disable_delete(admin):
    camera = admin.post("/api/cameras", json=RTSP).json()
    assert camera["status"]["state"] == "disabled"
    enabled = admin.patch(f"/api/cameras/{camera['id']}", json={"enabled": True}).json()
    assert enabled["enabled"] is True
    assert admin.delete(f"/api/cameras/{camera['id']}").status_code == 204
    assert admin.get(f"/api/cameras/{camera['id']}").status_code == 404


@pytest.mark.parametrize("payload", [
    {**RTSP, "source_url": "ftp://host/stream"},
    {**RTSP, "source_url": "not a url"},
    {**RTSP, "name": ""},
    {**RTSP, "name": "<script>"},
    {**RTSP, "source_type": "usb"},
    {**RTSP, "extra_field": 1},
    {**RTSP, "source_type": "file", "source_url": "../../etc/passwd"},
    {**RTSP, "source_type": "file", "source_url": "missing.mp4"},
])
def test_invalid_camera_input_rejected(admin, payload):
    assert admin.post("/api/cameras", json=payload).status_code == 422


def test_duplicate_camera_name(admin):
    admin.post("/api/cameras", json=RTSP)
    assert admin.post("/api/cameras", json={**RTSP, "name": "ENTRANCE"}).status_code == 409


def test_camera_connection_test_reports_failure_without_credentials(admin):
    response = admin.post("/api/cameras/test", json={
        "source_type": "rtsp", "source_url": "rtsp://user:Hidden-pass@127.0.0.1:9/none"})
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "Hidden-pass" not in response.text


# --- Zones and layout --------------------------------------------------------

def make_zone(admin, name="Level 1 North", camera_name="Entrance"):
    camera = admin.post("/api/cameras", json={**RTSP, "name": camera_name}).json()
    response = admin.post("/api/zones", json={"name": name, "area": "Level 1", "camera_id": camera["id"]})
    assert response.status_code == 201, response.text
    return camera, response.json()


def test_layout_save_keeps_stable_ids(admin):
    _camera, zone = make_zone(admin)
    layout = {"frame_width": 640, "frame_height": 360,
              "spaces": [{"label": "A1", "polygon": square(0, 0)},
                         {"label": "A2", "polygon": square(60, 0)},
                         {"label": "A3", "polygon": square(120, 0)}]}
    saved = admin.put(f"/api/zones/{zone['id']}/layout", json=layout).json()
    ids = {s["label"]: s["id"] for s in saved["spaces"]}

    # Rename A1<->A2 (swap), move A3, delete nothing, add A4.
    layout2 = {"frame_width": 640, "frame_height": 360, "spaces": [
        {"id": ids["A1"], "label": "A2", "polygon": square(0, 0)},
        {"id": ids["A2"], "label": "A1", "polygon": square(60, 0)},
        {"id": ids["A3"], "label": "A3", "polygon": square(200, 100)},
        {"label": "A4", "polygon": square(300, 100)},
    ]}
    saved2 = admin.put(f"/api/zones/{zone['id']}/layout", json=layout2)
    assert saved2.status_code == 200, saved2.text
    by_id = {s["id"]: s for s in saved2.json()["spaces"]}
    assert by_id[ids["A1"]]["label"] == "A2"
    assert by_id[ids["A3"]]["polygon"][0] == [200, 100]
    assert len(by_id) == 4

    # Deleting: omit A4 and A3.
    layout3 = {**layout2, "spaces": layout2["spaces"][:2]}
    assert len(admin.put(f"/api/zones/{zone['id']}/layout", json=layout3).json()["spaces"]) == 2


@pytest.mark.parametrize("spaces", [
    [{"label": "A1", "polygon": [[0, 0], [10, 0]]}],                       # < 3 points
    [{"label": "A1", "polygon": square(700, 0)}],                          # outside frame
    [{"label": "A1", "polygon": [[0, 0], [10, 10], [20, 20]]}],            # no area
    [{"label": "A1", "polygon": square(0, 0)}, {"label": "a1", "polygon": square(60, 0)}],  # dup label
])
def test_invalid_layouts_rejected(admin, spaces):
    _camera, zone = make_zone(admin)
    response = admin.put(f"/api/zones/{zone['id']}/layout",
                         json={"frame_width": 640, "frame_height": 360, "spaces": spaces})
    assert response.status_code == 422


def test_spaces_cannot_be_moved_between_zones(admin):
    _c, zone_a = make_zone(admin, "Zone A", "Cam A")
    _c, zone_b = make_zone(admin, "Zone B", "Cam B")
    saved = admin.put(f"/api/zones/{zone_a['id']}/layout", json={
        "frame_width": 640, "frame_height": 360, "spaces": [{"label": "A1", "polygon": square(0, 0)}]}).json()
    response = admin.put(f"/api/zones/{zone_b['id']}/layout", json={
        "frame_width": 640, "frame_height": 360,
        "spaces": [{"id": saved["spaces"][0]["id"], "label": "B1", "polygon": square(0, 0)}]})
    assert response.status_code == 409


def test_moving_zone_to_another_camera_clears_its_polygons(admin):
    _camera, zone = make_zone(admin)
    other = admin.post("/api/cameras", json={**RTSP, "name": "Exit"}).json()
    admin.put(f"/api/zones/{zone['id']}/layout", json={
        "frame_width": 640, "frame_height": 360, "spaces": [{"label": "A1", "polygon": square(0, 0)}]})
    moved = admin.put(f"/api/zones/{zone['id']}", json={"name": zone["name"], "area": "",
                                                       "camera_id": other["id"]}).json()
    assert moved["spaces"] == [] and moved["frame_width"] is None


def test_status_reports_camera_unavailable_spaces(admin):
    _camera, zone = make_zone(admin)
    admin.put(f"/api/zones/{zone['id']}/layout", json={
        "frame_width": 640, "frame_height": 360, "spaces": [{"label": "A1", "polygon": square(0, 0)}]})
    admin.app.state.monitor.reload()
    status = admin.get("/api/status").json()
    assert status["site"] == {"capacity": 1, "occupied": 0, "available": 0, "unknown": 1,
                              "occupancy_rate": None}
    assert status["zones"][0]["spaces"][0]["state"] == "camera_unavailable"
    legacy = admin.get("/status").json()
    assert legacy["capacity"] == 1 and legacy["spaces"] == {"A1": None}


# --- Settings ------------------------------------------------------------------

def test_settings_validation(admin):
    assert admin.get("/api/settings").json()["history_length"] == 8
    ok = admin.put("/api/settings", json={"history_length": 10, "occupied_threshold": 6,
                                          "timezone": "Asia/Karachi"})
    assert ok.status_code == 200 and ok.json()["occupied_threshold"] == 6
    assert admin.put("/api/settings", json={"occupied_threshold": 11}).status_code == 422
    assert admin.put("/api/settings", json={"confidence_threshold": 2}).status_code == 422
    assert admin.put("/api/settings", json={"timezone": "Mars/Olympus"}).status_code == 422
    assert admin.put("/api/settings", json={"vehicle_classes": ["bicycle"]}).status_code == 422
    assert admin.get("/api/settings").json()["history_length"] == 10


# --- History, analytics, export -------------------------------------------------

def seed_history(db, zone_id, base, values):
    for minute, occupied in enumerate(values):
        db.insert_snapshot(base + timedelta(minutes=minute), [{
            "camera_id": None, "zone_id": zone_id, "camera_name": "Entrance", "zone_name": "=cmd()",
            "capacity": 10, "occupied": occupied, "available": 10 - occupied, "unknown": 0}])


def test_history_pagination_and_limits(admin, db):
    _camera, zone = make_zone(admin)
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    seed_history(db, zone["id"], base, [1, 2, 3, 4, 5])
    page = admin.get("/api/history", params={"limit": 2, "offset": 1}).json()
    assert page["total"] == 5 and [r["occupied"] for r in page["items"]] == [4, 3]
    assert admin.get("/api/history", params={"limit": 0}).status_code == 422
    assert admin.get("/api/history", params={"limit": 100000}).status_code == 422
    assert admin.get("/api/history", params={"start": "2026-01-02T00:00:00Z",
                                             "end": "2026-01-01T00:00:00Z"}).status_code == 422
    assert admin.get("/api/history", params={"start": "2020-01-01T00:00:00Z",
                                             "end": "2026-01-01T00:00:00Z"}).status_code == 422
    assert admin.get("/api/history", params={"start": "yesterday"}).status_code == 422
    legacy = admin.get("/history", params={"limit": 3}).json()
    assert [r["occupied"] for r in legacy] == [5, 4, 3] and set(legacy[0]) >= {"timestamp", "capacity"}


def test_analytics_empty_and_populated(admin, db):
    empty = admin.get("/api/analytics").json()
    assert empty["summary"]["samples"] == 0 and empty["series"] == [] and empty["daily"] == []
    _camera, zone = make_zone(admin)
    seed_history(db, zone["id"], datetime.now(timezone.utc) - timedelta(minutes=30), [2, 8, 5])
    data = admin.get("/api/analytics").json()
    assert data["summary"]["samples"] == 3
    assert data["summary"]["peak_occupied"] == 8
    assert data["summary"]["avg_rate"] == pytest.approx(0.5)
    assert sum(point["samples"] for point in data["series"]) == 3
    assert data["zones"][0]["capacity"] == 10


def test_csv_export(admin, db):
    _camera, zone = make_zone(admin)
    seed_history(db, zone["id"], datetime.now(timezone.utc) - timedelta(minutes=30), [3, 7])
    response = admin.get("/api/reports/occupancy.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0][2:] == ["camera", "zone", "capacity", "occupied", "available", "unknown",
                           "occupancy_percent"]
    assert [r[5] for r in rows[1:]] == ["3", "7"]
    assert rows[1][3] == "'=cmd()"  # formula injection neutralised
    assert rows[2][8] == "70.0"


def test_delete_history_requires_confirmation(admin, db):
    _camera, zone = make_zone(admin)
    seed_history(db, zone["id"], datetime.now(timezone.utc) - timedelta(days=3), [1])
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert admin.post("/api/history/delete", json={"before": future}).status_code == 422
    response = admin.post("/api/history/delete", json={"before": future, "confirm": "DELETE"})
    assert response.json() == {"deleted": 1}


def test_security_headers(admin):
    response = admin.get("/api/status")
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
