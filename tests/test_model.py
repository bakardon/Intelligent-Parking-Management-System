"""
Real-model check on the demo video (skipped when the weights or the video
are not present, e.g. in CI). Verifies the detector output contract and
that the original 6-space layout produces a decision for every space.
"""

import os

import cv2
import pytest

from src import config
from src.occupancy import ParkingOccupancy, load_parking_spaces


pytestmark = pytest.mark.skipif(
    not (os.path.exists(config.MODEL_PATH) and os.path.exists(config.VIDEO_PATH)),
    reason="YOLO weights or demo video not available",
)


def test_yolo_detects_vehicles_in_demo_video():
    from src.detector import VehicleDetector

    detector = VehicleDetector()
    engine = ParkingOccupancy(load_parking_spaces())
    cap = cv2.VideoCapture(config.VIDEO_PATH)
    timings, counts = [], []
    try:
        for index in range(0, 300, 30):  # 10 frames across the clip
            cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = cap.read()
            assert ok
            vehicles = detector.detect(frame)
            timings.append(detector.last_inference_ms)
            counts.append(len(vehicles))
            for vehicle in vehicles:
                x1, y1, x2, y2 = vehicle["box"]
                assert 0 <= x1 < x2 and 0 <= y1 < y2
                assert vehicle["class"] in {"car", "motorcycle", "bus", "truck"}
                assert vehicle["confidence"] >= config.CONFIDENCE_THRESHOLD
            status = engine.update(vehicles)
    finally:
        cap.release()

    assert max(counts) > 0, "no vehicles detected in the demo video"
    assert status["unknown"] == 0 and status["capacity"] == 6
    print(f"\nYOLO inference ms per frame (after warm-up): "
          f"min {min(timings[1:]):.0f}, mean {sum(timings[1:]) / len(timings[1:]):.0f}, "
          f"max {max(timings[1:]):.0f}; vehicles per frame {counts}; final status {status}")
