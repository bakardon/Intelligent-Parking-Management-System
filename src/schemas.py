"""Pydantic models for API validation and operational settings."""

import re
from datetime import datetime
from typing import Literal, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src import config


VEHICLE_CLASS_NAMES = ("car", "motorcycle", "bus", "truck")

_NAME = r"^[^\x00-\x1f<>]+$"  # printable, no angle brackets


def _clean_name(value):
    value = value.strip()
    if not value:
        raise ValueError("must not be empty")
    if not re.match(_NAME, value):
        raise ValueError("contains invalid characters")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Operational settings
# ---------------------------------------------------------------------------

class OperationalSettings(StrictModel):
    site_name: str = Field("ParkSight", min_length=1, max_length=100)
    timezone: str = Field("UTC", min_length=1, max_length=64)
    confidence_threshold: float = Field(config.CONFIDENCE_THRESHOLD, ge=0.05, le=0.95)
    history_length: int = Field(config.HISTORY_LENGTH, ge=1, le=60)
    occupied_threshold: int = Field(config.OCCUPIED_THRESHOLD, ge=1, le=60)
    processing_interval_seconds: float = Field(config.PROCESSING_INTERVAL_SECONDS, ge=0.2, le=60)
    snapshot_interval_seconds: int = Field(config.DATABASE_SAVE_INTERVAL, ge=10, le=3600)
    stale_after_seconds: int = Field(config.STALE_AFTER_SECONDS, ge=3, le=600)
    reconnect_min_seconds: int = Field(config.RECONNECT_MIN_SECONDS, ge=1, le=300)
    reconnect_max_seconds: int = Field(config.RECONNECT_MAX_SECONDS, ge=1, le=3600)
    retention_days: int = Field(config.RETENTION_DAYS, ge=1, le=3650)
    vehicle_classes: list[str] = Field(default_factory=lambda: list(VEHICLE_CLASS_NAMES))

    @field_validator("site_name")
    @classmethod
    def check_site_name(cls, value):
        return _clean_name(value)

    @field_validator("vehicle_classes")
    @classmethod
    def _classes(cls, value):
        unknown = set(value) - set(VEHICLE_CLASS_NAMES)
        if unknown:
            raise ValueError(f"unknown vehicle classes: {sorted(unknown)}")
        if not value:
            raise ValueError("select at least one vehicle class")
        return sorted(set(value), key=VEHICLE_CLASS_NAMES.index)

    @model_validator(mode="after")
    def _consistent(self):
        if self.occupied_threshold > self.history_length:
            raise ValueError("occupied_threshold cannot exceed history_length")
        if self.reconnect_max_seconds < self.reconnect_min_seconds:
            raise ValueError("reconnect_max_seconds must be >= reconnect_min_seconds")
        return self


class SettingsUpdate(StrictModel):
    """Partial update; merged with current settings then fully validated."""

    site_name: Optional[str] = None
    timezone: Optional[str] = None
    confidence_threshold: Optional[float] = None
    history_length: Optional[int] = None
    occupied_threshold: Optional[int] = None
    processing_interval_seconds: Optional[float] = None
    snapshot_interval_seconds: Optional[int] = None
    stale_after_seconds: Optional[int] = None
    reconnect_min_seconds: Optional[int] = None
    reconnect_max_seconds: Optional[int] = None
    retention_days: Optional[int] = None
    vehicle_classes: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Cameras
# ---------------------------------------------------------------------------

