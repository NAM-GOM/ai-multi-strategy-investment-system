CREATE TABLE price_snapshots (
    symbol TEXT NOT NULL CHECK(symbol IN ('BTCUSDT','ETHUSDT','SOLUSDT')),
    bucket_start_ms INTEGER NOT NULL CHECK(bucket_start_ms >= 0),
    price_text TEXT NOT NULL,
    event_time_ms INTEGER NOT NULL CHECK(event_time_ms >= 0),
    received_at_ms INTEGER NOT NULL CHECK(received_at_ms >= 0),
    source TEXT NOT NULL CHECK(source = 'binance_spot'),
    PRIMARY KEY(symbol, bucket_start_ms)
) STRICT;
CREATE TABLE candles_4h (
    symbol TEXT NOT NULL CHECK(symbol IN ('BTCUSDT','ETHUSDT','SOLUSDT')),
    interval TEXT NOT NULL CHECK(interval = '4h'),
    open_time_ms INTEGER NOT NULL CHECK(open_time_ms >= 0 AND open_time_ms % 14400000 = 0),
    close_time_ms INTEGER NOT NULL CHECK(close_time_ms = open_time_ms + 14400000 - 1),
    open_text TEXT NOT NULL,
    high_text TEXT NOT NULL,
    low_text TEXT NOT NULL,
    close_text TEXT NOT NULL,
    volume_text TEXT NOT NULL,
    event_time_ms INTEGER,
    ingested_at_ms INTEGER NOT NULL CHECK(ingested_at_ms > close_time_ms),
    source TEXT NOT NULL CHECK(source IN ('WS_LIVE','REST_BOOTSTRAP','REST_RECOVERY')),
    CHECK(source != 'WS_LIVE' OR (event_time_ms IS NOT NULL AND event_time_ms > close_time_ms)),
    PRIMARY KEY(symbol, interval, open_time_ms)
) STRICT;
CREATE TABLE data_gaps (
    gap_id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL CHECK(symbol IN ('BTCUSDT','ETHUSDT','SOLUSDT')),
    interval TEXT NOT NULL CHECK(interval = '4h'),
    start_time_ms INTEGER NOT NULL CHECK(start_time_ms >= 0 AND start_time_ms % 14400000 = 0),
    end_time_ms INTEGER NOT NULL CHECK(end_time_ms >= start_time_ms AND end_time_ms % 14400000 = 0),
    detected_at_ms INTEGER NOT NULL,
    detected_reason TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('OPEN','RECOVERING','RESOLVED','FAILED','CONFLICT')),
    resolution_source TEXT,
    resolved_at_ms INTEGER,
    UNIQUE(symbol, interval, start_time_ms, end_time_ms, detected_reason)
) STRICT;
CREATE TABLE ingestion_runs (
    run_id TEXT PRIMARY KEY,
    started_at_ms INTEGER NOT NULL,
    ended_at_ms INTEGER,
    execution_environment TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('RUNNING','COMPLETED','INCOMPLETE','PERSISTENCE_FAILURE',
                                         'BLOCKED_ENVIRONMENT','INTERRUPTED')),
    messages_received INTEGER NOT NULL DEFAULT 0,
    price_snapshots_written INTEGER NOT NULL DEFAULT 0,
    candles_written INTEGER NOT NULL DEFAULT 0,
    duplicate_candles INTEGER NOT NULL DEFAULT 0,
    gaps_detected INTEGER NOT NULL DEFAULT 0,
    gaps_resolved INTEGER NOT NULL DEFAULT 0,
    reconnect_count INTEGER NOT NULL DEFAULT 0,
    error_category TEXT
) STRICT;
CREATE TABLE candle_conflicts (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    open_time_ms INTEGER NOT NULL,
    incoming_fingerprint TEXT NOT NULL,
    existing_data TEXT NOT NULL,
    incoming_data TEXT NOT NULL,
    detected_at_ms INTEGER NOT NULL,
    PRIMARY KEY(symbol, interval, open_time_ms, incoming_fingerprint)
) STRICT;
PRAGMA user_version = 1;
