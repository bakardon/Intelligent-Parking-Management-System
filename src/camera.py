"""
Per-camera capture and processing.

Each enabled camera gets one `CameraWorker` with two threads:

* reader    – opens the source (RTSP stream or local demo video), keeps
               the connection alive, reconnects with exponential back-off
               and keeps only the *latest* decoded frame in memory.
               Frames are grabbed continuously (so an RTSP buffer never
               lags behind real time) but only converted to images at the
               processing rate.
* processor – every `processing_interval_seconds` runs vehicle detection
               on the latest frame and updates the occupancy engine.
               A frame is never processed twice; a frame older than
               `stale_after_seconds` turns every space of the camera into
               *unknown*.

Frames are never written to disk.
"""

import logging
import os
import threading
import time
from datetime import datetime, timezone

import cv2
import numpy as np

from src import security
from src.occupancy import (
    AVAILABLE,
    OCCUPIED,
    UNKNOWN,
    ParkingOccupancy,
    get_vehicle_ground_points,
    scale_polygon,
)


log = logging.getLogger(__name__)

# Camera states
DISABLED = "disabled"
CONNECTING = "connecting"
ONLINE = "online"
OFFLINE = "offline"
STALE = "stale"

OPEN_TIMEOUT_MS = 10_000
READ_TIMEOUT_MS = 10_000

# OPENCV_FFMPEG_CAPTURE_OPTIONS is process-global and read when a capture
# is opened, so opening is serialised.
_open_lock = threading.Lock()


def _now():
    return datetime.now(timezone.utc)


def open_capture(source, source_type, rtsp_transport="tcp"):
    """Open a video source with timeouts. Returns an opened VideoCapture."""
    if source_type == "file":
        if not os.path.isfile(source):
            raise ConnectionError(f"Video file not found: {os.path.basename(source)}")
        cap = cv2.VideoCapture(source)
    else:
        with _open_lock:
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = f"rtsp_transport;{rtsp_transport}"
            cap = cv2.VideoCapture(
                source,
                cv2.CAP_FFMPEG,
                [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, OPEN_TIMEOUT_MS,
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC, READ_TIMEOUT_MS,
                ],
            )
    if not cap.isOpened():
        cap.release()
        raise ConnectionError("Could not open the video stream (check address, credentials and network)")
    return cap


def probe_source(source, source_type, rtsp_transport="tcp"):
    """Connect, read one frame and disconnect. Returns (width, height)."""
    cap = open_capture(source, source_type, rtsp_transport)
    try:
        ok, frame = cap.read()
        if not ok or frame is None:
            raise ConnectionError("Connected, but no video frame was received")
        return frame.shape[1], frame.shape[0], frame
    finally:
        cap.release()


