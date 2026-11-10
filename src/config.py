"""
ParkSight configuration.

Two kinds of configuration exist:

* Deployment settings (this module) come from environment variables / `.env`.
  They describe *where* things are: database, data directory, model file.
* Operational settings (thresholds, intervals, retention) live in the
  database `app_settings` table and are editable from the admin UI.
  The constants at the bottom of this module are their defaults.
"""

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

# Ultralytics performs an internet connectivity check on import unless this
# is set. ParkSight must work on isolated customer networks.
os.environ.setdefault("YOLO_OFFLINE", "1")
# Keep OpenCV/FFmpeg quiet: their error messages can contain stream URLs,
# and stream URLs can contain camera credentials.
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "-8")
# Without this, idle OpenMP worker threads spin-wait between inferences.
# Measured on the development laptop: ~135 % of a core at 1 inference/s
# with the default policy vs ~10 % with PASSIVE, same inference latency.
os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")


def _env(name, default=None):
    value = os.getenv(name)
    return default if value is None or value == "" else value


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _path(name, default):
    path = Path(_env(name, default))
    return path if path.is_absolute() else BASE_DIR / path


# --- Paths -----------------------------------------------------------------

DATA_DIR = _path("PARKSIGHT_DATA_DIR", "data")
VIDEO_DIR = _path("PARKSIGHT_VIDEO_DIR", str(DATA_DIR / "videos"))
MODEL_PATH = str(_path("PARKSIGHT_MODEL_PATH", "yolo11n.pt"))
WEB_DIR = BASE_DIR / "web"
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# --- Database --------------------------------------------------------------

DB_HOST = _env("DB_HOST", "localhost")
DB_PORT = int(_env("DB_PORT", "5432"))
DB_NAME = _env("DB_NAME", "parksight")
DB_USER = _env("DB_USER", "postgres")
DB_PASSWORD = _env("DB_PASSWORD")
DB_POOL_MAX = int(_env("DB_POOL_MAX", "10"))

# --- Web server / security -------------------------------------------------

HOST = _env("PARKSIGHT_HOST", "0.0.0.0")
PORT = int(_env("PARKSIGHT_PORT", "8000"))
LOG_LEVEL = _env("PARKSIGHT_LOG_LEVEL", "INFO").upper()
# Default reporting time zone (editable later in Settings).
DEFAULT_TIMEZONE = _env("PARKSIGHT_TIMEZONE", "UTC")
SECRET_KEY = _env("PARKSIGHT_SECRET_KEY")
# Set to true when ParkSight is served over HTTPS (e.g. behind a reverse proxy).
COOKIE_SECURE = _env_bool("PARKSIGHT_COOKIE_SECURE", False)
SESSION_HOURS = int(_env("PARKSIGHT_SESSION_HOURS", "12"))
# Disables camera processing (used by the automated tests and for
# API-only maintenance runs).
MONITOR_ENABLED = _env_bool("PARKSIGHT_MONITOR_ENABLED", True)

# --- Inference -------------------------------------------------------------

DEVICE = _env("PARKSIGHT_DEVICE", "cpu")
# PyTorch CPU threads. The original project pinned this to 1 to avoid
# threading problems on the development machine; that remains the default.
TORCH_THREADS = int(_env("PARKSIGHT_TORCH_THREADS", "1"))
INFERENCE_IMAGE_SIZE = int(_env("PARKSIGHT_IMAGE_SIZE", "640"))

# --- Operational defaults (editable at runtime via Settings) ---------------

CONFIDENCE_THRESHOLD = 0.50
# Temporal smoothing: a space is occupied when at least OCCUPIED_THRESHOLD
# of the last HISTORY_LENGTH observations saw a vehicle ground point in it.
HISTORY_LENGTH = 8
OCCUPIED_THRESHOLD = 5
PROCESSING_INTERVAL_SECONDS = 1.0
DATABASE_SAVE_INTERVAL = 60
STALE_AFTER_SECONDS = 15
RECONNECT_MIN_SECONDS = 2
RECONNECT_MAX_SECONDS = 60
RETENTION_DAYS = 365

# --- Legacy single-camera demo (src/main.py, parking_space_selector.py) ----

VIDEO_PATH = str(VIDEO_DIR / "parking.mp4")
SPACES_PATH = str(DATA_DIR / "parking_spaces.json")
SHOW_VEHICLES = False
