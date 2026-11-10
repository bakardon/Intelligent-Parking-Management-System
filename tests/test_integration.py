"""
End-to-end: video frame -> vehicle detection -> occupancy -> monitoring
service -> PostgreSQL -> API -> dashboard data.

Uses a synthetic video and the pixel-based ColorBlobDetector so the test
needs neither a camera nor the YOLO weights.
"""

import csv
import io
import time

from tests.conftest import make_client, setup_admin
from tests.synthetic import ColorBlobDetector, write_video


def bay(x):
    return [[x, 150], [x + 100, 150], [x + 100, 260], [x, 260]]


# Bays A1..A4 side by side. A1 holds a car; A2 is empty; one car straddles
# A3 and A4 (its ground points fall in both).
SPACES = [{"label": f"A{i + 1}", "polygon": bay(20 + 100 * i)} for i in range(4)]
CARS = [(30, 90, 110, 240), (270, 90, 370, 240)]


def wait_for(fetch, predicate, timeout=40):
    deadline = time.time() + timeout
    value = None
    while time.time() < deadline:
        value = fetch()
        if predicate(value):
            return value
        time.sleep(0.25)
    raise AssertionError(f"condition not met; last value: {value}")


def test_video_to_dashboard_pipeline(db, video_dir):
    write_video(video_dir / "lot.avi", CARS, frames=50, fps=10)
    with make_client(db, monitor_enabled=True, detector_factory=ColorBlobDetector) as client:
        setup_admin(client)
        assert client.put("/api/settings", json={
            "processing_interval_seconds": 0.2, "history_length": 3, "occupied_threshold": 2,
            "snapshot_interval_seconds": 3600}).status_code == 200

        camera = client.post("/api/cameras", json={
            "name": "Demo", "location": "Test", "source_type": "file", "source_url": "lot.avi",
            "rtsp_transport": "tcp", "enabled": True}).json()
        zone = client.post("/api/zones", json={"name": "Level 1", "area": "L1",
                                               "camera_id": camera["id"]}).json()
        saved = client.put(f"/api/zones/{zone['id']}/layout", json={
            "frame_width": 640, "frame_height": 360, "spaces": SPACES})
        assert saved.status_code == 200, saved.text

        status = wait_for(lambda: client.get("/api/status").json(),
                          lambda s: s["site"]["unknown"] == 0 and s["site"]["capacity"] == 4)
        states = {s["label"]: s["state"] for s in status["zones"][0]["spaces"]}
        assert states == {"A1": "occupied", "A2": "available", "A3": "occupied", "A4": "occupied"}
        assert status["site"]["occupied"] == 3 and status["site"]["available"] == 1
        assert status["site"]["occupancy_rate"] == 0.75
        assert status["cameras"][0]["state"] == "online"
        assert status["cameras"][0]["frames_processed"] > 0

        # Monitoring service -> database
        monitor = client.app.state.monitor
        assert monitor.write_snapshot() == 1

        # Database -> API
        page = client.get("/api/history").json()
        assert page["total"] == 1
        record = page["items"][0]
        assert (record["capacity"], record["occupied"], record["available"], record["unknown"]) == (4, 3, 1, 0)
        assert record["zone_name"] == "Level 1" and record["camera_name"] == "Demo"

        analytics = client.get("/api/analytics").json()
        assert analytics["summary"]["samples"] == 1
        assert analytics["summary"]["peak_rate"] == 0.75

        rows = list(csv.reader(io.StringIO(client.get("/api/reports/occupancy.csv").text)))
        assert rows[1][2:8] == ["Demo", "Level 1", "4", "3", "1", "0"]

        legacy = client.get("/status").json()
        assert legacy["spaces"] == {"A1": True, "A2": False, "A3": True, "A4": True}

        snapshot = client.get(f"/api/cameras/{camera['id']}/snapshot", params={"overlay": True})
        assert snapshot.status_code == 200 and snapshot.content[:2] == b"\xff\xd8"

        # Disabling the camera makes its spaces "camera unavailable", not stale numbers.
        client.patch(f"/api/cameras/{camera['id']}", json={"enabled": False})
        status = wait_for(lambda: client.get("/api/status").json(),
                          lambda s: s["site"]["unknown"] == 4)
        assert status["site"]["occupied"] == 0
        assert {s["state"] for s in status["zones"][0]["spaces"]} == {"camera_unavailable"}
