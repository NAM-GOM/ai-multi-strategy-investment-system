"""Conservative LIMIT-only sizing; all monetary values remain Decimal."""

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from .client import SYMBOLS, TestnetError


def dec(value) -> Decimal:
    if isinstance(value, float):
        raise TestnetError("FLOAT_FORBIDDEN")
    try:
        result = Decimal(value)
    except InvalidOperation, ValueError, TypeError:
        raise TestnetError("INVALID_DECIMAL") from None
    if not result.is_finite():
        raise TestnetError("INVALID_DECIMAL")
    return result


def floor_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step if step else value


@dataclass(frozen=True)
class Order:
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal

    @property
    def notional(self):
        return self.quantity * self.price

    def params(self, client_id):
        return dict(
            symbol=self.symbol,
            side=self.side,
            type="LIMIT",
            timeInForce="GTC",
            quantity=format(self.quantity, "f"),
            price=format(self.price, "f"),
            newClientOrderId=client_id,
            newOrderRespType="FULL",
        )


class RiskEngine:
    max_order = Decimal("20")
    max_daily = Decimal("40")
    max_count = 3
    max_open = 1

    def validate(self, symbol, side, quantity, price, info, balances, open_orders, attempts):
        if symbol not in SYMBOLS or side not in ("BUY", "SELL"):
            raise TestnetError("UNSUPPORTED_ORDER")
        rule = next((s for s in info["symbols"] if s["symbol"] == symbol), None)
        if (
            not rule
            or rule.get("status") != "TRADING"
            or not rule.get("isSpotTradingAllowed", False)
            or "LIMIT" not in rule.get("orderTypes", [])
        ):
            raise TestnetError("SPOT_NOT_TRADING")
        filters = {f["filterType"]: f for f in rule["filters"]}
        if not {"LOT_SIZE", "PRICE_FILTER"} <= filters.keys():
            raise TestnetError("MISSING_FILTER")
        qty, px = dec(quantity), dec(price)
        lot, pf = filters["LOT_SIZE"], filters["PRICE_FILTER"]
        qty = floor_step(qty, dec(lot["stepSize"]))
        px = floor_step(px, dec(pf["tickSize"]))
        if qty <= 0 or px <= 0:
            raise TestnetError("NON_POSITIVE_ORDER")
        for value, f, minimum, maximum in (
            (qty, lot, "minQty", "maxQty"),
            (px, pf, "minPrice", "maxPrice"),
        ):
            if dec(f[minimum]) and value < dec(f[minimum]):
                raise TestnetError("FILTER_MINIMUM")
            if dec(f[maximum]) and value > dec(f[maximum]):
                raise TestnetError("FILTER_MAXIMUM")
        order = Order(symbol, side, qty, px)
        for name in ("MIN_NOTIONAL", "NOTIONAL"):
            if name in filters:
                f = filters[name]
                if order.notional < dec(f["minNotional"]):
                    raise TestnetError("MIN_NOTIONAL")
                if dec(f.get("maxNotional", "0")) and order.notional > dec(f["maxNotional"]):
                    raise TestnetError("MAX_NOTIONAL")
        if not ({"MIN_NOTIONAL", "NOTIONAL"} & filters.keys()):
            raise TestnetError("MISSING_NOTIONAL_FILTER")
        if order.notional > self.max_order:
            raise TestnetError("ORDER_LIMIT")
        if len(attempts) >= self.max_count:
            raise TestnetError("DAILY_COUNT")
        if (
            sum((dec(a["notional"]) for a in attempts), Decimal(0)) + order.notional
            > self.max_daily
        ):
            raise TestnetError("DAILY_NOTIONAL")
        if len(open_orders) >= self.max_open:
            raise TestnetError("OPEN_ORDER_LIMIT")
        for f in [*rule["filters"], *info.get("exchangeFilters", [])]:
            key = {"MAX_NUM_ORDERS": "maxNumOrders", "EXCHANGE_MAX_NUM_ORDERS": "maxNumOrders"}
            if f["filterType"] in key:
                count = sum(o["symbol"] == symbol for o in open_orders)
                if f["filterType"].startswith("EXCHANGE_"):
                    count = len(open_orders)
                if count + 1 > int(f[key[f["filterType"]]]):
                    raise TestnetError("EXCHANGE_ORDER_LIMIT")
        # Daily local ceiling is also bounded by exchange order rate limits.
        for f in info.get("rateLimits", []):
            if f["rateLimitType"] == "ORDERS" and len(attempts) + 1 > int(f["limit"]):
                raise TestnetError("EXCHANGE_RATE_LIMIT")
        free = {b["asset"]: dec(b["free"]) for b in balances}
        asset = rule["quoteAsset"] if side == "BUY" else rule["baseAsset"]
        needed = order.notional if side == "BUY" else qty
        # Keep a conservative 1% buffer for fees; no borrowing or short sale.
        if free.get(asset, Decimal(0)) < needed * Decimal("1.01"):
            raise TestnetError("INSUFFICIENT_BALANCE")
        return order
