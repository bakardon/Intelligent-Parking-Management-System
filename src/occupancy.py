"""
Parking-space occupancy engine.

Algorithm (unchanged from the original implementation):

1. Every detected vehicle contributes five *ground-contact points* spread
   across its bounding box at 90 % of the box height, i.e. roughly where the
   tyres meet the ground. In oblique CCTV views the box centre usually lies
   over the next row of bays, so the bottom edge is a far better indicator.
2. A space is *detected* occupied in a frame when any ground point falls
   inside its polygon. A vehicle straddling two bays therefore occupies both.
3. Temporal smoothing: each space keeps its last `history_length`
   observations; it is occupied when at least `occupied_threshold` of them
   were occupied. This removes single-frame misses and passing vehicles.

Additions for the product:

* Stable space identifiers instead of positional `P1..Pn` names.
* An explicit *unknown* state: a space is unknown until enough observations
  exist to decide (start-up, after a camera outage). The original code
  reported every space as "available" during that period.
* Polygons can be rescaled when a camera's resolution differs from the
  resolution the layout was drawn on.
"""

import json

import cv2
import numpy as np

from src.config import HISTORY_LENGTH, OCCUPIED_THRESHOLD, SPACES_PATH


OCCUPIED = "occupied"
AVAILABLE = "available"
UNKNOWN = "unknown"

GROUND_Y_RATIO = 0.90
GROUND_X_RATIOS = (0.10, 0.30, 0.50, 0.70, 0.90)


def load_parking_spaces(path=SPACES_PATH):
    """Load the legacy JSON layout: a list of polygons."""
    with open(path, "r") as file:
        return json.load(file)


def get_vehicle_ground_points(box):
    """
    Generate several points near the bottom of a vehicle.

    Multiple points allow one vehicle to occupy
    multiple adjacent parking spaces.
    """
    x1, y1, x2, y2 = box
    ground_y = int(y1 + GROUND_Y_RATIO * (y2 - y1))
    width = x2 - x1
    return [(int(x1 + ratio * width), ground_y) for ratio in GROUND_X_RATIOS]


def is_space_occupied(polygon, vehicle_points):
    """
    Check whether any vehicle ground point
    falls inside a parking-space polygon.
    """
    for point in vehicle_points:
        if cv2.pointPolygonTest(polygon, point, False) >= 0:
            return True
    return False


def scale_polygon(polygon, from_size, to_size):
    """Rescale polygon points drawn on a `from_size` frame to `to_size`."""
    if not from_size or not to_size or tuple(from_size) == tuple(to_size):
        return polygon
    sx = to_size[0] / from_size[0]
    sy = to_size[1] / from_size[1]
    return [[x * sx, y * sy] for x, y in polygon]


class ParkingOccupancy:
    def __init__(
        self,
        parking_spaces=None,
        history_length=HISTORY_LENGTH,
        occupied_threshold=OCCUPIED_THRESHOLD,
        space_ids=None,
    ):
        if parking_spaces is None:
            parking_spaces = load_parking_spaces()
        if occupied_threshold > history_length:
            raise ValueError("occupied_threshold cannot exceed history_length")

        self.parking_spaces = parking_spaces
        self.space_ids = list(space_ids) if space_ids is not None else [
            f"P{index + 1}" for index in range(len(parking_spaces))
        ]
        if len(self.space_ids) != len(parking_spaces):
            raise ValueError("space_ids must match parking_spaces")
        self.history_length = history_length
        self.occupied_threshold = occupied_threshold
        self._polygons = [np.array(space, dtype=np.int32) for space in parking_spaces]
        self.occupancy_history = [[] for _ in parking_spaces]
        # Per-frame (unsmoothed) detection result, for installer debugging.
        self.last_detected = [False for _ in parking_spaces]

    def reset(self):
        """Forget all observations; every space becomes unknown."""
        for history in self.occupancy_history:
            history.clear()
        self.last_detected = [False for _ in self.parking_spaces]

    def space_state(self, index):
        history = self.occupancy_history[index]
        if len(history) < self.occupied_threshold:
            return UNKNOWN
        return OCCUPIED if sum(history) >= self.occupied_threshold else AVAILABLE

    def update(self, vehicles):
        # Convert vehicle detections into ground points.
        vehicle_points = []
        for vehicle in vehicles:
            vehicle_points.extend(get_vehicle_ground_points(vehicle["box"]))

        for index, polygon in enumerate(self._polygons):
            detected_occupied = is_space_occupied(polygon, vehicle_points)
            self.last_detected[index] = detected_occupied

            history = self.occupancy_history[index]
            history.append(1 if detected_occupied else 0)
            if len(history) > self.history_length:
                history.pop(0)

        return self.status()

    def status(self):
        states = {}
        counts = {OCCUPIED: 0, AVAILABLE: 0, UNKNOWN: 0}
        for index, space_id in enumerate(self.space_ids):
            state = self.space_state(index)
            counts[state] += 1
            # Legacy representation: True / False, None when unknown.
            states[space_id] = None if state == UNKNOWN else state == OCCUPIED
        return {
            "capacity": len(self.space_ids),
            "occupied": counts[OCCUPIED],
            "available": counts[AVAILABLE],
            "unknown": counts[UNKNOWN],
            "spaces": states,
        }
