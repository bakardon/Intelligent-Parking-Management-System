-- Baseline: the schema created by ParkSight before versioned migrations.
-- Existing installations already have this table; IF NOT EXISTS keeps it.
CREATE TABLE IF NOT EXISTS occupancy_history (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    capacity INTEGER NOT NULL,
    occupied INTEGER NOT NULL,
    available INTEGER NOT NULL
);
