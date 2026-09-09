import cv2
import json
import numpy as np

from config import (
    VIDEO_PATH,
    SPACES_PATH,
    HISTORY_LENGTH,
    OCCUPIED_THRESHOLD,
    SHOW_VEHICLES,
)

from detector import VehicleDetector


def load_parking_spaces():
    with open(SPACES_PATH, "r") as file:
        return json.load(file)


def get_vehicle_ground_points(box):
    """
    Generate several points near the bottom of the
    vehicle bounding box.

    Multiple points allow one vehicle to occupy
    more than one adjacent parking space.
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
    Determine whether any vehicle ground point
    falls inside the parking-space polygon.
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


def run():
    parking_spaces = load_parking_spaces()

    print(
        f"Loaded {len(parking_spaces)} parking spaces."
    )

    detector = VehicleDetector()

    cap = cv2.VideoCapture(VIDEO_PATH)

    if not cap.isOpened():
        print("Error: Could not open video.")
        return

    # Recent occupancy results for each space.
    occupancy_history = [
        [] for _ in parking_spaces
    ]

    while True:

        ret, frame = cap.read()

        if not ret:
            print("Video ended.")
            break

        vehicles = detector.detect(frame)

        vehicle_points = []

        # ---------------------------------------------
        # VEHICLE PROCESSING
        # ---------------------------------------------

        for vehicle in vehicles:

            box = vehicle["box"]

            points = get_vehicle_ground_points(
                box
            )

            vehicle_points.extend(points)

            # Optional debugging visualization.
            if SHOW_VEHICLES:

                x1, y1, x2, y2 = box

                cv2.rectangle(
                    frame,
                    (x1, y1),
                    (x2, y2),
                    (0, 255, 255),
                    2,
                )

                label = (
                    f'{vehicle["class"]} '
                    f'{vehicle["confidence"]:.2f}'
                )

                cv2.putText(
                    frame,
                    label,
                    (x1, y1 - 8),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 255),
                    2,
                )

        # ---------------------------------------------
        # PARKING OCCUPANCY
        # ---------------------------------------------

        occupied_count = 0

        for index, space in enumerate(
            parking_spaces
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

            # Add current result to history.
            history = occupancy_history[index]

            history.append(
                1 if detected_occupied else 0
            )

            if len(history) > HISTORY_LENGTH:
                history.pop(0)

            # Smooth the result.
            occupied_votes = sum(history)

            occupied = (
                occupied_votes >= OCCUPIED_THRESHOLD
            )

            if occupied:

                occupied_count += 1

                status = "OCCUPIED"
                line_color = (0, 0, 255)
                thickness = 3

            else:

                status = "AVAILABLE"
                line_color = (0, 255, 0)
                thickness = 2

            # Draw parking space.
            cv2.polylines(
                frame,
                [polygon],
                True,
                line_color,
                thickness,
            )

            center_x = int(
                np.mean(polygon[:, 0])
            )

            center_y = int(
                np.mean(polygon[:, 1])
            )

            cv2.putText(
                frame,
                f"P{index + 1}: {status}",
                (center_x - 50, center_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                line_color,
                2,
            )

        # ---------------------------------------------
        # PARKING SUMMARY
        # ---------------------------------------------

        capacity = len(parking_spaces)

        available_count = (
            capacity - occupied_count
        )

        cv2.rectangle(
            frame,
            (10, 10),
            (320, 115),
            (0, 0, 0),
            -1,
        )

        cv2.putText(
            frame,
            f"Capacity: {capacity}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )

        cv2.putText(
            frame,
            f"Occupied: {occupied_count}",
            (20, 68),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )

        cv2.putText(
            frame,
            f"Available: {available_count}",
            (20, 96),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )

        cv2.imshow(
            "ParkSight - Parking Occupancy",
            frame,
        )

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    run()