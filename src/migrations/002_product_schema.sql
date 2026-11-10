-- Multi-camera product schema. Existing occupancy history is preserved:
-- legacy rows keep their values and get zone_id/camera_id = NULL.

CREATE TABLE cameras (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    location VARCHAR(200) NOT NULL DEFAULT '',
    source_type VARCHAR(10) NOT NULL CHECK (source_type IN ('rtsp', 'file')),
    -- RTSP URL *without* credentials, or a file name inside the video directory.
    source_url TEXT NOT NULL,
    username VARCHAR(200),
    -- Fernet-encrypted; never returned by the API.
    password_encrypted TEXT,
    rtsp_transport VARCHAR(3) NOT NULL DEFAULT 'tcp' CHECK (rtsp_transport IN ('tcp', 'udp')),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX cameras_name_key ON cameras (lower(name));

CREATE TABLE zones (
    id SERIAL PRIMARY KEY,
    camera_id INTEGER NOT NULL REFERENCES cameras (id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    -- Floor / level / area label used for grouping, e.g. "Basement 1".
    area VARCHAR(100) NOT NULL DEFAULT '',
    -- Resolution of the frame the polygons were drawn on. Polygons are
    -- rescaled if the camera later delivers a different resolution.
    frame_width INTEGER CHECK (frame_width > 0),
    frame_height INTEGER CHECK (frame_height > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX zones_name_key ON zones (lower(name));
CREATE INDEX zones_camera_idx ON zones (camera_id);

CREATE TABLE parking_spaces (
    id SERIAL PRIMARY KEY,
    zone_id INTEGER NOT NULL REFERENCES zones (id) ON DELETE CASCADE,
    label VARCHAR(30) NOT NULL,
    polygon JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX parking_spaces_label_key ON parking_spaces (zone_id, lower(label));

CREATE TABLE camera_events (
    id BIGSERIAL PRIMARY KEY,
    camera_id INTEGER REFERENCES cameras (id) ON DELETE CASCADE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status VARCHAR(20) NOT NULL,
    message TEXT NOT NULL DEFAULT ''
);
CREATE INDEX camera_events_camera_time_idx ON camera_events (camera_id, recorded_at DESC);

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(64) NOT NULL,
    password_hash TEXT NOT NULL,
    role VARCHAR(10) NOT NULL CHECK (role IN ('admin', 'viewer')),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX users_username_key ON users (lower(username));

CREATE TABLE sessions (
    token_hash CHAR(64) PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX sessions_expires_idx ON sessions (expires_at);

CREATE TABLE app_settings (
    key VARCHAR(64) PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Occupancy history: one row per zone per snapshot. All zones of one
-- snapshot share the same recorded_at, so site totals are SUM() GROUP BY
-- recorded_at.
ALTER TABLE occupancy_history RENAME COLUMN timestamp TO recorded_at;
-- Legacy timestamps were written in the server's local time zone.
ALTER TABLE occupancy_history
    ALTER COLUMN recorded_at TYPE TIMESTAMPTZ
    USING recorded_at AT TIME ZONE current_setting('TimeZone');
ALTER TABLE occupancy_history ALTER COLUMN recorded_at SET DEFAULT now();
ALTER TABLE occupancy_history ALTER COLUMN recorded_at SET NOT NULL;
ALTER TABLE occupancy_history
    ADD COLUMN camera_id INTEGER REFERENCES cameras (id) ON DELETE SET NULL,
    ADD COLUMN zone_id INTEGER REFERENCES zones (id) ON DELETE SET NULL,
    -- Names are copied so reports stay readable after a zone is deleted.
    ADD COLUMN camera_name VARCHAR(100),
    ADD COLUMN zone_name VARCHAR(100),
    -- Spaces whose state could not be determined (camera offline / warming up).
    ADD COLUMN unknown INTEGER NOT NULL DEFAULT 0;
ALTER TABLE occupancy_history ADD CONSTRAINT occupancy_history_counts_check CHECK (
    capacity >= 0 AND occupied >= 0 AND available >= 0 AND unknown >= 0
    AND occupied + available + unknown = capacity
);
CREATE INDEX occupancy_history_recorded_idx ON occupancy_history (recorded_at);
CREATE UNIQUE INDEX occupancy_history_zone_time_key
    ON occupancy_history (zone_id, recorded_at) WHERE zone_id IS NOT NULL;
