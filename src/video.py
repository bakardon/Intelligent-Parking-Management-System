import cv2


VIDEO_PATH = "data/videos/parking.mp4"


def main():
    cap = cv2.VideoCapture(VIDEO_PATH)

    if not cap.isOpened():
        print("Error: Could not open video.")
        return

    print("Video opened successfully.")

    while True:
        ret, frame = cap.read()

        if not ret:
            print("Video ended.")
            break

        cv2.imshow("ParkSight - Video", frame)

        # Press Q to quit
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()