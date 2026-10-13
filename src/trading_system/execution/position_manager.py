"""Strategy ownership derives only from attributed, reconciled Testnet fills."""

from decimal import Decimal

from trading_system.observer.model import digest
from trading_system.testnet.client import TestnetError
from trading_system.testnet.engine import PENDING
from trading_system.testnet.risk import dec

from .config import T1

ZERO = Decimal(0)


class PositionManager:
    def __init__(self, store, sid):
        self.store, self.sid = store, sid

    def allocation(self, strategy=T1):
        rows = self.store.rows(
            "SELECT * FROM strategy_allocations WHERE session_id=? AND strategy_id=?",
            (self.sid, strategy),
        )
        if not rows:
            raise TestnetError("STRATEGY_ALLOCATION_REQUIRED")
        return rows[0]

    def positions(self, strategy=T1):
        return self.store.rows(
            "SELECT * FROM positions WHERE session_id=? AND strategy_id=? ORDER BY symbol",
            (self.sid, strategy),
        )

    def projection_hash(self, strategy):
        return digest(
            {
                "cash": self.allocation(strategy)["cash"],
                "initial_capital": self.allocation(strategy)["initial_capital"],
                "positions": self.positions(strategy),
                "fills": self.store.rows(
                    "SELECT * FROM position_fills WHERE session_id=? AND strategy_id=? "
                    "ORDER BY symbol,trade_id",
                    (self.sid, strategy),
                ),
            }
        )

    def verify(self, strategy=T1):
        if self.projection_hash(strategy) != self.allocation(strategy)["projection_hash"]:
            raise TestnetError("POSITION_LEDGER_MISMATCH")

    def allocate(self, capital, now):
        capital = dec(capital)
        if capital <= 0:
            raise TestnetError("INVALID_ALLOCATION")
        with self.store.transaction():
            if self.store.rows(
                "SELECT * FROM strategy_allocations WHERE session_id=?", (self.sid,)
            ):
                raise TestnetError("ALLOCATION_ALREADY_EXISTS")
            attempts = self.store.rows(
                "SELECT * FROM order_intents WHERE session_id=? AND attempted_ms IS NOT NULL",
                (self.sid,),
            )
            if any(
                a["state"] not in ("FILLED", "CANCELED", "EXPIRED", "REJECTED") for a in attempts
            ):
                raise TestnetError("PENDING_ORDER_BLOCK")
            # Completed manual verification is a baseline, never a T1 position/PnL.
            baseline = self.store.rows(
                "SELECT e.*,o.client_id FROM executions e JOIN exchange_orders o "
                "USING(session_id,symbol,order_id) WHERE e.session_id=?",
                (self.sid,),
            )
            for fill in baseline:
                approved = self.store.rows(
                    "SELECT * FROM execution_gates WHERE session_id=? AND gate=?",
                    (self.sid, "MANUAL:" + fill["client_id"]),
                )
                if not approved:
                    raise TestnetError("UNATTRIBUTED_EXECUTION")
                self.store.db.execute(
                    "INSERT INTO position_fills VALUES(?,?,?,?,?)",
                    (self.sid, fill["symbol"], fill["trade_id"], "MANUAL_BASELINE", digest(fill)),
                )
            latest = self.latest_balances()
            if latest.get("USDT", ZERO) < capital:
                raise TestnetError("INSUFFICIENT_ALLOCATABLE_CAPITAL")
            self.store.db.execute(
                "INSERT INTO strategy_allocations VALUES(?,?,?,?,?)",
                (self.sid, T1, str(capital), str(capital), ""),
            )
            self._seal(T1)
            self.store.event(self.sid, now, "T1_ALLOCATION_CREATED", str(capital))

    def latest_balances(self):
        rows = self.store.rows(
            "SELECT * FROM balance_snapshots WHERE session_id=? AND snapshot_id=(SELECT "
            "snapshot_id FROM balance_snapshots WHERE session_id=? "
            "ORDER BY time_ms DESC,rowid DESC LIMIT 1)",
            (self.sid, self.sid),
        )
        return {b["asset"]: dec(b["free"]) + dec(b["locked"]) for b in rows}

    def reserved(self, strategy=T1):
        rows = self.store.rows(
            "SELECT i.* FROM order_intents i JOIN signal_receipts r USING(client_id) "
            "WHERE i.session_id=? AND r.strategy_id=? AND i.state IN (?,?,?,?,?,?,?)",
            (self.sid, strategy, "INTENT_CREATED", "RISK_APPROVED", "VALIDATED", *PENDING),
        )
        cash, assets = ZERO, {}
        for order in rows:
            executed = self.store.rows(
                "SELECT executed_qty FROM exchange_orders WHERE session_id=? AND client_id=?",
                (self.sid, order["client_id"]),
            )
            remaining = dec(order["quantity"]) - (
                dec(executed[0]["executed_qty"]) if executed else ZERO
            )
            if order["side"] == "BUY":
                cash += remaining * dec(order["price"]) * Decimal("1.01")
            else:
                assets[order["symbol"]] = assets.get(order["symbol"], ZERO) + remaining
        return cash, assets

    def _seal(self, strategy):
        self.store.db.execute(
            "UPDATE strategy_allocations SET projection_hash=? "
            "WHERE session_id=? AND strategy_id=?",
            (self.projection_hash(strategy), self.sid, strategy),
        )

    def reconcile(self):
        """Commit only verified new fill deltas; never repair a mismatched projection."""
        with self.store.transaction():
            allocations = self.store.rows(
                "SELECT * FROM strategy_allocations WHERE session_id=?",
                (self.sid,),
            )
            for allocation in allocations:
                self.verify(allocation["strategy_id"])
            fills = self.store.rows(
                "SELECT e.*,o.client_id FROM executions e JOIN exchange_orders o "
                "USING(session_id,symbol,order_id) WHERE e.session_id=? ORDER BY time_ms,trade_id",
                (self.sid,),
            )
            for fill in fills:
                owners = self.store.rows(
                    "SELECT * FROM signal_receipts WHERE client_id=? AND session_id=?",
                    (fill["client_id"], self.sid),
                )
                if not owners:
                    if allocations:
                        baseline = self.store.rows(
                            "SELECT * FROM position_fills WHERE session_id=? AND symbol=? "
                            "AND trade_id=? AND strategy_id='MANUAL_BASELINE'",
                            (self.sid, fill["symbol"], fill["trade_id"]),
                        )
                        if not baseline or baseline[0]["fill_hash"] != digest(fill):
                            raise TestnetError("UNATTRIBUTED_EXECUTION")
                    continue
                owner = owners[0]
                strategy, symbol = owner["strategy_id"], fill["symbol"]
                applied = self.store.rows(
                    "SELECT * FROM position_fills WHERE session_id=? AND symbol=? AND trade_id=?",
                    (self.sid, symbol, fill["trade_id"]),
                )
                fill_hash = digest(fill)
                if applied:
                    if (
                        applied[0]["fill_hash"] != fill_hash
                        or applied[0]["strategy_id"] != strategy
                    ):
                        raise TestnetError("ATTRIBUTED_FILL_CONFLICT")
                    continue
                allocation = self.allocation(strategy)
                position = next(
                    (p for p in self.positions(strategy) if p["symbol"] == symbol), None
                )
                qty, cost, realized, stop = (
                    dec(position[k]) if position else ZERO
                    for k in (
                        "quantity",
                        "cost",
                        "realized_pnl",
                        "initial_stop",
                    )
                )
                traded, quote, fee = (dec(fill[k]) for k in ("quantity", "quote_qty", "commission"))
                fee_asset = fill["commission_asset"]
                if fee > 0 and fee_asset not in ("USDT", symbol.removesuffix("USDT")):
                    raise TestnetError("UNALLOCATED_FEE_ASSET")
                base_fee = fee if fee_asset == symbol.removesuffix("USDT") else ZERO
                quote_fee = fee if fee_asset == "USDT" else ZERO
                cash = dec(allocation["cash"])
                gross_qty = dec(position["entry_gross_quantity"]) if position else ZERO
                gross_quote = dec(position["entry_gross_quote"]) if position else ZERO
                if fill["is_buyer"]:
                    gross_qty += traded
                    gross_quote += quote
                    average_fill = gross_quote / gross_qty
                    qty += traded - base_fee
                    cost += quote + quote_fee
                    cash -= quote + quote_fee
                    stop = average_fill - Decimal(3) * dec(owner["atr"])
                else:
                    average_fill = dec(position["average_fill"]) if position else ZERO
                    removed = traded + base_fee
                    if removed > qty or qty <= 0:
                        raise TestnetError("STRATEGY_OVERSOLD")
                    removed_cost = cost * removed / qty
                    qty -= removed
                    cost -= removed_cost
                    proceeds = quote - quote_fee
                    realized += proceeds - removed_cost
                    cash += proceeds
                    if qty == 0:
                        stop = ZERO
                        average_fill = ZERO
                        gross_qty = gross_quote = ZERO
                if cash < 0 or qty < 0 or (qty > 0 and stop <= 0):
                    raise TestnetError("STRATEGY_LEDGER_UNSAFE")
                self.store.db.execute(
                    "INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT "
                    "(session_id,strategy_id,symbol) DO UPDATE SET quantity=excluded.quantity,"
                    "cost=excluded.cost,realized_pnl=excluded.realized_pnl,"
                    "initial_stop=excluded.initial_stop,average_fill=excluded.average_fill,"
                    "entry_gross_quantity=excluded.entry_gross_quantity,"
                    "entry_gross_quote=excluded.entry_gross_quote",
                    (
                        self.sid,
                        strategy,
                        symbol,
                        str(qty),
                        str(cost),
                        str(realized),
                        str(stop),
                        str(average_fill),
                        str(gross_qty),
                        str(gross_quote),
                    ),
                )
                self.store.db.execute(
                    "UPDATE strategy_allocations SET cash=? WHERE session_id=? AND strategy_id=?",
                    (str(cash), self.sid, strategy),
                )
                self.store.db.execute(
                    "INSERT INTO position_fills VALUES(?,?,?,?,?)",
                    (self.sid, symbol, fill["trade_id"], strategy, fill_hash),
                )
                self._seal(strategy)
            totals = self.latest_balances()
            claimed = {}
            for allocation in allocations:
                strategy = allocation["strategy_id"]
                claimed["USDT"] = claimed.get("USDT", ZERO) + dec(self.allocation(strategy)["cash"])
                for position in self.positions(strategy):
                    asset = position["symbol"].removesuffix("USDT")
                    claimed[asset] = claimed.get(asset, ZERO) + dec(position["quantity"])
            if any(value > totals.get(asset, ZERO) for asset, value in claimed.items()):
                raise TestnetError("STRATEGY_ACCOUNT_BALANCE_MISMATCH")

    def report(self, prices):
        result = []
        for position in self.positions():
            qty, cost = dec(position["quantity"]), dec(position["cost"])
            price = prices.get(position["symbol"])
            result.append(
                {
                    **position,
                    "average_fill_with_fees": str(cost / qty if qty else ZERO),
                    "unrealized_pnl": str(qty * dec(price) - cost) if price is not None else None,
                }
            )
        return result
