# DEV-E02 Risk & Order Limit Specification

| Rule | Implementation / outcome |
|---|---|
| T1 | `trend_ma_v0.1` only; BTCUSDT / ETHUSDT / SOLUSDT |
| T2/T3 | Original router shadow only; final HTTP boundary rejects ownership |
| Capital | Exactly 1000 USDT initial allocation; account free >=1000 before allocation |
| Risk / asset cap | Frozen 0.5% / 33.3%, never overridden by executor |
| Direction/order | Long only, LIMIT GTC; no margin/leverage/live endpoint |
| Notional | Decimal 8.31 USDT inclusive for BUY and SELL, never round up |
| Three cap checks | Sizing/raw validation, normalized filters, final HTTP request |
| Minimum | All LOT_SIZE/PRICE_FILTER/MIN_NOTIONAL/NOTIONAL filters pass; otherwise skip |
| Existing E01 ceilings | <=3 attempts per UTC day, <=40 USDT/day, <=1 open order |
| Protective reserve | Current and proposed marked exposure require capped exit slots and daily amount |
| Price | Existing E01 spread/difference limits, quote <=5s, production reference <=30s |
| Signal | Confirmed 4H LIVE only, original <=60s first execution window |
| Dependency | Both fresh READY; old boot/restarted instance blocks final submission |
| Uncertainty | UNKNOWN_EXECUTION, API errors, DB errors, account mismatches => OFF/HOLD |

Filters floor quantity and price independently. `quantity × price > 8.31` is
rejected before rounding even if exchange rounding would bring it below cap.
An order exactly at 8.31 can pass only if all other rules pass. A venue minimum
above 8.31 produces no order; capital is never raised to satisfy that minimum.

Daily attempts include original/manual/failed/uncertain attempted submissions,
across sessions; POST order/test is not an execution attempt. Reserve counts
per-asset ceil(marked notional / 8.31), not ceil(total combined assets / 8.31).
Entry consumes a slot plus the reserved exit slots. Price movement can increase
needed slots after entry; protection then reports HOLD without raising the cap.

Pending BUY remainder adds future protective exposure. Pending SELL unfilled
remainder reduces uncovered exposure and its attempt already consumes its slot.
Current exit filters and free balance are tested without sending a test/order.
After partial fills/cancel, dust below minimum causes `MIN_NOTIONAL` HOLD. The
E01 conservative 1% balance buffer on SELL also remains; inability to satisfy it
must be reviewed rather than relaxing E01. Stops and normal exits share daily
limits; there is no emergency exemption, MARKET order, new funding or manual override.

Testnet faucet holdings and order1507111 are not T1-owned assets. Allocation and
position seals plus exchange fill/account delta reconciliation establish ownership.
Orders/PnL are restored from durable fills, not assumed from POST success.
