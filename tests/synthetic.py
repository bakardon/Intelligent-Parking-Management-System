"""
Synthetic video and a pixel-based stand-in detector for automated tests.

`ColorBlobDetector` finds pure-red rectangles in real decoded frames with
OpenCV, so tests exercise the whole frame -> detection -> occupancy path
without a CCTV camera or the YOLO model.
"""

import cv2
import numpy as np


RED = (0, 0, 255)


def write_video(path, boxes, size=(640, 360), frames=40, fps=10):
    """Write an MJPG video with filled red rectangles (`boxes`: x1,y1,x2,y2)."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
    assert writer.isOpened(), "OpenCV could not create the test video"
    for _ in range(frames):
        frame = np.full((size[1], size[0], 3), 90, dtype=np.uint8)  # grey asphalt
        for x1, y1, x2, y2 in boxes:
            cv2.rectangle(frame, (x1, y1), (x2, y2), RED, -1)
        writer.write(frame)
    writer.release()
    return path


class ColorBlobDetector:
    def __init__(self, confidence=0.5, classes=None, **_kwargs):
        self.confidence = confidence
        self.calls = 0
        self.last_inference_ms = 0.0

    def configure(self, confidence=None, classes=None):
        pass

    def detect(self, frame):
        self.calls += 1
        mask = cv2.inRange(frame, (0, 0, 180), (80, 80, 255))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        vehicles = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w * h >= 200:
                vehicles.append({"box": (x, y, x + w, y + h), "class": "car", "confidence": 0.99})
        return vehicles