class CameraBase(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    location: str = Field("", max_length=200)
    source_type: Literal["rtsp", "file"]
    # RTSP: full URL (credentials may be embedded; they are split off and
    # stored encrypted). File: a file name inside the video directory.
    source_url: str = Field(min_length=1, max_length=2000)
    username: Optional[str] = Field(None, max_length=200)
    rtsp_transport: Literal["tcp", "udp"] = "tcp"
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def check_name(cls, value):
        return _clean_name(value)

    @field_validator("location")
    @classmethod
    def _location(cls, value):
        value = value.strip()
        if value and not re.match(_NAME, value):
            raise ValueError("contains invalid characters")
        return value

    @model_validator(mode="after")
    def _source(self):
        self.source_url = self.source_url.strip()
        if self.source_type == "rtsp":
            parts = urlsplit(self.source_url)
            if parts.scheme.lower() not in ("rtsp", "rtsps", "http", "https") or not parts.hostname:
                raise ValueError("source_url must be an rtsp:// (or http[s]://) stream URL")
        else:
            name = self.source_url
            if "/" in name or "\\" in name or name.startswith("."):
                raise ValueError("source_url must be a file name inside the video directory")
        return self


class CameraCreate(CameraBase):
    password: Optional[str] = Field(None, max_length=200)


class CameraUpdate(CameraBase):
    # None = keep the stored password; "" = remove it.
    password: Optional[str] = Field(None, max_length=200)


class CameraEnabled(StrictModel):
    enabled: bool


class CameraOut(BaseModel):
    id: int
    name: str
    location: str
    source_type: str
    source_url: str  # never contains credentials
    username: Optional[str]
    has_password: bool
    rtsp_transport: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
    status: dict
    zone_count: int = 0


class CameraTestRequest(StrictModel):
    camera_id: Optional[int] = None
    source_type: Optional[Literal["rtsp", "file"]] = None
    source_url: Optional[str] = Field(None, max_length=2000)
    username: Optional[str] = Field(None, max_length=200)
    password: Optional[str] = Field(None, max_length=200)
    rtsp_transport: Literal["tcp", "udp"] = "tcp"


# ---------------------------------------------------------------------------
# Zones and spaces
# ---------------------------------------------------------------------------

class ZoneBase(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    area: str = Field("", max_length=100)
    camera_id: int

    @field_validator("name")
    @classmethod
    def check_name(cls, value):
        return _clean_name(value)

    @field_validator("area")
    @classmethod
    def _area(cls, value):
        value = value.strip()
        if value and not re.match(_NAME, value):
            raise ValueError("contains invalid characters")
        return value


class ZoneCreate(ZoneBase):
    pass


class ZoneUpdate(ZoneBase):
    pass


class SpaceIn(StrictModel):
    id: Optional[int] = None
    label: str = Field(min_length=1, max_length=30)
    polygon: list[tuple[float, float]] = Field(min_length=3, max_length=20)

    @field_validator("label")
    @classmethod
    def check_label(cls, value):
        return _clean_name(value)


class LayoutIn(StrictModel):
    frame_width: int = Field(gt=0, le=10000)
    frame_height: int = Field(gt=0, le=10000)
    spaces: list[SpaceIn] = Field(max_length=500)

    @model_validator(mode="after")
    def _validate(self):
        labels = [s.label.lower() for s in self.spaces]
        if len(labels) != len(set(labels)):
            raise ValueError("space labels must be unique within a zone")
        for space in self.spaces:
            for x, y in space.polygon:
                if not (0 <= x <= self.frame_width and 0 <= y <= self.frame_height):
                    raise ValueError(f"space {space.label}: point ({x}, {y}) is outside the frame")
            if _polygon_area(space.polygon) < 4:
                raise ValueError(f"space {space.label}: polygon has no area")
        return self


def _polygon_area(points):
    total = 0.0
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


# ---------------------------------------------------------------------------
# Users and auth
# ---------------------------------------------------------------------------

_USERNAME = re.compile(r"^[A-Za-z0-9_.@-]{3,64}$")


def _check_username(value):
    if not _USERNAME.match(value):
        raise ValueError("3-64 characters: letters, digits, _ . @ -")
    return value


class LoginRequest(StrictModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class SetupRequest(StrictModel):
    setup_token: str = Field(min_length=1, max_length=200)
    username: str
    password: str = Field(max_length=200)

    @field_validator("username")
    @classmethod
    def check_username(cls, value):
        return _check_username(value)


class UserCreate(StrictModel):
    username: str
    password: str = Field(max_length=200)
    role: Literal["admin", "viewer"]

    @field_validator("username")
    @classmethod
    def check_username(cls, value):
        return _check_username(value)


class UserUpdate(StrictModel):
    role: Optional[Literal["admin", "viewer"]] = None
    active: Optional[bool] = None
    password: Optional[str] = Field(None, max_length=200)


class PasswordChange(StrictModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


class HistoryDelete(StrictModel):
    before: datetime
    confirm: Literal["DELETE"]
