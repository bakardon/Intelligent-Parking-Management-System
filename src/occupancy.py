import cv2
import json
import numpy as np
from ultralytics import YOLO


VIDEO_PATH = "data/videos/parking.mp4"
SPACES_PATH = "data/parking_spaces.json"

VEHICLE_CLASSES = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}


def load_parking_spaces():
    with open(SPACES_PATH, "r") as file:
        return json.load(file)


def get_box_center(box):
    x1, y1, x2, y2 = box
    return (
        int((x1 + x2) / 2),
        int((y1 + y2) / 2),
    )


def main():
    parking_spaces = load_parking_spaces()

    print(f"Loaded {len(parking_spaces)} parking spaces.")

    model = YOLO("yolo11n.pt")

    cap = cv2.VideoCapture(VIDEO_PATH)

    if not cap.isOpened():
        print("Error: Could not open video.")
        return

    while True:
        ret, frame = cap.read()

        if not ret:
            print("Video ended.")
            break

        results = model(frame, verbose=False)

        vehicle_centers = []

        for result in results:
            for box in result.boxes:

                class_id = int(box.cls[0])

                if class_id not in VEHICLE_CLASSES:
                    continue

                x1, y1, x2, y2 = map(
                    int,
                    box.xyxy[0],
                )

                center = get_box_center(
                    (x1, y1, x2, y2)
                )

                vehicle_centers.append(center)

                cv2.rectangle(
                    frame,
                    (x1, y1),
                    (x2, y2),
                    (0, 255, 255),
                    2,
                )

        occupied_count = 0

        for index, space in enumerate(parking_spaces):

            polygon = np.array(
                space,
                dtype=np.int32,
            )

            occupied = False

            for center in vehicle_centers:

                inside = cv2.pointPolygonTest(
                    polygon,
                    center,
                    False,
                )

                if inside >= 0:
                    occupied = True
                    break

            if occupied:
                occupied_count += 1
                status = "OCCUPIED"
                thickness = 3
            else:
                status = "AVAILABLE"
                thickness = 2

            cv2.polylines(
                frame,
                [polygon],
                True,
                (0, 0, 255) if occupied else (0, 255, 0),
                thickness,
            )

            center_x = int(np.mean(polygon[:, 0]))
            center_y = int(np.mean(polygon[:, 1]))

            cv2.putText(
                frame,
                f"P{index + 1}: {status}",
                (center_x - 50, center_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 0, 255) if occupied else (0, 255, 0),
                2,
            )

        capacity = len(parking_spaces)
        available_count = capacity - occupied_count

        cv2.rectangle(
            frame,
            (10, 10),
            (310, 105),
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
            (20, 65),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )

        cv2.putText(
            frame,
            f"Available: {available_count}",
            (20, 90),
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
    main()