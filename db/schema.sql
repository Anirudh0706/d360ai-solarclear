-- SolarClear database schema (SQLite)
-- Hierarchy: substation -> feeder -> DTR (distribution transformer) -> consumer
-- Time series: readings (per DTR, hourly), weather (per substation, hourly)
-- Workflow:    applications (net-meter / KUSUM requests), alerts, agent_runs

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'engineer' CHECK (role IN ('admin', 'engineer')),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS substations (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    code      TEXT    NOT NULL UNIQUE,
    name      TEXT    NOT NULL,
    name_te   TEXT,                       -- Telugu name
    latitude  REAL    NOT NULL,
    longitude REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS feeders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    substation_id INTEGER NOT NULL REFERENCES substations(id) ON DELETE CASCADE,
    code          TEXT    NOT NULL UNIQUE,
    name          TEXT    NOT NULL,
    name_te       TEXT,                   -- Telugu name
    voltage_kv    REAL    NOT NULL DEFAULT 11,
    rating_kva    REAL    NOT NULL CHECK (rating_kva > 0),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS dtrs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    feeder_id  INTEGER NOT NULL REFERENCES feeders(id) ON DELETE CASCADE,
    code       TEXT    NOT NULL UNIQUE,
    name       TEXT    NOT NULL,          -- locality, e.g. Pet Basheerabad
    name_te    TEXT,                      -- Telugu locality name
    rating_kva REAL    NOT NULL CHECK (rating_kva > 0),
    area_type  TEXT    NOT NULL DEFAULT 'urban' CHECK (area_type IN ('urban', 'rural', 'agri')),
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS consumers (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    dtr_id             INTEGER NOT NULL REFERENCES dtrs(id) ON DELETE CASCADE,
    account_no         TEXT    NOT NULL UNIQUE,
    name               TEXT    NOT NULL,
    category           TEXT    NOT NULL DEFAULT 'domestic'
                       CHECK (category IN ('domestic', 'commercial', 'agricultural', 'industrial')),
    sanctioned_load_kw REAL    NOT NULL DEFAULT 3,
    pv_kw              REAL    NOT NULL DEFAULT 0 CHECK (pv_kw >= 0),
    scheme             TEXT    NOT NULL DEFAULT 'none' CHECK (scheme IN ('none', 'rooftop', 'kusum')),
    pv_commissioned_on TEXT
);

-- Hourly DTR meter data. net_kw = load_kw - solar_kw (negative = reverse power flow).
CREATE TABLE IF NOT EXISTS readings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    dtr_id     INTEGER NOT NULL REFERENCES dtrs(id) ON DELETE CASCADE,
    ts         TEXT    NOT NULL,           -- local time, 'YYYY-MM-DDTHH:00'
    load_kw    REAL    NOT NULL,
    solar_kw   REAL    NOT NULL,
    net_kw     REAL    NOT NULL,
    voltage_pu REAL    NOT NULL,
    UNIQUE (dtr_id, ts)
);

-- Hourly irradiance/temperature. kind = observed history or forecast.
CREATE TABLE IF NOT EXISTS weather (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    substation_id INTEGER NOT NULL REFERENCES substations(id) ON DELETE CASCADE,
    ts            TEXT    NOT NULL,
    kind          TEXT    NOT NULL CHECK (kind IN ('observed', 'forecast')),
    ghi_wm2       REAL    NOT NULL,
    temp_c        REAL    NOT NULL,
    cloud_pct     REAL,
    source        TEXT    NOT NULL,        -- 'meter-site', 'open-meteo', 'clearsky-model'
    fetched_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (substation_id, ts, kind)
);

-- Net-metering / PM-KUSUM solar applications awaiting technical clearance.
CREATE TABLE IF NOT EXISTS applications (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    dtr_id             INTEGER NOT NULL REFERENCES dtrs(id) ON DELETE CASCADE,
    consumer_id        INTEGER REFERENCES consumers(id) ON DELETE SET NULL,
    applicant_name     TEXT    NOT NULL,
    scheme             TEXT    NOT NULL CHECK (scheme IN ('rooftop', 'kusum')),
    requested_kw       REAL    NOT NULL CHECK (requested_kw > 0),
    status             TEXT    NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'evaluated', 'approved', 'rejected')),
    recommendation     TEXT    CHECK (recommendation IN ('clear', 'partial', 'reject')),
    recommended_kw     REAL,
    binding_constraint TEXT,
    decision_reason    TEXT,
    decision_reason_te TEXT,              -- Telugu version of decision_reason
    approved_kw        REAL,
    created_by         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    decided_by         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    evaluated_at       TEXT,
    decided_at         TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    dtr_id       INTEGER NOT NULL REFERENCES dtrs(id) ON DELETE CASCADE,
    alert_type   TEXT    NOT NULL CHECK (alert_type IN ('overvoltage', 'reverse_flow', 'saturation', 'pipeline')),
    severity     TEXT    NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    message      TEXT    NOT NULL,
    message_te   TEXT,                    -- Telugu version of message
    forecast_for TEXT,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Audit trail of every agent run, including LLM token usage.
CREATE TABLE IF NOT EXISTS agent_runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER REFERENCES users(id) ON DELETE SET NULL,
    kind              TEXT    NOT NULL CHECK (kind IN ('chat', 'scan')),
    question          TEXT,
    answer            TEXT,
    tools_used        TEXT,
    mode              TEXT    NOT NULL CHECK (mode IN ('azure', 'offline')),
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_readings_dtr_ts   ON readings (dtr_id, ts);
CREATE INDEX IF NOT EXISTS idx_weather_sub_ts    ON weather (substation_id, kind, ts);
CREATE INDEX IF NOT EXISTS idx_dtrs_feeder       ON dtrs (feeder_id);
CREATE INDEX IF NOT EXISTS idx_consumers_dtr     ON consumers (dtr_id);
CREATE INDEX IF NOT EXISTS idx_applications_dtr  ON applications (dtr_id, status);
CREATE INDEX IF NOT EXISTS idx_alerts_open       ON alerts (acknowledged, severity);
