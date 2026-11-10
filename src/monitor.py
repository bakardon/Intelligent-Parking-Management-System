"""
Monitoring service: supervises camera workers, aggregates occupancy per
camera / zone / site, writes periodic history snapshots and applies data
retention.
"""

import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timezone

from src import config
from src.camera import DISABLED, CameraWorker


log = logging.getLogger(__name__)

RETENTION_EVERY_SECONDS = 6 * 3600
CONFIG_POLL_SECONDS = 30


def _signature(camera, zones):
    """Changes to this value require the camera's worker to be restarted."""
    payload = {
        "camera": {k: camera[k] for k in ("source_type", "source", "rtsp_transport", "enabled", "name")},
        "zones": [
            {"id": z["id"], "w": z["frame_width"], "h": z["frame_height"],
             "spaces": [(s["id"], s["polygon"]) for s in z["spaces"]]}
            for z in zones if z["camera_id"] == camera["id"]
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


class ParkingMonitor:
    def __init__(self, database, repositories, detector_factory=None, enabled=True):
        self.database = database
        self.repos = repositories
        self.detector_factory = detector_factory
        self.enabled = enabled

        self.detector = None
        self.detector_error = None
        self.settings = None

        self._workers = {}
        self._signatures = {}
        self._cameras = []
        self._zones = []
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._reload_requested = threading.Event()
        self._thread = None
        self.started_at = None
        self.last_snapshot_at = None
        self.last_snapshot_error = None
        self._last_retention = 0.0
        self._smoothing = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        if self._thread is not None:
            return
        self.started_at = datetime.now(timezone.utc)
        self.settings = self.repos.get_settings()
        if self.enabled:
            self._load_detector()
        self.reload()
        self._thread = threading.Thread(target=self._supervisor_loop, name="monitor", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._reload_requested.set()
        if self._thread:
            self._thread.join(timeout=10)
        with self._lock:
            for worker in self._workers.values():
                worker.stop(timeout=3)
            self._workers.clear()

    def _load_detector(self):
        if self.detector_factory is None:
            from src.detector import VehicleDetector

            self.detector_factory = VehicleDetector
        try:
            self.detector = self.detector_factory(
                confidence=self.settings.confidence_threshold,
                classes=self.settings.vehicle_classes,
            )
            self.detector_error = None
        except Exception as error:
            self.detector = None
            self.detector_error = str(error)
            log.error("Vehicle detector unavailable: %s", error)

    def request_reload(self):
        """Ask the supervisor to re-read configuration (non-blocking)."""
        self._reload_requested.set()

    def reload(self):
        """Re-read configuration and restart only the workers that changed."""
        settings = self.repos.get_settings()
        cameras, zones = self.repos.monitoring_config()
        with self._lock:
            smoothing = (settings.history_length, settings.occupied_threshold)
            smoothing_changed = self._smoothing is not None and smoothing != self._smoothing
            self._smoothing = smoothing
            self.settings = settings
            if self.detector is not None:
                self.detector.configure(settings.confidence_threshold, settings.vehicle_classes)

            wanted = {}
            for camera in cameras:
                if camera["enabled"] and self.enabled:
                    wanted[camera["id"]] = _signature(camera, zones)

            previous_states = {}
            for camera_id in list(self._workers):
                if camera_id not in wanted or wanted[camera_id] != self._signatures.get(camera_id) or smoothing_changed:
                    worker = self._workers.pop(camera_id)
                    worker.stop(timeout=3)
                    previous_states[camera_id] = worker._reported_state
                    self._signatures.pop(camera_id, None)

            for camera in cameras:
                camera_id = camera["id"]
                if camera_id in wanted and camera_id not in self._workers:
                    worker = CameraWorker(camera, zones, self.detector, settings, on_event=self._record_event,
                                          previous_state=previous_states.get(camera_id))
                    worker.start()
                    self._workers[camera_id] = worker
                    self._signatures[camera_id] = wanted[camera_id]
                elif camera_id in self._workers:
                    self._workers[camera_id].apply_live_settings(settings)

            self._cameras = cameras
            self._zones = zones

    def _record_event(self, camera_id, state, message):
        self.repos.add_camera_event(camera_id, state, message)

    # ------------------------------------------------------------------
    # Supervisor: snapshots, retention, config reloads
    # ------------------------------------------------------------------

    def _supervisor_loop(self):
        last_config_poll = time.monotonic()
        while not self._stop.is_set():
            interval = self.settings.snapshot_interval_seconds
            now = time.time()
            next_boundary = (int(now // interval) + 1) * interval
            # Wake at the next snapshot boundary, or earlier for a reload.
            woken = self._reload_requested.wait(timeout=max(0.05, min(next_boundary - now, CONFIG_POLL_SECONDS)))
            if self._stop.is_set():
                break
            try:
                if woken or time.monotonic() - last_config_poll >= CONFIG_POLL_SECONDS:
                    self._reload_requested.clear()
                    last_config_poll = time.monotonic()
                    self.reload()
                if time.time() >= next_boundary:
                    self.write_snapshot(datetime.fromtimestamp(next_boundary, timezone.utc))
                if time.monotonic() - self._last_retention > RETENTION_EVERY_SECONDS:
                    self._last_retention = time.monotonic()
                    deleted = self.database.purge_expired(self.settings.retention_days)
                    if deleted:
                        log.info("Retention: deleted %d history rows older than %d days",
                                 deleted, self.settings.retention_days)
            except Exception as error:
                # A database outage must not stop monitoring.
                log.error("Monitor supervisor error: %s", error)
                time.sleep(1)

    def write_snapshot(self, recorded_at=None):
        recorded_at = recorded_at or datetime.now(timezone.utc)
        status = self.get_status()
        rows = [
            {
                "camera_id": zone["camera_id"],
                "zone_id": zone["id"],
                "camera_name": zone["camera_name"],
                "zone_name": zone["name"],
                "capacity": zone["capacity"],
                "occupied": zone["occupied"],
                "available": zone["available"],
                "unknown": zone["unknown"],
            }
            for zone in status["zones"]
            if zone["capacity"] > 0
        ]
        try:
            inserted = self.database.insert_snapshot(recorded_at, rows)
            self.last_snapshot_at = recorded_at
            self.last_snapshot_error = None
            return inserted
        except Exception as error:
            self.last_snapshot_error = str(error)
            raise

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def camera_health(self, camera_id, enabled=None):
        with self._lock:
            worker = self._workers.get(camera_id)
            camera = next((c for c in self._cameras if c["id"] == camera_id), None)
        if enabled is None and camera is not None:
            enabled = camera["enabled"]
        if enabled is False:
            return {"state": DISABLED, "message": "Camera disabled"}
        if worker is not None:
            return worker.health()
        if not self.enabled:
            return {"state": "not_monitored", "message": "Video processing is switched off on this server"}
        return {"state": "pending", "message": "Waiting for the monitor to start this camera"}

    def worker(self, camera_id):
        with self._lock:
            return self._workers.get(camera_id)

    def get_status(self):
        with self._lock:
            cameras = list(self._cameras)
            zones = list(self._zones)
            workers = dict(self._workers)

        space_states = {}
        for camera_id, worker in workers.items():
            space_states.update(worker.space_states())

        zone_out = []
        site = {"capacity": 0, "occupied": 0, "available": 0, "unknown": 0}
        for zone in zones:
            spaces = []
            counts = {"occupied": 0, "available": 0, "unknown": 0}
            for space in zone["spaces"]:
                state = space_states.get(space["id"], "camera_unavailable")
                counts["occupied" if state == "occupied" else "available" if state == "available" else "unknown"] += 1
                spaces.append({"id": space["id"], "label": space["label"], "state": state,
                               "polygon": space["polygon"]})
            capacity = len(spaces)
            zone_out.append(
                {
                    "id": zone["id"],
                    "name": zone["name"],
                    "area": zone["area"],
                    "camera_id": zone["camera_id"],
                    "camera_name": zone["camera_name"],
                    "frame_width": zone["frame_width"],
                    "frame_height": zone["frame_height"],
                    "capacity": capacity,
                    **counts,
                    "occupancy_rate": _rate(counts["occupied"], capacity - counts["unknown"]),
                    "spaces": spaces,
                }
            )
            site["capacity"] += capacity
            for key in counts:
                site[key] += counts[key]

        camera_out = []
        for camera in cameras:
            health = self.camera_health(camera["id"])
            camera_out.append({"id": camera["id"], "name": camera["name"], "location": camera["location"],
                               "enabled": camera["enabled"], **health})

        online = sum(1 for c in camera_out if c["state"] == "online")
        return {
            "updated_at": datetime.now(timezone.utc),
            "site_name": self.settings.site_name if self.settings else "ParkSight",
            "site": {**site, "occupancy_rate": _rate(site["occupied"], site["capacity"] - site["unknown"])},
            "cameras_online": online,
            "cameras_total": len(camera_out),
            "cameras": camera_out,
            "zones": zone_out,
            "monitor": {
                "processing_enabled": self.enabled,
                "detector_ready": self.detector is not None,
                "detector_error": self.detector_error,
                "last_snapshot_at": self.last_snapshot_at,
                "last_snapshot_error": self.last_snapshot_error,
                "inference_ms": getattr(self.detector, "last_inference_ms", None),
            },
        }


def _rate(occupied, known):
    return round(occupied / known, 4) if known > 0 else None
