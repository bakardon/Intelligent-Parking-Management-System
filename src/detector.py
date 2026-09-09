import os

# Prevent PyTorch threading issues on this system.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

from ultralytics import YOLO

from src.config import (
    MODEL_PATH,
    CONFIDENCE_THRESHOLD,
)


VEHICLE_CLASSES = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}


class VehicleDetector:

    def __init__(self):
        self.model = YOLO(MODEL_PATH)

    def detect(self, frame):
        """
        Detect vehicles in a frame.

        Returns a list of dictionaries containing:
        - bounding box
        - class name
        - confidence
        """

        results = self.model(
            frame,
            verbose=False,
            conf=CONFIDENCE_THRESHOLD,
        )

        vehicles = []

        for result in results:

            for box in result.boxes:

                class_id = int(box.cls[0])

                if class_id not in VEHICLE_CLASSES:
                    continue

                x1, y1, x2, y2 = map(
                    int,
                    box.xyxy[0],
                )

                confidence = float(
                    box.conf[0]
                )

                vehicles.append(
                    {
                        "box": (x1, y1, x2, y2),
                        "class": VEHICLE_CLASSES[class_id],
                        "confidence": confidence,
                    }
                )

        return vehicles