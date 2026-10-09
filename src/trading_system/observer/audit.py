"""Verify byte-preserved W03 inputs and replay its original engine offline."""

import hashlib
import importlib.metadata
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from trading_system.config import SYMBOLS
from trading_system.observer.model import ObserverError, ObserverState, digest

ROOT = Path(__file__).resolve().parents[3]
LOCK = ROOT / "artifacts/w03/lock.json"
LOCK_SHA256 = "b1659e920f6b5e718a9073ddca8a0c91f6ae16993100af9d3a57758d73a68d30"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_audit():
    try:
        if sha(LOCK) != LOCK_SHA256:
            raise ObserverError("FROZEN_LOCK_CHANGED", ObserverState.RULE_MISMATCH_STOP)
        lock = json.loads(LOCK.read_text())
        manifest = json.loads((ROOT / "artifacts/w03/W03_manifest.json").read_text())
        failures = [p for p, h in lock["files"].items() if sha(ROOT / p) != h]
        for path, expected in manifest["original_code_sha256"].items():
            if sha(ROOT / lock["mapping"][path]) != expected:
                failures.append(path)
        for path, expected in manifest["config_sha256"].items():
            if sha(ROOT / lock["mapping"][path]) != expected:
                failures.append(path)
        for symbol in SYMBOLS:
            path = f"data/cycle01/{symbol}_4h.csv"
            if sha(ROOT / lock["mapping"][path]) != manifest["data_sha256"][path]:
                failures.append(path)
        for name, version in lock["dependencies"].items():
            if importlib.metadata.version(name) != version:
                failures.append(name)
        if lock["original_package_sha256"] != manifest["original_package_sha256"]:
            failures.append("original_package")
        if failures:
            raise ObserverError(
                "SOURCE_CONFIG_DATA_HASH_MISMATCH", ObserverState.RULE_MISMATCH_STOP
            )
        from trading_system.observer.frozen.alpha_lab.strategies import STRATEGY_REGISTRY

        expected_parameters = {
            "trend_ma_v0.1": {"fast_ema": 50, "slow_ema": 200},
            "trend_donchian_v0.1": {"entry_lookback": 55, "exit_lookback": 20},
            "trend_tsmom_v0.1": {"lookback": 180},
        }
        if set(STRATEGY_REGISTRY) != set(expected_parameters) or any(
            asdict(strategy.config) != expected_parameters[key]
            or strategy.version != "0.1"
            or strategy.atr_period != 20
            or strategy.atr_stop_multiple != 3.0
            for key, strategy in STRATEGY_REGISTRY.items()
        ):
            raise ObserverError("RUNTIME_PARAMETER_MISMATCH", ObserverState.RULE_MISMATCH_STOP)
        return {
            "verification_status": "SOURCE_HASH_PASS",
            "manifest_hash": digest(lock),
            "source_hash": manifest["original_code_sha256"]["alpha_lab/strategies.py"],
            "parameter_hash": manifest["config_sha256"]["config/w03_temporal_robustness.yaml"],
            "baseline_hash": digest(manifest["original_files_sha256"]),
            "market_data_commit": lock["market_data_commit"],
            "versions": manifest["strategy_versions"],
            "files_verified": len(lock["files"]),
            "data_hashes": {
                s: manifest["data_sha256"][f"data/cycle01/{s}_4h.csv"] for s in SYMBOLS
            },
            "w03_classifications": manifest["classifications"],
            "formal_w04_started": False,
        }
    except OSError, KeyError, ValueError, importlib.metadata.PackageNotFoundError:
        raise ObserverError(
            "BLOCKED_MISSING_FROZEN_ARTIFACT", ObserverState.RULE_MISMATCH_STOP
        ) from None


def historical_frames():
    manifest = json.loads((ROOT / "artifacts/w03/results/cycle01/manifest.json").read_text())
    frames = {}
    for symbol in SYMBOLS:
        # This is W03's original default float parser and common initialization start.
        frame = pd.read_csv(ROOT / f"artifacts/w03/historical/{symbol}_4h.csv", index_col=0)
        frame.index = pd.to_datetime(frame.index, utc=True)
        frames[symbol] = frame.loc[manifest["common_raw_start"] : manifest["last_bar_open"]]
    return manifest, frames


def csv_content(value):
    # ZIP's CSV transport has CRCRLF; numeric strings/order/timestamps are unchanged.
    return "\n".join(line for line in value.replace("\r", "").split("\n") if line)


def reproduction_gate():
    audit = source_audit()
    # Import only after verifying the preserved sources.
    from trading_system.observer.frozen.alpha_lab.cycle import generate_segments
    from trading_system.observer.frozen.alpha_lab.engine import BacktestConfig, run_portfolio
    from trading_system.observer.frozen.alpha_lab.strategies import STRATEGY_REGISTRY

    manifest, frames = historical_frames()
    combinations, checks = [], []
    for key, strategy in STRATEGY_REGISTRY.items():
        signals = {s: generate_segments(strategy, frame) for s, frame in frames.items()}
        ledger, curve = run_portfolio(
            signals,
            manifest["primary_start"],
            manifest["last_bar_open"],
            BacktestConfig(**manifest["config"]),
            strategy_key=key,
        )
        for name, actual in (
            ("trade_ledger.csv", ledger.to_csv(index=False)),
            ("equity_curve.csv", curve.to_csv()),
        ):
            path = ROOT / f"artifacts/w03/results/cycle01/common_portfolio/{key}/{name}"
            matched = csv_content(actual) == csv_content(path.read_text())
            checks.append({"strategy_id": key, "artifact": name, "matched": matched})
            if not matched:
                raise ObserverError("W03_REPRODUCTION_MISMATCH", ObserverState.RULE_MISMATCH_STOP)
        for symbol, signal in signals.items():
            # Independent prefix regeneration compares all indicator/boolean columns exactly.
            prefix = generate_segments(strategy, frames[symbol].iloc[:-1])
            if not prefix.equals(signal.iloc[:-1]):
                raise ObserverError("FUTURE_INFORMATION", ObserverState.RULE_MISMATCH_STOP)
            combinations.append(
                {
                    "strategy_id": key,
                    "symbol": symbol,
                    "bars": len(signal),
                    "entry_conditions": int(signal.entry_long.sum()),
                    "exit_conditions": int(signal.exit_long.sum()),
                    "completed_reference_trades": int((ledger.symbol == symbol).sum()),
                    "warmup_bars_from_frozen_source": strategy.warmup_bars,
                    "signal_hash": digest(signal[["entry_long", "exit_long"]].to_csv()),
                    "indicator_prefix_exact": True,
                    "position_stop_timing_basis": "EXACT_FROZEN_ENGINE_LEDGER_AND_EQUITY_PARITY",
                }
            )
    return {
        **audit,
        "verification_status": "W03_REPRODUCTION_PASS",
        "combinations": combinations,
        "checks": checks,
        "indicator_reference_scope": (
            "Original engine entry ATR/stop ledger + exact source/prefix parity; "
            "no independent full-bar W03 indicator dump exists"
        ),
    }
