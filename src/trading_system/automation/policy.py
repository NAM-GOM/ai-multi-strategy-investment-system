"""Tighter execution ceilings over the unchanged Frozen/E01 risk engine."""

from decimal import ROUND_CEILING, ROUND_DOWN, Decimal, localcontext

from trading_system.execution.config import T1
from trading_system.execution.risk_engine import RiskEngine
from trading_system.testnet.client import TestnetError
from trading_system.testnet.risk import dec

CAPITAL = Decimal("1000")
ORDER_CAP = Decimal("8.31")


def notional_guard(quantity, price):
    quantity, price = dec(quantity), dec(price)
    if quantity <= 0 or price <= 0:
        raise TestnetError("NON_POSITIVE_ORDER")
    # A high-precision raw input must not round back down to 8.31 during multiplication.
    precision = len(quantity.as_tuple().digits) + len(price.as_tuple().digits)
    with localcontext(prec=max(28, precision)):
        if quantity * price > ORDER_CAP:
            raise TestnetError("E02_ORDER_LIMIT")


class AutomationRisk(RiskEngine):
    max_order = ORDER_CAP
    # Retain, never relax, the inherited 3/day, 40 USDT/day, one open order.

    def capped(self, quantity, price):
        price = dec(price)
        if price <= 0:
            raise TestnetError("NON_POSITIVE_ORDER")
        with localcontext(rounding=ROUND_DOWN):
            ceiling = self.max_order / price
        return min(dec(quantity), ceiling)

    def size(self, decision, manager, quote, references):
        side, quantity, price = super().size(decision, manager, quote, references)
        quantity = self.capped(quantity, price)
        notional_guard(quantity, price)
        return side, quantity, price

    def validate(self, symbol, side, quantity, price, info, balances, opens, attempts):
        notional_guard(quantity, price)  # Raw input before exchange rounding.
        order = super().validate(symbol, side, quantity, price, info, balances, opens, attempts)
        notional_guard(order.quantity, order.price)  # After all filters.
        return order

    def reserve_exit_budget(self, attempts, positions, references, entry_notional=Decimal(0)):
        exposure = (
            sum(
                (dec(p["quantity"]) * dec(references[p["symbol"]]) for p in positions),
                Decimal(0),
            )
            + entry_notional
        )
        exits = sum(
            int(
                (
                    dec(p["quantity"]) * dec(references[p["symbol"]]) / self.max_order
                ).to_integral_value(rounding=ROUND_CEILING)
            )
            for p in positions
            if dec(p["quantity"]) > 0
        ) + int((entry_notional / self.max_order).to_integral_value(rounding=ROUND_CEILING))
        needed = exits + int(entry_notional > 0)
        spent = sum((dec(a["notional"]) for a in attempts), Decimal(0))
        if (
            len(attempts) + needed > self.max_count
            or spent + exposure + entry_notional > self.max_daily
        ):
            raise TestnetError("PROTECTION_BUDGET_UNAVAILABLE")
        return {"reserved_exit_orders": exits, "marked_exposure": str(exposure)}


def protection_budget(manager, quotes, info, balances):
    """Same read-only protective-capacity check for activation and live monitoring."""
    pending = manager.store.rows(
        "SELECT i.* FROM order_intents i JOIN signal_receipts r USING(client_id) "
        "WHERE r.strategy_id=? AND r.session_id=? AND i.state IN ('NEW','PARTIALLY_FILLED')",
        (T1, manager.sid),
    )
    inventory = {p["symbol"]: dict(p) for p in manager.positions.positions()}
    uncovered = {s: dict(p) for s, p in inventory.items()}
    for order in pending:
        observed = manager.store.rows(
            "SELECT executed_qty FROM exchange_orders WHERE client_id=?", (order["client_id"],)
        )[0]
        remaining = dec(order["quantity"]) - dec(observed["executed_qty"])
        p = inventory.setdefault(order["symbol"], {"symbol": order["symbol"], "quantity": "0"})
        p["quantity"] = str(
            max(dec(0), dec(p["quantity"]) + remaining * (1 if order["side"] == "BUY" else -1))
        )
        if order["side"] == "SELL" and order["symbol"] in uncovered:
            actual = uncovered[order["symbol"]]
            actual["quantity"] = str(max(dec(0), dec(actual["quantity"]) - remaining))
    marks = {s: manager._reference(s, manager.paths.market).price for s in inventory}
    attempts = manager.attempts()
    budget = manager.risk.reserve_exit_budget(attempts, list(inventory.values()), marks)
    # A hoped-for later fill cannot hide currently unprotectable partial-fill dust.
    for p in [*inventory.values(), *uncovered.values()]:
        if dec(p["quantity"]) > 0:
            symbol = p["symbol"]
            manager.risk.validate(
                symbol,
                "SELL",
                manager.risk.capped(p["quantity"], quotes[symbol].bid),
                quotes[symbol].bid,
                info,
                balances,
                [],
                attempts,
            )
    return budget
