"""Validated exchange models; monetary values are Decimal throughout."""

from dataclasses import dataclass
from decimal import Decimal

from trading_system.testnet.client import SYMBOLS, TestnetError
from trading_system.testnet.engine import STATES
from trading_system.testnet.risk import dec


@dataclass(frozen=True)
class Balance:
    asset: str
    free: Decimal
    locked: Decimal

    @classmethod
    def parse(cls, value):
        try:
            result = cls(value["asset"], dec(value["free"]), dec(value["locked"]))
            if not isinstance(result.asset, str) or not result.asset.isalnum():
                raise ValueError
            if min(result.free, result.locked) < 0:
                raise ValueError
            return result
        except KeyError, ValueError, TypeError:
            raise TestnetError("INVALID_BALANCES") from None


@dataclass(frozen=True)
class ExchangeOrder:
    symbol: str
    order_id: int
    client_id: str
    status: str
    side: str
    quantity: Decimal
    executed: Decimal
    quote: Decimal
    price: Decimal

    @classmethod
    def parse(cls, value):
        try:
            result = cls(
                value["symbol"],
                value["orderId"],
                value["clientOrderId"],
                value["status"],
                value["side"],
                dec(value["origQty"]),
                dec(value["executedQty"]),
                dec(value["cummulativeQuoteQty"]),
                dec(value["price"]),
            )
            if (
                result.symbol not in SYMBOLS
                or type(result.order_id) is not int
                or result.order_id < 0
                or not isinstance(result.client_id, str)
                or not result.client_id
                or result.status not in STATES
                or result.side not in ("BUY", "SELL")
                or value["type"] != "LIMIT"
                or result.quantity <= 0
                or result.price <= 0
                or not 0 <= result.executed <= result.quantity
                or result.quote < 0
            ):
                raise ValueError
            return result
        except KeyError, TypeError, ValueError:
            raise TestnetError("INVALID_ORDER_RESPONSE") from None


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: Decimal
    ask: Decimal
    received_ms: int
    update_id: int

    @classmethod
    def parse(cls, value, received_ms):
        try:
            result = cls(value["s"], dec(value["b"]), dec(value["a"]), received_ms, value["u"])
            if (
                result.symbol not in SYMBOLS
                or result.bid <= 0
                or result.ask < result.bid
                or type(result.update_id) is not int
                or result.update_id < 0
                or type(received_ms) is not int
                or received_ms <= 0
                or dec(value["B"]) <= 0
                or dec(value["A"]) <= 0
            ):
                raise ValueError
            return result
        except KeyError, TypeError, ValueError:
            raise TestnetError("INVALID_TESTNET_QUOTE") from None
