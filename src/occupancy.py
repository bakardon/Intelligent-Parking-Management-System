import os

# Prevent PyTorch threading issues on this system.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import cv2
import json
import numpy as np
from ultralytics import YOLO


VIDEO_PATH = "data/videos/parking.mp4"
SPACES_PATH = "data/parking_spaces.json"

CONFIDENCE_THRESHOLD = 0.50

# Number of recent frames used to determine occupancy.
HISTORY_LENGTH = 8

# Number of occupied detections required to mark a space occupied.
OCCUPIED_THRESHOLD = 5

VEHICLE_CLASSES = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}


def load_parking_spaces():
    with open(SPACES_PATH, "r") as file:
        return json.load(file)


def get_vehicle_ground_points(box):
    """
    Generate several points near the bottom of the
    vehicle bounding box.

    Using multiple points allows one vehicle to occupy
    more than one adjacent parking space.
    """
    x1, y1, x2, y2 = box

    ground_y = int(
        y1 + 0.90 * (y2 - y1)
    )

    width = x2 - x1

    points = []

    # Sample points across the lower part of the vehicle.
    for ratio in [0.10, 0.30, 0.50, 0.70, 0.90]:

        x = int(
            x1 + ratio * width
        )

        points.append(
            (x, ground_y)
        )

    return points


def main():
    parking_spaces = load_parking_spaces()

    print(f"Loaded {len(parking_spaces)} parking spaces.")

    model = YOLO("yolo11n.pt")

    cap = cv2.VideoCapture(VIDEO_PATH)

    if not cap.isOpened():
        print("Error: Could not open video.")
        return

    # Store recent occupancy results for every parking space.
    occupancy_history = [
        [] for _ in parking_spaces
    ]

    while True:
        ret, frame = cap.read()

        if not ret:
            print("Video ended.")
            break

        results = model(
            frame,
            verbose=False,
            conf=CONFIDENCE_THRESHOLD,
        )

        vehicle_points = []

        # --------------------------------------------------
        # VEHICLE DETECTION
        # --------------------------------------------------

        for result in results:

            for box in result.boxes:

                class_id = int(box.cls[0])

                if class_id not in VEHICLE_CLASSES:
                    continue

                confidence = float(box.conf[0])

                x1, y1, x2, y2 = map(
                    int,
                    box.xyxy[0],
                )

                ground_points = get_vehicle_ground_points(
                    (x1, y1, x2, y2)
                )

                vehicle_points.extend(ground_points)

                # Draw the ground points for debugging.
                for point in ground_points:
                    cv2.circle(
                        frame,
                        point,
                        4,
                        (255, 0, 255),
                        -1,
                    )

                # Draw vehicle bounding box.
                cv2.rectangle(
                    frame,
                    (x1, y1),
                    (x2, y2),
                    (0, 255, 255),
                    2,
                )

                # Display vehicle class and confidence.
                label = (
                    f"{VEHICLE_CLASSES[class_id]} "
                    f"{confidence:.2f}"
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

        # --------------------------------------------------
        # PARKING SPACE OCCUPANCY
        # --------------------------------------------------

        occupied_count = 0

        for index, space in enumerate(parking_spaces):

            polygon = np.array(
                space,
                dtype=np.int32,
            )

            detected_occupied = False

            # Check whether a vehicle's bottom-center
            # point lies inside this parking space.
            for point in vehicle_points:

                inside = cv2.pointPolygonTest(
                    polygon,
                    point,
                    False,
                )

                if inside >= 0:
                    detected_occupied = True
                    break

            # --------------------------------------------------
            # TEMPORAL SMOOTHING
            # --------------------------------------------------

            history = occupancy_history[index]

            history.append(
                1 if detected_occupied else 0
            )

            if len(history) > HISTORY_LENGTH:
                history.pop(0)

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

            # Draw parking-space polygon.
            cv2.polylines(
                frame,
                [polygon],
                True,
                line_color,
                thickness,
            )

            # Find approximate center of parking space.
            center_x = int(
                np.mean(polygon[:, 0])
            )

            center_y = int(
                np.mean(polygon[:, 1])
            )

            # Display parking-space status.
            cv2.putText(
                frame,
                f"P{index + 1}: {status}",
                (center_x - 50, center_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                line_color,
                2,
            )

        # --------------------------------------------------
        # PARKING STATISTICS
        # --------------------------------------------------

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

        # Display result.
        cv2.imshow(
            "ParkSight - Parking Occupancy",
            frame,
        )

        # Press Q to exit.
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()