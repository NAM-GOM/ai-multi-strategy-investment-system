# DEV-E01 — isolated Spot Testnet execution

This document preserves the previously validated manual adapter design at
`9612b240`. The current M04 integration extends it as described in
[DEV-E01-architecture.md](DEV-E01-architecture.md); use the integrated CLI for
strategy allocations and Router work. Existing manual APIs remain available on
legacy journals.

Issue: https://github.com/NAM-GOM/ai-multi-strategy-investment-system/issues/5

Source baseline: `574eb63597e42724a6450abd0928458ae72c4b88` (DEV-M04).
Branch: `dev-e01-binance-spot-testnet-execution`.

## Boundary and network policy

`trading_system.testnet` is independent of the production Config, GET-only client,
WebSocket collectors, market SQLite, Observer, frozen rules and W04 paper ledger.
The existing CLI is unchanged; run `python -m trading_system.testnet.cli`.
No strategy signal is consumed. No production credential fallback or `.env` loading.

Every HTTP request is constructed with the literal `https://testnet.binance.vision`.
An HTTPX request hook checks HTTPS, exact hostname, port 443, absence of userinfo,
and the exact method/path allowlist. TLS verification is enabled, environment proxy
and CA overrides are disabled, redirects are rejected, and POST is never retried.
Only the nine endpoints in the task are reachable. The authenticated signature
uses HMAC-SHA256 over the exact URL-encoded query and Testnet server time.
The adapter implements signing separately to avoid importing production configuration.
HTTPX and HTTPCore URL logging is disabled; errors contain local categories/codes only.

Default CLI operation is offline DRY_RUN. `--online` allows read-only Testnet requests.
Every POST/DELETE also requires `BINANCE_TESTNET_TRADING_ENABLED=YES_TESTNET_ONLY`
and the corresponding explicit CLI confirmation flag. A submit requires a successful
`order/test` check for the same persisted intent within five minutes. No generic URL,
endpoint, order type, or arbitrary trading parameter options are exposed by the CLI.
The low-level client is an adapter; use ExecutionEngine for journaled risk-controlled orders.

## Sizing and risk

Initial execution supports LIMIT/GTC BUY and held-asset SELL only, on BTCUSDT,
ETHUSDT and SOLUSDT. MARKET orders are deliberately refused: the allowed endpoint
set does not provide a trustworthy reference price for a bounded market execution.
`MARKET_LOT_SIZE` applies only to MARKET orders and therefore never overrides
`LOT_SIZE` for this LIMIT-only implementation. This is tested explicitly.

Quantities and prices are strings/Decimal, never floats. They are rounded down to
LOT_SIZE step and PRICE_FILTER tick, then checked against quantity/price bounds,
MIN_NOTIONAL and NOTIONAL. Missing required filters, Spot trading disabled or a
minimum above the local ceiling prevent submission. Dynamic exchange filters
(for example PERCENT_PRICE) are validated by `order/test`; filters are refreshed
before submit and a changed normalized quantity/price requires another test.
Exchange symbol/global open-order limits and order rate limits are also checked.

Conservative fixed ceilings: 20 USDT expected notional per order; three attempts
and 40 USDT total per UTC day; one outstanding order across the account; no borrowing
or naked sell. Free quote/base balances must also cover a 1% fee buffer. Attempt
budgets are reserved durably before POST and span sessions, including uncertain
or rejected attempts. These rules are independent of the unchanged W03 Risk Rule.

## Durability and lifecycle

The default database is `data/testnet_execution.sqlite`; another directory is
allowed, but the filename must remain dedicated. Databases with foreign tables
are rejected. WAL, FULL synchronous commits and BEGIN IMMEDIATE provide a single
writer. A UUID-based unique `e01_` client ID is stored at INTENT_CREATED before any
trading request. Successful preflight records VALIDATED; reservation commits
SUBMITTING before POST. Only validated exchange responses establish NEW,
PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED or REJECTED.

Connection loss, timeout, 5xx, invalid ACK and backend unknown codes lead to a
GET query by the same client ID. There is no re-POST path. An unresolved result
persists UNKNOWN_EXECUTION and a session hold; restart reconciliation checks
SUBMITTING reservations as well. A database failure stops submission immediately.
An ACK persistence failure leaves the committed SUBMITTING reservation for recovery.
SQLite read/write failures expose no SQL or remote payload to the CLI.

Orders, executions, fees and balance strings are session-scoped. Exchange order
IDs are unique per symbol/session, trade IDs per symbol/session. Duplicate trade
replay is idempotent, conflicting replay is a hold. Order identity, original size,
price, status and cumulative executed quantity are cross-checked against intents.
Full exchange responses are not logged; only known order fields are journaled.
Binance can replace clientOrderId during cancellation. The original local intent
ID is retained; the cancellation alias is stored in the verified order payload.
After the initial ACK, status/cancellation/restart queries use the stable exchange
order ID. Before ACK, uncertain submission is queried by the original client ID.

## Reconciliation and operator recovery

Every online account/status/reconcile command, check and submit reconciles first;
cancel queries the target before DELETE and reconciles afterward. Offline commands
never contact the exchange. Reconciliation queries outstanding and historical local
orders, all current account open orders, recent trades plus paginated order-specific
trades, and the account balances. Fee-adjusted base/quote changes must equal the
change in total free + locked balances, exactly. Known executed quantity and quote
notional must equal the journaled fills. External open orders/new executions,
regressing/missing orders, conflicting identities, incomplete history, missing fills
and unexplained balances persist a hold. Eventual exchange consistency may require
operator inspection; no hold is cleared automatically.

HTTP 403/451 is BLOCKED_ENVIRONMENT. HTTP 418/429 applies Retry-After backoff
(minimum 60 seconds) and a persistent hold. No access-restriction bypass is provided.
Missing historical order anchors are RESET_SUSPECTED; balance discontinuities are
RESET_OR_BALANCE_MISMATCH, since external activity cannot be distinguished safely
from a reset. Inspection is required before an explicit new session. Historical
records remain intact; PnL is never merged across sessions or with W04. A session
change preserves an active kill switch. New sessions reject existing external open
orders. Account key changes require a new session; an unused offline empty-key
session can be bound once to the dedicated Testnet key.

Kill switch is durable and blocks create/check/submit. Signed status queries and
explicit cancellation remain available so the operator can reduce exposure.
Deleting/replacing the journal is not a supported recovery procedure. The adapter
does not calculate W04 performance or claim Testnet fills represent production fills.

## References

- [Binance Spot Testnet REST](https://github.com/binance/binance-spot-api-docs/blob/master/testnet/rest-api.md)
- [Testnet resets and virtual funds](https://github.com/binance/binance-spot-api-docs/blob/master/testnet/general-info.md)
- [Exchange filters](https://developers.binance.com/en/docs/products/spot/filters)