class CameraWorker:
    def __init__(self, camera, zones, detector, settings, on_event=None, previous_state=None):
        self.camera = camera
        self.camera_id = camera["id"]
        self.zones = [z for z in zones if z["camera_id"] == camera["id"]]
        self.detector = detector
        self.on_event = on_event

        self.processing_interval = settings.processing_interval_seconds
        self.stale_after = settings.stale_after_seconds
        self.reconnect_min = settings.reconnect_min_seconds
        self.reconnect_max = settings.reconnect_max_seconds
        self.history_length = settings.history_length
        self.occupied_threshold = settings.occupied_threshold

        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._threads = []

        # Shared state (guarded by _lock)
        self._frame = None
        self._frame_at = 0.0  # monotonic time the frame was decoded
        self._frame_seq = 0
        self._last_grab_at = 0.0
        self._vehicles = []
        self._occupancy = None
        self._occupancy_size = None

        self.state = CONNECTING
        self.message = ""
        # State last recorded as an event (carried over when the worker is
        # restarted after a configuration change, to avoid duplicate events).
        self._reported_state = previous_state
        self.connected_since = None
        self.last_frame_at = None  # wall clock, for display
        self.last_processed_at = None
        self.frame_size = None
        self.reconnect_attempts = 0
        self.frames_processed = 0
        self.detector_error = None

        self._spaces = [
            {"id": space["id"], "label": space["label"], "zone_id": zone["id"], "polygon": space["polygon"],
             "ref_size": (zone["frame_width"], zone["frame_height"]) if zone["frame_width"] else None}
            for zone in self.zones
            for space in zone["spaces"]
        ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        for name, target in (("reader", self._reader_loop), ("processor", self._processor_loop)):
            thread = threading.Thread(
                target=target, name=f"camera-{self.camera_id}-{name}", daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def stop(self, timeout=5):
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=timeout)

    def apply_live_settings(self, settings):
        self.processing_interval = settings.processing_interval_seconds
        self.stale_after = settings.stale_after_seconds
        self.reconnect_min = settings.reconnect_min_seconds
        self.reconnect_max = settings.reconnect_max_seconds

    def _set_state(self, state, message=""):
        message = security.redact(message)
        if state == self.state and message == self.message:
            return
        previous = self.state
        self.state = state
        self.message = message
        # Only connectivity changes are logged/recorded, not the transient
        # "connecting" phase, and repeated failures are recorded once.
        if state != previous and state in (ONLINE, OFFLINE, STALE) and state != self._reported_state:
            self._reported_state = state
            level = logging.WARNING if state in (OFFLINE, STALE) else logging.INFO
            log.log(level, "Camera %s (%s): %s%s", self.camera_id, self.camera["name"], state,
                    f" - {message}" if message else "")
            if self.on_event:
                try:
                    self.on_event(self.camera_id, state, message)
                except Exception:  # never let event logging break capture
                    log.exception("Could not record camera event")

    # ------------------------------------------------------------------
    # Reader
    # ------------------------------------------------------------------

    def _reader_loop(self):
        attempt = 0
        source_type = self.camera["source_type"]
        while not self._stop.is_set():
            if self.state not in (OFFLINE, STALE):
                # A camera that is already failing stays "offline" while it
                # retries, so it never looks healthy before it delivers video.
                self._set_state(CONNECTING, "")
            try:
                cap = open_capture(self.camera["source"], source_type, self.camera.get("rtsp_transport", "tcp"))
            except Exception as error:
                attempt += 1
                self.reconnect_attempts = attempt
                delay = min(self.reconnect_max, self.reconnect_min * (2 ** (attempt - 1)))
                self._set_state(OFFLINE, f"{error}. Retrying in {delay:.0f}s")
                self._stop.wait(delay)
                continue

            attempt = 0
            self.reconnect_attempts = 0
            self.connected_since = _now()
            try:
                self._read_frames(cap, source_type)
            except Exception as error:
                log.warning("Camera %s read error: %s", self.camera_id, security.redact(error))
            finally:
                cap.release()
            if not self._stop.is_set():
                attempt += 1
                self.reconnect_attempts = attempt
                delay = min(self.reconnect_max, self.reconnect_min * (2 ** (attempt - 1)))
                self._set_state(OFFLINE, f"Stream interrupted. Reconnecting in {delay:.0f}s")
                self._stop.wait(delay)
        self.state, self.message = OFFLINE, "Stopped"

    def _read_frames(self, cap, source_type):
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        is_file = source_type == "file"
        frame_period = 1.0 / fps if is_file and 0 < fps <= 120 else 0
        next_due = time.monotonic()
        last_retrieve = 0.0
        while not self._stop.is_set():
            if frame_period:
                # Play demo files at their native speed (a real camera
                # delivers frames in real time on its own).
                next_due += frame_period
                delay = next_due - time.monotonic()
                if delay > 0:
                    self._stop.wait(delay)
                elif delay < -1:
                    next_due = time.monotonic()

            if not cap.grab():
                if is_file:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # loop the demo video
                    if cap.grab():
                        continue
                return  # stream ended or failed -> reconnect

            now = time.monotonic()
            self._last_grab_at = now
            if now - last_retrieve < self.processing_interval * 0.9:
                continue
            ok, frame = cap.retrieve()
            if not ok or frame is None:
                continue
            last_retrieve = now
            with self._lock:
                self._frame = frame
                self._frame_at = now
                self._frame_seq += 1
            self.last_frame_at = _now()
            self.frame_size = (frame.shape[1], frame.shape[0])
            if self.state != ONLINE:
                self._set_state(ONLINE, "")

    # ------------------------------------------------------------------
    # Processor
    # ------------------------------------------------------------------

    def _build_occupancy(self, size):
        polygons = [scale_polygon(s["polygon"], s["ref_size"], size) for s in self._spaces]
        self._occupancy = ParkingOccupancy(
            parking_spaces=polygons,
            history_length=self.history_length,
            occupied_threshold=self.occupied_threshold,
            space_ids=[s["id"] for s in self._spaces],
        )
        self._occupancy_size = size

    def _processor_loop(self):
        last_seq = 0
        while not self._stop.wait(self.processing_interval):
            with self._lock:
                frame, frame_at, seq = self._frame, self._frame_at, self._frame_seq

            now = time.monotonic()
            if frame is None or now - frame_at > self.stale_after:
                self._mark_unknown()
                if self.state == ONLINE and now - self._last_grab_at > self.stale_after:
                    self._set_state(STALE, f"No frames for more than {self.stale_after}s")
                continue
            if seq == last_seq:
                continue  # never process the same frame twice
            last_seq = seq

            if not self._spaces:
                self.last_processed_at = _now()
                continue
            if self.detector is None:
                self._mark_unknown()
                continue

            size = (frame.shape[1], frame.shape[0])
            if self._occupancy is None or self._occupancy_size != size:
                self._build_occupancy(size)
            try:
                vehicles = self.detector.detect(frame)
            except Exception as error:
                self.detector_error = str(error)
                log.exception("Detection failed for camera %s", self.camera_id)
                continue
            self.detector_error = None
            with self._lock:
                self._vehicles = vehicles
                self._occupancy.update(vehicles)
            self.frames_processed += 1
            self.last_processed_at = _now()

    def _mark_unknown(self):
        with self._lock:
            if self._occupancy is not None:
                self._occupancy.reset()
            self._vehicles = []

    # ------------------------------------------------------------------
    # Read side (API thread)
    # ------------------------------------------------------------------

    def is_available(self):
        return self.state == ONLINE

    def space_states(self):
        """{space_id: occupied|available|unknown|camera_unavailable}"""
        if not self.is_available():
            return {s["id"]: "camera_unavailable" for s in self._spaces}
        with self._lock:
            if self._occupancy is None:
                return {s["id"]: UNKNOWN for s in self._spaces}
            return {
                space_id: self._occupancy.space_state(index)
                for index, space_id in enumerate(self._occupancy.space_ids)
            }

    def health(self):
        return {
            "state": self.state,
            "message": self.message,
            "last_frame_at": self.last_frame_at,
            "last_processed_at": self.last_processed_at,
            "connected_since": self.connected_since if self.state == ONLINE else None,
            "frame_size": list(self.frame_size) if self.frame_size else None,
            "reconnect_attempts": self.reconnect_attempts,
            "frames_processed": self.frames_processed,
            "detector_error": self.detector_error,
        }

    def latest_frame(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def render_snapshot(self, overlay=False):
        """JPEG of the latest frame. `overlay` draws the installer debug view."""
        with self._lock:
            if self._frame is None:
                return None
            frame = self._frame.copy()
            vehicles = list(self._vehicles)
            occupancy = self._occupancy
            detected = list(occupancy.last_detected) if occupancy else []
            states = (
                [occupancy.space_state(i) for i in range(len(occupancy.space_ids))] if occupancy else []
            )
            polygons = occupancy.parking_spaces if occupancy else []
        if overlay:
            draw_debug_overlay(frame, self._spaces, polygons, states, detected, vehicles)
        ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buffer.tobytes() if ok else None


_STATE_COLOURS = {  # BGR
    OCCUPIED: (60, 60, 220),
    AVAILABLE: (80, 180, 60),
    UNKNOWN: (150, 150, 150),
}


def draw_debug_overlay(frame, spaces, polygons, states, detected, vehicles):
    """Installer view: space polygons, smoothed state, raw per-frame hit,
    vehicle boxes and ground-contact points. No tracking IDs."""
    for vehicle in vehicles:
        x1, y1, x2, y2 = vehicle["box"]
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 220, 255), 1)
        cv2.putText(frame, f'{vehicle["class"]} {vehicle["confidence"]:.2f}', (x1, max(12, y1 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 220, 255), 1, cv2.LINE_AA)
        for point in get_vehicle_ground_points(vehicle["box"]):
            cv2.circle(frame, point, 3, (255, 0, 255), -1)
    for index, polygon in enumerate(polygons):
        state = states[index] if index < len(states) else UNKNOWN
        colour = _STATE_COLOURS[state]
        pts = np.array(polygon, dtype=np.int32)
        cv2.polylines(frame, [pts], True, colour, 2)
        cx, cy = int(pts[:, 0].mean()), int(pts[:, 1].mean())
        hit = "*" if index < len(detected) and detected[index] else ""
        label = f'{spaces[index]["label"]}{hit}'
        cv2.putText(frame, label, (cx - 14, cy + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(frame, label, (cx - 14, cy + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1, cv2.LINE_AA)
