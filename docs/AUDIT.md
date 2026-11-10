# ParkSight — Stage 1 Repository Audit

Audit date: 2026-11-10. Audited commit: `ae90c78` ("Add PostgreSQL history graph").

## 1. What exists

| Area | Files | State |
|---|---|---|
| Detection | `src/detector.py` | Ultralytics YOLO (`yolo11n.pt`, COCO classes car/motorcycle/bus/truck), fixed confidence 0.50 |
| Occupancy | `src/occupancy.py` | 5 ground-contact points at 90 % box height; `cv2.pointPolygonTest`; per-space 8-frame vote window, occupied at ≥ 5 votes |
| Monitoring | `src/monitor.py` | One daemon thread, one hard-coded video file, loops forever, writes a DB row every 10 s |
| API | `src/api.py` | FastAPI, `GET /status`, `GET /history?limit=`, static dashboard |
| Database | `src/database.py` | psycopg2, one table `occupancy_history(id, timestamp, capacity, occupied, available)` |
| Calibration | `src/parking_space_selector.py`, `data/parking_spaces.json` | OpenCV desktop window, click 4 corners, saves a bare list of polygons (6 spaces) |
| Desktop preview | `src/main.py` | OpenCV window with overlays |
| Dashboard | `web/index.html`, `app.js`, `style.css` | KPI cards, space grid, canvas history chart |
| Tests | `tests/test_database.py` | A script with `main()`, not a pytest test; writes a fake row (10/4/6) into the production table |
| Docs | `README.md` | Describes planned features (tracking, entry/exit, Docker) that do not exist |

Environment observed: Windows 11, Python 3.10.11 in `.venv` (working), a second unused Python 3.14 `.venv-1`, PostgreSQL 18.6 running locally with 249 existing history rows (2026-09-19 → 2026-09-26), Docker CLI 29.4 installed but daemon not running. Demo video `data/videos/parking.mp4`: 848×478, 30 fps, 323 frames (10.8 s).

## 2. Findings

### Critical

| # | Finding | Location |
|---|---|---|
| C1 | **Live parking grid never renders.** `app.js` writes to `#parking-spaces` and `#last-updated`, but the HTML has `#parking-grid` and `#updated`; JS emits class `parking-space`, CSS styles `.space`. The dashboard shows KPIs only. | `web/app.js:41`, `web/index.html` |
| C2 | **No access control at all.** Every endpoint is public on the network. Unacceptable once cameras/configuration become editable. | `src/api.py` |
| C3 | **Licensing not established.** Ultralytics package and YOLO11 weights are AGPL-3.0. Shipping ParkSight as a closed commercial product without AGPL compliance or an Ultralytics Enterprise licence is a legal risk. No licence inventory exists. | `requirements.txt`, `yolo11n.pt` |
| C4 | **Disconnected camera looks healthy.** If the source fails, `/status` keeps returning the last good numbers forever; nothing reports camera state. | `src/monitor.py` |

### High

| # | Finding | Location |
|---|---|---|
| H1 | New PostgreSQL connection opened and closed for every write and every `/history` call; no pool, no retry. A DB outage raises inside the monitor thread and **kills the thread silently** (no try/except in `_run`), freezing occupancy until restart. | `src/database.py`, `src/monitor.py:79` |
| H2 | Any exception in detection/occupancy (e.g. corrupt frame) also kills the monitor thread silently. | `src/monitor.py:_run` |
| H3 | Cameras, video path, model path, thresholds are Python constants; spaces are a JSON list with no camera association. Configuring a customer site requires editing source. | `src/config.py`, `data/parking_spaces.json` |
| H4 | RTSP not considered: no open/read timeouts (a dead RTSP stream can block `cap.read()` indefinitely), no reconnect back-off, frames processed sequentially so an RTSP buffer would lag further and further behind real time. | `src/monitor.py` |
| H5 | Video files are processed as fast as the CPU allows (not at real-time rate), so "live" status for the demo runs at an arbitrary speed and burns 100 % of a core. | `src/monitor.py` |
| H6 | Detector and monitor are constructed at **import time** of `src/api.py` (`monitor = ParkingMonitor()` loads YOLO). Importing the API for tests requires the model; startup failures happen before logging exists. | `src/api.py:14` |
| H7 | History timestamps are `TIMESTAMP` without time zone (server-local), no index on `timestamp`, no constraints (`occupied + available = capacity`), no camera/zone columns, no migration mechanism. | `src/database.py` |
| H8 | `tests/test_database.py` inserts fake data into the production table and is not collected by pytest (no `test_` function). There is effectively no test suite. | `tests/` |
| H9 | Spaces initialise as "available" before any evidence: at startup every space is reported free until 5 occupied votes accumulate. Same after a camera outage. Misleading for operators. | `src/occupancy.py` |

