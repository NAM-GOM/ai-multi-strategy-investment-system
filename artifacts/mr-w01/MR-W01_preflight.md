# MR-W01 Preflight

MR_W01_PREFLIGHT_PASS

| Gate | Check | Tests | Result |
| --- | --- | --- | --- |
| P01 | Snapshot hashes, UTC, cutoff, OHLCV, continuous common sample | 8 | PASS |
| P02 | Wilder seed/recurrence, EMA adjust=False, population standard deviation | 2 | PASS |
| P03 | Prefix invariance, warmup mask, confirmed candles only | 3 | PASS |
| P04 | Frozen RSI/Bollinger/Shock boolean conditions and no EMA forced exit | 1 | PASS |
| P05 | Next Open scheduling, concurrent conditions, last signal not filled | 2 | PASS |
| P06 | Signal ATR frozen, entry-bar Stop, adverse gap and exit priority | 3 | PASS |
| P07 | Risk/cap/cash sizing, exits first, fixed BTC/ETH/SOL sequence | 2 | PASS |
| P08 | No pyramiding, no duplicated signal entry, explicit terminal accounting | 1 | PASS |
| P09 | Bilateral costs, net PnL, equity identity, failure detection | 1 | PASS |
| P10 | Determinism, zero-trade path, equal-weight costed benchmark | 1 | PASS |

P01~P10 mapping is defined here because no earlier MR gate specification was
provided. Gate thresholds are correctness checks, not profitability selection.
Test output and JUnit evidence accompany this file. No live API is called.
