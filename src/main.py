import cv2
import numpy as np

from src.config import SHOW_VEHICLES, VIDEO_PATH
from src.detector import VehicleDetector
from src.occupancy import ParkingOccupancy


def draw_vehicle_boxes(frame, vehicles):

    if not SHOW_VEHICLES:
        return

    for vehicle in vehicles:

        x1, y1, x2, y2 = (
            vehicle["box"]
        )

        label = (
            f'{vehicle["class"]} '
            f'{vehicle["confidence"]:.2f}'
        )

        cv2.rectangle(
            frame,
            (x1, y1),
            (x2, y2),
            (0, 255, 255),
            2,
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


def draw_parking_spaces(
    frame,
    parking_spaces,
    status,
):

    for index, space in enumerate(
        parking_spaces
    ):

        polygon = np.array(
        space,
        dtype=np.int32,
        )

        space_name = f"P{index + 1}"

        occupied = status[
            "spaces"
        ][space_name]

        if occupied:
            line_color = (0, 0, 255)
            thickness = 3
            state = "OCCUPIED"
        else:
            line_color = (0, 255, 0)
            thickness = 2
            state = "AVAILABLE"

        cv2.polylines(
            frame,
            [polygon],
            True,
            line_color,
            thickness,
        )

        center_x = int(
            polygon[:, 0].mean()
        )

        center_y = int(
            polygon[:, 1].mean()
        )

        cv2.putText(
            frame,
            f"{space_name}: {state}",
            (center_x - 50, center_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            line_color,
            2,
        )


def draw_summary(frame, status):

    cv2.rectangle(
        frame,
        (10, 10),
        (320, 115),
        (0, 0, 0),
        -1,
    )

    cv2.putText(
        frame,
        f'Capacity: {status["capacity"]}',
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2,
    )

    cv2.putText(
        frame,
        f'Occupied: {status["occupied"]}',
        (20, 68),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2,
    )

    cv2.putText(
        frame,
        f'Available: {status["available"]}',
        (20, 96),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2,
    )


def main():

    detector = VehicleDetector()

    occupancy = ParkingOccupancy()

    cap = cv2.VideoCapture(
        VIDEO_PATH
    )

    if not cap.isOpened():

        print(
            "Error: Could not open video."
        )

        return

    print("ParkSight started.")

    while True:

        ret, frame = cap.read()

        if not ret:
            print("Video ended.")
            break

        vehicles = detector.detect(
            frame
        )

        status = occupancy.update(
            vehicles
        )

        draw_vehicle_boxes(
            frame,
            vehicles,
        )

        draw_parking_spaces(
            frame,
            occupancy.parking_spaces,
            status,
        )

        draw_summary(
            frame,
            status,
        )

        cv2.imshow(
            "ParkSight - Parking Occupancy",
            frame,
        )

        if (
            cv2.waitKey(1) & 0xFF
            == ord("q")
        ):
            break

    cap.release()

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()