### Medium

| # | Finding | Location |
|---|---|---|
| M1 | Uses deprecated `@app.on_event` (warns on installed FastAPI 0.141). | `src/api.py` |
| M2 | `/status` returns a dict that the monitor thread replaces concurrently; acceptable in CPython but no snapshot semantics and no timestamps. | `src/monitor.py` |
| M3 | `/history` `limit` is unvalidated (negative or 10 000 000 accepted). No date filtering, pagination, or response model. | `src/api.py:50` |
| M4 | Relative paths (`web/`, `data/...`, `yolo11n.pt`) only work when the CWD is the repo root. | `src/config.py`, `src/api.py` |
| M5 | Space IDs are positional (`P1..Pn`); deleting one space renames all later ones and corrupts history meaning. | `src/occupancy.py:136` |
| M6 | Polygons are pixel coordinates without the reference resolution; if a camera's stream resolution changes the layout silently misaligns. | `data/parking_spaces.json` |
| M7 | `requirements.txt` unpinned; `opencv-python` (GUI build, bundles Qt) used for a server; CPU/GPU torch choice undocumented. | `requirements.txt` |
| M8 | Dashboard polls `/status` every 1 s and full history every 10 s regardless of visibility; errors only go to the console (no UI error state). Chart is a hand-drawn line with no axis labels for time. | `web/app.js` |
| M9 | `ultralytics` performs an internet connectivity check on import unless `YOLO_OFFLINE` is set — undesirable for offline sites. | `ultralytics/utils/__init__.py` |
| M10 | No logging framework (`print`). | all |
| M11 | No Docker/deployment files, no `.env.example`, no backup/restore procedure. | — |

### Low

| # | Finding | Location |
|---|---|---|
| L1 | `.gitignore` entry `" data/videos/"` has a leading space (ineffective; `*.mp4` masks it). A second virtualenv `.venv-1/` (Python 3.14, without the project's packages) sits in the repo root; it is not tracked, but should be explicitly ignored (left in place — deleting it is the owner's call). | `.gitignore` |
| L2 | `detector.py` forces `OMP_NUM_THREADS=1` globally for "threading issues"; reasonable default but not configurable. | `src/detector.py:4` |
| L3 | README advertises tracking, entry/exit, Docker and DeepSORT — none implemented. | `README.md` |
| L4 | Package is named `src` (unconventional). Kept to avoid churn; not worth breaking `python -m src.main`. | — |
| L5 | `parking_space_selector.py` uses module-level globals and fixed paths. | — |

### Not found (checked)
- No SQL injection: the existing queries are parameterised.
- No secrets committed: `.env` is ignored and untracked (verified with `git ls-files`).
- No facial recognition, plate recognition, or footage storage.

## 3. Assessment of the occupancy algorithm (preserve)

The multi-point ground-contact approach (5 points across the bottom 10 % of the box) is a sound choice for oblique CCTV views: it tests where the tyres meet the ground rather than the box centre, which sits over the *next* row in perspective views, and a vehicle straddling two bays marks both. The 8-sample / 5-vote smoothing suppresses single-frame misses and passing cars. Both are kept unchanged in behaviour; they become configurable, are covered by tests, and gain an explicit *unknown* state (H9, C4).

## 4. Prioritised plan

