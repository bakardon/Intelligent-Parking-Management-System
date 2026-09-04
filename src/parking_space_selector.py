import cv2
import json
import numpy as np


VIDEO_PATH = "data/videos/parking.mp4"
OUTPUT_PATH = "data/parking_spaces.json"

points = []
parking_spaces = []


def mouse_callback(event, x, y, _flags, _param):
    global points

    if event == cv2.EVENT_LBUTTONDOWN:
        points.append([x, y])
        print(f"Point selected: ({x}, {y})")

        if len(points) == 4:
            parking_spaces.append(points.copy())
            print(f"Parking space {len(parking_spaces)} created.")
            points.clear()


def main():
    cap = cv2.VideoCapture(VIDEO_PATH)

    if not cap.isOpened():
        print("Error: Could not open video.")
        return

    ret, frame = cap.read()

    if not ret:
        print("Error: Could not read video.")
        cap.release()
        return

    window_name = "ParkSight - Parking Space Selector"

    cv2.namedWindow(window_name)
    cv2.setMouseCallback(window_name, mouse_callback)

    print()
    print("PARKING SPACE SELECTOR")
    print("----------------------")
    print("Click 4 corners for each parking space.")
    print("Press S to save.")
    print("Press R to reset the current space.")
    print("Press Q to quit.")
    print()

    while True:
        display = frame.copy()

        # Draw existing parking spaces
        for index, space in enumerate(parking_spaces):
            pts = np.array(space, dtype=np.int32)

            cv2.polylines(
                display,
                [pts],
                True,
                (255, 0, 0),
                2,
            )

            center_x = int(np.mean(pts[:, 0]))
            center_y = int(np.mean(pts[:, 1]))

            cv2.putText(
                display,
                f"P{index + 1}",
                (center_x - 15, center_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 0, 0),
                2,
            )

        # Draw currently selected points
        for point in points:
            cv2.circle(
                display,
                tuple(point),
                5,
                (0, 255, 255),
                -1,
            )

        cv2.imshow(window_name, display)

        key = cv2.waitKey(1) & 0xFF

        if key == ord("s"):
            with open(OUTPUT_PATH, "w") as file:
                json.dump(parking_spaces, file, indent=4)

            print(
                f"Saved {len(parking_spaces)} parking spaces "
                f"to {OUTPUT_PATH}"
            )

        elif key == ord("r"):
            points.clear()
            print("Current selection reset.")

        elif key == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()