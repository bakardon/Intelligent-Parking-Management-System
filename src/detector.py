from ultralytics import YOLO


def main():
    model = YOLO("yolo11n.pt")
    print("YOLO model loaded successfully.")


if __name__ == "__main__":
    main()
