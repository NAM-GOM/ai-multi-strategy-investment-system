"""Observer records describe conditions, never orders or fills."""

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum

from trading_system.persistence.records import INTERVAL_MS

FREEZE_MS = 1790942400000  # 2026-10-02T12:00:00Z
STRATEGIES = ("trend_ma_v0.1", "trend_donchian_v0.1", "trend_tsmom_v0.1")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class ObserverState(StrEnum):
    INITIALIZING = "INITIALIZING"
    WARMING_UP = "WARMING_UP"
    READY = "READY"
    OBSERVING = "OBSERVING"
    DATA_HOLD = "DATA_HOLD"
    RULE_MISMATCH_STOP = "RULE_MISMATCH_STOP"
    PERSISTENCE_STOP = "PERSISTENCE_STOP"
    STOPPED = "STOPPED"


class ObserverError(Exception):
    def __init__(self, category, state=ObserverState.DATA_HOLD):
        self.category, self.state = category, state
        super().__init__(category)


@dataclass(frozen=True)
class SignalDecision:
    strategy_id: str
    strategy_version: str
    symbol: str
    timeframe: str
    evaluated_bar_open_ms: int
    evaluated_bar_close_ms: int
    decision: str
    signal_reason: str
    indicator_snapshot: dict
    input_data_hash: str
    strategy_code_hash: str
    parameter_hash: str
    evaluation_time_ms: int
    observation_mode: str
    data_provenance: dict

    @property
    def decision_hash(self):
        record = asdict(self)
        # Wall-clock evaluation time is not part of deterministic decision identity.
        record.pop("evaluation_time_ms")
        return digest(record)


def classify(open_ms, provenance, live_floor_ms, evaluated_at):
    if open_ms + INTERVAL_MS <= FREEZE_MS:
        return "SEEN_HISTORICAL_DATA"
    if (
        open_ms + INTERVAL_MS > live_floor_ms
        and provenance["source"] == "WS_LIVE"
        and live_floor_ms <= provenance["ingested_at_ms"] <= evaluated_at
    ):
        return "LIVE_OBSERVATION"
    return "PRELAUNCH_STATE_BACKFILL"