1. **Foundation** — settings from environment; pooled DB with versioned SQL migrations that preserve the existing 249 rows; lifespan startup; logging.
2. **Data model** — cameras, zones (camera-bound, floor/area label), spaces (stable IDs, reference resolution), users, sessions, settings, per-zone occupancy history with unique snapshot buckets and constraints.
3. **Engine** — per-camera worker threads (reader + processor), RTSP timeouts and exponential back-off reconnect, frame-staleness → *unknown*, shared thread-safe detector, occupancy engine kept algorithmically identical.
4. **Security** — scrypt password hashing (stdlib), server-side sessions in HttpOnly SameSite cookies, admin/viewer roles, one-time setup token for first admin, login throttling, RTSP passwords encrypted at rest (Fernet) and never returned.
5. **API** — Pydantic-validated REST API under `/api`, legacy `/status` and `/history` retained.
6. **UI** — rebuilt dashboard (vanilla JS, no framework, no CDN), camera management, browser-based calibration editor on a live snapshot, analytics, reports, users, settings.
7. **Reports/analytics/retention** — server-side aggregation, CSV export, retention purge.
8. **Docker** — CPU-only image, Compose with PostgreSQL, health checks, volumes.
9. **Tests** — pytest suite against a dedicated `parksight_test` database, synthetic video end-to-end test, measured performance.
10. **Docs & licensing** — commercial README, `THIRD_PARTY_LICENSES.md`, licensing decision record.

## 5. Resolution status (end of implementation, 2026-11-10)

| # | Status | How |
|---|---|---|
| C1 | Fixed | Dashboard rebuilt (`web/js/`); live parking map per zone |
| C2 | Fixed | Local accounts, admin/viewer roles, sessions, CSRF header, throttling (`src/auth.py`) |
| C3 | **Open — owner decision** | Documented in `THIRD_PARTY_LICENSES.md` with three options; not legally cleared |
| C4 | Fixed | Per-camera health states; stale/offline cameras turn their spaces "camera unavailable" |
| H1 | Fixed | Thread-safe connection pool, broken connections discarded, supervisor survives DB outages |
| H2 | Fixed | Detection errors are caught per frame; test `test_detector_failure_does_not_kill_worker` |
| H3 | Fixed | Cameras/zones/spaces/settings in PostgreSQL, editable in the UI |
| H4 | Fixed | FFmpeg open/read timeouts, exponential back-off, latest-frame-only processing |
| H5 | Fixed | Demo files paced at native frame rate; CPU measured (22 % of a core per camera) |
| H6 | Fixed | App factory + lifespan; model loads at start-up, failure reported in UI instead of crashing |
| H7 | Fixed | Versioned migrations, `timestamptz`, constraints, indexes, zone/camera columns; legacy rows kept |
| H8 | Fixed | 84-test pytest suite on a separate test database |
| H9 | Fixed | Explicit *unknown* state until smoothing has enough observations |
| M1–M11 | Fixed | Lifespan, snapshot status, validated/paginated queries, absolute paths, stable IDs, reference resolution + rescaling, pinned requirements, headless OpenCV in Docker, visibility-aware polling with error states, `YOLO_OFFLINE`, logging with credential redaction, Docker/.env.example/backup scripts |
| L1 | Fixed | `.gitignore` corrected; `.venv-*/`, secrets, backups, models ignored. `.venv-1/` left on disk |
| L2 | Fixed | `PARKSIGHT_TORCH_THREADS`; plus `OMP_WAIT_POLICY=PASSIVE` (cut idle CPU from ~135 % to ~10 % of a core) |
| L3 | Fixed | README rewritten |
| L4 | Kept | Package name `src` retained deliberately |
| L5 | Kept | Desktop selector still works; the browser editor replaces it for normal use |

Data notes: the production database was backed up to `backups/parksight-pre-v2-20261110.dump` before migration. Three of its 249 legacy rows (capacity 10, occupied 4) were written by the old `tests/test_database.py` script, not by monitoring; they were left untouched for the owner to decide.
