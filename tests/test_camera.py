"""Camera worker: capture, disconnection, reconnection, staleness."""

import threading
import time
from types import SimpleNamespace

import numpy as np

from src import camera as camera_module
from src.camera import OFFLINE, ONLINE, STALE, CameraWorker
from tests.synthetic import ColorBlobDetector, write_video


SPACE = [[100, 100], [200, 100], [200, 200], [100, 200]]
CAR_IN_SPACE = (110, 60, 190, 190)  # ground points at y=177, inside SPACE


def settings(**overrides):
    values = dict(processing_interval_seconds=0.1, stale_after_seconds=1, reconnect_min_seconds=1,
                  reconnect_max_seconds=2, history_length=3, occupied_threshold=2)
    values.update(overrides)
    return SimpleNamespace(**values)


def camera_row(source, source_type="file"):
    return {"id": 1, "name": "Test cam", "source_type": source_type, "source": str(source),
            "rtsp_transport": "tcp", "enabled": True}


def zones():
    return [{"id": 10, "camera_id": 1, "frame_width": 640, "frame_height": 360,
             "spaces": [{"id": 100, "label": "A1", "polygon": SPACE}]}]


def wait_for(predicate, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_file_source_goes_online_and_detects(tmp_path):
    video = write_video(tmp_path / "lot.avi", [CAR_IN_SPACE])
    events = []
    worker = CameraWorker(camera_row(video), zones(), ColorBlobDetector(), settings(),
                          on_event=lambda *e: events.append(e))
    worker.start()
    try:
        assert wait_for(lambda: worker.space_states() == {100: "occupied"})
        assert worker.health()["state"] == ONLINE
        assert worker.health()["frame_size"] == [640, 360]
        jpeg = worker.render_snapshot(overlay=True)
        assert jpeg[:2] == b"\xff\xd8"
    finally:
        worker.stop()
    assert (1, ONLINE, "") in events


def test_missing_source_is_offline_then_reconnects(tmp_path):
    video = tmp_path / "later.avi"
    worker = CameraWorker(camera_row(video), zones(), ColorBlobDetector(), settings())
    worker.start()
    try:
        assert wait_for(lambda: worker.state == OFFLINE)
        assert "not found" in worker.message
        assert worker.space_states() == {100: "camera_unavailable"}
        write_video(video, [CAR_IN_SPACE])  # the "camera" comes back
        assert wait_for(lambda: worker.state == ONLINE, timeout=20)
        assert wait_for(lambda: worker.space_states() == {100: "occupied"})
    finally:
        worker.stop()


def test_unreachable_rtsp_is_offline_and_credentials_redacted():
    url = "rtsp://admin:Do-not-log-me@127.0.0.1:9/stream"
    events = []
    worker = CameraWorker(camera_row(url, "rtsp"), zones(), ColorBlobDetector(),
                          settings(reconnect_min_seconds=5, reconnect_max_seconds=5),
                          on_event=lambda *e: events.append(e))
    worker.start()
    try:
        assert wait_for(lambda: worker.state == OFFLINE, timeout=20)
        assert worker.reconnect_attempts >= 1
        assert "Do-not-log-me" not in worker.message
        assert all("Do-not-log-me" not in str(e) for e in events)
    finally:
        worker.stop()


def _processor_only(worker):
    thread = threading.Thread(target=worker._processor_loop, daemon=True)
    thread.start()
    return thread


def _push_frame(worker, frame):
    with worker._lock:
        worker._frame = frame
        worker._frame_at = time.monotonic()
        worker._frame_seq += 1
    worker._last_grab_at = time.monotonic()


def _frame_with_car():
    frame = np.full((360, 640, 3), 90, dtype=np.uint8)
    x1, y1, x2, y2 = CAR_IN_SPACE
    frame[y1:y2, x1:x2] = (0, 0, 255)
    return frame


def test_frozen_stream_turns_spaces_unknown():
    worker = CameraWorker(camera_row("unused"), zones(), ColorBlobDetector(), settings())
    worker.state = ONLINE
    _processor_only(worker)
    try:
        for _ in range(6):
            _push_frame(worker, _frame_with_car())
            time.sleep(0.15)
        assert worker.space_states() == {100: "occupied"}
        # No new frames: after stale_after the state must not stay "occupied".
        assert wait_for(lambda: worker.state == STALE, timeout=5)
        assert worker.space_states() == {100: "camera_unavailable"}
        worker.state = ONLINE
        assert worker.space_states() == {100: "unknown"}
    finally:
        worker._stop.set()


def test_same_frame_is_never_processed_twice():
    detector = ColorBlobDetector()
    worker = CameraWorker(camera_row("unused"), zones(), detector, settings(stale_after_seconds=30))
    worker.state = ONLINE
    _processor_only(worker)
    try:
        _push_frame(worker, _frame_with_car())
        time.sleep(1.0)  # ~10 processing intervals
        assert detector.calls == 1
    finally:
        worker._stop.set()


def test_detector_failure_does_not_kill_worker():
    class Broken(ColorBlobDetector):
        def detect(self, frame):
            self.calls += 1
            raise RuntimeError("model crashed")

    detector = Broken()
    worker = CameraWorker(camera_row("unused"), zones(), detector, settings(stale_after_seconds=30))
    worker.state = ONLINE
    thread = _processor_only(worker)
    try:
        for _ in range(3):
            _push_frame(worker, _frame_with_car())
            time.sleep(0.2)
        assert detector.calls == 3 and thread.is_alive()
        assert worker.health()["detector_error"] == "model crashed"
    finally:
        worker._stop.set()


def test_open_capture_sets_rtsp_transport(monkeypatch):
    seen = {}

    class FakeCapture:
        def __init__(self, *args):
            seen["options"] = camera_module.os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS")

        def isOpened(self):
            return False

        def release(self):
            pass

    monkeypatch.setattr(camera_module.cv2, "VideoCapture", FakeCapture)
    try:
        camera_module.open_capture("rtsp://cam/stream", "rtsp", "udp")
    except ConnectionError:
        pass
    assert seen["options"] == "rtsp_transport;udp"
