import cv2
import json
import numpy as np


from src.config import (
    SPACES_PATH,
    HISTORY_LENGTH,
    OCCUPIED_THRESHOLD,
)


def load_parking_spaces():
    with open(SPACES_PATH, "r") as file:
        return json.load(file)


def get_vehicle_ground_points(box):
    """
    Generate several points near the bottom of a vehicle.

    Multiple points allow one vehicle to occupy
    multiple adjacent parking spaces.
    """

    x1, y1, x2, y2 = box

    ground_y = int(
        y1 + 0.90 * (y2 - y1)
    )

    width = x2 - x1

    points = []

    for ratio in [0.10, 0.30, 0.50, 0.70, 0.90]:

        x = int(
            x1 + ratio * width
        )

        points.append(
            (x, ground_y)
        )

    return points


def is_space_occupied(polygon, vehicle_points):
    """
    Check whether any vehicle ground point
    falls inside a parking-space polygon.
    """

    for point in vehicle_points:

        inside = cv2.pointPolygonTest(
            polygon,
            point,
            False,
        )

        if inside >= 0:
            return True

    return False


class ParkingOccupancy:

    def __init__(self):

        self.parking_spaces = (
            load_parking_spaces()
        )

        self.occupancy_history = [
            [] for _ in self.parking_spaces
        ]

    def update(self, vehicles):

        vehicle_points = []

        # Convert vehicle detections into
        # ground points.
        for vehicle in vehicles:

            points = get_vehicle_ground_points(
                vehicle["box"]
            )

            vehicle_points.extend(points)

        space_states = {}

        occupied_count = 0

        # Check every parking space.
        for index, space in enumerate(
            self.parking_spaces
        ):

            polygon = np.array(
                space,
                dtype=np.int32,
            )

            detected_occupied = (
                is_space_occupied(
                    polygon,
                    vehicle_points,
                )
            )

            # Add detection to history.
            history = (
                self.occupancy_history[index]
            )

            history.append(
                1 if detected_occupied else 0
            )

            if len(history) > HISTORY_LENGTH:
                history.pop(0)

            # Apply temporal smoothing.
            occupied_votes = sum(history)

            occupied = (
                occupied_votes >=
                OCCUPIED_THRESHOLD
            )

            space_name = f"P{index + 1}"

            space_states[space_name] = (
                occupied
            )

            if occupied:
                occupied_count += 1

        capacity = len(
            self.parking_spaces
        )

        available_count = (
            capacity - occupied_count
        )

        return {
            "capacity": capacity,
            "occupied": occupied_count,
            "available": available_count,
            "spaces": space_states,
        }