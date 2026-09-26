import threading
import time
import cv2

from src.config import (
    VIDEO_PATH,
    DATABASE_SAVE_INTERVAL,
)
from src.detector import VehicleDetector
from src.occupancy import ParkingOccupancy
from src.database import Database


class ParkingMonitor:
    def __init__(self):
        self.detector = VehicleDetector()
        self.occupancy = ParkingOccupancy()
        self.database = Database()

        self.status = {
            "capacity": 0,
            "occupied": 0,
            "available": 0,
            "spaces": {},
        }

        self.running = False
        self.thread = None
        self.last_database_save = 0

    def start(self):
        if self.running:
            return

        self.database.initialize()

        self.running = True
        self.thread = threading.Thread(
            target=self._run,
            daemon=True,
        )
        self.thread.start()

    def stop(self):
        self.running = False

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)

    def get_status(self):
        return self.status

    def _run(self):
        while self.running:
            cap = cv2.VideoCapture(VIDEO_PATH)

            if not cap.isOpened():
                print("Error: Could not open video.")
                time.sleep(2)
                continue

            while self.running:
                ret, frame = cap.read()

                if not ret:
                    break

                vehicles = self.detector.detect(frame)

                self.status = self.occupancy.update(vehicles)

                self._save_to_database_if_needed()

            cap.release()

    def _save_to_database_if_needed(self):
        current_time = time.time()

        if current_time - self.last_database_save < DATABASE_SAVE_INTERVAL:
            return

        self.database.save_occupancy(
            capacity=self.status["capacity"],
            occupied=self.status["occupied"],
            available=self.status["available"],
        )

        self.last_database_save = current_time