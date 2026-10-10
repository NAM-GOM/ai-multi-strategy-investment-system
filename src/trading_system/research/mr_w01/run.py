"""Run from repository root. Preflight gates all official baseline artifacts."""

import argparse
import json
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from trading_system.observer.frozen.alpha_lab.data import SYMBOLS

from .data import load_snapshot, sha256
from .engine import CONFIG, STEP, audit, run_portfolio
from .reporting import asset_results, benchmark, charts, classify, metrics
from .strategies import REGISTRY

BASE = "574eb63597e42724a6450abd0928458ae72c4b88"
GATES = {
    "P01": "Snapshot hashes, UTC, cutoff, OHLCV, continuous common sample",
    "P02": "Wilder seed/recurrence, EMA adjust=False, population standard deviation",
    "P03": "Prefix invariance, warmup mask, confirmed candles only",
    "P04": "Frozen RSI/Bollinger/Shock boolean conditions and no EMA forced exit",
    "P05": "Next Open scheduling, concurrent conditions, last signal not filled",
    "P06": "Signal ATR frozen, entry-bar Stop, adverse gap and exit priority",
    "P07": "Risk/cap/cash sizing, exits first, fixed BTC/ETH/SOL sequence",
    "P08": "No pyramiding, no duplicated signal entry, explicit terminal accounting",
    "P09": "Bilateral costs, net PnL, equity identity, failure detection",
    "P10": "Determinism, zero-trade path, equal-weight costed benchmark",
}


def frozen_audit():
    entries = subprocess.check_output(["git", "ls-tree", "-r", BASE], text=True).splitlines()
    for entry in entries:
        meta, path = entry.split("\t", 1)
        expected = meta.split()[2]
        actual = subprocess.check_output(["git", "hash-object", path], text=True).strip()
        if actual != expected:
            raise ValueError(f"Existing M04 baseline changed: {path}")
    return {"status": "PASS", "unchanged_existing_files": len(entries), "base_commit": BASE}


