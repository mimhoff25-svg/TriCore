-- TriCore Scanner Phase 3 starter schema.
-- SQL files use the sql_ prefix by convention.
-- This schema is SQLite-friendly first and can be adapted for MySQL later.

CREATE TABLE IF NOT EXISTS sdr_devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    device_type TEXT NOT NULL DEFAULT 'RTL-SDR',
    serial_number TEXT,
    host_name TEXT NOT NULL,
    gain_db REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scanner_systems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    system_type TEXT NOT NULL DEFAULT 'conventional',
    county TEXT,
    state TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scanner_sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scanner_system_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    site_number TEXT,
    notes TEXT,
    FOREIGN KEY (scanner_system_id) REFERENCES scanner_systems(id)
);

CREATE TABLE IF NOT EXISTS scanner_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scanner_system_id INTEGER NOT NULL,
    scanner_site_id INTEGER,
    channel_name TEXT NOT NULL,
    channel_id TEXT,
    frequency_hz INTEGER,
    modulation TEXT NOT NULL DEFAULT 'nfm',
    encrypted INTEGER NOT NULL DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0,
    favorite INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (scanner_system_id) REFERENCES scanner_systems(id),
    FOREIGN KEY (scanner_site_id) REFERENCES scanner_sites(id)
);

CREATE TABLE IF NOT EXISTS radio_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scanner_channel_id INTEGER,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TEXT,
    frequency_hz INTEGER,
    signal_power REAL,
    recording_path TEXT,
    FOREIGN KEY (scanner_channel_id) REFERENCES scanner_channels(id)
);

CREATE TABLE IF NOT EXISTS scanner_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL,
    scanner_state TEXT NOT NULL,
    message TEXT,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS rr_import_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    username TEXT,
    country TEXT,
    state TEXT,
    county TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS rr_raw_systems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rr_import_session_id INTEGER NOT NULL,
    rr_system_id TEXT,
    raw_name TEXT NOT NULL,
    raw_json TEXT,
    FOREIGN KEY (rr_import_session_id) REFERENCES rr_import_sessions(id)
);

CREATE TABLE IF NOT EXISTS rr_raw_sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rr_import_session_id INTEGER NOT NULL,
    rr_system_id TEXT,
    rr_site_id TEXT,
    raw_name TEXT NOT NULL,
    raw_json TEXT,
    FOREIGN KEY (rr_import_session_id) REFERENCES rr_import_sessions(id)
);

CREATE TABLE IF NOT EXISTS rr_raw_frequencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rr_import_session_id INTEGER NOT NULL,
    rr_system_id TEXT,
    rr_site_id TEXT,
    frequency_hz INTEGER,
    raw_label TEXT,
    raw_json TEXT,
    FOREIGN KEY (rr_import_session_id) REFERENCES rr_import_sessions(id)
);

CREATE TABLE IF NOT EXISTS rr_raw_talkgroups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rr_import_session_id INTEGER NOT NULL,
    rr_system_id TEXT,
    tgid TEXT,
    raw_alpha_tag TEXT,
    raw_description TEXT,
    encrypted INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT,
    FOREIGN KEY (rr_import_session_id) REFERENCES rr_import_sessions(id)
);

