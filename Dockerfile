# ParkSight application image (CPU-only).
#
# The detection model weights are NOT baked into the image; mount them at
# /app/models (see docker-compose.yml). This keeps third-party weights out
# of the distributed image and lets each site choose its model.

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    YOLO_OFFLINE=1 \
    YOLO_CONFIG_DIR=/tmp/ultralytics \
    PARKSIGHT_MODEL_PATH=/app/models/yolo11n.pt \
    PARKSIGHT_DATA_DIR=/app/data

# libgomp: OpenMP runtime for PyTorch; libglib: needed by OpenCV.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# 1. CPU-only PyTorch (avoids ~3 GB of CUDA libraries).
# 2. Application requirements.
# 3. Swap the desktop OpenCV build for the headless one (no GUI/Qt libs).
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.0 torchvision==0.29.0 \
    && pip install -r requirements.txt \
    && pip uninstall -y opencv-python \
    && pip install opencv-python-headless==5.0.0.93

COPY src ./src
COPY web ./web

RUN useradd --system --uid 10001 --home /app parksight \
    && mkdir -p /app/data/videos /app/models \
    && chown -R parksight /app/data
USER parksight

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# One worker only: camera processing runs inside the application process.
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