def preflight(out):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_mr_w01.py",
            "-q",
            f"--junitxml={out / 'preflight-tests.xml'}",
        ],
        capture_output=True,
        text=True,
    )
    (out / "preflight-tests.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    cases = ET.parse(out / "preflight-tests.xml").findall(".//testcase")
    counts = {}
    for gate in GATES:
        selected = [c for c in cases if c.attrib["name"].startswith(f"test_{gate}_")]
        counts[gate] = {
            "tests": len(selected),
            "status": "PASS"
            if selected
            and all(
                not any(c.find(tag) is not None for tag in ("failure", "error", "skipped"))
                for c in selected
            )
            else "FAIL",
        }
    status = (
        "MR_W01_PREFLIGHT_PASS"
        if result.returncode == 0 and all(c["status"] == "PASS" for c in counts.values())
        else "MR_W01_PREFLIGHT_STOP"
    )
    lines = [
        "# MR-W01 Preflight",
        "",
        status,
        "",
        "| Gate | Check | Tests | Result |",
        "| --- | --- | --- | --- |",
    ]
    lines += [
        f"| {g} | {description} | {counts[g]['tests']} | {counts[g]['status']} |"
        for g, description in GATES.items()
    ]
    lines += [
        "",
        "P01~P10 mapping is defined here because no earlier MR gate specification was",
        "provided. Gate thresholds are correctness checks, not profitability selection.",
        "Test output and JUnit evidence accompany this file. No live API is called.",
    ]
    (out / "MR-W01_preflight.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if status != "MR_W01_PREFLIGHT_PASS":
        raise RuntimeError(status)
    return {"status": status, "gates": counts, "passed": len(cases)}


def compute(data, start, end):
    results, signals, summaries, checks = {}, [], [], {}
    for key, strategy in REGISTRY.items():
        generated = {s: strategy.generate(df) for s, df in data.items()}
        ledger, curve = run_portfolio(generated, start, end, key)
        checks[key] = audit(ledger, curve)
        result = metrics(ledger, curve, start)
        summaries.append(
            {
                "strategy": key,
                "scope": "shared_portfolio",
                "classification": classify(result),
                **result,
            }
        )
        summaries.extend(asset_results(key, ledger, curve, start, SYMBOLS))
        results[key] = (ledger, curve)
        for s, frame in generated.items():
            signal = frame.loc[start:end].copy()
            signal.index.name = "signal_bar_open"
            signal["signal_confirmed_at"] = signal.index + STEP
            signal["next_open"] = signal.index + STEP
            signal["within_evaluation_next_open"] = signal.next_open <= end
            signal["strategy"], signal["symbol"] = key, s
            signals.append(signal.reset_index())
    b_ledger, b_curve = benchmark(data, start, end)
    np.testing.assert_allclose(b_curve.equity.iloc[-1], 100000 + b_ledger.net_pnl.sum(), atol=1e-5)
    results["equal_weight_buy_hold"] = (b_ledger, b_curve)
    summaries.append(
        {
            "strategy": "equal_weight_buy_hold",
            "scope": "benchmark",
            "classification": "BENCHMARK_NOT_CLASSIFIED",
            **metrics(b_ledger, b_curve, start),
        }
    )
    trades = pd.concat([t for t, _ in results.values()], ignore_index=True)
    equity = pd.concat(
        [c.assign(strategy=k).reset_index() for k, (_, c) in results.items()], ignore_index=True
    )
    return (
        pd.DataFrame(summaries),
        trades,
        pd.concat(signals, ignore_index=True),
        equity,
        results,
        checks,
    )


def write_report(out, summary, results, metadata):
    primary = summary[summary.scope.isin(["shared_portfolio", "benchmark"])]
    lines = [
        "# MR-W01 Baseline Report",
        "",
        "## FACT",
        "",
        "- Three independent candidates use one shared BTC/ETH/SOL portfolio each.",
        "- Binance Spot 4H, long only, no leverage/pyramiding; no exchange order endpoint.",
        f"- W01 evaluation: {metadata['evaluation_start_open']} "
        f"to {metadata['evaluation_end_close']}.",
        "- W01 clean CSV hashes and complete committed W03 lock verified. No new historical data.",
        "- Existing Trend T1/T2/T3, W03 classifications and W04/DEV-M02~M04 files unchanged.",
        "- MR rules fixed at v0.1; no parameter search, new filters or optimization.",
        "",
        "## ASSUMPTION",
        "",
        "- 100,000 USDT/candidate; 0.5% stop-distance risk; entry notional cap 33.3%.",
        "- Fees 10 bps/side, adverse slippage 5 bps/side; fractional units, no exchange filters.",
        "- Wilder uses SMA seeds, EMA200 adjust=False; both rolling standard deviations ddof=0.",
        "- 201 common warmup bars excluded, matching W01. Close signals fill next Open.",
        "- Stops remain EntryFill - 2.5*signal ATR20. Stop gaps fill adverse Open; exit first.",
        "- Simultaneous entries allocate BTC then ETH then SOL using shared cash and open equity.",
        "- Final close liquidation is explicit accounting, not a strategy exit or Time Stop.",
        "- Intrabar Stop timestamps use bar close: actual intrabar clock is "
        "unknown (holding-time estimate).",
        "- Asset rows attribute shared portfolio PnL to the same 100k "
        "reference; not standalone ROI.",
        "- Exposure is close-marked notional/equity; active-bar duration is a bar approximation.",
        "- Buy & Hold invests thirds including buy fees, no rebalance, same "
        "start Open/end Close costs.",
        "- Annualized ratios use 2,190 bars/year, zero risk-free rate. "
        "Undefined ratios remain blank.",
        "- Diagnostic conventions fixed: <30 trades INSUFFICIENT; positive net/PF>1/Sharpe>0",
        "  POSITIVE; negative net/PF<1 NEGATIVE; otherwise MIXED. Flags: asset absolute PnL share",
        "  >70%, any holding >30 days. These are reporting assumptions, not entry filters.",
        "",
        "## RESULT",
        "",
        "MR_W01_PREFLIGHT_PASS; MR_W01_BASELINE_COMPLETE.",
        "",
        "| Candidate | Total Return | CAGR | MDD | Sharpe | Trades | Net PnL "
        "USDT | Classification |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for _, row in primary.iterrows():
        sharpe = f"{row.sharpe:.3f}" if pd.notna(row.sharpe) else "undefined"
        lines.append(
            f"| {row.strategy} | {row.total_return:.2%} | {row.cagr:.2%} | "
            f"{row.mdd:.2%} | {sharpe} | {int(row.trade_count)} | "
            f"{row.net_pnl_usdt:.2f} | {row.classification} |"
        )
    lines += [
        "",
        "All requested metrics and asset attribution are in MR-W01_summary.csv.",
        "Signals record boolean conditions, not guaranteed fills; engine "
        "applies position/cash state.",
        "CSV outputs were independently recomputed and compared exactly before publication.",
        "",
        "## RISK",
        "",
        "- Historical in-sample diagnostics are not approval, profitability "
        "proof or W04 Forward validation.",
        "- Original raw API pages are absent here; verified CSV/manifest "
        "provenance is not raw-page re-audit.",
        "- Gap losses and costs can exceed 0.5%; passive appreciation can "
        "exceed entry allocation cap.",
        "- Bar-close equity underestimates intrabar drawdown; live "
        "liquidity/fill probability not modeled.",
        "- SOL receives cash last; report sequencing effects without changing the frozen order.",
    ]
    for key, (trades, curve) in results.items():
        if key == "equal_weight_buy_hold":
            continue
        pnl = np.array([abs(float(curve[f"{s}_pnl"].iloc[-1])) for s in SYMBOLS])
        share = float(pnl.max() / pnl.sum()) if pnl.sum() else 0.0
        longest = (
            float(
                (
                    pd.to_datetime(trades.exit_time, utc=True)
                    - pd.to_datetime(trades.entry_time, utc=True)
                )
                .dt.total_seconds()
                .max()
                / 3600
            )
            if len(trades)
            else 0.0
        )
        lines.append(
            f"- {key}: trades={len(trades)}, max absolute asset PnL share={share:.2%}, "
            f"concentration_flag={share > 0.70}, longest_hold_hours={longest:.1f}, "
            f"long_hold_flag={longest > 720}, terminal_exits="
            f"{int((trades.exit_reason == 'END_OF_TEST').sum())}."
        )
    lines += [
        "",
        "## DECISION",
        "",
        "Diagnostic labels do not mean APPROVED. Trend W03 classifications unchanged.",
    ]
    for _, row in primary[primary.scope == "shared_portfolio"].iterrows():
        recommendation = (
            "Continue diagnostics, not deployment"
            if row.classification == "POSITIVE_DIAGNOSTIC"
            else "Limited diagnostic continuation; establish failure causes before advancing"
        )
        lines.append(f"- {row.strategy}: {row.classification}. {recommendation}.")
    lines += [
        "",
        "## NEXT ACTION",
        "",
        "- M1 MR-W02: RSI recovery trades by regime/asset, cost burden and stop/holding tails.",
        "- M2 MR-W02: band recovery false positives, drawdown episodes and concentration.",
        "- M3 MR-W02: shock clusters, sparse signals, gap loss and "
        "prior-volatility regime dependence.",
        "- All: diagnostic subperiod/out-of-sample stability and "
        "benchmark-relative risk; retain v0.1.",
        "- No strategy approval, live execution or W04 Formal Clock activation is granted.",
    ]
    (out / "MR-W01_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/mr-w01"))
    args = parser.parse_args(argv)
    out = args.output
    out.mkdir(parents=True, exist_ok=False)  # Preserve previous reports, do not overwrite.
    manifest = {"status": "MR_W01_PREFLIGHT_HOLD", "base_commit": BASE}
    try:
        manifest["preservation"] = frozen_audit()
        manifest["preflight"] = preflight(out)
        data, start, end, metadata = load_snapshot()
        first, second = compute(data, start, end), compute(data, start, end)
        for a, b in zip(first[:4], second[:4]):
            pd.testing.assert_frame_equal(a, b, check_exact=True)
        summary, trades, signals, equity, results, audits = first
        for name, table in zip(("summary", "trades", "signals", "equity"), first[:4]):
            table.to_csv(out / f"MR-W01_{name}.csv", index=False, float_format="%.17g")
        charts(results, out / "MR-W01_charts")
        write_report(out, summary, results, metadata)
        manifest.update(
            status="MR_W01_BASELINE_COMPLETE",
            dataset=metadata,
            config=asdict(CONFIG),
            stop_atr_multiple=2.5,
            parameters={
                "rsi_period": 14,
                "rsi_entry": 30,
                "rsi_exit": 50,
                "atr_period": 20,
                "ema_period": 200,
                "bb_period": 20,
                "bb_sigma": 2,
                "std_ddof": 0,
                "shock_return_bars": 3,
                "shock_std_period": 60,
                "shock_sigma": 2,
                "wilder_seed": "SMA",
                "ema_adjust": False,
            },
            entry_order=list(SYMBOLS),
            python=platform.python_version(),
            pandas=pd.__version__,
            numpy=np.__version__,
            reproducibility="EXACT_RECOMPUTATION_PASS",
            accounting_audits=audits,
            code_sha256={
                str(p): sha256(p)
                for p in sorted(Path("src/trading_system/research/mr_w01").glob("*.py"))
            },
            test_sha256=sha256("tests/test_mr_w01.py"),
            artifact_sha256={
                str(p.relative_to(out)): sha256(p) for p in sorted(out.rglob("*")) if p.is_file()
            },
            classifications=dict(
                zip(
                    summary[summary.scope == "shared_portfolio"].strategy,
                    summary[summary.scope == "shared_portfolio"].classification,
                )
            ),
        )
        manifest["preservation"] = frozen_audit()
        print(
            summary[summary.scope.isin(["shared_portfolio", "benchmark"])][
                ["strategy", "total_return", "mdd", "trade_count", "classification"]
            ].to_string(index=False)
        )
    except Exception as exc:
        manifest.update(
            status="MR_W01_PREFLIGHT_STOP", error_category=type(exc).__name__, error=str(exc)
        )
        raise
    finally:
        (out / "MR-W01_manifest.json").write_text(
            json.dumps(manifest, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
