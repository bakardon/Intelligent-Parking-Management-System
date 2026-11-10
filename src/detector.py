"""
Vehicle detection with Ultralytics YOLO (COCO-pretrained).

One model instance is shared by all camera workers. Inference calls are
serialised with a lock: Ultralytics predictors are not thread-safe, and on
a CPU-only host parallel inference brings no throughput benefit.
"""

import logging
import os
import threading
import time

from src import config

# Must be set before torch is imported. The original project pinned these
# to 1 to avoid threading problems; PARKSIGHT_TORCH_THREADS overrides it.
os.environ.setdefault("OMP_NUM_THREADS", str(config.TORCH_THREADS))
os.environ.setdefault("MKL_NUM_THREADS", str(config.TORCH_THREADS))


log = logging.getLogger(__name__)

# COCO class ids used by the pretrained YOLO models.
VEHICLE_CLASSES = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}


class VehicleDetector:
    def __init__(self, model_path=None, confidence=None, classes=None):
        self.model_path = model_path or config.MODEL_PATH
        self.confidence = confidence if confidence is not None else config.CONFIDENCE_THRESHOLD
        self.classes = set(classes or VEHICLE_CLASSES.values())
        self._model = None
        self._lock = threading.Lock()
        self.last_inference_ms = None
        self._load()

    def _load(self):
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"Detection model not found at {self.model_path}. "
                "Place the weights file there or set PARKSIGHT_MODEL_PATH."
            )
        import torch
        from ultralytics import YOLO

        torch.set_num_threads(max(1, config.TORCH_THREADS))
        self._model = YOLO(self.model_path)
        log.info("Loaded detection model %s on %s", os.path.basename(self.model_path), config.DEVICE)

    def configure(self, confidence=None, classes=None):
        if confidence is not None:
            self.confidence = confidence
        if classes is not None:
            self.classes = set(classes)

    def detect(self, frame):
        """
        Detect vehicles in a frame.

        Returns a list of dictionaries containing:
        - box: (x1, y1, x2, y2) in frame pixels
        - class: class name
        - confidence
        """
        class_ids = [cid for cid, name in VEHICLE_CLASSES.items() if name in self.classes]
        with self._lock:
            started = time.perf_counter()
            results = self._model(
                frame,
                verbose=False,
                conf=self.confidence,
                classes=class_ids,
                imgsz=config.INFERENCE_IMAGE_SIZE,
                device=config.DEVICE,
            )
            self.last_inference_ms = (time.perf_counter() - started) * 1000

        vehicles = []
        for result in results:
            for box in result.boxes:
                class_id = int(box.cls[0])
                if class_id not in VEHICLE_CLASSES:
                    continue
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                vehicles.append(
                    {
                        "box": (x1, y1, x2, y2),
                        "class": VEHICLE_CLASSES[class_id],
                        "confidence": float(box.conf[0]),
                    }
                )
        return vehicles
