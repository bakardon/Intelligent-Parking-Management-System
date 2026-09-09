import cv2
import threading
import time

from src.config import VIDEO_PATH
from src.detector import VehicleDetector
from src.occupancy import ParkingOccupancy


class ParkingMonitor:

    def __init__(self):

        self.detector = VehicleDetector()
        self.occupancy = ParkingOccupancy()

        self.status = {
            "capacity": len(
                self.occupancy.parking_spaces
            ),
            "occupied": 0,
            "available": len(
                self.occupancy.parking_spaces
            ),
            "spaces": {
                f"P{i + 1}": False
                for i in range(
                    len(
                        self.occupancy.parking_spaces
                    )
                )
            },
        }

        self.running = False
        self.thread = None

    def process_video(self):

        cap = cv2.VideoCapture(
            VIDEO_PATH
        )

        if not cap.isOpened():
            print(
                "Error: Could not open video."
            )
            return

        while self.running:

            ret, frame = cap.read()

            if not ret:
                # Restart the video when it ends.
                cap.set(
                    cv2.CAP_PROP_POS_FRAMES,
                    0,
                )
                continue

            vehicles = self.detector.detect(
                frame
            )

            self.status = (
                self.occupancy.update(
                    vehicles
                )
            )

            # Small delay to avoid unnecessary
            # CPU usage with the demo video.
            time.sleep(0.01)

        cap.release()

    def start(self):

        if self.running:
            return

        self.running = True

        self.thread = threading.Thread(
            target=self.process_video,
            daemon=True,
        )

        self.thread.start()

    def stop(self):

        self.running = False

    def get_status(self):

        return self.status.copy()