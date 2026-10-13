"""Unmodified Frozen boolean conditions; execution state belongs to W04."""

import math

from trading_system.observer.gate import history_hash
from trading_system.observer.model import ObserverError, SignalDecision


class StrategyAdapter:
    def __init__(self, audit):
        from trading_system.observer.frozen.alpha_lab.cycle import generate_segments
        from trading_system.observer.frozen.alpha_lab.strategies import STRATEGY_REGISTRY

        self.registry, self.generate = STRATEGY_REGISTRY, generate_segments
        self.audit = audit

    def evaluate(self, strategy_id, symbol, confirmed_candle_history, frozen_state):
        context = frozen_state
        frame = confirmed_candle_history
        strategy = self.registry[strategy_id]
        if history_hash(frame, context["provenance"]) != context["input_hash"]:
            raise ObserverError("INPUT_HASH_MISMATCH")
        # W03 masks the first warmup_bars rows; row warmup_bars is the first eligible row.
        if len(frame) <= strategy.warmup_bars:
            raise ObserverError("INSUFFICIENT_FROZEN_WARMUP")
        if frame.index[-1].value // 1_000_000 != context["target_ms"]:
            raise ObserverError("FUTURE_INFORMATION")
        row = self.generate(strategy, frame).iloc[-1]
        indicators = {
            k: (float(v) if math.isfinite(float(v)) else None)
            for k, v in row.items()
            if k not in frame.columns and k not in ("entry_long", "exit_long")
        }
        if indicators["atr"] is None:
            raise ObserverError("INDICATOR_NOT_READY")
        entry, exit_ = bool(row.entry_long), bool(row.exit_long)
        if entry and exit_:
            raise ObserverError("AMBIGUOUS_FROZEN_RULE")
        indicators.update(
            entry_long=entry,
            exit_long=exit_,
            position_state_basis="CONDITION_ONLY_NO_POSITION_MUTATION",
            stop_initialization="NEXT_BAR_FILL_MINUS_3_TIMES_SIGNAL_ATR_IN_W04_ENGINE",
        )
        return SignalDecision(
            strategy_id,
            strategy.version,
            symbol,
            "4h",
            context["target_ms"],
            context["target_ms"] + 14_400_000 - 1,
            "ENTRY_CANDIDATE" if entry else "EXIT_CANDIDATE" if exit_ else "NO_ACTION",
            "FROZEN_ENTRY_BOOLEAN"
            if entry
            else "FROZEN_EXIT_BOOLEAN"
            if exit_
            else "FROZEN_NO_CONDITION",
            indicators,
            context["input_hash"],
            self.audit["source_hash"],
            self.audit["parameter_hash"],
            context["evaluated_at"],
            context["mode"],
            context["provenance"],
        )
