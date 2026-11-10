"""
ParkSight web application: REST API + dashboard.

Run:  uvicorn src.api:app --host 0.0.0.0 --port 8000
"""

import csv
import io
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src import __version__, auth, config, security
from src.auth import current_user, require_admin
from src.camera import probe_source
from src.database import Database, DatabaseUnavailable
from src.logging_setup import configure_logging
from src.monitor import ParkingMonitor
from src.repositories import Conflict, NotFound, Repositories, resolve_source
from src.schemas import (
    CameraCreate,
    CameraEnabled,
    CameraOut,
    CameraTestRequest,
    CameraUpdate,
    HistoryDelete,
    LayoutIn,
    LoginRequest,
    OperationalSettings,
    PasswordChange,
    SettingsUpdate,
    SetupRequest,
    UserCreate,
    UserUpdate,
    ZoneCreate,
    ZoneUpdate,
)


log = logging.getLogger("parksight")

MAX_RANGE_DAYS = 400
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mkv", ".mov", ".m4v"}
BUCKETS = [60, 300, 900, 1800, 3600, 3 * 3600, 6 * 3600, 12 * 3600, 86400]


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class UserOut(BaseModel):
    id: int
    username: str
    role: str
    active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None


class SpaceOut(BaseModel):
    id: int
    label: str
    polygon: list[list[float]]


class ZoneOut(BaseModel):
    id: int
    camera_id: int
    camera_name: str
    name: str
    area: str
    frame_width: Optional[int]
    frame_height: Optional[int]
    spaces: list[SpaceOut]


class HistoryRecord(BaseModel):
    id: int
    recorded_at: datetime
    camera_id: Optional[int]
    zone_id: Optional[int]
    camera_name: Optional[str]
    zone_name: Optional[str]
    capacity: int
    occupied: int
    available: int
    unknown: int


class HistoryPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[HistoryRecord]


