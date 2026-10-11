"""Offline W01 snapshot reuse, fail closed on hash/cutoff/continuity differences."""

import hashlib
import json
from pathlib import Path

import pandas as pd

from trading_system.observer.frozen.alpha_lab.data import SYMBOLS, validate

from .engine import STEP

SNAPSHOT = Path("artifacts/w03")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_snapshot(root=SNAPSHOT):
    root = Path(root)
    lock = json.loads((root / "lock.json").read_text())
    # Check the entire existing frozen bundle, including historical Trend outputs.
    for path, expected in lock["files"].items():
        if sha256(path) != expected:
            raise ValueError(f"Frozen W03 bundle hash mismatch: {path}")
    manifest = json.loads((root / "results/cycle01/manifest.json").read_text())
    cutoff = pd.Timestamp(manifest["source_snapshot"]["cutoff_ms"], unit="ms", tz="UTC")
    if cutoff > pd.Timestamp("2026-10-03", tz="UTC"):
        raise ValueError("Snapshot includes data beyond 2026-10-02")
    begin = pd.Timestamp(manifest["common_raw_start"])
    start, end = pd.Timestamp(manifest["primary_start"]), pd.Timestamp(manifest["last_bar_open"])
    if start != begin + STEP * 201 or end + STEP != cutoff:
        raise ValueError("W01 evaluation/warmup boundary mismatch")
    frames, hashes = {}, {}
    for s in SYMBOLS:
        path = root / "historical" / f"{s}_4h.csv"
        hashes[s] = sha256(path)
        if hashes[s] != manifest["data_sha256"][s]:
            raise ValueError("Historical W01 data hash mismatch")
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index, utc=True)
        validate(df, allow_gaps=True)
        if (df.index + STEP > cutoff).any():
            raise ValueError("Unconfirmed or post-cutoff candle")
        df = df.loc[begin:end].copy()
        validate(df)
        if df.index[0] != begin or df.index[-1] != end:
            raise ValueError("Incomplete common sample")
        df["is_closed"] = True  # Frozen snapshot provenance, not a new live observation.
        frames[s] = df
    return (
        frames,
        start,
        end,
        {
            "historical_sha256": hashes,
            "w01_manifest_sha256": sha256(root / "results/cycle01/manifest.json"),
            "source_snapshot": manifest["source_snapshot"],
            "common_raw_start": str(begin),
            "evaluation_start_open": str(start),
            "last_bar_open": str(end),
            "evaluation_end_close": str(cutoff),
            "warmup_excluded": 201,
            "common_bars_with_warmup": len(frames[SYMBOLS[0]]),
            "raw_page_reverification": (
                "NOT_AVAILABLE_IN_REPOSITORY; verified existing clean CSV hashes"
            ),
        },
    )
