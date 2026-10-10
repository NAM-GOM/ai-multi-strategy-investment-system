"""Independent durable journal. Text decimals, session-scoped exchange identities."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .client import TestnetError

SCHEMA = """
CREATE TABLE IF NOT EXISTS testnet_sessions (
 id TEXT PRIMARY KEY, created_ms INTEGER NOT NULL, active INTEGER NOT NULL,
 fingerprint TEXT NOT NULL, kill INTEGER NOT NULL DEFAULT 0, hold TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_session ON testnet_sessions(active) WHERE active=1;
CREATE TABLE IF NOT EXISTS order_intents (
 client_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES testnet_sessions(id),
 created_ms INTEGER NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL,
 quantity TEXT NOT NULL, price TEXT NOT NULL, notional TEXT NOT NULL,
 state TEXT NOT NULL, checked_ms INTEGER, attempted_ms INTEGER
);
CREATE TABLE IF NOT EXISTS exchange_orders (
 session_id TEXT NOT NULL, symbol TEXT NOT NULL, order_id INTEGER NOT NULL,
 client_id TEXT NOT NULL, status TEXT NOT NULL, executed_qty TEXT NOT NULL,
 quote_qty TEXT NOT NULL, updated_ms INTEGER NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(session_id,symbol,order_id), UNIQUE(session_id,client_id)
);
CREATE TABLE IF NOT EXISTS executions (
 session_id TEXT NOT NULL, symbol TEXT NOT NULL, trade_id INTEGER NOT NULL,
 order_id INTEGER NOT NULL, price TEXT NOT NULL, quantity TEXT NOT NULL,
 quote_qty TEXT NOT NULL, commission TEXT NOT NULL, commission_asset TEXT NOT NULL,
 time_ms INTEGER NOT NULL, is_buyer INTEGER NOT NULL,
 PRIMARY KEY(session_id,symbol,trade_id)
);
CREATE TABLE IF NOT EXISTS balance_snapshots (
 session_id TEXT NOT NULL, snapshot_id TEXT NOT NULL, time_ms INTEGER NOT NULL,
 asset TEXT NOT NULL, free TEXT NOT NULL, locked TEXT NOT NULL,
 PRIMARY KEY(session_id,snapshot_id,asset)
);
CREATE TABLE IF NOT EXISTS reconciliation_events (
 id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, time_ms INTEGER NOT NULL,
 kind TEXT NOT NULL, details TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS risk_events (
 id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, time_ms INTEGER NOT NULL,
 kind TEXT NOT NULL, client_id TEXT
);
"""


class Store:
    extension_tables = frozenset()

    def __init__(self, path="data/testnet_execution.sqlite"):
        target = Path(path)
        # CLI cannot accidentally point at a market/observer database.
        if target.name != "testnet_execution.sqlite":
            raise TestnetError("DEDICATED_DB_REQUIRED")
        target.parent.mkdir(parents=True, exist_ok=True)
        self.failed = False
        self.db = sqlite3.connect(target, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        existing = {
            r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        permitted = {
            "testnet_sessions",
            "order_intents",
            "exchange_orders",
            "executions",
            "balance_snapshots",
            "reconciliation_events",
            "risk_events",
        }
        if existing - (permitted | self.extension_tables):
            self.close()
            raise TestnetError("FOREIGN_DB_REJECTED")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        if self.failed:
            raise TestnetError("DB_FAILED")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            yield
            self.db.execute("COMMIT")
        except BaseException as error:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            if isinstance(error, sqlite3.Error):
                self.failed = True
                raise TestnetError("DB_FAILED") from None
            raise

    def rows(self, sql, params=()):
        try:
            return [dict(r) for r in self.db.execute(sql, params)]
        except sqlite3.Error:
            self.failed = True
            raise TestnetError("DB_FAILED") from None

    def session(self):
        rows = self.rows("SELECT * FROM testnet_sessions WHERE active=1")
        return rows[0] if rows else None

    def start_session(self, fingerprint, now, *, acknowledge_reset=False):
        with self.transaction():
            current = self.session()
            if current and not acknowledge_reset:
                if current["fingerprint"] != fingerprint:
                    # Bind an offline-only, empty-key session once credentials are supplied.
                    import hashlib

                    empty_key = hashlib.sha256(b"").hexdigest()
                    history = self.rows(
                        "SELECT client_id FROM order_intents WHERE session_id=? "
                        "AND attempted_ms IS NOT NULL",
                        (current["id"],),
                    )
                    snapshots = self.rows(
                        "SELECT snapshot_id FROM balance_snapshots WHERE session_id=? LIMIT 1",
                        (current["id"],),
                    )
                    if current["fingerprint"] != empty_key or history or snapshots:
                        raise TestnetError("ACCOUNT_CHANGED_NEW_SESSION_REQUIRED")
                    self.db.execute(
                        "UPDATE testnet_sessions SET fingerprint=? WHERE id=?",
                        (fingerprint, current["id"]),
                    )
                return current["id"]
            if current:
                self.db.execute("UPDATE testnet_sessions SET active=0 WHERE active=1")
            sid = uuid4().hex
            self.db.execute(
                "INSERT INTO testnet_sessions(id,created_ms,active,fingerprint) VALUES(?,?,1,?)",
                (sid, now, fingerprint),
            )
            # A new epoch must not silently disable an existing emergency stop.
            if current and current["kill"]:
                self.db.execute("UPDATE testnet_sessions SET kill=1 WHERE id=?", (sid,))
            self.event(
                sid,
                now,
                "SESSION_STARTED",
                {
                    "previous_session": current["id"] if current else None,
                    "reset_acknowledged": acknowledge_reset,
                },
            )
            return sid

    def event(self, sid, now, kind, details=""):
        self.db.execute(
            "INSERT INTO reconciliation_events(session_id,time_ms,kind,details) VALUES(?,?,?,?)",
            (sid, now, kind, json.dumps(details, sort_keys=True)),
        )

    def hold(self, sid, now, kind):
        with self.transaction():
            self.db.execute("UPDATE testnet_sessions SET hold=? WHERE id=?", (kind, sid))
            self.event(sid, now, kind)

    def kill(self, sid, now, enabled):
        with self.transaction():
            self.db.execute("UPDATE testnet_sessions SET kill=? WHERE id=?", (int(enabled), sid))
            self.db.execute(
                "INSERT INTO risk_events(session_id,time_ms,kind) VALUES(?,?,?)",
                (sid, now, "KILL_ON" if enabled else "KILL_OFF"),
            )
