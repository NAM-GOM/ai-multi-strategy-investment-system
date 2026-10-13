"""Additive tables in the existing dedicated execution SQLite, never M03/M04."""

from trading_system.testnet.store import Store

SCHEMA = """
CREATE TABLE IF NOT EXISTS strategy_allocations (
 session_id TEXT NOT NULL, strategy_id TEXT NOT NULL, initial_capital TEXT NOT NULL,
 cash TEXT NOT NULL, projection_hash TEXT NOT NULL, PRIMARY KEY(session_id,strategy_id)
);
CREATE TABLE IF NOT EXISTS positions (
 session_id TEXT NOT NULL, strategy_id TEXT NOT NULL, symbol TEXT NOT NULL,
 quantity TEXT NOT NULL, cost TEXT NOT NULL, realized_pnl TEXT NOT NULL,
 initial_stop TEXT NOT NULL, average_fill TEXT NOT NULL,
 entry_gross_quantity TEXT NOT NULL, entry_gross_quote TEXT NOT NULL,
 PRIMARY KEY(session_id,strategy_id,symbol)
);
CREATE TABLE IF NOT EXISTS signal_receipts (
 signal_key TEXT PRIMARY KEY, decision_hash TEXT NOT NULL, session_id TEXT NOT NULL,
 strategy_id TEXT NOT NULL, symbol TEXT NOT NULL, bar_open_ms INTEGER NOT NULL,
 outcome TEXT NOT NULL, client_id TEXT UNIQUE, atr TEXT NOT NULL,
 production_reference TEXT NOT NULL, executable_price TEXT NOT NULL,
 quote_received_ms INTEGER NOT NULL, classification TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS router_checkpoints (
 session_id TEXT PRIMARY KEY, observer_path TEXT NOT NULL, market_path TEXT NOT NULL,
 activated_ms INTEGER NOT NULL, last_rowid INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS position_fills (
 session_id TEXT NOT NULL, symbol TEXT NOT NULL, trade_id INTEGER NOT NULL,
 strategy_id TEXT NOT NULL, fill_hash TEXT NOT NULL,
 PRIMARY KEY(session_id,symbol,trade_id)
);
CREATE TABLE IF NOT EXISTS execution_gates (
 session_id TEXT NOT NULL, gate TEXT NOT NULL, completed_ms INTEGER NOT NULL,
 evidence TEXT NOT NULL, PRIMARY KEY(session_id,gate)
);
CREATE VIEW IF NOT EXISTS execution_sessions AS SELECT * FROM testnet_sessions;
CREATE VIEW IF NOT EXISTS fills AS SELECT * FROM executions;
CREATE VIEW IF NOT EXISTS balances AS SELECT * FROM balance_snapshots;
"""


class ExecutionStore(Store):
    extension_tables = frozenset(
        {
            "strategy_allocations",
            "positions",
            "signal_receipts",
            "router_checkpoints",
            "position_fills",
            "execution_gates",
        }
    )

    def __init__(self, path="data/testnet_execution.sqlite"):
        super().__init__(path)
        self.db.executescript(SCHEMA)

    def gate(self, sid, gate, now, evidence):
        # Called inside the same transaction as the verified operation.
        self.db.execute(
            "INSERT INTO execution_gates VALUES(?,?,?,?) ON CONFLICT(session_id,gate) "
            "DO UPDATE SET completed_ms=excluded.completed_ms,evidence=excluded.evidence",
            (sid, gate, now, evidence),
        )
