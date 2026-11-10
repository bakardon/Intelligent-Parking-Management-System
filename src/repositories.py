"""
Persistence for configuration entities: cameras, zones, parking spaces,
users, sessions, settings and camera health events.

All SQL is parameterised. Functions return plain dicts.
"""

from datetime import datetime, timedelta, timezone

import psycopg2
from psycopg2.extras import Json

from src import config, security
from src.schemas import OperationalSettings


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


def _unique_violation(error):
    return isinstance(error, psycopg2.errors.UniqueViolation)


class Repositories:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def default_settings(self):
        return OperationalSettings(timezone=config.DEFAULT_TIMEZONE)

    def get_settings(self):
        stored = {row["key"]: row["value"] for row in self.db.fetch_all("SELECT key, value FROM app_settings")}
        merged = self.default_settings().model_dump()
        merged.update({k: v for k, v in stored.items() if k in merged})
        try:
            return OperationalSettings(**merged)
        except ValueError:
            # A stored combination became invalid (e.g. after an upgrade
            # changed limits): fall back to defaults for safety.
            return self.default_settings()

    def update_settings(self, changes):
        current = self.get_settings().model_dump()
        current.update({k: v for k, v in changes.items() if v is not None})
        validated = OperationalSettings(**current)
        tz_ok = self.db.fetch_one(
            "SELECT 1 AS ok FROM pg_timezone_names WHERE name = %s", (validated.timezone,)
        )
        if not tz_ok:
            raise ValueError(f"Unknown time zone: {validated.timezone}")
        with self.db.cursor() as cur:
            for key, value in validated.model_dump().items():
                cur.execute(
                    """
                    INSERT INTO app_settings (key, value, updated_at)
                    VALUES (%s, %s, now())
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
                    """,
                    (key, Json(value)),
                )
        return validated

    # ------------------------------------------------------------------
    # Cameras
    # ------------------------------------------------------------------

    _CAMERA_COLUMNS = """
        c.id, c.name, c.location, c.source_type, c.source_url, c.username,
        (c.password_encrypted IS NOT NULL) AS has_password, c.rtsp_transport,
        c.enabled, c.created_at, c.updated_at,
        (SELECT count(*) FROM zones z WHERE z.camera_id = c.id)::int AS zone_count
    """

    def list_cameras(self):
        return self.db.fetch_all(f"SELECT {self._CAMERA_COLUMNS} FROM cameras c ORDER BY lower(c.name)")

    def get_camera(self, camera_id):
        row = self.db.fetch_one(f"SELECT {self._CAMERA_COLUMNS} FROM cameras c WHERE c.id = %s", (camera_id,))
        if not row:
            raise NotFound("Camera not found")
        return row

    def camera_stream_url(self, camera_id):
        """The full source location including credentials. In-memory use only."""
        row = self.db.fetch_one(
            "SELECT source_type, source_url, username, password_encrypted FROM cameras WHERE id = %s",
            (camera_id,),
        )
        if not row:
            raise NotFound("Camera not found")
        return resolve_source(
            row["source_type"],
            row["source_url"],
            row["username"],
            security.decrypt_secret(row["password_encrypted"]),
        )

    @staticmethod
    def _camera_fields(data):
        url, user, password = data["source_url"], data.get("username"), data.get("password")
        if data["source_type"] == "rtsp":
            url, url_user, url_password = security.split_credentials(url)
            user = user or url_user
            if password is None and url_password is not None:
                password = url_password
        else:
            user, password = None, ""
        return url, (user or None), password

    def create_camera(self, data):
        url, user, password = self._camera_fields(data)
        try:
            row = self.db.fetch_one(
                """
                INSERT INTO cameras (name, location, source_type, source_url, username,
                                     password_encrypted, rtsp_transport, enabled)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    data["name"], data["location"], data["source_type"], url, user,
                    security.encrypt_secret(password), data["rtsp_transport"], data["enabled"],
                ),
            )
        except psycopg2.Error as error:
            if _unique_violation(error):
                raise Conflict("A camera with this name already exists") from error
            raise
        return self.get_camera(row["id"])

    def update_camera(self, camera_id, data):
        self.get_camera(camera_id)
        url, user, password = self._camera_fields(data)
        sets = [
            "name = %s", "location = %s", "source_type = %s", "source_url = %s",
            "username = %s", "rtsp_transport = %s", "enabled = %s", "updated_at = now()",
        ]
        params = [data["name"], data["location"], data["source_type"], url, user,
                  data["rtsp_transport"], data["enabled"]]
        if password is not None:  # None keeps the stored password
            sets.append("password_encrypted = %s")
            params.append(security.encrypt_secret(password))
        params.append(camera_id)
        try:
            self.db.execute(f"UPDATE cameras SET {', '.join(sets)} WHERE id = %s", params)
        except psycopg2.Error as error:
            if _unique_violation(error):
                raise Conflict("A camera with this name already exists") from error
            raise
        return self.get_camera(camera_id)

    def set_camera_enabled(self, camera_id, enabled):
        if not self.db.execute(
            "UPDATE cameras SET enabled = %s, updated_at = now() WHERE id = %s", (enabled, camera_id)
        ):
            raise NotFound("Camera not found")
        return self.get_camera(camera_id)

    def delete_camera(self, camera_id):
        if not self.db.execute("DELETE FROM cameras WHERE id = %s", (camera_id,)):
            raise NotFound("Camera not found")

    def add_camera_event(self, camera_id, status, message=""):
        self.db.execute(
            "INSERT INTO camera_events (camera_id, status, message) VALUES (%s, %s, %s)",
            (camera_id, status, security.redact(message)[:500]),
        )

    def list_camera_events(self, camera_id=None, limit=50):
        if camera_id is None:
            return self.db.fetch_all(
                """
                SELECT e.id, e.camera_id, c.name AS camera_name, e.recorded_at, e.status, e.message
                FROM camera_events e LEFT JOIN cameras c ON c.id = e.camera_id
                ORDER BY e.recorded_at DESC LIMIT %s
                """,
                (limit,),
            )
        return self.db.fetch_all(
            """
            SELECT e.id, e.camera_id, c.name AS camera_name, e.recorded_at, e.status, e.message
            FROM camera_events e LEFT JOIN cameras c ON c.id = e.camera_id
            WHERE e.camera_id = %s ORDER BY e.recorded_at DESC LIMIT %s
            """,
            (camera_id, limit),
        )

    # ------------------------------------------------------------------
    # Zones and spaces
    # ------------------------------------------------------------------

    def list_zones(self, camera_id=None):
        params = ()
        where = ""
        if camera_id is not None:
            where = "WHERE z.camera_id = %s"
            params = (camera_id,)
        zones = self.db.fetch_all(
            f"""
            SELECT z.id, z.camera_id, c.name AS camera_name, z.name, z.area,
                   z.frame_width, z.frame_height, z.created_at, z.updated_at
            FROM zones z JOIN cameras c ON c.id = z.camera_id
            {where}
            ORDER BY lower(z.area), lower(z.name)
            """,
            params,
        )
        if not zones:
            return []
        spaces = self.db.fetch_all(
            "SELECT id, zone_id, label, polygon FROM parking_spaces WHERE zone_id = ANY(%s) ORDER BY id",
            ([z["id"] for z in zones],),
        )
        by_zone = {}
        for space in spaces:
            by_zone.setdefault(space["zone_id"], []).append(
                {"id": space["id"], "label": space["label"], "polygon": space["polygon"]}
            )
        for zone in zones:
            zone["spaces"] = by_zone.get(zone["id"], [])
        return zones

    def get_zone(self, zone_id):
        for zone in self.list_zones():
            if zone["id"] == zone_id:
                return zone
        raise NotFound("Zone not found")

    def create_zone(self, data):
        self.get_camera(data["camera_id"])
        try:
            row = self.db.fetch_one(
                "INSERT INTO zones (camera_id, name, area) VALUES (%s, %s, %s) RETURNING id",
                (data["camera_id"], data["name"], data["area"]),
            )
        except psycopg2.Error as error:
            if _unique_violation(error):
                raise Conflict("A zone with this name already exists") from error
            raise
        return self.get_zone(row["id"])

    def update_zone(self, zone_id, data):
        zone = self.get_zone(zone_id)
        self.get_camera(data["camera_id"])
        moved = data["camera_id"] != zone["camera_id"]
        try:
            with self.db.cursor() as cur:
                cur.execute(
                    "UPDATE zones SET camera_id = %s, name = %s, area = %s, updated_at = now() WHERE id = %s",
                    (data["camera_id"], data["name"], data["area"], zone_id),
                )
                if moved:
                    # Polygons are drawn in one camera's perspective; they
                    # are meaningless for another camera.
                    cur.execute("DELETE FROM parking_spaces WHERE zone_id = %s", (zone_id,))
                    cur.execute(
                        "UPDATE zones SET frame_width = NULL, frame_height = NULL WHERE id = %s",
                        (zone_id,),
                    )
        except psycopg2.Error as error:
            if _unique_violation(error):
                raise Conflict("A zone with this name already exists") from error
            raise
        return self.get_zone(zone_id)

    def delete_zone(self, zone_id):
        if not self.db.execute("DELETE FROM zones WHERE id = %s", (zone_id,)):
            raise NotFound("Zone not found")

    def save_layout(self, zone_id, frame_width, frame_height, spaces):
        """Replace a zone's spaces in one transaction, keeping stable IDs.

        Spaces sent with an existing `id` are updated in place (history and
        identity preserved); spaces without `id` are created; spaces of the
        zone that are not sent are deleted.
        """
        self.get_zone(zone_id)
        with self.db.cursor() as cur:
            cur.execute("SELECT id FROM parking_spaces WHERE zone_id = %s FOR UPDATE", (zone_id,))
            existing = {row["id"] for row in cur.fetchall()}
            sent_ids = {s["id"] for s in spaces if s.get("id") is not None}
            foreign = sent_ids - existing
            if foreign:
                raise Conflict(f"Spaces {sorted(foreign)} do not belong to this zone")
            removed = existing - sent_ids
            if removed:
                cur.execute("DELETE FROM parking_spaces WHERE id = ANY(%s)", (list(removed),))
            # Temporary labels avoid unique-label collisions while renaming
            # spaces into each other's labels (e.g. swapping P1 and P2).
            cur.execute(
                "UPDATE parking_spaces SET label = '~tmp' || id WHERE zone_id = %s", (zone_id,)
            )
            for space in spaces:
                polygon = [[round(float(x), 1), round(float(y), 1)] for x, y in space["polygon"]]
                if space.get("id") is not None:
                    cur.execute(
                        "UPDATE parking_spaces SET label = %s, polygon = %s, updated_at = now() WHERE id = %s",
                        (space["label"], Json(polygon), space["id"]),
                    )
                else:
                    cur.execute(
                        "INSERT INTO parking_spaces (zone_id, label, polygon) VALUES (%s, %s, %s)",
                        (zone_id, space["label"], Json(polygon)),
                    )
            cur.execute(
                "UPDATE zones SET frame_width = %s, frame_height = %s, updated_at = now() WHERE id = %s",
                (frame_width, frame_height, zone_id),
            )
        return self.get_zone(zone_id)

    # ------------------------------------------------------------------
    # Users and sessions
    # ------------------------------------------------------------------

    _USER_COLUMNS = "id, username, role, active, created_at, last_login_at"

    def count_users(self):
        return self.db.fetch_one("SELECT count(*)::int AS n FROM users")["n"]

    def list_users(self):
        return self.db.fetch_all(f"SELECT {self._USER_COLUMNS} FROM users ORDER BY lower(username)")

    def get_user(self, user_id):
        row = self.db.fetch_one(f"SELECT {self._USER_COLUMNS} FROM users WHERE id = %s", (user_id,))
        if not row:
            raise NotFound("User not found")
        return row

    def get_user_for_login(self, username):
        return self.db.fetch_one(
            f"SELECT {self._USER_COLUMNS}, password_hash FROM users WHERE lower(username) = lower(%s)",
            (username,),
        )

    def create_user(self, username, password, role):
        try:
            row = self.db.fetch_one(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) RETURNING id",
                (username, security.hash_password(password), role),
            )
        except psycopg2.Error as error:
            if _unique_violation(error):
                raise Conflict("A user with this name already exists") from error
            raise
        return self.get_user(row["id"])

    def create_first_admin(self, username, password):
        """Create the initial administrator only if no user exists (atomic)."""
        with self.db.cursor() as cur:
            cur.execute("LOCK TABLE users IN EXCLUSIVE MODE")
            cur.execute("SELECT count(*) AS n FROM users")
            if cur.fetchone()["n"]:
                raise Conflict("Setup has already been completed")
            cur.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, 'admin') RETURNING id",
                (username, security.hash_password(password)),
            )
            user_id = cur.fetchone()["id"]
        return self.get_user(user_id)

    def update_user(self, user_id, role=None, active=None, password=None):
        user = self.get_user(user_id)
        with self.db.cursor() as cur:
            demoting = (role is not None and role != "admin") or active is False
            if user["role"] == "admin" and user["active"] and demoting:
                cur.execute("LOCK TABLE users IN EXCLUSIVE MODE")
                cur.execute("SELECT count(*) AS n FROM users WHERE role = 'admin' AND active")
                if cur.fetchone()["n"] <= 1:
                    raise Conflict("At least one active administrator is required")
            if role is not None:
                cur.execute("UPDATE users SET role = %s WHERE id = %s", (role, user_id))
            if active is not None:
                cur.execute("UPDATE users SET active = %s WHERE id = %s", (active, user_id))
                if not active:
                    cur.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
            if password is not None:
                cur.execute(
                    "UPDATE users SET password_hash = %s WHERE id = %s",
                    (security.hash_password(password), user_id),
                )
                cur.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
        return self.get_user(user_id)

    def delete_user(self, user_id):
        user = self.get_user(user_id)
        with self.db.cursor() as cur:
            if user["role"] == "admin" and user["active"]:
                cur.execute("LOCK TABLE users IN EXCLUSIVE MODE")
                cur.execute("SELECT count(*) AS n FROM users WHERE role = 'admin' AND active")
                if cur.fetchone()["n"] <= 1:
                    raise Conflict("At least one active administrator is required")
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))

    def password_hash(self, user_id):
        row = self.db.fetch_one("SELECT password_hash FROM users WHERE id = %s", (user_id,))
        return row["password_hash"] if row else None

    def create_session(self, user_id, hours):
        token = security.new_token()
        expires = datetime.now(timezone.utc) + timedelta(hours=hours)
        with self.db.cursor() as cur:
            cur.execute(
                "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
                (security.hash_token(token), user_id, expires),
            )
            cur.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (user_id,))
        return token, expires

    def user_for_session(self, token):
        return self.db.fetch_one(
            """
            SELECT u.id, u.username, u.role, u.active, s.expires_at
            FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = %s AND s.expires_at > now() AND u.active
            """,
            (security.hash_token(token),),
        )

    def delete_session(self, token):
        self.db.execute("DELETE FROM sessions WHERE token_hash = %s", (security.hash_token(token),))

    # ------------------------------------------------------------------
    # Monitoring configuration snapshot
    # ------------------------------------------------------------------

    def monitoring_config(self):
        """Everything the monitoring service needs, in one consistent read."""
        cameras = self.db.fetch_all(
            """
            SELECT id, name, location, source_type, source_url, username,
                   password_encrypted, rtsp_transport, enabled, updated_at
            FROM cameras ORDER BY id
            """
        )
        zones = self.list_zones()
        for camera in cameras:
            camera["source"] = resolve_source(
                camera["source_type"],
                camera["source_url"],
                camera["username"],
                security.decrypt_secret(camera.pop("password_encrypted")),
            )
        return cameras, zones


def resolve_source(source_type, source_url, username, password):
    if source_type == "file":
        return str(config.VIDEO_DIR / source_url)
    return security.build_stream_url(source_url, username, password)
