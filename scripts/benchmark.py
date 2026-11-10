"""
Measure ParkSight's processing cost on this machine.

Runs the real capture + YOLO + occupancy pipeline on the demo video
(no database needed) and reports inference time, CPU and memory.

    python -m scripts.benchmark --seconds 60 --interval 1.0 --cameras 1
"""

import argparse
import os
import platform
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psutil  # installed with ultralytics

from src import config
from src.camera import CameraWorker
from src.detector import VehicleDetector
from src.occupancy import load_parking_spaces


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--interval", type=float, default=1.0, help="processing interval per camera")
    parser.add_argument("--cameras", type=int, default=1, help="simulated cameras (same demo video)")
    args = parser.parse_args()

    process = psutil.Process()
    detector = VehicleDetector()
    settings = SimpleNamespace(processing_interval_seconds=args.interval, stale_after_seconds=15,
                               reconnect_min_seconds=2, reconnect_max_seconds=60,
                               history_length=8, occupied_threshold=5)
    spaces = [{"id": i + 1, "label": f"P{i + 1}", "polygon": p} for i, p in enumerate(load_parking_spaces())]
    workers = []
    for n in range(args.cameras):
        camera = {"id": n + 1, "name": f"bench-{n + 1}", "source_type": "file",
                  "source": config.VIDEO_PATH, "rtsp_transport": "tcp", "enabled": True}
        zone = {"id": n + 1, "camera_id": n + 1, "frame_width": None, "frame_height": None,
                "spaces": [dict(s, id=s["id"] + 100 * n) for s in spaces]}
        workers.append(CameraWorker(camera, [zone], detector, settings))

    timings = []
    for worker in workers:
        worker.start()
    time.sleep(3)  # warm-up
    process.cpu_percent(None)
    start_frames = sum(w.frames_processed for w in workers)
    started = time.time()
    while time.time() - started < args.seconds:
        time.sleep(0.5)
        if detector.last_inference_ms:
            timings.append(detector.last_inference_ms)
    elapsed = time.time() - started
    cpu = process.cpu_percent(None)
    frames = sum(w.frames_processed for w in workers) - start_frames
    rss = process.memory_info().rss / 2**20
    for worker in workers:
        worker.stop()

    timings.sort()
    print(f"Machine: {platform.processor() or platform.machine()}, {psutil.cpu_count()} logical CPUs, "
          f"{psutil.virtual_memory().total / 2**30:.1f} GiB RAM, {platform.system()} {platform.release()}")
    print(f"Torch threads: {config.TORCH_THREADS}, image size: {config.INFERENCE_IMAGE_SIZE}, device: {config.DEVICE}")
    print(f"Cameras: {args.cameras}, processing interval: {args.interval}s, measured: {elapsed:.0f}s")
    print(f"Frames processed: {frames} ({frames / elapsed:.2f}/s total)")
    if timings:
        print(f"Inference ms: median {timings[len(timings) // 2]:.0f}, "
              f"p95 {timings[int(len(timings) * 0.95) - 1]:.0f}")
    print(f"Process CPU: {cpu:.0f}% of one core ({cpu / psutil.cpu_count():.1f}% of machine)")
    print(f"Resident memory: {rss:.0f} MiB")


if __name__ == "__main__":
    main()
