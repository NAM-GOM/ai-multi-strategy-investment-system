"""Frozen sizing plus independent execution ceilings; no AI trading discretion."""

from decimal import Decimal

from trading_system.testnet.client import TestnetError
from trading_system.testnet.risk import RiskEngine as ExchangeRisk
from trading_system.testnet.risk import dec

from .config import SafetyConfig


class RiskEngine(ExchangeRisk):
    def __init__(self, safety=None):
        self.safety = safety or SafetyConfig()

    def validate(self, symbol, side, quantity, price, info, balances, open_orders, attempts):
        try:
            order = super().validate(
                symbol, side, quantity, price, info, balances, open_orders, attempts
            )
            rule = next(s for s in info["symbols"] if s["symbol"] == symbol)
            for value, key in (
                (order.quantity, "baseAssetPrecision"),
                (order.price, "quoteAssetPrecision"),
            ):
                precision = rule.get(key, 8)
                if type(precision) is not int or not 0 <= precision <= 30:
                    raise TestnetError("INVALID_EXCHANGE_PRECISION")
                if max(0, -value.normalize().as_tuple().exponent) > precision:
                    raise TestnetError("EXCHANGE_PRECISION")
            for f in rule["filters"]:
                if f["filterType"] == "MAX_POSITION" and side == "BUY":
                    balance = next((b for b in balances if b["asset"] == rule["baseAsset"]), {})
                    held = dec(balance.get("free", "0")) + dec(balance.get("locked", "0"))
                    pending = sum(
                        (
                            dec(o["origQty"]) - dec(o["executedQty"])
                            for o in open_orders
                            if o["symbol"] == symbol and o["side"] == "BUY"
                        ),
                        dec(0),
                    )
                    if held + pending + order.quantity > dec(f["maxPosition"]):
                        raise TestnetError("EXCHANGE_MAX_POSITION")
            return order
        except KeyError, TypeError, ValueError, StopIteration:
            raise TestnetError("INVALID_EXCHANGE_FILTERS") from None

    def prices(self, quote, reference, reference_ms, now):
        reference = dec(reference)
        if not 0 <= now - quote.received_ms <= self.safety.max_quote_age_ms:
            raise TestnetError("STALE_TESTNET_QUOTE")
        if not 0 <= now - reference_ms <= self.safety.max_reference_age_ms:
            raise TestnetError("STALE_PRODUCTION_REFERENCE")
        if reference <= 0 or quote.bid <= 0 or quote.ask < quote.bid:
            raise TestnetError("INVALID_PRICE")
        difference = max(abs(quote.bid / reference - 1), abs(quote.ask / reference - 1))
        if difference > self.safety.max_price_difference:
            raise TestnetError("PRICE_DIVERGENCE")
        if (quote.ask - quote.bid) / quote.bid > self.safety.max_spread:
            raise TestnetError("TESTNET_SPREAD")
        return difference

    def size(self, decision, manager, quote, references):
        strategy, symbol = decision.strategy_id, decision.symbol
        manager.verify(strategy)
        allocation = manager.allocation(strategy)
        cash = dec(allocation["cash"])
        positions = manager.positions(strategy)
        qty = next((dec(p["quantity"]) for p in positions if p["symbol"] == symbol), Decimal(0))
        reserved_cash, reserved_assets = manager.reserved(strategy)
        if reserved_cash or reserved_assets:
            raise TestnetError("STRATEGY_PENDING_INTENT")
        if decision.decision == "EXIT_CANDIDATE":
            if qty <= 0:
                raise TestnetError("NO_STRATEGY_POSITION")
            return "SELL", qty, quote.bid
        if qty > 0:
            raise TestnetError("NO_PYRAMIDING")
        equity = cash
        for position in positions:
            if dec(position["quantity"]) > 0:
                if position["symbol"] not in references:
                    raise TestnetError("MISSING_POSITION_MARK")
                equity += dec(position["quantity"]) * dec(references[position["symbol"]])
        atr = dec(str(decision.indicator_snapshot["atr"]))
        if atr <= 0 or quote.ask <= Decimal(3) * atr:
            raise TestnetError("INVALID_FROZEN_STOP")
        # Frozen 0.5%, 33.3%, 10 bps fee and 5 bps slippage sizing assumptions.
        model_price = dec(references[symbol]) * Decimal("1.0005")
        quantity = min(
            equity * Decimal("0.005") / (Decimal(3) * atr),
            equity * Decimal("0.333") / max(model_price, quote.ask),
            cash / (model_price * Decimal("1.001")),
            self.max_order / quote.ask,
            cash / (quote.ask * Decimal("1.01")),
        )
        if quantity <= 0:
            raise TestnetError("INSUFFICIENT_STRATEGY_CAPITAL")
        return "BUY", quantity, quote.ask