class LegacyHistoryRecord(BaseModel):
    id: int
    timestamp: datetime
    capacity: int
    occupied: int
    available: int
    unknown: int


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app(database=None, monitor_enabled=None, detector_factory=None):
    configure_logging()
    database = database or Database()
    repos = Repositories(database)
    monitor = ParkingMonitor(
        database,
        repos,
        detector_factory=detector_factory,
        enabled=config.MONITOR_ENABLED if monitor_enabled is None else monitor_enabled,
    )

    @asynccontextmanager
    async def lifespan(app):
        log.info("ParkSight %s starting", __version__)
        app.state.db_error = None
        try:
            applied = database.initialize()
            if applied:
                log.info("Database migrations applied: %s", ", ".join(applied))
            if repos.count_users() == 0:
                token = app.state.setup_token.issue()
                log.warning("=" * 64)
                log.warning("No users exist. Open the dashboard and complete setup with")
                log.warning("SETUP TOKEN: %s", token)
                log.warning("=" * 64)
            monitor.start()
        except DatabaseUnavailable as error:
            # Keep serving so /api/health can report the problem.
            app.state.db_error = str(error)
            log.error("%s. ParkSight is running without database access.", error)
        yield
        log.info("ParkSight shutting down")
        monitor.stop()
        database.close()

    app = FastAPI(
        title="ParkSight API",
        description="On-premise parking occupancy monitoring",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.db = database
    app.state.repos = repos
    app.state.monitor = monitor
    app.state.setup_token = auth.SetupToken()
    app.state.throttle = auth.LoginThrottle()

    _install_handlers(app)
    _install_routes(app)
    app.mount("/static", StaticFiles(directory=config.WEB_DIR), name="static")
    return app


def _install_handlers(app):
    @app.exception_handler(NotFound)
    async def not_found(_request, error):
        return JSONResponse({"detail": str(error)}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(_request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(DatabaseUnavailable)
    async def db_down(_request, error):
        return JSONResponse({"detail": "Database unavailable"}, status_code=503)

    @app.exception_handler(ValueError)
    async def invalid(_request, error):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(RequestValidationError)
    async def validation(_request, error):
        messages = []
        for item in error.errors():
            where = ".".join(str(p) for p in item.get("loc", []) if p not in ("body", "query"))
            msg = str(item.get("msg", "")).removeprefix("Value error, ")
            messages.append(f"{where}: {msg}" if where else msg)
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
                  for e in error.errors()]
        return JSONResponse({"detail": "; ".join(messages), "errors": errors}, status_code=422)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        if not request.url.path.startswith("/api/docs"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'"
            )
        if request.url.path.startswith(("/api/", "/status", "/history")):
            response.headers["Cache-Control"] = "no-store"
        return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _camera_out(monitor, camera):
    return CameraOut(**camera, status=monitor.camera_health(camera["id"], camera["enabled"]))


def _parse_range(start, end, default_hours=24):
    now = datetime.now(timezone.utc)
    end = end or now
    start = start or end - timedelta(hours=default_hours)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if start >= end:
        raise HTTPException(422, "start must be before end")
    if end - start > timedelta(days=MAX_RANGE_DAYS):
        raise HTTPException(422, f"Date range is limited to {MAX_RANGE_DAYS} days")
    return start, end


def _auto_bucket(start, end, max_points=300):
    span = (end - start).total_seconds()
    for bucket in BUCKETS:
        if span / bucket <= max_points:
            return bucket
    return BUCKETS[-1]


def list_video_files():
    if not config.VIDEO_DIR.is_dir():
        return []
    return sorted(
        p.name for p in config.VIDEO_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    )


def _validate_camera_source(data):
    if data["source_type"] == "file" and data["source_url"] not in list_video_files():
        raise HTTPException(422, f"Video file '{data['source_url']}' is not in the video directory")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _install_routes(app):
    repos = app.state.repos
    db = app.state.db
    monitor = app.state.monitor

    # --- Dashboard ------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def root():
        return FileResponse(config.WEB_DIR / "index.html")

    # --- Health (public, no sensitive data) ------------------------------

    @app.get("/api/health", tags=["system"])
    def health():
        db_ok = db.ping()
        body = {"status": "ok" if db_ok else "degraded", "database": db_ok, "version": __version__}
        return JSONResponse(body, status_code=200 if db_ok else 503)

    # --- Authentication --------------------------------------------------

    @app.get("/api/auth/state", tags=["auth"])
    def auth_state(request: Request):
        setup_required = repos.count_users() == 0
        user = None
        token = request.cookies.get(auth.SESSION_COOKIE)
        if token and not setup_required:
            row = repos.user_for_session(token)
            if row:
                user = {"id": row["id"], "username": row["username"], "role": row["role"]}
        return {"setup_required": setup_required, "user": user}

    @app.post("/api/auth/setup", tags=["auth"])
    def setup(body: SetupRequest, request: Request, response: Response):
        auth.check_csrf(request)
        throttle = request.app.state.throttle
        key = auth.client_key(request)
        if throttle.blocked(key):
            raise HTTPException(429, "Too many attempts. Try again later.")
        if repos.count_users() > 0:
            raise HTTPException(409, "Setup has already been completed")
        if not request.app.state.setup_token.check(body.setup_token):
            throttle.failure(key)
            raise HTTPException(403, "Invalid setup token. It is printed in the server log.")
        problem = security.password_problem(body.password)
        if problem:
            raise HTTPException(422, problem)
        user = repos.create_first_admin(body.username, body.password)
        request.app.state.setup_token.consume()
        token, expires = repos.create_session(user["id"], config.SESSION_HOURS)
        auth.set_session_cookie(response, token, expires)
        log.info("Initial administrator '%s' created", user["username"])
        return {"id": user["id"], "username": user["username"], "role": user["role"]}

    @app.post("/api/auth/login", tags=["auth"])
    def login(body: LoginRequest, request: Request, response: Response):
        auth.check_csrf(request)
        throttle = request.app.state.throttle
        keys = (auth.client_key(request), f"user:{body.username.lower()}")
        if throttle.blocked(*keys):
            raise HTTPException(429, "Too many failed sign-in attempts. Try again in 15 minutes.")
        user = repos.get_user_for_login(body.username)
        stored = user["password_hash"] if user else security.DUMMY_PASSWORD_HASH
        valid = security.verify_password(body.password, stored)
        if not user or not valid or not user["active"]:
            throttle.failure(*keys)
            log.warning("Failed sign-in for '%s' from %s", body.username[:64], keys[0][3:])
            raise HTTPException(401, "Incorrect username or password")
        throttle.success(*keys)
        token, expires = repos.create_session(user["id"], config.SESSION_HOURS)
        auth.set_session_cookie(response, token, expires)
        return {"id": user["id"], "username": user["username"], "role": user["role"]}

    @app.post("/api/auth/logout", tags=["auth"])
    def logout(request: Request, response: Response):
        auth.check_csrf(request)
        token = request.cookies.get(auth.SESSION_COOKIE)
        if token:
            repos.delete_session(token)
        auth.clear_session_cookie(response)
        return {"ok": True}

    @app.get("/api/auth/me", tags=["auth"])
    def me(user=Depends(current_user)):
        return {"id": user["id"], "username": user["username"], "role": user["role"]}

    @app.post("/api/auth/password", tags=["auth"])
    def change_password(body: PasswordChange, response: Response, user=Depends(current_user)):
        if not security.verify_password(body.current_password, repos.password_hash(user["id"])):
            raise HTTPException(403, "Current password is incorrect")
        problem = security.password_problem(body.new_password)
        if problem:
            raise HTTPException(422, problem)
        repos.update_user(user["id"], password=body.new_password)  # also ends all sessions
        token, expires = repos.create_session(user["id"], config.SESSION_HOURS)
        auth.set_session_cookie(response, token, expires)
        return {"ok": True}

    # --- Live status -----------------------------------------------------

    @app.get("/api/status", tags=["status"])
    def status(user=Depends(current_user)):
        return monitor.get_status()

    @app.get("/status", tags=["status"], summary="Legacy site status")
    def legacy_status(user=Depends(current_user)):
        """Original response shape: capacity/occupied/available and a map of
        space label -> occupied (true/false, null when unknown)."""
        status = monitor.get_status()
        spaces = {}
        for zone in status["zones"]:
            for space in zone["spaces"]:
                key = space["label"] if len(status["zones"]) == 1 else f'{zone["name"]}/{space["label"]}'
                spaces[key] = {"occupied": True, "available": False}.get(space["state"])
        return {**{k: status["site"][k] for k in ("capacity", "occupied", "available", "unknown")},
                "spaces": spaces, "updated_at": status["updated_at"]}

    # --- History, analytics, reports -------------------------------------

    @app.get("/history", tags=["history"], response_model=list[LegacyHistoryRecord],
             summary="Legacy site history (newest first)")
    def legacy_history(limit: int = Query(100, ge=1, le=5000), user=Depends(current_user)):
        return db.get_history(limit=limit)

    @app.get("/api/history", tags=["history"], response_model=HistoryPage)
    def history(
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        zone_id: Optional[int] = None,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0, le=10_000_000),
        user=Depends(current_user),
    ):
        start, end = _parse_range(start, end)
        total, items = db.list_history(start, end, zone_id, limit, offset)
        return {"total": total, "limit": limit, "offset": offset, "items": items}

    @app.get("/api/analytics", tags=["history"])
    def analytics(
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        zone_id: Optional[int] = None,
        user=Depends(current_user),
    ):
        start, end = _parse_range(start, end)
        tz = repos.get_settings().timezone
        bucket = _auto_bucket(start, end)
        summary = db.occupancy_summary(start, end, zone_id)
        return {
            "start": start,
            "end": end,
            "timezone": tz,
            "bucket_seconds": bucket,
            "summary": summary,
            "series": db.occupancy_series(start, end, bucket, zone_id) if summary["samples"] else [],
            "daily": db.daily_summary(start, end, tz, zone_id) if summary["samples"] else [],
            "hourly": db.hourly_profile(start, end, tz, zone_id) if summary["samples"] else [],
            "zones": db.zone_comparison(start, end) if zone_id is None else [],
        }

    @app.get("/api/reports/occupancy.csv", tags=["history"])
    def export_csv(
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        zone_id: Optional[int] = None,
        user=Depends(current_user),
    ):
        start, end = _parse_range(start, end)
        tz = repos.get_settings().timezone

        def rows():
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow([f"timestamp ({tz})", "timestamp_utc", "camera", "zone", "capacity",
                             "occupied", "available", "unknown", "occupancy_percent"])
            for row in db.iter_history_rows(start, end, tz, zone_id):
                known = row["capacity"] - row["unknown"]
                writer.writerow([
                    row["local_time"].strftime("%Y-%m-%d %H:%M:%S"),
                    row["recorded_at"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    _csv_safe(row["camera_name"] or ""),
                    _csv_safe(row["zone_name"] or "Site total (legacy)"),
                    row["capacity"], row["occupied"], row["available"], row["unknown"],
                    f"{100 * row['occupied'] / known:.1f}" if known > 0 else "",
                ])
                if buffer.tell() > 64_000:
                    yield buffer.getvalue()
                    buffer.seek(0)
                    buffer.truncate()
            yield buffer.getvalue()

        name = f"parksight-occupancy-{start:%Y%m%d}-{end:%Y%m%d}.csv"
        return StreamingResponse(rows(), media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/history/stats", tags=["history"])
    def history_stats(user=Depends(require_admin)):
        return db.history_stats()

    @app.post("/api/history/delete", tags=["history"])
    def delete_history(body: HistoryDelete, user=Depends(require_admin)):
        deleted = db.delete_history_before(body.before)
        log.warning("User '%s' deleted %d history rows before %s", user["username"], deleted, body.before)
        return {"deleted": deleted}

    # --- Cameras ---------------------------------------------------------

    @app.get("/api/cameras", tags=["cameras"], response_model=list[CameraOut])
    def list_cameras(user=Depends(current_user)):
        return [_camera_out(monitor, c) for c in repos.list_cameras()]

    @app.get("/api/cameras/events", tags=["cameras"])
    def camera_events(camera_id: Optional[int] = None, limit: int = Query(50, ge=1, le=500),
                      user=Depends(current_user)):
        return repos.list_camera_events(camera_id, limit)

    @app.get("/api/cameras/{camera_id}", tags=["cameras"], response_model=CameraOut)
    def get_camera(camera_id: int, user=Depends(current_user)):
        return _camera_out(monitor, repos.get_camera(camera_id))

    @app.post("/api/cameras", tags=["cameras"], response_model=CameraOut, status_code=201)
    def create_camera(body: CameraCreate, user=Depends(require_admin)):
        data = body.model_dump()
        _validate_camera_source(data)
        camera = repos.create_camera(data)
        log.info("Camera '%s' created by %s", camera["name"], user["username"])
        monitor.request_reload()
        return _camera_out(monitor, camera)

    @app.put("/api/cameras/{camera_id}", tags=["cameras"], response_model=CameraOut)
    def update_camera(camera_id: int, body: CameraUpdate, user=Depends(require_admin)):
        data = body.model_dump()
        _validate_camera_source(data)
        camera = repos.update_camera(camera_id, data)
        monitor.request_reload()
        return _camera_out(monitor, camera)

    @app.patch("/api/cameras/{camera_id}", tags=["cameras"], response_model=CameraOut)
    def enable_camera(camera_id: int, body: CameraEnabled, user=Depends(require_admin)):
        camera = repos.set_camera_enabled(camera_id, body.enabled)
        monitor.request_reload()
        return _camera_out(monitor, camera)

    @app.delete("/api/cameras/{camera_id}", tags=["cameras"], status_code=204)
    def delete_camera(camera_id: int, user=Depends(require_admin)):
        repos.delete_camera(camera_id)
        log.info("Camera %s deleted by %s", camera_id, user["username"])
        monitor.request_reload()
        return Response(status_code=204)

    @app.post("/api/cameras/test", tags=["cameras"])
    def test_camera(body: CameraTestRequest, user=Depends(require_admin)):
        """Try to connect and read one frame. Uses the stored password when
        testing an existing camera and no new password is given."""
        if body.camera_id is not None and body.source_url is None:
            camera = repos.get_camera(body.camera_id)
            source_type, transport = camera["source_type"], camera["rtsp_transport"]
            source = repos.camera_stream_url(body.camera_id)
        else:
            if not body.source_type or not body.source_url:
                raise HTTPException(422, "source_type and source_url are required")
            source_type, transport = body.source_type, body.rtsp_transport
            if source_type == "file":
                if body.source_url not in list_video_files():
                    raise HTTPException(422, "Video file is not in the video directory")
                source = resolve_source("file", body.source_url, None, None)
            else:
                url, url_user, url_password = security.split_credentials(body.source_url.strip())
                password = body.password if body.password is not None else url_password
                if password is None and body.camera_id is not None:
                    stored = repos.db.fetch_one(
                        "SELECT password_encrypted FROM cameras WHERE id = %s", (body.camera_id,))
                    password = security.decrypt_secret(stored["password_encrypted"]) if stored else None
                source = security.build_stream_url(url, body.username or url_user, password)
        try:
            width, height, _frame = probe_source(source, source_type, transport)
        except Exception as error:
            return {"ok": False, "message": security.redact(str(error))}
        return {"ok": True, "message": f"Connected. Receiving {width}x{height} video.",
                "width": width, "height": height}

    @app.get("/api/cameras/{camera_id}/snapshot", tags=["cameras"],
             responses={200: {"content": {"image/jpeg": {}}}})
    def camera_snapshot(camera_id: int, overlay: bool = False, user=Depends(require_admin)):
        """Latest frame (administrators only; used for calibration).
        `overlay=true` draws the installer debug view. Nothing is stored."""
        camera = repos.get_camera(camera_id)
        worker = monitor.worker(camera_id)
        jpeg = worker.render_snapshot(overlay=overlay) if worker else None
        if jpeg is None:
            import cv2

            try:
                _w, _h, frame = probe_source(repos.camera_stream_url(camera_id), camera["source_type"],
                                             camera["rtsp_transport"])
            except Exception as error:
                raise HTTPException(503, f"No frame available: {security.redact(str(error))}")
            ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            jpeg = buffer.tobytes()
        return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/api/videos", tags=["cameras"])
    def videos(user=Depends(require_admin)):
        return {"directory": "videos", "files": list_video_files()}

    # --- Zones and spaces ------------------------------------------------

    @app.get("/api/zones", tags=["zones"], response_model=list[ZoneOut])
    def list_zones(camera_id: Optional[int] = None, user=Depends(current_user)):
        return repos.list_zones(camera_id)

    @app.get("/api/zones/{zone_id}", tags=["zones"], response_model=ZoneOut)
    def get_zone(zone_id: int, user=Depends(current_user)):
        return repos.get_zone(zone_id)

    @app.post("/api/zones", tags=["zones"], response_model=ZoneOut, status_code=201)
    def create_zone(body: ZoneCreate, user=Depends(require_admin)):
        zone = repos.create_zone(body.model_dump())
        monitor.request_reload()
        return zone

    @app.put("/api/zones/{zone_id}", tags=["zones"], response_model=ZoneOut)
    def update_zone(zone_id: int, body: ZoneUpdate, user=Depends(require_admin)):
        zone = repos.update_zone(zone_id, body.model_dump())
        monitor.request_reload()
        return zone

    @app.delete("/api/zones/{zone_id}", tags=["zones"], status_code=204)
    def delete_zone(zone_id: int, user=Depends(require_admin)):
        repos.delete_zone(zone_id)
        monitor.request_reload()
        return Response(status_code=204)

    @app.put("/api/zones/{zone_id}/layout", tags=["zones"], response_model=ZoneOut)
    def save_layout(zone_id: int, body: LayoutIn, user=Depends(require_admin)):
        zone = repos.save_layout(
            zone_id, body.frame_width, body.frame_height,
            [s.model_dump() for s in body.spaces],
        )
        log.info("Layout of zone '%s' saved (%d spaces) by %s", zone["name"], len(zone["spaces"]),
                 user["username"])
        monitor.request_reload()
        return zone

    # --- Users -----------------------------------------------------------

    @app.get("/api/users", tags=["users"], response_model=list[UserOut])
    def list_users(user=Depends(require_admin)):
        return repos.list_users()

    @app.post("/api/users", tags=["users"], response_model=UserOut, status_code=201)
    def create_user(body: UserCreate, user=Depends(require_admin)):
        problem = security.password_problem(body.password)
        if problem:
            raise HTTPException(422, problem)
        created = repos.create_user(body.username, body.password, body.role)
        log.info("User '%s' (%s) created by %s", created["username"], created["role"], user["username"])
        return created

    @app.patch("/api/users/{user_id}", tags=["users"], response_model=UserOut)
    def update_user(user_id: int, body: UserUpdate, user=Depends(require_admin)):
        if body.password is not None:
            problem = security.password_problem(body.password)
            if problem:
                raise HTTPException(422, problem)
        return repos.update_user(user_id, role=body.role, active=body.active, password=body.password)

    @app.delete("/api/users/{user_id}", tags=["users"], status_code=204)
    def delete_user(user_id: int, user=Depends(require_admin)):
        if user_id == user["id"]:
            raise HTTPException(409, "You cannot delete your own account")
        repos.delete_user(user_id)
        return Response(status_code=204)

    # --- Settings and system ----------------------------------------------

    @app.get("/api/settings", tags=["settings"], response_model=OperationalSettings)
    def get_settings(user=Depends(current_user)):
        return repos.get_settings()

    @app.put("/api/settings", tags=["settings"], response_model=OperationalSettings)
    def update_settings(body: SettingsUpdate, user=Depends(require_admin)):
        settings = repos.update_settings(body.model_dump(exclude_unset=True))
        log.info("Settings updated by %s", user["username"])
        monitor.request_reload()
        return settings

    @app.get("/api/system", tags=["settings"])
    def system_info(user=Depends(require_admin)):
        status = monitor.get_status()
        return {
            "version": __version__,
            "schema_version": db.schema_version(),
            "model_file": os.path.basename(config.MODEL_PATH),
            "device": config.DEVICE,
            "video_directory": str(config.VIDEO_DIR.name),
            "monitor": status["monitor"],
            "history": db.history_stats(),
        }


def _csv_safe(value):
    """Neutralise spreadsheet formula injection in text cells."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


app = create_app()
